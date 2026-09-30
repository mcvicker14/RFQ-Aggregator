"""ONE-TIME setup script for the COREWORKS RFQwire (Gmail) connector — run this
yourself, once, on your own machine, logged into the Gmail account that receives the
forwarded COREWORKS emails. This app never sees or handles your Google password; this
script's only job is to walk you through Google's own consent screen in your browser
and hand you back a long-lived refresh token, which is the only credential the
deployed app itself ever uses (see app/connectors/gmail_client.py).

WHAT YOU NEED FIRST (Google Cloud Console — https://console.cloud.google.com):
  1. Create a project (or use an existing one) — free.
  2. APIs & Services -> Library -> enable the "Gmail API" for that project.
  3. APIs & Services -> OAuth consent screen:
       - User type: External
       - Publishing status: leave it in "Testing" — you do NOT need Google's app
         verification review for this, since only your own account will ever use it.
         Verification is only required once an app is used by people outside a small
         testing-user allowlist, which doesn't apply here.
       - Under "Test users", add the Gmail address that receives the forwarded
         COREWORKS emails (your own address).
  4. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
       - Application type: Desktop app
       - This gives you a Client ID and Client Secret — copy both.

THEN, from backend/ with the venv active:
    pip install -r requirements.txt   # if not already installed
    GMAIL_CLIENT_ID=<paste> GMAIL_CLIENT_SECRET=<paste> python scripts/gmail_oauth_setup.py

This opens your browser to Google's consent screen. Log in as the account that
receives the COREWORKS emails, approve read-only Gmail access, and this script prints
a GMAIL_REFRESH_TOKEN value. Set that, plus GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET, in
Render's environment variables for the backend service (sync: false in render.yaml —
never committed to source control) — see backend/.env.example.
"""
import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


def _capture_authorization_code(expected_state: str) -> str:
    captured: dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib's required method name)
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            if params.get("state", [None])[0] != expected_state:
                self.wfile.write(b"State mismatch -- close this tab and re-run the script.")
                return
            code = params.get("code", [None])[0]
            if code:
                captured["code"] = code
                self.wfile.write(b"Authorized. You can close this tab and return to the terminal.")
            else:
                self.wfile.write(b"No authorization code received -- close this tab and re-run the script.")
            done.set()

        def log_message(self, *args):
            pass  # keep the terminal output clean

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    done.wait(timeout=300)
    server.server_close()
    if "code" not in captured:
        raise RuntimeError("Timed out waiting for Google's authorization redirect.")
    return captured["code"]


def main():
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET (from Google Cloud Console) as "
              "environment variables before running this script. See this file's own "
              "docstring for the Google Cloud Console setup steps.")
        raise SystemExit(1)

    state = secrets.token_urlsafe(16)
    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",   # required to receive a refresh_token at all
        "prompt": "consent",        # required to receive a refresh_token on repeat runs too
        "state": state,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    print(f"Opening your browser to authorize read-only Gmail access...\n{url}\n")
    webbrowser.open(url)

    code = _capture_authorization_code(state)

    response = httpx.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    })
    response.raise_for_status()
    payload = response.json()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        print(
            "No refresh_token in Google's response. This usually means you've already "
            "authorized this exact app before without revoking it — go to "
            "https://myaccount.google.com/permissions, remove this app's access, and "
            "re-run this script."
        )
        raise SystemExit(1)

    print("\nSuccess. Set these in Render's environment variables for the backend service:\n")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={refresh_token}")


if __name__ == "__main__":
    main()
