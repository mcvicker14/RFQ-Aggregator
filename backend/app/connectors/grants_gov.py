"""Grants.gov connector — federal grant funding announcements. Category is always
EARLY_SIGNAL: a grant landing at a Louisiana parish or state agency is a leading
indicator of the design/engineering RFQ that typically follows, not a procurement
itself, so these are never promoted to the pipeline (EARLY_SIGNAL is never in
PROMOTABLE_CATEGORIES — see app/services/intelligence_sync.py). See
docs/PHASE2_ARCHITECTURE.md §8/§10b.

Public, keyless API (`POST https://api.grants.gov/v1/api/search2`). Unlike
USAspending.gov, this sandbox's egress allowlist blocks every source tried for this
one — grants.gov itself, apify.com, dlthub.com, and a GitHub wiki mirror all returned
EGRESS_BLOCKED — so this mapping is triangulated from several independent third-party
integrations found via web search (an MCP server, an R package, and general search
summaries), which agreed on the core shape (POST body: `oppStatuses`, `rows`,
`startRecordNum`; response: `data.oppHits` array) but disagreed on some exact field
names (`id` vs `opportunityId`, `openDate` vs `postDate`). Rather than guess a single
name, `_first_present()` below tries every candidate name seen across those sources —
this is deliberately more defensive than the SAM.gov/USAspending connectors, which had
a single higher-confidence source to work from. **Verify `raw_metadata` on the first
real sync and simplify `_first_present()` down to whichever name actually appears once
that's confirmed.**

**Production incident**: technically working (116 items imported), but the vast
majority weren't Principal-relevant. Root cause: `_is_relevant()` used to be a
pre-persistence keyword filter here — the exact same architecture mistake round 1 of
the SAM.gov fix made (filter before storage, so a near-miss keyword or an unlisted-but-
genuinely-relevant program is silently lost forever, and nothing survives for
provenance). Removed. Following the same principle the SAM.gov redesign settled on:
retrieve broadly, keep everything fetched for provenance, score for Principal
relevance *after* persistence — see app/services/grants_relevance_scoring.py. Every
successfully-mapped opportunity is now persisted; only a genuine mapping failure (no
id) is still skipped, per IntelligenceConnector's contract.
"""
import logging
from datetime import date, datetime, timezone

import httpx

from app.connectors.base import IntelligenceConnector, RawIntelligenceItem
from app.connectors.http_retry import request_with_retry
from app.models.enums import IntelligenceCategory

logger = logging.getLogger(__name__)

BASE_URL = "https://api.grants.gov/v1/api/search2"
PAGE_SIZE = 100
# Grants.gov posts across every domain (health, arts, agriculture, education...), and
# unlike SAM.gov/USAspending there's no NAICS-equivalent server-side filter available
# here. This bounds one sync's fetch volume — relevance is no longer decided here at
# all (see module docstring), only how much gets paged through and persisted per sync.
MAX_FETCHED_PER_SYNC = 1000


def _first_present(item: dict, *keys: str):
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("Grants.gov connector: could not parse date value %r", value)
    return None


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class GrantsGovConnector(IntelligenceConnector):
    key = "grants_gov"
    name = "Grants.gov"
    default_category = IntelligenceCategory.EARLY_SIGNAL

    def is_configured(self) -> bool:
        return True  # public, keyless API — no credential to check

    def fetch(self, since: date, limit: int = MAX_FETCHED_PER_SYNC) -> list[RawIntelligenceItem]:
        results: list[RawIntelligenceItem] = []
        retrieved_at = datetime.now(timezone.utc)
        start = 0
        fetched = 0

        with httpx.Client(timeout=30.0) as client:
            while fetched < limit:
                body = {
                    "rows": min(PAGE_SIZE, limit - fetched),
                    "startRecordNum": start,
                    "oppStatuses": "forecasted|posted",
                }
                response = request_with_retry(client, "POST", BASE_URL, json=body)
                if response.status_code != 200:
                    logger.error("Grants.gov API returned %s: %s", response.status_code, response.text[:500])
                    response.raise_for_status()

                payload = response.json()
                data = payload.get("data") or {}
                hits = data.get("oppHits", [])
                hit_count = data.get("hitCount", len(hits))

                for item in hits:
                    try:
                        results.append(self._to_raw_intelligence_item(item, retrieved_at))
                    except Exception:
                        logger.exception(
                            "Grants.gov connector: failed to map opportunity %s — skipped, not fabricated",
                            _first_present(item, "id", "opportunityId") or "<unknown>",
                        )

                fetched += len(hits)
                start += len(hits)
                if not hits or start >= hit_count:
                    break

        return results

    def _to_raw_intelligence_item(self, item: dict, retrieved_at: datetime) -> RawIntelligenceItem:
        opp_id = _first_present(item, "id", "opportunityId")
        if opp_id is None:
            raise ValueError("Grants.gov opportunity missing an id — cannot dedupe reliably")

        title = _first_present(item, "title", "opportunityTitle") or "(untitled Grants.gov opportunity)"
        agency_name = _first_present(item, "agencyName")

        # Grants.gov's search response reportedly carries a synopsis and an eligible-
        # applicants description as separate fields (per third-party integrations — see
        # module docstring on this connector's field-name uncertainty generally).
        # Folded into one description so app/services/grants_relevance_scoring.py's
        # recipient-type matching (state/parish/municipal/utility/district/authority —
        # the user's own "strong recipient signals") has real text to check against;
        # that module reads IntelligenceItem.description, not raw_metadata, matching
        # how the SAM.gov scorer only ever reads normalized fields too.
        synopsis = _first_present(item, "description", "synopsis", "opportunitySynopsis")
        eligible_applicants = _first_present(
            item, "eligibleApplicants", "applicantEligibilityDesc", "applicantTypes", "eligibilityDesc"
        )
        description = " ".join(str(p) for p in (synopsis, eligible_applicants) if p) or None

        fields = {
            "title": title,
            "description": description,
            "agency_name": agency_name,
            "funding_award_number": str(_first_present(item, "number", "opportunityNumber") or "") or None,
            "proposal_due_at": _parse_date(_first_present(item, "closeDate")),
            "posted_at": _parse_date(_first_present(item, "openDate", "postDate")),
            "funding_amount": _to_float(_first_present(item, "estimatedFunding", "awardCeiling")),
            # Grants.gov's data model is about funding *opportunities* (forecasted/
            # posted/closed/archived — confirmed no "awarded" status exists), never
            # specific-recipient awards; this connector has no evidence it ever
            # provides real award/recipient data, so awardee_name is deliberately never
            # set here. If a future enhancement ever does have real recipient data,
            # setting this field is what genuinely (not heuristically) flips
            # grants_relevance_scoring's award-vs-opportunity distinction — see that
            # module's docstring.
        }

        return RawIntelligenceItem(
            external_id=str(opp_id),
            intelligence_category=IntelligenceCategory.EARLY_SIGNAL,
            source_url=f"https://www.grants.gov/search-results-detail/{opp_id}",
            retrieved_at=retrieved_at,
            fields=fields,
            raw=item,
            confidence="verified_fact",
        )
