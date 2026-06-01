"""Colorado state boundary ingestion adapter.

Loads the Colorado state boundary from the US Census TIGER/Line 2024 nationwide
state shapefile (filtered to STATEFP=08) into the ``geometry`` table as a single
row with ``kind='state'`` (per ADR-018 §3).

The source is a versioned Census ZIP release, so the SHA-256 is pinned against
the known-good 2024 file.  If the US Census updates the file at this URL the
hash will drift; this script will fail loud rather than silently commit a
changed geometry.  Re-download, verify manually, and update
``STATE_BOUNDARY_SHA256`` before re-running.

ADR lineage:
    ADR-001 — authority preserved, not replaced (SHA-256 fail-loud)
    ADR-014 — SourceCitation.document_type='gis_layer'
    ADR-018 — geometry.kind='state' value

Run from the repo root (direct path, NOT python -m — see known-pitfalls.md
"state-adapter scripts must be invoked as python <path> not python -m"):
    ingestion/.venv/bin/python ingestion/states/colorado/load_state_boundary.py

Required env: DATABASE_URL.
Optional env: HUNTREADY_INGESTION_CONTACT (appended to User-Agent as
    "(contact: <value>)").

Transaction discipline:
    The explicit ``conn.commit()`` inside ``main()`` is the real write gate.
    The ``with db.connect() as conn:`` context manager commits on clean exit
    as a safety net, but the explicit commit is intentional and documents the
    atomic write boundary clearly.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import logging
import pathlib
import tempfile
import zipfile
from typing import Literal

import geopandas  # type: ignore[import-untyped]  # no stubs package published
import requests
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon

from ingestion.lib import arcgis, db
from ingestion.lib.schema import Geometry, SourceCitation


# ---------------------------------------------------------------------------
# Pinned source values
# SHA-256 pinned from the live file fetched 2026-06-01.
# Re-pin if the Census Bureau updates the file at this URL.
# ---------------------------------------------------------------------------

STATE_BOUNDARY_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip"
)
STATE_BOUNDARY_SHA256 = (
    "ad00cbe66c7177091b668cee202e93d4a1ddcee271c28d1c9f9874af59c04b92"
)
STATE_BOUNDARY_PUBLICATION_DATE = "2026-01-01"
STATE_BOUNDARY_DOCUMENT_TYPE: Literal["gis_layer"] = "gis_layer"
STATE_BOUNDARY_AGENCY = "US Census Bureau"
STATE_BOUNDARY_TITLE = (
    "TIGER/Line State Shapefile 2024 (filtered to Colorado, STATEFP=08)"
)

CO_STATE_CODE = "US-CO"
CO_STATEFP = "08"
GEOMETRY_ID = "CO-STATEWIDE-geom"
GEOMETRY_NAME = "Colorado"
SOURCE_CITATION_ID = "co-census-tiger-state-2024"


# ---------------------------------------------------------------------------
# Pure functions — each independently testable
# ---------------------------------------------------------------------------


def _fetch_source_bytes(
    url: str,
    *,
    session: requests.Session | None = None,
) -> bytes:
    """GET ``url`` and return the raw response bytes.

    Uses ``arcgis._build_session()`` so the ``HUNTREADY_INGESTION_CONTACT``
    User-Agent convention is applied uniformly to all GIS sources.  If an
    open session is supplied (e.g., from a test), it is used directly.

    Raises ``RuntimeError`` (wrapping ``requests.RequestException``) on any
    network or HTTP error, naming the URL in the message.
    """
    try:
        if session is None:
            with arcgis._build_session() as built_session:
                response = built_session.get(url, timeout=60)
                response.raise_for_status()
                payload = response.content
        else:
            response = session.get(url, timeout=60)
            response.raise_for_status()
            payload = response.content
    except requests.RequestException as exc:
        msg = (
            f"Failed to fetch Colorado state boundary source from {url!r}: {exc}"
        )
        raise RuntimeError(msg) from exc

    if not payload:
        raise RuntimeError(
            f"Empty response body from {url!r}. Expected a TIGER/Line ZIP archive "
            "(~10MB). Check CDN availability or upstream Census Bureau status."
        )
    return payload


def _verify_sha256(payload: bytes, expected: str) -> str:
    """Raise ``RuntimeError`` if SHA-256 of ``payload`` does not match ``expected``.

    Fails loud — callers must not proceed if the hash drifts.  The error
    message includes both the observed and expected digests so operators can
    decide whether to re-pin or investigate upstream changes.

    Returns the observed digest on success so the caller can log it without
    re-hashing the payload.
    """
    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected:
        msg = (
            f"SHA-256 mismatch for Colorado state boundary source.\n"
            f"  expected: {expected}\n"
            f"  observed: {observed}\n"
            "The US Census Bureau may have updated the TIGER/Line file at this URL. "
            "Re-investigate the source URL, re-pin STATE_BOUNDARY_SHA256 in this file, "
            "and record the change in the S05.0 closure note before proceeding."
        )
        raise RuntimeError(msg)
    return observed


def _parse_to_multipolygon_wkt(payload: bytes) -> str:
    """Parse a TIGER/Line ZIP payload and return canonical MultiPolygon WKT.

    Steps:
      1. Open ``payload`` as a ZIP in memory.
      2. Extract all sidecar files (.shp/.shx/.dbf/.prj etc.) to a temp dir.
      3. Read the .shp via geopandas.
      4. Reproject to EPSG:4326 (TIGER ships in NAD83; WGS84 for Postgres).
      5. Filter to STATEFP == CO_STATEFP; assert exactly one row.
      6. Run shapely.make_valid; coerce Polygon → MultiPolygon.
      7. Return .wkt.

    Raises ``RuntimeError`` on ZIP parse errors, missing .shp file, wrong
    STATEFP count, or invalid geometry type.

    Note on reprojection: ``geopandas.GeoDataFrame.to_crs(4326)`` returns a
    NEW GeoDataFrame; it does NOT mutate in place.  The result MUST be
    reassigned to ``gdf``.  A bare ``gdf.to_crs(4326)`` would silently
    discard the reprojection, leaving NAD83 coordinates mis-interpreted as
    WGS84 by Postgres (systematic ~100m offset).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf, tempfile.TemporaryDirectory() as tmpdir:
            zf.extractall(tmpdir)
            namelist = zf.namelist()

            shp_candidates = list(pathlib.Path(tmpdir).glob("*.shp"))
            if not shp_candidates:
                msg = (
                    "TIGER ZIP missing .shp file — cannot read shapefile. "
                    f"ZIP contents: {namelist!r}"
                )
                raise RuntimeError(msg)
            if len(shp_candidates) > 1:
                msg = (
                    f"TIGER ZIP contains {len(shp_candidates)} .shp files; "
                    "expected exactly 1. Source structure may have changed. "
                    f"Candidates: {[p.name for p in shp_candidates]!r}"
                )
                raise RuntimeError(msg)
            shp_path = shp_candidates[0]

            gdf = geopandas.read_file(shp_path)

            if "STATEFP" not in gdf.columns:
                msg = (
                    f"TIGER shapefile missing STATEFP column. "
                    f"Available columns: {list(gdf.columns)!r}. "
                    f"Source: {STATE_BOUNDARY_URL!r}. "
                    "Schema may have drifted (future TIGER vintages may rename)."
                )
                raise RuntimeError(msg)

            # Reproject: TIGER 2024 ships in NAD83 (EPSG:4269); Postgres expects
            # WGS84 (EPSG:4326).  Reassignment is mandatory — to_crs() returns a
            # new GeoDataFrame and does NOT mutate gdf in place.
            gdf = gdf.to_crs(4326)

            colorado = gdf[gdf["STATEFP"] == CO_STATEFP]
            count = len(colorado)
            if count == 0:
                msg = (
                    f"No rows matched STATEFP == {CO_STATEFP!r} in TIGER shapefile. "
                    "The shapefile may be filtered or use a different column name."
                )
                raise RuntimeError(msg)
            if count > 1:
                msg = (
                    f"Expected exactly 1 row for STATEFP == {CO_STATEFP!r}, "
                    f"found {count}. Source structure may have changed."
                )
                raise RuntimeError(msg)

            geom = colorado.iloc[0].geometry
            if geom is None:
                msg = (
                    f"Colorado row (STATEFP == {CO_STATEFP!r}) has NULL geometry "
                    f"in TIGER shapefile. Source: {STATE_BOUNDARY_URL!r}."
                )
                raise RuntimeError(msg)
            geom = make_valid(geom)
    except zipfile.BadZipFile as exc:
        msg = (
            f"Colorado state boundary source is not a valid ZIP archive "
            f"(fetched from {STATE_BOUNDARY_URL!r}): {exc}"
        )
        raise RuntimeError(msg) from exc

    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])

    if not isinstance(geom, MultiPolygon):
        msg = (
            f"Colorado state boundary geometry is not a Polygon or MultiPolygon "
            f"after make_valid(); got {type(geom).__name__}."
        )
        raise RuntimeError(msg)

    return geom.wkt


