"""Montana geometry overlay fixture builder.

Builds the geometry-overlay fixture for E03 handoff per story S02.6.
The fixture captures four parent→child relationship classes:
  1. HD → HD self-references (programmatic, not spatial)
  2. HD → Portion containment (ST_Covers)
  3. HD → CWD zone containment or intersection
  4. HD → Restricted Area containment or intersection

Output path:
    ingestion/states/montana/fixtures/geometry-overlays.json

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/build_overlay_fixture.py

Required env: DATABASE_URL.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import psycopg

from ingestion.lib import db
from ingestion.lib.overlays import (
    ROLE_FOR_E03_BY_CHILD_KIND,
    OverlayChildKind,
    OverlayFixtureRow,
    OverlayRelationship,
)


MT_STATE_CODE = "US-MT"
MT_FIXTURE_DIR = Path(__file__).parent / "fixtures"
OVERLAY_FIXTURE_PATH = MT_FIXTURE_DIR / "geometry-overlays.json"

_logger = logging.getLogger(__name__)

class OverlayFixtureError(ValueError):
    """Raised when the overlay fixture violates the S02.6 coverage invariant."""


_HD_IDS_SQL = """
SELECT id FROM geometry
WHERE kind = 'hunting_district' AND state = %s
ORDER BY id
"""

_HD_TO_PORTION_SQL = """
SELECT a.id AS parent_id, b.id AS child_id
FROM geometry a, geometry b
WHERE a.kind = 'hunting_district' AND b.kind = 'portion'
  AND a.state = %s AND b.state = %s
  AND ST_Covers(a.geom, b.geom)
"""

_HD_TO_OVERLAY_SQL = """
SELECT a.id AS parent_id, b.id AS child_id,
       ST_Covers(a.geom, b.geom) AS is_covered
FROM geometry a, geometry b
WHERE a.kind = 'hunting_district' AND b.kind = %s
  AND a.state = %s AND b.state = %s
  AND ST_Intersects(a.geom, b.geom)
