# FIMS database mesh

Keep the product **catalog** data in sync across the Pi (hub), the laptop, and the
PC, with the Pi as the always-on source of truth. Conflicts resolve by
**last-write-wins** on each row's `updated_at`. Deletes propagate via tombstones.
New rows get node-partitioned IDs so inserts on different machines never collide.

Three layers, each its own tool:

| Layer | File | Does |
|------|------|------|
| 0 — backup/clone/hotswap | `dbmesh.sh` | dump a node, clone one node onto another, restore a dump (always snapshots the target first) |
| 1 — schema foundation | `mesh_phase1.sql` | adds `updated_at` + bump trigger, tombstone trigger, interleaved id sequences, and the `mesh_node` / `mesh_tombstone` tables |
| 2 — sync engine | `dbsync.py` | last-write-wins reconcile between hub and a spoke |

Nodes & id offsets (new-row ids end in the offset digit): **pi=0, laptop=1, pc=2**.
All nodes publish Postgres on `5432` over Tailscale
(pi `100.73.208.99`, laptop `100.123.23.84`, pc `100.99.89.118`).

## What syncs and what doesn't

**Syncs** (catalog/master data, LWW-safe): products, prices, price_history,
categories, brands, videos, barcodes, aliases, costing, packaging_units,
case_packs, price_types, suppliers, supplier_products, manufacturers, importers,
brand_importers, brand_manufacturers, deals, deal_conditions, deal_rewards,
store_documents.

**Does NOT sync** (still fully covered by layer-0 backup/clone): `alembic_version`,
`email_accounts`, the transactional ledger (`sales`, `sale_items`, `receipts`,
`inventory_events`), `audit_logs`, `import_jobs`/`import_rows`, `users`/`user_roles`.
LWW would corrupt a point-of-sale ledger, so those stay node-local.

## Bootstrapping a node — ORDER MATTERS

Phase 1 stamps `updated_at = now()`. If you apply it on two nodes at different
times *before* cloning, every row looks "newer" on the node that ran it last and
the first sync needlessly copies everything. Correct order:

1. **Hub first.** Apply Phase 1 to the Pi (once):
   ```bash
   cat scripts/db/mesh_phase1.sql | docker run --rm -i -e PGPASSWORD=fims postgres:17-alpine \
     psql -h 100.73.208.99 -p 5432 -U fims -d fims -v node_name=pi -v node_offset=0
   ```
