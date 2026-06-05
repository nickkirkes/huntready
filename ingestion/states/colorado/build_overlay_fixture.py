"""CO geometry overlay fixture builder.

Builds the geometry-overlay fixture for E06 handoff. Computes every spatial
relationship between V1 CO geometries (GMU self-references, GMU↔CWD-zone
(vacuous — zero CWD rows per S05.3 documented gap), GMU↔Restricted-Area) so
E06 can populate ``jurisdiction_binding`` rows once ``regulation_record`` rows
exist, without re-running PostGIS spatial computation.

Architecture: spatial relationships are computed *locally* with shapely +
STRtree, not via cross-join SQL. The single SQL query loads all CO geometries
(``ST_AsText`` on the geography column — no ``::geometry`` cast, per the
documented pitfall); shapely parses the WKT and runs the
covers/intersects discriminator in-process. Rationale: a Supabase
role-locked 2-min ``statement_timeout`` aborts the cross-join SQL on the
real dataset (~12k candidate pairs against ~113 KB MultiPolygons); local
shapely completes the same work in ~5 seconds.

Discriminator: the relationship label is derived from the child-area
overlap ratio (``parent.intersection(child).area / child.area``), not from
shapely's strict ``covers`` predicate. The thresholds below are the contract
documented in ADR-016 (digitization-tolerant containment):

    overlap_pct >= COVER_RELABEL_THRESHOLD (0.99)  -> relationship = "covers"
    overlap_pct <  COVER_DROP_THRESHOLD    (0.01)  -> drop the row, audit it
    otherwise                                       -> relationship = "intersects"

Outputs:
- ``ingestion/states/colorado/fixtures/geometry-overlays.json`` — kept rows.
- ``ingestion/states/colorado/fixtures/geometry-overlays-dropped.json`` —
  audit log of pairs filtered out by the lower threshold. Lets a reviewer
  verify nothing semantically real was discarded; filtering is one-way.

Run from the repo root::

    ingestion/.venv/bin/python ingestion/states/colorado/build_overlay_fixture.py

Required env: ``DATABASE_URL``.

``_JURISDICTION_BINDING_ID_FORMAT`` contract for E06
----------------------------------------------------
E06's CO binding loader must import ``_JURISDICTION_BINDING_ID_FORMAT`` from
S03.6.1's ``load_regulation_records.py`` (or its CO equivalent) so that
``CO-STATEWIDE-{species}`` binding ids derive symmetrically and produce a
UPSERT no-op when re-run. The format string is::

    "{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"

This is the same contract S03.6.1 locked for MT statewide bear bindings.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import psycopg
from shapely import from_wkt
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from ingestion.lib import db
from ingestion.lib.overlays import (
    ROLE_FOR_BINDING_BY_CHILD_KIND,
    DroppedOverlayPair,
    OverlayChildKind,
    OverlayFixtureRow,
    OverlayRelationship,
)


CO_STATE_CODE = "US-CO"
CO_FIXTURE_DIR = Path(__file__).parent / "fixtures"
OVERLAY_FIXTURE_PATH = CO_FIXTURE_DIR / "geometry-overlays.json"
DROPPED_AUDIT_PATH = CO_FIXTURE_DIR / "geometry-overlays-dropped.json"

# Digitization-tolerant containment thresholds. See ADR-016.
COVER_RELABEL_THRESHOLD = 0.99
COVER_DROP_THRESHOLD = 0.01
# Round overlap_pct to this many decimal places so the audit JSON is
# byte-deterministic across runs / shapely builds. Six decimals comfortably
# resolves both thresholds without exposing trailing-digit float noise.
_OVERLAP_PCT_PRECISION = 6


_logger = logging.getLogger(__name__)


class OverlayFixtureError(ValueError):
    """Raised when the overlay fixture violates the S05.5 coverage invariant."""


_LOAD_GEOMS_SQL = """
SELECT id, kind, ST_AsText(geom)
FROM geometry
WHERE state = %s
ORDER BY id
"""


def _load_geometries(
    conn: psycopg.Connection[tuple[object, ...]],
) -> list[tuple[str, str, BaseGeometry]]:
    """Load all CO geometries and parse WKT into shapely objects.

    Geography-native: uses ``ST_AsText(geom)`` which works directly on the
    ``geography(MultiPolygon, 4326)`` column without the disabled
    ``::geometry`` cast.
    """
    with conn.cursor() as cur:
        cur.execute(_LOAD_GEOMS_SQL, (CO_STATE_CODE,))
        rows = cur.fetchall()
    parsed: list[tuple[str, str, BaseGeometry]] = []
    for geom_id, kind, wkt_text in rows:
        parsed.append((str(geom_id), str(kind), from_wkt(str(wkt_text))))
    return parsed


def _build_gmu_self_rows(gmu_ids: list[str]) -> list[OverlayFixtureRow]:
    """Build GMU → GMU self-reference rows (programmatic, not spatial)."""
    rows: list[OverlayFixtureRow] = []
    for gmu_id in gmu_ids:
        rows.append(
            {
                "parent_geometry_id": gmu_id,
                "child_geometry_id": gmu_id,
                "parent_kind": "gmu",
                "child_kind": "gmu",
                "relationship": "self",
                "role_for_e03": ROLE_FOR_BINDING_BY_CHILD_KIND["gmu"],
            }
        )
    return rows


def _build_overlay_pairs(
    gmus: list[tuple[str, BaseGeometry]],
    children: list[tuple[str, BaseGeometry]],
    child_kind: OverlayChildKind,
) -> tuple[list[OverlayFixtureRow], list[DroppedOverlayPair]]:
    """Build GMU → child overlay rows + audit log of dropped pairs.

    Returns (kept_rows, dropped_rows). For each GMU, query the STRtree for
    bbox-overlapping child candidates, then compute the area-overlap ratio
    and apply the thresholds (see ADR-016):

        pct >= COVER_RELABEL_THRESHOLD  ->  kept as "covers"
        pct <  COVER_DROP_THRESHOLD     ->  dropped (audit log)
        otherwise                        ->  kept as "intersects"

    Zero-area children cannot produce a meaningful ratio; they are kept as
    "intersects" without ratio computation (defensive — should not occur
    with validated MultiPolygons).
    """
    if not children:
        return [], []
    tree = STRtree([c[1] for c in children])
    role = ROLE_FOR_BINDING_BY_CHILD_KIND[child_kind]
    kept: list[OverlayFixtureRow] = []
    dropped: list[DroppedOverlayPair] = []
    for gmu_id, gmu_geom in gmus:
        for cand_idx in tree.query(gmu_geom):
            child_id, child_geom = children[int(cand_idx)]
            if not gmu_geom.intersects(child_geom):
                continue
            relationship: OverlayRelationship
            if child_geom.area == 0:
                relationship = "intersects"
            else:
                overlap_pct = gmu_geom.intersection(child_geom).area / child_geom.area
                if overlap_pct < COVER_DROP_THRESHOLD:
                    dropped.append(
                        {
                            "parent_geometry_id": gmu_id,
                            "child_geometry_id": child_id,
                            "parent_kind": "gmu",
                            "child_kind": child_kind,
                            "overlap_pct": round(overlap_pct, _OVERLAP_PCT_PRECISION),
                        }
                    )
                    continue
                relationship = "covers" if overlap_pct >= COVER_RELABEL_THRESHOLD else "intersects"
            kept.append(
                {
                    "parent_geometry_id": gmu_id,
                    "child_geometry_id": child_id,
                    "parent_kind": "gmu",
                    "child_kind": child_kind,
                    "relationship": relationship,
                    "role_for_e03": role,
                }
            )
    return kept, dropped


# Per ADR-016: an explicit allowlist of restricted_area geometry IDs that
# are documented no-hunt zones (NPS National Parks, National Monuments, and
# the Air Force Academy) overlaid ON, not contained BY, GMUs. Any
# restricted_area orphan NOT on this list is a real data regression and fails
# the build. Add a new id only after human review confirms it is a no-hunt
# zone, not an internal GMU restriction that lost its parent.
# Source-of-truth: docs/planning/epics/E05-confidence-findings/S05.4.md
# (discovery report § "V1 expected IDs", line ~170).
EXPECTED_CO_RA_ORPHAN_IDS: frozenset[str] = frozenset(
    {
        "CO-restricted-rocky-mountain-national-park-geom",
        "CO-restricted-mesa-verde-national-park-geom",
        "CO-restricted-great-sand-dunes-national-park-geom",
        "CO-restricted-black-canyon-of-the-gunnison-national-park-geom",
        "CO-restricted-dinosaur-national-monument-geom",
        "CO-restricted-colorado-national-monument-geom",
        "CO-restricted-florissant-fossil-beds-national-monument-geom",
        "CO-restricted-hovenweep-national-monument-geom",
        "CO-restricted-yucca-house-national-monument-geom",
        "CO-restricted-united-states-air-force-academy-geom",
    }
)
assert len(EXPECTED_CO_RA_ORPHAN_IDS) == 10


def _validate_coverage(
    parsed: list[tuple[str, str, BaseGeometry]],
    rows: list[OverlayFixtureRow],
) -> None:
    """Validate the S05.5 coverage invariant; collect all violations then raise once.

    Two checks, both run before raising:
      A. Every ``cwd_zone`` / ``restricted_area`` row in the geometry table
         appears as ``child_geometry_id`` of some ``gmu`` parent (relationship
         ``covers`` or ``intersects``). Dropped pairs (audit log) are NOT
         counted toward coverage — only kept rows.

         ``restricted_area`` orphans split into two cases:
           - Allowlisted no-hunt zones (``EXPECTED_CO_RA_ORPHAN_IDS``):
             reported at INFO level, do not block. Federal no-hunt zones (NPS
             National Parks, National Monuments, Air Force Academy) are
             legitimately adjacent to GMUs without overlapping them.
           - Anything else: blocks the build like CWD orphans.
             A previously-covered restricted_area becoming an orphan is a
             real data regression worth surfacing loudly. See ADR-016 for
             the rationale.
      B. Every fixture-referenced ``geometry_id`` (parent or child) exists
         in the loaded geometry list.
    """
    child_set: set[tuple[str, str]] = {
        (row["child_kind"], row["child_geometry_id"])
        for row in rows
        if row["parent_kind"] == "gmu"
        and row["relationship"] in ("covers", "intersects")
    }
    orphans_by_kind: dict[str, list[str]] = {}
    for geom_id, kind, _ in parsed:
        if kind not in ("cwd_zone", "restricted_area"):
            continue
        if (kind, geom_id) not in child_set:
            orphans_by_kind.setdefault(kind, []).append(geom_id)

    blocking_orphans: dict[str, list[str]] = {}
    if "cwd_zone" in orphans_by_kind:
        blocking_orphans["cwd_zone"] = sorted(orphans_by_kind["cwd_zone"])
    if "restricted_area" in orphans_by_kind:
        ra_orphans = orphans_by_kind["restricted_area"]
        expected = sorted(r for r in ra_orphans if r in EXPECTED_CO_RA_ORPHAN_IDS)
        unexpected = sorted(r for r in ra_orphans if r not in EXPECTED_CO_RA_ORPHAN_IDS)
        if expected:
            _logger.info(
                "%d restricted_area orphan(s) per ADR-016 allowlist (no-hunt zones): %s",
                len(expected),
                expected,
            )
        if unexpected:
            blocking_orphans["restricted_area"] = unexpected

    id_set: set[str] = {g[0] for g in parsed}
    unknown_ids: set[str] = set()
    for row in rows:
        if row["parent_geometry_id"] not in id_set:
            unknown_ids.add(row["parent_geometry_id"])
        if row["child_geometry_id"] not in id_set:
            unknown_ids.add(row["child_geometry_id"])

    if not blocking_orphans and not unknown_ids:
        return

    lines = ["overlay fixture coverage invariant violated:"]
    for kind in ("cwd_zone", "restricted_area"):
        if kind in blocking_orphans:
            lines.append(f"  orphan {kind}: {blocking_orphans[kind]!r}")
    if unknown_ids:
        lines.append(f"  unknown geometry ids referenced in fixture: {sorted(unknown_ids)!r}")
    raise OverlayFixtureError("\n".join(lines))


def _collect_overlay_rows(
    conn: psycopg.Connection[tuple[object, ...]],
) -> tuple[list[OverlayFixtureRow], list[DroppedOverlayPair]]:
    """Load all geometries and compute the kept overlay rows + dropped audit log."""
    parsed = _load_geometries(conn)
    _logger.info("loaded %d CO geometries", len(parsed))

    gmus = [(g[0], g[2]) for g in parsed if g[1] == "gmu"]
    cwds = [(g[0], g[2]) for g in parsed if g[1] == "cwd_zone"]
    ras = [(g[0], g[2]) for g in parsed if g[1] == "restricted_area"]

    if not gmus:
        msg = (
            f"no gmu rows found for state {CO_STATE_CODE!r} — "
            "geometry table unpopulated? Re-run S05.2 loader before building the overlay fixture."
        )
        raise OverlayFixtureError(msg)

    self_rows = _build_gmu_self_rows([g[0] for g in gmus])
    cwd_rows, cwd_dropped = _build_overlay_pairs(gmus, cwds, "cwd_zone")
    ra_rows, ra_dropped = _build_overlay_pairs(gmus, ras, "restricted_area")

    _logger.info(
        "kept %d GMU self, %d GMU→cwd_zone (dropped %d), %d GMU→restricted_area (dropped %d)",
        len(self_rows),
        len(cwd_rows),
        len(cwd_dropped),
        len(ra_rows),
        len(ra_dropped),
    )

    kept = self_rows + cwd_rows + ra_rows
    dropped = cwd_dropped + ra_dropped
    _validate_coverage(parsed, kept)
    return kept, dropped


def _write_outputs(
    kept: list[OverlayFixtureRow],
    dropped: list[DroppedOverlayPair],
) -> None:
    """Serialize and write the fixture + audit pair as a transaction.

    Two-phase write to minimize the partial-update window:
      1. Pre-serialize both payloads in memory (catches any serialization
         error before touching disk).
      2. Write both ``.tmp`` files. If the second write fails, the first
         ``.tmp`` is unlinked so neither real file gets updated.
      3. Rename both ``.tmp`` files to their final paths.

    The renames in step 3 are not jointly atomic (POSIX has no
    multi-file rename), but renames are extremely fast and rarely fail
    given the writes already succeeded. The first rename is the kept
    fixture: if the second rename fails after the first succeeds, the
    on-disk state is "current fixture + previous audit", which is
    preferable to "previous fixture + current audit" (the audit is
    informational; the fixture is what E06 consumes). The orphan ``.tmp``
    is left for manual inspection rather than auto-deleted, so the
    operator can see the fixture/audit divergence.
    """
    sorted_kept = sorted(
        kept,
        key=lambda r: (r["parent_geometry_id"], r["child_geometry_id"], r["relationship"]),
    )
    sorted_dropped = sorted(
        dropped,
        key=lambda d: (d["parent_geometry_id"], d["child_geometry_id"]),
    )
    fixture_payload = (
        json.dumps(sorted_kept, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    audit_payload = (
        json.dumps(sorted_dropped, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    CO_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    fixture_tmp = OVERLAY_FIXTURE_PATH.with_name(OVERLAY_FIXTURE_PATH.name + ".tmp")
    audit_tmp = DROPPED_AUDIT_PATH.with_name(DROPPED_AUDIT_PATH.name + ".tmp")

    fixture_tmp.write_text(fixture_payload, encoding="utf-8")
    try:
        audit_tmp.write_text(audit_payload, encoding="utf-8")
    except Exception:
        fixture_tmp.unlink(missing_ok=True)
        raise

    fixture_tmp.replace(OVERLAY_FIXTURE_PATH)
    audit_tmp.replace(DROPPED_AUDIT_PATH)

    _logger.info("wrote %d overlay rows to %s", len(sorted_kept), OVERLAY_FIXTURE_PATH)
    _logger.info("wrote %d dropped-pair audit rows to %s", len(sorted_dropped), DROPPED_AUDIT_PATH)


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args, open DB, collect overlay rows, write fixture + audit."""
    parser = argparse.ArgumentParser(description="Build the CO geometry overlay fixture for E06.")
    parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    with db.connect() as conn:
        kept, dropped = _collect_overlay_rows(conn)

    _write_outputs(kept, dropped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
