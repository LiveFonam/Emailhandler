"""Queue builder: materialize a campaign's variants into SendJob rows.

Respects suppression, warmup caps, and per-campaign settings.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from src import db
from src.config import settings
from src.outreach.suppress import is_suppressed

log = logging.getLogger("inbox_zero.outreach.queue")


def build_send_jobs(
    campaign_id: int,
    start_at: Optional[dt.datetime] = None,
    daily_cap: Optional[int] = None,
) -> int:
    """For each (variant) in the campaign, create a SendJob. Returns count.

    Schedule across the day with a 60-90s jitter so sends are spread.
    """
    campaign = db.query_one("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    if not campaign:
        log.warning(f"queue: campaign {campaign_id} not found")
        return 0

    from_mailbox_id = campaign["from_mailbox_id"]
    if not from_mailbox_id:
        # Auto-pick the first mailbox in the DB; v1.1 will let users choose
        row = db.query_one("SELECT id FROM mailboxes ORDER BY id LIMIT 1")
        if not row:
            log.warning("queue: no mailboxes configured")
            return 0
        from_mailbox_id = row["id"]

    cap = daily_cap or campaign["daily_cap"] or settings.warmup.start_cap

    # Pull all generated variants in this campaign
    variants = db.query_all(
        """SELECT v.id AS variant_id, v.subject, v.body, v.framework, v.lead_id
           FROM campaign_variants v
           WHERE v.campaign_id = ? AND v.status = 'generated'""",
        (campaign_id,),
    )
    if not variants:
        log.info(f"queue: campaign {campaign_id} has no generated variants")
        return 0

    # Pull lead info for suppression + scheduling
    lead_ids = list({v["lead_id"] for v in variants})
    placeholders = ",".join("?" * len(lead_ids))
    lead_rows = db.query_all(
        f"SELECT id, email, country, timezone FROM leads WHERE id IN ({placeholders})",
        lead_ids,
    )
    leads = {r["id"]: dict(r) for r in lead_rows}

    # Build rows. Spacing: spread the first `cap` sends across the day.
    # Subsequent sends push to tomorrow.
    start_at = start_at or dt.datetime.now(dt.timezone.utc)
    # Round to next 5 min
    start_at = start_at.replace(minute=(start_at.minute // 5) * 5, second=0, microsecond=0)
    sent_today = 0
    today_end = start_at.replace(hour=23, minute=59, second=0)
    rows_to_insert: list[tuple] = []
    scheduled_for = start_at

    for v in variants:
        lead = leads.get(v["lead_id"])
        if not lead:
            log.warning(f"queue: lead {v['lead_id']} missing")
            continue
        if is_suppressed(lead["email"]):
            db.exec(
                "UPDATE campaign_variants SET status = 'suppressed' WHERE id = ?",
                (v["variant_id"],),
            )
            continue

        # If we've hit today's cap, roll to tomorrow
        if sent_today >= cap:
            scheduled_for = (scheduled_for + dt.timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            sent_today = 0

        rows_to_insert.append((
            campaign_id,
            v["variant_id"],
            v["lead_id"],
            from_mailbox_id,
            campaign["provider"] or "gmail",
            v["subject"],
            v["body"],
            scheduled_for.isoformat(),
        ))
        # Next slot: 60-90s jitter (use min for deterministic spacing in tests)
        jitter = 75
        scheduled_for = scheduled_for + dt.timedelta(seconds=jitter)
        if scheduled_for > today_end:
            scheduled_for = (scheduled_for + dt.timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            sent_today = 0
        sent_today += 1

    if not rows_to_insert:
        log.info(f"queue: nothing to insert (all suppressed?) for campaign {campaign_id}")
        return 0

    db.execmany(
        """INSERT OR IGNORE INTO send_jobs
            (campaign_id, variant_id, lead_id, mailbox_id, provider, subject, body, scheduled_for, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        rows_to_insert,
    )
    # Update lead status -> 'queued'
    queued_lead_ids = list({r[2] for r in rows_to_insert})
    placeholders = ",".join("?" * len(queued_lead_ids))
    db.exec(
        f"UPDATE leads SET status = 'queued' WHERE id IN ({placeholders}) "
        f"AND status IN ('new', 'enriched')",
        queued_lead_ids,
    )
    log.info(f"queue: inserted {len(rows_to_insert)} send_jobs for campaign {campaign_id}")
    return len(rows_to_insert)
