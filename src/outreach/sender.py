"""Outreach sender: the dispatch decision.

For v1, we only have the Gmail API path. v1.1 swaps in Instantly.ai.

`send_next_pending()` is called by the scheduler every 60s. It:
  1. SELECTs the oldest SendJob with status='pending' and scheduled_for<=now
  2. Checks suppression -> skips if suppressed
  3. Checks warmup cap -> defers if at cap
  4. Checks recipient-TZ business hours -> defers if outside
  5. Builds the MIME via the campaign_variant + compliance module
  6. Sends via Gmail API
  7. Records sent_log row, updates lead.status
"""
from __future__ import annotations

import base64
import datetime as dt
import logging
from email.message import EmailMessage

from src import db
from src.outreach.throttler import wait_for_slot
from src.outreach.suppress import is_suppressed
from src.outreach.compliance import (
    can_spam_headers,
    physical_address_footer,
    assert_headers,
)
from src.outreach.warmup import mailbox_send_count_today, current_cap

log = logging.getLogger("inbox_zero.outreach.sender")


def _next_pending_job() -> dict | None:
    row = db.query_one(
        """SELECT sj.*, l.email AS lead_email, l.first_name, l.last_name, l.company,
                  l.country, l.timezone, l.timezone AS lead_tz,
                  m.email AS mailbox_email
           FROM send_jobs sj
           JOIN leads l ON sj.lead_id = l.id
           JOIN mailboxes m ON sj.mailbox_id = m.id
           WHERE sj.status = 'pending' AND sj.scheduled_for <= ?
           ORDER BY sj.scheduled_for ASC
           LIMIT 1""",
        (dt.datetime.now(dt.timezone.utc).isoformat(),),
    )
    return dict(row) if row else None


def _build_mime_for_job(job: dict) -> bytes:
    """Build the CAN-SPAM-compliant MIME for a SendJob."""
    msg = EmailMessage()
    msg["Subject"] = job.get("subject", "")
    msg["From"] = job.get("mailbox_email", "")
    msg["To"] = job.get("lead_email", "")

    body = job.get("body", "")
    footer = physical_address_footer()
    if footer:
        # Replace the {{unsub_url}} placeholder
        from src.outreach.compliance import build_unsubscribe_url, generate_unsubscribe_token
        token = generate_unsubscribe_token()
        unsub_url = build_unsubscribe_url(job["lead_email"], token)
        body = body + footer.replace("{unsub_url}", unsub_url)

    msg.set_content(body)

    # CAN-SPAM headers
    headers, _tok = can_spam_headers(
        from_addr=job.get("mailbox_email", ""),
        reply_to=job.get("mailbox_email", ""),
        email=job.get("lead_email", ""),
    )
    for k, v in headers.items():
        msg[k] = v

    return msg.as_bytes()


def _send_via_gmail(mime_bytes: bytes, account: str, thread_id: str | None = None) -> dict:
    from src.gmail.client import build_service, with_backoff

    # compliance assertion (defense in depth — also enforced by src.gmail.send)
    assert_headers(mime_bytes)

    service = build_service(account)
    raw = base64.urlsafe_b64encode(mime_bytes).decode("ascii")
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id

    @with_backoff
    def _call():
        return service.users().messages().send(userId="me", body=body).execute()

    return _call()


def _record_sent(job: dict, gmail_response: dict, mime_bytes: bytes) -> None:
    sent_at = dt.datetime.now(dt.timezone.utc).isoformat()
    # Write MIME to disk for audit
    raw_path = paths_for_mime(job.get("id"))
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(mime_bytes)
    # sent_log
    db.exec(
        """INSERT INTO sent_log (send_job_id, provider, message_id, sent_at, raw_mime_path, compliance_ok, compliance_report)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            job["id"],
            job.get("provider", "gmail"),
            gmail_response.get("id", ""),
            sent_at,
            str(raw_path),
            1,
            "[]",
        ),
    )
    # Update job
    db.exec(
        """UPDATE send_jobs SET status = 'sent', sent_at = ?, sent_message_id = ? WHERE id = ?""",
        (sent_at, gmail_response.get("id", ""), job["id"]),
    )
    # Update lead status
    db.exec(
        "UPDATE leads SET status = 'sent' WHERE id = ? AND status IN ('queued', 'enriched', 'new')",
        (job["lead_id"],),
    )
    # Update variant
    if job.get("variant_id"):
        db.exec(
            "UPDATE campaign_variants SET status = 'sent' WHERE id = ?",
            (job["variant_id"],),
        )
    # Update mailbox
    db.exec(
        """UPDATE mailboxes
           SET total_sent_today = total_sent_today + 1,
               total_sent_lifetime = total_sent_lifetime + 1,
               last_sent_at = ?
           WHERE id = ?""",
        (sent_at, job["mailbox_id"]),
    )


def paths_for_mime(job_id: int):
    from app import paths
    return paths.SENT_MIME_DIR / f"job_{job_id}.eml"


def send_next_pending() -> int | None:
    """Pop the next eligible SendJob and send it. Returns job_id or None."""
    job = _next_pending_job()
    if not job:
        return None

    # Suppression check
    if is_suppressed(job["lead_email"]):
        db.exec(
            "UPDATE send_jobs SET status = 'skipped', error = 'suppressed' WHERE id = ?",
            (job["id"],),
        )
        log.info(f"send_next_pending: job {job['id']} skipped (suppressed)")
        return job["id"]

    # Cap check
    cap = current_cap(job["mailbox_id"])
    sent_today = mailbox_send_count_today(job["mailbox_id"])
    if sent_today >= cap:
        log.info(f"send_next_pending: cap reached for mailbox {job['mailbox_id']} ({sent_today}/{cap})")
        # Defer to tomorrow
        tomorrow = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0
        ).isoformat()
        db.exec(
            "UPDATE send_jobs SET scheduled_for = ? WHERE id = ?",
            (tomorrow, job["id"]),
        )
        return None

    # Business hours check + jitter
    slot = wait_for_slot(
        job["mailbox_id"],
        recipient_country=job.get("country"),
        recipient_tz=job.get("lead_tz"),
    )
    now = dt.datetime.now(dt.timezone.utc)
    if slot > now:
        log.info(f"send_next_pending: waiting for slot at {slot.isoformat()}")
        db.exec(
            "UPDATE send_jobs SET scheduled_for = ? WHERE id = ?",
            (slot.isoformat(), job["id"]),
        )
        return None

    # Build and send
    try:
        mime_bytes = _build_mime_for_job(job)
        gmail_resp = _send_via_gmail(mime_bytes, account="default", thread_id=None)
        _record_sent(job, gmail_resp, mime_bytes)
        log.info(f"send_next_pending: sent job {job['id']} (msg_id={gmail_resp.get('id', '')})")
        return job["id"]
    except Exception as e:
        log.warning(f"send_next_pending: send failed for job {job['id']}: {e}")
        db.exec(
            "UPDATE send_jobs SET status = 'failed', error = ? WHERE id = ?",
            (str(e)[:500], job["id"]),
        )
        return job["id"]
