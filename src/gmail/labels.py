"""Gmail label management: create the AI taxonomy, apply/remove per thread.

Label set is created once on first OAuth. apply_label and remove_label
are idempotent.
"""
from __future__ import annotations

from typing import Iterable

from src.gmail.client import build_service, with_backoff


# The complete AI label taxonomy. v1.1 may add more (e.g. snooze buckets).
AI_LABELS = [
    "AI/Triage-Pending",
    "AI/Action-Required",
    "AI/FYI",
    "AI/Newsletter",
    "AI/Promotion",
    "AI/Cold-Reply",
    "AI/Snoozed-24h",
    "AI/Snoozed-3d",
    "AI/Snoozed-1w",
    "AI/Auto-Replied",
]


# Map our internal category strings to the Gmail label name.
CATEGORY_TO_LABEL = {
    "action-required": "AI/Action-Required",
    "fyi": "AI/FYI",
    "newsletter": "AI/Newsletter",
    "promotion": "AI/Promotion",
    "cold-outreach-reply": "AI/Cold-Reply",
}


def _list_existing_labels(service) -> set[str]:
    @with_backoff
    def _call():
        return service.users().labels().list(userId="me").execute()
    resp = _call()
    return {lbl["name"] for lbl in (resp.get("labels") or [])}


def ensure_labels(account: str = "default") -> list[str]:
    """Create any missing AI labels. Returns the final list of created/existing."""
    service = build_service(account)
    existing = _list_existing_labels(service)
    created = []
    for name in AI_LABELS:
        if name in existing:
            continue
        @with_backoff
        def _create(n=name):
            return (
                service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": n,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
        try:
            _create()
            created.append(name)
        except Exception as e:
            import logging
            logging.getLogger("inbox_zero.gmail.labels").warning(
                f"Failed to create label {name}: {e}"
            )
    return created


def apply_label(
    thread_id: str,
    label_name: str,
    account: str = "default",
) -> None:
    service = build_service(account)
    @with_backoff
    def _get_or_create_id():
        existing = _list_existing_labels(service)
        if label_name in existing:
            # find id
            @with_backoff
            def _list():
                return service.users().labels().list(userId="me").execute()
            for lbl in (_list().get("labels") or []):
                if lbl["name"] == label_name:
                    return lbl["id"]
        @with_backoff
        def _create():
            return (
                service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": label_name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
        return _create()["id"]

    label_id = _get_or_create_id()

    @with_backoff
    def _modify():
        return (
            service.users()
            .threads()
            .modify(userId="me", id=thread_id, body={"addLabelIds": [label_id]})
            .execute()
        )
    _modify()


def remove_label(
    thread_id: str,
    label_name: str,
    account: str = "default",
) -> None:
    service = build_service(account)
    @with_backoff
    def _list():
        return service.users().labels().list(userId="me").execute()
    label_id = None
    for lbl in (_list().get("labels") or []):
        if lbl["name"] == label_name:
            label_id = lbl["id"]
            break
    if not label_id:
        return
    @with_backoff
    def _modify():
        return (
            service.users()
            .threads()
            .modify(userId="me", id=thread_id, body={"removeLabelIds": [label_id]})
            .execute()
        )
    _modify()


def apply_category(
    thread_id: str,
    category: str,
    account: str = "default",
) -> None:
    """Map a TriageResult.category to a label and apply it."""
    label = CATEGORY_TO_LABEL.get(category)
    if not label:
        return
    apply_label(thread_id, label, account=account)
