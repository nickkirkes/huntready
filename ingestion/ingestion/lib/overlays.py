"""Canonical type definitions for the S02.6 geometry-overlay fixture.

Spec: docs/planning/epics/E02-geometry-ingestion.md lines 458–570.
Consumed by: E03 jurisdiction_binding ingestion.

The overlay fixture captures spatial topology between Montana geometry rows
computed in S02.6 so that E03 can create `jurisdiction_binding` rows once
`regulation_record` rows exist (E03 territory).

Duplication note
----------------
``GeometryRoleForE03`` duplicates the seven Literal values from
``JurisdictionBinding.role`` in ``ingestion/ingestion/lib/schema.py:424-432``.
This is intentional: the overlay module is kept self-contained so E03 can
import it without pulling in the full Pydantic model graph. The values MUST be
kept manually in sync with ``JurisdictionBinding.role`` whenever that Literal
is changed. The module docstring is the designated sync reminder.
"""

from __future__ import annotations

from typing import Literal, TypedDict

# ---------------------------------------------------------------------------
# Literal type aliases
# ---------------------------------------------------------------------------

GeometryRoleForE03 = Literal[
    "primary_unit",
    "portion",
    "restricted_area",
    "cwd_management_zone",
    "bear_management_unit",
    "block_management_area",
    "other_overlay",
]
"""Seven roles that map directly to ``JurisdictionBinding.role`` in the DDL.

These are the roles E03 will assign when creating ``jurisdiction_binding`` rows
from overlay-fixture data. Spec: E02-geometry-ingestion.md § "Overlay roles".

SYNC REQUIRED: values must match ``JurisdictionBinding.role`` in
``ingestion/ingestion/lib/schema.py:424-432`` exactly. Update both locations
whenever the DDL role enum changes.
"""

OverlayRelationship = Literal["self", "covers", "intersects"]
"""Spatial relationship between a parent geometry and a child geometry.

- ``"self"`` — parent and child are the same row (HD → HD self-reference,
  yields ``role_for_e03='primary_unit'``).
- ``"covers"`` — parent fully covers child (``ST_Covers`` is true).
- ``"intersects"`` — parent and child intersect but parent does not fully cover
  child (``ST_Intersects`` true, ``ST_Covers`` false).

Spec: E02-geometry-ingestion.md § "Relationship discriminator".
"""

OverlayParentKind = Literal["hunting_district"]
"""Kind values that may appear as the parent in an overlay relationship.

V1 scope: only hunting districts act as parents. Extend this Literal (and
update ``ROLE_FOR_E03_BY_CHILD_KIND`` if needed) when additional parent kinds
are introduced. Spec: E02-geometry-ingestion.md § "Parent/child kinds".
"""

OverlayChildKind = Literal["hunting_district", "portion", "cwd_zone", "restricted_area"]
"""Kind values that may appear as the child in an overlay relationship.

V1 scope: four child kinds. Matches the ``geometry.kind`` column values used
by the Montana ingestion adapters. Spec: E02-geometry-ingestion.md § "Parent/child kinds".
"""

# ---------------------------------------------------------------------------
# TypedDict row definition
# ---------------------------------------------------------------------------


class OverlayFixtureRow(TypedDict):
    """One row in the S02.6 geometry-overlay fixture JSON.

    Each row records a parent→child spatial relationship discovered by the
    ``build_overlay_fixture.py`` script and persisted to
    ``ingestion/states/montana/fixtures/geometry-overlays.json``.

    E03 reads these rows to create ``jurisdiction_binding`` records once
    ``regulation_record`` rows exist.

    Fields
    ------
    parent_geometry_id:
        ``geometry.id`` of the enclosing geometry (always a hunting district
        in V1 per ``OverlayParentKind``).
    child_geometry_id:
        ``geometry.id`` of the contained or intersecting geometry.
    parent_kind:
        Kind of the parent geometry row. See ``OverlayParentKind``.
    child_kind:
        Kind of the child geometry row. See ``OverlayChildKind``.
    relationship:
        How parent and child relate spatially. See ``OverlayRelationship``.
    role_for_e03:
        The ``JurisdictionBinding.role`` value E03 should assign to this pair.
        Derived from ``child_kind`` via ``ROLE_FOR_E03_BY_CHILD_KIND``.

    Spec: E02-geometry-ingestion.md lines 458–570.
    """

    parent_geometry_id: str
    child_geometry_id: str
    parent_kind: OverlayParentKind
    child_kind: OverlayChildKind
    relationship: OverlayRelationship
    role_for_e03: GeometryRoleForE03


# ---------------------------------------------------------------------------
# Lookup table
# ---------------------------------------------------------------------------

ROLE_FOR_E03_BY_CHILD_KIND: dict[OverlayChildKind, GeometryRoleForE03] = {
    "hunting_district": "primary_unit",
    "portion": "portion",
    "cwd_zone": "cwd_management_zone",
    "restricted_area": "restricted_area",
}
"""Maps each ``OverlayChildKind`` to the ``GeometryRoleForE03`` E03 should use.

Used by ``build_overlay_fixture.py`` when constructing ``OverlayFixtureRow``
instances and by E03 when reading the fixture. Centralises the child-kind →
role mapping so it is not duplicated across multiple query functions.

Spec: E02-geometry-ingestion.md § "Role assignment by child kind".
"""


# ---------------------------------------------------------------------------
# Dropped-pair audit row
# ---------------------------------------------------------------------------


class DroppedOverlayPair(TypedDict):
    """One audit-log entry for an HD↔child pair dropped by the area-ratio threshold.

    The S02.6 builder filters HD↔child candidate pairs whose child-area
    overlap ratio falls below the lower threshold (`< COVER_DROP_THRESHOLD`,
    typically 0.01). Each dropped pair is recorded here so a future reviewer
    can verify that nothing semantically real was discarded.

    Schema and rationale: see ADR-016 (digitization-tolerant containment).

    Fields:
        parent_geometry_id:
            The hunting-district geometry id that was the parent in the
            dropped candidate pair.
        child_geometry_id:
            The child geometry id (portion / cwd_zone / restricted_area).
        parent_kind:
            Always ``"hunting_district"`` in V1; included for symmetry with
            ``OverlayFixtureRow`` and to future-proof against non-HD parents.
        child_kind:
            The child geometry's ``kind``. Useful for grouping the audit log
            by relationship class.
        overlap_pct:
            The ratio ``parent.intersection(child).area / child.area``,
            rounded to 6 decimal places for byte-deterministic output.
            Range: ``[0.0, 1.0)`` for dropped pairs (covers and near-covers
            land in the kept fixture, not here).
    """

    parent_geometry_id: str
    child_geometry_id: str
    parent_kind: OverlayParentKind
    child_kind: OverlayChildKind
    overlap_pct: float
