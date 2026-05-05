"""Unit tests for states.montana.load_state_boundary — pure-function, no real HTTP or DB."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from states.montana.load_state_boundary import (
    _build_source_citation,
    _parse_to_multipolygon_wkt,
    _verify_sha256,
    main,
)
from ingestion.lib import db as db_module
from ingestion.lib.db import _UPSERT_SQL


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_mock_conn() -> tuple[MagicMock, MagicMock]:
    """Return (mock_conn, mock_cursor) with psycopg3 context-manager wiring."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


def _make_geojson_feature_collection(geometry: dict[str, Any]) -> dict[str, Any]:
    """Wrap a geometry dict in a minimal GeoJSON FeatureCollection with one feature."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {},
            }
        ],
    }


def _encode(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj).encode("utf-8")


# A minimal valid Polygon covering a small region (not self-intersecting).
_SIMPLE_POLYGON_GEOMETRY: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [[-110.0, 45.0], [-109.0, 45.0], [-109.0, 46.0], [-110.0, 46.0], [-110.0, 45.0]]
    ],
}

_SIMPLE_MULTIPOLYGON_GEOMETRY: dict[str, Any] = {
    "type": "MultiPolygon",
    "coordinates": [
        [
            [[-110.0, 45.0], [-109.0, 45.0], [-109.0, 46.0], [-110.0, 46.0], [-110.0, 45.0]]
        ]
    ],
}

# Self-intersecting bowtie polygon — make_valid should repair it.
_BOWTIE_POLYGON_GEOMETRY: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]
    ],
}

# A canned single-polygon GeoJSON payload suitable for TestMain.
_CANNED_GEOJSON: dict[str, Any] = _make_geojson_feature_collection(_SIMPLE_POLYGON_GEOMETRY)
_CANNED_PAYLOAD: bytes = _encode(_CANNED_GEOJSON)
_CANNED_SHA256: str = hashlib.sha256(_CANNED_PAYLOAD).hexdigest()


# ---------------------------------------------------------------------------
# TestVerifySha256
# ---------------------------------------------------------------------------


class TestVerifySha256:
    def test_passes_on_match(self) -> None:
        payload = b"hello state boundary"
        expected = hashlib.sha256(payload).hexdigest()
        # Returns the observed digest on match — raises RuntimeError on mismatch.
        observed = _verify_sha256(payload, expected)
        assert observed == expected

    def test_raises_on_mismatch(self) -> None:
        payload = b"hello state boundary"
        observed_sha = hashlib.sha256(payload).hexdigest()
        bogus_expected = "0" * 64

        with pytest.raises(RuntimeError) as exc_info:
            _verify_sha256(payload, bogus_expected)

        message = str(exc_info.value)
        assert observed_sha in message
        assert bogus_expected in message


# ---------------------------------------------------------------------------
# TestParseToMultipolygonWkt
# ---------------------------------------------------------------------------


class TestParseToMultipolygonWkt:
    def test_geojson_polygon_path(self) -> None:
        """Single Feature with a Polygon geometry → WKT starts with MULTIPOLYGON."""
        fc = _make_geojson_feature_collection(_SIMPLE_POLYGON_GEOMETRY)
        payload = _encode(fc)
        wkt = _parse_to_multipolygon_wkt(payload)
        assert wkt.startswith("MULTIPOLYGON")

    def test_geojson_multipolygon_path(self) -> None:
        """Single Feature with a MultiPolygon geometry → WKT starts with MULTIPOLYGON."""
        fc = _make_geojson_feature_collection(_SIMPLE_MULTIPOLYGON_GEOMETRY)
        payload = _encode(fc)
        wkt = _parse_to_multipolygon_wkt(payload)
        assert wkt.startswith("MULTIPOLYGON")

    def test_raises_on_zero_features(self) -> None:
        """Empty features array → RuntimeError (fail loud)."""
        fc: dict[str, Any] = {"type": "FeatureCollection", "features": []}
        payload = _encode(fc)
        with pytest.raises(RuntimeError):
            _parse_to_multipolygon_wkt(payload)

    def test_raises_on_invalid_utf8_bytes(self) -> None:
        """Non-decodable bytes (UnicodeDecodeError path) → source-tagged RuntimeError."""
        # \x80 alone is a continuation byte with no leading byte — invalid UTF-8.
        payload = b"\x80\x81\x82\x83 not valid utf-8 bytes"
        with pytest.raises(RuntimeError) as exc_info:
            _parse_to_multipolygon_wkt(payload)
        message = str(exc_info.value)
        assert "non-JSON" in message

    def test_raises_on_non_object_json(self) -> None:
        """Top-level JSON that isn't a dict (e.g., null, list, number) → source-tagged RuntimeError."""
        for payload in (b"null", b"[]", b"42", b'"a string"'):
            with pytest.raises(RuntimeError) as exc_info:
                _parse_to_multipolygon_wkt(payload)
            message = str(exc_info.value)
            assert "unexpected JSON shape" in message

    def test_raises_on_non_json_payload(self) -> None:
        """HTTP 200 with non-JSON body (e.g., HTML captive portal) → RuntimeError citing source."""
        payload = b"<!DOCTYPE html><html><body>Captive portal - please sign in</body></html>"
        with pytest.raises(RuntimeError) as exc_info:
            _parse_to_multipolygon_wkt(payload)
        message = str(exc_info.value)
        assert "non-JSON" in message
        # Operator should be able to see the start of the payload to diagnose.
        assert "DOCTYPE html" in message or "Captive portal" in message

    def test_raises_on_arcgis_error_envelope(self) -> None:
        """HTTP 200 with `{"error": {...}}` envelope → RuntimeError citing the server code+message."""
        envelope: dict[str, Any] = {
            "error": {
                "code": 499,
                "message": "Token Required",
                "details": [],
            }
        }
        payload = _encode(envelope)
        with pytest.raises(RuntimeError) as exc_info:
            _parse_to_multipolygon_wkt(payload)
        message = str(exc_info.value)
        assert "499" in message
        assert "Token Required" in message

    def test_raises_on_multiple_features(self) -> None:
        """Two features → RuntimeError (fail loud — state boundary must be one polygon)."""
        feature: dict[str, Any] = {
            "type": "Feature",
            "geometry": _SIMPLE_POLYGON_GEOMETRY,
            "properties": {},
        }
        fc: dict[str, Any] = {"type": "FeatureCollection", "features": [feature, feature]}
        payload = _encode(fc)
        with pytest.raises(RuntimeError):
            _parse_to_multipolygon_wkt(payload)

    def test_invalid_polygon_repaired_via_make_valid(self) -> None:
        """Self-intersecting bowtie polygon is repaired and returns valid WKT."""
        fc = _make_geojson_feature_collection(_BOWTIE_POLYGON_GEOMETRY)
        payload = _encode(fc)
        # geojson_to_multipolygon_wkt (via arcgis) runs make_valid internally;
        # a bowtie should be repaired without raising.
        wkt = _parse_to_multipolygon_wkt(payload)
        assert isinstance(wkt, str)
        assert len(wkt) > 0


