"""Per-mailbox warmup ramp.

Each mailbox has a `warmup_started_at` timestamp. `current_cap()` returns
the daily cap based on days since warmup started. The cap grows 50% per
week (per the user-approved ramp schedule).

This is enforced server-side. The UI cannot override it.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Optional

from src import db
from src.config import settings


def _days_since(start_iso: str) -> int:
    if not start_iso:
        return 0
    try:
        start = dt.datetime.fromisoformat(start_iso)
    except Exception:
        return 0
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    return max(0, (now - start).days)


def current_cap(mailbox_id: int) -> int:
    row = db.query_one(
        "SELECT warmup_started_at, current_daily_cap, paused_reason FROM mailboxes WHERE id = ?",
        (mailbox_id,),
    )
    if not row:
        return 0
    if row["paused_reason"]:
        return 0
    days = _days_since(row["warmup_started_at"])
    return settings.warmup.cap_for_day(days)


def mailbox_send_count_today(mailbox_id: int) -> int:
    """Returns the count of SendJobs that completed today for this mailbox.

    We use sent_log as the source of truth (a job becomes "sent" when
    its log row is written). For jobs queued today but not yet sent,
    use the scheduled_for field instead.
    """
    row = db.query_one(
        """SELECT COUNT(*) AS c FROM sent_log
           WHERE send_job_id IN (SELECT id FROM send_jobs WHERE mailbox_id = ?)
             AND date(sent_at) = date('now')""",
        (mailbox_id,),
    )
    return int(row["c"]) if row else 0


def bump_day(mailbox_id: int) -> None:
    """Called by the scheduler daily at 00:00 to roll the cap up the ramp.
    We don't have to do anything explicit; current_cap() reads
    days_since(warmup_started_at) at call time. This is a no-op kept
    for symmetry with v1.1 plans.
    """
    return None


def start_warmup(mailbox_id: int, when: Optional[dt.datetime] = None) -> None:
    when = when or dt.datetime.now(dt.timezone.utc)
    db.exec(
        "UPDATE mailboxes SET warmup_started_at = ?, paused_reason = NULL WHERE id = ?",
        (when.isoformat(), mailbox_id),
    )


def pause(mailbox_id: int, reason: str) -> None:
    db.exec(
        "UPDATE mailboxes SET paused_reason = ? WHERE id = ?",
        (reason, mailbox_id),
    )


def unpause(mailbox_id: int) -> None:
    db.exec(
        "UPDATE mailboxes SET paused_reason = NULL WHERE id = ?",
        (mailbox_id,),
    )


def list_mailboxes() -> list[sqlite3.Row]:
    return db.query_all("SELECT * FROM mailboxes ORDER BY id")
