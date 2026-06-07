"""Tests for the leads module (dedupe, store, enrich).

No live API access: every test either uses pure-Python dedupe helpers
or hits the local sqlite DB and cleans up its own rows.

Run: cd inbox-zero-agent && python -m pytest tests/test_leads.py -v
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src import db as _db
from src.leads.dedupe import (
    normalize_name,
    normalize_company,
    dedupe_key,
    find_duplicates,
)
from src.leads.store import upsert_lead, bulk_upsert
from src.leads.enrich import hunter_verify
from src.outreach.suppress import add_suppression, is_suppressed


# --- pure-Python dedupe tests (no DB) ---


def test_normalize_name():
    assert normalize_name("Dr. Jane Smith") == "dr jane smith"
    assert normalize_name("O'Brien") == "obrien"
    assert normalize_name("  John   Doe  ") == "john doe"


def test_normalize_company():
    assert normalize_company("Acme Inc.") == "acme"
    assert normalize_company("Foo LLC") == "foo"
    assert normalize_company("Bar Ltd.") == "bar"
    assert normalize_company("Plain Co") == "plain"


def test_dedupe_key():
    # Same email -> same key regardless of name/company.
    a = {"email": "Foo@Bar.com", "first_name": "Jane", "last_name": "Doe",
         "company": "Acme Inc."}
    b = {"email": "foo@bar.com", "first_name": "Janet", "last_name": "Smith",
         "company": "Other Co"}
    assert dedupe_key(a) == dedupe_key(b)
    assert dedupe_key(a).startswith("email:")

    # Different email, different (name, company) -> different keys.
    c = {"email": "x@y.com", "first_name": "Bob", "last_name": "Jones",
         "company": "Beta"}
    assert dedupe_key(a) != dedupe_key(c)

    # Email takes precedence: even with matching name+company, different
    # emails produce different keys.
    d = {"email": "p@q.com", "first_name": "Jane", "last_name": "Doe",
         "company": "Acme Inc."}
    e = {"email": "r@s.com", "first_name": "Jane", "last_name": "Doe",
         "company": "Acme Inc."}
    assert dedupe_key(d) != dedupe_key(e)


def test_find_duplicates():
    leads = [
        # Group A: same person, slight spelling difference
        {"first_name": "Sarah", "last_name": "Kim", "company": "StemCell Bio",
         "email": ""},
        {"first_name": "Sara",  "last_name": "Kim", "company": "Stemcell Bio",
         "email": ""},
        # Group B: a unique lead
        {"first_name": "Marcus", "last_name": "Lee", "company": "Acme",
         "email": ""},
        # Group C: another unique lead
        {"first_name": "Priya", "last_name": "Patel", "company": "Helix",
         "email": ""},
    ]
    groups = find_duplicates(leads)
    sizes = sorted(len(g) for g in groups)
    # 1 group of size 2 (the duplicate pair) and 2 singletons = 3 groups.
    assert sizes == [1, 1, 2], f"expected [1, 1, 2] got {sizes}"

    # The size-2 group is the Sarah/Sara pair.
    pair = next(g for g in groups if len(g) == 2)
    pair_firsts = sorted([m["first_name"] for m in pair])
    assert pair_firsts == ["Sara", "Sarah"]


# --- DB-backed tests (each cleans up after itself) ---


def _unique_email() -> str:
    return f"test-leads-{uuid.uuid4().hex}@example.com"


def test_upsert_lead_insert():
    email = _unique_email()
    lead = {
        "email": email,
        "first_name": "Test",
        "last_name": "Lead",
        "company": "TestCo",
        "title": "CTO",
        "city": "Toronto",
        "country": "CA",
        "source": "test",
    }
    try:
        lead_id = upsert_lead(lead)
        assert isinstance(lead_id, int) and lead_id > 0

        row = _db.query_one("SELECT * FROM leads WHERE id = ?", (lead_id,))
        assert row is not None
        assert row["email"] == email
        assert row["first_name"] == "Test"
        assert row["company"] == "TestCo"
        assert row["status"] == "new"
    finally:
        _db.exec("DELETE FROM leads WHERE email = ?", (email,))


def test_upsert_lead_skips_suppressed():
    email = _unique_email()
    # Suppress first, then try to upsert.
    add_suppression(email, "test-suppress")
    try:
        assert is_suppressed(email) is True
        result = upsert_lead({
            "email": email,
            "first_name": "Should",
            "last_name": "NotInsert",
            "company": "RefusedCo",
        })
        assert result is None, f"expected None for suppressed email, got {result}"
        row = _db.query_one("SELECT id FROM leads WHERE email = ?", (email,))
        assert row is None, "no row should have been written for a suppressed email"
    finally:
        # Cleanup both the suppression row and (defensively) any lead row.
        _db.exec("DELETE FROM suppression WHERE email = ?", (email,))
        _db.exec("DELETE FROM leads WHERE email = ?", (email,))


def test_bulk_upsert_counts():
    tag = uuid.uuid4().hex[:8]
    leads = [
        {"email": f"test-bulk-{tag}-{i}@example.com",
         "first_name": f"First{i}",
         "last_name": f"Last{i}",
         "company": f"BulkCo{i}",
         "source": "test"}
        for i in range(3)
    ]
    try:
        counts = bulk_upsert(leads)
        assert counts == {"inserted": 3, "updated": 0, "skipped": 0}, \
            f"unexpected counts: {counts}"
    finally:
        for lead in leads:
            _db.exec("DELETE FROM leads WHERE email = ?", (lead["email"],))


def test_hunter_verify_no_key():
    # The test environment should have no HUNTER_API_KEY set. If it does,
    # skip the test rather than fail spuriously.
    import os
    if os.getenv("HUNTER_API_KEY"):
        pytest.skip("HUNTER_API_KEY is set; cannot verify the no-key path")
    result = hunter_verify("foo@bar.com")
    assert result == {"status": "unknown", "score": 0}
