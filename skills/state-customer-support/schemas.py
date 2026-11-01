"""Core data models for the customer support e-commerce benchmark."""

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
# the runner), not a per-skill db.json/state.json. This skill owns the rows tagged
# `source_skill = 'state-customer-support'` (products) and the users whose
# `skill_ids_json` names this skill, plus the orders/order_items/warranties owned
# by those customers. `load()` reads that scoped slice; `save()` writes mutations
# back. Override the DB path with CUGA_WORLD_DB.

SOURCE_SKILL = "state-customer-support"
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
def _row_to_product(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "product_id": r["product_id"],
        "name": r["name"],
        "category": r["category"],
        "subcategory": r["subcategory"],
        "price": r["price"],
        "warranty_months": r["warranty_months"],
        "return_window_days": r["return_window_days"],
        "restocking_fee_pct": r["restocking_fee_pct"],
        "weight_lbs": r["weight_lbs"],
        "is_fragile": bool(r["is_fragile"]),
        "in_stock": bool(r["in_stock"]),
        "current_price": r["current_price"],
    }


def _row_to_customer(r: sqlite3.Row, total_orders: int) -> dict[str, Any]:
    return {
        "customer_id": r["user_id"],
        "name": r["name"],
        "email": r["email"],
        "membership_tier": r["loyalty_tier"],
        "account_created": "",  # not tracked in world.db
        "total_orders": total_orders,
        "preferred_refund_method": r["preferred_refund_method"] or "original_payment",
        "store_credit_balance": r["store_credit_balance"],
        "has_prime_shipping": bool(r["has_prime_shipping"]),
    }


def _row_to_order(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "order_id": r["order_id"],
        "customer_id": r["customer_id"],
        "order_date": r["order_date"],
        "status": r["status"],
        "shipping_status": r["shipping_status"],
        "shipping_method": r["shipping_method"],
        "shipping_cost": r["shipping_cost"],
        "tracking_number": r["tracking_number"] or "",
        "delivery_date": r["delivery_date"],
        "delivery_promised_date": r["delivery_promised_date"] or "",
        "signature_required": bool(r["signature_required"]),
        "signature_on_file": r["signature_on_file"],
        "payment_method": r["payment_method"],
        "payment_details": json.loads(r["payment_details_json"] or "{}"),
        "subtotal": r["subtotal"],
        "discount_code": r["discount_code"],
        "discount_amount": r["discount_amount"],
        "total_paid": r["total_paid"],
        "is_gift": bool(r["is_gift"]),
        "gift_sender": r["gift_sender"],
    }


def _row_to_order_item(r: sqlite3.Row) -> dict[str, Any]:
    return {
        # world.db PK for an order line is `oi_id`; the nullable `item_id`
        # column is unused. Map oi_id -> our OrderItem.item_id field.
        "item_id": r["oi_id"],
        "order_id": r["order_id"],
        "product_id": r["product_id"],
        "quantity": r["quantity"],
        "unit_price": r["unit_price"],
        "item_status": r["item_status"],
        "return_reason": r["return_reason"],
        "refund_amount": r["refund_amount"],
        "refund_method": r["refund_method"],
        "restocking_fee": r["restocking_fee"],
        "return_label_issued": bool(r["return_label_issued"]),
        "replacement_item_id": r["replacement_item_id"],
        "goodwill_credit": r["goodwill_credit"],
        "goodwill_credit_method": r["goodwill_credit_method"],
        "store_credit_only": bool(r["store_credit_only"]),
    }


def _row_to_warranty(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "warranty_id": r["warranty_id"],
        "order_id": r["order_id"],
        # warranties links to an order line via `oi_id` (there is no item_id column).
        "item_id": r["oi_id"],
        "product_id": r["product_id"],
        "warranty_type": r["warranty_type"],
        "start_date": r["start_date"] or "",
        "end_date": r["end_date"] or "",
        "status": r["status"],
        "claim_count": r["claim_count"],
        "max_claims": r["max_claims"],
        "coverage": r["coverage"],
        "resolution": r["resolution"],
    }

# ---------------------------------------------------------------------------
# Database records
# ---------------------------------------------------------------------------


@dataclass
class Product(DictMixin):
    product_id: str  # e.g. "PROD-1001"
    name: str
    category: str  # electronics | clothing | kitchen | books | accessories
    subcategory: str  # laptop | phone | headphones | blender | shirt | novel
    price: int  # current price in dollars
    warranty_months: int  # manufacturer warranty duration
    return_window_days: int  # category-specific return window
    restocking_fee_pct: int  # 0 or 15 (for opened electronics)
    weight_lbs: float
    is_fragile: bool
    in_stock: bool = True
    current_price: int | None = None  # sale price if different from price


@dataclass
class Customer(DictMixin):
    customer_id: str  # e.g. "cust_001"
    name: str
    email: str
    membership_tier: str = "standard"  # standard | silver | gold | platinum
    account_created: str = ""  # ISO date
    total_orders: int = 0
    preferred_refund_method: str = "original_payment"  # original_payment | store_credit
    store_credit_balance: int = 0
    has_prime_shipping: bool = False  # free returns, extended windows


