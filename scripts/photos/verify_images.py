#!/usr/bin/env python3
"""FIMS product-photo audit (READ-ONLY) -- multi-engine OCR + AI-vision ensemble.

Checks whether each product's stored image actually depicts the named product, to
catch the wrong-photo mess in CLAUDE.md Priority 0 #4 (esp. World Class / Jake's).
NO DB WRITES, NO image fetching, NO image_path changes.

To "make certain", each photo is read by several independent engines and the verdict
is a consensus:

  A) printed-SKU check  (RapidOCR)  -- World Class prints the item number on the box;
     if the box's printed item number == the DB item_number, the photo is definitively
     the right product. This is the strongest signal.
  B) AI vision name     (llava-llama3 via local Ollama) -- reads the prominent product
     name off the box art (handles stylized branding the OCR garbles).
  C) full-text name     (RapidOCR, + pytesseract if the tesseract binary is present) --
     does the DB product name appear in any printed text on the box?

These mirror the OCR stack the repo's catalog pipeline already uses
(scripts/extract_catalog.py: RapidOCR primary, pytesseract fallback).

Verdict: printed-SKU match -> MATCH(sku). Else best name ratio >=0.8 -> MATCH;
>=0.5 -> UNCERTAIN; else MISMATCH. Missing file -> ERROR. Worst-first report so a
human (or Claude native vision) only has to look at the suspect tail.

Usage:
  python scripts/photos/verify_images.py --brand "World Class"
  python scripts/photos/verify_images.py --ids 1011418,1003942 --redo
  python scripts/photos/verify_images.py --sample 8
"""
import argparse
import base64
import glob
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from difflib import SequenceMatcher

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
VISION_MODEL = os.environ.get("AUDIT_VISION_MODEL", "llava-llama3")
DB_URL = os.environ.get("DATABASE_URL", "postgresql://fims:fims@100.73.208.99:5432/fims")
MEDIA = os.environ.get("MEDIA_ROOT", "media")
HERE = os.path.dirname(os.path.abspath(__file__))
JSON_OUT = os.path.join(HERE, "audit_report.json")
MD_OUT = os.path.join(HERE, "audit_report.md")

VISION_PROMPT = (
    "Look at this consumer fireworks product photo. Respond with ONLY a JSON object, "
    "no other text, with these keys: "
    '"label_text" (the largest brand/product name printed on the box, as a string), '
    '"single_product" (true if one product/box, false if several different products), '
    '"quality" (one of "ok","blank","cropped").'
)

# ---- engines -------------------------------------------------------------

_rapid = None
def rapid_ocr(img_path):
    """All text regions on the image, as a list of strings (RapidOCR / PaddleOCR onnx)."""
    global _rapid
    if _rapid is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid = RapidOCR()
    import numpy as np
    from PIL import Image
    arr = np.array(Image.open(img_path).convert("RGB"))
    res, _ = _rapid(arr)
    return [r[1] for r in res] if res else []


_TESS = shutil.which("tesseract")
def tess_ocr(img_path):
    if not _TESS:
        return ""
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(img_path), config="--psm 11")
    except Exception:
        return ""


