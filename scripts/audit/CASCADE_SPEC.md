# BUILD TASK: in-store video weed-out cascade (Tier 1, read-only)

Create ONE new Python file: `scripts/audit/video_cascade.py`. Do NOT modify any other file.
Do NOT run the script, do NOT make network/DB calls, do NOT write to the database. Just write the script.

## Purpose
FIMS has ~419 UNCONFIRMED YouTube videos auto-matched (loosely) to the 96 in-store products.
Many are unrelated junk (e.g. firework "49ER" pulled NFL clips like "#49ers pregame vs Bears").
This script classifies each in-store product's unconfirmed videos so a human can review which to
keep vs quarantine. This is TIER 1 of a progressive cascade (cheap title-based pass). Build T1 fully;
scaffold T2/T3 as clearly-marked NotImplemented stubs with docstrings describing intended behavior
(T2 = enrich via yt-dlp metadata: channel/duration/description; T3 = vision frame-check via
scripts/vision/). No DB writes anywhere in this version.

## DB (read-only)
- `DB_URL = os.environ.get("DATABASE_URL", "postgresql://fims:fims@100.73.208.99:5432/fims")`
- Use `psycopg` (v3). Connect read-only; SELECT only.
- Relevant tables/columns (verified):
  - products: id (varchar uuid), item_number, name, in_store (bool), brand_id, category_id
  - product_brands: id, name   (join brand_id -> name)
  - product_videos: id (int), product_id, title, youtube_id, url, search_query, source,
    confirmed (bool), is_primary (bool), duration_seconds (mostly NULL — do NOT rely on it)
- Scope: products WHERE in_store = true. For each, its product_videos WHERE confirmed = false.
- Sources `instore_playlist` and `LEGACY_KIOSK` are CURATED/trusted — if such a row is unconfirmed
  it should be classed KEEP with reason "curated source", never quarantined.

## Tier 1 logic (title-based)
For each unconfirmed video, compute a decision in {KEEP, QUARANTINE, UNCERTAIN} with a numeric
score and a human-readable reason. Normalize text: lowercase, strip non-alphanumerics to spaces,
collapse whitespace. Tokenize.

Signals:
- name_match: count of product-name tokens (ignore stopwords/very short tokens <=2 chars) present
  in the title. name_overlap_ratio = matched / total_name_tokens.
- item_match: product.item_number (if present, non-empty) appears in the title (case-insensitive).
- brand_match: brand name token(s) appear in title.
- fireworks_ctx: title contains any of {fireworks, firework, cake, 500g, 200g, repeater, fountain,
  shells, finale, mortar, pyro, 25 shot, 16 shot, "shot"} (word-ish).
- BLOCKLIST (strong non-fireworks signal): {nfl, football, quarterback, touchdown, stadium, pregame,
  vs bears, super bowl, basketball, nba, soccer, goal, highlights, gameplay, trailer, movie, song,
  official music video, lyrics, news at, breaking news, weather, vlog, unboxing of a phone}. Make it
  a tunable list at top of file. Match as substrings on normalized title.

Decision rules (tunable thresholds as module constants):
- If curated source -> KEEP ("curated source").
- Else if item_match -> KEEP ("item# in title").
- Else if BLOCKLIST hit AND name_overlap_ratio < 0.6 -> QUARANTINE (reason names the blocklist hit).
- Else if name_overlap_ratio >= 0.6 AND fireworks_ctx -> KEEP ("strong name + fireworks context").
- Else if name_overlap_ratio == 0 -> QUARANTINE ("no product-name overlap").
- Else -> UNCERTAIN (carry the partial signals in the reason).

## Output (write BOTH; no DB writes)
- `scripts/audit/video_cascade_t1.json`: list of products, each:
  `{product_id, item_number, name, brand, n_unconfirmed, keep:[...], quarantine:[...], uncertain:[...]}`
  where each video entry is `{video_id, youtube_id, title, score, reason}`.
- `scripts/audit/video_cascade_t1.md`: readable summary — totals per bucket, then per product a short
  table. Handle non-ASCII titles safely (write files as UTF-8; never crash on encoding).

## CLI
- `python scripts/audit/video_cascade.py` -> runs T1, writes artifacts, prints bucket totals.
- `--tier {1,2,3}` (default 1). 2 and 3 raise NotImplementedError with a clear message for now.
- `--product <item_or_id>` optional filter to one product (for spot checks).
- Robust: if a product has no unconfirmed videos, skip it. Use parameterized SQL. UTF-8 everywhere.

Keep it a single self-contained file, standard library + psycopg only. Clear constants at top so the
thresholds/blocklist/keeplist are easy to tune after we review the first run.
