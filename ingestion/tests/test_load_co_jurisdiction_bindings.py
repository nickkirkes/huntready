"""Unit tests for ``ingestion/states/colorado/load_jurisdiction_bindings.py``.

MagicMock-based — no live DB, no network.

Coverage:
- TestAstGuards             — drift_guard not imported; no cross-state imports
- TestIdFormatContract      — _JURISDICTION_BINDING_ID_FORMAT imported, not redefined
- TestRoleGateLock          — _VALID_ROLE_FOR_E03_CO stays narrow (AC #1106)
- TestIsBindingEligibleCo   — eligibility filter pure-function cases
- TestDeriveParentGeomId    — _derive_parent_geometry_id_co patterns + guards
- TestLoadOverlayFixture     — valid list, dict-with-relationships, error cases
- TestFetchGeometrySources  — mocked cursor, missing id, malformed jsonb
- TestFetchZoneWkts         — mocked cursor, missing id, extensions.ST_AsText
- TestBuildStatewideBindings — returns [] for empty + emits rows for non-empty
- TestBuildOverlayBindings  — self-rows -> primary_unit; restricted_area skipped;
                              error cases
- TestBuildNoHuntZoneBindings — AFA -> other_overlay; NPS -> no_hunt_zone; error cases
- TestAfaLock               — test_afa_bound_other_overlay_not_no_hunt_zone (AC #1105)
- TestCountGuard            — band inside/below/above
- TestCrossStateFilterRegression — SQL contains state = %s (AC #1109)
- TestMainStatewideGuard    — CO-STATEWIDE-* raises; zero statewide passes
- TestMainCrossBuilderDedupGuard — cross-builder duplicate id raises
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import states.colorado.load_jurisdiction_bindings as mod
from ingestion.lib.schema import (
    JurisdictionBinding,
    RegulationRecord,
    RegulationReporting,
    SourceCitation,
)
from states.colorado.build_overlay_fixture import EXPECTED_CO_RA_ORPHAN_IDS
from states.colorado.load_jurisdiction_bindings import (
    _AFA_GEOM_ID,
    _BINDING_COUNT_GUARD_BAND,
    _CO_BEAR_SPECIES_GROUP,
    _CO_STATEWIDE_GEOM_ID,
    _VALID_ROLE_FOR_E03_CO,
    _assert_binding_count_within_guard,
    _assert_regulation_reporting_structural_invariant,
    _build_no_hunt_zone_bindings_co,
    _build_overlay_bindings_co,
    _build_regulation_reporting_links,
    _build_statewide_bindings_co,
    _derive_parent_geometry_id_co,
    _fetch_geometry_sources,
    _fetch_zone_wkts,
    _load_overlay_fixture,
    _query_all_colorado_regulation_records,
    _query_co_reporting_obligations,
    is_binding_eligible_co,
)
from states.colorado.load_regulation_records import (
    _JURISDICTION_BINDING_ID_FORMAT as _FORMAT_FROM_REG_RECORDS,
)

# ---------------------------------------------------------------------------
# Module path (used by AST guard tests — must be defined before test classes)
# ---------------------------------------------------------------------------

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "states" / "colorado" / "load_jurisdiction_bindings.py"
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

_MESA_VERDE_GEOM_ID = "CO-restricted-mesa-verde-national-park-geom"
_RMNP_GEOM_ID = "CO-restricted-rocky-mountain-national-park-geom"

# All 9 non-AFA zone ids (NPS/NM — genuine no_hunt_zone)
_NPS_ZONE_IDS: frozenset[str] = EXPECTED_CO_RA_ORPHAN_IDS - {_AFA_GEOM_ID}


def _make_source_citation(
    citation_id: str = "co-cpw-big-game-2026-brochure",
    agency: str = "Colorado Parks and Wildlife",
    title: str = "2026 Colorado Big Game Brochure",
    url: str = "https://spl.cde.state.co.us/artemis/nrserials/nr1431internet/nr14312026internet.pdf",
    publication_date: str = "2026-03-04",
    document_type: str = "annual_regulations",
) -> SourceCitation:
    return SourceCitation(
        id=citation_id,
        agency=agency,
        title=title,
        url=url,
        publication_date=publication_date,
        document_type=document_type,  # type: ignore[arg-type]
    )


def _make_gis_source(geom_id: str = "CO-STATEWIDE-geom") -> SourceCitation:
    return SourceCitation(
        id=f"co-source-{geom_id}",
        agency="Test Agency",
        title="Test GIS Layer",
        url="https://example.com/layer",
        publication_date="2026-01-01",
        document_type="gis_layer",
    )


def _make_reg_record(
    jurisdiction_code: str = "CO-GMU-1",
    species_group: str = "mule_deer",
    state: str = "US-CO",
    license_year: int = 2026,
    confidence: str = "high",
) -> RegulationRecord:
    return RegulationRecord(
        state=state,
        jurisdiction_code=jurisdiction_code,
        species_group=species_group,
        license_year=license_year,
        schema_version=2,
        source=_make_source_citation(),
        confidence=confidence,  # type: ignore[arg-type]
        additional_rules=[],
    )


def _make_overlay_row(
    parent_gid: str = "CO-GMU-1-geom",
    child_gid: str = "CO-GMU-1-geom",
    role_for_e03: str = "primary_unit",
    parent_kind: str = "gmu",
    child_kind: str = "gmu",
    relationship: str = "covers",
) -> dict[str, str]:
    return {
        "parent_geometry_id": parent_gid,
        "child_geometry_id": child_gid,
        "parent_kind": parent_kind,
        "child_kind": child_kind,
        "relationship": relationship,
        "role_for_e03": role_for_e03,
    }


def _make_mock_cursor(rows: list[Any]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = rows
    return cur


def _make_mock_conn(rows: list[Any]) -> MagicMock:
    conn = MagicMock()
    cur = _make_mock_cursor(rows)
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


# ---------------------------------------------------------------------------
# TestAstGuards
# ---------------------------------------------------------------------------


class TestAstGuards:
    def _parse_module(self) -> ast.Module:
        return ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))

    def test_drift_guard_not_imported(self) -> None:
        """AC #1114: drift_guard must NOT appear in any import node."""
        tree = self._parse_module()
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "drift_guard" in module:
                    violations.append(
                        f"line {node.lineno}: import from {module!r}"
                    )
                for alias in node.names:
                    if "drift_guard" in alias.name:
                        violations.append(
                            f"line {node.lineno}: name {alias.name!r} imported"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "drift_guard" in alias.name:
                        violations.append(
                            f"line {node.lineno}: import {alias.name!r}"
                        )
        assert not violations, (
            "load_jurisdiction_bindings.py must NOT import drift_guard "
            "(ADR-020 carve-out):\n" + "\n".join(f"  - {v}" for v in violations)
        )

    def test_no_cross_state_import(self) -> None:
        """No imports from states.montana or other non-colorado state adapters."""
        tree = self._parse_module()
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "states.montana" in module:
                    violations.append(
                        f"line {node.lineno}: cross-state import from {module!r}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "states.montana" in alias.name:
                        violations.append(
                            f"line {node.lineno}: cross-state import {alias.name!r}"
                        )
        assert not violations, (
            "load_jurisdiction_bindings.py must not import from states.montana:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_only_colorado_state_imports_permitted(self) -> None:
        """Only ingestion.lib.* and states.colorado.* imports are permitted."""
        tree = self._parse_module()
        violations: list[str] = []
        _PERMITTED: frozenset[str] = frozenset({
            "states.colorado.load_regulation_records",
            "states.colorado.build_overlay_fixture",
        })
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "states." in module and module not in _PERMITTED:
                    violations.append(
                        f"line {node.lineno}: unexpected states.* import from {module!r}"
                    )
        assert not violations, (
            "Unexpected state adapter imports found:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# TestIdFormatContract
# ---------------------------------------------------------------------------


class TestIdFormatContract:
    def test_id_format_imported_not_redefined(self) -> None:
        """The module uses the imported _JURISDICTION_BINDING_ID_FORMAT, not a local one."""
        # The module-level object must be the same object as the one from
        # load_regulation_records.
        assert mod._JURISDICTION_BINDING_ID_FORMAT is _FORMAT_FROM_REG_RECORDS, (
            "_JURISDICTION_BINDING_ID_FORMAT must be the exact object imported from "
            "load_regulation_records, not a locally-defined copy."
        )

    def test_module_source_has_no_local_format_assignment(self) -> None:
        """The module source must not contain a local = assignment for the format const."""
        source = _MODULE_PATH.read_text(encoding="utf-8")
        # Exclude the import line itself; look for a local definition pattern
        local_define_count = source.count("_JURISDICTION_BINDING_ID_FORMAT =")
        # The only occurrence is in the import alias — actually there should be
        # zero occurrences of a local definition; the import uses `from ... import`
        # not `= `. Count assignments (not `from ... import`).
        assert local_define_count == 0, (
            f"Found {local_define_count} local assignment(s) of "
            "_JURISDICTION_BINDING_ID_FORMAT in the module source. "
            "It must only be imported, never redefined."
        )

    def test_id_format_value_correct(self) -> None:
        """Spot-check the format string value is the expected template."""
        assert "state" in _FORMAT_FROM_REG_RECORDS
        assert "jurisdiction_code" in _FORMAT_FROM_REG_RECORDS
        assert "species_group" in _FORMAT_FROM_REG_RECORDS
        assert "role" in _FORMAT_FROM_REG_RECORDS
        assert "geometry_id" in _FORMAT_FROM_REG_RECORDS


# ---------------------------------------------------------------------------
# TestRoleGateLock (AC #1106)
# ---------------------------------------------------------------------------


class TestRoleGateLock:
    def test_role_gate_stays_narrow(self) -> None:
        """_VALID_ROLE_FOR_E03_CO is exactly the 3-value narrow frozenset."""
        assert _VALID_ROLE_FOR_E03_CO == frozenset(
            {"primary_unit", "portion", "restricted_area"}
        )

    def test_no_hunt_zone_not_in_gate(self) -> None:
        assert "no_hunt_zone" not in _VALID_ROLE_FOR_E03_CO

    def test_other_overlay_not_in_gate(self) -> None:
        assert "other_overlay" not in _VALID_ROLE_FOR_E03_CO

    def test_cwd_management_zone_not_in_gate(self) -> None:
        assert "cwd_management_zone" not in _VALID_ROLE_FOR_E03_CO

    def test_bear_management_unit_not_in_gate(self) -> None:
        assert "bear_management_unit" not in _VALID_ROLE_FOR_E03_CO


# ---------------------------------------------------------------------------
# TestIsBindingEligibleCo
# ---------------------------------------------------------------------------


class TestIsBindingEligibleCo:
    def test_self_row_returns_true(self) -> None:
        row = _make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-1-geom",
            role_for_e03="primary_unit",
        )
        assert is_binding_eligible_co("mule_deer", "CO-GMU-1-geom", row) is True

    def test_self_row_returns_true_for_elk(self) -> None:
        row = _make_overlay_row(
            parent_gid="CO-GMU-20-geom",
            child_gid="CO-GMU-20-geom",
            role_for_e03="primary_unit",
        )
        assert is_binding_eligible_co("elk", "CO-GMU-20-geom", row) is True

    def test_restricted_area_returns_false(self) -> None:
        """Restricted_area rows are SKIPPED by the overlay builder (AC #1104)."""
        row = _make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid=_RMNP_GEOM_ID,
            role_for_e03="restricted_area",
            child_kind="restricted_area",
        )
        assert is_binding_eligible_co("mule_deer", "CO-GMU-1-geom", row) is False

    def test_portion_returns_true(self) -> None:
        """CO has zero portions in V1 but code path is preserved (AC #1103)."""
        row = _make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-1-portion-foo-geom",
            role_for_e03="portion",
            child_kind="portion",
        )
        assert is_binding_eligible_co("elk", "CO-GMU-1-geom", row) is True

    def test_non_self_primary_unit_returns_false(self) -> None:
        """Non-self primary_unit is defensive False (structurally unreachable in CO V1)."""
        row = _make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-2-geom",  # different gmu — not self
            role_for_e03="primary_unit",
        )
        assert is_binding_eligible_co("mule_deer", "CO-GMU-1-geom", row) is False

    def test_unknown_role_raises(self) -> None:
        row = _make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-99-geom",
            role_for_e03="unknown_role_xyz",
        )
        with pytest.raises(RuntimeError, match="unhandled role_for_e03"):
            is_binding_eligible_co("elk", "CO-GMU-1-geom", row)

    def test_unknown_role_raises_naming_child_id(self) -> None:
        row = _make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-special-geom",
            role_for_e03="block_management_area",  # valid binding role but not in CO gate
        )
        with pytest.raises(RuntimeError):
            is_binding_eligible_co("elk", "CO-GMU-1-geom", row)


