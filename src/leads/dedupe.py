"""Lead normalization + deduplication.

A "dedupe_key" is a stable string used to group near-duplicate leads. We use
email when present, otherwise (name, company). For fuzzy matching, we compare
dedupe_keys with rapidfuzz (already in requirements.txt) so a record with a
typo'd name still groups with the clean one.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz  # type: ignore
    _HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    _HAS_RAPIDFUZZ = False


_APOSTROPHE_RE = re.compile(r"[’'‘‛]")
# All non-word, non-space chars become spaces. We strip apostrophes FIRST so
# "O'Brien" -> "OBrien" -> "obrien" (one token), not "o brien" (two tokens).
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c\.|ltd|limited|corp|corporation|co|company|gmbh|s\.a\.|s\.r\.l\.|plc)\b\.?",
    re.IGNORECASE,
)


def _clean(s: str) -> str:
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation (including apostrophes), collapse whitespace."""
    if not name:
        return ""
    s = _APOSTROPHE_RE.sub("", str(name).lower())
    return _clean(s)


def normalize_company(company: str) -> str:
    """Lowercase, strip common suffixes (Inc, LLC, Ltd, Corp, Co), strip punctuation."""
    if not company:
        return ""
    s = _APOSTROPHE_RE.sub("", str(company).lower())
    s = _COMPANY_SUFFIX_RE.sub(" ", s)
    return _clean(s)


def _email_of(lead: dict) -> str:
    return str(lead.get("email") or "").strip().lower()


def dedupe_key(lead: dict) -> str:
    """Return a stable dedupe key. Two leads with the same key are duplicates.

    Strategy: if email is present (and non-empty), use lower(email). Otherwise
    use (normalized_name, normalized_company) joined by '|'.
    """
    email = _email_of(lead)
    if email:
        return f"email:{email}"
    name = normalize_name(
        f"{lead.get('first_name', '')} {lead.get('last_name', '')}"
    )
    company = normalize_company(lead.get("company", ""))
    return f"nameco:{name}|{company}"


def _ratio(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if _HAS_RAPIDFUZZ:
        return fuzz.ratio(a, b) / 100.0
    return SequenceMatcher(None, a, b).ratio()


def find_duplicates(
    leads: list[dict], threshold: float = 0.85
) -> list[list[dict]]:
    """Group near-duplicate leads.

    A group is a set of leads that all collapse to the same person. The
    grouping rules are:
      - Two leads with the same email (case-insensitive) -> same group.
      - Two leads with no email but matching (name, company) within
        `threshold` similarity -> same group.

    Returns one group per distinct person, including singletons (a
    lead that didn't match anything becomes a size-1 group). Group
    order follows the first member's input order.
    """
    n = len(leads)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            a, b = leads[i], leads[j]
            a_email = _email_of(a)
            b_email = _email_of(b)
            if a_email and b_email:
                if a_email == b_email:
                    union(i, j)
                continue
            # At least one lead has no email: fall back to name+company.
            a_nm = normalize_name(
                f"{a.get('first_name', '')} {a.get('last_name', '')}".strip()
            )
            b_nm = normalize_name(
                f"{b.get('first_name', '')} {b.get('last_name', '')}".strip()
            )
            a_co = normalize_company(a.get("company", ""))
            b_co = normalize_company(b.get("company", ""))
            if not a_nm or not b_nm:
                continue
            name_score = _ratio(a_nm, b_nm)
            co_score = _ratio(a_co, b_co) if (a_co and b_co) else 0.0
            score = 0.9 * name_score + 0.1 * co_score
            if score >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    return [
        [leads[i] for i in indices]
        for indices in groups.values()
    ]
