import json
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from tau2.environment.db import DB

FlightType = Literal["round_trip", "one_way"]
CabinClass = Literal["business", "economy", "basic_economy"]
Insurance = Literal["yes", "no"]

# ---------------------------------------------------------------------------
# Unified world.db backing store
# ---------------------------------------------------------------------------
# State lives in the unified per-task `world.db` (seeded fresh into /workspace by
# the runner), not the per-skill db.json. This skill owns the flights and
# flight_bookings tagged `source_skill = 'tau2Airline'` plus the users whose
# `skill_ids_json` names this skill. `FlightDB.load()` builds the nested tree from
# that scoped slice; `FlightDB.save()` writes mutations back. Override the DB path
# with CUGA_WORLD_DB.

SOURCE_SKILL = "tau2Airline"
DB_PATH_ENV = "CUGA_WORLD_DB"

# world.db `users.loyalty_tier` uses a shared vocabulary; tau2 membership is a
# closed set. "standard" (the shared default) is tau2's "regular".
_TIER_TO_MEMBERSHIP = {"standard": "regular"}
_MEMBERSHIP_TO_TIER = {"regular": "standard"}

# world.db is cross-domain: a few reservation rows carry cabin/trip values from
# other skills' vocabularies (e.g. "premium_economy"). tau2's schema is a closed
# set, so coerce anything outside it to the nearest valid tau2 value on read.
_TAU2_CABINS = {"business", "economy", "basic_economy"}
_TAU2_FLIGHT_TYPES = {"one_way", "round_trip"}


def _world_db_path() -> Path:
    override = os.environ.get(DB_PATH_ENV)
    if override:
        return Path(override)
    for candidate in (Path.cwd() / "world.db", Path("/workspace/world.db")):
        if candidate.exists():
            return candidate
    return Path.cwd() / "world.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_world_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _split_name(full: str) -> Dict[str, str]:
    parts = (full or "").split(" ", 1)
    return {"first_name": parts[0], "last_name": parts[1] if len(parts) > 1 else ""}



MembershipLevel = Annotated[
    Literal["gold", "silver", "regular"], Field(description="Membership level")
]


class AirportCode(BaseModel):
    iata: str = Field(description="IATA code")
    city: str = Field(description="City name")


AirportInfo = Annotated[list[AirportCode], Field(description="Airport information")]


class Name(BaseModel):
    first_name: str = Field(description="The person's first name")
    last_name: str = Field(description="The person's last name")


class Address(BaseModel):
    address1: str = Field(description="Primary address line")
    address2: Optional[str] = Field(
        None, description="Secondary address line (optional)"
    )
    city: str = Field(description="City name")
    country: str = Field(description="Country name")
    state: str = Field(description="State or province name")
    zip: str = Field(description="Postal code")


# Payment Related Models
class Payment(BaseModel):
    payment_id: str = Field(description="Unique identifier for the payment")
    amount: int = Field(description="Payment amount in dollars")


class PaymentMethodBase(BaseModel):
    source: str = Field(description="Type of payment method")
    id: str = Field(description="Unique identifier for the payment method")


class CreditCard(PaymentMethodBase):
    source: Literal["credit_card"] = Field(
        description="Indicates this is a credit card payment method"
    )
    brand: str = Field(description="Credit card brand (e.g., visa, mastercard)")
    last_four: str = Field(description="Last four digits of the credit card")


class GiftCard(PaymentMethodBase):
    source: Literal["gift_card"] = Field(
        description="Indicates this is a gift card payment method"
    )
    amount: float = Field(description="Gift card value amount")
    id: str = Field(description="Unique identifier for the gift card")


class Certificate(PaymentMethodBase):
    source: Literal["certificate"] = Field(
        description="Indicates this is a certificate payment method"
    )
    amount: float = Field(description="Certificate value amount")


PaymentMethod = Union[CreditCard, GiftCard, Certificate]


class Passenger(BaseModel):
    first_name: str = Field(description="Passenger's first name")
    last_name: str = Field(description="Passenger's last name")
    dob: str = Field(description="Date of birth in YYYY-MM-DD format")


SeatPrices = Annotated[
    dict[CabinClass, int], Field(description="Prices for different cabin classes")
]
AvailableSeats = Annotated[
    dict[CabinClass, int],
    Field(description="Available seats for different cabin classes"),
]


class FlightDateStatusAvailable(BaseModel):
    status: Literal["available"] = Field(
        description="Indicates flight is available for booking"
    )
    available_seats: AvailableSeats = Field(description="Available seats by class")
    prices: SeatPrices = Field(description="Current prices by class")


