"""Gmail OAuth flow with 3 scopes: read, compose, send.

Scopes are scoped to least-privilege per Google's recommendations:
  - gmail.readonly  : list/get threads, search
  - gmail.compose   : create/update drafts (no send)
  - gmail.send      : actually send mail

`force_reconsent()` deletes token.json when scopes change. Google does
NOT re-prompt the user when you add a scope to an existing token, so
we have to drop the cached token manually.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from app import paths


# Minimal scopes for the v1 use case. If you need labels.modify in the
# future, also request https://www.googleapis.com/auth/gmail.modify.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]


def credentials_path() -> Path:
    return paths.CREDENTIALS_PATH


def token_path(account: str = "default") -> Path:
    """One token per Gmail account we authenticate as."""
    if account == "default" or not account:
        return paths.TOKEN_PATH
    safe = "".join(c for c in account if c.isalnum() or c in "._-@")
    return paths.DATA_DIR / f"token_{safe}.json"


def force_reconsent(account: str = "default") -> None:
    """Delete the cached token so the next call to get_credentials() re-prompts."""
    p = token_path(account)
    if p.exists():
        p.unlink()


def get_credentials(account: str = "default"):
    """Run the InstalledAppFlow if needed; otherwise load cached creds.

    For multi-account rotation (sender.py), call get_credentials(account=email)
    once per account to cache each one separately.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds: Optional[Credentials] = None
    tpath = token_path(account)
    cpath = credentials_path()

    if not cpath.exists():
        raise FileNotFoundError(
            f"OAuth client secrets not found at {cpath}.\n"
            f"Create a Google Cloud project, enable Gmail API, create an "
            f"OAuth 2.0 Client ID of type 'Desktop app', and save the JSON "
            f"as {cpath}."
        )

    if tpath.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(cpath), SCOPES)
            # run_local_server opens a browser tab on http://localhost:xxxx
            creds = flow.run_local_server(port=0)
        # Persist
        tpath.write_text(creds.to_json(), encoding="utf-8")

    return creds
