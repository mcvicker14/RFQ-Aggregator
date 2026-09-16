from sqlalchemy import select

from app.models.intelligence import IntelligenceSource
from seed.intelligence_sources import SOURCES, seed_intelligence_sources


def test_seeding_creates_every_listed_source(db):
    seed_intelligence_sources(db)

    count = db.execute(select(IntelligenceSource)).scalars().all()
    seeded_names = {s.name for s in count}
    assert seeded_names == {entry["name"] for entry in SOURCES}


def test_only_sources_with_a_working_connector_are_enabled_on_first_creation(db):
    # Deliberately does not just call seed_intelligence_sources(db) against whatever
    # is already in the database: is_enabled is excluded from _UPDATE_ON_RESEED by
    # design (redeploying must never silently flip a switch an admin already set, or
    # one this same seed already set on an earlier run), so this "enabled by default"
    # behavior only shows up on a row's first creation. Clearing existing rows with
    # these names first isolates that create path from whatever a previous run in this
    # database already committed.
    db.execute(IntelligenceSource.__table__.delete().where(
        IntelligenceSource.name.in_(["SAM.gov", "USAspending.gov", "Grants.gov"])
    ))

    seed_intelligence_sources(db)

    enabled = db.execute(select(IntelligenceSource).where(IntelligenceSource.is_enabled.is_(True))).scalars().all()
    assert {s.name for s in enabled} == {"SAM.gov", "USAspending.gov", "Grants.gov"}


def test_reseeding_is_idempotent(db):
    seed_intelligence_sources(db)
    first_count = len(db.execute(select(IntelligenceSource)).scalars().all())

    seed_intelligence_sources(db)  # must not raise, must not duplicate
    second_count = len(db.execute(select(IntelligenceSource)).scalars().all())

    assert first_count == second_count == len(SOURCES)


def test_reseeding_preserves_admin_runtime_state(db):
    seed_intelligence_sources(db)
    grants_gov = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "Grants.gov")).scalars().one()
    # Grants.gov is enabled by default (it has a working connector) — set it to the
    # opposite of that default so this test actually proves reseeding preserves an
    # administrator's choice, rather than coincidentally matching the seed default.
    grants_gov.is_enabled = False
    grants_gov.last_result_count = 42
    db.commit()

    seed_intelligence_sources(db)

    db.refresh(grants_gov)
    assert grants_gov.is_enabled is False
    assert grants_gov.last_result_count == 42
