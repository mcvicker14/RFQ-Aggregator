"""Shared pytest fixtures. `db` gives each test a real session against the local
Postgres configured in DATABASE_URL, wrapped in an outer transaction that's always
rolled back at the end of the test — so tests exercise real SQL (constraints,
cascades, uniqueness) without leaving rows behind or needing a separate test database.
`join_transaction_mode="create_savepoint"` means service-layer code that calls
db.commit() only releases a SAVEPOINT here; the outer transaction.rollback() below is
what actually discards everything.
"""
import pytest

from app.db.session import SessionLocal, engine


@pytest.fixture()
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
