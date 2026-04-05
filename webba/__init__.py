from .search import search, SearchResults, Result, QuotaManager, SearchCache, route, rerank, PROVIDERS, searxng_start, searxng_stop
from .fetch import fetch

def purge_cache(db_path:str='~/.webba/cache.db'):
    "Purge all cached search results."
    SearchCache(db_path=db_path).purge()
