"""Colorado jurisdiction-binding loader — E06 reference scaffold (S05.6).

This module is a SCAFFOLD. It is NOT executed during E05. Actual
``jurisdiction_binding`` writes belong to E06 (binding rows FK to BOTH
``regulation_record`` — E06 territory — AND ``geometry.id`` — E05 territory),
per PRD 002 §"Why sequential". E05 produces only geometry rows + the
``geometry-overlays.json`` fixture; E06's S03.10-equivalent story writes the
bindings once ``regulation_record`` rows exist.

What S05.6 codifies for E06 to inherit:
    * ``_STATE`` — the cross-state spatial-filter constant (mirrors MT's
      ``montana/load_jurisdiction_bindings.py`` ``_STATE: Final[str] = "US-MT"``).
      Locks the CO binding loader to ``state = 'US-CO'`` so a future multi-state
      database cannot silently bind CO zones to MT GMUs (handoff §8 #5;
      S03.10 ``_query_nearby_hds_for_zone`` precedent).
    * ``_QUERY_NEARBY_GMUS_FOR_ZONE_SQL`` — the boundary-to-boundary
      "nearby GMU" reference SQL E06 drops in for no-hunt-zone bindings.

Critical discipline reminders (from S03.10's pitfall corpus + audit):
    1. State filter is parameter-bound (``WHERE gmu.state = %s``), never
       string-interpolated — prevents SQL injection and keeps the regression
       check straightforward.
    2. ``gmu.kind = 'gmu'`` filter prevents matching the ``kind='state'`` row
       (``CO-STATEWIDE-geom``) or any other kind.
    3. Boundary-to-boundary ``extensions.ST_DWithin`` on geography (NOT
       centroid-to-centroid ``ST_Distance``) — per S03.10 pitfall C,
       centroid-to-centroid yields zero matches for large polygons.
    4. ``extensions.``-prefix on every ``ST_*`` call (Supabase puts PostGIS in
       the ``extensions`` schema — see known-pitfalls.md).
    5. 5000-meter threshold inherited from MT's
       ``_NO_HUNT_ZONE_NEARBY_DISTANCE_M = 5000`` (S03.10 Option A). CO may
       recalibrate empirically post-load; deferred to E06's spec / closure note.

ADR lineage: ADR-004 (Supabase + PostGIS), ADR-010 (decomposed entities).

Naming note: the four existing CO loaders use ``CO_STATE_CODE = "US-CO"``.
This scaffold uses ``_STATE`` to mirror the MT binding-loader convention that
E06 inherits. Unifying the two names is an E06 cleanup candidate, out of
S05.6's scaffold-only scope.
"""

from __future__ import annotations

from typing import Final

import psycopg

# ---------------------------------------------------------------------------
# Cross-state spatial-filter discipline
# ---------------------------------------------------------------------------

# Mirrors montana/load_jurisdiction_bindings.py:110 ``_STATE: Final[str] = "US-MT"``.
# Every CO spatial query that scopes to GMUs binds this as a parameter so a
# multi-state database never cross-binds CO zones to MT geometry (handoff §8 #5).
_STATE: Final[str] = "US-CO"

# Inherited from MT's ``_NO_HUNT_ZONE_NEARBY_DISTANCE_M = 5000`` (S03.10 Option A).
# CO recalibration deferred to E06 — see module docstring reminder 5.
_NO_HUNT_ZONE_NEARBY_DISTANCE_M: Final[int] = 5000

# ---------------------------------------------------------------------------
# Reference SQL for E06's CO binding loader (NOT executed in E05)
# ---------------------------------------------------------------------------

# Boundary-to-boundary "nearby GMU" query. Mirrors S03.10's
# ``_query_nearby_hds_for_zone`` (montana/load_jurisdiction_bindings.py) with
# CO substitutions (``kind = 'gmu'``).
# Parameter binding: (_STATE, zone_geom_wkt, _NO_HUNT_ZONE_NEARBY_DISTANCE_M).
# The distance is a bound %s (NOT a hardcoded literal) so E06's recalibration of
# ``_NO_HUNT_ZONE_NEARBY_DISTANCE_M`` flows into the query without silent drift —
# mirrors MT binding the constant as a parameter at load_jurisdiction_bindings.py:588.
# All ``ST_*`` calls are ``extensions.``-prefixed; the state filter is %s-bound.
_QUERY_NEARBY_GMUS_FOR_ZONE_SQL: Final[str] = """
SELECT gmu.id, gmu.geom
FROM geometry gmu
WHERE gmu.state = %s
  AND gmu.kind = 'gmu'
  AND extensions.ST_DWithin(%s::geography, gmu.geom, %s)
"""


def query_nearby_gmus_for_zone(
    conn: psycopg.Connection[tuple[object, ...]],
    zone_geom_wkt: str,
) -> list[str]:
    """Return the ids of CO GMUs within 5 km of ``zone_geom_wkt``.

    Reference implementation for E06's CO binding loader — provided as a
    drop-in mirror of MT's ``_query_nearby_hds_for_zone``. NOT invoked during
    E05 (no ``main()`` wires it up; no DB write occurs in E05).

    ``zone_geom_wkt`` is an EWKT/WKT string the caller has already validated;
    it is cast to ``geography`` in-SQL. The ``_STATE`` constant is bound as the
    first parameter so the query is locked to CO; the distance threshold
    ``_NO_HUNT_ZONE_NEARBY_DISTANCE_M`` is bound as the third parameter so a
    future recalibration takes effect without editing the SQL string.
    """
    with conn.cursor() as cur:
        cur.execute(
            _QUERY_NEARBY_GMUS_FOR_ZONE_SQL,
            (_STATE, zone_geom_wkt, _NO_HUNT_ZONE_NEARBY_DISTANCE_M),
        )
        return [str(row[0]) for row in cur.fetchall()]
