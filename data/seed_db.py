"""Create and fill the inventory database with realistic sample data.

Run from the project root:  python data/seed_db.py
Running it again deletes the old database and builds a fresh one.
"""
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "inventory.db"   # data/inventory.db
TODAY = date.today()
random.seed(42)  # same "random" data on every run

# (name, email, lead_time_days)
SUPPLIERS = [
    ("FreshFarm Dairy", "orders@freshfarm.example", 2),
    ("Nile Bakery Co.", "sales@nilebakery.example", 1),
    ("GreenLeaf Produce", "supply@greenleaf.example", 1),
    ("Delta Dry Goods", "orders@deltadry.example", 5),
]

# (name, category, unit_cost, unit_price, reorder_level, supplier_index, shelf_life_days)
# Prices in EGP. supplier_index points into the SUPPLIERS list above.
PRODUCTS = [
    ("Full-fat milk 1L", "Dairy", 28, 38, 40, 0, 10),
    ("Greek yogurt 500g", "Dairy", 35, 50, 25, 0, 21),
    ("Cheddar cheese 200g", "Dairy", 60, 85, 15, 0, 60),
    ("Butter 250g", "Dairy", 70, 95, 15, 0, 90),
    ("White bread loaf", "Bakery", 15, 25, 30, 1, 5),
    ("Croissants (6 pack)", "Bakery", 40, 60, 15, 1, 4),
    ("Whole-wheat toast", "Bakery", 22, 32, 20, 1, 7),
    ("Tomatoes 1kg", "Produce", 12, 20, 30, 2, 8),
    ("Bananas 1kg", "Produce", 18, 28, 25, 2, 6),
    ("Baby spinach 250g", "Produce", 20, 32, 15, 2, 5),
    ("Basmati rice 5kg", "Dry Goods", 180, 240, 10, 3, 365),
    ("Pasta 500g", "Dry Goods", 18, 27, 30, 3, 540),
    ("Olive oil 1L", "Dry Goods", 210, 290, 8, 3, 540),
    ("Canned tuna 160g", "Dry Goods", 45, 65, 20, 3, 720),
]

SCHEMA = """
CREATE TABLE suppliers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    lead_time_days  INTEGER NOT NULL
);

CREATE TABLE products (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    unit_cost       REAL NOT NULL,
    unit_price      REAL NOT NULL,
    reorder_level   INTEGER NOT NULL,
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id)
);

CREATE TABLE batches (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    quantity        INTEGER NOT NULL,
    received_date   TEXT NOT NULL,
    expiry_date     TEXT NOT NULL
);

CREATE TABLE sales (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    sale_date       TEXT NOT NULL,
    quantity        INTEGER NOT NULL
);
"""


def insert_data(conn):
    # Suppliers: remember each new id so products can point to the right one
    supplier_ids = []
    for name, email, lead_time in SUPPLIERS:
        cur = conn.execute(
            "INSERT INTO suppliers (name, email, lead_time_days) VALUES (?, ?, ?)",
            (name, email, lead_time),
        )
        supplier_ids.append(cur.lastrowid)

    for name, category, cost, price, reorder, sup_idx, shelf_life in PRODUCTS:
        cur = conn.execute(
            """INSERT INTO products
               (name, category, unit_cost, unit_price, reorder_level, supplier_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, category, cost, price, reorder, supplier_ids[sup_idx]),
        )
        product_id = cur.lastrowid

        # Stock: 1-3 deliveries (batches), each with its own expiry date.
        # Received up to shelf_life + 2 days ago, so a few batches are already expired.
        for _ in range(random.randint(1, 3)):
            days_ago = random.randint(0, min(shelf_life + 2, 60))
            received = TODAY - timedelta(days=days_ago)
            expiry = received + timedelta(days=shelf_life)
            conn.execute(
                """INSERT INTO batches (product_id, quantity, received_date, expiry_date)
                   VALUES (?, ?, ?, ?)""",
                (product_id, random.randint(3, 30), received.isoformat(), expiry.isoformat()),
            )

        # Sales over the last 30 days. Popularity 0 = a product that never sells (slow mover).
        popularity = random.choice([0, 1, 3, 6, 10])
        for days_ago in range(1, 31):
            qty = random.randint(0, popularity)
            if qty > 0:
                conn.execute(
                    "INSERT INTO sales (product_id, sale_date, quantity) VALUES (?, ?, ?)",
                    (product_id, (TODAY - timedelta(days=days_ago)).isoformat(), qty),
                )


def print_summary(conn):
    print(f"Database created at: {DB_PATH}")
    for table in ("suppliers", "products", "batches", "sales"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<10} {count} rows")

    today = TODAY.isoformat()
    in_3_days = (TODAY + timedelta(days=3)).isoformat()
    expired = conn.execute(
        "SELECT COUNT(*) FROM batches WHERE expiry_date < ?", (today,)
    ).fetchone()[0]
    expiring = conn.execute(
        "SELECT COUNT(*) FROM batches WHERE expiry_date BETWEEN ? AND ?", (today, in_3_days)
    ).fetchone()[0]
    print(f"  Batches already expired:       {expired}")
    print(f"  Batches expiring in <= 3 days: {expiring}")


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()          # start fresh every time

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)    # create the 4 tables
    insert_data(conn)
    conn.commit()                 # save everything to the file
    print_summary(conn)
    conn.close()


if __name__ == "__main__":
    main()