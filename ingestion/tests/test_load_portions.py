"""Unit tests for ingestion.states.montana.load_portions — pure-function, no real HTTP or DB."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import states.montana.load_portions as load_portions_module
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry, SourceCitation
from states.montana.load_portions import (
    PORTION_LAYERS,
    PortionLayerConfig,
    _extract_district,
    _extract_license_year,
    _extract_portion_slug,
    _extract_verbatim_rule,
    _feature_to_geometry,
    _load_layer,
    _slugify,
)

# ---------------------------------------------------------------------------
# Shared constants and fixtures
# ---------------------------------------------------------------------------

SERVICE_URL = "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer"

SAMPLE_PORTION_FEATURE: dict[str, Any] = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [[-110.0, 45.0], [-109.0, 45.0], [-109.0, 46.0], [-110.0, 46.0], [-110.0, 45.0]]
        ],
    },
    "properties": {
        "DISTRICT": "262",
        "PORTIONNAME": "North Fork",
        "PORTIONTYPE": "north",
        "SHAPECODE": "262A",
        "REG": "Hunting permitted only with archery equipment.",
        "REGYEAR": 2026,
    },
}


@pytest.fixture
def sample_metadata() -> LayerMetadata:
    return LayerMetadata(
        name="Elk Portions",
        object_id_field="OBJECTID",
        max_record_count=2000,
        out_fields=("OBJECTID", "DISTRICT", "PORTIONNAME", "PORTIONTYPE", "SHAPECODE", "REG", "REGYEAR"),
        geometry_type="esriGeometryPolygon",
        last_edit_date_ms=None,
        raw={},
        spatial_reference_wkid=4326,
    )


@pytest.fixture
def sample_citation() -> SourceCitation:
    return SourceCitation(
        id="mt-fwp-arcgis-huntingDistricts-14-2026",
        agency="Montana Fish, Wildlife & Parks",
        title="Elk Portions (Layer 14)",
        url=f"{SERVICE_URL}/14",
        publication_date="2026-01-01",
        document_type="gis_layer",
    )


@pytest.fixture
def elk_config() -> PortionLayerConfig:
    return next(c for c in PORTION_LAYERS if c.species_slug == "elk")


@pytest.fixture
def antelope_config() -> PortionLayerConfig:
    return next(c for c in PORTION_LAYERS if c.species_slug == "antelope")


# ---------------------------------------------------------------------------
# _extract_district
# ---------------------------------------------------------------------------


class TestExtractDistrict:
    def test_returns_str_for_int_district(self, sample_metadata: LayerMetadata) -> None:
        result = _extract_district({"DISTRICT": 262}, sample_metadata)
        assert result == "262"
        assert isinstance(result, str)

    def test_returns_str_for_string_district(self, sample_metadata: LayerMetadata) -> None:
        result = _extract_district({"DISTRICT": "101"}, sample_metadata)
        assert result == "101"

    def test_raises_when_district_absent(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_district({}, sample_metadata)
        msg = str(exc_info.value)
        assert "missing DISTRICT" in msg
        assert "available=" in msg


# ---------------------------------------------------------------------------
# _extract_verbatim_rule
# ---------------------------------------------------------------------------


class TestExtractVerbatimRule:
    def test_returns_none_when_key_missing(self) -> None:
        assert _extract_verbatim_rule({}) is None

    def test_returns_none_when_value_is_none(self) -> None:
        assert _extract_verbatim_rule({"REG": None}) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _extract_verbatim_rule({"REG": ""}) is None

    def test_returns_none_for_whitespace_only(self) -> None:
        assert _extract_verbatim_rule({"REG": "   "}) is None

    def test_preserves_original_string_verbatim(self) -> None:
        result = _extract_verbatim_rule({"REG": "  Some text  "})
        assert result == "  Some text  "


# ---------------------------------------------------------------------------
# _extract_license_year
# ---------------------------------------------------------------------------


class TestExtractLicenseYear:
    def test_returns_int_for_int_input(self) -> None:
        assert _extract_license_year({"REGYEAR": 2026}) == 2026

    def test_returns_int_for_numeric_string(self) -> None:
        result = _extract_license_year({"REGYEAR": "2025"})
        assert result == 2025
        assert isinstance(result, int)

    def test_returns_none_when_key_missing(self) -> None:
        assert _extract_license_year({}) is None

    def test_returns_none_when_value_is_none(self) -> None:
        assert _extract_license_year({"REGYEAR": None}) is None

    def test_raises_for_non_numeric_string(self) -> None:
        with pytest.raises(ArcGISError):
            _extract_license_year({"REGYEAR": "not-a-year"})


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_single_word(self) -> None:
        assert _slugify("Bridger") == "bridger"

    def test_spaces_become_hyphens(self) -> None:
        assert _slugify("North Fork") == "north-fork"

    def test_collapses_non_alphanumeric_runs(self) -> None:
        assert _slugify("North/Fork & Co.") == "north-fork-co"

    def test_strips_leading_and_trailing_hyphens(self) -> None:
        assert _slugify("--North--") == "north"

    def test_raises_for_empty_string(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("")

    def test_raises_for_whitespace_only(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("   ")

    def test_raises_for_only_separators(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("---")


# ---------------------------------------------------------------------------
# _extract_portion_slug
# ---------------------------------------------------------------------------


class TestExtractPortionSlug:
    def test_shapecode_preferred_when_present(self, sample_metadata: LayerMetadata) -> None:
        props = {"DISTRICT": "262", "SHAPECODE": "262A", "PORTIONNAME": "North Fork"}
        result = _extract_portion_slug(props, sample_metadata, strategy="shapecode")
        assert result == "262A"

    def test_falls_back_to_portionname_when_shapecode_absent(self, sample_metadata: LayerMetadata) -> None:
        props = {"DISTRICT": "262", "PORTIONNAME": "North Fork"}
        result = _extract_portion_slug(props, sample_metadata, strategy="shapecode")
        assert result == "north-fork"

    def test_falls_back_when_shapecode_empty_string(self, sample_metadata: LayerMetadata) -> None:
        props = {"DISTRICT": "262", "SHAPECODE": "", "PORTIONNAME": "North Fork"}
        result = _extract_portion_slug(props, sample_metadata, strategy="shapecode")
        assert result == "north-fork"

    def test_falls_back_when_shapecode_whitespace_only(self, sample_metadata: LayerMetadata) -> None:
        props = {"DISTRICT": "262", "SHAPECODE": "   ", "PORTIONNAME": "North Fork"}
        result = _extract_portion_slug(props, sample_metadata, strategy="shapecode")
        assert result == "north-fork"

    def test_raises_when_both_absent(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_portion_slug({"DISTRICT": "262"}, sample_metadata, strategy="shapecode")
        msg = str(exc_info.value)
        assert "missing both SHAPECODE and PORTIONNAME" in msg
        assert "available=" in msg

    def test_raises_when_both_empty(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_portion_slug({"DISTRICT": "262", "SHAPECODE": "", "PORTIONNAME": ""}, sample_metadata, strategy="shapecode")

    def test_raises_when_shapecode_contains_space(self, sample_metadata: LayerMetadata) -> None:
        # SHAPECODE is embedded verbatim in hyphen-delimited geometry IDs.
        # Any non-id-safe character must fail loudly.
        with pytest.raises(ArcGISError) as exc_info:
            _extract_portion_slug({"DISTRICT": "262", "SHAPECODE": "262 A"}, sample_metadata, strategy="shapecode")
        assert "SHAPECODE" in str(exc_info.value)
        assert "[A-Za-z0-9_-]" in str(exc_info.value)

    def test_raises_when_shapecode_contains_slash(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_portion_slug({"DISTRICT": "262", "SHAPECODE": "262/A"}, sample_metadata, strategy="shapecode")

    def test_accepts_alphanumeric_and_hyphen_shapecode(self, sample_metadata: LayerMetadata) -> None:
        result = _extract_portion_slug(
            {"DISTRICT": "262", "SHAPECODE": "262-A_b"}, sample_metadata, strategy="shapecode"
        )
        assert result == "262-A_b"

    def test_portionname_strategy_ignores_shapecode(self, sample_metadata: LayerMetadata) -> None:
        # Under the portionname strategy, SHAPECODE is irrelevant — even if
        # present and well-formed, the slug comes from PORTIONNAME.
        props = {"DISTRICT": "262", "SHAPECODE": "262A", "PORTIONNAME": "North Fork"}
        result = _extract_portion_slug(props, sample_metadata, strategy="portionname")
        assert result == "north-fork"

    def test_portionname_strategy_raises_when_portionname_absent(
        self, sample_metadata: LayerMetadata,
    ) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_portion_slug(
                {"DISTRICT": "262", "SHAPECODE": "262A"}, sample_metadata, strategy="portionname"
            )
        assert "PORTIONNAME" in str(exc_info.value)
        assert "portionname strategy" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _feature_to_geometry
# ---------------------------------------------------------------------------


def _patch_arcgis(monkeypatch: pytest.MonkeyPatch, sample_citation: SourceCitation) -> None:
    monkeypatch.setattr(
        load_portions_module.arcgis,
        "geojson_to_multipolygon_wkt",
        lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
    )
    monkeypatch.setattr(
        load_portions_module.arcgis,
        "build_source_citation",
        lambda **kwargs: sample_citation,
    )


class TestFeatureToGeometry:
    def test_returns_geometry_with_kind_portion(
        self,
        monkeypatch: pytest.MonkeyPatch,
        elk_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            SAMPLE_PORTION_FEATURE, elk_config, sample_metadata, SERVICE_URL, fetch_year=2026,
            slug_strategy="shapecode",
        )
        assert isinstance(result, Geometry)
        assert result.kind == "portion"

    def test_id_uses_shapecode_when_present(
        self,
        monkeypatch: pytest.MonkeyPatch,
        elk_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            SAMPLE_PORTION_FEATURE, elk_config, sample_metadata, SERVICE_URL, fetch_year=2026,
            slug_strategy="shapecode",
        )
        assert result.id == "MT-HD-elk-262-portion-262A-geom"

    def test_id_uses_slugified_portionname_when_shapecode_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        elk_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        feature = {
            **SAMPLE_PORTION_FEATURE,
            "properties": {
                k: v for k, v in SAMPLE_PORTION_FEATURE["properties"].items()
                if k != "SHAPECODE"
            },
        }
        result = _feature_to_geometry(
            feature, elk_config, sample_metadata, SERVICE_URL, fetch_year=2026,
            slug_strategy="shapecode",
        )
        assert result.id == "MT-HD-elk-262-portion-north-fork-geom"

    def test_name_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        elk_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            SAMPLE_PORTION_FEATURE, elk_config, sample_metadata, SERVICE_URL, fetch_year=2026,
            slug_strategy="shapecode",
        )
        assert result.name == "Elk HD 262 portion 262A"

    def test_verbatim_rule_populated_from_reg(
        self,
        monkeypatch: pytest.MonkeyPatch,
        elk_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            SAMPLE_PORTION_FEATURE, elk_config, sample_metadata, SERVICE_URL, fetch_year=2026,
            slug_strategy="shapecode",
        )
        assert result.verbatim_rule == "Hunting permitted only with archery equipment."

    def test_verbatim_rule_none_when_reg_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        elk_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        feature = {
            **SAMPLE_PORTION_FEATURE,
            "properties": {**SAMPLE_PORTION_FEATURE["properties"], "REG": ""},
        }
        result = _feature_to_geometry(
            feature, elk_config, sample_metadata, SERVICE_URL, fetch_year=2026,
            slug_strategy="shapecode",
        )
        assert result.verbatim_rule is None

    def test_license_year_matches_regyear(
        self,
        monkeypatch: pytest.MonkeyPatch,
        elk_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            SAMPLE_PORTION_FEATURE, elk_config, sample_metadata, SERVICE_URL, fetch_year=2026,
            slug_strategy="shapecode",
        )
        assert result.license_year == 2026

    def test_citation_uses_regyear_when_present(
        self,
        monkeypatch: pytest.MonkeyPatch,
        elk_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_citation(**kwargs: Any) -> SourceCitation:
            captured.update(kwargs)
            return sample_citation

        monkeypatch.setattr(load_portions_module.arcgis, "build_source_citation", fake_citation)
        monkeypatch.setattr(
            load_portions_module.arcgis,
            "geojson_to_multipolygon_wkt",
            lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
        )
        _feature_to_geometry(
            SAMPLE_PORTION_FEATURE, elk_config, sample_metadata, SERVICE_URL,
            fetch_year=2099, slug_strategy="shapecode",
        )
        assert captured["license_year"] == 2026  # from REGYEAR, not fetch_year

    def test_citation_falls_back_to_fetch_year_when_regyear_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        antelope_config: PortionLayerConfig,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_citation(**kwargs: Any) -> SourceCitation:
            captured.update(kwargs)
            return sample_citation

        monkeypatch.setattr(load_portions_module.arcgis, "build_source_citation", fake_citation)
        monkeypatch.setattr(
            load_portions_module.arcgis,
            "geojson_to_multipolygon_wkt",
            lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
        )
        feature = {
            **SAMPLE_PORTION_FEATURE,
            "properties": {
                k: v for k, v in SAMPLE_PORTION_FEATURE["properties"].items()
                if k != "REGYEAR"
            },
        }
        result = _feature_to_geometry(
            feature, antelope_config, sample_metadata, SERVICE_URL, fetch_year=2026,
            slug_strategy="shapecode",
        )
        assert captured["license_year"] == 2026  # fell back to fetch_year
        assert result.license_year is None  # Geometry.license_year stays None


# ---------------------------------------------------------------------------
# _load_layer
# ---------------------------------------------------------------------------


def _patch_load_layer(
    monkeypatch: pytest.MonkeyPatch,
    sample_metadata: LayerMetadata,
    sample_citation: SourceCitation,
    features: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(
        load_portions_module.arcgis,
        "fetch_layer_metadata",
        lambda *args, **kwargs: sample_metadata,
    )
    monkeypatch.setattr(
        load_portions_module.arcgis,
        "fetch_features",
        lambda *args, **kwargs: features,
    )
    monkeypatch.setattr(
        load_portions_module.arcgis,
        "build_source_citation",
        lambda **kwargs: sample_citation,
    )
    monkeypatch.setattr(
        load_portions_module.arcgis,
        "geojson_to_multipolygon_wkt",
        lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
    )


class TestLoadLayer:
    def test_single_feature_happy_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        elk_config: PortionLayerConfig,
    ) -> None:
        _patch_load_layer(monkeypatch, sample_metadata, sample_citation, [SAMPLE_PORTION_FEATURE])
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_portions_module.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        result = _load_layer(conn, SERVICE_URL, elk_config, tmp_path, 2026)

        mock_upsert.assert_called_once()
        upserted_geoms = mock_upsert.call_args[0][1]
        assert isinstance(upserted_geoms, list)
        assert len(upserted_geoms) == 1
        assert isinstance(upserted_geoms[0], Geometry)
        assert len(result) == 1

    def test_multi_feature_happy_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        elk_config: PortionLayerConfig,
    ) -> None:
        feature_a = copy.deepcopy(SAMPLE_PORTION_FEATURE)
        feature_a["properties"]["SHAPECODE"] = "262A"
        feature_a["properties"]["DISTRICT"] = "262"

        feature_b = copy.deepcopy(SAMPLE_PORTION_FEATURE)
        feature_b["properties"]["SHAPECODE"] = "262B"
        feature_b["properties"]["DISTRICT"] = "262"

        _patch_load_layer(monkeypatch, sample_metadata, sample_citation, [feature_a, feature_b])
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_portions_module.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        result = _load_layer(conn, SERVICE_URL, elk_config, tmp_path, 2026)

        assert len(result) == 2

    def test_raises_when_both_strategies_collide(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        elk_config: PortionLayerConfig,
    ) -> None:
        # Two features with identical SHAPECODE AND identical PORTIONNAME:
        # neither strategy yields collision-free IDs, so loader must fail.
        feature_1 = copy.deepcopy(SAMPLE_PORTION_FEATURE)
        feature_1["properties"]["SHAPECODE"] = "262A"
        feature_1["properties"]["DISTRICT"] = "262"
        feature_2 = copy.deepcopy(SAMPLE_PORTION_FEATURE)
        feature_2["properties"]["SHAPECODE"] = "262A"
        feature_2["properties"]["DISTRICT"] = "262"
        # Both have PORTIONNAME="North Fork" via SAMPLE_PORTION_FEATURE.

        _patch_load_layer(monkeypatch, sample_metadata, sample_citation, [feature_1, feature_2])
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_portions_module.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError, match="under both SHAPECODE and PORTIONNAME"):
            _load_layer(conn, SERVICE_URL, elk_config, tmp_path, 2026)

        mock_upsert.assert_not_called()

    def test_falls_back_to_portionname_when_shapecode_collides(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        elk_config: PortionLayerConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Real MT FWP layer #12 condition: same DISTRICT, same SHAPECODE, but
        # distinct PORTIONNAMEs. Loader must detect the SHAPECODE collision and
        # silently retry with PORTIONNAME slugs (which are unique).
        feature_1 = copy.deepcopy(SAMPLE_PORTION_FEATURE)
        feature_1["properties"]["DISTRICT"] = "312"
        feature_1["properties"]["SHAPECODE"] = "mdPt312"
        feature_1["properties"]["PORTIONNAME"] = "Portion of HD 312 East side"
        feature_2 = copy.deepcopy(SAMPLE_PORTION_FEATURE)
        feature_2["properties"]["DISTRICT"] = "312"
        feature_2["properties"]["SHAPECODE"] = "mdPt312"
        feature_2["properties"]["PORTIONNAME"] = "Portion of HD 312 West side"

        _patch_load_layer(monkeypatch, sample_metadata, sample_citation, [feature_1, feature_2])
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_portions_module.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with caplog.at_level("INFO", logger="states.montana.load_portions"):
            result = _load_layer(conn, SERVICE_URL, elk_config, tmp_path, 2026)

        assert len(result) == 2
        ids = sorted(g.id for g in result)
        assert ids == [
            "MT-HD-elk-312-portion-portion-of-hd-312-east-side-geom",
            "MT-HD-elk-312-portion-portion-of-hd-312-west-side-geom",
        ]
        # Confirm fallback was logged (operator audit trail).
        assert any(
            "SHAPECODE collided" in r.message and "PORTIONNAME" in r.message
            for r in caplog.records
        )
        assert any(
            "slug strategy=PORTIONNAME" in r.message for r in caplog.records
        )
        mock_upsert.assert_called_once()
        assert len(mock_upsert.call_args[0][1]) == 2

    def test_passes_correct_layer_slug(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        elk_config: PortionLayerConfig,
    ) -> None:
        mock_metadata_fn = MagicMock(return_value=sample_metadata)
        monkeypatch.setattr(load_portions_module.arcgis, "fetch_layer_metadata", mock_metadata_fn)

        mock_features_fn = MagicMock(return_value=[SAMPLE_PORTION_FEATURE])
        monkeypatch.setattr(load_portions_module.arcgis, "fetch_features", mock_features_fn)

        monkeypatch.setattr(
            load_portions_module.arcgis,
            "build_source_citation",
            lambda **kwargs: sample_citation,
        )
        monkeypatch.setattr(
            load_portions_module.arcgis,
            "geojson_to_multipolygon_wkt",
            lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
        )
        monkeypatch.setattr(load_portions_module.db, "upsert_geometries", MagicMock())

        conn = MagicMock()
        _load_layer(conn, SERVICE_URL, elk_config, tmp_path, 2026)

        assert mock_metadata_fn.call_args.kwargs["layer_slug"] == "huntingDistricts"
        assert mock_features_fn.call_args.kwargs["layer_slug"] == "huntingDistricts"

    def test_raises_on_zero_features(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        elk_config: PortionLayerConfig,
    ) -> None:
        # Zero features is not an expected outcome for any V1 portion layer.
        # Loader must fail loud (ArcGISError) rather than write an empty load.
        monkeypatch.setattr(
            load_portions_module.arcgis, "fetch_layer_metadata", lambda *a, **k: sample_metadata,
        )
        monkeypatch.setattr(
            load_portions_module.arcgis, "fetch_features", lambda *a, **k: [],
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_portions_module.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError, match="returned zero features"):
            _load_layer(conn, SERVICE_URL, elk_config, tmp_path, 2026)

        # No DB write attempted on the empty-layer path.
        mock_upsert.assert_not_called()
