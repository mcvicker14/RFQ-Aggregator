import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import UserRole
from app.models.user import User


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


def test_any_user_can_read_the_setting(viewer_client):
    response = viewer_client.get("/api/settings/hide-sample-data")
    assert response.status_code == 200
    assert response.json() == {"hide_sample_data_by_default": False}


def test_viewer_cannot_change_the_setting(viewer_client):
    response = viewer_client.patch("/api/settings/hide-sample-data", json={"hide_sample_data_by_default": True})
    assert response.status_code == 403


def test_admin_can_change_the_setting_and_it_persists(admin_client):
    patch_response = admin_client.patch("/api/settings/hide-sample-data", json={"hide_sample_data_by_default": True})
    assert patch_response.status_code == 200

    get_response = admin_client.get("/api/settings/hide-sample-data")
    assert get_response.json() == {"hide_sample_data_by_default": True}


def test_opportunities_list_excludes_sample_data_when_requested(admin_client):
    all_response = admin_client.get("/api/opportunities")
    filtered_response = admin_client.get("/api/opportunities", params={"include_sample_data": False})

    assert all_response.status_code == filtered_response.status_code == 200
    assert all(not o["is_sample_data"] for o in filtered_response.json())
    assert len(filtered_response.json()) < len(all_response.json())
