#!/usr/bin/env python3
"""Generate SQL to wire the in-store 200g-cake playlist videos to FIMS products.

Emits SQL to stdout (review, then pipe to psql). For each target product:
  1. demote every existing video on it (is_primary=false, confirmed=false)
     -- clears the suspect auto-matches
  2. delete any stray copy of the in-store youtube_id anywhere (idempotent re-run)
  3. insert the in-store video(s) as confirmed + primary, source='instore_playlist'
New products (in the building but not in FIMS) are created first with minimal,
review-flagged records. Brand ids are resolved from the live DB (see header note).

Usage:
  python scripts/videopi/apply_playlist_matches.py /tmp/products.txt /tmp/cakes_playlist.txt > /tmp/apply.sql
"""
import re
import sys
import uuid

# brand ids resolved from the live DB on 2026-06-25
B_SUNWING, B_GRIZZLY, B_LEGEND, B_WC, B_SUNS, B_FIRE, B_WINDA = 1, 53, 32, 45, 3, 37, 17
B_PYROHIGH = "PYROHIGH"  # placeholder -> resolved via subselect (brand created below)

# (youtube_id, kind, payload, is_primary)
#   kind "existing": payload = item_number
#   kind "new":      payload = (item_number_or_None, name, brand_id_or_None)
MATCHES = [
    ("TwZ4jVlfSik", "existing", "NN2034", True),
    ("WQpGD-jYT4U", "existing", "NN2032", True),
    ("X8PmC7IVbqI", "existing", "NN2036", True),
    ("uYYPJ9iUFmE", "existing", "NN2028", True),
    ("kDidkuxqVrE", "existing", "NN2030", True),
    ("PdenLf-BvcI", "existing", "SWC2179", True),    # Huckleberry (primary)
    ("2bnCMvHCzMg", "existing", "SWC2179", False),   # Fearless (same product)
    ("aEXVHhsVTLM", "existing", "1004283", True),
    ("WxP2GJUoSc8", "existing", "1001301", True),
    ("0kAJKUmU8ng", "existing", "NN2007", True),
    ("LbekmzzJxv8", "existing", "1003498", True),
    ("ybHQGgbnLoM", "existing", "NN2043", True),
    ("oEheTpmqwQY", "existing", "NN2005", True),
    ("zmGqb1igaJw", "existing", "NN2027", True),
    ("Ji8MZ-Hjwf4", "existing", "NN2037", True),
    ("XTnIEiBAPqY", "existing", "NN2033", True),
    ("XnzJn4fhZVs", "existing", "SSRP2301", True),
    ("B2lW8gfXSKE", "existing", "NN2035", True),
    ("6LTSpDkcmJ0", "existing", "NN2039", True),
    ("oP2d5FDmw3s", "existing", "1004279", True),
    ("CDwYJ_PgYz4", "existing", "1004278", True),
    ("KGYKNPH9h2k", "existing", "1001348", True),
    ("VEaMgL5sKnk", "existing", "1004008", True),
    ("5jw1GBQO8cw", "existing", "1013515", True),
    # Pyromaniacs-Wholesale name matches (user approved attaching)
    ("yQOrMcwVyBw", "existing", "FC3017", True),     # Enforcer
    ("tTKx7oT1Zco", "existing", "22F221", True),     # Lights Out
    # new products (in building, not yet in FIMS)
    ("YWJnGsUC3kQ", "new", (None, "T.N.T.B.A.M", B_SUNWING), True),
    ("CXtFvSWlF_Q", "new", (None, "Inferno Run", B_GRIZZLY), True),
    ("aae976qI2qw", "new", (None, "Key Break", B_LEGEND), True),
    ("kzh4uLgpQ0g", "new", ("SW10163T", "Clowning Around", B_SUNWING), True),
    ("iDijPRUUPJQ", "new", ("BP2787", "Gold Alert", None), True),
    ("8tXXbdpKVys", "new", (None, "One Bad Baby", B_WC), True),
    ("WaODoaRFD3I", "new", (None, "Toadally Awesome", None), True),
    ("f28IAPNGw14", "new", (None, "King Cobra", B_FIRE), True),
    ("xkuE1TrpjFI", "new", (None, "Furs for Losers", None), True),
    ("DE0i-9-jI60", "new", ("PH2109", "Blaze It", B_PYROHIGH), True),
    ("BrPeYZGkTF0", "new", ("P5192", "Pulse Pounder", B_WINDA), True),
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
        # repair the cp1252 smart-apostrophe that came through as U+FFFD
        titles[yid.strip()] = title.strip().replace("�", "'")
    return titles


def main():
    products = load_products(sys.argv[1])
    titles = load_titles(sys.argv[2])

    # resolve targets -> product id (uuid); create new ones
    out = ["BEGIN;",
           "-- ensure Pyro High brand exists",
           "INSERT INTO product_brands (name, updated_at) SELECT 'Pyro High', now() "
           "WHERE NOT EXISTS (SELECT 1 FROM product_brands WHERE name='Pyro High');"]

    # group by target product id, preserving order
    groups = {}      # pid -> list of (yid, is_primary)
    created = []
    errors = []
    for yid, kind, payload, primary in MATCHES:
        if kind == "existing":
            pid = products.get(payload.upper())
            if not pid:
                errors.append(f"item {payload} not found for {yid}")
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