"""


def _fetch_hd_ids(conn: psycopg.Connection[tuple[object, ...]]) -> list[str]:
    """Return all hunting district geometry IDs for Montana, ordered by id."""
    with conn.cursor() as cur:
        cur.execute(_HD_IDS_SQL, (MT_STATE_CODE,))
        return [str(row[0]) for row in cur.fetchall()]


def _build_hd_self_rows(hd_ids: list[str]) -> list[OverlayFixtureRow]:
    """Build HD → HD self-reference rows (programmatic, not spatial)."""
    rows: list[OverlayFixtureRow] = []
    for hd_id in hd_ids:
        rows.append(
            OverlayFixtureRow(
                parent_geometry_id=hd_id,
                child_geometry_id=hd_id,
                parent_kind="hunting_district",
                child_kind="hunting_district",
                relationship="self",
                role_for_e03=ROLE_FOR_E03_BY_CHILD_KIND["hunting_district"],
            )
        )
    return rows


def _build_hd_portion_rows(conn: psycopg.Connection[tuple[object, ...]]) -> list[OverlayFixtureRow]:
    """Build HD → Portion containment rows via ST_Covers."""
    rows: list[OverlayFixtureRow] = []
    with conn.cursor() as cur:
        cur.execute(_HD_TO_PORTION_SQL, (MT_STATE_CODE, MT_STATE_CODE))
        for row in cur.fetchall():
            rows.append(
                OverlayFixtureRow(
                    parent_geometry_id=str(row[0]),
                    child_geometry_id=str(row[1]),
                    parent_kind="hunting_district",
                    child_kind="portion",
                    relationship="covers",
                    role_for_e03=ROLE_FOR_E03_BY_CHILD_KIND["portion"],
                )
            )
    return rows


def _build_hd_overlay_rows(
    conn: psycopg.Connection[tuple[object, ...]],
    child_kind: OverlayChildKind,
) -> list[OverlayFixtureRow]:
    """Build HD → overlay rows for a given child kind via ST_Intersects / ST_Covers."""
    rows: list[OverlayFixtureRow] = []
    with conn.cursor() as cur:
        cur.execute(_HD_TO_OVERLAY_SQL, (child_kind, MT_STATE_CODE, MT_STATE_CODE))
        for row in cur.fetchall():
            is_covered = bool(row[2])
            relationship: OverlayRelationship = "covers" if is_covered else "intersects"
            rows.append(
                OverlayFixtureRow(
                    parent_geometry_id=str(row[0]),
                    child_geometry_id=str(row[1]),
                    parent_kind="hunting_district",
                    child_kind=child_kind,
                    relationship=relationship,
                    role_for_e03=ROLE_FOR_E03_BY_CHILD_KIND[child_kind],
                )
            )
    return rows


def _emit_explain(
    conn: psycopg.Connection[tuple[object, ...]],
    label: str,
    sql: str,
    params: tuple[object, ...],
) -> None:
    """Run EXPLAIN ANALYZE for a spatial query and emit the plan to stderr."""
    with conn.cursor() as cur:
        cur.execute("EXPLAIN (ANALYZE, FORMAT TEXT) " + sql, params)
        rows = cur.fetchall()
    print(f"# EXPLAIN ANALYZE: {label}", file=sys.stderr)
    for row in rows:
        print(row[0], file=sys.stderr)
    print("", file=sys.stderr)


def _collect_overlay_rows(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    explain: bool,
) -> list[OverlayFixtureRow]:
    """Collect all overlay rows by running spatial queries against the DB."""
    if explain:
        _emit_explain(conn, "HD→Portion", _HD_TO_PORTION_SQL, (MT_STATE_CODE, MT_STATE_CODE))
        _emit_explain(conn, "HD→CWD zone", _HD_TO_OVERLAY_SQL, ("cwd_zone", MT_STATE_CODE, MT_STATE_CODE))
        _emit_explain(conn, "HD→Restricted Area", _HD_TO_OVERLAY_SQL, ("restricted_area", MT_STATE_CODE, MT_STATE_CODE))

    hd_ids = _fetch_hd_ids(conn)
    if not hd_ids:
        msg = (
            f"no hunting_district rows found for state {MT_STATE_CODE!r} — "
            "geometry table unpopulated? Re-run S02.2 loader before building the overlay fixture."
        )
        raise OverlayFixtureError(msg)
    self_rows = _build_hd_self_rows(hd_ids)
    portion_rows = _build_hd_portion_rows(conn)
    cwd_rows = _build_hd_overlay_rows(conn, "cwd_zone")
    ra_rows = _build_hd_overlay_rows(conn, "restricted_area")

    _logger.info(
        "collected %d HD self rows, %d HD→portion, %d HD→cwd_zone, %d HD→restricted_area",
        len(self_rows),
        len(portion_rows),
        len(cwd_rows),
        len(ra_rows),
    )

    rows = self_rows + portion_rows + cwd_rows + ra_rows
    _validate_coverage(conn, rows)
    return rows


def _validate_coverage(
    conn: psycopg.Connection[tuple[object, ...]],
    rows: list[OverlayFixtureRow],
) -> None:
    """Validate the S02.6 coverage invariant; collect all violations then raise once."""
    lines: list[str] = []

    # Check A — orphan coverage: every portion / cwd_zone / restricted_area
    # must appear as a child of at least one hunting_district.
    child_set: set[tuple[str, str]] = {
        (row["child_kind"], row["child_geometry_id"])
        for row in rows
        if row["parent_kind"] == "hunting_district"
        and row["relationship"] in ("covers", "intersects")
    }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, kind FROM geometry"
            " WHERE state = %s AND kind IN ('portion', 'cwd_zone', 'restricted_area')"
            " ORDER BY kind, id",
            (MT_STATE_CODE,),
        )
        orphans_by_kind: dict[str, list[str]] = {}
        for db_id, db_kind in cur.fetchall():
            if (str(db_kind), str(db_id)) not in child_set:
                orphans_by_kind.setdefault(str(db_kind), []).append(str(db_id))

    for kind in ("portion", "cwd_zone", "restricted_area"):
        if kind in orphans_by_kind:
            lines.append(f"  orphan {kind}: {orphans_by_kind[kind]}")

    # Check B — unknown geometry id: every parent_geometry_id and
    # child_geometry_id referenced in the fixture must exist in the DB.
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM geometry WHERE state = %s", (MT_STATE_CODE,))
        id_set: set[str] = {str(row[0]) for row in cur.fetchall()}

    unknown_ids: set[str] = set()
    for row in rows:
        if row["parent_geometry_id"] not in id_set:
            unknown_ids.add(row["parent_geometry_id"])
        if row["child_geometry_id"] not in id_set:
            unknown_ids.add(row["child_geometry_id"])

    if unknown_ids:
        lines.append(f"  unknown geometry ids referenced in fixture: {sorted(unknown_ids)}")

    if lines:
        msg = "overlay fixture coverage invariant violated:\n" + "\n".join(lines)
        raise OverlayFixtureError(msg)


def _write_fixture(rows: list[OverlayFixtureRow]) -> None:
    """Serialize overlay rows to the JSON fixture file atomically."""
    sorted_rows = sorted(
        rows,
        key=lambda r: (r["parent_geometry_id"], r["child_geometry_id"], r["relationship"]),
    )
    MT_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = OVERLAY_FIXTURE_PATH.with_name(OVERLAY_FIXTURE_PATH.name + ".tmp")
    payload = json.dumps(sorted_rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(OVERLAY_FIXTURE_PATH)
    _logger.info("wrote %d overlay rows to %s", len(sorted_rows), OVERLAY_FIXTURE_PATH)


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args, open DB, collect overlay rows, write fixture."""
    parser = argparse.ArgumentParser(
        description="Build the Montana geometry overlay fixture for E03."
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Emit EXPLAIN ANALYZE plans for the spatial queries to stderr.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    with db.connect() as conn:
        rows = _collect_overlay_rows(conn, explain=args.explain)

    _write_fixture(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
