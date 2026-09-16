"""Unit tests for bliss_blinds.protocol (pure Python, no HA import needed).

Run:  python -m unittest discover -s tests
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

# Load protocol.py standalone so these tests run WITHOUT Home Assistant
# installed (they never touch the HA package __init__).
_PROTOCOL_SPEC = importlib.util.spec_from_file_location(
    "bliss_blinds_protocol",
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "bliss_blinds"
    / "protocol.py",
)
_PROTOCOL = importlib.util.module_from_spec(_PROTOCOL_SPEC)
assert _PROTOCOL_SPEC.loader is not None
sys.modules["bliss_blinds_protocol"] = _PROTOCOL
_PROTOCOL_SPEC.loader.exec_module(_PROTOCOL)

from bliss_blinds_protocol import (  # noqa: E402
    ALL_BLIND_TYPES,
    BOTTOM_TO_POSITION_PREFIX,
    BatteryLevel,
    BarType,
    BlindConfig,
    BlindTypes,
    GOTO_PREFIX,
    HEADER,
    HEARTBEAT,
    MOVE_BOTH_BARS_PREFIX,
    MAX_TILT_ANGLE,
    MOTOR_MODELS,
    OperatingStatus,
    READ_STATUS,
    RESPONSE_HEADER,
    ROLLER_STOP,
    SET_TIME_PREFIX,
    TILT_TO_ANGLE_PREFIX,
    TOP_TO_POSITION_PREFIX,
    max_tilt_angle,
    map_position_to_relative_shangrila_position,
    map_position_to_shangrila_tilt_angle,
    move_ba24_command,
    move_both_bars_command,
    move_to_position_command,
    parse_frame,
    position_bytes,
    raw_from_fraction,
    set_internal_clock,
    set_shangrila_tilt_command,
    set_tilt_command,
    shangrila_tilt_angle_to_position,
    short_le,
)


class TestModels(unittest.TestCase):
    def test_hd0100_only_range_100(self):
        self.assertEqual(MOTOR_MODELS["HD0100"].range, 100)
        self.assertTrue(MOTOR_MODELS["HD0100"].is_first_gen)
        for name in ("HD0101", "HD3600", "HD1300", "UNKNOWN", "TS5500"):
            self.assertEqual(MOTOR_MODELS[name].range, 1000, name)

    def test_generation(self):
        # Verified FIRST-gen set: HD0100, HD0101, HD0200, HD0300, HD0700, HD0800,
        # HD1200, UNKNOWN (MotorTypeKt map). HD0400 is SECOND-gen.
        for name in ("HD0100", "HD0101", "HD0200", "HD0300", "HD0700", "HD0800", "HD1200", "UNKNOWN"):
            self.assertTrue(MOTOR_MODELS[name].is_first_gen, name)
        for name in ("HD0400", "HD0401", "HD0500", "HD0501", "HD1000", "HD1300", "HD3600", "HD3700", "HD3800", "HD3900"):
            self.assertFalse(MOTOR_MODELS[name].is_first_gen, name)

    def test_nordic(self):
        for name in ("HD3600", "HD3700", "HD3900"):
            self.assertTrue(MOTOR_MODELS[name].nordic, name)
        for name in ("HD3800", "HD0400"):
            self.assertFalse(MOTOR_MODELS[name].nordic, name)

    def test_find_motor_model_case_insensitive(self):
        blind = BlindConfig("hd3600", BlindTypes.ROLLER)
        self.assertEqual(blind.motor_name.upper(), "HD3600")

    def test_all_blind_types_count(self):
        # BlindType.smali declares 27 entries.
        self.assertEqual(len(ALL_BLIND_TYPES), 27)
        self.assertIn(BlindTypes.ROLLER, ALL_BLIND_TYPES)
        self.assertIn(BlindTypes.BA24, ALL_BLIND_TYPES)
        self.assertEqual(len(set(ALL_BLIND_TYPES)), len(ALL_BLIND_TYPES))


class TestMaxTiltAngle(unittest.TestCase):
    def test_tilt_types_get_180(self):
        for t in (
            BlindTypes.VENETIAN,
            BlindTypes.VERTICAL_VENETIAN,
            BlindTypes.VERTICAL_VENETIAN_CS,
            BlindTypes.VERTICAL_VENETIAN_LS,
            BlindTypes.VERTICAL_VENETIAN_RS,
            BlindTypes.VERTICAL_VENETIAN_SS,
            BlindTypes.CURTAIN_LS,
            BlindTypes.CURTAIN_RS,
            BlindTypes.CURTAIN_SS,
        ):
            self.assertEqual(MAX_TILT_ANGLE[t], 180, t)

    def test_shangrila_90(self):
        self.assertEqual(MAX_TILT_ANGLE[BlindTypes.SHANGRI_LA], 90)

    def test_non_tilt_0(self):
        self.assertEqual(max_tilt_angle(BlindTypes.ROLLER), 0)
        self.assertEqual(max_tilt_angle(BlindTypes.DUETTE), 0)
        self.assertEqual(max_tilt_angle(BlindTypes.BA24), 0)


class TestDirection(unittest.TestCase):
    def test_inverse_rules(self):
        # HD1300 + bottom-up
        self.assertTrue(BlindConfig("HD1300", BlindTypes.DUETTE_BOTTOM_UP).is_motor_direction_inverse)
        self.assertTrue(BlindConfig("HD1300", BlindTypes.BA24).is_motor_direction_inverse)
        # HD3600 + BA24
        self.assertTrue(BlindConfig("HD3600", BlindTypes.BA24).is_motor_direction_inverse)
        # Controls
        self.assertFalse(BlindConfig("HD1300", BlindTypes.ROLLER).is_motor_direction_inverse)
        self.assertFalse(BlindConfig("HD3600", BlindTypes.ROLLER).is_motor_direction_inverse)
        self.assertFalse(BlindConfig("HD0400", BlindTypes.BA24).is_motor_direction_inverse)

    def test_bottom_up_types(self):
        for t in (BlindTypes.PLISSE_BOTTOM_UP, BlindTypes.DUETTE_BOTTOM_UP, BlindTypes.BA24):
            self.assertTrue(BlindConfig("HD0800", t).is_bottom_up, t)
        self.assertFalse(BlindConfig("HD0800", BlindTypes.ROLLER).is_bottom_up)

    def test_double_servo(self):
        self.assertTrue(BlindConfig("HD3800", BlindTypes.BA24).is_double_servo)
        self.assertFalse(BlindConfig("HD3600", BlindTypes.ROLLER).is_double_servo)

    def test_has_two_bars(self):
        # Two-bar geometry ⇒ two bars, whatever the motor.
        for t in (
            BlindTypes.DOUBLE_ROLLER,
            BlindTypes.DUETTE_TDBU,
            BlindTypes.DUETTE_PLISSE_TDBU,
            BlindTypes.PLISSE_TDBU,
            BlindTypes.PLISSE_DUETTE_TDBU,
        ):
            self.assertTrue(BlindConfig("HD3800", t).has_two_bars, t)
            self.assertTrue(BlindConfig("HD3600", t).has_two_bars, t)

    def test_has_two_bars_double_servo_motor(self):
        # A double-servo motor supplies two servos even for a plain type…
        self.assertTrue(BlindConfig("HD3800", BlindTypes.ROLLER).has_two_bars)
        # …but BA24 rides moveBothBars as one coordinated pair — one cover.
        self.assertFalse(BlindConfig("HD3800", BlindTypes.BA24).has_two_bars)

    def test_has_two_bars_single_bar(self):
        self.assertFalse(BlindConfig("HD0400", BlindTypes.ROLLER).has_two_bars)
        self.assertFalse(BlindConfig("HD0400", BlindTypes.VENETIAN).has_two_bars)
        # Top-down-only / bottom-up-only types are a single bar.
        self.assertFalse(BlindConfig("HD0400", BlindTypes.DUETTE_TOP_DOWN).has_two_bars)
        self.assertFalse(BlindConfig("HD0400", BlindTypes.PLISSE_BOTTOM_UP).has_two_bars)


class TestTiltCapability(unittest.TestCase):
    def test_has_tilt_requires_second_gen(self):
        # First-gen motor + venetian ⇒ no tilt (BlindKt gates on generation).
        self.assertFalse(BlindConfig("HD0300", BlindTypes.VENETIAN).has_tilt)
        self.assertTrue(BlindConfig("HD0400", BlindTypes.VENETIAN).has_tilt)
        self.assertFalse(BlindConfig("HD0400", BlindTypes.ROLLER).has_tilt)

    def test_has_tilt_angle(self):
        self.assertTrue(BlindConfig("HD0400", BlindTypes.VENETIAN).has_tilt_angle)
        self.assertFalse(BlindConfig("HD0400", BlindTypes.SHANGRI_LA).has_tilt_angle)
        self.assertFalse(BlindConfig("HD0400", BlindTypes.ROLLER).has_tilt_angle)


class TestPositionBytes(unittest.TestCase):
    def test_range1000_short_le(self):
        self.assertEqual(position_bytes(300, 1000), b"\x2c\x01")
        self.assertEqual(position_bytes(1000, 1000), b"\xe8\x03")

    def test_range100_single_byte(self):
        self.assertEqual(position_bytes(50, 100), b"\x32")
        self.assertEqual(position_bytes(100, 100), b"\x64")


class TestEncodeDecodeRoundTrip(unittest.TestCase):
    def test_normal_scene_encode(self):
        blind = BlindConfig("HD3600", BlindTypes.ROLLER)
        self.assertEqual(raw_from_fraction(blind, 0.7), 300)          # (1-0.7)*1000
        self.assertEqual(raw_from_fraction(blind, 1.0), 0)            # open
        self.assertEqual(raw_from_fraction(blind, 0.0), 1000)         # closed

    def test_inverse_scene_encode(self):
        blind = BlindConfig("HD1300", BlindTypes.DUETTE_BOTTOM_UP)
        self.assertEqual(raw_from_fraction(blind, 0.7), 700)          # raw = f*range
        self.assertEqual(raw_from_fraction(blind, 1.0), 1000)         # open
        self.assertEqual(raw_from_fraction(blind, 0.0), 0)            # closed

    def test_round_trip_normal(self):
        blind = BlindConfig("HD3600", BlindTypes.ROLLER)
        for f in (0.0, 0.25, 0.5, 0.75, 1.0):
            raw = raw_from_fraction(blind, f)
            self.assertAlmostEqual(blind.decode_position_fraction(raw), f, places=1)

    def test_round_trip_inverse(self):
        blind = BlindConfig("HD1300", BlindTypes.DUETTE_BOTTOM_UP)
        for f in (0.0, 0.25, 0.5, 0.75, 1.0):
            raw = raw_from_fraction(blind, f)
            self.assertAlmostEqual(blind.decode_position_fraction(raw), f, places=1)


class TestMoveFrames(unittest.TestCase):
    def test_top_single_servo_prefix(self):
        blind = BlindConfig("HD3600", BlindTypes.ROLLER)
        self.assertEqual(move_to_position_command(blind, 0.7), GOTO_PREFIX + b"\x2c\x01")

    def test_top_double_servo_prefix(self):
        blind = BlindConfig("HD3800", BlindTypes.BA24)
        self.assertEqual(
            move_to_position_command(blind, 0.5, bar=BarType.TOP)[: len(TOP_TO_POSITION_PREFIX)],
            TOP_TO_POSITION_PREFIX,
        )

    def test_range100_frame(self):
        blind = BlindConfig("HD0100", BlindTypes.ROLLER)
        frame = move_to_position_command(blind, 0.5)
        self.assertEqual(frame, GOTO_PREFIX + b"\x32")

    def test_ba24_frame_exact(self):
        blind = BlindConfig("HD3800", BlindTypes.BA24)
        # f=0.25 → a=250, b=750 → both bars: short(750)+short(1000)
        self.assertEqual(
            move_ba24_command(blind, 0.25),
            MOVE_BOTH_BARS_PREFIX + b"\xee\x02" + b"\xe8\x03",
        )

    def test_move_both_bars(self):
        blind = BlindConfig("HD3600", BlindTypes.DOUBLE_ROLLER)
        self.assertEqual(
            move_both_bars_command(blind, 0.5, 0.25),
            MOVE_BOTH_BARS_PREFIX + short_le(500) + short_le(750),
        )

    def test_per_bar_commands(self):
        # TOP bar ⇒ topToPosition (B1 03); BOTTOM bar ⇒ bottomToPosition (F4 03).
        blind = BlindConfig("HD3800", BlindTypes.DUETTE_TDBU)
        self.assertEqual(
            move_to_position_command(blind, 0.6, bar=BarType.TOP),
            TOP_TO_POSITION_PREFIX + short_le(400),  # normal: (1-0.6)*1000
        )
        self.assertEqual(
            move_to_position_command(blind, 0.6, bar=BarType.BOTTOM),
            BOTTOM_TO_POSITION_PREFIX + short_le(400),
        )

    def test_per_bar_prefixes_are_distinct(self):
        # A top-bar and a bottom-bar move must never emit the same frame.
        blind = BlindConfig("HD3800", BlindTypes.DOUBLE_ROLLER)
        self.assertNotEqual(
            move_to_position_command(blind, 0.5, bar=BarType.TOP),
            move_to_position_command(blind, 0.5, bar=BarType.BOTTOM),
        )


class TestTiltFrames(unittest.TestCase):
    def test_set_tilt_frame(self):
        blind = BlindConfig("HD0400", BlindTypes.VENETIAN)
        # pos 0.5 → short(500); angle 90 → short(90)
        self.assertEqual(
            set_tilt_command(blind, 90, 0.5),
            TILT_TO_ANGLE_PREFIX + short_le(500) + short_le(90),
        )

    def test_set_tilt_clamps_to_max(self):
        blind = BlindConfig("HD0400", BlindTypes.VENETIAN)
        frame = set_tilt_command(blind, 999, 0.5)
        self.assertTrue(frame.endswith(short_le(180)))

    def test_shangrila_tilt_frame(self):
        blind = BlindConfig("HD0400", BlindTypes.SHANGRI_LA, tilt_open=0.5)
        # angle 45 → pos = 0.5*(90-45)/90 = 0.25 → raw 250
        self.assertEqual(
            set_shangrila_tilt_command(blind, 45),
            GOTO_PREFIX + short_le(250),
        )


class TestShangriLaMapping(unittest.TestCase):
    def test_angle_to_position(self):
        self.assertEqual(shangrila_tilt_angle_to_position(45, 0.5, 90), 0.25)
        self.assertEqual(shangrila_tilt_angle_to_position(0, 0.5, 90), 0.5)
        self.assertEqual(shangrila_tilt_angle_to_position(90, 0.5, 90), 0.0)

    def test_position_to_relative(self):
        self.assertAlmostEqual(map_position_to_relative_shangrila_position(0.8, 0.5), 0.6)
        self.assertEqual(map_position_to_relative_shangrila_position(0.3, 0.5), 0.0)

    def test_position_to_angle(self):
        self.assertEqual(map_position_to_shangrila_tilt_angle(0.25, 0.5, 90), 45)
        self.assertEqual(map_position_to_shangrila_tilt_angle(0.8, 0.5, 90), 0)  # p >= to
        self.assertEqual(map_position_to_shangrila_tilt_angle(0.5, 0.0, 90), 0)  # to == 0

    def test_relative_raises_when_tilt_open_1(self):
        with self.assertRaises(ValueError):
            map_position_to_relative_shangrila_position(0.5, 1.0)


class TestParseD1(unittest.TestCase):
    def test_normal_decode(self):
        blind = BlindConfig("HD3600", BlindTypes.ROLLER)
        # flags 0x4b: reverse(1) limits(2) battery low(0x08) op=MOVING_UP(0x40)
        payload = HEADER + bytes([0xD1, 0x4B, 0x00, 0x2C, 0x01, 0x00, 0x00, 0x00])
        state = parse_frame(payload, blind)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state.position_fraction, 0.7, places=3)
        self.assertEqual(state.battery, BatteryLevel.LOW)
        self.assertEqual(state.operating_status, OperatingStatus.MOVING_UP)
        self.assertTrue(state.is_moving)
        self.assertTrue(state.is_reverse)
        self.assertTrue(state.has_limits)

    def test_tilt_byte_at_7(self):
        blind = BlindConfig("HD0400", BlindTypes.VENETIAN)
        payload = HEADER + bytes([0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xB4])
        state = parse_frame(payload, blind)
        self.assertEqual(state.tilt_angle, 0xB4)

    def test_battery_all_states(self):
        blind = BlindConfig("HD3600", BlindTypes.ROLLER)
        cases = {
            0x00: BatteryLevel.NORMAL,
            0x08: BatteryLevel.LOW,
            0x10: BatteryLevel.NONE,
            0x18: BatteryLevel.UNKNOWN,
        }
        for bit, expected in cases.items():
            payload = HEADER + bytes([0xD1, bit, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            with self.subTest(flags=bit):
                self.assertEqual(parse_frame(payload, blind).battery, expected)

    def test_operating_status_all_states(self):
        blind = BlindConfig("HD3600", BlindTypes.ROLLER)
        cases = {0x00: 0, 0x20: 1, 0x40: 2, 0x60: 3}
        for bit, expected in cases.items():
            payload = HEADER + bytes([0xD1, bit, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            with self.subTest(flags=bit):
                self.assertEqual(parse_frame(payload, blind).operating_status, expected)

    def test_inverse_decode(self):
        blind = BlindConfig("HD1300", BlindTypes.DUETTE_BOTTOM_UP)
        payload = HEADER + bytes([0xD1, 0x00, 0x00, 0xE8, 0x03, 0x00, 0x00, 0x00])
        state = parse_frame(payload, blind)
        self.assertAlmostEqual(state.position_fraction, 1.0, places=3)

    def test_shangrila_tilt_from_position(self):
        blind = BlindConfig("HD0400", BlindTypes.SHANGRI_LA, tilt_open=0.5)
        # raw  250 → frac 0.25 → angle = int(90*(1 - 0.25/0.5)) = 45
        payload = HEADER + bytes([0xD1, 0x00, 0x00, 0xFA, 0x00, 0x00, 0x00, 0x00])
        state = parse_frame(payload, blind)
        self.assertEqual(state.tilt_angle, 45)

    def test_nordic_error_hd3600_index6(self):
        blind = BlindConfig("HD3600", BlindTypes.ROLLER)
        # body longer than 6 → error at [6] = 0x05 → kept as 5
        payload = HEADER + bytes([0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05, 0x00])
        self.assertEqual(parse_frame(payload, blind).nordic_error, 5)
        # values > 13 normalize to 10
        payload = HEADER + bytes([0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00])
        self.assertEqual(parse_frame(payload, blind).nordic_error, 10)

    def test_nordic_error_hd3900_index5(self):
        blind = BlindConfig("HD3900", BlindTypes.ROLLER)
        payload = HEADER + bytes([0xD1, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00])
        self.assertEqual(parse_frame(payload, blind).nordic_error, 3)

    def test_non_nordic_no_error(self):
        blind = BlindConfig("HD3700", BlindTypes.ROLLER)  # HD3700 is NOT Nordic
        payload = HEADER + bytes([0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.assertIsNone(parse_frame(payload, blind).nordic_error)

    def test_reject_other_status(self):
        blind = BlindConfig("HD3600", BlindTypes.ROLLER)
        self.assertIsNone(parse_frame(HEADER + bytes([0xD4, 0x00, 0x00, 0x00, 0x00]), blind))
        self.assertIsNone(parse_frame(b"\x00\x01\x02\x03\x04", blind))


class TestParseD2(unittest.TestCase):
    def test_tilt_byte_at_5(self):
        # D2 tilt byte at index 5 — needs a tilting type on the (double-servo) motor.
        blind = BlindConfig("HD3800", BlindTypes.VENETIAN)
        payload = HEADER + bytes([0xD2, 0x00, 0x00, 0xE8, 0x03, 0x5A, 0x00, 0x00])
        state = parse_frame(payload, blind)
        self.assertEqual(state.tilt_angle, 0x5A)
        self.assertAlmostEqual(state.position_fraction, 0.0, places=3)  # raw 1000

    def test_response_header_accepted(self):
        # Live log: motors reply with FF 01 02 03 response header, NOT the
        # command header. FF 01 02 03 D2 02 46 BC 02 → D2 status at body[0].
        blind = BlindConfig("HD0400", BlindTypes.ROLLER)
        payload = bytes([0xFF, 0x01, 0x02, 0x03, 0xD2, 0x02, 0x46, 0xBC, 0x02])
        state = parse_frame(payload, blind)
        self.assertIsNotNone(state)
        # For range 1000: raw = body[3] | body[4]<<8 = 0x02BC = 700 → normal 0.3
        self.assertAlmostEqual(state.position_fraction, 0.3, places=3)
        self.assertEqual(state.battery, BatteryLevel.NORMAL)  # flags=0x02

    def test_command_and_response_header_equivalent(self):
        # Both byte patterns must produce identical state.
        blind = BlindConfig("HD0400", BlindTypes.ROLLER)
        cmd = HEADER + bytes([0xD1, 0x08, 0x00, 0xE8, 0x03, 0x00, 0x00, 0x00])
        resp = RESPONSE_HEADER + bytes([0xD1, 0x08, 0x00, 0xE8, 0x03, 0x00, 0x00, 0x00])
        self.assertEqual(parse_frame(cmd, blind), parse_frame(resp, blind))


class TestConstants(unittest.TestCase):
    def test_known_command_bytes(self):
        self.assertEqual(HEARTBEAT, b"\xff\x01\x01\x01\x01\x01\x01")
        self.assertEqual(READ_STATUS, b"\xff\x78\xea\x41\xd1\x03\x01")
        self.assertEqual(ROLLER_STOP, b"\xff\x78\xea\x41\x5f\x03\x01")


class TestSetInternalClock(unittest.TestCase):
    def test_frame_shape(self):
        # setTimePrefix + 6 GregorianCalendar time bytes (BlissCommandsKt :1478).
        frame = set_internal_clock()
        self.assertEqual(len(frame), 14)
        self.assertEqual(frame[:8], SET_TIME_PREFIX)
        self.assertEqual(SET_TIME_PREFIX, b"\xff\x78\xea\x41\x28\x07\x41\x35")

    def test_time_bytes_in_range(self):
        frame = set_internal_clock()
        year, month, day, hour, minute, second = frame[8:]
        # year = UTC_year - 2000; month is field+1 = calendar month (1-12)
        self.assertTrue(0 <= year <= 200)
        self.assertTrue(1 <= month <= 12)
        self.assertTrue(1 <= day <= 31)
        self.assertTrue(0 <= hour <= 23)
        self.assertTrue(0 <= minute <= 59)
        self.assertTrue(0 <= second <= 59)


if __name__ == "__main__":
    unittest.main()