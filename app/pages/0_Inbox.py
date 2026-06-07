"""Inbox triage page.

Shows triaged threads by category, with a per-row "Draft reply" button
that creates a Gmail draft.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
from app.components.brand import header, page_setup
from src import db
from src.config import settings
from src.schemas import ReplyDraft
from src.triage.triage import draft_reply
from src.gmail.drafts import build_reply_mime, create_draft
from src.gmail.fetch import thread_to_digest, get_thread
from datetime import datetime, timezone


def main():
    page_setup()
    header("Inbox", "Triaged threads")

    # Category filter
    cat_options = ["all", "action-required", "fyi", "newsletter", "promotion", "cold-outreach-reply"]
    cat = st.selectbox("Category", cat_options, index=1)

    if cat == "all":
        rows = db.query_all(
            """SELECT t.id, t.subject, t.first_from, t.message_count,
                      t.last_seen_at, tr.category, tr.confidence, tr.action,
                      tr.summary_bullets
               FROM threads t
               JOIN triage tr ON t.id = tr.thread_id
               ORDER BY tr.triaged_at DESC
               LIMIT 200"""
        )
    else:
        rows = db.query_all(
            """SELECT t.id, t.subject, t.first_from, t.message_count,
                      t.last_seen_at, tr.category, tr.confidence, tr.action,
                      tr.summary_bullets
               FROM threads t
               JOIN triage tr ON t.id = tr.thread_id
               WHERE tr.category = ?
               ORDER BY tr.triaged_at DESC
               LIMIT 200""",
            (cat,),
        )

    if not rows:
        st.info("Nothing in this category. Run the backfill or wait for new mail.")
        return

    st.caption(f"{len(rows)} threads")

    tone = st.select_slider("Tone for new drafts", options=["warm", "concise", "formal", "playful"], value="warm")

    for r in rows:
        with st.expander(f"[{r['category']}] {r['subject'][:80] or '(no subject)'} — from {r['first_from'][:40]}"):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            with c1:
                bullets = db.from_json(r["summary_bullets"]) or []
                if bullets:
                    st.markdown("**Summary:**")
                    for b in bullets:
                        st.write(f"- {b}")
                if r["action"]:
                    st.write(f"**Action:** {r['action']}")
                st.caption(f"Confidence: {r['confidence']:.2f}  |  Messages: {r['message_count']}  |  Last seen: {r['last_seen_at']}")
            with c2:
                if st.button("Draft reply", key=f"draft_{r['id']}"):
                    _draft_for_thread(r["id"], tone)
            with c3:
                if st.button("Archive", key=f"archive_{r['id']}"):
                    _archive(r["id"])
            with c4:
                if st.button("Snooze 24h", key=f"snooze_{r['id']}"):
                    _snooze(r["id"], "24h")


def _draft_for_thread(thread_id: str, tone: str) -> None:
    try:
        thread = get_thread(thread_id, fmt="full")
        digest = thread_to_digest(thread)
        draft: ReplyDraft = draft_reply(digest, tone=tone, sender_name=settings.sender.name)
        mime = build_reply_mime(
            digest,
            draft.body,
            from_addr="",  # User will set the from in Gmail
            signature=settings.sender.signature,
        )
        draft_id = create_draft(thread_id, mime)
        now = datetime.now(timezone.utc).isoformat()
        db.exec(
            """INSERT INTO drafts (thread_id, gmail_draft_id, body, subject, tone, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pushed_to_gmail', ?, ?)""",
            (thread_id, draft_id, draft.body, draft.subject, tone, now, now),
        )
        st.success(f"Draft created: {draft.subject}")
    except Exception as e:
        st.error(f"Draft failed: {e}")


def _archive(thread_id: str) -> None:
    try:
        from src.gmail.modify import archive as gmail_archive
        gmail_archive(thread_id)
        st.success("Archived.")
    except Exception as e:
        st.error(f"Archive failed: {e}")


def _snooze(thread_id: str, bucket: str) -> None:
    try:
        from src.gmail.modify import snooze as gmail_snooze
        from datetime import datetime, timezone, timedelta
        delta = {"24h": timedelta(hours=24), "3d": timedelta(days=3), "1w": timedelta(weeks=1)}[bucket]
        until = gmail_snooze(thread_id, bucket)
        db.exec(
            "INSERT OR REPLACE INTO snoozes (thread_id, until_at, bucket, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, until.isoformat(), f"AI/Snoozed-{bucket}", datetime.now(timezone.utc).isoformat()),
        )
        st.success(f"Snoozed until {until.isoformat()}")
    except Exception as e:
        st.error(f"Snooze failed: {e}")


if __name__ == "__main__":
    main()
