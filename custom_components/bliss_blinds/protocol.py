"""Bliss motor BLE protocol — pure builders and parsers.

Ground truth is the decompiled official Bliss app v3.2.0 APK
(``Bliss+Smart+Blinds_3.2.0_APKPure.apk``). Every constant, byte offset
and formula carries a ``<file>:<line>`` reference to that app's smali
output under ``smali_classes5\\nl\\hunterdouglas\\bliss\\``:

  presentation/util/BleCharacteristics.smali   GATT UUIDs (63, 84, 105)
  models/BlissCommands.smali (clinit)          raw command byte constants
  models/BlissCommandsKt.smali                 frame assembly / position bytes
  models/MotorType.smali, MotorTypeKt.smali    motor model table (range/gen/nordic)
  models/BlindType.smali, BlindTypeKt.smali    blind-type properties
  models/Blind.smali, BlindKt.smali            tilt capability, direction, ShangriLa
  presentation/workmanagers/DeviceConnection.smali  response decode (D1/D2)

This module is pure Python and has **no** Home Assistant imports so it can
be unit-tested standalone.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from typing import Optional

# --------------------------------------------------------------------------- #
# GATT                                                                         #
# --------------------------------------------------------------------------- #
# BleCharacteristics.smali:63 (service), 84 (Command), 105 (Response)
SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
COMMAND_CHARACTERISTIC_UUID = "00010405-0405-0607-0809-0a0b0c0d1910"
RESPONSE_CHARACTERISTIC_UUID = "00010304-0405-0607-0809-0a0b0c0d1910"

# --------------------------------------------------------------------------- #
# Discovery                                                                    #
# --------------------------------------------------------------------------- #
# ScanManager.smali blissMacRegex — motors advertise their model as an
# HD-prefixed 4-digit name (e.g. "HD3600").
DISCOVERY_NAME_RE = re.compile(r"^HD\d{4}$")


# --------------------------------------------------------------------------- #
# Raw command bytes (BlissCommands.smali <clinit>)                             #
# --------------------------------------------------------------------------- #
HEADER = b"\xff\x78\xea\x41"                    # BlissCommands.HEADER
HEARTBEAT = b"\xff\x01\x01\x01\x01\x01\x01"     # BlissCommands.heartbeat
READ_STATUS = HEADER + b"\xd1\x03\x01"          # BlissCommands.readStatus
GOTO_PREFIX = HEADER + b"\xbf\x03"              # gotoPrefix (top bar, single servo)
TOP_TO_POSITION_PREFIX = HEADER + b"\xb1\x03"   # topToPosition (double-servo top)
BOTTOM_TO_POSITION_PREFIX = HEADER + b"\xf4\x03"  # bottomToPosition
TILT_TO_ANGLE_PREFIX = HEADER + b"\xf9\x06"     # tiltToAngle
MOVE_BOTH_BARS_PREFIX = HEADER + b"\xfe\x03"    # moveBothBars
ROLLER_STOP = HEADER + b"\x5f\x03\x01"          # rollerStop
ROLLER_UP = HEADER + b"\xcf\x03\x01"            # rollerUp (jog only)
ROLLER_DOWN = HEADER + b"\x1f\x03\x01"          # rollerDown (jog only)

STATUS_D1 = 0xD1   # single-motor response  (DeviceConnection.smali:2129 "-0x2f")
STATUS_D2 = 0xD2   # double-motor response


def _round_half_up(value: float) -> int:
    """Kotlin ``Math.round`` = ``floor(x + 0.5)`` (BlissCommandsKt position math)."""
    return int(math.floor(value + 0.5))


def short_le(value: int) -> bytes:
    """Kotlin ``ByteUtils.getBytes(Short)`` — 2-byte little-endian."""
    return struct.pack("<H", value & 0xFFFF)


# --------------------------------------------------------------------------- #
# Motor models — MotorType.smali enum order + MotorTypeKt.smali maps           #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MotorModel:
    """Properties the app derives per MotorType (range/generation/Nordic)."""

    name: str
    range: int = 1000
    generation: str = "second"          # "first" | "second"
    nordic: bool = False                # NordicMotorStatusParser support (HD36/37/3900)

    @property
    def is_first_gen(self) -> bool:
        return self.generation == "first"

    @property
    def is_second_gen(self) -> bool:
        return self.generation == "second"


def _model(
    name: str,
    range_: int = 1000,
    generation: str = "second",
    nordic: bool = False,
) -> MotorModel:
    return MotorModel(name, range_, generation, nordic)


# MotorTypeKt.smali getRange / getGeneration / isNordicMotor — values from the
# verified WhenMappings table. HD0100 is the only range-100 motor; everything
# else (including the UNKNOWN fallback) is range 1000.
MOTOR_MODELS: dict[str, MotorModel] = {
    "HD0100": _model("HD0100", range_=100, generation="first"),
    "HD0101": _model("HD0101", generation="first"),
    "HD0200": _model("HD0200", generation="first"),
    "HD0300": _model("HD0300", generation="first"),
    "HD0400": _model("HD0400"),
    "HD0401": _model("HD0401"),
    "HD0500": _model("HD0500"),
    "HD0501": _model("HD0501"),
    "HD0700": _model("HD0700", generation="first"),
    "HD0800": _model("HD0800", generation="first"),
    "HD1000": _model("HD1000"),
    "HD1001": _model("HD1001"),
    "HD1200": _model("HD1200", generation="first"),
    "HD1300": _model("HD1300"),
    "HD3600": _model("HD3600", nordic=True),
    "HD3700": _model("HD3700", nordic=True),
    "HD3800": _model("HD3800"),
    "HD3900": _model("HD3900", nordic=True),
    # Undiscoverable via ^HD, but kept so find_motor_model never falls back weirdly.
    "TS2600": _model("TS2600"),
    "TS2900": _model("TS2900", generation="first"),
    "TS3000": _model("TS3000", generation="first"),
    "TS5000": _model("TS5000", generation="first"),
    "TS5001": _model("TS5001"),
    "TS5100": _model("TS5100"),
    "TS5101": _model("TS5101"),
    "TS5200": _model("TS5200"),
    "TS5300": _model("TS5300"),
    "TS5500": _model("TS5500"),
    "UNKNOWN": _model("UNKNOWN", generation="first"),
}


def find_motor_model(name: Optional[str]) -> MotorModel:
    """BLE-name → MotorModel, as the app's ``MotorType$Companion.findByName``."""
    if not name:
        return MOTOR_MODELS["UNKNOWN"]
    return MOTOR_MODELS.get(name.strip().upper(), MOTOR_MODELS["UNKNOWN"])


