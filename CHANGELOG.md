# Changelog

All notable changes to Proxmox Extended Sensors are documented here.

## [Unreleased]

## [4.0.15] - 2026-06-07

### Fixed

- **K1 — PBS prune zerstörte alle Backups außer dem letzten** (`pbs_actions.py`) —
  `run_prune` iterierte über alle Namespaces und führte pro Gruppe `prune?keep-last=1`
  aus, was unwiderruflich Backups löschte und die im Datastore konfigurierten Retention-
  Regeln ignorierte. Ersetzt durch `prune-datastore`-Endpunkt, der die Datastore-eigenen
  Retention-Settings respektiert.

- **K2 — `entry`-Parameter in `button.py` wurde überschrieben** (`button.py`) —
  `entry = coordinator.config_entry` überschrieb den Funktionsparameter `entry` still,
  sodass nachfolgende Referenzen auf den Funktionsparameter auf ein falsches Objekt zeigten.
  Redundante Zuweisung entfernt.

- **K3 — WOL-Button sendete kein Magic Packet** (`button.py`) —
  `ProxmoxNodeButton.async_press()` behandelte den `"wake"`-Befehl nicht und führte
  stattdessen den Shutdown/Reboot-Pfad aus (oder tat nichts). WOL-Handling via
  `wake_on_lan.send_magic_packet` ergänzt; MAC-Adresse wird aus `entry.options["wol_macs"]`
  gelesen.

- **K4 — Alle Backup-Jobs bekamen denselben letzten Task-Status** (`coordinator.py`) —
  `_build_backup_jobs_payload` wählte den neuesten Task global aus und wies ihn allen Jobs zu.
  Jobs mit mehreren gesicherten VMs oder im selben Zeitraum sahen damit fremde Statusinformationen.
  Tasks werden jetzt per VMID indexiert; jeder Job bekommt den neuesten Task für seine
  konfigurierten VMIDs.

- **M1/N2 — Dead Code `limited_task_func`** (`coordinator.py`) —
  Funktion referenzierte das nicht-existente globale Semaphore `SEM` und warf bei jedem
  Aufruf einen `NameError`. Entfernt.

- **M2 — Disks ohne `model`-Feld wurden lautlos ignoriert** (`sensor/__init__.py`) —
  Die Bedingung `if d_model and "boot" not in d_model` übersprach Disks mit leerem oder
  fehlendem Model-Feld. Bedingung korrigiert: nur Disks mit `"boot"` im Model-Feld werden
  übersprungen; modellose Disks erhalten `d_id` als Label.

- **M4 — `ProxmoxPBSLastBackupSizeSensor.native_value` warf `TypeError` bei `size=None`**
  (`sensor/pbs.py`) — `None / (1024**3)` erzeugte einen `TypeError`. Fallback auf `0`
  ergänzt; gibt `None` zurück wenn keine Backup-Größe vorhanden.

- **M6 — `ProxmoxFailedTasksSensor` lieferte immer 0** (`coordinator.py`) —
  Der Cluster-Coordinator speicherte `cluster_tasks` nicht im Ergebnis-Dict, der Sensor
  las daher immer eine leere Liste. `cluster_tasks` wird jetzt explizit unter dem Schlüssel
  `"cluster_tasks"` gespeichert.

- **M7 — `datetime.now()` ohne UTC in Coordinator** (`coordinator.py`) —
  Drei Vorkommen von `datetime.now().strftime(...)` erzeugten naiven lokalen Timestamp-Strings,
  die je nach Server-Zeitzone inkonsistent waren. Geändert zu
  `datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")`.

- **M8 — WOL-MACs wurden nach Options-Speicherung gelöscht** (`options_flow.py`) —
  `async_update_entry(options={"wol_macs": ...})` setzte MACs korrekt, aber das sofort
  folgende `async_create_entry(data={})` überschrieb die Options mit einem leeren Dict.
  MACs werden jetzt korrekt via `async_create_entry(data={"wol_macs": wol_macs})`
  persistiert; redundanter `async_reload`-Aufruf entfernt.

- **N4 — `ProxmoxBackupHealthSensor.icon` verwendete `self.state` statt `self.native_value`**
  (`sensor/cluster.py`) — `self.state` gibt `"unavailable"` zurück solange die Entity nicht
  in der HA-Registry registriert ist, was zu falschen Icon-Anzeigen während der ersten
  Aktualisierung führte. Auf `self.native_value` umgestellt.

## [4.0.14] - 2026-06-07