# ---------------------------------------------------------------------------
# TestDeriveParentGeomId
# ---------------------------------------------------------------------------


class TestDeriveParentGeomId:
    def test_gmu_1_produces_correct_geom_id(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        assert _derive_parent_geometry_id_co(rr) == "CO-GMU-1-geom"

    def test_gmu_20_produces_correct_geom_id(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-GMU-20")
        assert _derive_parent_geometry_id_co(rr) == "CO-GMU-20-geom"

    def test_gmu_100_produces_correct_geom_id(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-GMU-100")
        assert _derive_parent_geometry_id_co(rr) == "CO-GMU-100-geom"

    def test_statewide_bear_raises(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-STATEWIDE-bear")
        with pytest.raises(RuntimeError, match="CO-STATEWIDE"):
            _derive_parent_geometry_id_co(rr)

    def test_statewide_generic_raises(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-STATEWIDE-elk")
        with pytest.raises(RuntimeError, match="CO-STATEWIDE"):
            _derive_parent_geometry_id_co(rr)

    def test_non_numeric_gmu_suffix_raises(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-GMU-abc")
        with pytest.raises(RuntimeError, match="non-numeric"):
            _derive_parent_geometry_id_co(rr)

    def test_garbage_pattern_raises(self) -> None:
        rr = _make_reg_record(jurisdiction_code="MT-HD-elk-100")
        with pytest.raises(RuntimeError, match="unhandled"):
            _derive_parent_geometry_id_co(rr)

    def test_empty_string_raises(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-GMU-")
        with pytest.raises(RuntimeError):
            _derive_parent_geometry_id_co(rr)


# ---------------------------------------------------------------------------
# TestLoadOverlayFixture
# ---------------------------------------------------------------------------


class TestLoadOverlayFixture:
    _VALID_ROW = {
        "parent_geometry_id": "CO-GMU-1-geom",
        "child_geometry_id": "CO-GMU-1-geom",
        "parent_kind": "gmu",
        "child_kind": "gmu",
        "relationship": "covers",
        "role_for_e03": "primary_unit",
    }

    def test_valid_list_parses(self, tmp_path: Path) -> None:
        f = tmp_path / "overlays.json"
        f.write_text(json.dumps([self._VALID_ROW]))
        rows = _load_overlay_fixture(f)
        assert len(rows) == 1
        assert rows[0]["role_for_e03"] == "primary_unit"

    def test_dict_with_relationships_key_parses(self, tmp_path: Path) -> None:
        f = tmp_path / "overlays.json"
        f.write_text(json.dumps({"relationships": [self._VALID_ROW]}))
        rows = _load_overlay_fixture(f)
        assert len(rows) == 1

    def test_empty_list_parses(self, tmp_path: Path) -> None:
        f = tmp_path / "overlays.json"
        f.write_text(json.dumps([]))
        rows = _load_overlay_fixture(f)
        assert rows == []

    def test_wrong_top_level_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text(json.dumps({"wrong": "shape"}))
        with pytest.raises(RuntimeError, match="top-level"):
            _load_overlay_fixture(f)

    def test_top_level_string_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text(json.dumps("not-a-list"))
        with pytest.raises(RuntimeError, match="top-level"):
            _load_overlay_fixture(f)

    def test_non_dict_row_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text(json.dumps(["not-a-dict"]))
        with pytest.raises(RuntimeError, match="row 0 is not a dict"):
            _load_overlay_fixture(f)

    def test_missing_key_row_raises(self, tmp_path: Path) -> None:
        bad_row = {k: v for k, v in self._VALID_ROW.items() if k != "role_for_e03"}
        f = tmp_path / "bad.json"
        f.write_text(json.dumps([bad_row]))
        with pytest.raises(RuntimeError, match="missing"):
            _load_overlay_fixture(f)

    def test_dict_with_relationships_non_list_value_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text(json.dumps({"relationships": "not-a-list"}))
        with pytest.raises(RuntimeError, match="not a list"):
            _load_overlay_fixture(f)

    def test_multiple_rows_all_return(self, tmp_path: Path) -> None:
        row2 = {**self._VALID_ROW, "child_geometry_id": "CO-GMU-2-geom"}
        f = tmp_path / "overlays.json"
        f.write_text(json.dumps([self._VALID_ROW, row2]))
        rows = _load_overlay_fixture(f)
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# TestFetchGeometrySources
# ---------------------------------------------------------------------------


class TestFetchGeometrySources:
    def _source_dict(self, citation_id: str = "co-cpw-big-game-2026-brochure") -> dict[str, Any]:
        return {
            "id": citation_id,
            "agency": "Colorado Parks and Wildlife",
            "title": "2026 CO Big Game",
            "url": "https://example.com/brochure.pdf",
            "publication_date": "2026-03-04",
            "document_type": "annual_regulations",
        }

    def test_returns_dict_from_cursor_rows(self) -> None:
        src_dict = self._source_dict()
        conn = _make_mock_conn(rows=[("CO-GMU-1-geom", src_dict)])
        result = _fetch_geometry_sources(conn, {"CO-GMU-1-geom"})
        assert "CO-GMU-1-geom" in result
        assert isinstance(result["CO-GMU-1-geom"], SourceCitation)

    def test_empty_geometry_ids_returns_empty_dict(self) -> None:
        conn = MagicMock()
        result = _fetch_geometry_sources(conn, set())
        assert result == {}
        conn.cursor.assert_not_called()

    def test_missing_id_raises(self) -> None:
        """Requested id not returned by the DB → raises with diagnostic."""
        conn = _make_mock_conn(rows=[])  # no rows returned
        with pytest.raises(RuntimeError, match="absent from the geometry table"):
            _fetch_geometry_sources(conn, {"CO-GMU-missing-geom"})

    def test_malformed_source_jsonb_raises(self) -> None:
        """source column is not a valid SourceCitation → raises naming the failing id."""
        conn = _make_mock_conn(rows=[("CO-GMU-1-geom", {"bad": "shape"})])
        with pytest.raises(RuntimeError, match="malformed source jsonb"):
            _fetch_geometry_sources(conn, {"CO-GMU-1-geom"})

    def test_multiple_ids_all_returned(self) -> None:
        src = self._source_dict()
        src2 = {**self._source_dict("co-source-2"), "id": "co-source-2"}
        conn = _make_mock_conn(rows=[
            ("CO-GMU-1-geom", src),
            ("CO-GMU-2-geom", src2),
        ])
        result = _fetch_geometry_sources(conn, {"CO-GMU-1-geom", "CO-GMU-2-geom"})
        assert set(result.keys()) == {"CO-GMU-1-geom", "CO-GMU-2-geom"}

    def test_missing_subset_raises_naming_missing(self) -> None:
        src = self._source_dict()
        conn = _make_mock_conn(rows=[("CO-GMU-1-geom", src)])
        with pytest.raises(RuntimeError, match="absent from the geometry table"):
            _fetch_geometry_sources(conn, {"CO-GMU-1-geom", "CO-GMU-missing-geom"})


# ---------------------------------------------------------------------------
# TestFetchZoneWkts
# ---------------------------------------------------------------------------


class TestFetchZoneWkts:
    def test_returns_dict_from_cursor_rows(self) -> None:
        conn = _make_mock_conn(rows=[(
            _RMNP_GEOM_ID,
            "MULTIPOLYGON(((-105.0 40.0, -105.0 40.5, -104.5 40.5, -104.5 40.0, -105.0 40.0)))",
        )])
        result = _fetch_zone_wkts(conn, {_RMNP_GEOM_ID})
        assert _RMNP_GEOM_ID in result
        assert "MULTIPOLYGON" in result[_RMNP_GEOM_ID]

    def test_empty_zone_ids_returns_empty_dict(self) -> None:
        conn = MagicMock()
        result = _fetch_zone_wkts(conn, set())
        assert result == {}
        conn.cursor.assert_not_called()

    def test_missing_zone_id_raises(self) -> None:
        conn = _make_mock_conn(rows=[])
        with pytest.raises(RuntimeError, match="absent from the geometry table"):
            _fetch_zone_wkts(conn, {_RMNP_GEOM_ID})

    def test_sql_uses_extensions_st_as_text(self) -> None:
        """SQL must use extensions.ST_AsText (Supabase schema-prefix discipline)."""
        conn = _make_mock_conn(rows=[(_RMNP_GEOM_ID, "MULTIPOLYGON EMPTY")])
        _fetch_zone_wkts(conn, {_RMNP_GEOM_ID})
        executed_sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "extensions.ST_AsText" in executed_sql, (
            f"SQL must use extensions.ST_AsText, got: {executed_sql!r}"
        )

    def test_sql_does_not_use_bare_st_as_text(self) -> None:
        conn = _make_mock_conn(rows=[(_RMNP_GEOM_ID, "MULTIPOLYGON EMPTY")])
        _fetch_zone_wkts(conn, {_RMNP_GEOM_ID})
        executed_sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        # every ST_AsText occurrence must be extensions.-prefixed
        assert executed_sql.count("ST_AsText") == executed_sql.count("extensions.ST_AsText")

    def test_multiple_zone_ids_all_returned(self) -> None:
        conn = _make_mock_conn(rows=[
            (_RMNP_GEOM_ID, "MULTIPOLYGON EMPTY"),
            (_MESA_VERDE_GEOM_ID, "MULTIPOLYGON EMPTY"),
        ])
        result = _fetch_zone_wkts(conn, {_RMNP_GEOM_ID, _MESA_VERDE_GEOM_ID})
        assert set(result.keys()) == {_RMNP_GEOM_ID, _MESA_VERDE_GEOM_ID}


# ---------------------------------------------------------------------------
# TestBuildStatewideBindings
# ---------------------------------------------------------------------------


class TestBuildStatewideBindings:
    def test_empty_list_returns_empty(self) -> None:
        source = _make_gis_source()
        result = _build_statewide_bindings_co([], source)
        assert result == []

    def test_one_statewide_rr_produces_one_binding(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-STATEWIDE-bear", species_group="bear")
        source = _make_gis_source(_CO_STATEWIDE_GEOM_ID)
        result = _build_statewide_bindings_co([rr], source)
        assert len(result) == 1
        assert result[0].geometry_id == _CO_STATEWIDE_GEOM_ID
        assert result[0].role == "primary_unit"

    def test_statewide_binding_id_uses_format(self) -> None:
        rr = _make_reg_record(
            jurisdiction_code="CO-STATEWIDE-bear",
            species_group="bear",
            state="US-CO",
            license_year=2026,
        )
        source = _make_gis_source(_CO_STATEWIDE_GEOM_ID)
        result = _build_statewide_bindings_co([rr], source)
        expected_id = _FORMAT_FROM_REG_RECORDS.format(
            state="US-CO",
            jurisdiction_code="CO-STATEWIDE-bear",
            species_group="bear",
            license_year=2026,
            role="primary_unit",
            geometry_id=_CO_STATEWIDE_GEOM_ID,
        )
        assert result[0].id == expected_id

    def test_statewide_binding_verbatim_rule_is_none(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-STATEWIDE-bear", species_group="bear")
        source = _make_gis_source()
        result = _build_statewide_bindings_co([rr], source)
        assert result[0].verbatim_rule is None


# ---------------------------------------------------------------------------
# TestBuildOverlayBindings
# ---------------------------------------------------------------------------


class TestBuildOverlayBindings:
    def _make_source_lookup(self, gid: str) -> dict[str, SourceCitation]:
        return {gid: _make_gis_source(gid)}

    def test_self_row_produces_primary_unit_binding(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        rows = [_make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-1-geom",
            role_for_e03="primary_unit",
        )]
        source_lookup = self._make_source_lookup("CO-GMU-1-geom")
        result = _build_overlay_bindings_co([rr], rows, source_lookup)
        assert len(result) == 1
        assert result[0].role == "primary_unit"
        assert result[0].geometry_id == "CO-GMU-1-geom"

    def test_overlay_builder_emits_zero_restricted_area_bindings(self) -> None:
        """AC #1104 lock: restricted_area rows are skipped by the overlay builder."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        rows = [
            _make_overlay_row(
                parent_gid="CO-GMU-1-geom",
                child_gid="CO-GMU-1-geom",
                role_for_e03="primary_unit",
            ),
            _make_overlay_row(
                parent_gid="CO-GMU-1-geom",
                child_gid=_RMNP_GEOM_ID,
                role_for_e03="restricted_area",
                child_kind="restricted_area",
            ),
        ]
        source_lookup = {
            "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
            _RMNP_GEOM_ID: _make_gis_source(_RMNP_GEOM_ID),
        }
        result = _build_overlay_bindings_co([rr], rows, source_lookup)
        restricted_area_bindings = [b for b in result if b.role == "restricted_area"]
        assert len(restricted_area_bindings) == 0, (
            "Overlay builder must NOT emit restricted_area bindings "
            "(those come from _build_no_hunt_zone_bindings_co)"
        )
        # Self-row still emitted
        assert len(result) == 1
        assert result[0].role == "primary_unit"

    def test_missing_parent_fixture_entry_raises(self) -> None:
        """Guard 12: reg_record's parent gid has no overlay fixture entries."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-99")
        rows = [_make_overlay_row(parent_gid="CO-GMU-1-geom", child_gid="CO-GMU-1-geom")]
        source_lookup = {"CO-GMU-1-geom": _make_gis_source()}
        with pytest.raises(RuntimeError, match="no overlay-fixture entries"):
            _build_overlay_bindings_co([rr], rows, source_lookup)

    def test_unknown_role_raises_before_eligibility_check(self) -> None:
        """Guard 13: unknown role_for_e03 raises before is_binding_eligible_co is called."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        rows = [_make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-1-geom",
            role_for_e03="no_hunt_zone",  # not in _VALID_ROLE_FOR_E03_CO
        )]
        source_lookup = {"CO-GMU-1-geom": _make_gis_source()}
        with pytest.raises(RuntimeError, match="unknown role_for_e03"):
            _build_overlay_bindings_co([rr], rows, source_lookup)

    def test_other_overlay_role_also_raises(self) -> None:
        """other_overlay is also outside the narrow gate."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        rows = [_make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-1-geom",
            role_for_e03="other_overlay",
        )]
        source_lookup = {"CO-GMU-1-geom": _make_gis_source()}
        with pytest.raises(RuntimeError, match="unknown role_for_e03"):
            _build_overlay_bindings_co([rr], rows, source_lookup)

    def test_missing_source_lookup_raises(self) -> None:
        """Guard 14: child_geometry_id not in source_lookup raises."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        rows = [_make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-1-geom",
            role_for_e03="primary_unit",
        )]
        # Empty source lookup — child id not present
        with pytest.raises(RuntimeError, match="missing from source_lookup"):
            _build_overlay_bindings_co([rr], rows, {})

    def test_duplicate_binding_id_raises(self) -> None:
        """Guard 15: two rows that produce the same id raises."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        # Two identical self-row entries (would produce duplicate ids)
        row = _make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-1-geom",
            role_for_e03="primary_unit",
        )
        source_lookup = {"CO-GMU-1-geom": _make_gis_source()}
        with pytest.raises(RuntimeError, match="duplicate binding id"):
            _build_overlay_bindings_co([rr], [row, row], source_lookup)

    def test_portion_row_produces_binding(self) -> None:
        """portion rows are emitted (code path preserved for M3+)."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        rows = [
            # Self-row
            _make_overlay_row(
                parent_gid="CO-GMU-1-geom",
                child_gid="CO-GMU-1-geom",
                role_for_e03="primary_unit",
            ),
            # Portion row
            _make_overlay_row(
                parent_gid="CO-GMU-1-geom",
                child_gid="CO-GMU-1-portion-foo-geom",
                role_for_e03="portion",
                child_kind="portion",
            ),
        ]
        source_lookup = {
            "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
            "CO-GMU-1-portion-foo-geom": _make_gis_source("CO-GMU-1-portion-foo-geom"),
        }
        result = _build_overlay_bindings_co([rr], rows, source_lookup)
        assert len(result) == 2
        roles = {b.role for b in result}
        assert "primary_unit" in roles
        assert "portion" in roles

    def test_multiple_reg_records_all_get_bindings(self) -> None:
        rr1 = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="elk")
        rr2 = _make_reg_record(jurisdiction_code="CO-GMU-2", species_group="mule_deer")
        rows = [
            _make_overlay_row(parent_gid="CO-GMU-1-geom", child_gid="CO-GMU-1-geom"),
            _make_overlay_row(parent_gid="CO-GMU-2-geom", child_gid="CO-GMU-2-geom"),
        ]
        source_lookup = {
            "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
            "CO-GMU-2-geom": _make_gis_source("CO-GMU-2-geom"),
        }
        result = _build_overlay_bindings_co([rr1, rr2], rows, source_lookup)
        assert len(result) == 2

    def test_binding_verbatim_rule_is_none(self) -> None:
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        rows = [_make_overlay_row(parent_gid="CO-GMU-1-geom", child_gid="CO-GMU-1-geom")]
        source_lookup = {"CO-GMU-1-geom": _make_gis_source()}
        result = _build_overlay_bindings_co([rr], rows, source_lookup)
        assert result[0].verbatim_rule is None


# ---------------------------------------------------------------------------
# TestBuildNoHuntZoneBindings + TestAfaLock
# ---------------------------------------------------------------------------


def _make_no_hunt_zone_setup(
    zone_ids: list[str],
    nearby_gmu_ids: list[str],
    reg_records: list[RegulationRecord] | None = None,
) -> tuple[MagicMock, dict[str, SourceCitation]]:
    """Create a mocked conn suitable for _build_no_hunt_zone_bindings_co.

    ``_fetch_zone_wkts`` is called first (uses conn.cursor to SELECT WKTs),
    then ``query_nearby_gmus_for_zone`` is called (also uses conn.cursor).

    We patch ``query_nearby_gmus_for_zone`` directly so the test doesn't
    need to worry about the internal cursor plumbing of that scaffold function.
    """
    wkt_rows = [(zid, "MULTIPOLYGON EMPTY") for zid in zone_ids]
    conn = _make_mock_conn(rows=wkt_rows)
    source_lookup = {zid: _make_gis_source(zid) for zid in zone_ids}
    # Add sources for any GMU geometries reg_records reference
    if reg_records:
        for rr in reg_records:
            gmu_geom_id = f"{rr.jurisdiction_code}-geom"
            source_lookup[gmu_geom_id] = _make_gis_source(gmu_geom_id)
    return conn, source_lookup


class TestAfaLock:
    """AC #1105 — AFA must bind other_overlay, not no_hunt_zone."""

    def test_afa_bound_other_overlay_not_no_hunt_zone(self) -> None:
        """AC #1105 (REQUIRED — exact name).

        - AFA zone → zero role='no_hunt_zone' bindings, ≥1 role='other_overlay'
        - A non-AFA zone (Mesa Verde) → role='no_hunt_zone' binding
        """
        zone_ids_to_test = [_AFA_GEOM_ID, _MESA_VERDE_GEOM_ID]
        conn, source_lookup = _make_no_hunt_zone_setup(
            zone_ids=zone_ids_to_test,
            nearby_gmu_ids=["CO-GMU-1-geom"],
        )
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="mule_deer")
        source_lookup["CO-GMU-1-geom"] = _make_gis_source("CO-GMU-1-geom")

        # Only test AFA and Mesa Verde from EXPECTED_CO_RA_ORPHAN_IDS to keep
        # the test focused; patch _fetch_zone_wkts to return only those two.
        # Also patch query_nearby_gmus_for_zone to return CO-GMU-1-geom for both zones.
        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={
                    _AFA_GEOM_ID: "MULTIPOLYGON EMPTY",
                    _MESA_VERDE_GEOM_ID: "MULTIPOLYGON EMPTY",
                },
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                return_value=["CO-GMU-1-geom"],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_AFA_GEOM_ID, _MESA_VERDE_GEOM_ID}),
            ),
        ):
            result = _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)

        # AFA: role must be other_overlay (not no_hunt_zone)
        afa_bindings = [b for b in result if b.geometry_id == _AFA_GEOM_ID]
        assert len(afa_bindings) >= 1, "AFA zone must produce at least 1 binding"
        afa_no_hunt = [b for b in afa_bindings if b.role == "no_hunt_zone"]
        assert len(afa_no_hunt) == 0, (
            "AFA must NOT be bound as no_hunt_zone — it is a regulated-access "
            "HUNTING area per CPW Big Game brochure p.78"
        )
        afa_other_overlay = [b for b in afa_bindings if b.role == "other_overlay"]
        assert len(afa_other_overlay) >= 1, (
            "AFA must be bound as other_overlay"
        )

        # Mesa Verde: role must be no_hunt_zone
        mv_bindings = [b for b in result if b.geometry_id == _MESA_VERDE_GEOM_ID]
        assert len(mv_bindings) >= 1, "Mesa Verde must produce at least 1 binding"
        mv_no_hunt = [b for b in mv_bindings if b.role == "no_hunt_zone"]
        assert len(mv_no_hunt) >= 1, (
            "Mesa Verde (NPS NM) must be bound as no_hunt_zone"
        )
        mv_other = [b for b in mv_bindings if b.role == "other_overlay"]
        assert len(mv_other) == 0, (
            "Mesa Verde must NOT be bound as other_overlay"
        )


