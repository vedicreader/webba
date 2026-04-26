import pytest, time, json, numpy as np
from pathlib import Path
from fastcore.all import L
from webba.search import (Result, SearchResults, QuotaManager,
                           _ddg, _google_scrape, _searxng, _searxng_enabled, route, rerank, PROVIDERS)
from webba.cache import SemanticSearchCache
from webba.fetch import fetch, _url_type


def test_result_attrdict():
    r = Result(title='t', url='u', snippet='s', provider='ddg')
    assert r.title == 't' and r['url'] == 'u'


def test_quota_roundtrip(tmp_path):
    qm = QuotaManager(quota_file=str(tmp_path/'q.json'))
    assert qm.remaining('serper') == 2500
    qm.consume('serper', 100)
    assert qm.remaining('serper') == 2400
    qm2 = QuotaManager(quota_file=str(tmp_path/'q.json'))
    assert qm2.remaining('serper') == 2400



# ── SemanticSearchCache fixtures & tests ──────────────────────────────────────

import hashlib

def _fake_emb(self, q:str) -> bytes:
    "Deterministic fake embedding: hash-seeded random float16 vector (256-dim = potion-base-8M)."
    seed = int(hashlib.md5(q.encode()).hexdigest()[:8], 16) % (2**31)
    return np.random.default_rng(seed).random(256).astype(np.float16).tobytes()

@pytest.fixture
def cache(tmp_path, monkeypatch):
    sc = SemanticSearchCache(db_path=str(tmp_path/'cache.db'), ttl=5, threshold=0.022)
    monkeypatch.setattr(SemanticSearchCache, '_emb', _fake_emb)
    return sc

_RESULTS = [{'title': 'T', 'url': 'https://example.com', 'snippet': 'S', 'provider': 'ddg'}]

def test_semantic_hit(cache):
    "Exact-match query returns cached result (highest possible RRF score)."
    q = 'python asyncio tutorial'
    cache.set(q, _RESULTS)
    hit = cache.get(q)
    assert hit is not None
    assert hit[0]['title'] == 'T'

def test_semantic_miss(cache):
    "Unrelated query scores below threshold and returns None."
    cache.set('python asyncio tutorial', _RESULTS)
    assert cache.get('football match scores today') is None

def test_ttl_expiry(cache):
    "Entry backdated past TTL returns None from get()."
    q = 'ttl test query'
    cache.set(q, _RESULTS)
    cache.db.execute('UPDATE webba_cache SET uploaded_at = ? WHERE content = ?',
                     [time.time() - cache.ttl - 1, q])
    assert cache.get(q) is None

def test_purge_expired(cache):
    "purge_expired() removes only entries older than TTL, leaves fresh ones."
    cache.set('old entry', _RESULTS)
    cache.db.execute('UPDATE webba_cache SET uploaded_at = ? WHERE content = ?',
                     [time.time() - cache.ttl - 1, 'old entry'])
    cache.set('new entry', _RESULTS)
    n = cache.purge_expired()
    assert n == 1
    assert cache.get('new entry') is not None

def test_purge_semantic(cache):
    "purge_semantic() deletes matching entries and returns victims."
    q = 'python asyncio tutorial'
    cache.set(q, _RESULTS)
    n_before = len(list(cache.db.query('SELECT rowid FROM webba_cache')))
    victims = cache.purge_semantic(q, threshold=0.0)
    assert len(victims) > 0
    n_after = len(list(cache.db.query('SELECT rowid FROM webba_cache')))
    assert n_after == n_before - len(victims)

def test_purge_semantic_dry_run(cache):
    "dry_run=True returns victims without deleting any rows."
    q = 'python asyncio tutorial'
    cache.set(q, _RESULTS)
    n_before = len(list(cache.db.query('SELECT rowid FROM webba_cache')))
    victims = cache.purge_semantic(q, threshold=0.0, dry_run=True)
    assert len(victims) > 0
    n_after = len(list(cache.db.query('SELECT rowid FROM webba_cache')))
    assert n_after == n_before

def test_purge_topic(cache):
    "purge_topic() combines expired TTL removal and semantic purge in one call."
    q = 'python async'
    cache.set(q, _RESULTS)
    cache.db.execute('UPDATE webba_cache SET uploaded_at = ?', [time.time() - cache.ttl - 1])
    result = cache.purge_topic(q, threshold=0.0)
    assert isinstance(result.expired, int)
    assert isinstance(result.semantic, L)
    assert not result.dry_run

