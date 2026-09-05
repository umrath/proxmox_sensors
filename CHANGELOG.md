# Changelog

All notable changes to Proxmox Extended Sensors are documented here.

## [Unreleased]

## [5.0.1] - 2026-09-05

Befunde aus dem Review des 5.0.0-Umbaus. Betrifft ausschließlich die
Authentifizierung per Benutzer/Passwort; Setups mit API-Token sind nicht
betroffen.

### Fixed

- **Fehlgeschlagener Login wurde pro Aufruf wiederholt statt einmal pro Zyklus**
  (`api.py`) — Der Auth-Lock bündelte nur *erfolgreiche* Logins. War der Node
  nicht erreichbar, stellte sich jeder Aufruf eines Poll-Zyklus am Lock an und
  versuchte den Login erneut: gemessen **14 serialisierte Loginversuche** für
  einen einzigen Node, jeder bis zu `REQUEST_TIMEOUT` lang. Ein fehlgeschlagener
  Login wird jetzt kurz gemerkt (`AUTH_RETRY_COOLDOWN`, 30 s — kürzer als das
  Poll-Intervall), sodass pro Zyklus genau ein Versuch stattfindet. Damit gilt
  die in den 5.0.0-Release-Notes behauptete Eigenschaft „ein Login statt einer
  pro Anfrage" nun auch im Fehlerfall; in 5.0.0 stimmte sie nur bei Erfolg.

- **Ticket und CSRF-Token konnten aus verschiedenen Logins stammen**
  (`api.py`) — `_ensure_ticket()` lieferte nur das Ticket zurück, das
  CSRF-Token wurde anschließend erneut aus dem Objektzustand gelesen. Erneuerte
  ein paralleler Aufruf dazwischen die Sitzung, konnte ein frisches Ticket mit
  einem veralteten CSRF-Token kombiniert werden — PVE hätte den schreibenden
  Aufruf abgelehnt. Beide Werte werden jetzt als Paar zurückgegeben und
  gemeinsam verwendet.

### Added

- Tests für den Cluster-Coordinator-Rückfall auf Vorwerte (in 5.0.0 geändert,
  aber ungetestet) sowie für beide oben genannten Fehler. Suite: 311 Tests.

## [5.0.0] - 2026-09-05

### Changed (Architektur)

- **API-Transport vollständig auf `aiohttp` umgestellt; `proxmoxer` entfällt**
  (`api.py`, `manifest.json`) — Bisher lief jeder Aufruf synchron über
  `hass.async_add_executor_job` (proxmoxer bzw. `requests`). Jetzt gibt es einen
  einzigen asynchronen `_api_request()`-Pfad für PVE, PBS und den Sidecar. Die
  Authentifizierung ist nativ implementiert: API-Token per Header
  (`PVEAPIToken=…`, PBS-Format unverändert) und Benutzer/Passwort per
  `access/ticket` mit `PVEAuthCookie`, `CSRFPreventionToken` für schreibende
  Aufrufe und Erneuerung unter einem Lock, sodass ein Schwall paralleler
  Anfragen genau einen Login auslöst. Die Abhängigkeit `proxmoxer` wurde aus
  `manifest.json` entfernt; `aiohttp` liefert Home Assistant ohnehin mit.

### Fixed

- **Ein schlecht erreichbarer PVE-Node ließ die gesamte HA-Instanz hängen**
  (`api.py`) — Ursache war nicht die Integration allein, sondern der geteilte
  Executor-Pool: `asyncio.timeout` bricht nur das `await` ab, **nicht** den
  Executor-Thread. Jeder abgelaufene Aufruf hinterließ damit einen blockierten
  Worker im HA-weiten `SyncWorker`-Pool (64 Threads, von *allen* Integrationen
  geteilt). Da die `Semaphore(5)` nur Awaits begrenzt, griff nach jeder
  Timeout-Welle die nächste Welle weitere Threads ab — ein hängender Node
  konnte so bis zu 14 Threads pro Zyklus binden, bei mehreren Nodes lief der
  Pool leer und jede andere Integration stand still. Der neue Transport nutzt
  `aiohttp.ClientTimeout(total=…)`: ein hartes Gesamtlimit, das Connect,
  TLS-Handshake und eine tröpfelnde Antwort gleichermaßen abdeckt — und da er
  asynchron ist, bleibt beim Auslaufen kein Thread zurück. Ein lahmer Node
  verlangsamt nur noch seinen eigenen Coordinator.

