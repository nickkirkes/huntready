"""Unit tests for states.colorado.load_gmus — pure-function, no real HTTP or DB."""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ingestion.lib import arcgis
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry
from states.colorado.load_gmus import (
    CO_AGENCY,
    CO_STATE_SLUG,
    CPW_GMU_LAYER_ID,
    CPW_SERVICE_URL,
    ColoradoGeometryError,
    _GMU_COUNT_GUARD_BAND,
    _check_count_band,
    _collect_multipart_gmus,
    _duplicate_ids,
    _extract_county,
    _extract_gmuid,
    _feature_to_geometry,
    _fetch_and_build,
    _write_multipart_fixture,
    main,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SQUARE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-105.0, 40.0],
            [-104.0, 40.0],
            [-104.0, 41.0],
            [-105.0, 41.0],
            [-105.0, 40.0],
        ]
    ],
}

_MULTIPART_POLYGON = {
    "type": "MultiPolygon",
    "coordinates": [
        [
            [
                [-105.0, 40.0],
                [-104.5, 40.0],
                [-104.5, 40.5],
                [-105.0, 40.5],
                [-105.0, 40.0],
            ]
        ],
        [
            [
                [-104.0, 40.0],
                [-103.5, 40.0],
                [-103.5, 40.5],
                [-104.0, 40.5],
                [-104.0, 40.0],
            ]
        ],
    ],
}


