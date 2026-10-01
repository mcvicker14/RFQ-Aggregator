"""COREWORKS RFQwire connector — turns forwarded COREWORKS digest emails into
individually normalized IntelligenceItems. Each email is a rolling, plaintext,
multi-section digest built by hand by one person (Ralph Fontcuberta) as a
daily/twice-daily mailing; this module's job is to turn that loosely-structured text
back into individual listings.

Retrieval transport: this app holds no Gmail/Google credentials at all. A Google Apps
Script, authorized directly against the Gmail account that receives the forwards, does
the actual searching and sends back raw message content (plaintext body, Gmail message
id, received timestamp) — see app/connectors/coreworks_apps_script_client.py and
google-apps-script/coreworks_sync.gs. That script also PUSHES newly found messages
straight to app/api/routes/coreworks_ingest.py on its own time-driven trigger, which
calls parse_messages_to_raw_items() below directly (bypassing fetch()'s own pull, since
the data has already arrived) — see that route for the push path. Either way, every
byte of the parsing logic below is identical and runs only in this app, in Python: the
script never parses a listing, it only finds and forwards whole messages.

Structure verified against two REAL forwarded emails in the target Gmail account (not
guessed) — see the project scratchpad notes this was built from for the full annotated
transcripts. Key, empirically-confirmed facts that shape this parser:

1. **Two distinct forward-header styles** show up in practice (Outlook's "Fw:" style —
   a signature block, a "________________________________" rule, then From:/Sent:/
   To:/Subject: lines — and Apple Mail/Gmail's "Fwd:" style — "Begin forwarded
   message:" then From:/Date:/To:/Subject:). Both are handled by ONE scan (see
   _find_original_sender_and_body below) that looks for a From:/Subject: pair anywhere
   in the plaintext body, rather than branching on which style produced it.
2. **Because these are forwards, the Gmail envelope "From" is always the forwarder**
   (e.g. eric.mcvicker@pi-aec.com), never RFQwire@dbacoreworks.com — original-sender
   confirmation is done entirely by parsing the embedded From:/Subject: header block
   inside the body text, exactly per the requirement not to trust the envelope alone.
3. **One email is a ROLLING digest, not just "what's new today.":** it repeats a
   "NEW & REVISED LISTINGS | <date>" section for every recent mailing, going backward
   in time, each with its own listings. The SAME opportunity legitimately appears
   several times within one email (addenda accumulate across re-listings) AND across
   consecutive emails (confirmed directly: two real emails a week apart shared an
   identical section verbatim). Handled by deriving a stable external_id (see
   _derive_external_id) so every re-listing upserts the same IntelligenceItem instead
   of duplicating it — this is a within-source concern, resolved entirely by
   intelligence_sync.py's existing (source_id, external_id) upsert key, with no
   changes needed to the cross-source dedup engine (app/services/dedup.py).
4. **A numbered multi-item advertisement** ("(Architectural) 1. ... Region A ...",
   "(Architectural) 2. ... Region B ...", up to 16 seen in one real advertisement)
   shares ONE combined Public Notice PDF across genuinely DISTINCT procurements —
   handled by giving each numbered sub-item its own #item-N URL fragment (see
   _disambiguate_shared_url) so dedup.py's source_url identifier match (added
   alongside this connector) doesn't incorrectly merge them into one cluster.
5. **Cancelled listings** show a literal trailing "NOTE: ... Cancelled<url>." sentence.
   **Other bracketed "[NOTE: ...]" annotations** carry free-text context (a missed
   posting, a pre-submittal meeting date) that ISN'T cancellation — kept as
   description text, never structurally over-parsed.
6. **A day with nothing to report** literally says "Free Parking" instead of a state
   section — skipped, not an error (see _parse_section).

Never filters for relevance here — same "broad, complete, auditable retrieval; scoring
happens after persistence" principle as sam_gov.py. See
app/services/infrastructure_relevance_scoring.py for the relevance stage.
"""
import hashlib
import logging
import re
from datetime import date, datetime, timezone

from app.connectors.base import ConnectorNotConfiguredError, IntelligenceConnector, RawIntelligenceItem
from app.connectors.coreworks_apps_script_client import CoreworksAppsScriptError, is_configured, mark_processed, scan
from app.models.enums import IntelligenceCategory

logger = logging.getLogger(__name__)

SOURCE_NAME = "COREWORKS RFQwire"
ORIGINAL_SENDER_DOMAIN = "dbacoreworks.com"
ORIGINAL_SENDER_NAME_PATTERN = re.compile(r"ralph\s+fontcuberta", re.IGNORECASE)

