"""Phase 2: lay URL anh tu Bing Images theo keyword.

    python crawl_urls.py input/keywords.txt -o output/urls.tsv --workers 4 --delay 1.0

Input : file txt, moi dong 1 keyword.
Output: <output> (TSV: url, keyword, rank), <output>.done (keyword da xong, de resume),
        <output>.failed (keyword khong ra URL nao).
"""
import argparse
import collections
import html
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
BING_URL = "https://www.bing.com/images/async"
PAGE_SIZE = 35  # so anh toi da moi page
BLOCK_STATUS = {429, 403, 503}
MAX_COOLDOWN = 4 * 3600
M_ATTR = re.compile(r'\sm="(\{.*?\})"')


def parse_page(text):
    """URL anh goc theo thu tu rank; bo trung va bo URL khong tai duoc (Facebook, khong phai http)."""
    urls, seen = [], set()
    for raw in M_ATTR.findall(text):
        try:
            u = json.loads(html.unescape(raw)).get("murl")
        except ValueError:
            continue
        if not u or not u.startswith("http") or "fbsbx.com" in u or u in seen:
            continue
        seen.add(u)
        urls.append(u)
    return urls


def fetch_page(session, query, first):
    """Tra ve (status, urls). Nem requests.RequestException khi loi mang."""
    r = session.get(
        BING_URL,
        params={"q": query, "first": first, "count": PAGE_SIZE, "mmasync": 1},
        timeout=25,
    )
    return r.status_code, (parse_page(r.text) if r.status_code == 200 else [])


def make_session(proxy=None):
    s = requests.Session()
    s.headers["User-Agent"] = UA
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def read_keywords(path):
    """Moi dong 1 keyword; bo dong trong va keyword trung (giu thu tu)."""
    with open(path, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f]
    return list(dict.fromkeys(ln for ln in lines if ln))


