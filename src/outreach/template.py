"""Jinja2 template loader with required-variable whitelist.

Templates live in data/templates/<id>.j2. They use {{ var }} placeholders
that are filled in at render time. The per-template `required_vars` field
prevents the most common cold-email spam pattern: a template that has
nothing but {{ first_name }} and falls back to "Hi there" if missing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, meta

from app import paths


@dataclass
class Template:
    id: str
    name: str
    body: str
    subject: str
    required_vars: list[str]
    path: Path

    def render(self, vars: dict) -> tuple[str, str]:
        env = Environment(loader=FileSystemLoader(str(self.path.parent)))
        subject_t = env.from_string(self.subject)
        body_t = env.from_string(self.body)
        # Validate required vars
        missing = [v for v in self.required_vars if not vars.get(v)]
        if missing:
            raise ValueError(
                f"Template {self.id} missing required vars: {missing}"
            )
        return subject_t.render(**vars), body_t.render(**vars)


def list_templates() -> list[Template]:
    out: list[Template] = []
    tdir = paths.TEMPLATES_DIR
    if not tdir.exists():
        return out
    for j2 in tdir.glob("*.j2"):
        # Sidecar JSON for metadata
        meta_path = j2.with_suffix(".json")
        meta_data: dict = {}
        if meta_path.exists():
            try:
                meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        body = j2.read_text(encoding="utf-8")
        # Extract subject from first line if "Subject: ..." present
        subject = meta_data.get("subject", "")
        if not subject and "subject:" in body.lower()[:200]:
            for line in body.splitlines()[:5]:
                if line.lower().startswith("subject:"):
                    subject = line.split(":", 1)[1].strip()
                    break
        out.append(
            Template(
                id=j2.stem,
                name=meta_data.get("name", j2.stem),
                body=body,
                subject=subject or "(no subject)",
                required_vars=meta_data.get("required_vars", ["first_name", "company"]),
                path=j2,
            )
        )
    return out


def get_template(template_id: str) -> Template | None:
    for t in list_templates():
        if t.id == template_id:
            return t
    return None


# --- framework prompts for the multi-variant generator ---

FRAMEWORK_SYSTEM = """\
You are an expert cold-outreach copywriter. You write short, specific,
non-spammy cold emails. You avoid: sycophancy, generic "I hope this
finds you well" openings, exclamation marks, all-caps, and any
"just checking in" follow-ups.

Each email must contain at least one specific, lead-personalized detail
(not just {{ first_name }}). Examples: a recent news item about their
company, a specific product feature, a role-specific pain point, a
mutual connection, a public talk they gave.

Format: plain text, line breaks between paragraphs, max 150 words,
under 60 char subject line. No markdown, no bullet lists.

Output JSON matching {framework, subject, body, personalization_tokens}.
"""


FRAMEWORK_USER = """\
Generate a cold-outreach email using the {framework} framework.

LEAD INFO:
- Name: {first_name} {last_name}
- Title: {title}
- Company: {company}
- Company domain: {company_domain}
- City: {city}, {country}
{recent_news_block}
{linkedin_block}

FRAMEWORK GUIDANCE ({framework}):
{framework_guidance}

Few-shot example for this framework:
{framework_example}

