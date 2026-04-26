"""Integration tests using local HTTP servers — test real network+parsing stack.

Run with: pytest -m integration
Override public SearXNG instance with: SEARXNG_URL=https://... pytest -m integration
"""
import json, threading, re, urllib.parse
import http.server
import pytest
import niquests
from webba.fetch import crawl, _links
from webba.search import _searxng


# ── local HTTP server fixture ──────────────────────────────────────────────────

_LOREM = 'The quick brown fox jumps over the lazy dog. ' * 12  # >200 chars

_SITE = {
    '/': f'<nav><a href="/page/1/">Page 1</a><a href="/page/2/">Page 2</a>'
         f'<a href="https://external.example.com/">ext</a></nav>'
         f'<main>{_LOREM}</main>',
    '/page/1/': f'<nav><a href="/">home</a><a href="/page/2/">Page 2</a>'
                f'<a href="/author/jane/">Jane</a></nav>'
                f'<main>Page 1: {_LOREM}</main>',
    '/page/2/': f'<nav><a href="/">home</a><a href="/page/1/">Page 1</a>'
                f'<a href="/author/john/">John</a></nav>'
                f'<main>Page 2: {_LOREM}</main>',
    '/author/jane/': f'<main>Jane Austen bio. {_LOREM}</main>',
    '/author/john/': f'<main>John Keats bio. {_LOREM}</main>',
}

_SEARXNG_RESULTS = lambda q, n: {
    'results': [
        {'title': f'Result {i}: {q}',
         'url':   f'https://example{i}.com/{q.replace(" ","_")}',
         'content': f'Snippet {i} about {q} — useful information here.'}
        for i in range(1, n + 1)
    ]
}


class _SiteHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        body = _SITE.get(path, '').encode()
        if body:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *_): pass


class _SearXNGHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        q = params.get('q', ['test'])[0]
        n = int(params.get('pageno', [1])[0]) and 5  # always 5 results
        body = json.dumps(_SEARXNG_RESULTS(q, n)).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_): pass


def _start_server(handler_cls):
    srv = http.server.HTTPServer(('127.0.0.1', 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}'


@pytest.fixture(scope='module')
def site_url():
    srv, url = _start_server(_SiteHandler)
    yield url
    srv.shutdown()


@pytest.fixture(scope='module')
def searxng_url():
    srv, url = _start_server(_SearXNGHandler)
    yield url
    srv.shutdown()


# ── crawl integration ──────────────────────────────────────────────────────────

@pytest.mark.integration
def test_crawl_pages_and_files(site_url, tmp_path):
    "Crawl local site paginated pages; verify {url,text} dicts and saved .txt files match."
    results = crawl(site_url + '/', link_pat=r'/page/\d+/', max_pages=5,
                    delay=0, save_dir=str(tmp_path))
    assert len(results) >= 1, f"Expected crawled pages, got {len(results)}"
    assert all('url' in r and 'text' in r for r in results)
    assert all(len(r['text']) > 50 for r in results), "Each page should have substantial text"
    saved = sorted(tmp_path.glob('*.txt'))
    assert len(saved) == len(results), f"Expected {len(results)} .txt files, got {len(saved)}"
    assert all(f.stat().st_size > 0 for f in saved)
    # File content must match the in-memory result text
    for r in results:
        slug = re.sub(r'[^\w-]', '_', urllib.parse.urlparse(r['url']).path).strip('_') or 'index'
        fpath = tmp_path / f'{slug}.txt'
        if fpath.exists():
            assert fpath.read_text(encoding='utf-8') == r['text']

@pytest.mark.integration
def test_crawl_same_domain_only(site_url, tmp_path):
    "same_domain=True must not follow the external link in the seed page."
    results = crawl(site_url + '/', max_pages=10, delay=0, same_domain=True)
    assert results, "Expected at least the seed page"
    host = urllib.parse.urlparse(site_url).netloc
    assert all(urllib.parse.urlparse(r['url']).netloc == host for r in results), \
        f"Off-domain URL found: {[r['url'] for r in results]}"

@pytest.mark.integration
def test_crawl_link_pattern_author_pages(site_url, tmp_path):
    "link_pat=/author/ from a page that has author links yields only author pages."
    # /page/1/ has /author/jane/ and /author/john/ links — seed from there
    results = crawl(site_url + '/page/1/', link_pat=r'/author/', max_pages=10, delay=0)
    urls = [r['url'] for r in results]
    non_author_non_seed = [u for u in urls
                           if '/author/' not in u and u != site_url + '/page/1/']
    assert not non_author_non_seed, f"Unexpected non-author URLs: {non_author_non_seed}"
    author_urls = [u for u in urls if '/author/' in u]
    assert len(author_urls) >= 1, "Expected at least one author page"

@pytest.mark.integration
def test_crawl_max_pages_respected(site_url):
    "max_pages=2 stops the crawl after 2 pages regardless of queue size."
    results = crawl(site_url + '/', max_pages=2, delay=0)
    assert len(results) <= 2

@pytest.mark.integration
def test_crawl_dedup_no_revisit(site_url):
    "Pages are never fetched twice even when multiple pages link to the same URL."
    results = crawl(site_url + '/', max_pages=20, delay=0)
    urls = [r['url'] for r in results]
    assert len(urls) == len(set(urls)), f"Duplicate URLs: {[u for u in urls if urls.count(u)>1]}"


# ── SearXNG integration ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_searxng_returns_results(searxng_url, monkeypatch):
    "Local SearXNG mock returns well-formed Result objects."
    monkeypatch.setenv('SEARXNG_URL', searxng_url)
    results = _searxng('python fastcore library', n=5)
    assert len(results) == 5
    for r in results:
        assert r.url.startswith('http'), f"Bad URL: {r.url!r}"
        assert isinstance(r.title, str) and r.title
        assert isinstance(r.snippet, str) and r.snippet
        assert r.provider == 'searxng'
        assert isinstance(r.ts, float) and r.ts > 0

@pytest.mark.integration
def test_searxng_n_limit(searxng_url, monkeypatch):
    "Result count is capped at n."
    monkeypatch.setenv('SEARXNG_URL', searxng_url)
    results = _searxng('test query', n=3)
    assert len(results) <= 3

@pytest.mark.integration
def test_searxng_ramayana_query(searxng_url, monkeypatch):
    "SearXNG on 'valmiki ramayana' returns results containing the query terms."
    monkeypatch.setenv('SEARXNG_URL', searxng_url)
    results = _searxng('valmiki ramayana iitk', n=5)
    assert results, "Expected results for ramayana query"
    assert all('valmiki' in r.title.lower() or 'ramayana' in r.title.lower()
               or 'valmiki' in r.url.lower() or 'ramayana' in r.url.lower()
               for r in results)

@pytest.mark.integration
def test_searxng_result_urls_unique(searxng_url, monkeypatch):
    "All returned URLs are unique (no duplicate results)."
    monkeypatch.setenv('SEARXNG_URL', searxng_url)
    results = _searxng('web scraping python', n=5)
    urls = [r.url for r in results]
    assert len(urls) == len(set(urls)), f"Duplicate URLs: {urls}"
