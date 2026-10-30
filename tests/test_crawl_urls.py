import html
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import crawl_urls  # noqa: E402


def bing_html(urls):
    items = []
    for u in urls:
        m = html.escape(json.dumps({"murl": u, "turl": "https://t/x"}), quote=True)
        items.append(f'<a class="iusc" m="{m}">x</a>')
    return "<html>" + "".join(items) + "</html>"


class ParsePageTest(unittest.TestCase):
    def test_unescapes_dedupes_and_filters(self):
        text = bing_html([
            "https://a.com/1.jpg?x=1&y=2",
            "https://a.com/1.jpg?x=1&y=2",  # trung
            "https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id=1",
            "ftp://a.com/2.jpg",
            "https://b.com/3.png",
        ])
        self.assertEqual(crawl_urls.parse_page(text),
                         ["https://a.com/1.jpg?x=1&y=2", "https://b.com/3.png"])

    def test_empty(self):
        self.assertEqual(crawl_urls.parse_page("<html></html>"), [])


class ReadKeywordsTest(unittest.TestCase):
    def test_blank_and_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "k.txt"
            p.write_text("messi\n\n  ronaldo  \nmessi\nVũ nhôm\n", encoding="utf-8")
            self.assertEqual(crawl_urls.read_keywords(p), ["messi", "ronaldo", "Vũ nhôm"])


def fake_fetch(calls, block_first=False):
    state = {"blocked": False}

    def fetch(session, query, first):
        calls.append((query, first))
        if block_first and not state["blocked"]:
            state["blocked"] = True
            return 429, []
        if first > 71:  # chi co 3 page (first = 1, 36, 71)
            return 200, []
        return 200, [f"https://img.test/{query}/{first + i}.jpg" for i in range(35)]
    return fetch


class CrawlerTest(unittest.TestCase):
    def run_crawler(self, d, keywords, **kw):
        out = Path(d) / "out" / "urls.tsv"
        with mock.patch.object(crawl_urls, "fetch_page", fake_fetch(kw.pop("calls", []),
                                                                    kw.pop("block_first", False))):
            c = crawl_urls.Crawler(keywords, out, delay=0, cooldown=0, **kw)
            c.run(report_every=1)
        return out

    def test_crawl_writes_tsv_and_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            out = self.run_crawler(d, ["a b", "c"], workers=2, target=100, calls=calls)
            lines = out.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "url\tkeyword\trank")
            rows = [ln.split("\t") for ln in lines[1:]]
            self.assertEqual(len(rows), 2 * 105)  # 3 page x 35 URL moi keyword
            ranks = [int(r[2]) for r in rows if r[1] == "a b"]
            self.assertEqual(ranks, list(range(1, 106)))
            self.assertEqual(sorted(crawl_urls.read_set(str(out) + ".done")), ["a b", "c"])

            calls2 = []  # chay lai: khong request them, khong them dong
            self.run_crawler(d, ["a b", "c"], workers=2, target=100, calls=calls2)
            self.assertEqual(calls2, [])
            self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1 + 2 * 105)

    def test_retries_after_block(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.run_crawler(d, ["x"], workers=1, target=70, block_first=True)
            rows = out.read_text(encoding="utf-8").splitlines()[1:]
            self.assertEqual(len(rows), 70)

    def test_keyword_without_results_is_failed_not_done(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "urls.tsv"
            with mock.patch.object(crawl_urls, "fetch_page", lambda s, q, f: (200, [])):
                crawl_urls.Crawler(["zzz"], out, delay=0, cooldown=0, workers=1,
                                   empty_limit=99).run(report_every=1)
            self.assertEqual(crawl_urls.read_set(str(out) + ".done"), set())
            self.assertEqual(crawl_urls.read_set(str(out) + ".failed"), {"zzz"})


class ProxyConfigTest(unittest.TestCase):
    def test_session_uses_proxy(self):
        s = crawl_urls.make_session("http://u:p@1.2.3.4:8080")
        self.assertEqual(s.proxies["https"], "http://u:p@1.2.3.4:8080")
        self.assertEqual(crawl_urls.make_session().proxies, {})


if __name__ == "__main__":
    unittest.main()
