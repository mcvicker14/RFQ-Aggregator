"""SAM.gov Get Opportunities v2 connector. Real integration against the public
federal procurement notice API — functional the moment SAM_GOV_API_KEY is set.

IMPORTANT — read before relying on this in production: this sandbox's network egress
allowlist blocks documentation sites (open.gsa.gov, govconapi.com, etc.), so the field
mapping below was written from well-established public knowledge of this stable,
widely-documented API rather than a live fetch of today's exact schema. Parsing is
defensive (every field read with .get(), nothing crashes on a missing/renamed key) and
unmapped notices are reported rather than silently dropped. Before the first real
production sync, run one manual sync, inspect `raw_snapshot` on the resulting
OpportunitySource rows, and adjust `_map_fields()` if anything has drifted. See
docs/DATA_INGESTION.md.
"""
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from app.core.config import get_settings
from app.connectors.base import ConnectorNotConfiguredError, OpportunityConnector, RawOpportunity
from app.models.enums import SetAsideType

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://api.sam.gov/prod/opportunities/v2/search"
MAX_RECORDS_PER_SYNC = 500
PAGE_SIZE = 100

# Best-known mapping of SAM.gov's typeOfSetAsideDescription free text to our enum.
# Matched by substring, case-insensitive, most-specific first.
_SET_ASIDE_KEYWORDS: list[tuple[str, SetAsideType]] = [
    ("service-disabled veteran", SetAsideType.SDVOSB),
    ("sdvosb", SetAsideType.SDVOSB),
    ("8(a)", SetAsideType.EIGHT_A),
    ("hubzone", SetAsideType.HUBZONE),
    ("edwosb", SetAsideType.EDWOSB),
    ("economically disadvantaged women", SetAsideType.EDWOSB),
    ("women-owned", SetAsideType.WOSB),
    ("wosb", SetAsideType.WOSB),
    ("total small business", SetAsideType.SMALL_BUSINESS),
    ("small business", SetAsideType.SMALL_BUSINESS),
]


def _map_set_aside(description: str | None) -> SetAsideType:
    if not description:
        return SetAsideType.UNRESTRICTED
    text = description.lower()
    for keyword, value in _SET_ASIDE_KEYWORDS:
        if keyword in text:
            return value
    return SetAsideType.UNRESTRICTED


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("SAM.gov connector: could not parse datetime value %r", value)
    return None


class SamGovConnector(OpportunityConnector):
    name = "SAM.gov"

    def is_configured(self) -> bool:
        return bool(settings.SAM_GOV_API_KEY)

    def fetch(
        self,
        since: date,
        naics_codes: list[str] | None = None,
        states: list[str] | None = None,
        limit: int = MAX_RECORDS_PER_SYNC,
    ) -> list[RawOpportunity]:
        if not self.is_configured():
            raise ConnectorNotConfiguredError(
                "SAM.gov integration is not configured. Add SAM_GOV_API_KEY to the backend "
                "environment (see backend/.env.example)."
            )

        naics_codes = naics_codes or [settings.PRINCIPAL_PRIMARY_NAICS, *settings.PRINCIPAL_SECONDARY_NAICS]

        posted_from = since
        posted_to = date.today()
        # SAM.gov's date range is capped at ~1 year; page backward in <=1yr windows.
        windows: list[tuple[date, date]] = []
        cursor = posted_from
        while cursor < posted_to:
            window_end = min(posted_to, cursor + timedelta(days=364))
            windows.append((cursor, window_end))
            cursor = window_end + timedelta(days=1)
        if not windows:
            windows = [(posted_from, posted_to)]

        results: list[RawOpportunity] = []
        retrieved_at = datetime.now(timezone.utc)

        with httpx.Client(timeout=30.0) as client:
            for window_start, window_end in windows:
                offset = 0
                while True:
                    params = {
                        "api_key": settings.SAM_GOV_API_KEY,
                        "limit": min(PAGE_SIZE, limit - len(results)),
                        "offset": offset,
                        "postedFrom": window_start.strftime("%m/%d/%Y"),
                        "postedTo": window_end.strftime("%m/%d/%Y"),
                        # Best-known param name for a comma-separated NAICS filter.
                        "ncode": ",".join(naics_codes),
                    }
                    if states:
                        params["state"] = ",".join(states)

                    response = client.get(BASE_URL, params=params)
                    if response.status_code != 200:
                        logger.error(
                            "SAM.gov API returned %s: %s", response.status_code, response.text[:500]
                        )
                        response.raise_for_status()

                    payload = response.json()
                    items = payload.get("opportunitiesData", [])
                    total_records = payload.get("totalRecords", len(items))

                    for item in items:
                        try:
                            results.append(self._to_raw_opportunity(item, retrieved_at))
                        except Exception:
                            logger.exception(
                                "SAM.gov connector: failed to map notice %s — skipped, not fabricated",
                                item.get("noticeId", "<unknown>"),
                            )

                    offset += len(items)
                    if not items or offset >= total_records or len(results) >= limit:
                        break

                if len(results) >= limit:
                    break

        return results

    def _to_raw_opportunity(self, item: dict, retrieved_at: datetime) -> RawOpportunity:
        notice_id = item.get("noticeId", "")
        ui_link = item.get("uiLink") or (f"https://sam.gov/opp/{notice_id}/view" if notice_id else None)

        office_address = item.get("officeAddress") or {}
        place_of_performance = item.get("placeOfPerformance") or {}
        pop_state = None
        if isinstance(place_of_performance.get("state"), dict):
            pop_state = place_of_performance["state"].get("code")
        pop_city = None
        if isinstance(place_of_performance.get("city"), dict):
            pop_city = place_of_performance["city"].get("name")

        fields = {
            "title": item.get("title") or "(untitled SAM.gov notice)",
            "solicitation_number": item.get("solicitationNumber"),
            "agency_path": item.get("fullParentPathName"),
            "location_city": pop_city or office_address.get("city"),
            "location_state": pop_state or office_address.get("state"),
            "naics_code": item.get("naicsCode"),
            "psc_code": item.get("classificationCode"),
            "set_aside": _map_set_aside(item.get("typeOfSetAsideDescription")),
            "proposal_due_at": _parse_datetime(item.get("responseDeadLine")),
            "opportunity_source_label": "SAM.gov",
            "notice_type": item.get("type"),
            "external_notice_id": notice_id,
        }

        return RawOpportunity(
            external_id=notice_id,
            source="SAM.gov",
            source_url=ui_link,
            retrieved_at=retrieved_at,
            fields=fields,
            raw=item,
            confidence="verified_fact",
        )
