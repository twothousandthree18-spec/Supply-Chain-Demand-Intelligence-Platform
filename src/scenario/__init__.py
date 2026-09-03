"""
Supply Chain & Demand Intelligence Platform
Phase 4 - Scenario Engine & Decision Intelligence.

Steps 1-3 of the phase (architecture/contracts, schema, pure calculations)
live in this package. The scenario engine CONSUMES completed-phase outputs
(Phase 3C demand moments, Phase 3D final forecasts, Phase 3E assumption set)
and reuses the existing inventory policy/engine (src.inventory) - it never
re-implements forecasting or inventory logic, and it never scans the 59M-row
observed fact.

Pure, deterministic, DB-free design: identical inputs always produce identical
scenario outputs, so every run is reproducible from the same parameters.
"""

from . import config  # noqa: F401
from . import contract  # noqa: F401
from . import scenarios  # noqa: F401
from . import validation  # noqa: F401

__all__ = ["config", "contract", "scenarios", "validation"]