# Changelog

All notable changes to the Bliss Blinds integration are documented here.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.1.5] — 2026-09-16

### Fixed
- **D2 status frames were dropped** — motors reply with the response header
  `FF 01 02 03`, not the command header `FF 78 EA 41`. `parse_frame` only
  accepted the command header, so every D2 (double-motor) frame logged
  `frame not D1/D2 (dropped): status=0xD2` and the entity never updated.
  Both headers are now accepted; the body offsets are unchanged.

### Added
- **Separate `Top` and `Bottom` cover entities for two-bar blinds.** Double-bar
  geometry (DoubleRoller, DuetteTDBU, DuettePlisseTDBU, PlisseTDBU,
  PlisseDuetteTDBU) and double-servo motors (HD3800) now expose two covers, each
  driving its own bar via the app's per-bar frames — `topToPosition` (`B1 03`)
  and `bottomToPosition` (`F4 03`), matching `setPosition(F, BarType)`.
  Single-bar blinds keep the one combined cover they had.
- `protocol.TWO_BAR_TYPES` and `BlindConfig.has_two_bars`.

### Changed
- `coordinator.async_open/async_close/async_stop/async_set_position` and
  `_position_command` take an optional `bar` (TOP / BOTTOM). With no bar the
  previous combined behaviour is unchanged.
- BA24 stays a **single** cover: it also rides `moveBothBars`, but drives its
  rails as one coordinated pair, so splitting it would move them out of sync.

### Known limitation (new)
- **The protocol carries only one position per D1/D2 frame** — there is no
  per-bar position word (`handleMotorPositionResponse` decodes a single raw
  value). Both bar entities therefore display the same reported position and
  the same moving/opening status; only the *commands* are per-bar. This matches
  the app, which likewise keeps a single `position` state.

### Upgrading
- A two-bar blind that previously had one `cover.<name>_blind` entity now gets
  `cover.<name>_top` and `cover.<name>_bottom`. The old entity is left orphaned
  in the registry — delete it in Settings → Devices & Services → Entities.

---

## [0.1.4] — 2026-09-15

### Fixed
- **Every blind entity stayed "unavailable" (all models, all types)** — the
  coordinator sent `readStatus` immediately after BLE connect, but the motor
  never replied with a D1/D2 frame. Root cause: the app's connect handshake
  sends `setInternalClock()` **before** `readStatus()` (DeviceConnection.smali
  :5615–5618); the motor gates status responses on receiving a valid clock
  frame first. The6-byte GregorianCalendar time payload was missing entirely.
  Now matches the app exactly: `setInternalClock` → `readStatus`.
- **Options menu showed "500 Internal Server Error"** — HA 2026.9 base
  `OptionsFlow` has no `__init__`; `config_entry` is a read-only property set
  by the flow manager after construction. Our `__init__` was assigning it
  directly, raising `AttributeError: can't set attribute`. Removed the
  `__init__` override; the entry is now read via the property inside the step.

### Changed
- Every BLE notification is now logged as hex at DEBUG level, including a
  `"frame not D1/D2 (dropped): status=0x%02X"` line for frames that don't
  match a known status type — makes protocol-level blind spots visible in
  `home-assistant.log` without any code changes.

---

## [0.1.3] — 2026-09-15

### Fixed
- **Blinds whose entity stayed "unavailable"** (the TDBU / double-servo types
  on HD3800) — the coordinator connected with a bare `BleakClient.connect()`,
  which Home Assistant logs as *"BleakClient.connect() called without
  bleak-retry-connector"* and which connects unreliably, so no status frames
  were ever received. Connecting now goes through
  `bleak_retry_connector.establish_connection()` — the HA-supported path that
  retries (up to 4 attempts) and re-fetches the live device from HA's
  Bluetooth registry (`bleak-retry-connector` ships with HA core).

### Added
- Debug logging of every command sent and every notification received (raw
  hex) plus an explicit "frame not D1/D2 (dropped)" line — makes a dead device
  diagnosable from `home-assistant.log` alone.
- `manifest.json` `requirements` entry for `bleak-retry-connector`.

---

## [0.1.2] — 2026-09-15

