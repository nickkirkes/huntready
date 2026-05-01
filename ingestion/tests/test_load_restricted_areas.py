"""Unit tests for ingestion.states.montana.load_restricted_areas — pure-function, no real HTTP or DB."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import states.montana.load_restricted_areas as load_ra
from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry, SourceCitation
from states.montana.load_restricted_areas import (
    RESTRICTED_AREA_LAYERS,
    RestrictedAreaLayerConfig,
    _extract_identity_slug,
    _extract_license_year,
    _extract_verbatim_rule_combined,
    _feature_to_geometry,
    _load_layer,
    _slugify,
)

# ---------------------------------------------------------------------------
# Shared constants and fixtures
# ---------------------------------------------------------------------------

SERVICE_URL = "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer"

_PROPS_LAYER_2: dict[str, Any] = {
    "PORTIONNAME": "Marshall Mountain Section A",
    "REG": "No hunting within 200 yards of designated roads.",
    "COMMENTS": "Applies to all legal weapons.",
}

_PROPS_LAYER_15: dict[str, Any] = {
    "PORTIONNAME": "North Fork Elk Area",
    "REG": "Elk restricted area — archery only September 1–15.",
    "COMMENTS": "See regulation booklet for boundary details.",
    "REGYEAR": 2026,
    "DISTRICT": "150",
    "SHAPECODE": "nfElk150",
}

_FEATURE_LAYER_2: dict[str, Any] = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [[-110.0, 45.0], [-109.0, 45.0], [-109.0, 46.0], [-110.0, 46.0], [-110.0, 45.0]]
        ],
    },
    "properties": _PROPS_LAYER_2,
}

_FEATURE_LAYER_15: dict[str, Any] = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [[-112.0, 47.0], [-111.0, 47.0], [-111.0, 48.0], [-112.0, 48.0], [-112.0, 47.0]]
        ],
    },
    "properties": _PROPS_LAYER_15,
}


def _layer_metadata(
    name: str = "Big Game Restricted Areas",
    layer_id: int = 2,
    fields: tuple[str, ...] = ("PORTIONNAME", "REG", "COMMENTS", "OBJECTID"),
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


def _layer_config_2() -> RestrictedAreaLayerConfig:
    return next(c for c in RESTRICTED_AREA_LAYERS if c.layer_id == 2)


def _layer_config_15() -> RestrictedAreaLayerConfig:
    return next(c for c in RESTRICTED_AREA_LAYERS if c.layer_id == 15)


@pytest.fixture
def sample_metadata() -> LayerMetadata:
    return _layer_metadata()


@pytest.fixture
def sample_citation() -> SourceCitation:
    return SourceCitation(
        id="mt-fwp-arcgis-huntingDistricts-2-2026",
        agency="Montana Fish, Wildlife & Parks",
        title="Big Game Restricted Areas (Layer 2)",
        url=f"{SERVICE_URL}/2",
        publication_date="2026-01-01",
        document_type="gis_layer",
    )


@pytest.fixture
def config_layer_2() -> RestrictedAreaLayerConfig:
    return _layer_config_2()


@pytest.fixture
def config_layer_15() -> RestrictedAreaLayerConfig:
    return _layer_config_15()


# ---------------------------------------------------------------------------
# TestExtractIdentitySlug
# ---------------------------------------------------------------------------


class TestExtractIdentitySlug:
    def test_portionname_present_returns_slug(self, sample_metadata: LayerMetadata) -> None:
        result = _extract_identity_slug({"PORTIONNAME": "North Fork"}, sample_metadata)
        assert result == "north-fork"

    def test_portionname_with_spaces_and_special_chars(self, sample_metadata: LayerMetadata) -> None:
        result = _extract_identity_slug({"PORTIONNAME": "Marshall Mountain Section A"}, sample_metadata)
        assert result == "marshall-mountain-section-a"

    def test_portionname_missing_raises(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_identity_slug({}, sample_metadata)
        msg = str(exc_info.value)
        assert sample_metadata.name in msg
        assert "available=" in msg

    def test_portionname_empty_string_raises(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_identity_slug({"PORTIONNAME": ""}, sample_metadata)

    def test_portionname_whitespace_only_raises(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_identity_slug({"PORTIONNAME": "   "}, sample_metadata)

    def test_portionname_none_raises(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_identity_slug({"PORTIONNAME": None}, sample_metadata)

    def test_portionname_non_string_coerced(self, sample_metadata: LayerMetadata) -> None:
        # Non-string values should be coerced to str then slugified.
        result = _extract_identity_slug({"PORTIONNAME": 42}, sample_metadata)
        assert result == "42"


# ---------------------------------------------------------------------------
# TestExtractLicenseYear
# ---------------------------------------------------------------------------


class TestExtractLicenseYear:
    def test_integer_regyear_returns_int(self) -> None:
        assert _extract_license_year({"REGYEAR": 2024}) == 2024

    def test_string_numeric_regyear_returns_int(self) -> None:
        result = _extract_license_year({"REGYEAR": "2024"})
        assert result == 2024
        assert isinstance(result, int)

    def test_regyear_missing_returns_none(self) -> None:
        assert _extract_license_year({}) is None

    def test_regyear_none_returns_none(self) -> None:
        assert _extract_license_year({"REGYEAR": None}) is None

    def test_regyear_non_numeric_string_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _extract_license_year({"REGYEAR": "not-a-year"})


# ---------------------------------------------------------------------------
# TestSlugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_spaces_become_hyphens(self) -> None:
        assert _slugify("Hello World") == "hello-world"

    def test_mixed_alpha_numeric(self) -> None:
        assert _slugify("ABC 123") == "abc-123"

    def test_strips_leading_and_trailing_whitespace(self) -> None:
        assert _slugify("  whitespace  ") == "whitespace"

    def test_collapses_multiple_hyphens(self) -> None:
        assert _slugify("multiple--hyphens") == "multiple-hyphens"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("   ")

    def test_special_chars_only_raises(self) -> None:
        with pytest.raises(ArcGISError):
            _slugify("!@#")


# ---------------------------------------------------------------------------
# TestExtractVerbatimRuleCombined
# ---------------------------------------------------------------------------


_SEPARATOR = "\n\n--- COMMENTS ---\n\n"


class TestExtractVerbatimRuleCombined:
    def test_both_populated_and_differ_combined(self) -> None:
        reg = "No hunting within 200 yards."
        comments = "Applies to all legal weapons."
        result = _extract_verbatim_rule_combined({"REG": reg, "COMMENTS": comments})
        assert result == f"{reg}{_SEPARATOR}{comments}"

    def test_both_populated_identical_returns_single(self) -> None:
        text = "Same rule text."
        result = _extract_verbatim_rule_combined({"REG": text, "COMMENTS": text})
        assert result == text

    def test_both_populated_identical_after_strip_returns_original_reg(self) -> None:
        # REG has trailing whitespace; after stripping they are identical.
        # The un-stripped REG value (with trailing whitespace) should be stored.
        reg = "Same text.   "
        comments = "Same text."
        result = _extract_verbatim_rule_combined({"REG": reg, "COMMENTS": comments})
        assert result == reg

    def test_both_populated_differ_interior_combined(self) -> None:
        reg = "Archery only."
        comments = "See map for boundary."
        result = _extract_verbatim_rule_combined({"REG": reg, "COMMENTS": comments})
        assert _SEPARATOR in result
        assert result == f"{reg}{_SEPARATOR}{comments}"

    def test_reg_only_comments_missing_returns_reg(self) -> None:
        reg = "No hunting within 200 yards."
        result = _extract_verbatim_rule_combined({"REG": reg})
        assert result == reg

    def test_reg_only_comments_empty_string_returns_reg(self) -> None:
        reg = "Archery only."
        result = _extract_verbatim_rule_combined({"REG": reg, "COMMENTS": ""})
        assert result == reg

    def test_reg_only_comments_whitespace_returns_reg(self) -> None:
        reg = "Archery only."
        result = _extract_verbatim_rule_combined({"REG": reg, "COMMENTS": "   "})
        assert result == reg

    def test_comments_only_reg_missing_returns_comments(self) -> None:
        comments = "See regulation booklet."
        result = _extract_verbatim_rule_combined({"COMMENTS": comments})
        assert result == comments

    def test_comments_only_reg_none_returns_comments(self) -> None:
        comments = "See regulation booklet."
        result = _extract_verbatim_rule_combined({"REG": None, "COMMENTS": comments})
        assert result == comments

    def test_both_missing_returns_none(self) -> None:
        assert _extract_verbatim_rule_combined({}) is None

    def test_both_empty_strings_returns_none(self) -> None:
        assert _extract_verbatim_rule_combined({"REG": "", "COMMENTS": ""}) is None

    def test_both_whitespace_only_returns_none(self) -> None:
        assert _extract_verbatim_rule_combined({"REG": "   ", "COMMENTS": "  "}) is None

    def test_separator_exact_literal(self) -> None:
        reg = "Rule A."
        comments = "Comment B."
        result = _extract_verbatim_rule_combined({"REG": reg, "COMMENTS": comments})
        assert result is not None
        assert _SEPARATOR in result
        assert result == f"{reg}\n\n--- COMMENTS ---\n\n{comments}"

    def test_non_string_reg_int_coerced(self) -> None:
        result = _extract_verbatim_rule_combined({"REG": 42, "COMMENTS": "some comment"})
        assert result is not None
        assert "42" in result


# ---------------------------------------------------------------------------
# _feature_to_geometry helpers
# ---------------------------------------------------------------------------


def _patch_arcgis(monkeypatch: pytest.MonkeyPatch, citation: SourceCitation) -> None:
    monkeypatch.setattr(
        load_ra.arcgis,
        "geojson_to_multipolygon_wkt",
        lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
    )
    monkeypatch.setattr(
        load_ra.arcgis,
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
        load_ra.arcgis,
        "fetch_layer_metadata",
        lambda *args, **kwargs: metadata,
    )
    monkeypatch.setattr(
        load_ra.arcgis,
        "fetch_features",
        lambda *args, **kwargs: features,
    )
    monkeypatch.setattr(
        load_ra.arcgis,
        "build_source_citation",
        lambda **kwargs: citation,
    )
    monkeypatch.setattr(
        load_ra.arcgis,
        "geojson_to_multipolygon_wkt",
        lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
    )


# ---------------------------------------------------------------------------
# TestFeatureToGeometry
# ---------------------------------------------------------------------------


class TestFeatureToGeometry:
    def test_happy_path_both_reg_and_comments_differ(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        result = _feature_to_geometry(
            _FEATURE_LAYER_2, config_layer_2, sample_metadata, SERVICE_URL, fetch_year=2026
        )
        assert isinstance(result, Geometry)
        slug = "marshall-mountain-section-a"
        assert result.id == f"{config_layer_2.id_prefix}-{slug}-geom"
        assert slug in result.name
        assert config_layer_2.display_name in result.name
        assert result.kind == "restricted_area"
        assert result.verbatim_rule is not None
        assert _SEPARATOR in result.verbatim_rule
        assert result.state == "US-MT"
        assert result.source.document_type == "gis_layer"

    def test_layer_2_happy_path_no_regyear_license_year_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        _patch_arcgis(monkeypatch, sample_citation)
        feature = copy.deepcopy(_FEATURE_LAYER_2)
        feature["properties"].pop("REGYEAR", None)
        result = _feature_to_geometry(
            feature, config_layer_2, sample_metadata, SERVICE_URL, fetch_year=2026
        )
        assert result.license_year is None

    def test_layer_2_citation_falls_back_to_fetch_year_when_no_regyear(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_citation(**kwargs: Any) -> SourceCitation:
            captured.update(kwargs)
            return sample_citation

        monkeypatch.setattr(load_ra.arcgis, "build_source_citation", fake_citation)
        monkeypatch.setattr(
            load_ra.arcgis,
            "geojson_to_multipolygon_wkt",
            lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
        )
        feature = copy.deepcopy(_FEATURE_LAYER_2)
        feature["properties"].pop("REGYEAR", None)
        _feature_to_geometry(
            feature, config_layer_2, sample_metadata, SERVICE_URL, fetch_year=2099
        )
        assert captured["license_year"] == 2099

    def test_layer_15_happy_path_regyear_present(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_citation: SourceCitation,
        config_layer_15: RestrictedAreaLayerConfig,
    ) -> None:
        metadata_15 = _layer_metadata(
            name="Elk Restricted Areas",
            layer_id=15,
            fields=("PORTIONNAME", "REG", "COMMENTS", "REGYEAR", "OBJECTID"),
        )
        captured: dict[str, Any] = {}

        def fake_citation(**kwargs: Any) -> SourceCitation:
            captured.update(kwargs)
            return sample_citation

        monkeypatch.setattr(load_ra.arcgis, "build_source_citation", fake_citation)
        monkeypatch.setattr(
            load_ra.arcgis,
            "geojson_to_multipolygon_wkt",
            lambda f: "MULTIPOLYGON (((-110 45, -109 45, -109 46, -110 46, -110 45)))",
        )
        result = _feature_to_geometry(
            _FEATURE_LAYER_15, config_layer_15, metadata_15, SERVICE_URL, fetch_year=2099
        )
        # license_year on Geometry should come from REGYEAR, not fetch_year
        assert result.license_year == 2026
        # citation also should use REGYEAR
        assert captured["license_year"] == 2026


# ---------------------------------------------------------------------------
# TestLoadLayer
# ---------------------------------------------------------------------------


class TestLoadLayer:
    def test_layer_2_happy_path_three_features(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        # 3 features, none CWD → all 3 upserted with kind='restricted_area'
        feat_a = copy.deepcopy(_FEATURE_LAYER_2)
        feat_a["properties"]["PORTIONNAME"] = "Area Alpha"
        feat_b = copy.deepcopy(_FEATURE_LAYER_2)
        feat_b["properties"]["PORTIONNAME"] = "Area Beta"
        feat_c = copy.deepcopy(_FEATURE_LAYER_2)
        feat_c["properties"]["PORTIONNAME"] = "Area Gamma"

        _patch_load_layer(
            monkeypatch, features=[feat_a, feat_b, feat_c],
            metadata=sample_metadata, citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_ra.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        result = _load_layer(conn, SERVICE_URL, config_layer_2, tmp_path, 2026)

        mock_upsert.assert_called_once()
        upserted = mock_upsert.call_args[0][1]
        assert len(upserted) == 3
        assert len(result) == 3
        assert all(g.kind == "restricted_area" for g in result)

    def test_layer_2_cwd_filter_removes_cwd_feature(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        # 4 features, 1 has COMMENTS='Includes CWD zone' → 3 upserted, 1 filtered out.
        feat_a = copy.deepcopy(_FEATURE_LAYER_2)
        feat_a["properties"]["PORTIONNAME"] = "Clean Area A"
        feat_b = copy.deepcopy(_FEATURE_LAYER_2)
        feat_b["properties"]["PORTIONNAME"] = "Clean Area B"
        feat_c = copy.deepcopy(_FEATURE_LAYER_2)
        feat_c["properties"]["PORTIONNAME"] = "Clean Area C"
        feat_cwd = copy.deepcopy(_FEATURE_LAYER_2)
        feat_cwd["properties"]["PORTIONNAME"] = "Should Be Filtered"
        feat_cwd["properties"]["COMMENTS"] = "Includes CWD zone"

        _patch_load_layer(
            monkeypatch, features=[feat_a, feat_b, feat_c, feat_cwd],
            metadata=sample_metadata, citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_ra.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        result = _load_layer(conn, SERVICE_URL, config_layer_2, tmp_path, 2026)

        assert len(result) == 3
        ids = [g.id for g in result]
        # The CWD-tagged feature's slug should not appear
        assert not any("should-be-filtered" in gid for gid in ids)

    def test_layer_2_zero_features_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        _patch_load_layer(
            monkeypatch, features=[], metadata=sample_metadata, citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_ra.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError, match="zero features"):
            _load_layer(conn, SERVICE_URL, config_layer_2, tmp_path, 2026)

        mock_upsert.assert_not_called()

    def test_layer_2_all_features_cwd_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        # Both features match the CWD discriminator → should raise ArcGISError
        feat_1 = copy.deepcopy(_FEATURE_LAYER_2)
        feat_1["properties"]["PORTIONNAME"] = "CWD Zone One"
        feat_1["properties"]["COMMENTS"] = "CWD management area"
        feat_2 = copy.deepcopy(_FEATURE_LAYER_2)
        feat_2["properties"]["PORTIONNAME"] = "CWD Zone Two"
        feat_2["properties"]["COMMENTS"] = "Also a CWD zone"

        _patch_load_layer(
            monkeypatch, features=[feat_1, feat_2],
            metadata=sample_metadata, citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_ra.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError, match="ALL matched the CWD discriminator"):
            _load_layer(conn, SERVICE_URL, config_layer_2, tmp_path, 2026)

        mock_upsert.assert_not_called()

    def test_layer_15_no_cwd_filter_applied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_citation: SourceCitation,
        config_layer_15: RestrictedAreaLayerConfig,
    ) -> None:
        # Layer #15 has apply_cwd_filter=False; a feature with "CWD" in COMMENTS
        # should still be upserted (discriminator not applied).
        metadata_15 = _layer_metadata(
            name="Elk Restricted Areas",
            layer_id=15,
            fields=("PORTIONNAME", "REG", "COMMENTS", "OBJECTID"),
        )
        feat = copy.deepcopy(_FEATURE_LAYER_15)
        feat["properties"]["COMMENTS"] = "CWD management note"
        feat["properties"]["PORTIONNAME"] = "Elk CWD Area"

        _patch_load_layer(
            monkeypatch, features=[feat],
            metadata=metadata_15, citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_ra.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        result = _load_layer(conn, SERVICE_URL, config_layer_15, tmp_path, 2026)

        # Feature should be upserted despite having CWD in COMMENTS
        assert len(result) == 1
        mock_upsert.assert_called_once()

    def test_duplicate_ids_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        # Two features share the same PORTIONNAME → duplicate IDs → ArcGISError
        feat_1 = copy.deepcopy(_FEATURE_LAYER_2)
        feat_1["properties"]["PORTIONNAME"] = "Duplicate Area"
        feat_2 = copy.deepcopy(_FEATURE_LAYER_2)
        feat_2["properties"]["PORTIONNAME"] = "Duplicate Area"

        _patch_load_layer(
            monkeypatch, features=[feat_1, feat_2],
            metadata=sample_metadata, citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_ra.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError) as exc_info:
            _load_layer(conn, SERVICE_URL, config_layer_2, tmp_path, 2026)

        # Error should mention the duplicate ID
        assert "duplicate-area" in str(exc_info.value)
        mock_upsert.assert_not_called()

    def test_upsert_called_exactly_once_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        feat = copy.deepcopy(_FEATURE_LAYER_2)
        feat["properties"]["PORTIONNAME"] = "Single Area"

        _patch_load_layer(
            monkeypatch, features=[feat],
            metadata=sample_metadata, citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_ra.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        _load_layer(conn, SERVICE_URL, config_layer_2, tmp_path, 2026)

        mock_upsert.assert_called_once()

    def test_slugify_cross_spelling_collision_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        config_layer_2: RestrictedAreaLayerConfig,
    ) -> None:
        # Two distinct PORTIONNAME spellings that slugify to the same value
        # ("Mt Foo" and "Mt-Foo" both → "mt-foo") must be caught by the
        # duplicate-id guard before any DB write.
        feat_a = copy.deepcopy(_FEATURE_LAYER_2)
        feat_a["properties"]["PORTIONNAME"] = "Mt Foo"
        feat_b = copy.deepcopy(_FEATURE_LAYER_2)
        feat_b["properties"]["PORTIONNAME"] = "Mt-Foo"

        _patch_load_layer(
            monkeypatch, features=[feat_a, feat_b],
            metadata=sample_metadata, citation=sample_citation,
        )
        mock_upsert = MagicMock()
        monkeypatch.setattr(load_ra.db, "upsert_geometries", mock_upsert)

        conn = MagicMock()
        with pytest.raises(ArcGISError) as exc_info:
            _load_layer(conn, SERVICE_URL, config_layer_2, tmp_path, 2026)

        assert "mt-foo" in str(exc_info.value)
        mock_upsert.assert_not_called()


class TestMainCommitAtomicity:
    """Verify the single atomic-commit boundary across both layers.

    Locks in the contract that `conn.commit()` happens once after BOTH
    layers succeed. A failure on layer #15 must NOT commit layer #2's
    writes — they belong to the same transaction.
    """

    def test_commit_not_called_when_second_layer_raises(
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

        monkeypatch.setattr(load_ra.arcgis, "_build_session", lambda: mock_session)
        monkeypatch.setattr(load_ra.db, "connect", lambda: connect_cm)

        call_count = {"n": 0}

        def fake_load_layer(*args: Any, **kwargs: Any) -> list[Any]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return []
            raise ArcGISError("simulated layer-#15 failure")

        monkeypatch.setattr(load_ra, "_load_layer", fake_load_layer)

        with pytest.raises(ArcGISError, match="simulated layer-#15 failure"):
            load_ra.main([])

        # Critical assertion: commit was NOT called because layer-#15 raised.
        # Layer #2's writes should be rolled back when the connection closes.
        mock_conn.commit.assert_not_called()
        # Both layers were attempted (so the test would fail if main()
        # short-circuited before reaching layer #15).
        assert call_count["n"] == 2

    def test_commit_called_once_when_both_layers_succeed(
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

        monkeypatch.setattr(load_ra.arcgis, "_build_session", lambda: mock_session)
        monkeypatch.setattr(load_ra.db, "connect", lambda: connect_cm)
        monkeypatch.setattr(load_ra, "_load_layer", lambda *a, **kw: [])

        result = load_ra.main([])

        assert result == 0
        mock_conn.commit.assert_called_once()
