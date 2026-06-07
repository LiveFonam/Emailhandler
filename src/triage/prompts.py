"""All triage-related system prompts in one place.

Tone matters: write as a careful executive-assistant style. Bias toward
under-flagging newsletters (those are usually fine to ignore) and
over-flagging anything that asks for a decision or response.
"""
from __future__ import annotations

TRIAGE_SYSTEM = """\
You are an expert executive assistant triaging an inbox. You classify each
incoming thread into exactly one category. Be decisive: pick the single
best category, do not hedge.

Categories (pick one):
  - action-required     The thread needs the user to do something: reply,
                        decide, send, sign, attend, pay. Even if the user
                        is just one of several recipients, classify as
                        action-required if any human is being asked to
                        act.
  - fyi                 The thread is informational, no action needed.
                        Status updates, FYI notices, internal chatter.
  - newsletter          A newsletter, blog digest, mailing-list post.
                        Often comes from no-reply@ or similar.
  - promotion           Marketing / sales / promotional. Discount codes,
                        product announcements, sales pitches.
  - cold-outreach-reply Someone cold-emailed the user and we are now in a
                        reply. Different from a normal action-required
                        because the user may not recognize the sender.

Confidence: 0.0 to 1.0. Be honest about uncertainty. 0.5+ is acceptable
for any case where you have enough signal.

Output JSON exactly matching the requested schema. No prose outside the
JSON.
"""


def triage_user_prompt(digest: dict) -> str:
    """Build the user prompt from a thread digest."""
    parts = [f"Subject: {digest.get('subject', '(no subject)')}\n"]
    parts.append(f"First from: {digest.get('first_from', '?')}")
    parts.append(f"Last from: {digest.get('last_from', '?')}")
    parts.append(f"Message count: {digest.get('message_count', 0)}\n")

    for i, m in enumerate(digest.get("messages", [])):
        parts.append(f"--- Message {i + 1} ---")
        parts.append(f"From: {m.get('from', '')}")
        parts.append(f"Date: {m.get('date', '')}")
        body = m.get("body", "") or m.get("snippet", "")
        if body:
            parts.append(f"\n{body[:1500]}")
        parts.append("")

    parts.append("Now classify this thread. Return JSON.")
    return "\n".join(parts)


SUMMARIZE_SYSTEM = """\
You are an expert executive assistant summarizing an email thread for
someone who is short on time. Output exactly 3 bullet points (5-15 words
each) capturing: what this is about, the current state, and the most
important detail. Then list 0-3 concrete action items for the user
("reply to X about Y", "review attached doc", etc.) or empty list if
none.

Be specific: name people, amounts, dates. No filler phrases like "this
email is about". Start each bullet with a verb or noun, not "This".
Output JSON only.
"""


def summarize_user_prompt(digest: dict) -> str:
    parts = [f"Subject: {digest.get('subject', '')}\n"]
    for i, m in enumerate(digest.get("messages", [])):
        parts.append(f"--- Message {i + 1} (from {m.get('from', '')}) ---")
        body = m.get("body", "") or m.get("snippet", "")
        if body:
            parts.append(body[:2000])
        parts.append("")
    parts.append("Summarize this thread in 3 bullets + 0-3 action items.")
    return "\n".join(parts)


REPLY_SYSTEM = """\
You are an executive assistant drafting a reply email in the user's voice.
The user is busy, professional, and writes in clear plain English. Do
not be sycophantic, do not start with "I hope this email finds you well",
do not use "just" as a filler word.

Style rules:
  - Lead with the substance: the answer, the decision, the ask.
  - 2-4 short paragraphs maximum. Cold replies are short.
  - Match the tone selected (warm | concise | formal | playful).
  - For tone=concise, total length is 1-3 sentences.
  - For tone=warm, you can add one friendly sentence but not multiple.
  - End with a clear next step or sign-off.
  - If the thread has questions, answer them. If it has a request, address it.

Output JSON: {subject, body, tone_used, notes}.
"""


def reply_user_prompt(
    digest: dict,
    tone: str = "warm",
    sender_name: str = "Lucas",
    extra_context: str = "",
) -> str:
    parts = [
        f"Tone: {tone}",
        f"Sender: {sender_name}",
        "",
        f"INBOUND THREAD",
        f"Subject: {digest.get('subject', '')}",
    ]
    if digest.get("last_from"):
        parts.append(f"Last from: {digest.get('last_from')}")
    for i, m in enumerate(digest.get("messages", [])):
        parts.append(f"--- Message {i + 1} (from {m.get('from', '')}) ---")
        body = m.get("body", "") or m.get("snippet", "")
        if body:
            parts.append(body[:2500])
        parts.append("")

    if extra_context.strip():
        parts.append("\nEXTRA CONTEXT FROM USER:")
        parts.append(extra_context.strip())

    parts.append("\nDraft a reply now. Output JSON only.")
    return "\n".join(parts)
