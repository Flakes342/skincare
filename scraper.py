#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, hashlib, json, random, re, time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

USER_AGENT = "SkincareResearchBot/0.4 (+contact: you@example.com)"
HEADERS = {"User-Agent": USER_AGENT}

@dataclass
class ProductRecord:
    source: str
    url: str
    name: str | None = None
    brand: str | None = None
    ingredients_overview: list[str] | None = None
    skim_table: list[dict[str, str]] | None = None
    ingredients_explained: list[dict[str, str]] | None = None
    image_url: str | None = None
    extra: dict | None = None

class SafeSession:
    def __init__(self, delay_seconds=2.0, jitter_seconds=3.0, timeout_seconds=45, max_retries=6):
        self.s = requests.Session(); self.s.headers.update(HEADERS)
        self.delay, self.jitter, self.timeout, self.max_retries = delay_seconds, jitter_seconds, timeout_seconds, max_retries
        self.last = 0.0; self.robots={}
    def _sleep(self):
        wait=max(0.0,self.delay-(time.time()-self.last))+random.uniform(0,self.jitter)
        time.sleep(wait)
    def _rp(self,base):
        if base in self.robots: return self.robots[base]
        rp=RobotFileParser(); rp.set_url(urljoin(base,'/robots.txt'))
        try: rp.read()
        except Exception: pass
        self.robots[base]=rp; return rp
    def get(self,url,obey_robots=True):
        p=urlparse(url); base=f"{p.scheme}://{p.netloc}"
        if obey_robots:
            rp=self._rp(base)
            if not (rp.can_fetch(USER_AGENT,url) or rp.can_fetch('*',url)):
                raise PermissionError(f"Blocked by robots.txt: {url}")
        last_err=None
        for i in range(1,self.max_retries+1):
            try:
                self._sleep(); r=self.s.get(url,timeout=self.timeout); self.last=time.time(); r.raise_for_status(); return r
            except requests.RequestException as e:
                last_err=e; backoff=min(30,(2**(i-1))+random.uniform(0.2,1.8))
                print(f"WARN ({i}/{self.max_retries}) {url} -> {e}; sleep {backoff:.1f}s")
                time.sleep(backoff)
        raise last_err

