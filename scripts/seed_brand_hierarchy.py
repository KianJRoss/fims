from __future__ import annotations

import psycopg


DB_URL = "postgresql://fims:fims@localhost:5432/fims"


BRANDS = [
    *[
        {"name": name, "tier": "tier1", "brand_type": "manufacturer_brand"}
        for name in [
            "Black Cat",
            "Brothers",
            "Winda",
            "Happy Family",
            "Panda",
            "Red Lantern",
            "Miracle",
            "Sunwing",
            "Sky Pioneer",
            "Golden Lion",
            "Horse Brand",
            "Dragon",
        ]
    ],
    *[
        {"name": name, "tier": "tier1", "brand_type": "independent"}
        for name in [
            "TNT",
            "Phantom",
            "Raccoon",
            "Shogun",
            "Fox",
            "Legend",
            "Warrior",
            "Magnum",
            "Pyro King",
            "Freedom Fireworks",
            "Fire Factory",
            "Black Scorpion",
            "Maximum Load",
            "Major League Pyro",
            "Big Shotter",
            "Pyro Diablo",
            "Fire Event",
        ]
    ],
    *[
        {"name": name, "tier": "tier1", "brand_type": "house_brand"}
        for name in [
            "Dominator",
            "World Class",
            "Firehawk",
            "Sky Bacon",
            "Pyro Demon",
            "Cutting Edge",
            "Boomer",
            "Big Fireworks",
            "Neon",
            "Great Grizzly",
            "Mad Ox",
        ]
    ],
    *[
        {"name": name, "tier": "sub", "brand_type": "house_brand"}
        for name in [
            "Brothers Platinum",
            "Brothers Black Label",
            "Raccoon Elite",
            "Black Cat Platinum",
            "Black Cat Legends",
            "Phantom Legends",
            "Phantom Excalibur",
            "Phantom HD",
            "TNT Supreme",
            "TNT Select",
        ]
    ],
]


IMPORTERS = [
    {"name": "Jakes Fireworks", "short_name": "Jakes", "hq_state": "KS"},
    {"name": "R&M Enterprises", "short_name": "R&M", "hq_state": None},
    {"name": "Winco Fireworks", "short_name": "Winco", "hq_state": None},
    {"name": "Phantom Fireworks", "short_name": "Phantom", "hq_state": "OH"},
    {"name": "Raccoon Fireworks", "short_name": "Raccoon", "hq_state": None},
    {"name": "Spirit of 76", "short_name": "Spirit of 76", "hq_state": None},
    {"name": "Victory Fireworks", "short_name": "Victory", "hq_state": None},
    {"name": "American Wholesale Fireworks", "short_name": "AWF", "hq_state": None},
    {"name": "Pyro Direct", "short_name": "Pyro Direct", "hq_state": None},
    {"name": "Red Rhino Fireworks", "short_name": "Red Rhino", "hq_state": None},
    {"name": "Fireworks Over America", "short_name": "FOA", "hq_state": None},
    {"name": "North Central Industries", "short_name": "NCI", "hq_state": None},
    {"name": "Fireworks International", "short_name": "FI", "hq_state": None},
]


MANUFACTURERS = [
    "Brothers Pyrotechnics",
    "Winda Fireworks",
    "Happy Family Fireworks",
    "Panda Fireworks",
    "Red Lantern Fireworks",
    "Miracle Fireworks",
    "Sunwing Fireworks",
    "Sky Pioneer Fireworks",
    "Golden Lion Fireworks",
    "Horse Brand Fireworks",
    "Dragon Fireworks",
]


BRAND_IMPORTERS = [
    ("Jakes Fireworks", "Dominator", "carries"),
    ("Jakes Fireworks", "World Class", "carries"),
    ("Jakes Fireworks", "Firehawk", "carries"),
    ("Jakes Fireworks", "Boomer", "carries"),
    ("Jakes Fireworks", "Cutting Edge", "carries"),
    ("Jakes Fireworks", "Sky Bacon", "carries"),
    ("Jakes Fireworks", "Pyro Demon", "carries"),
    ("Jakes Fireworks", "Big Fireworks", "carries"),
    ("Jakes Fireworks", "Neon", "carries"),
    ("Jakes Fireworks", "Great Grizzly", "carries"),
    ("Jakes Fireworks", "Mad Ox", "carries"),
    ("Jakes Fireworks", "Happy Family", "carries"),
    ("R&M Enterprises", "Winda", "carries"),
    ("R&M Enterprises", "Brothers", "carries"),
    ("R&M Enterprises", "Miracle", "carries"),
    ("R&M Enterprises", "Red Lantern", "carries"),
    ("R&M Enterprises", "Sunwing", "carries"),
    ("R&M Enterprises", "Golden Lion", "carries"),
    ("R&M Enterprises", "Panda", "carries"),
    ("R&M Enterprises", "Happy Family", "carries"),
    ("R&M Enterprises", "Sky Pioneer", "carries"),
    ("Winco Fireworks", "Black Cat", "exclusive"),
    ("Winco Fireworks", "Black Cat Platinum", "exclusive"),
    ("Winco Fireworks", "Black Cat Legends", "exclusive"),
    ("Winco Fireworks", "TNT", "exclusive"),
    ("Winco Fireworks", "TNT Supreme", "exclusive"),
    ("Winco Fireworks", "TNT Select", "exclusive"),
    ("Winco Fireworks", "Winda", "carries"),
    ("Phantom Fireworks", "Phantom", "owns"),
    ("Phantom Fireworks", "Phantom Legends", "owns"),
    ("Phantom Fireworks", "Phantom Excalibur", "owns"),
    ("Phantom Fireworks", "Phantom HD", "owns"),
    ("Raccoon Fireworks", "Raccoon", "owns"),
    ("Raccoon Fireworks", "Raccoon Elite", "owns"),
    ("Spirit of 76", "Raccoon", "carries"),
    ("Spirit of 76", "Brothers", "carries"),
    ("Spirit of 76", "Winda", "carries"),
    ("Spirit of 76", "Cutting Edge", "carries"),
    ("Victory Fireworks", "Brothers", "carries"),
    ("Victory Fireworks", "Winda", "carries"),
]


