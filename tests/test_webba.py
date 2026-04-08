import pytest, time, json
from pathlib import Path
from fastcore.all import L
from webba.search import (Result, SearchResults, QuotaManager, SearchCache,
                           _ddg, _google_scrape, _searxng, _searxng_enabled, route, rerank, PROVIDERS)
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


def test_cache_set_get(tmp_path):
    sc = SearchCache(db_path=str(tmp_path/'c.db'), ttl=60)
    sc.set('test:key', [{'title': 'x', 'url': 'y', 'snippet': 's', 'provider': 'ddg'}])
    cached = sc.get('test:key')
    assert cached is not None
    assert cached[0]['title'] == 'x'


def test_cache_ttl(tmp_path):
    sc = SearchCache(db_path=str(tmp_path/'c.db'), ttl=1)
    sc.set('test', [{'title': 'x', 'url': 'y'}])
    assert sc.get('test') is not None
    time.sleep(1.5)
    assert sc.get('test') is None


def test_cache_purge(tmp_path):
    sc = SearchCache(db_path=str(tmp_path/'c.db'), ttl=3600)
    sc.set('k1', [{'title': 'a'}])
    sc.set('k2', [{'title': 'b'}])
    assert sc.get('k1') is not None
    sc.purge()
    assert sc.get('k1') is None
    assert sc.get('k2') is None


def test_cache_purge_expired(tmp_path):
    sc = SearchCache(db_path=str(tmp_path/'c.db'), ttl=1)
    sc.set('old', [{'title': 'old'}])
    time.sleep(1.5)
    sc.set('new', [{'title': 'new'}])
    sc.purge_expired()
    assert sc.get('old') is None
    assert sc.get('new') is not None


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
    p = route('python github error', quota=qm)
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


def test_purge_cache_api(tmp_path):
    "purge_cache() exported from webba.__init__ clears all cache entries."
    from webba import purge_cache
    sc = SearchCache(db_path=str(tmp_path/'c.db'))
    sc.set('k1', [{'title': 'a', 'url': 'u', 'snippet': 's', 'provider': 'ddg'}])
    assert sc.get('k1') is not None
    purge_cache(db_path=str(tmp_path/'c.db'))
    # re-open same file to confirm rows are gone
    sc2 = SearchCache(db_path=str(tmp_path/'c.db'))
    assert sc2.get('k1') is None


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
    p = route('generic query', quota=qm)
    assert p == 'brave'


def test_search_empty_query():
    "search() returns empty SearchResults for blank query."
    from webba.search import search
    assert search('') == SearchResults()
    assert search('   ') == SearchResults()
