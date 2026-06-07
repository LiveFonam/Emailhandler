"""Thin shim over Evil research agents' src/llm.py.

We reuse Evil's battle-tested LLM router (Claude + Groq + Gemini + Ollama
with Pydantic schema validation, retry cascade, spend cap) by adding our
5 stage names to its _STAGE_ROLE dict and exposing convenience helpers
with sensible defaults for each.

This module deliberately adds NO new LLM-calling code. If Evil's router
gains a feature tomorrow, we get it for free.

Required one-time edit to Evil's src/llm.py (in _STAGE_ROLE) — already done
as of inbox-zero-agent creation; the stages below are now in Evil's dict:
    "triage": "reason",        # thread classification
    "summarize": "reason",     # 3-bullet summary + action items
    "draft_reply": "chat",     # reply draft in user's voice
    "personalize": "reason",   # single-variant hook
    "variant_gen": "reason",   # multi-framework outreach variant

Import strategy: we cannot use `from src import llm` because that resolves
to OUR src/ package (which has an __init__.py). We use importlib to load
Evil's llm.py by absolute file path, bypassing the package namespace.

If Evil's llm.py is missing or the stages are not registered, we raise
clear errors at import time.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Optional, Type

# Make sure app/paths.py is imported first so the sibling is on sys.path
# AND so DATA_DIR etc. exist.
from app import paths  # noqa: F401


def _load_evil_llm():
    """Load Evil's src/llm.py by file path, bypassing our src/ package shadow."""
    # paths.py already added Evil's src/ to sys.path. We need the FILE
    # path to llm.py, not a package import.
    evil_src = Path(r"C:/Users/lucas/Desktop/Evil research agents/src")
    if not evil_src.exists():
        # Try the config-driven path
        try:
            import yaml
            cfg_path = paths.project_root() / "config.yaml"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                root = cfg.get("paths", {}).get(
                    "evil_research_agents_root",
                    r"C:/Users/lucas/Desktop/Evil research agents",
                )
                evil_src = Path(root) / "src"
        except Exception:
            pass

    llm_path = evil_src / "llm.py"
    if not llm_path.exists():
        raise ImportError(
            f"Could not find Evil's llm.py at {llm_path}. "
            f"Set paths.evil_research_agents_root in config.yaml."
        )

    spec = importlib.util.spec_from_file_location(
        "evil_src_llm", str(llm_path)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {llm_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, llm_path


_evil_llm, _evil_llm_path = _load_evil_llm()


_REQUIRED_STAGES = {
    "triage": "reason",
    "summarize": "reason",
    "draft_reply": "chat",
    "variant_gen": "reason",
}


def _check_stages_registered() -> None:
    """Raise a clear error if Evil's _STAGE_ROLE is missing our stages."""
    stage_role = getattr(_evil_llm, "_STAGE_ROLE", None)
    if stage_role is None:
        return  # Evil's internals changed; can't verify, don't fail.
    missing = [s for s in _REQUIRED_STAGES if s not in stage_role]
    if missing:
        raise RuntimeError(
            "Evil's src/llm.py is missing the stages inbox-zero-agent needs. "
            f"Add these lines to _STAGE_ROLE in {_evil_llm_path}:\n"
            + "\n".join(
                f'    "{s}": "{role}",  # inbox-zero-agent'
                for s, role in _REQUIRED_STAGES.items()
                if s in missing
            )
        )


_check_stages_registered()


# ---- configuration: load config.yaml + .env at import time so Evil's
# ---- _PROVIDER / _LLM / _MODELS get set before any call.
def _bootstrap_evil_config() -> None:
    """Call Evil's configure() with the same config.yaml we use."""
    import yaml
    from dotenv import load_dotenv

    load_dotenv(paths.project_root() / ".env", override=False)

    cfg_path = paths.project_root() / "config.yaml"
    if not cfg_path.exists():
        return
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Evil's configure() expects keys: provider, llm, models, ollama.
    # We pass through the whole config; Evil ignores what it doesn't know.
    _evil_llm.configure(cfg)


_bootstrap_evil_config()


# ---- convenience helpers --------------------------------------------------


def call_triage(
    system: str,
    user: str,
    schema: Optional[Type[Any]] = None,
    max_tokens: int = 512,
) -> Any:
    """Cheap classification (Haiku-class). Subject + sender + 1st msg -> category."""
    return _evil_llm.call_model(
        "triage", system, user, schema=schema, max_tokens=max_tokens
    )


def call_summarize(
    system: str,
    user: str,
    schema: Optional[Type[Any]] = None,
    max_tokens: int = 600,
) -> Any:
    """3-bullet summary + 0-3 action items. Sonnet-class is fine here."""
    return _evil_llm.call_model(
        "summarize", system, user, schema=schema, max_tokens=max_tokens
    )


def call_draft(
    system: str,
    user: str,
    schema: Optional[Type[Any]] = None,
    max_tokens: int = 800,
) -> Any:
    """Reply draft in user's voice. Sonnet-class recommended."""
    return _evil_llm.call_model(
        "draft_reply", system, user, schema=schema, max_tokens=max_tokens
    )


def call_variant(
    system: str,
    user: str,
    schema: Optional[Type[Any]] = None,
    max_tokens: int = 500,
) -> Any:
    """Multi-framework outreach variant. Haiku-class for cost."""
    return _evil_llm.call_model(
        "variant_gen", system, user, schema=schema, max_tokens=max_tokens
    )


# ---- introspection helpers -----------------------------------------------


def last_backend() -> Optional[str]:
    """Return which provider served the most recent call (claude, groq, ...)."""
    return getattr(_evil_llm, "_LAST_BACKEND", None)


def claude_spend_usd() -> float:
    return float(getattr(_evil_llm, "_CLAUDE_SPEND_USD", 0.0))


def set_claude_enabled(enabled: bool) -> None:
    if hasattr(_evil_llm, "set_claude_enabled"):
        _evil_llm.set_claude_enabled(enabled)