def read_set(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {ln.rstrip("\n") for ln in f if ln.strip()}


class Crawler:
    def __init__(self, keywords, output, workers=4, delay=1.0, target=100, proxies=None,
                 cooldown=900.0, empty_limit=8, retries=3):
        self.output = Path(output)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.done_path = Path(str(output) + ".done")
        self.failed_path = Path(str(output) + ".failed")
        done = read_set(self.done_path)
        self.skipped = sum(1 for k in keywords if k in done)
        self.todo = queue.Queue()
        for k in keywords:
            if k not in done:
                self.todo.put(k)
        self.workers, self.delay, self.target = workers, delay, target
        self.proxies = proxies or []
        self.cooldown, self.empty_limit, self.retries = cooldown, empty_limit, retries

        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.t0 = time.time()
        self.req = self.urls_total = self.kw_done = self.kw_failed = 0
        self.status = collections.Counter()

        new_file = not self.output.exists() or self.output.stat().st_size == 0
        self.out = open(self.output, "a", encoding="utf-8")
        if new_file:
            self.out.write("url\tkeyword\trank\n")
            self.out.flush()
        self.done_f = open(self.done_path, "a", encoding="utf-8")
        self.failed_f = open(self.failed_path, "a", encoding="utf-8")

    def sleep(self, seconds):
        self.stop.wait(seconds)

    def log(self, msg):
        print(msg, flush=True)

    def count(self, status, n):
        with self.lock:
            self.req += 1
            self.urls_total += n
            self.status[status] += 1

    def fetch_with_retry(self, session, kw, first):
        for attempt in range(self.retries):
            try:
                return fetch_page(session, kw, first)
            except requests.RequestException:
                self.sleep(5 * (attempt + 1))
        return "neterr", []

    def commit(self, kw, urls):
        label = kw.replace("\t", " ")
        with self.lock:
            if urls:
                self.out.write("".join(f"{u}\t{label}\t{r}\n" for r, u in enumerate(urls, 1)))
                self.out.flush()
                self.done_f.write(kw + "\n")
                self.done_f.flush()
                self.kw_done += 1
            else:
                self.failed_f.write(kw + "\n")
                self.failed_f.flush()
                self.kw_failed += 1

    def run_worker(self, wid):
        proxy = self.proxies[wid % len(self.proxies)] if self.proxies else None
        session = make_session(proxy)
        empty_run, cooldown = 0, self.cooldown
        while not self.stop.is_set():
            try:
                kw = self.todo.get_nowait()
            except queue.Empty:
                return
            urls, seen, first = [], set(), 1
            while len(urls) < self.target and not self.stop.is_set():
                status, page = self.fetch_with_retry(session, kw, first)
                self.count(status, len(page))
                # page rong sau khi da co URL = het ket qua that; chi page dau rong lien tiep moi dang ngo
                blocked = status in BLOCK_STATUS or (
                    status == 200 and not page and not urls and empty_run + 1 >= self.empty_limit)
                if blocked:
                    # nghi bi chan: nghi roi thu lai cung page; nghi lau dan neu van bi
                    self.log(f"[w{wid}] nghi bi chan (status={status}), nghi {cooldown:.0f}s")
                    self.sleep(cooldown)
                    cooldown = min(cooldown * 2, MAX_COOLDOWN)
                    empty_run = 0
                    continue
                self.sleep(self.delay)
                if status != 200:  # loi mang / status la: bo keyword nay, de lan sau chay lai
                    break
                cooldown = self.cooldown
                new = [u for u in page if u not in seen]
                if not new:
                    if not page and not urls:
                        empty_run += 1
                    break
                empty_run = 0
                urls.extend(new)
                seen.update(new)
                first += PAGE_SIZE
            if not self.stop.is_set():
                self.commit(kw, urls)

    def report(self):
        el = max(time.time() - self.t0, 1e-9)
        with self.lock:
            self.log(f"[{el/60:6.1f}p] req={self.req} ({self.req/el:.2f}/s) kw_xong={self.kw_done} "
                     f"kw_loi={self.kw_failed} url={self.urls_total} {dict(self.status)}")

    def run(self, report_every=30):
        n = self.todo.qsize()
        self.log(f"{n} keyword can crawl ({self.skipped} da xong tu lan truoc), "
                 f"workers={self.workers}, delay={self.delay}s, proxy={len(self.proxies) or 'khong'}")
        threads = [threading.Thread(target=self.run_worker, args=(i,), daemon=True)
                   for i in range(self.workers)]
        for t in threads:
            t.start()
        try:
            while any(t.is_alive() for t in threads):
                for t in threads:
                    t.join(timeout=report_every / max(len(threads), 1))
                self.report()
        except KeyboardInterrupt:
            self.log("Ctrl+C: dang dung...")
            self.stop.set()
            for t in threads:
                t.join(timeout=30)
        self.report()
        for f in (self.out, self.done_f, self.failed_f):
            f.close()


def load_proxies(args):
    proxies = list(args.proxy or [])
    if args.proxy_file:
        with open(args.proxy_file, encoding="utf-8") as f:
            proxies += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if not proxies and os.environ.get("PROXY_URL"):
        proxies = [os.environ["PROXY_URL"]]
    return proxies


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lay URL anh tu Bing Images theo keyword.")
    ap.add_argument("keywords_file", help="file txt, moi dong 1 keyword")
    ap.add_argument("-o", "--output", default="output/urls.tsv")
    ap.add_argument("--urls", type=int, default=100, help="so URL moi keyword (35 URL/page)")
    ap.add_argument("--workers", type=int, default=4, help="so luong chay song song")
    ap.add_argument("--delay", type=float, default=1.0, help="giay cho sau moi request (moi luong)")
    ap.add_argument("--proxy", action="append", help="http://user:pass@host:port (dung nhieu lan)")
    ap.add_argument("--proxy-file", help="file proxy, moi dong 1 proxy")
    ap.add_argument("--cooldown", type=float, default=900.0, help="giay nghi khi nghi bi chan")
    ap.add_argument("--empty-limit", type=int, default=8,
                    help="so page rong lien tiep coi la bi chan")
    ap.add_argument("--limit", type=int, help="chi crawl N keyword dau (de thu)")
    a = ap.parse_args(argv)

    keywords = read_keywords(a.keywords_file)
    if a.limit:
        keywords = keywords[: a.limit]
    if not keywords:
        sys.exit("File keyword rong")
    Crawler(keywords, a.output, workers=a.workers, delay=a.delay, target=a.urls,
            proxies=load_proxies(a), cooldown=a.cooldown, empty_limit=a.empty_limit).run()


if __name__ == "__main__":
    main()