- **Teilausfall ließ Cluster-Entitäten flappen** (`coordinator.py`) — Der
  Cluster-Coordinator warf weiterhin bedingungslos `UpdateFailed` und hatte die
  Behandlung aus 4.2.1 nie erhalten. Er behält jetzt ebenfalls die Vorwerte,
  wenn bereits Daten vorliegen.

- **Nebenbefund aus dem Umbau**: Ein fehlgeschlagener Login (falsches Passwort
  oder Netz-Aussetzer) hätte beim normalen Polling eine Ausnahme bis in den
  Coordinator durchgereicht. Der Vertrag „liefert `None`, wirft nie" gilt jetzt
  auch für den Ticket-Pfad; Ausnahmen fliegen nur noch bei der Validierung im
  Config-Flow (`raise_errors=True`).

### Removed

- `proxmoxer` als Abhängigkeit, sowie sämtliche `requests`-/`urllib3`-Nutzung.
  Damit entfällt auch die geteilte, nicht thread-sichere `requests.Session`, die
  bisher von bis zu fünf Threads gleichzeitig benutzt wurde.
- `tests/test_api_urllib3_warnings.py` — testete das Eingrenzen der
  `urllib3`-Warnungen; dieser Code existiert nicht mehr. Die TLS-Verifikation
  läuft über `async_get_clientsession(verify_ssl=…)` und ist in
  `tests/test_api_transport.py` abgedeckt.

### Hinweis zur Migration

- Keine Konfigurationsänderung nötig; bestehende Einträge (Token wie
  Benutzer/Passwort) funktionieren unverändert. Da `proxmoxer` entfällt, kann
  Home Assistant das Paket nach dem Update entfernen.

## [4.2.2] - 2026-08-08

### Fixed

- **Sidecar-Aufrufe (`:9000`) schluckten Fehler wortlos** (`api.py`) — Die vier
  Sidecar-Endpunkte (`sensors`, `smart`, `memory`, `mounts`) fingen jeden Fehler
  mit `except Exception: return {}` ab. Lief der Sidecar-Dienst nicht, entstanden
  ohne jede Meldung keine Entitäten. Alle vier nutzen jetzt einen gemeinsamen
  Helfer `_sidecar_get()`, der bei Fehlern **einmal pro Host/Endpunkt** eine
  `LOGGER.warning` ausgibt — unterschieden nach „nicht erreichbar"
  (`ConnectionError`, Dienst läuft nicht) und „Anfrage fehlgeschlagen" (HTTP/
  Timeout). Bei Erfolg wird der Warn-Status zurückgesetzt, sodass eine
  Wiederherstellung bzw. ein erneuter Ausfall wieder sichtbar wird.

## [4.2.1] - 2026-08-05

### Fixed

- **Ein einzelner langsamer API-Aufruf machte alle Entitäten eines Knotens
  `unavailable`** (`coordinator.py`) — Die gesamte parallele Abfrage lief in
  einem gemeinsamen `asyncio.timeout(30)`. Blockierte ein Aufruf (z. B.
  `/nodes/{node}/storage`, während `pvestatd` auf einen nicht erreichbaren
  PBS-Datastore wartete), brach der Timeout die komplette `gather()` ab, die
  13 erfolgreichen Ergebnisse wurden verworfen und `UpdateFailed` setzte alle
  ~120 Entitäten des Knotens gleichzeitig auf `unavailable` — bei jedem
  Intervall erneut. Jeder Task hat jetzt sein eigenes Zeitlimit
  (`_TASK_TIMEOUT = 20 s`): ein hängender Aufruf wird zu einer `TimeoutError`
  in `results`, die restlichen Aufrufe befüllen weiter. Der äußere Timeout
  (`_OUTER_TIMEOUT = 45 s`) ist nur noch ein Sicherheitsnetz.

- **`UpdateFailed` bei Teilausfall ließ Entitäten flappen** (`coordinator.py`) —
  Ein Fehler im gesamten Zyklus wirft nur noch `UpdateFailed`, wenn keine
  Vorwerte existieren (erster Durchlauf, Host down, falsche Auth). Liegen
  bereits Daten vor (`coordinator.data`), werden diese behalten und im
  nächsten Intervall erneut versucht, statt alle Entitäten auf `unavailable`
  zu setzen.

- **Ergebnis-Verarbeitung stürzte bei einer `TimeoutError` ab**
  (`coordinator.py`) — `_build_vms_dict`, `_build_cts_dict` und der
  Storage-Aufbau iterierten über `x or []`; eine `TimeoutError` (wahrheitswert
  `True`) ist nicht iterierbar und löste `TypeError` aus, der wiederum den
  ganzen Zyklus scheitern ließ. Nicht-Listen werden jetzt als leer behandelt.

