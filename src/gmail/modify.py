"""Modify thread state: archive, trash, mark read/unread, snooze.

Snooze: apply the bucket label, remove from Inbox; the scheduler restores
the thread to Inbox at the until_at timestamp.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from src.gmail.client import build_service, with_backoff
from src.gmail.labels import apply_label, remove_label


def archive(thread_id: str, account: str = "default") -> None:
    service = build_service(account)
    @with_backoff
    def _modify():
        return (
            service.users()
            .threads()
            .modify(
                userId="me",
                id=thread_id,
                body={"removeLabelIds": ["INBOX"]},
            )
            .execute()
        )
    _modify()


def trash(thread_id: str, account: str = "default") -> None:
    service = build_service(account)
    @with_backoff
    def _modify():
        return (
            service.users()
            .threads()
            .modify(
                userId="me",
                id=thread_id,
                body={"addLabelIds": ["TRASH"]},
            )
            .execute()
        )
    _modify()


def mark_read(thread_id: str, account: str = "default") -> None:
    service = build_service(account)
    @with_backoff
    def _modify():
        return (
            service.users()
            .threads()
            .modify(
                userId="me",
                id=thread_id,
                body={"removeLabelIds": ["UNREAD"]},
            )
            .execute()
        )
    _modify()


SNOOZE_BUCKETS = {
    "24h": ("AI/Snoozed-24h", dt.timedelta(hours=24)),
    "3d": ("AI/Snoozed-3d", dt.timedelta(days=3)),
    "1w": ("AI/Snoozed-1w", dt.timedelta(weeks=1)),
}


def snooze(
    thread_id: str,
    bucket: Literal["24h", "3d", "1w"],
    account: str = "default",
) -> dt.datetime:
    """Move a thread out of Inbox; the scheduler restores it at the until_at."""
    label_name, delta = SNOOZE_BUCKETS[bucket]
    apply_label(thread_id, label_name, account=account)
    archive(thread_id, account=account)
    until = dt.datetime.now(dt.timezone.utc) + delta
    return until