def test_quota_available_no_keys(monkeypatch):
    for p in PROVIDERS.values():
        if p.env: monkeypatch.delenv(p.env, raising=False)
    qm = QuotaManager()
    avail = qm.available()
    assert 'ddg' in avail
    assert 'searxng' in avail
    assert 'serper' not in avail


def test_url_type():
    assert _url_type('https://github.com/AnswerDotAI/ContextKit/blob/main/contextkit/read.py') == 'gh_file'
    assert _url_type('https://github.com/AnswerDotAI/ContextKit') == 'gh_repo'
    assert _url_type('https://gist.github.com/user/abc123') == 'gist'
    assert _url_type('https://arxiv.org/abs/2310.06825') == 'arxiv'
    assert _url_type('https://example.com/doc.pdf') == 'pdf'
    assert _url_type('/local/path.txt') == 'local'


def test_url_type_docs_and_ar5iv():
    "Docs and ar5iv URLs are classified correctly."
    assert _url_type('https://ar5iv.org/abs/2310.06825') == 'arxiv'
    assert _url_type('https://fastcore.fast.ai/docs/') == 'docs'
    assert _url_type('https://fastcore.readthedocs.io/en/latest/') == 'docs'


def test_delegates_signature():
    "Verify @delegates correctly exposes read_gh_repo params on fetch()."
    import inspect
    sig = inspect.signature(fetch)
    assert 'as_dict' in sig.parameters      # from read_gh_repo
    assert 'url' in sig.parameters          # explicit param preserved


def test_search_results_to_md():
    r = SearchResults([Result(title='T', url='https://example.com', snippet='S', provider='ddg')])
    assert 'T' in r.to_md() and 'example.com' in r.to_md()


def test_route_intent(tmp_path):
    "Verify route detects intent and picks appropriate provider."
    qm = QuotaManager(quota_file=str(tmp_path/'q.json'))
    p, intent, extras = route('python github error', quota=qm)
    assert p in ('ddg', 'searxng', 'serper', 'exa')


def test_search_results_to_context():
    rs = SearchResults([
        Result(title='A', url='https://a.com', snippet='Hello world', provider='ddg'),
        Result(title='B', url='https://b.com', snippet='Foo bar', provider='ddg'),
    ])
    ctx = rs.to_context(max_chars=100)
    assert 'Hello world' in ctx


def test_searxng_enabled_flag(monkeypatch):
    monkeypatch.setenv('WEBBA_SEARXNG', 'false')
    assert not _searxng_enabled()
    monkeypatch.setenv('WEBBA_SEARXNG', 'true')
    assert _searxng_enabled()
    monkeypatch.delenv('WEBBA_SEARXNG', raising=False)
    assert _searxng_enabled()  # default is enabled