### Fixed

- **H1 — `build_cluster_notifications_data` doppelt definiert** (`logic/cluster_notifications.py`) —
  Die zweite Definition überschrieb die erste still und fehlte das `"notifications_configured"`-Feld
  sowie den `"not_configured"`-Zweig für leere Notify-Konfigurationen. Zweite Definition entfernt,
  erste (korrekte) bleibt erhalten.

- **H2 — `ProxmoxConfigFlow.VERSION = 1` vs. `ENTRY_VERSION = 2`** (`config_flow.py`) —
  Neue Einträge via Config Flow hatten `version=1` und lösten nach jedem HA-Start eine
  Migration aus. `VERSION` auf `2` gesetzt.

- **H3 — Operator-Precedence-Bug beim SMART-Disk-Matching** (`sensor/disks.py`) —
  `if smart_model and clean_model in smart_model or smart_model in clean_model` wurde falsch
  geklammert: `"" in any_string` ist immer `True`, sodass SMART-Einträge mit leerem Model-Feld
  jeder Disk zugeordnet wurden. Korrekte Klammerung:
  `if smart_model and (clean_model in smart_model or smart_model in clean_model)`.

- **H4 — `PBSLastActionSensor` unique_id ohne `server_id`-Präfix** (`sensor/sensor_last_action.py`) —
  Zwei PBS-Instanzen mit gleichnamigem Datastore erzeugten identische `unique_id`s und führten
  zu Entity-Konflikten in HA. Unique-ID-Schema auf `pbs_{server_id}_{datastore}_last_action`
  vereinheitlicht (konsistent mit allen anderen PBS-Sensoren).

- **H5 — `asyncio.sleep(delay_between)` blockierte den Semaphore-Slot** (`services.py`) —
  Der Delay-Sleep lag innerhalb des `async with semaphore`-Blocks in `backup_with_limit`.
  Mit `max_concurrent=1` konnte der nächste Backup erst nach dem gesamten Delay starten,
  obwohl der API-Call bereits abgeschlossen war — `max_concurrent` war damit wirkungslos.
  Sleep auf nach dem `async with`-Block verschoben.

## [4.0.13] - 2026-06-07

### Fixed

- **`manifest.json` version was stale** — still reported `4.0.1` (the last upstream
  release), so HACS would not detect or offer updates for this fork. Bumped to
  `4.0.12` to reflect the current state.

## [4.0.12] - 2026-06-07

### Added

- **HACS one-click install button** — Added the standard `my.home-assistant.io` badge
  to `README.md` and `docs/en/README.md` so users can add the repository to HACS
  without manually copying the URL.

## [4.0.11] - 2026-06-07

### Housekeeping