class TestBuildNoHuntZoneBindings:
    def test_nine_nps_zones_get_no_hunt_zone_role(self) -> None:
        """All zones except AFA get role='no_hunt_zone'."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="elk")
        source_lookup: dict[str, SourceCitation] = {
            zid: _make_gis_source(zid) for zid in EXPECTED_CO_RA_ORPHAN_IDS
        }
        source_lookup["CO-GMU-1-geom"] = _make_gis_source("CO-GMU-1-geom")
        conn = MagicMock()

        wkt_dict = {zid: "MULTIPOLYGON EMPTY" for zid in EXPECTED_CO_RA_ORPHAN_IDS}

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value=wkt_dict,
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                return_value=["CO-GMU-1-geom"],
            ),
        ):
            result = _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)

        # Every NPS zone should produce a no_hunt_zone binding
        no_hunt_zone_geom_ids = {b.geometry_id for b in result if b.role == "no_hunt_zone"}
        for nps_id in _NPS_ZONE_IDS:
            assert nps_id in no_hunt_zone_geom_ids, (
                f"{nps_id} should produce a no_hunt_zone binding"
            )

        # AFA should produce an other_overlay binding
        afa_bindings = [b for b in result if b.geometry_id == _AFA_GEOM_ID]
        assert all(b.role == "other_overlay" for b in afa_bindings)

    def test_per_zone_zero_nearby_gmus_raises(self) -> None:
        """Guard 17: zero nearby GMUs per zone raises RuntimeError."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        source_lookup = {_RMNP_GEOM_ID: _make_gis_source(_RMNP_GEOM_ID)}
        conn = MagicMock()

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={_RMNP_GEOM_ID: "MULTIPOLYGON EMPTY"},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                return_value=[],  # zero matches
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_RMNP_GEOM_ID}),
            ),
        ):
            with pytest.raises(RuntimeError, match="zero nearby GMU"):
                _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)

    def test_missing_zone_wkt_raises(self) -> None:
        """Guard 16: zone WKT missing from pre-fetched dict raises."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        source_lookup = {_RMNP_GEOM_ID: _make_gis_source(_RMNP_GEOM_ID)}
        conn = MagicMock()

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={},  # empty — zone WKT missing
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_RMNP_GEOM_ID}),
            ),
        ):
            with pytest.raises(RuntimeError):
                _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)

    def test_missing_zone_source_raises(self) -> None:
        """Guard 18: zone source citation missing from source_lookup raises."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1")
        # source_lookup does NOT include the RMNP zone
        source_lookup = {"CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom")}
        conn = MagicMock()

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={_RMNP_GEOM_ID: "MULTIPOLYGON EMPTY"},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                return_value=["CO-GMU-1-geom"],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_RMNP_GEOM_ID}),
            ),
        ):
            with pytest.raises(RuntimeError, match="missing from source_lookup"):
                _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)

    def test_duplicate_binding_id_raises(self) -> None:
        """Guard 19: duplicate binding id within no-hunt-zone builder raises."""
        # Two identical reg_records for the same GMU/species → same binding id twice
        rr1 = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="mule_deer")
        rr2 = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="mule_deer")
        source_lookup = {
            _RMNP_GEOM_ID: _make_gis_source(_RMNP_GEOM_ID),
            "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
        }
        conn = MagicMock()

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={_RMNP_GEOM_ID: "MULTIPOLYGON EMPTY"},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                return_value=["CO-GMU-1-geom"],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_RMNP_GEOM_ID}),
            ),
        ):
            with pytest.raises(RuntimeError, match="duplicate binding id"):
                _build_no_hunt_zone_bindings_co(conn, [rr1, rr2], source_lookup)

    def test_gmu_with_no_reg_records_emits_warning_zone_still_binds(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Zone has TWO nearby GMUs: one WITH reg_records, one WITHOUT.

        FIX A: the per-GMU WARNING fires for the empty GMU, the zone still
        produces ≥1 binding from the non-empty GMU (no raise), and no binding
        references the empty GMU.
        """
        # CO-GMU-1 has a reg_record; CO-GMU-2 does NOT.
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="mule_deer")
        source_lookup = {
            _RMNP_GEOM_ID: _make_gis_source(_RMNP_GEOM_ID),
            "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
            "CO-GMU-2-geom": _make_gis_source("CO-GMU-2-geom"),
        }
        conn = MagicMock()

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={_RMNP_GEOM_ID: "MULTIPOLYGON EMPTY"},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                # Two nearby GMUs: CO-GMU-1 (has rr) + CO-GMU-2 (no rr)
                return_value=["CO-GMU-1-geom", "CO-GMU-2-geom"],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_RMNP_GEOM_ID}),
            ),
            caplog.at_level(
                logging.WARNING,
                logger="states.colorado.load_jurisdiction_bindings",
            ),
        ):
            # Should NOT raise: CO-GMU-1 provides ≥1 binding; zone is visible.
            result = _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)

        # (a) Zone produces ≥1 binding from the non-empty GMU
        zone_bindings = [b for b in result if b.geometry_id == _RMNP_GEOM_ID]
        assert len(zone_bindings) >= 1, (
            "Zone must produce ≥1 binding when at least one nearby GMU has reg_records"
        )

        # (b) WARNING was emitted for the empty GMU
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "CO-GMU-2-geom" in msg and "no CO regulation_records" in msg
            for msg in warning_messages
        ), (
            f"Expected a WARNING about CO-GMU-2-geom having no regulation_records. "
            f"Got warnings: {warning_messages!r}"
        )

        # (c) No binding references the empty GMU
        empty_gmu_bindings = [
            b for b in result
            if b.regulation_record_jurisdiction_code == "CO-GMU-2"
        ]
        assert len(empty_gmu_bindings) == 0, (
            "No binding should reference the empty GMU (CO-GMU-2)"
        )

    def test_zone_with_all_empty_gmus_raises(self) -> None:
        """FIX A: zone whose ALL nearby GMUs lack reg_records raises RuntimeError.

        This is Guard 20: GMUs were found (Guard 17 doesn't fire) but none of
        them had CO regulation_records, so the zone emits zero bindings and would
        become invisible in query results.
        """
        # CO-GMU-99 has the only reg_record; nearby GMUs are CO-GMU-1 and CO-GMU-2
        # — neither maps to CO-GMU-99, so the zone produces zero bindings.
        rr = _make_reg_record(jurisdiction_code="CO-GMU-99", species_group="mule_deer")
        source_lookup = {
            _RMNP_GEOM_ID: _make_gis_source(_RMNP_GEOM_ID),
            "CO-GMU-99-geom": _make_gis_source("CO-GMU-99-geom"),
        }
        conn = MagicMock()

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={_RMNP_GEOM_ID: "MULTIPOLYGON EMPTY"},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                # Both nearby GMUs lack reg_records (rr is CO-GMU-99, not CO-GMU-1/2)
                return_value=["CO-GMU-1-geom", "CO-GMU-2-geom"],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_RMNP_GEOM_ID}),
            ),
        ):
            with pytest.raises(RuntimeError, match="zero bindings despite"):
                _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)


# ---------------------------------------------------------------------------
# TestCountGuard
# ---------------------------------------------------------------------------


class TestCountGuard:
    def test_value_within_band_passes(self) -> None:
        lo, hi = _BINDING_COUNT_GUARD_BAND
        mid = (lo + hi) // 2
        _assert_binding_count_within_guard(mid)  # should not raise

    def test_value_at_lower_bound_passes(self) -> None:
        lo, _ = _BINDING_COUNT_GUARD_BAND
        _assert_binding_count_within_guard(lo)  # inclusive lower bound

    def test_value_at_upper_bound_passes(self) -> None:
        _, hi = _BINDING_COUNT_GUARD_BAND
        _assert_binding_count_within_guard(hi)  # inclusive upper bound

    def test_value_below_band_raises(self) -> None:
        lo, _ = _BINDING_COUNT_GUARD_BAND
        with pytest.raises(RuntimeError, match="outside expected band"):
            _assert_binding_count_within_guard(lo - 1)

    def test_value_above_band_raises(self) -> None:
        _, hi = _BINDING_COUNT_GUARD_BAND
        with pytest.raises(RuntimeError, match="outside expected band"):
            _assert_binding_count_within_guard(hi + 1)

    def test_zero_raises(self) -> None:
        with pytest.raises(RuntimeError):
            _assert_binding_count_within_guard(0)

    def test_band_is_provisional_300_1200(self) -> None:
        """Band is explicitly documented as provisional (300, 1200)."""
        assert _BINDING_COUNT_GUARD_BAND == (300, 1200)


# ---------------------------------------------------------------------------
# TestCrossStateFilterRegression
# ---------------------------------------------------------------------------


class TestCrossStateFilterRegression:
    def test_query_all_colorado_regulation_records_sql_contains_state_filter(self) -> None:
        """AC #1109: SQL must contain 'state = %s' to prevent cross-state pollution."""
        # Call the function with a mocked conn that returns no rows
        conn = _make_mock_conn(rows=[])
        _query_all_colorado_regulation_records(conn)
        executed_sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "state = %s" in executed_sql, (
            f"_query_all_colorado_regulation_records SQL must contain 'state = %s' "
            f"for cross-state pollution prevention. Got: {executed_sql!r}"
        )

    def test_query_binds_state_value_as_us_co(self) -> None:
        """The state parameter must be bound to 'US-CO'."""
        conn = _make_mock_conn(rows=[])
        _query_all_colorado_regulation_records(conn)
        params = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][1]
        assert params[0] == "US-CO", (
            f"State parameter must be 'US-CO', got {params[0]!r}"
        )

    def test_query_binds_license_year(self) -> None:
        """The license_year parameter is bound (not hardcoded)."""
        conn = _make_mock_conn(rows=[])
        _query_all_colorado_regulation_records(conn)
        params = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][1]
        assert params[1] == 2026

    def test_query_sql_does_not_hardcode_us_co(self) -> None:
        """State value must be a bound parameter, not a hardcoded literal in SQL."""
        conn = _make_mock_conn(rows=[])
        _query_all_colorado_regulation_records(conn)
        executed_sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "'US-CO'" not in executed_sql, (
            "SQL must not hardcode 'US-CO' — state must be a bound %s parameter"
        )

    def test_query_sql_does_not_reference_mt_state(self) -> None:
        """SQL must have no reference to Montana state code."""
        conn = _make_mock_conn(rows=[])
        _query_all_colorado_regulation_records(conn)
        executed_sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "'US-MT'" not in executed_sql

    def test_nearby_gmu_sql_distance_bound_not_hardcoded(self) -> None:
        """AC #1110: query_nearby_gmus_for_zone binds _NO_HUNT_ZONE_NEARBY_DISTANCE_M
        as a parameter (not hardcoded 5000), confirmed by the scaffold test — ensure
        the constant is accessible and used in the module."""
        from states.colorado.load_jurisdiction_bindings import (
            _NO_HUNT_ZONE_NEARBY_DISTANCE_M,
            _QUERY_NEARBY_GMUS_FOR_ZONE_SQL,
        )
        # Confirm distance is NOT hardcoded in the SQL string
        assert "5000" not in _QUERY_NEARBY_GMUS_FOR_ZONE_SQL, (
            "Distance must be a bound %s parameter, not a literal 5000"
        )
        assert _NO_HUNT_ZONE_NEARBY_DISTANCE_M == 5000


