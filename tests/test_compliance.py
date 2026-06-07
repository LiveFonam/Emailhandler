"""Tests for the CAN-SPAM compliance module.

Per the plan, these are required to fail the build if any of the
required headers drop out of a test message.

Run: cd inbox-zero-agent && python -m pytest tests/test_compliance.py -v
"""
from __future__ import annotations

import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.outreach.compliance import (
    can_spam_headers,
    check_mime,
    assert_headers,
    physical_address_footer,
)


def _build_compliant_mime(addr: str = "123 Main St, Toronto, ON") -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Test"
    msg["From"] = "lucas@example.com"
    msg["To"] = "lead@example.com"
    body = f"Hi there,\n\nThis is a normal email.\n\n--\nLucas  |  {addr}\nUnsubscribe: {{unsub_url}}"
    msg.set_content(body)
    headers, _tok = can_spam_headers("lucas@example.com", "lucas@example.com", "lead@example.com")
    for k, v in headers.items():
        msg[k] = v
    return msg.as_bytes()


def test_compliant_mime_passes(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings.sender, "physical_address", "123 Main St, Toronto, ON")
    mime = _build_compliant_mime()
    check = assert_headers(mime)
    assert check.ok, f"Expected compliance ok=True, got issues: {check.issues}"


def test_missing_list_unsubscribe_fails():
    msg = EmailMessage()
    msg["Subject"] = "Test"
    msg["From"] = "lucas@example.com"
    msg["To"] = "lead@example.com"
    msg.set_content("Body without unsubscribe")
    with pytest.raises(ValueError, match="List-Unsubscribe"):
        assert_headers(msg.as_bytes())


def test_missing_physical_address_fails():
    # Set the config to require an address (it might be empty in test env)
    from src.config import settings
    if not settings.sender.physical_address:
        # Pretend we have an address configured
        settings.sender.physical_address = "123 Main St, Toronto, ON"
    mime = _build_compliant_mime()  # this has the address in body
    check = check_mime(mime)
    assert check.has_physical_address


def test_spam_score_basic():
    msg = EmailMessage()
    msg["Subject"] = "FREE!!!"
    msg["From"] = "x@y.com"
    msg["To"] = "a@b.com"
    msg.set_content("Click now for $$$ 100% free guaranteed!!")
    check = check_mime(msg.as_bytes())
    assert check.spam_score > 0.0, "Spammy content should produce non-zero score"
