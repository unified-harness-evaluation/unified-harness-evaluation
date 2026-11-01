import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from tau2.environment.db import DB

# ---------------------------------------------------------------------------
# Unified world.db backing store
# ---------------------------------------------------------------------------
# State lives in the unified per-task `world.db` (seeded fresh into /workspace by
# the runner), not a per-skill db.json. This skill owns products tagged
# `source_skill = 'tau2Retail'`, orders tagged likewise, and users whose
# `skill_ids_json` names this skill.
#
# Storage is fully normalized:
#   products       : product_id, name, source_skill='tau2Retail'
#   rt_variants    : item_id PK, product_id FK, options, available, price
#   users          : shared table, scoped by skill_ids_json
#   rt_payment_methods : payment_method_id PK, user_id FK, source, brand, last_four, balance
#   orders         : shared table, scoped by source_skill='tau2Retail', customer_id=user_id
#   order_items    : oi_id PK, order_id FK, product_id, item_id (variant ref), name, unit_price, options
#   order_fulfillments : id PK, order_id FK, tracking_ids JSON, item_ids JSON
#   order_payments : id PK, order_id FK, transaction_type, amount, payment_method_id
#
# RetailDB.load() builds the nested Pydantic tree from these tables.
# RetailDB.save() writes mutations back. tools.py is unchanged.

SOURCE_SKILL = "tau2Retail"
DB_PATH_ENV = "CUGA_WORLD_DB"

_TAU2_ORDER_STATUS = {
    "processed",
    "pending",
    "pending (item modified)",
    "delivered",
    "cancelled",
    "exchange requested",
    "return requested",
}


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