- **PVE-Anfrage-Timeout von 30 s auf 15 s gesenkt** (`api.py`) — Ein
  festhängender Endpunkt schlägt schneller fehl und gibt seinen Executor-Thread
  frei, statt nahe am Gesamt-Budget des Coordinators zu blockieren.

## [4.2.0] - 2026-08-04

Selektive Übernahme der Upstream-Änderungen (`Javisen/proxmox_sensors`,
Commit `9a6b7e3` „Fix node detection and improve hardware sensors"). Die
Upstream-Version-Bumps (4.0.2/4.0.3), der bereits vorhandene
`config_flow.VERSION = 2`, das VM/CT-`node`-Attribut (der Fork bietet mit
`current_node`/`migrated` mehr) sowie die fehlerhafte `get_zfs_pools`-Änderung
(referenziert das nirgends definierte `_is_expected_no_zfs_pools_error`,
`NameError`) wurden bewusst **nicht** übernommen.

### Added

- **Spannungs- und Lüfter-Sensoren** (`sensor/hardware.py`, `sensor/__init__.py`) —
  `ProxmoxHardwareSensor` erkennt pro lm-sensors-Messwert am Input-Key den Typ:
  `fanN_input` → Lüfter (Einheit `RPM`, Icon `mdi:fan`), `inN_input` → Spannung
  (Einheit `V`, `device_class: voltage`, Icon `mdi:flash`), sonst Temperatur
  (`°C`, unverändert). Zuvor wurden Lüfterdrehzahlen (> 145) durch den
  Temperaturfilter `1 < f < 145` verworfen und Spannungen fälschlich als `°C`
  dargestellt. Neue Kuratierung `is_meaningful()` filtert tote/unplausible Rails
  heraus (Lüfter `== 0` RPM, Spannung `<= 0` oder `> 30` V), damit nicht dutzende
  bedeutungslose Super-I/O-Rails als Entitäten erscheinen.

### Fixed

- **PVE-Knoten im Standby/ausgeschaltet erzeugten Error-Logspam** (`api.py`) —
  `ProxmoxClient.get()` protokollierte Verbindungsfehler eines nicht erreichbaren
  Knotens als `LOGGER.error`. Erwartete Verbindungsfehler
  (`ConnectionError`/`ConnectTimeout`/`Timeout`) werden jetzt auf `debug`
  herabgestuft und liefern `None`, statt bei jedem Poll-Zyklus einen Fehler zu
  loggen.

- **CPU-Aggregation las CPU-benannte Spannungs-/Lüfter-Rails als Temperatur**
  (`sensor/hardware.py`) — Ein Super-I/O-Messwert mit CPU-Label (z. B. `Vcore`,
  `CPU Fan`) wird von der Setup-Klassifizierung (`cpu`/`core`-Substring) zum
  aggregierten CPU-Sensor. `_detect_sensor_type` erzwingt für `_is_cpu`/
  `_is_chipset` nun `temperature`, und der Fallback in `_parse` überspringt
  `fanN_input`/`inN_input`, sodass eine 1,1-V-`Vcore`-Spannung nicht mehr als
  1,1 °C in Wert oder Attribute des CPU-Sensors einfließt.

### Changed

- **Auto-Node-Erkennung ohne IP-Treffer fällt auf manuelle Auswahl zurück**
  (`config_flow.py`) — Bisher wählte der Flow bei fehlendem IP-Abgleich still
  `nodes[0]` und konnte so in Clustern den falschen Knoten anbinden. Der
  `nodes[0]`-Fallback entfällt; ohne Treffer erscheint jetzt die manuelle
  Knotenauswahl.

### Hinweis zur Migration

- Spannungs-Rails, die zuvor im Bereich `1 < f < 145` lagen, erschienen
  fälschlich als `°C`-Temperatur-Entitäten mit identischer `unique_id`. Nach dem
  Update wechseln sie auf `V`/`device_class: voltage`; Home Assistant meldet
  dafür einmalig eine „units_changed"-Reparatur (Langzeitstatistik der
  betroffenen Entität zurücksetzen). Neue Lüfter-Entitäten, die beim ersten
  Poll `0` RPM anzeigen (Zero-RPM-Leerlauf), werden bis zum nächsten
  Neuladen der Integration ausgeblendet.

## [4.1.0] - 2026-06-08

### Added

