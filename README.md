## Incidecoder scraper

This version focuses on Incidecoder product pages and supports sitemap-based URL discovery.

### Install

```bash
pip install -r requirements.txt
```

### Discover + scrape products

```bash
python scraper.py --discover-incidecoder --discover-limit 100 --delay 1.5
```

### Scrape specific product URLs

```bash
python scraper.py "https://incidecoder.com/products/niod-non-acid-acid-precursor-15"
```

### Output

- JSONL: `data/products.jsonl`
- Raw HTML snapshots: `data/raw_html/*.html`

The parser extracts:
- product name + brand
- ingredients overview
- highlights
- **skim table**
- **ingredients explained section** (expanded content present in page HTML)
