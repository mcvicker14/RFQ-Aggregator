"""USAspending.gov connector — award/competitor intelligence, never promoted to the
pipeline. See docs/PHASE2_ARCHITECTURE.md §8.

Public, keyless API (`POST /api/v2/search/spending_by_award/`). This sandbox's network
egress allowlist blocks api.usaspending.gov directly, so this mapping is written
against the official contract doc in the fedspendingtransparency/usaspending-api GitHub
repo (unblocked):
https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md

**That doc's field-type labels are not trusted at face value anymore.** Two production
incidents have now each hit a field the doc calls `string` that the live API actually
returns as a nested object, and the doc ships no example response bodies to check
against:

1. "Awarding Agency" — documented `string, nullable`; live value is
   `{"name": ..., "agency_slug": ...}`. `psycopg.ProgrammingError: cannot adapt type
   'dict'` on 500/500 fetched awards.
2. "NAICS" — documented `string`; live value is `{"code": "541330", "description":
   "ENGINEERING SERVICES"}`. Same error class, caught immediately and precisely this
   time by `intelligence_sync.py`'s `_validate_connector_fields()` (added after
   incident 1) instead of surfacing as a raw DBAPI error.

Given that pattern repeating, every mapped field below was re-audited by structural
role rather than by re-trusting the doc's type column:

- **Named-entity fields** (Awarding Agency, Awarding Sub Agency, Recipient Name) —
  extracted via `_extract_name()`, which handles both the flat-string and
  `{"name": ...}`-object shapes.
- **Classification/location-code fields** (NAICS, PSC, Place of Performance State/City
  Code) — extracted via `_extract_code()`, which handles the flat-string/number shape
  *and* the `{"code": ..., "description": ...}`-object shape confirmed for NAICS. PSC
  is documented identically to NAICS and is USAspending's sibling classification code
  in the same response, so it gets the same treatment pre-emptively rather than waiting
  for its own production incident. A code field's description is never discarded when
  the object shape is used — `raw_metadata` on every IntelligenceItem always keeps the
  complete original field object (see `_to_raw_intelligence_item`'s `raw=item`), so
  e.g. `raw_metadata["NAICS"]["description"]` survives even though `naics_code` itself
  is stored as the flat code string.
- **Free-text / bare-identifier fields** (Award ID, Description) — no structural
  analogy to either pattern above, so they're deliberately left on `_scalar_str()`,
  which only coerces plain scalars and leaves a dict/list untouched. If one of these
  ever *does* arrive as an object, `_validate_connector_fields()` raises a clear,
  specific error instead of this connector guessing at an extraction key with no
  evidence — see that function's docstring for why silently stringifying an arbitrary
  dict would be worse than failing loud.

`_parse_date()` also no longer silently discards a dict/list value as "no date" — it
passes it through so the same shared validator can catch it, rather than quietly
turning a real-but-oddly-shaped date into a wrong `NULL`.
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
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        # Not a date at all — pass it through so _validate_connector_fields() raises a
        # clear, specific error instead of this silently becoming a wrong NULL, the way
        # a bare `not isinstance(value, str)` check would have (that's exactly how
        # incident 2's NAICS dict would have gone unnoticed if this were a date field).
        return value
    if not isinstance(value, str):
        logger.warning("USAspending connector: could not parse date value %r (unexpected type)", value)
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("USAspending connector: could not parse date value %r", value)
        return None


def _extract_name(value) -> str | None:
    """Named-entity fields (confirmed for Awarding Agency; same shape used for Awarding
    Sub Agency and Recipient Name) return a nested object rather than a flat string on
    some records. Extract the human-readable name either way."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("name") or value.get("agency_name") or value.get("recipient_name")
    return str(value)


def _extract_code(value) -> str | None:
    """Classification/location-code fields (confirmed for NAICS: `{"code": "541330",
    "description": "ENGINEERING SERVICES"}`; PSC is documented identically and treated
    the same pre-emptively; same reasoning covers Place of Performance State/City Code,
    documented as plain numbers but not trusted to stay that way) return a nested
    object on some records instead of the flat string/number the contract doc claims.
    Extract just the code either way — the description isn't lost, it's still in
    raw_metadata via the untouched original item (see module docstring)."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("code")
    return str(value)  # plain number, e.g. a documented-numeric place-of-performance code


def _scalar_str(value) -> str | None:
    """For fields with no structural analogy to a named-entity or coded-classification
    object (Award ID, Description) — coerce a plain scalar to str, but leave dict/list
    untouched rather than guessing at a shape this connector has no evidence for.
    intelligence_sync.py's shared _validate_connector_fields() will catch and clearly
    report those instead of this connector silently mangling data it doesn't
    understand or, worse, stringifying an arbitrary dict into a field with a real
    structured representation."""
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
            "location_city": _extract_code(item.get("Place of Performance City Code")),
            "location_state": _extract_code(item.get("Place of Performance State Code")),
            "naics_code": _extract_code(item.get("NAICS")),
            "psc_code": _extract_code(item.get("PSC")),
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
