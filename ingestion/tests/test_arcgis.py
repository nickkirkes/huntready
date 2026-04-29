"""Unit tests for ingestion.lib.arcgis."""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests as requests_lib  # alias to avoid colliding with any local `requests`

from ingestion.lib.arcgis import (
    ArcGISError,
    LayerMetadata,
    _check_and_fix_projection,
    _read_objectid,
    _request_with_retry,
    build_source_citation,
    compute_feature_hash,
    fetch_features,
    fetch_layer_metadata,
    geojson_to_multipolygon_wkt,
)


class TestComputeFeatureHash:
    def test_deterministic_across_attribute_order(self) -> None:
        """Hash is stable regardless of attribute insertion order."""
        a = compute_feature_hash(
            objectid=1,
            geometry_wkt="MULTIPOLYGON (((-111 46, -110 46, -110 47, -111 47, -111 46)))",
            attributes={"DISTRICT": "262", "REG": "verbatim"},
        )
        b = compute_feature_hash(
            objectid=1,
            geometry_wkt="MULTIPOLYGON (((-111 46, -110 46, -110 47, -111 47, -111 46)))",
            attributes={"REG": "verbatim", "DISTRICT": "262"},
        )
        assert a == b

    def test_objectid_change_changes_hash(self) -> None:
        a = compute_feature_hash(objectid=1, geometry_wkt="MULTIPOLYGON EMPTY", attributes={})
        b = compute_feature_hash(objectid=2, geometry_wkt="MULTIPOLYGON EMPTY", attributes={})
        assert a != b

    def test_geometry_change_changes_hash(self) -> None:
        a = compute_feature_hash(
            objectid=1,
            geometry_wkt="MULTIPOLYGON (((-111 46, -110 46, -110 47, -111 47, -111 46)))",
            attributes={},
        )
        b = compute_feature_hash(
            objectid=1,
            geometry_wkt="MULTIPOLYGON (((-112 46, -111 46, -111 47, -112 47, -112 46)))",
            attributes={},
        )
        assert a != b

    def test_attribute_change_changes_hash(self) -> None:
        a = compute_feature_hash(objectid=1, geometry_wkt="MULTIPOLYGON EMPTY", attributes={"REG": "a"})
        b = compute_feature_hash(objectid=1, geometry_wkt="MULTIPOLYGON EMPTY", attributes={"REG": "b"})
        assert a != b

    def test_returns_64_char_hex(self) -> None:
        h = compute_feature_hash(objectid=1, geometry_wkt="MULTIPOLYGON EMPTY", attributes={})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestGeojsonToMultipolygonWkt:
    def test_polygon_wraps_to_multipolygon(self, sample_polygon_feature: dict) -> None:
        wkt = geojson_to_multipolygon_wkt(sample_polygon_feature)
        assert wkt.startswith("MULTIPOLYGON")

    def test_multipolygon_passes_through(self, sample_multipolygon_feature: dict) -> None:
        wkt = geojson_to_multipolygon_wkt(sample_multipolygon_feature)
        assert wkt.startswith("MULTIPOLYGON")
        # 2 sub-polygons in the sample
        from shapely import from_wkt
        parsed = from_wkt(wkt)
        assert len(parsed.geoms) == 2

    def test_geometry_collection_raises_with_objectid(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 99, "DISTRICT": "BAD"},
            "geometry": {
                "type": "GeometryCollection",
                "geometries": [
                    {"type": "Point", "coordinates": [-110.0, 46.0]},
                    {
                        "type": "Polygon",
                        "coordinates": [[[-111.0, 46.0], [-110.0, 46.0], [-110.0, 47.0], [-111.0, 47.0], [-111.0, 46.0]]],
                    },
                ],
            },
        }
        with pytest.raises(ArcGISError, match=r"OBJECTID=99"):
            geojson_to_multipolygon_wkt(feature)

    def test_empty_polygon_raises_with_objectid(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 7},
            "geometry": {"type": "Polygon", "coordinates": []},
        }
        with pytest.raises(ArcGISError, match=r"OBJECTID=7"):
            geojson_to_multipolygon_wkt(feature)

    def test_missing_geometry_raises(self) -> None:
        feature = {"type": "Feature", "properties": {"OBJECTID": 5}, "geometry": None}
        with pytest.raises(ArcGISError, match=r"OBJECTID=5"):
            geojson_to_multipolygon_wkt(feature)

    def test_objectid_from_attributes_key(self) -> None:
        """ArcGIS f=json responses use `attributes` instead of `properties`."""
        feature = {
            "attributes": {"OBJECTID": 42},
            "geometry": None,
        }
        with pytest.raises(ArcGISError, match=r"OBJECTID=42"):
            geojson_to_multipolygon_wkt(feature)


