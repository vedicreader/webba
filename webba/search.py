"""webba — ALL search logic"""

from fastcore.all import store_attr, delegates, patch, ifnone, L, AttrDict, merge, first, call_parse, Param, filter_keys
from fastcore.parallel import parallel as _par
from litesearch import clean as _lsclean
from ._utils import _random_ua
import niquests, json, os, time, re, atexit, hashlib
from pathlib import Path
from urllib.parse import quote as _url_quote

PROVIDERS = {
    'ddg':           AttrDict(name='ddg',           base=None,
                              free_quota=999999, resets=None, env=None,
                              needs_key=False,  fragile=False),
    'searxng':       AttrDict(name='searxng',       base=None,
                              free_quota=999999, resets=None, env='SEARXNG_URL',
                              needs_key=False,  fragile=False),
    'google_scrape': AttrDict(name='google_scrape', base='https://www.google.com/search',
                              free_quota=999999, resets=None, env=None,
                              needs_key=False,  fragile=True),
    'serper':        AttrDict(name='serper',     base='https://google.serper.dev/search',
                              free_quota=2500,   resets='monthly', env='SERPER_API_KEY',     needs_key=True,  fragile=False),
    'tavily':        AttrDict(name='tavily',     base='https://api.tavily.com/search',
                              free_quota=1000,   resets='monthly', env='TAVILY_API_KEY',     needs_key=True,  fragile=False),
    'exa':           AttrDict(name='exa',        base='https://api.exa.ai/search',
                              free_quota=1000,   resets='monthly', env='EXA_API_KEY',        needs_key=True,  fragile=False),
    'perplexity':    AttrDict(name='perplexity', base='https://api.perplexity.ai/chat/completions',
                              free_quota=5,      resets='daily',   env='PERPLEXITY_API_KEY', needs_key=True,  fragile=False),
    'brave':         AttrDict(name='brave',      base='https://api.search.brave.com/res/v1/web/search',
                              free_quota=2000,   resets='monthly', env='BRAVE_API_KEY',      needs_key=True,  fragile=False),
}

FREE_TIER_ORDER = ['ddg', 'searxng', 'google_scrape']

SEARXNG_CATEGORY_MAP = {
    'recent':   'news',
    'academic': 'science',
    'code':     'it',
    'shopping': 'shopping',
    'default':  'general',
}

INTENT = AttrDict(
    academic = ['research', 'paper', 'study', 'arxiv', 'doi', 'journal', 'citation'],
    code     = ['github', 'python', 'javascript', 'stackoverflow', 'npm', 'pypi', 'error', 'bug'],
    recent   = ['today', 'yesterday', 'this week', 'latest', 'breaking', '2025', '2026'],
    shopping = ['buy', 'price', 'review', 'vs', 'best', 'cheap', 'deal'],
    local    = ['near me', 'nearby', 'restaurant', 'hotel', 'open now'],
    semantic = ['similar to', 'like this', 'related to', 'find me'],
)

INTENT_MAP = AttrDict(
    academic = ['exa', 'perplexity', 'tavily', 'searxng'],
    code     = ['serper', 'exa', 'ddg', 'searxng'],
    recent   = ['serper', 'brave', 'ddg', 'searxng'],
    shopping = ['serper', 'tavily', 'ddg'],
    local    = ['serper', 'ddg'],
    semantic = ['exa', 'tavily'],
    default  = ['serper', 'tavily', 'ddg', 'searxng'],
)

class Result(AttrDict):
    "A single search result. Fields: title, url, snippet, provider, ts (epoch float)."

class SearchResults(L):
    "L of Result objects. Gains .to_md(), .to_context(), .fetch_all() via @patch below."

