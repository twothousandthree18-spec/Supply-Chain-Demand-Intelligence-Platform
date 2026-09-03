"""
Supply Chain & Demand Intelligence Platform
Phase 3D - Data contract & chronological split validation (pure).

These functions enforce the forecasting data contract BEFORE any model runs:
  * observed-only daily demand (provenance must be 'observed')
  * chronological (sorted) input
  * no gaps / no NaN / no Inf
  * chronological train/validation split (past -> future); random splitting is
    intentionally unsupported (no shuffle here, and tests assert a passed-in
    shuffled split is rejected).
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from . import config


class DataContractError(ValueError):
    """Raised when the input series violates the forecasting data contract."""


def validate_series(
    date_ids,
    units,
    provenance,
    expected_provenance: str = "observed",
) -> None:
    """Validate a single daily demand series against the data contract.

    Checks, in order:
      1. same length for all three arrays
      2. provenance is the expected value (observed) on every point
      3. date_ids strictly increasing (chronological, no dup sort)
      4. units finite (no NaN/Inf)
      5. no gaps outside of minted absent-day padding (caller may supply padded
         zeros; the caller ensures the [start,end] window is covered)

    Raises DataContractError on any violation.
    """
    d = np.asarray(date_ids)
    u = np.asarray(units, dtype=np.float64)
    n = len(d)
    if len(u) != n:
        raise DataContractError("date_ids and units lengths differ")

    # provenance may be a single scalar string (constant provenance for the whole
    # series) or a per-point sequence (list / tuple / ndarray). A plain str is
    # treated as scalar, NOT iterated per character, so a scalar 'observed' works.
    is_sequence = isinstance(provenance, (list, tuple, np.ndarray))
    if is_sequence:
        if len(provenance) != n:
            raise DataContractError("provenance length differs from date_ids")
        bad_prov = [i for i in range(n) if provenance[i] != expected_provenance]
        if bad_prov:
            raise DataContractError(
                f"{len(bad_prov)} point(s) not provenance={expected_provenance}"
            )
    elif provenance != expected_provenance:
        raise DataContractError(f"provenance must be {expected_provenance}, got {provenance}")

    if np.any(np.diff(d) <= 0):
        raise DataContractError("series is not strictly chronological (unsorted or dup dates)")

    if not np.all(np.isfinite(u)):
        raise DataContractError("series contains NaN or Inf in units")

    # every integer day in [first, last] must be present (no internal gaps)
    expected_days = int(d[-1]) - int(d[0]) + 1
    if n != expected_days:
        raise DataContractError(
            f"series has {n} rows but window [{d[0]},{d[-1]}] needs {expected_days} "
            "(internal gaps present)"
        )


def validate_matrix(series_list: List[dict]) -> None:
    """Validate a batch of series (dicts with date_ids/units/provenance)."""
    if not series_list:
        return
    for s in series_list:
        validate_series(s["date_ids"], s["units"], s.get("provenance", "observed"))


def chronological_split(
    date_ids,
    units,
    train_end: int = config.TRAIN_END,
    validation_end: int = config.VALIDATION_END,
):
    """Return (train_x, train_y, valid_x, valid_y) split at train_end.

    train = values with date_id <= train_end
    valid = values with train_end < date_id <= validation_end
    Raises if the split is not a partition of a contiguous chronological window
    (i.e., never random).
    """
    d = np.asarray(date_ids)
    u = np.asarray(units, dtype=np.float64)
    if not np.issubdtype(d.dtype, np.integer):
        raise DataContractError("date_ids must be integers")
    if np.any(np.diff(d) <= 0):
        raise DataContractError("series not chronological; cannot split")

    train_mask = d <= train_end
    valid_mask = (d > train_end) & (d <= validation_end)

    if not np.any(train_mask):
        raise DataContractError("no training points; split would be empty on the train side")
    if not np.any(valid_mask):
        raise DataContractError("no validation points; holdout is empty")

    # must be contiguous (no holes between train tail and valid head)
    if int(d[train_mask][-1]) + 1 != int(d[valid_mask][0]):
        raise DataContractError("gap between training and validation windows")

    return d[train_mask], u[train_mask], d[valid_mask], u[valid_mask]
