"""Build a Gmail API Resource + central 429/503 backoff.

The Gmail API cost (per Google's 2026 docs):
  users.threads.list    = 5 quota units
  users.threads.get     = 40 quota units
  users.messages.send   = 100 quota units
  users.drafts.create   = 10 quota units
Per-user limit: 6,000 units / minute (~1 send/sec). Our 60-90s throttle
puts us 200x under that.

`with_backoff()` retries 429 / 503 / 504 with truncated exponential
backoff per Google's error-handling guide.
"""
from __future__ import annotations

import logging
import random
import time
from functools import wraps
from typing import Any, Callable

from googleapiclient.discovery import build, Resource
from google.auth.credentials import Credentials

from src.gmail import oauth

log = logging.getLogger("inbox_zero.gmail.client")


def build_service(account: str = "default") -> Resource:
    """Return an authenticated Gmail v1 Resource for the given account."""
    creds: Credentials = oauth.get_credentials(account)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return service


_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 6


def with_backoff(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Truncated exponential backoff: 1+rand, 2+rand, 4+rand, 8+rand, 16+rand, 32+rand s."""

    @wraps(fn)
    def wrapped(*args, **kwargs) -> Any:
        delay = 1.0
        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except Exception as e:  # HttpError, transport errors, etc.
                code = getattr(e, "resp", None)
                code = getattr(code, "status", None) if code is not None else None
                if code not in _RETRYABLE_CODES:
                    raise
                last_err = e
                sleep_s = delay + random.random()
                log.warning(
                    f"Gmail API retryable error (code={code}, attempt {attempt + 1}/{_MAX_RETRIES}): {e}. "
                    f"Sleeping {sleep_s:.2f}s"
                )
                time.sleep(sleep_s)
                delay = min(delay * 2, 32.0)
        # Exhausted retries
        raise RuntimeError(
            f"Gmail API call failed after {_MAX_RETRIES} retries: {last_err}"
        )

    return wrapped
