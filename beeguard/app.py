"""BeeGuard's dependency-free Python backend.



The application intentionally uses Python's standard library plus SQLite so it

can run on a fresh Python installation. It serves the browser UI and JSON API

from one local address.

"""



from __future__ import annotations



import json

import os

import re

import sqlite3

from datetime import date

from http import HTTPStatus

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from typing import Any

from urllib.parse import parse_qs, unquote, urlparse





ROOT = Path(__file__).resolve().parent

PUBLIC = ROOT / "public"

DATABASE_PATH = Path(os.environ.get("BEEGUARD_DB_PATH", ROOT / "data" / "beeguard.db"))

HOST = os.environ.get("HOST", "127.0.0.1")

PORT = int(os.environ.get("PORT", "5000"))

MAX_BODY_BYTES = 1_000_000





class ApiError(Exception):

    def __init__(self, status: int, message: str, code: str = "BAD_REQUEST") -> None:

        self.status = status

        self.message = message

        self.code = code

        super().__init__(message)





def connection() -> sqlite3.Connection:

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(DATABASE_PATH)

    db.row_factory = sqlite3.Row

    db.execute("PRAGMA foreign_keys = ON")

    return db





def ensure_column(db: sqlite3.Connection, table: str, column: str, declaration: str) -> None:

    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}

    if column not in columns:

        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")





def seed_farmer(

    db: sqlite3.Connection,

    *,

    name: str,

    farm_name: str,

    location: str,

    district: str,

    state: str,

    crop: str,

    phone: str,

    email: str,

    bio: str,

    specialty: str,

    experience_years: int,

    verified: int,

    crops: list[tuple[str, float, str]],

) -> int:

    row = db.execute("SELECT id FROM farmers WHERE farm_name = ?", (farm_name,)).fetchone()

    if row:

        farmer_id = row["id"]

        db.execute(

            """

            UPDATE farmers

            SET name = ?, location = ?, crop = ?, district = ?, state = ?, phone = ?,

                email = ?, bio = ?, specialty = ?, experience_years = ?, verified = ?

            WHERE id = ?

            """,

            (

                name,

                location,

                crop,

                district,

                state,

                phone,

                email,

                bio,

                specialty,

                experience_years,

                verified,

                farmer_id,

            ),

        )

    else:

        cursor = db.execute(

            """

            INSERT INTO farmers

            (name, farm_name, location, crop, district, state, phone, email, bio, specialty, experience_years, verified)

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            """,

            (

                name,

                farm_name,

                location,

                crop,

                district,

                state,

                phone,

                email,

                bio,

                specialty,

                experience_years,

                verified,

            ),

        )

        farmer_id = int(cursor.lastrowid)



    for crop_name, acreage, season in crops:

        db.execute(

            """

            INSERT OR IGNORE INTO farmer_crops (farmer_id, crop, area_acres, flowering_season)

            VALUES (?, ?, ?, ?)

            """,

            (farmer_id, crop_name, acreage, season),

        )

    return farmer_id





