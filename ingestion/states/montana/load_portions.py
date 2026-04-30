"""Montana portions ingestion adapter.

Loads layers #4 (Antelope Portions), #12 (Mule Deer Portions),
#13 (Whitetail Portions), #14 (Elk Portions) from MT FWP's
`admbnd/huntingDistricts` MapServer into the `geometry` table.

All rows have kind='portion'. IDs are species-prefixed and include the
parent DISTRICT plus a slug derived from SHAPECODE (preferred) or a
slugified PORTIONNAME (fallback).

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/load_portions.py

Required env: DATABASE_URL.
Optional env: HUNTREADY_INGESTION_CONTACT (appended to ArcGIS User-Agent).
"""

from __future__ import annotations

import argparse
import logging
import re
from collections import Counter
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
class PortionLayerConfig:
    layer_id: int
    species_slug: str
    id_prefix: str
    species_display: str  # for Geometry.name


PORTION_LAYERS: tuple[PortionLayerConfig, ...] = (
    PortionLayerConfig(4,  "antelope",  "MT-HD-antelope",  "Antelope"),
    PortionLayerConfig(12, "mule-deer", "MT-HD-mule-deer", "Mule Deer"),
    PortionLayerConfig(13, "whitetail", "MT-HD-whitetail", "Whitetail"),
    PortionLayerConfig(14, "elk",       "MT-HD-elk",       "Elk"),
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


def _slugify(text: str) -> str:
    """Lowercase + non-alphanumeric -> hyphen; strip leading/trailing hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        msg = f"cannot slugify empty/whitespace text: {text!r}"
        raise ArcGISError(msg)
    return slug


_SHAPECODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _extract_portion_slug(props: dict[str, Any], metadata: LayerMetadata) -> str:
    """Pick the per-portion identifier slug.

    Prefers SHAPECODE (verbatim — it's already a code) over slugified
    PORTIONNAME. SHAPECODE must match `[A-Za-z0-9_-]+` because it is
    embedded directly in hyphen-delimited geometry IDs; any other content
    (spaces, slashes, accents) raises ArcGISError to fail loudly rather
    than write a malformed ID. Raises ArcGISError if neither field yields
    a non-empty value.
    """
    shapecode = props.get("SHAPECODE")
    if shapecode is not None:
        coerced = str(shapecode)
        if coerced.strip():
            if not _SHAPECODE_PATTERN.fullmatch(coerced):
                msg = (
                    f"layer {metadata.name!r} feature SHAPECODE {coerced!r} "
                    f"contains characters outside [A-Za-z0-9_-]; "
                    f"refusing to embed in geometry id"
                )
                raise ArcGISError(msg)
            return coerced
    portion_name = props.get("PORTIONNAME")
    if portion_name is not None:
        coerced = str(portion_name)
        if coerced.strip():
            return _slugify(coerced)
    msg = (
        f"layer {metadata.name!r} feature missing both SHAPECODE and "
        f"PORTIONNAME; available={list(metadata.out_fields)}"
    )
    raise ArcGISError(msg)


def _feature_to_geometry(
    feature: dict[str, Any],
    layer_config: PortionLayerConfig,
    layer_metadata: LayerMetadata,
    service_url: str,
    fetch_year: int,
) -> Geometry:
    props = feature["properties"]
    district = _extract_district(props, layer_metadata)
    slug = _extract_portion_slug(props, layer_metadata)
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
        id=f"{layer_config.id_prefix}-{district}-portion-{slug}-geom",
        name=f"{layer_config.species_display} HD {district} portion {slug}",
        kind="portion",
        geom=geometry_wkt,
        state=MT_STATE_CODE,
        license_year=license_year,
        verbatim_rule=_extract_verbatim_rule(props),
        source=citation,
    )


def _load_layer(
    conn: psycopg.Connection[Any],
    service_url: str,
    layer_config: PortionLayerConfig,
    fixture_dir: Path,
    fetch_year: int,
    *,
    session: requests.Session | None = None,
) -> list[Geometry]:
    """Fetch metadata + features for one portion layer, normalize, and UPSERT.

    Returns the list of Geometry instances written (for caller-side spot-checking).
    Raises ArcGISError if normalized features produce duplicate geometry IDs
    (i.e. SHAPECODE/PORTIONNAME slugs collide within a layer).
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
    if not features:
        # Zero features is not an expected outcome for any V1 portion layer.
        # Most likely cause: server-side filter, projection mismatch, or wrong
        # OID field — surface loudly rather than silently writing nothing.
        logging.getLogger(__name__).warning(
            "layer %d (%s) returned zero features; skipping upsert",
            layer_config.layer_id, layer_config.species_slug,
        )
    geoms = [
        _feature_to_geometry(f, layer_config, metadata, service_url, fetch_year)
        for f in features
    ]
    ids = [g.id for g in geoms]
    if len(ids) != len(set(ids)):
        duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
        msg = (
            f"layer {layer_config.layer_id} ({layer_config.species_slug}) produced "
            f"{len(ids) - len(set(ids))} duplicate geometry id(s): {duplicates[:5]}"
            + (f" ... ({len(duplicates) - 5} more)" if len(duplicates) > 5 else "")
        )
        raise ArcGISError(msg)
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
        for layer_config in PORTION_LAYERS:
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
