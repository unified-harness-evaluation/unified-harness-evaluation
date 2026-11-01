"""A collection of tools which simulates common functions used for settings.

Ported from ToolSandbox ``tools/setting.py``. Device settings are a single row
in the ``device_settings`` table.
"""

from typing import Dict, Literal, cast

from . import db
from .validators import validate_type

_BOOLEAN_SETTINGS = {"cellular", "wifi", "location_service", "low_battery_mode"}


def _require_settings() -> Dict[str, object]:
    row = db.get_settings_row()
    if row is None:
        raise KeyError("No device settings row found")
    return row


def set_boolean_settings(setting_name: str, on: bool) -> None:
    """Utility for setting boolean settings. Not exposed as a tool.

    Raises:
        KeyError:   If setting_name is not a boolean setting column
        ValueError: If the setting is already in the requested state
    """
    validate_type(setting_name, "setting_name", str)
    validate_type(on, "on", bool)

    row = _require_settings()
    if setting_name not in _BOOLEAN_SETTINGS:
        raise KeyError(f"{setting_name} is not a boolean column")
    if bool(row[setting_name]) == on:
        raise ValueError(f"{setting_name} already {('disabled', 'enabled')[int(on)]}")
    db.update("device_settings", "device_id", cast(str, row["device_id"]), {setting_name: on})


def get_boolean_settings(setting_name: str) -> bool:
    """Utility for getting boolean settings. Not exposed as a tool.

    Raises:
        KeyError:   If setting_name is not a boolean setting column
    """
    validate_type(setting_name, "setting_name", str)
    row = _require_settings()
    if setting_name not in _BOOLEAN_SETTINGS:
        raise KeyError(f"{setting_name} is not a boolean column")
    return bool(row[setting_name])


def set_low_battery_mode_status(on: bool) -> None:
    """Enable / Disable low battery mode.

    Raises:
        ValueError: If low battery mode is already turned on / off
    """
    validate_type(on, "on", bool)
    set_boolean_settings(setting_name="low_battery_mode", on=on)
    # Automatically turn off dependent services when low battery mode is on.
    if on:
        for dependent_setting in ["cellular", "wifi", "location_service"]:
            try:
                set_boolean_settings(dependent_setting, on=False)
            except ValueError:
                pass


def get_low_battery_mode_status() -> bool:
    """Request low battery mode status."""
    return get_boolean_settings("low_battery_mode")


def set_location_service_status(on: bool) -> None:
    """Enable / Disable location service.

    Raises:
        ValueError:      If location service is already turned on / off
        PermissionError: If low battery mode is on
    """
    if on and get_low_battery_mode_status():
        raise PermissionError("Location service cannot be turned on in low battery mode")
    set_boolean_settings(setting_name="location_service", on=on)


def get_location_service_status() -> bool:
    """Request location service status."""
    return get_boolean_settings("location_service")


def set_cellular_service_status(on: bool) -> None:
    """Enable / Disable cellular service.

    Raises:
        ValueError:      If cellular service is already turned on / off
        PermissionError: If low battery mode is on
    """
    validate_type(on, "on", bool)
    if on and get_low_battery_mode_status():
        raise PermissionError("Cellular service cannot be turned on in low battery mode")
    set_boolean_settings(setting_name="cellular", on=on)


def get_cellular_service_status() -> bool:
    """Request cellular service status."""
    return get_boolean_settings("cellular")


def set_wifi_status(on: bool) -> None:
    """Enable / Disable wifi.

    Raises:
        ValueError:      If wifi is already turned on / off
        PermissionError: If low battery mode is on
    """
    validate_type(on, "on", bool)
    if on and get_low_battery_mode_status():
        raise PermissionError("Wifi cannot be turned on in low battery mode")
    set_boolean_settings(setting_name="wifi", on=on)


def get_wifi_status() -> bool:
    """Request wifi status."""
    return get_boolean_settings("wifi")


def get_current_location() -> Dict[Literal["latitude", "longitude"], float]:
    """Request current location latitude and longitude.

    Raises:
        PermissionError: If location service is not turned on
    """
    if not get_location_service_status():
        raise PermissionError("Location service is not enabled.")
    row = _require_settings()
    return {
        "latitude": cast(float, row["latitude"]),
        "longitude": cast(float, row["longitude"]),
    }
