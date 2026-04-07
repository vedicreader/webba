"""webba plugins — auto-install helpers for agent harnesses."""
from __future__ import annotations
import os, shutil, textwrap
from pathlib import Path
from fastcore.all import ifnone

__all__ = ['install_hermes_plugin', 'uninstall_hermes_plugin']


def _find_hermes_home(hermes_home: str | None = None) -> Path:
    "Resolve Hermes config/data dir. Order: param → HERMES_HOME env → ~/.hermes"
    raw = ifnone(hermes_home, os.environ.get('HERMES_HOME')) or str(Path.home() / '.hermes')
    return Path(raw).expanduser().resolve()


def install_hermes_plugin(hermes_home: str | None = None) -> dict:
    """Auto-install webba as a Hermes Agent web-search plugin.

    Copies webba/plugins/hermes_search.py
        → {hermes_home}/plugins/webba/__init__.py
    and writes plugin.yaml alongside it.

    Returns dict(installed:bool, path:str, message:str)
    """
    from webba import __version__ as webba_version
    target = _find_hermes_home(hermes_home) / 'plugins' / 'webba'
    src = Path(__file__).parent / 'hermes_search.py'
    if not src.exists():
        return dict(installed=False, path='', message=f"Bundled plugin not found: {src}")
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target / '__init__.py')
        (target / 'plugin.yaml').write_text(textwrap.dedent(f"""\
            name: webba-search
            version: {webba_version}
            description: >
              webba-powered web_search for Hermes. Zero-config (DDG/SearXNG/Google);
              upgrades when Serper/Tavily/Exa/Brave/Perplexity keys are set.
              Gracefully falls back to native hermes web_search_tool on any failure.
            author: vedicreader
            pip_dependencies:
              - webba
            """), encoding='utf-8')
        return dict(installed=True, path=str(target / '__init__.py'),
                    message=f"webba-search plugin installed to {target / '__init__.py'}")
    except Exception as e:
        return dict(installed=False, path=str(target), message=f"Installation failed: {e}")


def uninstall_hermes_plugin(hermes_home: str | None = None) -> dict:
    """Remove the webba Hermes plugin directory. Returns dict(uninstalled, path, message)."""
    target = _find_hermes_home(hermes_home) / 'plugins' / 'webba'
    if not target.exists():
        return dict(uninstalled=False, path=str(target), message="Plugin directory not found")
    try:
        shutil.rmtree(target)
        return dict(uninstalled=True, path=str(target), message=f"Removed {target}")
    except Exception as e:
        return dict(uninstalled=False, path=str(target), message=f"Uninstall failed: {e}")
