"""Covers the production sample-data guard (should_seed_demo_data) and the cleanup
script's safety guarantee that a sample-flagged Agency/Company with a real dependent
is never cascade-deleted. See seed/audit_sample_data.py and seed/cleanup_sample_data.py
for the mechanism these exercise.

The `db` fixture runs against the real local database inside an outer transaction that
is always rolled back (see conftest.py), so calling cleanup(confirm=True) here -- which
internally does real DELETEs and a db.commit() that only releases a SAVEPOINT under
create_savepoint join mode -- is safe and leaves no trace once the test ends.
"""
from sqlalchemy import select

from app.models.agency import Agency
from app.models.company import Company
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.task import Task
from seed.audit_sample_data import orphan_task_count, table_counts
from seed.cleanup_sample_data import cleanup
from seed.seed import settings, should_seed_demo_data


# --- should_seed_demo_data: production must never seed, dev/test always can absent --no-demo ---

def test_seeds_demo_data_by_default_outside_production(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "development")
    assert should_seed_demo_data(no_demo_flag=False) is True


def test_no_demo_flag_skips_seeding_outside_production(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "development")
    assert should_seed_demo_data(no_demo_flag=True) is False


def test_production_never_seeds_demo_data_even_without_no_demo_flag(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")
    assert should_seed_demo_data(no_demo_flag=False) is False


def test_production_never_seeds_demo_data_with_no_demo_flag_either(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")
    assert should_seed_demo_data(no_demo_flag=True) is False


# --- cleanup(): dry run is inert ---

def test_cleanup_dry_run_changes_nothing(db):
    before = table_counts(db)
    cleanup(db, confirm=False)
    after = table_counts(db)
    assert after == before


# --- cleanup(): sample rows removed by their own flag; real rows in the same tables untouched ---

def test_cleanup_removes_sample_opportunities_and_intelligence_items_only(db):
    before = table_counts(db)
    assert before["opportunities"]["sample"] > 0  # sanity: local dev DB has seeded sample data

    cleanup(db, confirm=True)

    after = table_counts(db)
    assert after["opportunities"]["sample"] == 0
    assert after["intelligence_items"]["sample"] == 0
    assert after["opportunities"]["real"] == before["opportunities"]["real"]
    assert after["intelligence_items"]["real"] == before["intelligence_items"]["real"]


# --- cleanup(): an Agency/Company a real record still depends on is preserved, not cascaded away ---

def test_cleanup_preserves_agency_referenced_by_a_real_opportunity(db):
    sample_agencies = db.execute(select(Agency).where(Agency.is_sample_data.is_(True))).scalars().all()
    assert len(sample_agencies) > 1  # sanity: need >=2 to prove this one survives while others don't
    target = sample_agencies[0]

    real_opp = Opportunity(
        title="Real live pursuit referencing a sample agency", agency_id=target.id, is_sample_data=False
    )
    db.add(real_opp)
    db.flush()

    cleanup(db, confirm=True)

    survivor = db.get(Agency, target.id)
    assert survivor is not None
    assert survivor.is_sample_data is True  # still flagged sample -- just correctly not deleted this run
    assert db.get(Opportunity, real_opp.id) is not None  # the real dependent itself is untouched

    remaining_sample_agency_ids = {
        a.id for a in db.execute(select(Agency).where(Agency.is_sample_data.is_(True))).scalars()
    }
    assert remaining_sample_agency_ids == {target.id}  # every OTHER pure-sample agency was actually removed


def test_cleanup_preserves_company_referenced_by_a_real_contact(db):
    sample_companies = db.execute(select(Company).where(Company.is_sample_data.is_(True))).scalars().all()
    assert len(sample_companies) > 1  # sanity: need >=2 to prove this one survives while others don't
    target = sample_companies[0]

    # Deliberately not the seed's "sample.contact+*@example.*" convention -- this is what
    # makes it count as a real, unconfirmed dependent (see _contact_blockers).
    real_contact = Contact(full_name="Real Live Contact", company_id=target.id, email="real.contact@principal-eng.com")
    db.add(real_contact)
    db.flush()

    cleanup(db, confirm=True)

    survivor = db.get(Company, target.id)
    assert survivor is not None
    assert survivor.is_sample_data is True
    assert db.get(Contact, real_contact.id) is not None

    remaining_sample_company_ids = {
        c.id for c in db.execute(select(Company).where(Company.is_sample_data.is_(True))).scalars()
    }
    assert remaining_sample_company_ids == {target.id}


# --- cleanup(): never touches a Task with no opportunity_id -- no unambiguous rule identifies it ---

def test_cleanup_never_deletes_an_orphan_task(db):
    orphan = Task(title="Orphan task with no opportunity_id")
    db.add(orphan)
    db.flush()
    orphan_id = orphan.id
    before_orphans = orphan_task_count(db)

    cleanup(db, confirm=True)

    assert db.get(Task, orphan_id) is not None
    assert orphan_task_count(db) == before_orphans
