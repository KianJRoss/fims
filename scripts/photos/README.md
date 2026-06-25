# Photo Audit Source Images

`scripts/photos/source_images.py` collects candidate replacement images for selected products and writes per-product manifests under `media/photo_audit/`.

## What it does

- Reads products from PostgreSQL with `SELECT` only.
- Pulls candidate images from:
  - gotfireworks.com
  - worldclassfireworks.com
  - DDGS image search
- Writes:
  - `media/photo_audit/{product_id}/{source}_{i}.{ext}`
  - `media/photo_audit/{product_id}/manifest.json`

## Usage

```bash
python scripts/photos/source_images.py --sample 2
python scripts/photos/source_images.py --brand "World Class" --limit 10
python scripts/photos/source_images.py --ids a,b,c
```

## Notes

- The script is read-only against the database.
- Existing downloaded files are skipped.
- `--web-top-n` controls how many DDGS image results are collected per product.
