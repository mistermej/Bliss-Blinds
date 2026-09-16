# Bliss Blinds (Hunter Douglas)

Home Assistant integration for **Hunter Douglas Bliss** motorized blinds over
Bluetooth Low Energy. One `cover` (+ optional tilt) and a battery sensor per
motor — or **two covers** (`Top` / `Bottom`) for two-bar blinds.

Built **from scratch** by reverse-engineering the official **Bliss app
v3.2.0** (decompiled APK). Every byte, offset, and formula is cited to the
app's smali output in this repo's notes — nothing is guessed from memory.

> **Honest limitations (protocol, not this integration):**
> * Battery is only a coarse **4‑state** level (`normal` / `low` / `none` /
>   `unknown`). There is **no percentage** anywhere in the protocol.
> * `readStatus` reports the **position and tilt the motor thinks it is at**;
>   the app works the same way.
> * Multi-bar types (BA24, double-servo HD3800, DoubleRoller) use their app
>   commands. ShangriLa blinds need the `tilt_open` option to behave exactly
>   like the cloud app (default 0.0 = treated like a normal motor).

---

## Install

Copy the `custom_components/bliss_blinds` folder into your HA
`config/custom_components/` directory, then restart Home Assistant.

```
config/
└── custom_components/
    └── bliss_blinds/
        ├── __init__.py
        ├── manifest.json
        ├── config_flow.py
        ├── const.py
        ├── protocol.py
        ├── coordinator.py
        ├── cover.py
        ├── sensor.py
        └── strings.json
```

Then: **Settings → Devices & Services → Add Integration → “Bliss Blinds”**.
The flow lists every discovered motor whose BLE name matches `HDxxxx` (the
name *is* the motor model), then asks for the **blind type** — a dropdown of
the full list from the app, default **Roller**.

No login or password is ever sent to the motor. The motor does not lock
movement behind a password, and none is needed.

---

## Entities

| Entity | Description |
|---|---|
| `cover.<name>_blind` | Position `0–100`, open / close / stop / set position, and tilt for tilting blind types. Single-bar blinds only. |
| `cover.<name>_top` | **Two-bar blinds only** — drives the top bar (`topToPosition`). Carries tilt where the type has one. |
| `cover.<name>_bottom` | **Two-bar blinds only** — drives the bottom bar (`bottomToPosition`). |
| `sensor.<name>_battery` | Coarse 4-state battery (diagnostic). |
| `sensor.<name>_nordic_error` | Nordic motor error code for **HD3600 / HD3900** (diagnostic, off by default). |

A blind gets two covers when its geometry is two-bar — **DoubleRoller** or any
of the four **TDBU** (top-down/bottom-up) types — or when the motor is a
double-servo **HD3800**. BA24 keeps a single cover: it drives its two rails as
one coordinated pair.

> **Protocol limit:** a D1/D2 status frame carries only **one** position, so both
> bar entities report the same position and moving/opening state. The *commands*
> are per-bar and independent; the *readout* is not. This matches the app, which
> keeps a single position value for every blind type.

Autodetected from the BLE name: motor **range** (HD0100 = 100, all others =
1000), **generation**, **Nordic** support, direction inversion (HD1300 +
bottom-up, HD3600 + BA24), double-servo (HD3800), and tilt capability
(second-generation Venetian/VerticalVenetian & co).

The only manual choice is the **blind type**, because the motor never reports
it — the app asks for it at pairing, and so do we.

---

## Commands / protocol notes

* Service: `00010203-0405-0607-0809-0a0b0c0d1910`
* Command (write): `00010405-...1910` · Response (notify): `00010304-...1910`
* No checksum, no sequence number — raw byte frames.
* Writes go out serialized ≥ 25 ms apart (the app's `ConnectionManager`).
* A `readStatus` frame (`FF 78 EA 41 D1 03 01`) is sent on connect and then
  every 60 s; the D1/D2 notify responses push state in between.

Frame encoding (`protocol.py`) implements exactly the app's
`BlissCommandsKt.getMoveToCommand` (scenes/position path), which round-trips
with the app's `handleMotorPositionResponse` decode:

| Motor | encode (move to fraction f) | decode (fraction from raw r) |
|---|---|---|
| normal | `raw = (1 − f) · range` | `f = 1 − r / range` |
| inverse (HD1300+bottom-up, HD3600+BA24) | `raw = f · range` | `f = r / range` |
| ShangriLa | via `tilt_open` mapping | `f = 1 − rel(r/range)` |

---

## Develop

```
cd bliss_blinds
python -m unittest discover -s tests
```

The protocol module has **no HA imports** and is fully unit-tested (52 tests)
against known frame bytes. Note this README's command tables reference the
decompiled app; see `protocol.py` docstrings for the `file:line` sources.

---

## TODO before publishing (metadata placeholders)

* `manifest.json` → set `codeowners`, `documentation`, `issue_tracker` to your
  real values.
* Decide the HACS homeassistant floor (`hacs.json` now says 2026.9.0).