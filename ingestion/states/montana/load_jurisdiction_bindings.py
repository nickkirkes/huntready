"""Montana jurisdiction_binding ingestion adapter.

Load ``jurisdiction_binding`` rows for Montana V1 by walking the
``geometry-overlays.json`` fixture × regulation_record cross product with
species-axis filtering, plus statewide bindings and no-hunt-zone Option A
bindings.

Three-phase shape
-----------------
This adapter's build phase necessarily reads from the DB (regulation_record
rows + geometry source citations + spatial nearby-rule query), so the three-
phase discipline is:

1. **Build** — load overlay fixture (pure), then open a DB connection to
   query regulation_records, pre-fetch geometry source citations, and run the
   spatial nearby-rule for the 3 orphan no-hunt-zone RAs.  Construct all
   binding rows in memory.
2. **Guards** — OQ7 row-count band check fires BEFORE the UPSERT write loop
   (still inside the same ``with db.connect()`` block).  Any band violation
   raises ``RuntimeError`` so no partial write occurs.
3. **Write** — UPSERT each ``JurisdictionBinding`` via
   ``db.upsert_jurisdiction_binding``; commit; rollback on any exception.

OQ7 row-count guard
-------------------
Band: ``[400, 1100]`` — intentionally wide pending T16's empirical count
(narrow to ±30% around the observed value after first live run).
See plan § "Spec deviations" #2 for derivation rationale.

ID format
---------
Imported from ``load_regulation_records._JURISDICTION_BINDING_ID_FORMAT`` —
DO NOT redefine locally.  Same format S03.6.1 used for the bear binding; this
adapter's symmetric re-derivation UPSERTs that row as a no-op.

DO NOT PARSE the id field.  The format embeds hyphenated ``jurisdiction_code``
and ``geometry_id`` values; naive ``id.split('-')`` is ambiguous and not
round-trippable.  Per spec line 1045 + plan § "Spec deviations" #1.

Source-citation pre-fetch
--------------------------
``SELECT id, source FROM geometry WHERE id = ANY(%s)`` runs inside the adapter
(no new ``db.py`` helper per S03.10 constraint #7 — ``db.py`` is reserved for
write/mutation helpers; read SELECTs for source attribution live here).

Per-species filter
------------------
``is_binding_eligible(species_group, parent_geometry_id, overlay_row)``
implements the filter table at
``docs/planning/epics/E03-regulation-text-ingestion.md`` lines 1024-1035.
The self-row short-circuit MUST fire first (Step A) — mule_deer and whitetail
reg_records have a ``MT-HD-deer-elk-lion-N`` jurisdiction_code whose geometry
id does NOT match the species prefix expected in Step B.

No-hunt-zone Option A
----------------------
The 3 orphan restricted-area IDs in ``EXPECTED_RA_ORPHAN_IDS`` (Glacier NP,
Sun River, Yellowstone NP) have no HD parent in the overlay fixture.  They
bind to nearby HDs via ``extensions.ST_DWithin(zone.geom, hd.geom, 5000)``
on the native geography type (boundary-to-boundary distance in meters).
Per-zone fail-loud on zero matches (AC #1086).

Schema-prefix discipline
------------------------
All PostGIS calls in raw SQL MUST be ``extensions.``-qualified.  PostGIS lives
in the ``extensions`` schema in this Supabase project.  Bare-name resolution
fails at runtime — see ``.roughly/known-pitfalls.md``.

Confidence
----------
``jurisdiction_binding`` has no ``confidence`` column per ADR-017 §2.

Relevant ADRs
-------------
- ADR-010: Decomposed entities (jurisdiction_binding as link entity)
- ADR-014: ``gis_layer`` document_type
- ADR-016: Overlay fixture provenance
- ADR-017: Spatial-confidence carve-out (no confidence column)
- ADR-018: Statewide bindings + ``MT-STATEWIDE-geom``
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Final, Literal, TypedDict, cast

import psycopg  # noqa: F401
from psycopg.types.json import Json  # noqa: F401

from ingestion.lib import db
from ingestion.lib.schema import JurisdictionBinding, RegulationRecord, SourceCitation
from states.montana.build_overlay_fixture import EXPECTED_RA_ORPHAN_IDS
# Shared with S03.6.1's `_build_statewide_bear_binding` — DO NOT redefine
# locally; the bear binding's id stability depends on this exact format string.
from states.montana.load_regulation_records import _JURISDICTION_BINDING_ID_FORMAT

# ---------------------------------------------------------------------------
# Module-scope constants
# ---------------------------------------------------------------------------

_OVERLAY_FIXTURE_PATH: Final[Path] = (
    Path(__file__).parent / "fixtures" / "geometry-overlays.json"
)
_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (400, 1100)
# Intentionally wide pending T16's empirical count — narrow to ±30% after
# first live run.  See plan § "Spec deviations" #2 for derivation rationale.
_MT_STATEWIDE_GEOM_ID: Final[str] = "MT-STATEWIDE-geom"
_STATE: Final[str] = "US-MT"  # locked by S03.6.1's test_id_encoding_is_deterministic
_LICENSE_YEAR: Final[int] = 2026
_NO_HUNT_ZONE_NEARBY_DISTANCE_M: Final[int] = 5000


# ---------------------------------------------------------------------------
# Overlay fixture loader (T2)
# ---------------------------------------------------------------------------


class _OverlayRow(TypedDict):
    """One row of the overlay fixture at ingestion/states/montana/fixtures/geometry-overlays.json.

    Per ADR-016, the fixture is the result of a local Shapely + STRtree build that
    runs the digitization-tolerant containment algorithm against the live geometry
    set.  Each row describes a parent → child geometry relationship plus the role
    the child plays in the parent's regulatory scope.
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
            f"overlay fixture at {path} has unexpected top-level shape: "
            f"neither a list nor a dict with 'relationships' key"
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
# Per-species binding eligibility filter (T3)
# ---------------------------------------------------------------------------


