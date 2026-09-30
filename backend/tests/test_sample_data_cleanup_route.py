"""POST /api/admin/sample-data-cleanup -- admin-only, dry-run by default, real deletion
only with the exact confirm value (see app/api/routes/sample_data_cleanup.py).

Like tests/test_sample_data_cleanup.py, this calls the real cleanup() against the real
local database inside the `db` fixture's outer transaction (see conftest.py) -- every
write here, including through the HTTP route, is rolled back when the test ends.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes.sample_data_cleanup import CLEANUP_CONFIRM_VALUE
from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.agency import Agency
from app.models.company import Company
from app.models.contact import Contact
from app.models.enums import UserRole
from app.models.opportunity import Opportunity
from app.models.task import Task
from app.models.user import User
from seed.audit_sample_data import table_counts


def _user(role):
    return User(id=None, email="test@example.com", full_name="Test", hashed_password="x", role=role, is_active=True)


@pytest.fixture()
def viewer_client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.VIEWER)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def admin_client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.ADMINISTRATOR)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_non_admin_cannot_call_cleanup(viewer_client):
    assert viewer_client.post("/api/admin/sample-data-cleanup").status_code == 403


def test_get_is_not_allowed_on_this_path(admin_client):
    assert admin_client.get("/api/admin/sample-data-cleanup").status_code == 405


def test_dry_run_with_no_body_changes_nothing(admin_client, db):
    before = table_counts(db)

    response = admin_client.post("/api/admin/sample-data-cleanup")

    assert response.status_code == 200
    body = response.json()
    assert body["performed"] is False
    assert body["after_counts"] is None
    assert body["deleted"] is None
    assert table_counts(db) == before


def test_dry_run_reports_expected_shape_matching_current_state(admin_client, db):
    body = admin_client.post("/api/admin/sample-data-cleanup", json={}).json()

    assert body["confirm_value_required"] == "DELETE_SAMPLE_DATA"
    assert body["before_counts"] == table_counts(db)
    assert body["before_counts"]["opportunities"]["sample"] > 0  # sanity: seeded locally
    assert "report_text" in body and "Dry run only" in body["report_text"]
    for key in ("safe_agencies", "blocked_agencies", "safe_companies", "blocked_companies", "orphan_tasks"):
        assert key in body


@pytest.mark.parametrize("near_miss", [
    "delete_sample_data",       # wrong case
    "DELETE SAMPLE DATA",       # space instead of underscore
    " DELETE_SAMPLE_DATA",      # leading whitespace
    "DELETE_SAMPLE_DATA ",      # trailing whitespace
    "yes", "true", "1", "",     # generic truthy-looking values
])
def test_near_miss_confirm_values_all_stay_a_dry_run(admin_client, db, near_miss):
    before = table_counts(db)

    response = admin_client.post("/api/admin/sample-data-cleanup", json={"confirm": near_miss})

    assert response.status_code == 200
    assert response.json()["performed"] is False
    assert table_counts(db) == before


def test_exact_confirm_value_performs_the_real_deletion(admin_client, db):
    before = table_counts(db)
    assert before["opportunities"]["sample"] > 0  # sanity

    response = admin_client.post("/api/admin/sample-data-cleanup", json={"confirm": CLEANUP_CONFIRM_VALUE})

    assert response.status_code == 200
    body = response.json()
    assert body["performed"] is True
    assert body["before_counts"] == before
    assert body["deleted"]["opportunities"] == before["opportunities"]["sample"]
    assert body["deleted"]["intelligence_items"] == before["intelligence_items"]["sample"]

    after = table_counts(db)
    assert body["after_counts"] == after
    assert after["opportunities"]["sample"] == 0
    assert after["intelligence_items"]["sample"] == 0
    assert after["companies"]["sample"] == 0
    assert after["agencies"]["sample"] == 0
    # real rows in the same 4 tables are untouched
    assert after["opportunities"]["real"] == before["opportunities"]["real"]
    assert after["intelligence_items"]["real"] == before["intelligence_items"]["real"]
    assert after["agencies"]["real"] == before["agencies"]["real"]
    assert after["companies"]["real"] == before["companies"]["real"]


def test_real_opportunity_survives_cleanup(admin_client, db):
    real_opp = Opportunity(title="Real live pursuit, unrelated to any sample agency", is_sample_data=False)
    db.add(real_opp)
    db.flush()

    admin_client.post("/api/admin/sample-data-cleanup", json={"confirm": CLEANUP_CONFIRM_VALUE})

    assert db.get(Opportunity, real_opp.id) is not None


def test_blocked_agency_survives_cleanup(admin_client, db):
    sample_agencies = db.execute(select(Agency).where(Agency.is_sample_data.is_(True))).scalars().all()
    assert len(sample_agencies) > 1  # sanity: need >=2 to prove this one survives while others don't
    target = sample_agencies[0]

    real_opp = Opportunity(title="Real live pursuit referencing a sample agency", agency_id=target.id, is_sample_data=False)
    db.add(real_opp)
    db.flush()

    body = admin_client.post("/api/admin/sample-data-cleanup", json={"confirm": CLEANUP_CONFIRM_VALUE}).json()

    survivor = db.get(Agency, target.id)
    assert survivor is not None
    assert survivor.is_sample_data is True
    assert db.get(Opportunity, real_opp.id) is not None
    assert str(target.id) in {row["id"] for row in body["blocked_agencies"]}

    remaining_sample_agency_ids = {
        a.id for a in db.execute(select(Agency).where(Agency.is_sample_data.is_(True))).scalars()
    }
    assert remaining_sample_agency_ids == {target.id}  # every OTHER pure-sample agency was actually removed


def test_blocked_company_survives_cleanup(admin_client, db):
    sample_companies = db.execute(select(Company).where(Company.is_sample_data.is_(True))).scalars().all()
    assert len(sample_companies) > 1  # sanity
    target = sample_companies[0]

    real_contact = Contact(full_name="Real Live Contact", company_id=target.id, email="real.contact@principal-eng.com")
    db.add(real_contact)
    db.flush()

    body = admin_client.post("/api/admin/sample-data-cleanup", json={"confirm": CLEANUP_CONFIRM_VALUE}).json()

    survivor = db.get(Company, target.id)
    assert survivor is not None
    assert survivor.is_sample_data is True
    assert db.get(Contact, real_contact.id) is not None
    assert str(target.id) in {row["id"] for row in body["blocked_companies"]}


def test_orphan_task_survives_cleanup_and_is_reported(admin_client, db):
    orphan = Task(title="Orphan task with no opportunity_id")
    db.add(orphan)
    db.flush()

    body = admin_client.post("/api/admin/sample-data-cleanup", json={"confirm": CLEANUP_CONFIRM_VALUE}).json()

    assert db.get(Task, orphan.id) is not None
    assert str(orphan.id) in {row["id"] for row in body["orphan_tasks"]}