# --------------------------------------------------------------------------- #
# Blind types — BlindType.smali (27 entries) + BlindTypeKt.smali / BlindKt    #
# --------------------------------------------------------------------------- #
class BlindTypes:
    """Names exactly as in BlindType.smali."""

    BA24 = "BA24"
    CURTAIN_LS = "CurtainLS"
    CURTAIN_RS = "CurtainRS"
    CURTAIN_SS = "CurtainSS"
    DOUBLE_ROLLER = "DoubleRoller"
    DUETTE = "Duette"
    DUETTE_BOTTOM_UP = "DuetteBottomUp"
    DUETTE_PLISSE_TDBU = "DuettePlisseTDBU"
    DUETTE_SLOPED_40 = "DuetteSloped40"
    DUETTE_SLOPED_70 = "DuetteSloped70"
    DUETTE_TDBU = "DuetteTDBU"
    DUETTE_TOP_DOWN = "DuetteTopDown"
    PLISSE = "Plisse"
    PLISSE_BOTTOM_UP = "PlisseBottomUp"
    PLISSE_DUETTE_TDBU = "PlisseDuetteTDBU"
    PLISSE_TDBU = "PlisseTDBU"
    PLISSE_TOP_DOWN = "PlisseTopDown"
    ROLLER = "Roller"
    ROMAN = "Roman"
    SHANGRI_LA = "ShangriLa"
    VENETIAN = "Venetian"
    VERTICAL_VENETIAN = "VerticalVenetian"
    VERTICAL_VENETIAN_CS = "VerticalVenetianCS"
    VERTICAL_VENETIAN_LS = "VerticalVenetianLS"
    VERTICAL_VENETIAN_RS = "VerticalVenetianRS"
    VERTICAL_VENETIAN_SS = "VerticalVenetianSS"
    WOOD_50MM = "Wood50mm"


