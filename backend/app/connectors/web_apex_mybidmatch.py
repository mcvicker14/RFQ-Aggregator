"""APEX MyBidMatch connector — a private, per-subscriber daily bid-match page on
OutreachSystems' mybidmatch.outreachsystems.com platform.

**IMPORTANT — this parser is UNVERIFIED against the real page.** Direct inspection of
the actual subscriber URL was attempted and blocked by this development environment's
network egress policy (confirmed against multiple unrelated domains too, not specific
to this one host — a policy denial, not a transient failure). What this module is
built from instead is OutreachSystems' OWN public support documentation for the
mybidmatch.com platform (found via web search, since that doesn't require fetching the
target domain directly): a per-client PRIVATE page (the `?sub=<GUID>` token identifies
the subscriber), showing a rolling 30-day window of bid matches, organized as dated
groups -- click a date to see that day's matches in a table with columns # / Source /
Agency / FSG (Federal Supply Group) / Title / Keywords -- then click the Title to reach
the actual bid's detail page (on the originating government site, not this platform).

That is GENERAL platform documentation, not a confirmed description of this specific
subscriber's page. _parse_page() below is deliberately isolated into its own function,
tries a structured-feed check first (per "prefer a feed/API if available"), then two
independent HTML-extraction strategies (a table-row reading matching the documented
column layout, and a generic anchor-based fallback for a div/list-based layout) so it
degrades to "found nothing, here's exactly why" — recorded in last_run_diagnostics,
the same way sam_gov.py surfaces retrieval diagnostics — rather than silently returning
wrong data if the real page doesn't match either guess. Whoever next has real access to
the page should treat this function (and it alone) as needing verification/rewrite;
everything downstream of it (field mapping, dedup-against-SAM, relevance scoring,
Discover/Source Manager wiring) does not depend on which extraction strategy succeeds.
"""
import logging
import re
from datetime import date, datetime, timezone

import httpx
from bs4 import BeautifulSoup, Tag

from app.connectors.base import ConnectorNotConfiguredError, IntelligenceConnector, RawIntelligenceItem
from app.connectors.http_retry import request_with_retry
from app.core.config import get_settings
from app.models.enums import IntelligenceCategory, SetAsideType

logger = logging.getLogger(__name__)
settings = get_settings()

SOURCE_NAME = "APEX MyBidMatch"
PAGE_URL = "https://mybidmatch.outreachsystems.com/go?sub=DE69E915-3C54-4C4B-B715-015BE156A230"
MAX_RECORDS_PER_SYNC = 200

# A SAM.gov notice link/id, wherever it shows up in a listing's row or detail page text
# -- reused verbatim so a matching item's source_url is BYTE-IDENTICAL to what
# app/connectors/sam_gov.py itself constructs for the same notice
# (f"https://sam.gov/opp/{notice_id}/view"), which is what lets dedup.py's canonical-
# URL identifier match (added alongside this connector) catch the duplicate without
# needing to guess at APEX's own link format. See module docstring and
# app/services/dedup.py's IDENTIFIER_FIELDS.
_SAM_NOTICE_ID = re.compile(r"sam\.gov/(?:opp|api/prod/opportunities/v\d+/noticedesc)[^A-Za-z0-9]*([A-Za-z0-9]{32})", re.IGNORECASE)
_SAM_URL_FALLBACK = re.compile(r"https?://sam\.gov/opp/([A-Za-z0-9]{32})/view", re.IGNORECASE)

_SET_ASIDE_KEYWORDS: list[tuple[str, SetAsideType]] = [
    ("service-disabled veteran", SetAsideType.SDVOSB), ("sdvosb", SetAsideType.SDVOSB),
    ("8(a)", SetAsideType.EIGHT_A), ("hubzone", SetAsideType.HUBZONE),
    ("edwosb", SetAsideType.EDWOSB), ("women-owned", SetAsideType.WOSB), ("wosb", SetAsideType.WOSB),
    ("total small business", SetAsideType.SMALL_BUSINESS), ("small business", SetAsideType.SMALL_BUSINESS),
]