def initialize_database() -> None:

    with connection() as db:

        # The first four tables also make a Python-only install work when no

        # database was created by the earlier Node prototype.

        db.executescript(

            """

            CREATE TABLE IF NOT EXISTS farmers (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                farm_name TEXT NOT NULL,

                location TEXT NOT NULL,

                crop TEXT NOT NULL,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

            );

            CREATE TABLE IF NOT EXISTS beekeepers (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                apiary_name TEXT NOT NULL,

                location TEXT NOT NULL,

                hive_count INTEGER NOT NULL DEFAULT 0,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

            );

            CREATE TABLE IF NOT EXISTS hives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                beekeeper_id INTEGER NOT NULL,
                hive_name TEXT NOT NULL,
                location TEXT NOT NULL,
                health_score INTEGER NOT NULL CHECK (health_score BETWEEN 0 AND 100),
                pollination_score INTEGER NOT NULL CHECK (pollination_score BETWEEN 0 AND 100),
                status TEXT NOT NULL DEFAULT 'occupied' CHECK (status IN ('occupied', 'available', 'maintenance')),
                bee_count INTEGER NOT NULL DEFAULT 0 CHECK (bee_count >= 0),
                FOREIGN KEY (beekeeper_id) REFERENCES beekeepers(id)
            );

            CREATE TABLE IF NOT EXISTS honey_products (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                seller_name TEXT NOT NULL,

                honey_type TEXT NOT NULL,

                price_per_kg REAL NOT NULL CHECK (price_per_kg >= 0),

                quantity_kg REAL NOT NULL CHECK (quantity_kg >= 0),

                origin TEXT NOT NULL,

                batch_id TEXT NOT NULL UNIQUE COLLATE NOCASE,

                quality_status TEXT NOT NULL DEFAULT 'Pending',

                hive_id INTEGER,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

            );

            CREATE TABLE IF NOT EXISTS pesticide_alerts (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                farm_name TEXT NOT NULL,

                distance_km REAL NOT NULL CHECK (distance_km >= 0),

                risk_level TEXT NOT NULL CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),

                spray_date TEXT NOT NULL,

                message TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'protected')),

                protected_at TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

            );

            CREATE TABLE IF NOT EXISTS hive_matches (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                crop TEXT NOT NULL,

                distance_km REAL NOT NULL,

                flower_availability INTEGER NOT NULL,

                score INTEGER NOT NULL,

                recommendation TEXT NOT NULL,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

            );

            CREATE TABLE IF NOT EXISTS farmer_crops (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                farmer_id INTEGER NOT NULL,

                crop TEXT NOT NULL,

                area_acres REAL,

                flowering_season TEXT,

                FOREIGN KEY (farmer_id) REFERENCES farmers(id) ON DELETE CASCADE,

                UNIQUE (farmer_id, crop)

            );

            CREATE TABLE IF NOT EXISTS honey_batch_events (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                honey_product_id INTEGER NOT NULL,

                event_type TEXT NOT NULL,

                title TEXT NOT NULL,

                details TEXT,

                event_date TEXT NOT NULL,

                sort_order INTEGER NOT NULL DEFAULT 0,

                FOREIGN KEY (honey_product_id) REFERENCES honey_products(id) ON DELETE CASCADE

            );

            CREATE TABLE IF NOT EXISTS chatbot_faqs (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                question TEXT NOT NULL,

                keywords TEXT NOT NULL,

                answer TEXT NOT NULL

            );

            """

        )



        # Safe additive migration from the first BeeGuard prototype.

        for table, column, declaration in (

            ("farmers", "district", "TEXT"),

            ("farmers", "state", "TEXT"),

            ("farmers", "phone", "TEXT"),

            ("farmers", "email", "TEXT"),

            ("farmers", "bio", "TEXT"),

            ("farmers", "specialty", "TEXT"),

            ("farmers", "experience_years", "INTEGER"),

            ("farmers", "verified", "INTEGER NOT NULL DEFAULT 0"),

            ("honey_products", "farmer_id", "INTEGER"),

            ("honey_products", "harvest_date", "TEXT"),

            ("honey_products", "floral_source", "TEXT"),

            ("honey_products", "certificate_code", "TEXT"),

            ("honey_products", "is_active", "INTEGER NOT NULL DEFAULT 1"),
            ("honey_products", "hive_id", "INTEGER"),
            ("hives", "status", "TEXT NOT NULL DEFAULT 'occupied'"),
            ("hives", "bee_count", "INTEGER NOT NULL DEFAULT 0"),

        ):

            ensure_column(db, table, column, declaration)



        db.executescript(

            """

            CREATE INDEX IF NOT EXISTS idx_farmers_district ON farmers (district);

            CREATE INDEX IF NOT EXISTS idx_farmers_verified ON farmers (verified);

            CREATE INDEX IF NOT EXISTS idx_farmer_crops_crop ON farmer_crops (crop);

            CREATE INDEX IF NOT EXISTS idx_honey_farmer ON honey_products (farmer_id);

            CREATE INDEX IF NOT EXISTS idx_honey_type_price ON honey_products (honey_type, price_per_kg);

            CREATE INDEX IF NOT EXISTS idx_honey_events_batch ON honey_batch_events (honey_product_id, sort_order);

            CREATE INDEX IF NOT EXISTS idx_alert_status_created ON pesticide_alerts (status, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_hive_status ON hives (status);

            CREATE INDEX IF NOT EXISTS idx_honey_hive ON honey_products (hive_id);

            """

        )



        profiles = [

            {

                "name": "Meera Nair",

                "farm_name": "Green Valley Apiary",

                "location": "Hunsur Road, Mysuru",

                "district": "Mysuru",

                "state": "Karnataka",

                "crop": "Wildflower",

                "phone": "+91 90000 10001",

                "email": "meera@beeguard.demo",

                "bio": "A small-batch beekeeper working with pesticide-aware farms and native flowering corridors.",

                "specialty": "Wildflower & eucalyptus honey",

                "experience_years": 11,

                "verified": 1,

                "crops": [("Wildflower", 12, "October–February"), ("Eucalyptus", 8, "February–April")],

            },

            {

                "name": "Arjun Kumar",

                "farm_name": "BeeFarm Karnataka",

                "location": "Malavalli, Mandya",

                "district": "Mandya",

                "state": "Karnataka",

                "crop": "Wildflower",

                "phone": "+91 90000 10002",

                "email": "arjun@beeguard.demo",

                "bio": "Producer of floral-source honey using seasonal hive movement and batch-level records.",

                "specialty": "Wildflower honey",

                "experience_years": 8,

                "verified": 1,

                "crops": [("Wildflower", 15, "September–January"), ("Mustard", 5, "December–March")],

            },

            {

                "name": "Sonal Kulkarni",

                "farm_name": "Honey World",

                "location": "Koppa, Chikkamagaluru",

                "district": "Chikkamagaluru",

                "state": "Karnataka",

                "crop": "Wildflower",

                "phone": "+91 90000 10003",

                "email": "sonal@beeguard.demo",

                "bio": "Community producer partnering with nearby coffee and forest-edge farms.",

                "specialty": "Forest wildflower honey",

                "experience_years": 14,

                "verified": 1,

                "crops": [("Wildflower", 20, "Year-round"), ("Coffee blossom", 7, "March–May")],

            },

            {

                "name": "Lakshmi Gowda",

                "farm_name": "Nature Bees",

                "location": "Nanjangud, Mysuru",

                "district": "Mysuru",

                "state": "Karnataka",

                "crop": "Mustard",

                "phone": "+91 90000 10004",

                "email": "lakshmi@beeguard.demo",

                "bio": "A farmer-beekeeper focused on pollinator-friendly mustard cultivation and transparent local sales.",

                "specialty": "Mustard honey",

                "experience_years": 6,

                "verified": 1,

                "crops": [("Mustard", 18, "November–February")],

            },

            {

                "name": "Ravi Shetty",

                "farm_name": "Pure Hive",

                "location": "Srirangapatna, Mandya",

                "district": "Mandya",

                "state": "Karnataka",

                "crop": "Sunflower",

                "phone": "+91 90000 10005",

                "email": "ravi@beeguard.demo",

                "bio": "Sunflower honey producer with a focus on maintaining healthy hives around seasonal crops.",

                "specialty": "Sunflower honey",

                "experience_years": 9,

                "verified": 1,

                "crops": [("Sunflower", 16, "January–March")],

            },

        ]

        farmer_ids = {profile["farm_name"]: seed_farmer(db, **profile) for profile in profiles}



        # Keep the original crop-farmer demo records useful in the directory.

        db.execute(

            """

            UPDATE farmers

            SET district = COALESCE(NULLIF(district, ''), 'Mysuru'),

                state = COALESCE(NULLIF(state, ''), 'Karnataka'),

                verified = COALESCE(verified, 0)

            """

        )



        if db.execute("SELECT COUNT(*) AS count FROM honey_products").fetchone()["count"] == 0:
            honey_demo = [
                ("Green Valley Apiary", "Wildflower", 450, 25, "Mysuru, Karnataka", "BG2026-001", "Verified", farmer_ids["Green Valley Apiary"], "2026-08-14", "Wildflower and eucalyptus", "BG-QUALITY-001", 1, "Sunrise Hive"),
                ("BeeFarm Karnataka", "Wildflower", 420, 40, "Mandya, Karnataka", "BG2026-002", "Verified", farmer_ids["BeeFarm Karnataka"], "2026-08-03", "Native wildflower", "BG-QUALITY-002", 1, "Orchard Hive"),
                ("Honey World", "Forest Wildflower", 520, 18, "Chikkamagaluru, Karnataka", "BG2026-003", "Verified", farmer_ids["Honey World"], "2026-07-26", "Forest wildflower", "BG-QUALITY-003", 1, "Sunrise Hive"),
                ("Nature Bees", "Mustard", 390, 30, "Mysuru, Karnataka", "BG2026-004", "Verified", farmer_ids["Nature Bees"], "2026-06-18", "Mustard blossom", "BG-QUALITY-004", 1, "Mustard Hive"),
                ("Pure Hive", "Sunflower", 410, 22, "Mandya, Karnataka", "BG2026-005", "Pending", farmer_ids["Pure Hive"], "2026-08-07", "Sunflower blossom", "BG-QUALITY-005", 1, "Orchard Hive"),
            ]
            for row in honey_demo:
                db.execute(
                    """
                    INSERT INTO honey_products
                    (seller_name, honey_type, price_per_kg, quantity_kg, origin, batch_id, quality_status,
                     farmer_id, harvest_date, floral_source, certificate_code, is_active, hive_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, (SELECT id FROM hives WHERE hive_name = ?))
                    """,
                    row,
                )


        honey_seed = {

            "Green Valley Apiary": ("Green Valley Apiary", "2026-08-14", "Wildflower and eucalyptus", "BG-QUALITY-001"),

            "BeeFarm Karnataka": ("BeeFarm Karnataka", "2026-08-03", "Native wildflower", "BG-QUALITY-002"),

            "Honey World": ("Honey World", "2026-07-26", "Forest wildflower", "BG-QUALITY-003"),

            "Nature Bees": ("Nature Bees", "2026-06-18", "Mustard blossom", "BG-QUALITY-004"),

            "Pure Hive": ("Pure Hive", "2026-08-07", "Sunflower blossom", "BG-QUALITY-005"),

        }

        for seller, (farm_name, harvest_date, floral_source, certificate) in honey_seed.items():

            db.execute(

                """

                UPDATE honey_products

                SET farmer_id = ?, harvest_date = ?, floral_source = ?, certificate_code = ?,

                    is_active = COALESCE(is_active, 1)

                WHERE seller_name = ?

                """,

                (farmer_ids[farm_name], harvest_date, floral_source, certificate, seller),

            )



        products = db.execute(

            """

            SELECT id, batch_id, harvest_date, quality_status

            FROM honey_products

            WHERE farmer_id IS NOT NULL

            """

        ).fetchall()

        for product in products:

            existing = db.execute(

                "SELECT COUNT(*) AS count FROM honey_batch_events WHERE honey_product_id = ?",

                (product["id"],),

            ).fetchone()["count"]

            if existing:

                continue

            db.executemany(

                """

                INSERT INTO honey_batch_events

                (honey_product_id, event_type, title, details, event_date, sort_order)

                VALUES (?, ?, ?, ?, ?, ?)

                """,

                [

                    (

                        product["id"],

                        "harvest",

                        "Harvest recorded",

                        "Floral source and harvest date were recorded by the producer.",

                        product["harvest_date"] or date.today().isoformat(),

                        1,

                    ),

                    (

                        product["id"],

                        "quality",

                        "Quality status recorded",

                        f"Batch status: {product['quality_status']}.",

                        product["harvest_date"] or date.today().isoformat(),

                        2,

                    ),

                    (

                        product["id"],

                        "listing",

                        "Available in BeeGuard marketplace",

                        f"Traceable batch ID: {product['batch_id']}.",

                        date.today().isoformat(),

                        3,

                    ),

                ],

            )



        if db.execute("SELECT COUNT(*) AS count FROM beekeepers").fetchone()["count"] == 0:

            db.executemany(

                "INSERT INTO beekeepers (name, apiary_name, location, hive_count) VALUES (?, ?, ?, ?)",

                [

                    ("Meera Nair", "Green Valley Apiary", "Mysuru, Karnataka", 14),

                    ("Arjun Kumar", "BeeFarm Karnataka", "Mandya, Karnataka", 10),

                ],

            )

        if db.execute("SELECT COUNT(*) AS count FROM hives").fetchone()["count"] == 0:

            beekeepers = db.execute("SELECT id FROM beekeepers ORDER BY id LIMIT 2").fetchall()

            if len(beekeepers) == 2:

                db.executemany(

                    """

                    INSERT INTO hives (beekeeper_id, hive_name, location, health_score, pollination_score)

                    VALUES (?, ?, ?, ?, ?)

                    """,

                    [

                        (beekeepers[0]["id"], "Sunrise Hive", "Mysuru", 94, 89),

                        (beekeepers[0]["id"], "Orchard Hive", "Mysuru", 91, 86),

                        (beekeepers[1]["id"], "Mustard Hive", "Mandya", 91, 86),

                    ],

                )

        if db.execute("SELECT COUNT(*) AS count FROM pesticide_alerts").fetchone()["count"] == 0:

            db.execute(

                """

                INSERT INTO pesticide_alerts

                (farm_name, distance_km, risk_level, spray_date, message)

                VALUES (?, ?, ?, ?, ?)

                """,

                (

                    "Green Valley Farm",

                    1.8,

                    "HIGH",

                    date.today().isoformat(),

                    "Pesticide spraying detected near bee colonies. Move hives away from the spray zone before treatment begins.",

                ),

            )




        # Demo hive occupancy and honey-to-hive relationships.
        hive_defaults = {
            "Sunrise Hive": ("occupied", 42000),
            "Orchard Hive": ("occupied", 38000),
            "Mustard Hive": ("available", 0),
        }
        for hive_name, (status, bee_count) in hive_defaults.items():
            db.execute(
                "UPDATE hives SET status = ?, bee_count = ? WHERE hive_name = ?",
                (status, bee_count, hive_name),
            )

        honey_hive_map = {
            "Green Valley Apiary": "Sunrise Hive",
            "BeeFarm Karnataka": "Orchard Hive",
            "Honey World": "Sunrise Hive",
            "Nature Bees": "Mustard Hive",
            "Pure Hive": "Orchard Hive",
        }
        for seller_name, hive_name in honey_hive_map.items():
            db.execute(
                """
                UPDATE honey_products
                SET hive_id = (SELECT id FROM hives WHERE hive_name = ?)
                WHERE seller_name = ? AND hive_id IS NULL
                """,
                (hive_name, seller_name),
            )

        seed_chatbot_faqs(db)



