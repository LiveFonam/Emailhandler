"""Shared brand/header component for the Streamlit UI.

Lifts the simple header pattern from Evil's app/Home.py.
"""
import streamlit as st


BRAND_NAME = "inbox-zero-agent"


def header(title: str, subtitle: str = ""):
    st.markdown(
        f"""
        <div style="padding: 0.5rem 0 1rem 0; border-bottom: 1px solid #e6e6e6;
                    margin-bottom: 1rem;">
          <h2 style="margin: 0;">{title}</h2>
          <div style="color: #888; font-size: 0.9rem;">{BRAND_NAME}{' - ' + subtitle if subtitle else ''}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_setup(layout: str = "wide"):
    st.set_page_config(
        page_title=BRAND_NAME,
        page_icon=":inbox_tray:",
        layout=layout,
    )
