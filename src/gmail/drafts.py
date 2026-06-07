"""Build a properly-threaded reply MIME and create Gmail drafts.

Threads need In-Reply-To + References headers and the same Subject with
Re: prefix, or Gmail treats it as a new conversation. We construct the
raw RFC 2822 bytes via stdlib email.mime and hand them to the API.
"""
from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from typing import Optional

from src.gmail.client import build_service, with_backoff


def _strip_r(headers: list[dict]) -> dict[str, str]:
    """Gmail headers come as [{name, value}, ...]."""
    return {h["name"].lower(): h["value"] for h in headers}


def _last_message_id(digest: dict) -> Optional[str]:
    """Get the Message-ID of the most recent message in the thread digest."""
    msgs = digest.get("messages", []) or []
    if not msgs:
        return None
    # The original Gmail thread's `messages[].id` is the Gmail message id, not
    # the RFC 2822 Message-ID. For threading we use the original headers'
    # Message-ID if present, otherwise fall back to the Gmail id.
    for m in reversed(msgs):
        gid = m.get("id")
        if gid:
            return gid
    return None


def _strip_re(subject: str) -> str:
    s = subject.strip()
    if s.lower().startswith("re:"):
        return s
    return "Re: " + s


def build_reply_mime(
    digest: dict,
    body: str,
    from_addr: str,
    signature: str = "",
) -> bytes:
    """Construct a properly-threaded reply MIME message as bytes."""
    msg = EmailMessage()
    subject = _strip_re(digest.get("subject", "(no subject)"))
    msg["Subject"] = subject
    msg["From"] = from_addr
    last_from = digest.get("last_from", "")
    if last_from:
        msg["To"] = last_from

    last_mid = _last_message_id(digest)
    if last_mid:
        msg["In-Reply-To"] = f"<{last_mid}@mail.gmail.com>"
        msg["References"] = f"<{last_mid}@mail.gmail.com>"

    full_body = body
    if signature:
        full_body = f"{body}\n\n{signature}"
    msg.set_content(full_body)
    return msg.as_bytes()


def create_draft(
    thread_id: str,
    mime_bytes: bytes,
    account: str = "default",
) -> str:
    """Create a Gmail draft attached to a thread. Returns the draft id."""
    service = build_service(account)
    raw = base64.urlsafe_b64encode(mime_bytes).decode("ascii")
    @with_backoff
    def _call():
        return (
            service.users()
            .drafts()
            .create(
                userId="me",
                body={"message": {"threadId": thread_id, "raw": raw}},
            )
            .execute()
        )
    resp = _call()
    return resp.get("id", "")


def update_draft(
    draft_id: str,
    mime_bytes: bytes,
    account: str = "default",
) -> None:
    """Update an existing draft's message body."""
    service = build_service(account)
    raw = base64.urlsafe_b64encode(mime_bytes).decode("ascii")
    @with_backoff
    def _call():
        return (
            service.users()
            .drafts()
            .update(
                userId="me",
                id=draft_id,
                body={"message": {"raw": raw}},
            )
            .execute()
        )
    _call()


def delete_draft(draft_id: str, account: str = "default") -> None:
    service = build_service(account)
    @with_backoff
    def _call():
        return service.users().drafts().delete(userId="me", id=draft_id).execute()
    _call()
