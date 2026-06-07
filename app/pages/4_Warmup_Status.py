"""Warmup Status page: per-mailbox daily cap, lifetime sent, ramp progress."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
from app.components.brand import header, page_setup
from src.analytics.warmup_metrics import per_mailbox_status, daily_send_history


def main():
    page_setup()
    header("Warmup Status", "Per-mailbox caps and send history")
    st.caption("Live data. Use the @st.fragment below to refresh every 5s.")

    @st.fragment(run_every=5)
    def _body():
        statuses = per_mailbox_status()
        if not statuses:
            st.info("No mailboxes configured. Add an account in Settings.")
            return

        for s in statuses:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(
                    f"{s['email']}",
                    f"{s['sent_today']} / {s['cap_today']}",
                    delta=f"lifetime: {s['lifetime_sent']}",
                )
            with col2:
                st.metric("Paused", "Yes" if s["paused"] else "No")
                if s["paused"]:
                    st.caption(s["paused_reason"])
            with col3:
                if s["warmup_started_at"]:
                    st.caption(f"Warmup started: {s['warmup_started_at'][:10]}")
            with col4:
                history = daily_send_history(s["id"], days=30)
                if history:
                    df = pd.DataFrame(history)
                    df["day"] = pd.to_datetime(df["day"])
                    fig = px.line(df, x="day", y="n", title=f"{s['email']} - last 30 days")
                    fig.update_layout(height=200, margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig, use_container_width=True)

    _body()


if __name__ == "__main__":
    main()