def test_searxng_disabled_excludes_from_available(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBBA_SEARXNG', 'false')
    for p in PROVIDERS.values():
        if p.env: monkeypatch.delenv(p.env, raising=False)
    qm = QuotaManager(quota_file=str(tmp_path/'q.json'))
    assert 'searxng' not in qm.available()


def test_searxng_disabled_returns_empty(monkeypatch):
    monkeypatch.setenv('WEBBA_SEARXNG', 'false')
    assert _searxng('test query') == L()


# ── new tests ──────────────────────────────────────────────────────────────────

def test_version_is_set():
    "webba.__version__ is defined and matches pyproject version."
    import webba
    assert hasattr(webba, '__version__')
    assert webba.__version__ == '0.1.0'


def test_rerank_dedup_and_order():
    "rerank deduplicates by URL and promotes URLs appearing in multiple provider lists."
    r_ddg_a  = Result(title='A',  url='https://a.com', snippet='', provider='ddg')
    r_ddg_b  = Result(title='B',  url='https://b.com', snippet='', provider='ddg')
    r_serp_a = Result(title='A2', url='https://a.com', snippet='x', provider='serper')  # dup
    ranked = rerank(L([r_ddg_a, r_ddg_b, r_serp_a]))
    # a.com scores from both ddg and serper → should rank first
    assert ranked[0].url == 'https://a.com'
    assert len(ranked) == 2  # deduplicated


def test_rerank_single_provider():
    "rerank with a single provider preserves ordering and deduplicates."
    results = L([
        Result(title='X', url='https://x.com', snippet='', provider='ddg'),
        Result(title='Y', url='https://y.com', snippet='', provider='ddg'),
        Result(title='X2', url='https://x.com', snippet='y', provider='ddg'),  # dup
    ])
    ranked = rerank(results)
    assert len(ranked) == 2
    assert ranked[0].url == 'https://x.com'


def test_cli_json_serializable():
    "Result objects serialize to JSON cleanly via dict() conversion."
    results = SearchResults([Result(title='T', url='https://example.com', snippet='S', provider='ddg')])
    out = json.dumps([dict(r) for r in results], indent=2)
    data = json.loads(out)
    assert data[0]['title'] == 'T'
    assert data[0]['url'] == 'https://example.com'


def test_purge_cache_api(tmp_path, monkeypatch):
    "purge_cache() exported from webba.__init__ clears all cache entries."
    from webba import purge_cache
    monkeypatch.setattr(SemanticSearchCache, '_emb', _fake_emb)
    sc = SemanticSearchCache(db_path=str(tmp_path/'c.db'))
    sc.set('python asyncio', [{'title': 'a', 'url': 'u', 'snippet': 's', 'provider': 'ddg'}])
    purge_cache(db_path=str(tmp_path/'c.db'))
    sc2 = SemanticSearchCache(db_path=str(tmp_path/'c.db'))
    assert len(list(sc2.db.query('SELECT rowid FROM webba_cache'))) == 0


def test_install_uninstall_hermes_plugin(tmp_path):
    "Hermes plugin installs and uninstalls cleanly."
    from webba.plugins import install_hermes_plugin, uninstall_hermes_plugin
    result = install_hermes_plugin(hermes_home=str(tmp_path))
    assert result['installed'], result['message']
    assert Path(result['path']).exists()
    result2 = uninstall_hermes_plugin(hermes_home=str(tmp_path))
    assert result2['uninstalled'], result2['message']
    assert not (tmp_path / 'plugins' / 'webba').exists()


def test_fetch_all_parallel(monkeypatch):
    "fetch_all fetches each result URL and returns L of strings."
    import sys
    fetch_mod = sys.modules['webba.fetch']
    calls = []
    def _fake(url, sel=None, heavy=False):
        calls.append(url)
        return f'content:{url}'
    monkeypatch.setattr(fetch_mod, 'fetch', _fake)
    rs = SearchResults([
        Result(title='A', url='https://a.com', snippet='', provider='ddg'),
        Result(title='B', url='https://b.com', snippet='', provider='ddg'),
    ])
    results = rs.fetch_all()
    assert len(results) == 2
    assert set(calls) == {'https://a.com', 'https://b.com'}


def test_route_fallback_to_first_available(monkeypatch, tmp_path):
    "route() returns first available provider when no preferred candidates match."
    qm = QuotaManager(quota_file=str(tmp_path/'q.json'))
    # mock available() to return only 'brave' — not in any default preferred list
    monkeypatch.setattr(qm, 'available', lambda min_remaining=1: L(['brave']))
    p, intent, extras = route('generic query', quota=qm)
    assert p == 'brave'


def test_search_empty_query():
    "search() returns empty SearchResults for blank query."
    from webba.search import search
    assert len(search('')) == 0
    assert len(search('   ')) == 0


# ── crawl tests ───────────────────────────────────────────────────────────────

from webba.fetch import _links, crawl

def test_links_absolute():
    html = '<a href="/page1">p1</a><a href="https://other.com/x">ext</a><a href="#skip">s</a>'
    result = _links(html, 'https://example.com')
    assert 'https://example.com/page1' in result
    assert 'https://other.com/x' in result
    assert not any('#' in u for u in result)

def test_links_pattern():
    html = '<a href="/sarga/1">s1</a><a href="/sarga/2">s2</a><a href="/about">about</a>'
    result = _links(html, 'https://site.com', pat=r'/sarga/')
    assert len(result) == 2 and all('sarga' in u for u in result)

def test_crawl_saves_files(tmp_path):
    "crawl() with save_dir writes one .txt file per page fetched."
    import unittest.mock as mock
    index_html  = '<a href="/p1">link</a><main>' + 'Index page content. ' * 15 + '</main>'
    page1_html  = '<main>' + 'Page one sarga content text. ' * 15 + '</main>'
    def fake_get(url, **kw):
        r = mock.MagicMock()
        r.status_code = 200
        r.text = index_html if url.endswith('/') else page1_html
        return r
    with mock.patch('niquests.Session') as MockSession:
        MockSession.return_value.__enter__.return_value.get.side_effect = fake_get
        results = crawl('https://site.com/', max_pages=5, delay=0, save_dir=str(tmp_path))
    assert len(results) >= 1
    assert all('url' in r and 'text' in r for r in results)
    assert any(tmp_path.iterdir())  # at least one .txt file written
