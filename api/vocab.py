"""Vocabulary sourcing for /vocab (INV-007 — no duplicated choice sets).

Sourced directly from the canonical `VALID_COMPOUNDS` / `VALID_DOSE_UNITS`
sets in `capture.session_init`; `api/` never duplicates the choice sets.
"""

from capture.session_init.constants import VALID_COMPOUNDS, VALID_DOSE_UNITS


def get_vocab() -> dict:
    """Return {compounds, dose_units} sourced from session_init."""
    return {
        "compounds": list(VALID_COMPOUNDS),
        "dose_units": list(VALID_DOSE_UNITS),
    }
