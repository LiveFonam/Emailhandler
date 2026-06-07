"""Suppression list. Checked before every send, and updated on
unsubscribe, bounce, complaint, or manual add.
"""
from __future__ import annotations

import datetime as dt
import secrets

from src import db
from src.outreach.compliance import generate_unsubscribe_token


def is_suppressed(email: str) -> bool:
    if not email:
        return True
    row = db.query_one("SELECT id FROM suppression WHERE email = ?", (email.lower(),))
    return row is not None


def add_suppression(email: str, reason: str, token: str | None = None) -> None:
    if not email:
        return
    if is_suppressed(email):
        return
    db.exec(
        """INSERT OR IGNORE INTO suppression (email, reason, token, added_at)
           VALUES (?, ?, ?, ?)""",
        (
            email.lower(),
            reason,
            token or generate_unsubscribe_token(),
            dt.datetime.now(dt.timezone.utc).isoformat(),
        ),
    )


def remove_suppression(email: str) -> bool:
    if not email:
        return False
    cur = db.get_conn().execute(
        "DELETE FROM suppression WHERE email = ?", (email.lower(),)
    )
    db.get_conn().commit()
    return cur.rowcount > 0


def lookup_by_token(token: str) -> str | None:
    if not token:
        return None
    row = db.query_one("SELECT email FROM suppression WHERE token = ?", (token,))
    return row["email"] if row else None
