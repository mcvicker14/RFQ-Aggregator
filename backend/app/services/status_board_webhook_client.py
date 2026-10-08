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


def _post(payload: dict, *, retry: bool = True) -> dict:
    settings = get_settings()
    if not is_configured():
        raise StatusBoardWebhookNotConfiguredError(
            "Status Board sync is not configured (STATUS_BOARD_WEBHOOK_URL / "
            "STATUS_BOARD_WEBHOOK_SECRET are not set)."
        )

    body = {"secret": settings.STATUS_BOARD_WEBHOOK_SECRET, **payload}
    try:
        # follow_redirects=True is required: Apps Script Web App URLs (.../exec)
        # 302-redirect the actual request to a script.googleusercontent.com URL that
        # serves the real response — without this, every call would return a redirect
        # page instead of the webhook's JSON.
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            if retry:
                response = request_with_retry(client, "POST", settings.STATUS_BOARD_WEBHOOK_URL, json=body)
            else:
                # A timeout may occur after the cell changed. Never replay an edit.
                response = client.post(settings.STATUS_BOARD_WEBHOOK_URL, json=body)
    except httpx.HTTPError as exc:
        raise StatusBoardWebhookError("Status Board webhook transport failed; verify connectivity and deployment.") from exc

    if response.status_code != 200:
        raise StatusBoardWebhookError(
            f"Status Board webhook returned HTTP {response.status_code}."
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise StatusBoardWebhookError(
            "Status Board webhook returned a non-JSON response."
        ) from exc
    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
        raise StatusBoardWebhookError("Status Board webhook returned an invalid response envelope.")
    return result


def sync_row(fields: dict[str, str]) -> dict:
    """POSTs one row's fields to the Apps Script webhook and returns its parsed JSON
    response unchanged (callers interpret `ok`/`status`/`error`/`row` themselves — see
    status_board_sync.py). Raises only for a transport-level failure; a structured
    `{"ok": false, ...}` business failure is returned, not raised. Omits "action" (the
    script's original, still-live request shape) rather than sending
    action: "write" explicitly — no behavior difference, kept exactly as this caller
    has always sent it."""
    return _post({"fields": fields})


def read_rows() -> dict:
    """Asks the Apps Script for every current New RFQs row and returns its parsed JSON
    response unchanged (`{"ok": true, "rows": [...]}` or a structured `{"ok": false,
    ...}` business failure — see app/services/status_board_read_sync.py for how the
    caller interprets either). Raises only for a transport-level failure, same as
    sync_row()."""
    result = _post({"action": "read"})
    if result.get("error") == "bad_request" and result.get("message") == "Missing 'fields' object.":
        raise StatusBoardWebhookError(
            "Status Board endpoint does not support action=read. Verify STATUS_BOARD_WEBHOOK_URL "
            "targets the intended Apps Script deployment and publish the reviewed script as a new "
            "version of that deployment. Do not add fields or retry as a write."
        )
    return result


def set_submit(payload: dict) -> dict:
    return _post({"action": "set_submit", **payload}, retry=False)


def reconcile_rows() -> dict:
    """Assign only missing source metadata, then read. No cached decisions sent."""
    return _post({"action": "reconcile"})
