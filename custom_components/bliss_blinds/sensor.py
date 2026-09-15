"""Sensor platform.

* **battery** — the only battery info the D1/D2 frame carries is a coarse
  2-bit level (normal / low / none / unknown). There is never a percentage
  in the protocol (NordicMotorStatusParser.js is error-code only).
* **nordic_error** (HD3600 / HD3900, off by default) — raw Nordic error code,
  normalized exactly like the app (0 → 0, 1-13 kept, everything else → 10).
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BlissBlindCoordinator
from .protocol import BatteryLevel


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlissBlindCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [BlissBatterySensor(coordinator)]
    if coordinator.blind.motor.nordic:
        entities.append(BlissNordicErrorSensor(coordinator))
    async_add_entities(entities)


class BlissBatterySensor(SensorEntity):
    """Coarse 4-state battery — no percentage exists in the protocol."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = [
        BatteryLevel.NORMAL,
        BatteryLevel.LOW,
        BatteryLevel.NONE,
        BatteryLevel.UNKNOWN,
    ]

    def __init__(self, coordinator: BlissBlindCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_battery"

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def available(self) -> bool:
        return self.coordinator.available and self.coordinator.data is not None

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.battery

    @property
    def icon(self) -> str:
        mapping = {
            BatteryLevel.NORMAL: "mdi:battery",
            BatteryLevel.LOW: "mdi:battery-low",
            BatteryLevel.NONE: "mdi:battery-alert-variant-outline",
            BatteryLevel.UNKNOWN: "mdi:battery-unknown",
        }
        value = self.native_value
        return mapping.get(value, "mdi:battery-unknown")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


class BlissNordicErrorSensor(SensorEntity):
    """Diagnostic Nordic error code (HD3600/HD3900); off by default."""

    _attr_has_entity_name = True
    _attr_name = "Nordic error"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: BlissBlindCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_nordic_error"

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def available(self) -> bool:
        return self.coordinator.available and self.coordinator.data is not None

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        # Empty/absent field reads as no error (0).
        return self.coordinator.data.nordic_error

    @property
    def icon(self) -> str:
        return "mdi:alert-circle-outline"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )