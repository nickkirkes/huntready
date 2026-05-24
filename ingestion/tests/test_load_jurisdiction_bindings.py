"""Unit tests for ``ingestion/states/montana/load_jurisdiction_bindings.py``.

Coverage (T1 — AST guard; T2 — overlay fixture loader):
- TestNoLibImports       — state-agnostic-clean AST guard
- TestLoadOverlayFixture — _load_overlay_fixture happy-path + error cases
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Shared path constants
# ---------------------------------------------------------------------------

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "states" / "montana" / "load_jurisdiction_bindings.py"
)

# ---------------------------------------------------------------------------
# TestNoLibImports
# ---------------------------------------------------------------------------

# Sibling-state imports that are explicitly permitted in this adapter.
# S03.10 is the only adapter that imports from sibling Montana modules (the
# id-format constant from load_regulation_records + the orphan-id allowlist
# from build_overlay_fixture).  The S03.9 pattern blocks all cross-adapter
# imports; here we whitelist the two known dependencies.
_PERMITTED_SIBLING_MODULES: frozenset[str] = frozenset({
    "states.montana.load_regulation_records",
    "states.montana.build_overlay_fixture",
})


class TestNoLibImports:
    """State-agnostic-clean AST guard (bidirectional).

    ``load_jurisdiction_bindings.py`` is a state adapter — it may import from
    ``ingestion.lib.*`` and from the two explicitly-permitted sibling Montana
    modules.  Any other cross-adapter or cross-state import is forbidden.
    """

    def _parse_adapter(self) -> ast.Module:
        return ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))

    def test_no_state_adapter_imports_lib_internals(self) -> None:
        """No imports from other state adapters except the two whitelisted siblings."""
        tree = self._parse_adapter()
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    # Block any import from ingestion.states.* that isn't in
                    # the permitted sibling list
                    if "states." in module and module not in _PERMITTED_SIBLING_MODULES:
                        violations.append(
                            f"line {node.lineno}: forbidden cross-adapter import "
                            f"from {module!r}"
                        )
                    # Block cross-state imports (belt-and-suspenders)
                    if "states.colorado" in module or "states.wyoming" in module:
                        violations.append(
                            f"line {node.lineno}: cross-state import from {module!r}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.name or ""
                        if "states." in name and name not in _PERMITTED_SIBLING_MODULES:
                            violations.append(
                                f"line {node.lineno}: forbidden cross-adapter import "
                                f"of {name!r}"
                            )
        assert not violations, (
            "load_jurisdiction_bindings.py has forbidden cross-adapter imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_no_relative_imports(self) -> None:
        """No relative imports (``from .`` or ``from ..``)."""
        tree = self._parse_adapter()
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    violations.append(
                        f"line {node.lineno}: relative import (level={node.level})"
                    )
        assert not violations, (
            "load_jurisdiction_bindings.py uses relative imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_only_lib_db_public_api_imported(self) -> None:
        """All ``from ingestion.lib.db import`` must use only public names."""
        tree = self._parse_adapter()
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "ingestion.lib.db":
                    for alias in node.names:
                        if alias.name.startswith("_"):
                            violations.append(
                                f"line {node.lineno}: private name {alias.name!r} "
                                f"imported from ingestion.lib.db"
                            )
        assert not violations, (
            "load_jurisdiction_bindings.py leaks private ingestion.lib.db names:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# TestLoadOverlayFixture (T2)
# ---------------------------------------------------------------------------

from states.montana.load_jurisdiction_bindings import _load_overlay_fixture  # noqa: E402
import states.montana.load_jurisdiction_bindings as adapter_module  # noqa: E402


class TestLoadOverlayFixture:
    def test_loads_real_fixture_with_required_keys(self) -> None:
        """Happy-path: real fixture loads, ≥586 rows, row 0 has all 6 required keys."""
        rows = _load_overlay_fixture(adapter_module._OVERLAY_FIXTURE_PATH)
        assert len(rows) >= 586, f"expected ≥586 rows, got {len(rows)}"
        row0 = rows[0]
        for key in ("parent_geometry_id", "child_geometry_id", "parent_kind",
                    "child_kind", "relationship", "role_for_e03"):
            assert key in row0, f"row 0 missing key {key!r}"

    def test_distinct_role_for_e03_values_match_fixture(self) -> None:
        """Fixture should contain only the 4 known role_for_e03 values."""
        rows = _load_overlay_fixture(adapter_module._OVERLAY_FIXTURE_PATH)
        roles = {row["role_for_e03"] for row in rows}
        expected = {"primary_unit", "portion", "restricted_area", "cwd_management_zone"}
        assert roles == expected, f"unexpected role_for_e03 values: {roles ^ expected}"

    def test_malformed_top_level_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"wrong": "shape"}))
        with pytest.raises(RuntimeError, match="top-level"):
            _load_overlay_fixture(bad)

    def test_row_not_dict_raises_with_index(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(["not-a-dict"]))
        with pytest.raises(RuntimeError, match="row 0 is not a dict"):
            _load_overlay_fixture(bad)

    def test_missing_key_raises_with_index_and_key(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps([{
            "parent_geometry_id": "p",
            "child_geometry_id": "c",
            "parent_kind": "x",
            "child_kind": "y",
            "relationship": "z",
            # missing role_for_e03
        }]))
        with pytest.raises(RuntimeError, match="row 0.*missing.*role_for_e03"):
            _load_overlay_fixture(bad)


# ---------------------------------------------------------------------------
# TestIsBindingEligible (T3)
# ---------------------------------------------------------------------------

from ingestion.lib.schema import RegulationRecord, SourceCitation  # noqa: E402
from states.montana.load_jurisdiction_bindings import (  # noqa: E402
    _derive_parent_geometry_id,
    is_binding_eligible,
)


def _row(
    parent_gid: str,
    child_gid: str,
    role_for_e03: str = "portion",
    child_kind: str = "portion",
    parent_kind: str = "hunting_district",
    relationship: str = "contains",
) -> dict:  # type: ignore[type-arg]  # returns dict, _OverlayRow is duck-typed at runtime
    return {
        "parent_geometry_id": parent_gid,
        "child_geometry_id": child_gid,
        "parent_kind": parent_kind,
        "child_kind": child_kind,
        "relationship": relationship,
        "role_for_e03": role_for_e03,
    }


class TestIsBindingEligible:
    # ----- Step A: self-row short-circuit (the C3 regression coverage) -----

    def test_elk_accepts_self_row(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-HD-deer-elk-lion-262-geom",
            role_for_e03="primary_unit",
            child_kind="hunting_district",
        )
        assert is_binding_eligible("elk", "MT-HD-deer-elk-lion-262-geom", row) is True

    def test_mule_deer_accepts_self_row(self) -> None:
        """C3 regression: mule_deer reg on MT-HD-deer-elk-lion-N-geom must
        accept its self-row even though child_gid doesn't start with MT-HD-mule-deer-."""
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-HD-deer-elk-lion-262-geom",
            role_for_e03="primary_unit",
            child_kind="hunting_district",
        )
        assert is_binding_eligible("mule_deer", "MT-HD-deer-elk-lion-262-geom", row) is True

    def test_whitetail_accepts_self_row(self) -> None:
        """C3 regression: same as above for whitetail."""
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-HD-deer-elk-lion-262-geom",
            role_for_e03="primary_unit",
            child_kind="hunting_district",
        )
        assert is_binding_eligible("whitetail", "MT-HD-deer-elk-lion-262-geom", row) is True

    def test_bear_accepts_self_row(self) -> None:
        row = _row(
            "MT-HD-bear-101-geom",
            "MT-HD-bear-101-geom",
            role_for_e03="primary_unit",
            child_kind="hunting_district",
        )
        assert is_binding_eligible("bear", "MT-HD-bear-101-geom", row) is True

    def test_pronghorn_accepts_self_row(self) -> None:
        row = _row(
            "MT-HD-antelope-690-geom",
            "MT-HD-antelope-690-geom",
            role_for_e03="primary_unit",
            child_kind="hunting_district",
        )
        assert is_binding_eligible("pronghorn", "MT-HD-antelope-690-geom", row) is True

    # ----- Step C: portion acceptance per species -----

    def test_elk_accepts_mt_hd_elk_portion(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-HD-elk-262-portion-elPt7-geom",
            role_for_e03="portion",
        )
        assert is_binding_eligible("elk", "MT-HD-deer-elk-lion-262-geom", row) is True

    def test_mule_deer_rejects_mt_hd_elk_portion(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-HD-elk-262-portion-elPt7-geom",
            role_for_e03="portion",
        )
        assert is_binding_eligible("mule_deer", "MT-HD-deer-elk-lion-262-geom", row) is False

    def test_whitetail_accepts_mt_hd_whitetail_portion(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-310-geom",
            "MT-HD-whitetail-310-portion-wtPt7-geom",
            role_for_e03="portion",
        )
        assert is_binding_eligible("whitetail", "MT-HD-deer-elk-lion-310-geom", row) is True

    def test_whitetail_rejects_mt_hd_elk_portion(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-HD-elk-262-portion-elPt7-geom",
            role_for_e03="portion",
        )
        assert is_binding_eligible("whitetail", "MT-HD-deer-elk-lion-262-geom", row) is False

    def test_pronghorn_accepts_antelope_portion_via_kind_disambiguation(self) -> None:
        row = _row(
            "MT-HD-antelope-311-geom",
            "MT-HD-antelope-311-portion-foo-geom",
            role_for_e03="portion",
            child_kind="portion",
        )
        assert is_binding_eligible("pronghorn", "MT-HD-antelope-311-geom", row) is True

    def test_pronghorn_rejects_antelope_hd_child_when_kind_is_hunting_district(self) -> None:
        """Pronghorn portions require child_kind='portion'; a child that shares the
        MT-HD-antelope- prefix but is a hunting_district (non-self-row) must be rejected."""
        row = _row(
            "MT-HD-antelope-311-geom",
            "MT-HD-antelope-312-geom",  # different HD — NOT the self-row
            role_for_e03="portion",
            child_kind="hunting_district",  # not a portion
        )
        assert is_binding_eligible("pronghorn", "MT-HD-antelope-311-geom", row) is False

    # ----- Step C: restricted_area discriminators -----

    def test_elk_accepts_mt_restricted_bigame(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-restricted-bigame-some-zone-geom",
            role_for_e03="restricted_area",
            child_kind="restricted_area",
        )
        assert is_binding_eligible("elk", "MT-HD-deer-elk-lion-262-geom", row) is True

    def test_elk_accepts_mt_restricted_elk(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-restricted-elk-some-zone-geom",
            role_for_e03="restricted_area",
            child_kind="restricted_area",
        )
        assert is_binding_eligible("elk", "MT-HD-deer-elk-lion-262-geom", row) is True

    def test_mule_deer_rejects_mt_restricted_elk(self) -> None:
        """Cross-species filter: mule_deer must NOT bind to elk-only restricted area."""
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-restricted-elk-some-zone-geom",
            role_for_e03="restricted_area",
            child_kind="restricted_area",
        )
        assert is_binding_eligible("mule_deer", "MT-HD-deer-elk-lion-262-geom", row) is False

    def test_bear_rejects_mt_restricted_elk(self) -> None:
        row = _row(
            "MT-HD-bear-101-geom",
            "MT-restricted-elk-some-zone-geom",
            role_for_e03="restricted_area",
            child_kind="restricted_area",
        )
        assert is_binding_eligible("bear", "MT-HD-bear-101-geom", row) is False

    def test_pronghorn_accepts_mt_restricted_bigame(self) -> None:
        row = _row(
            "MT-HD-antelope-690-geom",
            "MT-restricted-bigame-some-zone-geom",
            role_for_e03="restricted_area",
            child_kind="restricted_area",
        )
        assert is_binding_eligible("pronghorn", "MT-HD-antelope-690-geom", row) is True

    # ----- Step C: CWD acceptance -----

    def test_elk_accepts_cwd_zone(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-103-geom",
            "MT-CWD-zone-libby-geom",
            role_for_e03="cwd_management_zone",
            child_kind="cwd_zone",
        )
        assert is_binding_eligible("elk", "MT-HD-deer-elk-lion-103-geom", row) is True

    def test_mule_deer_accepts_cwd_zone(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-103-geom",
            "MT-CWD-zone-libby-geom",
            role_for_e03="cwd_management_zone",
            child_kind="cwd_zone",
        )
        assert is_binding_eligible("mule_deer", "MT-HD-deer-elk-lion-103-geom", row) is True

    def test_pronghorn_rejects_cwd_zone(self) -> None:
        row = _row(
            "MT-HD-antelope-690-geom",
            "MT-CWD-zone-libby-geom",
            role_for_e03="cwd_management_zone",
            child_kind="cwd_zone",
        )
        assert is_binding_eligible("pronghorn", "MT-HD-antelope-690-geom", row) is False

    def test_bear_rejects_cwd_zone(self) -> None:
        row = _row(
            "MT-HD-bear-101-geom",
            "MT-CWD-zone-libby-geom",
            role_for_e03="cwd_management_zone",
            child_kind="cwd_zone",
        )
        assert is_binding_eligible("bear", "MT-HD-bear-101-geom", row) is False

    # ----- Step B: defensive checks -----

    def test_unknown_species_group_fails_loud(self) -> None:
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-HD-elk-262-portion-elPt7-geom",
            role_for_e03="portion",
        )
        with pytest.raises(RuntimeError, match="unhandled species_group"):
            is_binding_eligible("mountain_goat", "MT-HD-deer-elk-lion-262-geom", row)

    def test_wrong_parent_prefix_for_species_returns_false(self) -> None:
        """Defensive Step B: elk reg_record with wrong-shaped parent geometry id."""
        row = _row(
            "MT-HD-bear-101-geom",
            "MT-HD-elk-101-portion-x-geom",
            role_for_e03="portion",
        )
        assert is_binding_eligible("elk", "MT-HD-bear-101-geom", row) is False

    def test_unknown_role_for_e03_fails_loud(self) -> None:
        """is_binding_eligible must raise on unknown role_for_e03, not silently
        skip — review-triad silent-failure-hunter finding INFO-I1.  The
        defensive `_VALID_ROLE_FOR_E03` gate in `_build_overlay_bindings` is
        the right place for known-but-not-implemented roles to be accepted
        silently; this public function should be independently loud so a future
        direct caller (test utility, REPL investigation) doesn't silently
        drop bindings."""
        row = _row(
            "MT-HD-deer-elk-lion-262-geom",
            "MT-HD-elk-262-portion-x-geom",
            role_for_e03="unknown_role_value",
        )
        with pytest.raises(RuntimeError, match="unhandled role_for_e03"):
            is_binding_eligible("elk", "MT-HD-deer-elk-lion-262-geom", row)


