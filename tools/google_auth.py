"""Shared Google auth + Sheets service builder for the Jobber engine (Layer 1).

Single responsibility: hand other tools an authenticated Google Sheets service. Imported
by the Sheet tools; runnable standalone only as a consent smoke test.

Least privilege (CLAUDE.md): this layer requests ONLY the Sheets scope. There is no
Gmail / Drive / send scope here — the engine surfaces to a Google Sheet and nothing else.

Credentials are owner-supplied:
  - credentials.json : Google OAuth client (Desktop app), repo root, gitignored.
  - token.json       : created/refreshed automatically on first consent, gitignored.
"""
from __future__ import annotations

import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# --- Least-privilege scope. Sheets only. Do NOT add Gmail/Drive/send scopes here. ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"


def normalize_spreadsheet_id(value: str) -> str:
    """Accept either a bare spreadsheet ID or a full Sheet URL; return the ID."""
    value = value.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", value)
    return match.group(1) if match else value


def _load_credentials() -> Credentials:
    """Load saved token, refresh it, or run the consent flow once."""
    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"Missing {CREDENTIALS_PATH}. Download your Google OAuth client "
                "(Desktop app) as credentials.json into the repo root. See README.md."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def sheets_service():
    """Return an authenticated Google Sheets API service (spreadsheets scope only)."""
    return build("sheets", "v4", credentials=_load_credentials(), cache_discovery=False)


if __name__ == "__main__":
    # Smoke test: trigger the consent flow and confirm the Sheets service builds.
    sheets_service()
    print("OK: Google Sheets service authenticated.")
    print("Granted scopes:", ", ".join(SCOPES))
