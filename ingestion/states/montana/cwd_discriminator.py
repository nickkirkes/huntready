"""Shared CWD discriminator predicate for MT FWP layer #2 (Big Game Restricted Areas).

S02.4 and S02.5 both read from layer #2 but apply mutually exclusive filters:
  - S02.4 ingests rows where is_cwd_feature() returns False (kind='restricted_area')
  - S02.5 ingests rows where is_cwd_feature() returns True  (kind='cwd_zone')

Both stories import this module so the predicate is defined exactly once,
preserving idempotency under any sequence of re-runs.
"""

from __future__ import annotations

from typing import Any


def is_cwd_feature(props: dict[str, Any]) -> bool:
    """Return True if feature attributes indicate a CWD zone row.

    Matches (case-insensitive substring):
      - COMMENTS contains 'CWD'
      - PORTIONNAME contains 'chronic wasting'
      - REG contains 'CWD'

    None-safe: missing or None field values are treated as empty strings.
    """

    def _coerce_upper(v: object) -> str:
        return str(v).upper() if v is not None else ""

    comments = _coerce_upper(props.get("COMMENTS"))
    portionname = _coerce_upper(props.get("PORTIONNAME"))
    reg = _coerce_upper(props.get("REG"))

    return (
        "CWD" in comments
        or "CHRONIC WASTING" in portionname
        or "CWD" in reg
    )