def parse_sitemap_xml(xml_text:str)->list[str]:
    root=ET.fromstring(xml_text)
    return [n.text.strip() for n in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc') if n.text]

def parse_incidecoder(url:str, html:str)->ProductRecord:
    soup=BeautifulSoup(html,'html.parser')
    def txt(n): return n.get_text(' ',strip=True) if n else None
    name=' '.join((txt(soup.select_one('h1')) or '').split())
    brand=txt(soup.select_one("a[href*='/brands/']"))
    skim=[]; table=soup.select_one('table.product-skim'); headers=['Ingredient name','what-it-does','irr., com.','ID-Rating']
    if table:
        hs=[txt(x) or '' for x in table.select('tr th')]
        if len(hs)>=4: headers=hs[:4]
        for tr in table.select('tr'):
            tds=[txt(td) or '' for td in tr.select('td')]
            if len(tds)>=4: skim.append({headers[0]:tds[0],headers[1]:tds[1],headers[2]:tds[2],headers[3]:tds[3]})
    image = None
    # prefer product-main image area and skip common site/logo assets
    candidates = soup.select('#product-main-image picture img, #product-main-image img, .imgcontainer picture img, .imgcontainer img')
    for img in candidates:
        src = (img.get('src') or img.get('data-src') or '').strip()
        if not src:
            continue
        lower = src.lower()
        if any(x in lower for x in ['/logo', 'logo.', 'favicon', 'icon', 'sprite']):
            continue
        image = src
        break

    explained=[]
    container=soup.select_one('#ingredients-explained, .ingredlist-long')
    if container:
        for h in container.select('h3,h4,.ingredient-name'):
            desc=[]; n=h.find_next_sibling()
            while n and n.name not in ('h3','h4'):
                if n.name=='p': desc.append(txt(n) or '')
                n=n.find_next_sibling()
            explained.append({'ingredient':txt(h) or '', 'description':' '.join(desc).strip()})
    return ProductRecord('incidecoder',url,name,brand,None,skim or None,explained or None,image,{'title':txt(soup.title)})

def read_urls_from_csv(path: str, column: str) -> list[str]:
    urls=[]
    with open(path, newline='', encoding='utf-8') as f:
        r=csv.DictReader(f)
        for row in r:
            u=(row.get(column) or '').strip()
            if u: urls.append(u)
    return urls

def append_ingredient_rows(ingredient_csv: Path, rec: dict):
    new_file=not ingredient_csv.exists()
    with ingredient_csv.open('a', newline='', encoding='utf-8') as f:
        w=csv.writer(f)
        if new_file:
            w.writerow(['product_url','product_name','brand','ingredient_name','what_it_does','irr_com','id_rating','description'])
        for row in rec.get('skim_table') or []:
            w.writerow([rec.get('url'),rec.get('name'),rec.get('brand'),row.get('Ingredient name',''),row.get('what-it-does',''),row.get('irr., com.',''),row.get('ID-Rating',''),''])
        for row in rec.get('ingredients_explained') or []:
            w.writerow([rec.get('url'),rec.get('name'),rec.get('brand'),row.get('ingredient',''),'','','',row.get('description','')])



def slugify(text: str, max_len: int = 80) -> str:
    text = (text or 'product').strip().lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return (text or 'product')[:max_len]

def download_product_image(sess: SafeSession, image_url: str, product_url: str, product_name: str, out_dir: Path, obey_robots=True) -> str | None:
    if not image_url:
        return None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        ext = '.jpg'
        p = urlparse(image_url)
        if '.' in Path(p.path).name:
            ext = Path(p.path).suffix or '.jpg'
        name_slug = slugify(product_name)
        h = hashlib.sha1(product_url.encode()).hexdigest()[:8]
        fname = f"{name_slug}-{h}{ext}"
        path = out_dir / fname
        if not path.exists():
            img_bytes = sess.get(image_url, obey_robots=obey_robots).content
            path.write_bytes(img_bytes)
        return str(path)
    except Exception as e:
        print(f"WARN image download failed for {product_url}: {e}")
        return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-csv', default='')
    ap.add_argument('--input-column', default='product_link')
    ap.add_argument('--out-jsonl', default='data/products.jsonl')
    ap.add_argument('--out-products-csv', default='data/products_full.csv')
    ap.add_argument('--out-ingredients-csv', default='data/ingredients_full.csv')
    ap.add_argument('--image-dir', default='data/product_images')
    ap.add_argument('--delay', type=float, default=2.0); ap.add_argument('--jitter', type=float, default=3.0)
    ap.add_argument('--timeout', type=int, default=45); ap.add_argument('--retries', type=int, default=6)
    ap.add_argument('--limit', type=int, default=0); ap.add_argument('--ignore-robots', action='store_true')
    ap.add_argument('urls', nargs='*')
    a=ap.parse_args()

    urls=list(a.urls)
    if a.input_csv: urls.extend(read_urls_from_csv(a.input_csv, a.input_column))
    urls=sorted(set(urls))
    if a.limit>0: urls=urls[:a.limit]
    if not urls:
        print('ERR no URLs provided. use --input-csv or positional URLs'); return

    sess=SafeSession(a.delay,a.jitter,a.timeout,a.retries)
    out_jsonl=Path(a.out_jsonl); out_jsonl.parent.mkdir(parents=True,exist_ok=True)
    products_csv=Path(a.out_products_csv); ingredients_csv=Path(a.out_ingredients_csv)

    new_products=not products_csv.exists()
    with out_jsonl.open('a',encoding='utf-8') as jf, products_csv.open('a', newline='', encoding='utf-8') as pf:
        pw=csv.writer(pf)
        if new_products: pw.writerow(['url','name','brand','image_url','image_path','raw_html_path'])
        for i,url in enumerate(urls,start=1):
            try:
                html=sess.get(url,obey_robots=not a.ignore_robots).text
                raw=Path('data/raw_html'); raw.mkdir(parents=True,exist_ok=True)
                raw_path=raw/f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.html"; raw_path.write_text(html,encoding='utf-8')
                rec=asdict(parse_incidecoder(url,html)); rec['raw_html_path']=str(raw_path)
                rec['image_path']=download_product_image(sess, rec.get('image_url'), url, rec.get('name') or '', Path(a.image_dir), obey_robots=not a.ignore_robots)
                jf.write(json.dumps(rec,ensure_ascii=False)+'\n')
                pw.writerow([rec['url'],rec.get('name'),rec.get('brand'),rec.get('image_url'),rec.get('image_path'),rec['raw_html_path']])
                append_ingredient_rows(ingredients_csv, rec)
                print(f"OK [{i}/{len(urls)}] {rec.get('name') or 'Unknown'} | skim={len(rec.get('skim_table') or [])} | explained={len(rec.get('ingredients_explained') or [])}")
            except PermissionError as e:
                print(f"SKIP robots block: {e}")
            except Exception as e:
                print(f"ERR {url} -> {e}")

if __name__=='__main__': main()
