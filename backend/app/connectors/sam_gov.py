"""SAM.gov Get Opportunities v2 connector. Real integration against the public
federal procurement notice API — functional the moment SAM_GOV_API_KEY is set.

**Production incident, round 2**: the round-1 fix (broadened NAICS + explicit ptype)
still produced Fetched 0 / Created 0 against the real API. The user checked the actual
official GSA API documentation directly — something this sandbox's egress allowlist
blocks Claude from doing itself — and found two of round 1's assumptions wrong:

1. `ncode` is documented as **a single NAICS code, up to 6 digits** — there is no
   documented prefix-search behavior. `"5413"` matching the whole subsector was never
   confirmed against the real API, only inferred from secondary sources (blog posts,
   scraper docs), which is exactly the kind of unverified claim that broke this
   project's USAspending connector twice already. **Corrected**: DEFAULT_NAICS_FILTER
   is now every individual 6-digit code in the family, queried **separately** — see
   below — never combined into one value.
2. `ptype` is documented in the OpenAPI spec as `collectionFormat: multi` — an array
   parameter sent as **repeated query keys** (`ptype=o&ptype=p&...`), not the
   comma-joined string round 1 sent. A comma-joined value for an array-typed parameter
   plausibly matched nothing server-side, which alone could explain the zero. Passing
   a Python list as an httpx params value produces exactly the repeated-key form —
   confirmed directly against httpx's own request-building code in this sandbox
   (`httpx.Request(...).url` — not an assumption about a third party this time).
   `postedFrom`/`postedTo`'s `%m/%d/%Y` formatting was re-checked and is unaffected —
   `strftime("%m/%d/%Y")` already produces exactly `MM/dd/yyyy`.

**This time, the fix ships with its own live evidence instead of another assumption.**
Every `fetch()` call runs three cheap (`limit=1`) diagnostic probes first — see
`_run_diagnostic_probes()` — that isolate which filter, if any, is still zeroing out
results: (A) date range alone, (B) + exact NAICS 541330, (C) + repeated ptype. Their
`totalRecords`, plus the real query's own NAICS-by-NAICS totals, page counts, and
post-relevance-filter count, are attached to the IntelligenceSyncRun and visible in the
Source Manager's sync history — no more diagnosing a live incident by guessing from
outside the system. The API key itself is never included in any recorded diagnostic.

**Retrieval strategy, per the corrected understanding above**: each NAICS code
(Principal's primary + the rest of the 541310–541380 "Architectural, Engineering, and
Related Services" family + configured secondary codes) is queried **separately** —
one exact `ncode` value per request, never combined — and results are merged and
deduped by notice ID before Stage 2 scoring. This costs more requests than a single
combined query would, but every individual request uses only documented, single-value
syntax instead of a speculative multi-value or prefix form.

**Still deliberately not added**: an `active`/status request parameter — nothing
confirms one exists or its default behavior. Staleness is instead handled from the
proposal deadline already in the response — see `_is_expired_opportunity()`.

**Two stages, per docs/PHASE2_ARCHITECTURE.md §5/§8**: Stage 1 (`fetch()`'s per-NAICS
queries) retrieves broadly within Principal's actual practice. Stage 2
(`_score_relevance()` / `_is_expired_opportunity()`) ranks and filters what Stage 1
retrieved against Principal's real profile — keyword relevance, agency/region weight,
set-aside status — so a broader Stage 1 doesn't just flood the app with a bigger
number; results are merged across every NAICS query, scored, sorted best-first, *then*
capped at MAX_RECORDS_PER_SYNC.

Parsing stays defensive (every field read with `.get()`) and unmapped notices are
logged rather than silently dropped. See docs/DATA_INGESTION.md.
"""
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from app.connectors.base import ConnectorNotConfiguredError, IntelligenceConnector, RawIntelligenceItem
from app.connectors.http_retry import request_with_retry
from app.core.config import get_settings
from app.models.enums import IntelligenceCategory, SetAsideType

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://api.sam.gov/prod/opportunities/v2/search"
MAX_RECORDS_PER_SYNC = 500  # cap on IntelligenceItems one sync returns, post-scoring
# Cap on raw SAM.gov notices paged through and scored before selecting the top
# MAX_RECORDS_PER_SYNC — bounds one sync's SAM.gov call volume even though Stage 1's
# broader NAICS-family/notice-type filter can match more than 500 notices in a
# 30-day window, now that it isn't artificially narrowed to a handful of exact codes.
MAX_CANDIDATES_TO_SCORE = 1500
PAGE_SIZE = 100

