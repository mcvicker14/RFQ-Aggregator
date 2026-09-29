"""Minimal Google Sheets API v4 client for the SOQ Status Board integration — see
app/services/status_board_sync.py for the write mechanism this supports.

Auth is a Google **service account** (server-to-server, no interactive user): the
account's JSON key is read from the GOOGLE_SERVICE_ACCOUNT_JSON environment variable
(never committed, never hard-coded — see app/core/config.py), and google-auth handles
signing the JWT assertion, exchanging it for a bearer access token, and caching/
refreshing that token. The actual Sheets API calls are made with this app's own httpx
client + request_with_retry, the same pattern every other connector in
app/connectors/ uses, rather than pulling in the much heavier google-api-python-client
just for two REST calls.

This module knows nothing about the SOQ Status Board's row/column layout — that's
status_board_sync.py's job. It only knows how to read a range and how to atomically
insert-and-populate one row.
"""
import json
import logging
from functools import lru_cache

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.service_account import Credentials

from app.connectors.http_retry import request_with_retry
from app.core.config import get_settings

logger = logging.getLogger(__name__)

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsNotConfiguredError(RuntimeError):
    """GOOGLE_SERVICE_ACCOUNT_JSON (or SOQ_STATUS_BOARD_SPREADSHEET_ID) isn't set.
    Distinct from GoogleSheetsApiError so callers can show "not configured yet"
    rather than "temporary failure, retry" — see docs the sync service returns."""


class GoogleSheetsApiError(RuntimeError):
    """A configured request to the Sheets API failed (auth, network, or a non-2xx
    response) after retries. Always safe to retry later — see status_board_sync.py."""


@lru_cache
def _load_credentials() -> Credentials:
    settings = get_settings()
    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        raise GoogleSheetsNotConfiguredError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not set — the Status Board sync is not configured."
        )
    try:
        info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as exc:
        raise GoogleSheetsNotConfiguredError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON — paste the full service account key file contents."
        ) from exc
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def _get_access_token() -> str:
    """Returns a valid bearer token, refreshing (and re-signing/exchanging) only when
    the cached one is missing or expired — google-auth tracks this internally on the
    Credentials object itself, so repeated calls within a token's ~1hr lifetime are free."""
    creds = _load_credentials()
    if not creds.valid:
        creds.refresh(GoogleAuthRequest())
    assert creds.token
    return creds.token


def _spreadsheet_id() -> str:
    settings = get_settings()
    if not settings.SOQ_STATUS_BOARD_SPREADSHEET_ID:
        raise GoogleSheetsNotConfiguredError("SOQ_STATUS_BOARD_SPREADSHEET_ID is not set.")
    return settings.SOQ_STATUS_BOARD_SPREADSHEET_ID


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.GOOGLE_SERVICE_ACCOUNT_JSON and settings.SOQ_STATUS_BOARD_SPREADSHEET_ID)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_get_access_token()}"}


def read_range(a1_range: str) -> list[list[str]]:
    """Returns the raw `values` grid for a range, one list per row, trailing blank
    cells/rows within the requested range trimmed (standard Sheets API behavior) — a
    row with nothing in it may be `[]` or simply absent past the last real row, so
    callers must index defensively rather than assume every row has every column.
    """
    url = f"{SHEETS_API_BASE}/{_spreadsheet_id()}/values/{a1_range}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = request_with_retry(client, "GET", url, headers=_auth_headers())
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError, GoogleAuthError) as exc:
        raise GoogleSheetsApiError(f"Failed to read {a1_range} from the Status Board sheet: {exc}") from exc
    if response.status_code != 200:
        raise GoogleSheetsApiError(
            f"Status Board sheet read failed ({response.status_code}): {response.text[:500]}"
        )
    return response.json().get("values", [])


def insert_and_write_row(
    *, sheet_id: int, row_index_0based: int, values: list[str], inherit_format_from_row_above: bool = True
) -> None:
    """Atomically inserts one new row at `row_index_0based` (0-indexed grid position —
    sheet row number = row_index_0based + 1), shifting that row and everything below it
    down by one, and writes `values` into the freshly-inserted (now-blank) row — in a
    single batchUpdate call, so this can never leave a half-written blank row behind:
    either both the insert and the write land, or (on any failure) neither does.

    Every existing row's *content* is preserved exactly; only row numbers below the
    insertion point shift down by one, the same as a human choosing "Insert row above"
    in the Sheets UI. Callers are responsible for choosing a row_index_0based that is
    actually safe (see status_board_sync.py's insertion-point search) — this function
    performs no structural validation of its own.
    """
    row_data = {
        "values": [{"userEnteredValue": {"stringValue": v}} for v in values]
    }
    requests = [
        {
            "insertDimension": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": row_index_0based, "endIndex": row_index_0based + 1},
                "inheritFromBefore": inherit_format_from_row_above,
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_index_0based,
                    "endRowIndex": row_index_0based + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(values),
                },
                "rows": [row_data],
                "fields": "userEnteredValue",
            }
        },
    ]
    url = f"{SHEETS_API_BASE}/{_spreadsheet_id()}:batchUpdate"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = request_with_retry(client, "POST", url, headers=_auth_headers(), json={"requests": requests})
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError, GoogleAuthError) as exc:
        raise GoogleSheetsApiError(f"Failed to write the new row to the Status Board sheet: {exc}") from exc
    if response.status_code != 200:
        raise GoogleSheetsApiError(
            f"Status Board sheet write failed ({response.status_code}): {response.text[:500]}"
        )