class QuotaManager:
    def __init__(self, quota_file:str='~/.webba/quota.json', providers:dict=None):
        "Track free-tier quota per provider; persist across sessions."
        store_attr()
        self.providers = ifnone(providers, PROVIDERS)
        self._load()

    def _load(self):
        "Read quota.json; initialise missing providers to full quota."
        p = Path(self.quota_file).expanduser()
        self._data = json.loads(p.read_text()) if p.exists() else {}
        for name in self.providers:
            if name not in self._data:
                self._data[name] = dict(used=0, reset_ts=time.time())
            self._reset_if_due(name)

    def _save(self):
        "Write quota.json atomically (write tmp → rename)."
        p = Path(self.quota_file).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.rename(p)

    def _reset_if_due(self, name:str):
        "Reset counter if monthly/daily period has elapsed since last reset ts."
        cfg = self.providers[name]
        if not cfg.resets: return
        d = self._data[name]
        period = 86400 if cfg.resets == 'daily' else 86400 * 30  # ~30 day approximation for monthly
        if time.time() - d['reset_ts'] >= period:
            d['used'], d['reset_ts'] = 0, time.time()

    def remaining(self, name:str) -> int:
        "Remaining quota for provider `name`."
        self._reset_if_due(name)
        return self.providers[name].free_quota - self._data[name]['used']

    def consume(self, name:str, n:int=1):
        "Record n queries used for `name`; persist."
        self._data[name]['used'] += n
        self._save()

    def available(self, min_remaining:int=1) -> L:
        "L of provider names with quota > min_remaining AND (key set OR needs_key=False)."
        return L(self.providers.keys()).filter(
            lambda p: self.remaining(p) >= min_remaining and
                      (not self.providers[p].needs_key or os.environ.get(self.providers[p].env)) and
                      (p != 'searxng' or _searxng_enabled()))


class ProviderHealth:
    "Progressive cooldown tracker for search providers. Persists to health.json."
    COOLDOWNS = [60, 300, 1500, 3600]  # 1m → 5m → 25m → 1h
    FATAL     = {401, 403}
    TRANSIENT = {429, 502, 503, 504}

    def __init__(self, health_file:str='~/.webba/health.json'):
        store_attr()
        self._data = {}
        self._load()

    def _load(self):
        p = Path(self.health_file).expanduser()
        if p.exists():
            try: self._data = json.loads(p.read_text())
            except Exception: pass

    def _save(self):
        p = Path(self.health_file).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.rename(p)

    def record_failure(self, provider:str, status_code:int):
        "Escalate cooldown level; persist."
        d = self._data.setdefault(provider, {'failures': 0, 'cooldown_until': 0, 'level': 0})
        if status_code in self.FATAL: d['level'] = len(self.COOLDOWNS) - 1
        else: d['level'] = min(d.get('level', 0) + 1, len(self.COOLDOWNS) - 1)
        d['failures'] = d.get('failures', 0) + 1
        d['cooldown_until'] = time.time() + self.COOLDOWNS[d['level']]
        self._save()

    def record_success(self, provider:str):
        "Reset cooldown level on success."
        if provider in self._data:
            self._data[provider]['level'] = 0
            self._save()

    def is_available(self, provider:str) -> bool:
        "True if provider is not in active cooldown."
        d = self._data.get(provider)
        return not d or time.time() > d.get('cooldown_until', 0)


_health_singleton = None

def _get_health() -> ProviderHealth:
    global _health_singleton
    if _health_singleton is None: _health_singleton = ProviderHealth()
    return _health_singleton


class QueryAnalyzer:
    "Signal-weighted intent classifier. Returns (intent, providers, confidence, extras)."
    _INTENTS = {
        'academic': (['research', 'paper', 'study', 'arxiv', 'doi', 'journal', 'citation',
                      'how does', 'why is', 'define', 'explain', 'mechanism', 'overview'],
                     ['exa', 'perplexity', 'tavily', 'searxng']),
        'code':     (['github', 'python', 'javascript', 'stackoverflow', 'npm', 'pypi',
                      'error', 'bug', 'library', 'framework', 'repo'],
                     ['serper', 'exa', 'ddg', 'searxng']),
        'recent':   (['today', 'yesterday', 'this week', 'latest', 'breaking', 'current',
                      'live', 'just announced', '2025', '2026'],
                     ['serper', 'brave', 'ddg', 'searxng']),
        'shopping': (['buy', 'price', 'review', 'vs', 'best', 'cheap', 'deal',
                      'cost', 'coupon', 'discount', 'compare'],
                     ['serper', 'tavily', 'ddg']),
        'local':    (['near me', 'nearby', 'restaurant', 'hotel', 'open now'],
                     ['serper', 'ddg']),
        'semantic': (['similar to', 'like this', 'related to', 'find me',
                      'alternatives', 'companies like', 'benchmark'],
                     ['exa', 'tavily']),
    }

    def analyze(self, q:str) -> tuple:
        "Return (intent, providers, confidence, extras)."
        ql = q.lower()
        scores = {intent: sum(1 for pat in pats if pat in ql)
                  for intent, (pats, _) in self._INTENTS.items()}
        sorted_s = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_intent, top_score = sorted_s[0]
        second_score = sorted_s[1][1] if len(sorted_s) > 1 else 0

        if top_score == 0:
            return 'default', list(INTENT_MAP.default), 0.0, {}

        max_pats   = max(len(pats) for pats, _ in self._INTENTS.values())
        abs_conf   = top_score / max_pats
        margin     = (top_score - second_score) / max(top_score, 1)
        confidence = 0.6 * abs_conf + 0.4 * margin

        if confidence < 0.3:
            tied = sorted(i for i, s in scores.items() if s == top_score)
            if len(tied) > 1:
                idx = int(hashlib.sha256(f"{q}|{'|'.join(tied)}".encode()).hexdigest(), 16) % len(tied)
                top_intent = tied[idx]

        providers = list(self._INTENTS.get(top_intent, ([], list(INTENT_MAP.default)))[1])

        extras = {}
        if top_intent in ('academic', 'semantic'):
            extras['exa_depth'] = 'deep-reasoning' if top_score >= 6 else ('deep' if top_score >= 4 else 'normal')

        return top_intent, providers, confidence, extras


