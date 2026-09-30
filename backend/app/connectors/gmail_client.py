"""Minimal Gmail REST API client — read-only (gmail.readonly scope only; this app
never sends, labels, deletes, or modifies anything in the mailbox). Raw httpx calls
against Google's REST endpoints directly, matching every other connector/webhook
client in this codebase (sam_gov.py, grants_gov.py, usaspending.py,
status_board_webhook_client.py) — no google-api-python-client/google-auth SDK
dependency, so this adds zero new third-party packages.

Auth is a standard OAuth2 "installed app" refresh-token flow: GMAIL_CLIENT_ID/
GMAIL_CLIENT_SECRET identify the Google Cloud OAuth app, GMAIL_REFRESH_TOKEN is a
long-lived credential obtained ONCE via a one-time interactive consent flow the account
owner runs themselves (see scripts/gmail_oauth_setup.py) — this app never sees or
handles the user's Google password, only the refresh token they explicitly generate
and paste into Render's environment variables afterward. An access token is minted
from the refresh token on demand (short-lived, ~1 hour) and never persisted.
"""
import logging

import httpx

from app.connectors.http_retry import request_with_retry
from app.core.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailNotConfiguredError(RuntimeError):
    """GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN isn't fully set."""


class GmailApiError(RuntimeError):
    """A Gmail API call itself failed (network/timeout/non-2xx) after retries."""


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.GMAIL_CLIENT_ID and settings.GMAIL_CLIENT_SECRET and settings.GMAIL_REFRESH_TOKEN)


def get_access_token(client: httpx.Client) -> str:
    settings = get_settings()
    if not is_configured():
        raise GmailNotConfiguredError(
            "Gmail integration is not configured. Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, "
            "and GMAIL_REFRESH_TOKEN (see backend/.env.example and scripts/gmail_oauth_setup.py)."
        )
    response = request_with_retry(client, "POST", TOKEN_URL, data={
        "client_id": settings.GMAIL_CLIENT_ID,
        "client_secret": settings.GMAIL_CLIENT_SECRET,
        "refresh_token": settings.GMAIL_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    })
    if response.status_code != 200:
        raise GmailApiError(f"Gmail token refresh failed: HTTP {response.status_code}: {response.text[:500]}")
    token = response.json().get("access_token")
    if not token:
        raise GmailApiError(f"Gmail token refresh returned no access_token: {response.text[:300]}")
    return token


def search_message_ids(client: httpx.Client, access_token: str, query: str, max_results: int = 100) -> list[str]:
    """Returns Gmail message IDs matching `query` (Gmail search syntax — see
    https://support.google.com/mail/answer/7190), newest results paged in until
    max_results or Gmail reports no further pages. Read-only: users.messages.list."""
    headers = {"Authorization": f"Bearer {access_token}"}
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < max_results:
        params = {"q": query, "maxResults": min(100, max_results - len(ids))}
        if page_token:
            params["pageToken"] = page_token
        response = request_with_retry(client, "GET", f"{API_BASE}/messages", headers=headers, params=params)
        if response.status_code != 200:
            raise GmailApiError(f"Gmail message search failed: HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        ids.extend(m["id"] for m in payload.get("messages", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_results]


def get_message_plaintext(client: httpx.Client, access_token: str, message_id: str) -> dict:
    """Returns {"id", "subject", "date_header", "internal_date_ms", "body_text"} for
    one message. format=full gives the full MIME structure; body_text is decoded from
    the first text/plain part found (falling back to text/html stripped of tags if no
    plain part exists — forwarded COREWORKS emails always have a text/plain part in
    practice, confirmed against real examples, but this fallback keeps a connector-level
    error from being the only option if a future forward client ever omits one)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    response = request_with_retry(
        client, "GET", f"{API_BASE}/messages/{message_id}", headers=headers, params={"format": "full"}
    )
    if response.status_code != 200:
        raise GmailApiError(f"Gmail message fetch failed for {message_id}: HTTP {response.status_code}: {response.text[:500]}")
    payload = response.json()

    header_list = payload.get("payload", {}).get("headers", [])
    headers_by_name = {h["name"].lower(): h["value"] for h in header_list}

    body_text = _extract_body_text(payload.get("payload", {}))

    return {
        "id": payload.get("id", message_id),
        "subject": headers_by_name.get("subject", ""),
        "date_header": headers_by_name.get("date", ""),
        "internal_date_ms": payload.get("internalDate"),
        "body_text": body_text,
    }


def _decode_base64url(data: str) -> str:
    import base64
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    import html as html_module
    return html_module.unescape(text)


def _extract_body_text(mime_part: dict) -> str:
    mime_type = mime_part.get("mimeType", "")
    body_data = mime_part.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return _decode_base64url(body_data)

    html_fallback = None
    for part in mime_part.get("parts", []) or []:
        part_type = part.get("mimeType", "")
        if part_type == "text/plain" and part.get("body", {}).get("data"):
            return _decode_base64url(part["body"]["data"])
        if part_type == "text/html" and part.get("body", {}).get("data") and html_fallback is None:
            html_fallback = part["body"]["data"]
        if part_type.startswith("multipart/"):
            nested = _extract_body_text(part)
            if nested:
                return nested

    if mime_type == "text/html" and body_data:
        html_fallback = html_fallback or body_data
    if html_fallback:
        return _strip_html(_decode_base64url(html_fallback))
    return ""
