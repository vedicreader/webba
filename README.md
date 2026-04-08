# webba

Zero-config web search: free-tier quota management, smart routing, any-URL fetching.

## Install

```bash
pip install webba
```

## Quick Start

```python
from webba import search, fetch

# Search — zero API keys needed (DDG + SearXNG + Google scrape)
results = search('python asyncio tutorial', n=5)
print(results.to_md())

# Fetch any URL as clean text
text = fetch('https://github.com/AnswerDotAI/ContextKit/blob/main/contextkit/read.py')
```

## CLI

```bash
webba "python asyncio" --n 5 --fmt md
webba "latest AI news" --provider ddg --fmt json
webba --purge-cache
webba --start-searxng
webba --stop-searxng
```

## Features

- **Zero-key search**: DuckDuckGo → SearXNG (auto-started Docker) → Google scrape
- **Paid providers**: Serper, Tavily, Exa, Perplexity, Brave — added when API keys are set
- **Smart routing**: Intent detection routes queries to the best provider
- **Quota tracking**: Free-tier quota persisted in `~/.webba/quota.json`
- **Semantic cache**: Paraphrase-tolerant SQLite cache via vector + FTS hybrid search (`~/.webba/cache.db`)
- **Any-URL fetch**: GitHub files/repos, arxiv, gists, PDFs, docs, HTML → clean text
- **Tier cascade**: niquests → Jina → playwrightnb → fastcdp for HTML fetching
- **Hermes Agent plugin**: Drop-in `web_search` replacement with graceful fallback

## Hermes Agent Integration

webba becomes the default web search backend for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — zero API keys required, with a graceful cascade fallback to hermes's native backend.

### Option A — pip (auto-discovered, zero extra steps)

```bash
pip install webba
# hermes picks up the plugin automatically on next start via entry-point discovery
```

### Option B — explicit install (karma-style one-liner)

```python
from webba.skill import install_hermes_plugin
result = install_hermes_plugin()
# → {"installed": true, "path": "~/.hermes/plugins/webba/__init__.py", ...}
```

Or from the terminal:

```bash
webba-install-hermes
# ✅  webba-search plugin installed to ~/.hermes/plugins/webba/__init__.py
```

Pass a custom Hermes home if you use a non-default location:

```bash
webba-install-hermes /path/to/hermes-home
```

### How it works

```
web_search(query)
    │
    ├─ webba.search(q, n=5) → results      ──────────────────────► _fmt(results)  ✅
    │
    ├─ webba.search(q, n=5) → empty list   ──────────────────────► hermes web_search_tool(q)
    │
    ├─ webba.search(q, n=5) → raises       ──────────────────────► hermes web_search_tool(q)
    │
    └─ hermes also fails    ──────────────────────────────────────► {"results":[], "error":"..."}
```

The plugin registers at Hermes startup — after `_discover_tools()`, before tools are frozen — so `TOOL_TO_TOOLSET_MAP` and `TOOLSET_REQUIREMENTS` see the webba handler. The `web` toolset check is patched to `lambda: True` (DDG needs no API key), so `hermes tools` always shows web as available.

### Uninstall

```python
from webba.skill import uninstall_hermes_plugin
uninstall_hermes_plugin()
# → {"uninstalled": true, ...}
```

## Environment Variables (all optional)

| Variable | Provider |
|---|---|
| `SERPER_API_KEY` | Google via Serper |
| `TAVILY_API_KEY` | Tavily research API |
| `EXA_API_KEY` | Exa neural search |
| `PERPLEXITY_API_KEY` | Perplexity Sonar |
| `BRAVE_API_KEY` | Brave Search |
| `SEARXNG_URL` | Override auto-started SearXNG |
| `WEBBA_SEARXNG` | Set to `false` to disable SearXNG entirely (default: `true`) |
| `HERMES_HOME` | Override Hermes config dir (default: `~/.hermes`) |

## API

### `search(q, n=10, provider='auto', cache=True, quota_file='~/.webba/quota.json', cache_ttl=3600)`

Search the web. Returns `SearchResults` (list of `Result` with `.title`, `.url`, `.snippet`, `.provider`).

- `provider`: `'auto'` | `'serper'` | `'tavily'` | `'exa'` | `'perplexity'` | `'brave'` | `'ddg'` | `'searxng'` | `'all'`

### `fetch(url, sel=None, heavy=False, cdp=False, save_pdf=False, **kwargs)`

Fetch any URL as clean text/markdown. Handles GitHub files/repos, arxiv, gists, PDFs, HTML, local files.

### `SearchResults.to_md() -> str`

Format results as a markdown numbered list with title, URL, and snippet.

### `SearchResults.to_context(max_chars=4000) -> str`

Concatenate snippets into an LLM context string, truncated to `max_chars`.

### `SearchResults.fetch_all(sel=None, heavy=False) -> L`

Fetch full page content for each result URL in parallel. Returns `L` of strings.

### `Result.fetch(sel=None, heavy=False) -> str`

Fetch full page content for a single result.

### `quota_status() -> dict`

Return remaining quota for all configured providers.

### `install_hermes_plugin(hermes_home=None) -> str`

Install webba as a Hermes Agent web-search plugin. Returns JSON status dict.

### `uninstall_hermes_plugin(hermes_home=None) -> str`

Remove the webba-search Hermes plugin. Returns JSON status dict.

### `purge_cache(db_path='~/.webba/cache.db', q=None, ttl_only=False)`

Purge cached search results.

- Default (no args): wipe entire cache.
- `q='my query'`: semantic purge — delete only entries matching the query topic.
- `ttl_only=True`: delete only entries older than the cache TTL.

### `SemanticSearchCache(db_path='~/.webba/cache.db', ttl=3600, threshold=0.022)`

Low-level cache API. Combines FTS5 and vector search (RRF fusion) for paraphrase-tolerant lookup.

```python
from webba import search
from webba.cache import SemanticSearchCache

results = search('python async tutorial', n=5)

sc = SemanticSearchCache(ttl=3600)
sc.set('python async tutorial', results)   # store with embedding
sc.get('asyncio python guide')             # semantic hit → returns list
sc.purge_expired()                         # → int (rows deleted)
sc.purge_semantic('python async', threshold=0.016)  # → L of deleted rows
sc.purge_topic('python async')             # → AttrDict(expired, semantic, dry_run)
```

Embeddings use [`minishlab/potion-base-8M`](https://huggingface.co/minishlab/potion-base-8M) (≈30 MB, lazy-loaded on first use). RRF score thresholds:

| Score | Meaning |
|---|---|
| ≥ 0.030 | Near-exact match |
| ≥ 0.022 | Safe paraphrase hit (default `threshold`) |
| ≥ 0.016 | Weak match — useful for broad `purge_semantic` sweeps |

### `searxng_start()`

Start SearXNG container. Idempotent. Returns base URL.

### `searxng_stop()`

Stop SearXNG container if webba started it. No-op otherwise.

## Architecture

| File | Owns |
|---|---|
| `webba/search.py` | Provider functions, quota, routing, CLI |
| `webba/cache.py` | `SemanticSearchCache` — vector + FTS hybrid cache |
| `webba/fetch.py` | URL classification, HTML extraction, fetch cascade |
| `webba/_utils.py` | Shared helpers (`_random_ua`) |
| `webba/skill.py` | Skill descriptor (`allow()`), Hermes install CLI |
| `webba/plugins/__init__.py` | File-based Hermes plugin installer/uninstaller |
| `webba/plugins/hermes_search.py` | Hermes `register(ctx)` entrypoint, runtime handler |

## License

Apache-2.0

