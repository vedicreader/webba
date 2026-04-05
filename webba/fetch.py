"""webba — ALL fetch logic"""

from fastcore.all import delegates, patch, L, ifnone
from contextkit.read import read_gh_file, read_gh_repo, read_gist, read_arxiv, read_link
from selectolax.parser import HTMLParser
import niquests, re, os, random, time
from pathlib import Path

_UAS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3) AppleWebKit/605.1.15 Version/17.2 Mobile Safari/604.1',
]
def _random_ua() -> dict: return {'User-Agent': random.choice(_UAS)}

_GH_FILE = re.compile(r'https://github\.com/[^/]+/[^/]+/blob/')
_GH_REPO = re.compile(r'https://github\.com/[^/]+/[^/]+/?$')
_GIST    = re.compile(r'https://gist\.github\.com/')
_ARXIV   = re.compile(r'(arxiv\.org|ar5iv\.org)')
_DOCS    = re.compile(r'(readthedocs|docs\.|/docs/|\.readthedocs\.io)')

def _url_type(url:str) -> str:
    "Classify URL: gh_file|gh_repo|gist|arxiv|pdf|docs|html|local"
    if not url.startswith('http'): return 'local'
    if _GH_FILE.search(url): return 'gh_file'
    if _GH_REPO.search(url): return 'gh_repo'
    if _GIST.search(url):    return 'gist'
    if _ARXIV.search(url):   return 'arxiv'
    if url.endswith('.pdf'):  return 'pdf'
    if _DOCS.search(url):    return 'docs'
    return 'html'

def _extract(html:str, sel:str=None) -> str:
    "Extract clean text from HTML via selectolax. Removes scripts/nav/footer."
    tree = HTMLParser(html)
    for tag in tree.css('script,style,nav,footer,[role=navigation],header'): tag.decompose()
    node = (tree.css_first(sel) if sel
            else tree.css_first('main,article,[role=main]') or tree.body)
    return node.text(separator='\n', strip=True) if node else ''

@delegates(read_link, but=['url'])
def _fetch_html(url:str, **kwargs) -> str:
    "Fetch HTML. Tier cascade: niquests → Jina → contextkit read_link (with same kwargs)."
    sel = kwargs.get('sel')
    cdp = kwargs.pop('cdp', False)
    if cdp:
        from fastcdp import fetch as cdp_fetch
        return cdp_fetch(url, sel=sel)
    # Tier 1: niquests
    try:
        r = niquests.get(url, headers=_random_ua(), timeout=15)
        if r.status_code == 200 and len(r.text) > 500:
            return _extract(r.text, sel)
    except Exception: pass
    # Tier 2: Jina
    try:
        r = niquests.get(f'https://r.jina.ai/{url}', timeout=20)
        if r.status_code == 200: return r.text
    except Exception: pass
    # Tier 3: playwrightnb via contextkit — kwargs forwarded here (this validates @delegates)
    try: return read_link(url, **kwargs)
    except Exception: return ''

def _fetch_docs(url:str, sel:str=None) -> str:
    "Try llms-full.txt → llms.txt → plain HTML for documentation URLs."
    base = url.rstrip('/').split('/docs')[0] if '/docs' in url else '/'.join(url.split('/')[:3])
    for suffix in ('/llms-full.txt', '/llms.txt'):
        try:
            r = niquests.get(base + suffix, timeout=10)
            if r.status_code == 200: return r.text
        except Exception: pass
    return _fetch_html(url, sel=sel)

@delegates(read_gh_repo, but=['path_or_url'])
def fetch(url:str,
          sel:str=None,
          heavy:bool=False,
          cdp:bool=False,
          save_pdf:bool=False,
          **kwargs,
) -> 'str|dict':
    "Fetch any URL or local path as clean text. kwargs forwarded to read_gh_repo for repo URLs."
    t = _url_type(url)
    if t == 'gh_file':  return read_gh_file(url)
    if t == 'gh_repo':  return read_gh_repo(url, **kwargs)
    if t == 'gist':     return read_gist(url)
    if t == 'arxiv':    return read_arxiv(url, save_pdf=save_pdf)
    if t == 'pdf':
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(niquests.get(url, timeout=30).content); tmp = f.name
        from contextkit.read import read_pdf
        return read_pdf(tmp)
    if t == 'docs':     return _fetch_docs(url, sel=sel)
    if t == 'local':    return Path(url).read_text()
    return _fetch_html(url, sel=sel, heavy=heavy, cdp=cdp)