class FlightDataStatusOnTime(BaseModel):
    status: Literal["on time"] = Field(description="Indicates flight is on time")
    estimated_departure_time_est: str = Field(
        description="Estimated departure time in EST in the format YYYY-MM-DDTHH:MM:SS, e.g 2024-05-15T06:04:00"
    )
    estimated_arrival_time_est: str = Field(
        description="Estimated arrival time in EST in the format YYYY-MM-DDTHH:MM:SS, e.g 2024-05-15T07:30:00"
    )


class FlightDataStatusFlying(BaseModel):
    status: Literal["flying"] = Field(description="Indicates flight is in flight")
    actual_departure_time_est: str = Field(
        description="Actual departure time in EST in the format YYYY-MM-DDTHH:MM:SS, e.g 2024-05-15T06:04:00"
    )
    estimated_arrival_time_est: str = Field(
        description="Estimated arrival time in EST in the format YYYY-MM-DDTHH:MM:SS, e.g 2024-05-15T07:30:00"
    )


class FlightDateStatusLanded(BaseModel):
    status: Literal["landed"] = Field(description="Indicates flight has landed")
    actual_departure_time_est: str = Field(
        description="Actual departure time in EST in the format YYYY-MM-DDTHH:MM:SS, e.g 2024-05-15T06:04:00"
    )
    actual_arrival_time_est: str = Field(
        description="Actual arrival time in EST in the format YYYY-MM-DDTHH:MM:SS, e.g 2024-05-15T07:30:00"
    )


class FlightDateStatusCancelled(BaseModel):
    status: Literal["cancelled"] = Field(description="Indicates flight was cancelled")


class FlightDateStatusDelayed(BaseModel):
    status: Literal["delayed"] = Field(description="Indicates flight was delayed")
    estimated_departure_time_est: str = Field(
        description="Estimated departure time in EST in the format YYYY-MM-DDTHH:MM:SS, e.g 2024-05-15T06:04:00"
    )
    estimated_arrival_time_est: str = Field(
        description="Estimated arrival time in EST in the format YYYY-MM-DDTHH:MM:SS, e.g 2024-05-15T07:30:00"
    )


FlightDateStatus = Union[
    FlightDateStatusAvailable,
    FlightDateStatusLanded,
    FlightDateStatusCancelled,
    FlightDateStatusDelayed,
    FlightDataStatusFlying,
    FlightDataStatusOnTime,
]


class FlightBase(BaseModel):
    flight_number: str = Field(description="Unique flight identifier")
    origin: str = Field(description="IATA code for origin airport")
    destination: str = Field(description="IATA code for destination airport")


class Flight(FlightBase):
    scheduled_departure_time_est: str = Field(
        description="Scheduled departure time in EST in the format HH:MM:SS, e.g 06:00:00"
    )
    scheduled_arrival_time_est: str = Field(
        description="Scheduled arrival time in EST in the format HH:MM:SS, e.g 07:00:00"
    )
    dates: Dict[str, FlightDateStatus] = Field(
        description="Flight status by date (YYYY-MM-DD)"
    )


class DirectFlight(FlightBase):
    status: Literal["available"] = Field(
        description="Indicates flight is available for booking"
    )
    scheduled_departure_time_est: str = Field(
        description="Scheduled departure time in EST in the format HH:MM:SS, e.g 06:00:00"
    )
    scheduled_arrival_time_est: str = Field(
        description="Scheduled arrival time in EST in the format HH:MM:SS, e.g 07:00:00"
    )
    date: Optional[str] = Field(
        description="Flight date in YYYY-MM-DD format", default=None
    )
    available_seats: AvailableSeats = Field(description="Available seats by class")
    prices: SeatPrices = Field(description="Current prices by class")


class ReservationFlight(FlightBase):
    date: str = Field(description="Flight date in YYYY-MM-DD format")
    price: int = Field(description="Flight price in dollars.")


class FlightInfo(BaseModel):
    flight_number: str = Field(description="Flight number, such as 'HAT001'.")
    date: str = Field(
        description="The date for the flight in the format 'YYYY-MM-DD', such as '2024-05-01'."
    )


class User(BaseModel):
    user_id: str = Field(description="Unique identifier for the user")
    name: Name = Field(description="User's full name")
    address: Address = Field(description="User's address information")
    email: str = Field(description="User's email address")
    dob: str = Field(
        description="User's date of birth in the format YYYY-MM-DD, e.g 1990-04-05"
    )
    payment_methods: Dict[str, PaymentMethod] = Field(
        description="User's saved payment methods"
    )
    saved_passengers: List[Passenger] = Field(
        description="User's saved passenger information"
    )
    membership: MembershipLevel = Field(description="User's membership level")
    reservations: List[str] = Field(description="List of user's reservation IDs")


