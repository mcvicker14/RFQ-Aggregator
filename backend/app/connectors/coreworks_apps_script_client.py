"""HTTP client for the COREWORKS RFQwire Google Apps Script — see
app/connectors/gmail_coreworks.py for the parsing logic that consumes this, and
google-apps-script/coreworks_sync.gs (in the repo root) for what actually runs inside
Gmail and answers these requests.

This app never authenticates to Google directly and holds no Gmail/Google credentials
of any kind — the Apps Script, authorized directly against the Gmail account that
receives forwarded COREWORKS digest emails, is the only thing that ever reads that
mailbox. Authentication from this app to the script is a shared secret carried in the
JSON body rather than an HTTP header — same reasoning as
status_board_webhook_client.py: Apps Script Web Apps (doPost(e)) do not reliably expose
custom request headers to the script, so a header-based secret would silently fail to
be checked.
"""
import logging
from datetime import date

import httpx

from app.connectors.http_retry import request_with_retry
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class CoreworksAppsScriptNotConfiguredError(RuntimeError):
    """COREWORKS_APPS_SCRIPT_URL or COREWORKS_WEBHOOK_SECRET isn't set."""


class CoreworksAppsScriptError(RuntimeError):
    """The Apps Script call itself failed — network/timeout/non-2xx/unparseable
    response, or a well-formed {"ok": false, ...} business failure (bad secret on its
    side, Gmail search error) — either way, always safe to retry later."""


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.COREWORKS_APPS_SCRIPT_URL and settings.COREWORKS_WEBHOOK_SECRET)


def scan(since: date) -> list[dict]:
    """Asks the Apps Script to search the Gmail account for confirmed COREWORKS
    RFQwire messages received on/after `since` that it hasn't already returned (it
    tracks that itself via a Gmail label — see the .gs file), and returns them as a
    list of {"id", "body_text", "internal_date_ms"} dicts — the same shape
    gmail_client.py's now-retired get_message_plaintext() used to return, which is all
    app/connectors/gmail_coreworks.py's parsing functions need. Used for this app's own
    on-demand "Sync Now" / scheduled pull; the Apps Script's own time-driven trigger
    additionally PUSHES newly found messages straight to the coreworks-ingest webhook
    without waiting to be asked — see app/api/routes/coreworks_ingest.py."""
    settings = get_settings()
    if not is_configured():
        raise CoreworksAppsScriptNotConfiguredError(
            "COREWORKS RFQwire sync is not configured (COREWORKS_APPS_SCRIPT_URL / "
            "COREWORKS_WEBHOOK_SECRET are not set)."
        )

    payload = {"secret": settings.COREWORKS_WEBHOOK_SECRET, "action": "scan", "since": since.isoformat()}
    try:
        # follow_redirects=True: Apps Script Web App URLs (.../exec) 302-redirect the
        # actual request to a script.googleusercontent.com URL that serves the real
        # response — see status_board_webhook_client.py for the same requirement.
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = request_with_retry(client, "POST", settings.COREWORKS_APPS_SCRIPT_URL, json=payload)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
        raise CoreworksAppsScriptError(f"COREWORKS Apps Script call failed: {exc}") from exc

    if response.status_code != 200:
        raise CoreworksAppsScriptError(
            f"COREWORKS Apps Script returned HTTP {response.status_code}: {response.text[:500]}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise CoreworksAppsScriptError(
            f"COREWORKS Apps Script returned a non-JSON response: {response.text[:500]}"
        ) from exc

    if not body.get("ok"):
        raise CoreworksAppsScriptError(f"COREWORKS Apps Script reported an error: {body.get('message', body)}")
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise CoreworksAppsScriptError(f"COREWORKS Apps Script response missing a 'messages' list: {body}")
    return messages


def mark_processed(message_ids: list[str]) -> None:
    """Tells the Apps Script these message ids were successfully retrieved and parsed
    (scan()'s caller already has fully usable RawIntelligenceItems from them), so it can
    label them and never return them from scan() again. Called only after a scan()
    result has been fully parsed without this app needing to raise — see
    CoreworksRfqwireConnector.fetch(). Deliberately non-fatal: a failure here only means
    these specific messages may be scanned and (harmlessly, idempotently) re-parsed on
    the next sync, never that any data is lost — so callers should log and continue
    rather than let this fail an otherwise-successful sync."""
    settings = get_settings()
    if not is_configured() or not message_ids:
        return
    payload = {"secret": settings.COREWORKS_WEBHOOK_SECRET, "action": "mark_processed", "message_ids": message_ids}
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = request_with_retry(client, "POST", settings.COREWORKS_APPS_SCRIPT_URL, json=payload)
    if response.status_code != 200:
        raise CoreworksAppsScriptError(
            f"COREWORKS Apps Script mark_processed returned HTTP {response.status_code}: {response.text[:500]}"
        )