# ---------------------------------------------------------------------------
# TestMainStatewideGuard
# ---------------------------------------------------------------------------


class TestMainStatewideGuard:
    """Test the unexpected-statewide guard in main()."""

    def _make_minimal_source_row(self) -> tuple[object, ...]:
        """Minimal source jsonb dict for a RegulationRecord row."""
        return (
            "co-cpw-big-game-2026-brochure",
            "Colorado Parks and Wildlife",
            "2026 Colorado Big Game",
            "https://spl.cde.state.co.us/brochure.pdf",
            "2026-03-04",
            "annual_regulations",
        )

    def _rr_tuple(self, jurisdiction_code: str, species_group: str = "mule_deer") -> tuple[object, ...]:
        """Build a fake DB row tuple matching _query_all_colorado_regulation_records SELECT."""
        source_dict = {
            "id": "co-cpw-big-game-2026-brochure",
            "agency": "Colorado Parks and Wildlife",
            "title": "2026 Colorado Big Game",
            "url": "https://spl.cde.state.co.us/brochure.pdf",
            "publication_date": "2026-03-04",
            "document_type": "annual_regulations",
        }
        import datetime
        return (
            "US-CO",           # state
            jurisdiction_code, # jurisdiction_code
            species_group,     # species_group
            2026,              # license_year
            2,                 # schema_version
            "high",            # confidence
            [],                # additional_rules
            datetime.datetime(2026, 6, 1),  # ingested_at
            source_dict,       # source
        )

    def test_unexpected_statewide_raises(self) -> None:
        """Guard 21: CO-STATEWIDE-* reg_record in main() raises RuntimeError."""
        statewide_tuple = self._rr_tuple("CO-STATEWIDE-bear", "bear")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [statewide_tuple]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with (
            patch("states.colorado.load_jurisdiction_bindings.db.connect",
                  return_value=mock_conn),
            patch("states.colorado.load_jurisdiction_bindings._load_overlay_fixture",
                  return_value=[]),
        ):
            with pytest.raises(RuntimeError, match="unexpected statewide"):
                mod.main(["--dry-run"])

    def test_zero_statewide_reg_records_no_raise(self) -> None:
        """No CO-STATEWIDE-* reg_records → no unexpected-statewide raise."""
        gmu_tuple = self._rr_tuple("CO-GMU-1", "mule_deer")

        source_dict = {
            "id": "co-test-source",
            "agency": "Test",
            "title": "Test",
            "url": "https://example.com",
            "publication_date": "2026-01-01",
            "document_type": "gis_layer",
        }
        source_rows = [("CO-GMU-1-geom", source_dict), (_CO_STATEWIDE_GEOM_ID, source_dict)]

        mock_cur_rr = MagicMock()
        mock_cur_rr.fetchall.return_value = [gmu_tuple]

        mock_cur_src = MagicMock()
        mock_cur_src.fetchall.return_value = source_rows

        overlay_row = _make_overlay_row(
            parent_gid="CO-GMU-1-geom",
            child_gid="CO-GMU-1-geom",
            role_for_e03="primary_unit",
        )

        # We'll patch main's sub-helpers to isolate the statewide guard logic
        with (
            patch("states.colorado.load_jurisdiction_bindings._load_overlay_fixture",
                  return_value=[overlay_row]),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_all_colorado_regulation_records",
                return_value=[_make_reg_record(jurisdiction_code="CO-GMU-1")],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_geometry_sources",
                return_value={
                    _CO_STATEWIDE_GEOM_ID: _make_gis_source(_CO_STATEWIDE_GEOM_ID),
                    "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
                },
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_overlay_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_no_hunt_zone_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_co_reporting_obligations",
                return_value=[("co-bear-mandatory-check-5day-statewide", None)],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_regulation_reporting_links",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._assert_binding_count_within_guard",
            ),
            patch("states.colorado.load_jurisdiction_bindings.db.connect") as mock_db_connect,
        ):
            mock_conn_ctx = MagicMock()
            mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn_ctx)
            mock_conn_ctx.__exit__ = MagicMock(return_value=False)
            mock_db_connect.return_value = mock_conn_ctx

            # Should not raise — no statewide reg_records
            result = mod.main(["--dry-run"])
        assert result == 0


