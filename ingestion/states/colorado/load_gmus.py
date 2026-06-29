"""Colorado GMU ingestion adapter.

Loads CPW Big Game Game Management Units (GMUs) from the CPWAdminData
FeatureServer layer 6 (~186 polygons) into the ``geometry`` table with
``kind='gmu'`` (``'hunting_district'`` is MT-specific; CO uses ``'gmu'``).

ADR lineage:
    ADR-001 — authority preserved, not replaced (fail-loud on missing/bad data)
    ADR-005 — state isolation; no lib/ edits; shared code via ingestion.lib only
    ADR-010 — all geometries stored as MultiPolygon/geography(MultiPolygon, 4326)
    ADR-014 — SourceCitation.document_type='gis_layer'; publication_date
              REGYEAR-anchored (Jan 1 of the fetch year), NOT the server's
              EDIT_DATE or INPUT_DATE timestamps

Provenance note:
    CPW FeatureServer layer 6 carries per-feature ``EDIT_DATE`` and
    ``INPUT_DATE`` attributes.  These are logged at INFO level for operator
    forensics only and are deliberately NOT written to the geometry row (the
    run log is the forensic record of record, since they cannot be persisted).
    ``SourceCitation`` is a frozen Pydantic model with ``extra="forbid"``, so
    no forensic field can be added without a schema change.  Per ADR-014,
    ``publication_date`` is anchored to REGYEAR (Jan 1 of _FETCH_YEAR), not
    server edit timestamps.

Run from the repo root (direct path, NOT python -m — see known-pitfalls.md
"state-adapter scripts must be invoked as python <path> not python -m"):
    ingestion/.venv/bin/python ingestion/states/colorado/load_gmus.py

Required env: DATABASE_URL.
Optional env: HUNTREADY_INGESTION_CONTACT (appended to ArcGIS User-Agent as
    "(contact: <value>)").
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Final

import psycopg
import requests
from shapely import wkt

from ingestion.lib import arcgis, db
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry

# ---------------------------------------------------------------------------
# Service coordinates
# ---------------------------------------------------------------------------

CPW_SERVICE_URL = (
    "https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services"
    "/CPWAdminData/FeatureServer"
)
CPW_GMU_LAYER_ID = 6

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

CO_FIXTURE_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Identity / citation constants
# ---------------------------------------------------------------------------

CO_LAYER_SLUG = "CPWAdminData"
CO_AGENCY = "Colorado Parks and Wildlife"
CO_STATE_SLUG = "co-cpw"
_STATE: Final[str] = "US-CO"
CO_GMU_ID_PREFIX = "CO-GMU"

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

MULTIPART_FIXTURE_PATH = CO_FIXTURE_DIR / "multipart-gmus.json"

# ---------------------------------------------------------------------------
# Ingestion parameters
# ---------------------------------------------------------------------------

# CPW layer 6 carries no per-feature REGYEAR attribute; default to the current
# operational year.  Update when the layer transitions to a new regulation year.
_FETCH_YEAR = 2026

# Guard band: 186 features ±10% per spec.
# Fires pre-db.connect() per OQ7 discipline — no partial writes on count drift.
_GMU_COUNT_GUARD_BAND = (167, 205)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ColoradoGeometryError(Exception):
    """Wraps a per-feature geometry failure with GMUID context for operator diagnosis."""


# ---------------------------------------------------------------------------
# Pure attribute extractors
# ---------------------------------------------------------------------------


def _extract_gmuid(props: dict[str, Any], metadata: LayerMetadata) -> str:
    """Return the GMUID string value from a feature's properties dict.

    Raises ColoradoGeometryError if the GMUID field is absent.
    """
    value = props.get("GMUID")
    if value is None:
        msg = (
            f"feature missing GMUID field; "
            f"available={list(metadata.out_fields)}"
        )
        raise ColoradoGeometryError(msg)
    return str(value)  # source value is int; coerce for id formatting


def _extract_county(props: dict[str, Any]) -> str | None:
    """Return the COUNTY string from a feature's properties, or None if absent/blank."""
    raw = props.get("COUNTY")
    if raw is None:
        return None
    coerced = str(raw).strip()
    return coerced if coerced else None


# ---------------------------------------------------------------------------
# Per-feature normalization
# ---------------------------------------------------------------------------


