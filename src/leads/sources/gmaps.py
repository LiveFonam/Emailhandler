"""Google Maps Places API (legacy Text Search) lead scraper.

Returns business-only leads (no person, no email). The lead store treats
person-less leads as 'needs enrichment' downstream.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "inbox-zero-agent/1.0"
REQUEST_TIMEOUT = 10  # seconds
INTER_PAGE_SLEEP = 2.0  # seconds; pagetoken needs ~2s to activate
PER_PAGE = 20  # legacy Text Search returns up to 20 per page

log = logging.getLogger(__name__)


def _maps_api_key() -> str:
    # No settings.google_maps_api_key on the project yet; read env directly
    # so this module is import-safe and config-edit-free.
    return os.getenv("GOOGLE_MAPS_API_KEY", "")


def _http_get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _domain_from_website(website: str) -> str:
    if not website:
        return ""
    try:
        host = urllib.parse.urlparse(website).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _parse_address(formatted_address: str) -> tuple[str, str]:
    """Split a Maps formatted_address into (city, country).

    Heuristic: city = first segment (before the first comma);
    country = last segment (after the last comma). Both can be empty
    if Maps gives us something unusual.
    """
    if not formatted_address:
        return "", ""
    parts = [p.strip() for p in formatted_address.split(",") if p.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], parts[-1]


def _result_to_lead(r: dict[str, Any]) -> dict[str, Any]:
    name = r.get("name", "") or ""
    website = r.get("website", "") or ""
    formatted = r.get("formatted_address", "") or ""
    place_id = r.get("place_id", "") or ""
    city, country = _parse_address(formatted)
    domain = _domain_from_website(website)
    if website:
        source_url = website
    else:
        source_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
    return {
        "email": "",
        "first_name": "",
        "last_name": "",
        "company": name,
        "company_domain": domain,
        "title": "",
        "city": city,
        "country": country,
        "timezone": "",
        "source": "gmaps",
        "source_url": source_url,
        "recent_news": "",
        "linkedin_snippet": "",
    }


def _check_status(data: dict[str, Any]) -> tuple[bool, str]:
    """Map Google's status string to (ok, error_msg)."""
    status = (data.get("status") or "").upper()
    if status in ("OK", "ZERO_RESULTS"):
        return True, ""
    if status == "OVER_QUERY_LIMIT":
        return False, "over query limit"
    if status == "REQUEST_DENIED":
        return False, f"request denied: {data.get('error_message', '')}"
    if status == "INVALID_REQUEST":
        return False, f"invalid request: {data.get('error_message', '')}"
    if status in ("UNKNOWN_ERROR",):
        return False, "unknown error (often transient)"
    return False, f"status={status or 'EMPTY'}"


def search(query: str, max_results: int = 20) -> list[dict]:
    """Run a Maps Text Search and return a list of Lead-shaped dicts.

    Returns [] and logs a warning if the API key is missing.
    """
    key = _maps_api_key()
    if not key:
        log.warning("gmaps: missing GOOGLE_MAPS_API_KEY; returning []")
        return []
    if not query or not query.strip():
        return []

    results: list[dict] = []
    encoded_q = urllib.parse.quote_plus(query)
    next_token: str | None = None
    base = "https://maps.googleapis.com/maps/api/place/textsearch/json"

    while True:
        if next_token:
            # pagetoken must be used after ~2s; sleep before issuing.
            time.sleep(INTER_PAGE_SLEEP)
            url = f"{base}?pagetoken={urllib.parse.quote_plus(next_token)}&key={urllib.parse.quote_plus(key)}"
        else:
            url = f"{base}?query={encoded_q}&key={urllib.parse.quote_plus(key)}"

        try:
            data = _http_get_json(url)
        except Exception as e:
            log.warning("gmaps: request failed: %s", e)
            return results

        ok, err = _check_status(data)
        if not ok:
            log.warning("gmaps: %s; returning %d results so far", err, len(results))
            return results

        for r in data.get("results") or []:
            results.append(_result_to_lead(r))
            if len(results) >= max_results:
                return results

        next_token = data.get("next_page_token")
        if not next_token:
            return results
