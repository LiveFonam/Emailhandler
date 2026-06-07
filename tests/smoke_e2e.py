"""End-to-end smoke test (offline).

Verifies that every module in the inbox-zero-agent project can be imported,
the database initializes with the full 12-table schema, and the public
function contracts are present.

Live steps (OAuth, real Gmail, real LLM) are documented in the plan but
require credentials the test environment doesn't have.

Run: cd inbox-zero-agent && python -m tests.smoke_e2e
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))


def main() -> int:
    print("=== FULL E2E SMOKE (offline) ===\n")
    failures: list[str] = []

    def check(name: str, fn):
        try:
            fn()
            print(f"  [OK] {name}")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
            failures.append(name)

    # === Phase A: bootstrap + LLM bridge ===
    print("Phase A: bootstrap + LLM bridge")
    def a1():
        from app import paths  # noqa: F401
    def a2():
        from src import llm_compat  # noqa: F401
    def a3():
        from src.config import settings  # noqa: F401
        assert settings is not None
    def a4():
        from src import db  # noqa: F401
    def a5():
        from src.schemas import (
            TriageResult, ThreadSummary, ReplyDraft,
            Lead, SendJob, SentResult, ComplianceCheck, Variant,
        )  # noqa: F401
    check("paths.py", a1)
    check("llm_compat", a2)
    check("config.settings", a3)
    check("db", a4)
    check("schemas", a5)

    # === Phase B: Gmail read + triage ===
    print("\nPhase B: Gmail read + triage")
    def b1():
        from src.gmail import oauth, client, fetch, labels, drafts, send, modify, watch  # noqa: F401
    def b2():
        from src.triage import triage, prompts  # noqa: F401
    check("gmail layer (8 modules)", b1)
    check("triage layer", b2)

    # === Phase C: send path + compliance ===
    print("\nPhase C: send path + compliance")
    def c1():
        from src.outreach import compliance, throttler, warmup, suppress  # noqa: F401
    def c2():
        from app import scheduler  # noqa: F401
    check("outreach (compliance, throttler, warmup, suppress)", c1)
    check("app.scheduler", c2)

    # === Phase D: outreach engine ===
    print("\nPhase D: outreach engine + variants + analytics")
    def d1():
        from src.outreach import template, variants, personalize, queue, sender, instantly  # noqa: F401
        from src.outreach.template import FRAMEWORKS
        assert len(FRAMEWORKS) >= 5, f"need 5 frameworks, got {len(FRAMEWORKS)}"
        print(f"    Frameworks: {list(FRAMEWORKS.keys())}")
    def d2():
        from src.analytics import warmup_metrics, reply_rate, compliance_audit  # noqa: F401
    check("outreach (template, variants, personalize, queue, sender, instantly)", d1)
    check("analytics (warmup, reply, audit)", d2)

    # === Phase E: leads + scraping ===
    print("\nPhase E: leads + scraping")
    def e1():
        from src.leads import dedupe, enrich, store  # noqa: F401
    def e2():
        from src.leads.sources import google_cse, gmaps  # noqa: F401
        assert callable(google_cse.search)
        assert callable(gmaps.search)
    check("leads (dedupe, enrich, store)", e1)
    check("leads.sources (google_cse, gmaps)", e2)

    # === DB schema ===
    print("\nDatabase schema (12 tables)")
    from src import db as _db
    expected = {
        "threads", "triage", "drafts", "leads", "campaigns",
        "campaign_variants", "send_jobs", "sent_log", "mailboxes",
        "suppression", "snoozes", "compliance_audit",
    }
    rows = _db.query_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    found = {r["name"] for r in rows}
    missing = expected - found
    if missing:
        print(f"  [FAIL] missing tables: {missing}")
        failures.append("db.schema")
    else:
        print(f"  [OK] all 12 tables present: {sorted(found & expected)}")

    # === CLI tools ===
    print("\nCLI tools")
    def cli_scrape():
        import subprocess  # noqa: F401
        r = subprocess.run(
            [sys.executable, "-m", "tools.scrape", "--help"],
            capture_output=True, text=True, cwd=str(PROJECT),
        )
        assert r.returncode == 0, f"scrape --help failed: {r.stderr}"
        assert "google_cse" in r.stdout
    check("tools.scrape --help", cli_scrape)

    # === Streamlit pages parse ===
    print("\nStreamlit pages")
    import ast
    page_dir = PROJECT / "app" / "pages"
    for p in sorted(page_dir.glob("*.py")):
        def parse_page(_path=p):
            with open(_path) as f:
                ast.parse(f.read())
        check(f"page {p.name}", parse_page)

    # === Summary ===
    print("\n=== SUMMARY ===")
    if failures:
        print(f"FAILED: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL E2E OFFLINE CHECKS PASSED")
    print("Live verification (OAuth, Gmail, LLM) requires credentials; see plan section 'Verification'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