- **Replikationsstatus-Sensor** (`sensor/node.py`, `coordinator.py`, `api.py`) —
  Neuer Knoten-Sensor `Replikation`, der den Zustand der PVE-Speicherreplikation
  (`GET /nodes/{node}/replication`) abbildet. Der Sensorzustand ist `ok` (alle
  Replikationsjobs erfolgreich), `error` (mindestens ein Job mit `fail_count > 0`
  oder gesetztem `error`) bzw. `unknown` (keine Replikationsjobs konfiguriert).
  Die Attribute enthalten `total_jobs`, `failed_jobs`, den jüngsten `last_sync`
  sowie eine `jobs`-Liste mit je Gast, Ziel, Zeitplan, Status, Fehlerzähler,
  Fehlertext, letzter/nächster Synchronisation und Dauer. Zeitstempel werden in
  UTC nach ISO-8601 normalisiert. Übersetzungen für alle unterstützten Sprachen
  ergänzt.

## [4.0.19] - 2026-06-07

### Fixed (Second review — LOW)

- **L1 — `PBSLastActionSensor` überschrieb `state` statt `native_value`** (`sensor/sensor_last_action.py`) —
  Eine `SensorEntity` soll ihren Wert über `native_value` liefern; das direkte Überschreiben
  von `state` umgeht die Verarbeitung der Basisklasse (Unit/Device-Class/State-Class). Auf
  `native_value` umgestellt.

- **L2 — Sidecar-URLs brachen bei Host mit Port** (`api.py`) —
  Die HTTP-Sidecar-Endpunkte (`:9000`) bauten die URL als `http://{host}:9000/...`. Enthielt
  `host` bereits einen API-Port (z. B. `pve.local:8006`), entstand die ungültige URL
  `http://pve.local:8006:9000/...`. Neuer Helfer `_sidecar_host()` entfernt einen eingebetteten
  Port (inkl. bracketed IPv6) vor dem Anhängen von `:9000`.

- **L3 — WOL-MAC-Validierung prüfte nur die Länge** (`services.py`) —
  `handle_wake_node` akzeptierte jeden 12-Zeichen-String nach Entfernen der Trennzeichen,
  auch nicht-hexadezimale wie `gg:hh:ii:jj:kk:ll`. Validiert jetzt gegen `^[0-9a-fA-F]{12}$`.

- **L4 — `pbs_auth_status` nutzte Dict-Truthiness** (`coordinator.py`) —
  `"OK" if version_info else "ERROR"` meldete "OK", sobald `get_pbs_version` irgendein
  nicht-leeres Dict zurückgab — auch ohne tatsächliche Versionsangabe. Prüft jetzt
  `version_info.get("version")`.

## [4.0.18] - 2026-06-07

### Fixed (Second review — MEDIUM)

- **M1 — Globale urllib3-Warnungsunterdrückung dokumentiert** (`api.py`) —
  `urllib3.disable_warnings(InsecureRequestWarning)` wirkt prozessglobal und lässt sich
  nicht sauber pro Client einschränken, da proxmoxer/requests in Executor-Threads laufen
  und `warnings.catch_warnings()` nicht thread-safe ist. Verhalten unverändert, aber als
  bewusste Einschränkung kommentiert, damit es nicht fälschlich als Bug "gefixt" wird.

- **M2 — PBS-Zeitstempel waren zeitzonen-naiv** (`sensor/pbs.py`) —
  Mehrere `datetime.fromtimestamp(...)`-Aufrufe interpretierten PBS-Epoch-Werte in der
  lokalen Zeitzone des Hosts. Alle Aufrufe nutzen jetzt `tz=timezone.utc`, sodass die
  angezeigten Zeiten unabhängig von der HA-Server-Zeitzone korrekt sind.

- **M3 — PBS `server_id` aus einem Sequenzzähler abgeleitet** (`config_flow.py`) —
  `server_id = f"pbs_{len(pbs_entries) + 1}"` war race-anfällig und änderte sich, wenn
  frühere Einträge entfernt wurden, was zu kollidierenden oder wechselnden Unique-IDs
  führte. Wird jetzt deterministisch aus dem Host abgeleitet (`pbs_<host_slug>`).

- **M4 — Shutdown/Reboot-Services validierten den Node nicht** (`services.py`) —
  `confirm_shutdown_node` / `confirm_reboot_node` übernahmen den `node`-Parameter ungeprüft
  in den API-Pfad. Beide validieren den Bezeichner jetzt über `_validate_identifier`
  (`^[a-zA-Z0-9_\-\.]+$`) und lehnen leere oder unsichere Werte mit `ValueError` ab.

