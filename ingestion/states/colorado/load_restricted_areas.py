"""Colorado restricted-area (no-hunt-zone) ingestion adapter.

Loads USGS PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer (layer 0)
federal no-hunt zones — National Parks, National Monuments, and the United States
Air Force Academy — into the ``geometry`` table with ``kind='restricted_area'``.

ADR lineage:
    ADR-001 — authority preserved, not replaced (fail-loud on missing/bad data)
    ADR-005 — state isolation; no lib/ edits; shared code via ingestion.lib only
    ADR-010 — all geometries stored as MultiPolygon/geography(MultiPolygon, 4326)
    ADR-014 — SourceCitation.document_type='gis_layer'; publication_date
              REGYEAR-anchored (Jan 1 of the fetch year), NOT
              editingInfo.lastEditDate or any server-side edit timestamp
    ADR-015 — geometry.verbatim_rule nullable

Provenance note:
    ``verbatim_rule=None`` for V1 — PAD-US carries geometry only, no regulatory
    text.  The CPW Big Game brochure (the would-be ``verbatim_rule`` source for
    the no-hunt narrative per unit) has an unresolved URL at story-open time, so
    text population is deferred to a future story (E06 / Group B).
    ``geometry.source`` cites PAD-US as the geometry authority, with
    ``document_type='gis_layer'``.

Run from the repo root (direct path, NOT python -m — see known-pitfalls.md
"state-adapter scripts must be invoked as python <path> not python -m"):
    ingestion/.venv/bin/python ingestion/states/colorado/load_restricted_areas.py

Required env: DATABASE_URL.
Optional env: HUNTREADY_INGESTION_CONTACT (appended to ArcGIS User-Agent as
    "(contact: <value>)").
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
import requests
from pydantic import ValidationError

from ingestion.lib import arcgis, db
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry, SourceCitation

# ---------------------------------------------------------------------------
# Service coordinates
# ---------------------------------------------------------------------------

PADUS_SERVICE_URL = (
    "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services"
    "/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer"
)
PADUS_LAYER_ID = 0

# Case-preserved from the service URL; used as a component of fixture filenames.
PADUS_LAYER_SLUG = "Federal_Fee_Managers_Authoritative_PADUS"

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

CO_FIXTURE_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Identity / citation constants
# ---------------------------------------------------------------------------

CO_AGENCY = "U.S. Geological Survey (PAD-US)"
CO_STATE_SLUG = "co-usgs-padus"
CO_STATE_CODE = "US-CO"
CO_RESTRICTED_ID_PREFIX = "CO-restricted"

# ---------------------------------------------------------------------------
# Ingestion parameters
# ---------------------------------------------------------------------------

# PAD-US has no per-feature REGYEAR attribute; default to the current
# operational year per ADR-014.  Update when the layer transitions to a new
# regulation year.
_FETCH_YEAR = 2026

# V1 server-side WHERE filter.
# Returns 11 features (10 NPS incl. Curecanti + 1 DOD AFA); Curecanti is
# dropped post-fetch per 36 CFR §2.2 (hunting IS permitted in NRAs).
_V1_WHERE = (
    "State_Nm = 'CO' AND ("
    "(Mang_Name = 'NPS' AND Des_Tp IN ('NP', 'NM', 'NRA'))"
    " OR (Mang_Name = 'DOD' AND Unit_Nm = 'United States Air Force Academy'))"
)

# Belt-and-suspenders: Curecanti must be dropped even if the WHERE filter
# is somehow widened in the future.
_CURECANTI_UNIT_NM = "Curecanti National Recreation Area"
_CURECANTI_GEOM_ID = "CO-restricted-curecanti-national-recreation-area-geom"

_RA_OUT_FIELDS = ("Unit_Nm", "Des_Tp", "Mang_Name", "Pub_Access", "GIS_Acres", "Src_Date")

# Exact band: V1 is a researcher-enumerated named set of 10 zones.
# 9 → leak (Curecanti slipped through); 11 → new zone appeared without review.
# Fires pre-db.connect() per OQ7 discipline — no partial writes on count drift.
_RA_COUNT_GUARD_BAND = (10, 10)

# The 10 V1 Colorado no-hunt zones loaded by this adapter.
_V1_EXPECTED_IDS: frozenset[str] = frozenset(
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
assert len(_V1_EXPECTED_IDS) == 10, "V1 restricted-area set must be exactly 10 zones"

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ColoradoGeometryError(Exception):
    """Wraps a per-feature geometry failure with Unit_Nm context for operator diagnosis."""


# ---------------------------------------------------------------------------
# Pure attribute extractors
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Return a URL-safe slug from *text*.

    Example::

        >>> _slugify("Rocky Mountain National Park")
        'rocky-mountain-national-park'
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _extract_unit_nm(props: dict[str, Any], metadata: LayerMetadata) -> str:
    """Return the Unit_Nm string value from a feature's properties dict.

    Raises ColoradoGeometryError if the Unit_Nm field is absent or blank.
    """
    value = props.get("Unit_Nm")
    if value is None or not str(value).strip():
        msg = (
            f"feature missing Unit_Nm field; "
            f"available={list(metadata.out_fields)}"
        )
        raise ColoradoGeometryError(msg)
    return str(value).strip()


# ---------------------------------------------------------------------------
# Per-feature normalization
# ---------------------------------------------------------------------------


def _feature_to_geometry(
    feature: dict[str, Any],
    layer_metadata: LayerMetadata,
    citation: SourceCitation,
    *,
    logger: logging.Logger,
) -> Geometry:
    """Convert one GeoJSON feature into a Geometry instance.

    ``citation`` is built once by the caller and passed in — all 10 PAD-US
    rows share an identical citation (same service URL, layer, year).

    Raises ColoradoGeometryError if Unit_Nm is missing/blank, the geometry
    cannot be coerced to MultiPolygon, or Pydantic validation fails.
    """
    props = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(props, dict):
        raise ColoradoGeometryError(
            f"feature has missing or non-dict 'properties' "
            f"(got {type(props).__name__}); "
            f"feature keys={sorted(feature) if isinstance(feature, dict) else type(feature).__name__}"
        )
    unit_nm = _extract_unit_nm(props, layer_metadata)

    try:
        geometry_wkt = arcgis.geojson_to_multipolygon_wkt(feature)
    except ArcGISError as exc:
        raise ColoradoGeometryError(
            f"{unit_nm}: geometry could not be coerced to MultiPolygon ({exc})"
        ) from exc

    # Src_Date / GIS_Acres are logged for forensics only and are NOT persisted
    # to the geometry row — SourceCitation is frozen with extra="forbid", and
    # ADR-014 anchors publication_date to REGYEAR, not server edit timestamps.
    if props.get("Src_Date") is not None or props.get("GIS_Acres") is not None:
        logger.info(
            "restricted area %s provenance: Src_Date=%s GIS_Acres=%s",
            unit_nm,
            props.get("Src_Date"),
            props.get("GIS_Acres"),
        )

    slug = _slugify(unit_nm)
    geom_id = f"{CO_RESTRICTED_ID_PREFIX}-{slug}-geom"

    try:
        return Geometry(
            id=geom_id,
            name=unit_nm,
            kind="restricted_area",
            geom=geometry_wkt,
            state=CO_STATE_CODE,
            license_year=None,
            verbatim_rule=None,
            source=citation,
        )
    except ValidationError as exc:
        raise ColoradoGeometryError(
            f"{unit_nm}: Geometry validation failed ({exc})"
        ) from exc


# ---------------------------------------------------------------------------
# Fetch + build  (network + normalisation; no DB connection)
# ---------------------------------------------------------------------------


def _fetch_and_build(
    service_url: str,
    fixture_dir: Path,
    fetch_year: int,
    *,
    session: requests.Session,
    logger: logging.Logger,
) -> list[Geometry]:
    """Fetch PAD-US V1 federal no-hunt zones and normalise each into a Geometry.

    Single-page WHERE-filtered fetch (the V1 set is ~11 features, far under one
    page). Composes arcgis lib primitives with a custom WHERE clause; no
    ingestion/lib edits (ADR-005). Network + transformation only — no DB
    connection is opened here; guards in main() fire on the returned list.
    """
    # Capture a single timestamp shared by all fixture writes in this run so
    # the metadata fixture, features fixture, and manifest are all co-named.
    # _utc_timestamp() is called here (not inside fetch_layer_metadata) because
    # fetch_layer_metadata does not surface its internal timestamp to callers,
    # and both _write_features_fixture and _write_manifest_fixture require a
    # positional timestamp argument with no default (REVIEW C1).
    timestamp = arcgis._utc_timestamp()

    # Step 1 — layer metadata fixture (AC-required; also provides object_id_field
    # and spatial_reference_wkid for downstream steps).
    metadata = arcgis.fetch_layer_metadata(
        service_url,
        PADUS_LAYER_ID,
        fixture_dir,
        layer_slug=PADUS_LAYER_SLUG,
        timestamp=timestamp,
        session=session,
    )

    # Step 2 — shared citation (all 10 V1 zones share one PAD-US citation).
    citation = arcgis.build_source_citation(
        service_url=service_url,
        layer_id=PADUS_LAYER_ID,
        metadata=metadata,
        license_year=fetch_year,
        state_slug=CO_STATE_SLUG,
        agency=CO_AGENCY,
    )

    # Step 3 — ArcGIS query endpoint + host for _request_with_retry throttling.
    host = urlparse(service_url).hostname or ""
    query_url = f"{service_url}/{PADUS_LAYER_ID}/query"

    # Step 4 — count cross-check (belt-and-suspenders before the page fetch).
    count_resp = arcgis._request_with_retry(
        session,
        query_url,
        params={"where": _V1_WHERE, "returnCountOnly": "true", "f": "json"},
        host=host,
    )
    if "count" not in count_resp:
        raise ArcGISError(
            f"malformed returnCountOnly response from {query_url}: "
            f"missing 'count'; keys={sorted(count_resp.keys())}"
        )
    expected_fetched = int(count_resp["count"])

    # Step 5 — single feature page (V1 set is ~11 features; well under one page).
    page = arcgis._request_with_retry(
        session,
        query_url,
        params={
            "where": _V1_WHERE,
            "outFields": ",".join(_RA_OUT_FIELDS),
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "geojson",
            "returnTrueCurves": "false",
            "geometryPrecision": 7,
        },
        host=host,
    )
    if "features" not in page:
        raise ArcGISError(
            f"PAD-US feature-page response missing 'features' key; "
            f"keys={sorted(page.keys())}"
        )
    features = page["features"]

    # Transfer-limit / count assert — the V1 named set must fit in one page.
    if page.get("exceededTransferLimit"):
        raise ArcGISError(
            f"PAD-US V1 query exceeded transfer limit "
            f"(expected ~{expected_fetched} features in one page); "
            f"WHERE or layer changed — review before ingesting"
        )
    if len(features) != expected_fetched:
        raise ArcGISError(
            f"PAD-US V1 feature count mismatch: "
            f"returnCountOnly={expected_fetched}, page returned {len(features)}; "
            f"cross-check the WHERE clause"
        )

    # Step 6 — projection guard (reproject from EPSG:3857 if needed; raises on
    # unsupported geometry types or mixed-CRS batches).
    checked = arcgis._check_and_fix_projection(
        features,
        declared_native_crs_wkid=metadata.spatial_reference_wkid,
    )

    # Step 7 — Curecanti drop (BEFORE fixture writes so fixtures, manifest
    # features_count, and DB all agree at 10 written features).
    # NPS NRAs permit hunting under 36 CFR §2.2; Curecanti must NOT be loaded
    # as a no-hunt zone even if the WHERE filter is widened in the future.
    # .strip() hardens the comparison against leading/trailing whitespace in
    # Unit_Nm values (mirrors _assert_curecanti_dropped's _slugify robustness).
    kept = [
        f for f in checked
        if str((f.get("properties") or {}).get("Unit_Nm") or "").strip() != _CURECANTI_UNIT_NM
    ]
    if len(kept) != len(checked):
        logger.info(
            "dropped Curecanti National Recreation Area "
            "(NPS NRAs permit hunting per 36 CFR §2.2); %d -> %d features",
            len(checked),
            len(kept),
        )

    # Step 8 — fixture writes (S05.2 parity) — over `kept` (10 features) so
    # fixtures, manifest features_count, and DB all agree on the written count.
    arcgis._write_features_fixture(
        fixture_dir, PADUS_LAYER_SLUG, PADUS_LAYER_ID, timestamp, kept
    )

    # Manifest: per-feature sha256 hashes → sorted → layer_hash → 256-bucket
    # distribution.  Mirrors fetch_features lines ~820-862 exactly so the
    # on-disk manifest is byte-compatible with the MT backfill tooling.
    per_feature_hashes_unsorted: list[str] = []
    for feature in kept:
        oid = arcgis._read_objectid(feature, oid_field=metadata.object_id_field)
        if oid is None:
            raise ArcGISError(
                f"PAD-US feature in layer {PADUS_LAYER_ID} ({PADUS_LAYER_SLUG}) "
                f"has no resolvable OBJECTID for manifest hash "
                f"(metadata.object_id_field={metadata.object_id_field!r})"
            )
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ArcGISError(
                f"PAD-US feature OID={oid} in layer {PADUS_LAYER_ID} "
                f"({PADUS_LAYER_SLUG}) has no 'properties' dict for manifest hash"
            )
        per_feature_hashes_unsorted.append(
            arcgis.compute_feature_hash(
                objectid=oid,
                geometry_wkt=arcgis.geojson_to_multipolygon_wkt(feature),
                attributes=properties,
            )
        )
    per_feature_hashes = sorted(per_feature_hashes_unsorted)
    layer_hash = hashlib.sha256(
        "\n".join(per_feature_hashes).encode("utf-8")
    ).hexdigest()
    hash_distribution: dict[str, int] = {f"{i:02x}": 0 for i in range(256)}
    for h in per_feature_hashes:
        hash_distribution[h[:2]] += 1
    manifest: dict[str, Any] = {
        "features_count": len(kept),
        "fetched_at": datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=timezone.utc)
        .isoformat(),
        "hash_distribution": hash_distribution,
        "layer_hash": layer_hash,
        "source_layer_max_record_count": metadata.max_record_count,
        "source_layer_object_id_field": metadata.object_id_field,
        "source_url": f"{service_url}/{PADUS_LAYER_ID}",
    }
    arcgis._write_manifest_fixture(
        fixture_dir, PADUS_LAYER_SLUG, PADUS_LAYER_ID, timestamp, manifest
    )

    # Step 9 — per-feature normalisation.
    geoms = [
        _feature_to_geometry(f, metadata, citation, logger=logger) for f in kept
    ]
    return geoms


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
    """Raise RuntimeError if ``n`` is outside ``_RA_COUNT_GUARD_BAND``.

    Fires pre-db.connect() per OQ7 discipline — no partial writes on count
    drift.  Cross-check the observed count against the layer's
    ``returnCountOnly=true`` query if this guard fires unexpectedly.
    """
    lo, hi = _RA_COUNT_GUARD_BAND
    if not (lo <= n <= hi):
        raise RuntimeError(
            f"restricted-area count {n} outside guard band {_RA_COUNT_GUARD_BAND}; "
            f"expected exactly 10 V1 zones (a count of 11 suggests Curecanti was not "
            f"dropped). Cross-check returnCountOnly=true on the V1 WHERE clause before re-running"
        )


def _assert_curecanti_dropped(geoms: list[Geometry]) -> None:
    """Belt-and-suspenders guard: raise if Curecanti is present in the output list.

    Independent of the WHERE-filter drop in Step 8 of ``_fetch_and_build``.
    NPS NRAs permit hunting under 36 CFR §2.2; Curecanti must never be loaded
    as a no-hunt zone.
    """
    if any(g.id == _CURECANTI_GEOM_ID for g in geoms):
        raise RuntimeError(
            f"{_CURECANTI_GEOM_ID} present in geometries; Curecanti NRA must be "
            f"dropped post-fetch (NPS NRAs permit hunting per 36 CFR §2.2)"
        )


# ---------------------------------------------------------------------------
# DB write  (called only after all pre-connect guards pass)
# ---------------------------------------------------------------------------


def _write_geometries(
    conn: psycopg.Connection[tuple[object, ...]], geoms: list[Geometry]
) -> None:
    """Upsert ``geoms`` into the geometry table via the shared db helper.

    The count-band + duplicate-id + Curecanti guards run in ``main()`` before
    this is ever reached; the caller owns the commit.
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
            PADUS_SERVICE_URL,
            CO_FIXTURE_DIR,
            args.fetch_year,
            session=session,
            logger=logger,
        )

    # Pre-connect guards (OQ7 discipline — no partial writes on bad data).
    dupes = _duplicate_ids(geoms)
    if dupes:
        raise RuntimeError(f"duplicate geometry ids ({len(dupes)}): {dupes[:5]}")
    _check_count_band(len(geoms))
    _assert_curecanti_dropped(geoms)
    actual_ids = {g.id for g in geoms}
    if actual_ids != _V1_EXPECTED_IDS:
        missing = sorted(_V1_EXPECTED_IDS - actual_ids)
        unexpected = sorted(actual_ids - _V1_EXPECTED_IDS)
        raise RuntimeError(
            f"fetched geometry ids do not match the V1 expected set; "
            f"missing={missing}, unexpected={unexpected}; "
            f"a PAD-US Unit_Nm rename or scope change requires updating "
            f"_V1_EXPECTED_IDS and the discovery report"
        )

    # DB write phase.
    with db.connect() as conn:
        _write_geometries(conn, geoms)
        conn.commit()

    logger.info("upserted %d restricted-area geometries", len(geoms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
