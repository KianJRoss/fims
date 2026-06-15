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

### Built ✓
- Product catalog with 548 World Class products (Jake's 2026 via Issuu text layer)
- Multi-brand checkbox filter, catalog sort by page number
- Video review queue: YouTube search, confirm, download via yt-dlp
- Sales screen: barcode scan, product search, cart, deal application, complete sale
- Pricing: multi-type price management with history
- Deal engine: BXGY, BUNDLE, PERCENT_OFF, FLAT_AMOUNT, CHEAPEST_FREE
- Documents tab: file storage (upload/download/delete) + catalog import
- Issuu scraper: fetches text layer by CDN ID, auto-imports Jake's or creates review rows
- PDF import pipeline: upload → OCR → review rows → commit
- Mobile network access: Caddy binds 0.0.0.0:80, VITE_API_URL is relative
- Barcode print page

### In Progress / Partial
- Reports page — stub, "Coming soon"
- Mobile-responsive nav — desktop sidebar only, no mobile bottom bar yet
- Product names — ~400 products still named "Item {sku}" (OCR script in progress)
- Receipt printing — no printer integration yet
- Email scraping — planned, not started

### Not Yet Built
- Transaction history / receipt lookup
- Inventory (cases on hand, receiving workflow)
- Shift open/close / cash drawer reconciliation
- Supplier management UI
- Purchase order workflow
- Dejavoo Z8 receipt printer integration
- Cloudflare Tunnel for off-network access
- Email inbox scraping for boss's invoices/price lists
- Customer-facing product QR codes
- Pi kiosk display (video plays when item scanned at register)
- Product aliases / alternate name table
- User authentication / manager vs. employee roles

---

## Suppliers

| Supplier | Brand(s) | Notes |
|----------|----------|-------|
| Jake's Fireworks | World Class | 2026 catalog imported via Issuu |
| RM Enterprises | No Name, others | Price lists needed; NoName2026.pdf exists |
| Black Cat | Black Cat | No catalog yet |
| Pyro Box | Pyro Box | No catalog yet |
| Sunwing | Sunwing | No catalog yet |

---

## Alembic Migration Chain

```
971c32055cad (base)
  → 6f8d3b2a9c11
    → a1b2c3d4e5f6 (video download_status)
      → b2c3d4e5f6a1
        → c3d4e5f6a1b2 (in_store)
          → d4e5f6a1b2c3 (no_video_confirmed)
            → e5f6a1b2c3d4 (store_documents)
              → f6a1b2c3d4e5 (catalog_page)
                → g7b2c3d4e5f6 (seed price types) [pending]
```

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

**Shift reconciliation** *(Medium)*
- Open register: count drawer, enter starting cash
- Close register: count drawer, system shows expected vs. actual, prints reconciliation sheet

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
| PC (MSI) | FIMS server, database, main UI | localhost / LAN IP |
| Raspberry Pi | Video playback, customer display | LAN, WebSocket to FIMS |
| Dejavoo Z8 | Credit card processing, receipt printing | TCP/IP or USB |
| Royal 435DX | Cash handling only | Not integrated |
| Barcode scanner | Sales scan, product lookup | USB HID → browser input |

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