# The "Architectural, Engineering, and Related Services" NAICS family — Principal's
# actual practice, not just its one primary code. Every code is queried SEPARATELY
# (see fetch()) since ncode is documented as accepting one code, not a prefix or a
# combined list — see module docstring for the incident that corrected this.
DEFAULT_NAICS_FILTER = [
    "541330",  # Engineering Services — Principal's primary code
    "541310",  # Architectural Services
    "541320",  # Landscape Architecture Services
    "541340",  # Drafting Services
    "541350",  # Building Inspection Services
    "541360",  # Geophysical Surveying and Mapping Services
    "541370",  # Surveying and Mapping (except Geophysical) Services
    "541380",  # Testing Laboratories and Services
]

# ptype codes, confirmed: o=Solicitation, p=Presolicitation, k=Combined Synopsis/
# Solicitation, r=Sources Sought, s=Special Notice, a=Award Notice. Deliberately
# excludes notice types that were never pursuable opportunities in the first place
# (Justification & Approval, Sale of Surplus Property, Intent to Bundle Requirements).
# Sent as a list, never comma-joined — ptype is collectionFormat: multi (repeated
# query keys), confirmed directly against httpx's own request-building in this sandbox.
NOTICE_TYPE_CODES = ["o", "p", "k", "r", "s", "a"]

# Diagnostic probes always use a full-year window regardless of the real sync's own
# (possibly much narrower) since — a narrow probe window could itself explain a zero
# and produce a misleading diagnosis. The API's documented max span is exactly 365 days.
DIAGNOSTIC_PROBE_WINDOW_DAYS = 365

# --- Stage 2: Principal relevance scoring ------------------------------------------
#
# Stage 1's NAICS/notice-type filter narrows the fetch to the right ballpark
# server-side, but membership in that ballpark isn't the same as "Principal should
# care about this" — SAM.gov's NAICS field is self-reported by the posting agency and
# often imprecise, so a small drafting task order and an unrelated multi-billion-dollar
# award can both carry the same code. This ranks/filters what Stage 1 retrieved against
# Principal's real profile — civil/water/wastewater/stormwater/utilities/roads/
# transportation/survey/CA/A-E — rather than treating "matched the NAICS filter" as
# the whole answer.
_POSITIVE_KEYWORDS: list[str] = [
    "engineering services", "architect-engineer", "a-e services", "a/e services",
    "civil engineering", "water", "wastewater", "sewer", "stormwater", "drainage",
    "utilities", "utility replacement", "water main", "sewer main", "lift station",
    "pump station", "treatment plant", "roadway", "transportation", "site civil",
    "survey", "construction administration", "idiq", "matoc", "satoc", "design services",
]

# Agencies where Principal has an established or strategically valuable relationship.
_WEIGHTED_AGENCY_KEYWORDS: list[str] = [
    "veterans affairs", "army corps of engineers", "usace", "air force",
    "department of defense", "federal emergency management", "fema",
    "natural resources conservation", "nrcs",
]

_GULF_COAST_SOUTHEAST_STATES = {"LA", "TX", "MS", "AL", "FL", "GA"}

# Calibrated against test fixtures, not arbitrary: NAICS-family membership alone
# (already guaranteed by Stage 1's query) clears this on its own, so the floor mainly
# catches the rare notice that matched the NAICS filter on a technicality but shows no
# other sign of relevance at all — it isn't meant to be a hard gate on top of Stage 1.
MIN_RELEVANCE_SCORE = 2

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

