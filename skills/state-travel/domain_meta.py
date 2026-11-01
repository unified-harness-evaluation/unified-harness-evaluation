"""Per-domain wiring for the portable CLI."""
from environment import TravelEnvironment as ENV_CLASS  # noqa: F401
from schemas import EnvironmentData as ENV_DATA_CLASS  # noqa: F401

DEFAULT_NOW = '2026-06-15T10:00:00'
DEFAULT_USER = 'user_001'

# EnvironmentData field -> environment index attribute (for rebuild-on-save)
SAVE_MAP = {
    "flights": "flights",
    "bookings": "bookings",
    "users": "users",
    "hotel_inventory": "hotel_inventory",
    "hotels": "hotels",
    "car_inventory": "car_inventory",
    "car_rentals": "car_rentals"
}
