"""Discover "Dismiss / Not Interested" — see app/services/dedup.py for the
ProjectCluster relationship this builds on, and docs/PHASE2_ARCHITECTURE.md §6.

Dismissing an item hides it — and, the whole point, every OTHER source's copy of the
same real-world procurement — from Discover's default view, without ever deleting the
IntelligenceItem row, its provenance, or touching dedup.py's own matching logic.

Two levels, by design:
- IntelligenceItem.is_dismissed — the specific row the user clicked Dismiss on.
- ProjectCluster.is_dismissed — the "normalized procurement concept." Set whenever a
  dismissed item is (or becomes) clustered, so every sibling — including one a FUTURE
  sync hasn't created yet — is suppressed by this one flag, with no per-item fan-out
  needed at dismiss time. intelligence_sync.py's per-item loop calls
  sync_cluster_dismissal_state() right after find_and_cluster_candidates() so a
  newly-clustered item immediately reflects its cluster's existing dismissal, in
  either direction — that's what actually satisfies "a future sync must not make it
  reappear": dedup.py's own matching rules (unmodified) decide WHETHER two records are
  the same procurement; this module only ever copies a dismissal flag across a link
  dedup.py already made, never influences the match itself.

One safety rule threaded through both directions: a cluster that contains an ALREADY
TRACKED item (opportunity_id set — a real, active pursuit) is never marked
cluster-dismissed, and an already-tracked item is never hidden by a cluster-level
dismissal regardless of what a sibling's own flag says — dismissing one source's
untracked copy of a procurement must never make a different source's actively-tracked
copy of that same procurement vanish from Discover.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import DismissalReason
from app.models.intelligence import IntelligenceItem, ProjectCluster

logger = logging.getLogger(__name__)


class ItemAlreadyTrackedError(RuntimeError):
    """Raised when Dismiss is attempted on an item that's already a tracked pursuit
    (opportunity_id is set). The caller (the route) turns this into a 409 — Dismiss
    must never look like, or act as, "close out this pursuit"."""


def _cluster_has_tracked_member(db: Session, cluster_id, exclude_item_id=None) -> bool:
    stmt = select(IntelligenceItem.id).where(
        IntelligenceItem.project_cluster_id == cluster_id,
        IntelligenceItem.opportunity_id.isnot(None),
    )
    if exclude_item_id is not None:
        stmt = stmt.where(IntelligenceItem.id != exclude_item_id)
    return db.execute(stmt).first() is not None


def effective_is_dismissed(item: IntelligenceItem, cluster: ProjectCluster | None) -> bool:
    """The one place "is this item actually hidden from Discover" is computed for an
    already-loaded item+cluster pair — mirrored as a SQL JOIN+WHERE in the list route
    for query-time filtering of the whole feed. An already-tracked item is never
    considered dismissed, regardless of either flag — see module docstring."""
    if item.opportunity_id is not None:
        return False
    return item.is_dismissed or bool(cluster and cluster.is_dismissed)


def dismiss_item(db: Session, item: IntelligenceItem, user_id, reason: DismissalReason | None = None) -> IntelligenceItem:
    """Dismisses `item` and, if it's clustered, the whole cluster (every sibling
    source's copy of the same procurement) — unless that cluster already has a
    different, actively tracked member, in which case only this one row is marked, so
    an active pursuit elsewhere in the same cluster is never affected. Raises
    ItemAlreadyTrackedError, touching nothing, if THIS item is already tracked."""
    if item.opportunity_id is not None:
        raise ItemAlreadyTrackedError(
            "This item is already tracked as an Opportunity. Dismiss only applies to "
            "untracked Discover items — use the Opportunity's own status in "
            "Pipeline to close out an active pursuit instead."
        )

    now = datetime.now(timezone.utc)
    item.is_dismissed = True
    item.dismissed_at = now
    item.dismissed_by_user_id = user_id
    item.dismissal_reason = reason

    if item.project_cluster_id is not None:
        cluster = db.get(ProjectCluster, item.project_cluster_id)
        if (
            cluster is not None
            and not cluster.is_dismissed
            and not _cluster_has_tracked_member(db, cluster.id, exclude_item_id=item.id)
        ):
            cluster.is_dismissed = True
            cluster.dismissed_at = now
            cluster.dismissed_by_user_id = user_id
            cluster.dismissal_reason = reason

    db.commit()
    db.refresh(item)
    return item


def restore_item(db: Session, item: IntelligenceItem, user_id) -> IntelligenceItem:
    """Undoes dismiss_item — clears both the item's own flag and, if clustered, the
    whole cluster's, so the procurement concept returns to normal Discover behavior
    (clearing only the item's own flag would leave it hidden via the cluster check).
    `user_id` isn't persisted anywhere today (no "restored_by" column exists) — kept as
    a parameter for symmetry with dismiss_item and in case that's added later."""
    item.is_dismissed = False
    item.dismissed_at = None
    item.dismissed_by_user_id = None
    item.dismissal_reason = None

    if item.project_cluster_id is not None:
        cluster = db.get(ProjectCluster, item.project_cluster_id)
        if cluster is not None:
            cluster.is_dismissed = False
            cluster.dismissed_at = None
            cluster.dismissed_by_user_id = None
            cluster.dismissal_reason = None

    db.commit()
    db.refresh(item)
    return item


def sync_cluster_dismissal_state(db: Session, item: IntelligenceItem) -> None:
    """Called from intelligence_sync.py's per-item loop, right after
    find_and_cluster_candidates() — so a newly-clustered item (today's fetch, matched
    against an existing dismissed item by dedup.py's EXISTING, unmodified matching
    rules) immediately inherits its cluster's dismissal. Also covers the reverse
    first-time case: an item was dismissed while still unclustered (no duplicate seen
    yet), and THIS sync is what first links it into a cluster with another source's
    item — the brand-new cluster inherits the dismissal immediately.

    Never influences dedup.py's own matching/clustering decision — this only ever
    reads project_cluster_id after the fact and copies a dismissal flag across a link
    dedup.py already made; it can never cause two records to cluster that dedup.py's
    own rules didn't already decide belong together. A no-op whenever a cluster
    contains an actively tracked member — see module docstring.
    """
    if item.project_cluster_id is None:
        return
    cluster = db.get(ProjectCluster, item.project_cluster_id)
    if cluster is None:
        return
    if _cluster_has_tracked_member(db, cluster.id):
        return

    if cluster.is_dismissed:
        if not item.is_dismissed:
            item.is_dismissed = True
            item.dismissed_at = cluster.dismissed_at
            item.dismissed_by_user_id = cluster.dismissed_by_user_id
            item.dismissal_reason = cluster.dismissal_reason
        return

    if item.is_dismissed:
        cluster.is_dismissed = True
        cluster.dismissed_at = item.dismissed_at
        cluster.dismissed_by_user_id = item.dismissed_by_user_id
        cluster.dismissal_reason = item.dismissal_reason
        return

    # Defensive: some other sibling was dismissed directly at the row level without
    # the cluster flag being set (shouldn't happen via dismiss_item(), which always
    # sets both together, but costs nothing to guard here too) — propagate so the
    # cluster-level flag can't silently drift behind an already-dismissed member.
    dismissed_sibling = db.execute(
        select(IntelligenceItem).where(
            IntelligenceItem.project_cluster_id == cluster.id,
            IntelligenceItem.is_dismissed.is_(True),
        )
    ).scalars().first()
    if dismissed_sibling is not None:
        cluster.is_dismissed = True
        cluster.dismissed_at = dismissed_sibling.dismissed_at
        cluster.dismissed_by_user_id = dismissed_sibling.dismissed_by_user_id
        cluster.dismissal_reason = dismissed_sibling.dismissal_reason
        item.is_dismissed = True
        item.dismissed_at = dismissed_sibling.dismissed_at
        item.dismissed_by_user_id = dismissed_sibling.dismissed_by_user_id
        item.dismissal_reason = dismissed_sibling.dismissal_reason
