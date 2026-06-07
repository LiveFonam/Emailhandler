"""Compliance page: suppression list, audit results, re-run audit."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
from app.components.brand import header, page_setup
from src import db
from src.outreach.suppress import add_suppression, remove_suppression
from src.analytics.compliance_audit import audit_last_n_days


def main():
    page_setup()
    header("Compliance", "Suppression list, audit history, CAN-SPAM")

    tab_suppress, tab_audit, tab_headers = st.tabs(["Suppression", "Audit", "Required headers"])

    with tab_suppress:
        st.subheader("Suppression list")
        rows = db.query_all(
            "SELECT id, email, reason, added_at FROM suppression ORDER BY added_at DESC LIMIT 500"
        )
        if rows:
            st.dataframe(pd.DataFrame([dict(r) for r in rows]), use_container_width=True, hide_index=True)
        else:
            st.info("No suppressions yet.")

        st.divider()
        st.subheader("Add a suppression")
        with st.form("add_supp"):
            email = st.text_input("Email")
            reason = st.selectbox("Reason", ["manual", "unsubscribe", "bounce", "complaint"])
            if st.form_submit_button("Add"):
                if email.strip():
                    add_suppression(email.strip(), reason)
                    st.success(f"Added {email} to suppression list.")

        st.divider()
        st.subheader("Remove a suppression")
        rem = st.text_input("Email to remove", key="rem")
        if st.button("Remove"):
            if rem.strip():
                ok = remove_suppression(rem.strip())
                st.success(f"Removed: {ok}")

    with tab_audit:
        st.subheader("Compliance audit history")
        rows = db.query_all(
            """SELECT id, ran_at, window_start, window_end, total_checked, passed, failed
               FROM compliance_audit ORDER BY ran_at DESC LIMIT 50"""
        )
        if rows:
            st.dataframe(pd.DataFrame([dict(r) for r in rows]), use_container_width=True, hide_index=True)
        else:
            st.info("No audits yet. Run one below.")

        st.divider()
        st.subheader("Run a fresh audit")
        days = st.number_input("Window (days)", min_value=1, max_value=365, value=30)
        if st.button("Run audit now"):
            with st.spinner("Scanning sent_log..."):
                result = audit_last_n_days(int(days))
            st.success(
                f"Total: {result['total']}  |  Passed: {result['passed']}  |  "
                f"Failed: {result['failed']}"
            )
            if result["failures"]:
                st.warning("Failures:")
                st.dataframe(pd.DataFrame(result["failures"]), use_container_width=True)

    with tab_headers:
        st.subheader("Required CAN-SPAM headers (auto-injected)")
        st.caption("If any of these are missing, the send path refuses to send. $53,088/email fine.")
        st.markdown(
            """
            - `List-Unsubscribe: <https://...>, <mailto:...>`
            - `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
            - `X-Entity-Ref-ID: <uuid>`
            - `Precedence: bulk`
            - Physical postal address in the body footer
            """
        )
        from src.config import settings
        if not settings.sender.has_physical_address:
            st.error(
                "Physical address not set in config.yaml. "
                "Set `sender_profile.physical_address` in the Settings page."
            )
        else:
            st.success(f"Physical address: {settings.sender.physical_address}")


if __name__ == "__main__":
    main()