# ---------------------------------------------------------------------------
# TestDeriveParentGeometryId (T4)
# ---------------------------------------------------------------------------


class TestDeriveParentGeometryId:
    @staticmethod
    def _make_rr(
        jurisdiction_code: str,
        species_group: str = "elk",
    ) -> RegulationRecord:
        """Build a minimal valid RegulationRecord for derivation tests.

        Required fields (frozen=True, extra='forbid'):
          state, jurisdiction_code, species_group, license_year, source, confidence
        """
        return RegulationRecord(
            state="US-MT",
            jurisdiction_code=jurisdiction_code,
            species_group=species_group,
            license_year=2026,
            source=SourceCitation(
                id="test-citation",
                agency="Montana FWP",
                title="Test Title",
                url="https://example.com/test.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
            ),
            confidence="high",
        )

    def test_deer_elk_lion_pattern(self) -> None:
        rr = self._make_rr("MT-HD-deer-elk-lion-262", "elk")
        assert _derive_parent_geometry_id(rr) == "MT-HD-deer-elk-lion-262-geom"

    def test_antelope_pattern(self) -> None:
        rr = self._make_rr("MT-HD-antelope-690", "pronghorn")
        assert _derive_parent_geometry_id(rr) == "MT-HD-antelope-690-geom"

    def test_bear_pattern(self) -> None:
        rr = self._make_rr("MT-HD-bear-101", "bear")
        assert _derive_parent_geometry_id(rr) == "MT-HD-bear-101-geom"

    def test_statewide_antelope_pattern(self) -> None:
        rr = self._make_rr("MT-STATEWIDE-antelope", "pronghorn")
        assert _derive_parent_geometry_id(rr) == "MT-STATEWIDE-geom"

    def test_statewide_bear_pattern(self) -> None:
        rr = self._make_rr("MT-STATEWIDE-bear", "bear")
        assert _derive_parent_geometry_id(rr) == "MT-STATEWIDE-geom"

    def test_unknown_pattern_fails_loud(self) -> None:
        rr = self._make_rr("CO-GMU-50", "elk")
        with pytest.raises(RuntimeError, match="unhandled jurisdiction_code"):
            _derive_parent_geometry_id(rr)


# ---------------------------------------------------------------------------
# TestFetchGeometrySources (T5)
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock  # noqa: E402
from states.montana.load_jurisdiction_bindings import _fetch_geometry_sources  # noqa: E402


def _valid_source_jsonb() -> dict:  # type: ignore[type-arg]
    """Minimal valid SourceCitation jsonb for mocked cursor returns.

    Required fields per schema.SourceCitation (frozen=True, extra='forbid'):
      id, agency, title, url, publication_date, document_type
    Optional: supersedes, page_reference

    Real geometry table stores ArcGIS layer citations with document_type='gis_layer'.
    """
    return {
        "id": "some-source-id",
        "agency": "MT FWP",
        "title": "Montana HD Layer",
        "url": "https://gisservicemt.gov/arcgis/rest/services/example/FeatureServer/0",
        "publication_date": "2026-01-01",
        "document_type": "gis_layer",
    }


