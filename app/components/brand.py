"""Brand, theme, and shared UI primitives for the inbox-zero-agent Streamlit UI.

Theme: "Ink + Amber"
  - Background: near-white ink (light) or midnight blue (dark)
  - Single accent: warm amber for primary actions and the brand mark
  - Two type families: system sans for UI, system mono for numerics
  - No rainbow badges, no gradient hero, no icon soup
  - Animations: CSS-only fade-in on page load, hover lift on cards,
    smooth sidebar transitions, animated metric counters

This file is the single source of truth for the UI. Pages should NOT
inline custom CSS; they should call page_setup() and the helpers below.

The look is intentionally distinct from the sibling research project,
which uses a forest-green academic palette.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st


BRAND_NAME = "inbox-zero-agent"
BRAND_TAGLINE = "Personal Gmail AI + outreach"
BRAND_VERSION = "v0.2"


_THEME_CSS = """
<style>
:root {
  --ink-bg:          #FAFAF9;
  --ink-bg-raised:   #FFFFFF;
  --ink-bg-sunken:   #F4F4F2;
  --ink-border:      #E7E5E4;
  --ink-border-strong: #D6D3D1;
  --ink-fg:          #1C1917;
  --ink-fg-muted:    #57534E;
  --ink-fg-subtle:   #A8A29E;
  --ink-accent:      #B45309;
  --ink-accent-soft: #FEF3C7;
  --ink-accent-fg:   #FFFFFF;
  --ink-success:     #15803D;
  --ink-warn:        #B45309;
  --ink-error:       #B91C1C;
  --ink-info:        #1D4ED8;
  --ink-shadow:      0 1px 2px rgba(28,25,23,0.04), 0 4px 12px rgba(28,25,23,0.04);
  --ink-shadow-lg:   0 8px 32px rgba(28,25,23,0.10);
  --ink-radius-sm:   6px;
  --ink-radius-md:   10px;
  --ink-radius-lg:   14px;
  --ink-mono:        ui-monospace, "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace;
  --ink-sans:        -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI",
                     Roboto, "Helvetica Neue", Arial, sans-serif;
  --ink-ease:        cubic-bezier(0.16, 1, 0.3, 1);
}

@media (prefers-color-scheme: dark) {
  :root {
    --ink-bg:          #0C0A09;
    --ink-bg-raised:   #1C1917;
    --ink-bg-sunken:   #050403;
    --ink-border:      #292524;
    --ink-border-strong: #44403C;
    --ink-fg:          #FAFAF9;
    --ink-fg-muted:    #A8A29E;
    --ink-fg-subtle:   #78716C;
    --ink-accent:      #F59E0B;
    --ink-accent-soft: #451A03;
    --ink-accent-fg:   #0C0A09;
    --ink-success:     #4ADE80;
    --ink-warn:        #FBBF24;
    --ink-error:       #F87171;
    --ink-info:        #60A5FA;
    --ink-shadow:      0 1px 2px rgba(0,0,0,0.4), 0 4px 12px rgba(0,0,0,0.3);
    --ink-shadow-lg:   0 8px 32px rgba(0,0,0,0.5);
  }
}

html, body, [class*="css"]  {
  font-family: var(--ink-sans);
  font-feature-settings: "ss01", "cv11", "tnum";
  -webkit-font-smoothing: antialiased;
  letter-spacing: -0.005em;
}
.stApp { background: var(--ink-bg); }
h1, h2, h3, h4 { font-weight: 600; letter-spacing: -0.02em; color: var(--ink-fg); }
h1 { font-size: 1.75rem; line-height: 1.2; }
h2 { font-size: 1.375rem; line-height: 1.25; }
h3 { font-size: 1.125rem; line-height: 1.3; }
code, pre, .stCode { font-family: var(--ink-mono); }
p, li, label, .stMarkdown { color: var(--ink-fg); }
.stCaption, caption, small { color: var(--ink-fg-muted); }

[data-testid="stSidebar"] {
  background: var(--ink-bg-raised);
  border-right: 1px solid var(--ink-border);
}
[data-testid="stSidebar"] .stMarkdown h1,
[data-testid="stSidebar"] .stMarkdown h2,
[data-testid="stSidebar"] .stMarkdown h3 {
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.10em;
  color: var(--ink-fg-subtle);
  margin: 1rem 0 0.5rem 0;
}
[data-testid="stSidebarNav"] { padding-top: 0.5rem; }
[data-testid="stSidebarNav"] a {
  border-radius: var(--ink-radius-sm);
  transition: background 120ms var(--ink-ease);
}
[data-testid="stSidebarNav"] a:hover { background: var(--ink-bg-sunken); }
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: var(--ink-accent-soft);
  color: var(--ink-accent);
  font-weight: 600;
}

