"""
ArcGIS MapServer fetch infrastructure (shared library).

Per ADR-005 (Python ingestion / TypeScript serving language split), this module
is state-agnostic and lives under `ingestion/lib/` for reuse by every state
adapter that pulls from ArcGIS feature services. No state-specific code.

Per ADR-008 (verbatim regulation text), partial extractions that lose meaning
are flagged loudly. The `geojson_to_multipolygon_wkt` helper raises on
GeometryCollection rather than silently filtering.

Public API:
    LayerMetadata          — typed descriptor of a queried ArcGIS layer
    ArcGISError            — raised on permanent fetch / parse / validation failures
    fetch_layer_metadata   — GETs ?f=json, captures fixture, returns LayerMetadata
    fetch_features         — paginated GeoJSON fetch, count cross-check, fixture write
    geojson_to_multipolygon_wkt — GeoJSON feature -> shapely.make_valid -> WKT
    build_source_citation  — assembles a SourceCitation with document_type='gis_layer'
    compute_feature_hash   — sha256 over canonical {objectid, geometry_wkt, attributes}

Caveat (per-feature change-detection hashes): the hash is computed over WKT
that has been canonicalized by shapely. A shapely upgrade can change WKT
formatting (e.g. float precision); `geometryPrecision=7` on the server side
mitigates but does not eliminate this. A "every hash changed" alert after a
shapely bump is a tooling-version event, not a data-quality event.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from pyproj import Transformer
from shapely.geometry import shape
from shapely.validation import make_valid

from ingestion.lib.schema import SourceCitation

# fwp-gis.mt.gov constants — used as defaults; functions accept overrides
MT_FWP_HOST = "fwp-gis.mt.gov"
DEFAULT_USER_AGENT = "HuntReady-Ingestion/1.0 (contact: nick@rowdycloud.io)"
DEFAULT_THROTTLE_SECONDS = 0.5

# Module-level per-host throttle state. Tests reset this via the
# autouse `_reset_throttle_state` fixture in conftest.py.
_LAST_REQUEST: dict[str, float] = {}

_logger = logging.getLogger(__name__)


class ArcGISError(Exception):
    """Raised when an ArcGIS MapServer fetch, parse, or validation fails permanently."""


@dataclass(frozen=True)
class LayerMetadata:
    """Typed descriptor of an ArcGIS MapServer layer.

    Constructed by `fetch_layer_metadata` after parsing the `?f=json` response.
    Used by `fetch_features` to drive paginated query parameters and by
    `build_source_citation` to read `editingInfo.lastEditDate` for provenance.
    """

    name: str
    object_id_field: str
    max_record_count: int
    out_fields: tuple[str, ...]   # field names with excludeFromAllRequest filtered out
    geometry_type: str
    last_edit_date_ms: int | None  # editingInfo.lastEditDate; None if absent
    raw: dict[str, Any] = field(repr=False)  # full descriptor (used for fixture write)
    # Layer's native EPSG code from extent.spatialReference (latestWkid then wkid).
    # Used by _check_and_fix_projection to flag the origin-near corner case where
    # 3857 coords look like WGS84. None if metadata lacks the field.
    spatial_reference_wkid: int | None = None


def _throttle(host: str, min_interval: float = DEFAULT_THROTTLE_SECONDS) -> None:
    """Sleep just enough so successive requests to `host` are at least `min_interval` apart.

    Per-host throttle state lives in the module-level `_LAST_REQUEST` dict.
    """
    now = time.monotonic()
    last = _LAST_REQUEST.get(host)
    if last is not None:
        elapsed = now - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
    _LAST_REQUEST[host] = time.monotonic()


# Transient ArcGIS error codes that warrant retry. Anything else in the
# error envelope is a permanent failure (raise immediately).
_TRANSIENT_ARCGIS_CODES: frozenset[int] = frozenset({500, 504, 504001})

# Backoff schedule (seconds) for transient retries. Length determines max retries.
_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0)


def _request_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    host: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """GET `url` with throttling, exponential backoff on transient failures, and ArcGIS error-envelope handling.

    ArcGIS MapServer endpoints sometimes return HTTP 200 with a body shaped
    `{"error": {"code": int, "message": str, "details": [...]}}`. This helper
    treats codes in `_TRANSIENT_ARCGIS_CODES` (500/504/504001) as transient
    (retry with backoff); any other error code is permanent (raise immediately).

    HTTP 5xx and `requests.RequestException` are also transient. HTTP 4xx is
    permanent.

    The `host` argument is used by `_throttle` to enforce per-host rate limits
    (≤1 req/500ms by default).

    Max retries is derived from `_BACKOFF_SCHEDULE` (currently 3 entries).
    """
    max_retries = len(_BACKOFF_SCHEDULE)
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        _throttle(host)
        try:
            response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(_BACKOFF_SCHEDULE[attempt])
                continue
            msg = f"network error after {max_retries} retries: {exc}"
            raise ArcGISError(msg) from exc

        # 4xx → permanent
        if 400 <= response.status_code < 500:
            msg = f"HTTP {response.status_code} from {url}: {response.text[:200]}"
            raise ArcGISError(msg)

        # 5xx → transient
        if response.status_code >= 500:
            last_error = ArcGISError(f"HTTP {response.status_code} from {url}")
            if attempt < max_retries:
                time.sleep(_BACKOFF_SCHEDULE[attempt])
                continue
            msg = f"HTTP {response.status_code} after {max_retries} retries: {url}"
            raise ArcGISError(msg)

        try:
            data = response.json()
        except ValueError as exc:
            msg = f"non-JSON response from {url}: {response.text[:200]}"
            raise ArcGISError(msg) from exc

        # ArcGIS error envelope (HTTP 200 with {error: {...}})
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            code = err.get("code")
            message = err.get("message", "")
            details = err.get("details", [])
            if isinstance(code, int) and code in _TRANSIENT_ARCGIS_CODES:
                last_error = ArcGISError(f"ArcGIS transient error {code}: {message}")
                if attempt < max_retries:
                    time.sleep(_BACKOFF_SCHEDULE[attempt])
                    continue
                msg = (
                    f"ArcGIS transient error {code} after {max_retries} retries: "
                    f"{message} (details={details})"
                )
                raise ArcGISError(msg)
            msg = f"ArcGIS error {code}: {message} (details={details})"
            raise ArcGISError(msg)

        return data

    # Unreachable in practice — the loop either returns or raises.
    if last_error is not None:
        raise ArcGISError(str(last_error)) from last_error
    msg = "request retry loop exited without success or failure"
    raise ArcGISError(msg)


def compute_feature_hash(
    *,
    objectid: int,
    geometry_wkt: str,
    attributes: dict[str, Any],
) -> str:
    """sha256 over canonical {objectid, geometry_wkt, attributes} for change-detection logging.

    Used by ingestion runs to detect which features changed, were added, or
    were removed since the last committed fixture. NOT a layer-level skip-fetch
    optimization — every layer is always re-fetched per epic E02 S02.1; this
    hash drives logging only.

    The canonical form sorts attribute keys via json.dumps(sort_keys=True) so
    insertion-order changes do not perturb the hash.

    Caveat (shapely-version sensitivity): `geometry_wkt` here is the WKT after
    shapely.make_valid canonicalization. A shapely upgrade can change WKT
    formatting (e.g. float precision); `geometryPrecision=7` on the server side
    mitigates but does not eliminate this. If a shapely bump produces "every
    hash changed" alerts, that is a tooling-version event, not a data-quality
    event.
    """
    payload = {
        "objectid": objectid,
        "geometry_wkt": geometry_wkt,
        "attributes": attributes,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def geojson_to_multipolygon_wkt(feature: dict[str, Any]) -> str:
    """Convert a GeoJSON Polygon/MultiPolygon feature to canonical MultiPolygon WKT.

    Steps:
      1. Parse `feature["geometry"]` via `shapely.geometry.shape`.
      2. Run `shapely.validation.make_valid` to fix self-intersections / ring orientation.
      3. Type-prune: Polygon -> MultiPolygon([poly]); MultiPolygon -> pass through;
         GeometryCollection or anything else -> raise loudly with OBJECTID + attributes.
      4. Reject empty / zero-area geometries (raise).

    Per ADR-008, partial extractions that lose meaning are flagged loudly. A
    GeometryCollection from a polygon-typed ArcGIS layer is a data-quality
    signal worth surfacing — refuse to silently filter and union.
    """
    from shapely.geometry import MultiPolygon, Polygon

    geom_dict = feature.get("geometry")
    oid = _read_objectid(feature)
    attrs = feature.get("properties") or feature.get("attributes") or {}

    if geom_dict is None:
        msg = f"feature OBJECTID={oid} attributes={attrs} has no geometry"
        raise ArcGISError(msg)

    parsed = shape(geom_dict)
    valid = make_valid(parsed)

    if isinstance(valid, Polygon):
        valid = MultiPolygon([valid])
    elif isinstance(valid, MultiPolygon):
        pass
    else:
        msg = (
            f"{type(valid).__name__} from feature OBJECTID={oid} attributes={attrs} "
            "— refusing to silently filter; treat as data-quality issue"
        )
        raise ArcGISError(msg)

    if valid.is_empty or valid.area == 0:
        msg = f"empty / zero-area geometry from feature OBJECTID={oid} attributes={attrs}"
        raise ArcGISError(msg)

    return valid.wkt


# Half-circumference of the WGS84 ellipsoid in meters at the equator. EPSG:3857
# (Web Mercator) coordinates are bounded by ±this value at ±180° longitude. Used
# to sanity-check that out-of-WGS84-range inputs are at least *plausibly* in
# Web Mercator before we attempt a 3857→4326 reprojection. Inputs that exceed
# this bound are in some other projected CRS (e.g. UTM) and we cannot guess.
_EPSG_3857_HALF_CIRCUMFERENCE_M = 20037508.342789244


def _coordinates_in_wgs84_range(coords: list) -> bool:
    """Recursively walk a GeoJSON coordinates structure; return True iff every
    [x, y] (or [x, y, z]) pair has |x| <= 180 and |y| <= 90.
    """
    if not coords:
        return True
    # Leaf: a coordinate pair like [x, y] or [x, y, z]
    if isinstance(coords[0], (int, float)):
        x, y = coords[0], coords[1]
        return abs(x) <= 180 and abs(y) <= 90
    # Recurse — coords is a list of rings, sub-rings, or sub-polygons
    return all(_coordinates_in_wgs84_range(c) for c in coords)


def _coordinates_in_3857_range(coords: list) -> bool:
    """Recursively check that every coordinate fits the EPSG:3857 valid extent.

    Used as a pre-check before attempting a 3857→4326 reprojection: if inputs
    exceed this bound, the source CRS is neither WGS84 nor Web Mercator and a
    bogus reprojection would silently succeed (the post-reprojection bounds
    check catches gross failures, not subtly-wrong UTM-as-3857 confusion).
    """
    if not coords:
        return True
    if isinstance(coords[0], (int, float)):
        x, y = coords[0], coords[1]
        return (
            abs(x) <= _EPSG_3857_HALF_CIRCUMFERENCE_M
            and abs(y) <= _EPSG_3857_HALF_CIRCUMFERENCE_M
        )
    return all(_coordinates_in_3857_range(c) for c in coords)


def _reproject_coordinates(coords: list, transformer: Transformer) -> list:
    """Recursively walk and reproject a GeoJSON coordinates structure.

    Returns a new structure with the same shape but transformed coords.
    """
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        x, y = coords[0], coords[1]
        nx, ny = transformer.transform(x, y)
        return [nx, ny] + list(coords[2:])  # preserve any z/m
    return [_reproject_coordinates(c, transformer) for c in coords]


def _check_and_fix_projection(
    features: list[dict[str, Any]],
    *,
    declared_native_crs_wkid: int | None = None,
) -> list[dict[str, Any]]:
    """Verify features are in WGS84; reproject from EPSG:3857 if not.

    Geometry-type guard: only Polygon and MultiPolygon are supported. Anything
    else (Point, LineString, etc.) raises ArcGISError. This keeps the helper
    state-agnostic but explicit — future callers ingesting non-polygon layers
    must extend this helper consciously rather than getting silently
    unchecked coordinates.

    Detection and reprojection are scoped narrowly:

    1. Per-feature classification: each feature is either fully in WGS84 range
       or fully out. (A single feature with one bad coordinate is treated as
       out-of-range — partial corruption inside one feature still indicates a
       CRS issue, not data integrity.)
    2. Mixed batches (some in-range, some out) are refused outright. ArcGIS
       layers serve a single CRS per layer; a mixed response is a server-side
       inconsistency that should be loud, not silently reprojected.
    3. All-out-of-range batches must additionally fit the EPSG:3857 valid
       extent (±~20037508 m at ±180°). If inputs exceed that, the source CRS
       is something other than WGS84 or Web Mercator (e.g. UTM); reprojection
       from 3857 would silently land in valid lat/lon bounds and corrupt the
       data. Raise instead.
    4. Otherwise, reproject from EPSG:3857 to 4326 via
       pyproj.Transformer.from_crs(3857, 4326, always_xy=True). Post-reproject
       output is rechecked against WGS84 bounds.

    Origin-near corner case: the magnitude-based detection has a residual
    blind spot. EPSG:3857 coords near (0, 0) (e.g. `(50, 50)`) fall within
    WGS84 bounds and are accepted as 4326 without reprojection — silent
    corruption (~6000 km misplacement) for any layer covering the
    equator+prime meridian intersection. To surface this when it could
    matter, callers may pass `declared_native_crs_wkid` (read from
    `metadata.spatial_reference_wkid`); a WARNING is logged when an
    in-range pass-through happens for a non-4326-native layer. We don't
    raise because the server may have legitimately honored outSR=4326,
    and we can't distinguish "honored" from "ignored at origin" purely
    from the coordinate magnitudes.
    """
    for feature in features:
        gtype = (feature.get("geometry") or {}).get("type")
        if gtype not in ("Polygon", "MultiPolygon"):
            oid = _read_objectid(feature)
            msg = (
                f"_check_and_fix_projection only supports Polygon/MultiPolygon, "
                f"got {gtype} for OBJECTID={oid}"
            )
            raise ArcGISError(msg)

    in_range_count = 0
    out_of_range_count = 0
    sample_out_of_range_oid: int | str | None = None
    for feature in features:
        if _coordinates_in_wgs84_range(feature["geometry"]["coordinates"]):
            in_range_count += 1
        else:
            out_of_range_count += 1
            if sample_out_of_range_oid is None:
                sample_out_of_range_oid = _read_objectid(feature)

    if out_of_range_count == 0:
        if declared_native_crs_wkid is not None and declared_native_crs_wkid != 4326:
            _logger.warning(
                "all %d features passed WGS84 range check, but layer's declared "
                "native CRS is EPSG:%d. If the server ignored outSR=4326 and the "
                "layer covers the equator/prime meridian, coordinates may be "
                "silently misprojected (residual limitation of magnitude-based "
                "detection — story spec accepts this).",
                len(features), declared_native_crs_wkid,
            )
        return features

    # Mixed batch — single CRS expected per ArcGIS layer; refuse rather than
    # blindly reproject the in-range features (which would corrupt them).
    if in_range_count > 0:
        msg = (
            f"mixed-CRS batch: {in_range_count} of {len(features)} features in WGS84 range, "
            f"{out_of_range_count} out of range "
            f"(first out-of-range OBJECTID={sample_out_of_range_oid}). "
            "ArcGIS layers serve a single CRS — refusing to reproject."
        )
        raise ArcGISError(msg)

    # All out-of-range. Confirm inputs at least fit EPSG:3857 valid extent
    # before attempting a 3857→4326 reprojection. A UTM-like input (e.g.
    # within ±20037508 but actually projected differently) can still slip
    # through to the post-reprojection bounds check; that is the residual
    # risk we accept per the story spec, which mandates the 3857 fallback.
    for feature in features:
        if not _coordinates_in_3857_range(feature["geometry"]["coordinates"]):
            oid = _read_objectid(feature)
            msg = (
                f"out-of-range coordinates exceed EPSG:3857 valid extent "
                f"(±{_EPSG_3857_HALF_CIRCUMFERENCE_M:.0f} m); first offending "
                f"OBJECTID={oid}. Source CRS is neither WGS84 nor Web Mercator; "
                "cannot safely reproject."
            )
            raise ArcGISError(msg)

    _logger.warning(
        "projection fallback triggered: %d features have out-of-range coords, "
        "reprojecting EPSG:3857 -> EPSG:4326. The ArcGIS endpoint may be misreporting CRS.",
        len(features),
    )
    transformer = Transformer.from_crs(3857, 4326, always_xy=True)
    reprojected: list[dict[str, Any]] = []
    for feature in features:
        new_feature = dict(feature)
        new_geom = dict(feature["geometry"])
        new_geom["coordinates"] = _reproject_coordinates(
            feature["geometry"]["coordinates"], transformer
        )
        new_feature["geometry"] = new_geom
        reprojected.append(new_feature)

    if not all(
        _coordinates_in_wgs84_range(f["geometry"]["coordinates"]) for f in reprojected
    ):
        msg = "post-reprojection coordinates still out of WGS84 range"
        raise ArcGISError(msg)
    return reprojected


def _read_objectid(feature: dict[str, Any]) -> int | str | None:
    """Best-effort OBJECTID extractor used in error messages.

    GeoJSON ArcGIS responses put attributes under either `properties` (the
    f=geojson convention) or `attributes` (the f=json convention).
    """
    for key in ("properties", "attributes"):
        attrs = feature.get(key)
        if isinstance(attrs, dict):
            for oid_key in ("OBJECTID", "objectid", "FID"):
                if oid_key in attrs:
                    val = attrs[oid_key]
                    return val if isinstance(val, (int, str)) else str(val)
    fid = feature.get("id")
    if isinstance(fid, (int, str)):
        return fid
    return None


def fetch_features(
    service_url: str,
    layer_id: int,
    metadata: LayerMetadata,
    fixture_dir: Path,
    *,
    layer_slug: str,
    timestamp: str | None = None,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Paginated GeoJSON fetch for an ArcGIS MapServer layer; cross-check + dedup + fixture write.

    Pre-flight: GET `?where=OBJECTID>=0&returnCountOnly=true&f=json` to learn the
    expected feature count.

    Page loop: GET `query?...&f=geojson` with `resultOffset` advanced by
    `metadata.max_record_count` per page. The termination rule is **fragile and
    important**: break only when `exceededTransferLimit` is False/absent AND the
    page is empty. "Fewer than page-size returned" fails at exact-N×pageSize
    boundaries (we'd terminate too early), so we always fetch one more page
    after the last non-empty response — even if `exceededTransferLimit=False`.

    Post-loop:
      - Dedup by OBJECTID (defensive — paginated ArcGIS responses can occasionally
        overlap if the server reorders rows mid-fetch).
      - Cross-check `len(deduped) == expected_count` from the count query.
      - Apply projection guard (`_check_and_fix_projection`) to detect EPSG:3857
        coords mislabeled as 4326.
      - Write the deduped GeoJSON FeatureCollection as fixture; the WGS84 crs
        envelope is added explicitly. Per E02 S02.1 caller convention, state
        adapters MUST pass `fixture_dir = ingestion/states/<state>/fixtures/`.

    Empty-layer guard: if the count query returns 0 and the first page returns
    [], the function returns [] without invoking the projection guard (no coords
    to check) and writes an empty FeatureCollection fixture.
    """
    timestamp = timestamp or _utc_timestamp()
    session = session if session is not None else _build_session()
    host = urlparse(service_url).hostname or ""
    query_url = f"{service_url}/{layer_id}/query"

    # Always-true predicate scoped to the layer's actual OID column. The spec's
    # example uses `OBJECTID>=0` literally, but ArcGIS layers occasionally use
    # FID, OBJECTID_1, etc.; using metadata.object_id_field avoids a confusing
    # silent count miscount or server-side error on those layers.
    where_clause = f"{metadata.object_id_field}>=0"

    # Pre-flight: count cross-check
    count_resp = _request_with_retry(
        session,
        query_url,
        params={"where": where_clause, "returnCountOnly": "true", "f": "json"},
        host=host,
    )
    if "count" not in count_resp:
        msg = (
            f"malformed returnCountOnly response from {query_url} layer {layer_id}: "
            f"missing 'count' key; available keys: {sorted(count_resp.keys())}"
        )
        raise ArcGISError(msg)
    expected_count = int(count_resp["count"])

    # Page loop
    seen_oids: set[Any] = set()
    dedup_features: list[dict[str, Any]] = []
    duplicate_oids: list[Any] = []
    offset = 0
    base_params: dict[str, Any] = {
        "where": where_clause,
        "outFields": ",".join(metadata.out_fields),
        "orderByFields": f"{metadata.object_id_field} ASC",
        "f": "geojson",
        "outSR": 4326,
        "returnTrueCurves": "false",
        "geometryPrecision": 7,
        "resultRecordCount": metadata.max_record_count,
    }

    while True:
        page = _request_with_retry(
            session,
            query_url,
            params={**base_params, "resultOffset": offset},
            host=host,
        )
        features = page.get("features") or []
        for feature in features:
            oid = _read_objectid(feature)
            if oid in seen_oids:
                duplicate_oids.append(oid)
                continue
            seen_oids.add(oid)
            dedup_features.append(feature)

        exceeded = bool(page.get("exceededTransferLimit", False))
        is_empty = not features

        if not exceeded and is_empty:
            break

        offset += metadata.max_record_count

    if duplicate_oids:
        _logger.warning(
            "OBJECTID dedup fired for layer %d (%s): %d duplicate(s) dropped: %s",
            layer_id, layer_slug, len(duplicate_oids), duplicate_oids,
        )

    # Cross-check
    if len(dedup_features) != expected_count:
        msg = (
            f"feature count mismatch for layer {layer_id}: "
            f"returnCountOnly={expected_count}, paginated={len(dedup_features)}"
        )
        raise ArcGISError(msg)

    # Empty-layer guard
    if expected_count == 0:
        _logger.warning(
            "layer %d (%s) at %s returned 0 features — verify the layer ID and "
            "where clause are correct (writing empty fixture)",
            layer_id, layer_slug, service_url,
        )
        _write_features_fixture(
            fixture_dir, layer_slug, layer_id, timestamp, []
        )
        return []

    # Projection guard
    checked = _check_and_fix_projection(
        dedup_features,
        declared_native_crs_wkid=metadata.spatial_reference_wkid,
    )

    # Fixture write
    _write_features_fixture(fixture_dir, layer_slug, layer_id, timestamp, checked)

    return checked