_FROM_LINE = re.compile(r"^From:\s*(?P<name>.*?)\s*<(?P<email>[^<>@\s]+@[^<>\s]+)>\s*$", re.MULTILINE)
_SUBJECT_LINE = re.compile(r"^Subject:\s*(?P<subject>.+)$", re.MULTILINE)

_SECTION_HEADER = re.compile(r"^NEW & REVISED LISTINGS\s*\|\s*(?P<section_date>.+?)\s*$", re.MULTILINE)
_FOOTER_MARKER = "RFQ Tracking and Form Response"

_STATE_NAMES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI",
    "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
}

# "<n> <Month> <d> (<ST>) <client>; <rest>" — the one line every real listing starts
# with. Month is matched loosely (word chars) rather than an exact month-name list so
# an unexpected abbreviation doesn't silently drop a real listing.
_LISTING_START = re.compile(
    r"^(?P<due_year>\d{4}) (?P<due_month>\w+) (?P<due_day>\d{1,2}) \((?P<state>[A-Z]{2})\) "
    r"(?P<client>[^;]+);\s*(?P<rest>.+)$",
    re.DOTALL,
)
# "(Label<https://url>)" — Gmail's plaintext conversion renders an <a href> this way,
# with no space between the label and the opening "<". Captures every such group in a
# listing's text; the label may be empty (rare but seen), never contains "<"/">".
_LINK_GROUP = re.compile(r"\(([^()<>]*?)<(https?://[^<>]+)>\)")
# "(Architectural) 1. <title...>" / "(Engineering) 2. <title...>" — a numbered
# sub-item of one combined advertisement. Deliberately distinct from a plain leading
# identifier like "(27-0014A)" by requiring a following "<digits>. " — see module
# docstring point 4.
_NUMBERED_SUBITEM = re.compile(r"^\((?P<discipline>[A-Za-z][A-Za-z /&-]{1,40})\)\s+(?P<index>\d+)\.\s+(?P<title>.+)$", re.DOTALL)
# "(27-0014A) <title>" / "(RFQ 26-ENGSRV-65) <title>" — a leading parenthetical that
# isn't the numbered-subitem pattern above is treated as a solicitation/RFQ number.
_LEADING_IDENTIFIER = re.compile(r"^\((?P<identifier>[^()<>]{1,40})\)\s+(?P<title>.+)$", re.DOTALL)
_CANCELLED = re.compile(r"NOTE:.*?\bcancelled\b.*?$", re.IGNORECASE | re.DOTALL)
_BRACKET_NOTE = re.compile(r"\[NOTE:\s*(?P<note>.+?)\]", re.IGNORECASE | re.DOTALL)

_MONTHS = {
    m.lower(): i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1
    )
}


def _find_original_sender_and_body(full_text: str) -> tuple[bool, str | None, str]:
    """Scans the WHOLE plaintext body for an embedded 'From: Name <email>' line
    (wherever it sits — after a personal signature, after 'Begin forwarded message:',
    or anywhere else) and the 'Subject:' line that follows it, regardless of which
    forward-client style produced them (see module docstring point 1). Returns
    (is_confirmed_coreworks, subject_or_None, body_after_headers). Never trusts the
    Gmail envelope sender (point 2) — confirmation is solely from this parsed header."""
    from_match = _FROM_LINE.search(full_text)
    if from_match is None:
        return False, None, ""

    name, email = from_match.group("name"), from_match.group("email")
    is_original_sender = email.lower().endswith("@" + ORIGINAL_SENDER_DOMAIN) or bool(
        ORIGINAL_SENDER_NAME_PATTERN.search(name)
    )
    if not is_original_sender:
        return False, None, ""

    subject_match = _SUBJECT_LINE.search(full_text, pos=from_match.end())
    if subject_match is None:
        return False, None, ""

    body = full_text[subject_match.end():]
    if "COREWORKS" not in body[:200].upper():
        logger.warning(
            "gmail_coreworks: From:/Subject: header confirmed %s, but body doesn't start "
            "with the expected 'COREWORKS RFQwire' marker — parsing anyway, but this "
            "message's structure may have changed.", email,
        )
    return True, subject_match.group("subject").strip(), body