class TestFetchGeometrySources:
    def test_happy_path_returns_dict_keyed_by_geometry_id(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [
            ("MT-HD-deer-elk-lion-262-geom", _valid_source_jsonb()),
            ("MT-HD-bear-101-geom", _valid_source_jsonb()),
        ]
        result = _fetch_geometry_sources(
            conn,
            {"MT-HD-deer-elk-lion-262-geom", "MT-HD-bear-101-geom"},
        )
        assert set(result.keys()) == {"MT-HD-deer-elk-lion-262-geom", "MT-HD-bear-101-geom"}
        # confirm each value is a SourceCitation Pydantic instance
        for v in result.values():
            assert isinstance(v, SourceCitation)

    def test_missing_ids_raise_with_diagnostic(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        # Return only 1 of 3 requested
        cur.fetchall.return_value = [
            ("MT-HD-deer-elk-lion-262-geom", _valid_source_jsonb()),
        ]
        with pytest.raises(RuntimeError, match="2 geometry ids that are absent"):
            _fetch_geometry_sources(
                conn,
                {
                    "MT-HD-deer-elk-lion-262-geom",
                    "MT-HD-bear-101-geom",
                    "MT-HD-antelope-690-geom",
                },
            )

    def test_empty_input_returns_empty_dict_no_db_call(self) -> None:
        conn = MagicMock()
        result = _fetch_geometry_sources(conn, set())
        assert result == {}
        conn.cursor.assert_not_called()


# ---------------------------------------------------------------------------
# TestBuildStatewideBindings (T6)
# ---------------------------------------------------------------------------

from states.montana.load_jurisdiction_bindings import (  # noqa: E402
    _build_statewide_bindings,
    _build_overlay_bindings,
    _OverlayRow,
)


class TestBuildStatewideBindings:
    @staticmethod
    def _make_source() -> SourceCitation:
        """A representative MT-STATEWIDE-geom source citation."""
        return SourceCitation(
            id="mt-msdi-framework-boundaries-9-2026",
            agency="MT FWP",
            title="MT MSDI Framework Boundaries Layer 9",
            url="https://gisservicemt.gov/arcgis/rest/services/example/FeatureServer/0",
            publication_date="2026-01-01",
            document_type="gis_layer",
        )

    @staticmethod
    def _make_rr(jurisdiction_code: str, species_group: str) -> RegulationRecord:
        """Build a minimal valid RegulationRecord for statewide binding tests."""
        return RegulationRecord(
            state="US-MT",
            jurisdiction_code=jurisdiction_code,
            species_group=species_group,
            license_year=2026,
            source=SourceCitation(
                id="test-citation",
                agency="Montana FWP",
                title="Test Title",
                url="https://example.com/test.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
            ),
            confidence="high",
        )

    def test_emits_one_primary_unit_binding_per_reg_record(self) -> None:
        antelope = self._make_rr("MT-STATEWIDE-antelope", "pronghorn")
        bear = self._make_rr("MT-STATEWIDE-bear", "bear")
        source = self._make_source()
        bindings = _build_statewide_bindings([antelope, bear], source)
        assert len(bindings) == 2
        for b in bindings:
            assert b.role == "primary_unit"
            assert b.geometry_id == "MT-STATEWIDE-geom"

    def test_bear_binding_id_byte_identical_to_s036_1_locked_value(self) -> None:
        """CRITICAL regression: this id must match S03.6.1's
        ``test_id_encoding_is_deterministic`` exactly, or the loader writes a
        duplicate bear binding instead of UPSERTing the existing row.

        Locked value: US-MT-MT-STATEWIDE-bear-bear-2026-primary_unit-MT-STATEWIDE-geom
        """
        bear = self._make_rr("MT-STATEWIDE-bear", "bear")
        bindings = _build_statewide_bindings([bear], self._make_source())
        assert bindings[0].id == "US-MT-MT-STATEWIDE-bear-bear-2026-primary_unit-MT-STATEWIDE-geom"

    def test_antelope_binding_id_format(self) -> None:
        antelope = self._make_rr("MT-STATEWIDE-antelope", "pronghorn")
        bindings = _build_statewide_bindings([antelope], self._make_source())
        assert bindings[0].id == "US-MT-MT-STATEWIDE-antelope-pronghorn-2026-primary_unit-MT-STATEWIDE-geom"

    def test_empty_input_returns_empty(self) -> None:
        assert _build_statewide_bindings([], self._make_source()) == []

    def test_verbatim_rule_is_none(self) -> None:
        rr = self._make_rr("MT-STATEWIDE-antelope", "pronghorn")
        bindings = _build_statewide_bindings([rr], self._make_source())
        assert bindings[0].verbatim_rule is None

    def test_source_is_attached(self) -> None:
        rr = self._make_rr("MT-STATEWIDE-bear", "bear")
        source = self._make_source()
        bindings = _build_statewide_bindings([rr], source)
        assert bindings[0].source == source


# ---------------------------------------------------------------------------
# TestBuildOverlayBindings (T7)
# ---------------------------------------------------------------------------


class TestBuildOverlayBindings:
    @staticmethod
    def _make_rr(jurisdiction_code: str, species_group: str = "elk") -> RegulationRecord:
        """Build a minimal valid RegulationRecord for overlay binding tests."""
        return RegulationRecord(
            state="US-MT",
            jurisdiction_code=jurisdiction_code,
            species_group=species_group,
            license_year=2026,
            source=SourceCitation(
                id="test-citation",
                agency="Montana FWP",
                title="Test Title",
                url="https://example.com/test.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
            ),
            confidence="high",
        )

    @staticmethod
    def _make_source() -> SourceCitation:
        """A representative geometry source citation."""
        return SourceCitation(
            id="mt-fwp-gis-layer-2026",
            agency="MT FWP",
            title="Montana HD Layer",
            url="https://gisservicemt.gov/arcgis/rest/services/example/FeatureServer/0",
            publication_date="2026-01-01",
            document_type="gis_layer",
        )

    @staticmethod
    def _row(
        parent_gid: str,
        child_gid: str,
        role_for_e03: str = "portion",
        child_kind: str = "portion",
    ) -> _OverlayRow:
        return _OverlayRow(
            parent_geometry_id=parent_gid,
            child_geometry_id=child_gid,
            parent_kind="hunting_district",
            child_kind=child_kind,
            relationship="contains",
            role_for_e03=role_for_e03,
        )

    def test_elk_hd_with_self_row_only_produces_one_primary_unit_binding(self) -> None:
        rr = self._make_rr("MT-HD-deer-elk-lion-262", "elk")
        parent_gid = "MT-HD-deer-elk-lion-262-geom"
        overlay = [self._row(parent_gid, parent_gid, role_for_e03="primary_unit",
                             child_kind="hunting_district")]
        sources = {parent_gid: self._make_source()}
        bindings = _build_overlay_bindings([rr], overlay, sources)
        assert len(bindings) == 1
        assert bindings[0].role == "primary_unit"
        assert bindings[0].geometry_id == parent_gid

    def test_elk_hd_with_self_row_portion_and_cwd(self) -> None:
        rr = self._make_rr("MT-HD-deer-elk-lion-103", "elk")
        parent_gid = "MT-HD-deer-elk-lion-103-geom"
        elk_portion = "MT-HD-elk-103-portion-elPt2-geom"
        cwd = "MT-CWD-zone-libby-geom"
        overlay = [
            self._row(parent_gid, parent_gid, role_for_e03="primary_unit",
                      child_kind="hunting_district"),
            self._row(parent_gid, elk_portion, role_for_e03="portion",
                      child_kind="portion"),
            self._row(parent_gid, cwd, role_for_e03="cwd_management_zone",
                      child_kind="cwd_zone"),
        ]
        sources = {
            parent_gid: self._make_source(),
            elk_portion: self._make_source(),
            cwd: self._make_source(),
        }
        bindings = _build_overlay_bindings([rr], overlay, sources)
        assert len(bindings) == 3
        roles = {b.role for b in bindings}
        assert roles == {"primary_unit", "portion", "cwd_management_zone"}

    def test_pronghorn_filters_out_cross_species_mule_deer_portion(self) -> None:
        """A pronghorn reg_record on MT-HD-antelope-N must not bind to a mule_deer
        portion that happens to share the same parent geometry in the fixture."""
        rr = self._make_rr("MT-HD-antelope-215", "pronghorn")
        parent_gid = "MT-HD-antelope-215-geom"
        # A cross-species elk portion that somehow appears under the antelope parent
        cross_species_portion = "MT-HD-elk-215-portion-elPt21-geom"
        overlay = [
            self._row(parent_gid, parent_gid, role_for_e03="primary_unit",
                      child_kind="hunting_district"),
            self._row(parent_gid, cross_species_portion, role_for_e03="portion",
                      child_kind="portion"),
        ]
        sources = {
            parent_gid: self._make_source(),
            cross_species_portion: self._make_source(),
        }
        bindings = _build_overlay_bindings([rr], overlay, sources)
        # Only the self-row should bind; the elk portion is filtered out
        assert len(bindings) == 1
        assert bindings[0].geometry_id == parent_gid

    def test_mule_deer_rejects_mt_restricted_elk_child(self) -> None:
        rr = self._make_rr("MT-HD-deer-elk-lion-262", "mule_deer")
        parent_gid = "MT-HD-deer-elk-lion-262-geom"
        elk_only = "MT-restricted-elk-foo-geom"
        overlay = [self._row(parent_gid, elk_only, role_for_e03="restricted_area",
                             child_kind="restricted_area")]
        sources = {elk_only: self._make_source()}
        bindings = _build_overlay_bindings([rr], overlay, sources)
        assert bindings == []

    def test_duplicate_binding_id_fails_loud(self) -> None:
        """Pathological: two identical reg_records process the same overlay row →
        produces the same binding id twice → fail-loud."""
        rr1 = self._make_rr("MT-HD-bear-101", "bear")
        rr2 = self._make_rr("MT-HD-bear-101", "bear")  # duplicate
        parent_gid = "MT-HD-bear-101-geom"
        overlay = [self._row(parent_gid, parent_gid, role_for_e03="primary_unit",
                             child_kind="hunting_district")]
        sources = {parent_gid: self._make_source()}
        with pytest.raises(RuntimeError, match="duplicate binding id"):
            _build_overlay_bindings([rr1, rr2], overlay, sources)

    def test_unknown_role_for_e03_fails_loud(self) -> None:
        rr = self._make_rr("MT-HD-bear-101", "bear")
        parent_gid = "MT-HD-bear-101-geom"
        overlay = [self._row(parent_gid, "MT-some-thing", role_for_e03="garbage_role",
                             child_kind="portion")]
        sources = {"MT-some-thing": self._make_source()}
        with pytest.raises(RuntimeError, match="unknown role_for_e03"):
            _build_overlay_bindings([rr], overlay, sources)

    def test_missing_source_for_child_geometry_fails_loud(self) -> None:
        rr = self._make_rr("MT-HD-bear-101", "bear")
        parent_gid = "MT-HD-bear-101-geom"
        overlay = [self._row(parent_gid, parent_gid, role_for_e03="primary_unit",
                             child_kind="hunting_district")]
        sources: dict[str, SourceCitation] = {}  # empty!
        with pytest.raises(RuntimeError, match="missing from source_lookup"):
            _build_overlay_bindings([rr], overlay, sources)

    def test_empty_inputs_return_empty_list(self) -> None:
        assert _build_overlay_bindings([], [], {}) == []

    def test_reg_record_with_no_overlay_entries_fails_loud(self) -> None:
        """If a reg_record's derived parent_geometry_id has zero overlay-fixture
        entries (no self-row, no portions, no overlays), fail loud rather than
        silently producing 0 bindings for that reg_record.

        Every HD-keyed reg_record's parent geometry MUST have at least a self-row
        (primary_unit) in the overlay fixture per E02 invariant.  A missing entry
        means a structural fixture / reg_record sync bug — silently skipping
        would drop ALL bindings (self + portions + overlays) for that record."""
        rr = self._make_rr("MT-HD-bear-999", "bear")
        # Overlay fixture has rows for HD 101 but NOT for HD 999
        overlay = [self._row("MT-HD-bear-101-geom", "MT-HD-bear-101-geom",
                             role_for_e03="primary_unit",
                             child_kind="hunting_district")]
        sources = {"MT-HD-bear-101-geom": self._make_source()}
        with pytest.raises(RuntimeError, match="no overlay-fixture entries"):
            _build_overlay_bindings([rr], overlay, sources)

    def test_binding_fields_are_fully_populated(self) -> None:
        """Spot-check all JurisdictionBinding fields on a single emitted binding."""
        rr = self._make_rr("MT-HD-deer-elk-lion-262", "elk")
        parent_gid = "MT-HD-deer-elk-lion-262-geom"
        overlay = [self._row(parent_gid, parent_gid, role_for_e03="primary_unit",
                             child_kind="hunting_district")]
        source = self._make_source()
        sources = {parent_gid: source}
        bindings = _build_overlay_bindings([rr], overlay, sources)
        b = bindings[0]
        assert b.regulation_record_state == "US-MT"
        assert b.regulation_record_jurisdiction_code == "MT-HD-deer-elk-lion-262"
        assert b.regulation_record_species_group == "elk"
        assert b.regulation_record_license_year == 2026
        assert b.verbatim_rule is None
        assert b.source == source
        # id encodes all PK + role + geometry_id fields
        assert "US-MT" in b.id
        assert "MT-HD-deer-elk-lion-262" in b.id
        assert "elk" in b.id
        assert "2026" in b.id
        assert "primary_unit" in b.id
        assert parent_gid in b.id


# ---------------------------------------------------------------------------
# TestQueryNearbyHdsForZone (T8)
# ---------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402
from states.montana.load_jurisdiction_bindings import (  # noqa: E402
    _build_no_hunt_zone_bindings,
    _query_nearby_hds_for_zone,
    _NO_HUNT_ZONE_NEARBY_DISTANCE_M,
)
from states.montana.build_overlay_fixture import EXPECTED_RA_ORPHAN_IDS  # noqa: E402


class TestQueryNearbyHdsForZone:
    def test_returns_sorted_hd_ids(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [
            ("MT-HD-deer-elk-lion-100-geom",),
            ("MT-HD-deer-elk-lion-101-geom",),
        ]
        result = _query_nearby_hds_for_zone(
            conn, "MT-restricted-bigame-glacier-national-park-geom"
        )
        assert result == [
            "MT-HD-deer-elk-lion-100-geom",
            "MT-HD-deer-elk-lion-101-geom",
        ]

    def test_passes_distance_constant_as_parameter(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        _query_nearby_hds_for_zone(conn, "some-zone-geom")
        call_args = cur.execute.call_args
        sql: str = call_args[0][0]
        params: tuple[object, ...] = call_args[0][1]
        # Spec Deviation #4 — single-clause geography-native ST_DWithin
        assert "extensions.ST_DWithin" in sql, "SQL must use extensions-qualified ST_DWithin"
        # HD-only filter: portions are intentionally excluded because
        # regulation_record is HD-keyed in V1 (portion ids never appear as
        # keys in `rrs_by_parent` from `_derive_parent_geometry_id`).  Including
        # portions would silently drop bindings.  See module docstring of
        # _query_nearby_hds_for_zone for the V1-Montana verification.
        assert "kind = 'hunting_district'" in sql
        assert "'portion'" not in sql, "portions must NOT be in the nearby filter"
        # No ST_Touches, no ST_Centroid, no ::geometry casts (Spec Deviation #4)
        assert "ST_Touches" not in sql
        assert "ST_Centroid" not in sql
        assert "::geometry" not in sql
        # Distance param is the constant value
        assert params[0] == _NO_HUNT_ZONE_NEARBY_DISTANCE_M

    def test_returns_empty_list_when_no_nearby_hds(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        result = _query_nearby_hds_for_zone(conn, "some-remote-zone-geom")
        assert result == []

    def test_sql_excludes_portions_regression_guard(self) -> None:
        """The nearby query MUST NOT include portion geometries.

        regulation_record is HD-keyed in V1 (see _derive_parent_geometry_id);
        portion ids never appear as keys in `rrs_by_parent`.  If the SQL ever
        re-introduces portions, the downstream `rrs_by_parent.get(portion_id, [])`
        lookup silently returns `[]` and the portion's contribution is dropped
        without diagnostic — a real silent-failure mode caught during review.

        This test locks the HD-only invariant.  If you legitimately need to
        include portions in the nearby query, also extend
        `_derive_parent_geometry_id` to produce portion-shaped ids, then update
        this test."""
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        _query_nearby_hds_for_zone(conn, "any-zone")
        sql: str = cur.execute.call_args[0][0]
        assert "'portion'" not in sql, (
            "SQL must not include 'portion' kind — portion ids don't map to "
            "regulation_records via _derive_parent_geometry_id and would be "
            "silently dropped by _build_no_hunt_zone_bindings."
        )
        # Positive: only 'hunting_district' is queried
        assert "kind = 'hunting_district'" in sql

    def test_sql_uses_extensions_prefix_not_bare_name(self) -> None:
        """Regression: bare ST_DWithin fails to resolve in Supabase extensions schema."""
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        _query_nearby_hds_for_zone(conn, "any-zone")
        sql: str = cur.execute.call_args[0][0]
        # Must have extensions. prefix — bare ST_DWithin fails on Supabase
        assert "extensions.ST_DWithin" in sql
        # Must NOT have a bare (unqualified) ST_DWithin call
        import re
        bare_matches = re.findall(r"(?<!extensions\.)ST_DWithin", sql)
        assert not bare_matches, f"Found bare ST_DWithin (missing extensions. prefix): {bare_matches}"

    def test_geom_column_not_geog(self) -> None:
        """Column name is `geom` (geography type) — not `geog`."""
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        _query_nearby_hds_for_zone(conn, "any-zone")
        sql: str = cur.execute.call_args[0][0]
        assert ".geom" in sql, "SQL must reference .geom column"
        assert ".geog" not in sql, "SQL must NOT reference .geog (wrong column name)"


# ---------------------------------------------------------------------------
# TestBuildNoHuntZoneBindings (T8)
# ---------------------------------------------------------------------------

import states.montana.load_jurisdiction_bindings as _ljb_module  # noqa: E402


class TestBuildNoHuntZoneBindings:
    @staticmethod
    def _make_rr(jurisdiction_code: str, species_group: str = "elk") -> RegulationRecord:
        return RegulationRecord(
            state="US-MT",
            jurisdiction_code=jurisdiction_code,
            species_group=species_group,
            license_year=2026,
            source=SourceCitation(
                id="test-citation",
                agency="Montana FWP",
                title="Test Title",
                url="https://example.com/test.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
            ),
            confidence="high",
        )

    @staticmethod
    def _make_source() -> SourceCitation:
        return SourceCitation(
            id="mt-fwp-gis-layer-2026",
            agency="MT FWP",
            title="Montana Restricted Area Layer",
            url="https://gisservicemt.gov/arcgis/rest/services/example/FeatureServer/0",
            publication_date="2026-01-01",
            document_type="gis_layer",
        )

    def test_emits_one_binding_per_rr_per_zone(self) -> None:
        """3 zones × 1 HD × 1 reg_record → 3 bindings, geometry_id = zone not HD."""
        rr = self._make_rr("MT-HD-bear-101", "bear")
        sources = {z: self._make_source() for z in EXPECTED_RA_ORPHAN_IDS}
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-bear-101-geom"],
        ):
            bindings = _build_no_hunt_zone_bindings(conn, [rr], sources)
        # 3 zones × 1 HD × 1 reg_record = 3 bindings
        assert len(bindings) == 3
        assert {b.role for b in bindings} == {"other_overlay"}
        # geometry_id is the zone, not the HD
        assert {b.geometry_id for b in bindings} == set(EXPECTED_RA_ORPHAN_IDS)

    def test_zero_nearby_hds_fails_loud_per_zone(self) -> None:
        """Per AC #1086 — if any zone returns 0 nearby HDs, RuntimeError with zone name."""
        conn = MagicMock()
        sources = {z: self._make_source() for z in EXPECTED_RA_ORPHAN_IDS}
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=[],
        ):
            with pytest.raises(RuntimeError, match="zero nearby HD matches"):
                _build_no_hunt_zone_bindings(conn, [], sources)

    def test_missing_zone_source_fails_loud(self) -> None:
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-bear-101-geom"],
        ):
            with pytest.raises(RuntimeError, match="missing from source_lookup"):
                _build_no_hunt_zone_bindings(
                    conn, [self._make_rr("MT-HD-bear-101", "bear")], {}
                )

    def test_role_is_other_overlay_only(self) -> None:
        rr = self._make_rr("MT-HD-bear-101", "bear")
        sources = {z: self._make_source() for z in EXPECTED_RA_ORPHAN_IDS}
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-bear-101-geom"],
        ):
            bindings = _build_no_hunt_zone_bindings(conn, [rr], sources)
        for b in bindings:
            assert b.role == "other_overlay"

    def test_three_species_on_shared_hd_produces_three_bindings_per_zone(self) -> None:
        """DEL HD has 3 reg_records (mule_deer + whitetail + elk); each gets its
        own binding to each nearby zone."""
        rrs = [
            self._make_rr("MT-HD-deer-elk-lion-100", "mule_deer"),
            self._make_rr("MT-HD-deer-elk-lion-100", "whitetail"),
            self._make_rr("MT-HD-deer-elk-lion-100", "elk"),
        ]
        sources = {z: self._make_source() for z in EXPECTED_RA_ORPHAN_IDS}
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-deer-elk-lion-100-geom"],
        ):
            bindings = _build_no_hunt_zone_bindings(conn, rrs, sources)
        # 3 zones × 1 HD × 3 reg_records = 9 bindings
        assert len(bindings) == 9

    def test_hd_with_no_reg_records_produces_no_bindings_for_that_hd(self) -> None:
        """nearby HDs returned but none have reg_records → 0 bindings (not a fail-loud)."""
        sources = {z: self._make_source() for z in EXPECTED_RA_ORPHAN_IDS}
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-bear-999-geom"],  # HD with no reg_records
        ):
            bindings = _build_no_hunt_zone_bindings(conn, [], sources)
        # Zero reg_records means zero bindings — NOT a fail-loud condition
        assert bindings == []

    def test_duplicate_binding_id_fails_loud(self) -> None:
        """Duplicate binding id within a single build run → RuntimeError."""
        rr1 = self._make_rr("MT-HD-bear-101", "bear")
        rr2 = self._make_rr("MT-HD-bear-101", "bear")  # duplicate
        sources = {z: self._make_source() for z in EXPECTED_RA_ORPHAN_IDS}
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-bear-101-geom"],
        ):
            with pytest.raises(RuntimeError, match="duplicate binding id"):
                _build_no_hunt_zone_bindings(conn, [rr1, rr2], sources)

    def test_binding_geometry_id_is_zone_not_hd(self) -> None:
        """geometry_id on the binding must be the zone, not the nearby HD."""
        zone_ids = sorted(EXPECTED_RA_ORPHAN_IDS)
        rr = self._make_rr("MT-HD-bear-101", "bear")
        sources = {z: self._make_source() for z in EXPECTED_RA_ORPHAN_IDS}
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-bear-101-geom"],
        ):
            bindings = _build_no_hunt_zone_bindings(conn, [rr], sources)
        for b in bindings:
            assert b.geometry_id in zone_ids, (
                f"binding geometry_id {b.geometry_id!r} should be a zone id, not an HD id"
            )

    def test_verbatim_rule_is_none(self) -> None:
        rr = self._make_rr("MT-HD-bear-101", "bear")
        sources = {z: self._make_source() for z in EXPECTED_RA_ORPHAN_IDS}
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-bear-101-geom"],
        ):
            bindings = _build_no_hunt_zone_bindings(conn, [rr], sources)
        for b in bindings:
            assert b.verbatim_rule is None

    def test_source_citation_is_from_zone_not_hd(self) -> None:
        """source on each binding must come from source_lookup[zone_id]."""
        zone_source = self._make_source()
        rr = self._make_rr("MT-HD-bear-101", "bear")
        sources = {z: zone_source for z in EXPECTED_RA_ORPHAN_IDS}
        conn = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            return_value=["MT-HD-bear-101-geom"],
        ):
            bindings = _build_no_hunt_zone_bindings(conn, [rr], sources)
        for b in bindings:
            assert b.source == zone_source


