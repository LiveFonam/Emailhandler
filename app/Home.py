"""Streamlit Home page: quick stats, system health, navigation entry point.

The single entry point that launches when you do `streamlit run app/Home.py`.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from app.components.brand import (
    header,
    metric_card,
    metric_row,
    page_setup,
    section_divider,
    sidebar_brand,
    status_pill,
)
from src import db
from src.config import settings


def _sched_status() -> tuple[str, str]:
    """(kind, label) for the scheduler health indicator."""
    from app import paths
    p = paths.RUN_LOG_PATH
    if not p.exists():
        return ("warn", "scheduler: no run.log")
    age_s = (datetime.now(timezone.utc).timestamp() - p.stat().st_mtime)
    if age_s < 600:
        return ("ok", "scheduler: live")
    if age_s < 3600:
        return ("warn", f"scheduler: idle {int(age_s) // 60}m")
    return ("error", f"scheduler: stale {int(age_s) // 3600}h")


def _last_activity() -> str:
    row = db.query_one("SELECT MAX(triaged_at) AS t FROM triage")
    if not row or not row["t"]:
        return "never"
    try:
        dt = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        mins = int(delta.total_seconds() // 60)
        if mins < 1:
            return "just now"
        if mins < 60:
            return f"{mins}m ago"
        if mins < 1440:
            return f"{mins // 60}h ago"
        return f"{mins // 1440}d ago"
    except Exception:
        return row["t"]


def _m3_status_label() -> tuple[str, str]:
    try:
        from src.llm_compat import m3_status
        s = m3_status()
    except Exception:
        return ("warn", "fallback")
    if not s:
        return ("warn", "fallback")
    if s.get("ready"):
        return ("ok", s.get("label", "M3 ready"))
    if s.get("offline"):
        return ("error", "Ollama offline")
    return ("warn", s.get("label", "fallback"))


def main():
    page_setup(layout=settings.streamlit.layout)

    with st.sidebar:
        sidebar_brand()

    header("Overview", "Last activity " + _last_activity())

    threads_n = db.query_one("SELECT COUNT(*) AS c FROM threads")["c"]
    triaged_n = db.query_one("SELECT COUNT(*) AS c FROM triage")["c"]
    leads_n = db.query_one("SELECT COUNT(*) AS c FROM leads")["c"]
    sent_n = db.query_one(
        "SELECT COUNT(*) AS c FROM send_jobs WHERE status='sent'"
    )["c"]

    cards = [
        metric_card("Threads seen", f"{threads_n}", help="All threads Gmail has surfaced"),
        metric_card("Triaged",       f"{triaged_n}", help="Threads with a category label"),
        metric_card("Leads",         f"{leads_n}",   help="Outreach prospects on file"),
        metric_card("Outreach sent", f"{sent_n}", accent=(sent_n > 0),
                    help="Send jobs that completed"),
    ]
    st.markdown(metric_row(cards), unsafe_allow_html=True)

    st.subheader("Triage breakdown")
    rows = db.query_all(
        "SELECT category, COUNT(*) AS c FROM triage GROUP BY category ORDER BY c DESC"
    )
    if rows:
        for r in rows:
            kind = {
                "action-required": "warn",
                "fyi": "info",
                "newsletter": "neutral",
                "promotion": "neutral",
                "cold-outreach-reply": "accent",
            }.get(r["category"], "neutral")
            st.markdown(
                status_pill(kind, r["category"]) + f"  &nbsp; {r['c']}",
                unsafe_allow_html=True,
            )
    else:
        st.info(
            "No triage yet. Run `python -m tools.backfill_inbox --max 342` to triage your inbox."
        )

    st.markdown(section_divider(), unsafe_allow_html=True)

    st.subheader("System")
    sched_kind, sched_label = _sched_status()
    m3_kind, m3_label = _m3_status_label()

    health_cards = [
        metric_card("Inference backend", m3_label,
                    help="Local M3 via Ollama. Falls back gracefully if unavailable."),
        metric_card("Scheduler", sched_label,
                    help="data/run.log mtime drives this indicator."),
        metric_card("Outreach accounts", f"{len(settings.outreach_accounts)}",
                    help="GMAIL_OUTREACH_ACCOUNT_1..3 in .env"),
    ]
    st.markdown(metric_row(health_cards), unsafe_allow_html=True)

    st.markdown(section_divider(), unsafe_allow_html=True)

    if not settings.sender.has_physical_address:
        st.markdown(
            metric_card(
                "Compliance",
                "address missing",
                help=("CAN-SPAM: physical postal address is required in every "
                      "commercial email. Add `sender_profile.physical_address` in config.yaml."),
            ),
            unsafe_allow_html=True,
        )
        st.warning("Send Now is disabled until the physical address is set in config.yaml.")

    accts = settings.outreach_accounts
    if accts:
        st.subheader("Outreach rotation")
        for a in accts:
            st.markdown(status_pill("info", a), unsafe_allow_html=True)
    else:
        st.caption("No outreach accounts configured. Set GMAIL_OUTREACH_ACCOUNT_1 in .env.")


if __name__ == "__main__":
    main()
