# Changelog

All notable changes to Proxmox Extended Sensors are documented here.

## [Unreleased]

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
