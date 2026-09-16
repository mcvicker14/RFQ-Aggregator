"""SAM.gov Get Opportunities v2 connector. Real integration against the public
federal procurement notice API — functional the moment SAM_GOV_API_KEY is set.

**Production incident**: connected and healthy (200 OK, is_configured() true), but a
manual sync returned 0 items. Investigated against SAM.gov's confirmed API behavior
(open.gsa.gov itself is blocked by this sandbox's egress allowlist, same as before, but
its documented parameter names/codes are corroborated by multiple independent
secondary sources this time, not read from memory alone — see below for what's
confirmed vs. what's still a reasoned judgment call):

- **Base URL, `ncode` param name, `postedFrom`/`postedTo` format and 1-year max span,
  `offset`/`limit` pagination, `totalRecords`** — all confirmed correct. Not the bug.
- **No post-fetch bug drops results silently** — `_to_raw_intelligence_item` has no
  unconditional raise (unlike USAspending's required-field check) and every field read
  is `.get()`-defensive, so a non-empty API response can't map down to zero here.
- **The actual cause: the query itself was too narrow to reliably return anything.**
  The default NAICS filter was 4 *exact* codes (541330 + 3 secondary codes), and
  `ncode` is confirmed to support prefix matching ("54" = all professional-services
  NAICS) — exact-coding was leaving real matches on the table by design, and combined
  with the default 30-day lookback window, zero is a very plausible outcome for a
  handful of exact codes in a slow week, not evidence of a broken integration.
  `ptype` (notice type) wasn't being sent at all — omitting it should return every
  type by default, so it isn't what caused *zero*, but SAM.gov's own type roster
  includes non-opportunity notice types (Justification & Approval, Sale of Surplus
  Property, Intent to Bundle) that have no business in this pipeline, so it's now sent
  explicitly rather than relying on an unstated default staying broad forever.
- **Deliberately not added**: an `active`/status request parameter. Multiple sources
  describe SAM.gov's response carrying an `active` field, but none confirm a
  corresponding *request* parameter or its default behavior — given this project has
  now hit two production incidents from trusting an unverified field-shape claim
  (see app/connectors/usaspending.py), a third guessed parameter isn't worth the risk.
  Staleness is instead handled from data already in the response — see
  `_is_expired_opportunity()`.

**Redesign — two stages, per docs/PHASE2_ARCHITECTURE.md §5/§8:**

Stage 1 (`fetch()`'s query parameters) retrieves broadly within Principal's actual
practice: NAICS 5413* (the whole "Architectural, Engineering, and Related Services"
subsector — 541310 through 541380 — not just the single primary code) plus the
configured secondary codes, and all six substantive notice types. Stage 2
(`_score_relevance()` / `_is_expired_opportunity()`) ranks and filters what Stage 1
retrieved against Principal's real profile — keyword relevance, agency/region weight,
set-aside status — so a broader Stage 1 doesn't just flood the app with a bigger
number; results are collected across pagination, scored, sorted best-first, *then*
capped at MAX_RECORDS_PER_SYNC, so the strongest matches survive the cap rather than
whichever page happened to load first.

Parsing stays defensive (every field read with `.get()`) and unmapped notices are
logged rather than silently dropped. Before the next production sync, check a sample
of `raw_metadata` on the resulting rows against this mapping — see
docs/DATA_INGESTION.md.
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

# NAICS 5413* = "Architectural, Engineering, and Related Services" (541310 Architectural,
# 541320 Landscape Architecture, 541330 Engineering, 541340 Drafting, 541350 Building
# Inspection, 541360 Geophysical Surveying, 541370 Surveying and Mapping, 541380 Testing
# Laboratories) — Principal's actual practice, not just its one primary code. SAM.gov's
# ncode filter is confirmed to support prefix matching, so this one prefix covers the
# whole subsector instead of silently missing siblings the way an exact-code list does.
DEFAULT_NAICS_FILTER = ["5413"]

# ptype codes, confirmed: o=Solicitation, p=Presolicitation, k=Combined Synopsis/
# Solicitation, r=Sources Sought, s=Special Notice, a=Award Notice. Deliberately
# excludes notice types that were never pursuable opportunities in the first place
# (Justification & Approval, Sale of Surplus Property, Intent to Bundle Requirements).
NOTICE_TYPE_CODES = ["o", "p", "k", "r", "s", "a"]

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


class SamGovConnector(IntelligenceConnector):
    key = "sam_gov"
    name = "SAM.gov"
    default_category = IntelligenceCategory.LIVE_OPPORTUNITY

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

        # Stage 1: broad-but-bounded retrieval. Defaults to the NAICS 5413* family
        # (the whole A/E subsector) plus Principal's configured secondary codes —
        # see DEFAULT_NAICS_FILTER's docstring for why exact-coding was the actual
        # cause of the zero-results incident this replaced.
        naics_codes = naics_codes or [*DEFAULT_NAICS_FILTER, *settings.PRINCIPAL_SECONDARY_NAICS]

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

        # (score, raw) pairs, collected across every window/page before any cap is
        # applied — Stage 2 needs the full candidate set to sort best-first, not just
        # whichever page happened to load first.
        candidates: list[tuple[int, RawIntelligenceItem]] = []
        retrieved_at = datetime.now(timezone.utc)

        with httpx.Client(timeout=30.0) as client:
            for window_start, window_end in windows:
                offset = 0
                while True:
                    params = {
                        "api_key": settings.SAM_GOV_API_KEY,
                        "limit": min(PAGE_SIZE, MAX_CANDIDATES_TO_SCORE - len(candidates)),
                        "offset": offset,
                        "postedFrom": window_start.strftime("%m/%d/%Y"),
                        "postedTo": window_end.strftime("%m/%d/%Y"),
                        # Confirmed param name; confirmed to support prefix matching.
                        "ncode": ",".join(naics_codes),
                        # Confirmed codes — explicit rather than relying on "omit
                        # ptype = every type" holding true forever (see module
                        # docstring). Sources Sought/Presolicitations included: they're
                        # strategically valuable, never dropped.
                        "ptype": ",".join(NOTICE_TYPE_CODES),
                    }
                    if states:
                        params["state"] = ",".join(states)

                    response = request_with_retry(client, "GET", BASE_URL, params=params)
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
                        candidates.append((score, raw))

                    offset += len(items)
                    if not items or offset >= total_records or len(candidates) >= MAX_CANDIDATES_TO_SCORE:
                        break

                if len(candidates) >= MAX_CANDIDATES_TO_SCORE:
                    break

        # Stage 2: best matches first, then cap — so a broader Stage 1 query means
        # better results, not just a bigger unranked pile capped in arrival order.
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return [raw for _, raw in candidates[:limit]]

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