def _feature_to_geometry(
    feature: dict[str, Any],
    layer_metadata: LayerMetadata,
    service_url: str,
    fetch_year: int,
    *,
    logger: logging.Logger,
) -> Geometry:
    """Convert one GeoJSON feature into a Geometry instance.

    Raises ColoradoGeometryError if 'properties' is missing/non-dict, the GMUID
    field is missing, or the geometry cannot be coerced to MultiPolygon.
    """
    props = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(props, dict):
        raise ColoradoGeometryError(
            f"feature has missing or non-dict 'properties' "
            f"(got {type(props).__name__}); "
            f"feature keys={sorted(feature) if isinstance(feature, dict) else type(feature).__name__}"
        )
    gmuid = _extract_gmuid(props, layer_metadata)

    try:
        geometry_wkt = arcgis.geojson_to_multipolygon_wkt(feature)
    except ArcGISError as exc:
        msg = f"GMU {gmuid}: geometry could not be coerced to MultiPolygon ({exc})"
        raise ColoradoGeometryError(msg) from exc

    # EDIT_DATE / INPUT_DATE are logged for forensics only and are NOT persisted
    # to the geometry row — SourceCitation is frozen with extra="forbid", and
    # ADR-014 anchors publication_date to REGYEAR, not server edit timestamps.
    if props.get("EDIT_DATE") is not None or props.get("INPUT_DATE") is not None:
        logger.info(
            "GMU %s provenance: EDIT_DATE=%s INPUT_DATE=%s",
            gmuid,
            props.get("EDIT_DATE"),
            props.get("INPUT_DATE"),
        )

    county = _extract_county(props)
    name = f"GMU {gmuid} ({county})" if county else f"GMU {gmuid}"

    citation = arcgis.build_source_citation(
        service_url=service_url,
        layer_id=CPW_GMU_LAYER_ID,
        metadata=layer_metadata,
        license_year=fetch_year,
        state_slug=CO_STATE_SLUG,
        agency=CO_AGENCY,
    )

    return Geometry(
        id=f"{CO_GMU_ID_PREFIX}-{gmuid}-geom",
        name=name,
        kind="gmu",
        geom=geometry_wkt,
        state=_STATE,
        license_year=None,
        source=citation,
    )


# ---------------------------------------------------------------------------
# Pre-connect guards  (fire before db.connect() per OQ7 discipline)
# ---------------------------------------------------------------------------


def _duplicate_ids(geoms: list[Geometry]) -> list[str]:
    """Return geometry ids that appear more than once, in first-seen order.

    Each duplicate id is reported exactly once.  An empty list means no
    duplicates were detected.
    """
    counts: Counter[str] = Counter(g.id for g in geoms)
    seen: set[str] = set()
    dupes: list[str] = []
    for g in geoms:
        if counts[g.id] > 1 and g.id not in seen:
            dupes.append(g.id)
            seen.add(g.id)
    return dupes


def _check_count_band(n: int) -> None:
    """Raise RuntimeError if ``n`` is outside ``_GMU_COUNT_GUARD_BAND``.

    Fires pre-db.connect() per OQ7 discipline — no partial writes on count
    drift.  Cross-check the observed count against the layer's
    ``returnCountOnly=true`` query if this guard fires unexpectedly.
    """
    lo, hi = _GMU_COUNT_GUARD_BAND
    if not (lo <= n <= hi):
        msg = (
            f"GMU count {n} outside guard band {_GMU_COUNT_GUARD_BAND}; "
            f"cross-check against returnCountOnly=true on layer "
            f"{CPW_GMU_LAYER_ID} before re-running"
        )
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Multipart-GMU analytics  (fixture writer for S05.7)
# ---------------------------------------------------------------------------