- **M5 — Recency-Prüfung galt nur für Einzel-Fehler** (`coordinator.py`) —
  Bei mehreren fehlgeschlagenen Backup-Jobs wurde der Zustand bedingungslos auf `error`
  gesetzt, ohne die 24h-Aktualitätsprüfung. Dadurch blieben längst veraltete Mehrfach-
  Fehler dauerhaft als `error` hängen. Die Recency-Prüfung gilt jetzt für jede Anzahl von
  Fehlern; veraltete Fehler werden zu `warning` herabgestuft.

- **M6 — Entity-Cleanup nutzte `_attr_unique_id` statt `unique_id`** (`sensor/__init__.py`) —
  Die Aufräumlogik bildete das Set aus `getattr(entity, "_attr_unique_id", None)`. Entities,
  die ihre `unique_id` über eine berechnete Property bereitstellen (ohne `_attr_unique_id`),
  wären fälschlich gelöscht worden. Nutzt jetzt die öffentliche `entity.unique_id`.

## [4.0.17] - 2026-06-07

### Fixed (Second review — HIGH)

- **H1 — PBS-Buttons schrieben rohen HA-State** (`button.py`) —
  `PBSBaseButton._update_last_action` setzte via `hass.states.async_set` direkt einen
  rohen String auf die Entity-ID des `PBSLastActionSensor`. Das umging die Entity-Registry,
  verwarf Attribute und wurde beim nächsten Coordinator-Update sofort überschrieben
  (Flackern). Helfer entfernt; die Buttons lösen nur noch `async_request_refresh()` aus,
  woraufhin `PBSLastActionSensor` seinen Zustand korrekt aus `pbs_tasks` neu berechnet.

- **H2 — Fehlendes `idx += 1` nach Memory-Result** (`coordinator.py`) —
  Nach dem Lesen von `memory_data = results[idx]` wurde `idx` nicht inkrementiert. Aktuell
  harmlos (Memory ist das letzte Result), aber inkonsistent mit jedem anderen indizierten
  Zugriff und ein latenter Bug, falls künftig ein weiteres Result angehängt wird. Korrigiert.

- **H3 — `run_sync` iterierte über Zeichen eines String-`store`-Felds** (`pbs_actions.py`) —
  `remote.get("store", [])` liefert bei PBS-Remotes mit einem einzelnen Store einen String.
  `for store in stores` iterierte dann über die einzelnen Zeichen und erzeugte fehlerhafte
  Sync-Calls. `store` wird jetzt zu einer Liste normalisiert (String → Einzel-Element).

- **H4 — Services wurden beim Entladen des letzten Eintrags nicht entfernt** (`__init__.py`) —
  `async_unload_entry` entfernte `hass.data[DOMAIN]`, ließ aber die registrierten Services
  (`backup_all`, `create_vzdump_backup`, `confirm_shutdown_node`, `confirm_reboot_node`,
  `wake_node`) bestehen. Nach Entfernen aller Einträge schlugen Service-Aufrufe fehl, weil
  der Domain-Key bereits weg war. Services werden jetzt entfernt, wenn der letzte Eintrag
  entladen wird.

## [4.0.16] - 2026-06-07

### Fixed (Second review — CRITICAL)

- **C1 — `ProxmoxPBSVerifySensor` las falschen Coordinator-Schlüssel** (`sensor/pbs.py`) —
  `_get_value` las `data.get("last_backup_time")`, ein Schlüssel den der Coordinator nie
  setzt. Der Coordinator speichert `"last_backup"` (ein Snapshot-Dict mit `"backup-time"`-
  Epoch). Dadurch war der "Backup neuer als letzter Verify → Pending"-Zweig toter Code und
  der Sensor zeigte nach jedem Verify dauerhaft "OK", auch wenn neuere, ungeprüfte Backups
  existierten. Liest jetzt `last_backup["backup-time"]`.

- **C2 — Node-Status-Fehler wurde lautlos verschluckt** (`coordinator.py`) —
  Das `asyncio.gather`-Ergebnis für `get_node_status` wurde nur per `isinstance(..., dict)`
  geprüft. Bei einer Exception fiel der Code auf `result["node"] = {"status": "unknown"}`
  zurück, ohne Warnung — alle Node-Metriken (CPU/RAM/etc.) zeigten 0, ohne dass der Fehler
  sichtbar war. Exception-Fall wird jetzt explizit erkannt und als Warnung geloggt.

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