_NAICS_PATTERN = re.compile(r"\bNAICS\b\D{0,10}(\d{6})", re.IGNORECASE)
_DEADLINE_LABELS = re.compile(r"(?:response|proposal|closing|due)\s*(?:date|deadline)?\s*:?\s*", re.IGNORECASE)
_MONEY_PATTERN = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?", re.IGNORECASE)
# A real timestamp -- date AND time, optionally with an explicit UTC offset or "Z" --
# checked BEFORE _DATE_ONLY_TOKEN below so e.g. "2026-10-07T14:00:00-05:00" is matched
# as the full instant it names, not just its leading "2026-10-07" date portion.
_TIMESTAMP_TOKEN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)\b"
)
# A bare calendar date -- no time-of-day, no timezone/offset -- meaning the source named
# a DAY, not an instant. See _parse_loose_date for why this is anchored differently from
# a real timestamp.
_DATE_ONLY_TOKEN = re.compile(
    r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b"
)


def _extract_sam_notice_id(text: str) -> str | None:
    for pattern in (_SAM_NOTICE_ID, _SAM_URL_FALLBACK):
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _map_set_aside(text: str | None) -> SetAsideType:
    if not text:
        return SetAsideType.UNRESTRICTED
    lowered = text.lower()
    for keyword, value in _SET_ASIDE_KEYWORDS:
        if keyword in lowered:
            return value
    return SetAsideType.UNRESTRICTED


def _extract_naics(text: str) -> str | None:
    match = _NAICS_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_money(text: str) -> float | None:
    match = _MONEY_PATTERN.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = (match.group(2) or "").lower()
    if suffix in ("k", "thousand"):
        value *= 1_000
    elif suffix in ("m", "million"):
        value *= 1_000_000
    return value


def _parse_loose_date(text: str) -> datetime | None:
    """Finds a deadline-shaped token anywhere in `text` (row_text realistically has a
    title/agency/etc. ahead of the actual date, so this must search, not require the
    whole string to be exactly the date).

    Two cases, handled differently on purpose:

    1. A real TIMESTAMP -- date and time, with an explicit "Z" or numeric UTC offset
       (e.g. "2026-10-07T19:00:00Z", "2026-10-07T14:00:00-05:00") -- names one exact
       instant. It's parsed and converted to UTC exactly, preserving that instant.

    2. A bare DATE-ONLY token -- just a calendar date, no time, no timezone (e.g.
       "10/07/2026", "October 7, 2026") -- is the overwhelmingly common real shape for
       a scraped bid-board deadline, and names a DAY, not an instant. Production bug:
       this used to be anchored at UTC MIDNIGHT (`.replace(tzinfo=timezone.utc)`).
       Midnight UTC on Oct 7, displayed in any negative-UTC-offset zone (Central is
       UTC-5/-6), falls on Oct 6 local time -- so a source deadline of October 7
       displayed as October 6 everywhere in the app (Discover, Source History, the
       Port Arthur listing this was reported from). A date-only value isn't really a
       midnight instant at all; it's anchored at NOON UTC instead, which lands within
       the same source calendar date for every real-world US display timezone (as
       early as ~6am Eastern DST, as late as ~2am Hawaii) without needing this
       connector to know or care what timezone the frontend renders in.
    """
    ts_match = _TIMESTAMP_TOKEN.search(text)
    if ts_match is not None:
        candidate = ts_match.group(1).replace(" ", "T", 1)
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

    date_match = _DATE_ONLY_TOKEN.search(text)
    if not date_match:
        return None
    token = date_match.group(1).rstrip(",")
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            naive = datetime.strptime(token, fmt)
        except ValueError:
            continue
        return datetime(naive.year, naive.month, naive.day, 12, 0, 0, tzinfo=timezone.utc)
    return None