def is_binding_eligible(
    species_group: str,
    parent_geometry_id: str,
    overlay_row: _OverlayRow,
) -> bool:
    """Decide whether an overlay row's child_geometry should bind to a regulation_record
    of this species_group whose primary geometry is parent_geometry_id.

    Implements the per-species filter table at
    docs/planning/epics/E03-regulation-text-ingestion.md lines 1024-1035.

    Pure function (no I/O).  Returns True iff the binding should be written.

    Statewide regulation_records (MT-STATEWIDE-antelope, MT-STATEWIDE-bear) do NOT
    pass through this function — they're handled by ``_build_statewide_bindings``
    (T6) and bind directly to MT-STATEWIDE-geom with role='primary_unit'.
    """
    # Step A: self-row short-circuit — always primary_unit eligible regardless of
    # species prefix.  Without this, mule_deer/whitetail reg_records (whose parent
    # geometry is MT-HD-deer-elk-lion-N-geom) would reject their own self-row
    # because the child_geometry_id does NOT start with MT-HD-mule-deer- /
    # MT-HD-whitetail-.  (Stage 4 review finding C3.)
    if overlay_row["child_geometry_id"] == parent_geometry_id:
        return True

    # Step B: parent geometry must match the species-expected prefix.  Defensive
    # structural check — the caller should have filtered to the right parent
    # already, but this catches a logic bug fast.
    if species_group in {"elk", "mule_deer", "whitetail"}:
        if not parent_geometry_id.startswith("MT-HD-deer-elk-lion-"):
            return False
    elif species_group == "pronghorn":
        if not parent_geometry_id.startswith("MT-HD-antelope-"):
            return False
    elif species_group == "bear":
        if not parent_geometry_id.startswith("MT-HD-bear-"):
            return False
    else:
        raise RuntimeError(
            f"is_binding_eligible: unhandled species_group {species_group!r}"
        )

    # Step C: filter child by per-species accept set on child_geometry_id prefix
    # + child_kind disambiguation
    child_gid = overlay_row["child_geometry_id"]
    role_for_e03 = overlay_row["role_for_e03"]

    if role_for_e03 == "portion":
        if species_group == "elk":
            return child_gid.startswith("MT-HD-elk-")
        if species_group == "mule_deer":
            return child_gid.startswith("MT-HD-mule-deer-")
        if species_group == "whitetail":
            return child_gid.startswith("MT-HD-whitetail-")
        if species_group == "pronghorn":
            # antelope HDs + portions share `MT-HD-antelope-` prefix — disambiguate via kind
            return (
                child_gid.startswith("MT-HD-antelope-")
                and overlay_row["child_kind"] == "portion"
            )
        if species_group == "bear":
            return child_gid.startswith("MT-HD-bear-")

    if role_for_e03 == "restricted_area":
        if child_gid.startswith("MT-restricted-bigame-"):
            return True  # species-agnostic — all big-game species
        if child_gid.startswith("MT-restricted-elk-"):
            return species_group == "elk"  # elk-only discriminator
        return False  # unknown restricted-area namespace — fail closed

    if role_for_e03 == "cwd_management_zone":
        # CWD doesn't apply to bear or antelope — accept only for deer-family
        return species_group in {"elk", "mule_deer", "whitetail"}

    if role_for_e03 == "primary_unit":
        # Non-self-row primary_unit: filtered out by Step A above; this branch is
        # unreachable for a well-formed fixture (every primary_unit row IS the
        # self-row).  Return False defensively.
        return False

    # Unknown role_for_e03 — fail loud independently of `_build_overlay_bindings`'s
    # `_VALID_ROLE_FOR_E03` gate.  Public function; any future caller (test utility,
    # second builder, REPL investigation) that bypasses the gate would otherwise
    # silently skip bindings for unknown roles.
    raise RuntimeError(
        f"is_binding_eligible: unhandled role_for_e03 "
        f"{role_for_e03!r} for child_geometry_id "
        f"{overlay_row['child_geometry_id']!r}"
    )


