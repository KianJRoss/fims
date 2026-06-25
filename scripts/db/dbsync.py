#!/usr/bin/env python3
"""FIMS DB mesh — Phase 2: last-write-wins bidirectional sync between two nodes.

Hub-and-spoke: always run as `dbsync.py <hub> <spoke>` (the hub is the Pi). The
laptop and PC each sync against the Pi; they never sync directly to each other,
so the always-on Pi is the single rendezvous point and changes fan out through it.

Reconciliation is STATELESS and idempotent: each run compares full manifests
(id -> updated_at) plus tombstones (id -> deleted_at) from both nodes and makes
both sides match the newest fact for every row. No watermarks to corrupt; running
it twice changes nothing the second time. Convergence relies on Phase 1 being
applied to both nodes (updated_at + bump trigger + tombstone trigger).

Requires: Phase 1 (scripts/db/mesh_phase1.sql) applied on both nodes.
Safety:   defaults to DRY-RUN. Pass --apply to actually write. Take a dbmesh.sh
          snapshot of both nodes before your first --apply.

Usage:
  python scripts/db/dbsync.py pi laptop                # dry-run, show plan
  python scripts/db/dbsync.py pi laptop --apply        # do it
  python scripts/db/dbsync.py pi laptop --tables products,product_prices
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

NODES = {
    "pi":     "100.73.208.99",
    "pc":     "100.99.89.118",
    "laptop": "100.123.23.84",
    "local":  "127.0.0.1",
}
DB_PORT = 5432
DB_NAME = "fims"
DB_USER = "fims"
DB_PASS = "fims"

# Same SET of tables as mesh_phase1.sql, but ordered PARENT -> CHILD by foreign
# keys. Upserts run in this order (a row's FK targets sync first); deletes run in
# reverse (children removed before parents). Transactional/log/auth tables are
# intentionally excluded (LWW is unsafe for a ledger).
SYNC_TABLES = [
    # independents / parents
    "price_types", "product_categories", "product_brands", "manufacturers",
    "importers", "suppliers", "packaging_units", "store_documents", "deals",
    # products depends on categories/brands
    "products",
    # everything below depends on products (and the parents above)
    "product_prices", "price_history", "product_videos", "product_barcodes",
    "product_aliases", "product_costing", "case_packs", "supplier_products",
    "brand_importers", "brand_manufacturers", "deal_conditions", "deal_rewards",
]

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def connect(node: str) -> psycopg.Connection:
    if node in NODES:
        host, port = NODES[node], DB_PORT
    elif ":" in node:                     # raw host:port (test/ad-hoc nodes)
        host, port = node.rsplit(":", 1)
    else:
        sys.exit(f"unknown node '{node}' (use: {', '.join(NODES)} or host:port)")
    dsn = (f"host={host} port={port} dbname={DB_NAME} user={DB_USER} "
           f"password={DB_PASS} connect_timeout=10")
    return psycopg.connect(dsn, autocommit=False, row_factory=dict_row)


def as_aware(ts) -> datetime:
    """Make timestamps comparable: assume UTC for naive (timestamp w/o tz cols)."""
    if ts is None:
        return EPOCH
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def columns(conn, table) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
            (table,),
        )
        return [r["column_name"] for r in cur.fetchall()]


def json_columns(conn, table) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s "
            "AND data_type IN ('json','jsonb')",
            (table,),
        )
        return {r["column_name"] for r in cur.fetchall()}


def manifest(conn, table) -> dict[str, datetime]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT id, updated_at FROM {table}")
        return {str(r["id"]): as_aware(r["updated_at"]) for r in cur.fetchall()}


def tombstones(conn, table) -> dict[str, datetime]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT row_pk, deleted_at FROM mesh_tombstone WHERE table_name=%s",
            (table,),
        )
        return {str(r["row_pk"]): as_aware(r["deleted_at"]) for r in cur.fetchall()}


def fetch_rows(conn, table, ids) -> dict[str, dict]:
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE id = ANY(%s)", (list(ids),))
        return {str(r["id"]): r for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# per-side effective state: (timestamp, alive?) where alive beats dead at a tie
# ---------------------------------------------------------------------------
@dataclass
class State:
    ts: datetime
    alive: bool

    def key(self):  # higher = wins; alive breaks ties over dead
        return (self.ts, 1 if self.alive else 0)


def side_state(man: dict, tomb: dict, rid: str) -> State | None:
    a = man.get(rid)
    d = tomb.get(rid)
    if a is None and d is None:
        return None
    if a is not None and (d is None or a >= d):
        return State(a, True)
    return State(d, False)


@dataclass
class Plan:
    upsert_to_hub: set = field(default_factory=set)    # row ids to write onto hub
    upsert_to_spoke: set = field(default_factory=set)
    delete_on_hub: dict = field(default_factory=dict)  # id -> deleted_at
    delete_on_spoke: dict = field(default_factory=dict)
    clear_tomb_hub: set = field(default_factory=set)
    clear_tomb_spoke: set = field(default_factory=set)


def reconcile(table, manH, tombH, manS, tombS) -> Plan:
    p = Plan()
    ids = set(manH) | set(manS) | set(tombH) | set(tombS)
    for rid in ids:
        sH = side_state(manH, tombH, rid)
        sS = side_state(manS, tombS, rid)
        kH = sH.key() if sH else (EPOCH, -1)
        kS = sS.key() if sS else (EPOCH, -1)
        # winner: strictly greater key wins; exact tie -> hub is source of truth
        winner = "hub" if kH >= kS else "spoke"
        win = sH if winner == "hub" else sS

        if win.alive:
            # both sides must hold the winner's alive row
            if winner == "hub":
                if not sS or not sS.alive or sS.ts < win.ts:
                    p.upsert_to_spoke.add(rid)
                if rid in tombS:
                    p.clear_tomb_spoke.add(rid)
                if rid in tombH:  # stale tombstone shadowing a live row
                    p.clear_tomb_hub.add(rid)
            else:
                if not sH or not sH.alive or sH.ts < win.ts:
                    p.upsert_to_hub.add(rid)
                if rid in tombH:
                    p.clear_tomb_hub.add(rid)
                if rid in tombS:
                    p.clear_tomb_spoke.add(rid)
        else:
            # winner says deleted: ensure both sides delete & carry the tombstone
            if sH and sH.alive and sH.ts < win.ts:
                p.delete_on_hub[rid] = win.ts
            elif rid not in tombH:
                p.delete_on_hub[rid] = win.ts  # tombstone-only propagation
            if sS and sS.alive and sS.ts < win.ts:
                p.delete_on_spoke[rid] = win.ts
            elif rid not in tombS:
                p.delete_on_spoke[rid] = win.ts
    return p


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------
def do_upsert(conn, table, rows: dict, cols, jcols):
    if not rows:
        return
    collist = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    setlist = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in cols if c != "id")
    sql = (f'INSERT INTO {table} ({collist}) VALUES ({placeholders}) '
           f'ON CONFLICT (id) DO UPDATE SET {setlist}')
    with conn.cursor() as cur:
        for r in rows.values():
            vals = [Json(r[c]) if c in jcols and r[c] is not None else r[c] for c in cols]
            cur.execute(sql, vals)


def do_delete(conn, table, deletes: dict, me: str):
    if not deletes:
        return
    with conn.cursor() as cur:
        for rid, ts in deletes.items():
            cur.execute(f"DELETE FROM {table} WHERE id=%s", (rid,))
            # overwrite the trigger-written tombstone with the propagated time
            cur.execute(
                "INSERT INTO mesh_tombstone (table_name,row_pk,deleted_at,node_name) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (table_name,row_pk) "
                "DO UPDATE SET deleted_at=EXCLUDED.deleted_at, node_name=EXCLUDED.node_name",
                (table, rid, ts, me),
            )


def clear_tombs(conn, table, ids):
    if not ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM mesh_tombstone WHERE table_name=%s AND row_pk = ANY(%s)",
            (table, list(ids)),
        )


def main():
    ap = argparse.ArgumentParser(description="FIMS LWW mesh sync (hub <-> spoke)")
    ap.add_argument("hub")
    ap.add_argument("spoke")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--tables", help="comma-separated subset of tables")
    args = ap.parse_args()

    tables = args.tables.split(",") if args.tables else SYNC_TABLES
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"== FIMS mesh sync {args.hub} <-> {args.spoke}  [{mode}] ==")

    ch = connect(args.hub)
    cs = connect(args.spoke)
    try:
        hub_name = ch.execute("SELECT node_name FROM mesh_node WHERE id=1").fetchone()["node_name"]
        spoke_name = cs.execute("SELECT node_name FROM mesh_node WHERE id=1").fetchone()["node_name"]
        ch.rollback(); cs.rollback()

        grand = {"->spoke": 0, "->hub": 0, "del spoke": 0, "del hub": 0}
        plans: dict[str, Plan] = {}
        for t in tables:
            p = reconcile(t, manifest(ch, t), tombstones(ch, t),
                             manifest(cs, t), tombstones(cs, t))
            plans[t] = p
            n = (len(p.upsert_to_spoke), len(p.upsert_to_hub),
                 len(p.delete_on_spoke), len(p.delete_on_hub))
            if any(n):
                print(f"  {t:22s} ->spoke {n[0]:4d} | ->hub {n[1]:4d} | "
                      f"del spoke {n[2]:3d} | del hub {n[3]:3d}")
            grand["->spoke"] += n[0]; grand["->hub"] += n[1]
            grand["del spoke"] += n[2]; grand["del hub"] += n[3]

        if args.apply:
            # Pass 1: upserts parent -> child (a row's FK targets land first)
            for t in tables:
                p = plans[t]
                if not (p.upsert_to_spoke or p.upsert_to_hub
                        or p.clear_tomb_hub or p.clear_tomb_spoke):
                    continue
                cols = columns(ch, t)
                jcols = json_columns(ch, t)
                do_upsert(cs, t, fetch_rows(ch, t, p.upsert_to_spoke), cols, jcols)
                do_upsert(ch, t, fetch_rows(cs, t, p.upsert_to_hub), cols, jcols)
                clear_tombs(ch, t, p.clear_tomb_hub)
                clear_tombs(cs, t, p.clear_tomb_spoke)
                ch.commit(); cs.commit()
            # Pass 2: deletes child -> parent (remove children before parents)
            for t in reversed(tables):
                p = plans[t]
                if not (p.delete_on_hub or p.delete_on_spoke):
                    continue
                do_delete(ch, t, p.delete_on_hub, hub_name)
                do_delete(cs, t, p.delete_on_spoke, spoke_name)
                ch.commit(); cs.commit()

        print(f"-- totals: {grand} --")
        if not args.apply and any(grand.values()):
            print("   (dry-run: re-run with --apply to write)")
    except Exception:
        ch.rollback(); cs.rollback()
        raise
    finally:
        ch.close(); cs.close()


if __name__ == "__main__":
    main()
