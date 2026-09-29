"""HTTP client for the SOQ Status Board Google Apps Script webhook — see
app/services/status_board_sync.py for the field mapping and sync orchestration that
uses this, and google-apps-script/status_board_sync.gs (in the repo root) for what
actually receives these requests and writes to the spreadsheet.

This app never authenticates to Google directly and holds no Google credentials of any
kind — the Apps Script Web App, running as its own owner inside Google's
infrastructure, is the only thing that ever reads or writes the sheet. Authentication
from this app to that webhook is a shared secret carried in the JSON body rather than
an HTTP header: Apps Script Web Apps (doPost(e)) do not reliably expose custom request
headers to the script, so a header-based secret would silently fail to be checked.
"""
import logging

import httpx

from app.connectors.http_retry import request_with_retry
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class StatusBoardWebhookNotConfiguredError(RuntimeError):
    """STATUS_BOARD_WEBHOOK_URL or STATUS_BOARD_WEBHOOK_SECRET isn't set. Distinct from
    StatusBoardWebhookError so callers can show "not configured yet" rather than
    "temporary failure, retry" — see how status_board_sync.py uses this."""


class StatusBoardWebhookError(RuntimeError):
    """The webhook call itself failed — network/timeout/non-2xx/unparseable response —
    after retries. Always safe to retry later — see status_board_sync.py. Distinct
    from a well-formed `{"ok": false, ...}` response, which is returned normally (not
    raised): that's the Apps Script correctly reporting a business-level failure (bad
    secret, sheet structure problem) rather than this client failing to reach it."""


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.STATUS_BOARD_WEBHOOK_URL and settings.STATUS_BOARD_WEBHOOK_SECRET)


def sync_row(fields: dict[str, str]) -> dict:
    """POSTs one row's fields to the Apps Script webhook and returns its parsed JSON
    response unchanged (callers interpret `ok`/`status`/`error`/`row` themselves — see
    status_board_sync.py). Raises only for a transport-level failure; a structured
    `{"ok": false, ...}` business failure is returned, not raised."""
    settings = get_settings()
    if not is_configured():
        raise StatusBoardWebhookNotConfiguredError(
            "Status Board sync is not configured (STATUS_BOARD_WEBHOOK_URL / "
            "STATUS_BOARD_WEBHOOK_SECRET are not set)."
        )

    payload = {"secret": settings.STATUS_BOARD_WEBHOOK_SECRET, "fields": fields}
    try:
        # follow_redirects=True is required: Apps Script Web App URLs (.../exec)
        # 302-redirect the actual request to a script.googleusercontent.com URL that
        # serves the real response — without this, every call would return a redirect
        # page instead of the webhook's JSON.
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = request_with_retry(client, "POST", settings.STATUS_BOARD_WEBHOOK_URL, json=payload)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
        raise StatusBoardWebhookError(f"Status Board webhook call failed: {exc}") from exc

    if response.status_code != 200:
        raise StatusBoardWebhookError(
            f"Status Board webhook returned HTTP {response.status_code}: {response.text[:500]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise StatusBoardWebhookError(
            f"Status Board webhook returned a non-JSON response: {response.text[:500]}"
        ) from exc
