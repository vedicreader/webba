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

## Environment Variables (all optional)
SERPER_API_KEY, TAVILY_API_KEY, EXA_API_KEY, PERPLEXITY_API_KEY, BRAVE_API_KEY
SEARXNG_URL  — override auto-started localhost SearXNG (for production deployments)

## Zero-Key Behaviour
With no API keys:
1. DuckDuckGo (instant, silently rate-limited)
2. SearXNG Docker container on localhost:8080 (first call ~3s via Compose.up(), subsequent instant)
   Aggregates: Google, Bing, Brave, DDG, Qwant, arXiv, GitHub, StackOverflow, Google News
3. Google scrape via niquests + selectolax (fragile, last resort)
