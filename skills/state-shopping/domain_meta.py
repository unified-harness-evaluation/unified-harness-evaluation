"""Per-domain wiring for the portable CLI."""
from environment import ShoppingAssistantEnvironment as ENV_CLASS  # noqa: F401
from schemas import SAEnvironmentData as ENV_DATA_CLASS  # noqa: F401

DEFAULT_NOW = '2026-06-15T10:00:00'
DEFAULT_USER = 'shop_004'

# EnvironmentData field -> environment index attribute (for rebuild-on-save)
SAVE_MAP = {
    "products": "products",
    "customers": "customers",
    "carts": "carts_by_id",
    "cart_items": "cart_items",
    "promotions": "promotions"
}