@dataclass
class Order(DictMixin):
    order_id: str  # e.g. "ORD-5001"
    customer_id: str
    order_date: str  # ISO datetime
    status: str = "confirmed"  # confirmed | processing | shipped | delivered | partially_returned | fully_returned | partially_cancelled | cancelled
    shipping_status: str = "pending"  # pending | in_transit | delivered | lost | damaged
    shipping_method: str = "standard"  # standard | express | overnight
    shipping_cost: int = 0
    tracking_number: str = ""
    delivery_date: str | None = None  # ISO datetime, None if not delivered
    delivery_promised_date: str = ""  # ISO datetime
    signature_required: bool = False
    signature_on_file: str | None = None  # signer name if signed
    payment_method: str = "credit_card"  # credit_card | debit_card | gift_card | split
    payment_details: dict[str, int] = field(default_factory=dict)  # e.g. {"credit_card": 150, "gift_card": 50}
    subtotal: int = 0  # sum of item prices before discount
    discount_code: str | None = None
    discount_amount: int = 0  # dollar amount of discount
    total_paid: int = 0  # subtotal - discount + shipping
    is_gift: bool = False
    gift_sender: str | None = None


@dataclass
class OrderItem(DictMixin):
    item_id: str  # e.g. "ITEM-8001"
    order_id: str  # FK to Order
    product_id: str  # FK to Product
    quantity: int = 1
    unit_price: int = 0  # price at time of purchase
    item_status: str = "confirmed"  # confirmed | shipped | delivered | return_requested | returned | exchange_requested | exchanged | cancelled
    return_reason: str | None = (
        None  # defective | wrong_item | not_as_described | changed_mind | damaged_in_transit | missing
    )
    refund_amount: int | None = None
    refund_method: str | None = None  # original_payment | store_credit
    restocking_fee: int | None = None
    return_label_issued: bool = False
    replacement_item_id: str | None = None  # links to replacement if exchanged/replaced
    goodwill_credit: int = 0  # additive credits applied via process_refund after a return
    goodwill_credit_method: str | None = None  # original_payment | store_credit
    store_credit_only: bool = False  # True when policy forced store_credit at return time
    # (outside-window grace, gift returns) — process_refund must not flip the method.


@dataclass
class Warranty(DictMixin):
    warranty_id: str  # e.g. "WRT-3001"
    order_id: str
    item_id: str
    product_id: str
    warranty_type: str = "manufacturer"  # manufacturer | extended | store
    start_date: str = ""  # ISO date
    end_date: str = ""  # ISO date
    status: str = "active"  # active | expired | claimed | voided
    claim_count: int = 0
    max_claims: int = 3
    coverage: str = "repair_or_replace"  # full_replacement | repair | repair_or_replace
    resolution: str | None = None  # set when claimed: repair | full_replacement | discounted_repair | paid_repair


# ---------------------------------------------------------------------------
# Environment snapshot
# ---------------------------------------------------------------------------


