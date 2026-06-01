"""Jobber OAuth 2.0 + GraphQL client for the engine (Layer 1, read-only).

Single responsibility: hand other tools an authenticated `graphql(query, variables)` call
against Jobber's API. Imported by the Jobber tools; also runnable for the one-time
`--authorize` bootstrap and a `--smoke` connectivity test.

Read-only by design: this module only issues the read QUERIES the tools build. The app's
OAuth scopes (set once in the Developer Center) are read Clients + read Requests, so there
is no capability to mutate Jobber data in this layer.

OAuth (confirmed against developer.getjobber.com):
  authorize : https://api.getjobber.com/api/oauth/authorize
  token     : https://api.getjobber.com/api/oauth/token  (authorization_code | refresh_token)
  Access token expires ~60 min. "Refresh Token Rotation" (an app setting) may return a NEW
  refresh token on every refresh, so we persist whatever the token endpoint returns.

GraphQL:
  endpoint  : https://api.getjobber.com/api/graphql
  headers   : Authorization: Bearer <token>, Content-Type: application/json,
              X-JOBBER-GRAPHQL-VERSION: <JOBBER_API_VERSION>   (REQUIRED on every request)
  throttling: HTTP 429 and/or GraphQL error code THROTTLED; extensions.cost.throttleStatus
              (currentlyAvailable / restoreRate) drives the backoff.

Secrets come from .env (JOBBER_CLIENT_ID/SECRET/REDIRECT_URI/API_VERSION). Tokens are
persisted to gitignored jobber_token.json. Nothing secret is committed.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from dotenv import load_dotenv

from jobber_queries import SMOKE_QUERY

AUTHORIZE_URL = "https://api.getjobber.com/api/oauth/authorize"
TOKEN_URL = "https://api.getjobber.com/api/oauth/token"
GRAPHQL_URL = "https://api.getjobber.com/api/graphql"

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / "jobber_token.json"

# Refresh this many seconds BEFORE the stated expiry, to avoid edge-of-expiry failures.
EXPIRY_BUFFER_SEC = 120
# Bounded retries when throttled, and a hard cap on any single backoff sleep.
MAX_THROTTLE_RETRIES = 5
MAX_BACKOFF_SEC = 60.0


class JobberError(RuntimeError):
    """A GraphQL/HTTP/auth error from Jobber that the caller should surface, not retry."""


# --- config ----------------------------------------------------------------

def _config() -> dict:
    load_dotenv()
    return {
        "client_id": os.environ.get("JOBBER_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("JOBBER_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.environ.get("JOBBER_REDIRECT_URI", "http://localhost:5000/callback").strip(),
        "api_version": os.environ.get("JOBBER_API_VERSION", "").strip(),
    }


def _require(cfg: dict, *keys: str) -> None:
    missing = [f"JOBBER_{k.upper()}" for k in keys if not cfg.get(k)]
    if missing:
        sys.exit(f"ERROR: missing required .env value(s): {', '.join(missing)} (see .env.example).")


# --- token persistence ------------------------------------------------------

def _load_tokens() -> dict | None:
    if TOKEN_PATH.exists():
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    return None


def _store_token_response(resp_json: dict, previous: dict | None) -> dict:
    """Normalize a token response into our stored shape, preserving the existing refresh
    token if the endpoint did not return a new one (i.e. rotation disabled)."""
    now = int(time.time())
    expires_in = int(resp_json.get("expires_in", 3600))
    refresh = resp_json.get("refresh_token") or (previous or {}).get("refresh_token", "")
    tok = {
        "access_token": resp_json["access_token"],
        "refresh_token": refresh,
        "expires_at": now + expires_in,
        "obtained_at": now,
    }
    TOKEN_PATH.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    return tok


# --- one-time authorization (auth-code flow with a local redirect catcher) --

class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802 (http.server API)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.code = (params.get("code") or [None])[0]
        _CallbackHandler.state = (params.get("state") or [None])[0]
        _CallbackHandler.error = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = ("Authorization failed: " + _CallbackHandler.error) if _CallbackHandler.error \
            else "Authorization received. You can close this tab and return to the terminal."
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode())

    def log_message(self, *args):  # silence default request logging
        pass


def authorize() -> dict:
    cfg = _config()
    _require(cfg, "client_id", "client_secret", "redirect_uri")
    parsed = urllib.parse.urlparse(cfg["redirect_uri"])
    host, port = (parsed.hostname or "localhost"), (parsed.port or 80)
    state = secrets.token_urlsafe(24)

    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
    })
    print("Open this URL in your browser to authorize the app:\n")
    print("  " + url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    server = HTTPServer((host, port), _CallbackHandler)
    print(f"Waiting for the OAuth redirect on {cfg['redirect_uri']} ...")
    try:
        server.handle_request()  # serve exactly one request, then return
    finally:
        server.server_close()

    if _CallbackHandler.error:
        sys.exit(f"ERROR: authorization denied/failed: {_CallbackHandler.error}")
    if not _CallbackHandler.code:
        sys.exit("ERROR: no authorization code received on the redirect.")
    if _CallbackHandler.state != state:
        sys.exit("ERROR: OAuth state mismatch (possible CSRF); aborting.")

    r = requests.post(TOKEN_URL, data={
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "grant_type": "authorization_code",
        "code": _CallbackHandler.code,
        "redirect_uri": cfg["redirect_uri"],
    }, timeout=30)
    if r.status_code != 200:
        sys.exit(f"ERROR: token exchange failed ({r.status_code}): {r.text}")
    _store_token_response(r.json(), None)
    print(f"OK: tokens stored in {TOKEN_PATH.name}. Access token ~60 min; refresh is automatic.")
    return _load_tokens()


# --- access token (with transparent refresh) --------------------------------

def _refresh(cfg: dict, tokens: dict) -> dict:
    _require(cfg, "client_id", "client_secret")
    if not tokens.get("refresh_token"):
        sys.exit("ERROR: no refresh_token stored. Run: python tools/jobber_auth.py --authorize")
    r = requests.post(TOKEN_URL, data={
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }, timeout=30)
    if r.status_code != 200:
        sys.exit(f"ERROR: token refresh failed ({r.status_code}): {r.text}. "
                 "Re-run: python tools/jobber_auth.py --authorize")
    return _store_token_response(r.json(), tokens)


def _access_token() -> str:
    cfg = _config()
    tokens = _load_tokens()
    if not tokens:
        sys.exit("ERROR: not authorized yet. Run: python tools/jobber_auth.py --authorize")
    if int(time.time()) >= tokens.get("expires_at", 0) - EXPIRY_BUFFER_SEC:
        tokens = _refresh(cfg, tokens)
    return tokens["access_token"]


# --- throttle helpers -------------------------------------------------------

def _is_throttled(body: dict) -> bool:
    for err in (body.get("errors") or []):
        if (err.get("extensions") or {}).get("code") == "THROTTLED":
            return True
    return False


def _throttle_wait(body: dict) -> float:
    """Seconds to wait for enough points to restore, from extensions.cost.throttleStatus."""
    cost = (body.get("extensions") or {}).get("cost") or {}
    ts = cost.get("throttleStatus") or {}
    deficit = max(0, (cost.get("requestedQueryCost") or 0) - (ts.get("currentlyAvailable") or 0))
    rate = ts.get("restoreRate") or 1
    return min(MAX_BACKOFF_SEC, max(1.0, deficit / max(rate, 1)))


def _retry_after(resp) -> float:
    try:
        return min(MAX_BACKOFF_SEC, max(1.0, float(resp.headers.get("Retry-After", "2"))))
    except (TypeError, ValueError):
        return 2.0


# --- the public call --------------------------------------------------------

def graphql(query: str, variables: dict | None = None) -> dict:
    """Execute a read query against Jobber's GraphQL API.

    Returns the full parsed JSON ({data, extensions, ...}) so callers can read
    extensions.cost. Refreshes the access token transparently and backs off on
    THROTTLED/429 using the leaky-bucket throttleStatus (bounded retries).
    Raises JobberError on non-retryable HTTP or GraphQL errors.
    """
    cfg = _config()
    _require(cfg, "api_version")
    payload = {"query": query, "variables": variables or {}}

    for attempt in range(MAX_THROTTLE_RETRIES + 1):
        headers = {
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json",
            "X-JOBBER-GRAPHQL-VERSION": cfg["api_version"],
        }
        resp = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=60)

        if resp.status_code == 429:
            if attempt < MAX_THROTTLE_RETRIES:
                time.sleep(_retry_after(resp))
                continue
            raise JobberError(f"Throttled (HTTP 429) after {MAX_THROTTLE_RETRIES} retries.")
        if resp.status_code == 401:
            raise JobberError(f"Unauthorized (401): {resp.text}. Token/scope issue — try --authorize.")
        if resp.status_code != 200:
            raise JobberError(f"HTTP {resp.status_code}: {resp.text}")

        body = resp.json()

        if _is_throttled(body):
            if attempt < MAX_THROTTLE_RETRIES:
                time.sleep(_throttle_wait(body))
                continue
            raise JobberError(f"Throttled (THROTTLED) after {MAX_THROTTLE_RETRIES} retries.")

        if body.get("errors"):
            raise JobberError("GraphQL errors: " + json.dumps(body["errors"], indent=2))

        return body

    raise JobberError("Exhausted throttle retries.")


def cost_summary(body: dict) -> str:
    """One-line cost/throttle summary from a GraphQL response's extensions.cost."""
    cost = (body.get("extensions") or {}).get("cost") or {}
    ts = cost.get("throttleStatus") or {}
    return (f"queryCost requested={cost.get('requestedQueryCost')} "
            f"actual={cost.get('actualQueryCost')} | points "
            f"available={ts.get('currentlyAvailable')}/{ts.get('maximumAvailable')} "
            f"restore={ts.get('restoreRate')}/s")


def resolved_version(body: dict) -> str:
    """The API version Jobber actually resolved the request against (extensions.versioning.version).
    Lets --smoke double as a 'which version am I on?' check vs. JOBBER_API_VERSION in .env."""
    return (((body.get("extensions") or {}).get("versioning") or {}).get("version")) or "(not reported)"


def main() -> None:
    ap = argparse.ArgumentParser(description="Jobber OAuth bootstrap + connectivity test.")
    ap.add_argument("--authorize", action="store_true",
                    help="Run the one-time OAuth consent flow and store tokens.")
    ap.add_argument("--smoke", action="store_true",
                    help="Run a minimal read query and print the cost/throttle status.")
    args = ap.parse_args()

    if args.authorize:
        authorize()
        return
    if args.smoke:
        body = graphql(SMOKE_QUERY)
        total = (((body.get("data") or {}).get("clients") or {}).get("totalCount"))
        print(f"OK: Jobber GraphQL reachable. clients.totalCount={total}")
        print(f"API version resolved: {resolved_version(body)}")
        print(cost_summary(body))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