class TestCheckAndFixProjection:
    def test_wgs84_passes_through_unchanged(self, sample_polygon_feature: dict) -> None:
        out = _check_and_fix_projection([sample_polygon_feature])
        assert out == [sample_polygon_feature]

    def test_web_mercator_reprojects(self) -> None:
        """A Helena-MT-ish coord in EPSG:3857 (~ -12826000, 5688000) reprojects to MT lat/lon."""
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 1},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-12826000.0, 5688000.0],
                    [-12825000.0, 5688000.0],
                    [-12825000.0, 5689000.0],
                    [-12826000.0, 5689000.0],
                    [-12826000.0, 5688000.0],
                ]],
            },
        }
        out = _check_and_fix_projection([feature])
        coords = out[0]["geometry"]["coordinates"][0]
        # First coord should now be in MT range: lon ~ -115, lat ~ 45
        x, y = coords[0]
        assert -116 < x < -114
        assert 45 < y < 46

    def test_point_geometry_raises_with_objectid(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 11},
            "geometry": {"type": "Point", "coordinates": [-110.0, 46.0]},
        }
        with pytest.raises(ArcGISError, match=r"got Point.*OBJECTID=11"):
            _check_and_fix_projection([feature])

    def test_linestring_geometry_raises_with_objectid(self) -> None:
        feature = {
            "type": "Feature",
            "attributes": {"OBJECTID": 22},
            "geometry": {"type": "LineString", "coordinates": [[-110.0, 46.0], [-109.0, 46.0]]},
        }
        with pytest.raises(ArcGISError, match=r"got LineString.*OBJECTID=22"):
            _check_and_fix_projection([feature])

    def test_post_reprojection_still_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If reprojection produces out-of-range coords, the post-check raises.

        Inputs must be within EPSG:3857 valid extent (±~2e7) so the pre-check
        passes; we then stub Transformer to identity so the output stays out
        of WGS84 range and trips the post-reprojection guard.
        """
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 1},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[1e7, 1e7], [1e7 + 1, 1e7], [1e7 + 1, 1e7 + 1], [1e7, 1e7 + 1], [1e7, 1e7]]],
            },
        }

        # Stub the Transformer to return identity (so out-of-range coords stay out-of-range)
        class IdentityTransformer:
            @staticmethod
            def transform(x: float, y: float) -> tuple[float, float]:
                return x, y

        monkeypatch.setattr(
            "ingestion.lib.arcgis.Transformer",
            type("T", (), {"from_crs": staticmethod(lambda *a, **kw: IdentityTransformer())})(),
        )
        with pytest.raises(ArcGISError, match=r"post-reprojection"):
            _check_and_fix_projection([feature])

    def test_mixed_batch_raises(self) -> None:
        """A batch with some in-range and some out-of-range features is refused.

        ArcGIS layers serve a single CRS per layer; mixed coords indicate a
        server-side inconsistency. Reprojecting all features (including the
        in-range ones) would corrupt the correct features.
        """
        in_range_feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 1, "DISTRICT": "good"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-111.0, 46.0], [-110.0, 46.0], [-110.0, 47.0], [-111.0, 47.0], [-111.0, 46.0],
                ]],
            },
        }
        out_of_range_feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 99, "DISTRICT": "bad"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-12826000.0, 5688000.0], [-12825000.0, 5688000.0],
                    [-12825000.0, 5689000.0], [-12826000.0, 5689000.0],
                    [-12826000.0, 5688000.0],
                ]],
            },
        }
        with pytest.raises(ArcGISError, match=r"mixed-CRS batch.*OBJECTID=99"):
            _check_and_fix_projection([in_range_feature, out_of_range_feature])

    def test_in_range_pass_through_with_non_4326_native_emits_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Origin-near corner case: 3857 coords like (50, 50) pass the WGS84
        range check but aren't actually WGS84. When the layer's declared
        native CRS is non-4326, surface this risk via a WARNING log even
        though we accept the coords as-is (we can't distinguish honored
        outSR=4326 from server-bug-at-origin from coords alone).
        """
        # Coords near origin, in WGS84 range (|x|<180, |y|<90) but suspiciously
        # close to (0, 0) — could be 3857 meters that the server failed to reproject.
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 1, "DISTRICT": "near-origin"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [50.0, 50.0], [60.0, 50.0], [60.0, 60.0], [50.0, 60.0], [50.0, 50.0],
                ]],
            },
        }
        with caplog.at_level(logging.WARNING, logger="ingestion.lib.arcgis"):
            out = _check_and_fix_projection([feature], declared_native_crs_wkid=3857)
        # Coords pass through unchanged (we don't distort the happy path)
        assert out == [feature]
        # But a warning was emitted documenting the residual risk
        assert any(
            "declared native CRS is EPSG:3857" in rec.message for rec in caplog.records
        )

    def test_in_range_pass_through_with_4326_native_no_warning(
        self, caplog: pytest.LogCaptureFixture, sample_polygon_feature: dict
    ) -> None:
        """The warning should only fire for non-4326 native layers."""
        with caplog.at_level(logging.WARNING, logger="ingestion.lib.arcgis"):
            _check_and_fix_projection(
                [sample_polygon_feature], declared_native_crs_wkid=4326,
            )
        assert not any(
            "declared native CRS" in rec.message for rec in caplog.records
        )

    def test_out_of_3857_range_raises_before_reprojection(self) -> None:
        """Coordinates exceeding EPSG:3857 valid extent (~2e7) cannot be safely
        reprojected — source CRS is neither WGS84 nor Web Mercator. Raise rather
        than letting pyproj produce silently-wrong lat/lon (e.g. UTM-like inputs
        that happen to land back in valid WGS84 range after a bogus 3857 transform).
        """
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 7},
            "geometry": {
                "type": "Polygon",
                # 5e7 exceeds ±20037508 (the 3857 bound at ±180° longitude).
                "coordinates": [[
                    [5e7, 5e7], [5e7 + 1, 5e7], [5e7 + 1, 5e7 + 1], [5e7, 5e7 + 1], [5e7, 5e7],
                ]],
            },
        }
        with pytest.raises(
            ArcGISError, match=r"exceed EPSG:3857 valid extent.*OBJECTID=7",
        ):
            _check_and_fix_projection([feature])


