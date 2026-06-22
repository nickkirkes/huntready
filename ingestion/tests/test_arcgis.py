"""Unit tests for ingestion.lib.arcgis."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
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
    _require_objectid,
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

    def test_geometry_collection_recovers_when_polygon_area_preserved(
        self, caplog
    ) -> None:
        # A GC with a Polygon + a zero-area Point is a topological artifact, not
        # data loss. Polygonal parts preserve area → recover with WARNING.
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
        with caplog.at_level("WARNING", logger="ingestion.lib.arcgis"):
            wkt = geojson_to_multipolygon_wkt(feature)
        assert wkt.startswith("MULTIPOLYGON")
        assert any(
            "OBJECTID=99" in r.getMessage() and "non-polygonal artifacts" in r.getMessage()
            for r in caplog.records
        )

    def test_geometry_collection_raises_when_area_not_preserved(self) -> None:
        # Two overlapping polygons in a GC: parsed.area = sum (counts overlap
        # twice); unary_union.area = single coverage (counts overlap once).
        # Areas don't match → raise (genuine data loss).
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 12, "DISTRICT": "OVL"},
            "geometry": {
                "type": "GeometryCollection",
                "geometries": [
                    {
                        "type": "Polygon",
                        "coordinates": [[[-111.0, 46.0], [-109.0, 46.0], [-109.0, 48.0], [-111.0, 48.0], [-111.0, 46.0]]],
                    },
                    {
                        "type": "Polygon",
                        "coordinates": [[[-110.0, 47.0], [-108.0, 47.0], [-108.0, 49.0], [-110.0, 49.0], [-110.0, 47.0]]],
                    },
                ],
            },
        }
        with pytest.raises(ArcGISError, match=r"OBJECTID=12.*do not preserve area"):
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

    def test_geometry_with_missing_coordinates_raises_arcgiserror(self) -> None:
        """A Polygon geometry without a `coordinates` key would otherwise
        raise KeyError on the downstream coords access. Convert to ArcGISError
        with the OID surfaced so callers see a structured library error
        instead of an unhandled crash.
        """
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 99},
            "geometry": {"type": "Polygon"},  # no coordinates key
        }
        with pytest.raises(
            ArcGISError, match=r"OBJECTID=99.*coordinates",
        ):
            _check_and_fix_projection([feature])

    def test_geometry_with_null_coordinates_raises_arcgiserror(self) -> None:
        """coordinates=None must raise ArcGISError. (Without the guard,
        `_coordinates_in_wgs84_range(None)` returns True and the feature
        passes through silently — an even worse failure mode.)
        """
        feature = {
            "type": "Feature",
            "properties": {"OBJECTID": 7},
            "geometry": {"type": "Polygon", "coordinates": None},
        }
        with pytest.raises(
            ArcGISError, match=r"OBJECTID=7.*coordinates",
        ):
            _check_and_fix_projection([feature])

    def test_geometry_with_non_list_coordinates_raises_arcgiserror(self) -> None:
        """A scalar/string in `coordinates` is malformed; raise loudly."""
        feature = {
            "type": "Feature",
            "attributes": {"OBJECTID": 5},
            "geometry": {"type": "Polygon", "coordinates": "not-a-list"},
        }
        with pytest.raises(
            ArcGISError, match=r"OBJECTID=5.*coordinates",
        ):
            _check_and_fix_projection([feature])


def _make_response(
    *,
    status_code: int = 200,
    json_body: dict | None = None,
    text: str = "",
    headers: dict | None = None,
) -> MagicMock:
    """Build a mock requests.Response with `.status_code`, `.json()`, `.text`, `.headers`."""
    resp = MagicMock(spec=requests_lib.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    resp.headers = headers or {}
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

    def test_http_429_retries_then_succeeds(self, monkeypatch) -> None:
        """HTTP 429 (Too Many Requests) is transient — back off and retry,
        not abort. ArcGIS uses 429 for throttling.
        """
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = [
            _make_response(status_code=429, text="rate limit exceeded"),
            _make_response(json_body={"ok": True}),
        ]
        out = _request_with_retry(session, "http://example.com", host="example.com")
        assert out == {"ok": True}
        assert session.get.call_count == 2

    def test_http_408_retries_then_succeeds(self, monkeypatch) -> None:
        """HTTP 408 (Request Timeout) is transient — retry per RFC 7231 §6.5.7."""
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = [
            _make_response(status_code=408, text="timeout"),
            _make_response(json_body={"ok": True}),
        ]
        out = _request_with_retry(session, "http://example.com", host="example.com")
        assert out == {"ok": True}
        assert session.get.call_count == 2

    def test_http_429_exhausts_retries_then_raises(self, monkeypatch) -> None:
        """If 429 persists across all retries, raise — but only after
        actually trying (not on first response like 4xx).
        """
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.return_value = _make_response(status_code=429, text="busy")
        with pytest.raises(ArcGISError, match=r"HTTP 429 after 3 retries"):
            _request_with_retry(session, "http://example.com", host="example.com")
        # 1 initial + 3 retries = 4 attempts
        assert session.get.call_count == 4

    def test_http_429_honors_retry_after_header(self, monkeypatch) -> None:
        """Retry-After header value drives sleep duration when present.

        Note: the throttle helper also calls time.sleep on subsequent attempts
        (~500ms), so we assert on the FIRST sleep (the retry backoff) rather
        than the full sequence.
        """
        sleeps: list[float] = []
        monkeypatch.setattr(
            "ingestion.lib.arcgis.time.sleep", lambda s: sleeps.append(s),
        )
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = [
            _make_response(
                status_code=429,
                text="busy",
                headers={"Retry-After": "5"},
            ),
            _make_response(json_body={"ok": True}),
        ]
        _request_with_retry(session, "http://example.com", host="example.com")
        assert sleeps[0] == 5.0  # first sleep == Retry-After, not the 1.0 default backoff

    def test_retry_after_capped_falls_back_to_backoff(self, monkeypatch) -> None:
        """Retry-After exceeding the cap is ignored; fall back to backoff.

        Defends against a buggy/malicious server returning a huge value
        that would stall ingestion.
        """
        sleeps: list[float] = []
        monkeypatch.setattr(
            "ingestion.lib.arcgis.time.sleep", lambda s: sleeps.append(s),
        )
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = [
            _make_response(
                status_code=429,
                text="busy",
                headers={"Retry-After": "999"},  # exceeds 30s cap
            ),
            _make_response(json_body={"ok": True}),
        ]
        _request_with_retry(session, "http://example.com", host="example.com")
        # Falls back to backoff schedule first entry (1.0s)
        assert sleeps[0] == 1.0

    def test_retry_after_invalid_falls_back_to_backoff(self, monkeypatch) -> None:
        """Non-numeric Retry-After (e.g. HTTP-date format, junk) is ignored."""
        sleeps: list[float] = []
        monkeypatch.setattr(
            "ingestion.lib.arcgis.time.sleep", lambda s: sleeps.append(s),
        )
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = [
            _make_response(
                status_code=429,
                text="busy",
                headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
            ),
            _make_response(json_body={"ok": True}),
        ]
        _request_with_retry(session, "http://example.com", host="example.com")
        assert sleeps[0] == 1.0


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

    def test_falls_back_to_fields_oid_when_top_level_missing(
        self, monkeypatch, tmp_fixture_dir, sample_layer_descriptor
    ) -> None:
        # Real-world: MT FWP's huntingDistricts MapServer omits the top-level
        # objectIdField but the OID column is present in fields[].
        descriptor = dict(sample_layer_descriptor)
        descriptor.pop("objectIdField", None)
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
        assert meta.object_id_field == "OBJECTID"

    def test_raises_when_no_oid_anywhere(
        self, monkeypatch, tmp_fixture_dir, sample_layer_descriptor
    ) -> None:
        descriptor = dict(sample_layer_descriptor)
        descriptor.pop("objectIdField", None)
        descriptor["fields"] = [
            {"name": "DISTRICT", "type": "esriFieldTypeString"},
            {"name": "REG", "type": "esriFieldTypeString"},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: descriptor,
        )
        with pytest.raises(ArcGISError, match=r"missing 'objectIdField'"):
            fetch_layer_metadata(
                "https://example.com/svc/MapServer",
                1,
                tmp_fixture_dir,
                layer_slug="svc",
                timestamp="20260101T000000Z",
            )


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

    def test_terminates_on_empty_page_even_when_exceeded_true(
        self, monkeypatch, tmp_fixture_dir,
    ) -> None:
        """A misbehaving server can return features=[] with
        exceededTransferLimit=True. The previous "not exceeded AND empty"
        rule would spin forever on that response. The fix terminates on
        any empty page regardless of the exceeded flag.
        """
        meta = _make_layer_metadata(max_record_count=2)
        responses = [
            {"count": 2},
            # First page returns 2 features and claims more.
            {"features": [_make_polygon_feature(1), _make_polygon_feature(2)],
             "exceededTransferLimit": True},
            # Server then returns empty + still claims more (the bug case).
            # Loop must terminate here, not spin.
            {"features": [], "exceededTransferLimit": True},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        out = fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )
        assert len(out) == 2
        assert responses == []  # Both pages consumed exactly once — no spin

    def test_iteration_cap_raises_on_pathological_server(
        self, monkeypatch, tmp_fixture_dir,
    ) -> None:
        """If a server keeps returning non-empty pages with exceededTransferLimit=True
        forever (e.g., always serving the same OIDs that get deduped), the iteration
        cap fires with a clear ArcGISError before the loop runs unbounded.
        """
        meta = _make_layer_metadata(max_record_count=2)
        # expected_count=2: pages_needed=1, max_iterations = 1 + 3 = 4.
        # The server returns the same exceeded=True non-empty page forever.
        # All features after page 1 are dedup duplicates, so dedup_features stays
        # at 2 — but the loop keeps fetching because pages aren't empty.
        repeating_page = {
            "features": [_make_polygon_feature(1), _make_polygon_feature(2)],
            "exceededTransferLimit": True,
        }

        # First response is the count query; everything after is the repeating page.
        call_count = {"n": 0}

        def fake_request(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"count": 2}
            return repeating_page

        monkeypatch.setattr("ingestion.lib.arcgis._request_with_retry", fake_request)

        with pytest.raises(
            ArcGISError, match=r"pagination loop exceeded max iterations \(4\)",
        ):
            fetch_features(
                "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
                layer_slug="svc", timestamp="20260101T000000Z",
            )

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

    def test_dedup_uses_metadata_object_id_field(
        self, monkeypatch, tmp_fixture_dir,
    ) -> None:
        """Dedup must read the OID from the layer's actual OID column.

        For a layer with `object_id_field="OBJECTID_1"`, the OID lives at
        `properties["OBJECTID_1"]`. If `_read_objectid` only tried the
        common keys (OBJECTID/objectid/FID) and fell through to
        `feature["id"]` (which the response doesn't include here), every
        feature would resolve to the same fallback value — collapsing to
        one survivor and triggering a confusing count-mismatch error
        instead of producing the right rows.
        """
        meta = LayerMetadata(
            name="Test",
            object_id_field="OBJECTID_1",
            max_record_count=2000,
            out_fields=("OBJECTID_1", "DISTRICT"),
            geometry_type="esriGeometryPolygon",
            last_edit_date_ms=None,
            raw={},
        )

        def make_feat(oid: int) -> dict:
            return {
                "type": "Feature",
                # No top-level "id" — force the helper to read from properties
                "properties": {"OBJECTID_1": oid, "DISTRICT": str(oid)},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-111.0, 46.0], [-110.0, 46.0], [-110.0, 47.0], [-111.0, 47.0], [-111.0, 46.0],
                    ]],
                },
            }

        # 3 distinct OBJECTID_1 values across two pages, with one duplicate
        # (OID 2 appears in both pages — dedup should drop the second).
        responses = [
            {"count": 3},
            {"features": [make_feat(1), make_feat(2)], "exceededTransferLimit": True},
            {"features": [make_feat(2), make_feat(3)], "exceededTransferLimit": False},
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
        # Must return exactly 3 distinct features (1, 2, 3) — not 1 (collapse)
        # or 4 (no dedup). Either failure mode would also trip the count
        # cross-check, so a passing test here proves dedup looked at OBJECTID_1.
        assert len(out) == 3
        oids = {feat["properties"]["OBJECTID_1"] for feat in out}
        assert oids == {1, 2, 3}


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


class TestUserAgent:
    """User-Agent must NOT bake a personal email into source. The contact
    suffix is opt-in via the HUNTREADY_INGESTION_CONTACT env var."""

    def test_default_user_agent_has_no_contact_when_env_unset(
        self, monkeypatch
    ) -> None:
        from ingestion.lib.arcgis import _default_user_agent
        monkeypatch.delenv("HUNTREADY_INGESTION_CONTACT", raising=False)
        ua = _default_user_agent()
        assert ua == "HuntReady-Ingestion/1.0"
        assert "@" not in ua  # no email anywhere
        assert "contact" not in ua.lower()

    def test_default_user_agent_includes_contact_when_env_set(
        self, monkeypatch
    ) -> None:
        from ingestion.lib.arcgis import _default_user_agent
        monkeypatch.setenv("HUNTREADY_INGESTION_CONTACT", "ingest@example.com")
        ua = _default_user_agent()
        assert ua == "HuntReady-Ingestion/1.0 (contact: ingest@example.com)"

    def test_default_user_agent_strips_whitespace_and_treats_blank_as_unset(
        self, monkeypatch
    ) -> None:
        from ingestion.lib.arcgis import _default_user_agent
        monkeypatch.setenv("HUNTREADY_INGESTION_CONTACT", "   ")
        ua = _default_user_agent()
        assert ua == "HuntReady-Ingestion/1.0"

    def test_session_uses_default_user_agent_at_call_time(
        self, monkeypatch
    ) -> None:
        """_build_session() with no explicit UA reads env at call time, not import time —
        operators can set the env var after import and still get the contact suffix.
        """
        from ingestion.lib.arcgis import _build_session
        monkeypatch.setenv("HUNTREADY_INGESTION_CONTACT", "operator@example.com")
        session = _build_session()
        assert (
            session.headers["User-Agent"]
            == "HuntReady-Ingestion/1.0 (contact: operator@example.com)"
        )

    def test_session_accepts_explicit_user_agent_override(self) -> None:
        from ingestion.lib.arcgis import _build_session
        session = _build_session(user_agent="CustomUA/2.0")
        assert session.headers["User-Agent"] == "CustomUA/2.0"

    def test_no_personal_email_in_module_source(self) -> None:
        """Regression: ensure no personal email gets re-introduced as a source-level constant."""
        import inspect
        from pathlib import Path

        from ingestion.lib import arcgis
        src = Path(inspect.getfile(arcgis)).read_text(encoding="utf-8")
        # The literal email that triggered the violation
        assert "nick@rowdycloud.io" not in src
        # Defensive: no rowdycloud-domain reference anywhere in non-comment code
        for line in src.splitlines():
            if line.lstrip().startswith("#"):
                continue  # comments may explain examples
            if "@" in line and "rowdycloud" in line:
                pytest.fail(f"personal email pattern found in source: {line!r}")


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


class TestFetchFeaturesManifest:
    """Manifest file written by fetch_features: existence, shape, hash properties."""

    # ------------------------------------------------------------------
    # Shared stub builders
    # ------------------------------------------------------------------

    def _responses_for_two_features(self) -> list[dict]:
        """Standard stub: count=2, one page of 2 features, empty terminator."""
        return [
            {"count": 2},
            {
                "features": [_make_polygon_feature(1), _make_polygon_feature(2)],
                "exceededTransferLimit": False,
            },
            {"features": [], "exceededTransferLimit": False},
        ]

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_manifest_file_written(self, monkeypatch, tmp_fixture_dir) -> None:
        """After a successful fetch, the manifest file exists with the expected name."""
        meta = _make_layer_metadata(max_record_count=2000)
        responses = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )

        manifest_path = tmp_fixture_dir / "svc-1-manifest-20260101T000000Z.json"
        assert manifest_path.exists()
        assert responses == []

    def test_manifest_required_fields(self, monkeypatch, tmp_fixture_dir) -> None:
        """Manifest contains all 7 required fields with correct types."""
        meta = _make_layer_metadata(max_record_count=2000)
        responses = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )

        manifest = json.loads(
            (tmp_fixture_dir / "svc-1-manifest-20260101T000000Z.json").read_text()
        )
        assert isinstance(manifest["features_count"], int)
        assert isinstance(manifest["fetched_at"], str)
        assert isinstance(manifest["hash_distribution"], dict)
        assert isinstance(manifest["layer_hash"], str)
        assert isinstance(manifest["source_layer_max_record_count"], int)
        assert isinstance(manifest["source_layer_object_id_field"], str)
        assert isinstance(manifest["source_url"], str)
        assert responses == []

    def test_manifest_features_count_matches_return(self, monkeypatch, tmp_fixture_dir) -> None:
        """manifest['features_count'] equals the number of features returned."""
        meta = _make_layer_metadata(max_record_count=2000)
        responses = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        returned = fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )

        manifest = json.loads(
            (tmp_fixture_dir / "svc-1-manifest-20260101T000000Z.json").read_text()
        )
        assert manifest["features_count"] == len(returned)
        assert responses == []

    def test_manifest_hash_distribution_keys(self, monkeypatch, tmp_fixture_dir) -> None:
        """hash_distribution has exactly 256 keys covering '00'..'ff'."""
        meta = _make_layer_metadata(max_record_count=2000)
        responses = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )

        manifest = json.loads(
            (tmp_fixture_dir / "svc-1-manifest-20260101T000000Z.json").read_text()
        )
        dist = manifest["hash_distribution"]
        assert len(dist) == 256
        expected_keys = {f"{i:02x}" for i in range(256)}
        assert set(dist.keys()) == expected_keys
        assert responses == []

    def test_manifest_hash_distribution_sums(self, monkeypatch, tmp_fixture_dir) -> None:
        """sum of hash_distribution values equals features_count."""
        meta = _make_layer_metadata(max_record_count=2000)
        responses = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )

        manifest = json.loads(
            (tmp_fixture_dir / "svc-1-manifest-20260101T000000Z.json").read_text()
        )
        assert sum(manifest["hash_distribution"].values()) == manifest["features_count"]
        assert responses == []

    def test_manifest_layer_hash_deterministic(self, monkeypatch, tmp_path) -> None:
        """Two runs with identical features and timestamp produce byte-identical manifests."""
        meta = _make_layer_metadata(max_record_count=2000)
        timestamp = "20260101T000000Z"
        slug = "svc"
        layer_id = 1

        run1_dir = tmp_path / "run1"
        run1_dir.mkdir()
        responses1 = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses1.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        fetch_features(
            "https://example.com/svc/MapServer", layer_id, meta, run1_dir,
            layer_slug=slug, timestamp=timestamp,
        )

        run2_dir = tmp_path / "run2"
        run2_dir.mkdir()
        responses2 = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses2.pop(0),
        )
        fetch_features(
            "https://example.com/svc/MapServer", layer_id, meta, run2_dir,
            layer_slug=slug, timestamp=timestamp,
        )

        manifest_name = f"{slug}-{layer_id}-manifest-{timestamp}.json"
        bytes1 = (run1_dir / manifest_name).read_bytes()
        bytes2 = (run2_dir / manifest_name).read_bytes()
        assert bytes1 == bytes2
        assert responses1 == []
        assert responses2 == []

    def test_manifest_layer_hash_changes_when_features_change(
        self, monkeypatch, tmp_path
    ) -> None:
        """Changing a feature attribute changes the layer_hash."""
        meta = _make_layer_metadata(max_record_count=2000)
        timestamp = "20260101T000000Z"

        # Run 1: features with DISTRICT "1" and "2"
        run1_dir = tmp_path / "run1"
        run1_dir.mkdir()
        feat_a1 = _make_polygon_feature(1)
        feat_a2 = _make_polygon_feature(2)
        responses1 = [
            {"count": 2},
            {"features": [feat_a1, feat_a2], "exceededTransferLimit": False},
            {"features": [], "exceededTransferLimit": False},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses1.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, run1_dir,
            layer_slug="svc", timestamp=timestamp,
        )

        # Run 2: modify one feature's attribute
        run2_dir = tmp_path / "run2"
        run2_dir.mkdir()
        feat_b1 = _make_polygon_feature(1)
        feat_b1["properties"]["DISTRICT"] = "CHANGED"
        feat_b2 = _make_polygon_feature(2)
        responses2 = [
            {"count": 2},
            {"features": [feat_b1, feat_b2], "exceededTransferLimit": False},
            {"features": [], "exceededTransferLimit": False},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses2.pop(0),
        )
        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, run2_dir,
            layer_slug="svc", timestamp=timestamp,
        )

        manifest1 = json.loads((run1_dir / "svc-1-manifest-20260101T000000Z.json").read_text())
        manifest2 = json.loads((run2_dir / "svc-1-manifest-20260101T000000Z.json").read_text())
        assert manifest1["layer_hash"] != manifest2["layer_hash"]
        assert responses1 == []
        assert responses2 == []

    def test_manifest_object_id_field_uses_parsed_value(
        self, monkeypatch, tmp_fixture_dir
    ) -> None:
        """source_layer_object_id_field reflects the value from LayerMetadata.

        When fetch_layer_metadata's field-scan fallback resolves objectIdField to
        "OBJECTID" (because the top-level key was missing), that resolved value
        is stored on LayerMetadata.object_id_field and written into the manifest.
        """
        # Simulate the resolved metadata where objectIdField was absent at the
        # top level but discovered via field scan (field type esriFieldTypeOID).
        meta = LayerMetadata(
            name="Test Layer",
            object_id_field="OBJECTID",  # what the field-scan fallback would yield
            max_record_count=2000,
            out_fields=("OBJECTID", "DISTRICT"),
            geometry_type="esriGeometryPolygon",
            last_edit_date_ms=None,
            raw={},
        )
        responses = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )

        manifest = json.loads(
            (tmp_fixture_dir / "svc-1-manifest-20260101T000000Z.json").read_text()
        )
        assert manifest["source_layer_object_id_field"] == "OBJECTID"
        assert responses == []

    def test_manifest_source_url_includes_layer_id(self, monkeypatch, tmp_fixture_dir) -> None:
        """manifest['source_url'] ends with '/{layer_id}'."""
        meta = _make_layer_metadata(max_record_count=2000)
        responses = self._responses_for_two_features()
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )

        manifest = json.loads(
            (tmp_fixture_dir / "svc-1-manifest-20260101T000000Z.json").read_text()
        )
        assert manifest["source_url"].endswith("/1")
        assert responses == []

    def test_manifest_written_for_empty_layer(self, monkeypatch, tmp_fixture_dir) -> None:
        """A layer that returns 0 features still writes a manifest with features_count=0,
        so that N->0 transitions show up in `git diff` rather than silently removing the file.
        """
        meta = _make_layer_metadata(max_record_count=2000)
        # count=0 + one empty page (the pagination loop runs at least once until it sees []).
        responses: list[dict] = [
            {"count": 0},
            {"features": [], "exceededTransferLimit": False},
        ]
        monkeypatch.setattr(
            "ingestion.lib.arcgis._request_with_retry",
            lambda *a, **kw: responses.pop(0),
        )
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        fetch_features(
            "https://example.com/svc/MapServer", 1, meta, tmp_fixture_dir,
            layer_slug="svc", timestamp="20260101T000000Z",
        )

        manifest_path = tmp_fixture_dir / "svc-1-manifest-20260101T000000Z.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["features_count"] == 0
        # Empty-input sha256 is a known constant: the hash signals "no features".
        assert manifest["layer_hash"] == hashlib.sha256(b"").hexdigest()
        assert sum(manifest["hash_distribution"].values()) == 0
        assert len(manifest["hash_distribution"]) == 256
        assert responses == []


# --------------------------------------------------------------------------- #
# State-agnostic guard for Colorado (ADR-005)                                 #
# --------------------------------------------------------------------------- #


class TestNoColoradoLeakIntoSharedLib:
    """The shared library `ingestion/ingestion/lib/` must remain state-agnostic
    per ADR-005 — no Colorado-specific identifiers and no CPW host literals
    in any file under the lib directory.

    Mirrors `test_pdf.py::TestPdfNoStateAdapterImports` (which guards a single
    lib file by its `__file__`) but walks every `.py` file under the lib
    directory dynamically, so files added in the future are auto-covered
    without test edits.

    Companion to E02 audit's MT_FWP_HOST removal discipline (commit 0093e88):
    state-host constants and state slugs belong in `states/<slug>/`, never
    in `ingestion/ingestion/lib/`.
    """

    # CPW-specific literals that must never appear in the shared library.
    # All entries MUST be lowercased; the scan compares against
    # `source.lower()` so any mixed-case entry would silently never match.
    # The class-body assertion immediately after this tuple enforces the
    # invariant at collection time.
    _CPW_HOST_LITERALS: tuple[str, ...] = (
        "services5.arcgis.com",
        "ttngmdvkqa7oedq3",
        "cpwadmindata",
    )
    assert all(s == s.lower() for s in _CPW_HOST_LITERALS), (
        "_CPW_HOST_LITERALS entries must be lowercase — the scan lowercases "
        "the source text but does NOT lowercase the needles, so a mixed-case "
        "entry would silently never match. See test_no_cpw_host_literals_in_lib."
    )

    @staticmethod
    def _lib_python_files() -> list[Path]:
        from ingestion import lib  # local import to avoid module-load order issues

        lib_dir = Path(lib.__file__).parent
        return sorted(lib_dir.rglob("*.py"))

    def test_lib_directory_enumeration_covers_known_files(self) -> None:
        files = self._lib_python_files()
        # As of S05.1: __init__.py + arcgis.py + db.py + drift_guard.py +
        # overlays.py + pdf.py + pdf_fetch.py + schema.py = 8 files.
        # Threshold of 5 catches a silent empty-rglob without being brittle
        # to legitimate future lib additions or deletions.
        assert len(files) >= 5, (
            f"Expected ≥5 .py files under ingestion/lib/, found {len(files)}. "
            f"Files: {[f.name for f in files]}. An empty enumeration would "
            f"silently pass the leak-guard tests below."
        )

    def test_no_colorado_slug_in_lib(self) -> None:
        files = self._lib_python_files()
        # Inline non-empty guard: makes this scan self-sufficient regardless
        # of pytest execution order. Without this, a tool like
        # `pytest-randomly` could run this test before the sanity-check method
        # and a broken-enumeration empty list would silently pass the loop.
        assert files, (
            "_lib_python_files() returned no files — the leak-guard cannot "
            "function. See test_lib_directory_enumeration_covers_known_files "
            "for diagnostic context."
        )
        for path in files:
            source_lower = path.read_text().lower()
            assert "colorado" not in source_lower, (
                f"{path.name} contains the state slug 'colorado' — Colorado-"
                f"specific code belongs in states/colorado/, not in the "
                f"shared library (ADR-005)."
            )

    def test_no_cpw_host_literals_in_lib(self) -> None:
        files = self._lib_python_files()
        # Inline non-empty guard: see test_no_colorado_slug_in_lib rationale.
        assert files, (
            "_lib_python_files() returned no files — the leak-guard cannot "
            "function. See test_lib_directory_enumeration_covers_known_files "
            "for diagnostic context."
        )
        for path in files:
            source_lower = path.read_text().lower()
            for literal in self._CPW_HOST_LITERALS:
                assert literal not in source_lower, (
                    f"{path.name} contains the CPW host literal {literal!r} — "
                    f"CPW-specific URL fragments belong in "
                    f"states/colorado/, not in the shared library "
                    f"(ADR-005; companion to E02 audit's MT_FWP_HOST removal "
                    f"discipline at commit 0093e88)."
                )


class TestReadObjectidFailsLoud:
    """S06.6.1: the strict `_require_objectid` extractor refuses the top-level
    `feature["id"]` fallback so an upstream ArcGIS republish that drops OBJECTID
    surfaces as a fail-loud ArcGISError instead of silently masking the gap.
    """

    def test_properties_objectid_returns_int(self) -> None:
        feature = {"type": "Feature", "properties": {"OBJECTID": 42, "Unit_Nm": "x"}}
        assert _require_objectid(feature) == 42

    def test_oid_field_resolves_non_default_column(self) -> None:
        # Layers with a non-default OID column (FID, OBJECTID_1, ...) resolve via
        # the passed oid_field, mirroring the dedup convention.
        feature = {"type": "Feature", "properties": {"OBJECTID_1": 7, "Unit_Nm": "x"}}
        assert _require_objectid(feature, oid_field="OBJECTID_1") == 7

    def test_top_level_id_only_raises(self) -> None:
        # Locks the S06.6.1 behavior change: the old `_read_objectid` fallback
        # would have returned 7 here; `_require_objectid` ignores `feature["id"]`
        # and raises, forcing OBJECTID into the request outFields.
        feature = {"type": "Feature", "id": 7, "properties": {"Unit_Nm": "x"}}
        assert _read_objectid(feature) == 7  # old best-effort behavior, for contrast
        with pytest.raises(ArcGISError):
            _require_objectid(feature)

    def test_neither_present_raises_with_diagnostic(self) -> None:
        feature = {"type": "Feature", "properties": {"Unit_Nm": "x"}}
        with pytest.raises(ArcGISError) as exc_info:
            _require_objectid(feature)
        message = str(exc_info.value)
        assert "OBJECTID" in message
        assert "outFields" in message

    def test_null_objectid_value_raises(self) -> None:
        # Strict: a present-but-null OBJECTID is NOT coerced to the string
        # "None" (which would collapse every such feature to one OID in the
        # manifest hash) — it raises, and the diagnostic flags the null value.
        feature = {"type": "Feature", "properties": {"OBJECTID": None}}
        with pytest.raises(ArcGISError) as exc_info:
            _require_objectid(feature)
        message = str(exc_info.value)
        assert "null/non-scalar" in message
        assert "OBJECTID" in message

    def test_non_scalar_objectid_value_raises(self) -> None:
        feature = {"type": "Feature", "properties": {"OBJECTID": [1, 2]}}
        with pytest.raises(ArcGISError):
            _require_objectid(feature)

    def test_float_objectid_value_raises(self) -> None:
        # A float OID (e.g. 42.0) is itself a type-drift signal — str(42.0) would
        # be "42.0", inconsistent with the int 42 representation. Reject it.
        feature = {"type": "Feature", "properties": {"OBJECTID": 42.0}}
        with pytest.raises(ArcGISError):
            _require_objectid(feature)

    def test_null_objectid_falls_through_to_sibling_oid(self) -> None:
        # A null OBJECTID does not abort the scan: a usable sibling candidate
        # (here FID) still resolves rather than failing the whole feature.
        feature = {"type": "Feature", "properties": {"OBJECTID": None, "FID": 99}}
        assert _require_objectid(feature) == 99
