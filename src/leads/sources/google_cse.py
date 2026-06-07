"""Google Custom Search JSON API lead scraper.

Pulls search results for a query and shapes each hit into a Lead dict.
CSE caps at 10 results per page; we paginate via `start` to honour
`max_results` up to ~100 (Google's per-query limit on the free tier).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

from src.config import settings

log = logging.getLogger(__name__)

USER_AGENT = "inbox-zero-agent/1.0"
PER_PAGE = 10  # Google CSE hard cap
REQUEST_TIMEOUT = 10  # seconds
INTER_PAGE_SLEEP = 1.5  # seconds; polite to the free tier

# Common honorifics to strip when guessing a name from a page title.
_TITLES = {
    "dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.",
    "prof", "prof.", "professor", "sir", "madam",
}


def _http_get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_name(title: str) -> tuple[str, str]:
    """Heuristic: first non-title token = first name, rest = last name."""
    if not title:
        return "", ""
    tokens = [t.strip(".,;:-") for t in title.split() if t.strip(".,;:-")]
    tokens = [t for t in tokens if t]
    if not tokens:
        return "", ""
    if tokens[0].lower() in _TITLES and len(tokens) > 1:
        tokens = tokens[1:]
    if not tokens:
        return "", ""
    first = tokens[0].capitalize()
    last = " ".join(t.capitalize() for t in tokens[1:]) if len(tokens) > 1 else ""
    return first, last


def _domain_from_url(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _company_from_display(display_link: str) -> str:
    """Strip the TLD-ish tail from displayLink (e.g. 'acme.co.uk' -> 'acme')."""
    if not display_link:
        return ""
    host = display_link.lower()
    if host.startswith("www."):
        host = host[4:]
    # Take the leading label(s) up to the first dot. 'co.uk' / 'com.au'
    # style second-level domains get the leading label only, which is a
    # reasonable best-effort guess for a company slug.
    return host.split(".", 1)[0] if host else ""


def _item_to_lead(item: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title", "") or ""
    link = item.get("link", "") or ""
    display_link = item.get("displayLink", "") or ""
    first, last = _parse_name(title)
    domain = _domain_from_url(link)
    company = _company_from_display(display_link) or domain.split(".", 1)[0]
    email = f"{first.lower()}.{last.lower()}@{domain}" if first and last and domain else ""
    return {
        "email": email,
        "first_name": first,
        "last_name": last,
        "company": company,
        "company_domain": domain,
        "title": "",
        "city": "",
        "country": "",
        "timezone": "",
        "source": "google_cse",
        "source_url": link,
        "recent_news": "",
        "linkedin_snippet": "",
    }


def search(query: str, max_results: int = 20) -> list[dict]:
    """Run a CSE query and return a list of Lead-shaped dicts.

    Returns [] and logs a warning if the API key or CX id is missing.
    """
    key = settings.google_cse_key
    cx = settings.google_cse_id
    if not key or not cx:
        log.warning("google_cse: missing GOOGLE_CSE_KEY or GOOGLE_CSE_ID; returning []")
        return []
    if not query or not query.strip():
        return []

    results: list[dict] = []
    fetched = 0
    start = 1
    encoded_q = urllib.parse.quote_plus(query)

    while fetched < max_results:
        want = min(PER_PAGE, max_results - fetched)
        url = (
            f"https://www.googleapis.com/customsearch/v1"
            f"?key={urllib.parse.quote_plus(key)}"
            f"&cx={urllib.parse.quote_plus(cx)}"
            f"&q={encoded_q}"
            f"&num={want}"
            f"&start={start}"
        )
        try:
            data = _http_get_json(url)
        except Exception as e:
            log.warning("google_cse: request failed at start=%d: %s", start, e)
            return results

        items = data.get("items") or []
        if not items:
            break

        for it in items:
            results.append(_item_to_lead(it))
            fetched += 1
            if fetched >= max_results:
                break

        # If Google returned fewer than asked, no more pages.
        if len(items) < want:
            break

        start += PER_PAGE
        # CSE allows start up to 91 (i.e. 10 pages of 10). Stop before that.
        if start > 91:
            break
        time.sleep(INTER_PAGE_SLEEP)

    return results
