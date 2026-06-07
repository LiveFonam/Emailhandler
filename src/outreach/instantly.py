"""Instantly.ai REST client (stubbed for v1).

The user has decided NOT to use Instantly, so this stays a no-op stub.
Kept as a placeholder so a future provider can be added by changing only
sender.py's dispatch decision.
"""
from __future__ import annotations


class InstantlyClient:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def create_campaign(self, name: str) -> str:
        raise NotImplementedError("Instantly integration is disabled in v1.")

    def add_lead(self, campaign_id: str, email: str) -> bool:
        raise NotImplementedError("Instantly integration is disabled in v1.")
