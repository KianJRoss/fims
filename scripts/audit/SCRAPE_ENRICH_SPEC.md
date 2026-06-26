# Spec: scrape_enrich.py — Layer-2 scripted online enricher → evidence ledger

Build `scripts/audit/scrape_enrich.py` (Python 3.13). It researches in-store
products online by SKU+name, extracts product fields from retailer/brand pages,
and **appends candidate facts to the evidence ledger** (`scripts/audit/evidence_ledger.py`
format). It does NOT write to the products DB — the ledger's verify/apply gate does.
Claude runs it (Codex must not run it; network/interactive). Keep it polite + resumable.

## Reuse the ledger module
Import from the sibling file:
`from evidence_ledger import add_records, FILLABLE, DSN`
Append via `add_records([...])`. Each record dict:
```
{"product_id":"", "item_number": <sku>, "name": <name>, "field": <one of FILLABLE>,
 "value": <extracted>, "source": "<site domain + short label>", "url": <page url>,
 "confidence": <0..1 float>, "identity_check": "<how we know page == this SKU>"}
```
FILLABLE = shot_count, duration_seconds, effects, packing, category_id, description.
**Do NOT emit category_id** from scraping (free-text categories are unreliable to map);
emit the other five only. Leave category to a later mapping pass.

## Target set (default)
Query the DB read-only for in-store products missing ≥1 fillable field:
`SELECT item_number,name,brand_id FROM products WHERE in_store=true AND item_number IS NOT NULL AND item_number<>''`
and (any of shot_count/duration_seconds/effects/packing IS NULL/empty). Use
`conn.read_only=True`. Add `--limit N` and `--only-sku SKU[,SKU...]` for controlled runs.
Skip a (product,field) if the DB field is already populated (only research gaps).

## Search → fetch → extract
For each product:
1. **Search** DuckDuckGo HTML (no API key): GET
   `https://html.duckduckgo.com/html/?q=<url-encoded query>` with a normal
   User-Agent. Query = `"<sku>" <name> fireworks`. Parse result anchors
   (`a.result__a`), decode DDG redirect (`uddg` param) to real URLs. Take top ~6.
   Also accept a second query `<name> <brand> fireworks` if the first yields <3.
2. **Fetch** each candidate URL (requests, 15s timeout, normal UA). Skip non-HTML,
   skip obvious junk domains (youtube, facebook, pinterest, reddit, wikipedia, ebay,
   amazon). De-dupe by domain (max 1 page per domain per product).
3. **Identity check** (critical — drives confidence):
   - strong: the page text/HTML contains the exact SKU, OR a 11–13 digit barcode whose
     trailing digits include the numeric part of the SKU. → identity_check notes it,
     base confidence 0.9.
   - medium: page name closely matches product name AND brand appears on page, SKU not
     found. → confidence 0.5, identity_check="name+brand match, SKU not found".
   - weak: only loose name match → confidence 0.3.
4. **Extract fields** from each page (best-effort, all optional):
   - Prefer JSON-LD (`<script type=application/ld+json>`) Product objects.
   - shot_count: regex like `(\d+)\s*(shots?|shot count|breaks?)`; also JSON-LD.
   - duration_seconds: `(\d+)\s*sec(onds?)?\b` or `duration[:\s]+(\d+)`; ignore values >600.
   - effects: from a labelled "Effects"/"Colors" spec field or JSON-LD; join list to
     comma string; cap length ~300 chars; reject if it's clearly prose paragraph (> 12 words AND no commas).
   - packing: regex `\b(\d{1,3}\s*/\s*\d{1,3})\b` near "pack"/"case"; normalize to `N/N`.
   - Sanity: ints must be >0; shot_count <2000; packing must match `^\d+/\d+$`.
5. Build one record per (field, page) that yielded a value. Confidence = identity base,
   minus 0.1 if the value came from loose regex rather than JSON-LD/labelled spec.

## Output / behavior
- Append all candidates via `add_records(...)`.
- Print a per-product line: sku, name, #pages fetched, fields found.
- Write a run log `scripts/audit/scrape_enrich_run.json`:
  `[{item_number,name,queries,urls_fetched,records_added}]`.
- **Rate-limit:** sleep ~2–4s between products and ~1s between page fetches; retry a
  failed fetch once. Catch per-product exceptions so one failure never aborts the run.
- Resumable: before researching a product, if the ledger already has records for it
  captured today, skip unless `--force`.

## Dependencies
Use `requests` + `beautifulsoup4` (bs4) + stdlib (re, json, time, urllib.parse, html).
If bs4 isn't desired, a tolerant regex/`html.parser` approach is fine. No Selenium.
One self-contained file. Do not run it; just produce correct code.
