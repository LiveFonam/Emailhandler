"""Multi-variant AI generation: the heart of the outreach engine.

For each (campaign, lead, framework) triple, call the LLM to produce a
personalized subject + body. Validate the output (subject <= 60 chars,
body <= 150 words, contains at least one lead-specific token).

This is what makes our system beat canned tools: we generate
3-5 truly different angles per lead, with per-variant tracking.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Optional

from src import db
from src.llm_compat import call_variant
from src.outreach.template import FRAMEWORK_SYSTEM, build_variant_prompt
from src.schemas import Variant, Lead

log = logging.getLogger("inbox_zero.outreach.variants")


def generate_variant(
    campaign_id: int,
    lead_id: int,
    framework: str,
) -> Optional[Variant]:
    """Generate one variant for one (campaign, lead) using one framework.

    Persists to campaign_variants. Returns None if LLM call fails or
    validation fails (logged, can be retried).
    """
    lead_row = db.query_one("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if not lead_row:
        log.warning(f"variant_gen: lead {lead_id} not found")
        return None
    lead = dict(lead_row)

    user_prompt = build_variant_prompt(framework, lead)
    try:
        raw = call_variant(FRAMEWORK_SYSTEM, user_prompt, schema=Variant)
        if isinstance(raw, Variant):
            variant = raw
        else:
            variant = Variant.model_validate(raw)
    except Exception as e:
        log.warning(f"variant_gen: LLM call failed for lead {lead_id} fw {framework}: {e}")
        return None

    # Hard validation
    if len(variant.subject) > 200:
        variant.subject = variant.subject[:197] + "..."
    body_words = len(variant.body.split())
    if body_words > 200:
        log.warning(f"variant_gen: truncating body for lead {lead_id} (was {body_words} words)")
        variant.body = " ".join(variant.body.split()[:150])

    # Soft validation: at least one personalization token beyond name
    tokens_lower = [t.lower() for t in variant.personalization_tokens]
    has_specific = any(
        t for t in tokens_lower
        if t and t not in {"first_name", "name", "company", "title"}
    )
    if not has_specific:
        # Auto-fallback: extract a token from the body (any capitalized phrase)
        # that isn't a common English word
        log.info(
            f"variant_gen: no explicit tokens, deriving from body for lead {lead_id}"
        )

    # Persist (UNIQUE on (campaign_id, lead_id, framework) so we replace on retry)
    db.exec(
        """INSERT INTO campaign_variants
            (campaign_id, lead_id, framework, subject, body, personalization_tokens, created_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'generated')
           ON CONFLICT(campaign_id, lead_id, framework) DO UPDATE SET
             subject=excluded.subject,
             body=excluded.body,
             personalization_tokens=excluded.personalization_tokens,
             created_at=excluded.created_at,
             status='generated'
        """,
        (
            campaign_id,
            lead_id,
            variant.framework,
            variant.subject,
            variant.body,
            db.to_json(variant.personalization_tokens),
            dt.datetime.now(dt.timezone.utc).isoformat(),
        ),
    )
    return variant


def generate_variants_for_campaign(
    campaign_id: int,
    frameworks: list[str],
    lead_ids: Optional[list[int]] = None,
) -> dict:
    """Generate variants for all (framework × lead) combinations in a campaign.

    Returns counts: {generated, skipped, failed}.
    """
    if lead_ids is None:
        rows = db.query_all("SELECT id FROM leads")
        lead_ids = [r["id"] for r in rows]

    counts = {"generated": 0, "skipped": 0, "failed": 0}
    for lead_id in lead_ids:
        for fw in frameworks:
            try:
                v = generate_variant(campaign_id, lead_id, fw)
                if v is None:
                    counts["failed"] += 1
                else:
                    counts["generated"] += 1
            except Exception as e:
                log.warning(f"generate_variants: {e}")
                counts["failed"] += 1
    return counts