# ---------------------------------------------------------------------------
# Parent geometry_id derivation (T4)
# ---------------------------------------------------------------------------


def _derive_parent_geometry_id(reg_record: RegulationRecord) -> str:
    """Map a regulation_record to its parent geometry_id.

    Patterns (locked by tests):

    +----------------------------+----------------------------+
    | jurisdiction_code          | parent geometry_id         |
    +============================+============================+
    | MT-HD-deer-elk-lion-N      | MT-HD-deer-elk-lion-N-geom |
    | MT-HD-antelope-N           | MT-HD-antelope-N-geom      |
    | MT-HD-bear-N               | MT-HD-bear-N-geom          |
    | MT-STATEWIDE-antelope      | MT-STATEWIDE-geom          |
    | MT-STATEWIDE-bear          | MT-STATEWIDE-geom          |
    +----------------------------+----------------------------+

    Fails loud on any other jurisdiction_code pattern — forces explicit handling
    when a new state or anchor introduces a new pattern.
    """
    jc = reg_record.jurisdiction_code
    if jc in {"MT-STATEWIDE-antelope", "MT-STATEWIDE-bear"}:
        return _MT_STATEWIDE_GEOM_ID
    if jc.startswith(("MT-HD-deer-elk-lion-", "MT-HD-antelope-", "MT-HD-bear-")):
        return f"{jc}-geom"
    raise RuntimeError(
        f"_derive_parent_geometry_id: unhandled jurisdiction_code pattern: "
        f"{jc!r}. Known patterns: MT-HD-deer-elk-lion-N, MT-HD-antelope-N, "
        f"MT-HD-bear-N, MT-STATEWIDE-antelope, MT-STATEWIDE-bear."
    )