BRAND_MANUFACTURERS = [
    ("Brothers", "Brothers Pyrotechnics"),
    ("Brothers Platinum", "Brothers Pyrotechnics"),
    ("Brothers Black Label", "Brothers Pyrotechnics"),
    ("Winda", "Winda Fireworks"),
    ("Happy Family", "Happy Family Fireworks"),
    ("Panda", "Panda Fireworks"),
    ("Red Lantern", "Red Lantern Fireworks"),
    ("Miracle", "Miracle Fireworks"),
    ("Sunwing", "Sunwing Fireworks"),
    ("Sky Pioneer", "Sky Pioneer Fireworks"),
    ("Golden Lion", "Golden Lion Fireworks"),
    ("Horse Brand", "Horse Brand Fireworks"),
    ("Dragon", "Dragon Fireworks"),
    ("Black Cat", "Brothers Pyrotechnics"),
    ("Black Cat Platinum", "Brothers Pyrotechnics"),
    ("Black Cat Legends", "Brothers Pyrotechnics"),
]


def ensure_brand(cur, brand: dict[str, str | None]) -> None:
    cur.execute(
        """
        INSERT INTO product_brands (name, tier, brand_type, website, notes, logo_url)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (name) DO NOTHING;
        """,
        (
            brand["name"],
            brand["tier"],
            brand["brand_type"],
            brand.get("website"),
            brand.get("notes"),
            brand.get("logo_url"),
        ),
    )


def ensure_importer(cur, importer: dict[str, str | None]) -> None:
    cur.execute(
        """
        INSERT INTO importers (name, short_name, website, hq_state, notes)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (name) DO NOTHING;
        """,
        (
            importer["name"],
            importer["short_name"],
            importer.get("website"),
            importer["hq_state"],
            importer.get("notes"),
        ),
    )


def ensure_manufacturer(cur, manufacturer: str) -> None:
    cur.execute(
        """
        INSERT INTO manufacturers (name, country, website, notes)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (name) DO NOTHING;
        """,
        (manufacturer, "China", None, None),
    )


def fetch_id(cur, table: str, name: str) -> int:
    cur.execute(f"SELECT id FROM {table} WHERE name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Missing row in {table}: {name}")
    return int(row[0])


def ensure_brand_importer(cur, brand_id: int, importer_id: int, relationship_type: str) -> None:
    cur.execute(
        """
        INSERT INTO brand_importers (brand_id, importer_id, relationship_type)
        VALUES (%s, %s, %s)
        ON CONFLICT (brand_id, importer_id) DO NOTHING;
        """,
        (brand_id, importer_id, relationship_type),
    )


def ensure_brand_manufacturer(cur, brand_id: int, manufacturer_id: int) -> None:
    cur.execute(
        """
        INSERT INTO brand_manufacturers (brand_id, manufacturer_id)
        VALUES (%s, %s)
        ON CONFLICT (brand_id, manufacturer_id) DO NOTHING;
        """,
        (brand_id, manufacturer_id),
    )


def main() -> None:
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            for brand in BRANDS:
                ensure_brand(cur, brand)
            for importer in IMPORTERS:
                ensure_importer(cur, importer)
            for manufacturer in MANUFACTURERS:
                ensure_manufacturer(cur, manufacturer)

            brand_ids = {brand["name"]: fetch_id(cur, "product_brands", brand["name"]) for brand in BRANDS}
            importer_ids = {importer["name"]: fetch_id(cur, "importers", importer["name"]) for importer in IMPORTERS}
            manufacturer_ids = {
                manufacturer: fetch_id(cur, "manufacturers", manufacturer) for manufacturer in MANUFACTURERS
            }

            for importer_name, brand_name, relationship_type in BRAND_IMPORTERS:
                ensure_brand_importer(cur, brand_ids[brand_name], importer_ids[importer_name], relationship_type)
            for brand_name, manufacturer_name in BRAND_MANUFACTURERS:
                ensure_brand_manufacturer(cur, brand_ids[brand_name], manufacturer_ids[manufacturer_name])

            conn.commit()

            for table in [
                "product_brands",
                "importers",
                "manufacturers",
                "brand_importers",
                "brand_manufacturers",
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                print(f"{table}: {count}")


if __name__ == "__main__":
    main()
