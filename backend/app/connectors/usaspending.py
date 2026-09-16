"""USAspending.gov connector — award/competitor intelligence, never promoted to the
pipeline. See docs/PHASE2_ARCHITECTURE.md §8.

Public, keyless API (`POST /api/v2/search/spending_by_award/`). This sandbox's network
egress allowlist blocks api.usaspending.gov directly, but the official API contract
lives in the fedspendingtransparency/usaspending-api GitHub repo (unblocked), which was
fetched directly to write this mapping — not guessed from memory. Specifically:
https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md
and .../search_filters.md confirm the exact request/response field names below,
including that NAICS and Description *are* populated for contract-type awards (an
earlier, less-informed assumption in this project's planning notes said otherwise —
corrected here against the real contract doc rather than left unverified).

**Production incident, since fixed**: a live sync fetched 500 real awards, and all 500
failed at persistence with `psycopg.ProgrammingError: cannot adapt type 'dict'`.
Reproduced directly against the real schema: "Awarding Agency" (and, per the same
underlying API pattern, plausibly "Awarding Sub Agency" and "Recipient Name" too) comes
back from the live API as a nested object (its documentation mentions an associated
`agency_slug` field), not the flat string the original field-name-only contract read
implied — this connector was passing that object straight into `agency_name`, a
VARCHAR column, with no scalar extraction. `_extract_name()` below fixes this by
pulling the human-readable name out of either shape. `app/services/intelligence_sync.py`
also gained a shared, generic version of this check for every other connector — see
its `_validate_connector_fields()` — so the next such mismatch fails with an immediate,
specific error instead of a cryptic DBAPI one. Verify `raw_metadata` on the next real
sync and extend `_extract_name()`'s key list if the real shape differs further.
"""
import logging
from datetime import date, datetime, timezone

import httpx

from app.connectors.base import IntelligenceConnector, RawIntelligenceItem
from app.connectors.http_retry import request_with_retry
from app.core.config import get_settings
from app.models.enums import IntelligenceCategory

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
MAX_RECORDS_PER_SYNC = 500
PAGE_SIZE = 100

# BPA Call, Purchase Order, Delivery Order, Definitive Contract — prime contract
# awards. Deliberately excludes grants/loans/IDVs-as-such: this connector answers
# "who won what contract," the classic competitor/incumbent intelligence question.
CONTRACT_AWARD_TYPE_CODES = ["A", "B", "C", "D"]

RESPONSE_FIELDS = [
    "Award ID", "Recipient Name", "Award Amount", "Description",
    "Awarding Agency", "Awarding Sub Agency",
    "Period of Performance Start Date", "Period of Performance Current End Date",
    "Place of Performance State Code", "Place of Performance City Code",
    "NAICS", "PSC", "generated_internal_id",
]


def _parse_date(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("USAspending connector: could not parse date value %r", value)
        return None


def _extract_name(value) -> str | None:
    """Some USAspending fields (confirmed for Awarding Agency; plausibly Awarding Sub
    Agency and Recipient Name too, per the same API pattern) return a nested object
    rather than a flat string. Extract the human-readable name either way."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("name") or value.get("agency_name") or value.get("recipient_name")
    return str(value)


def _scalar_str(value) -> str | None:
    """Coerce a plain scalar (e.g. a number, if a field is number-typed as some are
    documented to be) to str. Leaves dict/list untouched rather than guessing at a
    shape this connector has no evidence for — intelligence_sync.py's shared
    _validate_connector_fields() will catch and clearly report those instead of this
    connector silently mangling data it doesn't understand."""
    if value is None or isinstance(value, (str, dict, list)):
        return value
    return str(value)


class USAspendingConnector(IntelligenceConnector):
    key = "usaspending"
    name = "USAspending.gov"
    default_category = IntelligenceCategory.AWARD_INTELLIGENCE

    def is_configured(self) -> bool:
        return True  # public, keyless API — no credential to check

    def fetch(
        self,
        since: date,
        naics_codes: list[str] | None = None,
        states: list[str] | None = None,
        limit: int = MAX_RECORDS_PER_SYNC,
    ) -> list[RawIntelligenceItem]:
        naics_codes = naics_codes or [settings.PRINCIPAL_PRIMARY_NAICS, *settings.PRINCIPAL_SECONDARY_NAICS]

        filters: dict = {
            "award_type_codes": CONTRACT_AWARD_TYPE_CODES,
            "naics_codes": {"require": naics_codes},
            "time_period": [
                {"start_date": since.isoformat(), "end_date": date.today().isoformat(), "date_type": "action_date"}
            ],
        }
        if states:
            filters["place_of_performance_locations"] = [{"country": "USA", "state": s} for s in states]

        results: list[RawIntelligenceItem] = []
        retrieved_at = datetime.now(timezone.utc)
        page = 1

        with httpx.Client(timeout=30.0) as client:
            while len(results) < limit:
                body = {
                    "filters": filters,
                    "fields": RESPONSE_FIELDS,
                    "page": page,
                    "limit": min(PAGE_SIZE, limit - len(results)),
                    "sort": "Award Amount",
                    "order": "desc",
                }
                response = request_with_retry(client, "POST", BASE_URL, json=body)
                if response.status_code != 200:
                    logger.error("USAspending API returned %s: %s", response.status_code, response.text[:500])
                    response.raise_for_status()

                payload = response.json()
                items = payload.get("results", [])

                for item in items:
                    try:
                        results.append(self._to_raw_intelligence_item(item, retrieved_at))
                    except Exception:
                        logger.exception(
                            "USAspending connector: failed to map award %s — skipped, not fabricated",
                            item.get("internal_id", "<unknown>"),
                        )

                has_next = (payload.get("page_metadata") or {}).get("hasNext", False)
                if not items or not has_next:
                    break
                page += 1

        return results

    def _to_raw_intelligence_item(self, item: dict, retrieved_at: datetime) -> RawIntelligenceItem:
        internal_id = item.get("internal_id")
        if internal_id is None:
            raise ValueError("USAspending award missing internal_id — cannot dedupe reliably")

        generated_id = item.get("generated_internal_id")
        source_url = f"https://www.usaspending.gov/award/{generated_id}" if generated_id else None

        description = _scalar_str(item.get("Description"))
        award_id = _scalar_str(item.get("Award ID"))

        fields = {
            "title": description or award_id or "(untitled USAspending award)",
            "description": description,
            "agency_name": _extract_name(item.get("Awarding Agency")),
            "location_city": _scalar_str(item.get("Place of Performance City Code")),
            "location_state": _scalar_str(item.get("Place of Performance State Code")),
            "naics_code": _scalar_str(item.get("NAICS")),
            "psc_code": _scalar_str(item.get("PSC")),
            "estimated_value_high": item.get("Award Amount"),
            "posted_at": _parse_date(item.get("Period of Performance Start Date")),
            "awardee_name": _extract_name(item.get("Recipient Name")),
            "contract_number": award_id,
            "is_prime_award": True,
        }

        return RawIntelligenceItem(
            external_id=str(internal_id),
            intelligence_category=IntelligenceCategory.AWARD_INTELLIGENCE,
            source_url=source_url,
            retrieved_at=retrieved_at,
            fields=fields,
            raw=item,
            confidence="verified_fact",
        )
