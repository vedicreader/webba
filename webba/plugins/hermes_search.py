"""Webba search plugin for Hermes Agent.

Override hermes's built-in web_search with webba as primary backend,
falling back to native web_search_tool on empty results or any exception.

Installed via:
    from webba.skill import install_hermes_plugin; install_hermes_plugin()

Or auto-discovered via pip entry-point:
    [project.entry-points."hermes_agent.plugins"]
    webba-search = "webba.plugins.hermes_search"
"""
from __future__ import annotations
import json, logging
logger = logging.getLogger(__name__)

_webba_search = None
try:
    from webba import search as _webba_search
except ImportError:
    logger.info("webba not installed — native hermes web_search remains active. "
                "Run: pip install webba")


def _fmt(results) -> str:
    """Convert webba SearchResults (L of Result AttrDict) → hermes JSON format.

    hermes expects: {"results": [{"title", "url", "description"}, ...]}
    """
    def _get_attr(r, k, d=''):
        return r[k] if isinstance(r, dict) else getattr(r, k, d)
    return json.dumps(
        {"results": [{"title": _get_attr(r, "title"), "url": _get_attr(r, "url"),
                      "description": _get_attr(r, "snippet"), "provider": _get_attr(r, "provider", "webba")}
                     for r in results]},
        ensure_ascii=False, indent=2)


def _make_handler():
    """Return handler: webba primary → hermes fallback → error JSON."""
    def handler(args: dict, **kw) -> str:
        q = (args.get('query') or '').strip()
        if not q: return json.dumps({"results": [], "error": "Empty query"})
        # Primary: webba
        if _webba_search is not None:
            try:
                results = _webba_search(q, n=5)
                if results:
                    logger.debug("webba: %d result(s) via %s for %r", len(results),
                                 getattr(results[0], 'provider', '?'), q)
                    return _fmt(results)
                logger.debug("webba: empty — falling back for %r", q)
            except Exception as exc:
                logger.warning("webba raised %s(%s) — falling back for %r",
                               type(exc).__name__, exc, q)
        # Fallback: hermes native
        try:
            from tools.web_tools import web_search_tool
            return web_search_tool(q, limit=5)
        except Exception as exc2:
            logger.error("hermes fallback also failed: %s", exc2)
            return json.dumps({"results": [], "error": str(exc2)})
    return handler


WEB_SEARCH_SCHEMA = {
    "name": "web_search",
    "description": (
        "Search the web for information on any topic. Returns up to 5 relevant "
        "results with titles, URLs, and descriptions. "
        "Powered by webba (DDG/SearXNG/Google/Serper/Tavily/Exa/Brave/Perplexity) "
        "with automatic fallback to the native hermes web backend."
    ),
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string",
                                 "description": "The search query to look up"}},
        "required": ["query"],
    },
}


def _check_fn() -> bool:
    "Always True — webba's DDG backend requires no API keys."
    return True


def register(ctx) -> None:
    """Called by Hermes PluginManager after _discover_tools().

    Overwrites registry._tools["web_search"] via dict-key assignment — this is the
    intended overwrite mechanism (ToolRegistry.register silently replaces existing
    entries by tool name). Without this plugin, web_search would require a paid
    API key (Firecrawl/Exa/etc.) to be available. With it, DDG serves as the
    zero-config default.

    Also patches registry._toolset_checks["web"] directly because the registry
    guard `if toolset not in self._toolset_checks` prevents ctx.register_tool()
    from updating it (tools/web_tools.py set it first to check_web_api_key).
    Without this patch, `hermes tools` still reports web as unavailable even
    though our DDG-backed handler needs no API key.
    """
    if _webba_search is None:
        logger.info("webba-search: skipping override (webba not installed)")
        return
    ctx.register_tool(
        name="web_search", toolset="web",
        schema=WEB_SEARCH_SCHEMA, handler=_make_handler(),
        check_fn=_check_fn, requires_env=[],
        is_async=False, emoji="🔍",
        description="webba-powered web search with provider routing and fallback",
    )
    try:
        from tools.registry import registry as _r
        _r._toolset_checks["web"] = _check_fn
    except Exception as e:
        logger.warning("Could not patch _toolset_checks: %s", e)
    logger.info("✅ webba-search active — web_search overridden with webba cascade")