Return JSON: framework, subject, body, personalization_tokens
"""


FRAMEWORKS: dict[str, dict] = {
    "question_hook": {
        "guidance": (
            "Open with a sharp, specific, lead-relevant question that "
            "demonstrates you understand their world. The question should "
            "make them want to respond. NOT a yes/no question."
        ),
        "example": (
            "Subject: biotech ops in Montreal\n\n"
            "Hi Sarah,\n\n"
            "Saw the StemCell announcement last week — congrats on the "
            "Series A. How are you thinking about scaling the QC lab "
            "workflow now that you're tripling headcount?\n\n"
            "We helped Defy Nutrition cut their assay turnaround from "
            "11 days to 4 with a sample-tracking system. Not a fit for "
            "what you're building, but the patterns might be useful.\n\n"
            "Worth a 15-min call next week?\n\n"
            "— Lucas"
        ),
    },
    "recent_news": {
        "guidance": (
            "Reference something specific that happened to the lead's "
            "company or industry in the last ~30 days. Show that you "
            "actually pay attention to their world, not just scraped a list."
        ),
        "example": (
            "Subject: re: your G2 review\n\n"
            "Hi Marcus,\n\n"
            "Saw your team's G2 review last week about wanting better "
            "inter-team visibility on QA findings. That's a tough one to "
            "solve after a Series B because the org structure keeps "
            "shifting.\n\n"
            "I worked with a YC biotech that hit the same wall — we "
            "ended up doing a lightweight weekly digest instead of "
            "another dashboard. Happy to share what we learned.\n\n"
            "— Lucas"
        ),
    },
    "mutual_connection": {
        "guidance": (
            "If we have a real mutual connection, name them (only if "
            "we're certain they know the lead). Otherwise use a shared "
            "context like a conference, a podcast episode, or a community. "
            "Do NOT fabricate a mutual connection."
        ),
        "example": (
            "Subject: Anita suggested I reach out\n\n"
            "Hi James,\n\n"
            "Anita Chen mentioned you've been digging into the data-pipeline "
            "problem on the new diagnostics platform. I'm working on a "
            "similar question with two other Series A teams and thought "
            "you might want to compare notes.\n\n"
            "No pitch, just curious whether what we're seeing matches "
            "your experience.\n\n"
            "— Lucas"
        ),
    },
    "value_prop": {
        "guidance": (
            "Lead with a concrete, specific value claim tied to the lead's "
            "exact situation. Numbers and outcomes beat adjectives. If you "
            "don't have a real number, name a specific mechanism, not a "
            "vague benefit."
        ),
        "example": (
            "Subject: 3.2x faster in our last pilot\n\n"
            "Hi Priya,\n\n"
            "We ran a 6-week pilot with two clinical-ops teams running "
            "on the same LIMS you're using. Median sample-to-result "
            "time dropped from 8.4 days to 2.6 days, with no new headcount.\n\n"
            "The mechanism is a workflow refactor, not a new tool. Worth "
            "a 20-min look at what we did?\n\n"
            "— Lucas"
        ),
    },
    "soft_compliment": {
        "guidance": (
            "Acknowledge something specific the lead has done or built, "
            "without flattery. Connect it to why you're reaching out. "
            "The compliment must be specific enough that it couldn't be "
            "sent to a list of 100 people."
        ),
        "example": (
            "Subject: the cohort retention chart\n\n"
            "Hi Devon,\n\n"
            "Your post on PLG-era retention metrics last month was the "
            "clearest breakdown I've read. We tried to apply the same "
            "cohort framing to a B2B dev-tools product and hit a wall "
            "on activation windows.\n\n"
            "Curious whether you saw the same pattern in your SaaS "
            "research, or if you have a sharper take.\n\n"
            "— Lucas"
        ),
    },
}


def build_variant_prompt(framework: str, lead: dict) -> str:
    fw = FRAMEWORKS.get(framework, FRAMEWORKS["value_prop"])
    recent_news = (lead.get("recent_news") or "").strip()
    linkedin = (lead.get("linkedin_snippet") or "").strip()
    return FRAMEWORK_USER.format(
        framework=framework,
        first_name=lead.get("first_name", ""),
        last_name=lead.get("last_name", ""),
        title=lead.get("title", ""),
        company=lead.get("company", ""),
        company_domain=lead.get("company_domain", ""),
        city=lead.get("city", ""),
        country=lead.get("country", ""),
        recent_news_block=(
            f"Recent news about their company: {recent_news}" if recent_news else ""
        ),
        linkedin_block=(
            f"LinkedIn bio snippet: {linkedin}" if linkedin else ""
        ),
        framework_guidance=fw["guidance"],
        framework_example=fw["example"],
    )
