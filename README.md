## Incidecoder scraper (fast CSV pipeline)

### Install
```bash
pip install -r requirements.txt
```

### Fast run from large CSV
```bash
python scraper.py \
  --input-csv product_links.csv \
  --input-column product_link \
  --workers 8 \
  --delay 0.4 --jitter 0.6 --timeout 20 --retries 3 \
  --out-products-csv data/products_full.csv \
  --out-ingredients-csv data/ingredients_full.csv \
  --out-jsonl data/products.jsonl \
  --image-dir data/product_images \
  --no-download-images   # use this for faster metadata-only pass
```

### Outputs
- `data/products_full.csv`
- `data/ingredients_full.csv`
- `data/products.jsonl`
- `data/raw_html/*.html`
- `data/product_images/*`
- `data/blocked_by_robots.csv`

Image files are named `<product-name-slug>-<short-hash>.<ext>`.


Use `--no-download-images` to skip image downloads, and later rerun with image downloads enabled for shortlisted URLs.
