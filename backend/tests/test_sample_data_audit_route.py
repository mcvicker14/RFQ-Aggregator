"""GET /api/admin/sample-data-audit -- read-only, admin-only, must reuse
seed/audit_sample_data.py exactly (see app/api/routes/sample_data_audit.py)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.agency import Agency
from app.models.enums import UserRole
from app.models.opportunity import Opportunity
from app.models.task import Task
from app.models.user import User
from seed.audit_sample_data import audit_agencies, table_counts


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


def test_non_admin_cannot_read_the_audit(viewer_client):
    response = viewer_client.get("/api/admin/sample-data-audit")
    assert response.status_code == 403


def test_no_delete_capability_exists_at_this_path(admin_client):
    assert admin_client.delete("/api/admin/sample-data-audit").status_code == 405
    assert admin_client.post("/api/admin/sample-data-audit").status_code == 405


def test_admin_gets_exactly_the_expected_shape_and_nothing_else(admin_client):
    response = admin_client.get("/api/admin/sample-data-audit")
    assert response.status_code == 200
    body = response.json()

    assert set(body.keys()) == {
        "counts", "safe_agencies", "blocked_agencies", "safe_companies", "blocked_companies",
        "orphan_task_count", "orphan_tasks",
    }
    # No settings/config/secret values of any kind should ever appear in this response.
    dumped = response.text
    assert "DATABASE_URL" not in dumped
    assert "SECRET" not in dumped.upper()
    assert "password" not in dumped.lower()


def test_counts_match_table_counts_directly(admin_client, db):
    body = admin_client.get("/api/admin/sample-data-audit").json()
    assert body["counts"] == table_counts(db)
    assert body["counts"]["opportunities"]["sample"] > 0  # sanity: local dev DB has seeded sample data


def test_safe_and_blocked_agencies_match_audit_agencies_directly(admin_client, db):
    body = admin_client.get("/api/admin/sample-data-audit").json()
    safe, blocked = audit_agencies(db)

    assert {row["id"] for row in body["safe_agencies"]} == {str(a.id) for a, _, _ in safe}
    assert {row["id"] for row in body["blocked_agencies"]} == {str(a.id) for a, _, _ in blocked}


def test_agency_with_a_real_dependent_is_reported_blocked_with_a_reason(admin_client, db):
    sample_agency = db.execute(select(Agency).where(Agency.is_sample_data.is_(True))).scalars().first()
    assert sample_agency is not None  # sanity

    real_opp = Opportunity(title="Real live pursuit", agency_id=sample_agency.id, is_sample_data=False)
    db.add(real_opp)
    db.flush()

    body = admin_client.get("/api/admin/sample-data-audit").json()

    blocked_ids = {row["id"]: row for row in body["blocked_agencies"]}
    safe_ids = {row["id"] for row in body["safe_agencies"]}
    assert str(sample_agency.id) in blocked_ids
    assert str(sample_agency.id) not in safe_ids
    assert blocked_ids[str(sample_agency.id)]["hard_blockers"]["real_opportunities"] == 1


def test_orphan_task_count_is_reported(admin_client, db):
    orphan = Task(title="Orphan task with no opportunity_id")
    db.add(orphan)
    db.flush()

    body = admin_client.get("/api/admin/sample-data-audit").json()
    assert body["orphan_task_count"] >= 1


def test_orphan_task_details_are_reported_for_manual_review(admin_client, db):
    orphan = Task(title="Review USACE Mobile District procurement forecast for Q1")
    db.add(orphan)
    db.flush()

    body = admin_client.get("/api/admin/sample-data-audit").json()

    rows = {row["id"]: row for row in body["orphan_tasks"]}
    assert str(orphan.id) in rows
    row = rows[str(orphan.id)]
    assert row["title"] == "Review USACE Mobile District procurement forecast for Q1"
    assert row["status"] and row["priority"]  # non-sensitive fields present
    assert "notes" not in row and "owner_id" not in row and "created_by_id" not in row
    assert len(body["orphan_tasks"]) == body["orphan_task_count"]