_SEARXNG_SETTINGS = """\
use_default_settings: true

general:
  instance_name: webba
  debug: false

search:
  safe_search: 0
  autocomplete: ""
  default_lang: "en"
  formats:
    - html
    - json

server:
  # local-only dev instance — not for production use
  secret_key: "webba-secret-change-in-prod"
  bind_address: "0.0.0.0:8080"

# hostname 'redis' resolves via Docker network
redis:
  url: redis://redis:6379/0

outgoing:
  request_timeout: 3.0
  max_request_timeout: 10.0
  pool_maxsize: 20
  enable_http2: true

engines:
  - {name: google,      engine: google,      shortcut: g,   weight: 2.0}
  - {name: bing,        engine: bing,        shortcut: b,   weight: 1.5}
  - {name: brave,       engine: brave,       shortcut: br,  weight: 1.5}
  - {name: duckduckgo,  engine: duckduckgo,  shortcut: d,   weight: 1.0}
  - {name: qwant,       engine: qwant,       shortcut: q,   weight: 1.0}
  - {name: arxiv,            engine: arxiv,            shortcut: arx, categories: science}
  - {name: semantic scholar, engine: semantic_scholar,  shortcut: ss,  categories: science}
  - {name: google scholar,   engine: google_scholar,    shortcut: gs,  categories: science}
  - {name: github,        engine: github,        shortcut: gh, categories: it}
  - {name: stackoverflow, engine: stackoverflow, shortcut: so, categories: it}
  - {name: google news, engine: google_news, shortcut: gn, categories: news}
  - {name: bing news,   engine: bing_news,   shortcut: bn, categories: news}
  - {name: yahoo,  engine: yahoo,  disabled: true}
  - {name: yandex, engine: yandex, disabled: true}
  - {name: baidu,  engine: baidu,  disabled: true}
  - {name: ask,    engine: ask,    disabled: true}
"""

_SEARXNG_URL     = 'http://localhost:8080'
_SEARXNG_NAME    = 'webba-searxng'
_SEARXNG_NETWORK = 'webba-net'
_SEARXNG_DIR     = Path('/tmp/webba-searxng')
_COMPOSE_PATH = str(_SEARXNG_DIR / 'docker-compose.yml')
_SEARXNG_OURS = False  # True only when _we_ started the container

def _searxng_enabled():
    "Check if SearXNG is eligible (WEBBA_SEARXNG != 'false')."
    return os.environ.get('WEBBA_SEARXNG', 'true').lower() != 'false'

