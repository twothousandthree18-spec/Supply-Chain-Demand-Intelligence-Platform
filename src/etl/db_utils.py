"""
Supply Chain & Demand Intelligence Platform
Phase 2 - Database connection helpers.

Connection parameters are read from environment variables (PGHOST, PGPORT,
PGDATABASE, PGUSER, PGPASSWORD) per the 12-factor convention. No secrets are
hardcoded. Local dev uses PostgreSQL `trust` auth, so PGPASSWORD is optional.
"""

import os

import psycopg2
import psycopg2.extras

_ENV_TO_ARG = {
    "PGHOST": "host",
    "PGPORT": "port",
    "PGDATABASE": "dbname",
    "PGUSER": "user",
}
_DEFAULTS = {
    "PGHOST": "127.0.0.1",
    "PGPORT": "5432",
    "PGDATABASE": "supply_chain_intelligence",
    "PGUSER": "postgres",
}


def conninfo() -> dict:
    """Build a psycopg2 connection keyword dict from the environment."""
    info = {}
    for key, arg in _ENV_TO_ARG.items():
        info[arg] = os.environ.get(key, _DEFAULTS[key])
    # PGPASSWORD is optional (trust auth in local dev)
    pw = os.environ.get("PGPASSWORD")
    if pw:
        info["password"] = pw
    return info


def connect(autocommit: bool = False):
    """Open a psycopg2 connection to the project warehouse."""
    conn = psycopg2.connect(**conninfo())
    conn.autocommit = autocommit
    return conn
