"""Montana state boundary ingestion adapter.

Loads the Montana state boundary from the Montana State Library MSDI Framework
(Layer 9 of the Boundaries MapServer) into the ``geometry`` table as a single
row with ``kind='state'`` (per ADR-018 §3).

The source is a live MapServer query endpoint — not a versioned file — so the
SHA-256 is pinned against a known-good response. If the Montana State Library
updates the layer, the hash will drift; this script will fail loud rather than
silently commit a changed geometry.

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/load_state_boundary.py

Required env: DATABASE_URL.
Optional env: HUNTREADY_INGESTION_CONTACT (appended to ArcGIS User-Agent).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from typing import Literal

import requests

from ingestion.lib import arcgis, db
from ingestion.lib.schema import Geometry, SourceCitation


# ---------------------------------------------------------------------------
# Pinned source values (from T7 investigation — do not change without re-pinning
# the SHA and updating docs/planning/epics/E03-confidence-findings/S03.0.md).
# ---------------------------------------------------------------------------

STATE_BOUNDARY_URL = (
    "https://gisservicemt.gov/arcgis/rest/services/MSDI_Framework/Boundaries"
    "/MapServer/9/query?where=1%3D1&outFields=*&f=geojson&outSR=4326"
)
STATE_BOUNDARY_SHA256 = "d90b40c8f290e8fbcd83c30e89c4edf645adb73f2a3e367b29b8637ee6f79d34"
STATE_BOUNDARY_PUBLICATION_DATE = "2026-01-01"
STATE_BOUNDARY_DOCUMENT_TYPE: Literal["gis_layer"] = "gis_layer"
STATE_BOUNDARY_AGENCY = "Montana State Library"
STATE_BOUNDARY_TITLE = "Montana State Boundary (MSDI Framework, Layer 9)"

MT_STATE_CODE = "US-MT"
GEOMETRY_ID = "MT-STATEWIDE-geom"
GEOMETRY_NAME = "Montana"
SOURCE_CITATION_ID = "mt-msdi-framework-boundaries-9-2026"


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
    User-Agent convention is applied uniformly to all GIS sources, including
    this non-FWP endpoint.  If an open session is supplied (e.g., from a
    test), it is used directly.
    """
    if session is None:
        with arcgis._build_session() as built_session:
            response = built_session.get(url, timeout=60)
            response.raise_for_status()
            return response.content
    else:
        response = session.get(url, timeout=60)
        response.raise_for_status()
        return response.content


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
            f"SHA-256 mismatch for Montana state boundary source.\n"
            f"  expected: {expected}\n"
            f"  observed: {observed}\n"
            "The Montana State Library may have updated layer 9. "
            "Re-investigate, re-pin STATE_BOUNDARY_SHA256, and update "
            "docs/planning/epics/E03-confidence-findings/S03.0.md before proceeding."
        )
        raise RuntimeError(msg)
    return observed


def _parse_to_multipolygon_wkt(payload: bytes) -> str:
    """Parse a GeoJSON FeatureCollection payload and return canonical MultiPolygon WKT.

    Expects exactly one Feature in the collection.  Raises if zero or more
    than one Feature is present (fail loud — the source should be a single
    Montana state boundary polygon).

    Delegates geometry repair (``shapely.make_valid``) and Polygon →
    MultiPolygon coercion to ``arcgis.geojson_to_multipolygon_wkt``.
    """
    data = json.loads(payload)

    # ArcGIS / MapServer error envelopes come back with HTTP 200 and shape
    # `{"error": {"code": ..., "message": ..., "details": [...]}}`. Detect
    # before inspecting `features` — otherwise the operator gets a misleading
    # "zero features" diagnostic when the real cause is a server-side error.
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code", "?")
        message = error.get("message", "<no message>")
        msg = (
            f"Montana state boundary source returned an ArcGIS error envelope "
            f"(code={code}): {message}. "
            f"Check the source URL and the MSDI Framework layer status."
        )
        raise RuntimeError(msg)

    features = data.get("features", [])

    if len(features) == 0:
        msg = (
            "Montana state boundary response contained zero features. "
            "Expected exactly one Feature representing the state polygon."
        )
        raise RuntimeError(msg)

    if len(features) > 1:
        msg = (
            f"Montana state boundary response contained {len(features)} features; "
            "expected exactly one. Source may have changed structure."
        )
        raise RuntimeError(msg)

    feature = features[0]
    return arcgis.geojson_to_multipolygon_wkt(feature)


def _build_source_citation() -> SourceCitation:
    """Construct the ``SourceCitation`` for the MSDI Framework state boundary.

    Does NOT delegate to ``arcgis.build_source_citation`` — that helper is
    hardcoded to the ArcGIS service-URL slug pattern and ``layer_id`` parameter
    which don't fit cleanly for this cross-host MSDI source.
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
    """Fetch, verify, parse, and write the Montana state geometry row."""
    parser = argparse.ArgumentParser(
        description=(
            "Load the Montana state boundary into the geometry table. "
            "Writes one row: id='MT-STATEWIDE-geom', kind='state'. "
            "Verifies SHA-256 of the source before writing — fails loud on mismatch."
        )
    )
    parser.add_argument(
        "--service-url",
        default=STATE_BOUNDARY_URL,
        help="Override the MSDI Framework query URL (for testing).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("fetching Montana state boundary from %s", args.service_url)
    payload = _fetch_source_bytes(args.service_url)

    logger.info("verifying SHA-256 against pinned value")
    observed_sha = _verify_sha256(payload, STATE_BOUNDARY_SHA256)
    logger.info("SHA-256 verified: %s", observed_sha)

    logger.info("parsing GeoJSON to MultiPolygon WKT")
    wkt = _parse_to_multipolygon_wkt(payload)

    citation = _build_source_citation()

    geom = Geometry(
        id=GEOMETRY_ID,
        name=GEOMETRY_NAME,
        kind="state",
        geom=wkt,
        state=MT_STATE_CODE,
        license_year=None,        # year-invariant per ADR-018 §3
        verbatim_rule=None,
        legal_description=None,   # state-level boundary; no FWP prose for state shape
        source=citation,
    )

    with db.connect() as conn:
        db.upsert_geometry(conn, geom)
        # Single atomic commit — one row, one boundary, all-or-nothing.
        conn.commit()

    logger.info("loaded geometry id=%s name=%r", GEOMETRY_ID, GEOMETRY_NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