def _ensure_searxng() -> str:
    "Start SearXNG + Redis via Compose if not running; write settings.yml; return base URL."
    global _SEARXNG_OURS
    from dockeasy import Compose
    url = os.environ.get('SEARXNG_URL')
    if url: return url
    _SEARXNG_DIR.mkdir(parents=True, exist_ok=True)
    (_SEARXNG_DIR / 'settings.yml').write_text(_SEARXNG_SETTINGS)
    (Compose()
        .network(_SEARXNG_NETWORK)
        .svc('redis',
             image='redis:7-alpine',
             command='redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru --save ""',
             networks=[_SEARXNG_NETWORK],
             restart='unless-stopped')
        .svc('searxng',
             image='searxng/searxng:latest',
             ports={'8080': '8080'},
             volumes={str(_SEARXNG_DIR): '/etc/searxng'},
             env={'SEARXNG_SECRET': 'webba'},
             container_name=_SEARXNG_NAME,
             depends_on=['redis'],
             networks=[_SEARXNG_NETWORK])
        .up(detach=True, path=_COMPOSE_PATH))
    _SEARXNG_OURS = True
    _wait_for_searxng(_SEARXNG_URL)
    return _SEARXNG_URL

def searxng_start() -> str:
    "Start SearXNG container. Idempotent. Returns base URL."
    return _ensure_searxng()

def searxng_stop():
    "Stop SearXNG container if we started it. No-op otherwise."
    global _SEARXNG_OURS
    if not _SEARXNG_OURS: return
    from dockeasy import Compose
    try: Compose().down(path=_COMPOSE_PATH)
    except Exception: pass
    _SEARXNG_OURS = False

atexit.register(searxng_stop)

def _wait_for_searxng(url:str, timeout:int=20, interval:float=0.5):
    "Poll SearXNG / until HTTP 200 or raise RuntimeError on timeout."
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if niquests.get(url, timeout=2).status_code == 200: return
        except Exception: pass
        time.sleep(interval)
    raise RuntimeError(f'SearXNG did not start within {timeout}s at {url}. Check Docker is running.')

def _api_search(env_var:str, req_fn, parse_fn, provider:str=None) -> L:
    "Generic API search: check key → request → parse. Records health on failure/success."
    key = os.environ.get(env_var)
    if not key: return L()
    try:
        r = req_fn(key)
        if r.status_code != 200:
            if provider: _get_health().record_failure(provider, r.status_code)
            return L()
        if provider: _get_health().record_success(provider)
        return parse_fn(r.json())
    except Exception:
        if provider: _get_health().record_failure(provider, 0)
        return L()

def _mk_result(provider:str, title_k='title', url_k='url', snippet_k='snippet'):
    "Return a lambda that builds a Result from a raw API dict."
    return lambda x: Result(title=x.get(title_k,''), url=x.get(url_k,''),
                            snippet=x.get(snippet_k,''), provider=provider, ts=time.time())

def _serper(q:str, n:int=10) -> L:
    "Search via Serper (Google) JSON API. Needs SERPER_API_KEY."
    return _api_search('SERPER_API_KEY',
        lambda k: niquests.post(PROVIDERS['serper'].base,
            headers={'X-API-KEY': k, 'Content-Type': 'application/json'},
            json={'q': q, 'num': n}, timeout=10),
        lambda d: L(d.get('organic', [])).map(_mk_result('serper', url_k='link')),
        provider='serper')

def _tavily(q:str, n:int=10) -> L:
    "Search via Tavily research API. Needs TAVILY_API_KEY."
    return _api_search('TAVILY_API_KEY',
        lambda k: niquests.post(PROVIDERS['tavily'].base,
            json={'api_key': k, 'query': q, 'max_results': n}, timeout=10),
        lambda d: L(d.get('results', [])).map(_mk_result('tavily', snippet_k='content')),
        provider='tavily')

def _exa(q:str, n:int=10, semantic:bool=False, depth:str='normal') -> L:
    "Search via Exa neural API. depth: 'normal'|'deep'|'deep-reasoning'. Needs EXA_API_KEY."
    use_neural = semantic or depth != 'normal'
    return _api_search('EXA_API_KEY',
        lambda k: niquests.post(PROVIDERS['exa'].base,
            headers={'x-api-key': k, 'Content-Type': 'application/json'},
            json={'query': q, 'numResults': n, 'type': 'neural' if use_neural else 'keyword',
                  'contents': {'text': {'maxCharacters': 300}}}, timeout=10),
        lambda d: L(d.get('results', [])).map(_mk_result('exa', snippet_k='text')),
        provider='exa')

