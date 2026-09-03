"""
Supply Chain & Demand Intelligence Platform
Phase 2 - pytest conftest for warehouse acceptance tests.

Provides a read-only session-scoped connection to the PostgreSQL warehouse.
Connection parameters come from environment variables (PGHOST/PGPORT/PGDATABASE/
PGUSER/PGPASSWORD) via src/etl/db_utils, with local trust-auth defaults.

The tests in this directory are READ-ONLY: they SELECT against the completed
warehouse and never run DDL, DML, or ETL. They assert the results of the
successful detatched ETL run (run_id=3).
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.etl.db_utils import connect  # noqa: E402


@pytest.fixture(scope="session")
def conn():
    """Session-scoped read-only connection to the warehouse."""
    connection = connect()
    yield connection
    connection.close()


def scalar(cur, sql: str, params=None):
    """Execute a query and return the single scalar value."""
    cur.execute(sql, params)
    return cur.fetchone()[0]