def _looks_javascript_rendered(soup: BeautifulSoup) -> bool:
    """A near-empty <body> alongside a framework root div or a large inline bundle is
    the standard signature of a client-side-rendered page that a plain HTML fetch
    can't see the real content of. Checked so a genuinely empty result is reported as
    'this page needs JS rendering' rather than silently looking like 'no bids today.'"""
    body = soup.find("body")
    visible_text_length = len(body.get_text(strip=True)) if body else 0
    has_framework_root = bool(soup.select_one("#root, #app, [data-reactroot], ng-app, [ng-app]"))
    has_large_script = any(len(s.string or "") > 5000 for s in soup.find_all("script") if s.string)
    return visible_text_length < 200 and (has_framework_root or has_large_script)


def _find_feed_link(soup: BeautifulSoup) -> str | None:
    """Prefer a structured feed/API over HTML scraping if the page actually declares
    one — checked first, per the explicit instruction not to assume scraping is
    necessary. No RSS/JSON feed was found documented anywhere for this platform (see
    module docstring), so this is very likely a no-op today, but costs nothing to keep
    checking in case that changes or this guess about the live page is wrong."""
    for link in soup.find_all("link", rel="alternate"):
        link_type = (link.get("type") or "").lower()
        if "rss" in link_type or "json" in link_type or "atom" in link_type:
            href = link.get("href")
            if href:
                return href
    return None


def _cell_texts(row: Tag) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]


def _try_table_rows(soup: BeautifulSoup) -> list[dict]:
    """Strategy 1: a <table> whose rows roughly match the documented 6-column layout
    (# / Source / Agency / FSG / Title / Keywords), Title cell holding the detail link.
    Lenient on exact column count/order since this is a guess, not a confirmed schema."""
    results = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td"])
            if len(cells) < 3:
                continue
            title_cell = None
            for cell in cells:
                if cell.find("a") is not None:
                    title_cell = cell
                    break
            if title_cell is None:
                continue
            link = title_cell.find("a")
            title = link.get_text(" ", strip=True)
            if not title or len(title) < 5:
                continue
            href = link.get("href")
            texts = _cell_texts(row)
            results.append({
                "title": title, "detail_url": href, "row_text": " | ".join(texts),
                "cells": texts,
            })
    return results


def _try_generic_listing_items(soup: BeautifulSoup) -> list[dict]:
    """Strategy 2 (fallback if no table matched anything): any <li> or <div> that
    contains exactly one substantial-length link, treated as one listing with that
    link's text as the title and the element's full text as everything else to mine
    fields from. Deliberately broad since this is a total-unknown fallback."""
    results = []
    seen_hrefs = set()
    for container in soup.find_all(["li", "div", "article"]):
        links = container.find_all("a", href=True)
        if len(links) != 1:
            continue
        link = links[0]
        title = link.get_text(" ", strip=True)
        href = link["href"]
        if not title or len(title) < 8 or href in seen_hrefs:
            continue
        full_text = container.get_text(" ", strip=True)
        if len(full_text) < len(title) + 5:  # the link IS basically the whole element — not a listing row
            continue
        seen_hrefs.add(href)
        results.append({"title": title, "detail_url": href, "row_text": full_text, "cells": []})
    return results


def _parse_page(html: str, base_url: str) -> tuple[list[dict], dict]:
    """Returns (candidate_listings, diagnostics). Never raises for a structural
    mismatch — an empty list with an explanatory diagnostic is the correct outcome
    when the real page doesn't match either guessed structure, not a crash."""
    soup = BeautifulSoup(html, "html.parser")
    diagnostics: dict = {}

    feed_link = _find_feed_link(soup)
    diagnostics["feed_link_found"] = feed_link
    if feed_link:
        logger.info("apex_mybidmatch: page declares a feed link (%s) — not yet consumed, HTML-parsing instead.", feed_link)

    if _looks_javascript_rendered(soup):
        diagnostics["likely_javascript_rendered"] = True
        diagnostics["note"] = (
            "Static HTML fetch returned little/no visible text alongside a JS-framework "
            "marker — this page likely requires JavaScript rendering, which a plain HTTP "
            "fetch cannot see. No listings were fabricated; see module docstring."
        )
        return [], diagnostics
    diagnostics["likely_javascript_rendered"] = False

    candidates = _try_table_rows(soup)
    diagnostics["strategy_used"] = "table_rows" if candidates else None
    if not candidates:
        candidates = _try_generic_listing_items(soup)
        diagnostics["strategy_used"] = "generic_listing_items" if candidates else None

    for candidate in candidates:
        if candidate.get("detail_url"):
            candidate["detail_url"] = str(httpx.URL(base_url).join(candidate["detail_url"]))

    diagnostics["candidates_found"] = len(candidates)
    if not candidates:
        diagnostics["note"] = (
            "Neither the documented table layout nor a generic link-list fallback found "
            "any candidate listings. The real page structure differs from both guesses in "
            "this module's docstring and needs to be re-verified directly."
        )
    return candidates, diagnostics