def _perplexity(q:str, n:int=10) -> L:
    "Search via Perplexity Sonar. Returns cited answer as single Result. Needs PERPLEXITY_API_KEY."
    def _parse(d):
        content = d.get('choices', [{}])[0].get('message', {}).get('content', '')
        if not content: return L()
        url = (d.get('citations') or [''])[0]
        return L([Result(title=q, url=url, snippet=content[:500], provider='perplexity', ts=time.time())])
    return _api_search('PERPLEXITY_API_KEY',
        lambda k: niquests.post(PROVIDERS['perplexity'].base,
            headers={'Authorization': f'Bearer {k}', 'Content-Type': 'application/json'},
            json={'model': 'sonar', 'messages': [{'role': 'user', 'content': q}]}, timeout=30),
        _parse, provider='perplexity')

def _brave(q:str, n:int=10) -> L:
    "Search via Brave Search API. Needs BRAVE_API_KEY."
    return _api_search('BRAVE_API_KEY',
        lambda k: niquests.get(PROVIDERS['brave'].base,
            headers={'X-Subscription-Token': k, 'Accept': 'application/json'},
            params={'q': q, 'count': n}, timeout=10),
        lambda d: L(d.get('web', {}).get('results', [])).map(
            _mk_result('brave', snippet_k='description')),
        provider='brave')

def _ddg(q:str, n:int=10) -> L:
    "Search via DuckDuckGo (ddgs). Silently returns L() on rate limit — never raises."
    try:
        from duckduckgo_search import DDGS
        return L(DDGS().text(q, max_results=n)).map(_mk_result('ddg', url_k='href', snippet_k='body'))
    except Exception: return L()

def _searxng(q:str, n:int=10, engines:str=None, category:str=None) -> L:
    "Search via local SearXNG. category maps to SearXNG categories (news/science/it/shopping/general)."
    if not _searxng_enabled(): return L()
    try:
        url = _ensure_searxng()
        params = {'q': q, 'format': 'json', 'pageno': 1}
        if engines:  params['engines']    = engines
        if category: params['categories'] = category
        r = niquests.get(f'{url}/search', params=params, timeout=15)
        if r.status_code != 200: return L()
        return L(r.json().get('results', [])[:n]).map(lambda x: Result(
            title=x.get('title',''), url=x.get('url',''),
            snippet=x.get('content',''), provider='searxng', ts=time.time()))
    except Exception: return L()

def _google_scrape(q:str, n:int=10) -> L:
    "Scrape Google results via niquests + selectolax. Fragile CSS selectors — last free resort."
    from selectolax.parser import HTMLParser
    try:
        url = f'https://www.google.com/search?q={_url_quote(q)}&num={n}&hl=en&gl=us'
        r = niquests.get(url, headers=_random_ua(), timeout=10)
        if r.status_code != 200: return L()
        tree = HTMLParser(r.text)
        results = L()
        for block in tree.css('div.g'):
            a    = block.css_first('a[href]')
            h    = block.css_first('h3')
            snip = block.css_first('.VwiC3b') or block.css_first('[data-sncf]')
            if not (a and h): continue
            href = a.attrs.get('href', '')
            if not href.startswith('http'): continue
            results.append(Result(title=h.text(), url=href,
                                  snippet=snip.text() if snip else '',
                                  provider='google_scrape', ts=time.time()))
        return results[:n]
    except Exception: return L()

_PROVIDER_FNS = {
    'serper': _serper, 'tavily': _tavily, 'exa': _exa,
    'perplexity': _perplexity, 'brave': _brave,
    'ddg': _ddg, 'searxng': _searxng, 'google_scrape': _google_scrape,
}

def route(q:str, quota:QuotaManager=None, health:ProviderHealth=None) -> tuple:
    "Pick best available provider. Returns (provider, intent, extras)."
    qm = ifnone(quota, QuotaManager())
    hp = ifnone(health, _get_health())
    intent, preferred, _conf, extras = QueryAnalyzer().analyze(q)
    ordered = list(dict.fromkeys(preferred + FREE_TIER_ORDER))
    avail = set(qm.available())
    candidates = [p for p in ordered if p in avail and hp.is_available(p)]
    non_fragile = [p for p in candidates if not PROVIDERS[p].fragile]
    chosen = (non_fragile or candidates or [first(qm.available()) or 'ddg'])[0]
    return chosen, intent, extras

