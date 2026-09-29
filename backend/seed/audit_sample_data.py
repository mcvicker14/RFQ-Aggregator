"""Read-only audit of sample/demo data (is_sample_data=True) — safe to run against
production; never writes or deletes anything. See backend/seed/cleanup_sample_data.py
for the deletion this prepares for.

WHAT COUNTS AS SAMPLE DATA: exactly four tables carry an explicit `is_sample_data`
boolean column (NOT NULL, default false) — opportunities, intelligence_items,
companies, agencies. Every one of the ~30 other tables that hangs off these four does
so through a foreign key with ON DELETE CASCADE (verified directly against the schema,
not assumed — see the FK query in this module's own history/PR description), so
deleting a sample-flagged parent row correctly removes its sample-only children
(tasks, contacts-via-opportunity_contacts, activities, forecasts, go/no-go reviews,
win/loss reviews, alerts, scores, documents, AI analyses, agency offices, etc.)
without needing a flag on every one of those tables too.

THE ONE SHARP EDGE CASCADE CREATES: deleting a sample Agency or Company cascades to
*everything* that references it — including a real (is_sample_data=False) Opportunity
or IntelligenceItem that happens to point at that same Agency/Company row (e.g. a real
SAM.gov notice resolved to the pre-existing sample "U.S. Army Corps of Engineers"
Agency by exact name match — see _resolve_agency_for_item in
app/services/intelligence_sync.py). A naive `DELETE FROM agencies WHERE
is_sample_data` would silently take the real Opportunity down with it. This script
checks for exactly that before recommending any Agency/Company for deletion — see
_agency_blockers / _company_blockers below. Opportunities and IntelligenceItems are
never subject to this risk: they're always deleted by their own is_sample_data flag,
never by cascade from Agency/Company.

WHAT THIS SCRIPT DOES NOT AND CANNOT IDENTIFY: Task (and every other non-flagged
table) has no is_sample_data column of its own. A Task linked to a sample Opportunity
is correctly removed by that Opportunity's cascade. A Task with no opportunity_id at
all (the seed script creates exactly one: "Review USACE Mobile District procurement
forecast for Q1") has no flag and no parent to inherit sample-status from — there is
no unambiguous rule that identifies it. This script reports such orphan tasks
separately, by count only, and never recommends deleting them.

Usage (from backend/, with the venv active and DATABASE_URL pointed at whichever
database you want to audit — including production, read-only):
    python -m seed.audit_sample_data
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.agency import Agency  # noqa: E402
from app.models.company import Company, OpportunityCompany  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.intelligence import IntelligenceItem  # noqa: E402
from app.models.opportunity import Opportunity  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.winloss import WinLossReview  # noqa: E402

SAMPLE_FLAGGED_MODELS = [
    (Opportunity, "opportunities"),
    (IntelligenceItem, "intelligence_items"),
    (Company, "companies"),
    (Agency, "agencies"),
]


def table_counts(db: Session) -> dict[str, dict[str, int]]:
    counts = {}
    for model, name in SAMPLE_FLAGGED_MODELS:
        total = db.execute(select(func.count()).select_from(model)).scalar_one()
        sample = db.execute(select(func.count()).select_from(model).where(model.is_sample_data.is_(True))).scalar_one()
        counts[name] = {"total": total, "sample": sample, "real": total - sample}
    return counts


# Contact has no is_sample_data column at all. Every Contact seed.py's seed_demo_data()
# creates uses this exact, deliberate, non-organic email convention (verified against
# seed.py directly, not guessed) -- "sample.contact+<initials>@example.{gov,com}". This
# is a structured marker the seed data itself establishes, not a fuzzy content guess:
# used only as corroborating evidence below, and only to *narrow* what counts as a
# blocker, never to independently trigger a deletion on its own. Any contact that does
# NOT match it is treated as unconfirmed and blocks deletion unconditionally.
_SAMPLE_CONTACT_EMAIL_PATTERN = "sample.contact+%@example.%"


def _contact_blockers(db: Session, *, agency_id=None, company_id=None) -> tuple[int, int]:
    """Returns (matches_seed_pattern, does_not_match) for Contacts referencing this
    Agency or Company. Only the second number should ever block a deletion."""
    condition = Contact.agency_id == agency_id if agency_id is not None else Contact.company_id == company_id
    matches = db.execute(
        select(func.count()).select_from(Contact).where(condition, Contact.email.like(_SAMPLE_CONTACT_EMAIL_PATTERN))
    ).scalar_one()
    total = db.execute(select(func.count()).select_from(Contact).where(condition)).scalar_one()
    return matches, total - matches


def _agency_blockers(db: Session, agency_id) -> tuple[dict[str, int], dict[str, int]]:
    """Returns (hard_blockers, informational). Any non-zero value in hard_blockers
    means deleting this Agency would cascade-delete something that isn't confirmed
    sample data — see module docstring."""
    matching, unmatched = _contact_blockers(db, agency_id=agency_id)
    hard = {
        "real_opportunities": db.execute(
            select(func.count()).select_from(Opportunity)
            .where(Opportunity.agency_id == agency_id, Opportunity.is_sample_data.is_(False))
        ).scalar_one(),
        "real_intelligence_items": db.execute(
            select(func.count()).select_from(IntelligenceItem)
            .where(IntelligenceItem.agency_id == agency_id, IntelligenceItem.is_sample_data.is_(False))
        ).scalar_one(),
        "contacts_not_matching_seed_email_pattern": unmatched,
    }
    return hard, {"contacts_matching_seed_email_pattern": matching}


def _company_blockers(db: Session, company_id) -> tuple[dict[str, int], dict[str, int]]:
    matching, unmatched = _contact_blockers(db, company_id=company_id)
    hard = {
        "real_opportunities_incumbent": db.execute(
            select(func.count()).select_from(Opportunity)
            .where(Opportunity.incumbent_company_id == company_id, Opportunity.is_sample_data.is_(False))
        ).scalar_one(),
        "real_intelligence_items": db.execute(
            select(func.count()).select_from(IntelligenceItem)
            .where(
                IntelligenceItem.is_sample_data.is_(False),
                (IntelligenceItem.incumbent_company_id == company_id) | (IntelligenceItem.awardee_company_id == company_id),
            )
        ).scalar_one(),
        "contacts_not_matching_seed_email_pattern": unmatched,
        "real_opportunity_teaming_links": db.execute(
            select(func.count()).select_from(OpportunityCompany).join(
                Opportunity, OpportunityCompany.opportunity_id == Opportunity.id
            ).where(OpportunityCompany.company_id == company_id, Opportunity.is_sample_data.is_(False))
        ).scalar_one(),
        "real_winloss_winner": db.execute(
            select(func.count()).select_from(WinLossReview).join(
                Opportunity, WinLossReview.opportunity_id == Opportunity.id
            ).where(WinLossReview.winner_company_id == company_id, Opportunity.is_sample_data.is_(False))
        ).scalar_one(),
    }
    return hard, {"contacts_matching_seed_email_pattern": matching}


def audit_agencies(db: Session) -> tuple[list, list]:
    """Returns (safe_to_delete, blocked) — each a list of (Agency, hard_blockers, informational)."""
    safe, blocked = [], []
    for agency in db.execute(select(Agency).where(Agency.is_sample_data.is_(True))).scalars().all():
        hard, info = _agency_blockers(db, agency.id)
        (blocked if any(hard.values()) else safe).append((agency, hard, info))
    return safe, blocked


def audit_companies(db: Session) -> tuple[list, list]:
    safe, blocked = [], []
    for company in db.execute(select(Company).where(Company.is_sample_data.is_(True))).scalars().all():
        hard, info = _company_blockers(db, company.id)
        (blocked if any(hard.values()) else safe).append((company, hard, info))
    return safe, blocked


def orphan_task_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Task).where(Task.opportunity_id.is_(None))).scalar_one()


def orphan_tasks(db: Session) -> list[Task]:
    """The actual rows behind orphan_task_count. Never auto-deleted or otherwise acted
    on by this module or cleanup_sample_data.py -- returned only so a human can review
    each one's provenance by hand (see module docstring)."""
    return list(db.execute(select(Task).where(Task.opportunity_id.is_(None))).scalars().all())


