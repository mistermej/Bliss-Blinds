"""Per-device Bluetooth Low Energy coordinator for a Hunter Douglas Bliss blind.

Mirrors the app's per-device connection model (DeviceConnection.smali):

* connect to the advertised motor via the HA bluetooth registry
* notifications on the Response characteristic drive state (push, like the app)
* writes go to the Command characteristic, serialized ≥ 25 ms apart
* **no login/password frames are ever sent** (user decision, matches the app
  allowing movement without a paired password)

Updates are pushed: every D1/D2 frame is parsed and listeners are notified.
A slow readStatus poll (60 s) keeps the state fresh against remote changes and
doubles as a keep-alive; a reconnect loop restores the link after drops.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

# bleak 3.x re-exported BleakError at the top level (the old
# ``bleak.exceptions`` module was renamed to ``bleak.exc`` in 3.0 —
# importing it raises ModuleNotFoundError on HA 2026.x, which pins bleak==3.0.2).
from bleak import BleakClient, BleakError

# HA ships bleak-retry-connector==4.7.1 as a core bluetooth dependency.
# establish_connection() is the supported connect path on HA: it retries the
# connection (up to 4 attempts), re-fetches the live registry device via
# ble_device_callback, and cooperates with the BT manager/scanner. A bare
# BleakClient.connect() emits a WARNING ("BleakClient.connect() called without
# bleak-retry-connector") and connects unreliably, which shows up as devices
# that never become available.
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    COMMAND_CHARACTERISTIC_UUID,
    CONF_ADDRESS,
    CONF_BLIND_TYPE,
    CONF_MOTOR,
    CONF_TILT_OPEN,
    CONNECT_TIMEOUT,
    DEFAULT_TILT_OPEN,
    DOMAIN,
    MANUFACTURER,
    POLL_INTERVAL,
    RECONNECT_INTERVAL,
    RESPONSE_CHARACTERISTIC_UUID,
    WRITE_GAP,
)
from .protocol import (
    READ_STATUS,
    ROLLER_STOP,
    BlindConfig,
    BlindState,
    BlindTypes,
    BarType,
    move_ba24_command,
    move_both_bars_command,
    move_to_position_command,
    parse_frame,
    set_internal_clock,
    set_shangrila_tilt_command,
    set_tilt_command,
)

_LOGGER = logging.getLogger(__name__)


def _hex(frame: bytes) -> str:
    """Uppercase space-separated hex for readable debug logs."""
    return frame.hex(" ").upper()


class BlissBlindCoordinator:
    """Owns the BleakClient, decoded state, and the write queue for one blind."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.address = entry.data[CONF_ADDRESS]

        self.blind = BlindConfig(
            entry.data.get(CONF_MOTOR, "UNKNOWN"),
            entry.data.get(CONF_BLIND_TYPE, BlindTypes.ROLLER),
            float(entry.options.get(CONF_TILT_OPEN, DEFAULT_TILT_OPEN)),
        )

        self.data: Optional[BlindState] = None
        self.available = False

        self._client: Optional[BleakClient] = None
        self._write_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._shutdown = False
        self._connect_task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None

        self._listeners: set[Callable[[], None]] = set()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #
    async def async_start(self) -> None:
        """Connect and seed state; then start background reconnect/poll."""
        await self.async_ensure_connected()
        self._connect_task = self.hass.async_create_background_task(
            self._reconnect_loop(), f"{self.address}_reconnect"
        )
        self._poll_task = self.hass.async_create_background_task(
            self._poll_loop(), f"{self.address}_poll"
        )

    async def async_shutdown(self) -> None:
        self._shutdown = True
        for task in (self._connect_task, self._poll_task):
            if task is not None:
                task.cancel()
        if self._client is not None:
            client, self._client = self._client, None
            try:
                await client.stop_notify(RESPONSE_CHARACTERISTIC_UUID)
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass

    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback invoked after every decoded frame."""
        self._listeners.add(update_callback)

        def _remove() -> None:
            self._listeners.discard(update_callback)

        return _remove

    # ------------------------------------------------------------------ #
    # Device registry info                                                  #
    # ------------------------------------------------------------------ #
    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self.address)},
            "name": self.entry.title,
            "manufacturer": MANUFACTURER,
            "model": f"{self.blind.motor_name} · {self.blind.blind_type}",
        }

    # ------------------------------------------------------------------ #
    # Connection                                                            #
    # ------------------------------------------------------------------ #
    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def async_ensure_connected(self) -> bool:
        if self.is_connected:
            return True
        async with self._connect_lock:
            if self.is_connected:
                return True
            if self._shutdown:
                return False

            device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if device is None:
                _LOGGER.warning(
                    "Bliss blind %s no longer in the Bluetooth registry; will retry",
                    self.address,
                )
                return False

            client: Optional[BleakClient] = None
            try:
                client = await establish_connection(
                    BleakClient,
                    device,
                    self.address,
                    timeout=CONNECT_TIMEOUT,
                    ble_device_callback=lambda: bluetooth.async_ble_device_from_address(
                        self.hass, self.address, connectable=True
                    ),
                )
                await client.start_notify(RESPONSE_CHARACTERISTIC_UUID, self._on_notify)
            except (BleakError, OSError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Bliss blind %s connect failed: %s", self.address, err)
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                return False

            self._client = client
            self.data = None
            _LOGGER.info("Connected to Bliss blind %s", self.address)
            # App connect handshake: setInternalClock() THEN readStatus()
            # (DeviceConnection.smali:5615–5618). Motor may gate status
            # responses on receiving a valid clock frame first.
            await self._write_frame(set_internal_clock())
            await self._write_frame(READ_STATUS)
            return True

    async def _reconnect_loop(self) -> None:
        while not self._shutdown:
            await asyncio.sleep(RECONNECT_INTERVAL.total_seconds())
            try:
                if not self.is_connected:
                    if self.available:
                        self.available = False
                        self._notify_listeners()
                    await self.async_ensure_connected()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the loop alive
                _LOGGER.debug("Reconnect attempt failed", exc_info=True)

    async def _poll_loop(self) -> None:
        while not self._shutdown:
            await asyncio.sleep(POLL_INTERVAL.total_seconds())
            try:
                if self.is_connected:
                    await self._write_frame(READ_STATUS)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - transient BLE errors are normal
                _LOGGER.debug("Poll write failed (dropped connection?)", exc_info=True)

    # ------------------------------------------------------------------ #
    # Write path                                                            #
    # ------------------------------------------------------------------ #
    async def _write_frame(self, frame: bytes) -> None:
        """Serialized write, ≥ WRITE_GAP apart — the app's ConnectionManager."""
        async with self._write_lock:
            if not self.is_connected:
                raise BleakError(f"{self.address} not connected")
            # With-response write, like the app (DeviceConnection.sendWriteCommand).
            _LOGGER.debug("Bliss %s send: %s", self.address, _hex(frame))
            await self._client.write_gatt_char(
                COMMAND_CHARACTERISTIC_UUID, frame, response=True
            )
            await asyncio.sleep(WRITE_GAP)

    async def _send_motion(self, frame: bytes) -> None:
        await self.async_ensure_connected()
        try:
            await self._write_frame(frame)
        except (BleakError, OSError, asyncio.TimeoutError):
            # One retry — the motor may have dropped the link mid-sleep.
            _LOGGER.debug("Write failed, retrying once for %s", self.address)
            self.available = False
            if await self.async_ensure_connected():
                await self._write_frame(frame)

    # ------------------------------------------------------------------ #
    # Command API (called by the entities)                                 #
    # ------------------------------------------------------------------ #
    async def async_open(self, bar: str | None = None) -> None:
        await self._send_motion(self._position_command(1.0, bar))

    async def async_close(self, bar: str | None = None) -> None:
        await self._send_motion(self._position_command(0.0, bar))

    async def async_stop(self, bar: str | None = None) -> None:
        # RollerStop is bar-agnostic (halts whichever motor is running).
        await self._send_motion(ROLLER_STOP)

    async def async_set_position(self, fraction: float, bar: str | None = None) -> None:
        await self._send_motion(self._position_command(fraction, bar))

    async def async_set_tilt(self, tilt_percent: float) -> None:
        """tilt_percent 0..100 → cover tilt angle in the app's units."""
        tilt_percent = max(0.0, min(100.0, float(tilt_percent)))
        angle = round(tilt_percent / 100.0 * self.blind.max_tilt_angle)

        if self.blind.is_shangrila:
            frame = set_shangrila_tilt_command(self.blind, angle)
        elif self.blind.has_tilt_angle:
            current = self.data.position_fraction if self.data else 0.0
            frame = set_tilt_command(self.blind, angle, current or 0.0)
        else:  # no tilt capability — treat as position (safety)
            frame = self._position_command(tilt_percent / 100.0)
        await self._send_motion(frame)

    def _position_command(self, fraction: float, bar: str | None = None) -> bytes:
        """The exact move-to-position frame the app sends for this blind type.

        When ``bar`` is TOP or BOTTOM the frame targets that bar alone
        (topToPosition / bottomToPosition) — the two-entity path. With no bar
        the combined single-entity path is used: BA24 complement pair,
        double-servo moveBothBars, else the plain top-bar command.
        """
        if bar in (BarType.TOP, BarType.BOTTOM):
            return move_to_position_command(self.blind, fraction, bar=bar)
        if self.blind.blind_type == BlindTypes.BA24:
            return move_ba24_command(self.blind, fraction)
        if self.blind.is_double_servo or self.blind.blind_type == BlindTypes.DOUBLE_ROLLER:
            # Both bars travel to the same target fraction. Frame is the app's
            # moveBothBars (FE 03) carrying two raw shorts; encoding is our
            # scene-consistent one (raw_from_fraction) so HA's 0-100 target maps
            # back to the same 0-100 read after the motor settles.
            return move_both_bars_command(self.blind, fraction, fraction)
        return move_to_position_command(self.blind, fraction, bar=BarType.TOP)

    # ------------------------------------------------------------------ #
    # Notifications / state                                                 #
    # ------------------------------------------------------------------ #
    def _on_notify(self, _char: Any, data: bytearray) -> None:
        """Bleak notify callback — may run on the event loop thread already,
        but schedule via the loop to be safe from any thread."""
        raw = bytes(data)
        _LOGGER.debug("Bliss %s notify: %s", self.address, _hex(raw))
        state = parse_frame(raw, self.blind)
        if state is None:
            _LOGGER.debug(
                "Bliss %s frame not D1/D2 (dropped): status=0x%02X len=%d",
                self.address,
                raw[4] if len(raw) > 4 else 0x00,
                len(raw),
            )
            return
        self.hass.loop.call_soon_threadsafe(self._update_state, state)

    def _update_state(self, state: BlindState) -> None:
        self.data = state
        self.available = True
        self._notify_listeners()
        _LOGGER.debug(
            "Bliss %s: pos=%.2f tilt=%s batt=%s op=%s",
            self.address,
            state.position_fraction or 0.0,
            state.tilt_angle,
            state.battery,
            state.operating_status,
        )

    def _notify_listeners(self) -> None:
        for callback in tuple(self._listeners):
            callback()