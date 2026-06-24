"""Unit tests for states.colorado.load_seasons_and_licenses — T10/T11.

Covers (Part 1 — T10: pure functions and structural guards):
- TestSeasonDefinitionId      — exact-output lock for _co_season_definition_id
- TestLicenseTagId            — exact-output lock for _co_license_tag_id
- TestSeasonName              — exact-output lock for _co_season_name
- TestParseCoWindow           — null / parseable / year-wrap / embedded-year / ValueError
- TestBigGameLicenseKind      — A/B/C/None branches + ValueError
- TestBearLicenseKind         — limited_draw + 4 OTC variants + ValueError
- TestResidency               — valid pass-through + ValueError on unknown
- TestWindowWeaponType        — non-X single-weapon, X multi-weapon, ValueError
- TestVerbatimRule            — row extras wins, section fallback, raises when both empty
- TestParseQuotaRange         — parseable / None / empty / malformed ValueError
- TestDriftGuardCallSites     — AST: exactly 4 _build_* entity builders, all instrumented
- TestLinkTableNotInstrumented — AST: link builders + _iter have no assert_id_matches ref
- TestNoStateAdapterImports   — AST: no other-state adapter imports (ADR-005)

Covers (Part 2 — T11: builders, links, asymmetric-coverage criterion, guards, main):
- TestBuildBigGameSeasonDefinitions — builder count, per-window weapon_type, Season Choice fan-out,
                                      null-window WARNING skip, first-occurrence-wins dedup
- TestBuildBigGameLicenseTags       — kind from list_value, weapon_types, draw_spec_key=None,
                                      species/purchase_url/license_code pass-through
- TestBuildBearBuilders             — only section records produce rows; species=="bear" not
                                      "black_bear"; non-section records are skipped
- TestBuildLinks                    — license_season links tag to each season; regulation_season
                                      and regulation_license use CO-GMU-{int} jurisdiction_code;
                                      no deer fan-out (contrast MT)
- TestAsymmetricCoverageM2Criterion — PRD 002 SC #2: GMU 001 mule_deer has ≥3 distinct seasons
                                      spanning archery/muzzleloader/rifle; regulation_season links
                                      single (CO-GMU-1, mule_deer) regulation_record to all 3
- TestCountGuards                   — _check_count_band passes in-band, raises below low / above high
- TestMain                          — --dry-run returns 0 against real artifacts; mocked-write
                                      test checks entity upserts before link writes (FK order)
                                      and conn.commit() called exactly once
"""

from __future__ import annotations

import ast
import importlib.util
import logging
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingestion.lib.schema import SourceCitation
from states.colorado import load_seasons_and_licenses as mod


# ---------------------------------------------------------------------------
# Module source path helper (mirrors test_load_co_regulation_records.py)
# ---------------------------------------------------------------------------


def _loader_source_path() -> Path:
    spec = importlib.util.find_spec("states.colorado.load_seasons_and_licenses")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin)


# ---------------------------------------------------------------------------
# TestSeasonDefinitionId
# ---------------------------------------------------------------------------


class TestSeasonDefinitionId:
    """Exact-output lock for _co_season_definition_id.

    Verifies:
    - Leading-zero stripping: "001" → int 1 in the id.
    - Different window_index yields a different id (per-window fan-out).
    - Different hunt_code yields a different id.
    - season_code param removed (FIX 4): function takes 4 args not 5.
    """

    def test_exact_output_known_input(self) -> None:
        """Canonical round-trip: species/gmu/hunt_code/window_index → exact id."""
        result = mod._co_season_definition_id(
            "mule_deer", "001", "D-M-001-O1-A", 0
        )
        assert result == "CO-GMU-1-mule_deer-D-M-001-O1-A-w0-2026"

    def test_leading_zero_stripped_from_gmu(self) -> None:
        """Zero-padded GMU "001" and bare "1" produce the same id."""
        padded = mod._co_season_definition_id("elk", "001", "E-M-001-R1-A", 0)
        bare = mod._co_season_definition_id("elk", "1", "E-M-001-R1-A", 0)
        assert padded == bare

    def test_different_window_index_yields_different_id(self) -> None:
        """window_index=0 and window_index=1 on the same hunt_code must differ."""
        id0 = mod._co_season_definition_id("mule_deer", "001", "D-M-001-O1-X", 0)
        id1 = mod._co_season_definition_id("mule_deer", "001", "D-M-001-O1-X", 1)
        assert id0 != id1

    def test_different_hunt_code_yields_different_id(self) -> None:
        """Distinct hunt codes must not collide even for the same GMU/species."""
        id_a = mod._co_season_definition_id("mule_deer", "001", "D-M-001-O1-A", 0)
        id_r = mod._co_season_definition_id("mule_deer", "001", "D-M-001-R1-R", 0)
        assert id_a != id_r

    def test_season_code_not_a_parameter(self) -> None:
        """_co_season_definition_id takes exactly 4 positional args (no season_code).

        FIX 4: season_code was removed as a parameter because hunt_code already
        encodes it. Calling with 5 positional args must raise TypeError.
        """
        import inspect
        sig = inspect.signature(mod._co_season_definition_id)
        param_names = list(sig.parameters.keys())
        assert "season_code" not in param_names, (
            "_co_season_definition_id must not have a season_code parameter (FIX 4)"
        )
        assert len(param_names) == 4, (
            f"Expected 4 params (species_group, gmu_code, hunt_code, window_index); "
            f"got {param_names}"
        )


# ---------------------------------------------------------------------------
# TestLicenseTagId
# ---------------------------------------------------------------------------


class TestLicenseTagId:
    """Exact-output lock for _co_license_tag_id.

    Verifies:
    - Exact canonical id string.
    - UPSERT stability: same inputs always produce the same id.
    """

    def test_exact_output_known_input(self) -> None:
        """Canonical round-trip: species/gmu/hunt_code → exact id."""
        result = mod._co_license_tag_id("mule_deer", "001", "D-M-001-O1-A")
        assert result == "CO-GMU-1-mule_deer-D-M-001-O1-A-2026"

    def test_leading_zero_stripped_from_gmu(self) -> None:
        """Zero-padded "001" and bare "1" produce the same tag id."""
        padded = mod._co_license_tag_id("elk", "001", "E-M-001-R1-A")
        bare = mod._co_license_tag_id("elk", "1", "E-M-001-R1-A")
        assert padded == bare

    def test_same_inputs_same_id_upsert_stability(self) -> None:
        """Calling the function twice with identical args returns the same id."""
        first = mod._co_license_tag_id("bear", "082", "B-E-082-R1-R")
        second = mod._co_license_tag_id("bear", "082", "B-E-082-R1-R")
        assert first == second


# ---------------------------------------------------------------------------
# TestSeasonName
# ---------------------------------------------------------------------------


class TestSeasonName:
    """Exact-output lock for _co_season_name."""

    def test_mule_deer_archery_o1(self) -> None:
        """Canonical case: mule_deer + archery + O1."""
        assert mod._co_season_name("mule_deer", "archery", "O1") == "Mule Deer Archery (O1)"

    def test_elk_any_legal_weapon_r1(self) -> None:
        """Multi-word method_group underscores become Title Case spaces."""
        assert mod._co_season_name("elk", "any_legal_weapon", "R1") == "Elk Any Legal Weapon (R1)"

    def test_bear_rifle_r2(self) -> None:
        """Bear species renders as 'Bear' (no underscore)."""
        assert mod._co_season_name("bear", "rifle", "R2") == "Bear Rifle (R2)"

    def test_pronghorn_muzzleloader_m1(self) -> None:
        """Pronghorn renders correctly."""
        assert mod._co_season_name("pronghorn", "muzzleloader", "M1") == "Pronghorn Muzzleloader (M1)"


# ---------------------------------------------------------------------------
# TestParseCoWindow
# ---------------------------------------------------------------------------


