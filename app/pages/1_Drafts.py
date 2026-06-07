"""Drafts page: review, edit, send, or discard AI-generated drafts."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
from app.components.brand import header, page_setup
from src import db
from src.config import settings
from src.gmail.drafts import build_reply_mime, update_draft, delete_draft
from src.gmail.send import send_mime
from src.gmail.fetch import thread_to_digest, get_thread


def main():
    page_setup()
    header("Drafts", "AI-generated reply drafts")

    # Compliance gate
    if not settings.sender.has_physical_address:
        st.warning(
            "Physical address not set in config.yaml. The Send Now button is disabled. "
            "Set `sender_profile.physical_address` in config.yaml to enable sending."
        )

    rows = db.query_all(
        """SELECT id, thread_id, gmail_draft_id, subject, body, tone, status, created_at
           FROM drafts
           WHERE status IN ('pending_review', 'pushed_to_gmail')
           ORDER BY created_at DESC
           LIMIT 100"""
    )
    if not rows:
        st.info("No drafts yet. Open the Inbox page and click 'Draft reply' on a thread.")
        return

    for r in rows:
        with st.expander(f"{r['subject'][:80] or '(no subject)'} — tone: {r['tone']}"):
            st.caption(f"Draft id: {r['gmail_draft_id'] or '(not yet pushed)'}  |  Thread: {r['thread_id']}")
            new_body = st.text_area("Body", value=r["body"], key=f"body_{r['id']}", height=200)

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                if st.button("Save to Gmail", key=f"save_{r['id']}"):
                    _save_to_gmail(r, new_body)
            with c2:
                if st.button("Send now", key=f"send_{r['id']}", disabled=not settings.sender.has_physical_address):
                    _send_now(r, new_body)
            with c3:
                if st.button("Discard", key=f"discard_{r['id']}"):
                    _discard(r)
            with c4:
                if st.button("Re-draft with different tone", key=f"redraft_{r['id']}"):
                    st.info("Use the Inbox page Draft-reply button with the new tone.")


def _save_to_gmail(r, body: str) -> None:
    if not r["gmail_draft_id"]:
        st.warning("Draft not yet pushed to Gmail. Use 'Send now' to create + send.")
        return
    try:
        thread = get_thread(r["thread_id"], fmt="full")
        digest = thread_to_digest(thread)
        mime = build_reply_mime(digest, body, from_addr="", signature=settings.sender.signature)
        update_draft(r["gmail_draft_id"], mime)
        db.exec(
            "UPDATE drafts SET body = ?, status = 'pushed_to_gmail', updated_at = ? WHERE id = ?",
            (body, _now(), r["id"]),
        )
        st.success("Saved to Gmail.")
    except Exception as e:
        st.error(f"Save failed: {e}")


def _send_now(r, body: str) -> None:
    try:
        thread = get_thread(r["thread_id"], fmt="full")
        digest = thread_to_digest(thread)
        mime = build_reply_mime(digest, body, from_addr="", signature=settings.sender.signature)
        resp = send_mime(mime, thread_id=r["thread_id"])
        db.exec(
            "UPDATE drafts SET status = 'sent', updated_at = ? WHERE id = ?",
            (_now(), r["id"]),
        )
        st.success(f"Sent. Gmail message id: {resp.get('id', '')}")
    except Exception as e:
        st.error(f"Send failed: {e}")


def _discard(r) -> None:
    if r["gmail_draft_id"]:
        try:
            delete_draft(r["gmail_draft_id"])
        except Exception:
            pass
    db.exec("UPDATE drafts SET status = 'discarded' WHERE id = ?", (r["id"],))
    st.success("Discarded.")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
