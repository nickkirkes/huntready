"""Montana restricted areas ingestion adapter.

Loads layers #2 (Big Game Restricted Areas) and #15 (Elk Restricted Areas)
from MT FWP's `admbnd/huntingDistricts` MapServer into the `geometry` table.

All rows have kind='restricted_area'. IDs are derived from PORTIONNAME for
both layers: `MT-restricted-{area_slug}-{portionname_slug}-geom`.

Layer #2 applies the CWD discriminator filter (is_cwd_feature) to exclude CWD
rows; those belong to S02.5 (kind='cwd_zone'). Layer #15 is unfiltered.

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/load_restricted_areas.py

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
from states.montana.cwd_discriminator import is_cwd_feature


MT_FWP_HUNTING_DISTRICTS_URL = "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer"
MT_FIXTURE_DIR = Path(__file__).parent / "fixtures"
MT_LAYER_SLUG = "huntingDistricts"
MT_AGENCY = "Montana Fish, Wildlife & Parks"
MT_STATE_SLUG = "mt-fwp"
MT_STATE_CODE = "US-MT"


@dataclass(frozen=True)
class RestrictedAreaLayerConfig:
    layer_id: int
    area_slug: str          # "bigame" for layer #2, "elk" for layer #15
    id_prefix: str          # "MT-restricted-bigame", "MT-restricted-elk"
    display_name: str       # "Big Game", "Elk"
    apply_cwd_filter: bool  # True only for layer #2 (S02.5 idempotency boundary)


RESTRICTED_AREA_LAYERS: tuple[RestrictedAreaLayerConfig, ...] = (
    RestrictedAreaLayerConfig(
        layer_id=2,
        area_slug="bigame",
        id_prefix="MT-restricted-bigame",
        display_name="Big Game",
        apply_cwd_filter=True,
    ),
    RestrictedAreaLayerConfig(
        layer_id=15,
        area_slug="elk",
        id_prefix="MT-restricted-elk",
        display_name="Elk",
        apply_cwd_filter=False,
    ),
)


def _slugify(text: str) -> str:
    """Lowercase + non-alphanumeric -> hyphen; strip leading/trailing hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        msg = f"cannot slugify empty/whitespace text: {text!r}"
        raise ArcGISError(msg)
    return slug


def _extract_license_year(props: dict[str, Any]) -> int | None:
    raw = props.get("REGYEAR")
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        msg = f"REGYEAR {raw!r} is not a valid integer"
        raise ArcGISError(msg) from exc


def _extract_identity_slug(
    props: dict[str, Any],
    metadata: LayerMetadata,
) -> str:
    raw = props.get("PORTIONNAME")
    if raw is not None:
        coerced = str(raw)
        if coerced.strip():
            return _slugify(coerced)
    msg = (
        f"layer {metadata.name!r} feature missing PORTIONNAME; "
        f"available={list(metadata.out_fields)}"
    )
    raise ArcGISError(msg)


def _extract_verbatim_rule_combined(props: dict[str, Any]) -> str | None:
    """Combine REG and COMMENTS into a single verbatim rule string.

    Cases (per ADR-015):
      - both populated and differ        -> f"{REG}\\n\\n--- COMMENTS ---\\n\\n{COMMENTS}"
      - both populated and identical     -> REG (don't double-store)
      - REG only                         -> REG
      - COMMENTS only                    -> COMMENTS
      - both empty/whitespace/missing    -> None

    Original (un-stripped) source values are returned per ADR-008's verbatim
    discipline. .strip() is used only for emptiness and equality comparisons.
    The "identical" comparison uses stripped values so trailing-whitespace-only
    differences do not produce a duplicated combined record.
    """
    reg_raw = props.get("REG")
    comments_raw = props.get("COMMENTS")
    reg_str = str(reg_raw) if reg_raw is not None else ""
    comments_str = str(comments_raw) if comments_raw is not None else ""
    reg_has_text = bool(reg_str.strip())
    comments_has_text = bool(comments_str.strip())

    if reg_has_text and comments_has_text:
        if reg_str.strip() == comments_str.strip():
            return reg_str
        return f"{reg_str}\n\n--- COMMENTS ---\n\n{comments_str}"
    if reg_has_text:
        return reg_str
    if comments_has_text:
        return comments_str
    return None


