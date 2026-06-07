"""CAN-SPAM compliance: the single source of truth for outbound email.

Every cold / outreach email MUST have:
  - List-Unsubscribe: <https://...>      (RFC 8058 one-click)
  - List-Unsubscribe-Post: List-Unsubscribe=One-Click
  - X-Entity-Ref-ID: <uuid>               (Instantly-style tracking id)
  - Precedence: bulk
  - Physical postal address in the body (footer)

`assert_headers(mime_bytes)` is called from gmail.send.send_mime() before
any send. If any required header is missing, we raise and refuse to send.

Penalties: $53,088 per non-compliant commercial email (FTC 2025 inflation).
"""
from __future__ import annotations

import re
import secrets
import uuid
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Optional

from src.config import settings
from src.schemas import ComplianceCheck


REQUIRED_HEADERS = [
    "List-Unsubscribe",
    "List-Unsubscribe-Post",
    "X-Entity-Ref-ID",
]


def generate_unsubscribe_token() -> str:
    """Per-recipient one-click token. 32 url-safe bytes."""
    return secrets.token_urlsafe(32)


def build_unsubscribe_url(email: str, token: str) -> str:
    base = settings.compliance.unsubscribe_base_url.rstrip("/")
    return f"{base}?email={email}&token={token}"


def can_spam_headers(
    from_addr: str,
    reply_to: str,
    email: str,
) -> dict[str, str]:
    """Return the dict of CAN-SPAM headers to add to a Message object."""
    token = generate_unsubscribe_token()
    unsub_url = build_unsubscribe_url(email, token)
    return {
        "List-Unsubscribe": f"<{unsub_url}>, <mailto:unsubscribe@localhost?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        "X-Entity-Ref-ID": str(uuid.uuid4()),
        "Precedence": "bulk",
    }, token


def physical_address_footer() -> str:
    """The CAN-SPAM-required footer line. Empty if not configured."""
    addr = settings.sender.physical_address.strip()
    if not addr:
        return ""
    return (
        f"\n\n--\nLucas  |  {addr}\n"
        f"You're receiving this because you opted in or we have a prior "
        f"business relationship. Unsubscribe: {{unsub_url}}"
    )


def check_mime(mime_bytes: bytes) -> ComplianceCheck:
    """Parse a MIME and report which required CAN-SPAM fields are present."""
    msg = BytesParser(policy=policy.default).parsebytes(mime_bytes)
    headers = {k: str(v) for k, v in msg.items()}

    has_unsub = "List-Unsubscribe" in headers
    has_unsub_post = "List-Unsubscribe-Post" in headers
    has_ref = "X-Entity-Ref-ID" in headers
    has_bulk = headers.get("Precedence", "").lower() == "bulk"

    # Body inspection: look for the physical address or a stub
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body += part.get_content()
                except Exception:
                    pass
    else:
        try:
            body = msg.get_content()
        except Exception:
            body = ""

    has_addr = bool(
        settings.sender.physical_address.strip()
        and settings.sender.physical_address.strip() in body
    )

    issues: list[str] = []
    if not has_unsub:
        issues.append("missing List-Unsubscribe header")
    if not has_unsub_post:
        issues.append("missing List-Unsubscribe-Post header")
    if not has_ref:
        issues.append("missing X-Entity-Ref-ID header")
    if not has_bulk:
        issues.append("missing or wrong Precedence: bulk header")
    if not has_addr:
        if not settings.sender.physical_address.strip():
            issues.append("sender.physical_address not set in config.yaml")
        else:
            issues.append("physical address not found in body")

    # Cheap spam-score heuristic
    spam_hits = 0
    spam_words = [
        r"\bfree\b", r"\bguaranteed\b", r"act now", r"limited time",
        r"!!!+", r"\$\$\$", r"100% free",
    ]
    for pat in spam_words:
        if re.search(pat, body, re.IGNORECASE):
            spam_hits += 1
    spam_score = min(1.0, spam_hits / 4.0)

    return ComplianceCheck(
        has_list_unsubscribe=has_unsub,
        has_list_unsubscribe_post=has_unsub_post,
        has_physical_address=has_addr,
        has_precedence_bulk=has_bulk,
        spam_score=spam_score,
        issues=issues,
    )


def assert_headers(mime_bytes: bytes) -> ComplianceCheck:
    """Raise if the MIME is not CAN-SPAM compliant. Otherwise return the check."""
    check = check_mime(mime_bytes)
    if not check.ok:
        raise ValueError(
            "Refusing to send non-CAN-SPAM-compliant email. Issues:\n  - "
            + "\n  - ".join(check.issues)
        )
    return check
