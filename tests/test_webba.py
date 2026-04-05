import pytest, time, json
from pathlib import Path
from fastcore.all import L
from webba.search import (Result, SearchResults, QuotaManager, SearchCache,
                           _ddg, _google_scrape, route, PROVIDERS)
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
