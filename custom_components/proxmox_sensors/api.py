"""API for Proxmox Extended Sensors."""

from typing import Any, Optional
import asyncio
import logging
import time

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

LOGGER = logging.getLogger(__name__)

# Hard wall-clock cap for a single API call. Unlike a socket timeout this also
# bounds the TLS handshake and a response that trickles in byte by byte, so a
# struggling node can never hold a call open indefinitely. Because the transport
# is fully async there is no executor thread left behind when it fires.
REQUEST_TIMEOUT = 15

# PVE auth tickets are valid for two hours; refresh well before that so a
# request never races the expiry.
TICKET_LIFETIME = 100 * 60


class AuthenticationError(Exception):
    """Raised when the API rejects the supplied credentials."""


class CannotConnect(Exception):
    """Raised when the API cannot be reached."""


class PermissionError(Exception):
    """Raised when credentials are valid but permissions are insufficient."""


def _raise_for_auth_or_permission(status_code: int | None, path: str) -> None:
    """Map only auth/permission statuses; other HTTP errors are not network errors."""
    if status_code == 401:
        raise AuthenticationError(f"Authentication failed for {path}")
    if status_code == 403:
        raise PermissionError(f"Permission denied for {path}")


class ProxmoxClient:
    def __init__(
        self,
        host: str,
        user: str,
        password: Optional[str] = None,
        token_id: Optional[str] = None,
        token_secret: Optional[str] = None,
        server_type: str = "PVE",
        port: Optional[int] = None,
        verify_ssl: bool = True,
    ):
        self._host = host
        self._user = user
        self._password = password
        self._token_id = token_id
        self._token_secret = token_secret
        self._server_type = server_type
        self._port = port
        self._verify_ssl = verify_ssl
        # PVE password auth: ticket + CSRF token, refreshed under a lock so a
        # burst of parallel calls triggers exactly one login.
        self._ticket: Optional[str] = None
        self._csrf_token: Optional[str] = None
        self._ticket_expires: float = 0.0
        self._auth_lock = asyncio.Lock()
        # Sidecar endpoints already warned about, so a down service is logged
        # once per host instead of every poll. Cleared on recovery.
        self._sidecar_warned: set = set()

    # ================= TRANSPORT =================

    def _split_host_port(self):
        """Split the configured host into ``(host, embedded_port|None)``.

        ``self._host`` may carry a scheme and/or the API port (e.g.
        ``https://pve.local:8006``), while the port also lives in ``self._port``.
        Bracketed IPv6 literals keep their brackets, and a bare IPv6 literal gets
        bracketed, so the result can be spliced into a URL as-is.
        """
        host = (self._host or "").strip()
        for scheme in ("https://", "http://"):
            if host.startswith(scheme):
                host = host[len(scheme) :]
        host = host.split("/")[0]

        port = None
        if host.startswith("["):
            end = host.find("]")
            if end != -1:
                rest = host[end + 1 :]
                if rest.startswith(":") and rest[1:].isdigit():
                    port = int(rest[1:])
                host = host[: end + 1]
        elif host.count(":") == 1:
            name, _, maybe_port = host.partition(":")
            if maybe_port.isdigit():
                host, port = name, int(maybe_port)
        elif host.count(":") > 1:
            host = f"[{host}]"  # bare IPv6 literal

        return host, port

    def _api_base(self) -> str:
        host, embedded_port = self._split_host_port()
        default_port = 8007 if self._server_type == "PBS" else 8006
        port = self._port or embedded_port or default_port
        return f"https://{host}:{port}/api2/json"

    def _token_header(self) -> Optional[str]:
        """Authorization header for API-token auth, or None if not configured."""
        if not (self._token_id and self._token_secret):
            return None

        token_full = (
            self._token_id
            if "!" in self._token_id
            else f"{self._user}!{self._token_id}"
        )

        if self._server_type == "PBS":
            return f"PBSAPIToken {token_full}:{self._token_secret}"
        return f"PVEAPIToken={token_full}={self._token_secret}"

    def _session(self, hass):
        """HA's shared aiohttp session (no blocking SSL-context build here)."""
        return async_get_clientsession(hass, verify_ssl=self._verify_ssl)

    async def _ensure_ticket(self, session) -> str:
        """Fetch or refresh a PVE auth ticket, returning the ticket to use.

        The caller uses the returned value rather than re-reading ``self._ticket``,
        so a concurrent 401 clearing the cached ticket cannot turn this call's
        cookie into ``None``.
        """
        async with self._auth_lock:
            if self._ticket and time.monotonic() < self._ticket_expires:
                return self._ticket

            url = f"{self._api_base()}/access/ticket"
            async with session.post(
                url,
                data={"username": self._user, "password": self._password},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status in (401, 403):
                    _raise_for_auth_or_permission(response.status, "access/ticket")
                if response.status >= 400:
                    raise CannotConnect(
                        f"PVE ticket request failed with HTTP {response.status}"
                    )
                payload = await response.json(content_type=None)

            data = (payload or {}).get("data") or {}
            ticket = data.get("ticket")
            if not ticket:
                raise AuthenticationError("PVE did not return an auth ticket")

            self._ticket = ticket
            self._csrf_token = data.get("CSRFPreventionToken")
            self._ticket_expires = time.monotonic() + TICKET_LIFETIME
            return ticket

    async def _api_request(
        self,
        hass,
        method: str,
        path: str,
        data=None,
        raise_errors: bool = False,
    ) -> Any:
        """Perform one Proxmox API call and return the unwrapped ``data`` payload.

        The whole call is bounded by ``ClientTimeout(total=...)``, which covers
        connect, TLS and a trickling response alike — and, being async, leaves no
        executor thread behind when it fires.
        """
        session = self._session(hass)
        url = f"{self._api_base()}/{path}"
        headers = {"Accept": "application/json"}
        cookies = None

        try:
            auth_header = self._token_header()
            if auth_header:
                headers["Authorization"] = auth_header
            elif self._server_type == "PBS":
                LOGGER.error(
                    "PBS token authentication requires user, token_id and token_secret"
                )
                if raise_errors:
                    raise AuthenticationError("PBS token authentication is incomplete")
                return None
            else:
                cookies = {"PVEAuthCookie": await self._ensure_ticket(session)}
                if method != "GET" and self._csrf_token:
                    headers["CSRFPreventionToken"] = self._csrf_token

            payload_kwargs = {}
            if method != "GET" and data:
                # PVE expects form encoding; PBS expects JSON.
                key = "json" if self._server_type == "PBS" else "data"
                payload_kwargs[key] = data

            async with session.request(
                method,
                url,
                headers=headers,
                cookies=cookies,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                **payload_kwargs,
            ) as response:
                status = response.status

                if raise_errors and status >= 400:
                    _raise_for_auth_or_permission(status, path)
                    LOGGER.debug(
                        "%s HTTP %s on validation endpoint %s",
                        self._server_type,
                        status,
                        path,
                    )
                    return None

                if status == 401:
                    # Most likely an expired ticket — force a fresh login next call.
                    self._ticket = None
                    LOGGER.error("%s HTTP 401 on %s", self._server_type, path)
                    return None

                if status == 403:
                    return None

                if status >= 400:
                    LOGGER.error(
                        "%s HTTP %s on %s: %s",
                        self._server_type,
                        status,
                        path,
                        await response.text(),
                    )
                    return None

                payload = await response.json(content_type=None)

        except (AuthenticationError, PermissionError, CannotConnect) as err:
            # These are the config-flow's validation signals. During normal
            # polling the contract is "return None, never raise" — a login that
            # fails on a network blip must degrade like any other failed call
            # instead of taking the whole update cycle down.
            if raise_errors:
                raise
            LOGGER.debug(
                "%s auth/connection failure on %s: %s", self._server_type, path, err
            )
            return None
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            # Expected while a node is powered off, unreachable or wedged.
            if raise_errors:
                raise CannotConnect(
                    f"{self._server_type} request failed for {path}"
                ) from err
            LOGGER.debug(
                "%s node unreachable while requesting %s: %s",
                self._server_type,
                path,
                err,
            )
            return None
        except aiohttp.ClientError as err:
            if raise_errors:
                raise CannotConnect(
                    f"{self._server_type} request failed for {path}"
                ) from err
            LOGGER.error(
                "%s %s error on %s: %s", self._server_type, method, path, err
            )
            return None
        except Exception as err:
            if raise_errors:
                LOGGER.debug(
                    "%s validation endpoint %s failed with %s: %s",
                    self._server_type,
                    path,
                    type(err).__name__,
                    err,
                )
                raise
            LOGGER.error(
                "%s %s error on %s: %s", self._server_type, method, path, err
            )
            return None

        # Match proxmoxer's behaviour of handing back the `data` envelope content.
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    async def get(self, hass, path: str, raise_errors: bool = False) -> Any:
        return await self._api_request(hass, "GET", path, raise_errors=raise_errors)

    async def post(self, hass, path: str, data=None) -> Any:
        return await self._api_request(hass, "POST", path, data=data or {})

    async def get_cluster_resources(self, hass):
        return await self.get(hass, "cluster/resources") or []

    async def get_cluster_tasks(self, hass):
        return await self.get(hass, "cluster/tasks") or []

    async def get_backup_jobs(self, hass):
        return await self.get(hass, "cluster/backup") or []

    async def get_nodes(self, hass):
        """Return nodes in cluster."""
        data = await self.get(hass, "nodes")
        return data or []

    async def get_node_ip(self, hass, node):
        """Get primary IPv4 of a node"""
        net = await self.get_node_network(hass, node)

        for iface in net or []:
            addr = iface.get("address")

            if addr and not addr.startswith("127.") and ":" not in addr:
                return addr

        return None

    async def get_node_status(self, hass, node: str):
        return await self.get(hass, f"nodes/{node}/status")

    async def get_node_updates(self, hass, node: str):
        return await self.get(hass, f"nodes/{node}/apt/update")

    async def get_node_network(self, hass, node: str):
        return await self.get(hass, f"nodes/{node}/network") or []

    async def get_vms(self, hass, node: str):
        return await self.get(hass, f"nodes/{node}/qemu") or []

    async def get_containers(self, hass, node: str):
        return await self.get(hass, f"nodes/{node}/lxc") or []

    async def get_container_status(self, hass, node: str, vmid: str):
        return await self.get(hass, f"nodes/{node}/lxc/{vmid}/status/current")

    async def get_qemu_status(self, hass, node: str, vmid: str):
        return await self.get(hass, f"nodes/{node}/qemu/{vmid}/status/current")

    async def get_lxc_status(self, hass, node: str, vmid: str):
        return await self.get(hass, f"nodes/{node}/lxc/{vmid}/status/current")

    async def get_vm_type(self, hass, node: str, vmid: str) -> str:
        vms = await self.get_vms(hass, node)
        if isinstance(vms, list):
            for vm in vms:
                if str(vm.get("vmid")) == str(vmid):
                    return "qemu"

        containers = await self.get_containers(hass, node)
        if isinstance(containers, list):
            for ct in containers:
                if str(ct.get("vmid")) == str(vmid):
                    return "lxc"

        return "unknown"

    async def get_vm_status(self, hass, node: str, vmid: str):
        vmtype = await self.get_vm_type(hass, node, vmid)
        if vmtype == "qemu":
            return await self.get_qemu_status(hass, node, vmid)
        if vmtype == "lxc":
            return await self.get_lxc_status(hass, node, vmid)
        return None

    async def get_storages(self, hass, node: str):
        return await self.get(hass, f"nodes/{node}/storage") or []

    async def get_disks(self, hass, node: str):
        return await self.get(hass, f"nodes/{node}/disks/list") or []

    async def get_replication(self, hass, node: str):
        return await self.get(hass, f"nodes/{node}/replication") or []

    async def control_vm(self, hass, node: str, vmid: str, command: str):
        valid_vm_commands = [
            "start",
            "stop",
            "shutdown",
            "reboot",
            "reset",
            "suspend",
            "resume",
            "hibernate",
            "pause",
        ]
        if command not in valid_vm_commands:
            LOGGER.error(f"Invalid VM command: {command}")
            return False

        if command == "hibernate":
            path = f"nodes/{node}/qemu/{vmid}/status/suspend"
            data = {"todisk": 1}
        elif command == "pause":
            path = f"nodes/{node}/qemu/{vmid}/status/suspend"
            data = {}
        else:
            path = f"nodes/{node}/qemu/{vmid}/status/{command}"
            data = {}

        if command in ["shutdown", "reboot"]:
            data["timeout"] = 60

        result = await self.post(hass, path, data)

        return result

    async def execute_vm_command(self, hass, node: str, vmid: str, command: str):
        return await self.control_vm(hass, node, vmid, command)

    async def execute_ct_command(self, hass, node: str, vmid: str, command: str):
        return await self.control_container(hass, node, vmid, command)

    async def execute_node_command(self, hass, node: str, command: str):
        if command == "reboot":
            return await self.reboot_node(hass, node)
        elif command == "shutdown":
            return await self.shutdown_node(hass, node)
        else:
            LOGGER.error(f"Invalid node command: {command}")
            return False

    async def control_container(self, hass, node: str, vmid: str, command: str):
        valid_ct_commands = ["start", "stop", "shutdown", "reboot"]
        if command not in valid_ct_commands:
            LOGGER.error(
                f"Invalid CT command: {command}. Valid commands: {valid_ct_commands}"
            )
            return False

        path = f"nodes/{node}/lxc/{vmid}/status/{command}"
        data = {}

        if command in ["shutdown", "reboot"]:
            data["timeout"] = 60

        result = await self.post(hass, path, data)

        return result

    async def shutdown_node(self, hass, node: str):
        path = f"nodes/{node}/status"
        data = {"command": "shutdown"}
        return await self.post(hass, path, data)

    async def reboot_node(self, hass, node: str):
        path = f"nodes/{node}/status"
        data = {"command": "reboot"}
        return await self.post(hass, path, data)

    def _sidecar_host(self) -> str:
        """Host without any embedded port, for the sidecar (port 9000) URLs.

        ``self._host`` may carry the PVE/PBS API port (e.g. ``pve.local:8006``);
        appending ``:9000`` to that would produce an invalid URL. The Proxmox API
        port lives in ``self._port``, so any colon in the host is an embedded port
        and must be stripped first.
        """
        return self._split_host_port()[0]

    def _sidecar_warn_once(self, endpoint: str, err: Exception) -> None:
        """Log a down/failing sidecar endpoint once per host until it recovers."""
        if endpoint in self._sidecar_warned:
            return
        self._sidecar_warned.add(endpoint)

        host = self._sidecar_host()
        if isinstance(err, aiohttp.ClientConnectorError):
            LOGGER.warning(
                "Proxmox sidecar not reachable at %s:9000 — %s data stays empty "
                "until the sidecar service runs (%s). Further errors for this "
                "endpoint are suppressed until it recovers.",
                host,
                endpoint,
                err,
            )
        else:
            LOGGER.warning(
                "Proxmox sidecar request to %s:9000/%s failed: %s. Further errors "
                "for this endpoint are suppressed until it recovers.",
                host,
                endpoint,
                err,
            )

    async def _sidecar_get(self, hass, endpoint: str, timeout: int):
        """GET a sidecar (:9000) endpoint, returning {} and logging once on failure."""
        url = f"http://{self._sidecar_host()}:9000/{endpoint}"

        try:
            async with self._session(hass).get(
                url, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
            self._sidecar_warned.discard(endpoint)  # recovered
            return data
        except Exception as err:
            self._sidecar_warn_once(endpoint, err)
            return {}

    async def get_lm_sensors_http(self, hass, node: str):
        return await self._sidecar_get(hass, "sensors", 5)

    async def get_smart_data_http(self, hass, node: str):
        return await self._sidecar_get(hass, "smart", 15)

    async def get_memory_http(self, hass, node: str):
        return await self._sidecar_get(hass, "memory", 15)

    async def get_mounts(self, hass, node):
        return await self._sidecar_get(hass, "mounts", 15)

    async def get_zfs_pools(self, hass, node):
        return await self.get(hass, f"nodes/{node}/disks/zfs") or []

    async def start_vzdump(
        self,
        hass,
        node: str,
        vmid: str,
        storage: str,
        notes: str = None,
        mode: str = "snapshot",
        compress: str = "zstd",
    ):
        if not node or not vmid or not storage:
            raise ValueError("node, vmid, and storage are required to start a backup")

        path = f"nodes/{node}/vzdump"
        if compress == "none":
            compress = "0"

        valid_modes = ["snapshot", "suspend", "stop"]
        if mode not in valid_modes:
            raise ValueError(
                f"Invalid mode: {mode}. Must be one of: {', '.join(valid_modes)}"
            )

        valid_compress = ["0", "1", "lzo", "gzip", "zstd", "none"]
        if compress not in valid_compress:
            raise ValueError(
                f"Invalid compression: {compress}. Must be one of: {', '.join(valid_compress)}"
            )

        data = {
            "vmid": vmid,
            "storage": storage,
            "mode": mode,
            "compress": compress,
        }

        if notes:
            data["notes-template"] = notes

        result = await self.post(hass, path, data)

        return result

    async def get_cluster_status(self, hass):
        """Return cluster status (name, quorum, version)."""
        data = await self.get(hass, "cluster/status") or []
        # The API returns a list; extract the item with type=="cluster"
        for item in data:
            if isinstance(item, dict) and item.get("type") == "cluster":
                return item
        return {}

    async def get_cluster_ha_status(self, hass):
        """Return current HA manager status."""
        return await self.get(hass, "cluster/ha/status/current") or {}

    async def get_cluster_firewall_options(self, hass):
        """Return cluster firewall options."""
        return await self.get(hass, "cluster/firewall/options") or {}

    async def pbs_get(self, hass, path: str) -> Any:
        return await self._api_request(hass, "GET", path)

    async def pbs_post(self, hass, path: str, data=None) -> Any:
        return await self._api_request(hass, "POST", path, data=data or {})

    async def get_pbs_datastores(self, hass):
        data = await self.pbs_get(hass, "admin/datastore")
        return (
            [d["store"] for d in data if isinstance(d, dict) and "store" in d]
            if data
            else []
        )

    async def get_pbs_hostname(self, hass):
        """Get PBS hostname from status endpoint."""
        data = await self.pbs_get(hass, "status")

        if isinstance(data, dict):
            return data.get("hostname")

        return None

    async def get_pbs_datastore_status(self, hass, store: str):
        return await self.pbs_get(hass, f"admin/datastore/{store}/status") or {}

    async def get_pbs_datastore_usage(self, hass, store: str):
        # All disk-space fields (total/used/avail/deduplication) are already
        # included in get_pbs_datastore_status() → admin/datastore/{store}/status.
        # Calling /gc here was a copy-paste error that (a) duplicated the GC
        # request and (b) risked overwriting status fields in the coordinator merge.
        return {}

    async def get_pbs_tasks(self, hass):
        return await self.pbs_get(hass, "nodes/localhost/tasks") or []

    async def get_pbs_version(self, hass):
        return await self.pbs_get(hass, "version") or {}

    async def get_pbs_backup_list(self, hass, store: str):
        return await self.pbs_get(hass, f"admin/datastore/{store}/snapshots") or []

    async def get_pbs_node_status(self, hass):
        return await self.pbs_get(hass, "nodes/localhost/status") or {}

    async def get_pbs_gc(self, hass, store: str):
        return await self.pbs_get(hass, f"admin/datastore/{store}/gc") or {}

    async def get_pbs_snapshots(self, hass, store: str):
        return await self.pbs_get(hass, f"admin/datastore/{store}/snapshots") or []

    async def execute_pbs_node_command(self, hass, node, command):
        """Execute a command on PBS node (shutdown/reboot)."""
        try:
            path = f"nodes/{node}/status"
            data = {"command": command}

            result = await self.pbs_post(hass, path, data)
            return result is not None
        except Exception as e:
            LOGGER.error("Error executing PBS node command %s: %s", command, e)
            return False
