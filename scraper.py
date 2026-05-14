#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, random, re, time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

USER_AGENT = "SkincareResearchBot/0.3 (+contact: you@example.com)"
HEADERS = {"User-Agent": USER_AGENT}

@dataclass
class ProductRecord:
    source: str
    url: str
    name: str | None = None
    brand: str | None = None
    ingredients_overview: list[str] | None = None
    highlights: dict[str, list[str]] | None = None
    skim_table: list[dict[str, str]] | None = None
    ingredients_explained: list[dict[str, str]] | None = None
    extra: dict | None = None

class SafeSession:
    def __init__(self, delay_seconds: float = 1.0, jitter_seconds: float = 2.0, timeout_seconds: int = 30, max_retries: int = 4):
        self.s = requests.Session(); self.s.headers.update(HEADERS)
        self.delay = delay_seconds; self.jitter = jitter_seconds; self.timeout = timeout_seconds; self.max_retries = max_retries
        self.last = 0.0; self.robots={}

    def _sleep(self):
        min_wait = max(0.0, self.delay - (time.time() - self.last))
        jitter = random.uniform(0, self.jitter) if self.jitter > 0 else 0
        time.sleep(min_wait + jitter)

    def _rp(self, base: str):
        if base in self.robots: return self.robots[base]
        rp=RobotFileParser(); rp.set_url(urljoin(base,'/robots.txt'))
        try: rp.read()
        except Exception: pass
        self.robots[base]=rp; return rp

    def get(self, url:str, obey_robots=True):
        p=urlparse(url); base=f"{p.scheme}://{p.netloc}"
        if obey_robots and not self._rp(base).can_fetch(USER_AGENT,url):
            raise PermissionError(f"Blocked by robots.txt: {url}")

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._sleep()
                r=self.s.get(url,timeout=self.timeout)
                self.last=time.time()
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last_err = e
                backoff = min(20, (2 ** (attempt - 1)) + random.uniform(0.2, 1.5))
                print(f"WARN request failed ({attempt}/{self.max_retries}) {url}: {e}. retrying in {backoff:.1f}s")
                time.sleep(backoff)
        raise last_err

def parse_sitemap_xml(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    return [n.text.strip() for n in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc') if n.text]

def discover_incidecoder_product_urls(sess: SafeSession, obey_robots=True) -> list[str]:
    index = sess.get('https://incidecoder.com/sitemap-index.xml', obey_robots=obey_robots).text
    nested = parse_sitemap_xml(index)
    product_maps = [u for u in nested if '/sitemaps/products-' in u or 'products' in u]
    out=[]
    for sm in product_maps:
        xml=sess.get(sm, obey_robots=obey_robots).text
        out.extend([u for u in parse_sitemap_xml(xml) if '/products/' in u])
    return sorted(set(out))

def _txt(n): return n.get_text(' ', strip=True) if n else None

def parse_incidecoder(url: str, html: str) -> ProductRecord:
    soup = BeautifulSoup(html, 'html.parser')
    name = ' '.join((_txt(soup.select_one("h1")) or '').split())
    brand = _txt(soup.select_one("a[href*='/brands/']"))
    overview = [_txt(a) for a in soup.select('div.ingredinfobox a, .mt16 a') if _txt(a)]

    skim=[]
    table = soup.select_one('table.product-skim')
    headers = ['Ingredient name', 'what-it-does', 'irr., com.', 'ID-Rating']
    if table:
        head_cells = [_txt(x) or '' for x in table.select('tr th')]
        if len(head_cells) >= 4:
            headers = head_cells[:4]
        for tr in table.select('tr'):
            tds=[_txt(td) or '' for td in tr.select('td')]
            if len(tds) >= 4:
                skim.append({headers[0]: tds[0], headers[1]: tds[1], headers[2]: tds[2], headers[3]: tds[3]})

    explained=[]
    container=soup.select_one('#ingredients-explained, .ingredlist-long')
    if container:
        for h in container.select('h3, h4, .ingredient-name'):
            desc=[]; nxt=h.find_next_sibling()
            while nxt and nxt.name not in ('h3','h4'):
                if nxt.name=='p': desc.append(_txt(nxt) or '')
                nxt=nxt.find_next_sibling()
            explained.append({'ingredient':_txt(h) or '', 'description':' '.join(desc).strip()})

    return ProductRecord(source='incidecoder',url=url,name=name,brand=brand,
        ingredients_overview=overview or None,
        skim_table=skim or None, ingredients_explained=explained or None,
        extra={'title': _txt(soup.title), 'show_more_hint': bool(soup.select_one('div.showmore-link'))})

def pick_parser(url:str):
    if 'incidecoder.com' in urlparse(url).netloc.lower(): return parse_incidecoder
    raise ValueError(f'No parser for host: {url}')

def save_raw(output_dir: Path, url: str, html: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    p=output_dir/f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.html"; p.write_text(html,encoding='utf-8'); return p

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('urls', nargs='*')
    ap.add_argument('--discover-incidecoder', action='store_true')
    ap.add_argument('--discover-limit', type=int, default=0)
    ap.add_argument('--test-url', default='https://incidecoder.com/products/niod-non-acid-acid-precursor-15')
    ap.add_argument('--run-test', action='store_true', help='Scrape only test URL and print parsed JSON preview')
    ap.add_argument('--out', default='data/products.jsonl'); ap.add_argument('--raw-dir', default='data/raw_html')
    ap.add_argument('--delay', type=float, default=1.0); ap.add_argument('--jitter', type=float, default=2.0)
    ap.add_argument('--timeout', type=int, default=30); ap.add_argument('--retries', type=int, default=4)
    ap.add_argument('--ignore-robots', action='store_true')
    a=ap.parse_args(); sess=SafeSession(a.delay, a.jitter, a.timeout, a.retries)

    if a.run_test:
        html=sess.get(a.test_url, obey_robots=not a.ignore_robots).text
        rec=asdict(parse_incidecoder(a.test_url, html))
        print(json.dumps(rec, ensure_ascii=False, indent=2)[:8000])
        return

    urls=list(a.urls)
    if a.discover_incidecoder:
        urls.extend(discover_incidecoder_product_urls(sess, obey_robots=not a.ignore_robots))
    urls=sorted(set(urls))
    if a.discover_limit>0: urls=urls[:a.discover_limit]
    out=Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('a',encoding='utf-8') as f:
        for i, url in enumerate(urls, start=1):
            try:
                html=sess.get(url, obey_robots=not a.ignore_robots).text
                raw=save_raw(Path(a.raw_dir),url,html)
                rec=asdict(pick_parser(url)(url,html)); rec['raw_html_path']=str(raw)
                f.write(json.dumps(rec,ensure_ascii=False)+'\n')
                print(f"OK [{i}/{len(urls)}] {rec.get('name') or 'Unknown'} | brand={rec.get('brand')} | skim_rows={len(rec.get('skim_table') or [])} | explained={len(rec.get('ingredients_explained') or [])}")
            except Exception as e:
                print('ERR',url,'->',e)

if __name__=='__main__': main()
