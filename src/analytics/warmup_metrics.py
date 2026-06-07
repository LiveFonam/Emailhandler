"""Per-mailbox warmup metrics for the dashboard."""
from __future__ import annotations

import datetime as dt

from src import db
from src.outreach.warmup import current_cap, mailbox_send_count_today, list_mailboxes


def per_mailbox_status() -> list[dict]:
    out = []
    for mb in list_mailboxes():
        cap = current_cap(mb["id"])
        sent = mailbox_send_count_today(mb["id"])
        out.append({
            "id": mb["id"],
            "email": mb["email"],
            "sent_today": sent,
            "cap_today": cap,
            "lifetime_sent": mb["total_sent_lifetime"] or 0,
            "paused": bool(mb["paused_reason"]),
            "paused_reason": mb["paused_reason"] or "",
            "warmup_started_at": mb["warmup_started_at"] or "",
        })
    return out


def daily_send_history(mailbox_id: int, days: int = 30) -> list[dict]:
    rows = db.query_all(
        f"""SELECT date(sent_at) AS day, COUNT(*) AS n
            FROM sent_log
            WHERE send_job_id IN (SELECT id FROM send_jobs WHERE mailbox_id = ?)
              AND date(sent_at) >= date('now', '-{int(days)} day')
            GROUP BY date(sent_at)
            ORDER BY day""",
        (mailbox_id,),
    )
    return [dict(r) for r in rows]
