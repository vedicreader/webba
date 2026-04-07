"""webba skill interface for pyskills / Hermes agent frameworks"""

import json
from fastcore.all import AttrDict
from .search import search, QuotaManager, PROVIDERS
from .fetch import fetch
from webba import purge_cache

def allow():
    "Return skill descriptor for pyskills / Hermes agent framework discovery."
    return AttrDict(name='webba', version='0.1.0',
                    description='Zero-config web search across free and paid providers',
                    functions=[search, fetch, quota_status, purge_cache,
                               install_hermes_plugin, uninstall_hermes_plugin])

def quota_status() -> dict:
    "Return remaining quota for all configured providers."
    qm = QuotaManager()
    return {name: qm.remaining(name) for name in PROVIDERS}

def install_hermes_plugin(hermes_home: str | None = None) -> str:
    "Auto-install webba as a Hermes Agent web-search plugin. Single call, zero config."
    from .plugins import install_hermes_plugin as _i
    return json.dumps(_i(hermes_home=hermes_home))

def uninstall_hermes_plugin(hermes_home: str | None = None) -> str:
    "Remove the webba-search Hermes plugin. Returns JSON status."
    from .plugins import uninstall_hermes_plugin as _u
    return json.dumps(_u(hermes_home=hermes_home))

def _install_hermes_cli():
    "Entry point for `webba-install-hermes` CLI command."
    import sys
    from .plugins import install_hermes_plugin as _i
    result = _i(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"{'✅' if result['installed'] else '❌'}  {result['message']}")
    sys.exit(0 if result["installed"] else 1)
