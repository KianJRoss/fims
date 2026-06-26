#!/usr/bin/env python3
"""Evidence ledger + verifier/applier for gradual in-store product enrichment.

The ledger is an append-only JSON list of candidate facts, each with full
provenance (source, url), a confidence score, and an identity-check note (how we
know the source page is THIS product). A verifier promotes candidates to
'verified' only when identity is established and the value is trustworthy; an
applier writes verified facts into *empty* DB fields only, with a reversible
backup. Ambiguous candidates stay 'pending'/'conflict' for human or AI review.

This is engine-agnostic: a scripted scraper, Codex, Claude, or a local model can
all append candidates in the same record shape, then `verify` + `apply` gate them.

Usage:
  python evidence_ledger.py verify          # recompute statuses, print summary
  python evidence_ledger.py report          # show what's applicable / pending / conflict
  python evidence_ledger.py apply           # write verified facts to empty DB fields (reversible)
  python evidence_ledger.py add --json '<record or [records]>'   # append candidate(s)
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

DSN = "postgresql://fims:fims@100.73.208.99:5432/fims"
AUDIT_DIR = Path(__file__).resolve().parent
LEDGER_PATH = AUDIT_DIR / "evidence_ledger.json"
APPLY_BACKUP_PATH = AUDIT_DIR / "evidence_ledger_apply_backup.json"
APPLY_LOG_PATH = AUDIT_DIR / "evidence_ledger_apply_log.jsonl"

# Fields the ledger is allowed to fill (never name/brand/item_number/image_path).
FILLABLE = {"shot_count", "duration_seconds", "effects", "packing", "category_id", "description"}
INT_FIELDS = {"shot_count", "duration_seconds", "category_id"}

# A single source at/above this confidence WITH an identity check auto-verifies.
TRUST_THRESHOLD = 0.9


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def save_ledger(records: list[dict[str, Any]]) -> None:
    LEDGER_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def norm_value(field: str, value: Any) -> str:
    if value is None:
        return ""
    if field in INT_FIELDS:
        try:
            return str(int(str(value).strip()))
        except (TypeError, ValueError):
            return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def add_records(new: list[dict[str, Any]]) -> int:
    """Append candidates, de-duplicating on (item_number, field, value, source)."""
    ledger = load_ledger()
    seen = {
        (r.get("item_number"), r.get("field"), norm_value(r.get("field", ""), r.get("value")), r.get("source"))
        for r in ledger
    }
    added = 0
    for rec in new:
        field = rec.get("field")
        if field not in FILLABLE:
            print(f"  skip non-fillable field: {field}")
            continue
        key = (rec.get("item_number"), field, norm_value(field, rec.get("value")), rec.get("source"))
        if key in seen:
            continue
        rec.setdefault("confidence", 0.5)
        rec.setdefault("identity_check", "")
        rec.setdefault("captured_at", now_iso())
        rec.setdefault("status", "pending")
        rec.setdefault("url", "")
        ledger.append(rec)
        seen.add(key)
        added += 1
    save_ledger(ledger)
    return added


def verify(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recompute per-candidate status.

    verified  : value agreed by >=2 distinct sources, OR one source with
                confidence>=TRUST_THRESHOLD AND a non-empty identity_check.
    conflict  : trusted/multi sources exist for the field but disagree on value.
    pending   : otherwise (needs more evidence or human/AI review).
    'applied' and 'rejected' records are left untouched.
    """
    # group by (item_number, field)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in ledger:
        if rec.get("status") in {"applied", "rejected"}:
            continue
        groups.setdefault((rec.get("item_number"), rec.get("field")), []).append(rec)

    for (_item, field), recs in groups.items():
        # tally distinct sources per normalized value
        by_value: dict[str, set[str]] = {}
        for r in recs:
            nv = norm_value(field, r.get("value"))
            if nv:
                by_value.setdefault(nv, set()).add(r.get("source", ""))
        trusted_values = {
            nv for nv, srcs in by_value.items()
            if len(srcs) >= 2
        }
        for r in recs:
            nv = norm_value(field, r.get("value"))
            agreed = len(by_value.get(nv, set())) >= 2
            single_trust = (
                float(r.get("confidence", 0)) >= TRUST_THRESHOLD
                and bool(str(r.get("identity_check", "")).strip())
            )
            if agreed or single_trust:
                # conflict if some *other* value is also trusted
                others_trusted = (trusted_values - {nv}) or {
                    onv for onv, srcs in by_value.items()
                    if onv != nv and any(
                        float(x.get("confidence", 0)) >= TRUST_THRESHOLD and x.get("identity_check")
                        for x in recs if norm_value(field, x.get("value")) == onv
                    )
                }
                r["status"] = "conflict" if others_trusted else "verified"
            else:
                r["status"] = "pending"
    save_ledger(ledger)
    return ledger


def fetch_db_state() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with psycopg.connect(DSN) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_number, id, shot_count, duration_seconds, effects, packing, "
                "category_id, description FROM products WHERE in_store=true AND item_number IS NOT NULL"
            )
            for row in cur.fetchall():
                out[row[0]] = {
                    "id": row[1], "shot_count": row[2], "duration_seconds": row[3],
                    "effects": row[4], "packing": row[5], "category_id": row[6],
                    "description": row[7],
                }
    return out


