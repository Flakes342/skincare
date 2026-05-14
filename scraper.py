#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, hashlib, json, random, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

USER_AGENT = "SkincareResearchBot/0.5 (+contact: you@example.com)"
HEADERS = {"User-Agent": USER_AGENT}

@dataclass
class ProductRecord:
    source: str
    url: str
    name: str | None = None
    brand: str | None = None
    skim_table: list[dict[str, str]] | None = None
    ingredients_explained: list[dict[str, str]] | None = None
    image_url: str | None = None
    extra: dict | None = None

class SafeSession:
    def __init__(self, delay_seconds=0.4, jitter_seconds=0.6, timeout_seconds=20, max_retries=3):
        self.s = requests.Session(); self.s.headers.update(HEADERS)
        self.delay, self.jitter, self.timeout, self.max_retries = delay_seconds, jitter_seconds, timeout_seconds, max_retries
        self.last = 0.0; self.robots={}; self.lock = threading.Lock()
    def _sleep_locked(self):
        wait = max(0.0, self.delay - (time.time() - self.last)) + random.uniform(0, self.jitter)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
    def _rp(self, base):
        if base in self.robots: return self.robots[base]
        rp = RobotFileParser(); rp.set_url(urljoin(base, '/robots.txt'))
        try: rp.read()
        except Exception: pass
        self.robots[base] = rp; return rp
    def get(self, url, obey_robots=True):
        p = urlparse(url); base = f"{p.scheme}://{p.netloc}"
        if obey_robots:
            rp = self._rp(base)
            if not (rp.can_fetch(USER_AGENT, url) or rp.can_fetch('*', url)):
                raise PermissionError(f"Blocked by robots.txt: {url}")
        last_err = None
        for i in range(1, self.max_retries + 1):
            try:
                with self.lock:
                    self._sleep_locked()
                r = self.s.get(url, timeout=self.timeout)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last_err = e
                backoff = min(20, (2 ** (i - 1)) + random.uniform(0.1, 1.0))
                print(f"WARN ({i}/{self.max_retries}) {url} -> {e}; backoff {backoff:.1f}s")
                time.sleep(backoff)
        raise last_err

def slugify(text: str, max_len: int = 80) -> str:
    text = (text or 'product').strip().lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return (text or 'product')[:max_len]

def parse_incidecoder(url: str, html: str) -> ProductRecord:
    soup = BeautifulSoup(html, 'html.parser')
    def txt(n): return n.get_text(' ', strip=True) if n else None
    name = ' '.join((txt(soup.select_one('h1')) or '').split())
    brand = txt(soup.select_one("a[href*='/brands/']"))

    skim=[]; headers=['Ingredient name','what-it-does','irr., com.','ID-Rating']
    table=soup.select_one('table.product-skim')
    if table:
        hs=[txt(x) or '' for x in table.select('tr th')]
        if len(hs)>=4: headers=hs[:4]
        for tr in table.select('tr'):
            tds=[txt(td) or '' for td in tr.select('td')]
            if len(tds)>=4:
                skim.append({headers[0]:tds[0],headers[1]:tds[1],headers[2]:tds[2],headers[3]:tds[3]})

    image_url=None
    for img in soup.select('#product-main-image picture img, #product-main-image img, .imgcontainer picture img, .imgcontainer img'):
        src=(img.get('src') or img.get('data-src') or '').strip()
        if src and not any(x in src.lower() for x in ['/logo','logo.','favicon','icon','sprite']):
            image_url=src; break

    explained=[]
    container=soup.select_one('#ingredients-explained, .ingredlist-long')
    if container:
        for h in container.select('h3,h4,.ingredient-name'):
            desc=[]; n=h.find_next_sibling()
            while n and n.name not in ('h3','h4'):
                if n.name=='p': desc.append(txt(n) or '')
                n=n.find_next_sibling()
            explained.append({'ingredient':txt(h) or '', 'description':' '.join(desc).strip()})

    return ProductRecord('incidecoder', url, name, brand, skim or None, explained or None, image_url, {'title': txt(soup.title)})

def read_urls_from_csv(path: str, column: str) -> list[str]:
    with open(path, newline='', encoding='utf-8') as f:
        return [row[column].strip() for row in csv.DictReader(f) if row.get(column,'').strip()]

def download_product_image(sess: SafeSession, image_url: str | None, product_url: str, product_name: str, out_dir: Path, obey_robots=True) -> str | None:
    if not image_url: return None
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(image_url).path).suffix or '.jpg'
    fname = f"{slugify(product_name)}-{hashlib.sha1(product_url.encode()).hexdigest()[:8]}{ext}"
    path = out_dir / fname
    if path.exists(): return str(path)
    try:
        path.write_bytes(sess.get(image_url, obey_robots=obey_robots).content)
        return str(path)
    except Exception as e:
        print(f"WARN image download failed for {product_url}: {e}")
        return None

