"""Settings page.

Read-only display of config + .env state, with an OAuth re-consent button.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
from app.components.brand import header, page_setup
from src import db
from src.config import settings


def main():
    page_setup()
    header("Settings", "Sender profile, OAuth, accounts")

    # Physical address editor
    st.subheader("Sender profile")
    st.caption("CAN-SPAM requires a physical postal address in every commercial email.")
    addr = st.text_area(
        "Physical address (CAN-SPAM footer)",
        value=settings.sender.physical_address,
        placeholder="123 Main St, Toronto, ON M5V 1A1, Canada",
        height=80,
    )
    if st.button("Save physical address"):
        _update_yaml_field("sender_profile.physical_address", addr)
        st.success("Saved. Restart the app for changes to take effect." if not addr.strip() else
                   "Saved. Restart the app for changes to take effect.")

    st.divider()

    # Sender name + reply-to + signature
    name = st.text_input("Sender name", value=settings.sender.name)
    reply_to = st.text_input("Reply-to address", value=settings.sender.reply_to)
    signature = st.text_area("Signature (appended to replies)", value=settings.sender.signature, height=80)
    if st.button("Save sender info"):
        _update_yaml_field("sender_profile.name", name)
        _update_yaml_field("sender_profile.reply_to", reply_to)
        _update_yaml_field("sender_profile.signature", signature)
        st.success("Saved. Restart the app for changes to take effect.")

    st.divider()

    # OAuth re-consent
    st.subheader("OAuth / Gmail accounts")
    st.write(f"OAuth client secrets: `{Path_db('credentials.json')}`")
    st.write(f"Token (default): `{Path_db('token.json')}`")
    if st.button("Force re-consent (delete cached token)"):
        from src.gmail import oauth
        oauth.force_reconsent("default")
        st.success("Token deleted. Next OAuth call will re-prompt.")
    if st.button("Test connection (initialize OAuth)"):
        st.info("OAuth requires a browser. Use `python -m tools.oauth_init` from a terminal.")

    st.divider()

    # Mailboxes in the DB
    st.subheader("Outreach mailboxes (configured in DB)")
    rows = db.query_all("SELECT id, email, current_daily_cap, total_sent_today, total_sent_lifetime, paused_reason, warmup_started_at FROM mailboxes ORDER BY id")
    if rows:
        st.dataframe([dict(r) for r in rows], use_container_width=True)
    else:
        st.info("No mailboxes configured yet. Add outreach accounts via the Settings page (v1.1).")

    st.divider()
    st.subheader("Outreach rotation accounts (.env)")
    for a in settings.outreach_accounts:
        st.write(f"- {a}")
    if not settings.outreach_accounts:
        st.info("Set GMAIL_OUTREACH_ACCOUNT_1, _2, _3 in .env to enable rotation.")


def _update_yaml_field(dotted_key: str, value: str) -> None:
    """Naive YAML editor. For v1 we just rewrite the whole file. v1.1
    should use ruamel.yaml to preserve comments and formatting."""
    import yaml
    from app import paths
    p = paths.project_root() / "config.yaml"
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    parts = dotted_key.split(".")
    cur = cfg
    for k in parts[:-1]:
        cur = cur.setdefault(k, {})
    cur[parts[-1]] = value
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def Path_db(name: str) -> str:
    from app import paths
    return str(paths.DATA_DIR / name)


if __name__ == "__main__":
    main()
