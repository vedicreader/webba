"""webba — ALL fetch logic"""

from fastcore.all import delegates, patch, L, ifnone
from contextkit.read import read_gh_file, read_gh_repo, read_gist, read_arxiv, read_link
from selectolax.parser import HTMLParser
from ._utils import _random_ua
import niquests, re, os, time
from pathlib import Path
from urllib.parse import urljoin, urlparse

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
    sel = kwargs.pop('sel', None)
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

def _links(html:str, base:str, pat:str=None) -> L:
    "Absolute links from HTML, optionally filtered by regex pattern."
    hrefs = L(a.attrs.get('href','') for a in HTMLParser(html).css('a[href]'))
    urls  = L(urljoin(base,h) for h in hrefs if h and not h.startswith(('#','mailto:','javascript:')))
    return (urls.filter(re.compile(pat).search) if pat else urls).unique()

def crawl(seed:str, link_pat:str=None, sel:str=None,
          max_pages:int=500, delay:float=0.5, same_domain:bool=True,
          save_dir:str=None) -> L:
    "Crawl `seed`, follow links, return L of {url,text} dicts. Saves .txt per page to `save_dir` if given."
    dom = urlparse(seed).netloc
    seen, queue, out = set(), [seed], L()
    if save_dir: Path(save_dir).mkdir(parents=True, exist_ok=True)
    with niquests.Session() as s:
        while queue and len(out) < max_pages:
            url = queue.pop(0)
            if url in seen: continue
            seen.add(url)
            try:
                r = s.get(url, headers=_random_ua(), timeout=15)
                if r.status_code != 200 or len(r.text) < 200: continue
                html = r.text
            except Exception: continue
            text = _extract(html, sel)
            if not text: continue
            out.append({'url': url, 'text': text})
            if save_dir:
                slug = re.sub(r'[^\w-]', '_', urlparse(url).path).strip('_') or 'index'
                (Path(save_dir)/f'{slug}.txt').write_text(text, encoding='utf-8')
            new = _links(html, url, link_pat)
            if same_domain: new = new.filter(lambda u: urlparse(u).netloc == dom)
            queue += [u for u in new if u not in seen]
            if queue: time.sleep(delay)
    return out

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
        try:
            import litesearch  # side-effect: applies pdf_markdown patch onto pdf_oxide.PdfDocument
            from pdf_oxide import PdfDocument
            return '\n\n'.join(PdfDocument(tmp).pdf_markdown())
        except Exception:
            from contextkit.read import read_pdf
            return read_pdf(tmp)
        finally:
            os.unlink(tmp)
    if t == 'docs':     return _fetch_docs(url, sel=sel)
    if t == 'local':    return Path(url).read_text()
    return _fetch_html(url, sel=sel, heavy=heavy, cdp=cdp)
