"""A collection of tools which simulates common functions used for messaging.

Ported from ToolSandbox ``tools/messaging.py``. Preserves the cross-tool calls
into contacts (find self / recipient) and settings (cellular gating).
"""

import datetime
from typing import Dict, List, Literal, Union, cast
from uuid import uuid4

from . import db
from ._common import NOT_GIVEN, DuplicateError, NotGiven
from .contact import search_contacts
from .setting import get_cellular_service_status
from .validators import typechecked, validate_phone_number, validate_timestamp

_COLUMNS = [
    "message_id",
    "sender_person_id",
    "sender_phone_number",
    "recipient_person_id",
    "recipient_phone_number",
    "content",
    "creation_timestamp",
]


@typechecked
def send_message_with_phone_number(phone_number: str, content: str) -> str:
    """Send a message to a recipient using phone_number.

    Returns:
        String format unique identifier for the message.

    Raises:
        ValueError:         If less than or more than 1 self entry was found
        ConnectionError:    If cellular service is not on
    """
    validate_phone_number(phone_number)
    if not get_cellular_service_status():
        raise ConnectionError("Cellular service is not enabled")
    message_id = str(uuid4())
    # Find self
    self_data = search_contacts(is_self=True)
    if len(self_data) != 1:
        raise DuplicateError(
            "1 and only 1 self entry should exist in contacts database, instead "
            f"found {len(self_data)}"
        )
    # Find recipient, not guaranteed to exist
    recipient_data = search_contacts(phone_number=phone_number)
    recipient_person_id = (
        None if len(recipient_data) == 0 else recipient_data[0]["person_id"]
    )
    db.insert(
        "messages",
        {
            "message_id": message_id,
            "sender_person_id": self_data[0]["person_id"],
            "sender_phone_number": self_data[0]["phone_number"],
            "recipient_person_id": recipient_person_id,
            "recipient_phone_number": phone_number,
            "content": content,
            "creation_timestamp": datetime.datetime.now().timestamp(),
        },
    )
    return message_id


@typechecked
def search_messages(
    message_id: Union[str, NotGiven] = NOT_GIVEN,
    sender_person_id: Union[str, NotGiven] = NOT_GIVEN,
    sender_phone_number: Union[str, NotGiven] = NOT_GIVEN,
    recipient_person_id: Union[str, NotGiven] = NOT_GIVEN,
    recipient_phone_number: Union[str, NotGiven] = NOT_GIVEN,
    content: Union[str, NotGiven] = NOT_GIVEN,
    creation_timestamp_lowerbound: Union[float, NotGiven] = NOT_GIVEN,
    creation_timestamp_upperbound: Union[float, NotGiven] = NOT_GIVEN,
) -> List[
    Dict[
        Literal[
            "message_id",
            "sender_person_id",
            "sender_phone_number",
            "recipient_person_id",
            "recipient_phone_number",
            "content",
            "creation_timestamp",
        ],
        Union[str, float],
    ]
]:
    """Search for a message based on provided arguments.

    Fields match by exact value, fuzzy string matching (content, threshold 50),
    or timestamp range bounds. Results match all provided criteria.

    Raises:
        ValueError: When all arguments were not provided
    """
    validate_phone_number(sender_phone_number)
    validate_phone_number(recipient_phone_number)
    validate_timestamp(
        creation_timestamp_lowerbound, "creation_timestamp_lowerbound", Union[float, NotGiven]
    )
    validate_timestamp(
        creation_timestamp_upperbound, "creation_timestamp_upperbound", Union[float, NotGiven]
    )
    rows = db.fetch_rows("messages", _COLUMNS)
    matched = db.search(
        rows,
        [
            ("message_id", message_id, db.exact_match_filter, {}),
            ("sender_person_id", sender_person_id, db.exact_match_filter, {}),
            ("sender_phone_number", sender_phone_number, db.exact_match_filter, {}),
            ("recipient_person_id", recipient_person_id, db.exact_match_filter, {}),
            ("recipient_phone_number", recipient_phone_number, db.exact_match_filter, {}),
            ("content", content, db.fuzzy_match_filter, {"threshold": 50}),
            ("creation_timestamp", creation_timestamp_lowerbound, db.gt_eq_filter, {}),
            ("creation_timestamp", creation_timestamp_upperbound, db.lt_eq_filter, {}),
        ],
    )
    return cast(list, matched)
