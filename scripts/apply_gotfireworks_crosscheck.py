from __future__ import annotations

import json
import os
import re
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "scripts" / "catalogs" / "noname" / "2026" / "gotfireworks_crosscheck.json"


def load_crosscheck() -> dict[str, dict]:
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"Cross-check JSON not found: {JSON_PATH}")
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def normalize_item_code(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def existing_note_contains(notes: str | None, marker: str) -> bool:
    return bool(notes) and marker in notes


def main() -> None:
    crosscheck = load_crosscheck()
    if not crosscheck:
        print("Cross-check JSON is empty; nothing to apply.")
        return

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, file_name
                FROM import_jobs
                WHERE document_type = 'CATALOG'
                  AND file_name ILIKE '%NoName2026.pdf%'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            )
            job_row = cur.fetchone()
            if not job_row:
                print("No matching ImportJob found for NoName2026.pdf.")
                return

            job_id = job_row[0]
            cur.execute(
                """
                SELECT id, raw_data, notes
                FROM import_rows
                WHERE job_id = %s
                """,
                (job_id,),
            )
            rows = cur.fetchall()

        rows_by_code: dict[str, list[tuple[int, dict, str | None]]] = {}
        for row_id, raw_data, notes in rows:
            if isinstance(raw_data, dict):
                raw_dict = raw_data
            elif isinstance(raw_data, str):
                raw_dict = json.loads(raw_data)
            else:
                raw_dict = dict(raw_data)
            item_code = normalize_item_code(raw_dict.get("item_code"))
            if item_code:
                rows_by_code.setdefault(item_code, []).append((row_id, raw_dict, notes))

        enriched_rows = 0
        unmatched_json_keys: list[str] = []
        updates: list[tuple[int, dict, str | None]] = []

        for item_code, payload in crosscheck.items():
            db_rows = rows_by_code.get(normalize_item_code(item_code))
            if not db_rows:
                unmatched_json_keys.append(item_code)
                continue

            web_data = payload.get("web_data") or {}
            duration_seconds = payload.get("duration_seconds")
            stock_status = payload.get("stock_status")
            mismatches = payload.get("mismatches") or []

            for row_id, raw_data, notes in db_rows:
                new_raw = dict(raw_data)
                changed = False
                if duration_seconds is not None and new_raw.get("duration_seconds") is None:
                    new_raw["duration_seconds"] = duration_seconds
                    changed = True
                if stock_status is not None and new_raw.get("stock_status") is None:
                    new_raw["stock_status"] = stock_status
                    changed = True

                new_notes = notes
                if mismatches:
                    note_marker = f"GotFireworks cross-check for {normalize_item_code(item_code)}"
                    mismatch_text = "; ".join(str(item) for item in mismatches)
                    note_body = f"{note_marker}: {mismatch_text}"
                    if not existing_note_contains(notes, note_body):
                        new_notes = (notes.strip() + "\n\n" if notes and notes.strip() else "") + note_body
                        changed = True

                if changed:
                    updates.append((row_id, new_raw, new_notes))
                    enriched_rows += 1

        with conn.cursor() as cur:
            for row_id, new_raw, new_notes in updates:
                cur.execute(
                    """
                    UPDATE import_rows
                    SET raw_data = %s,
                        notes = %s
                    WHERE id = %s
                    """,
                    (Jsonb(new_raw), new_notes, row_id),
                )
        conn.commit()

    print(f"ImportJob id: {job_id}")
    print(f"Rows enriched: {enriched_rows}")
    print(f"JSON entries without DB match: {len(unmatched_json_keys)}")
    if unmatched_json_keys:
        print("Unmatched item_codes: " + ", ".join(sorted(unmatched_json_keys)))


if __name__ == "__main__":
    main()