# ---------------------------------------------------------------------------
# TestMainCrossBuilderDedupGuard
# ---------------------------------------------------------------------------


class TestMainCrossBuilderDedupGuard:
    """Guard 22: cross-builder duplicate binding ids raises in main()."""

    def _make_duplicate_binding(self) -> JurisdictionBinding:
        return JurisdictionBinding(
            id="US-CO-CO-GMU-1-mule_deer-2026-primary_unit-CO-GMU-1-geom",
            regulation_record_state="US-CO",
            regulation_record_jurisdiction_code="CO-GMU-1",
            regulation_record_species_group="mule_deer",
            regulation_record_license_year=2026,
            geometry_id="CO-GMU-1-geom",
            role="primary_unit",
            verbatim_rule=None,
            source=_make_gis_source(),
        )

    def test_cross_builder_duplicate_raises(self) -> None:
        """Two builders returning the same binding id → main() raises before write."""
        dup_binding = self._make_duplicate_binding()

        with (
            patch("states.colorado.load_jurisdiction_bindings._load_overlay_fixture",
                  return_value=[]),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_all_colorado_regulation_records",
                return_value=[_make_reg_record(jurisdiction_code="CO-GMU-1")],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_geometry_sources",
                return_value={
                    _CO_STATEWIDE_GEOM_ID: _make_gis_source(),
                    "CO-GMU-1-geom": _make_gis_source(),
                },
            ),
            # Overlay builder emits the binding
            patch(
                "states.colorado.load_jurisdiction_bindings._build_statewide_bindings_co",
                return_value=[dup_binding],
            ),
            # No-hunt builder emits the SAME id — cross-builder collision
            patch(
                "states.colorado.load_jurisdiction_bindings._build_overlay_bindings_co",
                return_value=[dup_binding],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_no_hunt_zone_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_co_reporting_obligations",
                return_value=[("co-bear-mandatory-check-5day-statewide", None)],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_regulation_reporting_links",
                return_value=[],
            ),
            patch("states.colorado.load_jurisdiction_bindings.db.connect") as mock_db_connect,
        ):
            mock_conn_ctx = MagicMock()
            mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn_ctx)
            mock_conn_ctx.__exit__ = MagicMock(return_value=False)
            mock_db_connect.return_value = mock_conn_ctx

            with pytest.raises(RuntimeError, match="cross-builder duplicate binding id"):
                mod.main(["--dry-run"])

    def test_no_duplicate_ids_passes_dedup_check(self) -> None:
        """Unique ids across all builders passes the dedup check."""
        binding1 = JurisdictionBinding(
            id="US-CO-CO-GMU-1-mule_deer-2026-primary_unit-CO-GMU-1-geom",
            regulation_record_state="US-CO",
            regulation_record_jurisdiction_code="CO-GMU-1",
            regulation_record_species_group="mule_deer",
            regulation_record_license_year=2026,
            geometry_id="CO-GMU-1-geom",
            role="primary_unit",
            verbatim_rule=None,
            source=_make_gis_source(),
        )
        binding2 = JurisdictionBinding(
            id="US-CO-CO-GMU-2-elk-2026-primary_unit-CO-GMU-2-geom",
            regulation_record_state="US-CO",
            regulation_record_jurisdiction_code="CO-GMU-2",
            regulation_record_species_group="elk",
            regulation_record_license_year=2026,
            geometry_id="CO-GMU-2-geom",
            role="primary_unit",
            verbatim_rule=None,
            source=_make_gis_source(),
        )

        with (
            patch("states.colorado.load_jurisdiction_bindings._load_overlay_fixture",
                  return_value=[]),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_all_colorado_regulation_records",
                return_value=[_make_reg_record()],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_geometry_sources",
                return_value={_CO_STATEWIDE_GEOM_ID: _make_gis_source()},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_statewide_bindings_co",
                return_value=[binding1],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_overlay_bindings_co",
                return_value=[binding2],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_no_hunt_zone_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_co_reporting_obligations",
                return_value=[("co-bear-mandatory-check-5day-statewide", None)],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_regulation_reporting_links",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._assert_binding_count_within_guard",
            ),
            patch("states.colorado.load_jurisdiction_bindings.db.connect") as mock_db_connect,
        ):
            mock_conn_ctx = MagicMock()
            mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn_ctx)
            mock_conn_ctx.__exit__ = MagicMock(return_value=False)
            mock_db_connect.return_value = mock_conn_ctx

            result = mod.main(["--dry-run"])
        assert result == 0


