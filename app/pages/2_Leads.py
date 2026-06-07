"""Leads page: scrape, dedupe, enrich, queue.

v1 lead sources: Google Custom Search JSON API + Google Maps Places.
Apollo/Hunter/company_site sources are stubbed for v1.1.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
from app.components.brand import header, page_setup
from src import db
from src.config import settings
from src.leads.sources import google_cse, gmaps
from src.leads.store import bulk_upsert, queue_for_campaign


# Source label -> (callable, whether it is a stub).
_SOURCES: dict[str, tuple[str, bool]] = {
    "google_cse": ("Google Custom Search", False),
    "gmaps": ("Google Maps Places", False),
    "(stub) apollo": ("Apollo", True),
    "(stub) hunter": ("Hunter.io", True),
    "(stub) company_site": ("Company site crawl", True),
}


def _run_scrape(source: str, query: str, max_results: int) -> list[dict]:
    """Dispatch to the correct source module. Returns [] on stub sources
    or when the source function itself returns [].
    """
    if source == "google_cse":
        return google_cse.search(query, max_results)
    if source == "gmaps":
        return gmaps.search(query, max_results)
    return []


def _scrape_source_warning(source: str) -> str | None:
    """Return a human-readable config error if the chosen source will
    silently return []. None means we expect a real response.
    """
    if source == "google_cse":
        if not settings.google_cse_key or not settings.google_cse_id:
            return (
                "Google Custom Search isn't configured. Set `GOOGLE_CSE_KEY` "
                "and `GOOGLE_CSE_ID` in `.env` (or on the Settings page). "
                "Free tier is 100 queries/day."
            )
    if source == "gmaps":
        import os
        if not os.getenv("GOOGLE_MAPS_API_KEY", ""):
            return (
                "Google Maps isn't configured. Set `GOOGLE_MAPS_API_KEY` in "
                "`.env` and enable the Places API for the project. "
                "The same key as CSE works if Places is enabled."
            )
    return None


def _render_scrape_tab() -> None:
    st.subheader("Scrape new leads")
    st.caption("v1 sources: Google Custom Search (free, 100/day) + Google Maps Places")

    query = st.text_input("Search query", placeholder="VP Engineering biotech Toronto")
    source = st.selectbox(
        "Source",
        list(_SOURCES.keys()),
        format_func=lambda k: _SOURCES[k][0],
    )
    n = st.number_input("Max results", min_value=1, max_value=100, value=20)

    if st.button("Run scrape"):
        label, is_stub = _SOURCES[source]
        if is_stub:
            st.info(f"{label} is coming in v1.1. For now, use the CSV import tab or the CLI.")
            st.code(
                "python -m tools.scrape --source %s --query '%s' --max %d" % (source, query, n),
                language="bash",
            )
            return

        if not query.strip():
            st.warning("Enter a search query first.")
            return

        warn = _scrape_source_warning(source)
        if warn:
            st.warning(warn)
            # Still let the user click through so they can see the empty
            # result is from missing config, not a real "no results".

        with st.spinner(f"Scraping {label} for '{query}'..."):
            results = _run_scrape(source, query, int(n))

        if not results:
            st.warning(
                f"No results from {label}. This usually means the API key is missing "
                f"or the query returned zero hits. Check the Settings page."
            )
            return

        # Stash for the Save button click below
        st.session_state["_scrape_results"] = results
        st.session_state["_scrape_source"] = source
        st.success(f"Found {len(results)} candidate leads. Preview below; click Save to persist.")

    # Render the preview + Save button if a scrape just ran in this session
    results = st.session_state.get("_scrape_results")
    if results:
        st.divider()
        st.subheader("Preview")
        preview_df = pd.DataFrame(results[:20])
        st.dataframe(preview_df, use_container_width=True, hide_index=True)
        if len(results) > 20:
            st.caption(f"Showing first 20 of {len(results)} results.")

        save_col, clear_col = st.columns([1, 4])
        with save_col:
            if st.button("Save to database"):
                with st.spinner("Dedupe + upsert..."):
                    counts = bulk_upsert(results)
                st.success(
                    f"Saved. Inserted: {counts['inserted']}  |  "
                    f"Updated: {counts['updated']}  |  "
                    f"Skipped: {counts['skipped']}"
                )
                st.session_state.pop("_scrape_results", None)
                st.session_state.pop("_scrape_source", None)
                st.rerun()
        with clear_col:
            if st.button("Discard preview"):
                st.session_state.pop("_scrape_results", None)
                st.session_state.pop("_scrape_source", None)
                st.rerun()


def _render_existing_leads_tab() -> None:
    st.subheader("Existing leads")
    rows = db.query_all(
        """SELECT id, email, first_name, last_name, company, title, city, country,
                  source, status, created_at
           FROM leads
           ORDER BY created_at DESC
           LIMIT 500"""
    )
    if not rows:
        st.info("No leads yet. Scrape or import some first.")
        return
    df = pd.DataFrame([dict(r) for r in rows])
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"{len(df)} leads")

    st.divider()
    st.subheader("Queue for a campaign")
    ids = st.multiselect("Select leads to queue", df["id"].tolist())

    draft_campaigns = db.query_all(
        "SELECT id, name, status FROM campaigns WHERE status = 'draft' ORDER BY id DESC"
    )
    if not draft_campaigns:
        st.info("No draft campaigns. Create one on the Campaigns page first.")
    else:
        camp = st.selectbox(
            "Campaign (draft only)",
            draft_campaigns,
            format_func=lambda r: f"#{r['id']} - {r['name']}",
            key="queue_campaign_pick",
        )
        if ids and st.button("Add to campaign", key="add_to_campaign_btn"):
            try:
                queued = queue_for_campaign(
                    [int(i) for i in ids], int(camp["id"])
                )
                st.success(f"Queued {queued} leads for campaign #{camp['id']} ({camp['name']}).")
            except ValueError as e:
                st.error(str(e))

    st.divider()
    st.subheader("Delete selected leads")
    delete_ids = st.multiselect(
        "Select leads to delete (permanent)", df["id"].tolist(), key="delete_ids"
    )
    confirm = st.checkbox(
        f"I understand this permanently deletes {len(delete_ids) if delete_ids else 0} lead(s).",
        value=False,
        key="delete_confirm",
    )
    if st.button("Delete selected", disabled=not (delete_ids and confirm)):
        for lid in delete_ids:
            db.exec("DELETE FROM leads WHERE id = ?", (int(lid),))
        st.success(f"Deleted {len(delete_ids)} leads.")
        st.rerun()


def _render_csv_import_tab() -> None:
    st.subheader("CSV import")
    st.caption(
        "Columns: email, first_name, last_name, company, company_domain, "
        "title, city, country. Optional extra columns are ignored."
    )
    uploaded = st.file_uploader("Upload CSV", type=["csv"], key="csv_upload")
    if uploaded is None:
        st.info("Upload a CSV to preview it here.")
        return

    try:
        df = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Failed to parse CSV: {e}")
        return

    required = ["email", "first_name", "last_name", "company", "title", "city", "country"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Missing required columns: {', '.join(missing)}")
        return

    st.caption(f"{len(df)} rows. Preview:")
    st.dataframe(df.head(20), use_container_width=True, hide_index=True)

    if st.button("Import to database"):
        rows = df.to_dict(orient="records")
        # Coerce NaN -> "" so the Lead schema's _to_str() handles it cleanly.
        for r in rows:
            for k, v in list(r.items()):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    r[k] = ""
            r.setdefault("source", "csv")
            r.setdefault("source_url", "")
        with st.spinner("Dedupe + upsert..."):
            counts = bulk_upsert(rows)
        st.success(
            f"Imported. Inserted: {counts['inserted']}  |  "
            f"Updated: {counts['updated']}  |  "
            f"Skipped: {counts['skipped']}"
        )


def _render_suppression_tab() -> None:
    st.subheader("Suppression list")
    st.caption(
        "Emails on this list are skipped by every send path. See the "
        "Compliance page for the full management UI (add/remove, audit, "
        "CAN-SPAM headers)."
    )
    rows = db.query_all(
        "SELECT id, email, reason, added_at FROM suppression ORDER BY added_at DESC LIMIT 200"
    )
    if rows:
        st.dataframe(
            pd.DataFrame([dict(r) for r in rows]),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"{len(rows)} suppressed emails shown (capped at 200).")
    else:
        st.info("No suppressions yet.")


def main():
    page_setup()
    header("Leads", "Scrape, dedupe, enrich, queue for outreach")

    tab_scrape, tab_leads, tab_csv, tab_suppress = st.tabs([
        "Scrape new", "Existing leads", "CSV import", "Suppression",
    ])

    with tab_scrape:
        _render_scrape_tab()
    with tab_leads:
        _render_existing_leads_tab()
    with tab_csv:
        _render_csv_import_tab()
    with tab_suppress:
        _render_suppression_tab()


if __name__ == "__main__":
    main()