def _collect_multipart_gmus(geoms: list[Geometry]) -> list[dict[str, Any]]:
    """Return fixture rows for every GMU whose geometry has more than one part.

    Each row contains:
        ``gmuid``          — integer GMU id (derived from the geometry id)
        ``part_count``     — number of polygon parts
        ``total_area_sq_km`` — always None (see note below)

    Note on ``total_area_sq_km``: planar WKT area is in squared degrees and
    cannot yield a faithful km² value.  The authoritative area is computed by
    S05.7's post-load PostGIS analytical layer via
    ``ST_Area(geom::geography)/1e6``.  The key is kept present (value None)
    so the fixture schema matches the spec's field list; a planar approximation
    is deliberately not fabricated here.

    Returned list is sorted by ``gmuid`` ascending.
    """
    rows: list[dict[str, Any]] = []
    for g in geoms:
        try:
            geom_obj = wkt.loads(g.geom)
        except Exception as exc:  # noqa: BLE001 — re-raised with id context below
            msg = f"geometry {g.id!r}: WKT could not be parsed ({exc})"
            raise ColoradoGeometryError(msg) from exc
        raw_geoms = getattr(geom_obj, "geoms", None)
        part_count = len(raw_geoms) if raw_geoms is not None else 1

        if part_count <= 1:
            continue

        # Derive integer gmuid from the geometry id: CO-GMU-{gmuid}-geom
        mid = g.id.removeprefix(f"{CO_GMU_ID_PREFIX}-").removesuffix("-geom")
        try:
            gmuid = int(mid)
        except ValueError as exc:
            msg = (
                f"geometry {g.id!r}: GMUID segment {mid!r} is not an integer; "
                "expected id shape CO-GMU-{GMUID}-geom"
            )
            raise ColoradoGeometryError(msg) from exc

        rows.append(
            {
                "gmuid": gmuid,
                "part_count": part_count,
                # planar WKT area is in squared degrees — not faithful km²;
                # authoritative ST_Area(geom::geography)/1e6 computed by S05.7
                "total_area_sq_km": None,
            }
        )

    rows.sort(key=lambda r: r["gmuid"])
    return rows


def _write_multipart_fixture(rows: list[dict[str, Any]], path: Path) -> None:
    """Write ``rows`` as deterministic JSON to ``path``, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Fetch + build  (network + normalization; no DB connection)
# ---------------------------------------------------------------------------


def _fetch_and_build(
    service_url: str,
    fixture_dir: Path,
    fetch_year: int,
    *,
    session: requests.Session | None = None,
    logger: logging.Logger,
) -> list[Geometry]:
    """Fetch CPW GMU features and normalise each into a Geometry instance.

    Performs only network I/O and pure data transformation — no DB connection
    is opened here.  Guards in ``main()`` fire on the returned list before
    ``db.connect()`` is ever called.
    """
    metadata = arcgis.fetch_layer_metadata(
        service_url,
        CPW_GMU_LAYER_ID,
        fixture_dir,
        layer_slug=CO_LAYER_SLUG,
        session=session,
    )
    features = arcgis.fetch_features(
        service_url,
        CPW_GMU_LAYER_ID,
        metadata,
        fixture_dir,
        layer_slug=CO_LAYER_SLUG,
        session=session,
    )
    geoms = [
        _feature_to_geometry(f, metadata, service_url, fetch_year, logger=logger)
        for f in features
    ]
    return geoms


# ---------------------------------------------------------------------------
# DB write  (called only after all pre-connect guards pass)
# ---------------------------------------------------------------------------


def _write_geometries(
    conn: psycopg.Connection[tuple[object, ...]], geoms: list[Geometry]
) -> None:
    """Upsert ``geoms`` into the geometry table via the shared db helper.

    The count-band + duplicate-id guards run in ``main()`` before this is ever
    reached; the caller owns the commit.
    """
    db.upsert_geometries(conn, geoms)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-year", type=int, default=_FETCH_YEAR)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    CO_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch + build before db.connect() — guards fire on the returned list.
    with arcgis._build_session() as session:
        geoms = _fetch_and_build(
            CPW_SERVICE_URL,
            CO_FIXTURE_DIR,
            args.fetch_year,
            session=session,
            logger=logger,
        )

    # Pre-connect guards (OQ7 discipline — no partial writes on bad data).
    dupes = _duplicate_ids(geoms)
    if dupes:
        raise RuntimeError(
            f"duplicate geometry ids ({len(dupes)}): {dupes[:5]}"
        )
    _check_count_band(len(geoms))

    # Multipart fixture written pre-connect so it is available even on DB failure.
    multipart = _collect_multipart_gmus(geoms)
    _write_multipart_fixture(multipart, MULTIPART_FIXTURE_PATH)
    logger.info("multi-part GMUs: %d", len(multipart))
    for row in multipart:
        logger.info("multi-part GMU %s: %d parts", row["gmuid"], row["part_count"])

    # DB write phase.
    with db.connect() as conn:
        _write_geometries(conn, geoms)
        conn.commit()

    logger.info("upserted %d GMU geometries", len(geoms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
