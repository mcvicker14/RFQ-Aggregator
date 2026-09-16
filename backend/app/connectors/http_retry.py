"""Shared retry/backoff for connectors making HTTP calls, so a momentary network blip
doesn't fail an entire sync. Retries transient failures (timeouts, connection errors,
5xx) with exponential backoff; never retries a 4xx (bad request/auth/not found — that
won't succeed on retry and should surface immediately). See
docs/PHASE2_ARCHITECTURE.md §5/§7.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0


def request_with_retry(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Like client.request(), but retries transient failures up to MAX_ATTEMPTS times
    with exponential backoff (2s, 4s). Raises the last exception if every attempt fails."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"{response.status_code} from {url}", request=response.request, response=response
                )
            return response
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt == MAX_ATTEMPTS:
                break
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Request to %s failed (attempt %d/%d): %s — retrying in %.0fs",
                url, attempt, MAX_ATTEMPTS, exc, wait,
            )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc
