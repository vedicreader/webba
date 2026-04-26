from .search import search, SearchResults, Result, QuotaManager, ProviderHealth, QueryAnalyzer, route, rerank, PROVIDERS, SEARXNG_CATEGORY_MAP, searxng_start, searxng_stop
from .cache import SemanticSearchCache
from .fetch import fetch, crawl

__version__ = "0.1.0"

def purge_cache(db_path:str='~/.webba/cache.db', q:str=None, ttl_only:bool=False):
    "Purge cached search results. Pass q for semantic purge, ttl_only for expired-only."
    sc = SemanticSearchCache(db_path=db_path)
    if q:
        return sc.purge_semantic(q)
    if ttl_only:
        return sc.purge_expired()
    sc.purge()
