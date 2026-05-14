## Incidecoder scraper (CSV pipeline)

### Install
```bash
pip install -r requirements.txt
```

### Run from your 180k links CSV
```bash
python scraper.py \
  --input-csv product_links.csv \
  --input-column product_link \
  --out-products-csv data/products_full.csv \
  --out-ingredients-csv data/ingredients_full.csv \
  --out-jsonl data/products.jsonl \
  --image-dir data/product_images \
  --delay 2.0 --jitter 3.0 --timeout 45 --retries 6
```

### Outputs
- `data/products_full.csv`: one row per product
- `data/ingredients_full.csv`: flattened ingredient + explained text rows
- `data/products.jsonl`: full structured product payloads
- `data/raw_html/*.html`: raw snapshots
- `data/product_images/*`: downloaded product images

### Notes
- This script is designed for compliant scraping and respects `robots.txt` by default.
- If a URL is blocked by robots policy, it is skipped and logged.


Image files are stored as `<product-name-slug>-<short-hash>.<ext>` for easier S3-style object keying.