def _to_raw_intelligence_item(candidate: dict, retrieved_at: datetime) -> RawIntelligenceItem | None:
    title = candidate["title"].strip()
    if not title:
        return None
    row_text = candidate.get("row_text", "")
    detail_url = candidate.get("detail_url")

    sam_notice_id = _extract_sam_notice_id(row_text) or (_extract_sam_notice_id(detail_url) if detail_url else None)
    # A detected SAM.gov reference wins as source_url, constructed in the EXACT format
    # sam_gov.py itself uses — see module docstring on why this (not APEX's own raw
    # link) is what makes cross-source dedup work without guessing APEX's link format.
    source_url = f"https://sam.gov/opp/{sam_notice_id}/view" if sam_notice_id else detail_url

    cells = candidate.get("cells", [])
    agency = cells[2] if len(cells) > 2 else None

    external_id = sam_notice_id or (detail_url or title)

    fields = {
        "title": title[:500],
        "agency_name": (agency or None) and agency[:300],
        "naics_code": _extract_naics(row_text),
        "set_aside": _map_set_aside(row_text),
        "proposal_due_at": _parse_loose_date(_DEADLINE_LABELS.sub("", row_text)),
        "estimated_value_high": _extract_money(row_text),
    }

    return RawIntelligenceItem(
        external_id=str(external_id)[:200],
        intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        source_url=source_url,
        retrieved_at=retrieved_at,
        fields=fields,
        raw={"row_text": row_text, "detail_url": detail_url, "sam_notice_id_detected": sam_notice_id},
        confidence="unverified" if not sam_notice_id else "verified_fact",
    )


class ApexMyBidMatchConnector(IntelligenceConnector):
    key = "web_apex_mybidmatch"
    name = SOURCE_NAME
    default_category = IntelligenceCategory.LIVE_OPPORTUNITY

    def __init__(self):
        self.last_run_diagnostics: dict | None = None

    def is_configured(self) -> bool:
        return True  # public page, no credentials — "configured" the moment PAGE_URL is reachable

    def fetch(self, since: date, limit: int = MAX_RECORDS_PER_SYNC) -> list[RawIntelligenceItem]:
        retrieved_at = datetime.now(timezone.utc)
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = request_with_retry(client, "GET", PAGE_URL)
        except Exception as exc:
            raise ConnectorNotConfiguredError(
                f"APEX MyBidMatch page could not be reached: {exc}. If this page requires a "
                f"session cookie or has moved, the URL/access method needs to be re-verified."
            ) from exc

        if response.status_code != 200:
            self.last_run_diagnostics = {
                "status_code": response.status_code, "final_url": str(response.url),
                "note": f"Page returned HTTP {response.status_code} instead of 200.",
            }
            return []

        candidates, diagnostics = _parse_page(response.text, str(response.url))
        diagnostics["final_url"] = str(response.url)
        diagnostics["redirected"] = str(response.url) != PAGE_URL

        kept: list[RawIntelligenceItem] = []
        mapping_errors = 0
        for candidate in candidates[:limit]:
            try:
                raw = _to_raw_intelligence_item(candidate, retrieved_at)
            except Exception:
                logger.exception("apex_mybidmatch: failed to map one candidate listing — skipped, not fabricated")
                mapping_errors += 1
                continue
            if raw is not None:
                kept.append(raw)
        diagnostics["mapping_errors"] = mapping_errors
        diagnostics["records_returned"] = len(kept)

        self.last_run_diagnostics = diagnostics
        return kept
