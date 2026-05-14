## Incidecoder scraper

### Install
```bash
pip install -r requirements.txt
```

### Test one product (preview parsed JSON)
```bash
python scraper.py --run-test
```

### Discover + scrape with random delay/jitter and retries
```bash
python scraper.py --discover-incidecoder --discover-limit 100 --delay 1.0 --jitter 2.0 --timeout 30 --retries 4
```

### Logging
Each scraped product logs progress and key counts:
- product name
- brand
- number of overview ingredients
- number of ingredients explained entries

### Output
- JSONL: `data/products.jsonl`
- Raw HTML snapshots: `data/raw_html/*.html`
