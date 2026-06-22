"""Unit tests for states.colorado.load_restricted_areas — pure-function, no real HTTP or DB."""

from __future__ import annotations

import ast
import importlib.util
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ingestion.lib import arcgis
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry
from states.colorado.load_restricted_areas import (
    CO_AGENCY,
    CO_STATE_SLUG,
    PADUS_LAYER_ID,
    PADUS_SERVICE_URL,
    ColoradoGeometryError,
    _RA_COUNT_GUARD_BAND,
    _CURECANTI_GEOM_ID,
    _V1_EXPECTED_IDS,
    _V1_WHERE,
    _assert_curecanti_dropped,
    _check_count_band,
    _duplicate_ids,
    _feature_to_geometry,
    _fetch_and_build,
    _slugify,
    main,
)

# ---------------------------------------------------------------------------
# Shared geometry fixtures
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

_TEST_LOGGER = logging.getLogger("test")

# The 10 V1 unit names.
_V1_UNIT_NMS = [
    "Rocky Mountain National Park",
    "Mesa Verde National Park",
    "Great Sand Dunes National Park",
    "Black Canyon of the Gunnison National Park",
    "Dinosaur National Monument",
    "Colorado National Monument",
    "Florissant Fossil Beds National Monument",
    "Hovenweep National Monument",
    "Yucca House National Monument",
    "United States Air Force Academy",
]

_CURECANTI_UNIT_NM = "Curecanti National Recreation Area"


