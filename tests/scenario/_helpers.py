"""Deterministic series-fixture helpers for the Phase 4 scenario tests.

Kept OUT of conftest.py because multiple conftest.py files can collide under
the module name 'conftest' when several test directories run together. This
module has a unique name, so imports are always unambiguous.
"""

from src.scenario import config
from src.scenario.contract import SeriesInput, SizingMoments


def make_series(pid=1, sid=1, mean=10.0, std=4.0, total=10000.0,
                cv=None, forecast=None):
    """A deterministic series fixture: moments + a 28-day forecast vector."""
    if cv is None:
        cv = (std / mean) if mean > 0 else 0.0
    if forecast is None:
        forecast = [mean] * config.HORIZON_DAYS
    return SeriesInput(
        int(pid), int(sid),
        SizingMoments(mean, std, total, cv),
        [float(v) for v in forecast],
    )