.ink-card {
  background: var(--ink-bg-raised);
  border: 1px solid var(--ink-border);
  border-radius: var(--ink-radius-md);
  padding: 1.25rem 1.5rem;
  box-shadow: var(--ink-shadow);
  transition: transform 180ms var(--ink-ease), box-shadow 180ms var(--ink-ease);
}
.ink-card:hover { transform: translateY(-1px); box-shadow: var(--ink-shadow-lg); }
.ink-card-accent { border-left: 3px solid var(--ink-accent); }
.ink-card-title {
  font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.10em; color: var(--ink-fg-subtle); margin: 0 0 0.5rem 0;
}
.ink-card-value {
  font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em;
  color: var(--ink-fg); font-variant-numeric: tabular-nums; line-height: 1.1;
}
.ink-card-delta-pos { color: var(--ink-success); font-size: 0.85rem; font-weight: 500; }
.ink-card-delta-neg { color: var(--ink-error);   font-size: 0.85rem; font-weight: 500; }
.ink-card-help { color: var(--ink-fg-muted); font-size: 0.78rem; margin-top: 0.35rem; }

.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: var(--ink-radius-sm);
  border: 1px solid var(--ink-border-strong);
  background: var(--ink-bg-raised);
  color: var(--ink-fg);
  font-weight: 500;
  padding: 0.5rem 1rem;
  transition: all 140ms var(--ink-ease);
  box-shadow: none;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--ink-fg-muted);
  background: var(--ink-bg-sunken);
  transform: translateY(-1px);
}
.stButton > button:active { transform: translateY(0); }
.stButton > button[kind="primary"], .stFormSubmitButton > button {
  background: var(--ink-accent);
  color: var(--ink-accent-fg);
  border-color: var(--ink-accent);
  font-weight: 600;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover {
  filter: brightness(1.05);
  border-color: var(--ink-accent);
}
.stButton > button:focus-visible {
  outline: 2px solid var(--ink-accent);
  outline-offset: 2px;
}

.stTextInput input, .stTextArea textarea, .stNumberInput input,
.stSelectbox div[data-baseweb="select"] > div,
.stMultiSelect div[data-baseweb="select"] > div {
  background: var(--ink-bg-raised);
  border: 1px solid var(--ink-border-strong);
  border-radius: var(--ink-radius-sm);
  color: var(--ink-fg);
  transition: border-color 120ms var(--ink-ease), box-shadow 120ms var(--ink-ease);
}
.stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
  border-color: var(--ink-accent);
  box-shadow: 0 0 0 3px var(--ink-accent-soft);
}

.stTabs [data-baseweb="tab-list"] { gap: 0; border-bottom: 1px solid var(--ink-border); }
.stTabs [data-baseweb="tab"] {
  padding: 0.5rem 1rem; border-radius: 0; background: transparent;
  color: var(--ink-fg-muted); border-bottom: 2px solid transparent;
  font-weight: 500;
  transition: color 120ms var(--ink-ease), border-color 120ms var(--ink-ease);
}
.stTabs [aria-selected="true"] {
  color: var(--ink-accent) !important;
  border-bottom-color: var(--ink-accent) !important;
}
.stExpander {
  background: var(--ink-bg-raised);
  border: 1px solid var(--ink-border);
  border-radius: var(--ink-radius-md);
  margin-bottom: 0.5rem;
  transition: border-color 140ms var(--ink-ease);
}
.stExpander:hover { border-color: var(--ink-border-strong); }
.stExpander summary { font-weight: 500; }
[data-testid="stDataFrame"] {
  border: 1px solid var(--ink-border);
  border-radius: var(--ink-radius-md);
  overflow: hidden;
}

.ink-pill {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.2rem 0.65rem; border-radius: 999px;
  font-size: 0.75rem; font-weight: 600;
  background: var(--ink-bg-sunken); color: var(--ink-fg-muted);
  border: 1px solid var(--ink-border); letter-spacing: 0.01em;
}
.ink-pill::before {
  content: ""; width: 6px; height: 6px; border-radius: 50%;
  background: var(--ink-fg-subtle);
}
.ink-pill-ok     { color: var(--ink-success); }
.ink-pill-ok::before     { background: var(--ink-success); }
.ink-pill-warn   { color: var(--ink-warn); }
.ink-pill-warn::before   { background: var(--ink-warn); }
.ink-pill-error  { color: var(--ink-error); }
.ink-pill-error::before  { background: var(--ink-error); }
.ink-pill-info   { color: var(--ink-info); }
.ink-pill-info::before   { background: var(--ink-info); }
.ink-pill-accent { background: var(--ink-accent-soft); color: var(--ink-accent); border-color: transparent; }
.ink-pill-accent::before { background: var(--ink-accent); }