# SAM.gov's own notice `type` -> our intelligence_category. Unknown/unlisted types
# default to LIVE_OPPORTUNITY, matching this connector's pre-Phase-2 behavior (every
# notice became a pipeline Opportunity) — solicitations are the overwhelming majority
# of what this API returns, so that default stays safe. See §5.
_NOTICE_TYPE_CATEGORY: dict[str, IntelligenceCategory] = {
    "solicitation": IntelligenceCategory.LIVE_OPPORTUNITY,
    "combined synopsis/solicitation": IntelligenceCategory.LIVE_OPPORTUNITY,
    "presolicitation": IntelligenceCategory.PRE_SOLICITATION,
    "sources sought": IntelligenceCategory.PRE_SOLICITATION,
    "special notice": IntelligenceCategory.PRE_SOLICITATION,
    "award notice": IntelligenceCategory.AWARD_INTELLIGENCE,
}


def _map_set_aside(description: str | None) -> SetAsideType:
    if not description:
        return SetAsideType.UNRESTRICTED
    text = description.lower()
    for keyword, value in _SET_ASIDE_KEYWORDS:
        if keyword in text:
            return value
    return SetAsideType.UNRESTRICTED


def _map_notice_type(notice_type: str | None) -> IntelligenceCategory:
    if not notice_type:
        return IntelligenceCategory.LIVE_OPPORTUNITY
    return _NOTICE_TYPE_CATEGORY.get(notice_type.strip().lower(), IntelligenceCategory.LIVE_OPPORTUNITY)


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


def _extract_place_of_performance(item: dict) -> tuple[str | None, str | None]:
    """Returns (city, state). Shared by the field mapper and the relevance scorer so
    the two don't drift on how they read the same nested shape."""
    office_address = item.get("officeAddress") or {}
    place_of_performance = item.get("placeOfPerformance") or {}
    state = None
    if isinstance(place_of_performance.get("state"), dict):
        state = place_of_performance["state"].get("code")
    city = None
    if isinstance(place_of_performance.get("city"), dict):
        city = place_of_performance["city"].get("name")
    return city or office_address.get("city"), state or office_address.get("state")


def _score_relevance(item: dict) -> int:
    """Higher means more relevant to Principal's actual A/E practice. Used to (a) drop
    the rare notice that only matched Stage 1's NAICS/notice-type filter on a
    technicality (see MIN_RELEVANCE_SCORE) and (b) sort kept results so the strongest
    matches survive the MAX_RECORDS_PER_SYNC cap first, rather than whichever page of
    the SAM.gov response happened to load first."""
    text = " ".join(str(item.get(key) or "") for key in ("title", "description", "additionalInfoText")).lower()
    score = sum(2 for keyword in _POSITIVE_KEYWORDS if keyword in text)

    naics = (item.get("naicsCode") or "").strip()
    if naics.startswith("5413"):
        score += 3
    elif naics in settings.PRINCIPAL_SECONDARY_NAICS:
        score += 2

    agency_path = (item.get("fullParentPathName") or "").lower()
    if any(keyword in agency_path for keyword in _WEIGHTED_AGENCY_KEYWORDS):
        score += 2

    _, state = _extract_place_of_performance(item)
    if state in _GULF_COAST_SOUTHEAST_STATES:
        score += 1

    set_aside = (item.get("typeOfSetAsideDescription") or "").lower()
    if "service-disabled veteran" in set_aside or "sdvosb" in set_aside:
        score += 2
    elif "small business" in set_aside:
        score += 1

    return score


def _is_expired_opportunity(raw: RawIntelligenceItem) -> bool:
    """A Live Opportunity or Pre-Solicitation past its own proposal deadline isn't
    something Principal can still pursue — keeping it would flood the app with exactly
    the kind of stale-notice noise this redesign is meant to cut. Uses the deadline
    already parsed from the response rather than an unverified 'active' request
    parameter (see module docstring). Award Notices are exempt — they represent
    already-closed procurements by definition, that's not staleness."""
    if raw.intelligence_category not in (IntelligenceCategory.LIVE_OPPORTUNITY, IntelligenceCategory.PRE_SOLICITATION):
        return False
    due = raw.fields.get("proposal_due_at")
    return due is not None and due < datetime.now(timezone.utc)


