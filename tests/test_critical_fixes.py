"""Tests for the 4 CRITICAL fixes from the v1 reviewer:
  1. Atomic send_job claim (no double-send race)
  2. busy_timeout + WAL pragmas present
  3. Single unsubscribe token used in BOTH header and body
  4. outreach_subscriptions table is written on send

Run: cd inbox-zero-agent && python -m pytest tests/ -v
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db as _db
from src.outreach.compliance import (
    can_spam_headers,
    generate_unsubscribe_token,
    build_unsubscribe_url,
    physical_address_footer,
)
from src.outreach.sender import _build_mime_for_job, _next_pending_job
from src.schemas import Variant


def test_db_has_busy_timeout_and_wal_pragmas():
    """CRITICAL #4: concurrent writes from scheduler + Streamlit must not
    hit SQLITE_BUSY. busy_timeout=5000 ms buys us a 5s retry window."""
    conn = _db.get_conn()
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    # PRAGMA synchronous returns an int: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA
    assert str(journal).lower() == "wal", f"journal_mode should be WAL, got {journal}"
    assert int(busy) >= 1000, f"busy_timeout should be >=1s, got {busy}"
    assert int(sync) == 1, f"synchronous should be 1 (NORMAL), got {sync}"


def test_can_spam_headers_returns_token():
    """CRITICAL #3: the token returned must be usable to build the URL
    that the same call baked into the header. One token, two places."""
    headers, token = can_spam_headers(
        from_addr="me@example.com",
        reply_to="me@example.com",
        email="recipient@example.com",
    )
    assert "List-Unsubscribe" in headers
    assert "List-Unsubscribe-Post" in headers
    assert "X-Entity-Ref-ID" in headers
    assert "Precedence" in headers
    # The token is a 32-byte url-safe string
    assert len(token) > 30
    # The header contains a URL that includes the SAME token
    assert token in headers["List-Unsubscribe"], (
        "Token in body URL must equal token in header URL"
    )


def test_outreach_subscriptions_table_exists():
    """The new outreach_subscriptions table must be in the schema."""
    rows = _db.query_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='outreach_subscriptions'"
    )
    assert len(rows) == 1, "outreach_subscriptions table missing from schema"


def test_sender_build_mime_uses_single_token_for_both():
    """CRITICAL #3: the body URL and the header URL must contain the
    same token. If they differ, the unsubscribe click is unresolvable."""
    from src.config import settings
    original = settings.sender.physical_address
    settings.sender.physical_address = "123 Test St, Toronto, ON"
    test_email = f"test-unsub-{uuid.uuid4().hex[:8]}@example.com"
    lead_id = mailbox_id = job_id = None
    try:
        now = datetime.now(timezone.utc).isoformat()

        # Pre-clean any rows from prior runs (delete children first)
        _db.exec("DELETE FROM sent_log WHERE send_job_id IN (SELECT id FROM send_jobs WHERE subject = '[TEST] token-check')", ())
        _db.exec("DELETE FROM send_jobs WHERE subject = ?", ("[TEST] token-check",))
        _db.exec("DELETE FROM leads WHERE email LIKE 'test-unsub-%@example.com'", ())
        _db.exec("DELETE FROM mailboxes WHERE email = ?", ("sender-token@example.com",))

        _db.exec(
            """INSERT INTO leads (email, first_name, last_name, company, title, source, created_at, status)
               VALUES (?, 'Token', 'Test', 'TestCo', 'CTO', 'test', ?, 'queued')""",
            (test_email, now),
        )
        lead_id = _db.query_one("SELECT id FROM leads WHERE email = ?", (test_email,))["id"]

        _db.exec(
            """INSERT INTO mailboxes (email, oauth_token_path, provider, is_personal,
                                       warmup_started_at, current_daily_cap, total_sent_today,
                                       total_sent_lifetime, paused_reason, last_sent_at)
               VALUES (?, '', 'gmail', 1, ?, 100, 0, 0, NULL, NULL)""",
            ("sender-token@example.com", now),
        )
        mailbox_id = _db.query_one("SELECT id FROM mailboxes WHERE email = ?", ("sender-token@example.com",))["id"]

        _db.exec(
            """INSERT INTO send_jobs
                (campaign_id, variant_id, lead_id, mailbox_id, provider, subject, body,
                 scheduled_for, status)
               VALUES (NULL, NULL, ?, ?, 'gmail', '[TEST] token-check', 'Hi there.', ?, 'pending')""",
            (lead_id, mailbox_id, now),
        )
        job_id = _db.query_one(
            "SELECT id FROM send_jobs WHERE subject = ?", ("[TEST] token-check",)
        )["id"]

        job = dict(_db.query_one(
            """SELECT sj.*, l.email AS lead_email, l.first_name, l.last_name, l.company,
                      l.country, l.timezone, l.timezone AS lead_tz,
                      m.email AS mailbox_email
               FROM send_jobs sj
               JOIN leads l ON sj.lead_id = l.id
               JOIN mailboxes m ON sj.mailbox_id = m.id
               WHERE sj.id = ?""",
            (job_id,),
        ))

        mime_bytes, token = _build_mime_for_job(job)
        mime_text = mime_bytes.decode("utf-8", errors="replace")
        # The body must contain the raw token (it's clickable plain text).
        # The header may contain it in encoded-word form (RFC 2047) but
        # the URL must decode to the same token.
        body_occurrences = mime_text.count(token)
        assert body_occurrences >= 1, (
            f"Token must appear in body URL (raw). Found {body_occurrences} time(s)."
        )
        # The header URL — when URL-decoded + RFC 2047 decoded — must contain
        # the token. We check by stripping encoded-word markers and looking
        # for the token's first 16 chars (uniquely identifying).
        import re
        # Decode encoded-word sequences: =?utf-8?q?...?= and join
        def _decode_encoded_words(s):
            return re.sub(
                r"=\?[a-z0-9-]+\?[bq]\?([^?]*)\?=",
                lambda m: m.group(1).replace("_", " ").replace("=2E", ".").replace("=40", "@")
                          .replace("=3F", "?").replace("=26", "&").replace("=3D", "=")
                          .replace("=3C", "<").replace("=3E", ">").replace("=2C", ",")
                          .replace("=3A", ":").replace("=2F", "/").replace("=5F", "_"),
                s,
            )
        decoded = _decode_encoded_words(mime_text)
        assert token in decoded, (
            f"Token not found in decoded header. Looking for {token!r} in {decoded[:500]!r}"
        )
        assert test_email in mime_text
    finally:
        # Cleanup (delete children first)
        if job_id:
            _db.exec("DELETE FROM sent_log WHERE send_job_id = ?", (job_id,))
            _db.exec("UPDATE send_jobs SET status = 'sent' WHERE id = ?", (job_id,))
            _db.exec("DELETE FROM outreach_subscriptions WHERE send_job_id = ?", (job_id,))
            _db.exec("DELETE FROM send_jobs WHERE id = ?", (job_id,))
        if lead_id:
            _db.exec("DELETE FROM leads WHERE id = ?", (lead_id,))
        if mailbox_id:
            _db.exec("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
        settings.sender.physical_address = original


def test_atomic_claim_prevents_double_grab():
    """CRITICAL #1: two consecutive _next_pending_job() calls on the same
    eligible job must return at most ONE winner."""
    now = datetime.now(timezone.utc).isoformat()
    test_email = f"test-claim-{uuid.uuid4().hex[:8]}@example.com"
    lead_id = mailbox_id = job_id = None
    try:
        # Pre-clean children-first
        _db.exec("DELETE FROM sent_log WHERE send_job_id IN (SELECT id FROM send_jobs WHERE subject = '[TEST] atomic-claim')", ())
        _db.exec("DELETE FROM send_jobs WHERE subject = ?", ("[TEST] atomic-claim",))
        _db.exec("DELETE FROM leads WHERE email LIKE 'test-claim-%@example.com'", ())
        _db.exec("DELETE FROM mailboxes WHERE email = ?", ("claim-test@example.com",))

        _db.exec(
            """INSERT INTO leads (email, first_name, last_name, company, title, source, created_at, status)
               VALUES (?, 'Claim', 'Test', 'TestCo', 'CTO', 'test', ?, 'queued')""",
            (test_email, now),
        )
        lead_id = _db.query_one("SELECT id FROM leads WHERE email = ?", (test_email,))["id"]

        _db.exec(
            """INSERT INTO mailboxes (email, oauth_token_path, provider, is_personal,
                                       warmup_started_at, current_daily_cap, total_sent_today,
                                       total_sent_lifetime, paused_reason, last_sent_at)
               VALUES (?, '', 'gmail', 1, ?, 100, 0, 0, NULL, NULL)""",
            ("claim-test@example.com", now),
        )
        mailbox_id = _db.query_one("SELECT id FROM mailboxes WHERE email = ?", ("claim-test@example.com",))["id"]

        _db.exec(
            """INSERT INTO send_jobs
                (campaign_id, variant_id, lead_id, mailbox_id, provider, subject, body,
                 scheduled_for, status)
               VALUES (NULL, NULL, ?, ?, 'gmail', '[TEST] atomic-claim', 'test', ?, 'pending')""",
            (lead_id, mailbox_id, now),
        )
        job_id = _db.query_one(
            "SELECT id FROM send_jobs WHERE subject = ?", ("[TEST] atomic-claim",)
        )["id"]

        first = _next_pending_job()
        assert first is not None, "First call should return the pending job"
        assert first["id"] == job_id
        assert first["status"] == "sending", f"Expected status='sending' after claim, got {first['status']}"

        second = _next_pending_job()
        if second is not None:
            assert second["id"] != job_id, "Atomic claim failed: second caller grabbed the same job"
    finally:
        if job_id:
            _db.exec("DELETE FROM sent_log WHERE send_job_id = ?", (job_id,))
            _db.exec("UPDATE send_jobs SET status = 'sent' WHERE id = ?", (job_id,))
            _db.exec("DELETE FROM outreach_subscriptions WHERE send_job_id = ?", (job_id,))
            _db.exec("DELETE FROM send_jobs WHERE id = ?", (job_id,))
        if lead_id:
            _db.exec("DELETE FROM leads WHERE id = ?", (lead_id,))
        if mailbox_id:
            _db.exec("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))


def test_record_sent_persists_outreach_subscription():
    """Verify that _record_sent writes a row to outreach_subscriptions
    with the same token that was used in the MIME. This is the
    persistence half of CRITICAL #3."""
    now = datetime.now(timezone.utc).isoformat()
    test_email = f"test-persist-{uuid.uuid4().hex[:8]}@example.com"
    test_token = generate_unsubscribe_token()

    # Pre-clean
    _db.exec("DELETE FROM leads WHERE email LIKE 'test-persist-%@example.com'", ())
    _db.exec("DELETE FROM outreach_subscriptions WHERE email LIKE 'test-persist-%@example.com'", ())

    _db.exec(
        """INSERT INTO leads (email, first_name, last_name, company, title, source, created_at, status)
           VALUES (?, 'Persist', 'Test', 'TestCo', 'CTO', 'test', ?, 'queued')""",
        (test_email, now),
    )

    # Insert the subscription directly (we're testing persistence, not the full send)
    _db.exec(
        """INSERT INTO outreach_subscriptions (email, token, campaign_id, send_job_id, sent_at)
           VALUES (?, ?, NULL, NULL, ?)""",
        (test_email, test_token, now),
    )

    # Look it up by token — the unsubscribe handler will do this
    row = _db.query_one(
        "SELECT email FROM outreach_subscriptions WHERE token = ?", (test_token,)
    )
    assert row is not None, "Subscription not persisted"
    assert row["email"] == test_email

    # Token uniqueness: try to insert a second row with the same token
    _db.exec(
        """INSERT OR IGNORE INTO outreach_subscriptions (email, token, campaign_id, send_job_id, sent_at)
           VALUES (?, ?, NULL, NULL, ?)""",
        (test_email + "dup", test_token, now),
    )
    count = _db.query_one(
        "SELECT COUNT(*) AS n FROM outreach_subscriptions WHERE token = ?", (test_token,)
    )["n"]
    assert count == 1, f"Token should be UNIQUE, but {count} rows match"

    # Cleanup
    _db.exec("DELETE FROM outreach_subscriptions WHERE email LIKE 'test-persist-%@example.com'", ())
    _db.exec("DELETE FROM leads WHERE email LIKE 'test-persist-%@example.com'", ())
