"""Shared pytest fixtures for the ingestion test suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ingestion.lib import arcgis


@pytest.fixture(autouse=True)
def _reset_throttle_state():
    """Clear the module-level per-host throttle state between tests."""
    arcgis._LAST_REQUEST.clear()
    yield
    arcgis._LAST_REQUEST.clear()


@pytest.fixture
def tmp_fixture_dir(tmp_path: Path) -> Path:
    """Per-test fixture directory under pytest's tmp_path."""
    d = tmp_path / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def sample_layer_descriptor() -> dict[str, Any]:
    """Minimal ArcGIS layer descriptor (?f=json response shape)."""
    return {
        "name": "Deer Elk Lion Hunting Districts",
        "objectIdField": "OBJECTID",
        "maxRecordCount": 2000,
        "geometryType": "esriGeometryPolygon",
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
            {"name": "DISTRICT", "type": "esriFieldTypeString"},
            {"name": "REG", "type": "esriFieldTypeString"},
            {"name": "REGYEAR", "type": "esriFieldTypeInteger"},
            {"name": "Shape__Area", "type": "esriFieldTypeDouble", "excludeFromAllRequest": True},
        ],
        "editingInfo": {"lastEditDate": 1700000000000},
    }


@pytest.fixture
def sample_polygon_feature() -> dict[str, Any]:
    """Minimal GeoJSON Polygon feature (a 1-degree square in Montana)."""
    return {
        "type": "Feature",
        "properties": {"OBJECTID": 1, "DISTRICT": "262", "REG": "verbatim text"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-111.0, 46.0], [-110.0, 46.0], [-110.0, 47.0], [-111.0, 47.0], [-111.0, 46.0]]],
        },
    }


@pytest.fixture
def sample_multipolygon_feature() -> dict[str, Any]:
    """Minimal GeoJSON MultiPolygon feature (two disjoint squares in Montana)."""
    return {
        "type": "Feature",
        "properties": {"OBJECTID": 2, "DISTRICT": "263"},
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [
                [[[-111.0, 46.0], [-110.5, 46.0], [-110.5, 46.5], [-111.0, 46.5], [-111.0, 46.0]]],
                [[[-110.0, 47.0], [-109.5, 47.0], [-109.5, 47.5], [-110.0, 47.5], [-110.0, 47.0]]],
            ],
        },
    }
