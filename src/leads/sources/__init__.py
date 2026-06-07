"""Lead source adapters.

Each source exposes a `search(query, max_results) -> list[dict]` function
that returns dicts matching the Lead schema (see src/schemas.py).

v1: google_cse + gmaps
v1.1: apollo, hunter, company_site
"""
from __future__ import annotations
