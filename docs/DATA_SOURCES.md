# FIMS Catalog Data Sources

Single reference for every place we can pull fireworks product data (names, item numbers,
UPCs/GTINs, case packs, images, videos, descriptions) into FIMS. Update this file as new
sources are found or existing ones are processed — don't scatter source lists elsewhere.

## Status legend
- ✅ Imported into FIMS Postgres already
- 🔄 Downloaded/staged locally, not yet imported
- 🔍 Identified, not yet downloaded or surveyed
- ⛔ Checked, not usable (blocked/empty/irrelevant)

---

## 1. Catalogs already in hand (current priority: Jake's + No Name/RM)

| Source | Local path | Status | Notes |
|---|---|---|---|
| Jake's Fireworks (World Class) 2026 | `scripts/catalogs/jakes/2026/` (`text_layer.json`, `vision.json`, extracted page images) + `scripts/jakes_catalog.json` | ✅ Imported | 548 products, 177 pages. Source: Issuu CDN ID `260506140512-f077399ecfd86afa6eee7e4087f1bd81`, publisher `cloudsent` — same catalog re-confirmed live at https://issuu.com/cloudsent/docs/2026_world_class_fireworks_catalog (June 9 2026 upload, identical CDN ID, no new data). |
| No Name / RM Enterprises 2026 | `NoName2026.pdf` (repo root, 4.2MB) + `scripts/catalogs/noname/2026/` (`noname_parsed_preview.json`, `gotfireworks_links.json`, gotfireworks cross-check) | 🔄 In progress — **major upgrade found 2026-06-17, see below** | |
| Red Rhino Fireworks (legacy kiosk DB) | `scripts/catalogs/legacy/redrhino_products.csv`, `videopi_filelist.txt` + live `/media/pi/VIDEOS/redrhino.db` on the Video Pi | 🔄 Staged, not imported | Script ready: `scripts/import_legacy_redrhino.py`. ~13,121 GTIN→name→video rows recovered from old kiosk SQLite DB. `import_jobs` table in Postgres is still empty — never actually run yet. |

### Catalog placeholder dirs awaiting content
`scripts/catalogs/brothers/2026/`, `raccoon/2026/`, `rm/2026/`, `winda/2026/` exist but are empty — matching structure ready for whenever those brands' catalogs are sourced.

### Issuu catalogs found but NOT yet pulled (deferred — manual page-image + Vision/OCR pass later)
Issuu's accessibility/text layer (`svg.issuu.com/{cdn-id}/page_N.html`) does **not** reliably return clean text for every publication (some return 403/AccessDenied, e.g. Red Rhino's), and pages aren't downloadable as a plain PDF. The working approach used for Jake's was: pull page images from `image.isu.pub/{cdn-id}/jpg/page_N_*.jpg` + run Vision/OCR per page. Treat all of these as 🔍 until that pass happens — do not attempt curl/text-layer scraping again, go straight to image+Vision.

