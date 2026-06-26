# Product Enrichment Pipeline

This document explains the in-store product enrichment system: how it searches
for missing product facts, how evidence is staged, how AI/sentry review works,
and how replacement/merge recommendations are audited without unsafe automatic
overwrites.

## Goal

For every product marked `in_store=true`, fill missing or weak product facts such
as:

- `shot_count`
- `duration_seconds`
- `effects`
- `packing`
- `description`
- `category_id` when supported by a trusted path

The pipeline must work even when the product has no SKU or an unreliable SKU. It
uses all known product information: name, brand, category, existing shot count,
duration, effects, image/OCR context, and any item number if present.

## Core Principle

Scraping and applying are separated.

The scraper can be aggressive. It may collect noisy facts from search results,
retail pages, catalogs, brand pages, and JSON-LD metadata.

The database writer is conservative. It only writes facts that pass:

1. Ledger verification.
2. AI sentry approval.
3. Empty-field safety checks.

Existing DB values are not overwritten automatically. Replacement and merge cases
are only logged as recommendations for human review.

## Main Files

- `scripts/audit/scrape_enrich.py`
  Product-scoped web search and candidate extraction.

- `scripts/audit/evidence_ledger.py`
  Append-only evidence ledger, verification, reporting, and guarded apply.

- `scripts/audit/ai_enrich_sentry.py`
  Local/cloud AI review gate. Approves empty-field fills and can review filled
  fields for keep/replace/merge recommendations.

- `scripts/audit/enrich_layered_watch.py`
  Watcher that processes one product at a time: scrape, sentry, apply if safe.

- `scripts/audit/enrichment_review_report.py`
  Human audit viewer for denied, pending, conflicted, replacement, merge, and
  keep-current candidates.

- `scripts/audit/evidence_ledger.json`
  Current staged evidence and sentry decisions.

- `scripts/audit/ai_enrich_sentry_log.jsonl`
  Sentry review log with candidate values, source URLs, identity checks, and
  decisions.

- `scripts/audit/product_research/`
  Per-product scratch packets containing known inputs, queries used, URLs found,
  pages fetched, and candidate facts.

## Product-Scoped Flow

The watcher processes one product transaction at a time.

1. Select one in-store product that still has fillable gaps.
2. Build search queries from all known product info.
3. Search the web.
4. Fetch candidate pages.
5. Extract candidate facts from JSON-LD, labeled fields, regex patterns, meta
   descriptions, and visible text.
6. Write a per-product research packet.
7. Append candidate records to the evidence ledger.
8. Run ledger verification.
9. Run AI sentry for that same product.
10. Apply only verified + sentry-approved facts into empty DB fields.

The product transaction is keyed by SKU when available, otherwise by product UUID.

## Search Behavior

The scraper does not rely only on SKU.

When available, it searches with:

- Exact SKU + product name.
- Product name + brand.
- Exact quoted product name.
- Product name + known shot count.
- Product name + known duration.
- Product name + category.
- Product name + known effect terms.

This supports products where:

- SKU is missing.
- SKU is wrong.
- SKU is not indexed online.
- The only useful starting point is name plus one or two known facts.

## Evidence Ledger Records

Every candidate fact is stored with provenance.

Important fields:

- `product_id`
- `item_number`
- `name`
- `field`
- `value`
- `source`
- `url`
- `confidence`
- `identity_check`
- `status`
- `sentry_status`
- `sentry_reason`
- `current_value` for filled-field comparisons

The ledger is intentionally append-only for candidate evidence. It records both
good and bad candidates so the scraping process can be audited.

## Ledger Status Meanings

`pending`

The scraper found a candidate, but the ledger does not trust it yet. Usually this
means it is a single weak/medium-confidence source, a name-only match, or a page
where identity is not strong enough.

`verified`

The candidate passed ledger verification. This currently means either:

- Two distinct sources agree on the same normalized value.
- One high-confidence source has a strong identity check.

Strong identity usually means exact SKU, barcode, or strong product identity from
name + brand + another known fact.

`conflict`

The ledger found multiple trusted values for the same product field, but they
disagree. These must be reviewed. The system should not guess.

`applied`

The fact was written to the DB.

`rejected`

The candidate was structurally bad, unrelated, a no-candidates marker, or failed
review strongly enough that it should not be reconsidered without new evidence.

## What "Not Ledger-Verified" Means

When the sentry says:

`chosen candidate is not ledger-verified yet`

it means the model liked a candidate, but the candidate's ledger `status` was not
`verified`.

This usually happens when:

- Only one source has the value.
- The source matched by name but not exact SKU/barcode.
- The source may be a generic page or a name collision.
- The confidence score is below the automatic trust threshold.
- There is not enough agreement yet.

This is a safety stop. It does not mean the fact is wrong. It means the pipeline
needs more evidence or a human decision before applying it.

Use:

```powershell
python scripts/audit/enrichment_review_report.py --mode denied --contains "not ledger-verified" --limit 50
```

## AI Sentry Decisions

