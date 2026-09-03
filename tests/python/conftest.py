"""Pytest conftest for Phase 3 Python tests.

Adds the repository ``src`` package to ``sys.path`` so tests can import
``src.analytics`` etc. (mirrors tests/sql/conftest.py).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
