"""webba skill interface for pyskills / Hermes agent frameworks"""

from fastcore.all import AttrDict
from .search import search, QuotaManager, PROVIDERS
from .fetch import fetch

def allow():
    "Return skill descriptor for pyskills / Hermes agent framework discovery."
    return AttrDict(name='webba', version='0.1.0',
                    description='Zero-config web search across free and paid providers',
                    functions=[search, fetch, quota_status])

def quota_status() -> dict:
    "Return remaining quota for all configured providers."
    qm = QuotaManager()
    return {name: qm.remaining(name) for name in PROVIDERS}
