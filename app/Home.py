"""Streamlit Home page: quick stats + navigation.

The single entry point that launches when you do `streamlit run app/Home.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from app.components.brand import header, page_setup
from src import db
from src.config import settings
from src.llm_compat import claude_spend_usd, last_backend


def main():
    page_setup(layout=settings.streamlit.layout)
    header("inbox-zero-agent", "Personal Gmail AI + outreach")

    # Quick stats from sqlite
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        n = db.query_one("SELECT COUNT(*) AS c FROM threads")["c"]
        st.metric("Threads seen", n)
    with col2:
        n = db.query_one("SELECT COUNT(*) AS c FROM triage")["c"]
        st.metric("Triaged", n)
    with col3:
        n = db.query_one("SELECT COUNT(*) AS c FROM leads")["c"]
        st.metric("Leads", n)
    with col4:
        n = db.query_one("SELECT COUNT(*) AS c FROM send_jobs WHERE status='sent'")["c"]
        st.metric("Outreach sent", n)

    st.divider()

    # Triage breakdown
    st.subheader("Triage breakdown")
    rows = db.query_all("SELECT category, COUNT(*) AS c FROM triage GROUP BY category ORDER BY c DESC")
    if rows:
        for r in rows:
            st.write(f"- **{r['category']}**: {r['c']}")
    else:
        st.info("No triage yet. Run `python -m tools.backfill_inbox --max 342` to triage your inbox.")

    st.divider()

    # LLM router health
    st.subheader("LLM router health")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Claude spend (USD)", f"${claude_spend_usd():.4f}")
    with col2:
        st.metric("Last backend", last_backend() or "(none)")
    with col3:
        # Show whether the sibling is wired up
        try:
            from src.llm_compat import _evil_llm
            st.success("Evil llm.py loaded")
        except Exception as e:
            st.error(f"Evil llm.py missing: {e}")

    st.divider()

    # Compliance gate
    st.subheader("Compliance")
    if settings.sender.has_physical_address:
        st.success("Physical address is set in config.yaml")
    else:
        st.warning(
            "Physical address NOT set in config.yaml. The Send Now button "
            "is disabled until you fill `sender_profile.physical_address` in "
            "config.yaml. CAN-SPAM fines are $53,088 per non-compliant email."
        )

    # Outreach accounts
    accts = settings.outreach_accounts
    if accts:
        st.write("Outreach rotation accounts:")
        for a in accts:
            st.write(f"- {a}")
    else:
        st.info("No outreach accounts configured. Set GMAIL_OUTREACH_ACCOUNT_1 in .env to enable rotation.")


if __name__ == "__main__":
    main()
