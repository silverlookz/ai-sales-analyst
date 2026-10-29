"""Generate a realistic synthetic sales warehouse in SQLite.

Star schema: fact_order_lines + dim_product, dim_customer, dim_region, dim_date.
Seeded, so every run produces the same data (tests depend on it).

    python scripts/generate_data.py            # -> data/sales.db
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "sales.db"

REGIONS = [
    (1, "Ontario", "Central"), (2, "Quebec", "East"), (3, "British Columbia", "West"),
    (4, "Alberta", "West"), (5, "Atlantic", "East"), (6, "Prairies", "Central"),
]
PRODUCTS = [  # id, name, category, unit_price, unit_cost
    (1, "Laptop Pro 14", "Computers", 1899, 1350), (2, "Laptop Air 13", "Computers", 1299, 930),
    (3, "Desktop Tower", "Computers", 1499, 1080), (4, "27in Monitor", "Displays", 429, 290),
    (5, "34in Ultrawide", "Displays", 799, 560), (6, "Wireless Mouse", "Accessories", 49, 18),
    (7, "Mechanical Keyboard", "Accessories", 139, 62), (8, "USB-C Dock", "Accessories", 249, 140),
    (9, "Noise-Cancel Headset", "Audio", 299, 170), (10, "Conference Speaker", "Audio", 399, 230),
    (11, "Cloud Backup (1yr)", "Services", 120, 25), (12, "Extended Warranty", "Services", 199, 40),
]
SEGMENTS = ["Enterprise", "Mid-Market", "Small Business", "Consumer"]
CHANNELS = ["Online", "Direct Sales", "Partner"]
REGION_WEIGHT = [0.34, 0.2, 0.18, 0.13, 0.07, 0.08]


def build(db_path: Path = DB_PATH, seed: int = 42, n_customers: int = 600, n_orders: int = 6000) -> Path:
    rng = random.Random(seed)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE dim_region (region_id INTEGER PRIMARY KEY, region_name TEXT, zone TEXT);
    CREATE TABLE dim_product (product_id INTEGER PRIMARY KEY, product_name TEXT, category TEXT,
                              unit_price REAL, unit_cost REAL);
    CREATE TABLE dim_customer (customer_id INTEGER PRIMARY KEY, customer_name TEXT, segment TEXT,
                               region_id INTEGER REFERENCES dim_region(region_id));
    CREATE TABLE dim_date (date_key TEXT PRIMARY KEY, year INTEGER, quarter INTEGER, month INTEGER,
                           month_name TEXT);
    CREATE TABLE fact_order_lines (
        line_id INTEGER PRIMARY KEY, order_id INTEGER, order_date TEXT REFERENCES dim_date(date_key),
        customer_id INTEGER REFERENCES dim_customer(customer_id),
        product_id INTEGER REFERENCES dim_product(product_id), channel TEXT,
        quantity INTEGER, discount_pct REAL, revenue REAL, cost REAL);
    """)
    cur.executemany("INSERT INTO dim_region VALUES (?,?,?)", REGIONS)
    cur.executemany("INSERT INTO dim_product VALUES (?,?,?,?,?)", PRODUCTS)

    customers = []
    for cid in range(1, n_customers + 1):
        seg = rng.choices(SEGMENTS, weights=[0.12, 0.23, 0.35, 0.30])[0]
        region = rng.choices([r[0] for r in REGIONS], weights=REGION_WEIGHT)[0]
        customers.append((cid, f"Customer {cid:04d}", seg, region))
    cur.executemany("INSERT INTO dim_customer VALUES (?,?,?,?)", customers)

    start, end = date(2024, 1, 1), date(2025, 12, 31)
    d = start
    while d <= end:
        cur.execute("INSERT INTO dim_date VALUES (?,?,?,?,?)",
                    (d.isoformat(), d.year, (d.month - 1) // 3 + 1, d.month, d.strftime("%B")))
        d += timedelta(days=1)

    days = (end - start).days
    line_id = 0
    for oid in range(1, n_orders + 1):
        # growth trend into 2025 + Q4 seasonality
        offset = int(days * rng.random() ** 0.85)
        odate = start + timedelta(days=offset)
        if odate.month in (11, 12) and rng.random() < 0.3:
            odate = odate.replace(day=min(odate.day, 28))
        cust = rng.choice(customers)
        channel = rng.choices(CHANNELS, weights=[0.45, 0.35, 0.20])[0]
        qty_scale = {"Enterprise": 8, "Mid-Market": 4, "Small Business": 2, "Consumer": 1}[cust[2]]
        for prod in rng.sample(PRODUCTS, k=rng.randint(1, 3)):
            line_id += 1
            qty = max(1, int(rng.expovariate(1 / qty_scale)) + 1)
            disc = rng.choice([0, 0, 0, 0.05, 0.1, 0.15]) if cust[2] != "Consumer" else rng.choice([0, 0, 0.05])
            revenue = round(prod[3] * qty * (1 - disc), 2)
            cur.execute("INSERT INTO fact_order_lines VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (line_id, oid, odate.isoformat(), cust[0], prod[0], channel, qty, disc,
                         revenue, round(prod[4] * qty, 2)))
    con.commit()
    con.close()
    return db_path


if __name__ == "__main__":
    path = build()
    print(f"Built {path}")
