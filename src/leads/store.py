"""Lead persistence.

upsert_lead is the only path that should write to the `leads` table. It is
the gate that enforces the suppression list and the dedupe rule. Everything
else in the pipeline funnels into here.
"""
from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from typing import Optional

from src import db
from src.leads.dedupe import dedupe_key
from src.outreach.suppress import is_suppressed

log = logging.getLogger("inbox_zero.leads.store")


_LEAD_COLUMNS = (
    "email", "first_name", "last_name", "company", "company_domain",
    "title", "city", "country", "timezone", "source", "source_url",
    "raw_payload", "recent_news", "linkedin_snippet",
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _norm_email(value: str) -> str:
    return (value or "").strip().lower()


def _existing_by_email(email: str) -> Optional[sqlite3.Row]:
    return db.query_one("SELECT * FROM leads WHERE email = ?", (email,))


def _existing_by_key(key: str) -> Optional[sqlite3.Row]:
    """Find a lead whose dedupe_key matches. dedupe_key is not a column; we
    reconstruct it from the row we just read. When the input key is a
    nameco:... key (no email), we compare each existing lead with its email
    masked out so a nameco-only input can still merge against a lead that
    already has an email.
    """
    rows = db.query_all("SELECT * FROM leads")
    for r in rows:
        candidate = {
            "email": "" if key.startswith("nameco:") else r["email"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "company": r["company"],
        }
        if dedupe_key(candidate) == key:
            return r
    return None


def upsert_lead(lead_data: dict) -> int | None:
    """Insert or update a lead in the `leads` table.

    - If lead_data['email'] is empty or suppressed, skip (return None).
    - If a lead with the same email exists, update it (preserve status).
    - If no email but dedupe_key matches an existing lead, merge into that one.
    - Otherwise insert as new with status='new'.

    Returns the lead id, or None if skipped.
    """
    email = _norm_email(lead_data.get("email", ""))

    if not email:
        # Try dedupe-by-(name, company)
        key = dedupe_key(lead_data)
        row = _existing_by_key(key)
        if not row:
            log.info("upsert_lead: skipping (no email, no dedupe match)")
            return None
        # No email supplied; merge non-empty fields into the existing row.
        return _update_lead(row["id"], lead_data, allow_status_change=False)

    if is_suppressed(email):
        log.info(f"upsert_lead: skipping suppressed email {email!r}")
        return None

    existing = _existing_by_email(email)
    if existing:
        return _update_lead(existing["id"], lead_data, allow_status_change=False)

    return _insert_lead(lead_data)


def _insert_lead(lead_data: dict) -> int:
    payload = {col: (lead_data.get(col) or "") for col in _LEAD_COLUMNS}
    email = _norm_email(lead_data.get("email", ""))
    if not email:
        raise ValueError("insert requires an email")
    raw = lead_data.get("raw_payload")
    raw_json = db.to_json(raw) if raw and not isinstance(raw, str) else (raw or "")
    now = _now()
    return db.insert_and_return_id(
        """INSERT INTO leads
            (email, first_name, last_name, company, company_domain, title,
             city, country, timezone, source, source_url, raw_payload,
             recent_news, linkedin_snippet, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
        (
            email,
            payload["first_name"],
            payload["last_name"],
            payload["company"],
            payload["company_domain"],
            payload["title"],
            payload["city"],
            payload["country"],
            payload["timezone"],
            payload["source"] or "manual",
            payload["source_url"],
            raw_json,
            payload["recent_news"],
            payload["linkedin_snippet"],
            now,
        ),
    )


def _update_lead(lead_id: int, lead_data: dict, *, allow_status_change: bool) -> int:
    raw = lead_data.get("raw_payload")
    raw_json = None
    if raw is not None:
        raw_json = db.to_json(raw) if not isinstance(raw, str) else raw

    set_clauses: list[str] = []
    params: list = []
    for col in _LEAD_COLUMNS:
        if col not in lead_data:
            continue
        val = lead_data[col]
        if col == "raw_payload" and raw_json is not None:
            val = raw_json
        if val in (None, ""):
            # Don't overwrite existing non-empty values with empty
            continue
        set_clauses.append(f"{col} = ?")
        params.append(val)

    if not set_clauses:
        return lead_id

    params.append(lead_id)
    db.exec(
        f"UPDATE leads SET {', '.join(set_clauses)} WHERE id = ?",
        params,
    )
    return lead_id


def bulk_upsert(leads: list[dict]) -> dict:
    """Upsert a list of leads.

    Each upsert is wrapped in its own transaction (db.transaction()) so a bad
    row never poisons the whole batch. Returns {'inserted', 'updated',
    'skipped'}. The 'updated' count includes both email-update and
    dedupe-merge paths; we report it as 'updated' for simplicity.
    """
    inserted = 0
    updated = 0
    skipped = 0
    for lead in leads:
        email = _norm_email(lead.get("email", ""))
        try:
            existed = False
            if email:
                existed = _existing_by_email(email) is not None
            else:
                existed = _existing_by_key(dedupe_key(lead)) is not None
            with db.transaction() as _conn:  # noqa: F841
                lead_id = upsert_lead(lead)
            if lead_id is None:
                skipped += 1
            elif existed:
                updated += 1
            else:
                inserted += 1
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(f"bulk_upsert: failed for {email!r}: {exc}")
            skipped += 1
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def queue_for_campaign(lead_ids: list[int], campaign_id: int) -> int:
    """Mark the given leads as 'queued' and create a stub send_job per lead.

    The stub job has status='pending', scheduled_for = now+1h, and a NULL
    variant_id so the campaign materialize step can pick them up. We use
    the first configured mailbox as the from-mailbox; if none exists we skip
    the send_job insert (still flipping the lead status to 'queued' for
    downstream visibility).
    """
    if not lead_ids:
        return 0

    mailbox_row = db.query_one("SELECT id FROM mailboxes ORDER BY id LIMIT 1")
    mailbox_id = mailbox_row["id"] if mailbox_row else None

    scheduled_for = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
    now = _now()

    queued = 0
    for lead_id in lead_ids:
        lead_row = db.query_one("SELECT email FROM leads WHERE id = ?", (lead_id,))
        if not lead_row:
            continue
        if lead_row["email"] and is_suppressed(lead_row["email"]):
            log.info(f"queue_for_campaign: skipping suppressed lead {lead_id}")
            continue

        db.exec(
            "UPDATE leads SET status = 'queued' WHERE id = ? "
            "AND status IN ('new', 'enriched', 'ready')",
            (lead_id,),
        )
        # Confirm the row was actually flipped (status was in the allowed set)
        after = db.query_one("SELECT status FROM leads WHERE id = ?", (lead_id,))
        if not after or after["status"] != "queued":
            continue

        if mailbox_id is not None:
            db.exec(
                """INSERT OR IGNORE INTO send_jobs
                    (campaign_id, variant_id, lead_id, mailbox_id, provider,
                     subject, body, scheduled_for, status)
                   VALUES (?, NULL, ?, ?, 'gmail', '', '', ?, 'pending')""",
                (
                    campaign_id,
                    lead_id,
                    mailbox_id,
                    scheduled_for,
                ),
            )
        else:
            log.warning(
                f"queue_for_campaign: no mailbox configured; "
                f"lead {lead_id} marked queued but no send_job created"
            )
        queued += 1

    log.info(
        f"queue_for_campaign: {queued} leads queued for campaign {campaign_id} at {now}"
    )
    return queued