def _probe(client: httpx.Client, posted_from: date, posted_to: date, **extra_params) -> dict:
    """One minimal (limit=1 — we only need totalRecords, not the records themselves)
    live query. Never returns the request params (which include api_key) — only the
    outcome. Used by both _run_diagnostic_probes() and, indirectly, every real
    per-NAICS query in fetch(), which reads totalRecords the same way."""
    params = {
        "api_key": settings.SAM_GOV_API_KEY,
        "limit": 1,
        "offset": 0,
        "postedFrom": posted_from.strftime("%m/%d/%Y"),
        "postedTo": posted_to.strftime("%m/%d/%Y"),
        **extra_params,
    }
    try:
        response = request_with_retry(client, "GET", BASE_URL, params=params)
    except Exception as exc:
        return {"status_code": None, "total_records": None, "error": str(exc)[:300]}
    if response.status_code != 200:
        return {"status_code": response.status_code, "total_records": None, "error": response.text[:300]}
    return {"status_code": 200, "total_records": response.json().get("totalRecords")}


def _run_diagnostic_probes(client: httpx.Client) -> dict:
    """Test A/B/C from the round-2 production incident: three cheap live queries that
    isolate which filter, if any, is still reducing SAM.gov's own totalRecords to
    zero — evidence for the Source Manager's sync history, not another assumption.
    Always uses a full DIAGNOSTIC_PROBE_WINDOW_DAYS window regardless of the real
    sync's own (possibly narrower) since, so a tight recency window can't itself
    produce a misleading zero here."""
    posted_to = date.today()
    posted_from = posted_to - timedelta(days=DIAGNOSTIC_PROBE_WINDOW_DAYS)
    return {
        "A_baseline_date_range_only": _probe(client, posted_from, posted_to),
        "B_exact_naics_541330": _probe(client, posted_from, posted_to, ncode=settings.PRINCIPAL_PRIMARY_NAICS),
        "C_naics_plus_notice_types": _probe(
            client, posted_from, posted_to, ncode=settings.PRINCIPAL_PRIMARY_NAICS, ptype=NOTICE_TYPE_CODES
        ),
    }


