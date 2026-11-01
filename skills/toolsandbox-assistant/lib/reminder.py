"""A collection of tools which simulates common functions used for reminders.

Ported from ToolSandbox ``tools/reminder.py``.
"""

import datetime
from typing import Dict, List, Literal, Optional, Union, cast
from uuid import uuid4

from . import db
from ._common import NOT_GIVEN, NoDataError, NotGiven
from .validators import (
    typechecked,
    validate_latitude,
    validate_longitude,
    validate_timestamp,
)

_COLUMNS = [
    "reminder_id",
    "content",
    "creation_timestamp",
    "reminder_timestamp",
    "latitude",
    "longitude",
]


@typechecked
def add_reminder(
    content: str,
    reminder_timestamp: float,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> str:
    """Add a reminder.

    Returns:
        String format unique identifier for the reminder.
    """
    validate_timestamp(reminder_timestamp, "reminder_timestamp", float)
    validate_latitude(latitude, "latitude", Optional[float])
    validate_longitude(longitude, "longitude", Optional[float])

    reminder_id = str(uuid4())
    db.insert(
        "reminders",
        {
            "reminder_id": reminder_id,
            "content": content,
            "creation_timestamp": datetime.datetime.now().timestamp(),
            "reminder_timestamp": reminder_timestamp,
            "latitude": latitude,
            "longitude": longitude,
        },
    )
    return reminder_id


@typechecked
def modify_reminder(
    reminder_id: str,
    content: Union[str, NotGiven] = NOT_GIVEN,
    reminder_timestamp: Union[float, NotGiven] = NOT_GIVEN,
    latitude: Union[Optional[float], NotGiven] = NOT_GIVEN,
    longitude: Union[Optional[float], NotGiven] = NOT_GIVEN,
) -> None:
    """Modify a reminder with new information provided.

    Creation timestamp is updated automatically.

    Raises:
        ValueError:     When all arguments were None
        NoDataError:    When the reminder_id cannot be found in database
    """
    validate_timestamp(reminder_timestamp, "reminder_timestamp", Union[float, NotGiven])
    validate_latitude(latitude, "latitude", Union[Optional[float], NotGiven])
    validate_longitude(longitude, "longitude", Union[Optional[float], NotGiven])

    if all(x is NOT_GIVEN for x in [content, reminder_timestamp, latitude, longitude]):
        raise ValueError(
            "No update information given. At least one new field should be provided among "
            "[content, reminder_timestamp, latitude, longitude] in order to modify reminder"
        )
    if db.count("reminders", "reminder_id", reminder_id) == 0:
        raise NoDataError(f"No db entry matching reminder_id={reminder_id!r} found")

    updates: Dict[str, object] = {"creation_timestamp": datetime.datetime.now().timestamp()}
    for field, value in [
        ("content", content),
        ("reminder_timestamp", reminder_timestamp),
        ("latitude", latitude),
        ("longitude", longitude),
    ]:
        if value is not NOT_GIVEN:
            updates[field] = value
    db.update("reminders", "reminder_id", reminder_id, updates)


@typechecked
def search_reminder(
    reminder_id: Union[str, NotGiven] = NOT_GIVEN,
    content: Union[str, NotGiven] = NOT_GIVEN,
    creation_timestamp_lowerbound: Union[float, NotGiven] = NOT_GIVEN,
    creation_timestamp_upperbound: Union[float, NotGiven] = NOT_GIVEN,
    reminder_timestamp_lowerbound: Union[float, NotGiven] = NOT_GIVEN,
    reminder_timestamp_upperbound: Union[float, NotGiven] = NOT_GIVEN,
    latitude: Union[float, NotGiven] = NOT_GIVEN,
    longitude: Union[float, NotGiven] = NOT_GIVEN,
) -> List[
    Dict[
        Literal[
            "reminder_id",
            "content",
            "creation_timestamp",
            "reminder_timestamp",
            "latitude",
            "longitude",
        ],
        Union[str, float],
    ]
]:
    """Search for a reminder based on provided arguments.

    Fields match by exact value, fuzzy string matching (content, threshold 50),
    or timestamp range bounds.

    Raises:
        ValueError: When all arguments were not provided
    """
    validate_timestamp(
        creation_timestamp_lowerbound, "creation_timestamp_lowerbound", Union[float, NotGiven]
    )
    validate_timestamp(
        creation_timestamp_upperbound, "creation_timestamp_upperbound", Union[float, NotGiven]
    )
    validate_timestamp(
        reminder_timestamp_lowerbound, "reminder_timestamp_lowerbound", Union[float, NotGiven]
    )
    validate_timestamp(
        reminder_timestamp_upperbound, "reminder_timestamp_upperbound", Union[float, NotGiven]
    )
    validate_latitude(latitude, "latitude", Union[float, NotGiven])
    validate_longitude(longitude, "longitude", Union[float, NotGiven])

    rows = db.fetch_rows("reminders", _COLUMNS)
    matched = db.search(
        rows,
        [
            ("reminder_id", reminder_id, db.exact_match_filter, {}),
            ("content", content, db.fuzzy_match_filter, {"threshold": 50}),
            ("creation_timestamp", creation_timestamp_lowerbound, db.gt_eq_filter, {}),
            ("creation_timestamp", creation_timestamp_upperbound, db.lt_eq_filter, {}),
            ("reminder_timestamp", reminder_timestamp_lowerbound, db.gt_eq_filter, {}),
            ("reminder_timestamp", reminder_timestamp_upperbound, db.lt_eq_filter, {}),
            ("latitude", latitude, db.exact_match_filter, {}),
            ("longitude", longitude, db.exact_match_filter, {}),
        ],
    )
    return cast(list, matched)


@typechecked
def remove_reminder(reminder_id: str) -> None:
    """Remove a reminder given its unique identifier.

    Raises:
        NoDataError:    If the provided reminder_id was not found
    """
    if db.count("reminders", "reminder_id", reminder_id) == 0:
        raise NoDataError(f"No db entry matching reminder_id={reminder_id!r} found")
    db.delete("reminders", "reminder_id", reminder_id)