def _make_feature(
    gmuid: int,
    *,
    county: str = "Larimer",
    objectid: int = 999,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal GeoJSON feature with GMU properties."""
    props: dict[str, Any] = {
        "GMUID": gmuid,
        "COUNTY": county,
        "OBJECTID": objectid,
        "EDIT_DATE": None,
        "INPUT_DATE": None,
    }
    return {
        "type": "Feature",
        "geometry": geometry if geometry is not None else _SQUARE_POLYGON,
        "properties": props,
    }


def _make_metadata(**overrides: Any) -> LayerMetadata:
    """Construct a real LayerMetadata for CPW layer 6 Big Game GMUs."""
    defaults: dict[str, Any] = {
        "name": "Big Game GMUs",
        "object_id_field": "OBJECTID",
        "max_record_count": 1000,
        "out_fields": ("GMUID", "COUNTY", "OBJECTID", "EDIT_DATE", "INPUT_DATE"),
        "geometry_type": "esriGeometryPolygon",
        "last_edit_date_ms": None,
        "raw": {},
        "spatial_reference_wkid": 4326,
    }
    defaults.update(overrides)
    return LayerMetadata(**defaults)


def _make_mock_conn() -> tuple[MagicMock, MagicMock]:
    """Return (mock_conn, mock_cursor) with psycopg3 context-manager wiring."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


def _make_connect_cm(mock_conn: MagicMock) -> MagicMock:
    """Wrap mock_conn so `with db.connect() as conn:` yields mock_conn."""
    connect_cm = MagicMock()
    connect_cm.__enter__ = MagicMock(return_value=mock_conn)
    connect_cm.__exit__ = MagicMock(return_value=False)
    return connect_cm


_TEST_LOGGER = logging.getLogger("test")

# ---------------------------------------------------------------------------
# TestExtractGmuid
# ---------------------------------------------------------------------------


class TestExtractGmuid:
    def test_int_coerced_to_string(self) -> None:
        metadata = _make_metadata()
        result = _extract_gmuid({"GMUID": 201}, metadata)
        assert result == "201"
        assert isinstance(result, str)

    def test_string_value_preserved(self) -> None:
        metadata = _make_metadata()
        result = _extract_gmuid({"GMUID": "305"}, metadata)
        assert result == "305"

    def test_missing_gmuid_raises_colorado_geometry_error(self) -> None:
        metadata = _make_metadata()
        with pytest.raises(ColoradoGeometryError) as exc_info:
            _extract_gmuid({"COUNTY": "Larimer"}, metadata)
        msg = str(exc_info.value)
        assert "GMUID" in msg

    def test_error_message_includes_out_fields(self) -> None:
        metadata = _make_metadata()
        with pytest.raises(ColoradoGeometryError) as exc_info:
            _extract_gmuid({}, metadata)
        msg = str(exc_info.value)
        # Error should mention available fields from out_fields
        assert "available=" in msg


# ---------------------------------------------------------------------------
# TestExtractCounty
# ---------------------------------------------------------------------------


class TestExtractCounty:
    def test_returns_stripped_string(self) -> None:
        result = _extract_county({"COUNTY": "  Larimer  "})
        assert result == "Larimer"

    def test_returns_none_when_absent(self) -> None:
        assert _extract_county({}) is None

    def test_returns_none_when_none(self) -> None:
        assert _extract_county({"COUNTY": None}) is None

    def test_returns_none_when_blank(self) -> None:
        assert _extract_county({"COUNTY": "   "}) is None

    def test_returns_none_when_empty(self) -> None:
        assert _extract_county({"COUNTY": ""}) is None


# ---------------------------------------------------------------------------
# TestFeatureToGeometry
# ---------------------------------------------------------------------------


class TestFeatureToGeometry:
    def _call(self, feature: dict[str, Any]) -> Geometry:
        return _feature_to_geometry(
            feature,
            _make_metadata(),
            CPW_SERVICE_URL,
            2026,
            logger=_TEST_LOGGER,
        )

    def test_geometry_id_derived_from_gmuid_not_objectid(self) -> None:
        """GMUID=201, OBJECTID=999 → id == 'CO-GMU-201-geom' and '999' not in id."""
        feature = _make_feature(201, county="Larimer", objectid=999)
        geom = self._call(feature)
        assert geom.id == "CO-GMU-201-geom"
        assert "999" not in geom.id

    def test_kind_is_gmu(self) -> None:
        feature = _make_feature(201)
        geom = self._call(feature)
        assert geom.kind == "gmu"

    def test_license_year_none_on_row(self) -> None:
        feature = _make_feature(201)
        geom = self._call(feature)
        assert geom.license_year is None

    def test_citation_publication_date_and_doc_type(self) -> None:
        feature = _make_feature(201)
        geom = self._call(feature)
        assert geom.source.publication_date == "2026-01-01"
        assert geom.source.document_type == "gis_layer"

    def test_citation_id_format(self) -> None:
        """Citation id must be 'co-cpw-arcgis-CPWAdminData-6-2026'.

        Cross-check via a direct call to arcgis.build_source_citation so the
        test doesn't just encode the same string literal twice.
        """
        feature = _make_feature(201)
        geom = self._call(feature)
        expected_citation = arcgis.build_source_citation(
            service_url=CPW_SERVICE_URL,
            layer_id=CPW_GMU_LAYER_ID,
            metadata=_make_metadata(),
            license_year=2026,
            state_slug=CO_STATE_SLUG,
            agency=CO_AGENCY,
        )
        assert geom.source.id == expected_citation.id
        assert geom.source.id == "co-cpw-arcgis-CPWAdminData-6-2026"

    def test_name_with_county(self) -> None:
        feature = _make_feature(201, county="Larimer")
        geom = self._call(feature)
        assert geom.name == "GMU 201 (Larimer)"

    def test_name_without_county(self) -> None:
        props = {
            "GMUID": 201,
            "OBJECTID": 1,
        }
        feature = {"type": "Feature", "geometry": _SQUARE_POLYGON, "properties": props}
        geom = self._call(feature)
        assert geom.name == "GMU 201"

    def test_geom_is_multipolygon_wkt(self) -> None:
        feature = _make_feature(201)
        geom = self._call(feature)
        assert geom.geom.startswith("MULTIPOLYGON")

    def test_geometrycollection_raises_colorado_geometry_error(self) -> None:
        """When geojson_to_multipolygon_wkt raises ArcGISError, ColoradoGeometryError is raised."""
        feature = _make_feature(201)
        with patch(
            "states.colorado.load_gmus.arcgis.geojson_to_multipolygon_wkt",
            side_effect=ArcGISError("GeometryCollection Polygon=1, LineString=2"),
        ):
            with pytest.raises(ColoradoGeometryError) as exc_info:
                self._call(feature)
        # GMUID should appear in the error message
        assert "201" in str(exc_info.value)

    def test_state_is_us_co(self) -> None:
        feature = _make_feature(201)
        geom = self._call(feature)
        assert geom.state == "US-CO"

    def test_missing_properties_key_raises_colorado_error(self) -> None:
        """A feature lacking a 'properties' key must raise ColoradoGeometryError,
        not a bare KeyError (fail-loud contract; mirrors load_restricted_areas)."""
        feature = {"type": "Feature", "geometry": _SQUARE_POLYGON}
        with pytest.raises(ColoradoGeometryError) as exc_info:
            self._call(feature)
        assert "properties" in str(exc_info.value)

    def test_null_properties_raises_colorado_error(self) -> None:
        """GeoJSON permits 'properties': null; a non-dict properties value must
        raise ColoradoGeometryError, not a bare AttributeError."""
        feature = {"type": "Feature", "geometry": _SQUARE_POLYGON, "properties": None}
        with pytest.raises(ColoradoGeometryError) as exc_info:
            self._call(feature)
        assert "properties" in str(exc_info.value)

    def test_edit_input_date_logged_at_info_not_persisted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC #235: EDIT_DATE/INPUT_DATE are emitted at INFO for forensics but
        NEVER persisted to the geometry row (SourceCitation is frozen,
        extra='forbid')."""
        props = {
            "GMUID": 201,
            "OBJECTID": 1,
            "EDIT_DATE": "2026-04-09",
            "INPUT_DATE": "2025-01-15",
        }
        feature = {"type": "Feature", "geometry": _SQUARE_POLYGON, "properties": props}
        with caplog.at_level(logging.INFO, logger="test"):
            geom = self._call(feature)
        # INFO line emitted carrying both provenance values…
        assert any(
            "2026-04-09" in r.message and "2025-01-15" in r.message
            for r in caplog.records
        )
        # …but neither value is persisted to the source jsonb.
        serialized = str(geom.source.model_dump())
        assert "2026-04-09" not in serialized
        assert "2025-01-15" not in serialized


# ---------------------------------------------------------------------------
# TestDuplicateIds
# ---------------------------------------------------------------------------


class TestDuplicateIds:
    def _make_geom(self, gmu_id: int) -> Geometry:
        feature = _make_feature(gmu_id, county="Test")
        return _feature_to_geometry(
            feature,
            _make_metadata(),
            CPW_SERVICE_URL,
            2026,
            logger=_TEST_LOGGER,
        )

    def test_empty_list_when_all_unique(self) -> None:
        geoms = [self._make_geom(i) for i in (100, 200, 300)]
        assert _duplicate_ids(geoms) == []

    def test_returns_repeated_id_once(self) -> None:
        g1 = self._make_geom(100)
        g2 = self._make_geom(100)  # duplicate
        g3 = self._make_geom(200)
        dupes = _duplicate_ids([g1, g2, g3])
        assert dupes == ["CO-GMU-100-geom"]

    def test_each_duplicate_reported_exactly_once(self) -> None:
        g1 = self._make_geom(100)
        g2 = self._make_geom(100)
        g3 = self._make_geom(100)
        dupes = _duplicate_ids([g1, g2, g3])
        assert len(dupes) == 1
        assert dupes[0] == "CO-GMU-100-geom"

    def test_empty_input_returns_empty(self) -> None:
        assert _duplicate_ids([]) == []


# ---------------------------------------------------------------------------
# TestCheckCountBand
# ---------------------------------------------------------------------------


class TestCheckCountBand:
    def test_no_raise_at_lower_bound(self) -> None:
        lo, _hi = _GMU_COUNT_GUARD_BAND
        assert lo == 167, "guard band lower bound has changed; update test"
        _check_count_band(lo)  # must not raise

    def test_no_raise_in_middle(self) -> None:
        _check_count_band(186)

    def test_no_raise_at_upper_bound(self) -> None:
        _hi = _GMU_COUNT_GUARD_BAND[1]
        assert _hi == 205, "guard band upper bound has changed; update test"
        _check_count_band(_hi)  # must not raise

    def test_raises_below_lower_bound(self) -> None:
        lo = _GMU_COUNT_GUARD_BAND[0]
        with pytest.raises(RuntimeError) as exc_info:
            _check_count_band(lo - 1)
        assert str(lo - 1) in str(exc_info.value)

    def test_raises_above_upper_bound(self) -> None:
        hi = _GMU_COUNT_GUARD_BAND[1]
        with pytest.raises(RuntimeError) as exc_info:
            _check_count_band(hi + 1)
        assert str(hi + 1) in str(exc_info.value)


# ---------------------------------------------------------------------------
# TestCollectMultipartGmus
# ---------------------------------------------------------------------------


class TestCollectMultipartGmus:
    def _make_geom_from_raw_polygon(self, gmu_id: int) -> Geometry:
        feature = _make_feature(gmu_id, county="Test")
        return _feature_to_geometry(
            feature, _make_metadata(), CPW_SERVICE_URL, 2026, logger=_TEST_LOGGER
        )

    def _make_geom_from_multipolygon(self, gmu_id: int) -> Geometry:
        feature = _make_feature(gmu_id, county="Test", geometry=_MULTIPART_POLYGON)
        return _feature_to_geometry(
            feature, _make_metadata(), CPW_SERVICE_URL, 2026, logger=_TEST_LOGGER
        )

    def test_single_polygon_excluded(self) -> None:
        geom = self._make_geom_from_raw_polygon(100)
        result = _collect_multipart_gmus([geom])
        assert result == []

    def test_multipolygon_included_with_part_count_2(self) -> None:
        geom = self._make_geom_from_multipolygon(201)
        result = _collect_multipart_gmus([geom])
        assert len(result) == 1
        assert result[0]["part_count"] == 2

    def test_multipolygon_row_has_parsed_gmuid(self) -> None:
        geom = self._make_geom_from_multipolygon(201)
        result = _collect_multipart_gmus([geom])
        assert len(result) == 1
        assert result[0]["gmuid"] == 201

    def test_multipolygon_row_has_total_area_sq_km_key_with_none(self) -> None:
        geom = self._make_geom_from_multipolygon(201)
        result = _collect_multipart_gmus([geom])
        assert len(result) == 1
        assert "total_area_sq_km" in result[0]
        assert result[0]["total_area_sq_km"] is None

    def test_result_sorted_by_gmuid_ascending(self) -> None:
        geom_300 = self._make_geom_from_multipolygon(300)
        geom_100 = self._make_geom_from_multipolygon(100)
        geom_200 = self._make_geom_from_multipolygon(200)
        result = _collect_multipart_gmus([geom_300, geom_100, geom_200])
        assert [r["gmuid"] for r in result] == [100, 200, 300]

    def test_empty_input_returns_empty(self) -> None:
        assert _collect_multipart_gmus([]) == []


# ---------------------------------------------------------------------------
# TestWriteMultipartFixture
# ---------------------------------------------------------------------------


class TestWriteMultipartFixture:
    def test_writes_deterministic_json(self, tmp_path: Path) -> None:
        rows: list[dict[str, Any]] = [
            {"gmuid": 100, "part_count": 2, "total_area_sq_km": None},
            {"gmuid": 200, "part_count": 3, "total_area_sq_km": None},
        ]
        out_path = tmp_path / "multipart-gmus.json"
        _write_multipart_fixture(rows, out_path)
        assert out_path.exists()

    def test_round_trips_as_json(self, tmp_path: Path) -> None:
        rows: list[dict[str, Any]] = [
            {"gmuid": 100, "part_count": 2, "total_area_sq_km": None},
        ]
        out_path = tmp_path / "multipart-gmus.json"
        _write_multipart_fixture(rows, out_path)
        loaded = json.loads(out_path.read_text())
        assert loaded == rows

    def test_ends_with_trailing_newline(self, tmp_path: Path) -> None:
        rows: list[dict[str, Any]] = [{"gmuid": 100, "part_count": 2, "total_area_sq_km": None}]
        out_path = tmp_path / "multipart-gmus.json"
        _write_multipart_fixture(rows, out_path)
        raw = out_path.read_text()
        assert raw.endswith("\n")

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "multipart-gmus.json"
        rows: list[dict[str, Any]] = []
        _write_multipart_fixture(rows, nested)
        assert nested.exists()

    def test_deterministic_output_stable(self, tmp_path: Path) -> None:
        """Writing the same data twice produces byte-identical files."""
        rows: list[dict[str, Any]] = [
            {"gmuid": 100, "part_count": 2, "total_area_sq_km": None},
        ]
        out_path1 = tmp_path / "run1.json"
        out_path2 = tmp_path / "run2.json"
        _write_multipart_fixture(rows, out_path1)
        _write_multipart_fixture(rows, out_path2)
        assert out_path1.read_text() == out_path2.read_text()


# ---------------------------------------------------------------------------
# TestFetchAndBuild
# ---------------------------------------------------------------------------


class TestFetchAndBuild:
    def test_returns_geometry_list_with_expected_ids(self, tmp_path: Path) -> None:
        metadata = _make_metadata()
        features = [
            _make_feature(100, county="Larimer", objectid=1),
            _make_feature(200, county="Boulder", objectid=2),
            _make_feature(300, county="Routt", objectid=3),
        ]
        with (
            patch(
                "states.colorado.load_gmus.arcgis.fetch_layer_metadata",
                return_value=metadata,
            ),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_features",
                return_value=features,
            ),
        ):
            result = _fetch_and_build(
                CPW_SERVICE_URL,
                tmp_path,
                2026,
                session=None,
                logger=_TEST_LOGGER,
            )

        assert len(result) == 3
        ids = {g.id for g in result}
        assert "CO-GMU-100-geom" in ids
        assert "CO-GMU-200-geom" in ids
        assert "CO-GMU-300-geom" in ids

    def test_all_results_are_geometry_instances(self, tmp_path: Path) -> None:
        metadata = _make_metadata()
        features = [
            _make_feature(100, county="Larimer", objectid=1),
        ]
        with (
            patch(
                "states.colorado.load_gmus.arcgis.fetch_layer_metadata",
                return_value=metadata,
            ),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_features",
                return_value=features,
            ),
        ):
            result = _fetch_and_build(
                CPW_SERVICE_URL,
                tmp_path,
                2026,
                session=None,
                logger=_TEST_LOGGER,
            )
        assert all(isinstance(g, Geometry) for g in result)


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    def _make_three_features(self) -> list[dict[str, Any]]:
        return [
            _make_feature(100, county="Larimer", objectid=1),
            _make_feature(200, county="Boulder", objectid=2),
            _make_feature(300, county="Routt", objectid=3),
        ]

    def test_main_returns_zero_and_commits(self, tmp_path: Path) -> None:
        mock_conn, _mock_cursor = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)
        metadata = _make_metadata()
        features = self._make_three_features()
        fixture_path = tmp_path / "multipart-gmus.json"

        # Build a minimal context-manager mock for _build_session
        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("states.colorado.load_gmus.arcgis._build_session", return_value=session_cm),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_layer_metadata",
                return_value=metadata,
            ),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_features",
                return_value=features,
            ),
            patch(
                "states.colorado.load_gmus.db.connect",
                return_value=connect_cm,
            ),
            patch(
                "states.colorado.load_gmus._check_count_band",
                return_value=None,
            ),
            patch(
                "states.colorado.load_gmus.MULTIPART_FIXTURE_PATH",
                fixture_path,
            ),
        ):
            result = main([])

        assert result == 0
        mock_conn.commit.assert_called_once()

    def test_main_no_commit_on_fetch_error(self, tmp_path: Path) -> None:
        """If fetch raises, exception propagates and commit is NOT called."""
        mock_conn, _mock_cursor = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)

        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("states.colorado.load_gmus.arcgis._build_session", return_value=session_cm),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_layer_metadata",
                side_effect=ArcGISError("network failure"),
            ),
            patch(
                "states.colorado.load_gmus.db.connect",
                return_value=connect_cm,
            ),
            pytest.raises(ArcGISError),
        ):
            main([])

        mock_conn.commit.assert_not_called()

    def test_main_no_commit_on_duplicate_id_guard(self, tmp_path: Path) -> None:
        """Duplicate GMUID → pre-connect guard raises; commit NOT called."""
        mock_conn, _mock_cursor = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)
        metadata = _make_metadata()
        # Two features with the same GMUID -> two CO-GMU-100-geom ids.
        features = [
            _make_feature(100, county="Larimer", objectid=1),
            _make_feature(100, county="Boulder", objectid=2),
        ]
        fixture_path = tmp_path / "multipart-gmus.json"

        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("states.colorado.load_gmus.arcgis._build_session", return_value=session_cm),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_layer_metadata",
                return_value=metadata,
            ),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_features",
                return_value=features,
            ),
            patch("states.colorado.load_gmus.db.connect", return_value=connect_cm),
            patch("states.colorado.load_gmus.MULTIPART_FIXTURE_PATH", fixture_path),
            pytest.raises(RuntimeError),
        ):
            main([])

        mock_conn.commit.assert_not_called()

    def test_main_no_commit_on_count_band_guard(self, tmp_path: Path) -> None:
        """Out-of-band feature count → pre-connect guard raises; commit NOT called.

        Three unique features is well below the [167, 205] band, so the real
        _check_count_band (NOT patched here) raises before db.connect().
        """
        mock_conn, _mock_cursor = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)
        metadata = _make_metadata()
        features = self._make_three_features()
        fixture_path = tmp_path / "multipart-gmus.json"

        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("states.colorado.load_gmus.arcgis._build_session", return_value=session_cm),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_layer_metadata",
                return_value=metadata,
            ),
            patch(
                "states.colorado.load_gmus.arcgis.fetch_features",
                return_value=features,
            ),
            patch("states.colorado.load_gmus.db.connect", return_value=connect_cm),
            patch("states.colorado.load_gmus.MULTIPART_FIXTURE_PATH", fixture_path),
            pytest.raises(RuntimeError),
        ):
            main([])

        mock_conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# TestNoLibImports
# ---------------------------------------------------------------------------


class TestNoLibImports:
    """Ensure load_gmus.py imports no sibling state adapter (ADR-005 isolation)."""

    def _load_gmus_path(self) -> Path:
        spec = importlib.util.find_spec("states.colorado.load_gmus")
        assert spec is not None and spec.origin is not None
        return Path(spec.origin)

    def test_no_montana_imports(self) -> None:
        """load_gmus.py must not import from states.montana or ingestion.states.montana."""
        source = self._load_gmus_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        forbidden_prefixes = ("states.montana", "ingestion.states.montana")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"load_gmus.py has forbidden import: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for prefix in forbidden_prefixes:
                    assert not module.startswith(prefix), (
                        f"load_gmus.py has forbidden from-import: from {module}"
                    )

    def test_no_other_state_adapter_imports(self) -> None:
        """load_gmus.py must not import any sibling state adapter (ADR-005).

        Broader than the Montana-specific guard: catches any
        ``states.<other>`` / ``ingestion.states.<other>`` import where
        ``<other>`` is not ``colorado``. Mirrors the cross-state isolation
        guard the MT loaders use, so the check stays durable as CO grows.
        """
        source = self._load_gmus_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        def _offending(module: str) -> bool:
            for root in ("states.", "ingestion.states."):
                if module.startswith(root):
                    sibling = module[len(root):].split(".", 1)[0]
                    if sibling != "colorado":
                        return True
            return False

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not _offending(alias.name), (
                        f"load_gmus.py imports a non-Colorado state adapter: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not _offending(module), (
                    f"load_gmus.py imports a non-Colorado state adapter: from {module}"
                )