def seed_chatbot_faqs(db: sqlite3.Connection) -> None:
    if db.execute("SELECT COUNT(*) AS count FROM chatbot_faqs").fetchone()["count"] > 0:
        return

    faqs = [
        (
            "What is BeeGuard?",
            "beeguard,what,is",
            "BeeGuard is a bee and honey management platform that helps monitor hives, protect bees, track honey batches, and manage local honey availability."
        ),
        (
            "How can I verify honey?",
            "verify,honey,batch,verification",
            "Enter the honey batch ID in the Honey Verification section. BeeGuard checks the local SQLite database and displays the available batch information."
        ),
        (
            "How can I protect bees from pesticides?",
            "pesticide,protect,bees,spray",
            "Monitor pesticide alerts and avoid placing hives inside active spraying zones. Coordinate with nearby farmers before pesticide application."
        ),
        (
            "What is hive occupancy?",
            "hive,occupancy,occupied,available,maintenance",
            "Hive occupancy shows how many registered hives are occupied, available, or under maintenance."
        ),
        (
            "How do I find honey?",
            "find,search,honey,availability",
            "Use the Honey Availability search and enter a honey type such as Wildflower. BeeGuard returns matching batches, quantity, price, origin, quality, and linked hive information."
        ),
        (
            "What honey types are available?",
            "types,honey,wildflower,eucalyptus,mustard,sunflower",
            "BeeGuard can display honey types stored in its local database, including Wildflower, Eucalyptus, Mustard, and Sunflower honey when those batches are available."
        ),
        (
            "How does hive matching work?",
            "hive,matching,crop,pollination",
            "Hive matching considers crop, distance, and flower availability to calculate a suitability score."
        ),
        (
            "Does the chatbot need internet?",
            "internet,offline,chatbot,ai",
            "No. The BeeGuard assistant uses locally stored questions and answers in SQLite, so the chatbot works without an Internet connection."
        ),
        (
            "How many bees are in a hive?",
            "bees,bee,count,hive",
            "BeeGuard stores an estimated bee count for each demo hive. Open Hive Occupancy to see the current stored count."
        ),
    ]
    db.executemany(
        "INSERT INTO chatbot_faqs (question, keywords, answer) VALUES (?, ?, ?)",
        faqs,
    )





