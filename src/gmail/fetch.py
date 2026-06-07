"""Fetch threads and individual messages from Gmail.

We use `format=FULL` only when we need the body (for summarize / draft).
For classification we use `format=metadata` to save quota units
(40 per call vs 40 with full body, but with much smaller payload).
"""
from __future__ import annotations

import base64
from typing import Any, Iterator, Optional

from src.gmail.client import build_service, with_backoff


def list_thread_ids(
    query: str = "is:unread",
    max_results: int = 50,
    account: str = "default",
) -> list[str]:
    """Return a list of thread ids matching the query, paginated."""
    service = build_service(account)
    out: list[str] = []
    page_token: Optional[str] = None
    while True:
        kwargs: dict[str, Any] = dict(
            userId="me",
            q=query,
            maxResults=min(max_results - len(out), 100),
        )
        if page_token:
            kwargs["pageToken"] = page_token

        @with_backoff
        def _call():
            return service.users().threads().list(**kwargs).execute()

        resp = _call()
        threads = resp.get("threads", []) or []
        out.extend(t["id"] for t in threads)
        page_token = resp.get("nextPageToken")
        if not page_token or len(out) >= max_results:
            break
    return out[:max_results]


def get_thread(
    thread_id: str,
    fmt: str = "full",
    account: str = "default",
) -> dict[str, Any]:
    """Fetch a single thread. fmt = 'full' | 'metadata' | 'minimal'."""
    service = build_service(account)

    @with_backoff
    def _call():
        return (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format=fmt)
            .execute()
        )

    return _call()


def get_threads_batch(
    thread_ids: list[str],
    fmt: str = "full",
    account: str = "default",
) -> Iterator[dict[str, Any]]:
    """Yield each fetched thread."""
    for tid in thread_ids:
        try:
            yield get_thread(tid, fmt=fmt, account=account)
        except Exception as e:
            # Skip individual failures but keep going
            import logging
            logging.getLogger("inbox_zero.gmail.fetch").warning(
                f"Failed to fetch thread {tid}: {e}"
            )


def parse_message_body(payload: dict[str, Any]) -> str:
    """Extract the best plain-text body from a Gmail message payload tree.

    Walks the multipart tree, preferring text/plain parts, falling back
    to text/html stripped of tags. Base64url-decodes the data.
    """
    def _decode(data: str) -> str:
        try:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
        except Exception:
            return ""

    def _walk(part: dict[str, Any]) -> tuple[str | None, str | None]:
        """Return (text_plain, text_html) for the best sub-part."""
        mime = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        data = body.get("data")
        if mime == "text/plain" and data:
            return _decode(data), None
        if mime == "text/html" and data:
            return None, _decode(data)
        if mime.startswith("multipart/"):
            tp, th = None, None
            for sub in part.get("parts", []) or []:
                s_tp, s_th = _walk(sub)
                tp = tp or s_tp
                th = th or s_th
                if tp and th:
                    break
            return tp, th
        return None, None

    tp, th = _walk(payload)
    if tp:
        return tp
    if th:
        # Strip HTML crud as a last resort
        import re
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", th)).strip()
    return ""


def thread_to_digest(thread: dict[str, Any]) -> dict[str, Any]:
    """Turn a thread dict into a compact digest for the LLM.

    Returns: {subject, from, to, date, message_count, body_excerpt, messages: [...]}
    Each message has: from, date, snippet, body.
    """
    messages = thread.get("messages", []) or []
    parsed = []
    for m in messages:
        payload = m.get("payload", {}) or {}
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        body = parse_message_body(payload)
        if len(body) > 1200:
            body = body[:1200] + "..."
        parsed.append(
            {
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "date": headers.get("date", ""),
                "subject": headers.get("subject", ""),
                "snippet": m.get("snippet", ""),
                "body": body,
            }
        )
    first_hdr = (messages[0].get("payload", {}) or {}).get("headers", []) if messages else []
    last_hdr = (messages[-1].get("payload", {}) or {}).get("headers", []) if messages else []
    first_from = ""
    last_from = ""
    for h in first_hdr:
        if h["name"].lower() == "from":
            first_from = h["value"]
            break
    for h in last_hdr:
        if h["name"].lower() == "from":
            last_from = h["value"]
            break
    subject = ""
    for h in first_hdr:
        if h["name"].lower() == "subject":
            subject = h["value"]
            break
    return {
        "id": thread.get("id", ""),
        "subject": subject,
        "first_from": first_from,
        "last_from": last_from,
        "message_count": len(messages),
        "messages": parsed,
    }
