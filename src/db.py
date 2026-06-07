"""Sqlite connection + schema migrations + tiny query helpers.

WAL mode, Row factory, one shared connection per process for the scheduler,
per-request connections for Streamlit (each request is a thread).

We use stdlib sqlite3. The 12 tables are defined in SCHEMA_SQL; init_schema
is idempotent (CREATE IF NOT EXISTS).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from app import paths


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS threads (
    id              TEXT PRIMARY KEY,
    subject         TEXT,
    first_from      TEXT,
    last_from       TEXT,
    first_seen_at   TEXT,
    last_seen_at    TEXT,
    message_count   INTEGER,
    snippet         TEXT,
    UNIQUE(id)
);

CREATE TABLE IF NOT EXISTS triage (
    thread_id        TEXT PRIMARY KEY REFERENCES threads(id),
    category         TEXT NOT NULL,
    confidence       REAL,
    action           TEXT,
    summary_bullets  TEXT,
    action_items     TEXT,
    triaged_at       TEXT,
    triaged_by_model TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id       TEXT REFERENCES threads(id),
    gmail_draft_id  TEXT,
    body            TEXT,
    subject         TEXT,
    tone            TEXT,
    status          TEXT DEFAULT 'pending_review',
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS mailboxes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT UNIQUE NOT NULL,
    oauth_token_path    TEXT,
    provider            TEXT DEFAULT 'gmail',
    is_personal         INTEGER DEFAULT 0,
    warmup_started_at   TEXT,
    current_daily_cap   INTEGER DEFAULT 10,
    total_sent_today    INTEGER DEFAULT 0,
    total_sent_lifetime INTEGER DEFAULT 0,
    paused_reason       TEXT,
    last_sent_at        TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT UNIQUE NOT NULL,
    first_name      TEXT,
    last_name       TEXT,
    company         TEXT,
    company_domain  TEXT,
    title           TEXT,
    city            TEXT,
    country         TEXT,
    timezone        TEXT,
    source          TEXT,
    source_url      TEXT,
    raw_payload     TEXT,
    recent_news     TEXT,
    linkedin_snippet TEXT,
    enriched_at     TEXT,
    status          TEXT DEFAULT 'new',
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_company ON leads(company);

CREATE TABLE IF NOT EXISTS campaigns (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT NOT NULL,
    template_id           TEXT,
    from_mailbox_id       INTEGER REFERENCES mailboxes(id),
    provider              TEXT DEFAULT 'gmail',
    instantly_campaign_id TEXT,
    status                TEXT DEFAULT 'draft',
    daily_cap             INTEGER,
    frameworks            TEXT,
    use_variants          INTEGER DEFAULT 1,
    created_at            TEXT
);

CREATE TABLE IF NOT EXISTS campaign_variants (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id              INTEGER NOT NULL REFERENCES campaigns(id),
    lead_id                  INTEGER NOT NULL REFERENCES leads(id),
    framework                TEXT NOT NULL,
    subject                  TEXT NOT NULL,
    body                     TEXT NOT NULL,
    personalization_tokens   TEXT,
    created_at               TEXT,
    status                   TEXT DEFAULT 'generated',
    UNIQUE(campaign_id, lead_id, framework)
);
CREATE INDEX IF NOT EXISTS idx_variants_campaign ON campaign_variants(campaign_id, framework);
CREATE INDEX IF NOT EXISTS idx_variants_status ON campaign_variants(status);

CREATE TABLE IF NOT EXISTS send_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     INTEGER REFERENCES campaigns(id),
    variant_id      INTEGER REFERENCES campaign_variants(id),
    lead_id         INTEGER REFERENCES leads(id),
    mailbox_id      INTEGER REFERENCES mailboxes(id),
    provider        TEXT DEFAULT 'gmail',
    subject         TEXT,
    body            TEXT,
    scheduled_for   TEXT,
    status          TEXT DEFAULT 'pending',
    sent_at         TEXT,
    sent_message_id TEXT,
    error           TEXT,
    UNIQUE(campaign_id, variant_id, lead_id)
);
CREATE INDEX IF NOT EXISTS idx_sendjobs_status ON send_jobs(status, scheduled_for);

CREATE TABLE IF NOT EXISTS sent_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    send_job_id       INTEGER REFERENCES send_jobs(id),
    provider          TEXT,
    message_id        TEXT,
    sent_at           TEXT,
    raw_mime_path     TEXT,
    compliance_ok     INTEGER,
    compliance_report TEXT
);

CREATE TABLE IF NOT EXISTS suppression (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    email     TEXT UNIQUE NOT NULL,
    reason    TEXT,
    token     TEXT UNIQUE,
    added_at  TEXT
);

CREATE TABLE IF NOT EXISTS snoozes (
    thread_id   TEXT PRIMARY KEY REFERENCES threads(id),
    until_at    TEXT NOT NULL,
    bucket      TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS compliance_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at          TEXT,
    window_start    TEXT,
    window_end      TEXT,
    total_checked   INTEGER,
    passed          INTEGER,
    failed          INTEGER,
    failures_json   TEXT
);

-- Per-recipient outreach subscription record. The token is the single
-- source of truth: the SAME token is baked into both the List-Unsubscribe
-- header and the in-body URL. Persisting it here lets the unsubscribe
-- handler resolve the recipient's click. CRITICAL for CAN-SPAM.
CREATE TABLE IF NOT EXISTS outreach_subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL,
    token           TEXT UNIQUE NOT NULL,
    campaign_id     INTEGER,
    send_job_id     INTEGER,
    sent_at         TEXT,
    unsubscribed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outreach_sub_token ON outreach_subscriptions(token);
CREATE INDEX IF NOT EXISTS idx_outreach_sub_email ON outreach_subscriptions(email);
"""


_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """Per-thread connection. Each Streamlit request is a thread, so this
    gives us request-scoped connections automatically.

    CRITICAL: WAL alone is not enough. We also set:
      - busy_timeout=5000  : 5s retry window when scheduler+Streamlit collide
      - synchronous=NORMAL : 2-3x write throughput; tolerates a 100-byte
                             data loss on OS crash (acceptable for outreach)
      - wal_autocheckpoint=1000 : keep the WAL file from growing unbounded
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(
            str(paths.DB_PATH),
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA wal_autocheckpoint=1000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_schema() -> None:
    """Idempotent. Safe to call on every startup."""
    with transaction() as conn:
        conn.executescript(SCHEMA_SQL)


def exec(sql: str, params: Iterable[Any] = (), return_rowcount: bool = False) -> Optional[int]:
    """Execute a write. If return_rowcount=True, returns the number of
    rows affected (useful for atomic CAS guards like
    `UPDATE ... WHERE status='pending'`)."""
    with transaction() as conn:
        cur = conn.execute(sql, tuple(params))
        if return_rowcount:
            return cur.rowcount
        return None


def execmany(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    with transaction() as conn:
        conn.executemany(sql, [tuple(r) for r in rows])


def query_all(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    cur = get_conn().execute(sql, tuple(params))
    return cur.fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    cur = get_conn().execute(sql, tuple(params))
    return cur.fetchone()


def insert_and_return_id(sql: str, params: Iterable[Any] = ()) -> int:
    with transaction() as conn:
        cur = conn.execute(sql, tuple(params))
        return int(cur.lastrowid)


# --- json helpers (we store some columns as JSON) ---

def to_json(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def from_json(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


# --- bootstrap ---
init_schema()