def row_as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:

    return dict(row) if row is not None else None





def public_farmer(row: sqlite3.Row) -> dict[str, Any]:

    data = dict(row)

    data["verified"] = bool(data.get("verified"))

    crops = data.pop("crops", "") or ""

    data["crops"] = [crop for crop in crops.split(" | ") if crop]

    return data





def public_honey(row: sqlite3.Row) -> dict[str, Any]:

    data = dict(row)

    data["farmer_verified"] = bool(data.get("farmer_verified"))

    data["is_active"] = bool(data.get("is_active", 1))

    return data





def clean_text(value: Any, label: str, maximum: int = 160, required: bool = True) -> str | None:

    if value is None or value == "":

        if required:

            raise ApiError(400, f"{label} is required.", "VALIDATION_ERROR")

        return None

    if not isinstance(value, str):

        raise ApiError(400, f"{label} must be text.", "VALIDATION_ERROR")

    value = value.strip()

    if not value or len(value) > maximum:

        raise ApiError(400, f"{label} must be between 1 and {maximum} characters.", "VALIDATION_ERROR")

    return value





def first_present(data: dict[str, Any], *keys: str) -> Any:

    for key in keys:

        if key in data:

            return data[key]

    return None





def numeric(

    value: Any,

    label: str,

    minimum: float = 0,

    maximum: float = 1_000_000,

    required: bool = True,

) -> float | None:

    if value is None or value == "":

        if required:

            raise ApiError(400, f"{label} is required.", "VALIDATION_ERROR")

        return None

    try:

        result = float(value)

    except (TypeError, ValueError) as error:

        raise ApiError(400, f"{label} must be a number.", "VALIDATION_ERROR") from error

    if result < minimum or result > maximum:

        raise ApiError(400, f"{label} must be between {minimum} and {maximum}.", "VALIDATION_ERROR")

    return result





def risk_score(level: str) -> int:

    return {"LOW": 25, "MEDIUM": 55, "HIGH": 82}.get(level, 0)





def create_match(crop: str, distance_km: float, flowers: int) -> dict[str, Any]:

    score = 100

    if distance_km > 5:

        score -= 35

    elif distance_km > 3:

        score -= 20

    elif distance_km > 2:

        score -= 10

    if flowers < 50:

        score -= 30

    elif flowers < 70:

        score -= 15

    if score >= 80:

        recommendation = "Excellent hive location for pollination."

    elif score >= 60:

        recommendation = "Good location, but monitor flower availability."

    else:

        recommendation = "High risk location. Consider another hive location."

    return {

        "crop": crop,

        "distance_km": distance_km,

        "flower_availability": flowers,

        "score": max(score, 0),

        "recommendation": recommendation,

    }





def parse_bool(value: str | None) -> bool | None:

    if value is None or value == "":

        return None

    lowered = value.lower()

    if lowered in {"true", "1", "yes"}:

        return True

    if lowered in {"false", "0", "no"}:

        return False

    raise ApiError(400, "Boolean filters must be true or false.", "VALIDATION_ERROR")





