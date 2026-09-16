"""Cover platform — one Blind cover per connected Hunter Douglas motor.

Double-bar blinds (HD3800 double-servo, DoubleRoller, *TDBU) get two covers,
one per bar (``TOP`` / ``BOTTOM``); everything else gets a single cover.
"""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BlissBlindCoordinator
from .protocol import BarType, OperatingStatus


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlissBlindCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.blind.has_two_bars:
        async_add_entities(
            [
                BlissCover(coordinator, bar=BarType.TOP),
                BlissCover(coordinator, bar=BarType.BOTTOM),
            ]
        )
    else:
        async_add_entities([BlissCover(coordinator)])


class BlissCover(CoverEntity):
    """A single cover for one bar (or the whole blind when bar is None).

    Position readout comes from the motor's one reported D1/D2 position — the
    protocol has no per-bar position word — but each bar is commanded
    independently (topToPosition / bottomToPosition).
    """

    _attr_has_entity_name = True
    _attr_device_class = CoverDeviceClass.BLIND

    def __init__(
        self, coordinator: BlissBlindCoordinator, bar: str | None = None
    ) -> None:
        self.coordinator = coordinator
        self._bar = bar
        if bar is None:
            self._attr_unique_id = f"{coordinator.address}_cover"
            self._attr_name = "Blind"
        else:
            label = "Top" if bar == BarType.TOP else "Bottom"
            self._attr_unique_id = f"{coordinator.address}_{bar.lower()}"
            self._attr_name = label

        features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )
        # Tilt rides the top motor; a bottom bar never has a tilt axis.
        if coordinator.blind.has_tilt_angle or coordinator.blind.is_shangrila:
            if bar != BarType.BOTTOM:
                features |= CoverEntityFeature.SET_TILT
        self._attr_supported_features = features

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def available(self) -> bool:
        return self.coordinator.available and self.coordinator.data is not None

    # -- position -------------------------------------------------------- #
    @property
    def current_cover_position(self) -> int | None:
        fraction = self.coordinator.data.position_fraction if self.coordinator.data else None
        if fraction is None:
            return None
        return min(100, max(0, round(fraction * 100)))

    @property
    def is_closed(self) -> bool:
        position = self.current_cover_position
        return position is not None and position <= 1

    @property
    def is_opening(self) -> bool:
        return self._moving_toward(open_direction=True)

    @property
    def is_closing(self) -> bool:
        return self._moving_toward(open_direction=False)

    def _moving_toward(self, open_direction: bool) -> bool:
        """App movement sense: raw motor UP is not 'open' for every blind."""
        if not self.coordinator.data:
            return False
        status = self.coordinator.data.operating_status
        moving_up_raw = status == OperatingStatus.MOVING_UP
        moving_down_raw = status == OperatingStatus.MOVING_DOWN
        if not (moving_up_raw or moving_down_raw):
            return False
        # fraction increases with raw position on inverse motors, decreases on normal.
        up_means_open = self.coordinator.blind.is_motor_direction_inverse
        return moving_up_raw == up_means_open if open_direction else moving_up_raw != up_means_open

    # -- tilt ------------------------------------------------------------- #
    @property
    def current_tilt_position(self) -> int | None:
        if not self.coordinator.data or self.coordinator.data.tilt_angle is None:
            return None
        max_angle = self.coordinator.blind.max_tilt_angle or 1
        angle = self.coordinator.data.tilt_angle
        fraction = max(0.0, min(1.0, angle / max_angle))
        return round(fraction * 100)

    # -- commands --------------------------------------------------------- #
    async def async_open_cover(self, **kwargs) -> None:
        await self.coordinator.async_open(self._bar)

    async def async_close_cover(self, **kwargs) -> None:
        await self.coordinator.async_close(self._bar)

    async def async_stop_cover(self, **kwargs) -> None:
        await self.coordinator.async_stop(self._bar)

    async def async_set_cover_position(self, **kwargs) -> None:
        position = kwargs.get("position")
        if position is None:
            return
        await self.coordinator.async_set_position(position / 100.0, self._bar)

    async def async_set_cover_tilt_position(self, **kwargs) -> None:
        tilt = kwargs.get("tilt_position")
        if tilt is None:
            return
        await self.coordinator.async_set_tilt(tilt)

    # -- housekeeping ----------------------------------------------------- #
    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))