# Config-flow / options dropdown order — same order as BlindType.smali.
ALL_BLIND_TYPES: tuple[str, ...] = (
    BlindTypes.BA24,
    BlindTypes.CURTAIN_LS,
    BlindTypes.CURTAIN_RS,
    BlindTypes.CURTAIN_SS,
    BlindTypes.DOUBLE_ROLLER,
    BlindTypes.DUETTE,
    BlindTypes.DUETTE_BOTTOM_UP,
    BlindTypes.DUETTE_PLISSE_TDBU,
    BlindTypes.DUETTE_SLOPED_40,
    BlindTypes.DUETTE_SLOPED_70,
    BlindTypes.DUETTE_TDBU,
    BlindTypes.DUETTE_TOP_DOWN,
    BlindTypes.PLISSE,
    BlindTypes.PLISSE_BOTTOM_UP,
    BlindTypes.PLISSE_DUETTE_TDBU,
    BlindTypes.PLISSE_TDBU,
    BlindTypes.PLISSE_TOP_DOWN,
    BlindTypes.ROLLER,
    BlindTypes.ROMAN,
    BlindTypes.SHANGRI_LA,
    BlindTypes.VENETIAN,
    BlindTypes.VERTICAL_VENETIAN,
    BlindTypes.VERTICAL_VENETIAN_CS,
    BlindTypes.VERTICAL_VENETIAN_LS,
    BlindTypes.VERTICAL_VENETIAN_RS,
    BlindTypes.VERTICAL_VENETIAN_SS,
    BlindTypes.WOOD_50MM,
)

# BlindTypeKt.smali getMaxTiltAngle (77-151), verified verbatim:
#   ShangriLa → 90 (0x5a)
#   Venetian, VerticalVenetian, VV±, CurtainLS/RS/SS → 180 (0xb4)  [cond_2]
#   every other type → 0 (cond_1)
# So "no tilt axis" is 0, not the default.
MAX_TILT_ANGLE: dict[str, int] = {
    BlindTypes.SHANGRI_LA: 90,
    BlindTypes.VENETIAN: 180,
    BlindTypes.VERTICAL_VENETIAN: 180,
    BlindTypes.VERTICAL_VENETIAN_CS: 180,
    BlindTypes.VERTICAL_VENETIAN_LS: 180,
    BlindTypes.VERTICAL_VENETIAN_RS: 180,
    BlindTypes.VERTICAL_VENETIAN_SS: 180,
    BlindTypes.CURTAIN_LS: 180,
    BlindTypes.CURTAIN_RS: 180,
    BlindTypes.CURTAIN_SS: 180,
}

# BlindTypeKt.smali isBottomUp — values 2,3,4 → PlisseBottomUp, DuetteBottomUp, BA24.
BOTTOM_UP_TYPES: frozenset[str] = frozenset(
    {BlindTypes.PLISSE_BOTTOM_UP, BlindTypes.DUETTE_BOTTOM_UP, BlindTypes.BA24}
)

# BlindKt.smali getHasTilt — second-gen motors AND type ∈ {ShangriLa, Venetian,
# VerticalVenetian, VV±}. Read via D1 byte[7] / D2 byte[5].
HAS_TILT_TYPES: frozenset[str] = frozenset(
    {
        BlindTypes.SHANGRI_LA,
        BlindTypes.VENETIAN,
        BlindTypes.VERTICAL_VENETIAN,
        BlindTypes.VERTICAL_VENETIAN_CS,
        BlindTypes.VERTICAL_VENETIAN_LS,
        BlindTypes.VERTICAL_VENETIAN_RS,
        BlindTypes.VERTICAL_VENETIAN_SS,
    }
)

