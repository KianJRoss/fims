#!/usr/bin/env python3
"""Match a YouTube playlist of in-store firework videos to FIMS products.

These playlists are authoritative footage of products actually in the building,
so they're the trustworthy source for fixing the loose auto-matched videos
(see CLAUDE.md Priority 0 #5). This script only PROPOSES matches; it prints a
table for human review and writes nothing. Inputs are two pipe-delimited files
produced ahead of time:

  playlist file : "<youtube_id> | <title>"          (yt-dlp --flat-playlist)
  products file : "<id>|<item_number>|<name>|<brand>" (from the DB)

  python scripts/videopi/match_playlist.py /tmp/cakes_playlist.txt /tmp/products.txt
"""
import re
import sys
from difflib import SequenceMatcher


def norm_code(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_name(s: str) -> str:
    s = s.lower()
    # drop common noise words / brand mentions / spec tokens
    noise = [
        "fireworks", "firework", "world class", "no name", "by", "from",
        "gram", "200g", "200 gram", "shot", "shots", "aerial", "repeaters",
        "cake", "cakes", "multi-shot", "4k", "60fps", "insane", "gold field",
    ]
    for w in noise:
        s = s.replace(w, " ")
    s = re.sub(r"#\w+", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_products(path):
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        pid, item, name, brand = parts[0], parts[1], parts[2], parts[3]
        rows.append({
            "id": pid, "item": item, "name": name, "brand": brand,
            "ncode": norm_code(item), "nname": norm_name(name),
        })
    return rows


def best_match(title, products):
    nt = norm_code(title)
    # 1) item-number-in-title (require >=4 chars to avoid junk hits)
    code_hits = [
        p for p in products
        if p["ncode"] and len(p["ncode"]) >= 4 and p["ncode"] in nt
    ]
    if code_hits:
        # prefer the longest code (most specific)
        p = max(code_hits, key=lambda x: len(x["ncode"]))
        return p, "item#", 1.0
    # 2) fuzzy name match
    tn = norm_name(title)
    scored = []
    for p in products:
        if not p["nname"]:
            continue
        # ignore very short names ("t", "rp") -- they false-match everything
        if len(p["nname"]) < 4:
            continue
        r = SequenceMatcher(None, tn, p["nname"]).ratio()
        # boost if the product name appears as a whole token-run in the title;
        # scale by length so a longer exact substring ("redneck safari") beats
        # a shorter one ("safari") instead of tie-breaking arbitrarily
        if p["nname"] in tn:
            r = max(r, 0.9 + len(p["nname"]) / 1000.0)
        scored.append((min(r, 0.99), p))
    if not scored:
        return None, "none", 0.0
    r, p = max(scored, key=lambda x: x[0])
    return p, "name", round(r, 2)


def main():
    pl, prod = sys.argv[1], sys.argv[2]
    products = load_products(prod)
    entries = []
    for line in open(pl, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if " | " not in line:
            continue
        yid, title = line.split(" | ", 1)
        entries.append((yid.strip(), title.strip()))

    print(f"{'yid':<12}  {'meth':<5} {'score':<5}  {'item#':<14} {'brand':<16} match-name  <=  title")
    print("-" * 120)
    strong = weak = none = 0
    for yid, title in entries:
        p, meth, score = best_match(title, products)
        if p is None:
            none += 1
            print(f"{yid:<12}  {'--':<5} {'--':<5}  {'(no match)':<14} {'':<16} {'':<20} <= {title}")
            continue
        flag = ""
        if meth == "item#" or score >= 0.6:
            strong += 1
        else:
            weak += 1
            flag = "  ?? LOW"
        print(f"{yid:<12}  {meth:<5} {score:<5}  {p['item']:<14} {p['brand']:<16} {p['name'][:20]:<20} <= {title}{flag}")
    print("-" * 120)
    print(f"strong={strong}  weak/low={weak}  none={none}  total={len(entries)}")


if __name__ == "__main__":
    main()