# ---------------------------------------------------------------------------
# Source-citation pre-fetch (T5)
# ---------------------------------------------------------------------------


def _fetch_geometry_sources(
    conn: psycopg.Connection[tuple[object, ...]],
    geometry_ids: set[str],
) -> dict[str, SourceCitation]:
    """Pre-fetch source citations for every geometry id that will appear in a binding row.

    Per AC #1088 the geometry table is the authoritative source-of-record for binding
    attribution (the overlay fixture is derived).  This adapter-local SELECT keeps the
    ``db.py`` surface limited to write/mutation helpers per S03.10 constraint #7.

    Fails loud if any requested id is missing — that means the overlay fixture
    references a geometry absent from the DB, which is a structural fixture/DB
    sync bug.  Diagnostic: names up to the first 10 missing ids and notes if
    truncated.
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
# Statewide-binding builder (T6)
# ---------------------------------------------------------------------------


def _build_statewide_bindings(
    statewide_reg_records: list[RegulationRecord],
    mt_statewide_source: SourceCitation,
) -> list[JurisdictionBinding]:
    """Emit one primary_unit binding per statewide regulation_record → MT-STATEWIDE-geom.

    Per ADR-018: any role beyond 'primary_unit' for a statewide binding requires
    an ADR amendment.

    V1 statewide reg_records: MT-STATEWIDE-antelope, MT-STATEWIDE-bear.

    The MT-STATEWIDE-bear binding was already written by S03.6.1 via
    ``load_regulation_records._build_statewide_bear_binding``.  This builder
    re-derives it identically (same id format, same source) so the loop
    UPSERTs that row as a no-op rather than creating a duplicate.

    The MT-STATEWIDE-antelope binding is genuinely new in S03.10 (S03.6.1
    intentionally deferred it per epic line 919).
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
            geometry_id=_MT_STATEWIDE_GEOM_ID,
        )
        bindings.append(
            JurisdictionBinding(
                id=bid,
                regulation_record_state=rr.state,
                regulation_record_jurisdiction_code=rr.jurisdiction_code,
                regulation_record_species_group=rr.species_group,
                regulation_record_license_year=rr.license_year,
                geometry_id=_MT_STATEWIDE_GEOM_ID,
                role=role,
                verbatim_rule=None,
                source=mt_statewide_source,
            )
        )
    return bindings


# ---------------------------------------------------------------------------
# Overlay binding builder (T7)
# ---------------------------------------------------------------------------

_VALID_ROLE_FOR_E03: Final[frozenset[str]] = frozenset(
    {"primary_unit", "portion", "restricted_area", "cwd_management_zone"}
)


