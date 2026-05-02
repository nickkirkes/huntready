"""Backfill manifests for S02.7 verification.

One-time script that scans the Montana fixtures directory for raw
``*-features-*.geojson`` files produced by S02.2–S02.5 and emits the paired
``*-manifest-*.json`` files using the same compute logic as ``fetch_features``.

The live ``fetch_features`` (``ingestion/lib/arcgis.py``) was extended in T1+T2
to write manifests automatically going forward.  This script is only needed for
the 10 layers ingested before that extension landed; raw features files exist
locally (git-ignored) but manifests were never written for them.

Re-running this script against the same on-disk files produces byte-identical
manifests, including ``fetched_at``, because the timestamp is parsed from the
filename rather than sampled from the clock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingestion.lib.arcgis import (
    LayerMetadata,
    _layer_metadata_from_raw_json,
    _write_manifest_fixture,
    compute_feature_hash,
    geojson_to_multipolygon_wkt,
)

# ---------------------------------------------------------------------------
# Service URL constants
# ---------------------------------------------------------------------------

HUNTING_DISTRICTS_URL = (
    "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer"
)
CWD_FEATURESERVER_URL = (
    "https://services3.arcgis.com/Cdxz8r11hT0MGzg1/arcgis/rest/services/"
    "ADMBND_HD_CWD/FeatureServer"
)

# (service_url, layer_slug, layer_id)
LAYER_TABLE: list[tuple[str, str, int]] = [
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 2),
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 3),
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 4),
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 10),
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 11),
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 12),
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 13),
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 14),
    (HUNTING_DISTRICTS_URL, "huntingDistricts", 15),
    (CWD_FEATURESERVER_URL, "ADMBND_HD_CWD", 0),
]

# Pattern for the embedded timestamp segment: 20260430T123456Z
_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def _ts_key(p: Path) -> str:
    """Extract the ``%Y%m%dT%H%M%SZ`` timestamp segment from a filename, or ``""``.

    Timestamps in this form sort lexicographically the same as chronologically.
    """
    m = _TS_RE.search(p.name)
    return m.group(1) if m else ""


def _latest_by_filename_ts(paths: list[Path]) -> Path | None:
    """Return the path whose embedded timestamp is lexicographically latest."""
    dated = [p for p in paths if _TS_RE.search(p.name)]
    if not dated:
        return None
    return max(dated, key=lambda p: (_ts_key(p), p.name))


def _latest_at_or_before(paths: list[Path], cutoff_ts: str) -> Path | None:
    """Return the path whose timestamp is the latest at-or-before ``cutoff_ts``.

    Used to pair a metadata fixture with a features fixture: loaders capture
    metadata first, then features, in a single fetch run — so the metadata
    paired with a given features file is the latest metadata captured at-or-
    before the features timestamp. Picking the unconditionally-latest metadata
    risks combining a recent metadata snapshot with an older features snapshot
    (or vice versa) and misrepresenting which fetch run the manifest documents.
    """
    candidates = [p for p in paths if _TS_RE.search(p.name) and _ts_key(p) <= cutoff_ts]
    if not candidates:
        return None
    return max(candidates, key=lambda p: (_ts_key(p), p.name))


def _parse_ts(path: Path) -> str:
    """Extract the ``%Y%m%dT%H%M%SZ`` timestamp from a filename; raise if absent."""
    m = _TS_RE.search(path.name)
    if not m:
        msg = f"no timestamp segment found in filename: {path.name}"
        raise ValueError(msg)
    return m.group(1)


def _process_layer(
    service_url: str,
    layer_slug: str,
    layer_id: int,
    fixture_dir: Path,
    *,
    dry_run: bool,
) -> str:
    """Process one layer: read fixtures, compute hashes, write manifest.

    Returns a human-readable summary line for the caller to print.

    Raises ``FileNotFoundError`` if the features file is missing.
    Raises ``FileNotFoundError`` if the metadata file is missing.
    """
    # --- Locate features file ---
    features_candidates = list(
        fixture_dir.glob(f"{layer_slug}-{layer_id}-features-*.geojson")
    )
    features_path = _latest_by_filename_ts(features_candidates)
    if features_path is None:
        msg = (
            f"no features fixture found for {layer_slug}-{layer_id} "
            f"in {fixture_dir}"
        )
        raise FileNotFoundError(msg)

    ts = _parse_ts(features_path)

    # --- Locate metadata file paired with this features fixture ---
    # Pair by latest-metadata-at-or-before-features-timestamp: loaders capture
    # metadata immediately before features in a single fetch run, so the
    # metadata that pairs with a given features file is the latest metadata
    # captured at-or-before the features timestamp. Picking the
    # unconditionally-latest metadata risks combining mismatched snapshots and
    # misrepresenting the manifest's source_layer_* fields.
    meta_candidates = list(
        fixture_dir.glob(f"{layer_slug}-{layer_id}-metadata-*.json")
    )
    meta_path = _latest_at_or_before(meta_candidates, ts)
    if meta_path is None:
        msg = (
            f"no metadata fixture at-or-before features timestamp {ts} "
            f"for {layer_slug}-{layer_id} in {fixture_dir}"
        )
        raise FileNotFoundError(msg)

    raw_meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    url = f"{service_url}/{layer_id}"
    metadata: LayerMetadata = _layer_metadata_from_raw_json(raw_meta, url=url)

    # --- Read features and compute hashes (then release the list) ---
    raw_features: dict[str, Any] = json.loads(features_path.read_text(encoding="utf-8"))
    features = raw_features.get("features")
    if not isinstance(features, list):
        msg = (
            f"features file {features_path} has no 'features' list "
            f"(top-level keys: {sorted(raw_features.keys())})"
        )
        raise ValueError(msg)
    oid_field = metadata.object_id_field
    if oid_field is None:
        msg = f"metadata for {layer_slug}-{layer_id} has no object_id_field"
        raise ValueError(msg)

    per_feature_hashes: list[str] = []
    for index, feature in enumerate(features):
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict) or oid_field not in properties:
            msg = (
                f"feature index {index} in {features_path.name} missing "
                f"properties.{oid_field!r}"
            )
            raise ValueError(msg)
        per_feature_hashes.append(
            compute_feature_hash(
                objectid=properties[oid_field],
                geometry_wkt=geojson_to_multipolygon_wkt(feature),
                attributes=properties,
            )
        )
    per_feature_hashes.sort()
    feature_count = len(per_feature_hashes)
    del raw_features, features  # release the parsed payload before next layer

    layer_hash = hashlib.sha256(
        "\n".join(per_feature_hashes).encode("utf-8")
    ).hexdigest()

    hash_distribution: dict[str, int] = {f"{i:02x}": 0 for i in range(256)}
    for h in per_feature_hashes:
        hash_distribution[h[:2]] += 1

    fetched_at = (
        datetime.strptime(ts, "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=timezone.utc)
        .isoformat()
    )

    manifest: dict[str, Any] = {
        "features_count": feature_count,
        "fetched_at": fetched_at,
        "hash_distribution": hash_distribution,
        "layer_hash": layer_hash,
        "source_layer_max_record_count": metadata.max_record_count,
        "source_layer_object_id_field": metadata.object_id_field,
        "source_url": url,
    }

    manifest_name = f"{layer_slug}-{layer_id}-manifest-{ts}.json"

    if not dry_run:
        _write_manifest_fixture(fixture_dir, layer_slug, layer_id, ts, manifest)

    return (
        f"[OK] {layer_slug}-{layer_id} → {manifest_name} "
        f"({feature_count} features, layer_hash={layer_hash[:8]}...)"
    )


def main() -> None:
    """Entry point for the backfill CLI."""
    default_fixture_dir = Path(__file__).parent / "fixtures"

    parser = argparse.ArgumentParser(
        description=(
            "One-time backfill: generate manifest fixtures for Montana layers "
            "ingested in S02.2–S02.5 that predate the automatic manifest write "
            "added in T1+T2."
        )
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=default_fixture_dir,
        help=(
            "Directory containing *-features-*.geojson and *-metadata-*.json files. "
            f"Default: {default_fixture_dir}"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and hash but do not write manifest files.",
    )
    args = parser.parse_args()

    fixture_dir: Path = args.fixture_dir
    dry_run: bool = args.dry_run

    missing: list[str] = []
    invalid: list[str] = []

    for service_url, layer_slug, layer_id in LAYER_TABLE:
        try:
            summary = _process_layer(
                service_url,
                layer_slug,
                layer_id,
                fixture_dir,
                dry_run=dry_run,
            )
            print(summary)
        except FileNotFoundError as exc:
            print(f"[MISSING] {exc}", file=sys.stderr)
            missing.append(f"{layer_slug}-{layer_id}")
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[INVALID] {layer_slug}-{layer_id}: {exc}", file=sys.stderr)
            invalid.append(f"{layer_slug}-{layer_id}")

    if missing:
        print(
            f"\nERROR: {len(missing)} layer(s) missing features files: "
            + ", ".join(missing),
            file=sys.stderr,
        )
    if invalid:
        print(
            f"\nERROR: {len(invalid)} layer(s) had invalid features/metadata: "
            + ", ".join(invalid),
            file=sys.stderr,
        )
    if missing or invalid:
        sys.exit(1)


if __name__ == "__main__":
    main()
