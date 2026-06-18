# FIMS — Fireworks Information Management System

## What This Is

FIMS is not a POS system. It is a **product-centric information backbone** for a retail fireworks store.

The core principle: every firework has one authoritative internal product record. Sales, videos, pricing, invoices, receipts, and inventory all reference that record — they do not own it.

The product database is the backbone. Everything else consumes it.

---

## Running the System

```bash
# Start everything
docker compose up -d

# Restart after code changes (hot-reload is on, but container restart clears errors)
docker compose restart api

# Run Alembic migrations
docker compose exec api alembic upgrade head

# Access from any device on the local network
http://<PC-IP-ADDRESS>        # find with ipconfig
http://localhost              # from the PC itself
```

### Port assignments (internal Docker network)
| Service  | Port |
|----------|------|
| Caddy (entry) | 80 |
| FastAPI  | 8000 |
| Vite dev | 3000 |
| PostgreSQL | 5432 |
| Redis    | 6379 |

### Key environment notes
- `VITE_API_URL=/api` — relative, works from any device on the LAN
- `MEDIA_ROOT=/app/media` inside containers, maps to `./media` on host
- DB: `postgresql://fims:fims@postgres:5432/fims`

---

## Architecture

```
Caddy (port 80)
├── /api/* → FastAPI (port 8000)
├── /ws/*  → FastAPI WebSocket
├── /media/* → static file server
└── /* → Vite dev server (port 3000)

FastAPI
├── SQLAlchemy 2 + PostgreSQL 17
├── Alembic migrations
└── Celery workers (Redis broker)
    ├── video_search — yt-dlp YouTube search
    ├── video_download — yt-dlp download
    ├── catalog_import — PDF/OCR import
    └── issuu_import — Issuu text layer scrape

React + Vite + TypeScript
├── TanStack Query (useQuery, useMutation, useInfiniteQuery)
├── Tailwind CSS (dark theme, orange accents)
├── axios via /api relative base
└── lucide-react icons
```

---

## Project Structure

```
fims/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # FastAPI route handlers
│   │   ├── models/             # SQLAlchemy models
│   │   ├── worker/tasks/       # Celery background tasks
│   │   └── db/session.py       # DB connection + Base
│   └── alembic/versions/       # Migration chain
├── frontend/
│   └── src/
│       ├── pages/              # One file per route
│       └── api/client.ts       # axios instance
├── scripts/
│   ├── importers/jakes.py      # Jake's catalog importer
│   ├── scrape_issuu_text.py    # Issuu text layer scraper
│   └── catalogs/               # Scraped catalog data (gitignored pages/)
├── proxy/Caddyfile             # Reverse proxy config
└── docker-compose.yml
```

---

## Data Model (Key Tables)

| Table | Purpose |
|-------|---------|
| `products` | Master product record. UUID primary key. |
| `product_barcodes` | Many barcodes per product. Duplicates allowed. |
| `product_brands` | Brand hierarchy (World Class, No Name, etc.) |
| `product_categories` | Category hierarchy from catalog TOC |
| `product_videos` | YouTube search results + downloaded files |
| `price_types` | RETAIL, SALE, WHOLE, COST, EMPLOYEE, CLEARANCE |
| `product_prices` | Active price per product+type |
| `price_history` | Append-only price change log |
| `deals` | Deal engine: BXGY, BUNDLE, PERCENT_OFF, FLAT_AMOUNT |
| `deal_conditions` | What triggers a deal |
| `deal_rewards` | What the customer gets |
| `sales` | Completed transactions |
| `sale_items` | Line items per sale |
| `store_documents` | Uploaded files (invoices, catalogs, price lists) |
| `import_jobs` | PDF/Issuu import job tracking |
| `import_rows` | Extracted rows awaiting human review |

### Product identity rules (from original design)
- **Internal Product ID (UUID) is the true identifier.** Never trust barcodes as unique.
- One product → many barcodes. One barcode → many products. This is expected and handled.
- When a barcode matches multiple products, the employee selects the correct one.
- Alternate names / supplier-specific names should be stored (ProductAliases — not yet built).

---

## Current Implementation Status

_Last reconciled against actual code/DB on 2026-06-17. The Pi (`KianPotPi`) is the real running deployment — see Hardware Reference below — and had drifted far ahead of this list for months; verify against code before trusting "not yet built" claims again._