# BlindKt.smali getHasTiltAngle — second-gen AND tilt type EXCEPT ShangriLa.
HAS_TILT_ANGLE_TYPES: frozenset[str] = frozenset(
    HAS_TILT_TYPES - {BlindTypes.SHANGRI_LA}
)


def max_tilt_angle(blind_type: str) -> int:
    """BlindTypeKt.getMaxTiltAngle: only tilting types have a non-zero value."""
    return MAX_TILT_ANGLE.get(blind_type, 0)


# --------------------------------------------------------------------------- #
# Blind configuration (the BLE-visible slice of the app's ``Blind`` model)     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BlindConfig:
    motor_name: str
    blind_type: str
    # ``Blind.getTiltOpen`` — cloud-configured ShangriLa fraction. Not derivable
    # from BLE; configurable in the HA options flow (0.0 default). Only used
    # by the ShangriLa mapping helpers.
    tilt_open: float = 0.0

    @property
    def motor(self) -> MotorModel:
        return find_motor_model(self.motor_name)

    @property
    def range(self) -> int:
        return self.motor.range

    @property
    def is_second_gen(self) -> bool:
        return self.motor.is_second_gen

    @property
    def has_tilt(self) -> bool:
        """BlindKt.getHasTilt: second-gen motor + tilting blind type."""
        return self.is_second_gen and self.blind_type in HAS_TILT_TYPES

    @property
    def has_tilt_angle(self) -> bool:
        """BlindKt.getHasTiltAngle: second-gen + tilt type except ShangriLa."""
        return self.is_second_gen and self.blind_type in HAS_TILT_ANGLE_TYPES

    @property
    def max_tilt_angle(self) -> int:
        return max_tilt_angle(self.blind_type)

    @property
    def is_bottom_up(self) -> bool:
        """BlindTypeKt.isBottomUp: PlisseBottomUp, DuetteBottomUp, BA24."""
        return self.blind_type in BOTTOM_UP_TYPES

    @property
    def is_motor_direction_inverse(self) -> bool:
        """BlindKt.isMotorDirectionInverse: HD1300+bottom-up, or HD3600+BA24.

        Verified: ``(MotorType==HD1300 AND isBottomUp) OR (MotorType==HD3600
        AND type==BA24)`` (BlindKt.smali:730).
        """
        return (
            self.motor_name == "HD1300" and self.is_bottom_up
        ) or (self.motor_name == "HD3600" and self.blind_type == BlindTypes.BA24)

    @property
    def is_double_servo(self) -> bool:
        """Blind.isDoubleServo: HD3800 (+ productId null or 1/2). Product id is
        cloud/user data, not BLE — we use the app's null-branch default: HD3800
        is treated as double-servo (Blind.smali:2285)."""
        return self.motor_name == "HD3800"

    @property
    def is_curtain(self) -> bool:
        """BlindTypeKt.isCurtain: CurtainLS/RS/SS."""
        return self.blind_type in (
            BlindTypes.CURTAIN_LS,
            BlindTypes.CURTAIN_RS,
            BlindTypes.CURTAIN_SS,
        )

    @property
    def is_shangrila(self) -> bool:
        return self.blind_type == BlindTypes.SHANGRI_LA

    # -- read-side helpers ------------------------------------------------ #
    def decode_position_fraction(self, raw: int) -> float:
        """handleMotorPositionResponse (4994-5046).

        inverse   → raw/range
        ShangriLa → 1 − mapPositionToRelativeShangrilaPosition(raw/range)
        normal    → 1 − raw/range
        """
        frac = raw / self.range
        if self.is_motor_direction_inverse:
            return frac
        if self.is_shangrila:
            return 1.0 - map_position_to_relative_shangrila_position(frac, self.tilt_open)
        return 1.0 - frac

    def decode_tilt_raw(self, raw_tilt: int) -> int:
        """Tilt the app stores after a D1/D2 frame.

        Non-ShangriLa → the raw byte straight through (app D1 handler 2392-2418).
        ShangriLa     → mapPositionToShangrilaTiltAngle(raw_position/range)
        (raw_position is passed instead by the caller for ShangriLa.)
        """
        if self.is_shangrila:
            raise ValueError("pass raw position to decode_shangrila_tilt for ShangriLa")
        return raw_tilt & 0xFF

    def decode_shangrila_tilt(self, raw_position: int) -> int:
        """D1 ShangriLa branch (2351-2369): angle from the RAW position."""
        return map_position_to_shangrila_tilt_angle(
            raw_position / self.range, self.tilt_open, self.max_tilt_angle
        )