def _build_source_citation() -> SourceCitation:
    """Construct the ``SourceCitation`` for the TIGER/Line state boundary.

    Does NOT delegate to ``arcgis.build_source_citation`` — that helper
    is hardcoded to the ArcGIS service-URL slug pattern and ``layer_id``
    parameter, which do not fit the Census TIGER download URL.
    """
    return SourceCitation(
        id=SOURCE_CITATION_ID,
        agency=STATE_BOUNDARY_AGENCY,
        title=STATE_BOUNDARY_TITLE,
        url=STATE_BOUNDARY_URL,
        publication_date=STATE_BOUNDARY_PUBLICATION_DATE,
        document_type=STATE_BOUNDARY_DOCUMENT_TYPE,
        supersedes=None,
        page_reference=None,
    )


def main(argv: list[str] | None = None) -> int:
    """Fetch, verify, parse, and write the Colorado state geometry row."""
    parser = argparse.ArgumentParser(
        description=(
            "Load the Colorado state boundary into the geometry table. "
            "Writes one row: id='CO-STATEWIDE-geom', kind='state'. "
            "Verifies SHA-256 of the source before writing — fails loud on mismatch."
        )
    )
    parser.add_argument(
        "--service-url",
        default=STATE_BOUNDARY_URL,
        help="Override the TIGER ZIP URL (for testing).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("fetching Colorado state boundary from %s", args.service_url)
    payload = _fetch_source_bytes(args.service_url)

    logger.info("verifying SHA-256 against pinned value")
    observed_sha = _verify_sha256(payload, STATE_BOUNDARY_SHA256)
    logger.info("SHA-256 verified: %s", observed_sha)

    logger.info("parsing TIGER ZIP to MultiPolygon WKT")
    wkt = _parse_to_multipolygon_wkt(payload)

    citation = _build_source_citation()

    geom = Geometry(
        id=GEOMETRY_ID,
        name=GEOMETRY_NAME,
        kind="state",
        geom=wkt,
        state=CO_STATE_CODE,
        license_year=None,       # year-invariant per ADR-018 §3
        verbatim_rule=None,
        legal_description=None,  # state-level boundary; no agency prose for state shape
        source=citation,
    )

    with db.connect() as conn:
        db.upsert_geometry(conn, geom)
        # Single atomic commit — one row, one boundary, all-or-nothing.
        # The explicit conn.commit() is the real write gate; the context-manager
        # commit-on-exit is a safety net only.
        conn.commit()

    logger.info("wrote CO-STATEWIDE-geom (sha256=%s)", observed_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
