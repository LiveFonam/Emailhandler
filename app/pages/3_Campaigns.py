"""Campaigns page: create campaigns, generate variants, materialize jobs, view status."""
from __future__ import annotations

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
from app.components.brand import header, page_setup
from src import db
from src.outreach.variants import generate_variants_for_campaign
from src.outreach.queue import build_send_jobs
from src.outreach.template import FRAMEWORKS


def main():
    page_setup()
    header("Campaigns", "Multi-variant AI outreach")

    tab_create, tab_list = st.tabs(["Create / run", "Existing campaigns"])

    with tab_create:
        st.subheader("Create a new campaign")
        with st.form("new_campaign"):
            name = st.text_input("Campaign name", placeholder="Q3 outreach - biotech VPs")
            fw_keys = list(FRAMEWORKS.keys())
            frameworks = st.multiselect(
                "Frameworks (each lead gets one variant per framework)",
                fw_keys,
                default=["question_hook", "value_prop"],
            )
            use_variants = st.checkbox("Use multi-variant generation", value=True)
            daily_cap = st.number_input("Daily cap per mailbox", min_value=1, max_value=500, value=15)
            submitted = st.form_submit_button("Create campaign")
            if submitted and name and frameworks:
                _create_campaign(name, frameworks, use_variants, daily_cap)
                st.success(f"Campaign '{name}' created. Add leads on the Leads page, then come back to generate variants.")

        st.divider()
        st.subheader("Generate variants for an existing campaign")
        campaigns = db.query_all("SELECT id, name, status FROM campaigns ORDER BY id DESC LIMIT 20")
        if not campaigns:
            st.info("Create a campaign first.")
        else:
            c = st.selectbox(
                "Campaign",
                campaigns,
                format_func=lambda r: f"#{r['id']} - {r['name']} ({r['status']})",
            )
            if st.button("Generate variants"):
                _generate(c["id"], list(FRAMEWORKS.keys()))
            if st.button("Materialize send jobs"):
                _materialize(c["id"])
            if st.button("Set status -> active"):
                db.exec("UPDATE campaigns SET status = 'active' WHERE id = ?", (c["id"],))

    with tab_list:
        st.subheader("All campaigns")
        rows = db.query_all("SELECT * FROM campaigns ORDER BY id DESC")
        if rows:
            st.dataframe(pd.DataFrame([dict(r) for r in rows]), use_container_width=True, hide_index=True)
        st.divider()
        st.subheader("Send jobs")
        jobs = db.query_all(
            """SELECT sj.id, sj.campaign_id, l.email, sj.status, sj.scheduled_for,
                      sj.sent_at, m.email AS mailbox
               FROM send_jobs sj
               JOIN leads l ON sj.lead_id = l.id
               JOIN mailboxes m ON sj.mailbox_id = m.id
               ORDER BY sj.id DESC LIMIT 200"""
        )
        if jobs:
            st.dataframe(pd.DataFrame([dict(r) for r in jobs]), use_container_width=True, hide_index=True)
        st.divider()
        st.subheader("Generated variants")
        variants = db.query_all(
            """SELECT v.id, v.campaign_id, l.email, v.framework, v.subject,
                      substr(v.body, 1, 80) AS body_preview, v.status
               FROM campaign_variants v
               JOIN leads l ON v.lead_id = l.id
               ORDER BY v.id DESC LIMIT 100"""
        )
        if variants:
            st.dataframe(pd.DataFrame([dict(r) for r in variants]), use_container_width=True, hide_index=True)


def _create_campaign(name: str, frameworks: list[str], use_variants: bool, daily_cap: int) -> None:
    from datetime import datetime, timezone
    db.exec(
        """INSERT INTO campaigns (name, template_id, from_mailbox_id, provider, status, daily_cap, frameworks, use_variants, created_at)
           VALUES (?, NULL, NULL, 'gmail', 'draft', ?, ?, ?, ?)""",
        (name, daily_cap, json.dumps(frameworks), 1 if use_variants else 0, datetime.now(timezone.utc).isoformat()),
    )


def _generate(campaign_id: int, frameworks: list[str]) -> None:
    with st.spinner(f"Generating variants for campaign {campaign_id}..."):
        counts = generate_variants_for_campaign(campaign_id, frameworks)
    st.success(f"Done. Generated: {counts}")


def _materialize(campaign_id: int) -> None:
    n = build_send_jobs(campaign_id)
    st.success(f"Inserted {n} send jobs.")


if __name__ == "__main__":
    main()