### Fixed
- **Config flow would not load ("Invalid handler specified")** on HA 2026.9 —
  `coordinator.py` imported `from bleak.exceptions import BleakError`, but the
  `bleak.exceptions` module was renamed to `bleak.exc` in **bleak 3.x** (HA
  2026.9 pins bleak==3.0.2), so importing the config flow raised
  `ModuleNotFoundError`. `BleakError` is now imported from the top-level
  `bleak` package (where 3.x re-exports it).

### Added
- `async_reload_entry` — changing the blind type or `tilt_open` in the Options
  flow now applies via reload instead of requiring a manual HA restart.

### Changed
- `manifest.json` `documentation` / `issue_tracker` URLs now point to the real
  repository (`mistermej/Bliss-Blinds`); version bumped to 0.1.2.

---

## [0.1.1] — 2026-09-15

### Fixed
- **manifest.json invalid JSON** — the `codeowners` entry was unquoted
  (`[mistermej]` instead of `["@mistermej"]`), which silently stopped HA from
  loading the integration at all. Manifest now parses cleanly.

---

## [0.1.0] — 2026-09-14

Initial release. Built from scratch by reverse-engineering the official
Hunter Douglas Bliss app v3.2.0 (decompiled APK).

### Added

**Core**
- Pure protocol layer (`protocol.py`) with zero Home Assistant dependencies:
  frame builders, frame parser, motor model table, ShangriLa mapping functions.
- 43 unit tests covering all command bytes, encode/decode round-trips, D1/D2
  response parsing (including battery, operating status, Nordic error codes),
  position bytes, tilt frames, and ShangriLa helpers.

**Config Flow**
- Automatic device discovery via BLE name matching (`^HD\d{4}$`).
- Device picker showing all discovered motors with name + MAC address.
- Blind type selection dropdown: all 27 types from the app, default Roller.
- Options flow to correct blind type or tune ShangriLa `tilt_open` later.

**Cover Entity**
- Position (0–100), open / close / stop / set-position.
- Tilt support for tilting blind types (Venetian, VerticalVenetian, Curtain,
  ShangriLa, etc.) with correct max-angle per type (90 for ShangriLa, 180 for
  Venetian/VV/Curtain, 0 for non-tilting types).
- Opening/closing indicators from BLE operating status.
- Multi-bar commands for BA24 (two-bar complement encoding) and DoubleRoller
  (HD3800 double-servo moveBothBars).

**Sensors**
- Battery sensor: coarse 4-state level (normal / low / none / unknown) from
  BLE flags — honest about protocol limitation (no percentage exists).
- Nordic error sensor (HD3600 / HD3900 only, off by default): exposes the
  motor's error code as a diagnostic entity.

**Protocol Coverage**
- Position encode/decode round-trips with the app's scene-path convention
  (normal: `raw = (1−f)×range`; inverse: `raw = f×range`).
- HD0100 range-100 special case (single-byte position).
- Direction inversion for HD1300 + bottom-up types, and HD3600 + BA24.
- ShangriLa tilt-to-position mapping (configurable `tilt_open`).
- Nordic error normalization (0→0, 1-13→same, else→10).
- Heartbeat frame recognition and silent discard.

**BLE Connection**
- BleakClient lifecycle with serialized writes (≥25ms gap, matching the app).
- With-response writes (matching DeviceConnection.sendWriteCommand).
- Automatic reconnect loop (15s interval).
- Periodic state poll (60s readStatus).
- State update callbacks for entity notifications.

**Manifest / Metadata**
- `integration_type: device`, `iot_class: local_polling`.
- Bluetooth auto-discovery matcher.
- HACS-compatible `hacs.json` (floor: HA 2026.9.0).
- README with install instructions, entity table, protocol notes, and honest
  limitations.

### Known Limitations

- **Battery is 4-state only** — the protocol does not expose a percentage.
- **No firmware update support** — the app's SMP/mcumgr path is out of scope.
- **No timer/schedule support** — cloud-side features not implemented.
- **ShangriLa blinds** need the `tilt_open` option tuned for correct behavior;
  defaults to 0.0 (treated like a normal motor).
- Manifest `codeowners`, `documentation`, and `issue_tracker` are placeholders.

### Credits

Every byte, offset, and formula is cited to the app's smali output. See
`protocol.py` docstrings for the specific `file:line` sources and
`LOGBOOK.md` for the full development history.
