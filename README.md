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
- **SQLite cache**: Never burn quota twice — cached in `~/.webba/cache.db`
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

### `install_hermes_plugin(hermes_home=None) -> str`

Install webba as a Hermes Agent web-search plugin. Returns JSON status dict.

### `uninstall_hermes_plugin(hermes_home=None) -> str`

Remove the webba-search Hermes plugin. Returns JSON status dict.

### `purge_cache(db_path='~/.webba/cache.db')`

Purge all cached search results.

### `searxng_start()`

Start SearXNG container. Idempotent. Returns base URL.

### `searxng_stop()`

Stop SearXNG container if webba started it. No-op otherwise.

## Architecture

| File | Owns |
|---|---|
| `webba/search.py` | Provider functions, quota, cache, routing, CLI |
| `webba/fetch.py` | URL classification, HTML extraction, fetch cascade |
| `webba/_utils.py` | Shared helpers (`_random_ua`) |
| `webba/skill.py` | Skill descriptor (`allow()`), Hermes install CLI |
| `webba/plugins/__init__.py` | File-based Hermes plugin installer/uninstaller |
| `webba/plugins/hermes_search.py` | Hermes `register(ctx)` entrypoint, runtime handler |

## License

Apache-2.0

