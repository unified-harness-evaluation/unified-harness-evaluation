"""SQLite state layer for ToolSandboxAssistant.

Replaces the original Polars ``ExecutionContext``. State lives in the unified
per-task ``world.db`` seeded into ``/workspace`` by the experiment runner. This
skill owns the ``ts_``-prefixed tables (``ts_contacts``, ``ts_messages``,
``ts_reminders``, ``ts_device_settings``); the library callers still refer to
the logical, unprefixed names (``contacts`` etc.), which ``_TABLE_MAP`` rewrites
to the ``ts_*`` physical tables here.

The DB path is taken from the ``TOOLSANDBOX_ASSISTANT_DB`` environment variable,
else the unified ``world.db`` in the workspace root (``./world.db``, which is
``/workspace/world.db`` in the sandbox). Because the runner seeds a fresh
``world.db`` per task, this layer never rebuilds or deletes the database:
``reset`` is a no-op and there is no bundled seed.

Search semantics mirror the original ``filter_dataframe`` helpers, including
fuzzy matching backed by ``rapidfuzz`` ``process.extract`` / ``fuzz.WRatio``
(and its default top-5 limit).
"""

import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process, utils

from ._common import NOT_GIVEN

DB_PATH_ENV = "TOOLSANDBOX_ASSISTANT_DB"

# Logical table name -> physical table in the unified world.db.
_TABLE_MAP = {
    "contacts": "ts_contacts",
    "messages": "ts_messages",
    "reminders": "ts_reminders",
    "device_settings": "ts_device_settings",
}


def _phys(table: str) -> str:
    """Map a logical table name to its physical ``ts_*`` table in world.db."""
    return _TABLE_MAP.get(table, table)


# Columns that are stored as SQLite INTEGER but represent booleans.
_BOOLEAN_COLUMNS = {"is_self", "cellular", "wifi", "location_service", "low_battery_mode"}
# Columns to expose as floats.
_FLOAT_COLUMNS = {"latitude", "longitude", "creation_timestamp", "reminder_timestamp"}


def working_db_path() -> Path:
    """Resolve the unified world.db path (env override, else workspace root)."""
    override = os.environ.get(DB_PATH_ENV)
    if override:
        return Path(override)
    for candidate in (Path.cwd() / "world.db", Path("/workspace/world.db")):
        if candidate.exists():
            return candidate
    return Path.cwd() / "world.db"


def ensure_db() -> Path:
    """Return the unified world.db path. Never seeds — the runner does that."""
    return working_db_path()


def reset() -> Path:
    """No-op: world.db is seeded fresh per task by the runner. Returns its path."""
    return working_db_path()


def connect() -> sqlite3.Connection:
    """Open a connection to the unified world.db with dict-style rows."""
    path = ensure_db()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _coerce(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a SQLite row into a dict with booleans/floats normalized."""
    out: Dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if value is None:
            out[key] = None
        elif key in _BOOLEAN_COLUMNS:
            out[key] = bool(value)
        elif key in _FLOAT_COLUMNS:
            out[key] = float(value)
        else:
            out[key] = value
    return out


def fetch_rows(table: str, columns: List[str]) -> List[Dict[str, Any]]:
    """Fetch all rows of ``table`` (selected ``columns``) as coerced dicts."""
    conn = connect()
    try:
        cur = conn.execute(f"SELECT {', '.join(columns)} FROM {_phys(table)}")
        return [_coerce(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── Filter helpers (mirror tool_sandbox.common.utils) ─────────────────────────
def exact_match_filter(rows: List[Dict[str, Any]], column: str, value: Any) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get(column) == value]


def gt_eq_filter(rows: List[Dict[str, Any]], column: str, value: Any) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get(column) is not None and r[column] >= value]


def lt_eq_filter(rows: List[Dict[str, Any]], column: str, value: Any) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get(column) is not None and r[column] <= value]


def fuzzy_match_filter(
    rows: List[Dict[str, Any]], column: str, value: Any, threshold: float = 90
) -> List[Dict[str, Any]]:
    """Fuzzy match ``value`` against ``column`` using rapidfuzz WRatio.

    Preserves the original behavior, including ``process.extract``'s default
    top-5 limit and ``utils.default_process`` normalization.
    """
    choices = ["" if r.get(column) is None else str(r[column]) for r in rows]
    matches = process.extract(
        query=value,
        choices=choices,
        processor=utils.default_process,
        scorer=fuzz.WRatio,
        score_cutoff=threshold,
    )
    return [rows[m[-1]] for m in matches]


# A criterion is (column, value, method, kwargs).
Criterion = Tuple[str, Any, Callable[..., List[Dict[str, Any]]], Dict[str, Any]]


def search(rows: List[Dict[str, Any]], criteria: List[Criterion]) -> List[Dict[str, Any]]:
    """Apply criteria in order, skipping any whose value is NOT_GIVEN.

    Raises:
        ValueError: if every criterion's value is NOT_GIVEN (matches original).
    """
    if all(value is NOT_GIVEN for _, value, _, _ in criteria):
        raise ValueError(
            "No search criteria are given. At least one search criteria should be "
            f"provided among {tuple(name for name, _, _, _ in criteria)}"
        )
    result = rows
    for column, value, method, kwargs in criteria:
        if value is not NOT_GIVEN:
            result = method(result, column, value, **kwargs)
    return result


# ── Write helpers ─────────────────────────────────────────────────────────────
def insert(table: str, row: Dict[str, Any]) -> None:
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    conn = connect()
    try:
        conn.execute(
            f"INSERT INTO {_phys(table)} ({', '.join(cols)}) VALUES ({placeholders})",
            [_to_sql(v) for v in row.values()],
        )
        conn.commit()
    finally:
        conn.close()


def update(table: str, id_column: str, id_value: str, updates: Dict[str, Any]) -> int:
    """Update matching rows. Returns the number of rows affected."""
    assignments = ", ".join(f"{c} = ?" for c in updates)
    params = [_to_sql(v) for v in updates.values()] + [id_value]
    conn = connect()
    try:
        cur = conn.execute(
            f"UPDATE {_phys(table)} SET {assignments} WHERE {id_column} = ?", params
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete(table: str, id_column: str, id_value: str) -> int:
    """Delete matching rows. Returns the number of rows affected."""
    conn = connect()
    try:
        cur = conn.execute(f"DELETE FROM {_phys(table)} WHERE {id_column} = ?", (id_value,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def count(table: str, id_column: str, id_value: str) -> int:
    conn = connect()
    try:
        cur = conn.execute(
            f"SELECT COUNT(*) FROM {_phys(table)} WHERE {id_column} = ?", (id_value,)
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def get_settings_row() -> Optional[Dict[str, Any]]:
    rows = fetch_rows(
        "device_settings",
        [
            "device_id",
            "cellular",
            "wifi",
            "location_service",
            "low_battery_mode",
            "latitude",
            "longitude",
        ],
    )
    return rows[0] if rows else None


def _to_sql(value: Any) -> Any:
    """Convert Python values to SQLite-storable ones (bool -> int)."""
    if isinstance(value, bool):
        return int(value)
    return value