def _make_ra_feature(
    unit_nm: str,
    *,
    des_tp: str = "NP",
    mang_name: str = "NPS",
    objectid: int = 1,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal GeoJSON feature with PAD-US restricted-area properties."""
    props: dict[str, Any] = {
        "Unit_Nm": unit_nm,
        "Des_Tp": des_tp,
        "Mang_Name": mang_name,
        "Pub_Access": "OA",
        "GIS_Acres": 265761.0,
        "Src_Date": "2023-01-01",
        "OBJECTID": objectid,
    }
    return {
        "type": "Feature",
        "geometry": geometry if geometry is not None else _SQUARE_POLYGON,
        "properties": props,
    }


def _make_metadata(**overrides: Any) -> LayerMetadata:
    """Construct a minimal LayerMetadata for PAD-US layer 0."""
    defaults: dict[str, Any] = {
        "name": "Federal_Fee_Managers_Authoritative_PADUS",
        "object_id_field": "OBJECTID",
        "max_record_count": 1000,
        "out_fields": (
            "Unit_Nm",
            "Des_Tp",
            "Mang_Name",
            "Pub_Access",
            "GIS_Acres",
            "Src_Date",
        ),
        "geometry_type": "esriGeometryPolygon",
        "last_edit_date_ms": None,
        "raw": {},
        "spatial_reference_wkid": 4326,
    }
    defaults.update(overrides)
    return LayerMetadata(**defaults)


def _make_citation() -> Any:
    """Build a SourceCitation for PAD-US layer 0, year 2026."""
    return arcgis.build_source_citation(
        service_url=PADUS_SERVICE_URL,
        layer_id=PADUS_LAYER_ID,
        metadata=_make_metadata(),
        license_year=2026,
        state_slug=CO_STATE_SLUG,
        agency=CO_AGENCY,
    )


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


def _make_11_features() -> list[dict[str, Any]]:
    """11 features: 10 V1 zones + Curecanti (must be dropped post-fetch)."""
    features = []
    for i, nm in enumerate(_V1_UNIT_NMS):
        des_tp = "NM" if "Monument" in nm else ("NP" if "Park" in nm else "DOD")
        mang = "DOD" if "Air Force" in nm else "NPS"
        features.append(_make_ra_feature(nm, des_tp=des_tp, mang_name=mang, objectid=i + 1))
    # Curecanti — NRA, must be dropped
    features.append(_make_ra_feature(_CURECANTI_UNIT_NM, des_tp="NRA", objectid=11))
    assert len(features) == 11
    return features


def _make_10_valid_geoms() -> list[Geometry]:
    """Build the full valid set of 10 V1 restricted-area Geometry objects."""
    citation = _make_citation()
    metadata = _make_metadata()
    geoms = [
        _feature_to_geometry(
            _make_ra_feature(_V1_UNIT_NMS[i], objectid=i + 1),
            metadata,
            citation,
            logger=_TEST_LOGGER,
        )
        for i in range(10)
    ]
    assert len(geoms) == 10, "test helper must produce exactly 10 geometries"
    return geoms


# ---------------------------------------------------------------------------
# TestSlugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_rocky_mountain_np(self) -> None:
        assert _slugify("Rocky Mountain National Park") == "rocky-mountain-national-park"

    def test_mesa_verde_np(self) -> None:
        assert _slugify("Mesa Verde National Park") == "mesa-verde-national-park"

    def test_great_sand_dunes_np(self) -> None:
        assert _slugify("Great Sand Dunes National Park") == "great-sand-dunes-national-park"

    def test_black_canyon_np(self) -> None:
        assert (
            _slugify("Black Canyon of the Gunnison National Park")
            == "black-canyon-of-the-gunnison-national-park"
        )

    def test_dinosaur_nm(self) -> None:
        assert _slugify("Dinosaur National Monument") == "dinosaur-national-monument"

    def test_colorado_nm(self) -> None:
        assert _slugify("Colorado National Monument") == "colorado-national-monument"

    def test_florissant_nm(self) -> None:
        assert (
            _slugify("Florissant Fossil Beds National Monument")
            == "florissant-fossil-beds-national-monument"
        )

    def test_hovenweep_nm(self) -> None:
        assert _slugify("Hovenweep National Monument") == "hovenweep-national-monument"

    def test_yucca_house_nm(self) -> None:
        assert _slugify("Yucca House National Monument") == "yucca-house-national-monument"

    def test_air_force_academy(self) -> None:
        assert (
            _slugify("United States Air Force Academy") == "united-states-air-force-academy"
        )

    def test_curecanti_nra(self) -> None:
        # Curecanti must produce the slug used in _CURECANTI_GEOM_ID.
        assert (
            _slugify("Curecanti National Recreation Area")
            == "curecanti-national-recreation-area"
        )


# ---------------------------------------------------------------------------
# TestExpectedIds
# ---------------------------------------------------------------------------


class TestExpectedIds:
    def test_expected_ids_has_exactly_10_entries(self) -> None:
        assert len(_V1_EXPECTED_IDS) == 10, (
            f"_V1_EXPECTED_IDS has {len(_V1_EXPECTED_IDS)} entries; expected exactly 10"
        )

    def test_expected_ids_equals_literal_set(self) -> None:
        literal_set = frozenset(
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
        assert _V1_EXPECTED_IDS == literal_set


# ---------------------------------------------------------------------------
# TestCitationId
# ---------------------------------------------------------------------------


class TestCitationId:
    def test_citation_id_value(self) -> None:
        """Derive-and-assert: build citation from real primitives; pin its id."""
        citation = _make_citation()
        assert (
            citation.id
            == "co-usgs-padus-arcgis-Federal_Fee_Managers_Authoritative_PADUS-0-2026"
        )

    def test_citation_document_type(self) -> None:
        citation = _make_citation()
        assert citation.document_type == "gis_layer"

    def test_citation_publication_date(self) -> None:
        citation = _make_citation()
        assert citation.publication_date == "2026-01-01"


# ---------------------------------------------------------------------------
# TestFeatureToGeometry
# ---------------------------------------------------------------------------


class TestFeatureToGeometry:
    def _call(self, feature: dict[str, Any]) -> Geometry:
        return _feature_to_geometry(
            feature,
            _make_metadata(),
            _make_citation(),
            logger=_TEST_LOGGER,
        )

    def test_geometry_id_derived_from_unit_nm(self) -> None:
        """Unit_Nm → slug → id; OBJECTID plays no role in the id."""
        feature = _make_ra_feature("Rocky Mountain National Park", objectid=42)
        geom = self._call(feature)
        assert geom.id == "CO-restricted-rocky-mountain-national-park-geom"
        assert geom.kind == "restricted_area"

    def test_id_not_derived_from_objectid(self) -> None:
        """OBJECTID=999 must never appear in the geometry id (regression guard)."""
        feature = _make_ra_feature("Rocky Mountain National Park", objectid=999)
        geom = self._call(feature)
        assert geom.id == "CO-restricted-rocky-mountain-national-park-geom"
        assert "999" not in geom.id

    def test_verbatim_rule_is_none(self) -> None:
        feature = _make_ra_feature("Rocky Mountain National Park")
        geom = self._call(feature)
        assert geom.verbatim_rule is None

    def test_state_is_us_co(self) -> None:
        feature = _make_ra_feature("Rocky Mountain National Park")
        geom = self._call(feature)
        assert geom.state == "US-CO"

    def test_license_year_none(self) -> None:
        feature = _make_ra_feature("Rocky Mountain National Park")
        geom = self._call(feature)
        assert geom.license_year is None

    def test_kind_is_restricted_area(self) -> None:
        feature = _make_ra_feature("Rocky Mountain National Park")
        geom = self._call(feature)
        assert geom.kind == "restricted_area"

    def test_geometrycollection_raises_colorado_error(self) -> None:
        """When geojson_to_multipolygon_wkt raises ArcGISError, ColoradoGeometryError is raised."""
        feature = _make_ra_feature("Rocky Mountain National Park")
        with patch(
            "states.colorado.load_restricted_areas.arcgis.geojson_to_multipolygon_wkt",
            side_effect=ArcGISError("GeometryCollection unsupported"),
        ):
            with pytest.raises(ColoradoGeometryError) as exc_info:
                self._call(feature)
        assert "Rocky Mountain National Park" in str(exc_info.value)

    def test_missing_unit_nm_raises(self) -> None:
        """A feature with no Unit_Nm property must raise ColoradoGeometryError."""
        feature = {
            "type": "Feature",
            "geometry": _SQUARE_POLYGON,
            "properties": {"OBJECTID": 1, "Des_Tp": "NP"},
        }
        with pytest.raises(ColoradoGeometryError) as exc_info:
            self._call(feature)
        assert "Unit_Nm" in str(exc_info.value)

    def test_missing_properties_key_raises_colorado_error(self) -> None:
        """A feature lacking a 'properties' key must raise ColoradoGeometryError,
        not a bare KeyError (fail-loud contract)."""
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


# ---------------------------------------------------------------------------
# TestCheckCountBand
# ---------------------------------------------------------------------------


class TestCheckCountBand:
    def test_no_raise_at_exact_10(self) -> None:
        lo, hi = _RA_COUNT_GUARD_BAND
        assert lo == 10, f"guard band lower bound changed to {lo}; update this test"
        assert hi == 10, f"guard band upper bound changed to {hi}; update this test"
        _check_count_band(10)  # must not raise

    def test_raises_at_9(self) -> None:
        """9 → Curecanti-leak guard fires."""
        with pytest.raises(RuntimeError) as exc_info:
            _check_count_band(9)
        assert "9" in str(exc_info.value)

    def test_raises_at_11(self) -> None:
        """11 → new zone appeared without review."""
        with pytest.raises(RuntimeError) as exc_info:
            _check_count_band(11)
        assert "11" in str(exc_info.value)


# ---------------------------------------------------------------------------
# TestDuplicateIds
# ---------------------------------------------------------------------------


class TestDuplicateIds:
    def _make_geom(self, unit_nm: str, objectid: int = 1) -> Geometry:
        return _feature_to_geometry(
            _make_ra_feature(unit_nm, objectid=objectid),
            _make_metadata(),
            _make_citation(),
            logger=_TEST_LOGGER,
        )

    def test_returns_repeated_id_once(self) -> None:
        g1 = self._make_geom("Rocky Mountain National Park", objectid=1)
        g2 = self._make_geom("Rocky Mountain National Park", objectid=2)  # same Unit_Nm → same id
        g3 = self._make_geom("Mesa Verde National Park", objectid=3)
        dupes = _duplicate_ids([g1, g2, g3])
        assert dupes == ["CO-restricted-rocky-mountain-national-park-geom"]

    def test_unique_list_returns_empty(self) -> None:
        g1 = self._make_geom("Rocky Mountain National Park")
        g2 = self._make_geom("Mesa Verde National Park", objectid=2)
        assert _duplicate_ids([g1, g2]) == []

    def test_empty_input_returns_empty(self) -> None:
        assert _duplicate_ids([]) == []


# ---------------------------------------------------------------------------
# TestAssertCurecantiDropped
# ---------------------------------------------------------------------------


class TestAssertCurecantiDropped:
    def _make_geom_with_id(self, geom_id: str) -> Geometry:
        """Build a Geometry with an arbitrary id via model_copy."""
        base = _feature_to_geometry(
            _make_ra_feature("Rocky Mountain National Park"),
            _make_metadata(),
            _make_citation(),
            logger=_TEST_LOGGER,
        )
        return base.model_copy(update={"id": geom_id})

    def test_curecanti_present_raises(self) -> None:
        """List containing the Curecanti geom id must raise RuntimeError."""
        geoms = [self._make_geom_with_id(_CURECANTI_GEOM_ID)]
        with pytest.raises(RuntimeError) as exc_info:
            _assert_curecanti_dropped(geoms)
        msg = str(exc_info.value)
        assert "Curecanti" in msg or _CURECANTI_GEOM_ID in msg

    def test_curecanti_absent_passes(self) -> None:
        """List without Curecanti must not raise."""
        geoms = [self._make_geom_with_id("CO-restricted-rocky-mountain-national-park-geom")]
        _assert_curecanti_dropped(geoms)  # must not raise

    def test_empty_list_passes(self) -> None:
        """Empty list must not raise."""
        _assert_curecanti_dropped([])  # must not raise


# ---------------------------------------------------------------------------
# TestFetchAndBuild
# ---------------------------------------------------------------------------


def _request_side_effect(
    session: Any,
    url: str,
    params: dict[str, Any],
    host: str,
) -> dict[str, Any]:
    """Stateless side-effect for _request_with_retry: count call vs feature page."""
    if params.get("returnCountOnly") == "true":
        return {"count": 11}
    return {"type": "FeatureCollection", "features": _make_11_features()}


class TestFetchAndBuild:
    def _run_fetch(
        self,
        tmp_path: Path,
        *,
        request_side_effect: Any = None,
    ) -> list[Geometry]:
        """Run _fetch_and_build with all network + IO patches applied."""
        side_effect = request_side_effect or _request_side_effect
        with (
            patch(
                "states.colorado.load_restricted_areas.arcgis.fetch_layer_metadata",
                return_value=_make_metadata(),
            ),
            patch(
                "states.colorado.load_restricted_areas.arcgis._request_with_retry",
                side_effect=side_effect,
            ),
            patch(
                "states.colorado.load_restricted_areas.arcgis._check_and_fix_projection",
                side_effect=lambda features, *, declared_native_crs_wkid=None: features,
            ),
            patch("states.colorado.load_restricted_areas.arcgis._write_features_fixture"),
            patch("states.colorado.load_restricted_areas.arcgis._write_manifest_fixture"),
            patch(
                "states.colorado.load_restricted_areas.arcgis.compute_feature_hash",
                return_value="aa" * 32,
            ),
            patch(
                "states.colorado.load_restricted_areas.arcgis._read_objectid",
                return_value=1,
            ),
            patch(
                "states.colorado.load_restricted_areas.arcgis._utc_timestamp",
                return_value="20260603T120000Z",
            ),
        ):
            return _fetch_and_build(
                PADUS_SERVICE_URL,
                tmp_path,
                2026,
                session=MagicMock(),
                logger=_TEST_LOGGER,
            )

    def test_curecanti_dropped_returns_10_geometries(self, tmp_path: Path) -> None:
        """11 raw features → Curecanti dropped → exactly 10 Geometry objects."""
        result = self._run_fetch(tmp_path)
        assert len(result) == 10
        assert _CURECANTI_GEOM_ID not in {g.id for g in result}

    def test_returned_ids_match_v1_expected_ids(self, tmp_path: Path) -> None:
        """Returned ids must equal _V1_EXPECTED_IDS exactly."""
        result = self._run_fetch(tmp_path)
        assert {g.id for g in result} == _V1_EXPECTED_IDS

    def test_v1_where_passed_on_both_calls(self, tmp_path: Path) -> None:
        """Both the count call and the feature-page call must use _V1_WHERE."""
        captured: list[dict[str, Any]] = []

        def _capture(
            session: Any, url: str, params: dict[str, Any], host: str
        ) -> dict[str, Any]:
            captured.append(params)
            return _request_side_effect(session, url, params, host)

        self._run_fetch(tmp_path, request_side_effect=_capture)

        assert len(captured) == 2, f"expected 2 _request_with_retry calls, got {len(captured)}"
        for params in captured:
            assert params.get("where") == _V1_WHERE, (
                f"WHERE clause mismatch in params: {params}"
            )

    def test_feature_query_uses_outsr_4326_and_geojson(self, tmp_path: Path) -> None:
        """Feature-page params must include outSR=4326 and f='geojson'."""
        feature_params: list[dict[str, Any]] = []

        def _capture(
            session: Any, url: str, params: dict[str, Any], host: str
        ) -> dict[str, Any]:
            if params.get("returnCountOnly") == "true":
                return {"count": 11}
            feature_params.append(params)
            return {"type": "FeatureCollection", "features": _make_11_features()}

        self._run_fetch(tmp_path, request_side_effect=_capture)

        assert len(feature_params) == 1, "expected exactly one feature-page call"
        p = feature_params[0]
        assert p.get("outSR") == 4326
        assert p.get("f") == "geojson"

    def test_fetch_raises_on_transfer_limit(self, tmp_path: Path) -> None:
        """exceededTransferLimit=True → ArcGISError."""

        def _transfer_limit(
            session: Any, url: str, params: dict[str, Any], host: str
        ) -> dict[str, Any]:
            if params.get("returnCountOnly") == "true":
                return {"count": 11}
            return {
                "type": "FeatureCollection",
                "features": _make_11_features(),
                "exceededTransferLimit": True,
            }

        with pytest.raises(ArcGISError):
            self._run_fetch(tmp_path, request_side_effect=_transfer_limit)

    def test_fetch_raises_on_count_mismatch(self, tmp_path: Path) -> None:
        """returnCountOnly=11 but page returns 5 features → ArcGISError."""

        def _mismatch(
            session: Any, url: str, params: dict[str, Any], host: str
        ) -> dict[str, Any]:
            if params.get("returnCountOnly") == "true":
                return {"count": 11}
            return {"type": "FeatureCollection", "features": _make_11_features()[:5]}

        with pytest.raises(ArcGISError):
            self._run_fetch(tmp_path, request_side_effect=_mismatch)


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_no_commit_on_duplicate_id_guard(self) -> None:
        """Duplicate geometry id → pre-connect guard raises; commit NOT called."""
        mock_conn, _ = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)

        # Two features with the same Unit_Nm → same id → duplicate
        citation = _make_citation()
        metadata = _make_metadata()
        g1 = _feature_to_geometry(
            _make_ra_feature("Rocky Mountain National Park", objectid=1),
            metadata, citation, logger=_TEST_LOGGER,
        )
        g2 = _feature_to_geometry(
            _make_ra_feature("Rocky Mountain National Park", objectid=2),
            metadata, citation, logger=_TEST_LOGGER,
        )
        dupe_geoms = [g1, g2]

        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "states.colorado.load_restricted_areas.arcgis._build_session",
                return_value=session_cm,
            ),
            patch(
                "states.colorado.load_restricted_areas._fetch_and_build",
                return_value=dupe_geoms,
            ),
            patch(
                "states.colorado.load_restricted_areas.db.connect",
                return_value=connect_cm,
            ),
            pytest.raises(RuntimeError),
        ):
            main([])

        mock_conn.commit.assert_not_called()

    def test_main_no_commit_on_count_band_guard(self) -> None:
        """9 geometries → _check_count_band raises; commit NOT called."""
        mock_conn, _ = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)

        # 9 unique geoms — below the exact-10 band
        citation = _make_citation()
        metadata = _make_metadata()
        nine_geoms = [
            _feature_to_geometry(
                _make_ra_feature(_V1_UNIT_NMS[i], objectid=i + 1),
                metadata, citation, logger=_TEST_LOGGER,
            )
            for i in range(9)
        ]
        assert len(nine_geoms) == 9

        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "states.colorado.load_restricted_areas.arcgis._build_session",
                return_value=session_cm,
            ),
            patch(
                "states.colorado.load_restricted_areas._fetch_and_build",
                return_value=nine_geoms,
            ),
            patch(
                "states.colorado.load_restricted_areas.db.connect",
                return_value=connect_cm,
            ),
            pytest.raises(RuntimeError),
        ):
            main([])

        mock_conn.commit.assert_not_called()

    def test_main_no_commit_on_curecanti_present(self) -> None:
        """10 geoms but one has Curecanti id → _assert_curecanti_dropped raises; no commit."""
        mock_conn, _ = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)

        # 9 valid V1 geoms + 1 geom whose id is the Curecanti id
        citation = _make_citation()
        metadata = _make_metadata()
        nine_geoms = [
            _feature_to_geometry(
                _make_ra_feature(_V1_UNIT_NMS[i], objectid=i + 1),
                metadata, citation, logger=_TEST_LOGGER,
            )
            for i in range(9)
        ]
        curecanti_geom = _feature_to_geometry(
            _make_ra_feature(_CURECANTI_UNIT_NM, des_tp="NRA", objectid=10),
            metadata, citation, logger=_TEST_LOGGER,
        )
        assert curecanti_geom.id == _CURECANTI_GEOM_ID
        geoms_with_curecanti = nine_geoms + [curecanti_geom]
        assert len(geoms_with_curecanti) == 10

        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "states.colorado.load_restricted_areas.arcgis._build_session",
                return_value=session_cm,
            ),
            patch(
                "states.colorado.load_restricted_areas._fetch_and_build",
                return_value=geoms_with_curecanti,
            ),
            patch(
                "states.colorado.load_restricted_areas.db.connect",
                return_value=connect_cm,
            ),
            pytest.raises(RuntimeError),
        ):
            main([])

        mock_conn.commit.assert_not_called()

    def test_main_happy_path_commits(self) -> None:
        """Valid 10 geoms → main() returns 0 and conn.commit called exactly once."""
        mock_conn, _ = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)

        valid_geoms = _make_10_valid_geoms()

        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "states.colorado.load_restricted_areas.arcgis._build_session",
                return_value=session_cm,
            ),
            patch(
                "states.colorado.load_restricted_areas._fetch_and_build",
                return_value=valid_geoms,
            ),
            patch(
                "states.colorado.load_restricted_areas.db.connect",
                return_value=connect_cm,
            ),
            patch("states.colorado.load_restricted_areas.db.upsert_geometries"),
        ):
            result = main([])

        assert result == 0
        mock_conn.commit.assert_called_once()

    def test_main_no_commit_on_unexpected_ids(self) -> None:
        """_fetch_and_build returns 10 geoms where one id is NOT in _V1_EXPECTED_IDS
        (e.g. a PAD-US Unit_Nm rename) → ids guard raises; commit NOT called."""
        mock_conn, _ = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)

        # Build 9 valid V1 geoms + 1 with an unexpected id (renamed unit).
        citation = _make_citation()
        metadata = _make_metadata()
        nine_geoms = [
            _feature_to_geometry(
                _make_ra_feature(_V1_UNIT_NMS[i], objectid=i + 1),
                metadata, citation, logger=_TEST_LOGGER,
            )
            for i in range(9)
        ]
        # Produce a geom with a wrong id by building from a renamed unit name.
        renamed_geom = _feature_to_geometry(
            _make_ra_feature("Rocky Mountain NP", objectid=10),
            metadata, citation, logger=_TEST_LOGGER,
        )
        # Confirm the renamed id is not in _V1_EXPECTED_IDS.
        assert renamed_geom.id not in _V1_EXPECTED_IDS
        unexpected_geoms = nine_geoms + [renamed_geom]
        assert len(unexpected_geoms) == 10

        mock_session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=mock_session)
        session_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "states.colorado.load_restricted_areas.arcgis._build_session",
                return_value=session_cm,
            ),
            patch(
                "states.colorado.load_restricted_areas._fetch_and_build",
                return_value=unexpected_geoms,
            ),
            patch(
                "states.colorado.load_restricted_areas.db.connect",
                return_value=connect_cm,
            ),
            pytest.raises(RuntimeError),
        ):
            main([])

        mock_conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# TestFetchAndBuildMissingFeaturesKey
# ---------------------------------------------------------------------------


class TestFetchAndBuildMissingFeaturesKey:
    """Tests for the explicit 'features' key guard added by Fix P1."""

    def test_fetch_raises_on_missing_features_key(self, tmp_path: Path) -> None:
        """Feature-page response missing 'features' key → ArcGISError raised."""

        def _no_features_key(
            session: Any,
            url: str,
            params: dict[str, Any],
            host: str,
        ) -> dict[str, Any]:
            if params.get("returnCountOnly") == "true":
                return {"count": 11}
            # Response has no 'features' key at all.
            return {"type": "FeatureCollection"}

        with (
            patch(
                "states.colorado.load_restricted_areas.arcgis.fetch_layer_metadata",
                return_value=_make_metadata(),
            ),
            patch(
                "states.colorado.load_restricted_areas.arcgis._request_with_retry",
                side_effect=_no_features_key,
            ),
            patch(
                "states.colorado.load_restricted_areas.arcgis._check_and_fix_projection",
                side_effect=lambda features, *, declared_native_crs_wkid=None: features,
            ),
            patch("states.colorado.load_restricted_areas.arcgis._write_features_fixture"),
            patch("states.colorado.load_restricted_areas.arcgis._write_manifest_fixture"),
            patch(
                "states.colorado.load_restricted_areas.arcgis._utc_timestamp",
                return_value="20260603T120000Z",
            ),
            pytest.raises(ArcGISError),
        ):
            _fetch_and_build(
                PADUS_SERVICE_URL,
                tmp_path,
                2026,
                session=MagicMock(),
                logger=_TEST_LOGGER,
            )


# ---------------------------------------------------------------------------
# TestNoLibImports
# ---------------------------------------------------------------------------


class TestNoLibImports:
    """Ensure load_restricted_areas.py imports no sibling state adapter (ADR-005)."""

    def _loader_path(self) -> Path:
        spec = importlib.util.find_spec("states.colorado.load_restricted_areas")
        assert spec is not None and spec.origin is not None
        return Path(spec.origin)

    def test_no_montana_imports(self) -> None:
        """load_restricted_areas.py must not import from states.montana."""
        source = self._loader_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        forbidden_prefixes = ("states.montana", "ingestion.states.montana")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"load_restricted_areas.py has forbidden import: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for prefix in forbidden_prefixes:
                    assert not module.startswith(prefix), (
                        f"load_restricted_areas.py has forbidden from-import: from {module}"
                    )

    def test_no_other_state_adapter_imports(self) -> None:
        """load_restricted_areas.py must not import any sibling state adapter (ADR-005).

        Broader than the Montana-specific guard: catches any
        ``states.<other>`` / ``ingestion.states.<other>`` import where
        ``<other>`` is not ``colorado``.
        """
        source = self._loader_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        def _offending(module: str) -> bool:
            for root in ("states.", "ingestion.states."):
                if module.startswith(root):
                    sibling = module[len(root) :].split(".", 1)[0]
                    if sibling != "colorado":
                        return True
            return False

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not _offending(alias.name), (
                        f"load_restricted_areas.py imports a non-Colorado state adapter: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not _offending(module), (
                    f"load_restricted_areas.py imports a non-Colorado state adapter: from {module}"
                )


class TestStateAdapterOutFieldsIncludeObjectid:
    """S06.6.1: every module-level ``_*_OUT_FIELDS`` tuple in the CO state-adapter
    dir must include ``"OBJECTID"``.

    The PAD-US 4.1 republish (2026-06) omits the top-level GeoJSON ``id`` unless
    OBJECTID is in the request outFields, so a loader that hardcodes an outFields
    tuple without OBJECTID writes 0 rows (fail-loud in the manifest-hash loop). A
    future CO loader that adds such a tuple without OBJECTID fails this test at
    PR-time. AST-walks every ``.py`` in the dir so the guard is not pinned to the
    single tuple that exists today.
    """

    def _co_adapter_dir(self) -> Path:
        spec = importlib.util.find_spec("states.colorado.load_restricted_areas")
        assert spec is not None and spec.origin is not None
        return Path(spec.origin).parent

    def _collect_out_fields_tuples(self) -> dict[str, list[str]]:
        # Scope: direct module-level tuple/list literal assignments only
        # (mirrors the TestNoLibImports AST-walk convention). A constant built
        # by concatenation (e.g. `_BASE + ("OBJECTID",)`) or an inline outFields
        # string at the call site is out of this guard's reach.
        collected: dict[str, list[str]] = {}
        for path in sorted(self._co_adapter_dir().glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if not (isinstance(target, ast.Name) and target.id.endswith("_OUT_FIELDS")):
                        continue
                    if not isinstance(node.value, (ast.Tuple, ast.List)):
                        continue
                    string_elts = [
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
                    collected[f"{path.name}:{target.id}"] = string_elts
        return collected

    def test_every_out_fields_tuple_includes_objectid(self) -> None:
        collected = self._collect_out_fields_tuples()
        # Fail loud rather than pass vacuously if the glob/AST-walk finds nothing
        # (and pin that at least _RA_OUT_FIELDS is discovered).
        assert collected, (
            "no _*_OUT_FIELDS tuples found in the CO state-adapter dir — the "
            "guard cannot function; expected at least _RA_OUT_FIELDS in "
            "load_restricted_areas.py"
        )
        for key, elts in collected.items():
            assert "OBJECTID" in elts, f"{key} is missing 'OBJECTID' (S06.6.1)"