Publisher **cloudsent** (https://issuu.com/cloudsent) hosts multiple wholesale brand catalogs, multi-year:
| Catalog | CDN ID | Issuu URL |
|---|---|---|
| World Class Fireworks 2026 | `260506140512-f077399ecfd86afa6eee7e4087f1bd81` | `/cloudsent/docs/2026_world_class_fireworks_catalog` (same as already-imported Jake's catalog) |
| World Class Fireworks 2025 | 🔍 not extracted yet | `/cloudsent/docs/2025_world_class_fireworks_catalog` |
| World Class Fireworks 2024 | 🔍 | `/cloudsent/docs/2024_world_class_catalog_final` |
| Jake's Fireworks 2023 | 🔍 | `/cloudsent/docs/2023_catalog_final` |
| Jake's Fireworks 2021 | 🔍 | `/cloudsent/docs/2021_catalog_final` |
| Red Rhino Fireworks 2026 | `260216165235-dcd995374770ab1f94821de84e69d1e3` | `/cloudsent/docs/red_rhino_fireworks_2026_catalog` (text layer blocked — 403) |
| Red Rhino Fireworks 2025 | 🔍 | `/cloudsent/docs/rrfw_2025_catalog_web` |
| Red Rhino Fireworks 2024 | 🔍 | `/cloudsent/docs/rrfw_2024_catalog_web` |
| Red Rhino Fireworks 2023 | 🔍 | `/cloudsent/docs/rrfw_2023_catalog` |
| Cutting Edge Fireworks 2024 | 🔍 | `/cloudsent/docs/2024_ce_catalog_8_page` |
| Fireworks Display Crate Brochure | 🔍 | `/cloudsent/docs/fireworks_display_crate_brochure` |

Other publishers seen on Issuu (not yet surveyed): `spiritof76` (multiple years 2015-2021), `wincofireworks` (`2026_winco_fireworks_premiums_catalog`), `extremedigitalprinting` (2019 generic fireworks catalog, publisher unclear).

**Why multi-year matters:** older-year catalog products may still be in circulation/inventory even after a new year's catalog drops — don't treat only the newest year as current stock.

---

## 2. Video Pi — substantial legacy database (confirmed, not yet imported)

- **Device**: Raspberry Pi at `192.168.0.198` (SSH alias `videopi`), separate from the main FIMS Pi (`KianPotPi`, 192.168.0.209/100.73.208.99).
- **Database**: `/media/pi/VIDEOS/redrhino.db` (SQLite, 3.4MB) — confirmed via direct SSH + python3 sqlite3 inspection:
  - `product` — **13,121 rows** (`gtin`, `pname`, `vname`, `vlocation`) — barcode → product name → video filename
  - `counts` — 8,006 rows (`gtin`, `pname`, `sdate`) — messy YouTube-link scrape log, low value
  - `download_list` — 216 rows — Dropbox links to yearly video batches (2021-2023) by brand, could still be live
  - `playlist` — empty
- **Video files**: served from `/media/pi/VIDEOS/videos/*.mp4`, indexed in FIMS's `legacy/videopi_filelist.txt` (14,181 filenames). Brand prefixes: WC (World Class), RR (Red Rhino), CE (Cutting Edge), JB (Jake's), BC (Black Cat), PB (Pyro Box), SW (Sunwing).
- **Live service**: `player_service.py` on port 8090 — FastAPI kiosk player, `GET /videos`, `POST /play`, `POST /idle/playlist`, etc. FIMS backend talks to it via `VIDEO_PI_URL` env var (`backend/app/api/v1/endpoints/video_library.py`).
- **Status**: 🔄 — import script `import_legacy_redrhino.py` exists and is ready but has never been run (`import_jobs` table empty in live Postgres as of 2026-06-17).

---

## 3. Wholesale distributor websites (large product databases — survey in progress)

| Distributor | Main site | Resources | Video | Surveyed? |
|---|---|---|---|---|
| Spirit of '76 | https://76fireworks.com/catalog/ | https://76fireworks.com/resources-for-retailers/ , https://76dealernetwork.com/ | YouTube `UCIgl7L8F3VwGnES_kEZrqHA` | 🔍 |
| Winco Fireworks | https://www.wincofireworks.com/fireworks/ | https://www.wincofireworks.com/resources/product-information/ , https://www.wincofireworks.com/product-category/new-for-2026/ | YouTube `@WincoFireworks` | 🔍 — also distributes Black Cat |
| Superior Fireworks | https://www.superiorfireworks.com/wholesale/all-categories | https://www.superiorfireworks.com/wholesale/category/new-products | YouTube `SuperiorFireworks` | 🔍 — pilot crawler being built separately |
| American Wholesale Fireworks | https://americanwholesalefireworks.com/ | — | — | 🔍 |
| Phantom Fireworks | https://fireworks.com/ | annual online catalog + 3D show builder | — | 🔍 |
| RM Enterprises (No Name/Sunwing/etc.) | **https://gotfireworks.com/** | confirmed live site — see survey below | — | ✅ surveyed |

### ⭐ No Name 2026 PDF — embedded hyperlinks (found 2026-06-17, supersedes OCR approach)
**The product images in `NoName2026.pdf` are clickable hyperlinks straight to the matching gotfireworks.com product page.** User pointed this out directly — confirmed via PyMuPDF (`page.get_links()`): **365 unique `gotfireworks.com` product links across the PDF's 69 pages** (only page 2, a cover/TOC page, has none). Extracted and saved to `scripts/catalogs/noname/2026/gotfireworks_links.json` (`[{"page": N, "url": "..."}]`).

This is a much better path than OCR/Vision for this catalog: instead of guessing names/fields from page images, each product can be resolved with 100% authority via its linked gotfireworks.com page. Confirmed by fetching `bloodthirst-9-shot-500-gram-multi-shot-aerial-by-no-name-fireworks.html` (linked from PDF page 3) and parsing its **"More Information" table** (a tab we hadn't checked before — separate from the "description" tab surveyed earlier):

```
SKU                  => NN5109
Brand                => NO NAME
Sales Per Case       => 6.00
Shots                => 9
Duration             => 35sec
Dimension            => 0   (blank/placeholder on this item)
Case Packing         => '6/1
Product Catalog Name => BLOODTHIRST
```

This exactly matches the existing OCR-parsed row for the same item (`noname_parsed_preview.json`: `NN5109` / `BLOODTHIRST` / `NO NAME` / packing `'6/1`) but with **guaranteed-clean Shots and Duration fields** that the OCR pass had marked as `None`/unknown for ~158 of 275 items (per the earlier `gotfireworks_crosscheck.py` fuzzy-match run). The hyperlinks remove the need for fuzzy name-matching entirely — direct 1:1 product correspondence.
- Table is server-rendered HTML (not JS-injected) — plain `curl` + regex/HTML parsing works, no headless browser needed.
- **Still no UPC/GTIN field** in this table either — consistent with every other gotfireworks.com page checked.
- 365 links vs. 275 items in the current OCR preview — the hyperlink approach likely has **better coverage** than the OCR/grid-bucketing pass, not just better field accuracy.
- **Done (2026-06-17)**: built and ran `scripts/scrape_gotfireworks_noname_links.py` — fetched all 365 linked pages, parsed the "More Information" table from each (SKU, Brand, Sales Per Case, Shots, Duration, Dimension, Case Packing, Product Catalog Name, description, stock status), 365/365 succeeded with zero errors. Saved to `scripts/catalogs/noname/2026/gotfireworks_scraped.json`.
- **Done (2026-06-17)**: built and ran `scripts/merge_gotfireworks_noname.py` — merged the scraped data into the live `products` table, matched by `item_number == SKU`. Non-destructive: only fills currently-NULL `shot_count`/`duration_seconds`/`description`/`brand_id`, appends case-packing info to `notes` (products has no `packing` column — that lives in the separate `case_packs` table, out of scope here). Result: **335 existing products gap-filled, 30 new products inserted, 0 skipped**. Verified — e.g. `M5039` BUCKLE UP went from no shot_count/duration/brand at all to fully populated (18 shots, 39sec, brand Miracle).
- This pipeline (`scrape_gotfireworks_noname_links.py` → `merge_gotfireworks_noname.py`) can be re-run any time `gotfireworks_links.json` is regenerated (e.g. if NoName2026.pdf is replaced with a newer year's catalog) — re-running is safe/idempotent since it only fills gaps and skips rows with no changes needed.

### Product photo downloads (2026-06-17)
Built and ran two image-pulling scripts, both saving to `media/product_images/{item_number}.{ext}` and setting `products.image_path` (existing convention from `backfill_product_images.py`, only fills `NULL`, never overwrites):
- `scripts/download_gotfireworks_images.py` — reuses the URLs already in `gotfireworks_scraped.json`, fetches each page's `img.gallery-placeholder__image`. **Result: 314/315 No Name-family products now have a photo** (1 failure: `MC2054` → 404, product page no longer live).
- `scripts/download_worldclass_images.py` — worldclassfireworks.com has no saved per-product URL list, so this one first enumerates every product by walking all 11 `/fw_type/{type}/` taxonomy archive pages (each renders its full category on one page, no pagination — confirmed up to 231 products on one page). SKU is recovered from the product image filename: site uses two different conventions, `1004385-PIONEERS-OF-PROGRESS-Right.png` (hyphenated) and older files like `100399820Money20Maker.jpg` (literal `20` where `%20`-encoded spaces should be) — so the regex anchors on **exactly the first 7 digits** of the filename (confirmed 548/549 World Class item_numbers are 7 digits) rather than requiring a hyphen separator. **Result: 280/549 World Class products now have a photo.**
- **The remaining ~269 World Class products without a photo are not a scraper bug** — spot-checked one (`1000421`, "KIDS DELIGHT") via the site's own search: zero results. These are older/legacy catalog items (originally OCR-imported from the Issuu catalog) that are no longer listed anywhere on the current live site under any taxonomy, so there's no photo left to pull from this source for them. Would need a different source (the Issuu catalog page images themselves, OCR'd, or a future visit if the brand re-lists them) to close this gap.

### No Name brand — direct search confirmation (2026-06-17)
- gotfireworks.com's own site search for "no name" returns **174 products** explicitly titled `"... By No Name Fireworks"` (e.g. `thunder-bomb-firecracker-1-000-count-roll-by-no-name-fireworks.html`, SKU `NN9002`) — confirms the `NN`-prefixed SKU scheme matches our PDF-parsed 2026 catalog items (e.g. `NN5109` BLOODTHIRST, `NN5095` CATICORN, `NN5022` COME AND GET IT! from `noname_parsed_preview.json`), but the *specific* SKUs don't overlap — gotfireworks.com's live "No Name" listings skew toward smaller evergreen novelty items (sparklers, firecracker rolls, smoke tubes, winged fireworks), not the 500-gram-cake/shell items that dominate the printed 2026 wholesale catalog. Same brand/scheme, different product slice — the live site likely just hasn't (or won't) list the big seasonal display items individually.
- **Still no UPC/GTIN/barcode field anywhere on gotfireworks.com**, re-confirmed on a No Name product page specifically (only SKU).
- Tried matching specific 2026 catalog item names (BLOODTHIRST, CATICORN) directly against both gotfireworks.com and OCFireworks — **zero matches**. These specific 2026 items aren't listed on either consumer site yet.
- OCFireworks.com has no explicit "No Name" brand page (its sibling RM brands Sunwing/Topgun/Miracle are there, No Name itself isn't a literal brand-tile) — one fuzzy "no name" search hit landed under its generic "Mixed Brands" bucket with a real clean UPC, but isn't confirmed to actually be RM's No Name brand, just a coincidental text match.

### gotfireworks.com survey (RM Enterprises — No Name, Sunwing, Forward, Pyro Box, etc.)
- Page copy explicitly says "R and M Enterprises" — confirmed this is RM's real consumer-facing site (Magento-based).
- Brand attribution is baked into the product title itself, e.g. `"EVERGREEN MAJESTY | 28 Shot 500 Gram Cake by Sunwing Fireworks"` — so multiple brands (No Name, Sunwing, etc.) live under one storefront, distinguished only by the "by {brand}" suffix in the name.
- Category landing page: `/fireworks-for-sale.html` → subcategory tiles (e.g. `/fireworks-for-sale/500-gram-cakes-fireworks.html`). Each subcategory's price-filter sidebar shows total product count (e.g. 500 Gram Cakes = 86 products: 18 under $100 + 68 over).
- Per-product list markup (`<li class="item product product-item">`) cleanly exposes, **without login**: internal numeric product ID, SKU (e.g. `SWC2611`), full name w/ brand suffix, product image URL, detail-page URL, live stock status (`QTY In Stock` / `QTY on Order` / `QTY in Trans`), and case/unit type (`CASE`).
- Product detail page adds: full marketing description (shot count + duration usually restated in prose, e.g. "28 breathtaking shots... 27 seconds"), SKU, stock.
- **No UPC/barcode anywhere on the site** — matches what the gotfireworks crosscheck script already found (only shot-count enrichment, no barcode source here).
- Price is gated behind login ("Login In For Price"), but note: the real price value still leaks into a hidden PayPal button's `data-amount` attribute in the page HTML even when not logged in (e.g. `data-amount="98.5"`) — not needed for our use case (product identity, not pricing), so not worth relying on, but documented in case price data becomes useful later.
- Advanced search exists at `/catalogsearch/advanced/`.
- **Conclusion**: gotfireworks.com is a solid secondary source for No Name/RM products — good for cross-checking names/SKUs/shot-counts/descriptions against the PDF parse (already partially done via `crosscheck_gotfireworks.py`), but cannot supply UPCs.

## 4. Manufacturer / brand sites

| Brand | URL | Surveyed? |
|---|---|---|
| Brothers Pyrotechnics | https://www.brotherspyro.com/ | 🔍 |
| Winda Fireworks USA | https://www.windafireworks.com/ | 🔍 |
| Black Cat Fireworks | https://www.blackcatfireworks.com/ | 🔍 |
| Raccoon Fireworks | https://raccoonfireworks.com/ | 🔍 |
| Dominator Fireworks | https://dominatorfireworks.com/ | 🔍 |
| World Class Fireworks (Jake's brand) | https://worldclassfireworks.com/ | ✅ surveyed — see below |
| Cutting Edge Fireworks | https://www.cuttingedgefireworks.com/ | 🔍 |
| Bright Star Fireworks | https://www.brightstarfireworks.com/ | 🔍 |
| Shogun Fireworks | https://shogunfireworks.com/ | 🔍 |

### worldclassfireworks.com survey (Jake's brand)
- WordPress + WooCommerce theme, NOT Issuu — this is the live site backing the brand, separate from the Issuu catalog PDF.
- Listing page `/fireworks/` renders product cards via an AJAX endpoint (`POST /wp-admin/admin-ajax.php`, `action=advanced_filters`) that supports filtering by category/color/effect/shots/duration and returns HTML fragments — paginates via a "Load More" button (20 at a time) rather than true pagination, so a scraper should drive the AJAX endpoint directly instead of clicking through pages.
- Each product card div (`.product-single`) embeds structured data attributes directly in the HTML — **no need to visit the detail page for these fields**: `data-color`, `data-effect`, `data-category`, `data-shots`, `data-duration`, plus the product name and detail-page link.
- Item number is embedded in the product image filename itself, e.g. `1004385-PIONEERS-OF-PROGRESS-Right.png` → SKU `1004385` — and confirmed matching the SKU shown on the detail page (`Product SKU: 1004385`).
- Detail page (`/firework/{slug}/`) adds: full description paragraph, and an embedded video — **hosted on Wistia**, account `jakesfireworks` (e.g. `https://jakesfireworks.wistia.com/s/5vblieyceop3i9j`), not YouTube.
- **No UPC/barcode and no price/case-pack info anywhere on the site** — same gap as gotfireworks.com.
- Taxonomy browsing also works via dedicated URLs: `/fw_type/{type}/`, `/fw_colors/{color}/`, `/fw_effects/{effect}/` — could be used to enumerate all products by type without the AJAX filter.
- **Conclusion**: strong supplemental source for Jake's/World Class — fills in colors/effects/shot-count/duration/description/video reliably, useful for cross-checking the already-imported Issuu-based 548 products and catching anything missing/changed since.

## 4b. Multi-brand consumer retailers (NEW — found 2026-06-17, high value)

These are consumer-facing e-commerce stores (not wholesale distributors) that resell products from many of the brands above under one storefront. Found while looking for "shared info between retailers" — these are exactly that, and several expose real UPCs.

| Retailer | URL | Platform | Surveyed? |
|---|---|---|---|
| **OCFireworks** | https://ocfireworks.com/ | BigCommerce | ✅ surveyed — see below, high value |
| Elite Fireworks | https://www.elitefireworks.com/collections/world-class-fireworks | — | 🔍 |
| AAH Fireworks | https://www.aahfireworks.com/brands/world-class/ | — | 🔍 |
| Fireworks Stores Online | https://www.fireworksstoresonline.com/world-class-fireworks | — | 🔍 |
| Intergalactic Fireworks | https://shop.intergalacticfireworks.com/brand/world-class | — | 🔍 |
| Victory Fireworks Wholesale | https://victoryfireworkswholesale.com/world-class/ | — | 🔍 |
| Wicked Fireworks | https://www.wickedfireworks.com/wholesale-retail/World-Class-Fireworks-11.aspx | — | 🔍 |

### OCFireworks.com survey — best single source found so far
- BigCommerce storefront, **no login wall, real prices visible**. Brand directory at `/brands/` (2 pages) lists ~150+ brand category pages, including **World Class** (Jake's), **Sunwing**, **Topgun**, **Miracle** (RM Enterprises' other brands — no literal "No Name" brand page, but its sibling brands are all here), **Red Rhino**, **Black Cat**, **Cutting Edge**, **Winda**, **Raccoon**, **Bright Star**, **Brothers**, **Dominator**, and dozens more (Amazing, Badaboom, Black Scorpion, Blast Wave, Boomer, Dragon Blade/Slayer, Eastsun, Fathead, Firehawk, Founding Fathers, Fowl, Freedom First, Golden Bear, Great Grizzly, Guandu, Happy Family, Hero Pyro, Ignite, Inked Pyro, JD, Keystone, King Bird, Legend, Leopard, Lidu, Link Triad, Mad Ox, Magnus, Mega Ton, Megabanger, MJG, Night Owl, OMG, Power Blast, Pyro Demon/Diablo/Eagle/High/King/Nation/Packed, RIAkeo, Shock Wave, Shogun, Shotgun, Showtime, Sky Bacon/Painter/Thunder, T-Sky, Time Bandit, Wild Dragon, Wise Guy, Wizard).
- Each product page has a `BCData.product_attributes` JS object with `sku`, `upc`, `mpn`, `gtin` fields, plus a visible "UPC:" row in the spec table.
- **UPC data quality varies by brand/feed**: World Class products carry a real, unique, well-formed UPC (confirmed: "Angels Kiss" → `8052531141914`, 13-digit EAN). Sunwing products checked (3 different items) all returned the **identical corrupted value `"6.95071E+11"`** — a spreadsheet scientific-notation export bug from whoever fed RM Enterprises' product data in, meaning **Sunwing/RM-brand UPCs on this site are not usable as-is**. Need to spot-check other brands individually before trusting any given brand's UPC field here.
- `mpn` field is populated and varies per product even when UPC is broken (e.g. `C253*D32*JFR`, `I74*ZZ03`) — looks like an internal distributor part-number scheme, worth keeping as a secondary cross-reference key even where UPC fails.
- **Conclusion**: OCFireworks is the best UPC source found for **World Class/Jake's** specifically — better than worldclassfireworks.com itself, which has no UPC at all. For No Name/RM-family brands it currently does not help with UPCs (broken data) but still gives clean names/prices/stock/descriptions across Sunwing/Topgun/Miracle. Worth scraping broadly; spot-check UPC validity per-brand before trusting it as a barcode source for a given brand.

## 5. Additional sources (from prior research, not yet surveyed)
- Red Rhino Fireworks current site — worth checking if it exists, separate from the legacy kiosk DB / Issuu catalogs above
- TNT Fireworks — https://www.tntfireworks.com/wholesale
- Sky King Fireworks — https://skykingfireworks.com/
- AllSpark Fireworks — direct importer/distributor
- Wald & Co. — https://www.waldfireworks.com/wholesale-consumer/
- Wisley Pyrotechnics (WPI) — https://www.wisleypyrotechnics.com/
- Lynch Imports — https://lynchimportsllc.com/
- Pyro Spectaculars — display/show pyro, less relevant for consumer SKU data
- American Pyrotechnics Association — https://en.wikipedia.org/wiki/American_Pyrotechnics_Association — possible member directory

## 6. Barcode/GTIN cross-reference databases (fill UPC gaps)
- UPCitemdb.com — https://www.upcitemdb.com/
- Barcode Lookup — https://www.barcodelookup.com/
- Go-UPC — https://go-upc.com/barcode-lookup

---

## Current priority (per user direction, 2026-06-17)
1. **Jake's** — catalog already imported; website survey + any newer/older-year products still pending.
2. **No Name / RM** — PDF import in progress; no web source exists, nothing further to find here except cross-checks (gotfireworks.com already done).
3. Live wholesale/brand **websites** (section 3 & 4) are being surveyed next — checking site structure, what product data is exposed, before any scraping/crawling work begins.
4. Issuu catalog images (section 1) are explicitly deferred until a manual page-image + Vision/OCR pass.