- **Fork attribution** — Added credits section to `README.md` and all localized docs
  crediting [Javisen](https://github.com/Javisen) as the original upstream author.
- **Repository URLs** — Updated `manifest.json` (`codeowners`, `documentation`,
  `issue_tracker`), HACS install instructions, sidecar script `wget` URLs, and all
  doc footers/logo links from `Javisen/proxmox_sensors` to `umrath/proxmox_sensors`.
- **License** — Added umrath's fork copyright alongside the original Javisen copyright
  as required by the MIT License terms.

## [4.0.10] - 2026-06-07

### Fixed

- **Duplicate `_LOGGER` definition in `sensor/__init__.py`** — `_LOGGER` was assigned
  twice (lines 19 and 95), the second assignment being a no-op that cluttered the file.
  Removed the redundant assignment.

- **`import re` inside function body in `sensor/__init__.py`** — `import re` was placed
  inside `async_setup_entry` instead of at the top of the module. Moved to module level.

## [4.0.9] - 2026-06-07

### Security

- **`urllib3.disable_warnings()` was called at module level** — this suppressed
  `InsecureRequestWarning` globally for the entire Python process, even for users
  who have SSL verification enabled and don't need it suppressed. It also affected
  all other integrations loaded in the same HA instance.

  Fix: Moved `urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)`
  into `ProxmoxClient._build_client_sync()`, called only when `verify_ssl=False`.
  Users with SSL verification enabled are no longer affected.

## [4.0.8] - 2026-06-07

### Security

- **Service call parameters `node` and `storage` were not validated** — a crafted
  service call with `node: "../../etc/proxmox"` or `storage: "local;rm -rf /"` would
  have passed the node/storage strings directly into Proxmox API URL paths, enabling
  path-traversal and command-injection attempts.

  Fix: Added `_validate_identifier(value, name)` which rejects any value not matching
  `^[a-zA-Z0-9_\-\.]+\Z` (alphanumeric, dash, underscore, dot). Both `handle_backup_all`
  and `handle_create_vzdump_backup` now validate `node` and `storage` before any further
  processing. The regex uses `\Z` (not `$`) to prevent Python's `re` from silently
  accepting a trailing newline.

## [4.0.7] - 2026-06-07

### Fixed

- **Entity cleanup wiped all entities on empty coordinator data** — on HA restart
  or temporary network failure the coordinator can return partial data, resulting
  in an empty entity list. The cleanup loop then removed every previously
  registered entity. The cleanup now runs only when at least one entity was
  successfully created.

- **`backup_all` delay used string comparison for "last target"** — the check
  `vmid != targets[-1]` compared strings, which works by coincidence but is
  semantically wrong. Replaced with an index check (`idx < last_idx`) that
  is unambiguous and works correctly even if two guests share an ID.

## [4.0.6] - 2026-06-07

### Fixed

- **Services only worked for the last configured node in multi-node setups** —
  Each PVE entry called `register_services()` which overwrote the previous
  handler. All service calls then used the client of the *last* registered
  entry, regardless of which node was specified in the call.

  Fix: Services are now registered only once per HA instance. Every handler
  looks up the correct entry at call time via `_find_entry_for_node()` which
  searches `hass.data[DOMAIN]` by the `node` parameter from the service call.
  If no matching entry is found the service logs a warning and exits cleanly.

## [4.0.5] - 2026-06-07

### Fixed

- **PBS datastore usage sensors showed wrong values** — `get_pbs_datastore_usage()`
  was calling `admin/datastore/{store}/gc` (garbage-collection stats) instead of
  the correct usage endpoint. Since `get_pbs_datastore_status()` already returns
  all disk-space fields (`total`, `used`, `avail`, `deduplication`), the usage
  method now returns `{}` to avoid a redundant network call and prevent GC data
  from overwriting size fields in the coordinator merge.

## [4.0.4] - 2026-06-07

### Fixed

- **CLUSTER entry was never auto-created** — `_async_manage_cluster_entry`
  assembled `cluster_data` but never called `hass.config_entries.flow.async_init()`.
  The CLUSTER coordinator (cluster-wide sensors: quorum, HA status, backup jobs)
  therefore never started. Added the missing `hass.async_create_task(flow.async_init(...))`
  call and the corresponding `async_step_integration_discovery` handler in the
  config flow so the entry is created without user interaction.

## [4.0.3] - 2026-06-07

### Fixed

- **`backup_all` service crashed with `NameError` on every call** — `limited_task`
  was referenced inside `handle_backup_all` but was only defined in the coordinator
  scope. The concurrency semaphore is already embedded in `backup_with_limit`, so
  `asyncio.gather(*tasks)` is the correct call.

- **`backup_all` crashed with `TypeError` when coordinator had no data yet** —
  `coordinator.data` can be `None` during the first poll or after a failed update.
  Added `or {}` guard so the service exits cleanly instead of raising.

## [4.0.2] - 2026-06-07

### Fixed

- **VM/CT migration: entities stay available after live migration**
  VMs and containers that migrate to another cluster node no longer become
  unavailable. The coordinator now enriches per-node data with
  `cluster/resources` so migrated guests are still found under their original
  `node:vmid` key.

- **Entity ID stability across migrations**
  The `node` field in migrated guest data is kept as the *configured* node
  (not the current physical location). This prevents HA from treating a
  migrated guest as a brand-new entity and creating duplicate entries.

- **`migrated` flag always set**
  Local guests now explicitly carry `migrated: false`. Previously the flag was
  absent for local guests, causing checks like `vm_data.get("migrated")` to be
  ambiguous.

- **Mass backup (`backup_all`) skips migrated guests**
  `nodes/{node}/vzdump` can only back up guests that are actually running on
  that node. Migrated guests are now excluded from the target list to prevent
  backup errors.

### Added

- `current_node` and `migrated` exposed as `extra_state_attributes` on VM and
  CT status sensors, making migration state visible in the HA UI without
  needing a separate sensor.

- Unit tests for migration behaviour (`tests/test_coordinator_migration.py`,
  `tests/test_sensor_vm_migration.py`, `tests/test_sensor_ct_migration.py`,
  `tests/test_services_migration.py`, `tests/test_guest_keys.py`).