# ---------------------------------------------------------------------------
# TestCountGuard (T9)
# ---------------------------------------------------------------------------

import logging  # noqa: E402

from ingestion.lib.schema import JurisdictionBinding  # noqa: E402
from states.montana.load_jurisdiction_bindings import (  # noqa: E402
    _assert_binding_count_within_guard,
    _log_summary,
    _query_all_montana_regulation_records,
)


class TestCountGuard:
    def test_low_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="outside expected band"):
            _assert_binding_count_within_guard(399)

    def test_in_band_no_op(self) -> None:
        _assert_binding_count_within_guard(770)  # no raise

    def test_high_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="outside expected band"):
            _assert_binding_count_within_guard(1101)

    def test_lower_bound_inclusive(self) -> None:
        _assert_binding_count_within_guard(400)  # no raise

    def test_upper_bound_inclusive(self) -> None:
        _assert_binding_count_within_guard(1100)  # no raise


# ---------------------------------------------------------------------------
# TestLogSummary (T9)
# ---------------------------------------------------------------------------


class TestLogSummary:
    @staticmethod
    def _make_binding(species_group: str, role: str) -> JurisdictionBinding:
        from ingestion.lib.schema import SourceCitation
        return JurisdictionBinding(
            id=f"US-MT-MT-HD-deer-elk-lion-262-{species_group}-2026-{role}-MT-HD-deer-elk-lion-262-geom",
            regulation_record_state="US-MT",
            regulation_record_jurisdiction_code="MT-HD-deer-elk-lion-262",
            regulation_record_species_group=species_group,
            regulation_record_license_year=2026,
            geometry_id="MT-HD-deer-elk-lion-262-geom",
            role=role,  # type: ignore[arg-type]
            verbatim_rule=None,
            source=SourceCitation(
                id="test-source",
                agency="MT FWP",
                title="Test",
                url="https://example.com",
                publication_date="2026-01-01",
                document_type="gis_layer",
            ),
        )

    def test_logs_total_count(self, caplog: pytest.LogCaptureFixture) -> None:
        bindings = [
            self._make_binding("elk", "primary_unit"),
            self._make_binding("elk", "portion"),
            self._make_binding("mule_deer", "primary_unit"),
        ]
        test_logger = logging.getLogger("ingestion.states.montana.load_jurisdiction_bindings")
        with caplog.at_level(logging.INFO, logger="ingestion.states.montana.load_jurisdiction_bindings"):
            _log_summary(bindings, test_logger)
        assert "TOTAL: 3 bindings" in caplog.text

    def test_logs_per_bucket_breakdown(self, caplog: pytest.LogCaptureFixture) -> None:
        bindings = [
            self._make_binding("elk", "primary_unit"),
            self._make_binding("elk", "portion"),
            self._make_binding("mule_deer", "primary_unit"),
        ]
        test_logger = logging.getLogger("ingestion.states.montana.load_jurisdiction_bindings")
        with caplog.at_level(logging.INFO, logger="ingestion.states.montana.load_jurisdiction_bindings"):
            _log_summary(bindings, test_logger)
        # Two elk rows: one primary_unit + one portion
        assert "elk × primary_unit: 1" in caplog.text
        assert "elk × portion: 1" in caplog.text
        assert "mule_deer × primary_unit: 1" in caplog.text

    def test_empty_bindings_logs_zero_total(self, caplog: pytest.LogCaptureFixture) -> None:
        test_logger = logging.getLogger("ingestion.states.montana.load_jurisdiction_bindings")
        with caplog.at_level(logging.INFO, logger="ingestion.states.montana.load_jurisdiction_bindings"):
            _log_summary([], test_logger)
        assert "TOTAL: 0 bindings" in caplog.text


