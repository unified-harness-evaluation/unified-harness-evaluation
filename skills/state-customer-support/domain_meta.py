"""Per-domain wiring for the portable CLI."""
from environment import CustomerSupportEnvironment as ENV_CLASS  # noqa: F401
from schemas import CSEnvironmentData as ENV_DATA_CLASS  # noqa: F401

DEFAULT_NOW = '2026-06-15T10:00:00'
DEFAULT_USER = 'cust_003'

# EnvironmentData field -> environment index attribute (for rebuild-on-save)
SAVE_MAP = {
    "products": "products",
    "orders": "orders",
    "order_items": "order_items",
    "customers": "customers",
    "warranties": "warranties"
}
