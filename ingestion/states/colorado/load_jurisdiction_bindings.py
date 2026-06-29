"""Colorado jurisdiction_binding ingestion adapter.

Load ``jurisdiction_binding`` rows AND ``regulation_reporting`` link rows for
Colorado V1.

**jurisdiction_binding** rows are built by walking the
``geometry-overlays.json`` fixture × regulation_record cross product, plus
no-hunt-zone bindings (10 federal restricted-area zones via the nearby spatial
query).

**regulation_reporting** link rows connect each CO bear regulation_record to the
single CO ``reporting_obligation`` (``co-bear-mandatory-check-5day-statewide``).
CO V1 has ~46 bear regulation_records, so ~46 link rows are written.
Formula: ``len(reporting_links) == len(co_bear_obligations) * len(bear_rrs)``
(CO V1: 1 × 46 ≈ 46 links).

Three-phase shape
-----------------
This adapter's build phase necessarily reads from the DB (regulation_record
rows + geometry source citations + zone WKTs + spatial nearby-rule query), so
the three-phase discipline is:

1. **Build** — load overlay fixture (pure), then open a DB connection to
   query regulation_records, pre-fetch geometry source citations, fetch zone
   WKTs, and run the spatial nearby-rule for the 10 orphan no-hunt-zone RAs.
   Construct all binding rows in memory.
2. **Guards** — OQ7 row-count band check fires BEFORE the UPSERT write loop
   (still inside the same ``with db.connect()`` block). Any band violation
   raises ``RuntimeError`` so no partial write occurs.
3. **Write** — UPSERT each ``JurisdictionBinding`` via
   ``db.upsert_jurisdiction_binding``; commit; rollback on any exception.

OQ7 row-count guard
-------------------
Band: ``(300, 1200)`` — PROVISIONAL pending the operator's first dry-run
empirical count (the S04.2 T16-narrowing analog). After the first live dry-run,
narrow to ±30% around the observed count and update the band constant + the
AC #1087-equivalent footnote in the E06 epic. The current wide band prevents
false fires before the empirical baseline is known.

Approximate expected counts
---------------------------
~398 self-row ``primary_unit`` bindings (one per reg_record whose GMU geometry
exists) + no-hunt-zone fan-out (10 zones × nearby-GMU count × species per GMU).

Statewide
---------
CO V1 wrote 0 ``CO-STATEWIDE-*`` regulation_records (S06.6 reality). The
statewide builder code path exists for forward-safety; the guard asserts zero
unexpected statewide pairs and returns [] for V1.

ID format
---------
Imported from ``load_regulation_records._JURISDICTION_BINDING_ID_FORMAT`` —
DO NOT redefine locally. DO NOT PARSE the id field. The format embeds
hyphenated ``jurisdiction_code`` and ``geometry_id`` values; naive
``id.split('-')`` is ambiguous and not round-trippable.

Source-citation pre-fetch
--------------------------
``SELECT id, source FROM geometry WHERE id = ANY(%s)`` runs inside the adapter
(no new ``db.py`` helper per S03.10 constraint #7 — ``db.py`` is reserved for
write/mutation helpers; read SELECTs for source attribution live here).

``drift_guard`` deliberately NOT imported
-----------------------------------------
ADR-020 carve-out: ``db.upsert_jurisdiction_binding`` excludes identity fields
from UPDATE entirely (S03.6.1 OQ-S6.1-4), so identity drift on UPSERT is
impossible at the SQL layer. This is strictly stronger than the module-load
derive-and-assert pattern. No drift guard is imported or needed.

Overlay builder: ``restricted_area`` fixture rows SKIPPED
----------------------------------------------------------
The CO ``geometry-overlays.json`` contains ``gmu→restricted_area`` rows
(``role_for_e03='restricted_area'``) for all 10 ``EXPECTED_CO_RA_ORPHAN_IDS``.
These fixture rows are NOT turned into bindings by the overlay builder — the
dedicated hardcoded ``_build_no_hunt_zone_bindings_co`` is the SOLE producer of
zone bindings (via the 5 km nearby spatial query, not fixture overlap rows). The
overlay builder's eligibility function returns False for ``restricted_area``
(seen-and-skipped, never raises).

Known Issue #6 — narrow role gate
----------------------------------
``_VALID_ROLE_FOR_E03_CO = frozenset({"primary_unit", "portion", "restricted_area"})``
stays narrow per S06.0/D2. ``no_hunt_zone`` and ``other_overlay`` are produced
ONLY by ``_build_no_hunt_zone_bindings_co``, never via the fixture gate.

AFA 9+1 hard constraint (Known Issue #12 RESOLVED)
----------------------------------------------------
The no-hunt-zone builder iterates all 10 ``EXPECTED_CO_RA_ORPHAN_IDS``. The AFA
id ``CO-restricted-united-states-air-force-academy-geom`` binds
``role='other_overlay'`` (it is a regulated-access HUNTING area per CPW Big Game
brochure p.78, NOT a closure). The other 9 NPS/NM rows bind
``role='no_hunt_zone'``. Locked by ``test_afa_bound_other_overlay_not_no_hunt_zone``.

Schema-prefix discipline
------------------------
All PostGIS calls in raw SQL MUST be ``extensions.``-qualified. PostGIS lives in
the ``extensions`` schema in this Supabase project. Bare-name resolution fails at
runtime — see ``.roughly/known-pitfalls.md``.

Confidence
----------
``jurisdiction_binding`` has no ``confidence`` column per ADR-017 §2.

Relevant ADRs
-------------
- ADR-005: Python for ingestion (state-adapter isolation; no lib edits)
- ADR-010: Decomposed entities (jurisdiction_binding as link entity)
- ADR-016: Overlay fixture provenance
- ADR-017 §2: No confidence column on jurisdiction_binding
- ADR-018: Statewide bindings (CO V1 produces 0)
- ADR-020: Derive-and-Assert carve-out (drift_guard NOT imported)
- ADR-021: ``no_hunt_zone`` role enum value
- ADR-022: Single-module per-state adapter
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Final, Literal, TypedDict, cast

import psycopg

from ingestion.lib import db
from ingestion.lib.schema import (
    JurisdictionBinding,
    RegulationRecord,
    RegulationReporting,
    SourceCitation,
)
from states.colorado.build_overlay_fixture import EXPECTED_CO_RA_ORPHAN_IDS

# Imported from load_regulation_records — DO NOT redefine locally.
# Same format as MT's S03.6.1; symmetric re-derivation UPSERTs as a no-op.
from states.colorado.load_regulation_records import _JURISDICTION_BINDING_ID_FORMAT

# ---------------------------------------------------------------------------
# Module-scope constants
# ---------------------------------------------------------------------------

# Cross-state spatial-filter constant — locked by test_co_binding_reference.py.
# Mirrors montana/load_jurisdiction_bindings.py ``_STATE: Final[str] = "US-MT"``.
# Every CO spatial query that scopes to GMUs binds this as a parameter so a
# multi-state database never cross-binds CO zones to MT geometry.
_STATE: Final[str] = "US-CO"

# Inherited from MT's S03.10 Option A; CO recalibration deferred (post-load).
# Locked by test_co_binding_reference.py.
_NO_HUNT_ZONE_NEARBY_DISTANCE_M: Final[int] = 5000

# Path to the geometry-overlays.json fixture built by build_overlay_fixture.py.
_OVERLAY_FIXTURE_PATH: Final[Path] = (
    Path(__file__).parent / "fixtures" / "geometry-overlays.json"
)

# OQ7 row-count guard band — PROVISIONAL. See module docstring.
# Narrow to ±30% around the first dry-run empirical count per S04.2 T16 analog.
_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (300, 1200)

_CO_STATEWIDE_GEOM_ID: Final[str] = "CO-STATEWIDE-geom"
_LICENSE_YEAR: Final[int] = 2026

# Bear species group for regulation_reporting link writes (CO V1 only has one
# reporting_obligation — the bear mandatory_check; all CO bear regulation_records
# are linked to it).
_CO_BEAR_SPECIES_GROUP: Final[str] = "bear"

# Module-level logger (used throughout the adapter).
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

# AFA geometry id — binds role='other_overlay' NOT 'no_hunt_zone' per Known
# Issue #12 (AFA is a regulated-access HUNTING area, not a closure).
_AFA_GEOM_ID: Final[str] = "CO-restricted-united-states-air-force-academy-geom"

# Narrow role gate per S06.0/D2 (Known Issue #6 hardcoded-path decision).
# no_hunt_zone / other_overlay are produced ONLY by _build_no_hunt_zone_bindings_co.
# CO has no cwd_management_zone or bear_management_unit.
_VALID_ROLE_FOR_E03_CO: Final[frozenset[str]] = frozenset(
    {"primary_unit", "portion", "restricted_area"}
)

# ---------------------------------------------------------------------------
# Reference SQL for CO binding loader (preserved verbatim from S05.6 scaffold)
# Locked by test_co_binding_reference.py — DO NOT MODIFY.
# ---------------------------------------------------------------------------

# Boundary-to-boundary "nearby GMU" query. Mirrors S03.10's
# ``_query_nearby_hds_for_zone`` (montana/load_jurisdiction_bindings.py) with
# CO substitutions (``kind = 'gmu'``).
# Parameter binding: (_STATE, zone_geom_wkt, _NO_HUNT_ZONE_NEARBY_DISTANCE_M).
# The distance is a bound %s (NOT a hardcoded literal) so a future recalibration
# of ``_NO_HUNT_ZONE_NEARBY_DISTANCE_M`` flows into the query without silent drift.
# All ``ST_*`` calls are ``extensions.``-prefixed; the state filter is %s-bound.
# ``ORDER BY gmu.id`` mirrors MT's ``ORDER BY hd.id`` for deterministic row order.
_QUERY_NEARBY_GMUS_FOR_ZONE_SQL: Final[str] = """
SELECT gmu.id, gmu.geom
FROM geometry gmu
WHERE gmu.state = %s
  AND gmu.kind = 'gmu'
  AND extensions.ST_DWithin(%s::geography, gmu.geom, %s)
