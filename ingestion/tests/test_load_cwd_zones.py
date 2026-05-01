"""Unit tests for ingestion.states.montana.load_cwd_zones — pure-function, no real HTTP or DB."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import states.montana.load_cwd_zones as load_cwd
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry, SourceCitation
from states.montana.load_cwd_zones import (
    ID_PREFIX,
    MT_AGENCY,
    MT_FWP_CWD_FEATURESERVER_URL,
    MT_FWP_CWD_LAYER_ID,
    MT_STATE_CODE,
    _duplicate_ids,
    _extract_areaname,
    _extract_license_year,
    _feature_to_geometry,
    _load_layer,
    _slugify,
)

# ---------------------------------------------------------------------------
# Shared constants and fixtures
# ---------------------------------------------------------------------------

SERVICE_URL = MT_FWP_CWD_FEATURESERVER_URL
LAYER_ID = MT_FWP_CWD_LAYER_ID

_PROPS_LIBBY: dict[str, Any] = {
    "OBJECTID": 1,
    "AREANAME": "Libby CWD Management Zone",
    "AREATYPE": "CWD Management Hunt Area",
    "SQMILES": 499,
    "REG": 1,
    "WEBPAGE": "http://fwp.mt.gov/cwd",
    "VALID_DATES": None,
    "REGYEAR": "2026",
}

_PROPS_KALISPELL: dict[str, Any] = {
    "OBJECTID": 2,
    "AREANAME": "Kalispell CWD Management Zone",
    "AREATYPE": "CWD Management Hunt Area",
    "SQMILES": 154,
    "REG": 1,
    "WEBPAGE": "http://fwp.mt.gov/cwd",
    "VALID_DATES": None,
    "REGYEAR": "2026",
}

# Small rectangles around each zone's approximate center
_FEATURE_LIBBY: dict[str, Any] = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [-115.6, 48.35],
                [-115.5, 48.35],
                [-115.5, 48.42],
                [-115.6, 48.42],
                [-115.6, 48.35],
            ]
        ],
    },
    "properties": _PROPS_LIBBY,
}

_FEATURE_KALISPELL: dict[str, Any] = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [-114.4, 48.15],
                [-114.3, 48.15],
                [-114.3, 48.22],
                [-114.4, 48.22],
                [-114.4, 48.15],
            ]
        ],
    },
    "properties": _PROPS_KALISPELL,
}


def _make_metadata(
    name: str = "ADMBND_HD_CWD",
    fields: tuple[str, ...] = (
        "OBJECTID",
        "AREANAME",
        "AREATYPE",
        "SQMILES",
        "REG",
        "WEBPAGE",
        "VALID_DATES",
        "REGYEAR",
    ),
) -> LayerMetadata:
    return LayerMetadata(
        name=name,
        object_id_field="OBJECTID",
        max_record_count=2000,
        out_fields=fields,
        geometry_type="esriGeometryPolygon",
        last_edit_date_ms=None,
        raw={},
        spatial_reference_wkid=4326,
    )


@pytest.fixture
def sample_metadata() -> LayerMetadata:
    return _make_metadata()


@pytest.fixture
def sample_citation() -> SourceCitation:
    return SourceCitation(
        id="mt-fwp-arcgis-ADMBND_HD_CWD-0-2026",
        agency=MT_AGENCY,
        title="ADMBND_HD_CWD (Layer 0)",
        url=f"{SERVICE_URL}/0",
        publication_date="2026-01-01",
        document_type="gis_layer",
    )


# ---------------------------------------------------------------------------
# Patching helpers
# ---------------------------------------------------------------------------


def _patch_arcgis(monkeypatch: pytest.MonkeyPatch, citation: SourceCitation) -> None:
    monkeypatch.setattr(
        load_cwd.arcgis,
        "geojson_to_multipolygon_wkt",
        lambda f: "MULTIPOLYGON (((-115.6 48.35, -115.5 48.35, -115.5 48.42, -115.6 48.42, -115.6 48.35)))",
    )
    monkeypatch.setattr(
        load_cwd.arcgis,
        "build_source_citation",
        lambda **kwargs: citation,
    )


def _patch_load_layer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    features: list[dict[str, Any]],
    metadata: LayerMetadata,
    citation: SourceCitation,
) -> None:
    monkeypatch.setattr(
        load_cwd.arcgis,
        "fetch_layer_metadata",
        lambda *args, **kwargs: metadata,
    )
    monkeypatch.setattr(
        load_cwd.arcgis,
        "fetch_features",
        lambda *args, **kwargs: features,
    )
    monkeypatch.setattr(
        load_cwd.arcgis,
        "build_source_citation",
        lambda **kwargs: citation,
    )
    monkeypatch.setattr(
        load_cwd.arcgis,
        "geojson_to_multipolygon_wkt",
        lambda f: "MULTIPOLYGON (((-115.6 48.35, -115.5 48.35, -115.5 48.42, -115.6 48.42, -115.6 48.35)))",
    )


# ---------------------------------------------------------------------------
# TestSlugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_ascii_name_produces_expected_slug(self) -> None:
        assert _slugify("Libby CWD Management Zone") == "libby-cwd-management-zone"

    def test_mixed_punctuation_collapses_to_hyphens(self) -> None:
        assert _slugify("North/South: Zone (A)") == "north-south-zone-a"

    def test_pre_existing_hyphens_preserved(self) -> None:
        assert _slugify("Deer-Elk Zone") == "deer-elk-zone"

    def test_multiple_non_alphanumeric_collapses_to_single_hyphen(self) -> None:
        assert _slugify("Zone  --  Alpha") == "zone-alpha"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("   ")

    def test_non_alphanumeric_only_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("---")

    def test_special_chars_only_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("!@#$")

    def test_mixed_case_lowercased(self) -> None:
        assert _slugify("CWD Zone ABC") == "cwd-zone-abc"

    def test_numeric_preserved(self) -> None:
        assert _slugify("Zone 123") == "zone-123"


# ---------------------------------------------------------------------------
# TestExtractLicenseYear
# ---------------------------------------------------------------------------


class TestExtractLicenseYear:
    def test_string_numeric_regyear_returns_int(self) -> None:
        result = _extract_license_year({"REGYEAR": "2026"})
        assert result == 2026
        assert isinstance(result, int)

    def test_integer_regyear_returns_int(self) -> None:
        result = _extract_license_year({"REGYEAR": 2026})
        assert result == 2026
        assert isinstance(result, int)

    def test_regyear_none_raises(self) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_license_year({"REGYEAR": None})
        assert "REGYEAR" in str(exc_info.value)

    def test_regyear_missing_raises(self) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_license_year({})
        assert "REGYEAR" in str(exc_info.value)

    def test_regyear_non_numeric_string_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _extract_license_year({"REGYEAR": "not a year"})

    def test_regyear_float_string_raises(self) -> None:
        # "2026.5" is not a valid integer
        with pytest.raises(ArcGISError):
            _extract_license_year({"REGYEAR": "2026.5"})


# ---------------------------------------------------------------------------
# TestExtractAreaname
# ---------------------------------------------------------------------------


class TestExtractAreaname:
    def test_valid_areaname_returned(self, sample_metadata: LayerMetadata) -> None:
        result = _extract_areaname({"AREANAME": "Libby CWD Management Zone"}, sample_metadata)
        assert result == "Libby CWD Management Zone"

    def test_areaname_empty_raises(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_areaname({"AREANAME": ""}, sample_metadata)

    def test_areaname_whitespace_raises(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_areaname({"AREANAME": "   "}, sample_metadata)

    def test_areaname_none_raises(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_areaname({"AREANAME": None}, sample_metadata)

    def test_areaname_missing_raises(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_areaname({}, sample_metadata)
        msg = str(exc_info.value)
        assert sample_metadata.name in msg
        assert "available=" in msg

    def test_error_message_includes_layer_name(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_areaname({"AREANAME": ""}, sample_metadata)
        assert sample_metadata.name in str(exc_info.value)


# ---------------------------------------------------------------------------
# TestFeatureToGeometry
# ---------------------------------------------------------------------------


class TestFeatureToGeometry:
    def test_libby_zone_happy_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            _FEATURE_LIBBY, sample_metadata, SERVICE_URL, LAYER_ID
        )
        assert isinstance(result, Geometry)
        assert result.id == f"{ID_PREFIX}-libby-cwd-management-zone-geom"
        assert result.name == "Libby CWD Management Zone"
        assert result.kind == "cwd_zone"
        assert result.state == MT_STATE_CODE
        assert result.license_year == 2026
        assert result.verbatim_rule is None
        assert result.source.document_type == "gis_layer"
        assert result.source.agency == MT_AGENCY

    def test_kalispell_zone_slug_derivation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            _FEATURE_KALISPELL, sample_metadata, SERVICE_URL, LAYER_ID
        )
        assert result.id == f"{ID_PREFIX}-kalispell-cwd-management-zone-geom"
        assert result.name == "Kalispell CWD Management Zone"
        assert result.kind == "cwd_zone"

    def test_verbatim_rule_is_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        """WEBPAGE field is a URL, not prose — verbatim_rule must remain None."""
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            _FEATURE_LIBBY, sample_metadata, SERVICE_URL, LAYER_ID
        )
        assert result.verbatim_rule is None

    def test_license_year_from_regyear(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        feature = copy.deepcopy(_FEATURE_LIBBY)
        feature["properties"]["REGYEAR"] = "2025"
        result = _feature_to_geometry(
            feature, sample_metadata, SERVICE_URL, LAYER_ID
        )
        assert result.license_year == 2025

    def test_citation_receives_correct_license_year(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        # REGYEAR is set to 2025 (not the 2026 default) so the assertion
        # proves the citation's license_year was built from the parsed REGYEAR,
        # not from another year-shaped value sneaking through.
        captured: dict[str, Any] = {}

        def fake_citation(**kwargs: Any) -> SourceCitation:
            captured.update(kwargs)
            return sample_citation

        monkeypatch.setattr(load_cwd.arcgis, "build_source_citation", fake_citation)
        monkeypatch.setattr(
            load_cwd.arcgis,
            "geojson_to_multipolygon_wkt",
            lambda f: "MULTIPOLYGON (((-115.6 48.35, -115.5 48.35, -115.5 48.42, -115.6 48.42, -115.6 48.35)))",
        )
        feature = copy.deepcopy(_FEATURE_LIBBY)
        feature["properties"]["REGYEAR"] = "2025"
        _feature_to_geometry(feature, sample_metadata, SERVICE_URL, LAYER_ID)
        assert captured["license_year"] == 2025

    def test_state_code_is_us_mt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            _FEATURE_LIBBY, sample_metadata, SERVICE_URL, LAYER_ID
        )
        assert result.state == "US-MT"


# ---------------------------------------------------------------------------
# TestDuplicateIds
# ---------------------------------------------------------------------------


def _make_geom(geom_id: str) -> Geometry:
    return Geometry(
        id=geom_id,
        name=geom_id,
        kind="cwd_zone",
        geom="MULTIPOLYGON (((-115.6 48.35, -115.5 48.35, -115.5 48.42, -115.6 48.42, -115.6 48.35)))",
        state="US-MT",
        license_year=2026,
        verbatim_rule=None,
        source=SourceCitation(
            id="mt-fwp-arcgis-ADMBND_HD_CWD-0-2026",
            agency=MT_AGENCY,
            title="ADMBND_HD_CWD (Layer 0)",
            url=f"{SERVICE_URL}/0",
            publication_date="2026-01-01",
            document_type="gis_layer",
        ),
    )


class TestDuplicateIds:
    def test_empty_list_returns_empty(self) -> None:
        assert _duplicate_ids([]) == []

    def test_unique_geoms_returns_empty(self) -> None:
        geoms = [_make_geom("MT-CWD-zone-libby-geom"), _make_geom("MT-CWD-zone-kalispell-geom")]
        assert _duplicate_ids(geoms) == []

    def test_two_same_id_returns_that_id(self) -> None:
        geoms = [_make_geom("MT-CWD-zone-libby-geom"), _make_geom("MT-CWD-zone-libby-geom")]
        result = _duplicate_ids(geoms)
        assert result == ["MT-CWD-zone-libby-geom"]

    def test_multiple_duplicates_returns_sorted_list(self) -> None:
        geoms = [
            _make_geom("MT-CWD-zone-beta-geom"),
            _make_geom("MT-CWD-zone-alpha-geom"),
            _make_geom("MT-CWD-zone-beta-geom"),
            _make_geom("MT-CWD-zone-alpha-geom"),
        ]
        result = _duplicate_ids(geoms)
        assert result == ["MT-CWD-zone-alpha-geom", "MT-CWD-zone-beta-geom"]

    def test_single_geom_returns_empty(self) -> None:
        geoms = [_make_geom("MT-CWD-zone-libby-geom")]
        assert _duplicate_ids(geoms) == []


# ---------------------------------------------------------------------------
# TestLoadLayer
# ---------------------------------------------------------------------------


class TestLoadLayer:
    def test_happy_path_two_features(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_load_layer(
            monkeypatch,
            features=[_FEATURE_LIBBY, _FEATURE_KALISPELL],
            metadata=sample_metadata,
            citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_cwd.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        result = _load_layer(conn, SERVICE_URL, LAYER_ID, tmp_path)

        mock_upsert.assert_called_once()
        upserted = mock_upsert.call_args[0][1]
        assert len(upserted) == 2
        assert len(result) == 2
        assert all(g.kind == "cwd_zone" for g in result)

    def test_zero_features_raises_before_upsert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_load_layer(
            monkeypatch,
            features=[],
            metadata=sample_metadata,
            citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_cwd.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError, match="zero features"):
            _load_layer(conn, SERVICE_URL, LAYER_ID, tmp_path)

        mock_upsert.assert_not_called()

    def test_duplicate_ids_raises_before_upsert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        feat_a = copy.deepcopy(_FEATURE_LIBBY)
        feat_b = copy.deepcopy(_FEATURE_LIBBY)
        # Both have the same AREANAME → same slug → duplicate ID
        _patch_load_layer(
            monkeypatch,
            features=[feat_a, feat_b],
            metadata=sample_metadata,
            citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_cwd.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError) as exc_info:
            _load_layer(conn, SERVICE_URL, LAYER_ID, tmp_path)

        assert "libby-cwd-management-zone" in str(exc_info.value)
        mock_upsert.assert_not_called()

    def test_single_feature_happy_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_load_layer(
            monkeypatch,
            features=[_FEATURE_LIBBY],
            metadata=sample_metadata,
            citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_cwd.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        result = _load_layer(conn, SERVICE_URL, LAYER_ID, tmp_path)

        mock_upsert.assert_called_once()
        upserted = mock_upsert.call_args[0][1]
        assert len(upserted) == 1
        assert len(result) == 1
        assert result[0].kind == "cwd_zone"

    def test_slug_collision_raises_before_upsert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        # Two distinct AREANAME spellings that slugify identically
        feat_a = copy.deepcopy(_FEATURE_LIBBY)
        feat_a["properties"]["AREANAME"] = "Libby Zone"
        feat_b = copy.deepcopy(_FEATURE_KALISPELL)
        feat_b["properties"]["AREANAME"] = "Libby-Zone"  # slugifies to same "libby-zone"

        _patch_load_layer(
            monkeypatch,
            features=[feat_a, feat_b],
            metadata=sample_metadata,
            citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_cwd.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError) as exc_info:
            _load_layer(conn, SERVICE_URL, LAYER_ID, tmp_path)

        assert "libby-zone" in str(exc_info.value)
        mock_upsert.assert_not_called()

    def test_upsert_geometries_raise_propagates(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        # Locks in the contract that an exception inside db.upsert_geometries
        # propagates out of _load_layer (so main() skips conn.commit() and the
        # connection's __exit__ rolls back). A future try/except around the
        # upsert that converted the error to a log-only would be a silent
        # partial-write regression — this test catches that.
        _patch_load_layer(
            monkeypatch,
            features=[_FEATURE_LIBBY, _FEATURE_KALISPELL],
            metadata=sample_metadata,
            citation=sample_citation,
        )

        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("simulated upsert failure mid-batch")

        monkeypatch.setattr(load_cwd.db, "upsert_geometries", boom)

        conn = MagicMock()
        with pytest.raises(RuntimeError, match="simulated upsert failure"):
            _load_layer(conn, SERVICE_URL, LAYER_ID, tmp_path)


# ---------------------------------------------------------------------------
# TestMainCommitAtomicity
# ---------------------------------------------------------------------------


class TestMainCommitAtomicity:
    """Verify the single atomic-commit boundary.

    Locks in the contract that `conn.commit()` is called exactly once after
    `_load_layer` succeeds, and NOT called when `_load_layer` raises.
    """

    def test_commit_called_once_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_conn = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        connect_cm = MagicMock()
        connect_cm.__enter__ = MagicMock(return_value=mock_conn)
        connect_cm.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(load_cwd.arcgis, "_build_session", lambda: mock_session)
        monkeypatch.setattr(load_cwd.db, "connect", lambda: connect_cm)
        monkeypatch.setattr(load_cwd, "_load_layer", lambda *a, **kw: [])

        result = load_cwd.main([])

        assert result == 0
        mock_conn.commit.assert_called_once()

    def test_commit_not_called_when_load_layer_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_conn = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        connect_cm = MagicMock()
        connect_cm.__enter__ = MagicMock(return_value=mock_conn)
        connect_cm.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(load_cwd.arcgis, "_build_session", lambda: mock_session)
        monkeypatch.setattr(load_cwd.db, "connect", lambda: connect_cm)
        monkeypatch.setattr(
            load_cwd,
            "_load_layer",
            lambda *a, **kw: (_ for _ in ()).throw(ArcGISError("simulated CWD load failure")),
        )

        with pytest.raises(ArcGISError, match="simulated CWD load failure"):
            load_cwd.main([])

        mock_conn.commit.assert_not_called()
