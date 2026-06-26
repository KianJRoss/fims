# BUILD TASK: Tier-2 video cascade (yt-dlp metadata enrichment + stricter scoring)

Create ONE new file: `scripts/audit/video_cascade_t2.py`. Do NOT modify any other file.
Do NOT run it. Do NOT make network/DB calls during the build. Just write the script.
It will be run by a human afterwards (it does the yt-dlp network calls itself).

## Purpose
Tier 1 (`video_cascade.py`, already built) classifies in-store unconfirmed videos by TITLE only and
is too lenient. Tier 2 enriches each candidate with real YouTube metadata via `yt-dlp` and re-scores
with stricter rules, then recommends a SINGLE best video to confirm per product (or NONE → flag for
sourcing) and a quarantine list. NO DB WRITES — report only.

## Scope (read-only DB)
- `DB_URL = os.environ.get("DATABASE_URL", "postgresql://fims:fims@100.73.208.99:5432/fims")`
- psycopg v3, connect read-only (`conn.read_only = True`; do NOT use conn.transaction(readonly=...)).
- Select products WHERE in_store=true that have NO curated video (no product_videos row with
  source='instore_playlist' or (source='LEGACY_KIOSK' AND confirmed=true)). For each such product,
  its product_videos WHERE confirmed=false AND COALESCE(source,'') NOT IN
  ('instore_playlist','LEGACY_KIOSK') AND youtube_id IS NOT NULL.
- Columns available: products(id,item_number,name,brand_id), product_brands(id,name),
  product_videos(id,product_id,youtube_id,title,url,source,confirmed,is_primary).

## Reuse Tier-1 helpers
Import from the sibling module to avoid drift:
`from video_cascade import normalize, tokenize, STOPWORDS, BLOCKLIST` (or whatever the actual
public names are — open video_cascade.py and import its real normalize/tokenize/blocklist; if a name
differs, adapt). If a needed helper isn't importable, copy it minimally with a comment.

## yt-dlp enrichment (the network part)
For each unique youtube_id, fetch metadata with yt-dlp via subprocess:
  yt-dlp --no-warnings --skip-download --print
    "%(id)s\t%(channel)s\t%(channel_id)s\t%(duration)s\t%(view_count)s\t%(upload_date)s\t%(availability)s\t%(live_status)s\t%(title)s"
    "https://youtu.be/<id>"
- Use subprocess.run with a per-video timeout (~45s). If returncode != 0 or output empty → record
  `{"status":"dead"}` (video removed/private/unavailable).
- Parse the tab-separated line; coerce duration/view_count to int when numeric ("NA"/"None"→None).
- CACHE: `scripts/audit/video_cascade_t2_cache.json` keyed by youtube_id. On start, load cache and
  SKIP ids already present (so reruns are cheap). Add `--refresh` flag to force re-fetch all.
  Write the cache incrementally (after every N fetches and at the end) so a crash doesn't lose work.
  Print progress to stderr (e.g. "fetch 12/60 <id> ...").

## Tier-2 scoring (per candidate video)
Start from T1 title signals (name_overlap_ratio, item_match, brand_match, fireworks_ctx, blocklist).
Then layer metadata, producing a numeric `score` and `reason`:
- DEAD (status dead)                       -> decision QUARANTINE, reason "unavailable on youtube".
- item# in title                           -> +strong (this is the surest signal).
- duration: None -> neutral; 5..180s -> +; 181..360s -> small penalty; >360s -> strong penalty
  ("likely compilation"); <5s -> penalty.
- channel match: if a brand-name token (from the product's brand, lowercased) OR the product name's
  distinctive tokens appear in the channel name -> + (e.g. official "World Class Fireworks",
  "Sunwing"). Keep a small KNOWN_OFFICIAL set (worldclass, sunwing, jakes, black cat, brothers,
  great grizzly, mad ox) tunable at top.
- name_overlap_ratio >= 0.6 -> +; == 0 -> strong penalty.
- blocklist hit and low overlap -> QUARANTINE.
Make all weights/thresholds module constants at the top so they're easy to tune.

Decision buckets per video: CONFIRM-CANDIDATE / QUARANTINE / UNCERTAIN based on score thresholds.

## Per-product recommendation
- Rank that product's candidates by score desc.
- RECOMMEND the top one as the confirm IF its score >= CONFIRM_THRESHOLD AND name_overlap_ratio>0;
  else recommend NONE and flag the product "needs sourcing / manual".
- Everything not recommended that scores below QUAR_THRESHOLD (or is dead/compilation/wrong-product)
  goes to that product's quarantine list. Middle scores -> uncertain.

## Output (no DB writes)
- `scripts/audit/video_cascade_t2.json`: list of products, each
  `{product_id,item_number,name,brand,recommend:{video_id,youtube_id,title,score,channel,duration} | null,
    quarantine:[...], uncertain:[...], all:[...]}` where each video entry carries the metadata + score + reason.
- `scripts/audit/video_cascade_t2.md`: readable per-product summary; mark RECOMMEND, QUARANTINE,
  UNCERTAIN; show channel/duration/views inline; UTF-8 safe (never crash on non-ASCII titles).
- Print bucket totals to stderr at the end.

## CLI
- `python scripts/audit/video_cascade_t2.py` -> fetch (using cache) + score + write artifacts.
- `--refresh` -> ignore cache, re-fetch all.
- `--product <item_or_id>` -> limit to one product.
- `--no-fetch` -> use only cached metadata (skip network; missing ids treated as unknown/neutral).
Single self-contained file: stdlib + psycopg + the video_cascade import; yt-dlp invoked as subprocess.
