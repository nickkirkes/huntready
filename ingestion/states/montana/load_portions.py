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
from typing import Any, Literal

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

# Slug strategy is chosen per-layer by `_load_layer`, not per-feature, because
# SHAPECODE collisions are layer-wide data realities (e.g. MT FWP layer #12
# uses `mdPt312` for both East and West halves of district 312). The whole
# layer must use the same field so feature IDs in a layer are uniformly
# formatted; per-feature mixing would produce a confusing mosaic of slug
# styles. Per spec line 308: "Fail loudly if neither SHAPECODE nor unique
# PORTIONNAME yields collision-free IDs within a layer."
SlugStrategy = Literal["shapecode", "portionname"]


def _extract_portion_slug(
    props: dict[str, Any],
    metadata: LayerMetadata,
    *,
    strategy: SlugStrategy,
) -> str:
    """Pick the per-portion identifier slug under the chosen layer strategy.

    `strategy="shapecode"`: use SHAPECODE verbatim (it's a code, not free text).
    SHAPECODE must match `[A-Za-z0-9_-]+` because it is embedded directly in
    hyphen-delimited geometry IDs; any other content raises ArcGISError. Falls
    back to slugified PORTIONNAME if SHAPECODE is missing/empty on a single
    feature (rare; occurs in mixed layers). Raises if both are absent.

    `strategy="portionname"`: use slugified PORTIONNAME directly. SHAPECODE is
    ignored. Raises if PORTIONNAME is missing/empty.
    """
    if strategy == "shapecode":
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
    # strategy == "portionname"
    portion_name = props.get("PORTIONNAME")
    if portion_name is not None:
        coerced = str(portion_name)
        if coerced.strip():
            return _slugify(coerced)
    msg = (
        f"layer {metadata.name!r} feature missing PORTIONNAME under "
        f"portionname strategy; available={list(metadata.out_fields)}"
    )
    raise ArcGISError(msg)


def _feature_to_geometry(
    feature: dict[str, Any],
    layer_config: PortionLayerConfig,
    layer_metadata: LayerMetadata,
    service_url: str,
    fetch_year: int,
    *,
    slug_strategy: SlugStrategy,
) -> Geometry:
    props = feature["properties"]
    district = _extract_district(props, layer_metadata)
    slug = _extract_portion_slug(props, layer_metadata, strategy=slug_strategy)
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


def _build_geoms(
    features: list[dict[str, Any]],
    layer_config: PortionLayerConfig,
    metadata: LayerMetadata,
    service_url: str,
    fetch_year: int,
    *,
    slug_strategy: SlugStrategy,
) -> list[Geometry]:
    return [
        _feature_to_geometry(
            f, layer_config, metadata, service_url, fetch_year,
            slug_strategy=slug_strategy,
        )
        for f in features
    ]


def _duplicate_ids(geoms: list[Geometry]) -> list[str]:
    counts = Counter(g.id for g in geoms)
    return sorted(i for i, n in counts.items() if n > 1)


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

    Slug strategy is chosen per-layer: try SHAPECODE first; if that produces
    duplicate IDs within the layer (a real MT FWP data condition — e.g.
    layer #12 mule-deer reuses `mdPt312` for two distinct district-312
    polygons), fall back to slugified PORTIONNAME for the whole layer. Raise
    ArcGISError only if BOTH strategies collide. Per spec line 308.

    Returns the list of Geometry instances written (for caller-side spot-checking).
    """
    logger = logging.getLogger(__name__)
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
        # Zero features is not an expected outcome for any V1 portion layer
        # (live load 2026-04-30 confirmed 4/11/13/27 features for #4/#12/#13/#14).
        # Most likely cause: server-side filter, projection mismatch, wrong OID
        # field, or upstream layer renumbering. Fail loud rather than write
        # nothing and have the operator miss it among INFO log noise.
        msg = (
            f"layer {layer_config.layer_id} ({layer_config.species_slug}) "
            f"returned zero features; refusing to record an empty load. "
            f"Investigate server response, projection guard, or OID resolution."
        )
        raise ArcGISError(msg)

    # Try SHAPECODE first.
    try:
        geoms = _build_geoms(
            features, layer_config, metadata, service_url, fetch_year,
            slug_strategy="shapecode",
        )
        shapecode_dupes = _duplicate_ids(geoms)
        if not shapecode_dupes:
            db.upsert_geometries(conn, geoms)
            return geoms
        # SHAPECODE collides — fall back, log so operators can audit.
        logger.info(
            "layer %d (%s): SHAPECODE collided on %d id(s) (%s%s); "
            "retrying with PORTIONNAME slugs",
            layer_config.layer_id, layer_config.species_slug,
            len(shapecode_dupes), shapecode_dupes[:3],
            "..." if len(shapecode_dupes) > 3 else "",
        )
    except ArcGISError as exc:
        # SHAPECODE strategy raised on a feature (e.g. invalid character or
        # neither SHAPECODE nor PORTIONNAME present). Treat as fallback signal
        # rather than a hard failure: PORTIONNAME-only path will either succeed
        # or surface a clearer error.
        logger.info(
            "layer %d (%s): SHAPECODE strategy raised (%s); "
            "retrying with PORTIONNAME slugs",
            layer_config.layer_id, layer_config.species_slug, exc,
        )
    geoms = _build_geoms(
        features, layer_config, metadata, service_url, fetch_year,
        slug_strategy="portionname",
    )
    portionname_dupes = _duplicate_ids(geoms)
    if portionname_dupes:
        msg = (
            f"layer {layer_config.layer_id} ({layer_config.species_slug}) "
            f"produced duplicate geometry id(s) under both SHAPECODE and "
            f"PORTIONNAME strategies: {portionname_dupes[:5]}"
            + (f" ... ({len(portionname_dupes) - 5} more)"
               if len(portionname_dupes) > 5 else "")
        )
        raise ArcGISError(msg)
    logger.info(
        "layer %d (%s): %d portions ingested with slug strategy=PORTIONNAME",
        layer_config.layer_id, layer_config.species_slug, len(geoms),
    )
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