# --------------------------------------------------------------------------- #
# Bar types (BarType enum used by BlissCommandsKt / DeviceConnection)          #
# --------------------------------------------------------------------------- #
class BarType:
    TOP = "TOP"
    BOTTOM = "BOTTOM"
    BOTH = "BOTH"
    TILT = "TILT"


def move_command_for_bar(blind: BlindConfig, bar: str) -> bytes:
    """BlissCommandsKt.getMoveToCommandForBarType (1269–1362).

    TOP    → topToPosition (double-servo) else gotoPrefix
    BOTTOM → bottomToPosition
    BOTH   → moveBothBars
    TILT   → tiltToAngle
    """
    if bar == BarType.BOTTOM:
        return BOTTOM_TO_POSITION_PREFIX
    if bar == BarType.BOTH:
        return MOVE_BOTH_BARS_PREFIX
    if bar == BarType.TILT:
        return TILT_TO_ANGLE_PREFIX
    # TOP
    return TOP_TO_POSITION_PREFIX if blind.is_double_servo else GOTO_PREFIX


# --------------------------------------------------------------------------- #
# Position encoding (BlissCommandsKt.getPositionBytes 1364–1400 +              #
# getMoveToCommand 1102–1136)                                                  #
# --------------------------------------------------------------------------- #
def position_bytes(raw: int, range_: int) -> bytes:
    """range 1000 → 2-byte LE short; range 100 → single byte."""
    if range_ == 1000:
        return short_le(raw)
    return bytes((raw & 0xFF,))


def raw_from_fraction(blind: BlindConfig, fraction: float) -> int:
    """Scenes/UI 'move to position' encode.

    getMoveToCommand: normal motor raw = round((1 - f) * range), inverse motor
    raw = round(f * range). This AND handleMotorPositionResponse's decode are
    exact inverses, so a sent position round-trips on read-back.
    """
    f = max(0.0, min(1.0, float(fraction)))
    if blind.is_motor_direction_inverse:
        return _round_half_up(f * blind.range)
    return _round_half_up((1.0 - f) * blind.range)


def move_to_position_command(blind: BlindConfig, fraction: float, bar: str = BarType.TOP) -> bytes:
    """Full frame: bar prefix + position bytes (getMoveToCommand / setPosition)."""
    raw = raw_from_fraction(blind, fraction)
    return move_command_for_bar(blind, bar) + position_bytes(raw, blind.range)


def move_ba24_command(blind: BlindConfig, fraction: float) -> bytes:
    """BlissCommandsKt.getMoveToCommandForBA24 (1195–1248).

    moveBothBars + short(range - round(f*maxPos)) + short(maxPos).
    """
    max_pos = blind.range
    a = _round_half_up(max(0.0, min(1.0, float(fraction))) * max_pos)
    b = max_pos - a
    return MOVE_BOTH_BARS_PREFIX + short_le(b) + short_le(max_pos)


def move_both_bars_command(blind: BlindConfig, top_frac: float, bottom_frac: float) -> bytes:
    """DeviceConnection.setPosition(F,F) → moveBothBars + two raw shorts (8531)."""
    top_raw = raw_from_fraction(blind, top_frac)
    bottom_raw = raw_from_fraction(blind, bottom_frac)
    return MOVE_BOTH_BARS_PREFIX + short_le(top_raw) + short_le(bottom_raw)