# ---------------------------------------------------------------------------
# TestQueryAllMontanaRegulationRecords (T10)
# ---------------------------------------------------------------------------


class TestQueryAllMontanaRegulationRecords:
    @staticmethod
    def _source_jsonb() -> dict:  # type: ignore[type-arg]
        return {
            "id": "mt-fwp-dea-2026-booklet",
            "agency": "MT FWP",
            "title": "Montana DEA 2026",
            "url": "https://fwp.mt.gov/hunt/regulations",
            "publication_date": "2026-04-27",
            "document_type": "annual_regulations",
        }

    def test_returns_pydantic_instances(self) -> None:
        from ingestion.lib.schema import RegulationRecord
        # additional_rules jsonb comes back as list[dict] from psycopg.
        # VerbatimRule requires: text, confidence, source.
        note_rule_jsonb = {
            "text": "NOTE: test note",
            "confidence": "high",
            "source": self._source_jsonb(),
        }
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [
            (
                "US-MT",                  # state
                "MT-HD-deer-elk-lion-262", # jurisdiction_code
                "elk",                    # species_group
                2026,                     # license_year
                2,                        # schema_version
                "high",                   # confidence
                [note_rule_jsonb],        # additional_rules (list[dict])
                None,                     # ingested_at
                self._source_jsonb(),     # source
            )
        ]
        records = _query_all_montana_regulation_records(conn)
        assert len(records) == 1
        assert isinstance(records[0], RegulationRecord)
        assert records[0].jurisdiction_code == "MT-HD-deer-elk-lion-262"
        assert records[0].species_group == "elk"
        assert records[0].confidence == "high"

    def test_empty_result_returns_empty_list(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        records = _query_all_montana_regulation_records(conn)
        assert records == []

    def test_queries_only_mt_state_and_current_license_year(self) -> None:
        """Verifies the SQL is parameterised with both `_STATE` AND `_LICENSE_YEAR`.

        The license_year filter is load-bearing: without it, a multi-year DB
        (post year-over-year re-ingestion) would silently fan out bindings
        across years, blowing past the count guard and writing cross-year
        bindings that violate the UPSERT contract.  See `_query_all_montana_
        regulation_records` docstring + commit history.
        """
        from states.montana.load_jurisdiction_bindings import _LICENSE_YEAR
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        _query_all_montana_regulation_records(conn)
        call_args = cur.execute.call_args
        sql: str = call_args[0][0]
        params: tuple[object, ...] = call_args[0][1]
        assert "license_year = %s" in sql, "SQL must filter by license_year"
        assert params == ("US-MT", _LICENSE_YEAR), (
            f"Expected ('US-MT', {_LICENSE_YEAR}), got {params}"
        )

    def test_null_additional_rules_coerced_to_empty_list(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [
            ("US-MT", "MT-HD-deer-elk-lion-262", "elk", 2026, 2, "high",
             None, None, self._source_jsonb())
        ]
        records = _query_all_montana_regulation_records(conn)
        assert records[0].additional_rules == []


# ---------------------------------------------------------------------------
# TestMain (T10)
# ---------------------------------------------------------------------------

from ingestion.lib import db as _db_module  # noqa: E402
import states.montana.load_jurisdiction_bindings as _ljb  # noqa: E402


def _make_minimal_rr(
    jurisdiction_code: str,
    species_group: str = "elk",
) -> RegulationRecord:
    return RegulationRecord(
        state="US-MT",
        jurisdiction_code=jurisdiction_code,
        species_group=species_group,
        license_year=2026,
        source=SourceCitation(
            id="test-citation",
            agency="MT FWP",
            title="Test",
            url="https://example.com",
            publication_date="2026-01-01",
            document_type="annual_regulations",
        ),
        confidence="high",
    )


def _make_minimal_source() -> SourceCitation:
    return SourceCitation(
        id="mt-fwp-gis-layer-2026",
        agency="MT FWP",
        title="MT GIS Layer",
        url="https://gisservicemt.gov/arcgis/rest/services/example/FeatureServer/0",
        publication_date="2026-01-01",
        document_type="gis_layer",
    )


def _make_minimal_statewide_reg_records() -> list[RegulationRecord]:
    """The 2 statewide reg_records main()'s new fail-loud guard requires.

    Both must be present or main() raises before reaching the builders.  Tests
    that mock the builders directly still need these to satisfy the guard.
    """
    return [
        RegulationRecord(
            state="US-MT",
            jurisdiction_code="MT-STATEWIDE-antelope",
            species_group="pronghorn",
            license_year=2026,
            source=_make_minimal_source(),
            confidence="high",
        ),
        RegulationRecord(
            state="US-MT",
            jurisdiction_code="MT-STATEWIDE-bear",
            species_group="bear",
            license_year=2026,
            source=_make_minimal_source(),
            confidence="high",
        ),
    ]


class TestMain:
    """Integration tests for main() wiring using a fully-mocked DB connection.

    Strategy: patch db.connect to return a MagicMock context manager, then
    pre-program the builder patches to return synthetic binding lists of
    controlled sizes.
    """

    def _make_conn_mock(self) -> MagicMock:
        """Build a MagicMock that behaves as a psycopg connection context manager."""
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    def _patch_builders_with_bindings(
        self,
        n_bindings: int,
    ) -> list[JurisdictionBinding]:
        """Build n_bindings synthetic JurisdictionBinding objects for test use."""
        source = _make_minimal_source()
        bindings = []
        for i in range(n_bindings):
            bindings.append(
                JurisdictionBinding(
                    id=f"US-MT-MT-HD-deer-elk-lion-{i}-elk-2026-primary_unit-MT-HD-deer-elk-lion-{i}-geom",
                    regulation_record_state="US-MT",
                    regulation_record_jurisdiction_code=f"MT-HD-deer-elk-lion-{i}",
                    regulation_record_species_group="elk",
                    regulation_record_license_year=2026,
                    geometry_id=f"MT-HD-deer-elk-lion-{i}-geom",
                    role="primary_unit",
                    verbatim_rule=None,
                    source=source,
                )
            )
        return bindings

    def test_dry_run_returns_0_and_no_upserts(self) -> None:
        """--dry-run: guard passes, no db.upsert_jurisdiction_binding called."""
        conn_mock = self._make_conn_mock()
        synthetic_bindings = self._patch_builders_with_bindings(770)

        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=_make_minimal_statewide_reg_records()), \
             patch.object(_ljb, "_fetch_geometry_sources", return_value={
                 _ljb._MT_STATEWIDE_GEOM_ID: _make_minimal_source(),
             }), \
             patch.object(_ljb, "_build_statewide_bindings", return_value=[]), \
             patch.object(_ljb, "_build_overlay_bindings", return_value=[]), \
             patch.object(_ljb, "_build_no_hunt_zone_bindings", return_value=synthetic_bindings), \
             patch.object(_db_module, "upsert_jurisdiction_binding") as mock_upsert:
            result = _ljb.main(["--dry-run"])

        assert result == 0
        mock_upsert.assert_not_called()

    def test_in_band_count_writes_commits_and_returns_0(self) -> None:
        """770 synthetic bindings → writes 770 upserts → commit called → returns 0."""
        conn_mock = self._make_conn_mock()
        synthetic_bindings = self._patch_builders_with_bindings(770)

        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=_make_minimal_statewide_reg_records()), \
             patch.object(_ljb, "_fetch_geometry_sources", return_value={
                 _ljb._MT_STATEWIDE_GEOM_ID: _make_minimal_source(),
             }), \
             patch.object(_ljb, "_build_statewide_bindings", return_value=[]), \
             patch.object(_ljb, "_build_overlay_bindings", return_value=[]), \
             patch.object(_ljb, "_build_no_hunt_zone_bindings", return_value=synthetic_bindings), \
             patch.object(_db_module, "upsert_jurisdiction_binding") as mock_upsert:
            result = _ljb.main([])

        assert result == 0
        assert mock_upsert.call_count == 770
        conn_mock.commit.assert_called_once()
        conn_mock.rollback.assert_not_called()

    def test_out_of_band_count_raises_before_any_upsert(self) -> None:
        """50 synthetic bindings → count guard fires → RuntimeError → no upserts."""
        conn_mock = self._make_conn_mock()
        # 50 bindings is below the [400, 1100] band floor
        synthetic_bindings = self._patch_builders_with_bindings(50)

        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=_make_minimal_statewide_reg_records()), \
             patch.object(_ljb, "_fetch_geometry_sources", return_value={
                 _ljb._MT_STATEWIDE_GEOM_ID: _make_minimal_source(),
             }), \
             patch.object(_ljb, "_build_statewide_bindings", return_value=[]), \
             patch.object(_ljb, "_build_overlay_bindings", return_value=[]), \
             patch.object(_ljb, "_build_no_hunt_zone_bindings", return_value=synthetic_bindings), \
             patch.object(_db_module, "upsert_jurisdiction_binding") as mock_upsert:
            with pytest.raises(RuntimeError, match="outside expected band"):
                _ljb.main([])

        mock_upsert.assert_not_called()
        conn_mock.commit.assert_not_called()

    def test_write_exception_triggers_rollback_not_commit(self) -> None:
        """If upsert raises mid-loop, rollback is called and commit is not."""
        conn_mock = self._make_conn_mock()
        synthetic_bindings = self._patch_builders_with_bindings(770)

        def _raise_on_first_call(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated DB error")

        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=_make_minimal_statewide_reg_records()), \
             patch.object(_ljb, "_fetch_geometry_sources", return_value={
                 _ljb._MT_STATEWIDE_GEOM_ID: _make_minimal_source(),
             }), \
             patch.object(_ljb, "_build_statewide_bindings", return_value=[]), \
             patch.object(_ljb, "_build_overlay_bindings", return_value=[]), \
             patch.object(_ljb, "_build_no_hunt_zone_bindings", return_value=synthetic_bindings), \
             patch.object(_db_module, "upsert_jurisdiction_binding", side_effect=_raise_on_first_call):
            with pytest.raises(RuntimeError, match="simulated DB error"):
                _ljb.main([])

        conn_mock.rollback.assert_called_once()
        conn_mock.commit.assert_not_called()

    def test_empty_reg_records_fails_loud_with_actionable_message(self) -> None:
        """If the regulation_record table is empty (e.g. operator forgot to run
        prior loaders), main() must fail loud with a diagnostic naming the
        prior loaders — review-triad silent-failure-hunter finding WARN-W1.
        Without this guard the count guard's "outside band" error misdiagnoses
        the root cause."""
        conn_mock = self._make_conn_mock()
        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=[]):
            with pytest.raises(RuntimeError, match="returned 0 rows.*S03.6"):
                _ljb.main([])

    def test_missing_statewide_reg_record_fails_loud(self) -> None:
        """If MT-STATEWIDE-antelope or MT-STATEWIDE-bear is absent, main() must
        fail loud — review-triad silent-failure-hunter finding WARN-W2.
        Without this guard the count guard's "outside band" error misdiagnoses
        the root cause (S03.6.1 not fully run)."""
        conn_mock = self._make_conn_mock()
        # Provide only MT-STATEWIDE-antelope; MT-STATEWIDE-bear is missing
        partial_statewide = [_make_minimal_statewide_reg_records()[0]]
        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=partial_statewide):
            with pytest.raises(RuntimeError, match="missing.*MT-STATEWIDE-bear"):
                _ljb.main([])

    def test_unexpected_statewide_reg_record_fails_loud(self) -> None:
        """Symmetric to test_missing_statewide_reg_record_fails_loud: any
        UNEXPECTED statewide code (e.g., MT-STATEWIDE-mountain_lion added in
        the future without an ADR-018 amendment) must fail loud rather than
        being silently bound by `_build_statewide_bindings`.

        V1 expects exactly {MT-STATEWIDE-antelope, MT-STATEWIDE-bear}; new
        statewide anchors require ADR-018 amendment + S03.10 spec update."""
        conn_mock = self._make_conn_mock()
        unexpected_rr = RegulationRecord(
            state="US-MT",
            jurisdiction_code="MT-STATEWIDE-mountain_lion",
            species_group="mountain_lion",
            license_year=2026,
            source=_make_minimal_source(),
            confidence="high",
        )
        all_statewide = _make_minimal_statewide_reg_records() + [unexpected_rr]
        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=all_statewide):
            with pytest.raises(RuntimeError, match="unexpected statewide.*MT-STATEWIDE-mountain_lion"):
                _ljb.main([])

    def test_cross_builder_duplicate_id_fails_loud(self) -> None:
        """If two builders produce the same binding id (statewide + overlay,
        or no-hunt + overlay), main() must fail loud BEFORE the write loop —
        review-triad code-reviewer finding CRITICAL-1.  Per-builder seen_ids
        sets don't catch cross-builder collisions."""
        conn_mock = self._make_conn_mock()
        source = _make_minimal_source()

        # Build two synthetic bindings with the SAME id from different builders
        same_id = "US-MT-MT-HD-deer-elk-lion-262-elk-2026-primary_unit-MT-HD-deer-elk-lion-262-geom"

        def _binding_at(role: str = "primary_unit") -> JurisdictionBinding:
            return JurisdictionBinding(
                id=same_id,
                regulation_record_state="US-MT",
                regulation_record_jurisdiction_code="MT-HD-deer-elk-lion-262",
                regulation_record_species_group="elk",
                regulation_record_license_year=2026,
                geometry_id="MT-HD-deer-elk-lion-262-geom",
                role=role,  # type: ignore[arg-type]
                verbatim_rule=None,
                source=source,
            )

        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records",
                          return_value=_make_minimal_statewide_reg_records()), \
             patch.object(_ljb, "_fetch_geometry_sources", return_value={
                 _ljb._MT_STATEWIDE_GEOM_ID: source,
             }), \
             patch.object(_ljb, "_build_statewide_bindings",
                          return_value=[_binding_at()]), \
             patch.object(_ljb, "_build_overlay_bindings",
                          return_value=[_binding_at()]), \
             patch.object(_ljb, "_build_no_hunt_zone_bindings", return_value=[]):
            with pytest.raises(RuntimeError, match="cross-builder duplicate binding id"):
                _ljb.main([])

    def test_malformed_geometry_source_raises_with_geometry_id(self) -> None:
        """If a geometry row has a malformed `source` jsonb, _fetch_geometry_sources
        must surface the geometry id in the error — review-triad silent-failure-hunter
        finding CRITICAL-2.  Without this, ValidationError gives no indication
        which of the 300+ candidate geometries had the bad data."""
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [
            ("MT-HD-bear-101-geom", _valid_source_jsonb()),
            ("MT-HD-broken-geom", {"missing": "required fields"}),
        ]
        with pytest.raises(RuntimeError, match="MT-HD-broken-geom.*malformed source jsonb"):
            _fetch_geometry_sources(
                conn,
                {"MT-HD-bear-101-geom", "MT-HD-broken-geom"},
            )