def rerank(results:L, k:int=60) -> L:
    "RRF merge: per-provider rank scoring. Deduplicates by URL."
    groups = {}
    for r in results: groups.setdefault(r.provider, []).append(r)
    scores = {}
    for lst in groups.values():
        for rank, r in enumerate(lst):
            s = 1.0 / (k + rank)
            if r.url in scores: scores[r.url]['_rrf'] += s
            else: scores[r.url] = merge(dict(r), {'_rrf': s})
    ranked = sorted(scores.values(), key=lambda x: x['_rrf'], reverse=True)
    return L(ranked).map(lambda x: Result(**filter_keys(x, lambda k: k != '_rrf')))

def search(q:str, n:int=10, provider:str='auto', cache:bool=True,
           quota_file:str='~/.webba/quota.json', cache_ttl:int=3600) -> SearchResults:
    "Search the web. Smart routing, quota tracking, semantic SQLite cache. Zero API keys needed."
    if _lsclean(q) is None: return SearchResults()
    from .cache import SemanticSearchCache
    qm = QuotaManager(quota_file=quota_file)
    sc = SemanticSearchCache(ttl=cache_ttl) if cache else None
    if sc:
        cached = sc.get(q)
        if cached is not None:
            return SearchResults(L(cached).map(lambda r: Result(**r) if isinstance(r, dict) else r))
    hp = _get_health()
    if provider == 'all':
        avail = qm.available()
        provider_results = L(_par(lambda p: (p, _PROVIDER_FNS[p](q, n)), avail, threadpool=True))
        for p, _ in provider_results: qm.consume(p)
        all_results = L()
        for _, rs in provider_results: all_results += rs
        results = rerank(all_results)[:n]
    else:
        if provider == 'auto':
            p, intent, extras = route(q, quota=qm, health=hp)
        else:
            p, intent, extras = provider, 'default', {}
        if p == 'searxng':
            results = _searxng(q, n, category=SEARXNG_CATEGORY_MAP.get(intent, 'general'))
        elif p == 'exa' and extras.get('exa_depth'):
            results = _exa(q, n, depth=extras['exa_depth'])
        else:
            results = _PROVIDER_FNS[p](q, n)
        qm.consume(p)
    if sc: sc.set(q, results)
    return SearchResults(results)

@patch
def to_md(self:SearchResults) -> str:
    "Format as markdown numbered list with title, URL, snippet."
    return '\n'.join(f'{i+1}. **[{r.title}]({r.url})**  \n   {r.snippet}'
                     for i, r in enumerate(self))

@patch
def to_context(self:SearchResults, max_chars:int=4000) -> str:
    "Concatenate snippets as LLM context string, truncated to max_chars."
    parts, total = L(), 0
    for r in self:
        s = f'{r.title}: {r.snippet}'
        if total + len(s) > max_chars: break
        parts.append(s)
        total += len(s)
    return '\n'.join(parts)

@patch
def fetch_all(self:SearchResults, sel:str=None, heavy:bool=False) -> L:
    "Fetch full page content for each URL in parallel. Returns L of strings."
    from .fetch import fetch as _fetch
    return L(_par(lambda r: _fetch(r.url, sel=sel, heavy=heavy), self, threadpool=True))

@patch
def fetch(self:Result, sel:str=None, heavy:bool=False) -> str:
    "Fetch full page content for this result."
    from .fetch import fetch as _fetch
    return _fetch(self.url, sel=sel, heavy=heavy)

@call_parse
def _cli(
    q:              Param("Search query", str)='',
    n:              Param("Number of results", int)=10,
    provider:       Param("Provider: auto|serper|tavily|exa|perplexity|brave|ddg|searxng|all", str)='auto',
    fmt:            Param("Output format: md|json", str)='md',
    purge_cache:    Param("Purge all cached results", bool)=False,
    start_searxng:  Param("Start SearXNG container", bool)=False,
    stop_searxng:   Param("Stop SearXNG container", bool)=False,
):
    "Search the web from the terminal."
    if start_searxng:
        print(f'SearXNG started at {searxng_start()}')
        return
    if stop_searxng:
        searxng_stop()
        print('SearXNG stopped.')
        return
    if purge_cache:
        from .cache import SemanticSearchCache
        SemanticSearchCache().purge()
        print('Cache purged.')
        return
    if not q:
        print('Usage: webba "search query" [--n N] [--provider PROV] [--fmt md|json]')
        return
    results = search(q, n=n, provider=provider)
    print(results.to_md() if fmt == 'md' else json.dumps([dict(r) for r in results], indent=2))
