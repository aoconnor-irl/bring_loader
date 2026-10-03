"""Small, dependency-free data layer shared by the app and CSV importer."""
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS groups (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 unit TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS group_items (
 id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
 item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
 quantity TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
 UNIQUE(group_id, item_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def quantity(raw):
    try:
        number = Decimal(str(raw).strip())
    except Exception as exc:
        raise ValueError("Quantity must be a number") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError("Quantity must be greater than zero")
    return number


def format_quantity(number):
    return format(number.normalize(), "f")


def aggregate(conn, counts):
    """Return consolidated (name, quantity, unit) tuples for selected group IDs."""
    totals = defaultdict(Decimal)
    rows = conn.execute("""SELECT gi.group_id, i.name, i.unit, gi.quantity
        FROM group_items gi JOIN items i ON i.id=gi.item_id""")
    for row in rows:
        count = int(counts.get(row["group_id"], 0))
        if count > 0:
            totals[(row["name"], row["unit"])] += quantity(row["quantity"]) * count
    return [(name, format_quantity(total), unit)
            for (name, unit), total in sorted(totals.items(), key=lambda pair: pair[0][0].casefold())]


def setting(conn, key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