def _make_response(*, status_code: int = 200, json_body: dict | None = None, text: str = "") -> MagicMock:
    """Build a mock requests.Response with `.status_code`, `.json()`, `.text`."""
    resp = MagicMock(spec=requests_lib.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


class TestRequestWithRetry:
    def test_success_returns_parsed_json(self, monkeypatch) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.return_value = _make_response(json_body={"name": "Layer", "fields": []})

        out = _request_with_retry(session, "http://example.com", host="example.com")

        assert out == {"name": "Layer", "fields": []}
        assert session.get.call_count == 1

    def test_throttle_invoked_per_attempt(self, monkeypatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr("ingestion.lib.arcgis._throttle", lambda host, *a, **kw: calls.append(host))
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.return_value = _make_response(json_body={"ok": True})

        _request_with_retry(session, "http://example.com", host="example.com")
        assert calls == ["example.com"]

    def test_transient_arcgis_envelope_retries_then_succeeds(self, monkeypatch) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = [
            _make_response(json_body={"error": {"code": 504001, "message": "timeout", "details": []}}),
            _make_response(json_body={"name": "OK"}),
        ]
        out = _request_with_retry(session, "http://example.com", host="example.com")
        assert out == {"name": "OK"}
        assert session.get.call_count == 2

    def test_permanent_arcgis_envelope_raises_immediately(self, monkeypatch) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.return_value = _make_response(
            json_body={"error": {"code": 400, "message": "bad request", "details": ["nope"]}}
        )
        with pytest.raises(ArcGISError, match=r"ArcGIS error 400"):
            _request_with_retry(session, "http://example.com", host="example.com")
        assert session.get.call_count == 1

    def test_http_500_retries_then_succeeds(self, monkeypatch) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = [
            _make_response(status_code=500, text="oops"),
            _make_response(json_body={"ok": True}),
        ]
        out = _request_with_retry(session, "http://example.com", host="example.com")
        assert out == {"ok": True}
        assert session.get.call_count == 2

    def test_http_503_exhausts_retries_then_raises(self, monkeypatch) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.return_value = _make_response(status_code=503, text="busy")
        with pytest.raises(ArcGISError, match=r"HTTP 503 after 3 retries"):
            _request_with_retry(session, "http://example.com", host="example.com")
        # 1 initial + 3 retries = 4 attempts
        assert session.get.call_count == 4

    def test_http_404_raises_immediately(self, monkeypatch) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.return_value = _make_response(status_code=404, text="not found")
        with pytest.raises(ArcGISError, match=r"HTTP 404"):
            _request_with_retry(session, "http://example.com", host="example.com")
        assert session.get.call_count == 1

    def test_network_error_retries_then_succeeds(self, monkeypatch) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = [
            requests_lib.exceptions.ConnectionError("conn reset"),
            _make_response(json_body={"ok": True}),
        ]
        out = _request_with_retry(session, "http://example.com", host="example.com")
        assert out == {"ok": True}
        assert session.get.call_count == 2


class TestFetchLayerMetadata:
    def test_happy_path_parses_and_writes_fixture(
        self,
        monkeypatch,
        tmp_fixture_dir,
        sample_layer_descriptor,
    ) -> None:
        # Mock _request_with_retry directly to avoid HTTP plumbing.
        captured: dict = {}

        def fake_request(session, url, *, params=None, host, **kw):
            captured["url"] = url
            captured["params"] = params
            captured["host"] = host
            return sample_layer_descriptor

        monkeypatch.setattr("ingestion.lib.arcgis._request_with_retry", fake_request)

        meta = fetch_layer_metadata(
            "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer",
            11,
            tmp_fixture_dir,
            layer_slug="huntingDistricts",
            timestamp="20260429T000000Z",
        )

        assert meta.name == "Deer Elk Lion Hunting Districts"
        assert meta.object_id_field == "OBJECTID"
        assert meta.max_record_count == 2000
        assert meta.geometry_type == "esriGeometryPolygon"
        assert meta.last_edit_date_ms == 1700000000000
        # excludeFromAllRequest=True field is dropped
        assert "Shape__Area" not in meta.out_fields
        assert "OBJECTID" in meta.out_fields
        assert "DISTRICT" in meta.out_fields

        # Fixture file written with expected name
        expected = tmp_fixture_dir / "huntingDistricts-11-metadata-20260429T000000Z.json"
        assert expected.exists()
        # Round-trip the JSON to confirm valid + non-empty
        loaded = json.loads(expected.read_text())
        assert loaded["name"] == "Deer Elk Lion Hunting Districts"

        # Host extracted from URL passed to _request_with_retry
        assert captured["host"] == "fwp-gis.mt.gov"
        assert captured["params"] == {"f": "json"}
        assert captured["url"].endswith("/MapServer/11")

    def test_missing_editing_info_yields_none(
        self, monkeypatch, tmp_fixture_dir, sample_layer_descriptor
    ) -> None:
        descriptor = dict(sample_layer_descriptor)
        descriptor.pop("editingInfo")
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: descriptor,
        )
        meta = fetch_layer_metadata(
            "https://example.com/svc/MapServer",
            1,
            tmp_fixture_dir,
            layer_slug="svc",
            timestamp="20260101T000000Z",
        )
        assert meta.last_edit_date_ms is None

    def test_creates_fixture_dir_if_missing(
        self, monkeypatch, tmp_path, sample_layer_descriptor
    ) -> None:
        nested = tmp_path / "nested" / "fixtures"
        assert not nested.exists()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: sample_layer_descriptor,
        )
        fetch_layer_metadata(
            "https://example.com/svc/MapServer",
            1,
            nested,
            layer_slug="svc",
            timestamp="20260101T000000Z",
        )
        assert nested.exists()

    def test_extracts_spatial_reference_wkid_prefers_latestWkid(
        self, monkeypatch, tmp_fixture_dir, sample_layer_descriptor
    ) -> None:
        """latestWkid is the modern EPSG code; prefer it over the legacy wkid."""
        descriptor = dict(sample_layer_descriptor)
        descriptor["extent"] = {
            "xmin": -1.3e7, "ymin": 5.5e6, "xmax": -1.2e7, "ymax": 6.1e6,
            "spatialReference": {"wkid": 102100, "latestWkid": 3857},
        }
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: descriptor,
        )
        meta = fetch_layer_metadata(
            "https://example.com/svc/MapServer",
            1,
            tmp_fixture_dir,
            layer_slug="svc",
            timestamp="20260101T000000Z",
        )
        assert meta.spatial_reference_wkid == 3857

    def test_extracts_spatial_reference_wkid_falls_back_to_wkid(
        self, monkeypatch, tmp_fixture_dir, sample_layer_descriptor
    ) -> None:
        """When latestWkid is absent, fall back to wkid."""
        descriptor = dict(sample_layer_descriptor)
        descriptor["extent"] = {"spatialReference": {"wkid": 4326}}
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: descriptor,
        )
        meta = fetch_layer_metadata(
            "https://example.com/svc/MapServer",
            1,
            tmp_fixture_dir,
            layer_slug="svc",
            timestamp="20260101T000000Z",
        )
        assert meta.spatial_reference_wkid == 4326

    def test_spatial_reference_wkid_none_when_extent_missing(
        self, monkeypatch, tmp_fixture_dir, sample_layer_descriptor
    ) -> None:
        descriptor = dict(sample_layer_descriptor)
        descriptor.pop("extent", None)
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: descriptor,
        )
        meta = fetch_layer_metadata(
            "https://example.com/svc/MapServer",
            1,
            tmp_fixture_dir,
            layer_slug="svc",
            timestamp="20260101T000000Z",
        )
        assert meta.spatial_reference_wkid is None


