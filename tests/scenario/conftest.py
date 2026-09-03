"""Shared fixtures for the Phase 4 scenario test suite.

The suite is deterministic and DB-free: it imports the scenario calculators and
the (already-completed) inventory engine. Helpers live in `_helpers.py` (see its
docstring for why they are not defined here).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(TESTS_DIR))