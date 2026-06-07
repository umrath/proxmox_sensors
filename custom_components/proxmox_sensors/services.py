"""SERVICES for Proxmox Extended Sensors."""

import logging
import asyncio
import re
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+\Z")


def _validate_identifier(value: str, name: str) -> None:
    """Raise ValueError if *value* is not a safe Proxmox node/storage identifier."""
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(
            f"Invalid {name}: {value!r}. Only alphanumeric, dash, underscore, dot allowed."
        )


def _find_entry_for_node(hass: HomeAssistant, node: str):
    """Return entry_data for the PVE entry that owns *node*, or None."""
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if entry_data.get("node") == node:
            return entry_data
    return None


def register_services(hass: HomeAssistant, entry):
    """Register (or no-op if already registered) all Proxmox services.

    All handlers dispatch on the ``node`` parameter from the service call so
    that multi-node setups with several PVE entries work correctly — the last
    call to register_services no longer silently overwrites the handlers of
    the first.
    """

    # Guard: register each service only once per HA instance.
    # Subsequent entries for other nodes still benefit from the node-dispatching
    # handlers below, which look up the right entry at call time.
    if hass.services.has_service(DOMAIN, "backup_all"):
        return

    # ====== SIMPLE / MULTI BACKUP SERVICE ==========
    async def handle_create_vzdump_backup(call: ServiceCall):
        node = call.data.get("node")
        guests = call.data.get("guests") or call.data.get("vmid")
        storage = call.data.get("storage")
        mode = call.data.get("mode", "snapshot")
        compress = call.data.get("compress", "zstd")

        max_concurrent = call.data.get("max_concurrent", 1)
        delay_between = call.data.get("delay_between", 0)

        if not node:
            raise ValueError("Node is required")

        if not guests:
            raise ValueError("Guests list is required")

        if not storage:
            raise ValueError("Storage is required")

        node = str(node).strip()
        storage = str(storage).strip()
        _validate_identifier(node, "node")
        _validate_identifier(storage, "storage")

        if isinstance(guests, str):
            guests = [g.strip() for g in guests.split(",") if g.strip()]
        elif isinstance(guests, int):
            guests = [guests]
        elif not isinstance(guests, list):
            raise ValueError("Guests must be int, list or comma-separated string")

        targets = [int(g) for g in guests]

        entry_data = _find_entry_for_node(hass, node)
        if entry_data is None:
            _LOGGER.warning("No configured entry found for node %s", node)
            return

        client = entry_data["client"]

        _LOGGER.info(
            f"Backup requested for guests {targets} on node {node} "
            f"with mode={mode}, compress={compress}"
        )

        success_count = 0
        error_count = 0

        for idx, vmid in enumerate(targets):
            try:
                _LOGGER.info(f"Starting backup of {vmid}...")

                result = await client.start_vzdump(
                    hass,
                    node=node,
                    vmid=vmid,
                    storage=storage,
                    mode=mode,
                    compress=compress,
                    notes="HA-{{vmid}}, {{guestname}}",
                )

                _LOGGER.info(f"Backup of {vmid} started successfully")
                success_count += 1

                if delay_between > 0 and idx < len(targets) - 1:
                    _LOGGER.info(f"Waiting {delay_between}s before next backup...")
                    await asyncio.sleep(delay_between)

            except Exception as e:
                error_count += 1
                _LOGGER.error(f"Error in backup of {vmid}: {e}")

        _LOGGER.info(
            f"Simple/Multi backup completed. "
            f"Success: {success_count} | Failures: {error_count} | Total: {len(targets)}"
        )

    hass.services.async_register(
        DOMAIN, "create_vzdump_backup", handle_create_vzdump_backup
    )

    # =======MASSIVE BACKUP=========

    async def handle_backup_all(call: ServiceCall):
        node = call.data.get("node")
        storage = call.data.get("storage")
        mode = call.data.get("mode", "snapshot")
        compress = call.data.get("compress", "zstd")
        max_concurrent = call.data.get("max_concurrent", 1)
        delay_between = call.data.get("delay_between", 30)

        if not node:
            raise ValueError("Node is required")

        if not storage:
            raise ValueError("Storage is required")

        node = str(node).strip()
        storage = str(storage).strip()
        _validate_identifier(node, "node")
        _validate_identifier(storage, "storage")

        # Validate mode values
        valid_modes = ["snapshot", "suspend", "stop"]
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode. Must be one of: {', '.join(valid_modes)}")

        valid_compress = ["zstd", "gzip", "lzo", "none", "0", "1"]
        if compress not in valid_compress:
            raise ValueError(
                f"Invalid compress. Must be one of: {', '.join(valid_compress)}"
            )

        if compress == "none":
            compress = "0"

        include_vms = call.data.get("include_vms", False)
        include_cts = call.data.get("include_cts", False)

        if not include_vms and not include_cts:
            _LOGGER.warning("Massive backup requested without selecting VMs or CTs")
            return

        entry_data = _find_entry_for_node(hass, node)
        if entry_data is None:
            _LOGGER.warning("No configured entry found for node %s", node)
            return

        client = entry_data["client"]
        coordinator = entry_data["coordinator"]
        data = coordinator.data or {}

        vm_list = []
        ct_list = []

        # VMs
        if include_vms and "vms" in data:
            for vm_data in data["vms"].values():
                if not isinstance(vm_data, dict):
                    continue
                if vm_data.get("migrated"):
                    continue   # migrated VMs live on another node; vzdump would fail
                if vm_data.get("node") != node:
                    continue
                vmid = vm_data.get("vmid")
                if vmid is not None:
                    vm_list.append(str(vmid))

        # CTs
        if include_cts and "cts" in data:
            for ct_data in data["cts"].values():
                if not isinstance(ct_data, dict):
                    continue
                if ct_data.get("migrated"):
                    continue   # migrated CTs live on another node; vzdump would fail
                if ct_data.get("node") != node:
                    continue
                ctid = ct_data.get("vmid")
                if ctid is not None:
                    ct_list.append(str(ctid))

        targets = vm_list + ct_list

        if not targets:
            _LOGGER.warning(f"No machines found for backup on node {node}")
            return

        _LOGGER.info(
            f"Massive backup started on node {node}. "
            f"VMs: {len(vm_list)} | CTs: {len(ct_list)} | "
            f"Mode: {mode} | Compress: {compress} | "
            f"Concurrent: {max_concurrent} | Delay: {delay_between}s"
        )

        # Process with concurrency limit using semaphore
        semaphore = asyncio.Semaphore(max_concurrent)
        results = []

        last_idx = len(targets) - 1

        async def backup_with_limit(vmid, idx):
            try:
                async with semaphore:
                    _LOGGER.info(f"Starting backup of {vmid}...")
                    result = await client.start_vzdump(
                        hass,
                        node=node,
                        vmid=vmid,
                        storage=storage,
                        mode=mode,
                        compress=compress,
                        notes="HA-{{vmid}}, {{guestname}}",
                    )
                _LOGGER.info(f"Backup of {vmid} started successfully")

                if delay_between > 0 and idx < last_idx:
                    _LOGGER.info(f"Waiting {delay_between}s before next backup...")
                    await asyncio.sleep(delay_between)

                return (vmid, True, result)
            except Exception as e:
                _LOGGER.error(f"Error in backup of {vmid}: {e}")
                return (vmid, False, str(e))

        tasks = [backup_with_limit(vmid, idx) for idx, vmid in enumerate(targets)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = 0
        error_count = 0
        detailed_results = []

        for result in results:
            if isinstance(result, tuple) and len(result) == 3:
                vmid, success, detail = result
                if success:
                    success_count += 1
                else:
                    error_count += 1
                detailed_results.append(
                    {"vmid": vmid, "success": success, "detail": detail}
                )
            else:
                error_count += 1
                detailed_results.append(
                    {
                        "vmid": "unknown",
                        "success": False,
                        "detail": str(result) if result else "Unknown error",
                    }
                )

        _LOGGER.info(
            f"Massive backup completed. "
            f"Success: {success_count} | Failures: {error_count} | Total: {len(targets)}"
        )

        if error_count > 0:
            notification_id = f"proxmox_backup_summary_{node}"
            message = (
                f"📊 **Massive Backup Summary - Node: {node}**\n\n"
                f"✅ Success: {success_count}\n"
                f"❌ Failures: {error_count}\n"
                f"📦 Total: {len(targets)}\n\n"
                f"💾 Storage: {storage}\n"
                f"⚙️ Mode: {mode}\n"
                f"🗜️ Compression: {compress}"
            )

            persistent_notification.create(
                hass, message, "Proxmox Backup Summary", notification_id
            )

        return detailed_results

    hass.services.async_register(DOMAIN, "backup_all", handle_backup_all)

    # ========SHUTDOWN NODE===========

    async def handle_confirm_shutdown(call: ServiceCall):
        node = str(call.data.get("node") or "").strip()
        confirm = call.data.get("confirm", False)

        _validate_identifier(node, "node")

        if not confirm:
            notification_id = f"proxmox_shutdown_confirm_{node}"
            message = (
                f"⚠️ **Shutdown node {node}**\n\n"
                f"To confirm, run this service again with `confirm: true`."
            )

            persistent_notification.create(
                hass, message, "Confirm Proxmox Shutdown", notification_id
            )
            return

        entry_data = _find_entry_for_node(hass, node)
        if entry_data is None:
            _LOGGER.warning("No configured entry found for node %s", node)
            return

        try:
            result = await entry_data["client"].shutdown_node(hass, node)
            if result:
                persistent_notification.dismiss(
                    hass, f"proxmox_shutdown_confirm_{node}"
                )
        except Exception as e:
            _LOGGER.error(f"Error shutting down node {node}: {e}")

    hass.services.async_register(
        DOMAIN, "confirm_shutdown_node", handle_confirm_shutdown
    )

    # =======REBOOT NODE==========

    async def handle_confirm_reboot(call: ServiceCall):
        node = str(call.data.get("node") or "").strip()
        confirm = call.data.get("confirm", False)

        _validate_identifier(node, "node")

        if not confirm:
            notification_id = f"proxmox_reboot_confirm_{node}"
            message = (
                f"🔄 **Reboot node {node}**\n\n"
                f"To confirm, run this service again with `confirm: true`."
            )

            persistent_notification.create(
                hass, message, "Confirm Proxmox Reboot", notification_id
            )
            return

        entry_data = _find_entry_for_node(hass, node)
        if entry_data is None:
            _LOGGER.warning("No configured entry found for node %s", node)
            return

        try:
            result = await entry_data["client"].reboot_node(hass, node)
            if result:
                persistent_notification.dismiss(hass, f"proxmox_reboot_confirm_{node}")
        except Exception as e:
            _LOGGER.error(f"Error rebooting node {node}: {e}")

    hass.services.async_register(DOMAIN, "confirm_reboot_node", handle_confirm_reboot)

    # ======= WAKE NODE (WOL) ==========

    async def handle_wake_node(call: ServiceCall):
        node = call.data.get("node")
        mac = call.data.get("mac")

        # Collect cluster_nodes from all available PVE coordinators
        cluster_nodes = []
        for edata in hass.data.get(DOMAIN, {}).values():
            coord = edata.get("coordinator")
            if coord and coord.data:
                nodes = coord.data.get("cluster_nodes", [])
                for n in nodes:
                    if n not in cluster_nodes:
                        cluster_nodes.append(n)

        # -------- AUTO NODE (single node setups) --------
        if not node:
            if len(cluster_nodes) == 1:
                node = cluster_nodes[0]
                _LOGGER.info(f"No node provided, using detected node: {node}")
            elif cluster_nodes:
                raise ValueError(
                    f"Node is required. Available nodes: {', '.join(cluster_nodes)}"
                )
            else:
                raise ValueError("Node is required and no cluster nodes detected yet")

        # -------- VALIDATION --------
        if cluster_nodes and node not in cluster_nodes:
            raise ValueError(
                f"Invalid node '{node}'. Available nodes: {', '.join(cluster_nodes)}"
            )

        # -------- MAC VALIDATION --------
        if not mac:
            raise ValueError("MAC address is required for WOL")

        mac_clean = mac.replace(":", "").replace("-", "")
        if len(mac_clean) != 12:
            raise ValueError(f"Invalid MAC address format: {mac}")

        try:
            _LOGGER.info(f"Sending WOL packet to node {node} ({mac})")

            await hass.services.async_call(
                "wake_on_lan",
                "send_magic_packet",
                {"mac": mac},
                blocking=True,
            )

            _LOGGER.info(f"WOL packet sent to {node}")

        except Exception as e:
            _LOGGER.error(f"Error sending WOL to node {node}: {e}")

    hass.services.async_register(DOMAIN, "wake_node", handle_wake_node)