The sentry reviews grouped candidates for one product and one field.

For empty DB fields, possible outcomes are:

- `approved`
- `rejected`

Only `approved` candidates with ledger `status=verified` can be applied.

For already-filled DB fields, possible outcomes are:

- `keep_current`
- `replace_recommended`
- `merge_recommended`
- `rejected`

Filled-field review is advisory. It does not overwrite the DB.

## Replacement And Merge Review

The pipeline now supports comparing a candidate value against the current DB
value.

Use:

```powershell
python scripts/audit/ai_enrich_sentry.py --backend ollama --model qwen2.5:14b --ollama-host http://100.99.89.118:11434 --review-filled --limit 20
```

This logs recommendations but does not apply them.

Review replacement recommendations:

```powershell
python scripts/audit/enrichment_review_report.py --mode replace-recommended --limit 50
```

Review merge recommendations:

```powershell
python scripts/audit/enrichment_review_report.py --mode merge-recommended --limit 50
```

Review keep-current decisions:

```powershell
python scripts/audit/enrichment_review_report.py --mode keep-current --limit 50
```

## Applying Facts

The normal apply path writes only empty fields.

It requires:

- `status=verified`
- `sentry_status=approved`
- DB field is empty

Run manually:

```powershell
python scripts/audit/evidence_ledger.py apply
```

The watcher does this automatically after sentry review, but only for empty
fields that passed both gates.

## Watcher

Start the normal fill-empty watcher:

```powershell
python -u scripts/audit/enrich_layered_watch.py --backend ollama --model qwen2.5:14b --ollama-host http://100.99.89.118:11434 --vision --vision-steps ocr,codes,vlm --sleep 45 --sentry-limit 20
```

The watcher:

- Processes one product at a time.
- Scrapes that product.
- Sends only that product's candidates to sentry.
- Applies only safe empty-field facts.
- Sleeps between products.
- Recovers from transient DB/search failures on the next loop.

It writes:

- `scripts/audit/enrich_layered_watch.out`
- `scripts/audit/enrich_layered_watch.err`

## Audit Commands

Summary of denied candidates:

```powershell
python scripts/audit/enrichment_review_report.py --mode denied --summary
```

Exact denied candidates:

```powershell
python scripts/audit/enrichment_review_report.py --mode denied --limit 50
```

Sentry-rejected candidates:

```powershell
python scripts/audit/enrichment_review_report.py --mode sentry-rejected --limit 50
```

Pending candidates:

```powershell
python scripts/audit/enrichment_review_report.py --mode pending --limit 50
```

Conflicts:

```powershell
python scripts/audit/enrichment_review_report.py --mode conflict --limit 50
```

No-candidate products:

```powershell
python scripts/audit/enrichment_review_report.py --mode no-candidates --limit 50
```

Filter by SKU:

```powershell
python scripts/audit/enrichment_review_report.py --mode denied --sku NN5059 --limit 0
```

Search inside values, reasons, URLs, and sources:

```powershell
python scripts/audit/enrichment_review_report.py --mode denied --contains "ledger-verified" --limit 50
```

## Known Safety Behavior

The system is intentionally strict.

It rejects or holds:

- Generic page text.
- Marketing text extracted as effects.
- Placeholder labels such as `Effects Holders`.
- HTML/CSS snippets.
- Name-only matches with possible collisions.
- Non-fireworks pages matching a generic SKU.
- Conflicting trusted sources.
- Candidates for existing fields unless explicitly reviewed as replacement or
  merge recommendations.

This reduces wrong data writes but may hold some accurate facts. Use the audit
viewer to inspect those cases.

## Human Review Workflow

Recommended review process:

1. Run denied summary.
2. Inspect `not ledger-verified` cases.
3. Inspect conflicts.
4. Inspect replacement recommendations.
5. For good candidates, either add more evidence from another source or make a
   deliberate manual DB update.

Useful commands:

```powershell
python scripts/audit/enrichment_review_report.py --mode denied --summary
python scripts/audit/enrichment_review_report.py --mode denied --contains "not ledger-verified" --limit 50
python scripts/audit/enrichment_review_report.py --mode conflict --limit 50
python scripts/audit/enrichment_review_report.py --mode replace-recommended --limit 50
python scripts/audit/enrichment_review_report.py --mode merge-recommended --limit 50
```

## Current Non-Goals

The pipeline does not currently:

- Auto-overwrite existing DB values.
- Auto-merge descriptions/effects.
- Trust a local model without ledger evidence.
- Treat name-only matches as safe enough for DB writes.
- Auto-resolve conflicts.

These are deliberate safety choices.

## Future Improvements

Likely next improvements:

- Add a manual approval command for specific ledger record IDs.
- Add a merge applier that writes only after human approval.
- Add source-specific trust policies.
- Improve page extraction for manufacturer pages that hide real details in
  scripts or image text.
- Use product package images and OCR more heavily for identity confirmation.
- Add retry/backoff around transient Postgres connection timeouts.
