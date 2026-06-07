"""Cross-source merge + Hunter/Apollo verify stubs.

We use Hunter's /v2/email-verifier to score the deliverability of an email.
Apollo is left as a stub. The lead_id-level re-fetch is best-effort: it pulls
the existing raw_payload, runs the merge over its individual fields, and
persists recent_news / linkedin_snippet / enriched_at.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request

from src import db
from src.config import settings
from src.leads.dedupe import find_duplicates


def _non_empty(a: str, b: str) -> str:
    a = (a or "").strip()
    return a if a else (b or "").strip()


def _longer(a: str, b: str) -> str:
    a, b = (a or "").strip(), (b or "").strip()
    return a if len(a) >= len(b) else b


def _earlier(a: str, b: str) -> str:
    a, b = (a or "").strip(), (b or "").strip()
    return a or b or "" if (a and not b) or (b and not a) else (a if a <= b else b)


_NON_EMPTY_FIELDS = (
    "email", "title", "company", "company_domain",
    "first_name", "last_name", "city", "country",
    "timezone", "source", "source_url", "linkedin_snippet", "raw_payload",
)
_LONGEST_FIELDS = ("recent_news",)
_EARLIEST_FIELDS = ("created_at",)


def merge_sources(leads: list[dict]) -> list[dict]:
    """Merge multiple source dicts for the same logical person into one.

    For each near-duplicate group (via find_duplicates), prefer:
      - non-empty email/title/name/company over empty
      - longest non-empty recent_news
      - earliest created_at

    Returns one merged dict per group; singletons pass through unchanged.
    """
    out: list[dict] = []
    seen: set[int] = set()

    for group in find_duplicates(leads):
        merged: dict = {}
        for src in group:
            for k, v in src.items():
                cur = merged.get(k)
                if cur in (None, "", []) or k not in merged:
                    merged[k] = v
                elif k in _NON_EMPTY_FIELDS:
                    merged[k] = _non_empty(str(cur), str(v))
                elif k in _LONGEST_FIELDS:
                    merged[k] = _longer(str(cur), str(v))
                elif k in _EARLIEST_FIELDS:
                    merged[k] = _earlier(str(cur), str(v))
        out.append(merged)
        seen.update(id(s) for s in group)

    for lead in leads:
        if id(lead) not in seen:
            out.append(dict(lead))
    return out


def hunter_verify(email: str) -> dict:
    """If settings.hunter_api_key is set, call Hunter.io /v2/email-verifier.

    Returns {'status': 'valid'|'invalid'|'accept_all'|'unknown', 'score': 0-100}.
    If no key configured, returns {'status': 'unknown', 'score': 0}.
    """
    if not email or not settings.hunter_api_key:
        return {"status": "unknown", "score": 0}
    url = "https://api.hunter.io/v2/email-verifier?" + urllib.parse.urlencode(
        {"email": email, "api_key": settings.hunter_api_key}
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data") or {}
        status = str(data.get("status") or "unknown").lower()
        if status not in {"valid", "invalid", "accept_all", "unknown"}:
            status = "unknown"
        return {"status": status, "score": max(0, min(100, int(data.get("score") or 0)))}
    except Exception:
        return {"status": "unknown", "score": 0}


def apollo_verify(email: str) -> dict:  # pragma: no cover - stub
    """Stub for Apollo enrichment. Always returns 'unknown' for v1; left here
    so callers can wire it up later without churn.
    """
    _ = settings.apollo_api_key
    _ = email
    return {"status": "unknown", "score": 0}


def enrich_lead(lead_id: int) -> bool:
    """Re-fetch and merge data for an existing lead from its raw_payload.
    Updates recent_news, linkedin_snippet, enriched_at. Returns True on
    change, False if there was nothing to do.
    """
    row = db.query_one("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if not row or not row["raw_payload"]:
        return False
    try:
        payload = json.loads(row["raw_payload"])
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    current = {k: row[k] for k in row.keys() if k not in ("id", "status", "enriched_at")}
    # raw_payload is usually a partial dict (just enrichment fields).
    # Backfill identifying fields from the row so find_duplicates can pair.
    enriched_payload = {
        **current, **payload, "email": current.get("email", ""),
        "first_name": current.get("first_name", ""),
        "last_name": current.get("last_name", ""),
        "company": current.get("company", ""),
    }
    merged = merge_sources([current, enriched_payload])
    if not merged:
        return False
    new_news = (merged[0].get("recent_news") or "").strip()
    new_link = (merged[0].get("linkedin_snippet") or "").strip()
    if (
        new_news == (row["recent_news"] or "").strip()
        and new_link == (row["linkedin_snippet"] or "").strip()
    ):
        return False
    db.exec(
        """UPDATE leads SET recent_news = ?, linkedin_snippet = ?,
              raw_payload = ?, enriched_at = ? WHERE id = ?""",
        (
            new_news, new_link, db.to_json(payload),
            dt.datetime.now(dt.timezone.utc).isoformat(), lead_id,
        ),
    )
    return True
