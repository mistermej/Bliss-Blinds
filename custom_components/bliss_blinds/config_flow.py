"""Config flow for Bliss Blinds.

Discovery is name-based, like the app's scanner: the config flow shows only
advertised devices whose name matches ``^HD\\d{4}$`` (the BLE name IS the motor
model). The only required user input is the blind type — a dropdown of the
app's full 27-type list with ``Roller`` preselected.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BLIND_TYPE,
    CONF_MOTOR,
    CONF_NAME,
    CONF_TILT_OPEN,
    DEFAULT_BLIND_TYPE,
    DEFAULT_TILT_OPEN,
    DOMAIN,
)
from .protocol import ALL_BLIND_TYPES, BlindTypes, DISCOVERY_NAME_RE, find_motor_model

_LOGGER = logging.getLogger(__name__)


class BlissBlindsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Bliss Blinds."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_name: Optional[str] = None
        self._discovered_address: Optional[str] = None

    # Should only consider HD-prefixed connectable motors.
    @staticmethod
    def _valid_name(name: Optional[str]) -> bool:
        return bool(name and DISCOVERY_NAME_RE.match(name.strip()))

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Manual 'pick a device' step (also the add-integration entry point)."""
        discovered = [
            discovery
            for discovery in async_discovered_service_info(self.hass)
            if self._valid_name(discovery.name)
        ]

        if not discovered:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            match = next((d for d in discovered if d.address == address), None)
            if match is None:
                # Motor vanished between listing and selection.
                return self.async_abort(reason="no_devices_found")
            return await self._create_or_start(match)

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {d.address: f"{d.name} ({d.address})" for d in discovered}
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Triggered by the manifest bluetooth matcher when a motor advertises."""
        if not self._valid_name(discovery_info.name):
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address.lower())
        self._abort_if_unique_id_configured()
        return await self._create_or_start(discovery_info)

    async def _create_or_start(
        self, discovery: BluetoothServiceInfoBleak
    ) -> FlowResult:
        self._discovered_name = discovery.name.strip()
        self._discovered_address = discovery.address
        await self.async_set_unique_id(discovery.address.lower())
        self._abort_if_unique_id_configured()
        return await self.async_step_blind_type()

    async def async_step_blind_type(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Pick the blind type from the app's full list (default Roller)."""
        if user_input is not None:
            model = find_motor_model(self._discovered_name).name
            return self.async_create_entry(
                title=self._discovered_name or self._discovered_address,
                data={
                    CONF_ADDRESS: self._discovered_address,
                    CONF_NAME: self._discovered_name,
                    CONF_MOTOR: model,
                    CONF_BLIND_TYPE: user_input[CONF_BLIND_TYPE],
                },
            )

        return self.async_show_form(
            step_id="blind_type",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BLIND_TYPE, default=DEFAULT_BLIND_TYPE
                    ): vol.In({t: t for t in ALL_BLIND_TYPES})
                }
            ),
            description_placeholders={
                "name": self._discovered_name or "?",
                "serial_number": self._discovered_address or "?",
                "model": find_motor_model(self._discovered_name).name,
            },
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        # HA 2024.x+: OptionsFlow is constructed with NO arguments and the
        # config entry is resolved lazily via the handler/id the manager sets
        # after this returns. Passing config_entry to the constructor is what
        # historically made the Options menu 500.
        return BlissBlindsOptionsFlow()


class BlissBlindsOptionsFlow(OptionsFlow):
    """Options: correct the blind type later, or tune the ShangriLa tilt-open.

    NOTE: on HA 2024.x+ the base ``OptionsFlow`` has no ``__init__``; the
    ``config_entry`` is a read-only property resolved lazily from the flow's
    ``handler`` (the entry id), which the flow manager sets AFTER construction.
    Assigning ``self.config_entry`` in our own ``__init__`` raises
    ``AttributeError: can't set attribute`` -> the Options menu fails to load
    with a 500. So there is deliberately no ``__init__`` here and the entry is
    read via the property inside the step (safe: the manager populates
    ``hass``/``handler`` before any step runs).
    """

    async def async_step_init(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        entry = self.config_entry
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BLIND_TYPE,
                    default=entry.data.get(CONF_BLIND_TYPE, DEFAULT_BLIND_TYPE),
                ): vol.In({t: t for t in ALL_BLIND_TYPES}),
                vol.Optional(
                    CONF_TILT_OPEN,
                    default=entry.options.get(CONF_TILT_OPEN, DEFAULT_TILT_OPEN),
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0.0, max=0.999, message="tilt_open must be < 1.0"),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)