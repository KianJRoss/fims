#!/usr/bin/env python3
"""Expand the set of auto-correctable World Class photos (READ-ONLY).

The first audit (verify_images.py) truncated OCR text to 200 chars, so any box
whose printed item number sat further down was missed. This pass re-reads every
MISMATCH/UNCERTAIN photo with:

  1) FULL RapidOCR text (no truncation) -> all 7-8 digit tokens on the box, and
  2) a SKU-targeted Qwen2.5-VL prompt that specifically reads the small printed
     item/model number near the barcode/warning block, plus the big box name.

A printed item number that exists in the DB as a DIFFERENT product means the
photo definitively belongs to that other product. We tier the result:

  HIGH  -- a known different SKU was found AND qwen's box-name read matches that
           SKU's DB name (two independent signals agree).
  MED   -- a known different SKU was found by one signal but the name doesn't
           corroborate (or several candidate SKUs).

NO DB WRITES. Outputs scripts/photos/remap_candidates.md + .json.
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
VISION_MODEL = os.environ.get("AUDIT_VISION_MODEL", "qwen2.5vl:7b")
DB_URL = os.environ.get("DATABASE_URL", "postgresql://fims:fims@100.73.208.99:5432/fims")
MEDIA = os.environ.get("MEDIA_ROOT", "media")
HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT_JSON = os.path.join(HERE, "audit_report.json")
OUT_JSON = os.path.join(HERE, "remap_candidates.json")
OUT_MD = os.path.join(HERE, "remap_candidates.md")

SKU_PROMPT = (
    "This is a photo of a consumer fireworks box. Respond with ONLY a JSON object "
    "with two keys: "
    '"item_number" (the small printed item / model / catalog number on the box, '
    "usually 6 to 8 digits, often near the barcode or the warning text; null if "
    'you cannot read one), and '
    '"product_name" (the largest brand / product name printed on the box).'
)

_rapid = None
def rapid_ocr(img_path):
    global _rapid
    if _rapid is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid = RapidOCR()
    import numpy as np
    from PIL import Image
    arr = np.array(Image.open(img_path).convert("RGB"))
    res, _ = _rapid(arr)
    return [r[1] for r in res] if res else []


def vision_sku(img_path):
    b = base64.b64encode(open(img_path, "rb").read()).decode()
    payload = {"model": VISION_MODEL, "stream": False, "prompt": SKU_PROMPT,
               "images": [b], "format": "json"}
    req = urllib.request.Request(
        OLLAMA + "/api/generate", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=240))
    raw = (r.get("response") or "").strip()
    try:
        d = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0)) if m else {}
    return (str(d.get("item_number") or "").strip(),
            str(d.get("product_name") or "").strip())


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_db():
    import psycopg
    with psycopg.connect(DB_URL) as c, c.cursor() as cur:
        cur.execute("SELECT item_number, name FROM products WHERE item_number IS NOT NULL")
        return {r[0]: r[1] for r in cur.fetchall()}


def name_targets(qwen_name, num2name, cur_item):
    """Item numbers whose DB name matches qwen's box-name read (excluding current)."""
    q = norm(qwen_name)
    if len(q) < 6:                       # too short/common to trust by name
        return []
    exact = [n for n, nm in num2name.items() if norm(nm) == q and n != cur_item]
    if exact:
        return sorted(set(exact))
    contains = [n for n, nm in num2name.items()
                if n != cur_item and len(norm(nm)) >= 6
                and (q in norm(nm) or norm(nm) in q)]
    return sorted(set(contains))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    num2name = load_db()
    audit = json.load(open(AUDIT_JSON, encoding="utf-8"))
    todo = [v for v in audit.values() if v["verdict"] in ("MISMATCH", "UNCERTAIN")]
    todo.sort(key=lambda v: v["item_number"])
    if args.limit:
        todo = todo[: args.limit]
    print(f"Re-scanning {len(todo)} MISMATCH/UNCERTAIN photos (full OCR + SKU-targeted qwen)")

    results = {}
    for i, v in enumerate(todo, 1):
        cur_item = v["item_number"]
        img = os.path.join(MEDIA, v.get("image_path") or "")
        t = time.time()
        if not (os.path.isfile(img) and os.path.getsize(img) > 0):
            continue
        try:
            ocr = rapid_ocr(img)
            full = " ".join(ocr)
            vsku, vname = vision_sku(img)
        except Exception as e:
            print(f"[{i}/{len(todo)}] {cur_item} ERR {type(e).__name__}")
            continue
        # candidate printed SKUs from both signals, excluding the current item#
        cand = set(re.findall(r"\b\d{6,8}\b", full))
        if re.fullmatch(r"\d{6,8}", vsku):
            cand.add(vsku)
        cand.discard(cur_item)
        known = sorted(n for n in cand if n in num2name)
        nmatch = name_targets(vname, num2name, cur_item)
        rec = {"item_number": cur_item, "name": v["name"], "verdict": v["verdict"],
               "candidates": known, "name_matches": nmatch, "qwen_name": vname,
               "image_path": v.get("image_path")}
        if known:
            target = known[0]
            tgt_name = num2name[target]
            # does the SKU's product name agree with qwen's box-name read?
            corroborated = bool(norm(vname) and (norm(vname) in norm(tgt_name)
                                or norm(tgt_name) in norm(vname)))
            # or does the SKU also show up as a unique name match?
            corroborated = corroborated or (target in nmatch)
            rec["target_item"] = target
            rec["target_name"] = tgt_name
            rec["via"] = "SKU+name" if corroborated else "SKU"
            rec["tier"] = "HIGH" if (corroborated and len(known) == 1) else "MED"
        elif len(nmatch) == 1:
            target = nmatch[0]
            rec["target_item"] = target
            rec["target_name"] = num2name[target]
            rec["via"] = "name"
            rec["tier"] = "NAME"           # unique name match, no SKU on box
        elif len(nmatch) > 1:
            rec["via"] = "name?"
            rec["tier"] = "NAME_AMBIG"     # qwen name matches several products
        else:
            rec["tier"] = "NONE"
        results[cur_item] = rec
        dt = round(time.time() - t)
        tag = rec["tier"]
        if rec.get("target_item"):
            extra = f"[{rec['via']}] -> {rec['target_item']} {str(rec['target_name'])[:22]}"
        elif nmatch:
            extra = f"name~{len(nmatch)} candidates: {','.join(nmatch[:4])}"
        else:
            extra = f"qwen_sku={vsku!r} name={vname[:18]!r}"
        print(f"[{i}/{len(todo)}] {dt}s {tag:5} {cur_item} {v['name'][:22]:22} {extra}")
        if i % 10 == 0 or i == len(todo):
            json.dump(results, open(OUT_JSON, "w", encoding="utf-8"), indent=1)

    json.dump(results, open(OUT_JSON, "w", encoding="utf-8"), indent=1)
    order = {"HIGH": 0, "MED": 1, "NAME": 2, "NAME_AMBIG": 3, "NONE": 4}
    rows = sorted(results.values(), key=lambda r: (order[r["tier"]], r["item_number"]))
    from collections import Counter
    c = Counter(r["tier"] for r in rows)
    pinned = c["HIGH"] + c["MED"] + c["NAME"]
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("# World Class photo remap candidates (expanded: full-OCR + SKU-targeted VLM + name match)\n\n")
        f.write(f"**{pinned} of {len(rows)}** wrong/uncertain photos now pinned to a specific product. "
                f"READ-ONLY; no DB changes.\n\n")
        f.write(f"- **HIGH {c['HIGH']}** — printed SKU of a different product AND box-name agrees (safest)\n")
        f.write(f"- **MED {c['MED']}** — printed SKU of a different product (name didn't corroborate)\n")
        f.write(f"- **NAME {c['NAME']}** — no SKU on box, but qwen's box-name uniquely matches one other product\n")
        f.write(f"- NAME_AMBIG {c['NAME_AMBIG']} — box-name matches several products (needs a human pick)\n")
        f.write(f"- unpinnable {c['NONE']} — product not identifiable from the box / not in DB\n\n")
        f.write("| tier | via | current item# | current name | -> correct item# | correct name | qwen read |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in rows:
            if r["tier"] in ("NONE", "NAME_AMBIG"):
                continue
            f.write(f"| {r['tier']} | {r.get('via','')} | {r['item_number']} | {r['name']} | "
                    f"{r.get('target_item','')} | {r.get('target_name','')} | {r.get('qwen_name','')} |\n")
    print(f"\nDone. pinned={pinned}/{len(rows)}  {dict(c)}. Report: {OUT_MD}")


if __name__ == "__main__":
    main()