### Built ✓
- Product catalog: 543 World Class + 140 No Name + Pyro Box/Sunwing/Suns Fireworks/Supreme/Miracle/etc — ~870 products across 17 brands (live counts via `product_brands`)
- Multi-brand checkbox filter, catalog sort by page number
- Video review queue: YouTube search, confirm, download via yt-dlp
- Sales screen: barcode scan, product search, cart, deal application, complete sale, **$0-price guard** (frontend disables checkout; backend now also rejects mismatched/unknown prices server-side)
- Pricing: multi-type price management with history; price types seeded via migration
- Deal engine: BXGY, BUNDLE, PERCENT_OFF, FLAT_AMOUNT, CHEAPEST_FREE
- Documents tab: file storage (upload/download/delete) + catalog import
- Issuu scraper (Jake's) + PDF/OCR import pipeline (No Name) → review rows → commit
- Mobile network access + **mobile-responsive nav** (hamburger drawer, bottom-safe header)
- Barcode print page
- **Reports page**: daily totals, transaction list + expandable detail, cash/card breakdown, date picker
- **Transaction history / receipt lookup**: via Reports + dedicated Receipt/Receipts pages, QR-token lookup exposed publicly through Tailscale Funnel (`/receipt*`)
- **Hold/park transaction**: park cart, recall or delete from parked list
- **Supplier management**: CRUD API + reconciliation UI
- **Product aliases**: alternate-name table, matched on import
- **Email inbox scraping**: IMAP sync every 15 min (Celery beat), Settings page for account config, encrypted credential storage
- **Dejavoo Z8 receipt printing**: printer service wired to sale/receipt endpoints (env vars now correctly passed to the `api` container)
- **Customer-facing shop + QR flow**: public `/shop` and `/receipt` routes via Tailscale Funnel (Caddyfile), product images
- **Pi kiosk / idle-loop video**: barcode scan drives video playback on the dedicated Video Pi, filterable idle-loop playlist
- **Off-network access**: solved via Tailscale Funnel (`kianpotpi.taile4f97e.ts.net`), not Cloudflare Tunnel

### In Progress / Partial
- Product names — some products may still need name cleanup (OCR/vision-assisted naming scripts exist: `apply_names_vision.py`, `fix_names_from_images.py`)

### Not Yet Built
- Inventory — cases on hand, receiving workflow
- Purchase order workflow
- Email receipt to customer (SMTP send at checkout) — inbound email scraping is built, outbound is not
- "Build your show" tool
- Year-over-year sales comparison (needs a full year of data first)

### Explicitly Out of Scope
- User authentication / manager vs. employee roles — single small pop-up store, not worth the complexity
- Shift open/close / cash drawer reconciliation — same reason

---

## Suppliers

Live product counts by brand (`product_brands`, checked 2026-06-17 — re-run the query below rather than trusting this table long-term):
`World Class 543, NO NAME 140, SUNS FIREWORKS 75, PYRO BOX 40, SUNWING 36, SUPREME 30, Miracle 22, TOP GUN 9, Boomer 6, ASIA PYRO 3, BLACK CAT 2, FORWARD 2, OTHER 2, BROTHERS 1, NITRO 1, GENERIC 1, THUNDERBOMB 1`

| Supplier | Brand(s) | Notes |
|----------|----------|-------|
| Jake's Fireworks | World Class | 2026 catalog imported via Issuu |
| RM Enterprises | No Name, others | Imported via PDF/OCR pipeline (`scripts/importers/noname.py`) + gotfireworks.com crosscheck/scrape scripts in `scripts/` |
| Black Cat | Black Cat | Only 2 products in DB — catalog likely still incomplete |
| Pyro Box | Pyro Box | 40 products in DB |
| Sunwing | Sunwing | 36 products in DB |

---

## Alembic Migration Chain

This list has gone stale every time it's been hand-maintained — 18 revision files exist as of 2026-06-17, far more than were ever drawn here. Don't hand-update this; instead run:

```bash
docker compose exec api alembic history
docker compose exec api alembic current
```

Current head as of 2026-06-17: `69888783a2f3` (merge point resolving a brief divergence between a `needs_data_review` migration and an `email accounts` migration — confirmed single head, no orphans).

---

## Catalog Import Notes

### Jake's 2026 (World Class)
- CDN ID: `260506140512-f077399ecfd86afa6eee7e4087f1bd81`
- Pages: 177. Products: 548 unique SKUs.
- Text layer URL: `https://svg.issuu.com/{cdn_id}/page_{N}.html`
- Page image URL: `https://image.isu.pub/{cdn_id}/jpg/page_{N}.jpg`
- Product names are **graphical** (not in text layer). Names extracted via OCR of page images.
- Categories assigned from TOC page ranges (page 10 of catalog).
- Run importer: `python scripts/importers/jakes.py 2026`

### No Name 2026
- PDF: `scripts/catalogs/noname/2026/NoName2026.pdf` (4MB)
- No Issuu CDN found yet. Will need PDF OCR import pipeline.
- Run when ready: upload via Documents → Catalog Import tab

---

## Development Rules

### Always use Codex for coding tasks
Delegate implementation work to Codex via Agent tool with `subagent_type: "codex:codex-rescue"`. Claude handles orchestration, planning, and review only.

### Backend patterns
- Use SQLAlchemy `Session` from `get_db` in API endpoints (never raw psycopg in endpoints)
- Use psycopg3 direct connections in Celery tasks (never SQLAlchemy sessions in tasks)
- All new endpoints follow the pattern in `products.py` — `select()`, `joinedload()`, `db.execute()`

### Frontend patterns
- All API calls via `axios` with base URL from `import.meta.env.VITE_API_URL ?? "/api"`
- TanStack Query for all server state — no raw fetch/useEffect for data
- Tailwind only — no custom CSS except `index.css` utility additions
- Dark theme: `bg-gray-950`, cards `bg-gray-900`, borders `border-gray-800`, accent `orange-500`

---

## 🔥 Ideas & Roadmap (Ranked by Priority)

These are actively desired features. Build these next.

### Priority 0 — Data Collection & Entry System Audit (HIGHEST PRIORITY, added 2026-06-18)

The whole information collection and entry pipeline needs to be checked end-to-end — both
completeness (missing data) and correctness (wrong data), not just for one brand.

**1. No Name/RM category backfill** *(cheap — data we already have)*
- Every RM Enterprises brand (No Name, Sunwing, Pyro Box, Suns Fireworks, Supreme, Miracle,
  Top Gun — 315 products) currently has **zero category assigned**. gotfireworks.com's
  "More Information" table has no category field, and the original `NoName2026.pdf` OCR
  parse (`noname_parsed_preview.json`) also left `category: None` on every single row —
  category-header detection in that parser never worked.
- Fix: re-parse `NoName2026.pdf` to detect the printed section headers (FOUNTAINS, SHELLS,
  etc.) that group each page, and backfill `category_id` from that. No new data sourcing
  needed, just a parser fix.

**2. Prior-year World Class catalogs** *(recovers legacy/discontinued items)*
- ~365 of 549 World Class products aren't listed anywhere on the current live
  worldclassfireworks.com site (confirmed via its own search returning zero results for
  sampled item numbers) — meaning no name/category/photo can be recovered for them from
  the current site, even though they may still be physically in the store.
- Publisher `cloudsent` on Issuu hosts World Class catalogs for **2021, 2023, 2024, 2025**
  in addition to the already-imported 2026 one (see `docs/DATA_SOURCES.md` for exact CDN
  IDs/URLs). Pull these to fill in older items still in inventory.

**3. Accuracy audit, not just completeness** *(the data we "have" may be wrong)*
- Confirmed real example: ~247 of 892 product images were corrupted (zero-byte) or were
  mis-cropped composites grabbing the wrong product's box from the original catalog-page
  OCR extraction — already partially fixed by re-pulling from gotfireworks.com/
  worldclassfireworks.com directly (see `scripts/download_gotfireworks_images.py` /
  `download_worldclass_images.py`), but the underlying OCR extraction
  (`extract_catalog_images.py`, `apply_names_vision.py`) that produced the bad data in the
  first place has not been reviewed or fixed, and may have caused other wrong-but-not-obviously-
  broken data (names, categories, shot counts) too — not just images.
- Needs a systematic pass: don't just check whether a field is populated, check whether
  it's actually correct, brand by brand.

### Priority 1 — Must Have Before Heavy Use

**Email inbox scraping** *(High — unlocks all missing documents)*
- Connect to boss's email via IMAP (or Gmail OAuth)
- Scan inbox for emails from boss containing fireworks keywords
- Download PDF/Excel/CSV attachments automatically
- Save to Documents system, categorize by type (Invoice, Price List, Sales Order, Catalog)
- Run on a schedule (e.g., every 15 minutes)
- UI: Settings page with email account config, last-sync time, found-documents log
- This is the primary way invoices, price lists, and sales orders will enter the system

**Dejavoo Z8 receipt printing** *(High — needed for every sale)*
- Z8 has a built-in thermal printer accessible via TCP/IP or USB ESC/POS
- Customer copy: store name, date/time, itemized products, qty, unit price, discounts, subtotal, total, payment method + last 4
- Merchant copy (card payments only): same + signature line + "I agree to pay above total"
- No signature line on cash payments
- Trigger automatically after sale completes

**Reports page** *(High — currently a stub)*
- Daily sales totals (transactions, revenue, discounts, avg sale)
- Transaction list for the day (expandable to see line items)
- Top products by revenue and quantity
- By category and by payment method breakdowns
- Date picker for historical view

**$0 price guard** *(High — prevents free sales)*
- If any cart item has unit_price === 0, show amber warning badge
- Disable checkout button with explanation

**Seed price types** *(High — pricing is broken without it)*
- Migration to insert RETAIL, SALE, WHOLESALE, COST, EMPLOYEE, CLEARANCE into price_types

### Priority 2 — Operational Improvements

**Mobile-responsive nav** *(Medium)*
- Bottom tab bar on mobile (Sales, Products, Videos, Documents, Pricing, Reports)
- Hamburger drawer for full nav on small screens

**Transaction history / receipt lookup** *(Medium)*
- `GET /sales/` paginated list
- `GET /sales/{id}` full detail with line items
- Accessible from Reports page or a dedicated Receipts section

**Hold / park a transaction** *(Medium)*
- Park current cart, start a new one, recall parked cart
- Common when customer walks away to get cash

**Inventory — cases on hand** *(Medium)*
- Simple integer field on products: `cases_on_hand`
- Increment on receive, decrement on sale (by packing ratio)
- Low stock alert in Reports

### Priority 3 — Customer Experience

**Product QR codes on shelf labels** *(Medium)*
- Each shelf label includes a QR code
- Customer scans → mobile page showing product name, shot count, demo video, price
- Requires Cloudflare Tunnel (see below) or a local-only URL

**Cloudflare Tunnel** *(Medium — enables off-network access)*
- Add `cloudflared` container to docker-compose
- Exposes `fims.yourdomain.com` without port forwarding
- Enables: customer QR code links, remote access for boss, email receipt URLs

**Email receipt** *(Medium)*
- Optional email field at checkout
- Send HTML email with itemized receipt after sale completes
- Uses SMTP (Gmail app password or Resend)

**Customer display / Pi kiosk** *(Medium)*
- When cashier scans a product, the Pi TV shows the product's demo video
- WebSocket push from FIMS to kiosk URL already partially wired (`/ws/*` in Caddyfile)

### Priority 4 — Bigger Builds

**Supplier purchase order workflow** *(Lower — future phase)*
- Create a PO for a supplier with product + qty + cost
- Mark received → auto-increment inventory
- Variance report (ordered vs. arrived)

**Product alias table** *(Lower)*
- Same product may appear as "Game On!", "Game On", "GAME ON" across documents
- Store alternate names, match on import

**Product photography integration** *(Lower)*
- Upload front/back/barcode photo per product
- Display in product detail and on customer-facing pages

**Year-over-year sales comparison** *(Lower — needs a year of data first)*

**"Build your show" tool** *(Lower — customer-facing)*
- Customer picks budget + duration
- System suggests product mix by category

---

## Hardware Reference

| Device | Role | Connection |
|--------|------|------------|
| KianPotPi | FIMS server: Postgres, Redis, all docker containers (api/web/worker/beat/proxy) | LAN `192.168.0.105` (DHCP, can change), mDNS `kianpotpi.local`, Tailscale `100.73.208.99`, repo at `~/fims` |
| Video Pi | Dedicated kiosk display driver — runs `player_service.py` (FastAPI/mpv), separate machine from KianPotPi | LAN `192.168.0.198`, SSH `pi@192.168.0.198`, service on **port 7777** (not the file's hardcoded default of 8090 — check `VIDEO_PI_URL` in KianPotPi's `.env`), videos live at `/media/pi/VIDEOS/videos/` |
| Old kiosk Pi (USB drive) | Legacy "PyroSalesman" kiosk app — barcode-scan-interrupts-loop video player, predates the current system | Physically a USB drive plugged into **KianPotPi** as storage (not booted). Boot partition (`sda6`, FAT32) auto-mounts at `/media/krioasns/boot`; main rootfs (`sda7`, ext4) needs manual mount: `sudo mount -o ro /dev/sda7 /mnt/oldpi`. App at `/mnt/oldpi/home/pi/python/pyrosalesman_v40.py` (latest version; `BackUp/` has older versions + an old `redrhino.db`). **Unmount when done**: `sudo umount /mnt/oldpi` |
| KianPuter (PC) | Secondary dev machine, separate git clone of fims | LAN `192.168.0.27`, Tailscale `100.99.89.118`, SSH alias `pc`, repo at `C:\FIMS` |
| MSI Laptop | Primary dev machine (Claude Code runs here) | Local clone at `C:\Users\batma\Fireworks Store\fims`, local Docker Postgres for dev/testing |
| Dejavoo Z8 | Credit card processing, receipt printing | TCP/IP or USB |
| Royal 435DX | Cash handling only | Not integrated |
| Barcode scanner | Sales scan, product lookup | USB HID → browser input |

### Where to find things (as of 2026-06-18)
- **Catalog data sourcing** (Issuu CDN IDs, wholesale site survey notes): `docs/DATA_SOURCES.md`
- **No Name/RM scraped data**: `scripts/catalogs/noname/2026/` (`gotfireworks_links.json` = PDF→URL map, `gotfireworks_scraped.json` = pulled product data, `noname_parsed_preview.json` = OCR parse)
- **Legacy Red Rhino kiosk data**: `scripts/catalogs/legacy/` (`redrhino_products.csv`, `videopi_filelist.txt`) — sourced from `redrhino.db` on the Video Pi (`/media/pi/VIDEOS/redrhino.db`)
- **Product photo pullers** (always overwrite, not just fill gaps): `scripts/download_gotfireworks_images.py`, `scripts/download_worldclass_images.py`
- **Barcode/SKU fix script**: `scripts/verify_worldclass_barcodes.py`
- **Live served product images**: `media/product_images/` on whichever host (laptop/KianPotPi) — not the same as the raw OCR extraction dirs under `scripts/catalogs/**/product_images/` (gitignored, not needed for live operation)
- **Inventory scan/confirm logic**: `backend/app/api/v1/endpoints/inventory.py`
- **Video player control + idle-loop filter**: `backend/app/api/v1/endpoints/video_library.py`
- **Main merged UI pages**: `frontend/src/pages/ProductCatalog.tsx` (Products: Catalog/Initialization/Data Entry/Pricing tabs), `frontend/src/pages/VideoReview.tsx` (Videos: Review Queue/Remote tabs)
- **Standing data-quality concerns**: see Priority 0 in the roadmap below

---

## Email Scraping — Technical Plan

**Goal:** Automatically find invoices, price lists, sales orders, and catalogs from boss's email and import them into the Documents system.

**Approach:**
1. Backend model: `EmailAccount` (host, port, email, encrypted password or OAuth token, last_synced_at)
2. Celery beat task: runs every 15 minutes, connects via IMAP, searches for:
   - Emails from boss's address (configurable)
   - Keywords in subject: "invoice", "order", "price list", "catalog", "fireworks", "shipment"
   - Date range: since last_synced_at
3. For each matching email:
   - Download PDF/Excel/CSV attachments
   - Save to `media/documents/imports/email/`
   - Create a `StoreDocument` record (category auto-detected from filename/subject)
   - Optionally queue through import pipeline for price list extraction
4. UI in Settings: connect email, set boss's address, view sync log, manually trigger sync

**Libraries:** `imaplib` (stdlib) for IMAP, `email` (stdlib) for parsing, existing document storage.

**Gmail note:** Requires an App Password (not regular password) if 2FA is on. Generate at myaccount.google.com → Security → App Passwords.
