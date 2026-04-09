"""SemanticSearchCache — vector + FTS hybrid cache for webba queries."""

from fastcore.all import store_attr, ifnone, L, AttrDict
from litesearch import database
from pathlib import Path
import json, time, numpy as np

__all__ = ['SemanticSearchCache']

_MODEL_ID = 'minishlab/potion-base-8M'

class SemanticSearchCache:
    "Semantic SQLite cache: stores query embeddings for paraphrase-tolerant lookup."

    _GET_LIMIT   = 5   # candidates considered in get() — only top match matters
    _PURGE_LIMIT = 50  # candidates considered in purge_semantic() — broader sweep

    def __init__(self, db_path:str='~/.webba/cache.db', ttl:int=3600, threshold:float=0.022):
        store_attr()
        self.db = database(Path(db_path).expanduser())
        self.store = self.db.get_store(name='webba_cache')
        self.db.execute('CREATE INDEX IF NOT EXISTS _idx_webba_cache_ts ON webba_cache(uploaded_at)')
        self._enc = None

    @property
    def enc(self):
        "Lazily loaded StaticModel encoder."
        return ifnone(self._enc, self._load_enc())

    def _load_enc(self):
        from model2vec import StaticModel
        self._enc = StaticModel.from_pretrained(_MODEL_ID)
        return self._enc

    def _emb(self, q:str) -> bytes:
        "Encode query string to float16 bytes."
        return self.enc.encode([q])[0].astype(np.float16).tobytes()

    def get(self, q:str, threshold:float=None) -> list|None:
        "Return cached results for q if fresh and above threshold, else None."
        emb = self._emb(q)
        hits = self.db.search(q=q, emb=emb, table_name='webba_cache',
                              columns=['metadata', 'uploaded_at'], limit=self._GET_LIMIT)
        if not hits: return None
        top = hits[0]
        if time.time() - top['uploaded_at'] > self.ttl: return None
        if top['_rrf_score'] < ifnone(threshold, self.threshold): return None
        return json.loads(top['metadata'])

    def set(self, q:str, results:list):
        "Store results with query embedding and current timestamp."
        self.store.insert({'content': q, 'embedding': self._emb(q),
                           'metadata': json.dumps([dict(r) for r in results]),
                           'uploaded_at': time.time()})

    def purge(self) -> None:
        "Delete all cached entries."
        self.db.execute('DELETE FROM webba_cache')

    def purge_expired(self, ttl:int=None) -> int:
        "Delete entries older than ttl. Returns number of rows deleted."
        self.db.execute('DELETE FROM webba_cache WHERE uploaded_at < ?',
                        [time.time() - ifnone(ttl, self.ttl)])
        return self.db.conn.changes()

    def purge_semantic(self, q:str, threshold:float=None, limit:int=None,
                       dry_run:bool=False) -> L:
        "Delete cache entries semantically matching q. Returns deleted (or would-be) victims."
        emb = self._emb(q)
        hits = self.db.search(q, emb, table_name='webba_cache',
                              columns=['content', 'uploaded_at'],
                              limit=ifnone(limit, self._PURGE_LIMIT))
        victims = L(hits or []).filter(lambda h: h['_rrf_score'] >= ifnone(threshold, self.threshold))
        if dry_run or not victims: return victims
        placeholders = ','.join('?' * len(victims))
        self.db.execute(f'DELETE FROM webba_cache WHERE rowid IN ({placeholders})',
                        [v['rowid'] for v in victims])
        return victims

    def purge_topic(self, q:str, threshold:float=None, include_expired:bool=True,
                    dry_run:bool=False) -> AttrDict:
        "Purge expired entries and semantic matches for q in one call."
        expired = self.purge_expired() if include_expired and not dry_run else 0
        semantic = self.purge_semantic(q, threshold=threshold, dry_run=dry_run)
        return AttrDict(expired=expired, semantic=semantic, dry_run=dry_run)
