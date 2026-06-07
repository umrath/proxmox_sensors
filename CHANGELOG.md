# Changelog

All notable changes to Proxmox Extended Sensors are documented here.

## [Unreleased]

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
