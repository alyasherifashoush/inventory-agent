"""Tools the agent can call to read the inventory database.

Each function is decorated with @tool. The LLM never sees the code inside,
only the function name, the arguments (with their types) and the docstring.
So the docstring is written FOR THE LLM: what the tool does and when to use it.
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from langchain.tools import tool

DB_PATH = Path(__file__).parent / "data" / "inventory.db"


def get_connection():
    """Open the database. Rows come back like dicts: row["name"] instead of row[1]."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@tool
def get_expiring_products(days: int = 7) -> list[dict]:
    """List stock batches that have already expired or will expire within the
    next `days` days, soonest first.

    Also includes batches that have ALREADY expired (days_left is negative),
    because those must be removed from the shelves.
    Use this for questions about expiry, waste, or what to sell or discount first.
    """
    today = date.today()
    limit = (today + timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.name AS product, b.quantity, b.expiry_date,
                   CAST(julianday(b.expiry_date) - julianday(?) AS INTEGER) AS days_left,
                   p.unit_cost, p.unit_price
            FROM batches b
            JOIN products p ON p.id = b.product_id
            WHERE b.expiry_date <= ?
            ORDER BY b.expiry_date
            """,
            (today.isoformat(), limit),
        ).fetchall()
    return [dict(row) for row in rows]


@tool
def get_low_stock_products() -> list[dict]:
    """List products whose usable stock (expired batches excluded) is below their
    reorder level, together with the supplier to contact and their delivery lead time.

    Use this for questions about reordering, shortages, or which suppliers to contact.
    """
    today = date.today().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.name AS product,
                   COALESCE(SUM(CASE WHEN b.expiry_date >= ? THEN b.quantity END), 0) AS stock,
                   p.reorder_level,
                   s.name AS supplier, s.email AS supplier_email, s.lead_time_days
            FROM products p
            JOIN suppliers s ON s.id = p.supplier_id
            LEFT JOIN batches b ON b.product_id = p.id
            GROUP BY p.id
            HAVING stock < p.reorder_level
            ORDER BY stock * 1.0 / p.reorder_level
            """,
            (today,),
        ).fetchall()
    return [dict(row) for row in rows]


@tool
def get_slow_moving_products(days: int = 30, max_units_sold: int = 10) -> list[dict]:
    """List products that sold `max_units_sold` units or fewer in the last `days` days
    but still have usable stock on the shelf.
    Slow movers tie up money and shelf space, so they are candidates for discounts.
    The defaults (last 30 days, 10 units or fewer) are the store's standard definition
    of a slow mover: use them unless the manager asks for something different.
    """
    today = date.today()
    since = (today - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.name AS product,
                   (SELECT COALESCE(SUM(quantity), 0) FROM sales
                     WHERE product_id = p.id AND sale_date >= ?) AS units_sold,
                   (SELECT COALESCE(SUM(quantity), 0) FROM batches
                     WHERE product_id = p.id AND expiry_date >= ?) AS stock,
                   p.unit_cost, p.unit_price
            FROM products p
            WHERE units_sold <= ? AND stock > 0
            ORDER BY units_sold
            """,
            (since, today.isoformat(), max_units_sold),
        ).fetchall()
    return [dict(row) for row in rows]


@tool
def get_product_details(product_name: str) -> dict:
    """Get everything about one product: category, cost, price, usable stock,
    its batches with expiry dates, units sold in the last 30 days, and its supplier.

    `product_name` can be part of the name, e.g. "milk" or "rice".
    """
    today = date.today()
    with get_connection() as conn:
        product = conn.execute(
            """
            SELECT p.id, p.name, p.category, p.unit_cost, p.unit_price, p.reorder_level,
                   s.name AS supplier, s.email AS supplier_email, s.lead_time_days
            FROM products p JOIN suppliers s ON s.id = p.supplier_id
            WHERE p.name LIKE ?
            """,
            (f"%{product_name}%",),
        ).fetchone()
        if product is None:
            return {"error": f"No product matches '{product_name}'."}

        batches = conn.execute(
            "SELECT quantity, received_date, expiry_date FROM batches "
            "WHERE product_id = ? ORDER BY expiry_date",
            (product["id"],),
        ).fetchall()
        units_sold = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM sales "
            "WHERE product_id = ? AND sale_date >= ?",
            (product["id"], (today - timedelta(days=30)).isoformat()),
        ).fetchone()[0]

    details = dict(product)
    details["batches"] = [dict(b) for b in batches]
    details["usable_stock"] = sum(
        b["quantity"] for b in batches if b["expiry_date"] >= today.isoformat()
    )
    details["units_sold_last_30_days"] = units_sold
    return details


# All tools in one list, so other files can import them together.
ALL_TOOLS = [
    get_expiring_products,
    get_low_stock_products,
    get_slow_moving_products,
    get_product_details,
]