"""Travel domain data models.

Domain-specific database records and environment data for the travel benchmark.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import DictMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unified world.db backing store
# ---------------------------------------------------------------------------
# State lives in the unified per-task `world.db` (seeded fresh into /workspace by
# the runner), not a per-skill db.json/state.json. This skill owns the flights and
# flight_bookings tagged `source_skill = 'state-travel'`, the users whose
# `skill_ids_json` names this skill, and their hotel/car reservations; hotel_inventory
# and car_inventory are shared (travel-only) catalogs. `load()` reads that scoped
# slice; `save()` writes mutations back. Override the DB path with CUGA_WORLD_DB.

SOURCE_SKILL = "state-travel"
DB_PATH_ENV = "CUGA_WORLD_DB"


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


def _scoped_user_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT user_id FROM users WHERE skill_ids_json LIKE ?",
        (f'%"{SOURCE_SKILL}"%',),
    ).fetchall()
    return [r["user_id"] for r in rows]


def _in_clause(values: list[str]) -> str:
    return ",".join("?" * len(values)) if values else "''"


# --- row <-> dataclass field mappers (world.db columns -> schemas.py fields) ---
def _row_to_flight(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "flight_id": r["flight_id"],
        "airline_code": r["airline_code"],
        "origin": r["origin"],
        "destination": r["destination"],
        "departure_time": r["departure_time"],
        "arrival_time": r["arrival_time"],
        "duration_minutes": r["duration_minutes"],
        "stops": r["stops"],
        "cabin_prices": json.loads(r["cabin_prices_json"] or "{}"),
        "status": r["status"],
        "delay_minutes": r["delay_minutes"],
        "route_type": r["route_type"],
    }


def _row_to_booking(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "booking_id": r["booking_id"],
        "user_id": r["user_id"],
        "flight_id": r["flight_id"],
        "status": r["status"],
        "cabin_class": r["cabin_class"],
        "seat_type": r["seat_type"] or None,
        "meal_preference": r["meal_preference"] or None,
        "add_wifi": bool(r["add_wifi"]),
        "add_extra_legroom": bool(r["add_extra_legroom"]),
        "add_insurance": (r["add_insurance"] or "").lower() in ("yes", "true", "1"),
        "price_paid": r["price_paid"],
        "payment_method": r["payment_method"],
        "points_used": r["points_used"],
        "cash_amount": r["cash_amount"],
        "booked_at": r["booked_at"] or "",
        "cancellation_fee": r["cancellation_fee"],
        "refund_amount": r["refund_amount"],
        "change_fee": r["change_fee"],
        "fare_difference": r["fare_difference"],
        "delay_compensation": r["delay_compensation"],
        "paid_checked_bags": r["paid_checked_bags"],
    }


def _row_to_user(r: sqlite3.Row) -> dict[str, Any]:
    prefs = json.loads(r["preferences_json"] or "{}")
    return {
        "user_id": r["user_id"],
        "name": r["name"],
        "email": r["email"],
        "loyalty_tier": r["loyalty_tier"],
        "loyalty_points": r["loyalty_points"],
        "budget": r["budget"],
        "preferences": prefs,
    }


def _row_to_hotel_inventory(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "hotel_id": r["hotel_id"],
        "hotel_name": r["hotel_name"],
        "city": r["city"],
        "check_in": r["check_in"],
        "check_out": r["check_out"],
        "room_type": r["room_type"],
        "nightly_rate": r["nightly_rate"],
        "total_price": r["total_price"],
    }


def _row_to_hotel_reservation(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "reservation_id": r["reservation_id"],
        "user_id": r["user_id"],
        "hotel_name": r["hotel_name"],
        "city": r["city"],
        "check_in": r["check_in"],
        "check_out": r["check_out"],
        "room_type": r["room_type"],
        "nightly_rate": r["nightly_rate"],
        "total_price": r["total_price"],
        "hotel_id": r["hotel_id"],
        "status": r["status"],
        "booked_at": r["booked_at"] or "",
        "cancellation_fee": r["cancellation_fee"],
        "refund_amount": r["refund_amount"],
    }


def _row_to_car_inventory(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "car_id": r["car_id"],
        "company": r["company"],
        "pickup_location": r["pickup_location"],
        "dropoff_location": r["dropoff_location"],
        "pickup_date": r["pickup_date"],
        "dropoff_date": r["dropoff_date"],
        "car_class": r["car_class"],
        "daily_rate": r["daily_rate"],
        "total_price": r["total_price"],
        "insurance_included": bool(r["insurance_included"]),
    }


def _row_to_car_rental(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "rental_id": r["rental_id"],
        "user_id": r["user_id"],
        "company": r["company"],
        "pickup_location": r["pickup_location"],
        "dropoff_location": r["dropoff_location"],
        "pickup_date": r["pickup_date"],
        "dropoff_date": r["dropoff_date"],
        "car_class": r["car_class"],
        "daily_rate": r["daily_rate"],
        "total_price": r["total_price"],
        "car_id": r["car_id"],
        "status": r["status"],
        "insurance_included": bool(r["insurance_included"]),
        "booked_at": r["booked_at"] or "",
        "cancellation_fee": r["cancellation_fee"],
        "refund_amount": r["refund_amount"],
    }

# ---------------------------------------------------------------------------
# Database records
# ---------------------------------------------------------------------------


@dataclass
class Flight(DictMixin):
    flight_id: str  # primary key, e.g. "DL401"
    airline_code: str
    origin: str
    destination: str
    departure_time: str  # ISO format
    arrival_time: str
    duration_minutes: int
    stops: int
    cabin_prices: dict[str, int] = field(default_factory=dict)  # e.g. {"economy": 350, "business": 875}
    status: str = "scheduled"  # scheduled | delayed | cancelled
    delay_minutes: int = 0
    route_type: str = "domestic"  # domestic | international


@dataclass
class Booking(DictMixin):
    booking_id: str
    user_id: str
    flight_id: str
    status: str = "confirmed"  # confirmed | cancelled | changed
    cabin_class: str | None = None
    seat_type: str | None = None
    meal_preference: str | None = None
    add_wifi: bool | None = None
    add_extra_legroom: bool | None = None
    add_insurance: bool | None = None
    price_paid: int = 0
    payment_method: str = "credit_card"  # credit_card | points | points_plus_cash
    points_used: int = 0
    cash_amount: int = 0
    booked_at: str = ""  # ISO format
    cancellation_fee: int | None = None
    refund_amount: int | None = None
    change_fee: int | None = None
    fare_difference: int | None = None
    delay_compensation: str | None = None  # none | meal_voucher | full
    paid_checked_bags: int = 0


@dataclass
class User(DictMixin):
    user_id: str
    name: str
    email: str
    loyalty_tier: str = "basic"  # basic | silver | gold | platinum
    loyalty_points: int = 0
    budget: int = 1000
    preferences: dict[str, Any] = field(
        default_factory=lambda: {
            "meal_preference": "standard",
            "seat_type": "aisle",
            "add_wifi": False,
            "add_extra_legroom": False,
            "add_insurance": False,
        }
    )


@dataclass
class HotelInventoryItem(DictMixin):
    hotel_id: str  # inventory key, e.g. "HOTEL-0001"
    hotel_name: str
    city: str  # destination city / airport area code
    check_in: str  # ISO date YYYY-MM-DD
    check_out: str  # ISO date YYYY-MM-DD
    room_type: str  # "standard" | "suite"
    nightly_rate: int
    total_price: int


@dataclass
class HotelReservation(DictMixin):
    reservation_id: str  # e.g. "HR-0001"
    user_id: str
    hotel_name: str
    city: str  # destination city (maps to airport code area)
    check_in: str  # ISO date YYYY-MM-DD
    check_out: str  # ISO date YYYY-MM-DD
    room_type: str  # "standard" | "suite"
    nightly_rate: int
    total_price: int
    hotel_id: str | None = None
    status: str = "confirmed"  # confirmed | cancelled
    booked_at: str = ""  # ISO format
    cancellation_fee: int | None = None
    refund_amount: int | None = None


@dataclass
class CarInventoryItem(DictMixin):
    car_id: str  # inventory key, e.g. "CAR-0001"
    company: str  # "Hertz" | "Enterprise" | "Avis"
    pickup_location: str  # airport code
    dropoff_location: str  # airport code (same or different)
    pickup_date: str  # ISO date YYYY-MM-DD
    dropoff_date: str  # ISO date YYYY-MM-DD
    car_class: str  # "economy" | "midsize" | "compact" | "suv" | "luxury"
    daily_rate: int
    total_price: int
    insurance_included: bool = False


@dataclass
class CarRental(DictMixin):
    rental_id: str  # e.g. "CR-0001"
    user_id: str
    company: str  # "Hertz" | "Enterprise" | "Avis"
    pickup_location: str  # airport code
    dropoff_location: str  # airport code (same or different)
    pickup_date: str  # ISO date YYYY-MM-DD
    dropoff_date: str  # ISO date YYYY-MM-DD
    car_class: str  # "economy" | "midsize" | "suv" | "luxury"
    daily_rate: int
    total_price: int
    car_id: str | None = None
    status: str = "confirmed"  # confirmed | cancelled
    insurance_included: bool = False
    booked_at: str = ""  # ISO format
    cancellation_fee: int | None = None
    refund_amount: int | None = None


# ---------------------------------------------------------------------------
# Environment snapshot (loaded from JSON, deep-copied per task run)
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentData:
    """Full environment state: flights, bookings, users, hotels, car rentals."""

    flights: list[Flight]
    bookings: list[Booking]
    users: list[User]
    hotel_inventory: list[HotelInventoryItem] = field(default_factory=list)
    hotels: list[HotelReservation] = field(default_factory=list)
    car_inventory: list[CarInventoryItem] = field(default_factory=list)
    car_rentals: list[CarRental] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flights": [f.to_dict() for f in self.flights],
            "bookings": [b.to_dict() for b in self.bookings],
            "users": [u.to_dict() for u in self.users],
            "hotel_inventory": [h.to_dict() for h in self.hotel_inventory],
            "hotels": [h.to_dict() for h in self.hotels],
            "car_inventory": [c.to_dict() for c in self.car_inventory],
            "car_rentals": [c.to_dict() for c in self.car_rentals],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnvironmentData:
        return cls(
            flights=[Flight.from_dict(f) for f in data["flights"]],
            bookings=[Booking.from_dict(b) for b in data["bookings"]],
            users=[User.from_dict(u) for u in data["users"]],
            hotel_inventory=[HotelInventoryItem.from_dict(h) for h in data.get("hotel_inventory", [])],
            hotels=[HotelReservation.from_dict(h) for h in data.get("hotels", [])],
            car_inventory=[CarInventoryItem.from_dict(c) for c in data.get("car_inventory", [])],
            car_rentals=[CarRental.from_dict(c) for c in data.get("car_rentals", [])],
        )

    def deep_copy(self) -> EnvironmentData:
        return EnvironmentData.from_dict(copy.deepcopy(self.to_dict()))

    def save(self, path: Path | None = None) -> None:
        """Write the mutated travel slice back to the unified world.db.

        `path` is accepted for CLI back-compat but ignored. Flights and the
        hotel/car inventory catalogs are frozen (reference-only). Users are updated
        in place; bookings/hotel reservations/car rentals are upserted by primary
        key so rows created during a run are captured and existing rows keep their
        non-travel columns (e.g. flights_json/passengers_json on flight_bookings).
        """
        conn = _connect()
        try:
            cur = conn.cursor()
            for u in self.users:
                cur.execute(
                    "UPDATE users SET loyalty_tier=?, loyalty_points=?, budget=?, "
                    "preferences_json=? WHERE user_id=?",
                    (u.loyalty_tier, u.loyalty_points, u.budget,
                     json.dumps(u.preferences), u.user_id),
                )
            for b in self.bookings:
                cur.execute(
                    "INSERT INTO flight_bookings (booking_id, user_id, flight_id, status, "
                    "cabin_class, seat_type, meal_preference, add_wifi, add_extra_legroom, "
                    "add_insurance, price_paid, payment_method, points_used, cash_amount, "
                    "booked_at, cancellation_fee, refund_amount, change_fee, fare_difference, "
                    "delay_compensation, paid_checked_bags, source_skill) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(booking_id) DO UPDATE SET user_id=excluded.user_id, "
                    "flight_id=excluded.flight_id, status=excluded.status, "
                    "cabin_class=excluded.cabin_class, seat_type=excluded.seat_type, "
                    "meal_preference=excluded.meal_preference, add_wifi=excluded.add_wifi, "
                    "add_extra_legroom=excluded.add_extra_legroom, add_insurance=excluded.add_insurance, "
                    "price_paid=excluded.price_paid, payment_method=excluded.payment_method, "
                    "points_used=excluded.points_used, cash_amount=excluded.cash_amount, "
                    "booked_at=excluded.booked_at, cancellation_fee=excluded.cancellation_fee, "
                    "refund_amount=excluded.refund_amount, change_fee=excluded.change_fee, "
                    "fare_difference=excluded.fare_difference, "
                    "delay_compensation=excluded.delay_compensation, "
                    "paid_checked_bags=excluded.paid_checked_bags",
                    (b.booking_id, b.user_id, b.flight_id, b.status, b.cabin_class,
                     b.seat_type, b.meal_preference, int(bool(b.add_wifi)),
                     int(bool(b.add_extra_legroom)), "yes" if b.add_insurance else "no",
                     b.price_paid, b.payment_method, b.points_used, b.cash_amount,
                     b.booked_at, b.cancellation_fee, b.refund_amount, b.change_fee,
                     b.fare_difference, b.delay_compensation, b.paid_checked_bags, SOURCE_SKILL),
                )
            for h in self.hotels:
                cur.execute(
                    "INSERT INTO hotel_reservations (reservation_id, user_id, hotel_id, "
                    "hotel_name, city, check_in, check_out, room_type, nightly_rate, "
                    "total_price, status, booked_at, cancellation_fee, refund_amount) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(reservation_id) DO UPDATE SET user_id=excluded.user_id, "
                    "hotel_id=excluded.hotel_id, hotel_name=excluded.hotel_name, "
                    "city=excluded.city, check_in=excluded.check_in, check_out=excluded.check_out, "
                    "room_type=excluded.room_type, nightly_rate=excluded.nightly_rate, "
                    "total_price=excluded.total_price, status=excluded.status, "
                    "booked_at=excluded.booked_at, cancellation_fee=excluded.cancellation_fee, "
                    "refund_amount=excluded.refund_amount",
                    (h.reservation_id, h.user_id, h.hotel_id, h.hotel_name, h.city,
                     h.check_in, h.check_out, h.room_type, h.nightly_rate, h.total_price,
                     h.status, h.booked_at, h.cancellation_fee, h.refund_amount),
                )
            for c in self.car_rentals:
                cur.execute(
                    "INSERT INTO car_rentals (rental_id, user_id, car_id, company, "
                    "pickup_location, dropoff_location, pickup_date, dropoff_date, car_class, "
                    "daily_rate, total_price, status, insurance_included, booked_at, "
                    "cancellation_fee, refund_amount) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(rental_id) DO UPDATE SET user_id=excluded.user_id, "
                    "car_id=excluded.car_id, company=excluded.company, "
                    "pickup_location=excluded.pickup_location, dropoff_location=excluded.dropoff_location, "
                    "pickup_date=excluded.pickup_date, dropoff_date=excluded.dropoff_date, "
                    "car_class=excluded.car_class, daily_rate=excluded.daily_rate, "
                    "total_price=excluded.total_price, status=excluded.status, "
                    "insurance_included=excluded.insurance_included, booked_at=excluded.booked_at, "
                    "cancellation_fee=excluded.cancellation_fee, refund_amount=excluded.refund_amount",
                    (c.rental_id, c.user_id, c.car_id, c.company, c.pickup_location,
                     c.dropoff_location, c.pickup_date, c.dropoff_date, c.car_class,
                     c.daily_rate, c.total_price, c.status, int(bool(c.insurance_included)),
                     c.booked_at, c.cancellation_fee, c.refund_amount),
                )
            conn.commit()
        finally:
            conn.close()
        logger.info(
            "Saved travel env to world.db: %s bookings, %s users, %s hotel reservations, %s car rentals",
            len(self.bookings), len(self.users), len(self.hotels), len(self.car_rentals),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> EnvironmentData:
        """Build the scoped travel environment from the unified world.db.

        `path` is accepted for CLI back-compat but ignored.
        """
        conn = _connect()
        try:
            user_ids = _scoped_user_ids(conn)
            uq = _in_clause(user_ids)
            flights = [
                Flight.from_dict(_row_to_flight(r))
                for r in conn.execute("SELECT * FROM flights WHERE source_skill=?", (SOURCE_SKILL,))
            ]
            bookings = [
                Booking.from_dict(_row_to_booking(r))
                for r in conn.execute("SELECT * FROM flight_bookings WHERE source_skill=?", (SOURCE_SKILL,))
            ]
            users = [
                User.from_dict(_row_to_user(r))
                for r in conn.execute(f"SELECT * FROM users WHERE user_id IN ({uq})", user_ids)
            ]
            hotel_inventory = [
                HotelInventoryItem.from_dict(_row_to_hotel_inventory(r))
                for r in conn.execute("SELECT * FROM hotel_inventory")
            ]
            hotels = [
                HotelReservation.from_dict(_row_to_hotel_reservation(r))
                for r in conn.execute(f"SELECT * FROM hotel_reservations WHERE user_id IN ({uq})", user_ids)
            ]
            car_inventory = [
                CarInventoryItem.from_dict(_row_to_car_inventory(r))
                for r in conn.execute("SELECT * FROM car_inventory")
            ]
            car_rentals = [
                CarRental.from_dict(_row_to_car_rental(r))
                for r in conn.execute(f"SELECT * FROM car_rentals WHERE user_id IN ({uq})", user_ids)
            ]
        finally:
            conn.close()
        return cls(
            flights=flights,
            bookings=bookings,
            users=users,
            hotel_inventory=hotel_inventory,
            hotels=hotels,
            car_inventory=car_inventory,
            car_rentals=car_rentals,
        )