# ---------------------------------------------------------------------------
# fetch_features helpers
# ---------------------------------------------------------------------------


def _make_layer_metadata(
    *,
    max_record_count: int = 2,
    spatial_reference_wkid: int | None = None,
) -> LayerMetadata:
    """Build a LayerMetadata stub for fetch_features tests."""
    return LayerMetadata(
        name="Test Layer",
        object_id_field="OBJECTID",
        max_record_count=max_record_count,
        out_fields=("OBJECTID", "DISTRICT"),
        geometry_type="esriGeometryPolygon",
        last_edit_date_ms=None,
        raw={},
        spatial_reference_wkid=spatial_reference_wkid,
    )


def _make_polygon_feature(oid: int, *, lon_offset: float = 0.0) -> dict:
    """Polygon feature with the given OBJECTID; geometry varies via lon_offset."""
    base = -111.0 + lon_offset
    return {
        "type": "Feature",
        "properties": {"OBJECTID": oid, "DISTRICT": str(oid)},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [base, 46.0], [base + 1, 46.0], [base + 1, 47.0], [base, 47.0], [base, 46.0],
            ]],
        },
    }


class TestFetchFeatures:
    """Pagination, count cross-check, dedup, projection guard, fixture write."""

    def test_single_page_layer(self, monkeypatch, tmp_fixture_dir) -> None:
        """5 features, exceededTransferLimit=False, expected_count=5."""
        meta = _make_layer_metadata(max_record_count=2000)
        features = [_make_polygon_feature(i) for i in range(1, 6)]

        responses = [
            {"count": 5},  # count cross-check
            {"features": features, "exceededTransferLimit": False},  # page 1 (non-empty, not exceeded)
            {"features": [], "exceededTransferLimit": False},  # empty terminator
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )

        out = fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )
        assert len(out) == 5
        fixture = tmp_fixture_dir / "svc-1-features-20260101T000000Z.geojson"
        assert fixture.exists()
        loaded = json.loads(fixture.read_text())
        assert loaded["type"] == "FeatureCollection"
        assert loaded["crs"]["properties"]["name"] == "EPSG:4326"
        assert len(loaded["features"]) == 5
        assert responses == []  # confirms the empty-terminator page was actually fetched

    def test_exact_n_times_max_record_count_boundary(
        self, monkeypatch, tmp_fixture_dir
    ) -> None:
        """maxRecordCount=2, expected=4 → 2 full pages + 1 empty terminator."""
        meta = _make_layer_metadata(max_record_count=2)
        responses = [
            {"count": 4},
            {"features": [_make_polygon_feature(1), _make_polygon_feature(2)],
             "exceededTransferLimit": True},
            {"features": [_make_polygon_feature(3), _make_polygon_feature(4)],
             "exceededTransferLimit": True},
            {"features": [], "exceededTransferLimit": False},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        out = fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )
        assert len(out) == 4
        # Confirm we consumed all 4 responses (count + 3 pages) — no leftovers
        assert responses == []

    def test_multi_page_mid_layer(self, monkeypatch, tmp_fixture_dir) -> None:
        """maxRecordCount=2, expected=3 → page1 [f1,f2] exceeded, page2 [f3] not exceeded, page3 [] terminator."""
        meta = _make_layer_metadata(max_record_count=2)
        responses = [
            {"count": 3},
            {"features": [_make_polygon_feature(1), _make_polygon_feature(2)],
             "exceededTransferLimit": True},
            {"features": [_make_polygon_feature(3)], "exceededTransferLimit": False},
            {"features": [], "exceededTransferLimit": False},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        out = fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )
        assert len(out) == 3
        # The non-empty page2 alone does NOT terminate the loop — page3 was fetched.
        assert responses == []

    def test_objectid_dedup(self, monkeypatch, tmp_fixture_dir) -> None:
        """Page 2 returns OBJECTID=1 (already seen on page 1); dup is skipped."""
        meta = _make_layer_metadata(max_record_count=2)
        responses = [
            {"count": 3},
            {"features": [_make_polygon_feature(1), _make_polygon_feature(2)],
             "exceededTransferLimit": True},
            {"features": [_make_polygon_feature(1), _make_polygon_feature(3)],
             "exceededTransferLimit": False},
            {"features": [], "exceededTransferLimit": False},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        out = fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )
        oids = [_read_objectid(f) for f in out]
        assert sorted(oids) == [1, 2, 3]  # type: ignore[type-var]
        assert len(out) == 3

    def test_count_mismatch_raises(self, monkeypatch, tmp_fixture_dir) -> None:
        meta = _make_layer_metadata(max_record_count=2000)
        responses = [
            {"count": 10},
            {"features": [_make_polygon_feature(i) for i in range(1, 9)],
             "exceededTransferLimit": False},  # only 8, not exceeded
            {"features": [], "exceededTransferLimit": False},  # empty terminator
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        with pytest.raises(ArcGISError, match=r"feature count mismatch"):
            fetch_features(
                "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
                layer_slug="svc", timestamp="20260101T000000Z",
            )

    def test_empty_layer(self, monkeypatch, tmp_fixture_dir) -> None:
        meta = _make_layer_metadata(max_record_count=2000)
        responses = [
            {"count": 0},
            {"features": [], "exceededTransferLimit": False},
        ]
        proj_calls: list[Any] = []
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        # Wrap the projection guard to confirm it's NOT called for empty layers
        original = _check_and_fix_projection
        def tracked(features):
            proj_calls.append(features)
            return original(features)
        monkeypatch.setattr("ingestion.lib.arcgis._check_and_fix_projection", tracked)

        out = fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )
        assert out == []
        assert proj_calls == []  # projection guard skipped on empty layer
        # Empty fixture still written
        fixture = tmp_fixture_dir / "svc-1-features-20260101T000000Z.geojson"
        assert fixture.exists()
        loaded = json.loads(fixture.read_text())
        assert loaded["features"] == []

    def test_web_mercator_response_reprojected(
        self, monkeypatch, tmp_fixture_dir
    ) -> None:
        """Coords arrive in EPSG:3857 (e.g., Helena ~ -12826000, 5688000)
        despite the GeoJSON envelope claiming 4326; projection guard rewrites them."""
        meta = _make_layer_metadata(max_record_count=2000)
        # Fabricate one feature with Web Mercator coords
        helena_3857 = {
            "type": "Feature",
            "properties": {"OBJECTID": 1, "DISTRICT": "test"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-12826000.0, 5688000.0], [-12825000.0, 5688000.0],
                    [-12825000.0, 5689000.0], [-12826000.0, 5689000.0],
                    [-12826000.0, 5688000.0],
                ]],
            },
        }
        responses = [
            {"count": 1},
            {"features": [helena_3857], "exceededTransferLimit": False},  # non-empty, not exceeded
            {"features": [], "exceededTransferLimit": False},  # empty terminator
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        out = fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )
        # First coord is now in MT range (lon ~ -115, lat ~ 45)
        x, y = out[0]["geometry"]["coordinates"][0][0]
        assert -116 < x < -114
        assert 45 < y < 46
        # Fixture should also be in WGS84
        fixture = json.loads(
            (tmp_fixture_dir / "svc-1-features-20260101T000000Z.geojson").read_text()
        )
        fx, fy = fixture["features"][0]["geometry"]["coordinates"][0][0]
        assert -116 < fx < -114
        assert 45 < fy < 46

    def test_where_clause_uses_metadata_object_id_field(
        self, monkeypatch, tmp_fixture_dir,
    ) -> None:
        """When the layer's OID column is not OBJECTID, the where clause must
        use the metadata field — otherwise the count query miscounts or fails."""
        meta = LayerMetadata(
            name="Test",
            object_id_field="FID",
            max_record_count=2000,
            out_fields=("FID", "DISTRICT"),
            geometry_type="esriGeometryPolygon",
            last_edit_date_ms=None,
            raw={},
        )
        captured_params: list[dict] = []

        def fake_request(session, url, *, params=None, host, **kw):
            captured_params.append(params or {})
            if params and params.get("returnCountOnly") == "true":
                return {"count": 0}
            return {"features": [], "exceededTransferLimit": False}

        monkeypatch.setattr("ingestion.lib.arcgis._request_with_retry", fake_request)

        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )
        # All requests should use the layer's actual OID column, not hardcoded "OBJECTID"
        assert all(p.get("where") == "FID>=0" for p in captured_params)