def db_field_empty(val: Any) -> bool:
    return val is None or (isinstance(val, str) and val.strip() == "")


def append_apply_log(rows: list[dict[str, Any]]) -> None:
    with APPLY_LOG_PATH.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def report(ledger: list[dict[str, Any]]) -> None:
    db = fetch_db_state()
    counts = {"verified": 0, "pending": 0, "conflict": 0, "applied": 0, "rejected": 0}
    applicable, blocked, needs_sentry = [], [], []
    for r in ledger:
        counts[r.get("status", "pending")] = counts.get(r.get("status", "pending"), 0) + 1
        if r.get("status") == "verified":
            cur = db.get(r.get("item_number"), {})
            if (
                r.get("item_number") in db
                and db_field_empty(cur.get(r.get("field")))
                and r.get("sentry_status") == "approved"
            ):
                applicable.append(r)
            elif r.get("item_number") in db and db_field_empty(cur.get(r.get("field"))):
                needs_sentry.append(r)
            elif r.get("item_number") in db:
                blocked.append(r)  # verified but DB already has a value
    print("ledger status counts:", counts)
    print(f"\nVERIFIED + AI-approved + DB-empty (would apply): {len(applicable)}")
    for r in applicable:
        print(f"  {r['item_number']:10} {r['field']:16} = {str(r['value'])[:46]!r}  conf={r['confidence']} [{r['source']}]")
    if needs_sentry:
        print(f"\nVERIFIED + DB-empty but waiting for AI sentry: {len(needs_sentry)}")
    if blocked:
        print(f"\nVERIFIED but DB already filled (skipped): {len(blocked)}")
    pend = [r for r in ledger if r.get("status") == "pending"]
    conf = [r for r in ledger if r.get("status") == "conflict"]
    if pend:
        print(f"\nPENDING (need more evidence / review): {len(pend)}")
        for r in pend[:20]:
            print(f"  {r['item_number']:10} {r['field']:16} = {str(r['value'])[:40]!r}  conf={r['confidence']} [{r['source']}]")
    if conf:
        print(f"\nCONFLICT (sources disagree): {len(conf)}")
        for r in conf:
            print(f"  {r['item_number']:10} {r['field']:16} = {str(r['value'])[:40]!r} [{r['source']}]")


def apply(ledger: list[dict[str, Any]]) -> None:
    db = fetch_db_state()
    backup, to_apply, log_rows = [], [], []
    for r in ledger:
        if r.get("status") != "verified":
            continue
        if r.get("sentry_status") != "approved":
            continue
        item = r.get("item_number")
        cur = db.get(item)
        if not cur or not db_field_empty(cur.get(r["field"])):
            continue
        to_apply.append(r)
        backup.append({"id": cur["id"], "item_number": item, "field": r["field"],
                       "old_value": cur.get(r["field"]), "applied_value": r["value"],
                       "source": r["source"]})
        log_rows.append({
            "applied_at": now_iso(),
            "id": str(cur["id"]),
            "item_number": item,
            "name": r.get("name", ""),
            "field": r["field"],
            "old_value": cur.get(r["field"]),
            "applied_value": r["value"],
            "source": r.get("source", ""),
            "url": r.get("url", ""),
            "confidence": r.get("confidence", 0),
            "identity_check": r.get("identity_check", ""),
        })
    if not to_apply:
        print("nothing verified+empty to apply.")
        return
    APPLY_BACKUP_PATH.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            for r in to_apply:
                value = r["value"]
                if r["field"] in INT_FIELDS:
                    value = int(str(value).strip())
                stmt = sql.SQL("UPDATE products SET {} = %s, updated_at=now() WHERE id=%s").format(
                    sql.Identifier(r["field"]))
                cur.execute(stmt, (value, db[r["item_number"]]["id"]))
                r["status"] = "applied"
        conn.commit()
    save_ledger(ledger)
    append_apply_log(log_rows)
    print(f"applied {len(to_apply)} verified facts (backup -> {APPLY_BACKUP_PATH.name}).")
    for row in log_rows:
        print(
            f"  APPLY {row['item_number']} {row['field']} = "
            f"{str(row['applied_value'])[:180]!r} [{row['source']}]"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    sub.add_parser("report")
    sub.add_parser("apply")
    a = sub.add_parser("add")
    a.add_argument("--json", required=True, help="a record dict or list of record dicts")
    args = ap.parse_args()

    if args.cmd == "add":
        payload = json.loads(args.json)
        recs = payload if isinstance(payload, list) else [payload]
        print(f"added {add_records(recs)} candidate(s).")
        return
    ledger = load_ledger()
    if args.cmd == "verify":
        verify(ledger)
        report(ledger)
    elif args.cmd == "report":
        report(ledger)
    elif args.cmd == "apply":
        apply(verify(ledger))


if __name__ == "__main__":
    main()
