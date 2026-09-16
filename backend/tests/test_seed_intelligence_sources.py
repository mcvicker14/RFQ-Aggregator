from sqlalchemy import select

from app.models.intelligence import IntelligenceSource
from seed.intelligence_sources import SOURCES, seed_intelligence_sources


def test_seeding_creates_every_listed_source(db):
    seed_intelligence_sources(db)

    count = db.execute(select(IntelligenceSource)).scalars().all()
    seeded_names = {s.name for s in count}
    assert seeded_names == {entry["name"] for entry in SOURCES}


def test_only_sam_gov_is_enabled_by_default(db):
    seed_intelligence_sources(db)

    enabled = db.execute(select(IntelligenceSource).where(IntelligenceSource.is_enabled.is_(True))).scalars().all()
    assert [s.name for s in enabled] == ["SAM.gov"]


def test_reseeding_is_idempotent(db):
    seed_intelligence_sources(db)
    first_count = len(db.execute(select(IntelligenceSource)).scalars().all())

    seed_intelligence_sources(db)  # must not raise, must not duplicate
    second_count = len(db.execute(select(IntelligenceSource)).scalars().all())

    assert first_count == second_count == len(SOURCES)


def test_reseeding_preserves_admin_runtime_state(db):
    seed_intelligence_sources(db)
    grants_gov = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "Grants.gov")).scalars().one()
    grants_gov.is_enabled = True
    grants_gov.last_result_count = 42
    db.commit()

    seed_intelligence_sources(db)

    db.refresh(grants_gov)
    assert grants_gov.is_enabled is True
    assert grants_gov.last_result_count == 42
