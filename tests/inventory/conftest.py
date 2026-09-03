"""Pytest conftest for the Phase 3E inventory test suite.

Adds the repository ``src`` package to ``sys.path`` so tests can import
``src.inventory`` (mirrors tests/forecast and tests/python conftests). These
are pure/DB-free unit tests - no database connection is required.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
