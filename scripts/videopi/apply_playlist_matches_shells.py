#!/usr/bin/env python3
"""Generate SQL to wire the in-store shells playlist videos to FIMS products.

Same mechanics as apply_playlist_matches.py (the 200g version) -- see that file's
docstring. Reviewed match list below was built from playlist_shells.txt + the live
products.txt and hand-verified: every "existing" item_number was confirmed present;
the "new" entries were confirmed absent.

Usage:
  python scripts/videopi/apply_playlist_matches_shells.py products.txt playlist_shells.txt > apply_shells.sql
"""
import sys
import uuid

# brand ids resolved from the live DB on 2026-06-26
B_GRIZZLY, B_BROTHERS, B_MADOX, B_WC = 53, 16, 54, 45

# (youtube_id, kind, payload, is_primary)
#   kind "existing": payload = item_number (verified present in products.txt)
#   kind "new":      payload = (item_number_or_None, name, brand_id_or_None)
MATCHES = [
    ("T3CCvBPVJDM", "existing", "1003570", True),                                   # Excalibur Platinum
    ("JMnZhWxQXsQ", "existing", "1001401", True),                                   # Excalibur
    ("YEjXEWpbAKg", "new", (None, "Terminator", B_GRIZZLY), True),                  # Great Grizzly, no SKU
    ("N4KvAbu6LC0", "new", ("BP-A081", "Gone Ballistic", B_BROTHERS), True),
    ("k8a_l552p1I", "existing", "1004083", True),                                   # Pure Venom
    ("dDBpsbv7nrU", "existing", "1003547", True),                                   # Growler
    ("64ySasNLi2M", "existing", "Cr2027", True),                                    # HCMF Loco
    ("p9rMFW5OY38", "existing", "1004330", True),                                   # Ultimate American
    ("9rgoraScw8M", "new", (None, "Avenger", B_WC), True),                          # World Class, no SKU
    ("40Hv1haw56o", "existing", "1004329", True),                                   # Victory Vault
    ("uVvn8VuaIug", "existing", "1001478", True),                                   # Super Magnum W/ Tail
    ("N5srCJjQLmQ", "new", ("BP-A036", "Smoke-n-Mirrors", B_BROTHERS), True),
    ("25UPfYSH9J4", "new", ("OX319-6", "Raging Bull", B_MADOX), True),
    ("WFxu-QNr6pA", "existing", "23FE502", True),                                   # Tiki Bomb
    ("4F0dWpPrEQg", "new", (None, "Predator XL", B_GRIZZLY), True),                 # Predator XL — distinct from Predator (user); Great Grizzly
    ("8me_8nw7NkM", "existing", "1004004", True),                                   # Predator Anniversary = normal Predator w/ new box (user)
    ("e1GA-DD-eFI", "existing", "1001416", True),                                   # Whistling Jake
    ("056L6-buyGw", "existing", "1001493", True),                                   # Sir Lancelot
    ("G3VYpCNJVdM", "existing", "GP0809", True),                                    # BTA (Belt to Ass), Pyromaniacs
    ("O1owyQb6L_k", "existing", "26FW809A", True),                                  # Monster Shells
    ("4dxcBYtzMxs", "existing", "FC1001", True),                                    # PyroManiacs salute, Pyromaniacs
]

# brand corrections on EXISTING products (item_number -> brand_id). User: Predator
# is Great Grizzly, not World Class (the Anniversary box video confirms it).
BRAND_FIX = {
    "1004004": B_GRIZZLY,   # PREDATOR: World Class -> Great Grizzly
}


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

    out = ["BEGIN;"]

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
            brand_sql = str(brand) if brand else "NULL"
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

    # brand corrections on existing products
    for item, brand_id in BRAND_FIX.items():
        pid = products.get(item.upper())
        if not pid:
            sys.stderr.write(f"BRAND_FIX: item {item!r} not found, skipped\n")
            continue
        out.append(f"-- brand fix {item}")
        out.append(f"UPDATE products SET brand_id={brand_id}, updated_at=now() "
                   f"WHERE id={q(pid)};")

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