def _build_overlay_bindings(
    non_statewide_reg_records: list[RegulationRecord],
    overlay_rows: list[_OverlayRow],
    source_lookup: dict[str, SourceCitation],
) -> list[JurisdictionBinding]:
    """Walk every (non-statewide regulation_record × overlay_row) cross product,
    apply the species-axis filter from is_binding_eligible, and emit one
    JurisdictionBinding per qualified pair.

    Per-row source attribution comes from source_lookup (pre-fetched from the
    geometry table per AC #1088).

    Fails loud on:
        - unknown role_for_e03 value (defensive — _VALID_ROLE_FOR_E03 gate fires
          BEFORE is_binding_eligible so a malformed fixture row is caught even if
          the filter would have rejected it)
        - duplicate binding id within a single build run (structural invariant)
        - missing source citation for any child_geometry_id (KeyError surfaces
          from source_lookup)
    """
    # Index overlay rows by parent_geometry_id for O(N) lookup per reg_record
    rows_by_parent: dict[str, list[_OverlayRow]] = {}
    for row in overlay_rows:
        rows_by_parent.setdefault(row["parent_geometry_id"], []).append(row)

    bindings: list[JurisdictionBinding] = []
    seen_ids: set[str] = set()

    for rr in non_statewide_reg_records:
        parent_gid = _derive_parent_geometry_id(rr)
        parent_rows = rows_by_parent.get(parent_gid)
        if parent_rows is None:
            # Every HD-keyed reg_record's parent geometry must have at least a
            # self-row (primary_unit) in the overlay fixture per E02 invariant.
            # A missing entry means a structural fixture / reg_record sync bug —
            # silently skipping would lose ALL bindings (self-row + portions +
            # overlays) for this reg_record without diagnostic.  Fail loud.
            raise RuntimeError(
                f"_build_overlay_bindings: regulation_record "
                f"({rr.state}, {rr.jurisdiction_code}, {rr.species_group}, "
                f"{rr.license_year}) has parent_geometry_id {parent_gid!r} but "
                f"no overlay-fixture entries reference it as a parent. "
                f"Either the geometry-overlays.json fixture is stale, or a "
                f"regulation_record was inserted for a non-existent HD."
            )
        for row in parent_rows:
            role_e03 = row["role_for_e03"]
            # Unknown-role guard MUST fire before is_binding_eligible so a
            # malformed fixture row fails loud even if the filter would have
            # rejected it (constraint #5 in task spec).
            if role_e03 not in _VALID_ROLE_FOR_E03:
                raise RuntimeError(
                    f"overlay row has unknown role_for_e03 {role_e03!r}; "
                    f"parent={row['parent_geometry_id']!r} "
                    f"child={row['child_geometry_id']!r}"
                )
            if not is_binding_eligible(rr.species_group, parent_gid, row):
                continue
            child_gid = row["child_geometry_id"]
            try:
                source = source_lookup[child_gid]
            except KeyError as exc:
                raise RuntimeError(
                    f"_build_overlay_bindings: child_geometry_id {child_gid!r} "
                    f"missing from source_lookup; caller must pre-fetch all child ids."
                ) from exc

            # DO NOT PARSE the resulting id — see module docstring.
            # The id embeds hyphenated jurisdiction_code + geometry_id values.
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
                    f"_build_overlay_bindings: duplicate binding id {bid!r} — "
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
                            "primary_unit", "portion", "restricted_area",
                            "cwd_management_zone", "bear_management_unit",
                            "block_management_area", "other_overlay",
                        ],
                        role_e03,
                    ),
                    verbatim_rule=None,
                    source=source,
                )
            )

    return bindings


# ---------------------------------------------------------------------------
# No-hunt-zone Option A binder (T8)
# ---------------------------------------------------------------------------


