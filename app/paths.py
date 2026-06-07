"""Project root + sibling-resolver for Evil research agents.

This module is imported by every other module first. It:
  - Resolves the project root (parent of app/)
  - Adds the sibling `Evil research agents/src` to sys.path so we can
    `from src import llm` and reuse its router
  - Exposes the standard path constants used everywhere

If the sibling is missing or the path is wrong, we raise a clear error
at import time rather than a traceback later.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Project root: parent of the directory containing this file (app/).
_ROOT = Path(__file__).resolve().parent.parent

# Add Evil research agents' src/ to sys.path so we can reuse src.llm etc.
# Path is read from env first, then config.yaml, then a sensible default.
try:
    import yaml
    _cfg_path = _ROOT / "config.yaml"
    if _cfg_path.exists():
        with open(_cfg_path, "r", encoding="utf-8") as _f:
            _cfg = yaml.safe_load(_f) or {}
        _evil_root = _cfg.get("paths", {}).get(
            "evil_research_agents_root",
            r"C:\Users\lucas\Desktop\Evil research agents",
        )
    else:
        _evil_root = r"C:\Users\lucas\Desktop\Evil research agents"
except Exception:
    _evil_root = r"C:\Users\lucas\Desktop\Evil research agents"

_EVIL_SRC = Path(_evil_root) / "src"

if not _EVIL_SRC.exists():
    # Don't crash the UI; just log a warning. Many pages work without Evil.
    # Only llm_compat and anything calling the LLM needs the sibling.
    import warnings
    warnings.warn(
        f"Evil research agents src/ not found at {_EVIL_SRC}. "
        f"LLM-backed features will fail until paths.evil_research_agents_root "
        f"in config.yaml points to the right place.",
        stacklevel=2,
    )
else:
    if str(_EVIL_SRC) not in sys.path:
        sys.path.insert(0, str(_EVIL_SRC))


# Standard paths used across the project.
DATA_DIR = _ROOT / "data"
OUTPUT_DIR = _ROOT / "output"
TESTS_DIR = _ROOT / "tests"
TOOLS_DIR = _ROOT / "tools"
APP_DIR = _ROOT / "app"
SRC_DIR = _ROOT / "src"

DB_PATH = DATA_DIR / "inbox_zero.db"
TOKEN_PATH = DATA_DIR / "token.json"
CREDENTIALS_PATH = DATA_DIR / "credentials.json"
SENT_MIME_DIR = DATA_DIR / "sent_mime"
TEMPLATES_DIR = DATA_DIR / "templates"
RUN_LOG_PATH = DATA_DIR / "run.log"
SEND_LOG_PATH = DATA_DIR / "send_log.jsonl"
EXPORTS_DIR = DATA_DIR / "exports"

DRAFTS_OUTPUT_DIR = OUTPUT_DIR / "drafts"
CAMPAIGNS_OUTPUT_DIR = OUTPUT_DIR / "campaigns"


def ensure_dirs() -> None:
    """Create the standard directories if they don't exist."""
    for p in [
        DATA_DIR, OUTPUT_DIR, SENT_MIME_DIR, TEMPLATES_DIR,
        DRAFTS_OUTPUT_DIR, CAMPAIGNS_OUTPUT_DIR, EXPORTS_DIR,
    ]:
        p.mkdir(parents=True, exist_ok=True)


def project_root() -> Path:
    return _ROOT


# Run directory creation on import so subsequent modules can assume it exists.
ensure_dirs()
