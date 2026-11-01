"""Shopping assistant domain data models.

Designed for the strict-equality semantics of `evaluate_state_requirements`:
- `cart` is pre-created empty in every task_env and mutated as the agent acts.
  Only changed fields show up in StateDiff.modified, so aggregate assertions
  stay selective.
- `cart_item` is minimal (5 fields). Created by add_to_cart, identified in
  assertions via `match_fields`. No stored unit_price or line_total —
  those are derived on-the-fly from `products[product_id].price`.
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
# State no longer lives in a per-skill db.json/state.json. It lives in the
# unified per-task `world.db` (seeded fresh into /workspace by the runner). This
# skill owns the rows tagged `source_skill = 'state-shopping'` (products) and the
# users whose `skill_ids_json` names this skill, plus their carts/cart_items;
# `promotions` is a shared, untagged catalog. `load()` reads that scoped slice;
# `save()` writes the mutated slice back. Override the DB path with CUGA_WORLD_DB.

SOURCE_SKILL = "state-shopping"
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


# --- row <-> dataclass field mappers (world.db columns -> schemas.py fields) ---
def _row_to_product(r: sqlite3.Row) -> dict[str, Any]:
    variants = json.loads(r["variants_json"]) if r["variants_json"] else None
    return {
        "product_id": r["product_id"],
        "name": r["name"],
        "category": r["category"],
        "subcategory": r["subcategory"],
        "brand": r["brand"],
        "price": r["price"],
        "rating": r["rating"],
        "review_count": r["review_count"],
        "description": r["description"] or "",
        "specs": json.loads(r["specs_json"] or "{}"),
        "compatible_with": json.loads(r["compatible_with_json"] or "[]"),
        "in_stock": bool(r["in_stock"]),
        "stock_quantity": r["stock_quantity"],
        "shipping_days": r["shipping_days"],
        "gift_wrap_available": bool(r["gift_wrap_available"]),
        "backorder_available": bool(r["backorder_available"]),
        "previous_price": r["previous_price"],
        "variants": variants or None,
    }


def _row_to_customer(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "customer_id": r["user_id"],
        "name": r["name"],
        "email": r["email"],
        "tier": r["loyalty_tier"],
        "is_first_time": bool(r["is_first_time"]),
        "loyalty_points": r["loyalty_points"],
        "purchase_history": json.loads(r["purchase_history_json"] or "[]"),
    }


def _row_to_cart(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "cart_id": r["cart_id"],
        "customer_id": r["customer_id"],
        "item_ids": json.loads(r["item_ids_json"] or "[]"),
        "subtotal": r["subtotal"],
        "discount_amount": r["discount_amount"],
        "gift_wrap_fee": r["gift_wrap_fee"],
        "total": r["total"],
        "applied_promo_codes": json.loads(r["applied_promo_codes_json"] or "[]"),
        "loyalty_points_redeemed": r["loyalty_points_redeemed"],
        "loyalty_discount": r["loyalty_discount"],
        "shipping_option": r["shipping_option"],
        "shipping_cost": r["shipping_cost"],
    }


def _row_to_cart_item(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "cart_item_id": r["cart_item_id"],
        "customer_id": r["customer_id"],
        "product_id": r["product_id"],
        "quantity": r["quantity"],
        "gift_wrap": bool(r["gift_wrap"]),
        "variant_id": r["variant_id"] or None,
    }


def _row_to_promotion(r: sqlite3.Row) -> dict[str, Any]:
    cr = r["category_restriction_json"]
    return {
        "promo_code": r["promo_code"],
        "description": r["description"],
        "discount_type": r["discount_type"],
        "discount_value": r["discount_value"],
        "min_purchase": r["min_purchase"],
        "max_discount": r["max_discount"],
        "category_restriction": json.loads(cr) if cr else None,
        "expiry_date": r["expiry_date"],
        "active": bool(r["active"]),
    }

# ---------------------------------------------------------------------------
# Database records
# ---------------------------------------------------------------------------


@dataclass
class Product(DictMixin):
    """Catalog product. Frozen at env-load time — never mutated during a run."""

    product_id: str  # e.g. "SP-1003"
    name: str  # Unique within a single task_env
    category: str  # electronics | kitchen | clothing | accessories | home_office | outdoor
    subcategory: str  # laptop | phone | headphones | blender | jacket | desk | etc.
    brand: str
    price: int  # dollars
    rating: float  # 1.0-5.0
    review_count: int
    description: str = ""  # short prose description surfaced in details
    specs: dict[str, Any] = field(default_factory=dict)
    compatible_with: list[str] = field(default_factory=list)  # canonical device strings
    in_stock: bool = True
    stock_quantity: int = 50
    shipping_days: int = 3
    gift_wrap_available: bool = True
    backorder_available: bool = False
    previous_price: int | None = None  # for price-drop alerts
    variants: list[dict[str, Any]] | None = (
        None  # None = no variants; when set, each dict has {variant_id, label, price_delta, in_stock, stock_quantity}
    )


@dataclass
class Customer(DictMixin):
    """Shopper profile. Generally not mutated during a run."""

    customer_id: str
    name: str
    email: str
    tier: str = "standard"  # standard | gold | platinum
    is_first_time: bool = False
    loyalty_points: int = 0
    purchase_history: list[str] = field(default_factory=list)  # product_ids; populated per-task when needed


@dataclass
class CartItem(DictMixin):
    """Minimal cart item. Created by add_to_cart, mutated by update_cart_item.

    Only 5 fields so that a fresh creation produces a tight StateDiff.
    Unit price is NOT stored; cart.subtotal recomputes from products table.
    """

    cart_item_id: str  # e.g. "CI-0001"
    customer_id: str  # denormalized for match_fields convenience
    product_id: str
    quantity: int
    gift_wrap: bool
    variant_id: str | None = None  # None = no variant selected; must match a variant on the product when set


@dataclass
class Cart(DictMixin):
    """One cart per customer. Pre-exists empty in every task_env."""

    cart_id: str  # canonical: f"CART-{customer_id}"
    customer_id: str
    item_ids: list[str] = field(default_factory=list)  # ordered list of cart_item_ids
    subtotal: int = 0
    discount_amount: int = 0
    gift_wrap_fee: int = 0
    total: int = 0
    applied_promo_codes: list[str] = field(default_factory=list)
    loyalty_points_redeemed: int = 0  # points debited from customer balance for this cart
    loyalty_discount: int = 0  # dollars discounted from total via redemption (defaults to 0 = no regression)
    shipping_option: str | None = None  # None = not yet chosen; 'standard' | 'express' | 'next_day'
    shipping_cost: int = 0  # dollars added to cart.total for shipping (defaults to 0 = no regression)


@dataclass
class Promotion(DictMixin):
    promo_code: str
    description: str
    discount_type: str = "percentage"  # percentage | fixed
    discount_value: int = 0  # percentage (10 = 10%) or fixed dollar amount
    min_purchase: int = 0
    max_discount: int = 0  # 0 = no max
    category_restriction: list[str] | None = None  # None = all categories
    expiry_date: str = ""  # ISO date
    active: bool = True


# ---------------------------------------------------------------------------
# Environment snapshot
# ---------------------------------------------------------------------------


@dataclass
class SAEnvironmentData:
    """Full environment state for a single task run."""

    products: list[Product]
    customers: list[Customer]
    carts: list[Cart]
    cart_items: list[CartItem] = field(default_factory=list)
    promotions: list[Promotion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": [p.to_dict() for p in self.products],
            "customers": [c.to_dict() for c in self.customers],
            "carts": [c.to_dict() for c in self.carts],
            "cart_items": [ci.to_dict() for ci in self.cart_items],
            "promotions": [p.to_dict() for p in self.promotions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SAEnvironmentData:
        return cls(
            products=[Product.from_dict(p) for p in data["products"]],
            customers=[Customer.from_dict(c) for c in data["customers"]],
            carts=[Cart.from_dict(c) for c in data["carts"]],
            cart_items=[CartItem.from_dict(ci) for ci in data.get("cart_items", [])],
            promotions=[Promotion.from_dict(p) for p in data.get("promotions", [])],
        )

    def deep_copy(self) -> SAEnvironmentData:
        return SAEnvironmentData.from_dict(copy.deepcopy(self.to_dict()))

    def save(self, path: Path | None = None) -> None:
        """Write the mutated shopping slice back to the unified world.db.

        `path` is accepted for CLI back-compat but ignored; state lives in
        world.db. Products/promotions are effectively frozen (only mutable stock
        fields are refreshed); carts are updated in place; cart_items for the
        scoped customers are replaced wholesale (captures adds/removes/updates);
        customers get their mutable loyalty/history fields refreshed.
        """
        conn = _connect()
        try:
            cur = conn.cursor()
            for c in self.customers:
                cur.execute(
                    "UPDATE users SET loyalty_tier=?, loyalty_points=?, is_first_time=?, "
                    "purchase_history_json=? WHERE user_id=?",
                    (c.tier, c.loyalty_points, int(c.is_first_time),
                     json.dumps(c.purchase_history), c.customer_id),
                )
            for c in self.carts:
                cur.execute(
                    "UPDATE carts SET subtotal=?, discount_amount=?, gift_wrap_fee=?, "
                    "loyalty_discount=?, loyalty_points_redeemed=?, shipping_option=?, "
                    "shipping_cost=?, total=?, applied_promo_codes_json=?, item_ids_json=? "
                    "WHERE cart_id=?",
                    (c.subtotal, c.discount_amount, c.gift_wrap_fee, c.loyalty_discount,
                     c.loyalty_points_redeemed, c.shipping_option, c.shipping_cost, c.total,
                     json.dumps(c.applied_promo_codes), json.dumps(c.item_ids), c.cart_id),
                )
            cust_ids = [c.customer_id for c in self.carts] or [ci.customer_id for ci in self.cart_items]
            if cust_ids:
                placeholders = ",".join("?" * len(cust_ids))
                cur.execute(f"DELETE FROM cart_items WHERE customer_id IN ({placeholders})", cust_ids)
            for ci in self.cart_items:
                cur.execute(
                    "INSERT INTO cart_items (cart_item_id, cart_id, customer_id, product_id, "
                    "quantity, gift_wrap, variant_id) VALUES (?,?,?,?,?,?,?)",
                    (ci.cart_item_id, f"CART-{ci.customer_id}", ci.customer_id, ci.product_id,
                     ci.quantity, int(ci.gift_wrap), ci.variant_id),
                )
            for p in self.products:
                cur.execute(
                    "UPDATE products SET in_stock=?, stock_quantity=? WHERE product_id=?",
                    (int(p.in_stock), p.stock_quantity, p.product_id),
                )
            conn.commit()
        finally:
            conn.close()
        logger.info(
            "Saved shopping env to world.db: %s products, %s customers, %s carts, %s cart_items",
            len(self.products), len(self.customers), len(self.carts), len(self.cart_items),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> SAEnvironmentData:
        """Build the scoped shopping environment from the unified world.db.

        `path` is accepted for CLI back-compat but ignored.
        """
        conn = _connect()
        try:
            user_ids = _scoped_user_ids(conn)
            uq = ",".join("?" * len(user_ids)) if user_ids else "''"
            products = [
                Product.from_dict(_row_to_product(r))
                for r in conn.execute("SELECT * FROM products WHERE source_skill=?", (SOURCE_SKILL,))
            ]
            customers = [
                Customer.from_dict(_row_to_customer(r))
                for r in conn.execute(f"SELECT * FROM users WHERE user_id IN ({uq})", user_ids)
            ]
            carts = [
                Cart.from_dict(_row_to_cart(r))
                for r in conn.execute(f"SELECT * FROM carts WHERE customer_id IN ({uq})", user_ids)
            ]
            cart_items = [
                CartItem.from_dict(_row_to_cart_item(r))
                for r in conn.execute(f"SELECT * FROM cart_items WHERE customer_id IN ({uq})", user_ids)
            ]
            promotions = [
                Promotion.from_dict(_row_to_promotion(r))
                for r in conn.execute("SELECT * FROM promotions")
            ]
        finally:
            conn.close()
        return cls(
            products=products,
            customers=customers,
            carts=carts,
            cart_items=cart_items,
            promotions=promotions,
        )