# ---------------------------------------------------------------------------
# TestModuleConstants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_afa_geom_id_value(self) -> None:
        assert _AFA_GEOM_ID == "CO-restricted-united-states-air-force-academy-geom"

    def test_afa_geom_id_is_in_expected_orphan_ids(self) -> None:
        assert _AFA_GEOM_ID in EXPECTED_CO_RA_ORPHAN_IDS

    def test_expected_orphan_ids_has_ten_entries(self) -> None:
        assert len(EXPECTED_CO_RA_ORPHAN_IDS) == 10

    def test_co_statewide_geom_id_value(self) -> None:
        assert _CO_STATEWIDE_GEOM_ID == "CO-STATEWIDE-geom"

    def test_binding_count_guard_band_is_tuple_of_two_ints(self) -> None:
        lo, hi = _BINDING_COUNT_GUARD_BAND
        assert isinstance(lo, int)
        assert isinstance(hi, int)
        assert lo < hi


# ---------------------------------------------------------------------------
# TestBuildRegulationReportingLinks (FIX 1)
# ---------------------------------------------------------------------------


class TestBuildRegulationReportingLinks:
    """Tests for _build_regulation_reporting_links (FIX 1)."""

    def _make_bear_rr(self, jurisdiction_code: str = "CO-GMU-1") -> RegulationRecord:
        return _make_reg_record(jurisdiction_code=jurisdiction_code, species_group="bear")

    def _make_deer_rr(self, jurisdiction_code: str = "CO-GMU-1") -> RegulationRecord:
        return _make_reg_record(jurisdiction_code=jurisdiction_code, species_group="mule_deer")

    def test_empty_obligations_raises(self) -> None:
        """Guard A: empty obligations list → raises naming S06.9."""
        rr = self._make_bear_rr()
        with pytest.raises(RuntimeError, match="no CO reporting_obligation rows found"):
            _build_regulation_reporting_links([rr], [])

    def test_no_bear_reg_records_raises(self) -> None:
        """Guard B: no bear species_group → raises naming S06.6."""
        deer_rr = self._make_deer_rr()
        with pytest.raises(RuntimeError, match="no CO bear regulation_records found"):
            _build_regulation_reporting_links(
                [deer_rr], [("co-bear-mandatory-check-5day-statewide", None)]
            )

    def test_non_co_bear_obligation_id_raises(self) -> None:
        """Guard C: non-'co-bear-' obligation id → raises naming the id."""
        rr = self._make_bear_rr()
        with pytest.raises(RuntimeError, match="unexpected CO reporting_obligation"):
            _build_regulation_reporting_links(
                [rr], [("co-elk-mandatory-report-statewide", None)]
            )

    def test_regional_bear_obligation_raises(self) -> None:
        """Guard C: bear obligation with non-null applies_to_regions → raises.

        FIX B: a future regional bear obligation (e.g. applies_to_regions=["R7"])
        must not be silently fanned out to ALL bear reg_records. Guard C now
        checks both the id prefix AND applies_to_regions.
        """
        rr = self._make_bear_rr()
        with pytest.raises(RuntimeError, match="unexpected CO reporting_obligation"):
            _build_regulation_reporting_links(
                [rr],
                [("co-bear-region-7-tooth-submission", ["R7"])],
            )

    def test_second_statewide_bear_obligation_raises(self) -> None:
        """Guard A2: a second statewide bear obligation → raises (exact-count lock).

        Both rows pass Guard C (co-bear- + statewide) and the structural invariant
        scales with the obligation count, so a second obligation would otherwise
        silently double the link set. The exact-count guard (mirroring S06.9's
        (1,1) band) fails loud so a new CPW obligation is a reviewed change.
        """
        rr = self._make_bear_rr()
        with pytest.raises(RuntimeError, match="expected exactly 1 CO"):
            _build_regulation_reporting_links(
                [rr],
                [
                    ("co-bear-mandatory-check-5day-statewide", None),
                    ("co-bear-second-statewide-obligation", None),
                ],
            )

    def test_one_obligation_one_bear_rr_produces_one_link(self) -> None:
        """1 STATEWIDE bear obligation × 1 bear reg_record → 1 link with correct fields."""
        rr = self._make_bear_rr(jurisdiction_code="CO-GMU-5")
        ob_id = "co-bear-mandatory-check-5day-statewide"
        result = _build_regulation_reporting_links([rr], [(ob_id, None)])
        assert len(result) == 1
        link = result[0]
        assert isinstance(link, RegulationReporting)
        assert link.state == "US-CO"
        assert link.jurisdiction_code == "CO-GMU-5"
        assert link.species_group == "bear"
        assert link.license_year == 2026
        assert link.reporting_obligation_id == ob_id

    def test_one_obligation_n_bear_rrs_produces_n_links(self) -> None:
        """1 STATEWIDE obligation × N bear reg_records → N links."""
        rrs = [
            self._make_bear_rr(f"CO-GMU-{i}") for i in range(1, 6)
        ]
        ob_id = "co-bear-mandatory-check-5day-statewide"
        result = _build_regulation_reporting_links(rrs, [(ob_id, None)])
        assert len(result) == 5
        obligation_ids_in_result = {lnk.reporting_obligation_id for lnk in result}
        assert obligation_ids_in_result == {ob_id}

    def test_non_bear_reg_records_excluded_from_links(self) -> None:
        """Only bear reg_records produce links; deer/elk/pronghorn are excluded."""
        bear_rr = self._make_bear_rr("CO-GMU-10")
        deer_rr = self._make_deer_rr("CO-GMU-10")
        elk_rr = _make_reg_record(jurisdiction_code="CO-GMU-10", species_group="elk")
        ob_id = "co-bear-mandatory-check-5day-statewide"
        result = _build_regulation_reporting_links(
            [bear_rr, deer_rr, elk_rr], [(ob_id, None)]
        )
        # Only 1 link — for the bear reg_record
        assert len(result) == 1
        assert result[0].species_group == "bear"

    def test_duplicate_composite_pk_raises(self) -> None:
        """Guard D: two identical bear reg_records → duplicate PK → raises."""
        rr1 = self._make_bear_rr("CO-GMU-1")
        rr2 = self._make_bear_rr("CO-GMU-1")  # same jurisdiction_code + species
        ob_id = "co-bear-mandatory-check-5day-statewide"
        with pytest.raises(RuntimeError, match="duplicate regulation_reporting composite PK"):
            _build_regulation_reporting_links([rr1, rr2], [(ob_id, None)])

    def test_structural_invariant_passes(self) -> None:
        """len(links) == len(obligations) × bear_rr_count."""
        bear_rrs = [self._make_bear_rr(f"CO-GMU-{i}") for i in range(1, 4)]
        ob_id = "co-bear-mandatory-check-5day-statewide"
        links = _build_regulation_reporting_links(bear_rrs, [(ob_id, None)])
        # 1 obligation × 3 bear rrs = 3 links
        assert len(links) == 3
        _assert_regulation_reporting_structural_invariant(links, [(ob_id, None)], 3)

    def test_structural_invariant_fails_raises(self) -> None:
        """_assert_regulation_reporting_structural_invariant raises on mismatch."""
        # 1 link but claim 3 obligations × 2 bear = 6 expected
        dummy_ob_id = "co-bear-mandatory-check-5day-statewide"
        links = [
            RegulationReporting(
                state="US-CO",
                jurisdiction_code="CO-GMU-1",
                species_group="bear",
                license_year=2026,
                reporting_obligation_id=dummy_ob_id,
            ),
        ]
        with pytest.raises(RuntimeError, match="structural invariant violated"):
            _assert_regulation_reporting_structural_invariant(
                links, [(dummy_ob_id, None)] * 3, 2
            )

    def test_co_bear_species_group_constant(self) -> None:
        """_CO_BEAR_SPECIES_GROUP is 'bear' (the DB value, not 'black_bear')."""
        assert _CO_BEAR_SPECIES_GROUP == "bear"