class TestParseCoWindow:
    """Covers null case, parseable cases, year-wrap, embedded year suffix, and ValueError."""

    def test_none_start_returns_none(self) -> None:
        """start_date=None → returns None (null-window skip)."""
        window = {"start_date": None, "end_date": "Sept. 30", "raw_text": "null window"}
        assert mod._parse_co_window(window, 2026) is None

    def test_none_end_returns_none(self) -> None:
        """end_date=None → returns None (null-window skip)."""
        window = {"start_date": "Sept. 2", "end_date": None, "raw_text": "null window"}
        assert mod._parse_co_window(window, 2026) is None

    def test_both_none_returns_none(self) -> None:
        """Both None → returns None (null-window skip)."""
        window = {"start_date": None, "end_date": None, "raw_text": "New"}
        assert mod._parse_co_window(window, 2026) is None

    def test_parseable_dotted_month(self) -> None:
        """Standard dotted-month case: Sept. 2 – Sept. 30."""
        window = {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"}
        result = mod._parse_co_window(window, 2026)
        assert result is not None
        opens, closes = result
        assert opens == date(2026, 9, 2)
        assert closes == date(2026, 9, 30)

    def test_parseable_october_window(self) -> None:
        """Oct. abbreviation parsed correctly."""
        window = {"start_date": "Oct. 1", "end_date": "Oct. 31", "raw_text": "Oct. 1-31"}
        result = mod._parse_co_window(window, 2026)
        assert result is not None
        opens, closes = result
        assert opens == date(2026, 10, 1)
        assert closes == date(2026, 10, 31)

    def test_year_wrap_december_january(self) -> None:
        """Season opens in Dec, closes in Jan → closes year is license_year + 1."""
        window = {
            "start_date": "Dec. 1",
            "end_date": "Jan. 15",
            "raw_text": "Dec. 1-Jan. 15",
        }
        result = mod._parse_co_window(window, 2026)
        assert result is not None
        opens, closes = result
        assert opens == date(2026, 12, 1)
        assert closes == date(2027, 1, 15)

    def test_embedded_year_suffix_stripped(self) -> None:
        """end_date like 'Jan. 31, 2027' strips the year and parses correctly."""
        window = {
            "start_date": "Dec. 5",
            "end_date": "Jan. 31, 2027",
            "raw_text": "Dec. 5-Jan. 31, 2027",
        }
        result = mod._parse_co_window(window, 2026)
        assert result is not None
        opens, closes = result
        assert opens == date(2026, 12, 5)
        assert closes == date(2027, 1, 31)

    def test_garbage_start_date_raises_value_error(self) -> None:
        """A non-null, non-parseable start_date fragment raises ValueError."""
        window = {
            "start_date": "GARBAGE",
            "end_date": "Sept. 30",
            "raw_text": "GARBAGE-Sept. 30",
        }
        with pytest.raises(ValueError, match="unparseable start_date"):
            mod._parse_co_window(window, 2026)

    def test_garbage_end_date_raises_value_error(self) -> None:
        """A non-null, non-parseable end_date fragment raises ValueError."""
        window = {
            "start_date": "Sept. 2",
            "end_date": "BADDATE",
            "raw_text": "Sept. 2-BADDATE",
        }
        with pytest.raises(ValueError, match="unparseable end_date"):
            mod._parse_co_window(window, 2026)


# ---------------------------------------------------------------------------
# TestBigGameLicenseKind
# ---------------------------------------------------------------------------


class TestBigGameLicenseKind:
    """Covers all list_value branches and ValueError on unknown input."""

    def test_list_a_is_limited_draw(self) -> None:
        assert mod._co_big_game_license_kind("A", "O1") == "limited_draw"

    def test_list_b_is_over_the_counter(self) -> None:
        assert mod._co_big_game_license_kind("B", "O1") == "over_the_counter"

    def test_list_c_is_limited_draw(self) -> None:
        """Season Choice (C) is still draw-required → limited_draw."""
        assert mod._co_big_game_license_kind("C", "O1") == "limited_draw"

    def test_none_is_limited_draw(self) -> None:
        """The single None row (elk GMU 214 W4) maps to limited_draw."""
        assert mod._co_big_game_license_kind(None, "W4") == "limited_draw"

    def test_unrecognized_raises_value_error(self) -> None:
        """An unrecognized list_value raises ValueError with the bad value in the message."""
        with pytest.raises(ValueError, match="unrecognized list_value"):
            mod._co_big_game_license_kind("Z", "O1")


# ---------------------------------------------------------------------------
# TestBearLicenseKind
# ---------------------------------------------------------------------------


class TestBearLicenseKind:
    """Covers limited_draw pass-through, all four OTC variants, and ValueError."""

    def test_limited_draw_passthrough(self) -> None:
        assert mod._co_bear_license_kind("limited_draw") == "limited_draw"

    def test_over_the_counter_passthrough(self) -> None:
        assert mod._co_bear_license_kind("over_the_counter") == "over_the_counter"

    def test_add_on_otc_maps_to_over_the_counter(self) -> None:
        assert mod._co_bear_license_kind("add_on_otc") == "over_the_counter"

    def test_plains_otc_maps_to_over_the_counter(self) -> None:
        assert mod._co_bear_license_kind("plains_otc") == "over_the_counter"

    def test_private_land_otc_maps_to_over_the_counter(self) -> None:
        assert mod._co_bear_license_kind("private_land_otc") == "over_the_counter"

    def test_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unrecognized license_kind"):
            mod._co_bear_license_kind("mystery_otc")


# ---------------------------------------------------------------------------
# TestResidency
# ---------------------------------------------------------------------------


class TestResidency:
    """Validates Residency pass-through and ValueError on non-member strings."""

    def test_both_passes(self) -> None:
        assert mod._co_residency("both") == "both"

    def test_nonresident_passes(self) -> None:
        assert mod._co_residency("nonresident") == "nonresident"

    def test_resident_passes(self) -> None:
        assert mod._co_residency("resident") == "resident"

    def test_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unrecognized scope"):
            mod._co_residency("alien")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unrecognized scope"):
            mod._co_residency("")


# ---------------------------------------------------------------------------
# TestWindowWeaponType
# ---------------------------------------------------------------------------


class TestWindowWeaponType:
    """Covers non-X single-weapon, Season Choice multi-weapon indexing, and ValueError."""

    def _make_row(self, weapon_types: list[str]) -> dict:  # type: ignore[type-arg]
        return {"weapon_types": weapon_types, "method_letter": "A" if len(weapon_types) == 1 else "X"}

    def test_single_weapon_row_returns_weapon_types_zero(self) -> None:
        """Non-X row (1 weapon): weapon_types[0] is returned regardless of window_index."""
        row = self._make_row(["archery"])
        assert mod._co_window_weapon_type(row, 0) == "archery"

    def test_single_weapon_rifle_row(self) -> None:
        row = self._make_row(["any_legal_weapon"])
        assert mod._co_window_weapon_type(row, 0) == "any_legal_weapon"

    def test_x_row_index_0_returns_archery(self) -> None:
        """Season Choice row: window_index=0 → archery."""
        row = self._make_row(["archery", "muzzleloader", "any_legal_weapon"])
        assert mod._co_window_weapon_type(row, 0) == "archery"

    def test_x_row_index_1_returns_muzzleloader(self) -> None:
        """Season Choice row: window_index=1 → muzzleloader."""
        row = self._make_row(["archery", "muzzleloader", "any_legal_weapon"])
        assert mod._co_window_weapon_type(row, 1) == "muzzleloader"

    def test_x_row_index_2_returns_any_legal_weapon(self) -> None:
        """Season Choice row: window_index=2 → any_legal_weapon."""
        row = self._make_row(["archery", "muzzleloader", "any_legal_weapon"])
        assert mod._co_window_weapon_type(row, 2) == "any_legal_weapon"

    def test_bogus_weapon_string_raises_value_error(self) -> None:
        """A weapon type string not in the WeaponType Literal raises ValueError."""
        row = self._make_row(["laser_cannon"])
        with pytest.raises(ValueError, match="not a valid WeaponType"):
            mod._co_window_weapon_type(row, 0)


# ---------------------------------------------------------------------------
# TestVerbatimRule
# ---------------------------------------------------------------------------


class TestVerbatimRule:
    """Covers row-extras-wins, section-fallback, and raises-when-both-empty."""

    def test_row_extras_wins_over_section_verbatim(self) -> None:
        """Non-empty row extras is returned, ignoring section verbatim_text."""
        row = {"extras": "First and only choice.", "hunt_code": "D-M-001-O1-A"}
        section = {"verbatim_text": "This is the section verbatim.", "gmu_code": "001"}
        assert mod._select_co_verbatim_rule(row, section) == "First and only choice."

    def test_row_extras_stripped(self) -> None:
        """Row extras with trailing whitespace is stripped."""
        row = {"extras": "  Season note.  ", "hunt_code": "D-M-001-O1-A"}
        section = {"verbatim_text": "Section text.", "gmu_code": "001"}
        assert mod._select_co_verbatim_rule(row, section) == "Season note."

    def test_empty_extras_falls_back_to_section_verbatim(self) -> None:
        """Empty string extras falls back to section verbatim_text."""
        row = {"extras": "", "hunt_code": "D-M-001-O1-A"}
        section = {"verbatim_text": "Unit 001 archery deer.", "gmu_code": "001"}
        assert mod._select_co_verbatim_rule(row, section) == "Unit 001 archery deer."

    def test_none_extras_falls_back_to_section_verbatim(self) -> None:
        """None extras falls back to section verbatim_text."""
        row = {"hunt_code": "D-M-001-O1-A"}
        section = {"verbatim_text": "Verbatim section text.", "gmu_code": "001"}
        assert mod._select_co_verbatim_rule(row, section) == "Verbatim section text."

    def test_both_empty_raises_value_error(self) -> None:
        """Both row extras and section verbatim_text empty/absent → ValueError."""
        row = {"extras": "", "hunt_code": "D-M-001-O1-A"}
        section = {"verbatim_text": "", "gmu_code": "001"}
        with pytest.raises(ValueError, match="both row 'extras' and section 'verbatim_text'"):
            mod._select_co_verbatim_rule(row, section)

    def test_both_absent_raises_value_error(self) -> None:
        """Neither extras nor verbatim_text present → ValueError."""
        row = {"hunt_code": "D-M-001-O1-A"}
        section = {"gmu_code": "001"}
        with pytest.raises(ValueError, match="both row 'extras' and section 'verbatim_text'"):
            mod._select_co_verbatim_rule(row, section)


# ---------------------------------------------------------------------------
# TestParseQuotaRange
# ---------------------------------------------------------------------------


class TestParseQuotaRange:
    """Covers parseable strings, None, empty, and malformed ValueError."""

    def test_hyphen_range_parses_correctly(self) -> None:
        assert mod._parse_quota_range("1-50") == (1, 50)

    def test_large_range_with_comma_thousands(self) -> None:
        """Comma thousand-separators are stripped before int conversion."""
        assert mod._parse_quota_range("1,000-5,000") == (1000, 5000)

    def test_none_returns_none(self) -> None:
        assert mod._parse_quota_range(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert mod._parse_quota_range("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert mod._parse_quota_range("   ") is None

    def test_malformed_no_hyphen_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="expected exactly one '-' separator"):
            mod._parse_quota_range("abc")

    def test_malformed_two_hyphens_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="expected exactly one '-' separator"):
            mod._parse_quota_range("1-2-3")

    def test_non_numeric_parts_raise_value_error(self) -> None:
        """Non-integer parts raise ValueError from int() conversion."""
        with pytest.raises(ValueError):
            mod._parse_quota_range("a-b")


# ---------------------------------------------------------------------------
# TestDriftGuardCallSites
# ---------------------------------------------------------------------------


class TestDriftGuardCallSites:
    """AST walk: exactly 4 _build_* entity builders, all instrumented with assert_id_matches.

    Locks ADR-020: every per-row entity-construction site in the four season_definition
    and license_tag builders must call assert_id_matches. A future builder added without
    the call will fail this test.

    The four expected entity builders are:
      - _build_big_game_season_definitions
      - _build_big_game_license_tags
      - _build_bear_season_definitions
      - _build_bear_license_tags
    """

    _EXPECTED_ENTITY_BUILDERS = frozenset(
        {
            "_build_big_game_season_definitions",
            "_build_big_game_license_tags",
            "_build_bear_season_definitions",
            "_build_bear_license_tags",
        }
    )

    def _parse_module(self) -> ast.Module:
        source = _loader_source_path().read_text(encoding="utf-8")
        return ast.parse(source, filename=str(_loader_source_path()))

    def _has_assert_id_matches_call(self, func_node: ast.FunctionDef) -> bool:
        """Return True iff the function body contains an assert_id_matches(...) call."""
        for child in ast.walk(func_node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            # Direct call: assert_id_matches(...)
            if isinstance(func, ast.Name) and func.id == "assert_id_matches":
                return True
        return False

    def test_exactly_four_entity_builders_exist(self) -> None:
        """The module defines exactly the 4 expected _build_* entity-builder functions."""
        tree = self._parse_module()
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in self._EXPECTED_ENTITY_BUILDERS:
                found.add(node.name)
        assert found == self._EXPECTED_ENTITY_BUILDERS, (
            f"Expected entity builders {self._EXPECTED_ENTITY_BUILDERS}, found {found}"
        )

    def test_all_four_entity_builders_have_assert_id_matches(self) -> None:
        """Every one of the 4 entity builders contains an assert_id_matches call."""
        tree = self._parse_module()
        missing: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name not in self._EXPECTED_ENTITY_BUILDERS:
                continue
            if not self._has_assert_id_matches_call(node):
                missing.append(node.name)
        assert not missing, (
            f"Entity builder(s) missing assert_id_matches call: {missing}. "
            "ADR-020 requires every per-row entity-construction site to call "
            "assert_id_matches."
        )

    def test_big_game_season_definitions_is_instrumented(self) -> None:
        """_build_big_game_season_definitions contains assert_id_matches."""
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_big_game_season_definitions":
                assert self._has_assert_id_matches_call(node)
                return
        pytest.fail("_build_big_game_season_definitions not found in module")

    def test_big_game_license_tags_is_instrumented(self) -> None:
        """_build_big_game_license_tags contains assert_id_matches."""
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_big_game_license_tags":
                assert self._has_assert_id_matches_call(node)
                return
        pytest.fail("_build_big_game_license_tags not found in module")

    def test_bear_season_definitions_is_instrumented(self) -> None:
        """_build_bear_season_definitions contains assert_id_matches."""
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_bear_season_definitions":
                assert self._has_assert_id_matches_call(node)
                return
        pytest.fail("_build_bear_season_definitions not found in module")

    def test_bear_license_tags_is_instrumented(self) -> None:
        """_build_bear_license_tags contains assert_id_matches."""
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_bear_license_tags":
                assert self._has_assert_id_matches_call(node)
                return
        pytest.fail("_build_bear_license_tags not found in module")


# ---------------------------------------------------------------------------
# TestLinkTableNotInstrumented
# ---------------------------------------------------------------------------


class TestLinkTableNotInstrumented:
    """AST walk: link builders and _iter_co_entity_rows must NOT call assert_id_matches.

    Locks the ADR-020 carve-out: link tables carry no id-text PK so drift-guard
    instrumentation is forbidden. The carve-out is documented in the adapter's
    module docstring.
    """

    _LINK_FUNCTIONS = frozenset(
        {
            "_build_license_seasons",
            "_build_regulation_seasons",
            "_build_regulation_licenses",
            "_iter_co_entity_rows",
        }
    )

    def _parse_module(self) -> ast.Module:
        source = _loader_source_path().read_text(encoding="utf-8")
        return ast.parse(source, filename=str(_loader_source_path()))

    def _has_assert_id_matches_call(self, func_node: ast.FunctionDef) -> bool:
        for child in ast.walk(func_node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Name) and func.id == "assert_id_matches":
                return True
        return False

    def _has_drift_guard_name_ref(self, func_node: ast.FunctionDef) -> bool:
        """Return True iff the function body references a Name 'drift_guard' or 'assert_id_matches'."""
        for child in ast.walk(func_node):
            if isinstance(child, ast.Name) and child.id in ("drift_guard", "assert_id_matches"):
                return True
        return False

    def test_build_license_seasons_not_instrumented(self) -> None:
        """_build_license_seasons must not contain assert_id_matches."""
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_license_seasons":
                assert not self._has_assert_id_matches_call(node), (
                    "_build_license_seasons must NOT call assert_id_matches "
                    "(ADR-020 carve-out for link tables)"
                )
                return
        pytest.fail("_build_license_seasons not found in module")

    def test_build_regulation_seasons_not_instrumented(self) -> None:
        """_build_regulation_seasons must not contain assert_id_matches."""
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_regulation_seasons":
                assert not self._has_assert_id_matches_call(node), (
                    "_build_regulation_seasons must NOT call assert_id_matches"
                )
                return
        pytest.fail("_build_regulation_seasons not found in module")

    def test_build_regulation_licenses_not_instrumented(self) -> None:
        """_build_regulation_licenses must not contain assert_id_matches."""
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_regulation_licenses":
                assert not self._has_assert_id_matches_call(node), (
                    "_build_regulation_licenses must NOT call assert_id_matches"
                )
                return
        pytest.fail("_build_regulation_licenses not found in module")

    def test_iter_co_entity_rows_not_instrumented(self) -> None:
        """_iter_co_entity_rows must not contain assert_id_matches."""
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_iter_co_entity_rows":
                assert not self._has_assert_id_matches_call(node), (
                    "_iter_co_entity_rows must NOT call assert_id_matches"
                )
                return
        pytest.fail("_iter_co_entity_rows not found in module")

    def test_all_link_functions_absent_of_assert_id_matches(self) -> None:
        """Batch check: none of the 4 link functions contain assert_id_matches calls."""
        tree = self._parse_module()
        violations: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name not in self._LINK_FUNCTIONS:
                continue
            if self._has_assert_id_matches_call(node):
                violations.append(node.name)
        assert not violations, (
            f"Link function(s) contain assert_id_matches calls (ADR-020 carve-out violated): "
            f"{violations}"
        )


# ---------------------------------------------------------------------------
# TestNoStateAdapterImports
# ---------------------------------------------------------------------------


class TestNoStateAdapterImports:
    """AST guard: load_seasons_and_licenses.py must not import any non-Colorado state adapter.

    CO → CO imports (states.colorado.*) are permitted — the adapter imports
    _STATE and _co_gmu_jurisdiction_code from states.colorado.load_regulation_records.
    All other state adapters are forbidden per ADR-005 state-isolation discipline.
    """

    def _parse_module(self) -> ast.Module:
        source = _loader_source_path().read_text(encoding="utf-8")
        return ast.parse(source, filename=str(_loader_source_path()))

    def _is_forbidden(self, module: str) -> bool:
        """Return True iff module refers to a non-Colorado state adapter."""
        for root in ("states.", "ingestion.states."):
            if module.startswith(root):
                sibling = module[len(root):].split(".", 1)[0]
                if sibling != "colorado":
                    return True
        return False

    def test_no_montana_imports(self) -> None:
        """load_seasons_and_licenses.py must not import from states.montana."""
        tree = self._parse_module()
        forbidden_prefixes = ("states.montana", "ingestion.states.montana")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"load_seasons_and_licenses.py has forbidden import: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for prefix in forbidden_prefixes:
                    assert not module.startswith(prefix), (
                        f"load_seasons_and_licenses.py has forbidden from-import: from {module}"
                    )

    def test_no_other_state_adapter_imports(self) -> None:
        """load_seasons_and_licenses.py must not import any non-Colorado state adapter.

        CO → CO imports (states.colorado.*) are permitted — the adapter
        imports from states.colorado.load_regulation_records (same state).
        Any other state adapter is forbidden per ADR-005.
        """
        tree = self._parse_module()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not self._is_forbidden(alias.name), (
                        f"load_seasons_and_licenses.py imports a non-Colorado state "
                        f"adapter: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not self._is_forbidden(module), (
                    f"load_seasons_and_licenses.py imports a non-Colorado state "
                    f"adapter: from {module}"
                )

    def test_co_to_co_import_is_permitted(self) -> None:
        """Confirm load_regulation_records (same-state CO) IS imported — guards against over-stripping."""
        tree = self._parse_module()
        found_co_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "load_regulation_records" in module or (
                    module.startswith("states.colorado") and any(
                        alias.name in ("_STATE", "_co_gmu_jurisdiction_code")
                        for alias in node.names
                    )
                ):
                    found_co_import = True
                    break
        assert found_co_import, (
            "Expected import of _STATE/_co_gmu_jurisdiction_code from "
            "states.colorado.load_regulation_records not found — "
            "this test guards that the CO→CO import is present and the "
            "test_no_other_state_adapter_imports guard is not over-stripping."
        )


# ===========================================================================
# T11: builders, links, asymmetric-coverage criterion, guards, main
# ===========================================================================


# ---------------------------------------------------------------------------
# Shared fixtures (T11)
# ---------------------------------------------------------------------------


def _make_citation() -> SourceCitation:
    """Minimal valid annual_regulations citation for testing."""
    return SourceCitation(
        id="co-cpw-big-game-2026-brochure",
        agency="Colorado Parks and Wildlife",
        title="2026 Colorado Big Game Hunting Regulations",
        url="https://spl.cde.state.co.us/artemis/nrserials/nr1431internet/nr14312026internet.pdf",
        publication_date="2026-03-04",
        document_type="annual_regulations",
        supersedes=None,
        page_reference=None,
    )


def _make_section(
    gmu_code: str = "001",
    species_group: str = "mule_deer",
    method_group: str = "archery",
    residency_scope: str = "both",
    verbatim_text: str = "Unit 001 archery mule deer season.",
    rows: list[dict] | None = None,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """Minimal big-game section dict. ``rows`` defaults to a single archery row."""
    if rows is None:
        rows = [
            {
                "hunt_code": f"D-M-{gmu_code}-O1-A",
                "season_code": "O1",
                "gmu_code": gmu_code,
                "list_value": "A",
                "method_letter": "A",
                "season_windows": [
                    {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
                ],
                "weapon_types": ["archery"],
                "residency_scope": None,
                "quota": None,
                "quota_range": None,
                "extras": "",
                "page_reference": {"page_num_1based": 10, "bbox": None,
                                   "pdf_filename": "x.pdf",
                                   "extracted_at": "2026-06-09T00:00:00+00:00"},
            }
        ]
    return {
        "gmu_code": gmu_code,
        "species_group": species_group,
        "method_group": method_group,
        "residency_scope": residency_scope,
        "verbatim_text": verbatim_text,
        "rows": rows,
    }


def _make_bear_record(
    gmu_code: str = "082",
    hunt_code: str = "B-E-082-R1-R",
    record_type: str = "section",
    license_kind: str = "limited_draw",
    verbatim_text: str = "Bear GMU 082 rifle season.",
) -> dict:  # type: ignore[type-arg]
    """Minimal bear record dict with record_type discriminator."""
    row: dict = {  # type: ignore[type-arg]
        "hunt_code": hunt_code,
        "season_code": "R1",
        "gmu_code": gmu_code,
        "weapon_types": ["any_legal_weapon"],
        "method_letter": "R",
        "residency_scope": None,
        "quota": None,
        "quota_range": None,
        "extras": "",
        "season_windows": [
            {"start_date": "Sept. 2", "end_date": "Oct. 31", "raw_text": "Sept. 2 – Oct. 31"},
        ],
        "page_reference": {"page_num_1based": 74, "bbox": None,
                           "pdf_filename": "x.pdf",
                           "extracted_at": "2026-06-09T00:00:00+00:00"},
    }
    return {
        "record_type": record_type,
        "species_group": "black_bear",
        "gmu_code": gmu_code,
        "method_group": "rifle",
        "residency_scope": "both",
        "license_kind": license_kind,
        "verbatim_text": verbatim_text,
        "rows": [row],
    }


def _make_connect_cm(mock_conn: MagicMock) -> MagicMock:
    """Wrap mock_conn so `with db.connect() as conn:` yields mock_conn."""
    connect_cm = MagicMock()
    connect_cm.__enter__ = MagicMock(return_value=mock_conn)
    connect_cm.__exit__ = MagicMock(return_value=False)
    return connect_cm


# ---------------------------------------------------------------------------
# TestBuildBigGameSeasonDefinitions
# ---------------------------------------------------------------------------


class TestBuildBigGameSeasonDefinitions:
    """Builder count, per-window weapon_type, Season Choice fan-out,
    null-window WARNING skip, and first-occurrence-wins dedup."""

    def test_single_archery_row_produces_one_season(self) -> None:
        """A section with one archery row and one window → one SeasonDefinition."""
        cit = _make_citation()
        secs = [_make_section(gmu_code="001", species_group="mule_deer",
                               method_group="archery")]
        result = mod._build_big_game_season_definitions(secs, cit)
        assert len(result) == 1
        sd = result[0]
        assert sd.weapon_type == "archery"
        assert sd.id.startswith("CO-GMU-1-mule_deer")

    def test_season_choice_x_row_fans_out_three_seasons(self) -> None:
        """A Season Choice (method_letter=X) row with 3 windows → 3 SeasonDefinitions,
        one per weapon type (archery, muzzleloader, any_legal_weapon)."""
        cit = _make_citation()
        x_row = {
            "hunt_code": "D-M-001-O1-X",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "C",
            "method_letter": "X",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
                {"start_date": "Oct. 1", "end_date": "Oct. 15", "raw_text": "Oct. 1-15"},
                {"start_date": "Oct. 20", "end_date": "Nov. 5", "raw_text": "Oct. 20 – Nov. 5"},
            ],
            "weapon_types": ["archery", "muzzleloader", "any_legal_weapon"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Season choice row.",
            "page_reference": {"page_num_1based": 12, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        secs = [_make_section(gmu_code="001", species_group="mule_deer",
                               method_group="season_choice", rows=[x_row])]
        result = mod._build_big_game_season_definitions(secs, cit)
        assert len(result) == 3
        weapon_types = {sd.weapon_type for sd in result}
        assert weapon_types == {"archery", "muzzleloader", "any_legal_weapon"}

    def test_null_window_is_skipped_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A null-date window (start_date=None) is skipped and emits a WARNING."""
        cit = _make_citation()
        row = {
            "hunt_code": "D-M-001-O1-A",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "A",
            "method_letter": "A",
            "season_windows": [
                {"start_date": None, "end_date": None, "raw_text": "New"},
                {"start_date": "Oct. 1", "end_date": "Oct. 31", "raw_text": "Oct. 1-31"},
            ],
            "weapon_types": ["archery"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Only one real window.",
            "page_reference": {"page_num_1based": 10, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        secs = [_make_section(gmu_code="001", rows=[row])]
        with caplog.at_level(logging.WARNING):
            result = mod._build_big_game_season_definitions(secs, cit)
        # Only one parseable window → one SeasonDefinition
        assert len(result) == 1
        assert any("null window" in r.message.lower() for r in caplog.records)

    def test_first_occurrence_wins_dedup(self) -> None:
        """Two sections sharing the same hunt_code/gmu/species → only one SeasonDefinition."""
        cit = _make_citation()
        row = {
            "hunt_code": "D-M-001-O1-A",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "A",
            "method_letter": "A",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
            ],
            "weapon_types": ["archery"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "First occurrence.",
            "page_reference": {"page_num_1based": 10, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        sec1 = _make_section(gmu_code="001", rows=[row])
        sec2 = _make_section(gmu_code="001", rows=[row])  # identical id → duplicate
        result = mod._build_big_game_season_definitions([sec1, sec2], cit)
        # The same id appears twice across sections but dedup keeps only one.
        ids = [sd.id for sd in result]
        assert len(ids) == len(set(ids)), "Duplicate season_definition ids after dedup"

    def test_season_definition_id_in_result(self) -> None:
        """Returned SeasonDefinition.id matches _co_season_definition_id output."""
        cit = _make_citation()
        secs = [_make_section(gmu_code="010", species_group="elk",
                               method_group="any_legal_weapon")]
        result = mod._build_big_game_season_definitions(secs, cit)
        assert len(result) == 1
        expected_id = mod._co_season_definition_id("elk", "010", "D-M-010-O1-A", 0)
        assert result[0].id == expected_id


# ---------------------------------------------------------------------------
# TestBuildBigGameLicenseTags
# ---------------------------------------------------------------------------


class TestBuildBigGameLicenseTags:
    """kind from list_value, weapon_types, draw_spec_key=None, species/purchase_url/license_code."""

    def test_list_a_yields_limited_draw_tag(self) -> None:
        """list_value='A' row → LicenseTag.kind == 'limited_draw'."""
        cit = _make_citation()
        secs = [_make_section(gmu_code="001", species_group="elk")]
        result = mod._build_big_game_license_tags(secs, cit)
        assert len(result) == 1
        assert result[0].kind == "limited_draw"

    def test_list_b_yields_over_the_counter_tag(self) -> None:
        """list_value='B' row → LicenseTag.kind == 'over_the_counter'."""
        cit = _make_citation()
        row = {
            "hunt_code": "D-M-001-O1-A",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "B",
            "method_letter": "A",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
            ],
            "weapon_types": ["archery"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "OTC row.",
            "page_reference": {"page_num_1based": 10, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        secs = [_make_section(gmu_code="001", rows=[row])]
        result = mod._build_big_game_license_tags(secs, cit)
        assert result[0].kind == "over_the_counter"

    def test_weapon_types_set_correctly(self) -> None:
        """LicenseTag.weapon_types matches row weapon_types from the artifact."""
        cit = _make_citation()
        secs = [_make_section(gmu_code="001", species_group="mule_deer",
                               method_group="archery")]
        result = mod._build_big_game_license_tags(secs, cit)
        assert result[0].weapon_types == ["archery"]

    def test_draw_spec_key_is_none_on_every_tag(self) -> None:
        """draw_spec_key is always None — S06.8 backfills it later."""
        cit = _make_citation()
        secs = [_make_section(gmu_code="001"), _make_section(gmu_code="002")]
        result = mod._build_big_game_license_tags(secs, cit)
        assert all(lt.draw_spec_key is None for lt in result), (
            "At least one LicenseTag has non-None draw_spec_key; S06.8 backfills."
        )

    def test_species_matches_section_species_group(self) -> None:
        """LicenseTag.species == the section's species_group."""
        cit = _make_citation()
        secs = [_make_section(gmu_code="020", species_group="pronghorn")]
        result = mod._build_big_game_license_tags(secs, cit)
        assert result[0].species == "pronghorn"

    def test_purchase_url_is_module_constant(self) -> None:
        """LicenseTag.purchase_url == mod._PURCHASE_URL."""
        cit = _make_citation()
        secs = [_make_section(gmu_code="001")]
        result = mod._build_big_game_license_tags(secs, cit)
        assert result[0].purchase_url == mod._PURCHASE_URL

    def test_license_code_equals_hunt_code(self) -> None:
        """LicenseTag.license_code is the full CPW hunt code from the row."""
        cit = _make_citation()
        secs = [_make_section(gmu_code="001")]
        result = mod._build_big_game_license_tags(secs, cit)
        assert result[0].license_code == "D-M-001-O1-A"


# ---------------------------------------------------------------------------
# TestBuildBearBuilders
# ---------------------------------------------------------------------------


class TestBuildBearBuilders:
    """Only section records produce rows; species=='bear'; non-section records are skipped."""

    def _bear_flat_list(self) -> list[dict]:  # type: ignore[type-arg]
        """Minimal flat bear artifact list with all three record types."""
        return [
            _make_bear_record(gmu_code="082", record_type="section"),
            {
                "record_type": "statewide_rule",
                "rule_hint": "season_dates_summary",
                "verbatim_text": "Statewide rule text.",
            },
            {
                "record_type": "reporting_obligation",
                "kind": "harvest_report",
                "verbatim_text": "Harvest reporting obligation.",
            },
        ]

    def test_only_section_records_produce_season_definitions(self) -> None:
        """Only record_type='section' records contribute SeasonDefinitions."""
        cit = _make_citation()
        records = self._bear_flat_list()
        result = mod._build_bear_season_definitions(records, cit)
        # 1 section × 1 row × 1 valid window → 1 SeasonDefinition
        assert len(result) == 1

    def test_only_section_records_produce_license_tags(self) -> None:
        """Only record_type='section' records contribute LicenseTags."""
        cit = _make_citation()
        records = self._bear_flat_list()
        result = mod._build_bear_license_tags(records, cit)
        # 1 section × 1 row → 1 LicenseTag
        assert len(result) == 1

    def test_bear_season_definition_species_is_bear_not_black_bear(self) -> None:
        """SeasonDefinition id contains 'bear' not 'black_bear' (DB species key)."""
        cit = _make_citation()
        records = [_make_bear_record(gmu_code="082", record_type="section")]
        result = mod._build_bear_season_definitions(records, cit)
        assert len(result) == 1
        assert "bear" in result[0].id
        assert "black_bear" not in result[0].id

    def test_bear_license_tag_species_is_bear_not_black_bear(self) -> None:
        """LicenseTag.species == 'bear' (not 'black_bear' — known-pitfalls.md)."""
        cit = _make_citation()
        records = [_make_bear_record(gmu_code="082", record_type="section")]
        result = mod._build_bear_license_tags(records, cit)
        assert len(result) == 1
        assert result[0].species == "bear"

    def test_bear_kind_maps_from_section_license_kind(self) -> None:
        """Bear LicenseTag.kind is derived from section-level license_kind field."""
        cit = _make_citation()
        records = [_make_bear_record(gmu_code="082", license_kind="over_the_counter")]
        result = mod._build_bear_license_tags(records, cit)
        assert result[0].kind == "over_the_counter"

    def test_statewide_rule_and_reporting_obligation_produce_no_rows(self) -> None:
        """statewide_rule and reporting_obligation record types are completely skipped."""
        cit = _make_citation()
        non_section_records: list[dict] = [  # type: ignore[type-arg]
            {"record_type": "statewide_rule", "rule_hint": "x", "verbatim_text": "x"},
            {"record_type": "reporting_obligation", "kind": "harvest_report", "verbatim_text": "x"},
        ]
        sds = mod._build_bear_season_definitions(non_section_records, cit)
        lts = mod._build_bear_license_tags(non_section_records, cit)
        assert sds == []
        assert lts == []


# ---------------------------------------------------------------------------
# TestBuildLinks
# ---------------------------------------------------------------------------


class TestBuildLinks:
    """license_season links tag to each season; regulation_season and regulation_license
    use CO-GMU-{int} jurisdiction_code; no deer fan-out (contrast MT)."""

    def _two_method_sections(self) -> list[dict]:  # type: ignore[type-arg]
        """Two sections for the same GMU/species with different method groups."""
        archery_row: dict = {  # type: ignore[type-arg]
            "hunt_code": "D-M-001-O1-A",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "A",
            "method_letter": "A",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
            ],
            "weapon_types": ["archery"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Archery row.",
            "page_reference": {"page_num_1based": 10, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        rifle_row: dict = {  # type: ignore[type-arg]
            "hunt_code": "D-M-001-O2-R",
            "season_code": "O2",
            "gmu_code": "001",
            "list_value": "A",
            "method_letter": "R",
            "season_windows": [
                {"start_date": "Oct. 17", "end_date": "Nov. 20", "raw_text": "Oct. 17 – Nov. 20"},
            ],
            "weapon_types": ["any_legal_weapon"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Rifle row.",
            "page_reference": {"page_num_1based": 11, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        sec_archery = _make_section(gmu_code="001", species_group="mule_deer",
                                     method_group="archery", rows=[archery_row])
        sec_rifle = _make_section(gmu_code="001", species_group="mule_deer",
                                   method_group="any_legal_weapon", rows=[rifle_row])
        return [sec_archery, sec_rifle]

    def test_license_season_links_tag_to_its_seasons(self) -> None:
        """Each LicenseSeason links a license_tag_id to a season_definition_id."""
        secs = self._two_method_sections()
        bear_records: list[dict] = []  # type: ignore[type-arg]
        result = mod._build_license_seasons(secs, bear_records)
        # 2 tags × 1 window each → 2 license_season rows
        assert len(result) == 2
        lt_ids = {ls.license_tag_id for ls in result}
        sd_ids = {ls.season_definition_id for ls in result}
        assert len(lt_ids) == 2, "Each hunt code should produce a distinct tag id"
        assert len(sd_ids) == 2, "Each hunt code should produce a distinct season id"

    def test_regulation_season_jurisdiction_code_uses_int_gmu(self) -> None:
        """RegulationSeason.jurisdiction_code == 'CO-GMU-1' (not 'CO-GMU-001')."""
        secs = self._two_method_sections()
        bear_records: list[dict] = []  # type: ignore[type-arg]
        result = mod._build_regulation_seasons(secs, bear_records)
        for rs in result:
            assert rs.jurisdiction_code == "CO-GMU-1", (
                f"Expected 'CO-GMU-1' (leading zeros stripped), got {rs.jurisdiction_code!r}"
            )

    def test_regulation_season_state_is_us_co(self) -> None:
        """RegulationSeason.state == 'US-CO'."""
        secs = [_make_section(gmu_code="001")]
        bear_records: list[dict] = []  # type: ignore[type-arg]
        result = mod._build_regulation_seasons(secs, bear_records)
        assert all(rs.state == "US-CO" for rs in result)

    def test_regulation_license_jurisdiction_code_uses_int_gmu(self) -> None:
        """RegulationLicense.jurisdiction_code == 'CO-GMU-1'."""
        secs = self._two_method_sections()
        bear_records: list[dict] = []  # type: ignore[type-arg]
        result = mod._build_regulation_licenses(secs, bear_records)
        for rl in result:
            assert rl.jurisdiction_code == "CO-GMU-1"

    def test_no_deer_fan_out_in_co(self) -> None:
        """A mule_deer section yields exactly ONE regulation_season per season,
        NOT two (contrast MT which fans 'deer' → mule_deer + whitetail)."""
        secs = [_make_section(gmu_code="001", species_group="mule_deer")]
        bear_records: list[dict] = []  # type: ignore[type-arg]
        reg_seasons = mod._build_regulation_seasons(secs, bear_records)
        # 1 section × 1 row × 1 window → 1 regulation_season (no fan-out)
        assert len(reg_seasons) == 1
        assert reg_seasons[0].species_group == "mule_deer"

    def test_link_dedup_works_across_identical_rows(self) -> None:
        """Two sections with the same hunt_code/gmu produce no duplicate link rows."""
        same_row: dict = {  # type: ignore[type-arg]
            "hunt_code": "D-M-001-O1-A",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "A",
            "method_letter": "A",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
            ],
            "weapon_types": ["archery"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Row.",
            "page_reference": {"page_num_1based": 10, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        sec1 = _make_section(gmu_code="001", rows=[same_row])
        sec2 = _make_section(gmu_code="001", rows=[same_row])
        bear_records: list[dict] = []  # type: ignore[type-arg]
        ls = mod._build_license_seasons([sec1, sec2], bear_records)
        rl = mod._build_regulation_licenses([sec1, sec2], bear_records)
        # Dedup: same row in two sections → only 1 link row each
        assert len(ls) == 1
        assert len(rl) == 1


# ---------------------------------------------------------------------------
# TestAsymmetricCoverageM2Criterion
# ---------------------------------------------------------------------------


class TestAsymmetricCoverageM2Criterion:
    """PRD 002 success criterion #2 lock (M2 analog of MT's test_license_season_asymmetric_coverage_m1_criterion).

    GMU 001 mule deer should have hunt codes covering at least archery, muzzleloader,
    and rifle (any_legal_weapon) methods.  The license_season link table ties one
    license_tag to each of its distinct season_definition ids.  The regulation_season
    table links the single (CO-GMU-1, mule_deer) regulation_record to ALL seasons —
    the asymmetric-coverage property: different tags cover different season sets.

    This test runs against the REAL committed ``big-game-2026.json`` artifact.
    """

    def test_gmu_001_mule_deer_has_multi_method_seasons(self) -> None:
        """GMU 001 mule_deer has ≥3 distinct season_definition ids spanning
        archery, muzzleloader, and any_legal_weapon weapon types.

        PRD 002 success criterion #2: per-method seasons are distinct entities.
        Ties to the REAL CO artifact.
        """
        cit = _make_citation()
        all_secs = mod._load_big_game_sections()
        # Filter to mule_deer sections that have at least one row for GMU 001.
        gmu001_mule_deer_secs = [
            s for s in all_secs
            if s["species_group"] == "mule_deer"
            and any(r["gmu_code"] == "001" for r in s["rows"])
        ]
        assert gmu001_mule_deer_secs, (
            "No mule_deer sections found with gmu_code='001' in big-game-2026.json; "
            "check the artifact or filter logic."
        )

        sds = mod._build_big_game_season_definitions(gmu001_mule_deer_secs, cit)
        lts = mod._build_big_game_license_tags(gmu001_mule_deer_secs, cit)

        # ≥3 distinct season ids for GMU 001 mule_deer
        sd_ids = {sd.id for sd in sds}
        assert len(sd_ids) >= 3, (
            f"Expected ≥3 distinct season_definition ids for GMU 001 mule_deer; "
            f"got {len(sd_ids)}: {sorted(sd_ids)}"
        )

        # Weapon types span at least archery + muzzleloader + any_legal_weapon
        weapon_types_seen = {sd.weapon_type for sd in sds}
        required_weapons = {"archery", "muzzleloader", "any_legal_weapon"}
        assert required_weapons <= weapon_types_seen, (
            f"Expected weapon types {required_weapons} in GMU 001 mule_deer seasons; "
            f"found {weapon_types_seen}"
        )

        # Expected hunt codes in the 2026 artifact for GMU 001 mule_deer
        hunt_codes_in_tags = {lt.license_code for lt in lts}
        expected_codes = {"D-M-001-O1-A", "D-M-001-O1-M", "D-M-001-O2-R"}
        assert expected_codes <= hunt_codes_in_tags, (
            f"Expected hunt codes {expected_codes} present in license_tags for GMU 001 "
            f"mule_deer; found {hunt_codes_in_tags}"
        )

    def test_gmu_001_mule_deer_regulation_season_links_all_seasons(self) -> None:
        """regulation_season links the single (CO-GMU-1, mule_deer) regulation_record
        to ALL distinct seasons for GMU 001 mule_deer — the asymmetric-coverage property.

        The archery-season coverage set differs from the rifle-season coverage set
        (different weapon_type and window dates). regulation_season links ALL of them
        to the same regulation_record anchor, so a query for GMU 1 mule_deer
        returns all available methods.
        """
        cit = _make_citation()
        all_secs = mod._load_big_game_sections()
        gmu001_mule_deer_secs = [
            s for s in all_secs
            if s["species_group"] == "mule_deer"
            and any(r["gmu_code"] == "001" for r in s["rows"])
        ]

        bear_records: list[dict] = []  # type: ignore[type-arg]
        sds = mod._build_big_game_season_definitions(gmu001_mule_deer_secs, cit)
        reg_seasons = mod._build_regulation_seasons(gmu001_mule_deer_secs, bear_records)

        # All regulation_seasons for GMU 001 mule_deer point to "CO-GMU-1"
        gmu1_rs = [
            rs for rs in reg_seasons
            if rs.jurisdiction_code == "CO-GMU-1" and rs.species_group == "mule_deer"
        ]
        assert len(gmu1_rs) >= 3, (
            f"Expected ≥3 regulation_season rows for (CO-GMU-1, mule_deer); "
            f"got {len(gmu1_rs)}"
        )

        # The set of season_definition_ids in regulation_seasons spans all methods
        rs_sd_ids = {rs.season_definition_id for rs in gmu1_rs}
        sd_ids = {sd.id for sd in sds}
        # Every regulation_season id must have a corresponding season_definition
        assert rs_sd_ids <= sd_ids, (
            "Some regulation_season.season_definition_id values have no matching "
            "season_definition; link/entity builders are out of sync."
        )

        # Archery coverage set differs from rifle coverage set (asymmetric coverage)
        archery_seasons = {sd for sd in sds if sd.weapon_type == "archery"}
        rifle_seasons = {sd for sd in sds if sd.weapon_type == "any_legal_weapon"}
        archery_ids = {sd.id for sd in archery_seasons}
        rifle_ids = {sd.id for sd in rifle_seasons}
        assert archery_ids != rifle_ids, (
            "Archery and rifle season_definition sets should differ "
            "(asymmetric-coverage is the key property PRD 002 SC #2 verifies)"
        )


# ---------------------------------------------------------------------------
# TestCountGuards
# ---------------------------------------------------------------------------


class TestCountGuards:
    """_check_count_band passes in-band; raises RuntimeError below low and above high."""

    def test_in_band_does_not_raise(self) -> None:
        """A count exactly equal to the lower bound passes without raising."""
        mod._check_count_band("season_definition", 1409, mod._SEASON_DEFINITION_BAND)

    def test_in_band_upper_bound_does_not_raise(self) -> None:
        """A count exactly equal to the upper bound passes without raising."""
        mod._check_count_band("season_definition", 2617, mod._SEASON_DEFINITION_BAND)

    def test_below_band_raises_runtime_error(self) -> None:
        """A count below the lower bound raises RuntimeError."""
        with pytest.raises(RuntimeError, match="count guard failed"):
            mod._check_count_band("season_definition", 100, mod._SEASON_DEFINITION_BAND)

    def test_above_band_raises_runtime_error(self) -> None:
        """A count above the upper bound raises RuntimeError."""
        with pytest.raises(RuntimeError, match="count guard failed"):
            mod._check_count_band("season_definition", 9999, mod._SEASON_DEFINITION_BAND)

    def test_license_tag_band_below_raises(self) -> None:
        """A count below the license_tag lower bound raises RuntimeError."""
        with pytest.raises(RuntimeError, match="count guard failed"):
            mod._check_count_band("license_tag", 50, mod._LICENSE_TAG_BAND)

    def test_license_tag_band_above_raises(self) -> None:
        """A count above the license_tag upper bound raises RuntimeError."""
        with pytest.raises(RuntimeError, match="count guard failed"):
            mod._check_count_band("license_tag", 99999, mod._LICENSE_TAG_BAND)

    def test_error_message_contains_name_and_count(self) -> None:
        """RuntimeError message names the table and the out-of-band count."""
        with pytest.raises(RuntimeError) as exc_info:
            mod._check_count_band("my_table", 5, (100, 200))
        msg = str(exc_info.value)
        assert "my_table" in msg
        assert "5" in msg


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    """dry-run smoke test against real artifacts; mocked-write FK-order + single-commit asserts."""

    def test_dry_run_returns_zero_against_real_artifacts(self) -> None:
        """--dry-run: builds all entities from the real artifacts and returns 0.

        This is an integration smoke test — exercises the full Phase 1 + Phase 2
        pipeline (artifact load → build → count guards) without any DB connectivity.
        """
        result = mod.main(["--dry-run"])
        assert result == 0

    def test_live_path_entity_upserts_before_link_writes_and_single_commit(self) -> None:
        """Live path: entity upserts (season_definition, license_tag) are called BEFORE
        link writes (license_season, regulation_season, regulation_license), and
        conn.commit() is called exactly once at the end.

        FK order assertion: season_definition and license_tag rows must exist in the DB
        before license_season / regulation_season / regulation_license rows reference them.
        """
        mock_conn = MagicMock()
        connect_cm = _make_connect_cm(mock_conn)

        call_log: list[str] = []

        def _track_upsert_sd(*_args: object, **_kwargs: object) -> None:
            call_log.append("upsert_season_definition")

        def _track_upsert_lt(*_args: object, **_kwargs: object) -> None:
            call_log.append("upsert_license_tag")

        def _track_write_ls(*_args: object, **_kwargs: object) -> None:
            call_log.append("write_license_season")

        def _track_write_rs(*_args: object, **_kwargs: object) -> None:
            call_log.append("write_regulation_season")

        def _track_write_rl(*_args: object, **_kwargs: object) -> None:
            call_log.append("write_regulation_license")

        with (
            patch("ingestion.lib.db.connect", return_value=connect_cm),
            patch("ingestion.lib.db.upsert_season_definition", side_effect=_track_upsert_sd),
            patch("ingestion.lib.db.upsert_license_tag", side_effect=_track_upsert_lt),
            patch("ingestion.lib.db.write_license_season", side_effect=_track_write_ls),
            patch("ingestion.lib.db.write_regulation_season", side_effect=_track_write_rs),
            patch("ingestion.lib.db.write_regulation_license", side_effect=_track_write_rl),
        ):
            result = mod.main([])

        assert result == 0

        # Verify conn.commit() was called exactly once.
        mock_conn.commit.assert_called_once()

        # FK order: every upsert_season_definition call must precede every
        # write_license_season / write_regulation_season call in the log.
        first_sd_pos = next(
            (i for i, op in enumerate(call_log) if op == "upsert_season_definition"), None
        )
        first_lt_pos = next(
            (i for i, op in enumerate(call_log) if op == "upsert_license_tag"), None
        )
        first_link_pos = next(
            (
                i for i, op in enumerate(call_log)
                if op in ("write_license_season", "write_regulation_season",
                          "write_regulation_license")
            ),
            None,
        )

        assert first_sd_pos is not None, "upsert_season_definition was never called"
        assert first_lt_pos is not None, "upsert_license_tag was never called"
        assert first_link_pos is not None, "No link-table write was called"

        # All entity upserts precede all link writes in the call sequence.
        last_entity_pos = max(
            i for i, op in enumerate(call_log)
            if op in ("upsert_season_definition", "upsert_license_tag")
        )
        assert last_entity_pos < first_link_pos, (
            f"FK order violated: last entity upsert at position {last_entity_pos} "
            f"but first link write at position {first_link_pos}. "
            "Entity rows must be written before link rows that FK-reference them."
        )

    def test_count_guard_fires_before_db_connect(self) -> None:
        """Count guard fires before db.connect; if it raises, connect is never called."""
        mock_connect = MagicMock()

        with (
            patch.object(
                mod, "_check_count_band", side_effect=RuntimeError("guard boom")
            ),
            patch("ingestion.lib.db.connect", mock_connect),
        ):
            with pytest.raises(RuntimeError, match="guard boom"):
                mod.main([])

        mock_connect.assert_not_called()


# ---------------------------------------------------------------------------
# TestFixReview6Behaviors (FIX 1, FIX 2, FIX 3 new behavior locks)
# ---------------------------------------------------------------------------


class TestFixReview6Behaviors:
    """Lock the six review-fix behaviors introduced in S06.7 review-fix pass.

    FIX 1: Zero-season rows emit a WARNING.
    FIX 2: Lossy dedup (id collision with differing fields) emits a WARNING;
           identical-content collision does NOT emit a WARNING.
    FIX 3: Empty weapon_types raises RuntimeError (license_tag builders) /
           ValueError (_co_window_weapon_type).
    """

    # -----------------------------------------------------------------------
    # FIX 1: zero-season WARNING
    # -----------------------------------------------------------------------

    def test_big_game_builder_emits_warning_for_empty_season_windows(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A big-game row with season_windows=[] and valid gmu/hunt_code emits a WARNING.

        Data outcome unchanged: no season_definition emitted, but a WARNING is
        logged naming the builder, gmu_code, hunt_code, species_group, and page.
        """
        cit = _make_citation()
        row: dict = {  # type: ignore[type-arg]
            "hunt_code": "D-F-001-O1-R",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "A",
            "method_letter": "R",
            "season_windows": [],  # empty — FIX 1 target
            "weapon_types": ["any_legal_weapon"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Female rifle row.",
            "page_reference": {"page_num_1based": 15, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        secs = [_make_section(gmu_code="001", rows=[row])]
        with caplog.at_level(logging.WARNING):
            result = mod._build_big_game_season_definitions(secs, cit)
        # No seasons emitted (empty windows).
        gmu001_ids = [sd.id for sd in result if "D-F-001-O1-R" in sd.id]
        assert gmu001_ids == [], "No season_definition should be emitted for empty windows"
        # WARNING must be logged.
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no season_definition" in m.lower() for m in warning_msgs), (
            f"Expected a WARNING about no season_definition for empty season_windows; "
            f"got warnings: {warning_msgs}"
        )

    def test_bear_builder_emits_warning_for_empty_season_windows(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A bear row with season_windows=[] emits a WARNING (FIX 1, bear builder)."""
        cit = _make_citation()
        row: dict = {  # type: ignore[type-arg]
            "hunt_code": "B-E-082-R1-R",
            "season_code": "R1",
            "gmu_code": "082",
            "weapon_types": ["any_legal_weapon"],
            "method_letter": "R",
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Bear empty windows.",
            "season_windows": [],  # empty — FIX 1 target
            "page_reference": {"page_num_1based": 73, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        record = {
            "record_type": "section",
            "species_group": "black_bear",
            "gmu_code": "082",
            "method_group": "rifle",
            "residency_scope": "both",
            "license_kind": "limited_draw",
            "verbatim_text": "Bear GMU 082.",
            "rows": [row],
        }
        with caplog.at_level(logging.WARNING):
            result = mod._build_bear_season_definitions([record], cit)
        assert result == [], "No season_definition should be emitted for empty bear windows"
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no season_definition" in m.lower() for m in warning_msgs), (
            f"Expected WARNING about no season_definition; got {warning_msgs}"
        )

    # -----------------------------------------------------------------------
    # FIX 2: lossy dedup WARNING / silent identical dedup
    # -----------------------------------------------------------------------

    def test_big_game_builder_warns_on_lossy_dedup_differing_opens(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two rows with the same id but different opens date → WARNING emitted."""
        cit = _make_citation()
        row1: dict = {  # type: ignore[type-arg]
            "hunt_code": "E-F-085-P5-R",
            "season_code": "P5",
            "gmu_code": "085",
            "list_value": "A",
            "method_letter": "R",
            "season_windows": [
                {"start_date": "Oct. 14", "end_date": "Nov. 20", "raw_text": "Oct. 14 – Nov. 20"},
            ],
            "weapon_types": ["any_legal_weapon"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "First occurrence.",
            "page_reference": {"page_num_1based": 30, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        row2: dict = dict(row1)  # same id-encoding fields
        row2 = {**row1, "season_windows": [
            {"start_date": "Oct. 15", "end_date": "Nov. 20", "raw_text": "Oct. 15 – Nov. 20"},
        ], "extras": "Second occurrence."}
        sec1 = _make_section(gmu_code="085", species_group="elk",
                             method_group="any_legal_weapon", rows=[row1])
        sec2 = _make_section(gmu_code="085", species_group="elk",
                             method_group="any_legal_weapon", rows=[row2])
        with caplog.at_level(logging.WARNING):
            result = mod._build_big_game_season_definitions([sec1, sec2], cit)
        # First-occurrence wins — only 1 season_definition in result.
        ids = [sd.id for sd in result]
        assert len(ids) == len(set(ids))
        # WARNING must mention lossy dedup.
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("lossy dedup" in m.lower() for m in warning_msgs), (
            f"Expected a 'lossy dedup' WARNING for differing opens; got: {warning_msgs}"
        )

    def test_big_game_builder_no_warning_on_identical_dedup(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two rows with the same id and IDENTICAL opens/closes/weapon_type → NO WARNING."""
        cit = _make_citation()
        row: dict = {  # type: ignore[type-arg]
            "hunt_code": "D-M-001-O1-A",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "A",
            "method_letter": "A",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
            ],
            "weapon_types": ["archery"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Same row twice.",
            "page_reference": {"page_num_1based": 10, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        sec1 = _make_section(gmu_code="001", rows=[row])
        sec2 = _make_section(gmu_code="001", rows=[row])  # identical — benign dedup
        with caplog.at_level(logging.WARNING):
            result = mod._build_big_game_season_definitions([sec1, sec2], cit)
        assert len(result) == 1, "Dedup should yield exactly one season_definition"
        # No WARNING from lossy-dedup path (identical content).
        lossy_warnings = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING and "lossy dedup" in r.message.lower()
        ]
        assert lossy_warnings == [], (
            f"No 'lossy dedup' WARNING expected for identical content; got: {lossy_warnings}"
        )

    def test_big_game_builder_warns_on_lossy_dedup_differing_verbatim(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Same id + identical dates/weapon/residency but DIFFERENT verbatim_rule
        → WARNING. Regression for the review finding that the collision check
        compared only a subset of fields (dates/weapon) and silently dropped
        rows differing in verbatim_rule/residency."""
        cit = _make_citation()
        base: dict = {  # type: ignore[type-arg]
            "hunt_code": "D-M-006-E1-R",
            "season_code": "E1",
            "gmu_code": "006",
            "list_value": "A",
            "method_letter": "R",
            "season_windows": [
                {"start_date": "Oct. 1", "end_date": "Oct. 9", "raw_text": "Oct. 1-9"},
            ],
            "weapon_types": ["any_legal_weapon"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "First occurrence verbatim text.",
            "page_reference": {"page_num_1based": 37, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        # Identical id-encoding + dates/weapon/residency; only extras (→ verbatim) differs.
        row2 = {**base, "extras": "Second, different verbatim text."}
        sec1 = _make_section(gmu_code="006", species_group="mule_deer",
                             method_group="any_legal_weapon", rows=[base])
        sec2 = _make_section(gmu_code="006", species_group="mule_deer",
                             method_group="any_legal_weapon", rows=[row2])
        with caplog.at_level(logging.WARNING):
            result = mod._build_big_game_season_definitions([sec1, sec2], cit)
        assert len(result) == 1
        lossy = [r.message for r in caplog.records
                 if r.levelno == logging.WARNING and "lossy dedup" in r.message.lower()]
        assert lossy, "Expected a lossy-dedup WARNING when only verbatim_rule differs"
        assert any("verbatim_rule" in m for m in lossy), (
            f"WARNING should name verbatim_rule; got: {lossy}"
        )

    def test_big_game_builder_no_warning_on_page_only_difference(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Same id + identical regulatory content but DIFFERENT page_reference
        → NO WARNING. page_reference is deliberately excluded from the lossy-dedup
        comparison: the same season legitimately recurs across multiple
        GMU-section pages (157 such benign collisions in the 2026 artifact), so a
        page-only difference is provenance, not data drift."""
        cit = _make_citation()
        base: dict = {  # type: ignore[type-arg]
            "hunt_code": "D-M-007-O1-A",
            "season_code": "O1",
            "gmu_code": "007",
            "list_value": "A",
            "method_letter": "A",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
            ],
            "weapon_types": ["archery"],
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Identical verbatim text in both.",
            "page_reference": {"page_num_1based": 40, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        # Identical regulatory content; ONLY the page number differs.
        row2 = {**base, "page_reference": {**base["page_reference"], "page_num_1based": 42}}
        sec1 = _make_section(gmu_code="007", species_group="mule_deer", rows=[base])
        sec2 = _make_section(gmu_code="007", species_group="mule_deer", rows=[row2])
        with caplog.at_level(logging.WARNING):
            result = mod._build_big_game_season_definitions([sec1, sec2], cit)
        assert len(result) == 1
        lossy = [r.message for r in caplog.records
                 if r.levelno == logging.WARNING and "lossy dedup" in r.message.lower()]
        assert lossy == [], (
            f"Page-only differences must NOT warn (benign provenance); got: {lossy}"
        )

    # -----------------------------------------------------------------------
    # FIX 3: empty weapon_types raises RuntimeError / ValueError
    # -----------------------------------------------------------------------

    def test_big_game_license_tag_builder_raises_on_empty_weapon_types(self) -> None:
        """_build_big_game_license_tags raises RuntimeError when weapon_types=[]."""
        cit = _make_citation()
        row: dict = {  # type: ignore[type-arg]
            "hunt_code": "D-M-001-O1-A",
            "season_code": "O1",
            "gmu_code": "001",
            "list_value": "A",
            "method_letter": "A",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2-30"},
            ],
            "weapon_types": [],  # FIX 3: empty → must raise
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Missing weapon types.",
            "page_reference": {"page_num_1based": 10, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        secs = [_make_section(gmu_code="001", rows=[row])]
        with pytest.raises(RuntimeError, match="empty/missing weapon_types"):
            mod._build_big_game_license_tags(secs, cit)

    def test_bear_license_tag_builder_raises_on_empty_weapon_types(self) -> None:
        """_build_bear_license_tags raises RuntimeError when weapon_types=[]."""
        cit = _make_citation()
        row: dict = {  # type: ignore[type-arg]
            "hunt_code": "B-E-082-R1-R",
            "season_code": "R1",
            "gmu_code": "082",
            "weapon_types": [],  # FIX 3: empty → must raise
            "method_letter": "R",
            "residency_scope": None,
            "quota": None,
            "quota_range": None,
            "extras": "Missing weapon types.",
            "season_windows": [
                {"start_date": "Sept. 2", "end_date": "Oct. 31", "raw_text": "Sept. 2-Oct. 31"},
            ],
            "page_reference": {"page_num_1based": 74, "bbox": None,
                               "pdf_filename": "x.pdf",
                               "extracted_at": "2026-06-09T00:00:00+00:00"},
        }
        record = {
            "record_type": "section",
            "species_group": "black_bear",
            "gmu_code": "082",
            "method_group": "rifle",
            "residency_scope": "both",
            "license_kind": "limited_draw",
            "verbatim_text": "Bear GMU 082.",
            "rows": [row],
        }
        with pytest.raises(RuntimeError, match="empty/missing weapon_types"):
            mod._build_bear_license_tags([record], cit)

    def test_window_weapon_type_raises_value_error_on_empty_weapon_types(self) -> None:
        """_co_window_weapon_type raises ValueError when row weapon_types is empty.

        FIX 3: the function now fails loud on empty weapon_types before any
        indexing, preventing a silent weapon_types=[] write downstream.
        """
        row: dict = {  # type: ignore[type-arg]
            "weapon_types": [],
            "method_letter": "R",
            "hunt_code": "D-M-001-O1-R",
            "gmu_code": "001",
        }
        with pytest.raises(ValueError, match="empty/missing weapon_types"):
            mod._co_window_weapon_type(row, 0)

    def test_window_weapon_type_raises_value_error_on_out_of_range_index(self) -> None:
        """_co_window_weapon_type raises ValueError (not IndexError) on out-of-range window_index.

        FIX 3: replaced the bare IndexError from weapon_types[window_index] with a
        diagnostic ValueError that names the hunt_code and the lengths involved.
        """
        row: dict = {  # type: ignore[type-arg]
            "weapon_types": ["archery", "muzzleloader"],  # len=2
            "method_letter": "X",
            "hunt_code": "D-M-001-O1-X",
            "gmu_code": "001",
        }
        with pytest.raises(ValueError, match="out of range"):
            mod._co_window_weapon_type(row, 5)  # window_index=5 > len=2
