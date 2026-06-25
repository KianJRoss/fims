#!/usr/bin/env python3
"""Generate SQL to wire the in-store 500g-cake playlist videos to FIMS products.

Same mechanics as apply_playlist_matches.py (the 200g version) -- see that file's
docstring. Reviewed match list below was built from playlist_500g.txt + the live
products.txt (1436 rows pulled from the Pi DB on 2026-06-25) and hand-verified:
every "existing" item_number was confirmed present; the "new" entries were
confirmed *absent* (e.g. Panda Tai != Panda Fountain 1004113, Mummy Blaster !=
Mummy NN2031, Turbo != Turbo Truckster 1004111).

Usage:
  python scripts/videopi/apply_playlist_matches_500g.py products.txt playlist_500g.txt > apply_500g.sql
"""
import sys
import uuid

# brand ids resolved from the live DB on 2026-06-25
B_SUNWING, B_GRIZZLY, B_LEGEND, B_WC, B_NONAME = 1, 53, 32, 45, 5
B_PYROHIGH = "PYROHIGH"  # resolved via subselect (brand row already exists, id 70)

# (youtube_id, kind, payload, is_primary)
#   kind "existing": payload = item_number (verified present in products.txt)
#   kind "new":      payload = (item_number_or_None, name, brand_id_or_None)
MATCHES = [
    ("OZyI23kMCkY", "existing", "1015147", True),          # Gorilla Warfare
    ("UP2TgApX6A4", "new", (None, "Voodoo", B_GRIZZLY), True),
    ("8J5Qb7csF20", "new", (None, "Nature's Rampage", B_WC), True),
    ("KSTOtO6Jvnw", "existing", "MC5101", True),            # Chevelle
    ("a4zqtZr2Qdo", "existing", "1015085", True),           # Flicker
    ("yDHlbGbUyJM", "existing", "1003893", True),           # Made in America
    ("Fw1N2xuatIM", "existing", "1015389", True),           # Loud & Proud
    ("D6lx2SZX_fo", "existing", "SWC2199", True),           # Never Retreat Never Surrender
    ("HG3LjHTB2FA", "existing", "NN5059", True),            # Oh Snap!
    ("ZEoYo6yFQtA", "existing", "1013185", True),           # One Bad Mother
    ("3jaVd0Zc8mc", "existing", "1015039", True),           # Crazy Exciting on Steroids
    ("VZ1gRUw7nTc", "new", (None, "Panda Tai", B_WC), True),  # NOT Panda Fountain
    ("o4pBK7icdZM", "existing", "1004327", True),           # Sunflower Delight
    ("ArekcgDzMRo", "existing", "1030029", True),           # Chasing Booty
    ("wmWcu16__jE", "existing", "1004103", True),           # Red White Rawwwr
    ("DHyG_AXN6pw", "existing", "1015406", True),           # Breathing Fire
    ("7j_1hMWMg5I", "existing", "1015402", True),           # Trigger Happy
    ("PEI2NOlaqjk", "existing", "1004314", True),           # Gorilla Jams
    ("F6ML0EIoqyw", "existing", "1004317", True),           # Love It or Leave It
    ("OcpsH8KD7M0", "existing", "1015439", True),           # Future Warrior
    ("hPj5bBgpTQo", "new", ("NN5018", "Eye See You", B_NONAME), True),
    ("Zy3NSvid4Ik", "existing", "1004037", True),           # Showboatin
    ("FgQSKqevLEU", "existing", "1015137", True),           # Fighting Rooster
    ("87vgVZqYqWw", "new", (None, "Spaz", B_WC), True),
    ("LSwAZXqYE54", "new", ("BP2877", "Last Man Standing", None), True),
    ("a34PqNKzXE0", "existing", "1004325", True),           # Bead Bandit
    ("yzzbXOg63nc", "existing", "1004328", True),           # Comet Me Bro
    ("ekKxNdk3Kfk", "existing", "1013121", True),           # Loyal To None
    ("QtDj2ypnCVs", "existing", "M513", True),              # Never Say Die
    ("0CFU-JNdd9E", "existing", "1001427", True),           # United We Stand
    ("hzyI9iNkiK4", "new", (None, "Gold Digger", B_WC), True),
    ("D23oBRkS-_M", "existing", "M5050", True),             # Luck of the Irish
    ("XyO8gtVSTTI", "existing", "SWC2630", True),           # Let Freedom Ring
    ("8CIc_dq8skE", "existing", "M5047", True),             # May the 4th
    ("Egk0EW0n9fY", "existing", "MA018", True),             # FJB
    ("oXDKWeMANaA", "existing", "SWC2636A/B/C", True),      # Quantum Burst
    ("Q--IBSaNfJE", "existing", "MA014", True),             # MVP
    ("yJ544S_nX3U", "existing", "CRC52325", True),          # Hell Raiser
    ("pnpaUyk9V4c", "existing", "1013224", True),           # Widow Maker
    ("0ql37Mxihew", "new", ("BP-A135", "Class Clown", None), True),
    ("FA6wbd13eNs", "existing", "1003754", True),           # USA Strong
    ("HI5-GmO3VqM", "existing", "1003704", True),           # Statue of Liberty
    ("k936sSSz1jM", "existing", "1003706", True),           # Bootleggers Dream
    ("uUjjm2NTfdU", "existing", "SWC2635", True),           # Gold Rush
    ("azg5tvwTRnU", "existing", "1024435", True),           # American Honor (DB: AMERICA)
    ("DQWSjN6rOkI", "existing", "1003506", True),           # Deadly Strike
    ("ExfpmmKJYUs", "existing", "1004033", True),           # Show Biz Baby
    ("oS5Lcnd380g", "new", (None, "Joltix", B_GRIZZLY), True),  # by Pyro Planet, dist. Great Grizzly
    ("cZRnIwJMK70", "existing", "1004386", True),           # We the People
    ("V5lc9iR6Tm8", "existing", "1003701", True),           # Harry Beaver
    ("GEkwxi42Z00", "existing", "MF510", True),             # Dream Weaver
    ("9WZUWwWCq9g", "existing", "1004019", True),           # Reptile Dysfunction
    ("jaJAWF-nBUM", "new", (None, "Chill Out", B_WC), True),
    ("61prCqZ0Rys", "existing", "1004373", True),           # Ol' Glory
    ("PQFRAK4XcpQ", "existing", "PED5503 were", True),      # Hells Bells (DB item# has typo)
    ("eOrYKNzxUrQ", "existing", "SQ5504", True),            # Zeppelin
    ("uBZiRnspxvc", "new", (None, "Uruk Hai", None), True),
    ("vJSvPOqktOA", "existing", "1004368", True),           # Women of Valor
    ("Z6Ee9kAWc0c", "existing", "1004372", True),           # All-American Athletics
    ("7Xff6E1tL2M", "existing", "1004376", True),           # We the People Love Fireworks
    ("KSggTBb9L5w", "existing", "1004318", True),           # Neon Stripes
    ("4O4cOlrYN-Q", "new", (None, "Bumble Bee", B_LEGEND), True),
    ("ODWQZU1Uc1c", "new", (None, "Devil Side", B_LEGEND), True),
    ("8CFPPX0sv-M", "existing", "1004116", True),           # Golden Boy
    ("viIOINsJyxs", "new", (None, "Strawberry Diesel", B_PYROHIGH), True),
    ("ybab_PfXL9U", "new", (None, "Corona Killer", None), True),
    ("czHK6P-_yHc", "new", (None, "Turbo", None), True),    # NOT Turbo Truckster 1004111
    ("rcDiFV79PLk", "new", (None, "Thor", None), True),
    ("GdCoGVowxYQ", "new", (None, "Infinity War", None), True),
    ("5FYySAnnkMY", "new", (None, "Mummy Blaster", B_LEGEND), True),  # NOT Mummy NN2031
]


