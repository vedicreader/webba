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

## API

### `search(q, n=10, provider='auto', cache=True, quota_file='~/.webba/quota.json', cache_ttl=3600)`

Search the web. Returns `SearchResults` (list of `Result` with `.title`, `.url`, `.snippet`, `.provider`).

- `provider`: `'auto'` | `'serper'` | `'tavily'` | `'exa'` | `'perplexity'` | `'brave'` | `'ddg'` | `'searxng'` | `'all'`

### `fetch(url, sel=None, heavy=False, cdp=False, save_pdf=False, **kwargs)`

Fetch any URL as clean text/markdown. Handles GitHub files/repos, arxiv, gists, PDFs, HTML, local files.

### `purge_cache(db_path='~/.webba/cache.db')`

Purge all cached search results.

### `searxng_start()`

Start SearXNG container. Idempotent. Returns base URL.

### `searxng_stop()`

Stop SearXNG container if webba started it. No-op otherwise.

## License

Apache-2.0

