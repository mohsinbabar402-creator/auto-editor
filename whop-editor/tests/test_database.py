import pytest
import uuid
from db.connection import check_db_connection, transaction_scope, DatabaseConnectionError, DatabaseTransactionError
from db.repository import (
    DatabaseRepository,
    DuplicateEntityError,
    ForeignKeyMissingError,
    EntityNotFoundError
)


@pytest.fixture
def repo():
    return DatabaseRepository()


@pytest.mark.skipif(not check_db_connection(), reason="PostgreSQL is not reachable")
def test_project_crud(repo):
    p_id = f"test_proj_{uuid.uuid4().hex[:8]}"
    created = repo.create_project(
        project_id=p_id,
        name="Test Project",
        niche_description="Test Niche Description"
    )
    assert created["id"] == p_id

    fetched = repo.get_project(p_id)
    assert fetched is not None
    assert fetched["name"] == "Test Project"

    # Duplicate project creation raises DuplicateEntityError
    with pytest.raises(DuplicateEntityError):
        repo.create_project(p_id, "Duplicate", "Desc")


@pytest.mark.skipif(not check_db_connection(), reason="PostgreSQL is not reachable")
def test_foreign_key_enforcement(repo):
    # Registering video to non-existent project fails
    fake_proj = f"non_existent_{uuid.uuid4().hex[:8]}"
    v_id = f"vid_{uuid.uuid4().hex[:8]}"
    with pytest.raises(ForeignKeyMissingError):
        repo.register_video(video_id=v_id, project_id=fake_proj, file_path="/tmp/fake.mp4")


@pytest.mark.skipif(not check_db_connection(), reason="PostgreSQL is not reachable")
def test_transaction_rollback_on_failure():
    unique_audit = f"audit_fail_{uuid.uuid4().hex[:8]}"
    try:
        with transaction_scope() as cur:
            cur.execute(
                "INSERT INTO audit_log (id, action, target, detail, created_at) VALUES (%s, %s, %s, %s, NOW());",
                (unique_audit, "FAIL_TEST", "target", "detail")
            )
            # Deliberate failure inside transaction
            raise RuntimeError("Forced abort to test rollback")
    except DatabaseTransactionError:
        pass

    # Verify record was rolled back
    with transaction_scope() as cur:
        cur.execute("SELECT id FROM audit_log WHERE id = %s;", (unique_audit,))
        assert cur.fetchone() is None


def test_connection_error_handling(monkeypatch):
    """Verifies that database connection failures raise clean custom exceptions."""
    from db.connection import get_raw_connection
    from config import settings
    # Monkeypatch port to an unused port
    monkeypatch.setattr(settings, "DB_PORT", 59999)
    with pytest.raises(DatabaseConnectionError):
        get_raw_connection()