def q(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def load_products(path):
    by_item = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        parts = line.rstrip("\n").split("|")
        if len(parts) < 4:
            continue
        pid, item = parts[0], parts[1]
        if item:
            by_item[item.upper()] = pid
    return by_item


def load_titles(path):
    titles = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        if " | " not in line:
            continue
        yid, title = line.rstrip("\n").split(" | ", 1)
        titles[yid.strip()] = title.strip().replace("�", "'")
    return titles


def main():
    products = load_products(sys.argv[1])
    titles = load_titles(sys.argv[2])

    out = ["BEGIN;",
           "-- ensure Pyro High brand exists (already id 70 on the Pi; no-op there)",
           "INSERT INTO product_brands (name, updated_at) SELECT 'Pyro High', now() "
           "WHERE NOT EXISTS (SELECT 1 FROM product_brands WHERE name='Pyro High');"]

    groups = {}      # pid -> list of (yid, is_primary)
    created = []
    errors = []
    for yid, kind, payload, primary in MATCHES:
        if kind == "existing":
            pid = products.get(payload.upper())
            if not pid:
                errors.append(f"item {payload!r} not found for {yid}")
                continue
        else:
            item, name, brand = payload
            pid = str(uuid.uuid4())
            brand_sql = ("(SELECT id FROM product_brands WHERE name='Pyro High')"
                         if brand == B_PYROHIGH else (str(brand) if brand else "NULL"))
            out.append(
                f"INSERT INTO products (id, item_number, name, brand_id, is_active, "
                f"in_store, needs_data_review, created_at, updated_at) VALUES "
                f"({q(pid)}, {q(item)}, {q(name)}, {brand_sql}, true, true, true, now(), now());")
            created.append((name, item, brand))
        groups.setdefault(pid, []).append((yid, primary))

    if errors:
        sys.stderr.write("ERRORS:\n  " + "\n  ".join(errors) + "\n")
        sys.exit(1)

    # flag every targeted product (existing + newly created) as in-store
    out.append("-- mark all targeted products in_store")
    out.append("UPDATE products SET in_store=true, updated_at=now() WHERE id IN ("
               + ",".join(q(pid) for pid in groups) + ");")

    for pid, vids in groups.items():
        out.append(f"-- product {pid}")
        out.append(f"UPDATE product_videos SET is_primary=false, confirmed=false "
                   f"WHERE product_id={q(pid)};")
        yids = [y for y, _ in vids]
        out.append("DELETE FROM product_videos WHERE youtube_id IN ("
                   + ",".join(q(y) for y in yids) + ");")
        for yid, primary in vids:
            title = titles.get(yid, "")
            out.append(
                f"INSERT INTO product_videos (product_id, file_path, is_primary, "
                f"uploaded_at, source, url, youtube_id, title, confirmed, "
                f"download_status, video_filename, created_at, updated_at) VALUES "
                f"({q(pid)}, {q('videos/'+yid+'.mp4')}, {str(primary).lower()}, now(), "
                f"'instore_playlist', {q('https://youtu.be/'+yid)}, {q(yid)}, {q(title)}, "
                f"true, 'pending', {q(yid+'.mp4')}, now(), now());")

    out.append("COMMIT;")
    print("\n".join(out))
    sys.stderr.write(
        f"\nGenerated: {len(groups)} target products, "
        f"{len(MATCHES)} videos, {len(created)} new products created.\n")


if __name__ == "__main__":
    main()
