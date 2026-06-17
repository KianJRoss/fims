"""
Verify (and where safely possible, fix) the relationship between World Class
item_number and its barcode.

Observed convention (from inspecting existing data): World Class item_numbers are
7 digits, always starting with "10" (e.g. 1024433). The barcode embeds the trailing
5 digits of the item_number (everything after the leading "10") immediately before
the barcode's final check digit:

    barcode = <prefix> + item_number[2:] (5 digits) + <check digit, 1 digit>

e.g. item_number 1024433 -> suffix "24433" -> barcode ...805253-24433-0 = 805253244330

This script checks every World Class product+barcode pair against that rule and
reports matches/mismatches without changing anything (read-only by default).
Pass --fix to attempt safe repairs:
  - Restores a dropped leading zero on a truncated (11-digit instead of 12-digit)
    barcode when item_number[2] == "0" (classic "leading zero stripped by Excel/
    import" bug) and the recovered 12-digit value would match the rule.
  - Anything else is left untouched and printed for manual review (e.g. true
    duplicate barcodes shared by two different item_numbers) -- not safe to guess.

Run:
    python scripts/verify_worldclass_barcodes.py            # report only
    python scripts/verify_worldclass_barcodes.py --fix       # report + apply safe fixes
"""
from __future__ import annotations

import os
import sys

import psycopg

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")


def expected_suffix(item_number: str) -> str | None:
    if len(item_number) != 7 or not item_number.startswith("10") or not item_number.isdigit():
        return None
    return item_number[2:]  # 5 digits


def check_match(barcode: str, suffix: str) -> bool:
    # suffix should sit immediately before the final check digit
    return len(barcode) >= 6 and barcode[-6:-1] == suffix


def main() -> None:
    do_fix = "--fix" in sys.argv

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.item_number, pbc.id, pbc.barcode
                FROM products p
                JOIN product_brands pb ON pb.id = p.brand_id
                JOIN product_barcodes pbc ON pbc.product_id = p.id
                WHERE pb.name = 'World Class'
                ORDER BY p.item_number
                """
            )
            rows = cur.fetchall()

        print(f"Checking {len(rows)} World Class product/barcode pairs...\n")

        matched = 0
        not_7digit = []
        mismatched = []
        fixed = []

        for product_id, item_number, barcode_id, barcode in rows:
            suffix = expected_suffix(item_number or "")
            if suffix is None:
                not_7digit.append((item_number, barcode))
                continue

            if check_match(barcode, suffix):
                matched += 1
                continue

            # Try the "dropped leading zero" repair: only when the item_number's
            # first suffix digit is '0' (so a naive int() cast upstream would have
            # silently dropped it), the barcode is exactly 11 digits, and inserting
            # a '0' right after the first 6 characters reproduces the expected rule.
            if len(barcode) == 11 and suffix[0] == "0":
                candidate = barcode[:6] + "0" + barcode[6:]
                if check_match(candidate, suffix):
                    if do_fix:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE product_barcodes SET barcode = %s WHERE id = %s",
                                (candidate, barcode_id),
                            )
                        conn.commit()
                    fixed.append((item_number, barcode, candidate))
                    continue

            mismatched.append((item_number, barcode, suffix))

        print(f"Matched (already correct): {matched}")
        print(f"Skipped (item_number not 7-digit '10xxxxx' pattern): {len(not_7digit)}")
        for item_number, barcode in not_7digit:
            print(f"  {item_number} -> barcode {barcode}")

        verb = "Fixed" if do_fix else "Fixable (leading zero recovery) -- rerun with --fix to apply"
        print(f"\n{verb}: {len(fixed)}")
        for item_number, old, new in fixed:
            print(f"  {item_number}: {old} -> {new}")

        print(f"\nMismatched, needs manual review (not auto-fixed): {len(mismatched)}")
        for item_number, barcode, suffix in mismatched:
            print(f"  {item_number}: barcode={barcode} expected_suffix={suffix} (barcode[-6:-1]={barcode[-6:-1] if len(barcode) >= 6 else '?'})")

        # check for duplicate barcodes shared across different item_numbers
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pbc.barcode, array_agg(DISTINCT p.item_number)
                FROM product_barcodes pbc
                JOIN products p ON p.id = pbc.product_id
                JOIN product_brands pb ON pb.id = p.brand_id
                WHERE pb.name = 'World Class'
                GROUP BY pbc.barcode
                HAVING COUNT(DISTINCT p.item_number) > 1
                """
            )
            dupes = cur.fetchall()
        if dupes:
            print(f"\nDuplicate barcodes shared by multiple item_numbers: {len(dupes)}")
            for barcode, item_numbers in dupes:
                print(f"  {barcode}: {item_numbers}")


if __name__ == "__main__":
    main()
