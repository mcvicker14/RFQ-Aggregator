"""Deletes sample/demo data (is_sample_data=True). This is the actual removal step —
see seed/audit_sample_data.py for the read-only report this reuses as its *only*
source of truth for what's safe to delete, so the two scripts can never disagree.

Never deletes:
  - an Agency or Company audit_sample_data.py finds a real (non-sample) dependent for
    — every FK into these tables is ON DELETE CASCADE, so deleting one of these would
    take the real dependent down with it; see that module's docstring for the full
    reasoning and how it distinguishes a real dependent from a seed-created one.
  - anything without is_sample_data=True on its own row. In particular, a Task with no
    opportunity_id has no flag of its own and no parent to inherit sample-status from
    — audit_sample_data.py reports these by count for manual review; this script never
    touches them.

Requires --yes to actually delete anything. Without it, runs the exact same read-only
audit as `python -m seed.audit_sample_data` and stops — safe to run with no arguments
to preview. This script is NOT gated by ENV the way seed.py's demo-data seeding is:
that gate stops sample data from being *created* in production; this script is what
*removes* it once already there, so it is meant to be run against production.

Usage (from backend/, with the venv active and DATABASE_URL pointed at the database to
clean up):
    python -m seed.cleanup_sample_data           # dry run -- audit only, deletes nothing
    python -m seed.cleanup_sample_data --yes     # performs the deletion
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.agency import Agency  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.intelligence import IntelligenceItem  # noqa: E402
from app.models.opportunity import Opportunity  # noqa: E402
from seed.audit_sample_data import audit_agencies, audit_companies, run_audit, table_counts  # noqa: E402


def cleanup(db: Session, *, confirm: bool) -> None:
    run_audit(db)

    safe_agencies, blocked_agencies = audit_agencies(db)
    safe_companies, blocked_companies = audit_companies(db)

    if not confirm:
        print("\nDry run only — nothing was deleted. Re-run with --yes to perform this cleanup.")
        return

    print("\n" + "=" * 78)
    print("DELETING — this cannot be undone")
    print("=" * 78)

    # Order matters only for keeping each statement's own rowcount an accurate,
    # uncorrelated report -- opportunities/intelligence_items first (by their own
    # flag) so a later agency/company delete's cascade never silently shrinks what an
    # earlier statement reports having removed.
    opp_deleted = db.execute(delete(Opportunity).where(Opportunity.is_sample_data.is_(True))).rowcount
    item_deleted = db.execute(delete(IntelligenceItem).where(IntelligenceItem.is_sample_data.is_(True))).rowcount

    agency_ids = [agency.id for agency, _, _ in safe_agencies]
    company_ids = [company.id for company, _, _ in safe_companies]
    agency_deleted = db.execute(delete(Agency).where(Agency.id.in_(agency_ids))).rowcount if agency_ids else 0
    company_deleted = db.execute(delete(Company).where(Company.id.in_(company_ids))).rowcount if company_ids else 0

    db.commit()

    print(f"\nDeleted: {opp_deleted} opportunities, {item_deleted} intelligence_items, "
          f"{agency_deleted} agencies, {company_deleted} companies")
    print("(+ all cascade-dependent rows: tasks, contact links, activities, forecasts, "
          "go/no-go reviews, win/loss reviews, alerts, scores, documents, AI analyses, "
          "agency offices, and any contacts only linked to a deleted agency/company).")
    if blocked_agencies or blocked_companies:
        print(f"\nPreserved (a real record still depends on them): "
              f"{len(blocked_agencies)} agencies, {len(blocked_companies)} companies.")
        print("These are still flagged is_sample_data=True but were NOT deleted -- see the")
        print("BLOCKED list above for exactly what still references each one.")

    print("\n-- Post-cleanup counts --")
    final = table_counts(db)
    for name, c in final.items():
        print(f"  {name:22s} total={c['total']:6d}   sample={c['sample']:6d}   real={c['real']:6d}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Actually perform the deletion (default: dry run / audit only)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        cleanup(db, confirm=args.yes)
    finally:
        db.close()


if __name__ == "__main__":
    main()