def query_one(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:

    return query.get(key, [default])[0]





def farmer_rows(db: sqlite3.Connection, query: dict[str, list[str]]) -> list[dict[str, Any]]:

    conditions: list[str] = []

    values: list[Any] = []

    text_query = query_one(query, "q")

    district = query_one(query, "district")

    crop = query_one(query, "crop")

    verified = parse_bool(query_one(query, "verified"))



    if text_query:

        phrase = f"%{text_query.strip()}%"

        conditions.append("(f.name LIKE ? COLLATE NOCASE OR f.farm_name LIKE ? COLLATE NOCASE OR f.specialty LIKE ? COLLATE NOCASE)")

        values.extend([phrase, phrase, phrase])

    if district:

        conditions.append("f.district = ? COLLATE NOCASE")

        values.append(district.strip())

    if crop:

        conditions.append("EXISTS (SELECT 1 FROM farmer_crops filter_crop WHERE filter_crop.farmer_id = f.id AND filter_crop.crop = ? COLLATE NOCASE)")

        values.append(crop.strip())

    if verified is not None:

        conditions.append("f.verified = ?")

        values.append(1 if verified else 0)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = db.execute(

        f"""

        SELECT f.*,

               COALESCE(GROUP_CONCAT(DISTINCT fc.crop), '') AS crops,

               COUNT(DISTINCT CASE WHEN COALESCE(h.is_active, 1) = 1 THEN h.id END) AS active_honey_count

        FROM farmers f

        LEFT JOIN farmer_crops fc ON fc.farmer_id = f.id

        LEFT JOIN honey_products h ON h.farmer_id = f.id

        {where}

        GROUP BY f.id

        ORDER BY f.verified DESC, active_honey_count DESC, f.name COLLATE NOCASE ASC

        """,

        values,

    ).fetchall()

    return [public_farmer(row) for row in rows]





def honey_rows(db: sqlite3.Connection, query: dict[str, list[str]]) -> list[dict[str, Any]]:

    conditions = ["COALESCE(h.is_active, 1) = 1"]

    values: list[Any] = []

    honey_type = query_one(query, "type")

    district = query_one(query, "district")

    search = query_one(query, "q")

    max_price = query_one(query, "maxPrice") or query_one(query, "max_price")

    min_price = query_one(query, "minPrice") or query_one(query, "min_price")

    verified = parse_bool(query_one(query, "verified"))

    in_stock = parse_bool(query_one(query, "inStock") or query_one(query, "in_stock"))



    if honey_type:

        conditions.append("h.honey_type = ? COLLATE NOCASE")

        values.append(honey_type.strip())

    if district:

        conditions.append("f.district = ? COLLATE NOCASE")

        values.append(district.strip())

    if search:

        phrase = f"%{search.strip()}%"

        conditions.append("(h.batch_id LIKE ? COLLATE NOCASE OR h.honey_type LIKE ? COLLATE NOCASE OR h.seller_name LIKE ? COLLATE NOCASE OR f.name LIKE ? COLLATE NOCASE)")

        values.extend([phrase, phrase, phrase, phrase])

    if max_price is not None:

        values.append(numeric(max_price, "Maximum price"))

        conditions.append("h.price_per_kg <= ?")

    if min_price is not None:

        values.append(numeric(min_price, "Minimum price"))

        conditions.append("h.price_per_kg >= ?")

    if verified is not None:

        conditions.append("h.quality_status = ?" if verified else "h.quality_status <> ?")

        values.append("Verified")

    if in_stock is True:

        conditions.append("h.quantity_kg > 0")



    sort_mapping = {

        "price_asc": "h.price_per_kg ASC, h.id ASC",

        "price_desc": "h.price_per_kg DESC, h.id ASC",

        "newest": "h.created_at DESC, h.id DESC",

    }

    sort = sort_mapping.get(query_one(query, "sort", "price_asc") or "price_asc")

    if not sort:

        raise ApiError(400, "Sort must be price_asc, price_desc, or newest.", "VALIDATION_ERROR")



    rows = db.execute(

        f"""

        SELECT h.*,

               f.id AS farmer_profile_id, f.name AS farmer_name, f.farm_name AS farmer_farm_name,

               f.district AS farmer_district, f.state AS farmer_state, f.verified AS farmer_verified,

               hi.hive_name, hi.location AS hive_location, hi.status AS hive_status, hi.bee_count

        FROM honey_products h

        LEFT JOIN farmers f ON f.id = h.farmer_id

        LEFT JOIN hives hi ON hi.id = h.hive_id

        WHERE {' AND '.join(conditions)}

        ORDER BY {sort}

        """,

        values,

    ).fetchall()

    return [public_honey(row) for row in rows]





def farmer_detail(db: sqlite3.Connection, farmer_id: int) -> dict[str, Any]:

    farmer = db.execute(

        """

        SELECT f.*, COALESCE(GROUP_CONCAT(DISTINCT fc.crop), '') AS crops, 0 AS active_honey_count

        FROM farmers f

        LEFT JOIN farmer_crops fc ON fc.farmer_id = f.id

        WHERE f.id = ?

        GROUP BY f.id

        """,

        (farmer_id,),

    ).fetchone()

    if not farmer:

        raise ApiError(404, "Farmer not found.", "FARMER_NOT_FOUND")

    crops = [dict(row) for row in db.execute(

        "SELECT crop, area_acres, flowering_season FROM farmer_crops WHERE farmer_id = ? ORDER BY crop",

        (farmer_id,),

    )]

    batches = [public_honey(row) for row in db.execute(

        """

        SELECT h.*, f.id AS farmer_profile_id, f.name AS farmer_name, f.farm_name AS farmer_farm_name,

               f.district AS farmer_district, f.state AS farmer_state, f.verified AS farmer_verified

        FROM honey_products h

        JOIN farmers f ON f.id = h.farmer_id

        WHERE h.farmer_id = ? AND COALESCE(h.is_active, 1) = 1

        ORDER BY h.price_per_kg

        """,

        (farmer_id,),

    )]

    profile = public_farmer(farmer)

    profile["phone"] = profile.get("phone") or "Contact through BeeGuard"

    profile["email"] = profile.get("email") or "Contact through BeeGuard"

    return {"farmer": profile, "crops": crops, "batches": batches}





def batch_detail(db: sqlite3.Connection, batch_id: str) -> dict[str, Any]:

    row = db.execute(

        """

        SELECT h.*,

               f.id AS farmer_profile_id, f.name AS farmer_name, f.farm_name AS farmer_farm_name,

               f.location AS farmer_location, f.district AS farmer_district, f.state AS farmer_state,

               f.phone AS farmer_phone, f.email AS farmer_email, f.verified AS farmer_verified,

               f.specialty AS farmer_specialty, f.experience_years AS farmer_experience_years,

               hi.hive_name, hi.location AS hive_location, hi.status AS hive_status, hi.bee_count

        FROM honey_products h

        LEFT JOIN farmers f ON f.id = h.farmer_id

        LEFT JOIN hives hi ON hi.id = h.hive_id

        WHERE h.batch_id = ? COLLATE NOCASE

        """,

        (batch_id.upper(),),

    ).fetchone()

    if not row:

        raise ApiError(404, "Batch not found.", "BATCH_NOT_FOUND")

    product = public_honey(row)

    farmer_id = product.get("farmer_id")

    crops: list[dict[str, Any]] = []

    if farmer_id:

        crops = [dict(crop) for crop in db.execute(

            "SELECT crop, area_acres, flowering_season FROM farmer_crops WHERE farmer_id = ? ORDER BY crop",

            (farmer_id,),

        )]

    events = [dict(event) for event in db.execute(

        """

        SELECT event_type, title, details, event_date

        FROM honey_batch_events

        WHERE honey_product_id = ?

        ORDER BY sort_order, id

        """,

        (product["id"],),

    )]

    farmer = {

        "id": product.get("farmer_profile_id"),

        "name": product.get("farmer_name") or product["seller_name"],

        "farm_name": product.get("farmer_farm_name") or product["seller_name"],

        "location": product.get("farmer_location") or product["origin"],

        "district": product.get("farmer_district"),

        "state": product.get("farmer_state"),

        "phone": product.get("farmer_phone") or "Contact through BeeGuard",

        "email": product.get("farmer_email") or "Contact through BeeGuard",

        "verified": product.get("farmer_verified", False),

        "specialty": product.get("farmer_specialty"),

        "experience_years": product.get("farmer_experience_years"),

    }

    return {"batch": product, "farmer": farmer, "crops": crops, "events": events}





def create_farmer(db: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:

    name = clean_text(first_present(body, "name"), "Name")

    farm_name = clean_text(first_present(body, "farmName", "farm_name"), "Farm name")

    location = clean_text(first_present(body, "location"), "Location")

    district = clean_text(first_present(body, "district"), "District")

    state = clean_text(first_present(body, "state"), "State")

    crop = clean_text(first_present(body, "primaryCrop", "crop"), "Primary crop")

    phone = clean_text(first_present(body, "phone"), "Phone", 40, required=False)

    email = clean_text(first_present(body, "email"), "Email", 120, required=False)

    bio = clean_text(first_present(body, "bio", "about"), "About", 500, required=False)

    specialty = clean_text(first_present(body, "specialty"), "Specialty", 120, required=False)

    experience = numeric(first_present(body, "experienceYears", "experience_years"), "Experience years", 0, 100, required=False)

    crops_input = body.get("crops", [crop])

    if not isinstance(crops_input, list):

        raise ApiError(400, "Crops must be a list.", "VALIDATION_ERROR")



    existing = db.execute("SELECT id FROM farmers WHERE farm_name = ? COLLATE NOCASE", (farm_name,)).fetchone()

    if existing:

        raise ApiError(409, "A farmer with that farm name already exists.", "DUPLICATE_FARM")

    cursor = db.execute(

        """

        INSERT INTO farmers

        (name, farm_name, location, crop, district, state, phone, email, bio, specialty, experience_years, verified)

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)

        """,

        (name, farm_name, location, crop, district, state, phone, email, bio, specialty, int(experience or 0)),

    )

    farmer_id = int(cursor.lastrowid)

    for item in crops_input[:8]:

        if isinstance(item, dict):

            crop_name = clean_text(item.get("name"), "Crop")

            acres = numeric(item.get("areaAcres", item.get("area_acres")), "Crop area", 0, 100_000, required=False)

            season = clean_text(item.get("floweringSeason", item.get("flowering_season")), "Flowering season", 80, required=False)

        else:

            crop_name = clean_text(item, "Crop")

            acres, season = None, None

        db.execute(

            "INSERT OR IGNORE INTO farmer_crops (farmer_id, crop, area_acres, flowering_season) VALUES (?, ?, ?, ?)",

            (farmer_id, crop_name, acres, season),

        )

    return farmer_detail(db, farmer_id)





def create_honey_batch(db: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:

    farmer_id = int(numeric(first_present(body, "farmerId", "farmer_id"), "Farmer ID", 1, 1_000_000))

    farmer = db.execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()

    if not farmer:

        raise ApiError(404, "Selected farmer was not found.", "FARMER_NOT_FOUND")

    batch_id = clean_text(first_present(body, "batchId", "batch_id", "batchCode"), "Batch ID", 60).upper()

    if not re.fullmatch(r"[A-Z0-9-]{4,60}", batch_id):

        raise ApiError(400, "Batch ID may contain only letters, numbers, and hyphens.", "VALIDATION_ERROR")

    honey_type = clean_text(first_present(body, "honeyType", "honey_type"), "Honey type", 50)

    price = numeric(first_present(body, "pricePerKg", "price_per_kg"), "Price per kg", 0, 1_000_000)

    quantity = numeric(first_present(body, "quantityKg", "quantity_kg"), "Quantity", 0, 1_000_000)

    harvest = clean_text(first_present(body, "harvestDate", "harvest_date"), "Harvest date", 20, required=False) or date.today().isoformat()

    floral = clean_text(first_present(body, "floralSource", "floral_source"), "Floral source", 120, required=False)

    quality = clean_text(first_present(body, "qualityStatus", "quality_status"), "Quality status", 40, required=False) or "Pending"
    hive_value = first_present(body, "hiveId", "hive_id")
    hive_id = int(numeric(hive_value, "Hive ID", 1, 1_000_000, required=False)) if hive_value not in (None, "") else None
    if hive_id is not None and not db.execute("SELECT id FROM hives WHERE id = ?", (hive_id,)).fetchone():
        raise ApiError(404, "Selected hive was not found.", "HIVE_NOT_FOUND")

    if quality not in {"Pending", "Verified"}:

        raise ApiError(400, "Quality status must be Pending or Verified.", "VALIDATION_ERROR")

    try:

        cursor = db.execute(

            """

            INSERT INTO honey_products

            (seller_name, honey_type, price_per_kg, quantity_kg, origin, batch_id, quality_status,

             farmer_id, harvest_date, floral_source, is_active, hive_id)

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)

            """,

            (

                farmer["farm_name"],

                honey_type,

                price,

                quantity,

                farmer["location"],

                batch_id,

                quality,

                farmer_id,

                harvest,

                floral,

                hive_id,

                hive_id,

            ),

        )

    except sqlite3.IntegrityError as error:

        raise ApiError(409, "That batch ID already exists.", "DUPLICATE_BATCH") from error

    honey_id = int(cursor.lastrowid)

    db.executemany(

        """

        INSERT INTO honey_batch_events

        (honey_product_id, event_type, title, details, event_date, sort_order)

        VALUES (?, ?, ?, ?, ?, ?)

        """,

        [

            (honey_id, "harvest", "Harvest recorded", floral or "Harvest recorded by the producer.", harvest, 1),

            (honey_id, "listing", "Honey listing created", f"{quantity:g} kg listed at ₹{price:g}/kg.", date.today().isoformat(), 3),

        ],

    )

    return batch_detail(db, batch_id)





class BeeGuardHandler(BaseHTTPRequestHandler):

    server_version = "BeeGuardPython/1.0"



    def log_message(self, format: str, *args: object) -> None:

        # Keep normal requests quiet; unexpected errors are returned as JSON.

        return



    def json_response(self, status: int, payload: Any) -> None:

        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

        self.send_response(status)

        self.send_header("Content-Type", "application/json; charset=utf-8")

        self.send_header("Content-Length", str(len(data)))

        self.send_header("Cache-Control", "no-store")

        self.send_header("Access-Control-Allow-Origin", "*")

        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        self.send_header("Access-Control-Allow-Headers", "Content-Type")

        self.end_headers()

        self.wfile.write(data)



    def error_response(self, error: ApiError | Exception) -> None:

        if isinstance(error, ApiError):

            self.json_response(error.status, {"error": {"code": error.code, "message": error.message}})

        else:

            print(f"BeeGuard internal error: {error}")

            self.json_response(500, {"error": {"code": "INTERNAL_ERROR", "message": "Unexpected server error."}})



    def read_json(self) -> dict[str, Any]:

        try:

            content_length = int(self.headers.get("Content-Length", "0"))

        except ValueError as error:

            raise ApiError(400, "Invalid Content-Length.", "INVALID_JSON") from error

        if content_length > MAX_BODY_BYTES:

            raise ApiError(413, "Request body is too large.", "PAYLOAD_TOO_LARGE")

        raw = self.rfile.read(content_length)

        if not raw:

            return {}

        try:

            data = json.loads(raw.decode("utf-8"))

        except (UnicodeDecodeError, json.JSONDecodeError) as error:

            raise ApiError(400, "Request body must be valid JSON.", "INVALID_JSON") from error

        if not isinstance(data, dict):

            raise ApiError(400, "JSON body must be an object.", "INVALID_JSON")

        return data



    def do_OPTIONS(self) -> None:

        self.send_response(204)

        self.send_header("Access-Control-Allow-Origin", "*")

        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        self.send_header("Access-Control-Allow-Headers", "Content-Type")

        self.end_headers()



    def do_GET(self) -> None:

        self.dispatch("GET")



    def do_POST(self) -> None:

        self.dispatch("POST")



    def dispatch(self, method: str) -> None:

        parsed = urlparse(self.path)

        path = parsed.path

        query = parse_qs(parsed.query)

        try:

            if not path.startswith("/api/"):

                self.serve_static(path)

                return

            with connection() as db:

                if method == "GET" and path == "/api/health":

                    self.json_response(200, {"status": "ok", "service": "BeeGuard Python API", "database": "SQLite"})

                    return

                if method == "GET" and path == "/api/dashboard":

                    self.json_response(200, self.dashboard(db))

                    return

                if method == "GET" and path == "/api/meta/districts":

                    districts = [row["district"] for row in db.execute(

                        "SELECT DISTINCT district FROM farmers WHERE district IS NOT NULL AND district <> '' ORDER BY district"

                    )]

                    self.json_response(200, {"items": districts})

                    return

                if method == "GET" and path == "/api/meta/crops":

                    crops = [row["crop"] for row in db.execute(

                        "SELECT DISTINCT crop FROM farmer_crops UNION SELECT DISTINCT crop FROM farmers ORDER BY crop"

                    )]

                    self.json_response(200, {"items": crops})

                    return

                if method == "GET" and path == "/api/farmers":

                    self.json_response(200, {"items": farmer_rows(db, query), "total": len(farmer_rows(db, query))})

                    return

                if method == "POST" and path == "/api/farmers":

                    created = create_farmer(db, self.read_json())

                    db.commit()

                    self.json_response(201, created)

                    return

                farmer_match = re.fullmatch(r"/api/farmers/(\d+)", path)

                if method == "GET" and farmer_match:

                    self.json_response(200, farmer_detail(db, int(farmer_match.group(1))))

                    return

                if method == "GET" and path == "/api/honey":

                    self.json_response(200, honey_rows(db, query))

                    return

                if method == "GET" and path == "/api/honey/availability":
                    products = honey_rows(db, query)
                    available_quantity = round(sum(float(item.get("quantity_kg") or 0) for item in products), 2)
                    self.json_response(200, {"honeyType": query_one(query, "type", "All") or "All", "availableQuantity": available_quantity, "count": len(products), "results": products})
                    return

                if method == "GET" and path == "/api/hives/occupancy":
                    totals = db.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'occupied' THEN 1 ELSE 0 END) AS occupied, SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END) AS available, SUM(CASE WHEN status = 'maintenance' THEN 1 ELSE 0 END) AS maintenance, COALESCE(SUM(bee_count), 0) AS total_bees FROM hives").fetchone()
                    total = int(totals["total"] or 0)
                    occupied = int(totals["occupied"] or 0)
                    hives = [dict(row) for row in db.execute("SELECT h.id, h.hive_name, h.location, h.status, h.bee_count, h.health_score, h.pollination_score, b.name AS beekeeper_name, b.apiary_name FROM hives h JOIN beekeepers b ON b.id = h.beekeeper_id ORDER BY h.id").fetchall()]
                    self.json_response(200, {"total": total, "occupied": occupied, "available": int(totals["available"] or 0), "maintenance": int(totals["maintenance"] or 0), "totalBees": int(totals["total_bees"] or 0), "occupancyPercent": round((occupied / total) * 100, 1) if total else 0, "hives": hives})
                    return

                if method == "GET" and path == "/api/chatbot/faqs":
                    faqs = [dict(row) for row in db.execute("SELECT id, question FROM chatbot_faqs ORDER BY id").fetchall()]
                    self.json_response(200, {"offline": True, "items": faqs})
                    return

                if method == "POST" and path == "/api/chatbot":
                    body = self.read_json()
                    question = (clean_text(body.get("question"), "Question", 300) or "").lower()
                    faq_rows = db.execute("SELECT question, keywords, answer FROM chatbot_faqs").fetchall()
                    best_answer = None
                    best_question = None
                    best_score = 0
                    question_words = set(re.findall(r"[a-z0-9]+", question))
                    for faq in faq_rows:
                        keywords = [k.strip().lower() for k in faq["keywords"].split(",") if k.strip()]
                        score = sum(1 for keyword in keywords if keyword in question or keyword in question_words)
                        if score > best_score:
                            best_score = score
                            best_answer = faq["answer"]
                            best_question = faq["question"]
                    if not best_answer:
                        best_answer = "I can answer predefined BeeGuard questions about honey availability, hive occupancy, honey verification, pesticides, hive matching, and offline use."
                    self.json_response(200, {"question": question, "answer": best_answer, "matchedQuestion": best_question, "offline": True})
                    return

                if method == "GET" and path == "/api/honey/compare":

                    self.json_response(200, honey_rows(db, {"type": [query_one(query, "type", "Wildflower") or "Wildflower"]}))

                    return

                if method == "GET" and path == "/api/buyer/search":

                    products = honey_rows(db, query)

                    self.json_response(

                        200,

                        {

                            "honeyType": query_one(query, "type", "Wildflower") or "Wildflower",

                            "maximumPrice": numeric(query_one(query, "maxPrice"), "Maximum price", required=False) or 999999,

                            "results": products,

                        },

                    )

                    return

                batch_match = re.fullmatch(r"/api/honey/batch/([^/]+)", path)

                detailed_batch_match = re.fullmatch(r"/api/honey/batches/([^/]+)", path)

                if method == "GET" and batch_match:

                    detail = batch_detail(db, unquote(batch_match.group(1)))

                    self.json_response(200, detail["batch"])

                    return

                if method == "GET" and detailed_batch_match:

                    self.json_response(200, batch_detail(db, unquote(detailed_batch_match.group(1))))

                    return

                if method == "POST" and path in {"/api/honey", "/api/honey/batches"}:

                    created = create_honey_batch(db, self.read_json())

                    db.commit()

                    self.json_response(201, created)

                    return

                if method == "GET" and path == "/api/alerts":

                    status = query_one(query, "status")

                    if status and status not in {"active", "protected"}:

                        raise ApiError(400, "Status must be active or protected.", "VALIDATION_ERROR")

                    if status:

                        alerts = db.execute(

                            "SELECT * FROM pesticide_alerts WHERE status = ? ORDER BY id DESC", (status,)

                        ).fetchall()

                    else:

                        alerts = db.execute(

                            "SELECT * FROM pesticide_alerts ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC"

                        ).fetchall()

                    self.json_response(200, [dict(alert) for alert in alerts])

                    return

                if method == "POST" and path == "/api/alerts":

                    alert = self.create_alert(db, self.read_json())

                    db.commit()

                    self.json_response(201, {"success": True, "alert": alert})

                    return

                protect_match = re.fullmatch(r"/api/alerts/(\d+)/protect", path)

                if method == "POST" and protect_match:

                    alert_id = int(protect_match.group(1))

                    if not db.execute("SELECT id FROM pesticide_alerts WHERE id = ?", (alert_id,)).fetchone():

                        raise ApiError(404, "Pesticide alert not found.", "ALERT_NOT_FOUND")

                    db.execute(

                        "UPDATE pesticide_alerts SET status = 'protected', protected_at = CURRENT_TIMESTAMP WHERE id = ?",

                        (alert_id,),

                    )

                    updated = db.execute("SELECT * FROM pesticide_alerts WHERE id = ?", (alert_id,)).fetchone()

                    db.commit()

                    self.json_response(

                        200,

                        {"success": True, "message": "Hive protection was recorded for this pesticide alert.", "alert": dict(updated)},

                    )

                    return

                if method == "GET" and path == "/api/matches":

                    matches = db.execute("SELECT * FROM hive_matches ORDER BY id DESC LIMIT 20").fetchall()

                    self.json_response(200, [dict(match) for match in matches])

                    return

                if method == "POST" and path == "/api/matches":

                    body = self.read_json()

                    match = create_match(

                        clean_text(body.get("crop"), "Crop", 50) or "",

                        numeric(first_present(body, "distanceKm", "distance_km"), "Distance", 0, 1000) or 0,

                        int(numeric(first_present(body, "flowerAvailability", "flower_availability"), "Flower availability", 0, 100) or 0),

                    )

                    cursor = db.execute(

                        """

                        INSERT INTO hive_matches (crop, distance_km, flower_availability, score, recommendation)

                        VALUES (?, ?, ?, ?, ?)

                        """,

                        (

                            match["crop"],

                            match["distance_km"],

                            match["flower_availability"],

                            match["score"],

                            match["recommendation"],

                        ),

                    )

                    stored = db.execute("SELECT * FROM hive_matches WHERE id = ?", (cursor.lastrowid,)).fetchone()

                    db.commit()

                    self.json_response(201, {"match": dict(stored)})

                    return

                raise ApiError(404, "API route not found.", "NOT_FOUND")

        except ApiError as error:

            self.error_response(error)

        except sqlite3.Error as error:

            self.error_response(ApiError(500, f"Database error: {error}", "DATABASE_ERROR"))

        except Exception as error:

            self.error_response(error)



    def dashboard(self, db: sqlite3.Connection) -> dict[str, Any]:

        averages = db.execute(

            "SELECT ROUND(AVG(health_score)) AS bee_health, ROUND(AVG(pollination_score)) AS pollination FROM hives"

        ).fetchone()

        active_alert = db.execute(

            "SELECT * FROM pesticide_alerts WHERE status = 'active' ORDER BY id DESC LIMIT 1"

        ).fetchone()

        count = lambda table: db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]

        verified = db.execute(

            "SELECT COUNT(*) AS count FROM honey_products WHERE quality_status = 'Verified' AND COALESCE(is_active, 1) = 1"

        ).fetchone()["count"]

        return {

            "beeHealth": averages["bee_health"] or 0,

            "pollination": averages["pollination"] or 0,

            "pesticideRisk": {

                "level": active_alert["risk_level"] if active_alert else "LOW",

                "score": risk_score(active_alert["risk_level"]) if active_alert else 0,

            },

            "honeyBatches": verified,

            "honeyProducts": count("honey_products"),

            "pesticideAlerts": db.execute(

                "SELECT COUNT(*) AS count FROM pesticide_alerts WHERE status = 'active'"

            ).fetchone()["count"],

            "farmers": count("farmers"),

            "beekeepers": count("beekeepers"),

            "latestAlert": row_as_dict(active_alert),

        }



    def create_alert(self, db: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:

        risk_level = (clean_text(first_present(body, "riskLevel", "risk_level"), "Risk level", 10) or "").upper()

        if risk_level not in {"LOW", "MEDIUM", "HIGH"}:

            raise ApiError(400, "Risk level must be LOW, MEDIUM, or HIGH.", "VALIDATION_ERROR")

        cursor = db.execute(

            """

            INSERT INTO pesticide_alerts (farm_name, distance_km, risk_level, spray_date, message)

            VALUES (?, ?, ?, ?, ?)

            """,

            (

                clean_text(first_present(body, "farmName", "farm_name"), "Farm name"),

                numeric(first_present(body, "distanceKm", "distance_km"), "Distance", 0, 1000),

                risk_level,

                clean_text(first_present(body, "sprayDate", "spray_date"), "Spray date", 20),

                clean_text(body.get("message"), "Message", 500),

            ),

        )

        return dict(db.execute("SELECT * FROM pesticide_alerts WHERE id = ?", (cursor.lastrowid,)).fetchone())



    def serve_static(self, path: str) -> None:

        static = {

            "/": ("index.html", "text/html; charset=utf-8"),

            "/index.html": ("index.html", "text/html; charset=utf-8"),

            "/style.css": ("style.css", "text/css; charset=utf-8"),

            "/app.js": ("app.js", "application/javascript; charset=utf-8"),

        }

        asset = static.get(path)

        if not asset:

            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

            return

        try:

            data = (PUBLIC / asset[0]).read_bytes()

        except OSError:

            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to read application files")

            return

        self.send_response(HTTPStatus.OK)

        self.send_header("Content-Type", asset[1])

        self.send_header("Content-Length", str(len(data)))

        self.send_header("Cache-Control", "no-cache")

        self.end_headers()

        self.wfile.write(data)





if __name__ == "__main__":

    initialize_database()

    print(f"🐝 BeeGuard Python backend is running at http://{HOST}:{PORT}")

    ThreadingHTTPServer((HOST, PORT), BeeGuardHandler).serve_forever()
