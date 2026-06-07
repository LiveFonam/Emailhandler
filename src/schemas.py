"""Pydantic v2 contracts for the pipeline.

Lifted coercion helpers from Evil's src/schemas.py: `_flatten_to_str_list`
and `_to_str` handle the messiness of LLM JSON output (lists of dicts, None
mixed with strings, etc.) so we don't write 20 lines of field_validators.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _flatten_to_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out: list[str] = []
        for item in v:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
            elif isinstance(item, dict):
                # Common LLM shapes: {"action": "x"} or {"item": "x"}
                s = (
                    item.get("action")
                    or item.get("item")
                    or item.get("text")
                    or item.get("value")
                    or ""
                )
                if isinstance(s, str) and s.strip():
                    out.append(s.strip())
            else:
                s = str(item).strip()
                if s:
                    out.append(s)
        return out
    if isinstance(v, str):
        # Newline-separated list is a common LLM shape
        return [s.strip() for s in v.splitlines() if s.strip()]
    return [str(v).strip()]


# --- triage ----

class TriageResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str = Field(
        description="One of: action-required, fyi, newsletter, promotion, cold-outreach-reply"
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    action: str = Field(default="", description="Short human-readable reason")
    summary_bullets: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)

    @field_validator("category")
    @classmethod
    def _norm_cat(cls, v: str) -> str:
        v = (v or "").strip().lower()
        allowed = {
            "action-required", "fyi", "newsletter",
            "promotion", "cold-outreach-reply",
        }
        return v if v in allowed else "fyi"

    @field_validator("summary_bullets", "action_items", mode="before")
    @classmethod
    def _flatten(cls, v: Any) -> list[str]:
        return _flatten_to_str_list(v)

    @field_validator("action", mode="before")
    @classmethod
    def _act(cls, v: Any) -> str:
        return _to_str(v)


# --- reply draft ----

class ReplyDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: str
    body: str
    tone_used: str = "warm"
    notes: str = ""

    @field_validator("subject", "body", "tone_used", "notes", mode="before")
    @classmethod
    def _s(cls, v: Any) -> str:
        return _to_str(v)


# --- thread summary ----

class ThreadSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bullets: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)

    @field_validator("bullets", "action_items", mode="before")
    @classmethod
    def _fl(cls, v: Any) -> list[str]:
        return _flatten_to_str_list(v)


# --- lead ----

class Lead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str
    first_name: str = ""
    last_name: str = ""
    company: str = ""
    company_domain: str = ""
    title: str = ""
    city: str = ""
    country: str = ""
    timezone: str = ""
    source: str = "manual"
    source_url: str = ""
    recent_news: str = ""
    linkedin_snippet: str = ""

    @field_validator("first_name", "last_name", "company", "title", "city", "country", "source", "source_url", "recent_news", "linkedin_snippet", mode="before")
    @classmethod
    def _s(cls, v: Any) -> str:
        return _to_str(v)


# --- variant ----

class Variant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    framework: str = Field(description="question_hook | recent_news | mutual_connection | value_prop | soft_compliment")
    subject: str = Field(max_length=200)
    body: str
    personalization_tokens: list[str] = Field(default_factory=list)

    @field_validator("framework", mode="before")
    @classmethod
    def _f(cls, v: Any) -> str:
        v = (v or "").strip().lower().replace(" ", "_").replace("-", "_")
        allowed = {
            "question_hook", "recent_news", "mutual_connection",
            "value_prop", "soft_compliment",
        }
        return v if v in allowed else "value_prop"

    @field_validator("subject", "body", mode="before")
    @classmethod
    def _s(cls, v: Any) -> str:
        return _to_str(v)

    @field_validator("personalization_tokens", mode="before")
    @classmethod
    def _fl(cls, v: Any) -> list[str]:
        return _flatten_to_str_list(v)


# --- send job / result ----

class SendJob(BaseModel):
    campaign_id: int
    variant_id: Optional[int] = None
    lead_id: int
    mailbox_id: int
    provider: str = "gmail"
    subject: str
    body: str
    scheduled_for: str


class SentResult(BaseModel):
    message_id: str = ""
    thread_id: str = ""
    sent_at: str
    provider: str = "gmail"


# --- compliance check ----

class ComplianceCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    has_list_unsubscribe: bool = False
    has_list_unsubscribe_post: bool = False
    has_physical_address: bool = False
    has_precedence_bulk: bool = False
    spam_score: float = 0.0  # 0.0 = clean, 1.0 = obvious spam
    issues: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.has_list_unsubscribe
            and self.has_list_unsubscribe_post
            and self.has_physical_address
        )

    @field_validator("issues", mode="before")
    @classmethod
    def _fl(cls, v: Any) -> list[str]:
        return _flatten_to_str_list(v)