ORDER BY gmu.id
"""


def query_nearby_gmus_for_zone(
    conn: psycopg.Connection[tuple[object, ...]],
    zone_geom_wkt: str,
) -> list[str]:
    """Return the ids of CO GMUs within 5 km of ``zone_geom_wkt``.

    Drop-in mirror of MT's ``_query_nearby_hds_for_zone``. The ``_STATE``
    constant is bound as the first parameter so the query is locked to CO;
    the distance threshold ``_NO_HUNT_ZONE_NEARBY_DISTANCE_M`` is bound as the
    third parameter so a future recalibration takes effect without editing the
    SQL string.
    """
    with conn.cursor() as cur:
        cur.execute(
            _QUERY_NEARBY_GMUS_FOR_ZONE_SQL,
            (_STATE, zone_geom_wkt, _NO_HUNT_ZONE_NEARBY_DISTANCE_M),
        )
        return [str(row[0]) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Overlay fixture loader
# ---------------------------------------------------------------------------


class _OverlayRow(TypedDict):
    """One row of the overlay fixture at fixtures/geometry-overlays.json.

    Per ADR-016, the fixture is the result of a local Shapely + STRtree build
    that runs the digitization-tolerant containment algorithm against the live
    geometry set. Each row describes a parent → child geometry relationship plus
    the role the child plays in the parent's regulatory scope.
    """

    parent_geometry_id: str
    child_geometry_id: str
    parent_kind: str
    child_kind: str
    relationship: str
    role_for_e03: str


_REQUIRED_OVERLAY_KEYS: Final[frozenset[str]] = frozenset(
    _OverlayRow.__annotations__.keys()
)


def _load_overlay_fixture(path: Path) -> list[_OverlayRow]:
    """Load the geometry-overlays.json fixture and validate row shape.

    Defensive pattern (per S03.9 review-triad findings): isinstance check BEFORE
    key access; try/except KeyError on missing keys raises RuntimeError with the
    row index + the present-keys diagnostic, so a fixture drift fails fast and
    points at the exact problematic row.

    Guard 1: top-level shape not list or dict-with-relationships key → raise.
    Guard 2: top-level after unwrap not a list → raise.
    Guard 3: row not a dict → raise.
    Guard 4: row missing required keys → raise.
    """
    with path.open() as f:
        data = json.load(f)
    if isinstance(data, list):
        raw_rows: object = data
    elif isinstance(data, dict) and "relationships" in data:
        raw_rows = data["relationships"]
    else:
        raise RuntimeError(
            f"overlay fixture at {path} has unexpected top-level shape: "
            f"neither a list nor a dict with 'relationships' key"
        )
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            f"overlay fixture at {path} 'relationships' value is not a list: "
            f"got {type(raw_rows).__name__}"
        )
    rows: list[_OverlayRow] = []
    for idx, element in enumerate(raw_rows):
        if not isinstance(element, dict):
            raise RuntimeError(
                f"overlay fixture row {idx} is not a dict: "
                f"got {type(element).__name__}"
            )
        missing = _REQUIRED_OVERLAY_KEYS - element.keys()
        if missing:
            raise RuntimeError(
                f"overlay fixture row {idx} missing required keys: "
                f"{sorted(missing)}; present keys: {sorted(element.keys())}"
            )
        rows.append(cast(_OverlayRow, element))
    return rows


# ---------------------------------------------------------------------------
# Per-species binding eligibility filter
# ---------------------------------------------------------------------------


def is_binding_eligible_co(
    species_group: str,
    parent_geometry_id: str,
    overlay_row: _OverlayRow,
) -> bool:
    """Decide whether an overlay row's child geometry should bind to a
    regulation_record of this species_group whose primary geometry is
    parent_geometry_id.

    Pure function (no I/O). Returns True iff the binding should be written.

    CO has no species-axis geometry partitioning (every GMU serves all species),
    so there is no Step-B species-prefix check (unlike MT). The eligibility
    decision is purely role-based.

    Statewide regulation_records do NOT pass through this function — they are
    handled by ``_build_statewide_bindings_co`` and bind directly to
    ``_CO_STATEWIDE_GEOM_ID`` with role='primary_unit'.

    Guard 5: unknown role_for_e03 → raise.
    """
    # Step A: self-row short-circuit — always eligible regardless of role.
    if overlay_row["child_geometry_id"] == parent_geometry_id:
        return True

    role = overlay_row["role_for_e03"]

    # Non-self primary_unit: defensive. Every primary_unit row IS the self-row
    # in the CO fixture, so this branch is structurally unreachable for a
    # well-formed fixture. Return False defensively.
    if role == "primary_unit":
        return False

    # CO has zero portion geometries in V1, but preserve the code path so
    # future portion-keyed geometries bind correctly (AC #1103).
    if role == "portion":
        return True

    # Restricted-area fixture rows are SKIPPED here — the 10 CO RAs are
    # documented orphans handled exclusively by ``_build_no_hunt_zone_bindings_co``
    # via the nearby spatial query (AC #1104). Binding them here would
    # double-bind. This branch returns False (seen-and-skipped, never raises).
    if role == "restricted_area":
        return False

    # Unknown role_for_e03 — fail loud independently of the _VALID_ROLE_FOR_E03_CO
    # gate. Public function; any future caller that bypasses the gate would
    # otherwise silently skip bindings for unknown roles.
    raise RuntimeError(
        f"is_binding_eligible_co: unhandled role_for_e03 "
        f"{role!r} for child_geometry_id "
        f"{overlay_row['child_geometry_id']!r}"
    )


# ---------------------------------------------------------------------------
# Parent geometry_id derivation
# ---------------------------------------------------------------------------


def _derive_parent_geometry_id_co(reg_record: RegulationRecord) -> str:
    """Map a CO regulation_record to its parent geometry_id.

    Patterns (locked by tests):

    +----------------+--------------------+
    | jurisdiction_code | parent geometry_id |
    +================+====================+
    | CO-GMU-1       | CO-GMU-1-geom      |
    | CO-GMU-20      | CO-GMU-20-geom     |
    +----------------+--------------------+

    CO-STATEWIDE-* → fail loud (no statewide bindings in V1; any statewide
    reg_record reaching this helper is a logic error — statewide records are
    split off before the overlay/no-hunt builders call this).

    Guard 6: CO-STATEWIDE-* pattern → raise.
    Guard 7: CO-GMU-{non-numeric} suffix → raise.
    Guard 8: unhandled pattern → raise.
    """
    jc = reg_record.jurisdiction_code
    if jc.startswith("CO-STATEWIDE-"):
        raise RuntimeError(
            f"_derive_parent_geometry_id_co: CO-STATEWIDE-* jurisdiction_code "
            f"{jc!r} reached the overlay builder — statewide reg_records must "
            f"be split off before calling this helper. CO V1 has no statewide "
            f"bindings; any statewide reg_record is a structural logic error."
        )
    if jc.startswith("CO-GMU-"):
        suffix = jc.removeprefix("CO-GMU-")
        try:
            int(suffix)
        except ValueError:
            raise RuntimeError(
                f"_derive_parent_geometry_id_co: jurisdiction_code {jc!r} has "
                f"non-numeric GMU suffix {suffix!r}; expected CO-GMU-{{int}}."
            )
        return f"{jc}-geom"
    raise RuntimeError(
        f"_derive_parent_geometry_id_co: unhandled jurisdiction_code pattern: "
        f"{jc!r}. Known patterns: CO-GMU-{{int}}. "
        f"CO-STATEWIDE-* is handled before this helper is called."
    )


# ---------------------------------------------------------------------------
# Source-citation pre-fetch
# ---------------------------------------------------------------------------


def _fetch_geometry_sources(
    conn: psycopg.Connection[tuple[object, ...]],
    geometry_ids: set[str],
) -> dict[str, SourceCitation]:
    """Pre-fetch source citations for every geometry id that will appear in a
    binding row.

    Per AC #1088 the geometry table is the authoritative source-of-record for
    binding attribution (the overlay fixture is derived). This adapter-local
    SELECT keeps the ``db.py`` surface limited to write/mutation helpers per
    S03.10 constraint #7.

    Guard 9: malformed source jsonb → raise naming the failing geometry id.
    Guard 10: missing geometry ids → raise naming up to the first 10 missing.
    """
    if not geometry_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, source FROM geometry WHERE id = ANY(%s)",
            (sorted(geometry_ids),),
        )
        rows = cur.fetchall()
    sources: dict[str, SourceCitation] = {}
    for row in rows:
        gid = str(row[0])
        try:
            sources[gid] = SourceCitation.model_validate(row[1])
        except Exception as exc:
            raise RuntimeError(
                f"geometry {gid!r} has malformed source jsonb: {exc}"
            ) from exc
    missing = geometry_ids - sources.keys()
    if missing:
        sample = sorted(missing)[:10]
        suffix = "..." if len(missing) > 10 else ""
        raise RuntimeError(
            f"overlay fixture references {len(missing)} geometry ids that are "
            f"absent from the geometry table: {sample}{suffix}"
        )
    return sources


# ---------------------------------------------------------------------------
# Zone WKT pre-fetch (CO-specific: scaffold query_nearby_gmus_for_zone takes WKT)
# ---------------------------------------------------------------------------


def _fetch_zone_wkts(
    conn: psycopg.Connection[tuple[object, ...]],
    zone_ids: set[str],
) -> dict[str, str]:
    """Pre-fetch WKT strings for each no-hunt zone geometry id.

    The scaffold ``query_nearby_gmus_for_zone`` takes a WKT string (not a
    zone_id JOIN), so we must fetch the WKT for each zone before calling it.
    Uses ``extensions.ST_AsText`` (Supabase schema-prefix discipline).
    ``ST_AsText`` works directly on the geography column.

    Guard 11: any requested zone_id absent from the geometry table → raise
    naming the missing ids.
    """
    if not zone_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, extensions.ST_AsText(geom) FROM geometry WHERE id = ANY(%s)",
            (sorted(zone_ids),),
        )
        rows = cur.fetchall()
    wkts: dict[str, str] = {}
    for row in rows:
        wkts[str(row[0])] = str(row[1])
    missing = zone_ids - wkts.keys()
    if missing:
        sample = sorted(missing)[:10]
        suffix = "..." if len(missing) > 10 else ""
        raise RuntimeError(
            f"_fetch_zone_wkts: {len(missing)} zone id(s) absent from the "
            f"geometry table: {sample}{suffix}"
        )
    return wkts


# ---------------------------------------------------------------------------
# Statewide-binding builder
# ---------------------------------------------------------------------------


def _build_statewide_bindings_co(
    statewide_reg_records: list[RegulationRecord],
    co_statewide_source: SourceCitation,
) -> list[JurisdictionBinding]:
    """Emit one primary_unit binding per statewide regulation_record →
    CO-STATEWIDE-geom.

    CO V1 wrote 0 CO-STATEWIDE-* regulation_records (S06.6 reality), so this
    builder always returns [] in V1. The code path exists for forward-safety so
    future statewide anchors (if any) bind correctly without structural changes.

    Per ADR-018: any role beyond 'primary_unit' for a statewide binding requires
    an ADR amendment.
    """
    bindings: list[JurisdictionBinding] = []
    for rr in statewide_reg_records:
        role: Literal["primary_unit"] = "primary_unit"
        bid = _JURISDICTION_BINDING_ID_FORMAT.format(
            state=rr.state,
            jurisdiction_code=rr.jurisdiction_code,
            species_group=rr.species_group,
            license_year=rr.license_year,
            role=role,
            geometry_id=_CO_STATEWIDE_GEOM_ID,
        )
        bindings.append(
            JurisdictionBinding(
                id=bid,
                regulation_record_state=rr.state,
                regulation_record_jurisdiction_code=rr.jurisdiction_code,
                regulation_record_species_group=rr.species_group,
                regulation_record_license_year=rr.license_year,
                geometry_id=_CO_STATEWIDE_GEOM_ID,
                role=role,
                verbatim_rule=None,
                source=co_statewide_source,
            )
        )
    return bindings


# ---------------------------------------------------------------------------
# Overlay binding builder
# ---------------------------------------------------------------------------


def _build_overlay_bindings_co(
    non_statewide_reg_records: list[RegulationRecord],
    overlay_rows: list[_OverlayRow],
    source_lookup: dict[str, SourceCitation],
) -> list[JurisdictionBinding]:
    """Walk every (non-statewide regulation_record × overlay_row) cross product,
    apply the CO eligibility filter from ``is_binding_eligible_co``, and emit
    one JurisdictionBinding per qualified pair.

    For CO V1, only ``primary_unit`` self-row bindings are emitted:
        - ``restricted_area`` fixture rows are SKIPPED (see module docstring).
        - ``portion`` rows: CO has zero, code path preserved.

    Per-row source attribution comes from source_lookup (pre-fetched from the
    geometry table per AC #1088).

    Guard 12: parent geometry has no fixture entries → raise.
    Guard 13: unknown role_for_e03 value → raise.
    Guard 14: missing source citation for child_geometry_id → raise.
    Guard 15: duplicate binding id within a single build run → raise.
    """
    # Index overlay rows by parent_geometry_id for O(N) lookup per reg_record.
    rows_by_parent: dict[str, list[_OverlayRow]] = {}
    for row in overlay_rows:
        rows_by_parent.setdefault(row["parent_geometry_id"], []).append(row)

    bindings: list[JurisdictionBinding] = []
    seen_ids: set[str] = set()

    for rr in non_statewide_reg_records:
        parent_gid = _derive_parent_geometry_id_co(rr)
        parent_rows = rows_by_parent.get(parent_gid)
        if parent_rows is None:
            # Every GMU-keyed reg_record's parent geometry must have at least a
            # self-row (primary_unit) in the overlay fixture. A missing entry
            # means a structural fixture / reg_record sync bug — silently
            # skipping would lose ALL bindings for this reg_record without
            # diagnostic. Fail loud.
            raise RuntimeError(
                f"_build_overlay_bindings_co: regulation_record "
                f"({rr.state}, {rr.jurisdiction_code}, {rr.species_group}, "
                f"{rr.license_year}) has parent_geometry_id {parent_gid!r} but "
                f"no overlay-fixture entries reference it as a parent. "
                f"Either geometry-overlays.json is stale, or a regulation_record "
                f"was inserted for a non-existent GMU geometry."
            )
        for row in parent_rows:
            role_e03 = row["role_for_e03"]
            # Unknown-role guard MUST fire before is_binding_eligible_co so a
            # malformed fixture row fails loud even if the filter would reject it.
            if role_e03 not in _VALID_ROLE_FOR_E03_CO:
                raise RuntimeError(
                    f"overlay row has unknown role_for_e03 {role_e03!r}; "
                    f"parent={row['parent_geometry_id']!r} "
                    f"child={row['child_geometry_id']!r}"
                )
            if not is_binding_eligible_co(rr.species_group, parent_gid, row):
                continue
            child_gid = row["child_geometry_id"]
            try:
                source = source_lookup[child_gid]
            except KeyError as exc:
                raise RuntimeError(
                    f"_build_overlay_bindings_co: child_geometry_id {child_gid!r} "
                    f"missing from source_lookup; caller must pre-fetch all child ids."
                ) from exc

            # DO NOT PARSE the resulting id — see module docstring.
            bid = _JURISDICTION_BINDING_ID_FORMAT.format(
                state=rr.state,
                jurisdiction_code=rr.jurisdiction_code,
                species_group=rr.species_group,
                license_year=rr.license_year,
                role=role_e03,
                geometry_id=child_gid,
            )
            if bid in seen_ids:
                raise RuntimeError(
                    f"_build_overlay_bindings_co: duplicate binding id {bid!r} — "
                    f"second occurrence on reg_record ({rr.state}, "
                    f"{rr.jurisdiction_code}, {rr.species_group}, "
                    f"{rr.license_year})"
                )
            seen_ids.add(bid)

            bindings.append(
                JurisdictionBinding(
                    id=bid,
                    regulation_record_state=rr.state,
                    regulation_record_jurisdiction_code=rr.jurisdiction_code,
                    regulation_record_species_group=rr.species_group,
                    regulation_record_license_year=rr.license_year,
                    geometry_id=child_gid,
                    role=cast(
                        Literal[
                            "primary_unit",
                            "portion",
                            "restricted_area",
                            "cwd_management_zone",
                            "bear_management_unit",
                            "block_management_area",
                            "other_overlay",
                            "no_hunt_zone",
                        ],
                        role_e03,
                    ),
                    verbatim_rule=None,
                    source=source,
                )
            )

    return bindings


# ---------------------------------------------------------------------------
# No-hunt-zone binding builder
# ---------------------------------------------------------------------------


def _build_no_hunt_zone_bindings_co(
    conn: psycopg.Connection[tuple[object, ...]],
    non_statewide_reg_records: list[RegulationRecord],
    source_lookup: dict[str, SourceCitation],
) -> list[JurisdictionBinding]:
    """For each of the 10 EXPECTED_CO_RA_ORPHAN_IDS, query the nearby GMUs via
    the geography-native ST_DWithin rule, then emit one binding per
    (reg_record using that GMU as parent_geometry, zone) pair.

    Role dispatch (AFA 9+1 hard constraint — Known Issue #12 RESOLVED, AC #1104):
    - AFA (``_AFA_GEOM_ID``): role='other_overlay' — regulated-access HUNTING
      area per CPW Big Game brochure p.78; NOT a closure.
    - Other 9 NPS/NM zones: role='no_hunt_zone' per ADR-021.

    Uses the scaffold ``query_nearby_gmus_for_zone(conn, zone_geom_wkt)`` — the
    ONLY invocation pattern. Zone WKTs are pre-fetched via ``_fetch_zone_wkts``
    before this builder is called.

    Guard 16: zone WKT missing from pre-fetched dict → raise.
    Guard 17: per-zone zero nearby GMU matches → raise.
    Guard 18: zone source citation missing from source_lookup → raise.
    Guard 19: duplicate binding id within a single build run → raise.
    Guard 20: per-zone zero bindings despite non-empty nearby GMUs → raise
              (every nearby GMU lacked CO reg_records — broken sync).
    """
    # Index reg_records by their parent geometry id for O(N) fan-out.
    rrs_by_parent: dict[str, list[RegulationRecord]] = {}
    for rr in non_statewide_reg_records:
        parent_gid = _derive_parent_geometry_id_co(rr)
        rrs_by_parent.setdefault(parent_gid, []).append(rr)

    # Pre-fetch zone WKTs (CO-specific: scaffold function takes WKT, not zone_id).
    zone_wkts = _fetch_zone_wkts(conn, set(EXPECTED_CO_RA_ORPHAN_IDS))

    bindings: list[JurisdictionBinding] = []
    seen_ids: set[str] = set()

    for zone_id in sorted(EXPECTED_CO_RA_ORPHAN_IDS):
        try:
            wkt = zone_wkts[zone_id]
        except KeyError as exc:
            raise RuntimeError(
                f"_build_no_hunt_zone_bindings_co: zone {zone_id!r} WKT "
                f"missing from pre-fetched wkts dict; caller must pre-fetch all "
                f"EXPECTED_CO_RA_ORPHAN_IDS before this builder is called."
            ) from exc

        nearby_gmu_ids = query_nearby_gmus_for_zone(conn, wkt)
        if not nearby_gmu_ids:
            raise RuntimeError(
                f"no-hunt zone {zone_id!r} produced zero nearby GMU matches at "
                f"{_NO_HUNT_ZONE_NEARBY_DISTANCE_M}m — escalate per spec (AC #1104). "
                f"Either the zone geometry is not within 5km of any CO GMU, or "
                f"the CO GMU geometries have not been written to the DB yet."
            )

        try:
            zone_source = source_lookup[zone_id]
        except KeyError as exc:
            raise RuntimeError(
                f"_build_no_hunt_zone_bindings_co: zone {zone_id!r} missing from "
                f"source_lookup; caller must pre-fetch all EXPECTED_CO_RA_ORPHAN_IDS."
            ) from exc

        # AFA 9+1 hard constraint (Known Issue #12 RESOLVED, AC #1104):
        # AFA is a regulated-access HUNTING area → other_overlay (not no_hunt_zone).
        # The other 9 NPS/NM zones are genuine closures → no_hunt_zone (ADR-021).
        role: Literal["no_hunt_zone", "other_overlay"] = (
            "other_overlay" if zone_id == _AFA_GEOM_ID else "no_hunt_zone"
        )

        # Track per-zone binding count to detect the case where GMUs were found
        # but none had regulation_records (Guard 20: per-zone zero-bindings guard).
        bindings_before = len(bindings)

        for gmu_id in nearby_gmu_ids:
            rrs_for_gmu = rrs_by_parent.get(gmu_id, [])
            if not rrs_for_gmu:
                _LOGGER.warning(
                    "zone %s: nearby GMU %s has no CO regulation_records "
                    "— no binding emitted",
                    zone_id,
                    gmu_id,
                )
            for rr in rrs_for_gmu:
                bid = _JURISDICTION_BINDING_ID_FORMAT.format(
                    state=rr.state,
                    jurisdiction_code=rr.jurisdiction_code,
                    species_group=rr.species_group,
                    license_year=rr.license_year,
                    role=role,
                    geometry_id=zone_id,
                )
                if bid in seen_ids:
                    raise RuntimeError(
                        f"_build_no_hunt_zone_bindings_co: duplicate binding id "
                        f"{bid!r} — second occurrence for zone {zone_id!r} + "
                        f"GMU {gmu_id!r}."
                    )
                seen_ids.add(bid)
                bindings.append(
                    JurisdictionBinding(
                        id=bid,
                        regulation_record_state=rr.state,
                        regulation_record_jurisdiction_code=rr.jurisdiction_code,
                        regulation_record_species_group=rr.species_group,
                        regulation_record_license_year=rr.license_year,
                        geometry_id=zone_id,
                        role=role,
                        verbatim_rule=None,
                        source=zone_source,
                    )
                )

        # Guard 20: per-zone zero-bindings guard.
        # Guard 17 (above) fires when nearby_gmu_ids itself is empty.
        # This guard fires when GMUs were found but EVERY nearby GMU lacked
        # CO regulation_records — the zone becomes invisible in query results.
        # This indicates a broken geometry/regulation_record sync: either
        # load_regulation_records.py (S06.6) has not been run yet, or the
        # nearby GMUs genuinely have no CO reg_records (investigate).
        if len(bindings) == bindings_before:
            raise RuntimeError(
                f"no-hunt zone {zone_id!r} produced zero bindings despite "
                f"{len(nearby_gmu_ids)} nearby GMU(s) {sorted(nearby_gmu_ids)}: "
                f"every nearby GMU lacked CO regulation_records. "
                f"Either run load_regulation_records.py (S06.6) first, or "
                f"investigate whether the geometry/regulation_record sync is broken."
            )

    return bindings


# ---------------------------------------------------------------------------
# Row-count guard + cross-tab summary
# ---------------------------------------------------------------------------


def _assert_binding_count_within_guard(written: int) -> None:
    """OQ7 row-count guard for S06.10.

    Band is ``_BINDING_COUNT_GUARD_BAND`` — PROVISIONAL ``(300, 1200)`` pending
    the operator's first dry-run empirical count. Narrow to ±30% around the
    observed count per S04.2 T16-narrowing analog.

    Guard 23: count outside band → raise.
    """
    lo, hi = _BINDING_COUNT_GUARD_BAND
    if not (lo <= written <= hi):
        raise RuntimeError(
            f"jurisdiction_binding write count {written} outside expected "
            f"band [{lo}, {hi}] (provisional — narrow after first dry-run). "
            f"See S06.10 epic + plan § 'OQ7 row-count guard'."
        )


def _log_summary(
    bindings: list[JurisdictionBinding], logger: logging.Logger
) -> None:
    """Cross-tab: per-(species_group, role) binding counts.

    Mirrors S03.6's and MT S03.10's ``_log_summary`` pattern. Logged at INFO at
    end of build phase, before the guard check, so the operator sees the
    per-bucket breakdown even if the guard subsequently aborts.
    """
    by_bucket: dict[tuple[str, str], int] = {}
    for b in bindings:
        key = (b.regulation_record_species_group, b.role)
        by_bucket[key] = by_bucket.get(key, 0) + 1
    logger.info("jurisdiction_binding cross-tab (species_group × role):")
    for (species, role), n in sorted(by_bucket.items()):
        logger.info("  %s × %s: %d", species, role, n)
    logger.info("  TOTAL: %d bindings", len(bindings))


# ---------------------------------------------------------------------------
# Regulation-record query helper
# ---------------------------------------------------------------------------


def _query_all_colorado_regulation_records(
    conn: psycopg.Connection[tuple[object, ...]],
) -> list[RegulationRecord]:
    """Fetch every Colorado regulation_record for _LICENSE_YEAR from the DB.

    Returns one RegulationRecord per row, ordered deterministically so the
    binding-build pass is reproducible across runs.

    ``license_year`` filter is load-bearing: binding loader is sized and
    count-guarded for V1 (_LICENSE_YEAR = 2026). Without this clause, a future
    year-over-year re-ingestion would silently fan out bindings across both
    years, blowing past the count guard and writing cross-year bindings.

    ``state`` filter is load-bearing per PRD 002 SC #4: in a multi-state DB,
    omitting the filter would fan out bindings across MT + CO, blowing the count
    guard and producing cross-state bindings.
    """
    sql = """
        SELECT
            state, jurisdiction_code, species_group, license_year,
            schema_version, confidence, additional_rules, ingested_at, source
        FROM regulation_record
        WHERE state = %s
          AND license_year = %s
        ORDER BY jurisdiction_code, species_group, license_year
    """
    with conn.cursor() as cur:
        cur.execute(sql, (_STATE, _LICENSE_YEAR))
        rows = cur.fetchall()
    records: list[RegulationRecord] = []
    for row in rows:
        try:
            source = SourceCitation.model_validate(row[8])
        except Exception as exc:
            raise RuntimeError(
                f"regulation_record ({str(row[1])!r}, {str(row[2])!r}) "
                f"has malformed source jsonb: {exc}"
            ) from exc
        records.append(
            RegulationRecord(
                state=str(row[0]),
                jurisdiction_code=str(row[1]),
                species_group=str(row[2]),
                license_year=int(row[3]),  # type: ignore[call-overload]
                schema_version=int(row[4]),  # type: ignore[call-overload]
                confidence=cast(
                    Literal["high", "medium", "low"], str(row[5])
                ),
                additional_rules=list(row[6]) if row[6] else [],  # type: ignore[call-overload]
                ingested_at=row[7],  # type: ignore[arg-type]
                source=source,
            )
        )
    return records


# ---------------------------------------------------------------------------
# Regulation-reporting helpers (FIX 1: contracted scope — S06.10 must write links)
# ---------------------------------------------------------------------------


def _query_co_reporting_obligations(
    conn: psycopg.Connection[tuple[object, ...]],
) -> list[tuple[str, list[str] | None]]:
    """Fetch all CO reporting_obligation rows (id, applies_to_regions) from the DB.

    Uses a LIKE 'co-%' filter to scope to Colorado obligations only.
    Returns rows in deterministic ORDER BY id order.

    Scoping note: ``reporting_obligation`` has no ``state`` column, so this relies
    on the ``co-`` id-prefix naming convention (MT obligations use ``mt-``). The
    convention is backstopped downstream: ``_build_regulation_reporting_links``
    Guard C fails loud on any returned id that is not ``co-bear-``-prefixed or
    whose ``applies_to_regions`` is non-null, so a future non-bear or regional CO
    obligation cannot be silently mis-routed to all bear reg_records.

    ``applies_to_regions`` is fetched so the builder can enforce the STATEWIDE-only
    contract: ``None`` means statewide (permitted for V1 fan-out); a non-null list
    means regional routing, which requires explicit species/region routing code
    before it can be linked.

    Fails loud (empty list check in caller) if no CO rows exist, which means
    ``load_reporting_obligations.py`` (S06.9) has not been run yet.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, applies_to_regions FROM reporting_obligation "
            "WHERE id LIKE 'co-%' ORDER BY id"
        )
        rows = cur.fetchall()
    result: list[tuple[str, list[str] | None]] = []
    for row in rows:
        ob_id = str(row[0])
        raw_regions = row[1]
        regions: list[str] | None = list(raw_regions) if raw_regions is not None else None
        result.append((ob_id, regions))
    return result


def _build_regulation_reporting_links(
    reg_records: list[RegulationRecord],
    obligations: list[tuple[str, list[str] | None]],
) -> list[RegulationReporting]:
    """Build regulation_reporting link rows for CO V1.

    CO V1 semantics: exactly 1 STATEWIDE bear mandatory_check obligation
    (``co-bear-mandatory-check-5day-statewide``, ``applies_to_regions=None``).
    It links to every CO bear regulation_record — i.e., every reg_record with
    ``species_group == 'bear'``.

    ``obligations`` is a list of ``(id, applies_to_regions)`` tuples as returned
    by ``_query_co_reporting_obligations``. ``applies_to_regions=None`` means
    statewide (the only V1-permitted fan-out path).

    Formula: ``len(result) == len(obligations) * len(bear_rrs)``.

    Guard A: obligations is empty → raises (S06.9 hasn't run).
    Guard B: no bear regulation_records → raises (S06.6 hasn't run / no bear data).
    Guard C: non-``co-bear-`` obligation id OR non-null ``applies_to_regions`` →
             raises (V1 only knows the STATEWIDE bear mandatory_check;
             a regional or non-bear obligation requires explicit species/region
             routing code before it can be linked — do not silently fan out).
    Guard D: duplicate composite PK → raises (structural code bug, not data drift).
    """
    if not obligations:
        raise RuntimeError(
            "no CO reporting_obligation rows found — run load_reporting_obligations.py "
            "(S06.9) against this DB first"
        )

    bear_rrs = [rr for rr in reg_records if rr.species_group == _CO_BEAR_SPECIES_GROUP]
    if not bear_rrs:
        raise RuntimeError(
            "no CO bear regulation_records found — run load_regulation_records.py "
            "(S06.6) against this DB first"
        )

    # Guard C: V1 only knows the STATEWIDE bear mandatory_check.
    # Any non-bear obligation or regional obligation (applies_to_regions non-null)
    # requires explicit species/region routing code — do NOT silently fan out.
    for ob_id, regions in obligations:
        if not ob_id.startswith("co-bear-") or regions is not None:
            raise RuntimeError(
                f"unexpected CO reporting_obligation {ob_id!r} "
                f"(applies_to_regions={regions!r}): V1 only links STATEWIDE "
                f"(applies_to_regions IS NULL) bear obligations. "
                f"A regional or non-bear obligation requires explicit "
                f"species/region routing code in _build_regulation_reporting_links "
                f"before it can be linked."
            )

    links: list[RegulationReporting] = []
    seen: set[tuple[str, str, str, int, str]] = set()

    for ob_id, _regions in obligations:
        for rr in bear_rrs:
            pk = (rr.state, rr.jurisdiction_code, rr.species_group, rr.license_year, ob_id)
            if pk in seen:
                raise RuntimeError(
                    f"duplicate regulation_reporting composite PK {pk!r} — "
                    f"check for duplicate bear reg_records in the DB"
                )
            seen.add(pk)
            links.append(
                RegulationReporting(
                    state=rr.state,
                    jurisdiction_code=rr.jurisdiction_code,
                    species_group=rr.species_group,
                    license_year=rr.license_year,
                    reporting_obligation_id=ob_id,
                )
            )

    return links


def _assert_regulation_reporting_structural_invariant(
    links: list[RegulationReporting],
    obligations: list[tuple[str, list[str] | None]],
    bear_rr_count: int,
) -> None:
    """Assert len(links) == len(obligations) * bear_rr_count.

    This is a correctness check on the loop arithmetic in
    ``_build_regulation_reporting_links``, independent of any OQ7 band guard.
    Raises RuntimeError naming the mismatch if violated.
    """
    expected = len(obligations) * bear_rr_count
    if len(links) != expected:
        raise RuntimeError(
            f"regulation_reporting structural invariant violated: "
            f"got {len(links)} link rows but expected "
            f"{len(obligations)} obligation(s) × {bear_rr_count} bear reg_records "
            f"= {expected}; this indicates a code bug in "
            f"_build_regulation_reporting_links, not artifact drift"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Three-phase orchestration: build → guard → write.

    Phase 1 (build): load overlay fixture (pure), open DB conn, query
    regulation_records, pre-fetch geometry source citations, run the spatial
    nearby-rule per orphan zone, construct all binding rows + regulation_reporting
    link rows in memory.

    Phase 2 (guard): OQ7 row-count band check + regulation_reporting structural
    invariant fire BEFORE any write. Any violation raises RuntimeError so no
    partial write occurs. Cross-tab summary logs before the guard check so
    operators see the breakdown even if the guard aborts.

    Phase 3 (write): UPSERT each JurisdictionBinding via
    ``db.upsert_jurisdiction_binding``, then write each RegulationReporting
    via ``db.write_regulation_reporting``; single commit; rollback on any
    exception.

    ``--dry-run``: short-circuit after the guard check; no writes.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(__name__)
    dry_run = "--dry-run" in (argv if argv is not None else sys.argv[1:])

    # PHASE 1: BUILD
    # Overlay fixture load is pure; all remaining build steps require DB reads.
    overlay_rows = _load_overlay_fixture(_OVERLAY_FIXTURE_PATH)

    with db.connect() as conn:
        reg_records = _query_all_colorado_regulation_records(conn)

        # Guard 20: 0 reg_records → prior loaders haven't run.
        if not reg_records:
            raise RuntimeError(
                "_query_all_colorado_regulation_records returned 0 rows — "
                "ensure prior loaders (S06.6 load_regulation_records.py + "
                "S06.7 load_seasons_and_licenses.py + S06.8 load_draw_specs.py + "
                "S06.9 load_reporting_obligations.py) have been run against this "
                "DB first."
            )

        statewide_rrs = [
            rr for rr in reg_records
            if rr.jurisdiction_code.startswith("CO-STATEWIDE-")
        ]

        # CO V1 expects ZERO statewide reg_records (S06.6 reality).
        # Guard 21: unexpected statewide pair → raise.
        # (No "missing" check needed since expected set is empty.)
        expected_statewide_pairs: set[tuple[str, str]] = set()
        present_statewide_pairs = {
            (rr.jurisdiction_code, rr.species_group) for rr in statewide_rrs
        }
        unexpected_statewide = present_statewide_pairs - expected_statewide_pairs
        if unexpected_statewide:
            raise RuntimeError(
                f"unexpected statewide (jurisdiction_code, species_group) "
                f"pairs: {sorted(unexpected_statewide)}. CO V1 ships 0 statewide "
                f"regulation_record anchors; any new anchor requires an ADR-018 "
                f"amendment + S06.10 spec update before this loader can bind it."
            )

        non_statewide_rrs = [
            rr for rr in reg_records
            if not rr.jurisdiction_code.startswith("CO-STATEWIDE-")
        ]

        # Collect every geometry id that any builder will reference so the
        # source pre-fetch is a single query instead of N queries.
        # FIX 2: Only include _CO_STATEWIDE_GEOM_ID when statewide_rrs is
        # non-empty. CO V1 always has 0 statewide reg_records (the unexpected-
        # statewide guard fires first), so the statewide geometry is never
        # required — adding it unconditionally would force a spurious dependency
        # on CO-STATEWIDE-geom existing in the DB even when no statewide
        # reg_records bind to it.
        candidate_geom_ids: set[str] = set()
        if statewide_rrs:
            candidate_geom_ids.add(_CO_STATEWIDE_GEOM_ID)
        for row in overlay_rows:
            candidate_geom_ids.add(row["child_geometry_id"])
        candidate_geom_ids.update(EXPECTED_CO_RA_ORPHAN_IDS)
        source_lookup = _fetch_geometry_sources(conn, candidate_geom_ids)

        # FIX 2 (cont.): only resolve statewide source when statewide_rrs is
        # non-empty; pass None when it isn't (builder returns [] anyway).
        statewide_source = (
            source_lookup.get(_CO_STATEWIDE_GEOM_ID)
            if statewide_rrs
            else None
        )
        if statewide_rrs and statewide_source is None:
            raise RuntimeError(
                f"{_CO_STATEWIDE_GEOM_ID!r} source not found in source_lookup "
                f"but statewide_rrs is non-empty; ensure the CO statewide geometry "
                f"has been written to the DB (run load_state_boundary.py first)."
            )
        statewide_bindings = _build_statewide_bindings_co(
            statewide_rrs,
            statewide_source,  # type: ignore[arg-type]  # None only when list is empty
        )
        overlay_bindings = _build_overlay_bindings_co(
            non_statewide_rrs, overlay_rows, source_lookup
        )
        no_hunt_bindings = _build_no_hunt_zone_bindings_co(
            conn, non_statewide_rrs, source_lookup
        )

        all_bindings = statewide_bindings + overlay_bindings + no_hunt_bindings

        # Build regulation_reporting links (FIX 1).
        # Query obligations (id, applies_to_regions) inside the same DB connection.
        obligations = _query_co_reporting_obligations(conn)
        reporting_links = _build_regulation_reporting_links(reg_records, obligations)

        # PHASE 2: GUARD
        # Cross-builder duplicate-id check: each builder maintains its own
        # ``seen_ids`` set, so a collision between the statewide / overlay /
        # no-hunt-zone builders would slip through. Catch it here before any
        # UPSERT.
        # Guard 22: cross-builder duplicate binding ids → raise.
        all_ids = [b.id for b in all_bindings]
        if len(all_ids) != len(set(all_ids)):
            seen: set[str] = set()
            dupes: set[str] = set()
            for bid in all_ids:
                if bid in seen:
                    dupes.add(bid)
                seen.add(bid)
            dupe_list = sorted(dupes)
            raise RuntimeError(
                f"cross-builder duplicate binding id(s) detected before write: "
                f"{dupe_list[:5]}{'...' if len(dupe_list) > 5 else ''}"
            )

        # regulation_reporting structural invariant guard (FIX 1).
        bear_rr_count = len(
            [rr for rr in reg_records if rr.species_group == _CO_BEAR_SPECIES_GROUP]
        )
        _assert_regulation_reporting_structural_invariant(
            reporting_links, obligations, bear_rr_count
        )

        # Log summary before the guard so operators see the breakdown even if
        # the row-count guard subsequently aborts.
        _log_summary(all_bindings, logger)
        _LOGGER.info(
            "regulation_reporting: %d link rows built "
            "(%d obligation(s) × %d bear reg_records)",
            len(reporting_links),
            len(obligations),
            bear_rr_count,
        )
        _assert_binding_count_within_guard(len(all_bindings))

        if dry_run:
            _LOGGER.info(
                "Dry-run complete: %d jurisdiction_binding rows + "
                "%d regulation_reporting link rows would be written",
                len(all_bindings),
                len(reporting_links),
            )
            return 0

        # PHASE 3: WRITE
        try:
            for binding in all_bindings:
                db.upsert_jurisdiction_binding(conn, binding)
            for link in reporting_links:
                db.write_regulation_reporting(conn, link)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    _LOGGER.info(
        "Wrote %d jurisdiction_binding rows + %d regulation_reporting link rows",
        len(all_bindings),
        len(reporting_links),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
