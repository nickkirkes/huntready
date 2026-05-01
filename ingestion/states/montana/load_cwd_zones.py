"""Montana CWD management zone ingestion adapter (S02.5, Path A).

Loads the dedicated `ADMBND_HD_CWD` FeatureServer (a public MT FWP ArcGIS
Online layer) into the `geometry` table with kind='cwd_zone'.

Unlike S02.2-S02.4, this layer is not part of MT FWP's on-prem MapServer
(`fwp-gis.mt.gov`); it is hosted on services3.arcgis.com under the
MtFishWildlifeParks ArcGIS Online organization.

IDs are derived from AREANAME: `MT-CWD-zone-{areaname_slug}-geom`.

Investigation that selected this path is recorded in
ingestion/states/montana/cwd-source-discovery.md.

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/load_cwd_zones.py

Required env: DATABASE_URL.
Optional env: HUNTREADY_INGESTION_CONTACT (appended to ArcGIS User-Agent).
"""

from __future__ import annotations

import argparse
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg
import requests

from ingestion.lib import arcgis, db
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry


MT_FWP_CWD_FEATURESERVER_URL = (
    "https://services3.arcgis.com/Cdxz8r11hT0MGzg1/arcgis/rest/services"
    "/ADMBND_HD_CWD/FeatureServer"
)
MT_FWP_CWD_LAYER_ID = 0
MT_FIXTURE_DIR = Path(__file__).parent / "fixtures"
MT_LAYER_SLUG = "ADMBND_HD_CWD"
MT_AGENCY = "Montana Fish, Wildlife & Parks"
MT_STATE_SLUG = "mt-fwp"
MT_STATE_CODE = "US-MT"
ID_PREFIX = "MT-CWD-zone"


def _slugify(text: str) -> str:
    """Lowercase + non-alphanumeric -> hyphen; strip leading/trailing hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        msg = f"cannot slugify empty/whitespace text: {text!r}"
        raise ArcGISError(msg)
    return slug


def _extract_license_year(props: dict[str, Any]) -> int:
    """Parse REGYEAR (a string field, e.g. "2026") to int; raise ArcGISError if missing or unparseable."""
    raw = props.get("REGYEAR")
    if raw is None:
        msg = "REGYEAR field is missing from feature properties; cannot determine license year"
        raise ArcGISError(msg)
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        msg = f"REGYEAR {raw!r} is not a valid integer"
        raise ArcGISError(msg) from exc


def _extract_areaname(props: dict[str, Any], metadata: LayerMetadata) -> str:
    """Read AREANAME; raise ArcGISError if missing or empty/whitespace."""
    raw = props.get("AREANAME")
    if raw is not None:
        coerced = str(raw)
        if coerced.strip():
            return coerced
    msg = (
        f"layer {metadata.name!r} feature missing AREANAME; "
        f"available={list(metadata.out_fields)}"
    )
    raise ArcGISError(msg)


def _feature_to_geometry(
    feature: dict[str, Any],
    layer_metadata: LayerMetadata,
    service_url: str,
    layer_id: int,
) -> Geometry:
    props = feature["properties"]
    areaname = _extract_areaname(props, layer_metadata)
    slug = _slugify(areaname)
    geometry_wkt = arcgis.geojson_to_multipolygon_wkt(feature)
    license_year = _extract_license_year(props)
    citation = arcgis.build_source_citation(
        service_url=service_url,
        layer_id=layer_id,
        metadata=layer_metadata,
        license_year=license_year,
        state_slug=MT_STATE_SLUG,
        agency=MT_AGENCY,
    )
    return Geometry(
        id=f"{ID_PREFIX}-{slug}-geom",
        name=areaname,
        kind="cwd_zone",
        geom=geometry_wkt,
        state=MT_STATE_CODE,
        license_year=license_year,
        # verbatim_rule=None — this layer has no inline regulation text
        # (WEBPAGE is a URL, not regulation prose); per ADR-015, verbatim_rule
        # is for inline regulation text and is appropriately null here.
        verbatim_rule=None,
        source=citation,
    )


def _duplicate_ids(geoms: list[Geometry]) -> list[str]:
    counts = Counter(g.id for g in geoms)
    return sorted(i for i, n in counts.items() if n > 1)


def _load_layer(
    conn: psycopg.Connection[Any],
    service_url: str,
    layer_id: int,
    fixture_dir: Path,
    *,
    session: requests.Session | None = None,
) -> list[Geometry]:
    logger = logging.getLogger(__name__)
    metadata = arcgis.fetch_layer_metadata(
        service_url,
        layer_id,
        fixture_dir,
        layer_slug=MT_LAYER_SLUG,
        session=session,
    )
    features = arcgis.fetch_features(
        service_url,
        layer_id,
        metadata,
        fixture_dir,
        layer_slug=MT_LAYER_SLUG,
        session=session,
    )
    if not features:
        msg = (
            f"layer {layer_id} ({MT_LAYER_SLUG}) returned zero features; "
            f"refusing to record an empty load."
        )
        raise ArcGISError(msg)

    logger.info(
        "layer %d (%s): %d feature(s) fetched",
        layer_id,
        MT_LAYER_SLUG,
        len(features),
    )

    geoms = [
        _feature_to_geometry(f, metadata, service_url, layer_id)
        for f in features
    ]
    dupes = _duplicate_ids(geoms)
    if dupes:
        msg = (
            f"layer {layer_id} ({MT_LAYER_SLUG}) produced duplicate geometry "
            f"id(s): {dupes[:5]}"
            + (f" ... ({len(dupes) - 5} more)" if len(dupes) > 5 else "")
        )
        raise ArcGISError(msg)

    db.upsert_geometries(conn, geoms)
    return geoms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-url", default=MT_FWP_CWD_FEATURESERVER_URL)
    parser.add_argument("--layer-id", type=int, default=MT_FWP_CWD_LAYER_ID)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    MT_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    with arcgis._build_session() as session, db.connect() as conn:
        geoms = _load_layer(
            conn,
            args.service_url,
            args.layer_id,
            MT_FIXTURE_DIR,
            session=session,
        )
        logger.info("upserted %d CWD zone geometries", len(geoms))
        # Single atomic commit covering the CWD zone layer. If `_load_layer`
        # raises, this commit is skipped and the connection's `__exit__`
        # rolls back the transaction.
        conn.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