def _parse_due_date(year: str, month: str, day: str) -> datetime | None:
    month_num = _MONTHS.get(month.lower())
    if month_num is None:
        return None
    try:
        return datetime(int(year), month_num, int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


def _disambiguate_shared_url(url: str, subitem_index: str | None) -> str:
    """A numbered multi-item advertisement's sub-items share one literal PDF URL (see
    module docstring point 4). Appending a fragment keeps the link fully clickable to
    the same real document while making each sub-item's source_url textually distinct,
    so dedup.py's canonical-URL identifier match treats them as the distinct
    procurements they are instead of one false merge."""
    if subitem_index is None:
        return url
    return f"{url}#item-{subitem_index}"


def _split_link_groups(text: str) -> tuple[str, list[dict[str, str]]]:
    links = [{"label": label.strip(), "url": url} for label, url in _LINK_GROUP.findall(text)]
    return _LINK_GROUP.sub("", text).strip(), links


def _parse_listing(raw_text: str, section_date_label: str, state_default: str) -> dict | None:
    match = _LISTING_START.match(raw_text.strip())
    if match is None:
        return None

    due_at = _parse_due_date(match.group("due_year"), match.group("due_month"), match.group("due_day"))
    state = match.group("state") or state_default
    client = match.group("client").strip()
    rest = match.group("rest").strip()

    cancelled = bool(_CANCELLED.search(rest))
    rest = _CANCELLED.sub("", rest).strip()

    bracket_notes = [n.strip() for n in _BRACKET_NOTE.findall(rest)]
    rest = _BRACKET_NOTE.sub("", rest).strip()

    body_text, links = _split_link_groups(rest)
    body_text = body_text.rstrip(". ").strip()

    subitem_index = None
    solicitation_number = None
    subitem = _NUMBERED_SUBITEM.match(body_text)
    if subitem is not None:
        subitem_index = subitem.group("index")
        title = f"{subitem.group('discipline').strip()} {subitem_index}: {subitem.group('title').strip()}"
    else:
        leading = _LEADING_IDENTIFIER.match(body_text)
        if leading is not None:
            solicitation_number = leading.group("identifier").strip()
            title = leading.group("title").strip()
        else:
            title = body_text

    if links:
        primary_url = _disambiguate_shared_url(links[0]["url"], subitem_index)
        addendum_links = [link_ for link_ in links if "addendum" in link_["label"].lower()]
    else:
        primary_url = None
        addendum_links = []

    if not title:
        return None

    return {
        "title": title,
        "client": client,
        "state": state.upper() if state else None,
        "due_at": due_at,
        "solicitation_number": solicitation_number,
        "source_url": primary_url,
        "links": links,
        "addendum_links": addendum_links,
        "cancelled": cancelled,
        "notes": bracket_notes,
        "listing_date_label": section_date_label,
    }


def _parse_section(section_text: str, section_date_label: str) -> list[dict]:
    listings: list[dict] = []
    current_state: str | None = None
    for paragraph in re.split(r"\n\s*\n", section_text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        state_abbrev = _STATE_NAMES.get(paragraph.upper())
        if state_abbrev is not None:
            current_state = state_abbrev
            continue
        # "Free Parking" (a day with nothing to report) and any other paragraph that
        # isn't a real listing line simply fails _LISTING_START and is skipped — never
        # guessed at, per the module's "do not invent missing fields" principle.
        parsed = _parse_listing(paragraph, section_date_label, current_state or "")
        if parsed is not None:
            listings.append(parsed)
    return listings


def _derive_external_id(listing: dict) -> str:
    """Stable id so the same opportunity re-listed in a later section of this email,
    or in a later email entirely, upserts the existing IntelligenceItem instead of
    duplicating it — see module docstring point 3. Ordered exactly as specified:
    solicitation/RFQ number, then canonical source URL, then client+title+due date."""
    if listing["solicitation_number"]:
        return f"solnum:{listing['solicitation_number'].strip().lower()}"
    if listing["source_url"]:
        return f"url:{listing['source_url'].strip().lower()}"
    due = listing["due_at"].date().isoformat() if listing["due_at"] else "unknown-due-date"
    basis = f"{listing['client'].strip().lower()}|{listing['title'].strip().lower()}|{due}"
    return "hash:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def _to_raw_intelligence_item(
    listing: dict, message_id: str, message_subject: str, received_at: datetime, retrieved_at: datetime,
) -> RawIntelligenceItem:
    fields = {
        "title": listing["title"][:500],
        "agency_name": listing["client"][:300] or None,
        "location_state": listing["state"],
        "solicitation_number": (listing["solicitation_number"] or None) and listing["solicitation_number"][:120],
        "proposal_due_at": listing["due_at"],
        "description": ("CANCELLED. " if listing["cancelled"] else "") + " ".join(listing["notes"]) or None,
    }
    return RawIntelligenceItem(
        external_id=_derive_external_id(listing),
        intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        source_url=listing["source_url"],
        retrieved_at=retrieved_at,
        fields=fields,
        raw={
            "gmail_message_id": message_id,
            "gmail_message_subject": message_subject,
            "received_at": received_at.isoformat(),
            "coreworks_listing_date": listing["listing_date_label"],
            "links": listing["links"],
            "addendum_links": listing["addendum_links"],
            "cancelled": listing["cancelled"],
            "bracket_notes": listing["notes"],
        },
        confidence="verified_fact",
    )


def parse_messages_to_raw_items(messages: list[dict]) -> list[RawIntelligenceItem]:
    """Turns raw Gmail messages (each {"id", "body_text", "internal_date_ms"} — the
    Apps Script's scan result shape, identical to what gmail_client.py's now-retired
    get_message_plaintext() used to return) into normalized RawIntelligenceItems. The
    one shared core of both retrieval paths: CoreworksRfqwireConnector.fetch() below
    (on-demand pull, via coreworks_apps_script_client.scan()) and
    app/api/routes/coreworks_ingest.py (the Apps Script's own time-driven push) both
    call this directly with whatever messages they have — this function never talks to
    Gmail or Apps Script itself, it only parses text already in hand.

    Independently re-confirms original-sender authenticity per message
    (_find_original_sender_and_body) even though the Apps Script already did a coarse
    version of the same check before sending — defense in depth, and this app's parser
    remains the single authoritative source of truth for what's actually ingested."""
    retrieved_at = datetime.now(timezone.utc)
    items: dict[str, RawIntelligenceItem] = {}
    messages_scanned = messages_confirmed = 0

    for message in messages:
        messages_scanned += 1
        message_id = message.get("id", "<unknown>")

        is_coreworks, subject, body = _find_original_sender_and_body(message.get("body_text") or "")
        if not is_coreworks:
            continue
        messages_confirmed += 1

        received_at = retrieved_at
        if message.get("internal_date_ms"):
            try:
                received_at = datetime.fromtimestamp(int(message["internal_date_ms"]) / 1000, tz=timezone.utc)
            except (ValueError, OSError):
                pass

        for section_match in list(_SECTION_HEADER.finditer(body)):
            section_start = section_match.end()
            next_header = _SECTION_HEADER.search(body, pos=section_start)
            footer_pos = body.find(_FOOTER_MARKER, section_start)
            section_end = min(
                p for p in (next_header.start() if next_header else len(body),
                            footer_pos if footer_pos != -1 else len(body))
                if p >= section_start
            )
            section_text = body[section_start:section_end]

            for listing in _parse_section(section_text, section_match.group("section_date")):
                try:
                    raw = _to_raw_intelligence_item(
                        listing, message_id, subject or "", received_at, retrieved_at,
                    )
                except Exception:
                    logger.exception(
                        "gmail_coreworks: failed to map one listing from message %s — skipped, not fabricated",
                        message_id,
                    )
                    continue
                # Keyed by external_id: the same listing appearing in an earlier (more
                # addenda) section of THIS email should win over an earlier-seen, less-
                # complete occurrence — sections iterate newest-first, matching how
                # COREWORKS itself orders them, so the FIRST occurrence seen is already
                # the most current one.
                items.setdefault(raw.external_id, raw)

    logger.info(
        "gmail_coreworks: parsed %d message(s), %d confirmed as COREWORKS RFQwire, %d listing(s) extracted",
        messages_scanned, messages_confirmed, len(items),
    )
    return list(items.values())


class CoreworksRfqwireConnector(IntelligenceConnector):
    key = "gmail_coreworks"
    name = SOURCE_NAME
    default_category = IntelligenceCategory.LIVE_OPPORTUNITY

    def is_configured(self) -> bool:
        return is_configured()

    def fetch(self, since: date, **filters) -> list[RawIntelligenceItem]:
        if not self.is_configured():
            raise ConnectorNotConfiguredError(
                "COREWORKS RFQwire integration is not configured. Set COREWORKS_APPS_SCRIPT_URL "
                "and COREWORKS_WEBHOOK_SECRET (see backend/.env.example and "
                "google-apps-script/coreworks_sync.gs for the one-time Apps Script deploy)."
            )
        messages = scan(since)
        raw_items = parse_messages_to_raw_items(messages)
        try:
            mark_processed([m["id"] for m in messages if m.get("id")])
        except CoreworksAppsScriptError:
            # Non-fatal: these messages were already fully parsed into raw_items above
            # (nothing here is lost), they'll just be scanned — and harmlessly,
            # idempotently re-parsed — again next time. See mark_processed()'s docstring.
            logger.exception("gmail_coreworks: mark_processed failed — messages will be re-scanned next sync")
        return raw_items
