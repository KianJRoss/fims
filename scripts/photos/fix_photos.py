#!/usr/bin/env python3
"""Apply (or dry-run) the World Class photo remap from remap_candidates.json.

The audit found that the image FILE currently attached to product S actually
depicts a different product T (the "pin": S -> T). The correct image for product
T is therefore the file that currently sits at S's image_path. So the fix is a
pure DB repoint:

    products[T].image_path := products[S].image_path

Files are never moved or renamed (paths stay product_images/<item>.<ext>), so the
change is fully reversible by restoring the saved image_path values. For a mutual
swap A<->B both repoint and the swap is resolved. For a chain end (S->T but nobody
shows S) only T is fixed; S keeps pointing at a wrong file and is listed as still
needing a correct photo.

Collisions (two+ sources claiming the same target) are arbitrated by confidence:
HIGH > MED > NAME, then SKU-corroborated, then exact name match. The losing
source is dropped from the plan and reported as still-wrong.

DRY-RUN by default: prints/writes the full before/after plan and writes NOTHING to
the DB. Pass --apply to perform the repoint; --apply first saves every current
image_path to scripts/photos/fix_backup.json for rollback (scripts/photos/fix_photos.py --rollback).
"""
import argparse
import json
import os
import re
import sys

DB_URL = os.environ.get("DATABASE_URL", "postgresql://fims:fims@100.73.208.99:5432/fims")
HERE = os.path.dirname(os.path.abspath(__file__))
PINS_JSON = os.path.join(HERE, "remap_candidates.json")
AUDIT_JSON = os.path.join(HERE, "audit_report.json")
PLAN_JSON = os.path.join(HERE, "fix_plan.json")
PLAN_MD = os.path.join(HERE, "fix_plan.md")
BACKUP_JSON = os.path.join(HERE, "fix_backup.json")

TIER_SCORE = {"HIGH": 3, "MED": 2, "NAME": 1}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def db():
    import psycopg
    return psycopg.connect(DB_URL)


def load_products():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT item_number, name, image_path FROM products "
                    "WHERE item_number IS NOT NULL")
        return {r[0]: {"name": r[1], "image_path": r[2]} for r in cur.fetchall()}


def score(pin, target_name):
    s = TIER_SCORE.get(pin["tier"], 0)
    if "SKU" in (pin.get("via") or ""):
        s += 0.5
    if norm(pin.get("qwen_name")) == norm(target_name):
        s += 0.25
    return s


def build_plan(prods):
    pins = json.load(open(PINS_JSON, encoding="utf-8"))
    audit = json.load(open(AUDIT_JSON, encoding="utf-8"))
    verdict = {a["item_number"]: a["verdict"] for a in audit.values()}
    # group all source->target pins by target, keep the strongest source per target
    by_target = {}
    losers = []
    dup_sources = []   # source's file shows an ALREADY-correct product -> source needs its own photo
    for src, v in pins.items():
        if v["tier"] not in TIER_SCORE or not v.get("target_item"):
            continue
        tgt = v["target_item"]
        if tgt not in prods or src not in prods:
            continue
        # SAFETY: only repoint a target that is currently wrong (MISMATCH) or has a
        # missing/broken file (ERROR). If the target is already MATCH/UNCERTAIN (or
        # was not audited), repointing could overwrite a good photo -- skip it and
        # treat the source as a duplicate that needs its own photo instead.
        if verdict.get(tgt) not in ("MISMATCH", "ERROR"):
            dup_sources.append({"src": src, "tgt": tgt, "tgt_verdict": verdict.get(tgt, "NOT_AUDITED")})
            continue
        cand = {"src": src, "tgt": tgt, "tier": v["tier"], "via": v.get("via"),
                "qwen_name": v.get("qwen_name"),
                "src_name": prods[src]["name"], "tgt_name": prods[tgt]["name"],
                "src_path": prods[src]["image_path"],
                "old_tgt_path": prods[tgt]["image_path"]}
        prev = by_target.get(tgt)
        if prev is None or score(v, prods[tgt]["name"]) > prev["_score"]:
            if prev is not None:
                losers.append(prev)
            cand["_score"] = score(v, prods[tgt]["name"])
            by_target[tgt] = cand
        else:
            losers.append(cand)

    plan = sorted(by_target.values(),
                  key=lambda x: (-TIER_SCORE.get(x["tier"], 0), x["tgt"]))
    targets = set(by_target)
    sources = {p["src"] for p in plan}
    # a source whose own file is reassigned away but is never itself a target ->
    # it keeps pointing at a wrong photo and needs a fresh image
    orphan_sources = sorted(s for s in sources if s not in targets)
    dup_need_photo = sorted({d["src"] for d in dup_sources} - targets)
    return plan, losers, orphan_sources, dup_need_photo