# Reservation Models
class Reservation(BaseModel):
    reservation_id: str = Field(description="Unique identifier for the reservation")
    user_id: str = Field(description="ID of the user who made the reservation")
    origin: str = Field(description="IATA code for trip origin")
    destination: str = Field(description="IATA code for trip destination")
    flight_type: FlightType = Field(description="Type of trip")
    cabin: CabinClass = Field(description="Selected cabin class")
    flights: List[ReservationFlight] = Field(
        description="List of flights in the reservation"
    )
    passengers: List[Passenger] = Field(
        description="List of passengers on the reservation"
    )
    payment_history: List[Payment] = Field(
        description="History of payments for this reservation"
    )
    created_at: str = Field(
        description="Timestamp when reservation was created in the format YYYY-MM-DDTHH:MM:SS"
    )
    total_baggages: int = Field(description="Total number of bags in reservation")
    nonfree_baggages: int = Field(description="Number of paid bags in reservation")
    insurance: Insurance = Field(description="Whether travel insurance was purchased")
    status: Optional[Literal["cancelled"]] = Field(
        description="Status of the reservation", default=None
    )


class FlightDB(DB):
    """Database of all flights, users, and reservations."""

    flights: Dict[str, Flight] = Field(
        description="Dictionary of all flights indexed by flight number"
    )
    users: Dict[str, User] = Field(
        description="Dictionary of all users indexed by user ID"
    )
    reservations: Dict[str, Reservation] = Field(
        description="Dictionary of all reservations indexed by reservation ID"
    )

    def get_statistics(self) -> dict[str, Any]:
        """Get the statistics of the database."""
        num_flights = len(self.flights)
        num_flights_instances = sum(
            len(flight.dates) for flight in self.flights.values()
        )
        num_users = len(self.users)
        num_reservations = len(self.reservations)
        return {
            "num_flights": num_flights,
            "num_flights_instances": num_flights_instances,
            "num_users": num_users,
            "num_reservations": num_reservations,
        }

    @classmethod
    def load(cls, path: Optional[str] = None) -> "FlightDB":
        """Build the scoped tau2 airline tree from the unified world.db.

        `path` is accepted for back-compat (the old db.json seed) but ignored;
        data is read from world.db (see CUGA_WORLD_DB). Flights/reservations are
        scoped by `source_skill='tau2Airline'`; users by `skill_ids_json`.
        """
        conn = _connect()
        try:
            flights: Dict[str, Any] = {}
            for r in conn.execute(
                "SELECT * FROM flights WHERE source_skill=?", (SOURCE_SKILL,)
            ):
                flights[r["flight_id"]] = {
                    "flight_number": r["flight_id"],
                    "origin": r["origin"],
                    "destination": r["destination"],
                    "scheduled_departure_time_est": r["departure_time"],
                    "scheduled_arrival_time_est": r["arrival_time"],
                    "dates": json.loads(r["dates_json"] or "{}"),
                }

            # Reservation ids per user (User.reservations is derived, not stored).
            resv_by_user: Dict[str, list] = {}
            reservations: Dict[str, Any] = {}
            for r in conn.execute(
                "SELECT * FROM flight_bookings WHERE source_skill=?", (SOURCE_SKILL,)
            ):
                res_flights = []
                for fj in json.loads(r["flights_json"] or "[]"):
                    res_flights.append(
                        {
                            "flight_number": fj.get("flight_number") or fj.get("flight_id"),
                            "origin": fj.get("origin", ""),
                            "destination": fj.get("destination", ""),
                            "date": fj.get("date", ""),
                            "price": fj.get("price", 0),
                        }
                    )
                reservations[r["booking_id"]] = {
                    "reservation_id": r["booking_id"],
                    "user_id": r["user_id"],
                    "origin": r["origin"],
                    "destination": r["destination"],
                    "flight_type": r["flight_type"] if r["flight_type"] in _TAU2_FLIGHT_TYPES else "one_way",
                    "cabin": r["cabin_class"] if r["cabin_class"] in _TAU2_CABINS else "economy",
                    "flights": res_flights,
                    "passengers": json.loads(r["passengers_json"] or "[]"),
                    "payment_history": json.loads(r["payment_history_json"] or "[]"),
                    "created_at": r["booked_at"],
                    "total_baggages": r["total_baggages"],
                    "nonfree_baggages": r["nonfree_baggages"],
                    "insurance": r["add_insurance"] if r["add_insurance"] in ("yes", "no") else "no",
                    "status": "cancelled" if r["status"] == "cancelled" else None,
                }
                resv_by_user.setdefault(r["user_id"], []).append(r["booking_id"])

            users: Dict[str, Any] = {}
            for r in conn.execute(
                "SELECT * FROM users WHERE skill_ids_json LIKE ?",
                (f'%"{SOURCE_SKILL}"%',),
            ):
                users[r["user_id"]] = {
                    "user_id": r["user_id"],
                    "name": _split_name(r["name"]),
                    "address": json.loads(r["address_json"] or "{}"),
                    "email": r["email"],
                    "dob": r["dob"] or "",
                    "payment_methods": json.loads(r["payment_methods_json"] or "{}"),
                    "saved_passengers": json.loads(r["saved_passengers_json"] or "[]"),
                    "membership": _TIER_TO_MEMBERSHIP.get(r["loyalty_tier"], r["loyalty_tier"]),
                    "reservations": resv_by_user.get(r["user_id"], []),
                }
        finally:
            conn.close()
        return cls.model_validate(
            {"flights": flights, "users": users, "reservations": reservations}
        )

    def save(self, path: Optional[str] = None) -> None:
        """Write mutations back to the unified world.db (scoped to this skill).

        `path` is accepted for back-compat but ignored. Persists per-date flight
        availability (seat/price changes from bookings), user payment methods, and
        the reservation rows (upserted by id so new bookings are captured).
        """
        conn = _connect()
        try:
            cur = conn.cursor()
            for fn, flight in self.flights.items():
                cur.execute(
                    "UPDATE flights SET dates_json=? WHERE flight_id=? AND source_skill=?",
                    (json.dumps({d: s.model_dump() for d, s in flight.dates.items()}), fn, SOURCE_SKILL),
                )
            for uid, user in self.users.items():
                cur.execute(
                    "UPDATE users SET name=?, email=?, loyalty_tier=?, dob=?, "
                    "payment_methods_json=?, saved_passengers_json=?, address_json=? "
                    "WHERE user_id=?",
                    (
                        f"{user.name.first_name} {user.name.last_name}".strip(),
                        user.email,
                        _MEMBERSHIP_TO_TIER.get(user.membership, user.membership),
                        user.dob,
                        json.dumps({k: v.model_dump() for k, v in user.payment_methods.items()}),
                        json.dumps([p.model_dump() for p in user.saved_passengers]),
                        json.dumps(user.address.model_dump()),
                        uid,
                    ),
                )
            for rid, res in self.reservations.items():
                flights_json = json.dumps(
                    [
                        {
                            "flight_id": f.flight_number,
                            "origin": f.origin,
                            "destination": f.destination,
                            "date": f.date,
                            "price": f.price,
                        }
                        for f in res.flights
                    ]
                )
                cur.execute(
                    "INSERT INTO flight_bookings (booking_id, user_id, origin, destination, "
                    "flight_type, cabin_class, flights_json, passengers_json, payment_history_json, "
                    "booked_at, total_baggages, nonfree_baggages, add_insurance, status, source_skill) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(booking_id) DO UPDATE SET user_id=excluded.user_id, "
                    "origin=excluded.origin, destination=excluded.destination, "
                    "flight_type=excluded.flight_type, cabin_class=excluded.cabin_class, "
                    "flights_json=excluded.flights_json, passengers_json=excluded.passengers_json, "
                    "payment_history_json=excluded.payment_history_json, booked_at=excluded.booked_at, "
                    "total_baggages=excluded.total_baggages, nonfree_baggages=excluded.nonfree_baggages, "
                    "add_insurance=excluded.add_insurance, status=excluded.status",
                    (
                        rid, res.user_id, res.origin, res.destination, res.flight_type,
                        res.cabin, flights_json,
                        json.dumps([p.model_dump() for p in res.passengers]),
                        json.dumps([p.model_dump() for p in res.payment_history]),
                        res.created_at, res.total_baggages, res.nonfree_baggages,
                        res.insurance, res.status if res.status else "confirmed", SOURCE_SKILL,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def dump(self, path: Optional[str] = None, **kwargs: Any) -> None:
        """Back-compat alias for save(); the old db.json dump now writes world.db."""
        self.save(path)



def get_db():
    return FlightDB.load()


if __name__ == "__main__":
    db = get_db()
    print(db.get_statistics())