# ---------------------------------------------------------------------------
# TestRealArtifactRegression (T11)
# ---------------------------------------------------------------------------


class TestRealArtifactRegression:
    """End-to-end regression test that exercises the full build pipeline
    against the REAL geometry-overlays.json fixture.

    Design decision: rather than constructing 437 synthetic reg_records
    (verbose, fragile on schema changes), this test uses a small representative
    set of ~14 reg_records covering all 5 species_groups + both statewide
    anchors.  The SHAPE invariants (id uniqueness, byte-identical bear id,
    valid roles, no confidence field) are fully exercisable with this smaller
    input; the absolute count band is not meaningful here because we only pass
    in ~14 reg_records.  Count-band accuracy is separately locked by
    TestCountGuard + TestMain::test_out_of_band_count_raises_before_any_upsert.

    The "real-artifact" value comes from verifying:
      1. The real geometry-overlays.json fixture is accepted without error.
      2. The full build pipeline (_build_statewide_bindings + _build_overlay_bindings
         + _build_no_hunt_zone_bindings) composes correctly end-to-end.
      3. id uniqueness holds across the full builder cross product.
      4. The bear binding's id is byte-identical to S03.6.1's locked value.
      5. Every binding carries a valid DDL role.
      6. No binding has a `confidence` attribute (ADR-017 §2).
    """

    # T0 probe results — fixed nearby HD lists used as mock returns.
    # Glacier=8, Sun River=8, Yellowstone=13 (live probe 2026-05-23).
    _GLACIER_NEARBY_HDS = [
        "MT-HD-bear-100-geom",
        "MT-HD-bear-101-geom",
        "MT-HD-bear-110-geom",
        "MT-HD-bear-120-geom",
        "MT-HD-deer-elk-lion-100-geom",
        "MT-HD-deer-elk-lion-101-geom",
        "MT-HD-deer-elk-lion-110-geom",
        "MT-HD-deer-elk-lion-120-geom",
    ]
    _SUN_RIVER_NEARBY_HDS = [
        "MT-HD-bear-441-geom",
        "MT-HD-bear-442-geom",
        "MT-HD-bear-450-geom",
        "MT-HD-bear-460-geom",
        "MT-HD-deer-elk-lion-441-geom",
        "MT-HD-deer-elk-lion-442-geom",
        "MT-HD-deer-elk-lion-450-geom",
        "MT-HD-deer-elk-lion-460-geom",
    ]
    _YELLOWSTONE_NEARBY_HDS = [
        "MT-HD-bear-316-geom",
        "MT-HD-bear-317-geom",
        "MT-HD-bear-325-geom",
        "MT-HD-bear-326-geom",
        "MT-HD-bear-330-geom",
        "MT-HD-bear-331-geom",
        "MT-HD-deer-elk-lion-316-geom",
        "MT-HD-deer-elk-lion-317-geom",
        "MT-HD-deer-elk-lion-325-geom",
        "MT-HD-deer-elk-lion-326-geom",
        "MT-HD-deer-elk-lion-330-geom",
        "MT-HD-deer-elk-lion-331-geom",
        "MT-HD-antelope-316-geom",
    ]

    # Map zone id → nearby HD list for the mock dispatcher below.
    _NEARBY_MAP: dict[str, list[str]] = {
        "MT-restricted-bigame-glacier-national-park-geom": _GLACIER_NEARBY_HDS,
        "MT-restricted-bigame-sun-river-game-preserve-geom": _SUN_RIVER_NEARBY_HDS,
        "MT-restricted-bigame-yellowstone-national-park-geom": _YELLOWSTONE_NEARBY_HDS,
    }

    @staticmethod
    def _make_source(gid: str) -> SourceCitation:
        """Synthetic gis_layer source for any geometry id."""
        return SourceCitation(
            id=f"mt-fwp-gis-layer-{gid}",
            agency="MT FWP",
            title=f"MT GIS Layer {gid}",
            url="https://gisservicemt.gov/arcgis/rest/services/example/FeatureServer/0",
            publication_date="2026-01-01",
            document_type="gis_layer",
        )

    @staticmethod
    def _make_rr(
        jurisdiction_code: str,
        species_group: str,
    ) -> RegulationRecord:
        return RegulationRecord(
            state="US-MT",
            jurisdiction_code=jurisdiction_code,
            species_group=species_group,
            license_year=2026,
            source=SourceCitation(
                id="mt-fwp-dea-2026-booklet",
                agency="MT FWP",
                title="MT DEA 2026",
                url="https://fwp.mt.gov/hunt/regulations",
                publication_date="2026-04-27",
                document_type="annual_regulations",
            ),
            confidence="high",
        )

    def _build_synthetic_reg_records(self) -> list[RegulationRecord]:
        """14 reg_records spanning all 5 species_groups + both statewide anchors.

        DEL HDs (deer+elk+lion): 3 recs per HD (mule_deer, whitetail, elk)
        → chosen HDs: 100, 262, 103 (CWD overlap candidate)
        Antelope HDs: 1 pronghorn rec per HD → 215, 311
        Bear BMUs: 1 bear rec per BMU → 100, 101, 411
        Statewide: MT-STATEWIDE-antelope + MT-STATEWIDE-bear

        Total: 9 DEL + 2 antelope + 3 bear + 2 statewide = 16 reg_records.
        """
        records: list[RegulationRecord] = []
        del_hds = ["MT-HD-deer-elk-lion-100", "MT-HD-deer-elk-lion-262", "MT-HD-deer-elk-lion-103"]
        for jc in del_hds:
            for sg in ("mule_deer", "whitetail", "elk"):
                records.append(self._make_rr(jc, sg))
        for jc in ("MT-HD-antelope-215", "MT-HD-antelope-311"):
            records.append(self._make_rr(jc, "pronghorn"))
        for jc in ("MT-HD-bear-100", "MT-HD-bear-101", "MT-HD-bear-411"):
            records.append(self._make_rr(jc, "bear"))
        records.append(self._make_rr("MT-STATEWIDE-antelope", "pronghorn"))
        records.append(self._make_rr("MT-STATEWIDE-bear", "bear"))
        return records

    def _make_source_lookup_for_fixture(self) -> dict[str, SourceCitation]:
        """Build source_lookup for every geometry id that could appear in a binding."""
        import json
        with _ljb_module._OVERLAY_FIXTURE_PATH.open() as f:
            overlay_rows = json.load(f)
        gids: set[str] = set()
        gids.add(_ljb_module._MT_STATEWIDE_GEOM_ID)
        for row in overlay_rows:
            gids.add(row["child_geometry_id"])
        # Also add the orphan zone ids
        from states.montana.build_overlay_fixture import (
            EXPECTED_RA_ORPHAN_IDS as _orphan_ids,
        )
        gids.update(_orphan_ids)
        # All nearby HD ids from the mocked probe
        for hd_list in self._NEARBY_MAP.values():
            gids.update(hd_list)
        return {gid: self._make_source(gid) for gid in gids}

    def _query_nearby_side_effect(
        self,
        conn: object,
        zone_id: str,
    ) -> list[str]:
        """Dispatcher returning the T0-probe-calibrated HD list per zone."""
        result = self._NEARBY_MAP.get(zone_id)
        if result is None:
            return []
        return result

    def test_full_build_pipeline_with_real_fixture(self) -> None:
        """Build pipeline runs against the real overlay fixture with a
        synthetic reg_record set and mocked DB; verify shape invariants."""
        reg_records = self._build_synthetic_reg_records()
        source_lookup = self._make_source_lookup_for_fixture()

        statewide_rrs = [
            rr for rr in reg_records
            if rr.jurisdiction_code.startswith("MT-STATEWIDE-")
        ]
        non_statewide_rrs = [
            rr for rr in reg_records
            if not rr.jurisdiction_code.startswith("MT-STATEWIDE-")
        ]

        # Load real fixture directly
        overlay_rows = _ljb_module._load_overlay_fixture(
            _ljb_module._OVERLAY_FIXTURE_PATH
        )
        statewide_source = source_lookup[_ljb_module._MT_STATEWIDE_GEOM_ID]

        # Run all three builders
        statewide_bindings = _ljb_module._build_statewide_bindings(
            statewide_rrs, statewide_source
        )

        overlay_bindings = _ljb_module._build_overlay_bindings(
            non_statewide_rrs, overlay_rows, source_lookup
        )

        conn_mock = MagicMock()
        with patch.object(
            _ljb_module,
            "_query_nearby_hds_for_zone",
            side_effect=self._query_nearby_side_effect,
        ):
            no_hunt_bindings = _ljb_module._build_no_hunt_zone_bindings(
                conn_mock, non_statewide_rrs, source_lookup
            )

        all_bindings = statewide_bindings + overlay_bindings + no_hunt_bindings

        # --- Invariant 1: no duplicate ids across full set ---
        all_ids = [b.id for b in all_bindings]
        assert len(all_ids) == len(set(all_ids)), (
            f"Duplicate binding ids found; total={len(all_ids)}, "
            f"unique={len(set(all_ids))}"
        )

        # --- Invariant 2: bear statewide binding id is byte-identical to S03.6.1 locked value ---
        bear_id = "US-MT-MT-STATEWIDE-bear-bear-2026-primary_unit-MT-STATEWIDE-geom"
        assert bear_id in set(all_ids), (
            f"Bear statewide binding id {bear_id!r} not found in output ids. "
            f"S03.6.1 UPSERT no-op guarantee has drifted."
        )

        # --- Invariant 3: every binding's role is a DDL-permitted value ---
        _valid_roles = frozenset({
            "primary_unit", "portion", "restricted_area", "cwd_management_zone",
            "bear_management_unit", "block_management_area", "other_overlay",
        })
        for b in all_bindings:
            assert b.role in _valid_roles, (
                f"Binding {b.id!r} has invalid role {b.role!r}"
            )

        # --- Invariant 4: no binding has a `confidence` attribute ---
        # JurisdictionBinding has no confidence column per ADR-017 §2.
        for b in all_bindings:
            assert not hasattr(b, "confidence"), (
                f"Binding {b.id!r} unexpectedly has a `confidence` attribute; "
                f"ADR-017 §2 forbids this column on jurisdiction_binding."
            )

        # --- Invariant 5: statewide bindings are all primary_unit to MT-STATEWIDE-geom ---
        for b in statewide_bindings:
            assert b.role == "primary_unit"
            assert b.geometry_id == "MT-STATEWIDE-geom"

        # --- Invariant 6: all bindings have non-empty ids ---
        for b in all_bindings:
            assert b.id, f"Found binding with empty id: {b!r}"

    def test_bear_statewide_id_is_upsert_noop_with_s036_1(self) -> None:
        """Isolated assertion: the bear statewide binding id from this loader
        must be byte-identical to S03.6.1's locked value so it UPSERTs as a
        no-op rather than producing a duplicate row."""
        bear_rr = self._make_rr("MT-STATEWIDE-bear", "bear")
        source = self._make_source("MT-STATEWIDE-geom")
        bindings = _ljb_module._build_statewide_bindings([bear_rr], source)
        assert len(bindings) == 1
        assert bindings[0].id == "US-MT-MT-STATEWIDE-bear-bear-2026-primary_unit-MT-STATEWIDE-geom"


