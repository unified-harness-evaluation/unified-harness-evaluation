"""A collection of tools which simulates utility functions.

Ported from ToolSandbox ``tools/utilities.py``: timestamp math, unit conversion
(``pint``), lat/lon distance (``geopy``), and US holiday lookup (``holidays``).
``search_holiday`` still simulates a web-backed tool by requiring wifi.
"""

import datetime
from typing import Dict, Literal, Optional, cast

import geopy.distance  # type: ignore
import holidays
import pint
from pint import UndefinedUnitError
from rapidfuzz import fuzz, utils

from .setting import get_wifi_status
from .validators import (
    typechecked,
    validate_latitude,
    validate_longitude,
    validate_timestamp,
)


@typechecked
def get_current_timestamp() -> float:
    """Get current POSIX timestamp."""
    return datetime.datetime.now().timestamp()


@typechecked
def timestamp_to_datetime_info(
    timestamp: float,
) -> Dict[Literal["year", "month", "day", "hour", "minute", "second", "isoweekday"], int]:
    """Convert POSIX timestamp to a dictionary of date time information."""
    validate_timestamp(timestamp, "timestamp", float)
    target_datetime = datetime.datetime.fromtimestamp(timestamp)
    return {
        "year": target_datetime.year,
        "month": target_datetime.month,
        "day": target_datetime.day,
        "hour": target_datetime.hour,
        "minute": target_datetime.minute,
        "second": target_datetime.second,
        "isoweekday": target_datetime.isoweekday(),
    }


@typechecked
def datetime_info_to_timestamp(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> float:
    """Convert date time information to POSIX timestamp."""
    return datetime.datetime(
        year=year, month=month, day=day, hour=hour, minute=minute, second=second
    ).timestamp()


@typechecked
def shift_timestamp(
    timestamp: float,
    weeks: int = 0,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
) -> float:
    """Shift a POSIX timestamp by the provided deltas (may be negative)."""
    validate_timestamp(timestamp, "timestamp", float)
    target_datetime = datetime.datetime.fromtimestamp(timestamp) + datetime.timedelta(
        weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return target_datetime.timestamp()


@typechecked
def timestamp_diff(
    timestamp_0: float, timestamp_1: float
) -> Dict[Literal["days", "seconds"], int]:
    """Return timestamp_1 - timestamp_0 represented in days and seconds."""
    validate_timestamp(timestamp_0, "timestamp_0", float)
    validate_timestamp(timestamp_1, "timestamp_1", float)
    time_delta = datetime.datetime.fromtimestamp(timestamp_1) - datetime.datetime.fromtimestamp(
        timestamp_0
    )
    return {"days": time_delta.days, "seconds": time_delta.seconds}


@typechecked
def seconds_to_hours_minutes_seconds(
    seconds: float,
) -> Dict[Literal["hour", "minute", "second"], int]:
    """Convert total seconds past 0:00 into hours, minutes and seconds."""
    target_datetime = datetime.datetime.fromtimestamp(seconds)
    return {
        "hour": target_datetime.hour,
        "minute": target_datetime.minute,
        "second": target_datetime.second,
    }


@typechecked
def unit_conversion(amount: float, from_unit: str, to_unit: str) -> float:
    """Convert an amount from one unit to another (common English unit names).

    Raises:
        UndefinedUnitError: If unable to parse the unit names provided
        ValueError:         If unable to convert between provided units
    """
    try:
        return cast(float, pint.Quantity(amount, from_unit).to(to_unit).magnitude)
    except UndefinedUnitError:
        return cast(
            float, pint.Quantity(amount, from_unit.lower()).to(to_unit.lower()).magnitude
        )


@typechecked
def calculate_lat_lon_distance(
    latitude_0: float, longitude_0: float, latitude_1: float, longitude_1: float
) -> float:
    """Calculate the distance in kilometers between 2 lat/lon pairs."""
    validate_latitude(latitude_0, name="latitude_0", expected_type=float)
    validate_latitude(latitude_1, name="latitude_1", expected_type=float)
    validate_longitude(longitude_0, name="longitude_0", expected_type=float)
    validate_longitude(longitude_1, name="longitude_1", expected_type=float)
    return cast(
        float,
        geopy.distance.distance(
            (latitude_0, longitude_0), (latitude_1, longitude_1)
        ).kilometers,
    )


@typechecked
def search_holiday(holiday_name: str, year: Optional[int] = None) -> Optional[float]:
    """Search for a US holiday by name; return its POSIX timestamp or None.

    Simulates a web-backed tool by requiring wifi.

    Raises:
        ConnectionError: If wifi is not enabled
    """
    if not get_wifi_status():
        raise ConnectionError("Wifi is not enabled")
    if year is None:
        year = datetime.datetime.now().year
    holiday_matches = sorted(
        (
            (
                fuzz.partial_ratio(holiday_name, name, processor=utils.default_process),
                date,
                name,
            )
            for date, name in holidays.country_holidays(country="US", years=year).items()
        ),
        reverse=True,
    )
    if holiday_matches and holiday_matches[0][0] > 90:
        return datetime.datetime.combine(
            holiday_matches[0][1], datetime.datetime.min.time()
        ).timestamp()
    return None