# ---------------------------------------------------------------------------
# TestQueryCoReportingObligations (FIX B)
# ---------------------------------------------------------------------------


class TestQueryCoReportingObligations:
    """Tests for _query_co_reporting_obligations (renamed from _query_co_reporting_obligation_ids).

    FIX B: function now returns list[tuple[str, list[str] | None]] (id, applies_to_regions).
    """

    def test_returns_id_and_null_regions_tuple(self) -> None:
        """STATEWIDE obligation (applies_to_regions=None DB value) → (id, None) tuple."""
        conn = _make_mock_conn(rows=[
            ("co-bear-mandatory-check-5day-statewide", None),
        ])
        result = _query_co_reporting_obligations(conn)
        assert result == [("co-bear-mandatory-check-5day-statewide", None)]

    def test_returns_id_and_regions_list_tuple(self) -> None:
        """Regional obligation (applies_to_regions non-null) → (id, [...]) tuple."""
        conn = _make_mock_conn(rows=[
            ("co-bear-region-7-tooth-submission", ["R7"]),
        ])
        result = _query_co_reporting_obligations(conn)
        assert result == [("co-bear-region-7-tooth-submission", ["R7"])]

    def test_returns_multiple_rows_preserving_order(self) -> None:
        """Multiple rows returned in ORDER BY id order as tuples."""
        conn = _make_mock_conn(rows=[
            ("co-bear-mandatory-check-5day-statewide", None),
            ("co-bear-other-obligation", None),
        ])
        result = _query_co_reporting_obligations(conn)
        assert result == [
            ("co-bear-mandatory-check-5day-statewide", None),
            ("co-bear-other-obligation", None),
        ]

    def test_returns_empty_list_when_no_rows(self) -> None:
        conn = _make_mock_conn(rows=[])
        result = _query_co_reporting_obligations(conn)
        assert result == []

    def test_sql_contains_applies_to_regions(self) -> None:
        """FIX B: SQL now selects applies_to_regions in addition to id."""
        conn = _make_mock_conn(rows=[])
        _query_co_reporting_obligations(conn)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "applies_to_regions" in sql

    def test_sql_contains_reporting_obligation(self) -> None:
        conn = _make_mock_conn(rows=[])
        _query_co_reporting_obligations(conn)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "reporting_obligation" in sql

    def test_sql_contains_co_like_filter(self) -> None:
        conn = _make_mock_conn(rows=[])
        _query_co_reporting_obligations(conn)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "co-%" in sql

    def test_sql_contains_order_by_id(self) -> None:
        conn = _make_mock_conn(rows=[])
        _query_co_reporting_obligations(conn)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "ORDER BY id" in sql


# ---------------------------------------------------------------------------
# TestMainRegulationReporting (FIX 1 integration in main())
# ---------------------------------------------------------------------------


class TestMainRegulationReporting:
    """dry-run + write-path tests confirming regulation_reporting integration."""

    def test_dry_run_logs_both_counts(self, caplog: pytest.LogCaptureFixture) -> None:
        """--dry-run logs both jurisdiction_binding count and regulation_reporting count."""
        bear_rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="bear")
        ob_id = "co-bear-mandatory-check-5day-statewide"
        binding = JurisdictionBinding(
            id="US-CO-CO-GMU-1-bear-2026-primary_unit-CO-GMU-1-geom",
            regulation_record_state="US-CO",
            regulation_record_jurisdiction_code="CO-GMU-1",
            regulation_record_species_group="bear",
            regulation_record_license_year=2026,
            geometry_id="CO-GMU-1-geom",
            role="primary_unit",
            verbatim_rule=None,
            source=_make_gis_source(),
        )

        with (
            patch("states.colorado.load_jurisdiction_bindings._load_overlay_fixture",
                  return_value=[]),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_all_colorado_regulation_records",
                return_value=[bear_rr],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_geometry_sources",
                return_value={"CO-GMU-1-geom": _make_gis_source()},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_statewide_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_overlay_bindings_co",
                return_value=[binding],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_no_hunt_zone_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_co_reporting_obligations",
                return_value=[(ob_id, None)],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._assert_binding_count_within_guard",
            ),
            patch("states.colorado.load_jurisdiction_bindings.db.connect") as mock_db_connect,
        ):
            mock_conn_ctx = MagicMock()
            mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn_ctx)
            mock_conn_ctx.__exit__ = MagicMock(return_value=False)
            mock_db_connect.return_value = mock_conn_ctx

            with caplog.at_level(logging.INFO):
                result = mod.main(["--dry-run"])

        assert result == 0
        # The dry-run log should mention both counts
        dry_run_logs = [r.message for r in caplog.records if "Dry-run" in r.message or "dry-run" in r.message.lower()]
        combined_log = " ".join(dry_run_logs)
        # Should mention jurisdiction_binding and regulation_reporting counts
        assert "1" in combined_log  # 1 binding
        assert "regulation_reporting" in combined_log or "link" in combined_log

    def test_write_path_calls_write_regulation_reporting(self) -> None:
        """Phase 3 write: db.write_regulation_reporting is called for each link."""
        bear_rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="bear")
        ob_id = "co-bear-mandatory-check-5day-statewide"
        binding = JurisdictionBinding(
            id="US-CO-CO-GMU-1-bear-2026-primary_unit-CO-GMU-1-geom",
            regulation_record_state="US-CO",
            regulation_record_jurisdiction_code="CO-GMU-1",
            regulation_record_species_group="bear",
            regulation_record_license_year=2026,
            geometry_id="CO-GMU-1-geom",
            role="primary_unit",
            verbatim_rule=None,
            source=_make_gis_source(),
        )

        with (
            patch("states.colorado.load_jurisdiction_bindings._load_overlay_fixture",
                  return_value=[]),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_all_colorado_regulation_records",
                return_value=[bear_rr],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_geometry_sources",
                return_value={"CO-GMU-1-geom": _make_gis_source()},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_statewide_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_overlay_bindings_co",
                return_value=[binding],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_no_hunt_zone_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_co_reporting_obligations",
                return_value=[(ob_id, None)],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._assert_binding_count_within_guard",
            ),
            patch("states.colorado.load_jurisdiction_bindings.db.upsert_jurisdiction_binding"),
            patch("states.colorado.load_jurisdiction_bindings.db.write_regulation_reporting") as mock_write_rr,
            patch("states.colorado.load_jurisdiction_bindings.db.connect") as mock_db_connect,
        ):
            mock_conn_ctx = MagicMock()
            mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn_ctx)
            mock_conn_ctx.__exit__ = MagicMock(return_value=False)
            mock_db_connect.return_value = mock_conn_ctx

            result = mod.main([])

        assert result == 0
        # write_regulation_reporting should have been called once (1 obligation × 1 bear rr)
        assert mock_write_rr.call_count == 1


# ---------------------------------------------------------------------------
# TestFix2StatewideSourceConditional (FIX 2)
# ---------------------------------------------------------------------------