def _query_nearby_hds_for_zone(
    conn: psycopg.Connection[tuple[object, ...]],
    zone_id: str,
) -> list[str]:
    """Return the geometry ids of every HD whose boundary is within
    `_NO_HUNT_ZONE_NEARBY_DISTANCE_M` meters of the zone's boundary.

    Per Spec Deviation #4 (plan § "Spec deviations" #4): single-clause
    extensions.ST_DWithin on native geography type.  This supersedes the spec's
    two-clause ST_Touches OR ST_DWithin(centroid, centroid, 5000) rule because
    (a) the centroid-to-centroid clause empirically returned 0 matches for all
    3 orphan zones at 5km, and (b) boundary-to-boundary at 5000m covers
    ST_Touches (touching = 0m distance) and "near" simultaneously.

    **Filter is `kind = 'hunting_district'` — portions intentionally excluded.**
    `regulation_record` is HD-keyed in V1 (every reg_record's jurisdiction_code
    resolves to an HD-shaped parent_geometry_id via `_derive_parent_geometry_id`;
    portion ids never appear as keys in `rrs_by_parent`).  Including portions in
    this query would silently produce 0 bindings for every portion match (the
    downstream `rrs_by_parent.get(portion_id, [])` lookup returns `[]`).  In
    V1 Montana every nearby portion's parent HD is also nearby (verified at
    2026-05-24 against Yellowstone NP's 4 portion matches — all share HDs 310
    or 314, both of which are in the nearby HD list), so HD-only filter loses
    zero bindings.  Future state work that introduces portion-keyed reg_records
    must also extend `_derive_parent_geometry_id` and revisit this filter.

    Schema-prefix discipline: PostGIS lives in the `extensions` schema in this
    Supabase project; all ST_* functions must be `extensions.`-qualified or
    they fail to resolve.
    """
    # `hd.state = %s` is load-bearing: in M2+ when Colorado geometry rows land,
    # an out-of-state HD whose geom is within 5km of a Montana orphan zone
    # (e.g., a CO HD near a MT/CO border zone) would be returned here, but its
    # id (`CO-GMU-*-geom`) doesn't appear as a key in `rrs_by_parent` (which is
    # built only from Montana reg_records).  The downstream
    # `rrs_by_parent.get(out_of_state_hd_id, [])` lookup silently returns [],
    # and the zero-nearby fail-loud guard doesn't fire because `nearby_hd_ids`
    # is non-empty.  Filter at the SQL layer so the guard's semantics are
    # actually preserved (non-empty result = at least one in-scope HD).
    sql = """
        SELECT DISTINCT hd.id
        FROM geometry zone
        JOIN geometry hd
          ON hd.kind = 'hunting_district'
          AND hd.state = %s
          AND extensions.ST_DWithin(zone.geom, hd.geom, %s)
        WHERE zone.id = %s
        ORDER BY hd.id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (_STATE, _NO_HUNT_ZONE_NEARBY_DISTANCE_M, zone_id))
        return [str(row[0]) for row in cur.fetchall()]


def _build_no_hunt_zone_bindings(
    conn: psycopg.Connection[tuple[object, ...]],
    non_statewide_reg_records: list[RegulationRecord],
    source_lookup: dict[str, SourceCitation],
) -> list[JurisdictionBinding]:
    """For each of the 3 EXPECTED_RA_ORPHAN_IDS, query the nearby HDs via the
    geography-native ST_DWithin rule, then emit one binding per
    (reg_record using that HD as parent_geometry, zone) pair with
    role='other_overlay'.

    Per-zone fail-loud (AC #1086): if any zone produces zero nearby HD matches
    (because no HD is within the threshold), raise RuntimeError naming the
    zone — that means Option A is infeasible for this zone and escalation is
    required per spec line 1067.

    `role='other_overlay'` is the only DDL-permitted role for this semantic
    (the 7-value role enum does not include 'no_hunt_zone' — see plan T8
    paragraph + M2-deferred items).
    """
    # Index reg_records by their parent geometry id so we can quickly fan out
    # zone-to-HD edges into (reg_record, zone) bindings.
    rrs_by_parent: dict[str, list[RegulationRecord]] = {}
    for rr in non_statewide_reg_records:
        parent_gid = _derive_parent_geometry_id(rr)
        rrs_by_parent.setdefault(parent_gid, []).append(rr)

    bindings: list[JurisdictionBinding] = []
    seen_ids: set[str] = set()

    for zone_id in sorted(EXPECTED_RA_ORPHAN_IDS):
        nearby_hd_ids = _query_nearby_hds_for_zone(conn, zone_id)
        if not nearby_hd_ids:
            raise RuntimeError(
                f"no-hunt zone {zone_id!r} produced zero nearby HD matches at "
                f"{_NO_HUNT_ZONE_NEARBY_DISTANCE_M}m — escalate per spec line 1067."
            )
        try:
            zone_source = source_lookup[zone_id]
        except KeyError as exc:
            raise RuntimeError(
                f"_build_no_hunt_zone_bindings: zone {zone_id!r} missing from "
                f"source_lookup; caller must pre-fetch all EXPECTED_RA_ORPHAN_IDS."
            ) from exc

        for hd_id in nearby_hd_ids:
            for rr in rrs_by_parent.get(hd_id, []):
                role: Literal["other_overlay"] = "other_overlay"
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
                        f"_build_no_hunt_zone_bindings: duplicate binding id "
                        f"{bid!r} — second occurrence for zone {zone_id!r} + "
                        f"HD {hd_id!r}."
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

    return bindings


# ---------------------------------------------------------------------------
# Row-count guard + cross-tab summary (T9)
# ---------------------------------------------------------------------------


def _assert_binding_count_within_guard(written: int) -> None:
    """OQ7 row-count guard for S03.10.

    Band is ``_BINDING_COUNT_GUARD_BAND`` (currently ``(400, 1100)`` — intentionally
    wide pending T16's empirical count; narrow to ±30% after first live run).
    See plan § "Spec deviations" #2 for derivation rationale.
    """
    lo, hi = _BINDING_COUNT_GUARD_BAND
    if not (lo <= written <= hi):
        raise RuntimeError(
            f"jurisdiction_binding write count {written} outside expected "
            f"band [{lo}, {hi}] — investigate for regression before re-running. "
            f"See spec § S03.10 line 1071 + plan § 'Spec deviations' #2."
        )


def _log_summary(
    bindings: list[JurisdictionBinding], logger: logging.Logger
) -> None:
    """Cross-tab: per-(species_group, role) binding counts.

    Mirrors S03.6's ``_log_summary`` pattern.  Logged at INFO at end of build
    phase, before the guard check, so the operator sees the per-bucket
    breakdown even if the guard subsequently aborts.
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
# Regulation-record query helper (T10)
# ---------------------------------------------------------------------------


def _query_all_montana_regulation_records(
    conn: psycopg.Connection[tuple[object, ...]],
) -> list[RegulationRecord]:
    """Fetch every Montana regulation_record from the DB and validate via Pydantic.

    Returns one RegulationRecord per row, ordered deterministically so the
    binding-build pass is reproducible across runs.
    """
    # license_year filter is load-bearing: the binding loader is sized + count-
    # guarded for V1 (_LICENSE_YEAR = 2026).  Without this clause, a future
    # year-over-year re-ingestion (when 2027 rows land) would silently fan out
    # bindings across both years, blowing past the count guard and writing
    # cross-year bindings that violate the (reg_record, geometry, role) UPSERT
    # contract.  Filter at the SQL layer, not in Python, so the count guard
    # narrows to the in-year set.
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
                source=SourceCitation.model_validate(row[8]),
            )
        )
    return records


