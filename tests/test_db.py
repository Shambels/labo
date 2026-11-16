"""Integration test: needs the PostgreSQL container (docker compose up -d). Skipped when it isn't reachable."""
import psycopg
import pytest

from rag_calorvia import db


@pytest.fixture
def conn():
    try:
        connection = db.connect()
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL is not running")
    with connection:
        db.create_tables(connection)
        yield connection


def test_experiment_is_stamped_with_git_state(conn):
    experiment_id = db.start_experiment(conn, "test_setup", {"name": "test_setup"})
    try:
        db.finish_experiment(conn, experiment_id, "done", 0.1)
        row = conn.execute(
            "SELECT status, git_commit, git_dirty FROM experiments WHERE id = %s", (experiment_id,)
        ).fetchone()
        status, commit, dirty = row
        assert status == "done"
        assert len(commit) == 40
        assert isinstance(dirty, bool)
    finally:
        conn.execute("DELETE FROM experiments WHERE id = %s", (experiment_id,))
        conn.commit()