# ---------------------------------------------------------------------------
# TestBuildSourceCitation
# ---------------------------------------------------------------------------


class TestBuildSourceCitation:
    def test_id_is_deterministic(self) -> None:
        """Calling _build_source_citation() twice returns the same .id."""
        citation_a = _build_source_citation()
        citation_b = _build_source_citation()
        assert citation_a.id == citation_b.id

    def test_document_type_is_gis_layer(self) -> None:
        citation = _build_source_citation()
        assert citation.document_type == "gis_layer"

    def test_publication_date_iso_format(self) -> None:
        """Publication date matches T7's pinned value."""
        citation = _build_source_citation()
        assert citation.publication_date == "2026-01-01"

    def test_agency_is_montana_state_library(self) -> None:
        """Source agency is Montana State Library, NOT Montana FWP."""
        citation = _build_source_citation()
        assert citation.agency == "Montana State Library"


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


def _make_connect_cm(mock_conn: MagicMock) -> MagicMock:
    """Wrap mock_conn in a context manager so `with db.connect() as conn:` yields mock_conn."""
    connect_cm = MagicMock()
    connect_cm.__enter__ = MagicMock(return_value=mock_conn)
    connect_cm.__exit__ = MagicMock(return_value=False)
    return connect_cm


class TestMain:
    def _run_main_with_mocks(
        self,
        mock_conn: MagicMock,
    ) -> None:
        """Patch _fetch_source_bytes, STATE_BOUNDARY_SHA256, and db.connect; run main([])."""
        connect_cm = _make_connect_cm(mock_conn)
        with (
            patch(
                "states.montana.load_state_boundary._fetch_source_bytes",
                return_value=_CANNED_PAYLOAD,
            ),
            patch(
                "states.montana.load_state_boundary.STATE_BOUNDARY_SHA256",
                _CANNED_SHA256,
            ),
            patch.object(db_module, "connect", return_value=connect_cm),
        ):
            main([])

    def test_main_writes_one_geometry_row(self) -> None:
        """main([]) calls cursor.execute exactly once with the upsert SQL."""
        mock_conn, mock_cursor = _make_mock_conn()
        self._run_main_with_mocks(mock_conn)

        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args

        # First positional arg is the SQL string.
        sql: str = call_args[0][0]
        assert sql == _UPSERT_SQL

        # Second positional arg is the params tuple.
        params: tuple[object, ...] = call_args[0][1]

        # Extract named positions from _UPSERT_SQL parameter order:
        # (id, name, kind, geom_wkt, state, license_year, source_json, verbatim_rule, legal_description)
        id_val = params[0]
        kind_val = params[2]
        license_year_val = params[5]

        assert id_val == "MT-STATEWIDE-geom"
        assert kind_val == "state"
        assert license_year_val is None

    def test_main_commits_after_upsert(self) -> None:
        """main([]) commits exactly once after the upsert (single atomic commit)."""
        mock_conn, _mock_cursor = _make_mock_conn()
        self._run_main_with_mocks(mock_conn)
        mock_conn.commit.assert_called_once()

    def test_main_raises_on_sha_mismatch(self) -> None:
        """SHA mismatch → RuntimeError; commit must NOT be called (no partial state)."""
        mock_conn, _mock_cursor = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)

        with (
            patch(
                "states.montana.load_state_boundary._fetch_source_bytes",
                return_value=_CANNED_PAYLOAD,
            ),
            patch(
                "states.montana.load_state_boundary.STATE_BOUNDARY_SHA256",
                "0" * 64,  # deliberately wrong
            ),
            patch.object(db_module, "connect", return_value=connect_cm),
            pytest.raises(RuntimeError),
        ):
            main([])

        mock_conn.commit.assert_not_called()