def write_plan(plan, losers, orphans, dup_need_photo, prods):
    audit = json.load(open(AUDIT_JSON, encoding="utf-8"))
    fixed_targets = {p["tgt"] for p in plan}
    missing = sorted(v["item_number"] for v in audit.values()
                     if v["verdict"] == "ERROR" and v["item_number"] not in fixed_targets)
    unpinned = sorted(v["item_number"] for v in audit.values()
                      if v["verdict"] in ("MISMATCH", "UNCERTAIN")
                      and v["item_number"] not in fixed_targets
                      and v["item_number"] not in {p["src"] for p in plan})
    out = {"repoints": [{"target_item": p["tgt"], "target_name": p["tgt_name"],
                         "new_image_path": p["src_path"], "old_image_path": p["old_tgt_path"],
                         "from_source": p["src"], "tier": p["tier"], "via": p["via"]}
                        for p in plan],
           "conflict_losers": [{"item": l["src"], "wanted_target": l["tgt"],
                                "tier": l["tier"]} for l in losers],
           "orphan_sources_need_photo": orphans,
           "duplicate_sources_need_photo": dup_need_photo,
           "still_unpinned": unpinned, "missing_file": missing}
    json.dump(out, open(PLAN_JSON, "w", encoding="utf-8"), indent=1)
    with open(PLAN_MD, "w", encoding="utf-8") as f:
        f.write("# World Class photo fix plan (DRY-RUN — nothing applied)\n\n")
        f.write(f"- **{len(plan)} products** would get their image repointed to the file that depicts them "
                f"(regression-safe: every target is currently MISMATCH or has a missing file)\n")
        f.write(f"- {len(losers)} conflict losers dropped (a stronger source won the same target)\n")
        f.write(f"- {len(dup_need_photo)} duplicate sources need their own photo "
                f"(their file shows an ALREADY-correct product, so the target was left untouched)\n")
        f.write(f"- {len(orphans)} 'orphan source' products still need a fresh photo "
                f"(their wrong file moved to its rightful product, none arrived for them)\n")
        f.write(f"- {len(unpinned)} still unpinned + {len(missing)} missing-file: need re-pull/sourcing\n\n")
        f.write("Mechanism: `products[target].image_path := source file path`. Files are not "
                "moved; reversible via fix_backup.json.\n\n")
        f.write("## Repoints (before -> after)\n\n")
        f.write("| tier | via | product (gets correct photo) | new image_path | (was) | source file from |\n")
        f.write("|---|---|---|---|---|---|\n")
        for p in plan:
            f.write(f"| {p['tier']} | {p['via']} | {p['tgt']} {p['tgt_name']} | "
                    f"{p['src_path']} | {p['old_tgt_path']} | {p['src']} ({p['src_name']}) |\n")
        if orphans:
            f.write("\n## Orphan sources — still need a correct photo\n\n")
            for s in orphans:
                f.write(f"- {s} {prods[s]['name']}\n")
    return out


def apply_plan(out):
    # save backup of ALL current image_paths for the touched targets
    with db() as c, c.cursor() as cur:
        tgts = [r["target_item"] for r in out["repoints"]]
        cur.execute("SELECT item_number, image_path FROM products WHERE item_number = ANY(%s)", [tgts])
        backup = {r[0]: r[1] for r in cur.fetchall()}
        json.dump(backup, open(BACKUP_JSON, "w", encoding="utf-8"), indent=1)
        n = 0
        for r in out["repoints"]:
            cur.execute("UPDATE products SET image_path=%s WHERE item_number=%s",
                        [r["new_image_path"], r["target_item"]])
            n += cur.rowcount
        c.commit()
    print(f"Applied {n} repoints. Backup of prior paths -> {BACKUP_JSON}")


def rollback():
    backup = json.load(open(BACKUP_JSON, encoding="utf-8"))
    with db() as c, c.cursor() as cur:
        n = 0
        for item, path in backup.items():
            cur.execute("UPDATE products SET image_path=%s WHERE item_number=%s", [path, item])
            n += cur.rowcount
        c.commit()
    print(f"Rolled back {n} image_path values from {BACKUP_JSON}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform the DB repoint (writes!)")
    ap.add_argument("--rollback", action="store_true", help="restore image_path from fix_backup.json")
    args = ap.parse_args()
    if args.rollback:
        return rollback()
    prods = load_products()
    plan, losers, orphans, dup_need_photo = build_plan(prods)
    out = write_plan(plan, losers, orphans, dup_need_photo, prods)
    print(f"Plan: {len(plan)} safe repoints, {len(losers)} conflict losers, "
          f"{len(dup_need_photo)} duplicate-sources, {len(orphans)} orphan sources, "
          f"{len(out['still_unpinned'])} unpinned, {len(out['missing_file'])} missing. -> {PLAN_MD}")
    if args.apply:
        apply_plan(out)
    else:
        print("DRY-RUN: no DB changes made. Review fix_plan.md, then re-run with --apply.")


if __name__ == "__main__":
    main()
