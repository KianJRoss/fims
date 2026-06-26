# Spec: enrich_instore.py — fill missing in-store product fields from local evidence

Build `scripts/audit/enrich_instore.py` (Python 3.13, psycopg v3). It enriches the
**146 in_store=true products** by filling ONLY currently-missing fields from local
scraped evidence. **Report-only by default; `--apply` does reversible writes.**

## DB
- DSN: `postgresql://fims:fims@100.73.208.99:5432/fims`
- Report mode: `conn = psycopg.connect(DSN); conn.read_only = True`
- `products`: id (UUID varchar PK), item_number (the SKU), name, description (text),
  category_id (int FK→product_categories.id), brand_id (int), shot_count (int),
  duration_seconds (int), effects (text), packing (varchar), in_store (bool).
- `product_categories(id, name)` — 26 rows already exist; **never create new categories.**

## Evidence sources (all local JSON; match key = item_number/sku, normalized = `.strip().upper()`)
1. `scripts/jakes_catalog.json` — list. key=`item_number`. World Class. Gives:
   `shot_count`, `duration_seconds`, `description`, `effects` (list) + `colors` (list),
   `category` (slug e.g. "artillery-shells").
2. `scripts/catalogs/jakes/2026/vision.json` — `pages[].products[]`. key=`item_number`.
   World Class. Gives: `shell_count`→shot_count, `packing`, `description`.
3. `scripts/catalogs/noname/2026/gotfireworks_scraped.json` — list. key=`sku`. RM brands
   (No Name/Sunwing/etc). Gives: `shot_count`, `duration_seconds`, `description`,
   `case_packing`→packing, `product_catalog_name` (name candidate — DO NOT use, name is out of scope).
4. `scripts/catalogs/pyromaniacs/2026/products.json` — `['products']` list. key=`sku`.
   Gives: `category` (name string), `weightKg` (ignore). **WARNING: its `description`
   field is actually a PACKING code like "18/1"/"1/1", NOT prose** → use it as a *packing*
   candidate, never as description.

## Fields to fill (fill a field ONLY if the DB value is NULL or empty string)
`shot_count`, `duration_seconds`, `effects`, `packing`, `description`, `category_id`.
**Never touch:** name, brand_id, item_number, image_path.

## Per-field value selection
For each in-store product, normalize its item_number and look it up in each source.
Choose source by brand preference, then fall back to any source that has a value:
- brand_id 45 (World Class) → prefer jakes_catalog, then jakes_vision.
- RM brands (5 No Name, 1 Sunwing, + Pyro Box/Suns/Supreme/Miracle/Top Gun) → prefer
  gotfireworks, then pyromaniacs.
- otherwise: first source with a non-empty value.

### Field-specific rules
- **effects**: join jakes_catalog `colors` + `effects` lists into a comma-separated string
  (dedupe, keep order colors then effects). Skip if both empty.
- **description**: accept only real prose — reject candidates < 20 chars or matching
  `^\d+/\d+$` (packing codes). Pyromaniacs description is NEVER a description candidate.
- **packing**: gotfireworks `case_packing`, jakes_vision `packing`, or pyromaniacs
  `description` (the "18/1" code). First non-empty by brand preference.
- **shot_count / duration_seconds**: int only, must be > 0.
- **category_id**: map source category string → product_categories.id. Normalize both
  sides: lowercase, replace `-`/`_` with space, collapse spaces, strip. Also try a
  trailing-'s' tolerant match. If no existing category matches, DO NOT set category_id;
  instead record the raw string under `unmapped_category` in the report.

## Output (report mode)
- `scripts/audit/enrich_instore.json`: list of
  `{id, item_number, name, brand_id, proposed: {field: {current, value, source}}, unmapped_category?}`
  (include only products that have ≥1 proposed fill).
- `scripts/audit/enrich_instore.md`: a summary — total products with proposals, a
  per-field fill count table, the list of unmapped category strings (with counts), and
  a compact per-product table (item_number | name | fields being filled).
- Print the per-field counts to stdout too.

## --apply mode
1. Recompute proposals (same logic).
2. Write `scripts/audit/enrich_instore_backup.json`: for every product/field about to
   change, record `{id, item_number, field, old_value}` (for full reversibility).
3. `UPDATE products SET <only the proposed fields> ... WHERE id=%s`, set `updated_at=now()`.
4. Commit; print number of products and fields updated.

Keep it one self-contained file. No network. No new dependencies beyond psycopg + stdlib.