# ---------------------------------------------------------------------------
# TestUpsertIdempotency (T12)
# ---------------------------------------------------------------------------


class TestUpsertIdempotency:
    """Verify that re-running main() with unchanged data produces byte-identical
    upsert calls in the same order.

    The bear binding from S03.6.1 is the canonical proof case: it was written
    by load_regulation_records.py and this loader must re-derive the same id
    and UPSERT it as a no-op rather than creating a duplicate.
    """

    def _make_conn_mock(self) -> MagicMock:
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    def _synthetic_bindings(self, n: int = 770) -> list[JurisdictionBinding]:
        source = _make_minimal_source()
        return [
            JurisdictionBinding(
                id=f"US-MT-MT-HD-deer-elk-lion-{i}-elk-2026-primary_unit-MT-HD-deer-elk-lion-{i}-geom",
                regulation_record_state="US-MT",
                regulation_record_jurisdiction_code=f"MT-HD-deer-elk-lion-{i}",
                regulation_record_species_group="elk",
                regulation_record_license_year=2026,
                geometry_id=f"MT-HD-deer-elk-lion-{i}-geom",
                role="primary_unit",
                verbatim_rule=None,
                source=source,
            )
            for i in range(n)
        ]

    def test_main_run_twice_produces_byte_identical_upsert_calls(self) -> None:
        """Re-running main() with unchanged data must produce the same upsert
        call arguments in the same order — no id drift across runs."""
        synthetic_bindings = self._synthetic_bindings(770)

        upsert_calls_run1: list[str] = []
        upsert_calls_run2: list[str] = []

        def _capture_run1(conn: object, binding: JurisdictionBinding) -> None:
            upsert_calls_run1.append(binding.id)

        def _capture_run2(conn: object, binding: JurisdictionBinding) -> None:
            upsert_calls_run2.append(binding.id)

        conn_mock = self._make_conn_mock()

        # Run 1
        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=_make_minimal_statewide_reg_records()), \
             patch.object(_ljb, "_fetch_geometry_sources", return_value={
                 _ljb._MT_STATEWIDE_GEOM_ID: _make_minimal_source(),
             }), \
             patch.object(_ljb, "_build_statewide_bindings", return_value=[]), \
             patch.object(_ljb, "_build_overlay_bindings", return_value=[]), \
             patch.object(_ljb, "_build_no_hunt_zone_bindings", return_value=synthetic_bindings), \
             patch.object(_db_module, "upsert_jurisdiction_binding", side_effect=_capture_run1):
            result1 = _ljb.main([])
        assert result1 == 0

        conn_mock2 = self._make_conn_mock()

        # Run 2 — same synthetic input, different capture list
        with patch.object(_db_module, "connect", return_value=conn_mock2), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=_make_minimal_statewide_reg_records()), \
             patch.object(_ljb, "_fetch_geometry_sources", return_value={
                 _ljb._MT_STATEWIDE_GEOM_ID: _make_minimal_source(),
             }), \
             patch.object(_ljb, "_build_statewide_bindings", return_value=[]), \
             patch.object(_ljb, "_build_overlay_bindings", return_value=[]), \
             patch.object(_ljb, "_build_no_hunt_zone_bindings", return_value=synthetic_bindings), \
             patch.object(_db_module, "upsert_jurisdiction_binding", side_effect=_capture_run2):
            result2 = _ljb.main([])
        assert result2 == 0

        # Both runs must produce identical id sequences
        assert upsert_calls_run1 == upsert_calls_run2, (
            f"Upsert call ids differ between run 1 and run 2. "
            f"First mismatch at index: "
            f"{next(i for i, (a, b) in enumerate(zip(upsert_calls_run1, upsert_calls_run2)) if a != b)}"
        )
        assert len(upsert_calls_run1) == 770


