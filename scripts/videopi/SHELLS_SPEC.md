# BUILD TASK: apply_playlist_matches_shells.py

Create ONE new file: `scripts/videopi/apply_playlist_matches_shells.py`. Do NOT modify any other
file. Do NOT run it, do NOT touch the network/DB. It only PRINTS SQL to stdout.

Mirror `scripts/videopi/apply_playlist_matches_500g.py` EXACTLY (same imports, q(), load_products(),
load_titles(), main() structure, same INSERT/UPDATE/DELETE SQL shape, BEGIN/COMMIT, the
`groups.setdefault(pid,...)` multi-video-per-product handling, the in_store UPDATE, and the
demote-old-then-delete-then-reinsert block). The ONLY differences are the MATCHES list below and the
brand-id constants. No "Pyro High" brand bootstrap line is needed here — delete that INSERT INTO
product_brands preamble; just start `out = ["BEGIN;"]`.

Usage stays identical:
  python scripts/videopi/apply_playlist_matches_shells.py products.txt playlist_shells.txt > apply_shells.sql

## Brand id constants (resolved from live DB 2026-06-26)
B_GRIZZLY = 53      # Great Grizzly
B_BROTHERS = 16     # Brothers
B_MADOX = 54        # Mad Ox
B_WC = 45           # World Class

## MATCHES (youtube_id, kind, payload, is_primary) — hand-verified, do not alter
# kind "existing": payload = item_number (all confirmed present in DB)
# kind "new":      payload = (item_number_or_None, name, brand_id_or_None)
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
    ("4F0dWpPrEQg", "existing", "1004004", True),                                   # Predator XL (primary)
    ("8me_8nw7NkM", "existing", "1004004", False),                                  # Predator Anniversary (same product, secondary)
    ("e1GA-DD-eFI", "existing", "1001416", True),                                   # Whistling Jake
    ("056L6-buyGw", "existing", "1001493", True),                                   # Sir Lancelot
    ("G3VYpCNJVdM", "existing", "GP0809", True),                                    # BTA (Belt to Ass), Pyromaniacs
    ("O1owyQb6L_k", "existing", "26FW809A", True),                                  # Monster Shells
    ("4dxcBYtzMxs", "existing", "FC1001", True),                                    # PyroManiacs salute, Pyromaniacs
]

NOTE: the Predator product (1004004) intentionally has TWO videos — the existing
`groups.setdefault(pid, []).append((yid, primary))` logic already groups both under the same pid, so
no special handling is required; just keep the False for the Anniversary one so only Predator XL is
primary. Item numbers Cr2027 / 23FE502 / GP0809 / FC1001 are mixed-case in the DB but
load_products() upper-cases keys and lookups, so they resolve fine.
