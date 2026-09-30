"""MyBidMatch static subscriber index -> daily table -> article connector.

Verified against the live subscriber page on 2026-09-30. Only table rows with
the exact FSG value C are eligible. Navigation/date rows are never listings.
No feed is declared by the verified pages; unknown layouts fail closed.
"""
import logging
import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup, Tag

from app.connectors.base import ConnectorNotConfiguredError, IntelligenceConnector, RawIntelligenceItem
from app.connectors.http_retry import request_with_retry
from app.models.enums import IntelligenceCategory, SetAsideType

logger = logging.getLogger(__name__)

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
_SAM_NOTICE_ID = re.compile(r"sam\.gov/(?:workspace/contract/opp|opp|api/prod/opportunities/v\d+/noticedesc)[^A-Za-z0-9]*([A-Za-z0-9]{32})", re.IGNORECASE)
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
_DATE_TOKEN = re.compile(
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
    """Finds a date-shaped token anywhere in `text` (row_text realistically has a
    title/agency/etc. ahead of the actual date, so this must search, not require the
    whole string to be exactly the date — an earlier version passed a fixed-length
    prefix straight to strptime, which only matched when the date happened to be the
    very first thing in the string and nothing else was within that prefix; i.e.
    almost never, on any real row shape)."""
    match = _DATE_TOKEN.search(text)
    if not match:
        return None
    token = match.group(1).rstrip(",")
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(token, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
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


def _same_host_url(base: str, href: str, path: str) -> str | None:
    url = urljoin(base, href)
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.netloc == urlparse(PAGE_URL).netloc and parsed.path == path else None


def _parse_page(html: str, base_url: str) -> tuple[list[dict], dict]:
    """Recognize either the subscriber index or the documented daily table."""
    soup = BeautifulSoup(html, "html.parser")
    diagnostics = {"feed_link_found": _find_feed_link(soup),
                   "likely_javascript_rendered": _looks_javascript_rendered(soup),
                   "strategy_used": None, "candidates_found": 0,
                   "rows_fetched": 0, "matched_fsg_c": 0,
                   "skipped_non_c": 0, "skipped_missing_fsg": 0,
                   "skipped_malformed": 0}
    if diagnostics["likely_javascript_rendered"]:
        diagnostics["note"] = "Page requires JavaScript rendering; no rows normalized."
        return [], diagnostics
    candidates, bulletins = [], []
    for table in soup.find_all("table"):
        rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
        if not rows:
            continue
        header = next((h for h in table.find_all("thead") if h.find_parent("table") is table), None) or rows[0]
        headers = [c.get_text(" ", strip=True).lower() for c in header.find_all(["td", "th"])]
        data_rows = [row for row in rows if row is not header and row.find_parent("thead") is None] if header.name == "thead" else rows[1:]
        if headers == ["date", "articles", "read"]:
            diagnostics["strategy_used"] = "bulletin_index"
            for row in data_rows:
                cells = row.find_all("td")
                link = cells[0].find("a", href=True) if cells else None
                if not link:
                    continue
                url = _same_host_url(base_url, link["href"], "/go")
                posted = _parse_loose_date(link.get_text(" ", strip=True))
                if url and parse_qs(urlparse(url).query).get("doc") and posted:
                    bulletins.append({"url": url, "bulletin_date": posted.date().isoformat()})
        elif all(h in headers for h in ("source", "agency", "fsg", "title", "keywords")):
            diagnostics["strategy_used"] = "daily_table"
            positions = {h: headers.index(h) for h in ("source", "agency", "fsg", "title", "keywords")}
            for row in data_rows:
                cells = row.find_all("td")
                if not cells:
                    continue
                diagnostics["rows_fetched"] += 1
                fsg = cells[positions["fsg"]].get_text(" ", strip=True) if len(cells) > positions["fsg"] else ""
                if not fsg:
                    diagnostics["skipped_missing_fsg"] += 1
                    continue
                if fsg != "C":
                    diagnostics["skipped_non_c"] += 1
                    continue
                diagnostics["matched_fsg_c"] += 1
                if len(cells) <= max(positions.values()):
                    diagnostics["skipped_malformed"] += 1
                    continue
                link = cells[positions["title"]].find("a", href=True)
                url = _same_host_url(base_url, link["href"], "/article") if link else None
                if not url or not all(parse_qs(urlparse(url).query).get(k) for k in ("doc", "seq")):
                    diagnostics["skipped_malformed"] += 1
                    continue
                candidates.append({"title": link.get_text(" ", strip=True), "detail_url": url,
                    "fsg": fsg, "source_type": cells[positions["source"]].get_text(" ", strip=True),
                    "agency": cells[positions["agency"]].get_text(" ", strip=True),
                    "row_text": " | ".join(_cell_texts(row)), "bulletin_url": base_url})
    diagnostics["bulletins"] = bulletins
    diagnostics["candidates_found"] = len(candidates)
    if not diagnostics["strategy_used"]:
        diagnostics["note"] = "Unrecognized page structure; must be re-verified. Generic links are not procurement records."
    return candidates, diagnostics


def _parse_article(html: str, candidate: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one(".art-box")
    if article is None or article.find("h4") is None:
        raise ValueError("MyBidMatch article body/agency heading missing")
    for navigation in article.select(".noprint"):
        navigation.decompose()
    heading = article.find("h4")
    paragraphs = heading.find_next_siblings("p")
    if not paragraphs:
        raise ValueError("MyBidMatch article summary missing")
    summary = paragraphs[0].get_text(" ", strip=True)
    text = article.get_text(" ", strip=True)
    number = re.search(r"OutreachSystems Article Number:\s*([A-Za-z0-9/.-]+)", text)
    if not number:
        raise ValueError("MyBidMatch article identifier missing")
    # Article header must corroborate the row's FSG, never broaden its inclusion.
    if not re.match(r"^C\s*--?\s+", summary):
        raise ValueError("Article FSG does not corroborate table FSG C")
    title = re.split(r"\s+(?:SOL\s|DUE\s|Due Date:|POC\s|URL\s|Contact:)", re.sub(r"^C\s*--?\s+", "", summary), maxsplit=1, flags=re.I)[0]
    links = [urljoin(candidate["detail_url"], a["href"]) for a in article.find_all("a", href=True)]
    sam_id = next((value for link in links if (value := _extract_sam_notice_id(link))), None)
    solicitation = re.search(r"\bSOL\s+([A-Za-z0-9][A-Za-z0-9_. /-]*?)(?=\s+(?:DUE|POC|URL|Contact:)\b|$)", summary, re.I)
    due = re.search(r"\bDUE(?:\s+Date)?\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})(?:\s+at)?(?:\s+(\d{1,2}:\d{2}\s*[AP]M)(?:\s+([+-]\d{2}:\d{2}))?)?", summary, re.I)
    due_label = re.search(r"\bDUE(?:\s+Date)?\s*:?\s*(.{0,85})", summary, re.I)
    deadline = _parse_loose_date(due_label[1]) if due_label else None
    if due and due[2] and due[3]:
        deadline = datetime.strptime(due[1] + " " + re.sub(r"\s", "", due[2]).upper() + " " + due[3], "%m/%d/%Y %I:%M%p %z")
    # Date-only/unzoned deadlines retain their original text and precision below.
    source_type = candidate.get("source_type", "").lower()
    body_start = " ".join(p.get_text(" ", strip=True) for p in paragraphs[:4])
    if source_type == "awards":
        category, notice_type = IntelligenceCategory.AWARD_INTELLIGENCE, "Award"
    elif re.search(r"\bSOURCES SOUGHT\b|\bPRE[- ]?SOLICITATION\b|\bNOTICE OF INTENT\b", body_start[:3000], re.I):
        category, notice_type = IntelligenceCategory.PRE_SOLICITATION, "Sources Sought / Pre-Solicitation"
    else:
        category, notice_type = IntelligenceCategory.LIVE_OPPORTUNITY, None
    fields = {"title": title[:500], "description": text,
              "agency_name": candidate.get("agency", "")[:300] or None,
              "solicitation_number": solicitation[1].strip()[:120] if solicitation else None,
              "naics_code": _extract_naics(text), "proposal_due_at": deadline}
    location = re.search(r"Place of Performance:\s*(.*?)(?=\s+URL:|OutreachSystems Article|$)", text, re.I)
    if location:
        state = re.fullmatch(r"(.+?)\s+([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?", location[1].strip())
        if state:
            fields.update(location_city=state[1].rstrip(", ")[:120], location_state=state[2])
    # Only an explicit restriction label is evidence, not generic small-business prose.
    restriction = re.search(r"(?:^|[.;])\s*Set[- ]aside\s*:\s*([^.;]+)", text, re.I)
    if restriction and (any(k in restriction[1].lower() for k, _ in _SET_ASIDE_KEYWORDS) or restriction[1].strip().lower() in ("none", "unrestricted", "full and open")):
        fields["set_aside"] = _map_set_aside(restriction[1])
    # Do not mistake bid bonds, size standards or a shared MATOC ceiling for project value.
    value = re.search(r"Estimated (?:contract |project )?value\s*:\s*(\$[\d,.]+(?:\s*(?:million|thousand|m|k))?)", text, re.I)
    if value:
        fields["estimated_value_high"] = _extract_money(value[1])
    return {**candidate, "title": title, "fields": fields, "category": category,
            "article_number": number[1], "article_text": text, "agency_heading": heading.get_text(" ", strip=True),
            "sam_notice_id": sam_id, "notice_type": notice_type, "outbound_urls": links,
            "deadline_text": due_label[0] if due_label else None,
            "deadline_precision": "offset_datetime" if due and due[2] and due[3] else "date_only_assumed_utc" if deadline else None}


def _to_raw_intelligence_item(candidate: dict, retrieved_at: datetime) -> RawIntelligenceItem | None:
    # Defense in depth: no caller may bypass the pre-normalization inclusion rule.
    if candidate.get("fsg") != "C" or not candidate.get("article_number"):
        return None
    sam_id = candidate.get("sam_notice_id")
    source_url = f"https://sam.gov/opp/{sam_id}/view" if sam_id else candidate["detail_url"]
    return RawIntelligenceItem(
        external_id=sam_id or candidate["article_number"],
        intelligence_category=candidate["category"], source_url=source_url,
        retrieved_at=retrieved_at, fields=candidate["fields"],
        raw={k: v for k, v in candidate.items() if k not in ("fields", "category")},
        confidence="verified_fact",
    )


class ApexMyBidMatchConnector(IntelligenceConnector):
    key = "web_apex_mybidmatch"
    name = SOURCE_NAME
    default_category = IntelligenceCategory.LIVE_OPPORTUNITY

    def __init__(self):
        self.last_run_diagnostics = None

    def is_configured(self) -> bool:
        return True

    def fetch(self, since: date, limit: int = MAX_RECORDS_PER_SYNC) -> list[RawIntelligenceItem]:
        retrieved_at = datetime.now(timezone.utc)
        diagnostics = {"parser_version": "verified-static-fsg-c-v1", "rows_fetched": 0,
                       "matched_fsg_c": 0, "skipped_non_c": 0, "skipped_missing_fsg": 0,
                       "skipped_malformed": 0, "bulletins_fetched": 0, "mapping_errors": 0,
                       "detail_errors": [], "records_returned": 0, "duplicate_notices_in_run": 0}
        self.last_run_diagnostics = diagnostics
        candidates = []
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            def get(url):
                response = request_with_retry(client, "GET", url)
                response.raise_for_status()
                if urlparse(str(response.url)).netloc != urlparse(PAGE_URL).netloc:
                    raise ValueError("MyBidMatch redirected outside the source host; access requires review")
                return response
            response = get(PAGE_URL)
            _, index = _parse_page(response.text, str(response.url))
            diagnostics.update(final_url=str(response.url), redirected=str(response.url) != PAGE_URL,
                               feed_link_found=index["feed_link_found"], strategy_used=index["strategy_used"])
            if index["strategy_used"] != "bulletin_index":
                raise ValueError("Expected MyBidMatch dated bulletin index; refusing generic-link ingestion")
            bulletins = sorted(index["bulletins"], key=lambda b: b["bulletin_date"], reverse=True)
            for bulletin in bulletins:
                if date.fromisoformat(bulletin["bulletin_date"]) < since:
                    continue
                response = get(bulletin["url"])
                rows, daily = _parse_page(response.text, str(response.url))
                if daily["strategy_used"] != "daily_table":
                    raise ValueError("Expected MyBidMatch daily opportunity table; source layout changed")
                diagnostics["bulletins_fetched"] += 1
                for key in ("rows_fetched", "matched_fsg_c", "skipped_non_c", "skipped_missing_fsg", "skipped_malformed"):
                    diagnostics[key] += daily[key]
                candidates.extend({**r, "bulletin_date": bulletin["bulletin_date"]} for r in rows)
            diagnostics["deferred_fsg_c_limit"] = max(0, len(candidates) - limit)
            kept, seen = [], set()
            for candidate in candidates[:limit]:
                try:
                    response = get(candidate["detail_url"])
                    raw = _to_raw_intelligence_item(_parse_article(response.text, candidate), retrieved_at)
                    if raw is None:
                        raise ValueError("FSG C/detail evidence missing; row not normalized")
                    if raw.external_id in seen:
                        diagnostics["duplicate_notices_in_run"] += 1
                        continue  # newest bulletin wins; no duplicate upserts in one run
                    seen.add(raw.external_id)
                    kept.append(raw)
                except Exception as exc:
                    diagnostics["mapping_errors"] += 1
                    diagnostics["detail_errors"].append({"title": candidate["title"],
                        "external_id": candidate["detail_url"], "error": str(exc)[:1000]})
            diagnostics["records_returned"] = len(kept)
            return kept