@dataclass
class CSEnvironmentData:
    """Full environment state for customer support domain."""

    products: list[Product]
    orders: list[Order]
    order_items: list[OrderItem]
    customers: list[Customer]
    warranties: list[Warranty]

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": [p.to_dict() for p in self.products],
            "orders": [o.to_dict() for o in self.orders],
            "order_items": [i.to_dict() for i in self.order_items],
            "customers": [c.to_dict() for c in self.customers],
            "warranties": [w.to_dict() for w in self.warranties],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CSEnvironmentData:
        return cls(
            products=[Product.from_dict(p) for p in data["products"]],
            orders=[Order.from_dict(o) for o in data["orders"]],
            order_items=[OrderItem.from_dict(i) for i in data["order_items"]],
            customers=[Customer.from_dict(c) for c in data["customers"]],
            warranties=[Warranty.from_dict(w) for w in data.get("warranties", [])],
        )

    def deep_copy(self) -> CSEnvironmentData:
        return CSEnvironmentData.from_dict(copy.deepcopy(self.to_dict()))

    def save(self, path: Path | None = None) -> None:
        """Write the mutated customer-support slice back to the unified world.db.

        `path` is accepted for CLI back-compat but ignored. Products are frozen
        (reference-only). Orders/customers are updated in place; order_items and
        warranties for the scoped orders are replaced wholesale so created/removed
        rows are captured.
        """
        conn = _connect()
        try:
            cur = conn.cursor()
            for c in self.customers:
                cur.execute(
                    "UPDATE users SET loyalty_tier=?, preferred_refund_method=?, "
                    "store_credit_balance=?, has_prime_shipping=? WHERE user_id=?",
                    (c.membership_tier, c.preferred_refund_method, c.store_credit_balance,
                     int(c.has_prime_shipping), c.customer_id),
                )
            for o in self.orders:
                cur.execute(
                    "UPDATE orders SET status=?, shipping_status=?, shipping_method=?, "
                    "shipping_cost=?, tracking_number=?, delivery_date=?, delivery_promised_date=?, "
                    "signature_required=?, signature_on_file=?, payment_method=?, "
                    "payment_details_json=?, subtotal=?, discount_code=?, discount_amount=?, "
                    "total_paid=?, is_gift=?, gift_sender=? WHERE order_id=?",
                    (o.status, o.shipping_status, o.shipping_method, o.shipping_cost,
                     o.tracking_number, o.delivery_date, o.delivery_promised_date,
                     int(o.signature_required), o.signature_on_file, o.payment_method,
                     json.dumps(o.payment_details), o.subtotal, o.discount_code,
                     o.discount_amount, o.total_paid, int(o.is_gift), o.gift_sender, o.order_id),
                )
            order_ids = [o.order_id for o in self.orders]
            if order_ids:
                ph = _in_clause(order_ids)
                # warranties map 1:1 to the dataclass, so replacing wholesale is lossless.
                # order_items carry extra runner-seeded columns (name, options) not modelled
                # here — upsert those below instead of DELETE+INSERT to preserve them.
                cur.execute(f"DELETE FROM warranties WHERE order_id IN ({ph})", order_ids)
            for i in self.order_items:
                cur.execute(
                    "INSERT INTO order_items (oi_id, order_id, product_id, quantity, unit_price, "
                    "item_status, return_reason, refund_amount, refund_method, restocking_fee, "
                    "return_label_issued, replacement_item_id, goodwill_credit, "
                    "goodwill_credit_method, store_credit_only) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(oi_id) DO UPDATE SET "
                    "order_id=excluded.order_id, product_id=excluded.product_id, "
                    "quantity=excluded.quantity, unit_price=excluded.unit_price, "
                    "item_status=excluded.item_status, return_reason=excluded.return_reason, "
                    "refund_amount=excluded.refund_amount, refund_method=excluded.refund_method, "
                    "restocking_fee=excluded.restocking_fee, "
                    "return_label_issued=excluded.return_label_issued, "
                    "replacement_item_id=excluded.replacement_item_id, "
                    "goodwill_credit=excluded.goodwill_credit, "
                    "goodwill_credit_method=excluded.goodwill_credit_method, "
                    "store_credit_only=excluded.store_credit_only",
                    (i.item_id, i.order_id, i.product_id, i.quantity, i.unit_price, i.item_status,
                     i.return_reason, i.refund_amount, i.refund_method, i.restocking_fee,
                     int(i.return_label_issued), i.replacement_item_id, i.goodwill_credit,
                     i.goodwill_credit_method, int(i.store_credit_only)),
                )
            for w in self.warranties:
                cur.execute(
                    "INSERT INTO warranties (warranty_id, order_id, oi_id, product_id, "
                    "warranty_type, start_date, end_date, status, claim_count, max_claims, "
                    "coverage, resolution) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (w.warranty_id, w.order_id, w.item_id, w.product_id, w.warranty_type,
                     w.start_date, w.end_date, w.status, w.claim_count, w.max_claims,
                     w.coverage, w.resolution),
                )
            conn.commit()
        finally:
            conn.close()
        logger.info(
            "Saved customer-support env to world.db: %s orders, %s items, %s customers, %s warranties",
            len(self.orders), len(self.order_items), len(self.customers), len(self.warranties),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> CSEnvironmentData:
        """Build the scoped customer-support environment from the unified world.db.

        `path` is accepted for CLI back-compat but ignored.
        """
        conn = _connect()
        try:
            user_ids = _scoped_user_ids(conn)
            uq = _in_clause(user_ids)
            products = [
                Product.from_dict(_row_to_product(r))
                for r in conn.execute("SELECT * FROM products WHERE source_skill=?", (SOURCE_SKILL,))
            ]
            order_rows = conn.execute(
                f"SELECT * FROM orders WHERE customer_id IN ({uq})", user_ids
            ).fetchall()
            orders = [Order.from_dict(_row_to_order(r)) for r in order_rows]
            order_ids = [r["order_id"] for r in order_rows]
            oq = _in_clause(order_ids)
            order_items = [
                OrderItem.from_dict(_row_to_order_item(r))
                for r in conn.execute(f"SELECT * FROM order_items WHERE order_id IN ({oq})", order_ids)
            ]
            warranties = [
                Warranty.from_dict(_row_to_warranty(r))
                for r in conn.execute(f"SELECT * FROM warranties WHERE order_id IN ({oq})", order_ids)
            ]
            orders_per_customer: dict[str, int] = {}
            for r in order_rows:
                orders_per_customer[r["customer_id"]] = orders_per_customer.get(r["customer_id"], 0) + 1
            customers = [
                Customer.from_dict(_row_to_customer(r, orders_per_customer.get(r["user_id"], 0)))
                for r in conn.execute(f"SELECT * FROM users WHERE user_id IN ({uq})", user_ids)
            ]
        finally:
            conn.close()
        return cls(
            products=products,
            orders=orders,
            order_items=order_items,
            customers=customers,
            warranties=warranties,
        )