class TestBuildSourceCitation:
    def _meta(self, *, last_edit_date_ms: int | None = None, name: str = "Deer Elk Lion HDs") -> LayerMetadata:
        return LayerMetadata(
            name=name,
            object_id_field="OBJECTID",
            max_record_count=2000,
            out_fields=("OBJECTID",),
            geometry_type="esriGeometryPolygon",
            last_edit_date_ms=last_edit_date_ms,
            raw={},
        )

    def test_publication_date_is_jan_1_of_license_year(self) -> None:
        """Per ADR-014: publication_date = Jan 1 of REGYEAR (i.e. license_year)."""
        sc = build_source_citation(
            service_url="https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer",
            layer_id=11,
            metadata=self._meta(last_edit_date_ms=1700000000000),
            license_year=2026,
            state_slug="mt-fwp",
            agency="Montana Fish, Wildlife & Parks",
        )
        assert sc.publication_date == "2026-01-01"

    def test_publication_date_ignores_lastedit_per_adr014(self) -> None:
        """Regression: lastEditDate is an edit timestamp, not a publication
        date. ADR-014 prescribes Jan 1 of license_year regardless of
        last_edit_date_ms — even when lastEditDate would suggest a different
        year. The metadata edit timestamp is preserved on LayerMetadata for
        forensic value but never bleeds into publication_date.
        """
        # lastEditDate=1700000000000 → 2023-11-14 if used (wrong); ADR-014 → 2025-01-01
        sc = build_source_citation(
            service_url="https://example.com/svc/MapServer",
            layer_id=1,
            metadata=self._meta(last_edit_date_ms=1700000000000),
            license_year=2025,
            state_slug="mt-fwp",
            agency="Montana Fish, Wildlife & Parks",
        )
        assert sc.publication_date == "2025-01-01"
        assert sc.publication_date != "2023-11-14"

    def test_publication_date_unaffected_by_missing_lastedit(self) -> None:
        """When lastEditDate is absent, publication_date is still Jan 1 of
        license_year (no fallback needed — license_year is required and
        carries the regulation-cycle year)."""
        sc = build_source_citation(
            service_url="https://example.com/svc/MapServer",
            layer_id=1,
            metadata=self._meta(last_edit_date_ms=None),
            license_year=2026,
            state_slug="mt-fwp",
            agency="Montana Fish, Wildlife & Parks",
        )
        assert sc.publication_date == "2026-01-01"

    def test_document_type_is_gis_layer(self) -> None:
        sc = build_source_citation(
            service_url="https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer",
            layer_id=11,
            metadata=self._meta(last_edit_date_ms=1700000000000),
            license_year=2026,
            state_slug="mt-fwp",
            agency="Montana Fish, Wildlife & Parks",
        )
        assert sc.document_type == "gis_layer"

    def test_id_matches_spec_format(self) -> None:
        sc = build_source_citation(
            service_url="https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer",
            layer_id=11,
            metadata=self._meta(),
            license_year=2026,
            state_slug="mt-fwp",
            agency="Montana Fish, Wildlife & Parks",
        )
        assert sc.id == "mt-fwp-arcgis-huntingDistricts-11-2026"

    def test_url_includes_layer_id(self) -> None:
        sc = build_source_citation(
            service_url="https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer",
            layer_id=11,
            metadata=self._meta(),
            license_year=2026,
            state_slug="mt-fwp",
            agency="Montana Fish, Wildlife & Parks",
        )
        assert sc.url.endswith("/MapServer/11")

    def test_title_includes_layer_name_and_id(self) -> None:
        sc = build_source_citation(
            service_url="https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer",
            layer_id=11,
            metadata=self._meta(name="Deer Elk Lion Hunting Districts"),
            license_year=2026,
            state_slug="mt-fwp",
            agency="Montana Fish, Wildlife & Parks",
        )
        assert sc.title == "Deer Elk Lion Hunting Districts (Layer 11)"

    def test_agency_required_no_default(self) -> None:
        """No default — caller MUST pass `agency` (state-agnosticism)."""
        import inspect
        sig = inspect.signature(build_source_citation)
        assert sig.parameters["agency"].default is inspect.Parameter.empty

    def test_slug_from_service_url(self) -> None:
        from ingestion.lib.arcgis import _slug_from_service
        assert (
            _slug_from_service("https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer")
            == "huntingDistricts"
        )
        assert (
            _slug_from_service("https://example.com/svc/FeatureServer")
            == "svc"
        )
        # Trailing slash tolerated
        assert (
            _slug_from_service("https://example.com/abc/MapServer/")
            == "abc"
        )


