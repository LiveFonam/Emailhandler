"""Send a raw MIME message via Gmail API.

This is the ONLY path that calls users.messages.send. Before any send,
`compliance.assert_headers()` is called; if any required header is missing
or the physical address isn't in the body, we refuse.
"""
from __future__ import annotations

import base64

from src.gmail.client import build_service, with_backoff
from src.outreach.compliance import assert_headers


def send_mime(
    mime_bytes: bytes,
    thread_id: str | None = None,
    account: str = "default",
) -> dict:
    """Send a constructed MIME message. Raises if compliance check fails.

    Returns the API response dict (with 'id' = the Gmail message id).
    """
    # CAN-SPAM gate: refuse to send non-compliant mail.
    assert_headers(mime_bytes)

    service = build_service(account)
    raw = base64.urlsafe_b64encode(mime_bytes).decode("ascii")
    body: dict = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id

    @with_backoff
    def _call():
        return service.users().messages().send(userId="me", body=body).execute()

    return _call()