def vision_label(img_path):
    b = base64.b64encode(open(img_path, "rb").read()).decode()
    payload = {"model": VISION_MODEL, "stream": False, "prompt": VISION_PROMPT,
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
    return {"label_text": str(d.get("label_text", "")).strip(),
            "single_product": d.get("single_product"),
            "quality": d.get("quality")}

# ---- matching ------------------------------------------------------------

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_STOP = {"the", "and", "of", "a", "an", "in", "on", "with", "for", "1", "2", "3", "4",
         "5", "6", "7", "8", "9", "0", "pc", "pcs", "pack", "shot", "shots", "gram",
         "grams", "g", "oz", "inch", "in"}


def name_ratio(text, name):
    a, b = norm(text), norm(name)
    if not a or not b:
        return 0.0
    if b in a or a in b:
        return max(0.85, SequenceMatcher(None, a, b).ratio())
    ta = set(re.findall(r"[a-z0-9]+", (text or "").lower())) - _STOP
    tb = set(re.findall(r"[a-z0-9]+", (name or "").lower())) - _STOP
    # Bidirectional token overlap: long descriptive DB names ("M-5000 CRACKER MAX
    # LOAD 1 3/4...") shouldn't be penalized just because the box shows only the
    # key name. Take the max of "fraction of DB words seen" and "fraction of read
    # words that are real DB words" so a strong partial match still scores high.
    inter = len(ta & tb)
    tok_name = inter / max(1, len(tb)) if tb else 0.0   # fraction of DB name words seen
    tok_read = inter / max(1, len(ta)) if ta else 0.0   # fraction of read words in DB name
    tok = max(tok_name, tok_read)
    return max(SequenceMatcher(None, a, b).ratio(), tok)


def sku_printed(item_number, ocr_texts):
    """True if the DB item number appears as printed text on the box."""
    n = norm(item_number)
    if len(n) < 5:                       # too short to be a confident hit
        return False
    return n in norm(" ".join(ocr_texts))

# ---- db ------------------------------------------------------------------

def fetch_products(args):
    import psycopg
    where, params = ["p.image_path IS NOT NULL"], []
    if args.ids:
        where.append("p.item_number = ANY(%s)")
        params.append([x.strip() for x in args.ids.split(",") if x.strip()])
    if args.brand:
        where.append("b.name = %s")
        params.append(args.brand)
    sql = ("SELECT p.id, p.item_number, p.name, b.name, p.image_path "
           "FROM products p LEFT JOIN product_brands b ON b.id=p.brand_id "
           "WHERE " + " AND ".join(where) + " ORDER BY p.item_number")
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = [{"id": str(r[0]), "item_number": r[1], "name": r[2],
                 "brand": r[3], "image_path": r[4]} for r in cur.fetchall()]
    if args.sample:
        import random
        random.shuffle(rows)
        return rows[: args.sample]
    return rows[: args.limit] if args.limit else rows

# ---- verdict + report ----------------------------------------------------

def decide(p, img):
    if not img:
        return dict(verdict="ERROR", error="missing_file", ratio=0.0,
                    sku_match=False, vision_label="", ocr_text="")
    rapid = rapid_ocr(img)
    tess = tess_ocr(img)
    vis = vision_label(img)
    all_ocr = rapid + ([tess] if tess else [])
    sku = sku_printed(p["item_number"], all_ocr)
    r_vision = name_ratio(vis["label_text"], p["name"])
    r_ocr = name_ratio(" ".join(all_ocr), p["name"])
    ratio = round(max(r_vision, r_ocr), 2)
    # did vision actually read a confident, real product phrase (vs garble/empty)?
    vis_words = re.findall(r"[a-z]{3,}", vis["label_text"].lower())
    vision_confident = len(vis_words) >= 1
    if sku:
        v = "MATCH"               # printed SKU is definitive
    elif ratio >= 0.8:
        v = "MATCH"
    elif ratio >= 0.5:
        v = "UNCERTAIN"
    elif vision_confident:
        # an engine clearly read a DIFFERENT product than the DB name
        v = "MISMATCH"
    else:
        # engines garbled/blank -- could be a correct but heavily stylized label;
        # don't condemn it, send it to arbitration (2nd model / native vision)
        v = "UNCERTAIN"
    return dict(verdict=v, ratio=ratio, sku_match=sku,
                vision_label=vis["label_text"], single_product=vis["single_product"],
                quality=vis["quality"], ocr_text=" | ".join(rapid)[:200],
                r_vision=round(r_vision, 2), r_ocr=round(r_ocr, 2))


SEV = {"ERROR": 0, "NO_TEXT": 1, "MISMATCH": 2, "UNCERTAIN": 3, "MATCH": 4}


def write_md(results):
    rows = sorted(results.values(),
                  key=lambda r: (SEV.get(r["verdict"], 9), r.get("ratio", 1.0)))
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write("# FIMS product-photo audit (worst-first)\n\n")
        f.write(f"_Engines: RapidOCR + {VISION_MODEL}"
                + ("" if not _TESS else " + tesseract")
                + ". Read-only; no DB or image changes._\n\n")
        f.write("Verdicts: " + ", ".join(f"**{k}** {v}" for k, v in sorted(counts.items()))
                + f"  (total {len(rows)})\n\n")
        f.write("| verdict | item# | DB name | vision read | OCR text | ratio | sku |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['verdict']} | {r['item_number']} | {r['name']} | "
                    f"{r.get('vision_label','')} | {r.get('ocr_text','')} | "
                    f"{r.get('ratio','')} | {'Y' if r.get('sku_match') else ''} |\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", default=None)
    ap.add_argument("--ids", default=None)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()

    results = {}
    if os.path.isfile(JSON_OUT) and not args.redo:
        results = json.load(open(JSON_OUT, encoding="utf-8"))

    products = fetch_products(args)
    todo = [p for p in products if args.redo or p["id"] not in results]
    print(f"{len(products)} products ({len(products)-len(todo)} already done), "
          f"engines: RapidOCR + {VISION_MODEL}" + (" + tesseract" if _TESS else ""))

    for i, p in enumerate(todo, 1):
        img = (lambda fp: fp if (os.path.isfile(fp) and os.path.getsize(fp) > 0) else None)(
            os.path.join(MEDIA, p["image_path"]))
        t = time.time()
        try:
            rec = {**p, **decide(p, img)}
        except Exception as e:
            rec = {**p, "verdict": "ERROR", "error": type(e).__name__,
                   "ratio": 0.0, "sku_match": False}
        results[p["id"]] = rec
        print(f"[{i}/{len(todo)}] {round(time.time()-t)}s {rec['verdict']:9} "
              f"{p['item_number']:10} {p['name'][:26]:26} "
              f"sku={'Y' if rec.get('sku_match') else '-'} r={rec.get('ratio','')} "
              f"vis={rec.get('vision_label','')[:22]!r}")
        if i % 5 == 0 or i == len(todo):
            json.dump(results, open(JSON_OUT, "w", encoding="utf-8"), indent=1)
            write_md(results)

    json.dump(results, open(JSON_OUT, "w", encoding="utf-8"), indent=1)
    write_md(results)
    print(f"\nDone. Report: {MD_OUT}")


if __name__ == "__main__":
    main()