class TestFix2StatewideSourceConditional:
    """FIX 2: CO-STATEWIDE-geom not added to candidate_geom_ids when statewide_rrs is empty."""

    def test_main_succeeds_without_co_statewide_geom_in_source_lookup(self) -> None:
        """When statewide_rrs is empty, source_lookup need NOT contain CO-STATEWIDE-geom."""
        gmu_rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="mule_deer")
        ob_id = "co-bear-mandatory-check-5day-statewide"
        # Source lookup deliberately does NOT include CO-STATEWIDE-geom
        source_lookup_without_statewide = {
            "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
        }
        bear_rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="bear")
        binding = JurisdictionBinding(
            id="US-CO-CO-GMU-1-mule_deer-2026-primary_unit-CO-GMU-1-geom",
            regulation_record_state="US-CO",
            regulation_record_jurisdiction_code="CO-GMU-1",
            regulation_record_species_group="mule_deer",
            regulation_record_license_year=2026,
            geometry_id="CO-GMU-1-geom",
            role="primary_unit",
            verbatim_rule=None,
            source=_make_gis_source(),
        )

        with (
            patch("states.colorado.load_jurisdiction_bindings._load_overlay_fixture",
                  return_value=[]),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_all_colorado_regulation_records",
                return_value=[gmu_rr, bear_rr],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_geometry_sources",
                return_value=source_lookup_without_statewide,
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_statewide_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_overlay_bindings_co",
                return_value=[binding],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_no_hunt_zone_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_co_reporting_obligations",
                return_value=[(ob_id, None)],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._assert_binding_count_within_guard",
            ),
            patch("states.colorado.load_jurisdiction_bindings.db.connect") as mock_db_connect,
        ):
            mock_conn_ctx = MagicMock()
            mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn_ctx)
            mock_conn_ctx.__exit__ = MagicMock(return_value=False)
            mock_db_connect.return_value = mock_conn_ctx

            # Should NOT raise — CO-STATEWIDE-geom is NOT required when statewide_rrs is empty
            result = mod.main(["--dry-run"])
        assert result == 0

    def test_fetch_geometry_sources_not_called_with_co_statewide_geom_when_no_statewide_rrs(
        self,
    ) -> None:
        """_fetch_geometry_sources must NOT receive _CO_STATEWIDE_GEOM_ID when statewide_rrs is empty."""
        gmu_rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="mule_deer")
        bear_rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="bear")
        ob_id = "co-bear-mandatory-check-5day-statewide"
        captured_geom_ids: list[set[str]] = []

        def capture_fetch(conn: Any, geom_ids: set[str]) -> dict[str, SourceCitation]:
            captured_geom_ids.append(set(geom_ids))
            return {gid: _make_gis_source(gid) for gid in geom_ids}

        binding = JurisdictionBinding(
            id="US-CO-CO-GMU-1-mule_deer-2026-primary_unit-CO-GMU-1-geom",
            regulation_record_state="US-CO",
            regulation_record_jurisdiction_code="CO-GMU-1",
            regulation_record_species_group="mule_deer",
            regulation_record_license_year=2026,
            geometry_id="CO-GMU-1-geom",
            role="primary_unit",
            verbatim_rule=None,
            source=_make_gis_source(),
        )

        with (
            patch("states.colorado.load_jurisdiction_bindings._load_overlay_fixture",
                  return_value=[]),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_all_colorado_regulation_records",
                return_value=[gmu_rr, bear_rr],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_geometry_sources",
                side_effect=capture_fetch,
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_statewide_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_overlay_bindings_co",
                return_value=[binding],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._build_no_hunt_zone_bindings_co",
                return_value=[],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._query_co_reporting_obligations",
                return_value=[(ob_id, None)],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings._assert_binding_count_within_guard",
            ),
            patch("states.colorado.load_jurisdiction_bindings.db.connect") as mock_db_connect,
        ):
            mock_conn_ctx = MagicMock()
            mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn_ctx)
            mock_conn_ctx.__exit__ = MagicMock(return_value=False)
            mock_db_connect.return_value = mock_conn_ctx
            mod.main(["--dry-run"])

        assert captured_geom_ids, "Expected _fetch_geometry_sources to be called"
        assert _CO_STATEWIDE_GEOM_ID not in captured_geom_ids[0], (
            f"CO-STATEWIDE-geom must NOT be in candidate_geom_ids when statewide_rrs "
            f"is empty (FIX 2). Got: {captured_geom_ids[0]!r}"
        )


# ---------------------------------------------------------------------------
# TestFix3MalformedRegRecordSource (FIX 3)
# ---------------------------------------------------------------------------


class TestFix3MalformedRegRecordSource:
    """FIX 3: malformed source jsonb in _query_all_colorado_regulation_records raises
    RuntimeError naming jurisdiction_code."""

    def _rr_tuple(
        self,
        jurisdiction_code: str = "CO-GMU-1",
        species_group: str = "mule_deer",
        source_dict: dict | None = None,
    ) -> tuple[object, ...]:
        import datetime
        if source_dict is None:
            source_dict = {
                "id": "co-cpw-big-game-2026-brochure",
                "agency": "Colorado Parks and Wildlife",
                "title": "2026 Colorado Big Game",
                "url": "https://spl.cde.state.co.us/brochure.pdf",
                "publication_date": "2026-03-04",
                "document_type": "annual_regulations",
            }
        return (
            "US-CO",
            jurisdiction_code,
            species_group,
            2026,
            2,
            "high",
            [],
            datetime.datetime(2026, 6, 1),
            source_dict,
        )

    def test_malformed_source_raises_naming_jurisdiction_code(self) -> None:
        """Bad source jsonb raises RuntimeError that names the failing jurisdiction_code."""
        bad_tuple = self._rr_tuple(
            jurisdiction_code="CO-GMU-42",
            species_group="elk",
            source_dict={"bad": "shape", "missing_required_fields": True},
        )
        conn = _make_mock_conn(rows=[bad_tuple])
        with pytest.raises(RuntimeError, match="CO-GMU-42"):
            _query_all_colorado_regulation_records(conn)

    def test_malformed_source_raises_naming_species_group(self) -> None:
        """RuntimeError message also names the species_group for context."""
        bad_tuple = self._rr_tuple(
            jurisdiction_code="CO-GMU-7",
            species_group="elk",
            source_dict={"not": "a_source_citation"},
        )
        conn = _make_mock_conn(rows=[bad_tuple])
        with pytest.raises(RuntimeError, match="elk"):
            _query_all_colorado_regulation_records(conn)

    def test_valid_source_does_not_raise(self) -> None:
        """A well-formed source dict parses cleanly."""
        good_tuple = self._rr_tuple(jurisdiction_code="CO-GMU-5")
        conn = _make_mock_conn(rows=[good_tuple])
        # Should not raise
        records = _query_all_colorado_regulation_records(conn)
        assert len(records) == 1
        assert records[0].jurisdiction_code == "CO-GMU-5"


# ---------------------------------------------------------------------------
# TestFix4NoRegRecordsWarning (FIX 4)
# ---------------------------------------------------------------------------


class TestFix4NoRegRecordsWarning:
    """FIX 4: nearby GMU with no CO regulation_records emits WARNING, no raise.

    FIX A (Guard 20) adds a per-zone zero-bindings guard: if ALL nearby GMUs
    lack reg_records, raises RuntimeError. The per-GMU WARNING still fires for
    the PARTIAL case (some GMUs have reg_records, some do not).
    """

    def test_empty_rrs_for_nearby_gmu_emits_warning_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """PARTIAL case: one nearby GMU has reg_records, one does not.

        FIX A: zone still produces ≥1 binding (no raise), but the empty GMU
        emits a per-GMU WARNING. This is the partial case vs. the all-empty
        case (Guard 20) tested in TestBuildNoHuntZoneBindings.
        """
        # CO-GMU-1 has the reg_record; CO-GMU-2 is returned as nearby but has no rr
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="mule_deer")
        source_lookup = {
            _RMNP_GEOM_ID: _make_gis_source(_RMNP_GEOM_ID),
            "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
            "CO-GMU-2-geom": _make_gis_source("CO-GMU-2-geom"),
        }
        conn = MagicMock()

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={_RMNP_GEOM_ID: "MULTIPOLYGON EMPTY"},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                # Two nearby GMUs: CO-GMU-1 (has rr) + CO-GMU-2 (no rr)
                return_value=["CO-GMU-1-geom", "CO-GMU-2-geom"],
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_RMNP_GEOM_ID}),
            ),
            caplog.at_level(logging.WARNING, logger="states.colorado.load_jurisdiction_bindings"),
        ):
            # Does NOT raise — CO-GMU-1 provides ≥1 binding; zone is visible.
            result = _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)

        # Zone produces ≥1 binding (from CO-GMU-1)
        zone_bindings = [b for b in result if b.geometry_id == _RMNP_GEOM_ID]
        assert len(zone_bindings) >= 1, (
            "Zone must produce ≥1 binding when at least one nearby GMU has reg_records"
        )

        # WARNING must have been emitted for the empty GMU (CO-GMU-2)
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "CO-GMU-2-geom" in msg and "no CO regulation_records" in msg
            for msg in warning_messages
        ), (
            f"Expected a WARNING about CO-GMU-2-geom having no regulation_records. "
            f"Got warnings: {warning_messages!r}"
        )

    def test_nearby_gmu_with_rrs_does_not_emit_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A nearby GMU that has reg_records must NOT emit the empty-fan-out warning."""
        rr = _make_reg_record(jurisdiction_code="CO-GMU-1", species_group="mule_deer")
        source_lookup = {
            _RMNP_GEOM_ID: _make_gis_source(_RMNP_GEOM_ID),
            "CO-GMU-1-geom": _make_gis_source("CO-GMU-1-geom"),
        }
        conn = MagicMock()

        with (
            patch(
                "states.colorado.load_jurisdiction_bindings._fetch_zone_wkts",
                return_value={_RMNP_GEOM_ID: "MULTIPOLYGON EMPTY"},
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.query_nearby_gmus_for_zone",
                return_value=["CO-GMU-1-geom"],  # has a matching rr
            ),
            patch(
                "states.colorado.load_jurisdiction_bindings.EXPECTED_CO_RA_ORPHAN_IDS",
                frozenset({_RMNP_GEOM_ID}),
            ),
            caplog.at_level(logging.WARNING, logger="states.colorado.load_jurisdiction_bindings"),
        ):
            result = _build_no_hunt_zone_bindings_co(conn, [rr], source_lookup)

        # There should be 1 binding (rr matched CO-GMU-1-geom)
        assert len(result) == 1

        # No empty-fan-out WARNING should have been emitted
        no_rr_warnings = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING and "no CO regulation_records" in r.message
        ]
        assert len(no_rr_warnings) == 0, (
            f"Unexpected warning for a GMU that has reg_records: {no_rr_warnings!r}"
        )
