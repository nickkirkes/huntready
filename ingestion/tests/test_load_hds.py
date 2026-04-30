"""Unit tests for ingestion.states.montana.load_hds — pure-function, no real HTTP or DB."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ingestion.lib.arcgis import ArcGISError, LayerMetadata
from ingestion.lib.schema import Geometry, SourceCitation
from states.montana.load_hds import (
    HD_LAYERS,
    HDLayerConfig,
    _extract_district,
    _extract_license_year,
    _extract_verbatim_rule,
    _feature_to_geometry,
    _load_layer,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SERVICE_URL = "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer"

SAMPLE_POLYGON_FEATURE: dict[str, Any] = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [[-110.0, 45.0], [-109.0, 45.0], [-109.0, 46.0], [-110.0, 46.0], [-110.0, 45.0]]
        ],
    },
    "properties": {
        "DISTRICT": "262",
        "REG": "Hunting permitted only with archery equipment.",
        "REGYEAR": 2026,
    },
}


@pytest.fixture
def sample_metadata() -> LayerMetadata:
    return LayerMetadata(
        name="Deer Elk Lion Hunting Districts",
        object_id_field="OBJECTID",
        max_record_count=2000,
        out_fields=("OBJECTID", "DISTRICT", "REG", "REGYEAR"),
        geometry_type="esriGeometryPolygon",
        last_edit_date_ms=None,
        raw={},
        spatial_reference_wkid=4326,
    )


@pytest.fixture
def sample_citation() -> SourceCitation:
    return SourceCitation(
        id="mt-fwp-arcgis-huntingDistricts-11-2026",
        agency="Montana Fish, Wildlife & Parks",
        title="Deer Elk Lion Hunting Districts (Layer 11)",
        url=f"{SERVICE_URL}/11",
        publication_date="2026-01-01",
        document_type="gis_layer",
    )


@pytest.fixture
def deer_elk_lion_config() -> HDLayerConfig:
    # layer_id=11 from HD_LAYERS tuple
    return next(c for c in HD_LAYERS if c.species_slug == "deer-elk-lion")


@pytest.fixture
def antelope_config() -> HDLayerConfig:
    return next(c for c in HD_LAYERS if c.species_slug == "antelope")


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
        assert isinstance(result, str)

    def test_raises_when_district_absent(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_district({"OTHER_FIELD": "x"}, sample_metadata)
        assert "available=" in str(exc_info.value)
        # The message should include field names from out_fields
        assert "DISTRICT" in str(exc_info.value) or "available=" in str(exc_info.value)

    def test_raises_available_field_list_in_message(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError) as exc_info:
            _extract_district({}, sample_metadata)
        msg = str(exc_info.value)
        assert "available=" in msg
        # out_fields are in the message
        assert "OBJECTID" in msg or "REGYEAR" in msg

    def test_raises_when_district_is_none(self, sample_metadata: LayerMetadata) -> None:
        with pytest.raises(ArcGISError):
            _extract_district({"DISTRICT": None}, sample_metadata)


# ---------------------------------------------------------------------------
# _extract_verbatim_rule
# ---------------------------------------------------------------------------


class TestExtractVerbatimRule:
    def test_returns_string_when_reg_non_empty(self) -> None:
        result = _extract_verbatim_rule({"REG": "Archery only."})
        assert result == "Archery only."

    def test_returns_none_for_missing_key(self) -> None:
        assert _extract_verbatim_rule({}) is None

    def test_returns_none_for_reg_none(self) -> None:
        assert _extract_verbatim_rule({"REG": None}) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _extract_verbatim_rule({"REG": ""}) is None

    def test_returns_none_for_whitespace_only(self) -> None:
        assert _extract_verbatim_rule({"REG": "   "}) is None

    def test_returns_none_for_tab_newline(self) -> None:
        assert _extract_verbatim_rule({"REG": "\t\n"}) is None

    def test_returns_original_unstripped_value(self) -> None:
        # The original value (with surrounding whitespace) is preserved when
        # there IS non-whitespace content — not stripped
        result = _extract_verbatim_rule({"REG": "  text  "})
        assert result == "  text  "


# ---------------------------------------------------------------------------
# _extract_license_year
# ---------------------------------------------------------------------------


class TestExtractLicenseYear:
    def test_returns_int_for_int_regyear(self) -> None:
        assert _extract_license_year({"REGYEAR": 2026}) == 2026

    def test_returns_int_for_string_regyear(self) -> None:
        result = _extract_license_year({"REGYEAR": "2026"})
        assert result == 2026
        assert isinstance(result, int)

    def test_returns_none_for_missing_key(self) -> None:
        assert _extract_license_year({}) is None

    def test_returns_none_for_regyear_none(self) -> None:
        assert _extract_license_year({"REGYEAR": None}) is None


# ---------------------------------------------------------------------------
# _feature_to_geometry
# ---------------------------------------------------------------------------


SERVICE_URL_FOR_FEATURE = "https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer"


class TestFeatureToGeometry:
    def test_basic_geometry_fields(
        self,
        deer_elk_lion_config: HDLayerConfig,
        sample_metadata: LayerMetadata,
    ) -> None:
        geom = _feature_to_geometry(
            SAMPLE_POLYGON_FEATURE,
            deer_elk_lion_config,
            sample_metadata,
            SERVICE_URL_FOR_FEATURE,
            2026,
        )
        assert isinstance(geom, Geometry)
        assert geom.id == "MT-HD-deer-elk-lion-262-geom"
        assert geom.name == "Deer/Elk/Lion HD 262"
        assert geom.kind == "hunting_district"
        assert geom.state == "US-MT"
        assert geom.license_year == 2026
        assert geom.verbatim_rule == "Hunting permitted only with archery equipment."
        assert geom.source.document_type == "gis_layer"
        # citation.publication_date encodes citation.license_year per ADR-014
        assert geom.source.publication_date == "2026-01-01"
        assert geom.source.agency == "Montana Fish, Wildlife & Parks"

    def test_geom_is_valid_multipolygon_wkt(
        self,
        deer_elk_lion_config: HDLayerConfig,
        sample_metadata: LayerMetadata,
    ) -> None:
        geom = _feature_to_geometry(
            SAMPLE_POLYGON_FEATURE,
            deer_elk_lion_config,
            sample_metadata,
            SERVICE_URL_FOR_FEATURE,
            2026,
        )
        assert geom.geom.startswith("MULTIPOLYGON")

    def test_species_id_collision_antelope(
        self,
        antelope_config: HDLayerConfig,
        sample_metadata: LayerMetadata,
    ) -> None:
        feature = {
            **SAMPLE_POLYGON_FEATURE,
            "properties": {**SAMPLE_POLYGON_FEATURE["properties"], "DISTRICT": "700"},
        }
        geom = _feature_to_geometry(
            feature, antelope_config, sample_metadata, SERVICE_URL_FOR_FEATURE, 2026,
        )
        assert geom.id == "MT-HD-antelope-700-geom"

    def test_species_id_collision_deer_elk_lion(
        self,
        deer_elk_lion_config: HDLayerConfig,
        sample_metadata: LayerMetadata,
    ) -> None:
        feature = {
            **SAMPLE_POLYGON_FEATURE,
            "properties": {**SAMPLE_POLYGON_FEATURE["properties"], "DISTRICT": "700"},
        }
        geom = _feature_to_geometry(
            feature, deer_elk_lion_config, sample_metadata, SERVICE_URL_FOR_FEATURE, 2026,
        )
        assert geom.id == "MT-HD-deer-elk-lion-700-geom"

    def test_same_district_different_species_produce_different_ids(
        self,
        antelope_config: HDLayerConfig,
        deer_elk_lion_config: HDLayerConfig,
        sample_metadata: LayerMetadata,
    ) -> None:
        feature = {
            **SAMPLE_POLYGON_FEATURE,
            "properties": {**SAMPLE_POLYGON_FEATURE["properties"], "DISTRICT": "700"},
        }
        antelope_geom = _feature_to_geometry(
            feature, antelope_config, sample_metadata, SERVICE_URL_FOR_FEATURE, 2026,
        )
        deer_geom = _feature_to_geometry(
            feature, deer_elk_lion_config, sample_metadata, SERVICE_URL_FOR_FEATURE, 2026,
        )
        assert antelope_geom.id != deer_geom.id
        assert antelope_geom.id == "MT-HD-antelope-700-geom"
        assert deer_geom.id == "MT-HD-deer-elk-lion-700-geom"

    def test_citation_uses_regyear_when_present(
        self,
        deer_elk_lion_config: HDLayerConfig,
        sample_metadata: LayerMetadata,
    ) -> None:
        # Per epic E02:175-188, citation.license_year prefers per-feature REGYEAR
        # so a 2025-cycle feature loaded in a 2026 fetch run is correctly attributed.
        feature = {
            **SAMPLE_POLYGON_FEATURE,
            "properties": {**SAMPLE_POLYGON_FEATURE["properties"], "REGYEAR": 2025},
        }
        geom = _feature_to_geometry(
            feature, deer_elk_lion_config, sample_metadata, SERVICE_URL_FOR_FEATURE, 2026,
        )
        assert geom.license_year == 2025
        assert geom.source.publication_date == "2025-01-01"

    def test_citation_falls_back_to_fetch_year_when_regyear_absent(
        self,
        antelope_config: HDLayerConfig,
        sample_metadata: LayerMetadata,
    ) -> None:
        # Per epic E02:175-188, citation.license_year falls back to fetch_year
        # only when source data carries no REGYEAR. Geometry.license_year stays NULL.
        feature = {
            **SAMPLE_POLYGON_FEATURE,
            "properties": {
                k: v for k, v in SAMPLE_POLYGON_FEATURE["properties"].items()
                if k != "REGYEAR"
            },
        }
        geom = _feature_to_geometry(
            feature, antelope_config, sample_metadata, SERVICE_URL_FOR_FEATURE, 2026,
        )
        assert geom.license_year is None
        assert geom.source.publication_date == "2026-01-01"


# ---------------------------------------------------------------------------
# _load_layer
# ---------------------------------------------------------------------------


class TestLoadLayer:
    def test_calls_arcgis_helpers_and_db_with_correct_args(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: LayerMetadata,
        sample_citation: SourceCitation,
        deer_elk_lion_config: HDLayerConfig,
    ) -> None:
        canned_features = [SAMPLE_POLYGON_FEATURE]
        conn = MagicMock()
        fetch_year = 2026
        fixture_dir = tmp_path

        fetch_metadata_calls: list[tuple[Any, ...]] = []
        fetch_features_calls: list[tuple[Any, ...]] = []
        build_citation_calls: list[dict[str, Any]] = []
        upsert_calls: list[tuple[Any, ...]] = []

        def fake_fetch_layer_metadata(
            service_url: str,
            layer_id: int,
            fixture_dir_arg: Path,
            *,
            layer_slug: str,
            session: Any = None,
        ) -> LayerMetadata:
            fetch_metadata_calls.append((service_url, layer_id, fixture_dir_arg, layer_slug))
            return sample_metadata

        def fake_fetch_features(
            service_url: str,
            layer_id: int,
            metadata: LayerMetadata,
            fixture_dir_arg: Path,
            *,
            layer_slug: str,
            session: Any = None,
        ) -> list[dict[str, Any]]:
            fetch_features_calls.append((service_url, layer_id, metadata, fixture_dir_arg, layer_slug))
            return canned_features

        def fake_build_source_citation(
            *,
            service_url: str,
            layer_id: int,
            metadata: LayerMetadata,
            license_year: int,
            state_slug: str,
            agency: str,
        ) -> SourceCitation:
            build_citation_calls.append({
                "service_url": service_url,
                "layer_id": layer_id,
                "metadata": metadata,
                "license_year": license_year,
                "state_slug": state_slug,
                "agency": agency,
            })
            return sample_citation

        def fake_upsert_geometries(
            conn_arg: Any, geoms: list[Geometry]
        ) -> None:
            upsert_calls.append((conn_arg, geoms))

        monkeypatch.setattr(
            "states.montana.load_hds.arcgis.fetch_layer_metadata",
            fake_fetch_layer_metadata,
        )
        monkeypatch.setattr(
            "states.montana.load_hds.arcgis.fetch_features",
            fake_fetch_features,
        )
        monkeypatch.setattr(
            "states.montana.load_hds.arcgis.build_source_citation",
            fake_build_source_citation,
        )
        monkeypatch.setattr(
            "states.montana.load_hds.db.upsert_geometries",
            fake_upsert_geometries,
        )

        result = _load_layer(conn, SERVICE_URL, deer_elk_lion_config, fixture_dir, fetch_year)

        # --- fetch_layer_metadata called correctly ---
        assert len(fetch_metadata_calls) == 1
        su, lid, fd, slug = fetch_metadata_calls[0]
        assert su == SERVICE_URL
        assert lid == deer_elk_lion_config.layer_id
        assert fd == fixture_dir
        assert slug == "huntingDistricts"

        # --- fetch_features called correctly ---
        assert len(fetch_features_calls) == 1
        su2, lid2, meta2, fd2, slug2 = fetch_features_calls[0]
        assert su2 == SERVICE_URL
        assert lid2 == deer_elk_lion_config.layer_id
        assert meta2 is sample_metadata
        assert fd2 == fixture_dir
        assert slug2 == "huntingDistricts"

        # --- build_source_citation called per-feature with correct args ---
        # Per the per-feature citation contract (epic E02:175-188), the helper is
        # called once per ingested feature, not once per layer. The sample feature
        # has REGYEAR=2026 which equals fetch_year, so license_year=2026 either way.
        assert len(build_citation_calls) == len(canned_features)
        call_kwargs = build_citation_calls[0]
        assert call_kwargs["service_url"] == SERVICE_URL
        assert call_kwargs["layer_id"] == deer_elk_lion_config.layer_id
        assert call_kwargs["metadata"] is sample_metadata
        assert call_kwargs["license_year"] == 2026
        assert call_kwargs["state_slug"] == "mt-fwp"
        assert call_kwargs["agency"] == "Montana Fish, Wildlife & Parks"

        # --- upsert_geometries called with conn and the built geometries ---
        assert len(upsert_calls) == 1
        upsert_conn, upsert_geoms = upsert_calls[0]
        assert upsert_conn is conn
        assert len(upsert_geoms) == 1
        assert isinstance(upsert_geoms[0], Geometry)
        assert upsert_geoms[0].id == "MT-HD-deer-elk-lion-262-geom"

        # --- return value matches what was built ---
        assert result == upsert_geoms
        assert len(result) == 1
        assert result[0].id == "MT-HD-deer-elk-lion-262-geom"
