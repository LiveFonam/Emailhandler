"""Backfill CLI: triage the entire inherited inbox.

Usage:
    python -m tools.backfill_inbox --max 342 --workers 4
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import paths
from src.gmail.fetch import list_thread_ids, get_thread, thread_to_digest
from src.gmail.labels import ensure_labels, apply_category
from src.triage.triage import classify_thread, summarize_thread
from src.schemas import TriageResult, ThreadSummary
from src import db
from src.config import settings


log = logging.getLogger("inbox_zero.backfill")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(paths.RUN_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


def _process_one(thread_id: str) -> tuple[str, str, str | None]:
    """Triage one thread: fetch, classify, summarize, persist, label.
    Returns (thread_id, category, error_or_None)."""
    try:
        thread = get_thread(thread_id, fmt="full")
        digest = thread_to_digest(thread)

        # Persist thread metadata
        first_from = digest.get("first_from", "")
        last_from = digest.get("last_from", "")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        db.exec(
            """INSERT INTO threads (id, subject, first_from, last_from, first_seen_at, last_seen_at, message_count, snippet)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 subject=excluded.subject,
                 first_from=excluded.first_from,
                 last_from=excluded.last_from,
                 last_seen_at=excluded.last_seen_at,
                 message_count=excluded.message_count,
                 snippet=excluded.snippet
            """,
            (
                digest["id"],
                digest.get("subject", ""),
                first_from,
                last_from,
                now,
                now,
                digest.get("message_count", 0),
                (digest.get("messages", [{}])[-1].get("snippet", "")
                 if digest.get("messages") else ""),
            ),
        )

        # Classify + summarize (combined for efficiency: 2 calls)
        triage = classify_thread(digest)
        # Only summarize if it looks like a real thread
        if digest.get("message_count", 0) >= 1 and triage.category != "promotion":
            summary = summarize_thread(digest)
            bullets = summary.bullets
            actions = summary.action_items
        else:
            bullets = []
            actions = []

        db.exec(
            """INSERT INTO triage (thread_id, category, confidence, action, summary_bullets, action_items, triaged_at, triaged_by_model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(thread_id) DO UPDATE SET
                 category=excluded.category,
                 confidence=excluded.confidence,
                 action=excluded.action,
                 summary_bullets=excluded.summary_bullets,
                 action_items=excluded.action_items,
                 triaged_at=excluded.triaged_at,
                 triaged_by_model=excluded.triaged_by_model
            """,
            (
                digest["id"],
                triage.category,
                triage.confidence,
                triage.action,
                db.to_json(bullets),
                db.to_json(actions),
                now,
                "triage",
            ),
        )

        # Apply the Gmail label so the user sees it in Gmail
        try:
            apply_category(digest["id"], triage.category)
        except Exception as e:
            log.warning(f"Failed to apply label to {thread_id}: {e}")

        return digest["id"], triage.category, None
    except Exception as e:
        return thread_id, "error", str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=settings.triage.backfill_max_threads,
                    help="Max threads to triage (default from config)")
    ap.add_argument("--query", type=str, default="is:unread",
                    help="Gmail search query (default: is:unread)")
    ap.add_argument("--workers", type=int, default=settings.triage.backfill_max_workers,
                    help="Parallel workers (default from config)")
    ap.add_argument("--account", type=str, default="default",
                    help="Which Gmail account to triage (default = first OAuth)")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the y/N prompt")
    args = ap.parse_args()

    if not args.yes:
        print(f"About to triage up to {args.max} threads on account '{args.account}'")
        print(f"Using query: {args.query}")
        try:
            ans = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            ans = "y"
        if ans != "y":
            print("Aborted.")
            return

    log.info(f"Ensuring AI labels exist on account '{args.account}'")
    try:
        created = ensure_labels(args.account)
        log.info(f"Created {len(created)} labels: {created}")
    except Exception as e:
        log.error(f"Could not ensure labels: {e}")
        return

    log.info(f"Listing up to {args.max} thread ids matching '{args.query}'")
    thread_ids = list_thread_ids(query=args.query, max_results=args.max, account=args.account)
    log.info(f"Found {len(thread_ids)} thread ids")

    if not thread_ids:
        print("No threads matched. Done.")
        return

    counts: dict[str, int] = {}
    errors: list[tuple[str, str]] = []
    t0 = time.time()
    completed = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_process_one, tid): tid for tid in thread_ids
        }
        for fut in cf.as_completed(futures):
            tid = futures[fut]
            try:
                _tid, cat, err = fut.result()
            except Exception as e:
                cat, err = "error", str(e)
            counts[cat] = counts.get(cat, 0) + 1
            if err:
                errors.append((_tid, err))
            completed += 1
            if completed % 10 == 0 or completed == len(thread_ids):
                rate = completed / max(0.1, time.time() - t0)
                eta = (len(thread_ids) - completed) / max(0.01, rate)
                log.info(
                    f"[{completed}/{len(thread_ids)}] {rate:.1f}/s "
                    f"ETA {eta:.0f}s  counts={counts}"
                )

    elapsed = time.time() - t0
    log.info(f"Done. {len(thread_ids)} threads in {elapsed:.1f}s ({len(thread_ids)/elapsed:.1f}/s)")
    log.info(f"Category counts: {json.dumps(counts, indent=2)}")
    if errors:
        log.warning(f"{len(errors)} errors. First 5:")
        for tid, err in errors[:5]:
            log.warning(f"  {tid}: {err}")


if __name__ == "__main__":
    main()