# --------------------------------------------------------------------------- #
# Tilt encoding (BlissCommandsKt.setPositionAndTiltAngle 1583–1715,            #
#                 DeviceConnection.setTiltAngle 9142)                          #
# --------------------------------------------------------------------------- #
def set_tilt_command(blind: BlindConfig, tilt_angle: int, position_fraction: float) -> bytes:
    """Non-ShangriLa tilt+position frame.

    tiltToAngle + short(roundTo2dp(posFrac) * range) + short(coerced tiltAngle).
    The present (current) position travels in the same frame — exactly what the
    app sends from its tilt slider. tilt_angle is clamped 0..maxTiltAngle.
    """
    angle = max(0, min(blind.max_tilt_angle, int(tilt_angle)))
    f = max(0.0, min(1.0, float(position_fraction)))
    # roundToNumberOfDecimals(x, 2) == Math.round(x*100)/100.0 (app semantics).
    pos_raw = _round_half_up(_round_half_up(f * 100.0) / 100.0 * blind.range)
    return TILT_TO_ANGLE_PREFIX + short_le(pos_raw) + short_le(angle)


def set_shangrila_tilt_command(blind: BlindConfig, tilt_angle: int) -> bytes:
    """ShangriLa-only tilt path (DeviceConnection.setTiltAngle 9142–9206).

    position = mapShangrilaTiltAngleToPosition(angle) = tilt_open*(maxTilt-angle)/maxTilt
    frame   = TOP bar command + position bytes.
    """
    angle = max(0, min(blind.max_tilt_angle, int(tilt_angle)))
    pos_frac = shangrila_tilt_angle_to_position(angle, blind.tilt_open, blind.max_tilt_angle)
    return move_command_for_bar(blind, BarType.TOP) + position_bytes(
        _round_half_up(pos_frac * blind.range), blind.range
    )


# --------------------------------------------------------------------------- #
# ShangriLa mapping helpers (BlindKt.smali 278–318)                            #
# --------------------------------------------------------------------------- #
def shangrila_tilt_angle_to_position(tilt_angle: int, tilt_open: float, max_angle: int) -> float:
    """mapShangrilaTiltAngleToPosition (1081–1120): tilt_open*(maxTilt-angle)/maxTilt."""
    return tilt_open * (max_angle - tilt_angle) / max_angle


def map_position_to_relative_shangrila_position(pos_frac: float, tilt_open: float) -> float:
    """mapPositionToRelativeShangrilaPosition (864–970).

    Raises when tilt_open == 1.0 (the app's IllegalArgumentException)."""
    p = max(0.0, min(1.0, float(pos_frac)))
    to = float(tilt_open)
    if to == 1.0:
        raise ValueError("tiltOpen cannot be 1.0")
    if p > to:
        return (p - to) / (1.0 - to)
    return 0.0


def map_position_to_shangrila_tilt_angle(pos_frac: float, tilt_open: float, max_angle: int) -> int:
    """mapPositionToShangrilaTiltAngle (972–1042): int(maxTilt * (1 - p/to))."""
    p = max(0.0, min(1.0, float(pos_frac)))
    to = float(tilt_open)
    if to == 0.0:
        return 0
    if p >= to:
        return 0
    return int(max_angle * (1.0 - p / to))


# --------------------------------------------------------------------------- #
# Response decode (DeviceConnection.smali)                                     #
# --------------------------------------------------------------------------- #
class BatteryLevel:
    """mapMotorRetToBattery (5280–5315) — coarse 4-state, no percentage."""

    NORMAL = "normal"
    LOW = "low"
    NONE = "none"
    UNKNOWN = "unknown"

    _MAP = {0x00: NORMAL, 0x08: LOW, 0x10: NONE}

    @classmethod
    def from_flags(cls, flags: int) -> str:
        return cls._MAP.get(flags & 0x18, cls.UNKNOWN)


class OperatingStatus:
    """parseCalibrationOperatingStatus (5634–5683) — (flags & 0x60) >> 5."""

    IDLE = 0
    MOVING_DOWN = 1
    MOVING_UP = 2
    STALLED = 3
    UNKNOWN = 4

    _MAP = {0: IDLE, 1: MOVING_DOWN, 2: MOVING_UP, 3: STALLED}

    @classmethod
    def from_flags(cls, flags: int) -> int:
        return cls._MAP.get((flags & 0x60) >> 5, cls.UNKNOWN)


