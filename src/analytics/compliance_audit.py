"""Compliance audit: re-scan sent_log for any non-compliant sends."""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from src import db
from src.outreach.compliance import check_mime

log = logging.getLogger("inbox_zero.analytics.compliance_audit")


def audit_last_n_days(days: int = 30) -> dict:
    rows = db.query_all(
        f"""SELECT id, raw_mime_path FROM sent_log
            WHERE date(sent_at) >= date('now', '-{int(days)} day')
              AND raw_mime_path IS NOT NULL"""
    )
    failures = []
    passed = 0
    for r in rows:
        path = Path(r["raw_mime_path"])
        if not path.exists():
            failures.append({"id": r["id"], "issues": ["raw_mime_path missing on disk"]})
            continue
        try:
            mime = path.read_bytes()
            check = check_mime(mime)
            if check.ok:
                passed += 1
            else:
                failures.append({"id": r["id"], "issues": check.issues})
        except Exception as e:
            failures.append({"id": r["id"], "issues": [str(e)]})

    db.exec(
        """INSERT INTO compliance_audit
            (ran_at, window_start, window_end, total_checked, passed, failed, failures_json)
           VALUES (?, date('now', ?), date('now'), ?, ?, ?, ?)""",
        (
            dt.datetime.now(dt.timezone.utc).isoformat(),
            f"-{int(days)} day",
            len(rows),
            passed,
            len(failures),
            db.to_json(failures),
        ),
    )
    return {
        "total": len(rows),
        "passed": passed,
        "failed": len(failures),
        "failures": failures,
    }
