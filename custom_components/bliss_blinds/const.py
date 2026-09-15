"""Constants for the Bliss Blinds Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta

from .protocol import (  # noqa: F401  (re-exported for other modules)
    COMMAND_CHARACTERISTIC_UUID,
    DISCOVERY_NAME_RE,
    RESPONSE_CHARACTERISTIC_UUID,
    SERVICE_UUID,
    BlindConfig,
    BlindTypes,
)

DOMAIN = "bliss_blinds"

PLATFORMS = ["cover", "sensor"]

# Config-entry data keys.
CONF_ADDRESS = "address"
CONF_NAME = "name"
CONF_MOTOR = "motor_model"      # motor model derived from the BLE name
CONF_BLIND_TYPE = "blind_type"  # user-picked from the app's full list

# Config-entry option keys.
CONF_TILT_OPEN = "tilt_open"    # ShangriLa open-fraction; cloud-free default 0.0

DEFAULT_BLIND_TYPE = BlindTypes.ROLLER
DEFAULT_TILT_OPEN = 0.0

# Connection / polling tuning.
CONNECT_TIMEOUT = 15.0
WRITE_GAP = 0.025               # app ConnectionManager ≥ 25 ms between writes
POLL_INTERVAL = timedelta(seconds=60)
RECONNECT_INTERVAL = timedelta(seconds=15)

# Diagnostics.
LOGGER_NAME = __name__

# Manufacturer shown in the device registry.
MANUFACTURER = "Hunter Douglas"