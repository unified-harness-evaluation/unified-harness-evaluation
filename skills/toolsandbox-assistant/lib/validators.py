"""Validation utilities for common data types.

Ported from ``tool_sandbox.common.validators``. The currency-code validator
(only used by the dropped RapidAPI tools) is removed; everything else is
preserved, including the custom ``typechecked`` decorator so the ported tools
keep the same runtime type checking they had in the original sandbox.
"""

import inspect
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, Union, cast, get_args, get_origin

import phonenumbers

from ._common import NOT_GIVEN, NotGiven

T = TypeVar("T")
Numeric = TypeVar("Numeric", int, float)


def validate_type(value: Any, value_name: str, expected_type: Any) -> None:
    """Validate that ``value`` is of type ``expected_type``.

    Raises:
      TypeError if ``value`` is not of the expected type(s).
    """
    expected_types = set(
        get_args(expected_type)
        if get_origin(expected_type) is Union
        else (expected_type,)
    )
    expected_types = {get_origin(t) or t for t in expected_types}
    if type(value) in expected_types:
        return

    # Allow the natural int -> float upcast (PEP 484).
    if isinstance(value, int) and float in expected_types:
        return

    # Booleans are a subclass of integers.
    if isinstance(value, bool) and (int in expected_types or float in expected_types):
        return

    raise TypeError(
        f"Parameter '{value_name}' is of type '{type(value)}', but expected "
        f"'{expected_type}'."
    )


def typechecked(function: Callable[..., T]) -> Callable[..., T]:
    """Validate the parameter types of a function against its annotations."""

    @wraps(function)
    def typechecker(*args: Any, **kwargs: Any) -> Any:
        params = inspect.signature(function).parameters
        for arg, param in zip(args, params.values()):
            validate_type(arg, param.name, param.annotation)
        for name, kwarg in kwargs.items():
            param = params[name]
            validate_type(kwarg, param.name, param.annotation)
        return function(*args, **kwargs)

    return typechecker


def validate_range(
    value: Numeric,
    value_name: str,
    *,
    min_val: Optional[Numeric] = None,
    max_val: Optional[Numeric] = None,
) -> None:
    """Validate that ``value`` is within the optional inclusive [min, max]."""
    if min_val is not None and value < min_val:
        raise ValueError(
            f"Parameter '{value_name}' is smaller than its valid range minimum of {min_val}."
        )
    if max_val is not None and value > max_val:
        raise ValueError(
            f"Parameter '{value_name}' is larger than its valid range maximum of {max_val}."
        )


def validate_type_range(
    value: Any,
    value_name: str,
    expected_type: Any,
    *,
    min_val: Optional[Numeric] = None,
    max_val: Optional[Numeric] = None,
) -> None:
    """Validate parameter type and (for numerics) range."""
    validate_type(value, value_name, expected_type)
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        validate_range(cast(Numeric, value), value_name, min_val=min_val, max_val=max_val)


def validate_timestamp(timestamp: Any, name: str, expected_type: Any) -> None:
    """Validate a POSIX timestamp's range so a unit mistake (s vs ms) is caught."""
    TS_JAN_1_1980 = 315529200.0  # seconds
    TS_JAN_1_2050 = 2524604400.0  # seconds
    validate_type_range(
        timestamp, name, expected_type, min_val=TS_JAN_1_1980, max_val=TS_JAN_1_2050
    )


def validate_latitude(latitude: Any, name: str, expected_type: Any) -> None:
    """Validate the type and range of a latitude in degrees."""
    validate_type_range(latitude, name, expected_type, min_val=-90.0, max_val=90.0)


def validate_longitude(longitude: Any, name: str, expected_type: Any) -> None:
    """Validate the type and range of a longitude in degrees."""
    validate_type_range(longitude, name, expected_type, min_val=-180.0, max_val=180.0)


def validate_phone_number(phone_number: Union[str, NotGiven]) -> None:
    """Validate that a string parses as a phone number.

    If it is ``NOT_GIVEN`` validation is skipped.

    Raises:
        NumberParseException:  If the phone number cannot be parsed.
    """
    if phone_number is not NOT_GIVEN:
        assert not isinstance(phone_number, NotGiven)
        phonenumbers.parse(phone_number)
