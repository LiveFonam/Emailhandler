"""OAuth init CLI: walk the user through the Gmail consent flow.

Usage:
    python -m tools.oauth_init             # normal consent
    python -m tools.oauth_init --reconsent # delete token, re-prompt
    python -m tools.oauth_init --account you.personal@gmail.com
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gmail import oauth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reconsent", action="store_true",
                    help="Delete existing token.json and re-prompt")
    ap.add_argument("--account", type=str, default="default",
                    help="Account alias (default = first OAuth)")
    args = ap.parse_args()

    if args.reconsent:
        print(f"Deleting cached token for account '{args.account}'...")
        oauth.force_reconsent(args.account)

    print(f"Running OAuth flow for account '{args.account}'...")
    print("A browser tab will open. Sign in and grant the requested scopes.")
    creds = oauth.get_credentials(args.account)
    print("OK. Token cached at:", oauth.token_path(args.account))
    print("Token valid:", bool(creds and creds.valid))
    if creds and creds.expiry:
        print("Token expires:", creds.expiry.isoformat())


if __name__ == "__main__":
    main()