class TestErrorHandlingAndLogging:
    def test_fetch_layer_metadata_malformed_response_raises_arcgiserror(
        self, monkeypatch, tmp_fixture_dir
    ) -> None:
        """KeyError on missing top-level fields is caught and re-raised with context."""
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: {"objectIdField": "OBJECTID"},  # missing 'name', etc.
        )
        with pytest.raises(ArcGISError, match=r"malformed layer metadata"):
            fetch_layer_metadata(
                "https://example.com/svc/MapServer", 1, tmp_fixture_dir,
                layer_slug="svc", timestamp="20260101T000000Z",
            )

    def test_fetch_features_missing_count_raises_arcgiserror(
        self, monkeypatch, tmp_fixture_dir
    ) -> None:
        """returnCountOnly response without 'count' key raises ArcGISError, not KeyError."""
        meta = _make_layer_metadata(max_record_count=2000)
        # First response is the count query; return malformed body (no 'count')
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: {"foo": "bar"},
        )
        with pytest.raises(ArcGISError, match=r"missing 'count'"):
            fetch_features(
                "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
                layer_slug="svc", timestamp="20260101T000000Z",
            )

    def test_projection_fallback_emits_warning_log(self, monkeypatch, caplog) -> None:
        """When _check_and_fix_projection reprojects, a WARNING is logged."""
        helena_3857 = {
            "type": "Feature",
            "properties": {"OBJECTID": 1},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-12826000.0, 5688000.0], [-12825000.0, 5688000.0],
                    [-12825000.0, 5689000.0], [-12826000.0, 5689000.0],
                    [-12826000.0, 5688000.0],
                ]],
            },
        }
        with caplog.at_level(logging.WARNING, logger="ingestion.lib.arcgis"):
            _check_and_fix_projection([helena_3857])
        assert any("projection fallback" in record.message for record in caplog.records)

    def test_dedup_emits_warning_log(self, monkeypatch, tmp_fixture_dir, caplog) -> None:
        """When fetch_features drops duplicates, a WARNING is logged with the OIDs."""
        meta = _make_layer_metadata(max_record_count=2)
        responses = [
            {"count": 3},
            {"features": [_make_polygon_feature(1), _make_polygon_feature(2)],
             "exceededTransferLimit": True},
            {"features": [_make_polygon_feature(1), _make_polygon_feature(3)],  # OID 1 is dup
             "exceededTransferLimit": False},
            {"features": [], "exceededTransferLimit": False},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        with caplog.at_level(logging.WARNING, logger="ingestion.lib.arcgis"):
            fetch_features(
                "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
                layer_slug="svc", timestamp="20260101T000000Z",
            )
        assert any("OBJECTID dedup fired" in record.message for record in caplog.records)

    def test_empty_layer_emits_warning_log(self, monkeypatch, tmp_fixture_dir, caplog) -> None:
        """When fetch_features sees expected_count=0, a WARNING is logged."""
        meta = _make_layer_metadata(max_record_count=2000)
        responses = [
            {"count": 0},
            {"features": [], "exceededTransferLimit": False},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        with caplog.at_level(logging.WARNING, logger="ingestion.lib.arcgis"):
            fetch_features(
                "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
                layer_slug="svc", timestamp="20260101T000000Z",
            )
        assert any("returned 0 features" in record.message for record in caplog.records)
