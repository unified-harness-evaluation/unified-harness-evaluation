"""A collection of tools which simulates common functions used for contact book.

Ported from ToolSandbox ``tools/contact.py``: same tool names, signatures and
behavior, with the Polars ``ExecutionContext`` swapped for SQLite (``db.py``).
"""

from typing import Dict, List, Literal, Optional, Union, cast
from uuid import uuid4

from . import db
from ._common import NOT_GIVEN, DuplicateError, NoDataError, NotGiven
from .validators import typechecked, validate_phone_number, validate_type

_COLUMNS = ["person_id", "name", "phone_number", "relationship", "is_self"]


@typechecked
def add_contact(
    name: str,
    phone_number: str,
    relationship: Optional[str] = None,
    is_self: bool = False,
) -> str:
    """Add a new contact person to contact database. Entries with identical
    information are allowed, and will be assigned different person_ids.

    Args:
        name:           Name of contact person
        phone_number:   Phone number of contact person
        relationship:   Optional, relationship between user and this contact
        is_self:        Optional. Defaults to False. Should be set to True if the
                        contact corresponds to the current user.

    Returns:
        String format unique identifier for the contact person.

    Raises:
        DuplicateError: When self entry already exists, and we are adding a new one
    """
    validate_phone_number(phone_number)
    person_id = str(uuid4())
    if is_self and search_contacts(is_self=True):
        raise DuplicateError("Self entry already exists. Cannot add another one.")
    db.insert(
        "contacts",
        {
            "person_id": person_id,
            "name": name,
            "phone_number": phone_number,
            "relationship": relationship,
            "is_self": is_self,
        },
    )
    return person_id


@typechecked
def modify_contact(
    person_id: str,
    name: Union[str, NotGiven] = NOT_GIVEN,
    phone_number: Union[str, NotGiven] = NOT_GIVEN,
    relationship: Union[str, NotGiven] = NOT_GIVEN,
    is_self: Union[bool, NotGiven] = NOT_GIVEN,
) -> None:
    """Modify a contact entry with new information provided.

    Raises:
        ValueError:     When all arguments were None
        NoDataError:    When the person_id cannot be found in database
        DuplicateError: When modifying an entry to self with an existing self
    """
    if all(x is NOT_GIVEN for x in [name, phone_number, relationship, is_self]):
        raise ValueError(
            "No update information given. At least one new field should be provided among "
            "[name, phone_number, relationship, is_self] in order to modify contact"
        )
    validate_phone_number(phone_number)
    # Make sure there won't be duplicate self
    self_entries = search_contacts(is_self=True)
    if self_entries and is_self and self_entries[0]["person_id"] != person_id:
        raise DuplicateError("Self entry already exists. Cannot add another one.")
    if db.count("contacts", "person_id", person_id) == 0:
        raise NoDataError(f"No db entry matching person_id={person_id!r} found")

    updates: Dict[str, object] = {}
    for field, value in [
        ("name", name),
        ("phone_number", phone_number),
        ("relationship", relationship),
        ("is_self", is_self),
    ]:
        if value is not NOT_GIVEN:
            updates[field] = value
    db.update("contacts", "person_id", person_id, updates)


@typechecked
def remove_contact(person_id: str) -> None:
    """Remove an existing contact person from contact database.

    Raises:
        NoDataError:    If the provided person_id was not found
    """
    validate_type(person_id, "person_id", str)
    if db.count("contacts", "person_id", person_id) == 0:
        raise NoDataError(f"No db entry matching person_id={person_id!r} found")
    db.delete("contacts", "person_id", person_id)


def search_contacts(
    person_id: Union[str, NotGiven] = NOT_GIVEN,
    name: Union[str, NotGiven] = NOT_GIVEN,
    phone_number: Union[str, NotGiven] = NOT_GIVEN,
    relationship: Union[str, NotGiven] = NOT_GIVEN,
    is_self: Union[bool, NotGiven] = NOT_GIVEN,
) -> List[
    Dict[Literal["person_id", "name", "phone_number", "relationship", "is_self"], str]
]:
    """Search for a contact person based on provided arguments.

    Each field is matched by exact value or fuzzy string matching (name and
    relationship). Results contain entries matching all provided criteria.

    Raises:
        ValueError: When all arguments were not provided
    """
    validate_phone_number(phone_number)
    rows = db.fetch_rows("contacts", _COLUMNS)
    matched = db.search(
        rows,
        [
            ("person_id", person_id, db.exact_match_filter, {}),
            ("name", name, db.fuzzy_match_filter, {}),
            ("phone_number", phone_number, db.exact_match_filter, {}),
            ("relationship", relationship, db.fuzzy_match_filter, {"threshold": 90}),
            ("is_self", is_self, db.exact_match_filter, {}),
        ],
    )
    return cast(list, matched)