def append_ingredient_rows(ingredient_csv: Path, rec: dict, lock: threading.Lock):
    new_file = not ingredient_csv.exists()
    with lock, ingredient_csv.open('a', newline='', encoding='utf-8') as f:
        w=csv.writer(f)
        if new_file:
            w.writerow(['product_url','product_name','brand','ingredient_name','what_it_does','irr_com','id_rating','description'])
        for row in rec.get('skim_table') or []:
            w.writerow([rec.get('url'),rec.get('name'),rec.get('brand'),row.get('Ingredient name',''),row.get('what-it-does',''),row.get('irr., com.',''),row.get('ID-Rating',''),''])
        for row in rec.get('ingredients_explained') or []:
            w.writerow([rec.get('url'),rec.get('name'),rec.get('brand'),row.get('ingredient',''),'','','',row.get('description','')])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-csv', default='')
    ap.add_argument('--input-column', default='product_link')
    ap.add_argument('--out-jsonl', default='data/products.jsonl')
    ap.add_argument('--out-products-csv', default='data/products_full.csv')
    ap.add_argument('--out-ingredients-csv', default='data/ingredients_full.csv')
    ap.add_argument('--image-dir', default='data/product_images')
    ap.add_argument('--download-images', action='store_true', default=True, help='Download product images')
    ap.add_argument('--no-download-images', action='store_false', dest='download_images', help='Skip image downloads')
    ap.add_argument('--blocked-log-csv', default='data/blocked_by_robots.csv')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--delay', type=float, default=0.4); ap.add_argument('--jitter', type=float, default=0.6)
    ap.add_argument('--timeout', type=int, default=20); ap.add_argument('--retries', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0); ap.add_argument('--ignore-robots', action='store_true')
    ap.add_argument('urls', nargs='*')
    a=ap.parse_args()

    urls=list(a.urls)
    if a.input_csv: urls.extend(read_urls_from_csv(a.input_csv, a.input_column))
    urls=sorted(set(urls))
    if a.limit>0: urls=urls[:a.limit]
    if not urls:
        print('ERR no URLs provided'); return

    sess=SafeSession(a.delay,a.jitter,a.timeout,a.retries)
    out_jsonl=Path(a.out_jsonl); out_jsonl.parent.mkdir(parents=True,exist_ok=True)
    products_csv=Path(a.out_products_csv); ingredients_csv=Path(a.out_ingredients_csv)
    blocked_csv=Path(a.blocked_log_csv); blocked_csv.parent.mkdir(parents=True, exist_ok=True)
    raw_dir=Path('data/raw_html'); raw_dir.mkdir(parents=True, exist_ok=True)

    io_lock=threading.Lock()
    if not products_csv.exists(): products_csv.write_text('url,name,brand,image_url,image_path,raw_html_path\n', encoding='utf-8')
    if not blocked_csv.exists(): blocked_csv.write_text('url,reason\n', encoding='utf-8')

    ok=blocked=errs=0
    def work(url: str):
        html=sess.get(url,obey_robots=not a.ignore_robots).text
        raw_path=raw_dir/f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.html"; raw_path.write_text(html,encoding='utf-8')
        rec=asdict(parse_incidecoder(url,html)); rec['raw_html_path']=str(raw_path)
        rec['image_path']=None
        if a.download_images:
            rec['image_path']=download_product_image(sess,rec.get('image_url'),url,rec.get('name') or '',Path(a.image_dir),obey_robots=not a.ignore_robots)
        return rec

    with ThreadPoolExecutor(max_workers=max(1,a.workers)) as ex:
        futs={ex.submit(work,u):u for u in urls}
        for i,f in enumerate(as_completed(futs),start=1):
            u=futs[f]
            try:
                rec=f.result(); ok+=1
                with io_lock:
                    with out_jsonl.open('a',encoding='utf-8') as jf: jf.write(json.dumps(rec,ensure_ascii=False)+'\n')
                    with products_csv.open('a', newline='', encoding='utf-8') as pf: csv.writer(pf).writerow([rec['url'],rec.get('name'),rec.get('brand'),rec.get('image_url'),rec.get('image_path'),rec['raw_html_path']])
                append_ingredient_rows(ingredients_csv, rec, io_lock)
                print(f"OK [{i}/{len(urls)}] {rec.get('name') or 'Unknown'}")
            except PermissionError as e:
                blocked+=1
                with io_lock, blocked_csv.open('a', newline='', encoding='utf-8') as bf: csv.writer(bf).writerow([u,str(e)])
                print(f"SKIP robots block: {u}")
            except Exception as e:
                errs+=1
                print(f"ERR {u} -> {e}")

    print(f"DONE total={len(urls)} ok={ok} blocked={blocked} errors={errs}")

if __name__=='__main__': main()
