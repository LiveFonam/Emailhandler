"""One-off CLI: scrape leads from a single source and dump to CSV.

Usage:
    python -m tools.scrape --source google_cse --query "VP Engineering biotech Toronto" --max 20
    python -m tools.scrape --source gmaps --query "biotech companies Toronto" --max 50 --save
    python -m tools.scrape --source google_cse --query "..." --max 20 --save

The CLI mirrors the convention of tools/backfill_inbox.py and
tools/oauth_init.py: argparse, sys.path bootstrap, a `main()` function
called from an `if __name__ == "__main__":` block.
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import sys
from pathlib import Path

# Make project root importable so `from src.leads...` works when run as
# `python -m tools.scrape ...` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.leads.sources import google_cse, gmaps
from src.leads.store import bulk_upsert


log = logging.getLogger("inbox_zero.scrape")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


SOURCE_CHOICES = ("google_cse", "gmaps")


# The columns we expose in the CSV preview. Order is chosen to match what
# a human triaging a list will want to see first.
_CSV_COLUMNS = (
    "email",
    "first_name",
    "last_name",
    "company",
    "title",
    "city",
    "country",
    "source",
    "source_url",
)


def _missing_env_for_source(source: str) -> list[str]:
    """Return the env-var names the user must set to run this source."""
    if source == "google_cse":
        out: list[str] = []
        if not settings.google_cse_key:
            out.append("GOOGLE_CSE_KEY")
        if not settings.google_cse_id:
            out.append("GOOGLE_CSE_ID")
        return out
    if source == "gmaps":
        if not os.getenv("GOOGLE_MAPS_API_KEY", ""):
            return ["GOOGLE_MAPS_API_KEY"]
        return []
    return []


def _run_source(source: str, query: str, max_results: int) -> list[dict]:
    """Dispatch to the right source module's search() function."""
    if source == "google_cse":
        return google_cse.search(query, max_results=max_results)
    if source == "gmaps":
        return gmaps.search(query, max_results=max_results)
    raise ValueError(f"Unknown source: {source}")


def _format_csv(leads: list[dict], columns: tuple[str, ...] = _CSV_COLUMNS) -> str:
    """Format leads as a CSV string. Always emits the header row."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        row = {col: (lead.get(col) or "") for col in columns}
        writer.writerow(row)
    return buf.getvalue()


def _format_table(leads: list[dict], max_rows: int = 20) -> str:
    """Format leads as a fixed-width text table for stdout. The CSV is the
    canonical export; the table is just a human-friendly preview."""
    if not leads:
        return "(no results)"
    columns = _CSV_COLUMNS
    rows = [
        [str(lead.get(c) or "") for c in columns]
        for lead in leads[:max_rows]
    ]
    widths = [
        max(len(columns[i]), *(len(r[i]) for r in rows))
        for i in range(len(columns))
    ]
    sep = "  "
    out_lines = []
    out_lines.append(sep.join(c.ljust(widths[i]) for i, c in enumerate(columns)))
    out_lines.append(sep.join("-" * widths[i] for i in range(len(columns))))
    for r in rows:
        out_lines.append(sep.join(r[i].ljust(widths[i]) for i in range(len(columns))))
    if len(leads) > max_rows:
        out_lines.append(f"... ({len(leads) - max_rows} more rows)")
    return "\n".join(out_lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scrape leads from a single source and print a CSV preview."
    )
    ap.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default="google_cse",
        help="Which lead source to scrape (default: google_cse)",
    )
    ap.add_argument(
        "--query",
        type=str,
        required=True,
        help="Search query string (required)",
    )
    ap.add_argument(
        "--max",
        type=int,
        default=20,
        help="Maximum number of results to fetch (default: 20)",
    )
    ap.add_argument(
        "--save",
        action="store_true",
        help="If set, persist the scraped leads via bulk_upsert and print counts.",
    )
    args = ap.parse_args()

    if args.max <= 0:
        print(f"--max must be a positive integer, got {args.max}", file=sys.stderr)
        return 1

    # Pre-flight: if the chosen source's API key is missing, fail early
    # with a clear, actionable error.
    missing = _missing_env_for_source(args.source)
    if missing:
        print(
            f"Error: {args.source} is not configured. "
            f"Set the following env var(s) in your .env or environment: "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    log.info("Running %s scrape: query=%r max=%d", args.source, args.query, args.max)
    try:
        leads = _run_source(args.source, args.query, args.max)
    except Exception as exc:
        print(f"Error: scrape failed: {exc}", file=sys.stderr)
        return 1

    if not leads:
        print("(no results from source)")
        if args.save:
            print("Save: 0 inserted, 0 updated, 0 skipped")
        return 0

    # CSV preview to stdout (always).
    print(_format_csv(leads))
    print()
    print(f"=== Preview (first {min(20, len(leads))} of {len(leads)} results) ===")
    print(_format_table(leads, max_rows=20))

    if not args.save:
        return 0

    # Persist.
    try:
        counts = bulk_upsert(leads)
    except Exception as exc:
        print(f"Error: bulk_upsert failed: {exc}", file=sys.stderr)
        return 1

    print()
    print(
        f"Save: {counts.get('inserted', 0)} inserted, "
        f"{counts.get('updated', 0)} updated, "
        f"{counts.get('skipped', 0)} skipped"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
