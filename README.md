## Incidecoder scraper

### Install
```bash
pip install -r requirements.txt
```

### Test one product
```bash
python scraper.py --run-test
```

### Manual sitemap fallback (recommended when index discovery times out)
```bash
python scraper.py --sitemap-url https://incidecoder.com/sitemap-products.0.xml --discover-limit 100
```

### Local sitemap file fallback
```bash
python scraper.py --sitemap-file sitemap-products.0.xml --discover-limit 100
```

### Full index discovery
```bash
python scraper.py --discover-incidecoder --discover-limit 100 --delay 1.0 --jitter 2.0 --timeout 30 --retries 4
```

### Output
- JSONL: `data/products.jsonl`
- Raw HTML snapshots: `data/raw_html/*.html`