2. **Clone hub → spoke** (copies the hub's real `updated_at` values):
   ```bash
   scripts/db/dbmesh.sh clone pi local      # or: clone pi pc  (run from any box)
   ```
3. **Apply Phase 1 to the spoke** (preserves the cloned timestamps; only adds
   triggers/sequences/offset):
   ```bash
   # laptop = offset 1, pc = offset 2
   cat scripts/db/mesh_phase1.sql | docker run --rm -i -e PGPASSWORD=fims postgres:17-alpine \
     psql -h 127.0.0.1 -p 5432 -U fims -d fims -v node_name=laptop -v node_offset=1
   ```
4. Verify: `python scripts/db/dbsync.py pi laptop` should report **all zeros**.

> Status: **all three nodes bootstrapped and converged** — pi (offset 0, hub),
> laptop (offset 1), pc (offset 2). On the PC only the `postgres` service runs
> (`docker compose up -d postgres` from `C:\FIMS`); the app stack is not started
> there (its Caddy would collide with net-os on 80/443). The PC's `postgres:17-alpine`
> image was side-loaded from the laptop (`docker save … | ssh pc docker load`)
> because the PC's Docker credential helper can't pull from the registry.

## Day-to-day sync

Always hub ↔ spoke (never spoke ↔ spoke):

```bash
python scripts/db/dbsync.py pi laptop          # dry-run: show the plan
python scripts/db/dbsync.py pi laptop --apply  # do it
python scripts/db/dbsync.py pi pc --apply      # when the PC is online
python scripts/db/dbsync.py pi laptop --tables products,product_prices  # subset
```

It's stateless and idempotent — safe to run repeatedly; a second run with no new
edits reports zero. **Before the first `--apply` after any manual DB surgery, take
snapshots** (`dbmesh.sh snapshot pi`, `... laptop`).

### Automated (live)

`scripts/db/mesh_cron.sh` runs on the Pi from cron **every 10 minutes**, syncing
each reachable spoke (laptop, pc) and skipping any that are powered off. It logs
to `scripts/db/mesh_sync.log` on the Pi (auto-trimmed to 2000 lines).

```bash
# already installed in the krioasns crontab on the Pi:
*/10 * * * * /home/krioasns/fims/scripts/db/mesh_cron.sh
# watch it:  ssh krioasns@100.73.208.99 'tail -f ~/fims/scripts/db/mesh_sync.log'
```

Note: the Pi's `auto_search_missing_videos` beat task keeps touching
`product_videos`, so most runs will show some video rows flowing pi→spokes. That's
correct (real changes propagating), just expected chatter.

## Backups / clone / hotswap (layer 0, no sync needed)

```bash
scripts/db/dbmesh.sh snapshot pi                 # backup -> backups/
scripts/db/dbmesh.sh clone pi local              # pull a full fresh copy here
scripts/db/dbmesh.sh restore <file.sql.gz> pi    # hotswap a copy onto a node
scripts/db/dbmesh.sh list
```
Every `clone`/`restore` auto-snapshots the target first and prints the rollback
command.

## Media (product images)

`dbsync.py` syncs DB rows, not the `media/product_images/*.webp` files. Mirror
those separately with `media_sync.sh` (tar-over-ssh; works where there's no
rsync, e.g. the laptop's git-bash). It transfers only the files the node is
missing, so repeat runs are cheap and never overwrite existing files:

```bash
scripts/db/media_sync.sh            # pull missing images from the Pi hub -> here
scripts/db/media_sync.sh --push     # push local-only images up to the Pi
scripts/db/media_sync.sh --dir documents   # sync media/documents instead
```

All three nodes mirrored to **1694 images** on 2026-06-25. On the PC (no
git-bash for the script) it was filled directly from the laptop via
`tar -C media/product_images -cf - . | ssh pc "tar -C C:\FIMS\media\product_images -xf -"`.

## Video Pi staging (`scripts/videopi/`)

The kiosk plays a product's demo video from the Video Pi's flat
`/media/pi/VIDEOS/videos/` dir, matched by `product_videos.video_filename`.
Two scripts stage and deploy those:

```bash
scripts/videopi/stage_videos.sh        # download confirmed videos (<=720p) flat as
                                       # {youtube_id}.mp4 into media/videopi_staging/
                                       # and set video_filename/duration/download_status
                                       # on the Pi hub DB. Idempotent + resumable.
scripts/videopi/deploy_to_videopi.sh   # when the Video Pi is plugged in: copy only the
                                       # files it's missing onto its USB, then reload the
                                       # idle playlist. --check to preview counts.
```

The staging dir (`media/videopi_staging/`) is gitignored — large and
regeneratable. `video_filename` is set to `{youtube_id}.mp4` (youtube_ids are
filesystem-safe; item numbers contain `/` and spaces). Setting it before the
files reach the Video Pi is safe: the idle-playlist builder only matches names
that actually exist on the device.

## Caveats

- **Clock skew** is the one thing LWW can't defend against. Keep NTP on across all
  three boxes or "newest" can be wrong.
- The bump trigger preserves an explicitly-supplied `updated_at` (that's how sync
  writes the source timestamp). App code must keep *not* setting `updated_at` by
  hand so normal edits get `now()`.
- Schema changes (Alembic migrations) are **not** mesh-managed. Run migrations on
  every node, then re-run Phase 1 (idempotent) so any new syncable tables get the
  foundation; add them to `SYNC_TABLES` in `dbsync.py` and the array in
  `mesh_phase1.sql`.
