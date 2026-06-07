"""Tests for the multi-variant pipeline that don't require live LLM access.

Run: cd inbox-zero-agent && python -m pytest tests/ -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.outreach.template import FRAMEWORKS, build_variant_prompt
from src.schemas import Variant
from src import db as _db


def test_all_frameworks_have_guidance():
    """All 5 frameworks must have non-empty guidance and example."""
    assert len(FRAMEWORKS) >= 5, f"Expected at least 5 frameworks, got {len(FRAMEWORKS)}"
    for name, fw in FRAMEWORKS.items():
        assert fw["guidance"], f"Framework {name} missing guidance"
        assert fw["example"], f"Framework {name} missing example"
        assert len(fw["example"]) > 50, f"Framework {name} example too short"


def test_variant_prompt_includes_lead_data():
    prompt = build_variant_prompt(
        "value_prop",
        {
            "first_name": "Sarah",
            "last_name": "Kim",
            "title": "VP Engineering",
            "company": "StemCell Bio",
            "company_domain": "stemcellbio.com",
            "city": "Toronto",
            "country": "CA",
            "recent_news": "Just raised Series A",
            "linkedin_snippet": "",
        },
    )
    assert "Sarah Kim" in prompt
    assert "VP Engineering" in prompt
    assert "StemCell Bio" in prompt
    assert "Series A" in prompt
    assert "value_prop" in prompt


def test_variant_prompt_omits_optional_when_missing():
    prompt = build_variant_prompt(
        "question_hook",
        {
            "first_name": "Marcus",
            "last_name": "Lee",
            "title": "Director",
            "company": "Acme",
            "company_domain": "acme.com",
            "city": "",
            "country": "",
            "recent_news": "",
            "linkedin_snippet": "",
        },
    )
    assert "Marcus Lee" in prompt
    assert "Recent news" not in prompt
    assert "LinkedIn bio" not in prompt


def test_variant_schema_validates():
    v = Variant(
        framework="question_hook",
        subject="biotech ops question",
        body="Hi Sarah,\n\nQuick question about your new lab workflow.\n\n— Lucas",
        personalization_tokens=["recent_news", "company"],
    )
    assert v.framework == "question_hook"
    assert "Sarah" in v.body


def test_persist_variant_roundtrip():
    """Insert a variant and read it back. Bypasses the LLM call by
    inserting directly (the LLM needs an API key we don't have in tests)."""
    import uuid
    now = datetime.now(timezone.utc).isoformat()
    test_email = f"test-variant-{uuid.uuid4().hex[:8]}@example.com"
    test_campaign_name = f"Test campaign {uuid.uuid4().hex[:8]}"

    # Pre-clean any leftover rows from prior failed runs (defensive)
    _db.exec("DELETE FROM leads WHERE email LIKE 'test-variant-%@example.com'", ())
    _db.exec("DELETE FROM campaigns WHERE name LIKE 'Test campaign %'", ())

    # Insert lead
    _db.exec(
        """INSERT INTO leads (email, first_name, last_name, company, title, city, country, source, created_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')""",
        (test_email, "Test", "Lead", "TestCo", "CTO", "Toronto", "CA", "test", now),
    )
    lead_id = _db.query_one(
        "SELECT id FROM leads WHERE email = ?", (test_email,)
    )["id"]

    # Insert campaign
    _db.exec(
        """INSERT INTO campaigns (name, status, daily_cap, frameworks, use_variants, created_at)
           VALUES (?, 'draft', 10, '["value_prop"]', 1, ?)""",
        (test_campaign_name, now),
    )
    campaign_id = _db.query_one(
        "SELECT id FROM campaigns WHERE name = ?", (test_campaign_name,)
    )["id"]

    # Insert variant directly
    v = Variant(
        framework="value_prop",
        subject="3x faster pipeline",
        body="Hi Test, this is a test body with company mention.",
        personalization_tokens=["company"],
    )
    _db.exec(
        """INSERT INTO campaign_variants
            (campaign_id, lead_id, framework, subject, body, personalization_tokens, created_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'generated')""",
        (campaign_id, lead_id, v.framework, v.subject, v.body, _db.to_json(v.personalization_tokens), now),
    )
    row = _db.query_one(
        """SELECT * FROM campaign_variants WHERE campaign_id = ? AND lead_id = ?""",
        (campaign_id, lead_id),
    )
    assert row is not None
    assert row["framework"] == "value_prop"
    assert row["body"] == v.body
    assert "company" in row["body"]

    # Cleanup
    _db.exec("DELETE FROM campaign_variants WHERE campaign_id = ?", (campaign_id,))
    _db.exec("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    _db.exec("DELETE FROM leads WHERE id = ?", (lead_id,))