@keyframes ink-fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.main .block-container { animation: ink-fade-in 280ms var(--ink-ease) both; }
.main .block-container > div:nth-child(2) { animation-delay: 60ms; }
.main .block-container > div:nth-child(3) { animation-delay: 120ms; }
.main .block-container > div:nth-child(4) { animation-delay: 180ms; }

@keyframes ink-pulse-soft { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
.ink-pulse { animation: ink-pulse-soft 1.6s var(--ink-ease) infinite; }

.ink-header {
  padding: 0.25rem 0 1.25rem 0; margin-bottom: 1.25rem;
  border-bottom: 1px solid var(--ink-border);
  display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap;
}
.ink-header h1 { font-size: 1.625rem; font-weight: 600; letter-spacing: -0.025em; margin: 0; color: var(--ink-fg); }
.ink-header .ink-header-tag {
  font-size: 0.78rem; font-weight: 500; color: var(--ink-fg-subtle);
  letter-spacing: 0.04em; text-transform: uppercase;
}
.ink-header .ink-header-sub {
  font-size: 0.9rem; color: var(--ink-fg-muted);
  margin-left: auto; font-variant-numeric: tabular-nums;
}

.ink-brand {
  display: flex; align-items: center; gap: 0.6rem;
  padding: 0.75rem 0 1rem 0; margin-bottom: 0.25rem;
  border-bottom: 1px solid var(--ink-border);
}
.ink-brand-mark {
  width: 28px; height: 28px; border-radius: 8px;
  background: var(--ink-accent); color: var(--ink-accent-fg);
  font-weight: 700; font-size: 0.95rem;
  display: inline-flex; align-items: center; justify-content: center;
  letter-spacing: -0.04em; font-family: var(--ink-mono);
}
.ink-brand-text { line-height: 1.1; }
.ink-brand-text .ink-brand-name { font-weight: 600; font-size: 0.95rem; color: var(--ink-fg); }
.ink-brand-text .ink-brand-sub  { font-size: 0.7rem; color: var(--ink-fg-subtle); letter-spacing: 0.04em; text-transform: uppercase; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}

#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
</style>
"""


def status_pill(kind: str = "neutral", label: str = "") -> str:
    """Kinds: ok, warn, error, info, accent, neutral."""
    return f'<span class="ink-pill ink-pill-{kind}">{label}</span>'


def metric_card(
    title: str,
    value: str,
    *,
    delta: Optional[str] = None,
    delta_positive: bool = True,
    help: Optional[str] = None,
    accent: bool = False,
) -> str:
    """Render a single metric as a card. Use in st.markdown(...)."""
    delta_html = ""
    if delta is not None:
        cls = "ink-card-delta-pos" if delta_positive else "ink-card-delta-neg"
        prefix = "" if (delta.startswith("+") or delta.startswith("-")) else ("+" if delta_positive else "-")
        delta_html = f'<div class="{cls}">{prefix}{delta}</div>'
    help_html = f'<div class="ink-card-help">{help}</div>' if help else ""
    accent_cls = " ink-card-accent" if accent else ""
    return (
        f'<div class="ink-card{accent_cls}">'
        f'  <div class="ink-card-title">{title}</div>'
        f'  <div class="ink-card-value">{value}</div>'
        f'  {delta_html}'
        f'  {help_html}'
        f'</div>'
    )


def metric_row(cards: list[str]) -> str:
    return (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));'
        'gap:0.75rem;margin:0.5rem 0 1.5rem 0;">'
        + "".join(cards)
        + "</div>"
    )


def section_divider() -> str:
    return '<div style="height:1px;background:var(--ink-border);margin:2rem 0 1.5rem 0;"></div>'


def page_setup(
    layout: str = "wide",
    *,
    title: Optional[str] = None,
    page_icon: Optional[str] = None,
) -> None:
    st.set_page_config(
        page_title=title or BRAND_NAME,
        page_icon=page_icon or "0",
        layout=layout,
        initial_sidebar_state="expanded",
    )
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "") -> None:
    sub_html = f'<div class="ink-header-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="ink-header">
          <div>
            <h1>{title}</h1>
            <div class="ink-header-tag">{BRAND_NAME}</div>
          </div>
          {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar_brand() -> None:
    st.markdown(
        f"""
        <div class="ink-brand">
          <div class="ink-brand-mark">0</div>
          <div class="ink-brand-text">
            <div class="ink-brand-name">{BRAND_NAME}</div>
            <div class="ink-brand-sub">{BRAND_VERSION}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(BRAND_TAGLINE)