@dataclass
class BlindState:
    """Decoded view of the latest motor response."""

    position_fraction: Optional[float] = None      # 0 (closed) .. 1 (open)
    tilt_angle: Optional[int] = None               # degrees-ish (raw D1 byte / mapped)
    battery: str = BatteryLevel.UNKNOWN
    operating_status: int = OperatingStatus.UNKNOWN
    has_limits: bool = False
    is_reverse: bool = False
    nordic_error: Optional[int] = None             # HD3600/3900 error code, else None

    @property
    def is_moving(self) -> bool:
        return self.operating_status in (
            OperatingStatus.MOVING_UP,
            OperatingStatus.MOVING_DOWN,
        )


def normalize_nordic_error_code(raw: int) -> int:
    """NordicMotorStatusParser.normalizeNordicErrorCode (98-122): 0→0, 1..13→same, else→10."""
    raw = raw & 0xFF
    if raw == 0:
        return 0
    if 1 <= raw <= 13:
        return raw
    return 10


def parse_frame(payload: bytes, blind: BlindConfig) -> Optional[BlindState]:
    """Parse a notify payload (full frame incl. header).

    Returns None for anything that is not a D1/D2 status frame. Byte offsets
    verified against the app response handlers (DeviceConnection.smali).
    """
    if payload is None or len(payload) < 5 or payload[:4] != HEADER:
        return None

    body = payload[4:]
    status = body[0]

    if status == STATUS_D1:
        # Flag bits: bit0 reverse, bit1 hasLimits, bit2 remoteLink,
        # bits3-4 battery, bits5-6 operating status (device handler 2197-2250).
        flags = body[1]
        state = BlindState(
            battery=BatteryLevel.from_flags(flags),
            operating_status=OperatingStatus.from_flags(flags),
            has_limits=bool(flags & 0x02),
            is_reverse=bool(flags & 0x01),
        )

        # Position: short LE at [3] when range==1000, else byte at [2]
        # (handleMotorPositionResponse 4929-5059).
        if blind.range == 1000:
            if len(body) >= 5:
                raw = body[3] | (body[4] << 8)
            else:
                return None
        else:
            if len(body) >= 3:
                raw = body[2]
            else:
                return None
        state.position_fraction = blind.decode_position_fraction(raw)

        # Nordic status error (NordicMotorStatusParser): HD3600 → byte[6],
        # HD3900 → byte[5]; both normalized (1-13 kept, else 10).
        if blind.motor.nordic:
            if blind.motor_name == "HD3600" and len(body) >= 7:
                state.nordic_error = normalize_nordic_error_code(body[6])
            elif blind.motor_name == "HD3900" and len(body) >= 6:
                state.nordic_error = normalize_nordic_error_code(body[5])

        # Tilt: ShangriLa derives angle from raw position (D1 branch 2351-2369);
        # otherwise raw byte at [7] when the blind has tilt (2392-2418).
        if blind.has_tilt:
            if blind.is_shangrila:
                state.tilt_angle = blind.decode_shangrila_tilt(raw)
            elif len(body) > 7:
                state.tilt_angle = blind.decode_tilt_raw(body[7])

        return state

    if status == STATUS_D2:
        flags = body[1]
        state = BlindState(
            battery=BatteryLevel.from_flags(flags),
            operating_status=OperatingStatus.from_flags(flags),
            has_limits=bool(flags & 0x02),
            is_reverse=bool(flags & 0x01),
        )

        if blind.range == 1000:
            if len(body) >= 5:
                raw = body[3] | (body[4] << 8)
            else:
                return None
        elif len(body) >= 3:
            raw = body[2]
        else:
            return None
        state.position_fraction = blind.decode_position_fraction(raw)

        # D2 tilt byte lives at [5] (D2 handler 2850-2867); ShangriLa from position.
        if blind.has_tilt:
            if blind.is_shangrila:
                state.tilt_angle = blind.decode_shangrila_tilt(raw)
            elif len(body) > 5:
                state.tilt_angle = blind.decode_tilt_raw(body[5])

        return state

    return None