def _g(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    """Tolerant column read: returns default if the column is absent or NULL."""
    if key not in row.keys():
        return default
    value = row[key]
    return default if value is None else value


def _split_name(full: str) -> Dict[str, str]:
    parts = (full or "").split(" ", 1)
    return {"first_name": parts[0], "last_name": parts[1] if len(parts) > 1 else ""}


def _build_payment_method(row: sqlite3.Row) -> Dict[str, Any]:
    """Build a payment method dict from an rt_payment_methods row."""
    pm: Dict[str, Any] = {
        "source": row["source"],
        "id": row["payment_method_id"],
    }
    if row["source"] == "credit_card":
        pm["brand"] = row["brand"] or ""
        pm["last_four"] = row["last_four"] or ""
    elif row["source"] == "gift_card":
        pm["balance"] = row["balance"] or 0.0
    return pm


class Variant(BaseModel):
    """Represents a specific variant of a product with its options, availability and price"""

    item_id: str = Field(description="Unique identifier for the variant")
    options: Dict[str, str] = Field(
        description="Dictionary of option names to values (e.g. {'color': 'blue', 'size': 'large'})"
    )
    available: bool = Field(description="Whether this variant is currently in stock")
    price: float = Field(description="Price of this variant")


class Product(BaseModel):
    """Represents a product with its variants"""

    name: str = Field(description="Name of the product")
    product_id: str = Field(description="Unique identifier for the product")
    variants: Dict[str, Variant] = Field(
        description="Dictionary of variants indexed by variant ID"
    )


class UserName(BaseModel):
    """Represents a user's full name"""

    first_name: str = Field(description="User's first name")
    last_name: str = Field(description="User's last name")


class UserAddress(BaseModel):
    """Represents a physical address"""

    address1: str = Field(description="Primary address line")
    address2: str = Field(description="Secondary address line")
    city: str = Field(description="City name")
    country: str = Field(description="Country name")
    state: str = Field(description="State or province name")
    zip: str = Field(description="Postal code")


class PaymentMethodBase(BaseModel):
    source: str = Field(description="Type of payment method")
    id: str = Field(description="Unique identifier for the payment method")


class CreditCard(PaymentMethodBase):
    source: Literal["credit_card"] = Field(
        description="Indicates this is a credit card payment method"
    )
    brand: str = Field(description="Credit card brand (e.g., visa, mastercard)")
    last_four: str = Field(description="Last four digits of the credit card")


class Paypal(PaymentMethodBase):
    source: Literal["paypal"] = Field(
        description="Indicates this is a paypal payment method"
    )


class GiftCard(PaymentMethodBase):
    source: Literal["gift_card"] = Field(
        description="Indicates this is a gift card payment method"
    )
    balance: float = Field(description="Gift card value amount")
    id: str = Field(description="Unique identifier for the gift card")


PaymentMethod = Union[CreditCard, GiftCard, Paypal]


class User(BaseModel):
    """Represents a user with their personal information, payment methods and order history"""

    user_id: str = Field(description="Unique identifier for the user")
    name: UserName = Field(description="User's full name")
    address: UserAddress = Field(description="User's primary address")
    email: str = Field(description="User's email address")
    payment_methods: Dict[str, PaymentMethod] = Field(
        description="Dictionary of payment methods indexed by payment method ID"
    )
    orders: List[str] = Field(description="List of order IDs associated with this user")


class OrderFullfilment(BaseModel):
    """Represents the fulfillment details for items in an order"""

    tracking_id: list[str] = Field(description="List of tracking IDs for shipments")
    item_ids: list[str] = Field(
        description="List of item IDs included in this fulfillment"
    )


class OrderItem(BaseModel):
    """Represents an item in an order"""

    name: str = Field(description="Name of the product")
    product_id: str = Field(description="ID of the product")
    item_id: str = Field(description="ID of the specific variant")
    price: float = Field(description="Price of the item at time of purchase")
    options: Dict[str, str] = Field(description="Options selected for this item")


OrderPaymentType = Literal["payment", "refund"]


class OrderPayment(BaseModel):
    """Represents a payment or refund transaction for an order"""

    transaction_type: OrderPaymentType = Field(
        description="Type of transaction (payment or refund)"
    )
    amount: float = Field(description="Amount of the transaction")
    payment_method_id: str = Field(description="ID of the payment method used")


OrderStatus = Literal[
    "processed",
    "pending",
    "pending (item modified)",
    "delivered",
    "cancelled",
    "exchange requested",
    "return requested",
]

CancelReason = Literal["no longer needed", "ordered by mistake"]


class Order(BaseModel):
    """Represents an order with its items, status, fulfillment and payment details"""

    order_id: str = Field(description="Unique identifier for the order")
    user_id: str = Field(description="Unique identifier for the user")
    address: UserAddress = Field(description="Address of the user")
    items: List[OrderItem] = Field(description="Items in the order")
    status: OrderStatus = Field(description="Status of the order")
    fulfillments: List[OrderFullfilment] = Field(
        description="Fulfillments of the order"
    )
    payment_history: List[OrderPayment] = Field(description="Payments of the order")
    cancel_reason: Optional[CancelReason] = Field(
        description="Reason for cancelling the order. Should be 'no longer needed' or 'ordered by mistake'",
        default=None,
    )
    exchange_items: Optional[List[str]] = Field(
        description="Items to be exchanged", default=None
    )
    exchange_new_items: Optional[List[str]] = Field(
        description="Items exchanged for", default=None
    )
    exchange_payment_method_id: Optional[str] = Field(
        description="Payment method ID for the exchange", default=None
    )
    exchange_price_difference: Optional[float] = Field(
        description="Price difference for the exchange", default=None
    )
    return_items: Optional[List[str]] = Field(
        description="Items to be returned", default=None
    )
    return_payment_method_id: Optional[str] = Field(
        description="Payment method ID for the return", default=None
    )


class RetailDB(DB):
    """Database containing all retail-related data including products, users and orders"""

    products: Dict[str, Product] = Field(
        description="Dictionary of all products indexed by product ID"
    )
    users: Dict[str, User] = Field(
        description="Dictionary of all users indexed by user ID"
    )
    orders: Dict[str, Order] = Field(
        description="Dictionary of all orders indexed by order ID"
    )

    def get_statistics(self) -> dict[str, Any]:
        """Get the statistics of the database."""
        num_products = len(self.products)
        num_users = len(self.users)
        num_orders = len(self.orders)
        total_num_items = sum(
            len(product.variants) for product in self.products.values()
        )
        return {
            "num_products": num_products,
            "num_users": num_users,
            "num_orders": num_orders,
            "total_num_items": total_num_items,
        }

    @classmethod
    def load(cls, path: Optional[str] = None) -> "RetailDB":
        """Build the scoped tau2 retail tree from the unified world.db.

        Reads from normalized tables: products + rt_variants, orders +
        order_items + order_fulfillments + order_payments, users +
        rt_payment_methods. Products/orders scoped by source_skill;
        users by skill_ids_json.
        """
        conn = _connect()
        try:
            # ── Products + Variants ──────────────────────────────────
            products: Dict[str, Any] = {}
            for r in conn.execute(
                "SELECT * FROM products WHERE source_skill=?", (SOURCE_SKILL,)
            ):
                variants: Dict[str, Any] = {}
                for v in conn.execute(
                    "SELECT * FROM rt_variants WHERE product_id=?",
                    (r["product_id"],),
                ):
                    variants[v["item_id"]] = {
                        "item_id": v["item_id"],
                        "options": json.loads(_g(v, "options", "{}") or "{}"),
                        "available": bool(v["available"]),
                        "price": v["price"],
                    }
                products[r["product_id"]] = {
                    "name": r["name"],
                    "product_id": r["product_id"],
                    "variants": variants,
                }

            # ── Orders + order_items + order_fulfillments + order_payments ──
            orders_by_user: Dict[str, list] = {}
            orders: Dict[str, Any] = {}
            for r in conn.execute(
                "SELECT * FROM orders WHERE source_skill=?", (SOURCE_SKILL,)
            ):
                oid = r["order_id"]
                status = _g(r, "status", "processed")
                if status not in _TAU2_ORDER_STATUS:
                    status = "processed"
                user_id = _g(r, "customer_id")

                # Order items from normalized table
                items = []
                for oi in conn.execute(
                    "SELECT * FROM order_items WHERE order_id=?", (oid,)
                ):
                    items.append({
                        "name": _g(oi, "name", ""),
                        "product_id": oi["product_id"],
                        "item_id": _g(oi, "item_id", ""),
                        "price": oi["unit_price"],
                        "options": json.loads(_g(oi, "options", "{}") or "{}"),
                    })

                # Fulfillments from normalized table
                fulfillments = []
                for f in conn.execute(
                    "SELECT * FROM order_fulfillments WHERE order_id=?", (oid,)
                ):
                    fulfillments.append({
                        "tracking_id": json.loads(_g(f, "tracking_ids", "[]") or "[]"),
                        "item_ids": json.loads(_g(f, "item_ids", "[]") or "[]"),
                    })

                # Payment history from normalized table
                payment_history = []
                for p in conn.execute(
                    "SELECT * FROM order_payments WHERE order_id=?", (oid,)
                ):
                    payment_history.append({
                        "transaction_type": p["transaction_type"],
                        "amount": p["amount"],
                        "payment_method_id": p["payment_method_id"],
                    })

                orders[oid] = {
                    "order_id": oid,
                    "user_id": user_id,
                    "address": json.loads(_g(r, "address_json", "{}") or "{}"),
                    "items": items,
                    "status": status,
                    "fulfillments": fulfillments,
                    "payment_history": payment_history,
                    "cancel_reason": _g(r, "cancel_reason"),
                    "exchange_items": json.loads(_g(r, "exchange_items") or "null"),
                    "exchange_new_items": json.loads(
                        _g(r, "exchange_new_items") or "null"
                    ),
                    "exchange_payment_method_id": _g(r, "exchange_payment_method_id"),
                    "exchange_price_difference": _g(r, "exchange_price_difference"),
                    "return_items": json.loads(_g(r, "return_items") or "null"),
                    "return_payment_method_id": _g(r, "return_payment_method_id"),
                }
                if user_id is not None:
                    orders_by_user.setdefault(user_id, []).append(oid)

            # ── Users + rt_payment_methods ───────────────────────────
            users: Dict[str, Any] = {}
            for r in conn.execute(
                "SELECT * FROM users WHERE skill_ids_json LIKE ?",
                (f'%"{SOURCE_SKILL}"%',),
            ):
                uid = r["user_id"]
                pms: Dict[str, Any] = {}
                for pm in conn.execute(
                    "SELECT * FROM rt_payment_methods WHERE user_id=?", (uid,)
                ):
                    pms[pm["payment_method_id"]] = _build_payment_method(pm)

                users[uid] = {
                    "user_id": uid,
                    "name": _split_name(r["name"]),
                    "address": json.loads(_g(r, "address_json", "{}") or "{}"),
                    "email": r["email"],
                    "payment_methods": pms,
                    "orders": orders_by_user.get(uid, []),
                }
        finally:
            conn.close()
        return cls.model_validate(
            {"products": products, "users": users, "orders": orders}
        )

    def save(self, path: Optional[str] = None) -> None:
        """Write mutations back to the unified world.db (normalized tables).

        Persists user payment methods (gift-card balance changes via
        rt_payment_methods), order rows + order_items + order_payments +
        order_fulfillments. Products are read-only in the retail domain.
        """
        conn = _connect()
        try:
            cur = conn.cursor()

            # ── Users: update name/email/address + upsert payment methods ──
            for uid, user in self.users.items():
                cur.execute(
                    "UPDATE users SET name=?, email=?, address_json=? WHERE user_id=?",
                    (
                        f"{user.name.first_name} {user.name.last_name}".strip(),
                        user.email,
                        json.dumps(user.address.model_dump()),
                        uid,
                    ),
                )
                for pm_id, pm in user.payment_methods.items():
                    pm_data = pm.model_dump()
                    cur.execute(
                        """INSERT OR REPLACE INTO rt_payment_methods
                           (payment_method_id, user_id, source, brand, last_four, balance)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            pm_id,
                            uid,
                            pm_data.get("source", ""),
                            pm_data.get("brand"),
                            pm_data.get("last_four"),
                            pm_data.get("balance", 0.0),
                        ),
                    )

            # ── Orders: upsert order row + replace child rows ──────────
            for oid, order in self.orders.items():
                # Upsert the order row
                order_cols = {
                    "customer_id": order.user_id,
                    "status": order.status,
                    "address_json": json.dumps(order.address.model_dump()),
                    "cancel_reason": order.cancel_reason,
                    "exchange_items": json.dumps(order.exchange_items)
                    if order.exchange_items is not None
                    else None,
                    "exchange_new_items": json.dumps(order.exchange_new_items)
                    if order.exchange_new_items is not None
                    else None,
                    "exchange_payment_method_id": order.exchange_payment_method_id,
                    "exchange_price_difference": order.exchange_price_difference,
                    "return_items": json.dumps(order.return_items)
                    if order.return_items is not None
                    else None,
                    "return_payment_method_id": order.return_payment_method_id,
                    "source_skill": SOURCE_SKILL,
                }
                set_clause = ", ".join(f"{c}=?" for c in order_cols)
                cur.execute(
                    f"UPDATE orders SET {set_clause} WHERE order_id=?",
                    (*order_cols.values(), oid),
                )
                if cur.rowcount == 0:
                    # Insert new order with sensible defaults for CS columns
                    insert_cols = {
                        "order_id": oid,
                        "order_date": "2026-09-11T10:00:00",
                        "shipping_status": "pending",
                        **order_cols,
                    }
                    col_names = ", ".join(insert_cols.keys())
                    placeholders = ", ".join("?" for _ in insert_cols)
                    cur.execute(
                        f"INSERT INTO orders ({col_names}) VALUES ({placeholders})",
                        tuple(insert_cols.values()),
                    )

                # Replace order_items (delete + reinsert)
                cur.execute("DELETE FROM order_items WHERE order_id=?", (oid,))
                for idx, item in enumerate(order.items):
                    oi_id = f"RT-{oid}-{idx}"
                    cur.execute(
                        """INSERT INTO order_items
                           (oi_id, order_id, product_id, item_id, name,
                            unit_price, options)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            oi_id,
                            oid,
                            item.product_id,
                            item.item_id,
                            item.name,
                            item.price,
                            json.dumps(item.options),
                        ),
                    )

                # Replace order_payments
                cur.execute("DELETE FROM order_payments WHERE order_id=?", (oid,))
                for p in order.payment_history:
                    cur.execute(
                        """INSERT INTO order_payments
                           (order_id, transaction_type, amount, payment_method_id)
                           VALUES (?, ?, ?, ?)""",
                        (oid, p.transaction_type, p.amount, p.payment_method_id),
                    )

                # Replace order_fulfillments
                cur.execute(
                    "DELETE FROM order_fulfillments WHERE order_id=?", (oid,)
                )
                for f in order.fulfillments:
                    cur.execute(
                        """INSERT INTO order_fulfillments
                           (order_id, tracking_ids, item_ids)
                           VALUES (?, ?, ?)""",
                        (
                            oid,
                            json.dumps(f.tracking_id),
                            json.dumps(f.item_ids),
                        ),
                    )

            conn.commit()
        finally:
            conn.close()

    def dump(self, path: Optional[str] = None, **kwargs: Any) -> None:
        """Back-compat alias for save()."""
        self.save(path)


def get_db():
    return RetailDB.load()


if __name__ == "__main__":
    db = get_db()
    print(db.get_statistics())