def _write_features_fixture(
    fixture_dir: Path,
    layer_slug: str,
    layer_id: int,
    timestamp: str,
    features: list[dict[str, Any]],
) -> None:
    """Write a deduped GeoJSON FeatureCollection as a committed fixture."""
    fixture_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
    fixture_path = fixture_dir / f"{layer_slug}-{layer_id}-features-{timestamp}.geojson"
    fixture_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def _build_session(user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    """Construct a requests.Session with the project's User-Agent header set."""
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    return session


def _utc_timestamp() -> str:
    """Compact ISO 8601 timestamp (UTC) suitable for filenames."""
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug_from_service(service_url: str) -> str:
    """Extract the service name from an ArcGIS service URL.

    Example:
        "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer"
        -> "huntingDistricts"

    Splits the path on '/'; returns the segment immediately before 'MapServer'
    (or 'FeatureServer'). Falls back to the last non-empty segment if neither
    marker is present.
    """
    path = urlparse(service_url).path.rstrip("/")
    segments = [s for s in path.split("/") if s]
    for marker in ("MapServer", "FeatureServer"):
        if marker in segments:
            idx = segments.index(marker)
            if idx > 0:
                return segments[idx - 1]
    return segments[-1] if segments else ""


def build_source_citation(
    *,
    service_url: str,
    layer_id: int,
    metadata: LayerMetadata,
    license_year: int,
    fetch_date: date,
    state_slug: str,
    agency: str,
) -> SourceCitation:
    """Construct a SourceCitation for an ArcGIS layer with `document_type='gis_layer'`.

    `publication_date` is taken from `metadata.last_edit_date_ms` (Unix epoch
    milliseconds, converted to UTC ISO date) when available; otherwise falls
    back to `fetch_date.isoformat()`.

    `state_slug` is the prefix the state adapter passes (e.g. "mt-fwp" for
    Montana FWP, matching the epic E02 spec example
    `id=f"mt-fwp-arcgis-{service}-{layer_id}-{license_year}"`). Pass `state_slug="mt-fwp"`
    in S02.2 to match the spec exactly.
    """
    if metadata.last_edit_date_ms is not None:
        publication_date = (
            datetime.fromtimestamp(metadata.last_edit_date_ms / 1000, tz=timezone.utc)
            .date()
            .isoformat()
        )
    else:
        publication_date = fetch_date.isoformat()

    service_slug = _slug_from_service(service_url)
    return SourceCitation(
        id=f"{state_slug}-arcgis-{service_slug}-{layer_id}-{license_year}",
        agency=agency,
        title=f"{metadata.name} (Layer {layer_id})",
        url=f"{service_url}/{layer_id}",
        publication_date=publication_date,
        document_type="gis_layer",
        supersedes=None,
        page_reference=None,
    )


def fetch_layer_metadata(
    service_url: str,
    layer_id: int,
    fixture_dir: Path,
    *,
    layer_slug: str,
    timestamp: str | None = None,
    session: requests.Session | None = None,
) -> LayerMetadata:
    """GET ?f=json for an ArcGIS MapServer layer; capture as fixture; parse to LayerMetadata.

    The library is host-agnostic but state adapters (e.g. ingestion/states/montana/)
    MUST pass `fixture_dir = Path("ingestion/states/<state>/fixtures/")` so the
    epic E02 source-fixture-capture AC ("fixtures committed; no symlinks") is
    met. The MT path is `ingestion/states/montana/fixtures/`.

    Drops fields with `excludeFromAllRequest: true` from `out_fields` so that
    callers using `outFields=<list>` do not request fields the server has marked
    excluded.
    """
    timestamp = timestamp or _utc_timestamp()
    session = session if session is not None else _build_session()
    host = urlparse(service_url).hostname or ""

    url = f"{service_url}/{layer_id}"
    data = _request_with_retry(session, url, params={"f": "json"}, host=host)

    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / f"{layer_slug}-{layer_id}-metadata-{timestamp}.json"
    fixture_path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )

    fields = data.get("fields") or []
    out_fields = tuple(
        f["name"] for f in fields
        if isinstance(f, dict) and "name" in f and not f.get("excludeFromAllRequest")
    )
    last_edit_ms = (data.get("editingInfo") or {}).get("lastEditDate")
    last_edit_ms_typed = last_edit_ms if isinstance(last_edit_ms, int) else None

    extent = data.get("extent")
    sr = extent.get("spatialReference") if isinstance(extent, dict) else None
    sr = sr if isinstance(sr, dict) else {}
    # latestWkid is the modern EPSG code; wkid is the Esri legacy code (often
    # 102100 for Web Mercator). Prefer latestWkid.
    sr_wkid = sr.get("latestWkid") or sr.get("wkid")
    spatial_reference_wkid = sr_wkid if isinstance(sr_wkid, int) else None

    try:
        return LayerMetadata(
            name=data["name"],
            object_id_field=data["objectIdField"],
            max_record_count=int(data["maxRecordCount"]),
            out_fields=out_fields,
            geometry_type=data["geometryType"],
            last_edit_date_ms=last_edit_ms_typed,
            raw=data,
            spatial_reference_wkid=spatial_reference_wkid,
        )
    except KeyError as exc:
        msg = (
            f"malformed layer metadata response from {url}: "
            f"missing key {exc!s}; available keys: {sorted(data.keys())}"
        )
        raise ArcGISError(msg) from exc
