"""Gmail history.poll: incremental change detection.

v1 uses users.history.list polling every 5 minutes instead of a real
Pub/Sub push. Polling is fine for ≤1000 messages/day.

The historyId is a per-account monotonically increasing counter. We
persist the last one we've seen and only ask for changes since.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.gmail.client import build_service, with_backoff
from app import paths


HISTORY_STATE_PATH = paths.DATA_DIR / "history_state.json"

log = logging.getLogger("inbox_zero.gmail.watch")


def _load_state() -> dict[str, int]:
    if not HISTORY_STATE_PATH.exists():
        return {}
    try:
        return json.loads(HISTORY_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, int]) -> None:
    HISTORY_STATE_PATH.write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


def _latest_history_id(account: str, service) -> int:
    """Get the current profile historyId; we use this as our anchor on
    the very first run."""
    @with_backoff
    def _profile():
        return service.users().getProfile(userId="me").execute()
    return int(_profile().get("historyId", 0))


def poll_changes(account: str = "default", max_results: int = 100) -> list[str]:
    """Return thread ids that have changed since the last poll."""
    service = build_service(account)
    state = _load_state()
    last = int(state.get(account, 0))
    if not last:
        last = _latest_history_id(account, service)
        state[account] = last
        _save_state(state)
        log.info(f"history.poll: initial anchor historyId={last} for {account}")
        return []

    added: list[str] = []
    page_token: str | None = None
    while True:
        @with_backoff
        def _call(token=page_token):
            kwargs: dict[str, Any] = dict(
                userId="me",
                startHistoryId=last,
                historyTypes=["messageAdded"],
                maxResults=min(max_results, 100),
            )
            if token:
                kwargs["pageToken"] = token
            return service.users().history().list(**kwargs).execute()
        resp = _call()
        for h in (resp.get("history") or []):
            for m in h.get("messagesAdded", []) or []:
                tid = (m.get("message") or {}).get("threadId")
                if tid:
                    added.append(tid)
        new_history = int(resp.get("historyId", last))
        last = new_history
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    state[account] = last
    _save_state(state)
    return list(dict.fromkeys(added))  # de-dup, preserve order
