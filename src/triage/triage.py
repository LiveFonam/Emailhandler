"""Triage: classify a thread, summarize it, draft a reply.

All three use the LLM via src.llm_compat. The prompts live in prompts.py
so iteration on copy doesn't require touching logic.
"""
from __future__ import annotations

from typing import Optional

from src.llm_compat import call_triage, call_summarize, call_draft
from src.schemas import TriageResult, ThreadSummary, ReplyDraft
from src.gmail.fetch import thread_to_digest


def classify_thread(
    digest: dict,
    model_alias: Optional[str] = None,
) -> TriageResult:
    """Classify a thread digest into one of 5 categories."""
    from src.triage.prompts import TRIAGE_SYSTEM, triage_user_prompt
    user = triage_user_prompt(digest)
    raw = call_triage(TRIAGE_SYSTEM, user, schema=TriageResult)
    if isinstance(raw, TriageResult):
        return raw
    return TriageResult.model_validate(raw)


def summarize_thread(
    digest: dict,
    model_alias: Optional[str] = None,
) -> ThreadSummary:
    """3-bullet summary + 0-3 action items."""
    from src.triage.prompts import SUMMARIZE_SYSTEM, summarize_user_prompt
    user = summarize_user_prompt(digest)
    raw = call_summarize(SUMMARIZE_SYSTEM, user, schema=ThreadSummary)
    if isinstance(raw, ThreadSummary):
        return raw
    return ThreadSummary.model_validate(raw)


def draft_reply(
    digest: dict,
    tone: str = "warm",
    sender_name: str = "Lucas",
    extra_context: str = "",
    model_alias: Optional[str] = None,
) -> ReplyDraft:
    """Generate a reply draft in the user's voice. NEVER auto-sends."""
    from src.triage.prompts import REPLY_SYSTEM, reply_user_prompt
    user = reply_user_prompt(
        digest, tone=tone, sender_name=sender_name, extra_context=extra_context
    )
    raw = call_draft(REPLY_SYSTEM, user, schema=ReplyDraft)
    if isinstance(raw, ReplyDraft):
        return raw
    return ReplyDraft.model_validate(raw)