# ---------------------------------------------------------------------------
# TestAtomicTransaction (T12)
# ---------------------------------------------------------------------------


class TestAtomicTransaction:
    """Verify that a mid-write exception triggers rollback and suppresses commit.

    Note: TestMain::test_write_exception_triggers_rollback_not_commit (T10)
    already covers this invariant with an exception on the FIRST upsert call.
    This class adds a complementary variant that raises on the 50th call to
    confirm the rollback invariant holds even after partial write progress —
    i.e., it's not coincidentally passing because no upserts ran at all.
    Both tests are intentionally kept because they test distinct failure modes:
    T10 = immediate failure; T12 = partial-progress failure.
    """

    def _make_conn_mock(self) -> MagicMock:
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    def test_main_forces_rollback_on_mid_write_exception(self) -> None:
        """Force upsert_jurisdiction_binding to raise on the 50th call;
        assert rollback() called and commit() NOT called."""
        conn_mock = self._make_conn_mock()
        source = _make_minimal_source()
        n_bindings = 770
        synthetic_bindings = [
            JurisdictionBinding(
                id=f"US-MT-MT-HD-deer-elk-lion-{i}-elk-2026-primary_unit-MT-HD-deer-elk-lion-{i}-geom",
                regulation_record_state="US-MT",
                regulation_record_jurisdiction_code=f"MT-HD-deer-elk-lion-{i}",
                regulation_record_species_group="elk",
                regulation_record_license_year=2026,
                geometry_id=f"MT-HD-deer-elk-lion-{i}-geom",
                role="primary_unit",
                verbatim_rule=None,
                source=source,
            )
            for i in range(n_bindings)
        ]

        call_count = 0

        def _raise_on_50th(conn: object, binding: JurisdictionBinding) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 50:
                raise RuntimeError("simulated mid-write DB error on call 50")

        with patch.object(_db_module, "connect", return_value=conn_mock), \
             patch.object(_ljb, "_query_all_montana_regulation_records", return_value=_make_minimal_statewide_reg_records()), \
             patch.object(_ljb, "_fetch_geometry_sources", return_value={
                 _ljb._MT_STATEWIDE_GEOM_ID: _make_minimal_source(),
             }), \
             patch.object(_ljb, "_build_statewide_bindings", return_value=[]), \
             patch.object(_ljb, "_build_overlay_bindings", return_value=[]), \
             patch.object(_ljb, "_build_no_hunt_zone_bindings", return_value=synthetic_bindings), \
             patch.object(_db_module, "upsert_jurisdiction_binding", side_effect=_raise_on_50th):
            with pytest.raises(RuntimeError, match="simulated mid-write DB error on call 50"):
                _ljb.main([])

        conn_mock.rollback.assert_called_once()
        conn_mock.commit.assert_not_called()
        # Confirm 49 successful calls before the 50th raised
        assert call_count == 50


# ---------------------------------------------------------------------------
# TestIdStability (T13)
# ---------------------------------------------------------------------------


from states.montana.load_jurisdiction_bindings import (  # noqa: E402
    _build_statewide_bindings as _statewide_builder,
    _build_overlay_bindings as _overlay_builder,
)
from states.montana.load_regulation_records import (  # noqa: E402
    _JURISDICTION_BINDING_ID_FORMAT,
)


class TestIdStability:
    """Lock the id format string + assert specific known-id values.

    These ids are load-bearing for UPSERT idempotency:
    - The bear binding id was written by S03.6.1 and MUST match this loader's
      re-derivation exactly; any drift creates a duplicate row.
    - The antelope and representative HD ids confirm the full format is stable.

    If test_id_format_string_is_canonical fails:
        - Coordinate the change across load_regulation_records._JURISDICTION_BINDING_ID_FORMAT
          (line 116), load_jurisdiction_bindings (imports it), the S03.6.1 test
          (TestBuildStatewideBearBinding::test_id_encoding_is_deterministic), and
          every locked literal below.
    """

    @staticmethod
    def _make_rr(jurisdiction_code: str, species_group: str) -> RegulationRecord:
        return RegulationRecord(
            state="US-MT",
            jurisdiction_code=jurisdiction_code,
            species_group=species_group,
            license_year=2026,
            source=SourceCitation(
                id="test-citation",
                agency="MT FWP",
                title="Test",
                url="https://example.com",
                publication_date="2026-01-01",
                document_type="annual_regulations",
            ),
            confidence="high",
        )

    @staticmethod
    def _make_source() -> SourceCitation:
        return SourceCitation(
            id="mt-fwp-gis-layer-2026",
            agency="MT FWP",
            title="MT GIS Layer",
            url="https://gisservicemt.gov/arcgis/rest/services/example/FeatureServer/0",
            publication_date="2026-01-01",
            document_type="gis_layer",
        )

    def test_id_format_string_is_canonical(self) -> None:
        """The format string imported from load_regulation_records MUST equal
        this literal.  If this assertion fires, the id format has drifted from
        S03.6.1's locked value.  Requires coordinated update across:
          - load_regulation_records._JURISDICTION_BINDING_ID_FORMAT
          - load_jurisdiction_bindings (which imports it)
          - TestBuildStatewideBearBinding::test_id_encoding_is_deterministic
          - All locked id literals in this class
        """
        assert _JURISDICTION_BINDING_ID_FORMAT == (
            "{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"
        )

    def test_statewide_bear_id_locked(self) -> None:
        """S03.6.1 bear binding id MUST match exactly so this loader UPSERTs it
        rather than creating a duplicate row."""
        bear_rr = self._make_rr("MT-STATEWIDE-bear", "bear")
        source = self._make_source()
        bindings = _statewide_builder([bear_rr], source)
        assert len(bindings) == 1
        assert bindings[0].id == (
            "US-MT-MT-STATEWIDE-bear-bear-2026-primary_unit-MT-STATEWIDE-geom"
        )

    def test_statewide_antelope_id_format(self) -> None:
        """Antelope statewide binding — the MT-STATEWIDE-antelope anchor first
        written in this loader (S03.6.1 intentionally deferred it)."""
        antelope_rr = self._make_rr("MT-STATEWIDE-antelope", "pronghorn")
        source = self._make_source()
        bindings = _statewide_builder([antelope_rr], source)
        assert len(bindings) == 1
        assert bindings[0].id == (
            "US-MT-MT-STATEWIDE-antelope-pronghorn-2026-primary_unit-MT-STATEWIDE-geom"
        )

    def test_representative_overlay_binding_id(self) -> None:
        """HD 262 elk self-row binding — the canonical AC #1091 UAT spot-check HD."""
        elk_rr = self._make_rr("MT-HD-deer-elk-lion-262", "elk")
        parent_gid = "MT-HD-deer-elk-lion-262-geom"
        overlay = [
            _OverlayRow(
                parent_geometry_id=parent_gid,
                child_geometry_id=parent_gid,
                parent_kind="hunting_district",
                child_kind="hunting_district",
                relationship="contains",
                role_for_e03="primary_unit",
            )
        ]
        source = self._make_source()
        bindings = _overlay_builder([elk_rr], overlay, {parent_gid: source})
        assert len(bindings) == 1
        expected = (
            "US-MT-MT-HD-deer-elk-lion-262-elk-2026-primary_unit-MT-HD-deer-elk-lion-262-geom"
        )
        assert bindings[0].id == expected, (
            f"Expected {expected!r} but got {bindings[0].id!r}"
        )

    def test_format_string_produces_ids_without_binding_literal(self) -> None:
        """Spec line 1045 had a stale format including '-binding-'; the shipped
        format does NOT include this literal.  If this assertion fails, the
        spec's stale format crept back in."""
        bear_rr = self._make_rr("MT-STATEWIDE-bear", "bear")
        source = self._make_source()
        bindings = _statewide_builder([bear_rr], source)
        assert "-binding-" not in bindings[0].id, (
            f"id {bindings[0].id!r} contains '-binding-' literal from the stale "
            f"spec format; shipped format has no '-binding-' substring."
        )
