"""Entity resolution / deduplication across intelligence sources. See
docs/PHASE2_ARCHITECTURE.md §6.

The one rule this whole module exists to enforce: matching NEVER deletes or merges a
row, and NEVER writes CONFIRMED_SAME_PROJECT itself — it only ever proposes
LIKELY_DUPLICATE or POSSIBLE_DUPLICATE by grouping items under a shared
ProjectCluster. Confirming (or rejecting) a proposed match is a human action via
confirm_cluster()/reject_cluster() below, called from an API route a person clicks
through, never from the sync path.
"""
import re
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.enums import DedupStatus
from app.models.intelligence import IntelligenceItem, ProjectCluster

# Identifier fields checked first, in order — an exact match on any of these is
# treated as strong enough on its own (no title/date corroboration needed).
IDENTIFIER_FIELDS = ("solicitation_number", "contract_number", "funding_award_number", "project_number")

TITLE_LIKELY_THRESHOLD = 0.82
TITLE_POSSIBLE_THRESHOLD = 0.55
DATE_PROXIMITY_DAYS = 21

# Never downgrade a cluster member's status when a new match joins the cluster.
_STATUS_RANK = {
    DedupStatus.UNCLUSTERED: 0,
    DedupStatus.POSSIBLE_DUPLICATE: 1,
    DedupStatus.LIKELY_DUPLICATE: 2,
    DedupStatus.CONFIRMED_SAME_PROJECT: 3,
}


def _normalized_word_order(text: str) -> str:
    """Words sorted alphabetically, so 'Pump Station Rehab, Slidell' and 'Slidell Pump
    Station Rehabilitation' compare as similar despite different word order — two
    independent sources describing the same project rarely use identical phrasing."""
    return " ".join(sorted(re.findall(r"[a-z0-9]+", text.lower())))


def _title_similarity(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    raw_ratio = SequenceMatcher(None, a, b).ratio()
    word_order_ratio = SequenceMatcher(None, _normalized_word_order(a), _normalized_word_order(b)).ratio()
    return max(raw_ratio, word_order_ratio)


def _dates_close(item: IntelligenceItem, other: IntelligenceItem) -> bool:
    a = item.proposal_due_at or item.posted_at
    b = other.proposal_due_at or other.posted_at
    if a is None or b is None:
        return False
    return abs((a - b).days) <= DATE_PROXIMITY_DAYS


def _find_identifier_match(db: Session, item: IntelligenceItem) -> tuple[IntelligenceItem | None, str | None]:
    for field_name in IDENTIFIER_FIELDS:
        value = getattr(item, field_name)
        if not value:
            continue
        column = getattr(IntelligenceItem, field_name)
        match = db.execute(
            select(IntelligenceItem).where(
                column.isnot(None),
                func.lower(column) == value.lower(),
                IntelligenceItem.id != item.id,
            )
        ).scalars().first()
        if match is not None:
            return match, field_name
    return None, None


def _find_agency_location_candidates(db: Session, item: IntelligenceItem) -> list[IntelligenceItem]:
    if not item.location_state:
        return []
    if item.agency_id:
        agency_condition = IntelligenceItem.agency_id == item.agency_id
    elif item.agency_name:
        agency_condition = func.lower(IntelligenceItem.agency_name) == item.agency_name.lower()
    else:
        return []
    return db.execute(
        select(IntelligenceItem).where(
            IntelligenceItem.location_state == item.location_state,
            agency_condition,
            IntelligenceItem.id != item.id,
        )
    ).scalars().all()


def _link(db: Session, item: IntelligenceItem, candidate: IntelligenceItem, status: DedupStatus, reason: str) -> None:
    cluster = db.get(ProjectCluster, candidate.project_cluster_id) if candidate.project_cluster_id else None
    if cluster is None:
        cluster = ProjectCluster(representative_title=candidate.title)
        db.add(cluster)
        db.flush()
        candidate.project_cluster_id = cluster.id

    if _STATUS_RANK[status] > _STATUS_RANK[candidate.dedup_status]:
        candidate.dedup_status = status
        candidate.dedup_match_reason = reason

    item.project_cluster_id = cluster.id
    item.dedup_status = status
    item.dedup_match_reason = reason
    db.flush()


def find_and_cluster_candidates(db: Session, item: IntelligenceItem) -> None:
    """Look for other intelligence_items that plausibly describe the same real-world
    project as `item`, and if found, group them under a shared ProjectCluster.
    Safe to call unconditionally — a no-op if `item` is already clustered (re-running
    dedup on every sync, not just on newly-created items, would just churn statuses
    without adding information)."""
    if item.dedup_status != DedupStatus.UNCLUSTERED:
        return

    identifier_match, matched_field = _find_identifier_match(db, item)
    if identifier_match is not None:
        field_label = matched_field.replace("_", " ")
        _link(
            db, item, identifier_match, DedupStatus.LIKELY_DUPLICATE,
            f"Same {field_label} ({getattr(item, matched_field)}).",
        )
        return

    for candidate in _find_agency_location_candidates(db, item):
        similarity = _title_similarity(item.title, candidate.title)
        dates_close = _dates_close(item, candidate)

        if similarity >= TITLE_LIKELY_THRESHOLD:
            status = DedupStatus.LIKELY_DUPLICATE
        elif similarity >= TITLE_POSSIBLE_THRESHOLD and dates_close:
            status = DedupStatus.POSSIBLE_DUPLICATE
        else:
            continue

        reason = f"Title similarity {similarity:.0%}; same agency; same state ({item.location_state})"
        if dates_close:
            reason += "; dates within 21 days"
        _link(db, item, candidate, status, reason + ".")
        return  # first sufficiently-strong match wins — a human can broaden the cluster later


def confirm_cluster(db: Session, item: IntelligenceItem, user_id) -> None:
    """A human confirmed item's cluster is genuinely the same project."""
    item.dedup_status = DedupStatus.CONFIRMED_SAME_PROJECT
    if item.project_cluster_id:
        cluster = db.get(ProjectCluster, item.project_cluster_id)
        if cluster is not None:
            cluster.confirmed_by_user_id = user_id
            cluster.confirmed_at = utcnow()
    db.flush()


def reject_cluster(db: Session, item: IntelligenceItem) -> None:
    """A human decided item does NOT belong with its cluster-mates. Detaches only this
    item — nothing else in the cluster changes, and no row is ever deleted."""
    item.project_cluster_id = None
    item.dedup_status = DedupStatus.UNCLUSTERED
    item.dedup_match_reason = None
    db.flush()
