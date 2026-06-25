# Build: FIMS product photo audit — PHASE 1 (image sourcing only)

Build ONE Python script: `scripts/photos/source_images.py`. Goal: gather candidate
replacement images for products whose current photo is wrong (many Jake's / World Class
images are the wrong product — see CLAUDE.md Priority 0 #4). This phase only COLLECTS
candidate images + writes a manifest. The vision verification is a separate later phase —
**do NOT build verify_images.py in this pass.**

## HARD GUARDRAILS (do not violate)
- **READ-ONLY DB.** You may run `SELECT` only. NEVER emit or execute INSERT / UPDATE /
  DELETE / ALTER, never touch `products.image_path`, never write SQL files. The only things
  this script writes are image files under `media/photo_audit/` and `manifest.json` files.
- **Stay in scope.** Build only `source_images.py` + update `scripts/requirements-scraper.txt`
  + a short `scripts/photos/README.md`. Do not modify any other file.
- **Do not explore the repo broadly.** The only files you need to read are the two named
  reference scrapers below. Don't go reading importers, merge scripts, or migrations.

## Reference files to model after (read ONLY these two)
- `scripts/download_gotfireworks_images.py`  — how the repo fetches gotfireworks images (httpx, polite timeouts, file naming).
- `scripts/download_worldclass_images.py`    — same for worldclassfireworks.com.

## Conventions
- DB access: connection string `postgresql://fims:fims@100.73.208.99:5432/fims` (env
  `DATABASE_URL` overrides). Use `psycopg` (v3). SELECT only.
- Product fields: `products.id` (uuid str), `item_number`, `name`, `brand_id`; current image
  is `products.image_path` (relative, e.g. `product_images/{uuid}.webp`, under `media/`).
  Brand name via `product_brands`.
- Add any new deps to `scripts/requirements-scraper.txt` (e.g. `ddgs` for web image search).

## `source_images.py` behaviour
For each selected product, gather candidate images from up to THREE sources and save them:
1. **gotfireworks.com** — reuse the approach/URL map from the gotfireworks reference script.
2. **worldclassfireworks.com** — reuse the worldclass reference approach.
3. **general web image search** — query `"{name}" {brand} firework {item_number}` via a
   no-API-key lib (`ddgs` image search preferred). Take top N (default 5).
Save to `media/photo_audit/{product_id}/{source}_{i}.{ext}` and write per-product
`media/photo_audit/{product_id}/manifest.json`:
`{product_id, item_number, name, brand, current_image, candidates:[{source,url,file}]}`.

Selection args: `--sample N`, `--brand "World Class"`, `--limit N`, `--ids a,b,c`.
Be polite (timeouts, small concurrency, skip already-downloaded → idempotent).
No API key required. **SELF-TEST it on `--sample 2` and paste the output.**

## Deliverables
- `scripts/photos/source_images.py`, `scripts/photos/README.md`, updated
  `scripts/requirements-scraper.txt`. Runnable + idempotent. NO DB writes. Then STOP and
  summarize what you built + paste the `--sample 2` self-test output.