def run_audit(db: Session) -> None:
    print("=" * 78)
    print("SAMPLE DATA AUDIT — read-only, nothing is written or deleted")
    print("=" * 78)

    counts = table_counts(db)
    print("\n-- Counts by table (is_sample_data = true) --")
    for name, c in counts.items():
        print(f"  {name:22s} total={c['total']:6d}   sample={c['sample']:6d}   real={c['real']:6d}")

    print(f"\nOpportunities and intelligence_items are always safe to delete by their own")
    print(f"is_sample_data flag: {counts['opportunities']['sample']} opportunities, "
          f"{counts['intelligence_items']['sample']} intelligence_items.")

    safe_agencies, blocked_agencies = audit_agencies(db)
    safe_companies, blocked_companies = audit_companies(db)

    print(f"\n-- Agencies flagged sample: {counts['agencies']['sample']} --")
    print(f"  Safe to delete (no real dependents): {len(safe_agencies)}")
    for agency, _, info in safe_agencies:
        note = f" ({info['contacts_matching_seed_email_pattern']} seed-pattern contact(s) will cascade with it)" if info["contacts_matching_seed_email_pattern"] else ""
        print(f"    - {agency.name}{note}")
    print(f"  BLOCKED (a real record still references this row — will NOT be deleted): {len(blocked_agencies)}")
    for agency, hard, _ in blocked_agencies:
        nonzero = {k: v for k, v in hard.items() if v}
        print(f"    - {agency.name}: {nonzero}")

    print(f"\n-- Companies flagged sample: {counts['companies']['sample']} --")
    print(f"  Safe to delete (no real dependents): {len(safe_companies)}")
    for company, _, info in safe_companies:
        note = f" ({info['contacts_matching_seed_email_pattern']} seed-pattern contact(s) will cascade with it)" if info["contacts_matching_seed_email_pattern"] else ""
        print(f"    - {company.name}{note}")
    print(f"  BLOCKED (a real record still references this row — will NOT be deleted): {len(blocked_companies)}")
    for company, hard, _ in blocked_companies:
        nonzero = {k: v for k, v in hard.items() if v}
        print(f"    - {company.name}: {nonzero}")

    orphans = orphan_tasks(db)
    print(f"\n-- Tasks with no opportunity_id: {len(orphans)} --")
    print("  Task has no is_sample_data column and these have no parent to inherit")
    print("  sample-status from — NOT included in any deletion count. This script will")
    print("  never guess based on title text; review each one by hand:")
    for task in orphans:
        print(f"    - [{task.id}] \"{task.title}\" (status={task.status.value}, "
              f"priority={task.priority.value}, due={task.due_date}, created={task.created_at})")

    print("\n" + "=" * 78)
    print("SUMMARY — what a cleanup run would remove:")
    print(f"  {counts['opportunities']['sample']} opportunities (+ all cascade-dependent rows: tasks, contacts")
    print(f"    links, activities, forecasts, go/no-go reviews, win/loss reviews, alerts,")
    print(f"    scores, documents, AI analyses)")
    print(f"  {counts['intelligence_items']['sample']} intelligence_items")
    print(f"  {len(safe_agencies)} agencies (+ their offices, and any contacts only linked to them)")
    print(f"  {len(safe_companies)} companies (+ any contacts only linked to them)")
    if blocked_agencies or blocked_companies:
        print(f"  {len(blocked_agencies)} agencies and {len(blocked_companies)} companies are flagged sample")
        print(f"    but will be PRESERVED because real data still depends on them.")
    if orphans:
        print(f"  {len(orphans)} orphan task(s) require your manual review — not auto-included.")
    print("=" * 78)


def main():
    db = SessionLocal()
    try:
        run_audit(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
