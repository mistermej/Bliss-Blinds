# Bliss Blinds — Development Logbook

A chronological record of every decision, discovery, bug, and code change made
during the build of this integration. Written so future sessions of Claude (or
anyone else) can look back and understand *what was done, why, and how*.

---

## 2026-09-13: Project Genesis

### Why this project exists

The user had prior integrations `bliss2ha` and `tuiss2ha` (at `C:\omniroute\`)
but wanted a clean, from-scratch build grounded solely in the decompiled
official Hunter Douglas Bliss app v3.2.0 at `C:\omniroute\blissapp\decompiled\`.
The old integrations were deliberately forgotten — every protocol fact in this
build is extracted from smali, not from memory.

### User decisions (confirmed via AskUserQuestion)

| Decision | Choice |
|---|---|
| HA version | 2026.9 / current |
| Entity scope | Covers (+ optional tilt) + battery sensor |
| Blind type | Full 27-type dropdown, default Roller |
| Discovery | Auto via BLE name `^HD\d{4}$` |
| Login/password | **None** — motor movement is not gated on login |
| Write destination | Self-contained source folder `C:\omniroute\bliss_blinds\` |

### First smali reads — building ground truth

I navigated to `C:\omniroute\blissapp\decompiled\` and read every relevant file
in the APK's decompiled source. Key files and what they yielded:

| File | What it contains |
|---|---|
| `presentation/util/BleCharacteristics.smali` | GATT UUIDs (service/command/response) |
| `scan/ScanManager.smali` | BLE name regex `^HD\d{4}$` for discovery |
| `models/MotorTypeKt.smali` | Motor properties: range, generation, Nordic, brand |
| `models/BlindTypeKt.smali` | All 27 blind types, maxTiltAngle table, hasTilt, isBottomUp |
| `models/BlindKt.smali` | isMotorDirectionInverse, isDoubleServo, hasTilt logic |
| `models/BlissCommandsKt.smali` | Frame assembly: getMoveToCommand, setPositionAndTiltAngle, etc. |
| `models/BlissCommands.smali` | Command byte constants (clinit) |
| `workmanagers/DeviceConnection.smali` | Response parsing: handleMotorPositionResponse, D1/D2 decode |
| `workmanagers/NordicMotorStatusParser.smali` | Nordic error code extraction |

---

## 2026-09-13/14: Protocol Extraction

### GATT UUIDs (from `BleCharacteristics.smali` lines 63/84/105)
```
Service:   00010203-0405-0607-0809-0a0b0c0d1910
Command:   00010405-0405-0607-0809-0a0b0c0d1910  (write)
Response:  00010304-0405-0607-0809-0a0b0c0d1910  (notify)
```

### Command bytes (from `BlissCommands.smali` clinit; header `FF 78 EA 41`)
| Name | Bytes |
|---|---|
| heartbeat | `FF 01 01 01 01 01 01` |
| readStatus | `FF 78 EA 41 D1 03 01` |
| gotoPrefix (top) | `FF 78 EA 41 BF 03` |
| topToPosition (double-servo) | `FF 78 EA 41 B1 03` |
| bottomToPosition | `FF 78 EA 41 F4 03` |
| tiltToAngle | `FF 78 EA 41 F9 06` |
| moveBothBars | `FF 78 EA 41 FE 03` |
| rollerStop | `FF 78 EA 41 5F 03 01` |
| rollerUp / rollerDown (jog) | `FF 78 EA 41 CF 03 01` / `1F 03 01` |

No checksum, no sequence number. Frames are raw bytes.

### Motor model table (from `MotorTypeKt.smali`)
- **HD0100** is the only motor with range=100; all others = 1000.
- First-gen: HD0100, HD0101, HD0200, HD0300, HD0700, HD0800, HD1200, UNKNOWN.
  - **HD0400 is second-gen** (this was initially misclassified; caught during testing).
- Nordic motors: HD3600, HD3700, HD3900 (but HD3700 does NOT have Nordic error parsing —
  this is a common misconception; NordicMotorStatusParser only handles HD3600 and HD3900).
- isDoubleServo = HD3800 (default branch; product ID is cloud data).

### Position encoding (from `BlissCommandsKt.smali` getMoveToCommand lines 1102–1136)
The encode/decode convention was the trickiest part:
- **Scene path** (`getMoveToCommand`): normal motor raw = round((1−f)×range); inverse raw = round(f×range).
- **App slider path** (`setPosition(F,BarType)`): always uses f×range, but this is the *immediate*
  path and does NOT round-trip with the read decode. The scene path does round-trip.
- **Decision**: HA uses the scene-path encode (self-consistent with `handleMotorPositionResponse` decode).
  Verified by round-trip unit tests.

### Tilt encoding (from `BlissCommandsKt.smali` setPositionAndTiltAngle)
- `tiltToAngle + shortLE(raw_pos) + shortLE(tilt_angle)`
- `raw_pos` = round(round(f×100)/100×range) — the rounded-2dp trick.
- Tilt angle is clamped to maxTiltAngle for the blind type.

### BA24 encode (from `BlissCommandsKt.smali` lines 1195–1248)
`moveBothBars + shortLE(range−round(f×range)) + shortLE(range)`
The two bars get different targets: top bar = complement, bottom bar = full range.

### D1 response parse (from `DeviceConnection.smali` handleMotorPositionResponse lines 4929–5059)
- After header `FF 78 EA 41`, status byte = `0xD1`.
- body[0]=status, body[1]=flags, body[2]=pos byte (range 100), body[3:5]=pos short (range 1000),
  body[7]=tilt.
- Flags byte breakdown: bit 0x01=reverse, 0x02=hasLimits, 0x04=remoteLink,
  bits 0x18=battery, bits 0x60>>5=operating status.

### D2 response parse
- Same as D1 but tilt byte is at body[5] instead of body[7].
- Triggered by status byte 0xD2.

### Nordic error (from `NordicMotorStatusParser.smali`)
- HD3600: error byte at body[6], needs length≥7.
- HD3900: error byte at body[5], needs length≥6.
- HD3700: NOT Nordic despite the similar model number.
- Normalize: 0→0, 1-13→same, else→10.

### getMaxTiltAngle table (from `BlindTypeKt.smali` lines 77–151)
**CRITICAL FIX**: The initial summary (inherited from earlier context) had the table
WRONG. Re-reading the smali showed the opposite:
- ShangriLa = 90
- {Venetian, VerticalVenetian, VVRS/LS/SS/CS, CurtainLS/RS/SS} = 180
- **Everything else = 0** (including Roller, Duette, Plisse, BA24, etc.)

### ShangriLa mappings (from `BlindKt.smali` mapPositionTo* functions)
All depend on configurable `tilt_open` (default 0.0):
- `mapPositionToRelativeShangrilaPosition`: rel = (p − to) / (1 − to). Raises ValueError if to==1.0.
- `mapPositionToShangrilaTiltAngle`: angle = int(maxTilt × (1 − p/to)). Returns 0 when to==0 or p≥to.
- `mapRelativeShangrilaPositionToAbsolutePosition`: abs = rel × (1 − to) + to.
- `shangrilaTiltAngleToPosition`: pos = to × (maxTilt − angle) / maxTilt.

---

## 2026-09-14: Code Generation

### Files created (in order)

1. **`tests/test_protocol.py`** — Written first to anchor protocol facts. Initially
   used `from custom_components.bliss_blinds.protocol import ...` which broke tests
   (ModuleNotFoundError: homeassistant). Fixed by loading `protocol.py` standalone
   via `importlib.util.spec_from_file_location`.

2. **`protocol.py`** — The core: pure Python, zero HA imports. Motor model table,
   BlindTypes enum (27 entries), frame builders, frame parser, ShangriLa mapping
   functions. This is the only file that touches raw bytes.

3. **`const.py`** — Domain, platforms, UUIDs, timeout constants, re-exports from protocol.

4. **`coordinator.py`** — The heart: owns the BleakClient, drives notifications,
   reconnect loop (15s), poll loop (60s), serialized write queue (≥25ms gap).
   Plain coordinator (NOT DataUpdateCoordinator) because state is push-driven.
   Initially lacked `DOMAIN`/`MANUFACTURER` imports in `device_info` — fixed.

5. **`__init__.py`** — Setup creates coordinator, starts it, stores in `hass.data[DOMAIN]`.
   Added `async_reload_entry` during review phase (options changes weren't
   reloading the coordinator — blind type changes wouldn't take effect until
   manual HA restart).

6. **`config_flow.py`** — Two-step: device picker (auto-discovered `HDxxxx`) then
   blind-type dropdown (27 types, default Roller). Options flow for correcting
   blind type or setting `tilt_open`. Added stale-device guard (if motor
   disappears between listing and selection, `next()` previously raised
   StopIteration — now aborts cleanly).

7. **`cover.py`** — CoverEntity with position, tilt, open/close/stop.
   `_moving_toward` logic: normal motor → opening=MOVING_DOWN (raw decreases),
   inverse → opening=MOVING_UP (raw increases). Tilt feature flagged by
   `has_tilt_angle` or `is_shangrila`.

8. **`sensor.py`** — Battery (4-state enum, diagnostic) + Nordic error
   (HD3600/3900 only, off by default). Battery icon varies by state.

9. **`manifest.json`** — `integration_type: device`, bluetooth matcher
   `{"connectable": true, "local_name": "HD"}`. Initially had invalid keys
   `domains` and `after_dependencies` (not in HA manifest schema) — removed.

10. **`strings.json`** — Flow labels, abort reasons, step descriptions.

11. **`hacs.json`** — `homeassistant: "2026.9.0"`.

12. **`README.md`** — Install, entities table, protocol notes, honest limitations.

---

## Bugs Found and Fixed

| Bug | How discovered | Fix |
|---|---|---|
| `getMaxTiltAngle` table was backwards (roller=180, venetian=0) | Re-read `BlindTypeKt.smali` lines 77–151 | Corrected to ShangriLa=90, Venetian/VV±/Curtain=180, rest=0 |
| HD0400 incorrectly classified as first-gen | Test `test_generation` failed for HD0400 | Verified in `MotorTypeKt.smali` — HD0400 is second-gen. Fixed test expectation. |
| D2 tilt test used BA24 (no tilt capability) | Test `test_tilt_byte_at_5` failed | Changed to `BlindConfig("HD3800", BlindTypes.VENETIAN)` which has tilt |
| Float precision `0.6000000000000001 != 0.6` | ShangriLa relative position test | Changed exact assert to `assertAlmostEqual` |
| `ModuleNotFoundError: homeassistant` when tests imported package `__init__` | Running `python -m unittest` | Load `protocol.py` standalone via importlib; never touch package `__init__` |
| Invalid manifest keys `domains` and `after_dependencies` | Manual review against HA manifest schema | Removed both keys |
| Junk lines in const.py (`NORTHERN_LIGHTS = "claude"`) and cover.py (`_SETTLE = 0.1`) | Manual review | Removed |
| `DOMAIN`/`MANUFACTURER` not imported in coordinator.py | Lint-style review after writing cover/sensor | Added to const import block |
| Options changes not reloading coordinator | Review: BlindConfig built once at coordinator init | Added `async_reload_entry` to `__init__.py` |
| `next()` crash on stale device selection | Review: device could vanish between listing and selection | Added `next(..., None)` guard + abort |
| Coordinator `_connect_lock` never released on inner return | Manual review of async_ensure_connected | Added explicit `return False` before lock release was wrong; restructured to ensure lock is properly released via `async with` |
| **Manifest JSON invalid: `"codeowners": [mistermej]`** | User copied folder to HA, integration wouldn't appear | User had edited the placeholder `codeowners` to their GitHub name but left it **unquoted**, breaking the entire manifest's JSON. HA silently rejects whole-file invalid manifests. Fixed to `["@mistermej"]` (quoted handle format). **Lesson: every manifest edit must be valid JSON — HA never logs a targeted message for a broken manifest.** |
| **Config flow won't load: "Invalid handler specified" — `bleak.exceptions` is gone in bleak 3.x** | After manifest fix, user saw "Config flow could not be loaded: {\"message\":\"Invalid handler specified\"}" | HA 2026.9 pins **bleak==3.0.2**, and bleak 3.0 **renamed `bleak.exceptions` → `bleak.exc`**. Our `from bleak.exceptions import BleakError` raised `ModuleNotFoundError` the instant HA imported `config_flow.py` (package `__init__` → coordinator chain), and HA surfaces any import failure in the flow chain as the generic "Invalid handler specified". Fixed to `from bleak import BleakClient, BleakError` (BleakError is re-exported at the top level in 3.x). Also verified the rest of our bleak API against v3.0.2: `BleakClient(device, timeout=…)` ✓, `write_gatt_char(char, data, response=True)` ✓, `is_connected` property ✓, `start_notify`/`stop_notify`/`connect`/`disconnect` ✓. **Lessons: (1) HA silently collapses a config-flow import error into "Invalid handler specified" — the real traceback is only in home-assistant.log; (2) when targeting current HA, verify third-party API names against HA's pinned dependency versions (package_constraints.txt).** |
| **TDBU blind types (PlisseTDBU/DuetteTDBU/DuettePlisseTDBU/PlisseDuetteTDBU) "don't do anything" — cover never moves, battery stuck Unknown, entity unavailable** | Live test: selecting a TDBU type for an HD3800 produced a dead cover + dead battery; HA log showed `BleakClient.connect() called without bleak-retry-connector` | Two-part investigation. **(1) Protocol check:** TDBU needs **no** type-specific handling. `BlindKt.isTDBU` (`BlindKt.smali:785`) is used *only* in the advanced-settings UI (`AdvancedSettingsScreenKt.smali:6515`), never for movement or parsing. Movement = the standard double-servo path: `setPosition(FF)` (`DeviceConnection.smali:8531`) builds `moveBothBars + short(round(f·range)) + short(...)` where callers pass `f = 1 − displayValue/100` (`MultiConnectViewModel.smali:5354–5385`), i.e. `raw = round((1−d)·range)` — byte-identical to our `move_both_bars_command`. readStatus stays `FF 78 EA 41 D1 03 01` (`BlissCommands.smali:1464`). The reply is D1 or D2 and our `parse_frame` already matches the app's indices (`handleMotorPositionResponse` `DeviceConnection.smali:4969`; D2 tilt at body[5] `:2850`). **(2) Root cause:** the coordinator connected with a bare `BleakClient.connect()`. On HA that bypasses `bleak_retry_connector.establish_connection()` (the supported path, ships with HA core as `==4.7.1`), which warns and connects unreliably → no notify ever arrives → `available` stays False → entity shows "unavailable". **Fix:** connect via `establish_connection(BleakClient, device, address, timeout=…, ble_device_callback=…)` (retries up to 4, re-fetches the live registry device). Also added per-frame debug logging (`send:`/`notify:` hex ⇒ distinguishes "motor never replies" from "frame unparsed"). Signed off against the actual pinned wheels (bleak 3.0.2 accepts the `establish_connection` kwargs; `BleakConnectionError` subclasses `BleakError`). |

---

## 2026-09-15: Live-Test Fix — connect reliability (0.1.3)

User's first HACS live test surfaced two things:

1. **Auto-recognition question** — answered: no. The BLE advert name is the
   *motor model* (`^HD\d{4}$`); the *blind type* is never transmitted over
   BLE (same as the app — the user picks it). The dropdown stays.
2. **TDBU blinds appeared dead** — see the bug row above. Verdict: protocol is
   correct for TDBU (double-servo HD3800, moveBothBars, D1/D2 parse — all
   cross-checked to smali). The real failure was the **bare `BleakClient.connect()`**
   path, which HA flags with *"BleakClient.connect() called without
   bleak-retry-connector"* and which connects unreliably.

Changes in 0.1.3:
- `coordinator.py`: connect through `bleak_retry_connector.establish_connection()`
  with a `ble_device_callback` that re-fetches the live registry device;
  `max_attempts` default (4) gives retry+backoff the bare connect lacked.
- `coordinator.py`: raw `send:` / `notify:` hex at DEBUG plus an explicit
  "frame not D1/D2 (dropped)" line, so a future dead-device report can be
  diagnosed from the log alone.
- `manifest.json`: `requirements: ["bleak-retry-connector>=4.7"]` (already
  present in HA core; declared for correctness), version → 0.1.3.

Diagnostics note for future sessions: `available`/entity state only changes
after a decoded D1/D2 frame (`_update_state`). Persistent "unavailable" ⇒ no
frame ever parsed ⇒ check `send:`/`notify:` in debug logs to split
connect-failure vs unrecognized-frame.

---

## Version-Snapshot Workflow (added 2026-09-15)

The user keeps **release snapshots** in `C:\omniroute\bliss_blinds_versions\<version>\`
— a flat copy of the integration files (same layout as HACS repos drop into
`config/custom_components/`), plus a `brand/` folder with their icons
(icon.png + logo.png). Folders `0.1.1` and `0.1.2` already existed; both are
byte-identical to the matching manifest version of the source.

The project root now has **`build_version.py`** so every future version bump
snapshots itself automatically:

| Command | Effect |
|---|---|
| `python build_version.py` | Snapshot at the current `manifest.json` version (no bump). |
| `python build_version.py 0.1.3` | Bump `manifest.json` to 0.1.3 AND snapshot `0.1.3/`. |
| `python build_version.py --next` | Auto-bump the highest existing version folder (0.1.2 → 0.1.3) and snapshot. |

Notes:
- Snapshot = the 9 release files (`__init__.py`, `config_flow.py`, `const.py`,
  `coordinator.py`, `cover.py`, `manifest.json`, `protocol.py`, `sensor.py`,
  `strings.json`) + `brand/` (source wins, else carried forward).
- `__pycache__` and dev docs are never copied.
- The script stays in lock-step with `manifest.json` version.

## Design Decisions

### Why plain coordinator instead of DataUpdateCoordinator?
State is push-driven via BLE notifications. The coordinator owns the BleakClient
directly and notifies entities when a new frame arrives. A 60s poll acts as
drift correction and keep-alive, not as the primary state source.
DataUpdateCoordinator's poll-centric model doesn't fit this pattern.

### Why scene-path encode (not slider-path encode)?
The app has two encode paths: immediate slider and scene. The scene path
(`getMoveToCommand`) produces bytes that decode correctly via
`handleMotorPositionResponse`. The slider path (`setPosition(F,BarType)`)
uses a different convention that does NOT round-trip with the read decode.
For HA, where set_position(70) should result in position reporting back as 70,
the scene path is the correct choice. Verified by round-trip unit tests.

### Why no login/password?
The user confirmed that movement commands work without any authentication.
The app allows movement before pairing a password. The user only logs into
the cloud account for remote control, not for local BLE commands.
Therefore no login frames are ever sent.

### Why WRITE_GAP = 25ms?
The app's `ConnectionManager.sendNext` throttles writes to ≥25ms apart.
This prevents the motor's BLE stack from dropping frames. Implemented as
an asyncio Lock + sleep(WRITE_GAP) after each write.

### Why BD0008 as BA24 tilt bar?
The app sends `BD 0008` as the bar identifier in `setPositionAndTiltAngle`
for BA24. This was extracted directly from `BlissCommandsKt.smali`.

---

## Key Constants Reference

| Constant | Value | Source |
|---|---|---|
| SERVICE_CHARACTERISTIC_UUID | `00010203-0405-0607-0809-0a0b0c0d1910` | BleCharacteristics.smali:63 |
| COMMAND_CHARACTERISTIC_UUID | `00010405-0405-0607-0809-0a0b0c0d1910` | BleCharacteristics.smali:84 |
| RESPONSE_CHARACTERISTIC_UUID | `00010304-0405-0607-0809-0a0b0c0d1910` | BleCharacteristics.smali:105 |
| HEADER | `FF 78 EA 41` | BlissCommands.smali clinit |
| WRITE_GAP | 25ms | DeviceConnection / ConnectionManager |
| POLL_INTERVAL | 60s | DeviceConnection readStatus interval |
| RECONNECT_INTERVAL | 15s | Reasonable reconnect backoff |
| CONNECT_TIMEOUT | 15s | BleakClient timeout |

---

## File sizes (lines, approximate at completion)

| File | Lines | Notes |
|---|---|---|
| protocol.py | ~450 | The largest file; contains all protocol logic |
| coordinator.py | ~290 | BLE lifecycle + command API |
| config_flow.py | ~160 | Config + options flow |
| cover.py | ~130 | CoverEntity |
| sensor.py | ~110 | Battery + Nordic error sensors |
| const.py | ~50 | Constants + re-exports |
| __init__.py | ~45 | Setup/unload/reload |
| test_protocol.py | ~360 | 43 unit tests |

---

*End of logbook. Last updated: 2026-09-14.*
