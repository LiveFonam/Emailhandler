"""Typed config loader.

Reads config.yaml + .env once at import time, exposes a Settings dataclass.
Most code should `from src.config import settings` and use it directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app import paths


def _load_yaml() -> dict[str, Any]:
    cfg_path = paths.project_root() / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_CFG = _load_yaml()
load_dotenv(paths.project_root() / ".env", override=False)


@dataclass
class SenderProfile:
    name: str = ""
    reply_to: str = ""
    signature: str = ""
    physical_address: str = ""

    @property
    def has_physical_address(self) -> bool:
        return bool(self.physical_address and self.physical_address.strip())


@dataclass
class WarmupConfig:
    start_cap: int = 10
    week_2_cap: int = 15
    week_3_cap: int = 22
    week_4_cap: int = 33
    week_5_cap: int = 50
    week_6_cap: int = 75
    week_7_plus_cap: int = 100
    spam_rate_pause_threshold: float = 0.005

    def cap_for_day(self, days_into_campaign: int) -> int:
        if days_into_campaign < 7:
            return self.start_cap
        if days_into_campaign < 14:
            return self.week_2_cap
        if days_into_campaign < 21:
            return self.week_3_cap
        if days_into_campaign < 28:
            return self.week_4_cap
        if days_into_campaign < 35:
            return self.week_5_cap
        if days_into_campaign < 42:
            return self.week_6_cap
        return self.week_7_plus_cap


@dataclass
class ThrottlerConfig:
    min_jitter_seconds: int = 60
    max_jitter_seconds: int = 90
    business_hours_start: int = 9
    business_hours_end: int = 17
    default_recipient_timezone: str = "America/Toronto"


@dataclass
class ComplianceConfig:
    unsubscribe_base_url: str = "http://localhost:8503/u"
    required_headers: list[str] = field(default_factory=lambda: [
        "List-Unsubscribe",
        "List-Unsubscribe-Post",
        "X-Entity-Ref-ID",
    ])


@dataclass
class TriageConfig:
    triage_account: str = ""
    backfill_max_workers: int = 4
    backfill_max_threads: int = 500


@dataclass
class StreamlitConfig:
    port: int = 8502
    page_icon: str = ":inbox_tray:"
    layout: str = "wide"


@dataclass
class Settings:
    sender: SenderProfile
    warmup: WarmupConfig
    throttler: ThrottlerConfig
    compliance: ComplianceConfig
    triage: TriageConfig
    streamlit: StreamlitConfig

    @property
    def anthropic_api_key(self) -> str:
        return os.getenv("ANTHROPIC_API_KEY", "")

    @property
    def groq_api_key(self) -> str:
        return os.getenv("GROQ_API_KEY", "")

    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "")

    @property
    def google_cse_id(self) -> str:
        return os.getenv("GOOGLE_CSE_ID", "")

    @property
    def google_cse_key(self) -> str:
        return os.getenv("GOOGLE_CSE_KEY", "")

    @property
    def google_cloud_project(self) -> str:
        return os.getenv("GOOGLE_CLOUD_PROJECT", "")

    @property
    def hunter_api_key(self) -> str:
        return os.getenv("HUNTER_API_KEY", "")

    @property
    def apollo_api_key(self) -> str:
        return os.getenv("APOLLO_API_KEY", "")

    @property
    def outreach_accounts(self) -> list[str]:
        return [
            a.strip()
            for a in [
                os.getenv("GMAIL_OUTREACH_ACCOUNT_1", ""),
                os.getenv("GMAIL_OUTREACH_ACCOUNT_2", ""),
                os.getenv("GMAIL_OUTREACH_ACCOUNT_3", ""),
            ]
            if a and a.strip()
        ]


def _build() -> Settings:
    sp = _CFG.get("sender_profile", {}) or {}
    wu = _CFG.get("warmup", {}) or {}
    th = _CFG.get("throttler", {}) or {}
    co = _CFG.get("compliance", {}) or {}
    tr = _CFG.get("triage", {}) or {}
    st = _CFG.get("streamlit", {}) or {}

    return Settings(
        sender=SenderProfile(
            name=sp.get("name", ""),
            reply_to=sp.get("reply_to", ""),
            signature=sp.get("signature", ""),
            physical_address=sp.get("physical_address", ""),
        ),
        warmup=WarmupConfig(
            start_cap=wu.get("start_cap", 10),
            week_2_cap=wu.get("week_2_cap", 15),
            week_3_cap=wu.get("week_3_cap", 22),
            week_4_cap=wu.get("week_4_cap", 33),
            week_5_cap=wu.get("week_5_cap", 50),
            week_6_cap=wu.get("week_6_cap", 75),
            week_7_plus_cap=wu.get("week_7_plus_cap", 100),
            spam_rate_pause_threshold=wu.get("spam_rate_pause_threshold", 0.005),
        ),
        throttler=ThrottlerConfig(
            min_jitter_seconds=th.get("min_jitter_seconds", 60),
            max_jitter_seconds=th.get("max_jitter_seconds", 90),
            business_hours_start=th.get("business_hours_start", 9),
            business_hours_end=th.get("business_hours_end", 17),
            default_recipient_timezone=th.get("default_recipient_timezone", "America/Toronto"),
        ),
        compliance=ComplianceConfig(
            unsubscribe_base_url=co.get("unsubscribe_base_url", "http://localhost:8503/u"),
            required_headers=co.get("required_headers", [
                "List-Unsubscribe", "List-Unsubscribe-Post", "X-Entity-Ref-ID",
            ]),
        ),
        triage=TriageConfig(
            triage_account=tr.get("triage_account", ""),
            backfill_max_workers=tr.get("backfill_max_workers", 4),
            backfill_max_threads=tr.get("backfill_max_threads", 500),
        ),
        streamlit=StreamlitConfig(
            port=st.get("port", 8502),
            page_icon=st.get("page_icon", ":inbox_tray:"),
            layout=st.get("layout", "wide"),
        ),
    )


settings = _build()