# ---------------------------------------------------------------------------
# Entry point (T10)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Three-phase orchestration: build → guard → write.

    Phase 1 (build): load overlay fixture (pure), open DB conn, query
    regulation_records, pre-fetch geometry source citations, run the spatial
    nearby-rule per orphan zone, construct all binding rows in memory.

    Phase 2 (guard): OQ7 row-count band check fires BEFORE the UPSERT write
    loop (still inside the same ``with db.connect()`` block).  Any band
    violation raises RuntimeError so no partial write occurs.  Cross-tab
    summary logs before the guard check so operators see the breakdown even
    if the guard aborts.

    Phase 3 (write): UPSERT each JurisdictionBinding via
    db.upsert_jurisdiction_binding; commit; rollback on any exception.

    ``--dry-run``: short-circuit after the guard check; no writes.
    """
    logger = logging.getLogger(__name__)
    dry_run = "--dry-run" in (argv if argv is not None else sys.argv[1:])

    # PHASE 1: BUILD
    # Overlay fixture load is pure; all remaining build steps require DB reads.
    overlay_rows = _load_overlay_fixture(_OVERLAY_FIXTURE_PATH)

    with db.connect() as conn:
        reg_records = _query_all_montana_regulation_records(conn)
        if not reg_records:
            raise RuntimeError(
                "_query_all_montana_regulation_records returned 0 rows — "
                "ensure prior loaders (S03.6 load_regulation_records.py + "
                "S03.6.1 statewide-bear amendment + S03.7 + S03.8 + S03.9) "
                "have been run against this DB first."
            )
        statewide_rrs = [
            rr for rr in reg_records
            if rr.jurisdiction_code.startswith("MT-STATEWIDE-")
        ]
        # V1 expects exactly 2 statewide reg_records: MT-STATEWIDE-antelope and
        # MT-STATEWIDE-bear.  Their absence indicates either S03.6 / S03.6.1
        # weren't fully run, or the schema invariant has drifted.
        expected_statewide = {"MT-STATEWIDE-antelope", "MT-STATEWIDE-bear"}
        present_statewide = {rr.jurisdiction_code for rr in statewide_rrs}
        missing_statewide = expected_statewide - present_statewide
        if missing_statewide:
            raise RuntimeError(
                f"expected statewide regulation_records {sorted(expected_statewide)} "
                f"but found only {sorted(present_statewide)}; missing: "
                f"{sorted(missing_statewide)}. Ensure S03.6 + S03.6.1 ran fully."
            )
        # Symmetric check: any UNEXPECTED statewide code must fail loud too.
        # `_build_statewide_bindings` would happily emit a binding for an unknown
        # code, but downstream species filtering + UAT spot-checks assume only
        # the V1 set.  A new statewide anchor (e.g., MT-STATEWIDE-mountain_lion)
        # requires an ADR amendment per ADR-018; until then, surface it loudly.
        unexpected_statewide = present_statewide - expected_statewide
        if unexpected_statewide:
            raise RuntimeError(
                f"unexpected statewide regulation_records: "
                f"{sorted(unexpected_statewide)}. V1 Montana expects only "
                f"{sorted(expected_statewide)}; any new statewide anchor "
                f"requires an ADR-018 amendment + S03.10 spec update before "
                f"this loader can bind it correctly."
            )
        non_statewide_rrs = [
            rr for rr in reg_records
            if not rr.jurisdiction_code.startswith("MT-STATEWIDE-")
        ]

        # Collect every geometry id that any builder will reference so the
        # source pre-fetch is a single query instead of N queries.
        candidate_geom_ids: set[str] = {_MT_STATEWIDE_GEOM_ID}
        for row in overlay_rows:
            candidate_geom_ids.add(row["child_geometry_id"])
        candidate_geom_ids.update(EXPECTED_RA_ORPHAN_IDS)
        source_lookup = _fetch_geometry_sources(conn, candidate_geom_ids)

        statewide_source = source_lookup[_MT_STATEWIDE_GEOM_ID]
        statewide_bindings = _build_statewide_bindings(statewide_rrs, statewide_source)
        overlay_bindings = _build_overlay_bindings(
            non_statewide_rrs, overlay_rows, source_lookup
        )
        no_hunt_bindings = _build_no_hunt_zone_bindings(
            conn, non_statewide_rrs, source_lookup
        )

        all_bindings = statewide_bindings + overlay_bindings + no_hunt_bindings

        # PHASE 2: GUARD
        # Cross-builder duplicate-id check: each builder maintains its own
        # `seen_ids` set, so a collision between the statewide / overlay / no-
        # hunt-zone builders would slip through.  Catch it here before any
        # UPSERT.  If this fires, investigate which two builders produced the
        # same id — it usually means a no-hunt-zone child collides with an
        # overlay-fixture-derived binding for the same (reg_record, geometry,
        # role) tuple, which shouldn't happen given the role discriminator.
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
        # Log summary so operators see the per-bucket breakdown even if the
        # row-count guard subsequently aborts.  Guard fires BEFORE any UPSERT.
        _log_summary(all_bindings, logger)
        _assert_binding_count_within_guard(len(all_bindings))

        if dry_run:
            logger.info(
                "Dry-run complete: %d bindings would be written", len(all_bindings)
            )
            return 0

        # PHASE 3: WRITE
        try:
            for binding in all_bindings:
                db.upsert_jurisdiction_binding(conn, binding)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    logger.info("Wrote %d jurisdiction_binding rows", len(all_bindings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
