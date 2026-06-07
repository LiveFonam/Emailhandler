"""Single-variant personalized opener (legacy path).

Used when a campaign has variants disabled. Calls the M3 to generate
just the opening 1-2 sentences; the rest is template.
"""
from __future__ import annotations

from src.llm_compat import call_personalize


PERSONALIZE_SYSTEM = """\
You are an expert cold-outreach copywriter. Write a 1-2 sentence opening
for a cold email that demonstrates you understand the recipient's specific
situation. Do not use {{ first_name }}-only personalization.

Plain text, no markdown. Output JSON: {body}.
"""


def generate_personalized_hook(lead: dict, template_body: str) -> str:
    """Generate just the opening 1-2 sentences."""
    user = (
        f"Lead: {lead.get('first_name', '')} {lead.get('last_name', '')}"
        f" at {lead.get('company', '')} ({lead.get('title', '')})\n"
        f"Email template body that will follow your opening:\n\n"
        f"{template_body}\n\n"
        f"Generate a 1-2 sentence opener that fits before this template. "
        f"Return JSON: {{\"body\": \"<your opener>\"}}."
    )
    try:
        raw = call_personalize(PERSONALIZE_SYSTEM, user)
    except Exception:
        return ""
    if isinstance(raw, dict):
        return raw.get("body", "")
    return str(raw)
