"""APScheduler runs in a SEPARATE Python process, not inside Streamlit.

This is non-negotiable: Streamlit's script-rerun semantics reset any
in-script BackgroundScheduler on every widget interaction, so background
jobs would never run. We launch this with launch.ps1 in a hidden window.

Jobs:
  1. inbox_poll          every 5 min     watch.poll_changes -> triage new
  2. outreach_dispatch   every 60s       pop next SendJob -> send
  3. warmup_bump         daily 00:00     roll mailbox caps up the ramp
  4. snooze_restore      every 60s       move expired snoozes back to Inbox
  5. compliance_audit    daily 04:00     re-scan sent_log for missing headers
  6. reply_scan          every 6h        refresh reply-rate metrics
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
import time
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import paths  # noqa: E402
from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402
from apscheduler.triggers.interval import IntervalTrigger  # noqa: E402

from src import db  # noqa: E402
from src.gmail.watch import poll_changes  # noqa: E402
from src.gmail.modify import SNOOZE_BUCKETS  # noqa: E402


log = logging.getLogger("inbox_zero.scheduler")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(paths.RUN_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


# --- job bodies ---


def job_inbox_poll():
    """Poll each configured mailbox for new messages and trigger triage."""
    accounts = _configured_accounts()
    for acct in accounts:
        try:
            new_thread_ids = poll_changes(account=acct)
            if new_thread_ids:
                log.info(f"inbox_poll: {acct} -> {len(new_thread_ids)} new thread(s)")
                # Triage is heavy; defer to a separate background pool
                # in v1.1. For now, log and let the user click "Triage
                # new" in the Inbox page.
                for tid in new_thread_ids:
                    log.info(f"  new thread: {tid}")
        except Exception as e:
            log.warning(f"inbox_poll: {acct} failed: {e}")


def job_outreach_dispatch():
    """Pop the next SendJob whose scheduled_for <= now and dispatch it."""
    from src.outreach.sender import send_next_pending
    try:
        n = send_next_pending()
        if n:
            log.info(f"outreach_dispatch: sent 1 job ({n})")
    except Exception as e:
        log.warning(f"outreach_dispatch failed: {e}")


def job_warmup_bump():
    """Daily 00:00: roll caps up the ramp. The current_cap() function
    reads days_since(warmup_started_at) at call time, so this is mostly
    bookkeeping to log the new cap values."""
    from src.outreach.warmup import list_mailboxes, current_cap
    for mb in list_mailboxes():
        cap = current_cap(mb["id"])
        log.info(
            f"warmup_bump: mailbox {mb['id']} ({mb['email']}) -> cap {cap}/day"
        )


def job_snooze_restore():
    """Move expired snoozes back to Inbox."""
    from src.gmail.modify import archive  # We un-archive
    from src.gmail.client import build_service, with_backoff

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = db.query_all(
        "SELECT thread_id, bucket FROM snoozes WHERE until_at <= ?", (now,)
    )
    for r in rows:
        thread_id = r["thread_id"]
        # Find the corresponding Gmail label to remove and re-add INBOX
        try:
            # The "restore" is: remove the snooze label, add INBOX.
            # For v1, we just call a label remove; the Gmail API also
            # has "un-archive" via INBOX label add.
            # We don't know which account without join, so default for now.
            from src.gmail.client import build_service, with_backoff
            from src.gmail.labels import remove_label
            remove_label(thread_id, r["bucket"] or "AI/Snoozed-24h")
            # Add INBOX back: build a small modify call.
            service = build_service("default")
            with_backoff(lambda: service.users().threads().modify(
                userId="me", id=thread_id, body={"addLabelIds": ["INBOX"]}
            ).execute())()
            db.exec("DELETE FROM snoozes WHERE thread_id = ?", (thread_id,))
            log.info(f"snooze_restore: restored {thread_id}")
        except Exception as e:
            log.warning(f"snooze_restore: failed to restore {thread_id}: {e}")


def job_compliance_audit():
    """Daily 04:00: re-scan sent_log for any non-compliant sends."""
    from src.outreach.compliance import check_mime
    from src import db
    from pathlib import Path

    rows = db.query_all(
        """SELECT id, raw_mime_path FROM sent_log
           WHERE date(sent_at) >= date('now', '-1 day') AND raw_mime_path IS NOT NULL"""
    )
    failures = []
    passed = 0
    for r in rows:
        path = Path(r["raw_mime_path"])
        if not path.exists():
            failures.append({"id": r["id"], "issues": ["raw_mime_path missing on disk"]})
            continue
        try:
            mime = path.read_bytes()
            check = check_mime(mime)
            if check.ok:
                passed += 1
            else:
                failures.append({"id": r["id"], "issues": check.issues})
        except Exception as e:
            failures.append({"id": r["id"], "issues": [str(e)]})

    db.exec(
        """INSERT INTO compliance_audit (ran_at, window_start, window_end, total_checked, passed, failed, failures_json)
           VALUES (?, date('now', '-1 day'), date('now'), ?, ?, ?, ?)""",
        (
            dt.datetime.now(dt.timezone.utc).isoformat(),
            len(rows),
            passed,
            len(failures),
            db.to_json(failures),
        ),
    )
    if failures:
        log.warning(f"compliance_audit: {len(failures)} failures in the last 24h")
    else:
        log.info(f"compliance_audit: all {len(rows)} sends in the last 24h OK")


def job_reply_scan():
    """Refresh reply-rate metrics. v1: just log a heartbeat. v1.1
    implementation: scan threads, look for replies from sent-log leads."""
    from src.analytics.reply_rate import refresh_all_reply_metrics
    try:
        refresh_all_reply_metrics()
    except Exception as e:
        log.warning(f"reply_scan failed: {e}")


# --- helpers ---


def _configured_accounts() -> list[str]:
    """Return the list of account aliases we should poll. For v1 this is
    just the default account + the personal Gmail in config."""
    accounts = ["default"]
    try:
        from src.config import settings
        if settings.triage.triage_account:
            accounts.append(settings.triage.triage_account)
    except Exception:
        pass
    return accounts


# --- main ---


def main():
    log.info("inbox-zero-agent scheduler starting")
    log.info(f"DB: {paths.DB_PATH}")
    db.init_schema()

    sched = BackgroundScheduler(timezone="UTC")
    # CRITICAL: max_instances=1 + coalesce=True on outreach_dispatch prevents
    # the same SendJob from being processed by two iterations simultaneously.
    # The DB-level claim in sender._next_pending_job is the second line of
    # defense; this is the first.
    sched.add_job(job_inbox_poll, IntervalTrigger(minutes=5), id="inbox_poll", replace_existing=True)
    sched.add_job(
        job_outreach_dispatch,
        IntervalTrigger(seconds=60),
        id="outreach_dispatch",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    sched.add_job(job_warmup_bump, CronTrigger(hour=0, minute=0), id="warmup_bump", replace_existing=True)
    sched.add_job(job_snooze_restore, IntervalTrigger(seconds=60), id="snooze_restore", replace_existing=True)
    sched.add_job(job_compliance_audit, CronTrigger(hour=4, minute=0), id="compliance_audit", replace_existing=True)
    sched.add_job(job_reply_scan, IntervalTrigger(hours=6), id="reply_scan", replace_existing=True)

    sched.start()
    log.info("scheduler started; jobs registered: %s", [j.id for j in sched.get_jobs()])

    try:
        # Block forever
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler shutting down")
        sched.shutdown(wait=False)


if __name__ == "__main__":
    main()
