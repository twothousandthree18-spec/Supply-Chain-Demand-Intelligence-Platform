"""
Supply Chain & Demand Intelligence Platform
Phase 1 - Shared config loader.

Loads config/project.json and exposes it to scripts. Kept dependency-free
(stdlib json only) so profiling/validation does not require extra packages.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_FILE = REPO_ROOT / "config" / "project.json"

_CACHE = None


def load_config() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            _CACHE = json.load(f)
    return _CACHE


def get_repo_root() -> Path:
    return REPO_ROOT


if __name__ == "__main__":
    # quick smoke test
    cfg = load_config()
    print("project:", cfg["project"])
    print("core files:", cfg["m5"]["core_files"])
    sys.exit(0)
