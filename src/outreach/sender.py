"""Outreach sender: the dispatch decision.

`send_next_pending()` is called by the scheduler every 60s. It:
  1. ATOMICALLY CLAIMs the oldest SendJob (UPDATE...SET status='sending'
     WHERE status='pending'; if rowcount=0, another worker grabbed it).
  2. Checks suppression -> skips if suppressed
  3. Checks warmup cap -> defers if at cap
  4. Checks recipient-TZ business hours -> defers if outside
  5. Builds the MIME via the campaign_variant + compliance module
     (CAN-SPAM headers use a single token, baked into both header AND body
     URL, then persisted to outreach_subscriptions so the unsubscribe
     handler can resolve the click).
  6. Sends via the Gmail account the job was assigned to (mailbox.email
     resolves to the OAuth token at gmail/oauth.py)
  7. Records sent_log row + all state updates in a SINGLE transaction
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
    build_unsubscribe_url,
)
from src.outreach.warmup import mailbox_send_count_today, current_cap

log = logging.getLogger("inbox_zero.outreach.sender")


def _next_pending_job() -> dict | None:
    """ATOMIC claim: flip status from 'pending' to 'sending' in one UPDATE.
    Returns the row only if we won the race. Two scheduler iterations cannot
    both grab the same job.
    """
    # Step 1: pick the oldest eligible job (read-only)
    row = db.query_one(
        """SELECT sj.*, l.email AS lead_email, l.first_name, l.last_name, l.company,
                  l.country, l.timezone, l.timezone AS lead_tz,
                  m.email AS mailbox_email, m.oauth_token_path
           FROM send_jobs sj
           JOIN leads l ON sj.lead_id = l.id
           JOIN mailboxes m ON sj.mailbox_id = m.id
           WHERE sj.status = 'pending' AND sj.scheduled_for <= ?
           ORDER BY sj.scheduled_for ASC
           LIMIT 1""",
        (dt.datetime.now(dt.timezone.utc).isoformat(),),
    )
    if not row:
        return None

    # Step 2: claim it. UPDATE...WHERE status='pending' acts as a CAS guard.
    n = db.exec(
        "UPDATE send_jobs SET status = 'sending' WHERE id = ? AND status = 'pending'",
        (row["id"],),
        return_rowcount=True,
    )
    if n != 1:
        log.info(f"send_next_pending: job {row['id']} lost the claim race")
        return None

    # Step 3: re-read with the post-claim status so callers see 'sending'
    updated = db.query_one(
        """SELECT sj.*, l.email AS lead_email, l.first_name, l.last_name, l.company,
                  l.country, l.timezone, l.timezone AS lead_tz,
                  m.email AS mailbox_email, m.oauth_token_path
           FROM send_jobs sj
           JOIN leads l ON sj.lead_id = l.id
           JOIN mailboxes m ON sj.mailbox_id = m.id
           WHERE sj.id = ?""",
        (row["id"],),
    )
    return dict(updated) if updated else None


def _release_claim(job_id: int) -> None:
    """If the send failed before _record_sent, put the job back to 'pending'."""
    db.exec(
        "UPDATE send_jobs SET status = 'pending' WHERE id = ? AND status = 'sending'",
        (job_id,),
    )


def _build_mime_for_job(job: dict) -> tuple[bytes, str]:
    """Build the CAN-SPAM-compliant MIME for a SendJob.

    Returns (mime_bytes, token). The token is the single source of truth
    for the unsubscribe URL — same token in header AND body, and the caller
    MUST persist it to outreach_subscriptions.
    """
    msg = EmailMessage()
    msg["Subject"] = job.get("subject", "")
    msg["From"] = job.get("mailbox_email", "")
    msg["To"] = job.get("lead_email", "")

    # Generate the token ONCE here, reuse it in both header and body.
    # Pass it through physical_address_footer as a substitution token.
    body = job.get("body", "")
    footer_template = physical_address_footer()
    if footer_template:
        # We need the token before we can build the body URL. Build the
        # headers first to get the token, then rebuild the body with it.
        pass

    # CAN-SPAM headers (returns headers dict + the single token)
    headers, token = can_spam_headers(
        from_addr=job.get("mailbox_email", ""),
        reply_to=job.get("mailbox_email", ""),
        email=job.get("lead_email", ""),
    )

    if footer_template:
        unsub_url = build_unsubscribe_url(job["lead_email"], token)
        body = body + footer_template.replace("{unsub_url}", unsub_url)

    # cte='8bit' is critical: the unsubscribe URL contains '=' which would
    # otherwise be quoted-printable encoded as '=3D' in the body, making
    # the body URL unresolvable on click.
    msg.set_content(body, cte="8bit")
    for k, v in headers.items():
        msg[k] = v

    return msg.as_bytes(), token


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


def _record_sent(job: dict, gmail_response: dict, mime_bytes: bytes, token: str) -> None:
    """Write sent_log + update all related rows in a SINGLE transaction.

    Critical: a crash mid-write (between sent_log and mailboxes counter)
    would leave the daily cap stale. With the unified transaction, either
    all 6 writes commit or none do.
    """
    sent_at = dt.datetime.now(dt.timezone.utc).isoformat()
    raw_path = paths_for_mime(job.get("id"))
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(mime_bytes)

    with db.transaction() as conn:
        # 1. sent_log
        conn.execute(
            """INSERT INTO sent_log (send_job_id, provider, message_id, sent_at, raw_mime_path, compliance_ok, compliance_report)
               VALUES (?, ?, ?, ?, ?, 1, '[]')""",
            (
                job["id"],
                job.get("provider", "gmail"),
                gmail_response.get("id", ""),
                sent_at,
                str(raw_path),
            ),
        )
        # 2. send_jobs (only flip from 'sending' to 'sent', preserving the claim)
        conn.execute(
            """UPDATE send_jobs SET status = 'sent', sent_at = ?, sent_message_id = ?
               WHERE id = ? AND status = 'sending'""",
            (sent_at, gmail_response.get("id", ""), job["id"]),
        )
        # 3. leads
        conn.execute(
            "UPDATE leads SET status = 'sent' WHERE id = ? AND status IN ('queued', 'enriched', 'new')",
            (job["lead_id"],),
        )
        # 4. campaign_variants
        if job.get("variant_id"):
            conn.execute(
                "UPDATE campaign_variants SET status = 'sent' WHERE id = ?",
                (job["variant_id"],),
            )
        # 5. mailboxes counter
        conn.execute(
            """UPDATE mailboxes
               SET total_sent_today = total_sent_today + 1,
                   total_sent_lifetime = total_sent_lifetime + 1,
                   last_sent_at = ?
               WHERE id = ?""",
            (sent_at, job["mailbox_id"]),
        )
        # 6. outreach_subscriptions — persist the token so unsubscribe works
        conn.execute(
            """INSERT OR IGNORE INTO outreach_subscriptions
                (email, token, campaign_id, send_job_id, sent_at)
               VALUES (?, ?, ?, ?, ?)""",
            (job["lead_email"], token, job.get("campaign_id"), job["id"], sent_at),
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
        # Defer to tomorrow AND release the claim (back to pending)
        tomorrow = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0
        ).isoformat()
        db.exec(
            "UPDATE send_jobs SET status = 'pending', scheduled_for = ? WHERE id = ?",
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
        # Release claim (back to pending with new scheduled_for)
        db.exec(
            "UPDATE send_jobs SET status = 'pending', scheduled_for = ? WHERE id = ?",
            (slot.isoformat(), job["id"]),
        )
        return None

    # Build and send
    try:
        mime_bytes, token = _build_mime_for_job(job)
        # Use the mailbox's actual email address as the OAuth account key
        account = job.get("mailbox_email", "default")
        gmail_resp = _send_via_gmail(mime_bytes, account=account, thread_id=None)
        _record_sent(job, gmail_resp, mime_bytes, token)
        log.info(f"send_next_pending: sent job {job['id']} (msg_id={gmail_resp.get('id', '')})")
        return job["id"]
    except Exception as e:
        log.warning(f"send_next_pending: send failed for job {job['id']}: {e}")
        db.exec(
            "UPDATE send_jobs SET status = 'failed', error = ? WHERE id = ? AND status = 'sending'",
            (str(e)[:500], job["id"]),
        )
        return job["id"]
