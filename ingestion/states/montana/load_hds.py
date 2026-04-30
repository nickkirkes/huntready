"""Montana hunting-district ingestion adapter.

Loads layers #3 (Antelope), #10 (Black Bear), #11 (Deer/Elk/Lion) from
MT FWP's `admbnd/huntingDistricts` MapServer into the `geometry` table.

All rows have kind='hunting_district' (NOT 'bmu' for layer #10 — see epic
S02.2 line 246: FWP's GIS authority calls these "Black Bear Hunting
Districts"; the regulation booklet's "Bear Management Unit" terminology is
a separate concern carried by jurisdiction_binding.role in E03).

IDs are species-prefixed to prevent cross-layer collisions (district 700
exists in multiple species layers as different polygons).

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/load_hds.py

Required env: DATABASE_URL.
Optional env: HUNTREADY_INGESTION_CONTACT (appended to ArcGIS User-Agent).
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import requests

from ingestion.lib import arcgis, db
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry


MT_FWP_HUNTING_DISTRICTS_URL = "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer"
MT_FIXTURE_DIR = Path(__file__).parent / "fixtures"
MT_LAYER_SLUG = "huntingDistricts"
MT_AGENCY = "Montana Fish, Wildlife & Parks"
MT_STATE_SLUG = "mt-fwp"
MT_STATE_CODE = "US-MT"


@dataclass(frozen=True)
class HDLayerConfig:
    layer_id: int
    species_slug: str
    id_prefix: str
    species_display: str  # for Geometry.name


HD_LAYERS: tuple[HDLayerConfig, ...] = (
    HDLayerConfig(3,  "antelope",      "MT-HD-antelope",      "Antelope"),
    HDLayerConfig(10, "bear",          "MT-HD-bear",          "Black Bear"),
    HDLayerConfig(11, "deer-elk-lion", "MT-HD-deer-elk-lion", "Deer/Elk/Lion"),
)


def _extract_district(props: dict[str, Any], metadata: LayerMetadata) -> str:
    value = props.get("DISTRICT")
    if value is not None:
        return str(value)
    msg = (
        f"layer {metadata.name!r} feature missing DISTRICT field; "
        f"available={list(metadata.out_fields)}"
    )
    raise ArcGISError(msg)


def _extract_verbatim_rule(props: dict[str, Any]) -> str | None:
    raw = props.get("REG")
    if raw is None:
        return None
    coerced = str(raw)
    if not coerced.strip():
        return None
    return coerced


def _extract_license_year(props: dict[str, Any]) -> int | None:
    raw = props.get("REGYEAR")
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        msg = f"REGYEAR {raw!r} is not a valid integer"
        raise ArcGISError(msg) from exc


def _feature_to_geometry(
    feature: dict[str, Any],
    layer_config: HDLayerConfig,
    layer_metadata: LayerMetadata,
    service_url: str,
    fetch_year: int,
) -> Geometry:
    props = feature["properties"]
    district = _extract_district(props, layer_metadata)
    geometry_wkt = arcgis.geojson_to_multipolygon_wkt(feature)
    license_year = _extract_license_year(props)
    # Citation license_year prefers per-feature REGYEAR ("which annual cycle is
    # this evidence from"); falls back to fetch_year only when source data
    # carries no REGYEAR. Geometry.license_year stays REGYEAR-or-NULL because
    # NULL is meaningful for year-invariant geometries (separate field, separate
    # contract). Per epic E02-geometry-ingestion.md:175-188.
    citation = arcgis.build_source_citation(
        service_url=service_url,
        layer_id=layer_config.layer_id,
        metadata=layer_metadata,
        license_year=license_year if license_year is not None else fetch_year,
        state_slug=MT_STATE_SLUG,
        agency=MT_AGENCY,
    )
    return Geometry(
        id=f"{layer_config.id_prefix}-{district}-geom",
        name=f"{layer_config.species_display} HD {district}",
        kind="hunting_district",
        geom=geometry_wkt,
        state=MT_STATE_CODE,
        license_year=license_year,
        verbatim_rule=_extract_verbatim_rule(props),
        source=citation,
    )


def _load_layer(
    conn: psycopg.Connection[Any],
    service_url: str,
    layer_config: HDLayerConfig,
    fixture_dir: Path,
    fetch_year: int,
    *,
    session: requests.Session | None = None,
) -> list[Geometry]:
    """Fetch metadata + features for one HD layer, normalize, and UPSERT.

    Returns the list of Geometry instances written (for caller-side spot-checking).
    """
    metadata = arcgis.fetch_layer_metadata(
        service_url,
        layer_config.layer_id,
        fixture_dir,
        layer_slug=MT_LAYER_SLUG,
        session=session,
    )
    features = arcgis.fetch_features(
        service_url,
        layer_config.layer_id,
        metadata,
        fixture_dir,
        layer_slug=MT_LAYER_SLUG,
        session=session,
    )
    geoms = [
        _feature_to_geometry(f, layer_config, metadata, service_url, fetch_year)
        for f in features
    ]
    db.upsert_geometries(conn, geoms)
    return geoms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-url", default=MT_FWP_HUNTING_DISTRICTS_URL)
    parser.add_argument("--fetch-year", type=int, default=datetime.now(timezone.utc).year)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger = logging.getLogger(__name__)

    MT_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    with arcgis._build_session() as session, db.connect() as conn:
        for layer_config in HD_LAYERS:
            logger.info("loading layer %d (%s)", layer_config.layer_id, layer_config.species_slug)
            geoms = _load_layer(
                conn, args.service_url, layer_config, MT_FIXTURE_DIR, args.fetch_year,
                session=session,
            )
            logger.info("layer %d: upserted %d geometries", layer_config.layer_id, len(geoms))
        conn.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
