"""Phase 2 (tuy chon): tai anh tu file TSV cua crawl_urls.py.

    python download_images.py output/urls.tsv -o images -n 50

Moi keyword -> <out>/<keyword>_<hash>/<rank>.<ext>: N anh hop le dau tien theo thu tu rank.
Anh hop le = mo duoc bang Pillow, canh ngan >= --min-side, khong trung noi dung.
Ghi them <out>/manifest.tsv (folder, file, keyword, rank, url). Chay lai se bo qua keyword da du anh.
"""
import argparse
import hashlib
import io
import itertools
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image
from requests.utils import requote_uri

from crawl_urls import UA

EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "BMP": "bmp"}
MAX_BYTES = 15 * 1024 * 1024


def slug(keyword):
    base = re.sub(r"[^\w\-]+", "_", keyword, flags=re.UNICODE).strip("_")[:80]
    return f"{base}_{hashlib.md5(keyword.encode('utf-8')).hexdigest()[:6]}"


def fetch_image(session, url, min_side):
    """Tra ve (bytes, ext) neu la anh hop le, nguoc lai None."""
    try:
        with session.get(requote_uri(url), timeout=15, stream=True) as r:
            if r.status_code != 200:
                return None
            data = b""
            for chunk in r.iter_content(65536):
                data += chunk
                if len(data) > MAX_BYTES:
                    return None
        im = Image.open(io.BytesIO(data))
        im.load()
        if min(im.size) < min_side or im.format not in EXT:
            return None
        return data, EXT[im.format]
    except Exception:
        return None


def read_groups(tsv):
    """Doc TSV (cac dong cua 1 keyword nam lien nhau) -> (keyword, [(rank, url), ...])."""
    def rows():
        with open(tsv, encoding="utf-8") as f:
            next(f, None)  # header
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 3:
                    yield parts[1], int(parts[2]), parts[0]
    for kw, grp in itertools.groupby(rows(), key=lambda x: x[0]):
        yield kw, sorted((r, u) for _, r, u in grp)


class Downloader:
    def __init__(self, out_dir, n=50, min_side=100):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.n, self.min_side = n, min_side
        self.lock = threading.Lock()
        self.manifest = open(self.out / "manifest.tsv", "a", encoding="utf-8")
        if self.manifest.tell() == 0:
            self.manifest.write("folder\tfile\tkeyword\trank\turl\n")
        self.ok = self.short = self.skipped = 0

    def one(self, item):
        kw, rows = item
        folder = slug(kw)
        kdir = self.out / folder
        if kdir.exists() and sum(1 for p in kdir.iterdir() if p.is_file()) >= self.n:
            with self.lock:
                self.skipped += 1
            return
        kdir.mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        session.headers["User-Agent"] = UA
        hashes, saved, lines = set(), 0, []
        for rank, url in rows:
            if saved >= self.n:
                break
            got = fetch_image(session, url, self.min_side)
            if got is None:
                continue
            data, ext = got
            h = hashlib.md5(data).hexdigest()
            if h in hashes:
                continue
            hashes.add(h)
            name = f"{rank:04d}.{ext}"
            (kdir / name).write_bytes(data)
            lines.append(f"{folder}\t{name}\t{kw}\t{rank}\t{url}\n")
            saved += 1
        with self.lock:
            self.manifest.writelines(lines)
            self.manifest.flush()
            self.ok += saved >= self.n
            self.short += saved < self.n
            print(f"[{kw}] {saved}/{self.n} anh", flush=True)

    def run(self, groups, workers):
        with ThreadPoolExecutor(workers) as ex:
            while True:
                batch = list(itertools.islice(groups, workers * 4))
                if not batch:
                    break
                list(ex.map(self.one, batch))
        self.manifest.close()
        print(f"Xong: {self.ok} keyword du {self.n} anh, {self.short} keyword thieu, "
              f"{self.skipped} keyword bo qua (da du tu truoc)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tai anh tu file TSV cua crawl_urls.py.")
    ap.add_argument("tsv")
    ap.add_argument("-o", "--out", default="images")
    ap.add_argument("-n", type=int, default=50, help="so anh moi keyword")
    ap.add_argument("--workers", type=int, default=8, help="so keyword tai song song")
    ap.add_argument("--min-side", type=int, default=100, help="canh ngan toi thieu (px)")
    ap.add_argument("--limit", type=int, help="chi xu ly N keyword dau (de thu)")
    a = ap.parse_args(argv)
    groups = read_groups(a.tsv)
    if a.limit:
        groups = itertools.islice(groups, a.limit)
    Downloader(a.out, a.n, a.min_side).run(groups, a.workers)


if __name__ == "__main__":
    main()
