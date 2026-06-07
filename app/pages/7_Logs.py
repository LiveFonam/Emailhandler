"""Logs page: filterable view of send_log, errors, scheduler output."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
from app.components.brand import header, page_setup
from src import db
from app import paths


def main():
    page_setup()
    header("Logs", "send_log + scheduler output")

    tab_sent, tab_run, tab_errors = st.tabs(["sent_log", "run.log", "errors"])

    with tab_sent:
        st.subheader("Recent sends")
        rows = db.query_all(
            """SELECT id, send_job_id, provider, message_id, sent_at,
                      compliance_ok, raw_mime_path
               FROM sent_log ORDER BY id DESC LIMIT 200"""
        )
        if rows:
            st.dataframe(pd.DataFrame([dict(r) for r in rows]), use_container_width=True, hide_index=True)
        else:
            st.info("No sends yet.")

    with tab_run:
        st.subheader("scheduler / app stdout (run.log)")
        log_path = paths.RUN_LOG_PATH
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="replace")
            # Last 5k chars
            st.code(content[-5000:], language="text")
        else:
            st.info(f"No run.log yet at {log_path}.")

    with tab_errors:
        st.subheader("Failed send jobs")
        rows = db.query_all(
            """SELECT id, campaign_id, lead_id, mailbox_id, scheduled_for, error
               FROM send_jobs WHERE status = 'failed' ORDER BY id DESC LIMIT 100"""
        )
        if rows:
            st.dataframe(pd.DataFrame([dict(r) for r in rows]), use_container_width=True, hide_index=True)
        else:
            st.info("No failures.")


if __name__ == "__main__":
    main()