def _feature_to_geometry(
    feature: dict[str, Any],
    layer_config: RestrictedAreaLayerConfig,
    layer_metadata: LayerMetadata,
    service_url: str,
    fetch_year: int,
) -> Geometry:
    props = feature["properties"]
    slug = _extract_identity_slug(props, layer_metadata)
    geometry_wkt = arcgis.geojson_to_multipolygon_wkt(feature)
    license_year = _extract_license_year(props)
    citation = arcgis.build_source_citation(
        service_url=service_url,
        layer_id=layer_config.layer_id,
        metadata=layer_metadata,
        license_year=license_year if license_year is not None else fetch_year,
        state_slug=MT_STATE_SLUG,
        agency=MT_AGENCY,
    )
    return Geometry(
        id=f"{layer_config.id_prefix}-{slug}-geom",
        name=f"{layer_config.display_name} Restricted Area {slug}",
        kind="restricted_area",
        geom=geometry_wkt,
        state=MT_STATE_CODE,
        license_year=license_year,
        verbatim_rule=_extract_verbatim_rule_combined(props),
        source=citation,
    )


def _duplicate_ids(geoms: list[Geometry]) -> list[str]:
    counts = Counter(g.id for g in geoms)
    return sorted(i for i, n in counts.items() if n > 1)


def _load_layer(
    conn: psycopg.Connection[Any],
    service_url: str,
    layer_config: RestrictedAreaLayerConfig,
    fixture_dir: Path,
    fetch_year: int,
    *,
    session: requests.Session | None = None,
) -> list[Geometry]:
    logger = logging.getLogger(__name__)
    metadata = arcgis.fetch_layer_metadata(
        service_url, layer_config.layer_id, fixture_dir,
        layer_slug=MT_LAYER_SLUG, session=session,
    )
    features = arcgis.fetch_features(
        service_url, layer_config.layer_id, metadata, fixture_dir,
        layer_slug=MT_LAYER_SLUG, session=session,
    )
    if not features:
        msg = (
            f"layer {layer_config.layer_id} ({layer_config.area_slug}) "
            f"returned zero features; refusing to record an empty load."
        )
        raise ArcGISError(msg)

    pre_count = len(features)
    logger.info(
        "layer %d (%s): %d feature(s) fetched",
        layer_config.layer_id, layer_config.area_slug, pre_count,
    )
    if layer_config.apply_cwd_filter:
        features = [f for f in features if not is_cwd_feature(f.get("properties") or {})]
        cwd_filtered = pre_count - len(features)
        if not features:
            msg = (
                f"layer {layer_config.layer_id} ({layer_config.area_slug}) "
                f"returned {pre_count} features but ALL matched the CWD "
                f"discriminator; refusing to record an empty restricted_area "
                f"load. CWD rows belong to S02.5 (kind='cwd_zone')."
            )
            raise ArcGISError(msg)
        logger.info(
            "layer %d (%s): pre=%d cwd_filtered=%d kept=%d",
            layer_config.layer_id, layer_config.area_slug,
            pre_count, cwd_filtered, len(features),
        )

    geoms = [
        _feature_to_geometry(f, layer_config, metadata, service_url, fetch_year)
        for f in features
    ]
    dupes = _duplicate_ids(geoms)
    if dupes:
        msg = (
            f"layer {layer_config.layer_id} ({layer_config.area_slug}) "
            f"produced duplicate geometry id(s): {dupes[:5]}"
            + (f" ... ({len(dupes) - 5} more)" if len(dupes) > 5 else "")
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
        for layer_config in RESTRICTED_AREA_LAYERS:
            logger.info(
                "loading layer %d (%s)",
                layer_config.layer_id, layer_config.area_slug,
            )
            geoms = _load_layer(
                conn, args.service_url, layer_config, MT_FIXTURE_DIR, args.fetch_year,
                session=session,
            )
            logger.info(
                "layer %d: upserted %d geometries",
                layer_config.layer_id, len(geoms),
            )
        # Single atomic commit covering BOTH layers. If either _load_layer
        # raises, this commit is skipped and the connection's __exit__
        # rolls back the transaction. Do not move this inside the loop —
        # per-layer commits would leave partial state on a layer-#15 failure.
        conn.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
