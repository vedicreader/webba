# webba

Zero-config web search with automatic quota management across free and paid providers.

## Functions

### search(q, n=10, provider='auto', cache=True)
Search the web. Returns SearchResults (list of Result with .title, .url, .snippet, .provider).
- provider options: 'auto' | 'serper' | 'tavily' | 'exa' | 'perplexity' | 'brave' | 'ddg' | 'searxng' | 'all'
- Works with zero API keys: routes to DDG → SearXNG → Google scrape automatically

### fetch(url, sel=None, heavy=False, cdp=False, **kwargs)
Fetch any URL as clean markdown/text.
- Handles: GitHub files/repos, arxiv, gists, PDFs, HTML, local files
- sel: CSS selector to extract specific content from HTML
- heavy: use headless browser (playwrightnb) for JS-heavy pages
- cdp: attach to existing Chrome session for login-gated pages (requires webba[cdp])
- kwargs forwarded to read_gh_repo for repo URLs (branch, as_dict, included_patterns, etc.)

### quota_status()
Return remaining free-tier quota for all providers as dict.

### install_hermes_plugin(hermes_home=None) -> str
Install webba as the default web_search backend for Hermes Agent.
- Copies the plugin to {hermes_home}/plugins/webba/ (default: ~/.hermes/plugins/webba/)
- hermes_home: override via param, HERMES_HOME env var, or defaults to ~/.hermes
- Returns JSON: {"installed": true, "path": "...", "message": "..."}
- Idempotent — safe to call multiple times

### uninstall_hermes_plugin(hermes_home=None) -> str
Remove the webba-search Hermes plugin directory.
- Returns JSON: {"uninstalled": true, "path": "...", "message": "..."}

## Hermes Agent Integration

webba registers as a Hermes tool plugin, replacing `web_search` with a cascade:

```
webba.search(q)  →  results?  ✅
                 →  empty / raises  →  hermes native web_search_tool(q)  ✅
                                    →  both fail  →  {"results":[], "error":"..."}
```

### Install (two ways)

**Option A — pip entry-point (auto, zero steps):**
`pip install webba` — hermes discovers the plugin automatically on next start.

**Option B — explicit file install (karma-style):**
```python
from webba.skill import install_hermes_plugin
install_hermes_plugin()
```
Or via CLI: `webba-install-hermes`

## Environment Variables (all optional)
SERPER_API_KEY, TAVILY_API_KEY, EXA_API_KEY, PERPLEXITY_API_KEY, BRAVE_API_KEY
SEARXNG_URL  — override auto-started localhost SearXNG (for production deployments)
HERMES_HOME  — override Hermes config dir (default: ~/.hermes)

## Zero-Key Behaviour
With no API keys:
1. DuckDuckGo (instant, silently rate-limited)
2. SearXNG Docker container on localhost:8080 (first call ~3s via Compose.up(), subsequent instant)
   Aggregates: Google, Bing, Brave, DDG, Qwant, arXiv, GitHub, StackOverflow, Google News
3. Google scrape via niquests + selectolax (fragile, last resort)