class SamGovConnector(IntelligenceConnector):
    key = "sam_gov"
    name = "SAM.gov"
    default_category = IntelligenceCategory.LIVE_OPPORTUNITY

    def __init__(self):
        # Set at the end of every fetch() call — read by intelligence_sync.run_sync()
        # and attached to the IntelligenceSyncRun so the Source Manager's sync history
        # shows exactly what was queried and what SAM.gov reported, per-field, without
        # anyone needing to check logs. Never contains the API key. None until the
        # first fetch() call completes.
        self.last_run_diagnostics: dict | None = None

    def is_configured(self) -> bool:
        return bool(settings.SAM_GOV_API_KEY)

    def fetch(
        self,
        since: date,
        naics_codes: list[str] | None = None,
        states: list[str] | None = None,
        limit: int = MAX_RECORDS_PER_SYNC,
    ) -> list[RawIntelligenceItem]:
        if not self.is_configured():
            raise ConnectorNotConfiguredError(
                "SAM.gov integration is not configured. Add SAM_GOV_API_KEY to the backend "
                "environment (see backend/.env.example)."
            )

        # Stage 1: broad-but-bounded retrieval, one NAICS code per request — see
        # module docstring for why this is no longer a single combined/prefixed value.
        naics_codes = naics_codes or [*DEFAULT_NAICS_FILTER, *settings.PRINCIPAL_SECONDARY_NAICS]
        seen_codes = set()
        naics_codes = [c for c in naics_codes if not (c in seen_codes or seen_codes.add(c))]

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

        # Keyed by external_id so the same notice matching more than one NAICS query
        # (e.g. a multi-disciplinary IDIQ) is merged, not duplicated.
        candidates: dict[str, tuple[int, RawIntelligenceItem]] = {}
        total_records_by_naics: dict[str, int] = {}
        pages_fetched = 0
        retrieved_at = datetime.now(timezone.utc)

        with httpx.Client(timeout=30.0) as client:
            probes = _run_diagnostic_probes(client)

            for naics_code in naics_codes:
                if len(candidates) >= MAX_CANDIDATES_TO_SCORE:
                    break
                naics_total_across_windows = 0
                for window_start, window_end in windows:
                    offset = 0
                    window_total = 0
                    while True:
                        params = {
                            "api_key": settings.SAM_GOV_API_KEY,
                            "limit": min(PAGE_SIZE, MAX_CANDIDATES_TO_SCORE - len(candidates)),
                            "offset": offset,
                            "postedFrom": window_start.strftime("%m/%d/%Y"),
                            "postedTo": window_end.strftime("%m/%d/%Y"),
                            "ncode": naics_code,  # one exact code — see module docstring
                            "ptype": NOTICE_TYPE_CODES,  # list -> repeated query keys
                        }
                        if states:
                            params["state"] = ",".join(states)

                        response = request_with_retry(client, "GET", BASE_URL, params=params)
                        pages_fetched += 1
                        if response.status_code != 200:
                            logger.error(
                                "SAM.gov API returned %s: %s", response.status_code, response.text[:500]
                            )
                            response.raise_for_status()

                        payload = response.json()
                        items = payload.get("opportunitiesData", [])
                        window_total = payload.get("totalRecords", window_total + len(items))

                        for item in items:
                            try:
                                raw = self._to_raw_intelligence_item(item, retrieved_at)
                            except Exception:
                                logger.exception(
                                    "SAM.gov connector: failed to map notice %s — skipped, not fabricated",
                                    item.get("noticeId", "<unknown>"),
                                )
                                continue
                            if _is_expired_opportunity(raw):
                                continue
                            score = _score_relevance(item)
                            if score < MIN_RELEVANCE_SCORE:
                                continue
                            candidates[raw.external_id] = (score, raw)

                        offset += len(items)
                        if not items or offset >= window_total or len(candidates) >= MAX_CANDIDATES_TO_SCORE:
                            break

                    naics_total_across_windows += window_total
                    if len(candidates) >= MAX_CANDIDATES_TO_SCORE:
                        break
                total_records_by_naics[naics_code] = naics_total_across_windows

        # Stage 2: best matches first, then cap — so a broader Stage 1 means better
        # results, not just a bigger unranked pile capped in arrival order.
        ranked = sorted(candidates.values(), key=lambda pair: pair[0], reverse=True)
        kept = [raw for _, raw in ranked[:limit]]

        self.last_run_diagnostics = {
            "probes": probes,
            "retrieval": {
                "date_window": [posted_from.isoformat(), posted_to.isoformat()],
                "naics_codes_queried": naics_codes,
                "notice_type_codes": NOTICE_TYPE_CODES,
                "total_records_by_naics": total_records_by_naics,
                "pages_fetched": pages_fetched,
                "candidates_before_relevance_filter": len(candidates),
                "records_after_relevance_filter": len(kept),
            },
        }
        return kept

    def _to_raw_intelligence_item(self, item: dict, retrieved_at: datetime) -> RawIntelligenceItem:
        notice_id = item.get("noticeId", "")
        ui_link = item.get("uiLink") or (f"https://sam.gov/opp/{notice_id}/view" if notice_id else None)

        pop_city, pop_state = _extract_place_of_performance(item)

        # First segment of SAM.gov's dot-delimited fullParentPathName is the top-level
        # department (e.g. "Department Of Defense") — stable across notices, unlike
        # the more specific office segments further in. Using the same segment the
        # pre-Phase-2 connector used for Agency.name means promoted opportunities keep
        # resolving to the same existing Agency rows rather than fragmenting into new
        # ones. Office-level granularity (e.g. "New Orleans District") isn't modeled as
        # a structured field on IntelligenceItem yet — it's still fully recoverable
        # from raw_metadata below.
        agency_path = item.get("fullParentPathName")
        agency_name = None
        if agency_path:
            segments = [s.strip() for s in agency_path.split(".") if s.strip()]
            if segments:
                agency_name = segments[0].title()

        fields = {
            "title": item.get("title") or "(untitled SAM.gov notice)",
            "solicitation_number": item.get("solicitationNumber"),
            "agency_name": agency_name,
            "location_city": pop_city,
            "location_state": pop_state,
            "naics_code": item.get("naicsCode"),
            "psc_code": item.get("classificationCode"),
            "set_aside": _map_set_aside(item.get("typeOfSetAsideDescription")),
            "proposal_due_at": _parse_datetime(item.get("responseDeadLine")),
        }

        return RawIntelligenceItem(
            external_id=notice_id,
            intelligence_category=_map_notice_type(item.get("type")),
            source_url=ui_link,
            retrieved_at=retrieved_at,
            fields=fields,
            raw=item,
            confidence="verified_fact",
        )
