#!/usr/bin/env python3
"""Set up the "3 for $45" cake sale: member prices + the bundle deal.

Members = every NO NAME product linked (via product_videos.youtube_id) to the
in-store "200g cakes" playlist (scripts/videopi/playlist_200g_fresh.txt), plus
anything added with --add. For each member: set the individual RETAIL price
(default $17.95, logged to price_history). Then create/refresh one deal named
"3 for $45 Cakes": PRODUCT_ANY condition rows (one per member — the deal
engine pools them) and a BUNDLE_PRICE reward (quantity=3, flat_off=45.00).

Re-runnable; adding a cake later is one command:
    python3 scripts/audit/setup_3for45.py --apply                  # seed list
    python3 scripts/audit/setup_3for45.py --apply --add SWC2196    # add member
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DSN = "postgresql://fims:fims@localhost:5432/fims"
PLAYLIST = Path(__file__).resolve().parents[1] / "videopi" / "playlist_200g_fresh.txt"
SEED_BRAND = "NO NAME"


def playlist_youtube_ids() -> list[str]:
    ids = []
    # only the ASCII youtube ids matter; titles may carry cp1252 punctuation
    for line in PLAYLIST.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            ids.append(line.split("|")[0].strip())
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--price", type=float, default=17.95)
    parser.add_argument("--bundle-qty", type=int, default=3)
    parser.add_argument("--bundle-price", type=float, default=45.00)
    parser.add_argument("--deal-name", default="3 for $45 Cakes")
    parser.add_argument("--add", action="append", default=[],
                        help="extra member by item_number or exact product name (repeatable)")
    parser.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    args = parser.parse_args()

    conn = psycopg.connect(DSN)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    yids = playlist_youtube_ids()
    members: dict[str, str] = {}  # product_id -> name
    rows = conn.execute(
        """
        SELECT DISTINCT p.id, p.name FROM products p
        JOIN product_videos pv ON pv.product_id = p.id
        JOIN product_brands pb ON pb.id = p.brand_id
        WHERE pv.youtube_id = ANY(%s) AND pb.name = %s AND p.is_active
        """,
        (yids, SEED_BRAND),
    ).fetchall()
    for pid, name in rows:
        members[str(pid)] = name

    for extra in args.add:
        row = conn.execute(
            "SELECT id, name FROM products WHERE item_number = %s OR name = %s LIMIT 1",
            (extra, extra),
        ).fetchone()
        if row is None:
            print(f"!! --add not found, skipping: {extra}")
            continue
        members[str(row[0])] = row[1]

    print(f"members ({len(members)}):")
    for pid, name in sorted(members.items(), key=lambda kv: kv[1]):
        print(f"  {name}")

    retail_type_id = conn.execute(
        "SELECT id FROM price_types WHERE upper(code) = 'RETAIL'"
    ).fetchone()[0]

    for pid, name in members.items():
        current = conn.execute(
            """
            SELECT id, amount FROM product_prices
            WHERE product_id = %s AND price_type_id = %s
            ORDER BY effective_from DESC NULLS LAST, id DESC LIMIT 1
            """,
            (pid, retail_type_id),
        ).fetchone()
        old = float(current[1]) if current else None
        if old == args.price and current is not None:
            continue
        print(f"  price: {name}: {old} -> {args.price}")
        if not args.apply:
            continue
        conn.execute(
            """
            INSERT INTO price_history (product_id, price_type_id, old_amount, new_amount, reason, changed_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (pid, retail_type_id, old, args.price, "3 for $45 sale setup", now),
        )
        if current:
            conn.execute(
                "UPDATE product_prices SET amount=%s, is_active=TRUE, effective_from=%s WHERE id=%s",
                (args.price, now, current[0]),
            )
        else:
            conn.execute(
                """
                INSERT INTO product_prices (product_id, price_type_id, amount, is_active, effective_from)
                VALUES (%s, %s, %s, TRUE, %s)
                """,
                (pid, retail_type_id, args.price, now),
            )

    deal_row = conn.execute("SELECT id FROM deals WHERE name = %s", (args.deal_name,)).fetchone()
    if args.apply:
        if deal_row is None:
            deal_id = conn.execute(
                """
                INSERT INTO deals (name, deal_type, priority, is_active, is_stackable, notes)
                VALUES (%s, 'BUNDLE', 10, TRUE, FALSE, %s) RETURNING id
                """,
                (args.deal_name, f"Any {args.bundle_qty} member cakes for ${args.bundle_price:.2f}"),
            ).fetchone()[0]
        else:
            deal_id = deal_row[0]

        # reconcile PRODUCT_ANY membership
        existing = {
            str(r[0])
            for r in conn.execute(
                "SELECT product_id FROM deal_conditions WHERE deal_id=%s AND condition_type='PRODUCT_ANY'",
                (deal_id,),
            )
        }
        for pid in members:
            if pid not in existing:
                conn.execute(
                    "INSERT INTO deal_conditions (deal_id, condition_type, product_id) VALUES (%s,'PRODUCT_ANY',%s)",
                    (deal_id, pid),
                )
        stale = existing - set(members)
        if stale:
            conn.execute(
                "DELETE FROM deal_conditions WHERE deal_id=%s AND condition_type='PRODUCT_ANY' AND product_id = ANY(%s)",
                (deal_id, list(stale)),
            )

        reward = conn.execute(
            "SELECT id FROM deal_rewards WHERE deal_id=%s AND reward_type='BUNDLE_PRICE'", (deal_id,)
        ).fetchone()
        if reward:
            conn.execute(
                "UPDATE deal_rewards SET quantity=%s, flat_off=%s WHERE id=%s",
                (args.bundle_qty, args.bundle_price, reward[0]),
            )
        else:
            conn.execute(
                "INSERT INTO deal_rewards (deal_id, reward_type, quantity, flat_off) VALUES (%s,'BUNDLE_PRICE',%s,%s)",
                (deal_id, args.bundle_qty, args.bundle_price),
            )
        conn.commit()
        print(f"applied: deal '{args.deal_name}' (id {deal_id}) with {len(members)} members, "
              f"{args.bundle_qty} for ${args.bundle_price:.2f}, individual ${args.price:.2f}")
    else:
        print(f"dry-run: would set {len(members)} members to ${args.price:.2f} and "
              f"create/refresh deal '{args.deal_name}' ({args.bundle_qty} for ${args.bundle_price:.2f})")
    conn.close()


if __name__ == "__main__":
    main()
