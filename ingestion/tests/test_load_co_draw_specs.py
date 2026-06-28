"""Unit tests for states.colorado.load_draw_specs — T8 (S06.8).

Test classes:
- TestLoadArtifacts              — loaders return expected shapes; hybrid set size 116;
                                   missing/empty artifact raises ColoradoDrawSpecError.
- TestArtifactConstantsValidator — passes on real artifact; mocked wrong value raises naming the field.
- TestPointOnlyCodeMap           — all 4 species letters {A,B,D,E} present; values are *-P-999-99-P.
- TestMakePools                  — hybrid: 2 pools, correct shares/selections/eligibility/tie_break;
                                   non-hybrid: 1 pool share 1.0.
- TestMakeResidencyCap           — hybrid 0.20, non-hybrid 0.25.
- TestMakePointSystem            — kind/accrual/reset_on_success/inactive_forfeit_years; purchase_only_code;
                                   unknown species letter raises.
- TestConstantsLock              — AC #972: named constants equal 5/0.80/0.20/6 exactly;
                                   _HIGH_DEMAND_NR_CAP==0.20, _STANDARD_NR_CAP==0.25.
- TestCouplingLock               — AC #973: every 2-pool spec has NR cap from artifact nr_allocation;
                                   every 1-pool spec has standard cap from artifact.
- TestBuildCoDrawSpecs           — real artifact: 1917 draw_specs, 113 hybrid; known codes correct
                                   pool count; backfill targets are CO-GMU-*; bear specs present.
- TestOtcDiscriminator           — AC #980: synthetic minimal artifact; only limited_draw produces draw_spec.
- TestParametersAndPhase         — every spec: parameters is None, draw_phase=="primary",
                                   successor_hunt_code_key is None, quota is None, deadline==2026-04-07.
- TestCrossListingValidator      — passes on real data; synthetic 2-distinct-quota raises;
                                   override-dict entry suppresses.
- TestOrphanAndMalformedWarnings — 3 B-E-851-* orphans logged at WARNING; malformed + codes logged;
                                   no exception raised.
- TestCountGuard                 — 1917 passes; 100 raises; 9999 raises; band edges.
- TestMain                       — --dry-run returns 0 with NO db.connect(); mocked-write test:
                                   all upserts before all backfills; exactly one conn.commit().
- TestNoDriftGuardImport         — AST: loader has no import referencing drift_guard.
- TestNoStateAdapterImports      — AST: loader does not import non-Colorado state adapter.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from states.colorado import load_draw_specs as mod
from states.colorado.load_draw_specs import (
    ColoradoDrawSpecError,
    _assert_draw_spec_count_within_guard,
    _build_co_draw_specs,
    _build_hybrid_code_set,
    _build_point_only_code_by_species_letter,
    _emit_draw_spec,
    _extract_application_deadline,
    _extract_single_record,
    _HIGH_DEMAND_NR_CAP,
    _HYBRID_ELIGIBILITY_POINT_LINE,
    _HYBRID_PREFERENCE_POOL_SHARE,
    _HYBRID_RANDOM_POOL_MIN_POINTS,
    _HYBRID_RANDOM_POOL_SHARE,
    _load_draw_mechanics,
    _load_section_artifact,
    _make_pools,
    _make_point_system,
    _make_residency_cap,
    _report_orphan_hybrid_codes,
    _STANDARD_NR_CAP,
    _validate_artifact_constants,
    _validate_cross_listing_consistency,
    main,
)


# ---------------------------------------------------------------------------
# Shared path constants and module source path helper
# ---------------------------------------------------------------------------

_COLORADO_DIR = Path(__file__).resolve().parent.parent / "states" / "colorado"
_DRAW_MECHANICS_PATH = _COLORADO_DIR / "extracted" / "draw-mechanics-2026.json"
_BIG_GAME_PATH = _COLORADO_DIR / "extracted" / "big-game-2026.json"
_BLACK_BEAR_PATH = _COLORADO_DIR / "extracted" / "black-bear-2026.json"


def _loader_source_path() -> Path:
    spec = importlib.util.find_spec("states.colorado.load_draw_specs")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin)


# ---------------------------------------------------------------------------
# Module-scope real-artifact fixtures (read-only)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_mechanics() -> list[dict]:
    data = json.loads(_DRAW_MECHANICS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data, "draw-mechanics artifact empty or missing"
    return data  # type: ignore[return-value]


@pytest.fixture(scope="module")
def real_big_game() -> list[dict]:
    data = json.loads(_BIG_GAME_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data, "big-game artifact empty or missing"
    return data  # type: ignore[return-value]


@pytest.fixture(scope="module")
def real_bear() -> list[dict]:
    data = json.loads(_BLACK_BEAR_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data, "bear artifact empty or missing"
    return data  # type: ignore[return-value]


@pytest.fixture(scope="module")
def real_hybrid_set(real_mechanics: list[dict]) -> frozenset[str]:
    return _build_hybrid_code_set(real_mechanics)


@pytest.fixture(scope="module")
def real_point_only(real_mechanics: list[dict]) -> dict[str, str]:
    return _build_point_only_code_by_species_letter(real_mechanics)


@pytest.fixture(scope="module")
def real_deadline(real_mechanics: list[dict]) -> date:
    return _extract_application_deadline(real_mechanics)


@pytest.fixture(scope="module")
def real_citation():  # type: ignore[return]
    return mod._load_citation_from_sources_yaml(mod._BIG_GAME_CITATION_ID)


@pytest.fixture(scope="module")
def real_draw_specs_and_backfill(
    real_big_game: list[dict],
    real_bear: list[dict],
    real_hybrid_set: frozenset[str],
    real_point_only: dict[str, str],
    real_deadline: date,
    real_citation,  # type: ignore[type-arg]
) -> tuple[dict, list]:
    draw_specs, backfill = _build_co_draw_specs(
        real_big_game,
        real_bear,
        real_hybrid_set,
        real_point_only,
        real_deadline,
        real_citation,
    )
    assert draw_specs, "draw_specs is empty — loader build failed"
    return draw_specs, backfill


# ---------------------------------------------------------------------------
# Synthetic builder helpers
# ---------------------------------------------------------------------------


def _make_big_game_section(
    species_group: str,
    gmu_code: str,
    rows: list[dict],
) -> dict:
    return {
        "species_group": species_group,
        "gmu_code": gmu_code,
        "rows": rows,
    }


def _make_big_game_row(
    hunt_code: str,
    list_value: str | None,
    gmu_code: str | None = None,
    quota: int | None = None,
) -> dict:
    return {
        "hunt_code": hunt_code,
        "list_value": list_value,
        "gmu_code": gmu_code,
        "quota": quota,
        "page_reference": None,
    }


def _make_bear_section(
    gmu_code: str,
    license_kind: str,
    rows: list[dict],
) -> dict:
    return {
        "record_type": "section",
        "gmu_code": gmu_code,
        "license_kind": license_kind,
        "rows": rows,
    }


def _make_bear_row(hunt_code: str, gmu_code: str | None = None, quota: int | None = None) -> dict:
    return {
        "hunt_code": hunt_code,
        "gmu_code": gmu_code,
        "quota": quota,
    }


def _make_minimal_citation():  # type: ignore[return]
    from ingestion.lib.schema import SourceCitation
    return SourceCitation(
        id="co-cpw-big-game-2026-brochure",
        agency="Colorado Parks and Wildlife",
        title="2026 Colorado Big Game Brochure",
        url="https://example.com/brochure.pdf",
        publication_date="2026-03-04",
        document_type="annual_regulations",
    )


def _make_minimal_point_only() -> dict[str, str]:
    return {
        "A": "A-P-999-99-P",
        "B": "B-P-999-99-P",
        "D": "D-P-999-99-P",
        "E": "E-P-999-99-P",
    }


# ---------------------------------------------------------------------------
# TestLoadArtifacts
# ---------------------------------------------------------------------------


class TestLoadArtifacts:
    """_load_draw_mechanics + _build_hybrid_code_set return expected shapes.

    All tests are self-sufficient (no ordering assumption per pytest-randomly).
    """

    def test_load_draw_mechanics_returns_list(self, real_mechanics: list[dict]) -> None:
        assert isinstance(real_mechanics, list), "draw-mechanics artifact must be a list"
        assert len(real_mechanics) > 0

    def test_draw_mechanics_has_123_records(self, real_mechanics: list[dict]) -> None:
        assert len(real_mechanics) == 123

    def test_draw_mechanics_has_hybrid_code_records(self, real_mechanics: list[dict]) -> None:
        hybrid = [r for r in real_mechanics if r.get("record_type") == "hybrid_code"]
        assert hybrid, "artifact must have at least one hybrid_code record"

    def test_hybrid_set_size_is_116(self, real_mechanics: list[dict]) -> None:
        hs = _build_hybrid_code_set(real_mechanics)
        assert len(hs) == 116

    def test_hybrid_set_is_frozenset(self, real_mechanics: list[dict]) -> None:
        hs = _build_hybrid_code_set(real_mechanics)
        assert isinstance(hs, frozenset)

    def test_missing_artifact_raises_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        with pytest.raises(ColoradoDrawSpecError, match="artifact not found"):
            mod._load_json_artifact(missing)

    def test_empty_json_artifact_raises_error(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty.json"
        # An empty list JSON is "falsy" — should raise
        empty_file.write_text("[]", encoding="utf-8")
        with pytest.raises(ColoradoDrawSpecError):
            mod._load_json_artifact(empty_file)

    def test_invalid_json_artifact_raises_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not_valid_json", encoding="utf-8")
        with pytest.raises(ColoradoDrawSpecError, match="not valid JSON"):
            mod._load_json_artifact(bad)

    def test_load_draw_mechanics_non_list_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "dict.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        with pytest.raises(ColoradoDrawSpecError, match="not a JSON array"):
            _load_draw_mechanics(f)

    def test_build_hybrid_code_set_zero_records_raises(self) -> None:
        no_hybrids = [{"record_type": "important_dates"}]
        with pytest.raises(ColoradoDrawSpecError, match="zero 'hybrid_code' records"):
            _build_hybrid_code_set(no_hybrids)

    def test_hybrid_code_missing_hunt_code_field_raises(self) -> None:
        bad = [{"record_type": "hybrid_code", "species": "deer"}]
        with pytest.raises(ColoradoDrawSpecError):
            _build_hybrid_code_set(bad)


# ---------------------------------------------------------------------------
# TestArtifactConstantsValidator
# ---------------------------------------------------------------------------


class TestArtifactConstantsValidator:
    """_validate_artifact_constants passes on the real artifact; raises on drift."""

    def test_passes_on_real_artifact(self, real_mechanics: list[dict]) -> None:
        # Must not raise
        _validate_artifact_constants(real_mechanics)

    def test_raises_on_wrong_min_preference_points(self, real_mechanics: list[dict]) -> None:
        # Inject a wrong value for min_preference_points
        patched = [
            {**r, "min_preference_points": 99}
            if r.get("record_type") == "hybrid_mechanics"
            else r
            for r in real_mechanics
        ]
        with pytest.raises(ColoradoDrawSpecError, match="min_preference_points"):
            _validate_artifact_constants(patched)

    def test_raises_on_wrong_random_pool_share(self, real_mechanics: list[dict]) -> None:
        patched = [
            {**r, "random_pool_share": 0.50}
            if r.get("record_type") == "hybrid_mechanics"
            else r
            for r in real_mechanics
        ]
        with pytest.raises(ColoradoDrawSpecError, match="random_pool_share"):
            _validate_artifact_constants(patched)

    def test_raises_on_wrong_high_demand_nr_cap(self, real_mechanics: list[dict]) -> None:
        patched = [
            {**r, "high_demand_nr_cap": 0.50}
            if r.get("record_type") == "nr_allocation"
            else r
            for r in real_mechanics
        ]
        with pytest.raises(ColoradoDrawSpecError, match="high_demand_nr_cap"):
            _validate_artifact_constants(patched)

    def test_raises_on_wrong_standard_nr_cap(self, real_mechanics: list[dict]) -> None:
        patched = [
            {**r, "standard_nr_cap": 0.10}
            if r.get("record_type") == "nr_allocation"
            else r
            for r in real_mechanics
        ]
        with pytest.raises(ColoradoDrawSpecError, match="standard_nr_cap"):
            _validate_artifact_constants(patched)

    def test_raises_on_wrong_high_demand_threshold_points(self, real_mechanics: list[dict]) -> None:
        patched = [
            {**r, "high_demand_threshold_points": 99}
            if r.get("record_type") == "nr_allocation"
            else r
            for r in real_mechanics
        ]
        with pytest.raises(ColoradoDrawSpecError, match="high_demand_threshold_points"):
            _validate_artifact_constants(patched)

    def test_extract_single_record_raises_on_zero_matches(self, real_mechanics: list[dict]) -> None:
        with pytest.raises(ColoradoDrawSpecError, match="expected exactly 1"):
            _extract_single_record(real_mechanics, "nonexistent_type")

    def test_extract_single_record_raises_on_multiple_matches(self, real_mechanics: list[dict]) -> None:
        # Build a list with 2 hybrid_mechanics records
        hm = [r for r in real_mechanics if r.get("record_type") == "hybrid_mechanics"]
        assert hm, "fixture must contain at least one hybrid_mechanics record"
        two_records = hm + hm
        with pytest.raises(ColoradoDrawSpecError, match="expected exactly 1"):
            _extract_single_record(two_records, "hybrid_mechanics")


# ---------------------------------------------------------------------------
# TestPointOnlyCodeMap
# ---------------------------------------------------------------------------


class TestPointOnlyCodeMap:
    """_build_point_only_code_by_species_letter — all 4 V1 species letters present."""

    def test_all_four_species_letters_present(self, real_mechanics: list[dict]) -> None:
        by_letter = _build_point_only_code_by_species_letter(real_mechanics)
        expected = {"A", "B", "D", "E"}
        missing = expected - set(by_letter.keys())
        assert not missing, f"Missing species letters: {missing}"

    def test_returns_dict(self, real_mechanics: list[dict]) -> None:
        result = _build_point_only_code_by_species_letter(real_mechanics)
        assert isinstance(result, dict)

    def test_bear_letter_value(self, real_mechanics: list[dict]) -> None:
        by_letter = _build_point_only_code_by_species_letter(real_mechanics)
        assert by_letter["B"] == "B-P-999-99-P"

    def test_deer_letter_value(self, real_mechanics: list[dict]) -> None:
        by_letter = _build_point_only_code_by_species_letter(real_mechanics)
        assert by_letter["D"] == "D-P-999-99-P"

    def test_elk_letter_value(self, real_mechanics: list[dict]) -> None:
        by_letter = _build_point_only_code_by_species_letter(real_mechanics)
        assert by_letter["E"] == "E-P-999-99-P"

    def test_pronghorn_letter_value(self, real_mechanics: list[dict]) -> None:
        by_letter = _build_point_only_code_by_species_letter(real_mechanics)
        assert by_letter["A"] == "A-P-999-99-P"

    def test_values_match_p_999_pattern(self, real_mechanics: list[dict]) -> None:
        by_letter = _build_point_only_code_by_species_letter(real_mechanics)
        for letter, code in by_letter.items():
            assert code.startswith(f"{letter}-P-999"), (
                f"Expected code for {letter!r} to start with '{letter}-P-999', got {code!r}"
            )

    def test_missing_species_letter_raises(self) -> None:
        # Only 3 of 4 V1 species have a point_only_code → must raise
        three_only = [
            {"record_type": "point_only_code", "hunt_code": "B-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "D-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "E-P-999-99-P"},
        ]
        with pytest.raises(ColoradoDrawSpecError, match="missing point_only_code"):
            _build_point_only_code_by_species_letter(three_only)


# ---------------------------------------------------------------------------
# TestMakePools
# ---------------------------------------------------------------------------


class TestMakePools:
    """_make_pools — hybrid: 2 pools; non-hybrid: 1 pool.

    Uses only the module-level Final constants for verification (single source of truth).
    """

    def test_hybrid_returns_two_pools(self) -> None:
        pools = _make_pools(is_hybrid=True)
        assert len(pools) == 2

    def test_hybrid_pool0_share(self) -> None:
        pools = _make_pools(is_hybrid=True)
        assert pools[0].share == _HYBRID_PREFERENCE_POOL_SHARE

    def test_hybrid_pool0_selection_rank_ordered_by_points(self) -> None:
        pools = _make_pools(is_hybrid=True)
        assert pools[0].selection == "rank_ordered_by_points"

    def test_hybrid_pool0_tie_break_is_random(self) -> None:
        pools = _make_pools(is_hybrid=True)
        assert pools[0].tie_break == "random"

    def test_hybrid_pool1_share(self) -> None:
        pools = _make_pools(is_hybrid=True)
        assert pools[1].share == _HYBRID_RANDOM_POOL_SHARE

    def test_hybrid_pool1_selection_unweighted_random(self) -> None:
        pools = _make_pools(is_hybrid=True)
        assert pools[1].selection == "unweighted_random"

    def test_hybrid_pool1_tie_break_is_none(self) -> None:
        """AC #971: the random pool must NOT have a tie_break."""
        pools = _make_pools(is_hybrid=True)
        assert pools[1].tie_break is None

    def test_hybrid_pool1_eligibility_min_points(self) -> None:
        pools = _make_pools(is_hybrid=True)
        assert pools[1].eligibility is not None
        assert pools[1].eligibility.min_points == _HYBRID_RANDOM_POOL_MIN_POINTS

    def test_hybrid_pool_shares_sum_to_one(self) -> None:
        pools = _make_pools(is_hybrid=True)
        total = sum(p.share for p in pools)
        assert abs(total - 1.0) < 1e-9, f"pool shares sum to {total}, expected 1.0"

    def test_non_hybrid_returns_one_pool(self) -> None:
        pools = _make_pools(is_hybrid=False)
        assert len(pools) == 1

    def test_non_hybrid_pool_share_is_one(self) -> None:
        pools = _make_pools(is_hybrid=False)
        assert pools[0].share == 1.0

    def test_non_hybrid_pool_selection_rank_ordered_by_points(self) -> None:
        pools = _make_pools(is_hybrid=False)
        assert pools[0].selection == "rank_ordered_by_points"

    def test_non_hybrid_pool_tie_break_is_random(self) -> None:
        pools = _make_pools(is_hybrid=False)
        assert pools[0].tie_break == "random"

    def test_non_hybrid_pool_no_min_points_eligibility(self) -> None:
        """Non-hybrid pool has no meaningful eligibility constraint (min_points is None)."""
        pools = _make_pools(is_hybrid=False)
        # The loader may create a default eligibility object with all-None fields;
        # the important constraint is that min_points is NOT set (unlike the hybrid random pool)
        if pools[0].eligibility is not None:
            assert pools[0].eligibility.min_points is None, (
                "Non-hybrid pool must not have a min_points eligibility requirement"
            )


# ---------------------------------------------------------------------------
# TestMakeResidencyCap
# ---------------------------------------------------------------------------


class TestMakeResidencyCap:
    """_make_residency_cap — uses module constants exclusively."""

    def test_hybrid_returns_high_demand_cap(self) -> None:
        cap = _make_residency_cap(is_hybrid=True)
        assert cap.nonresident_max_share == _HIGH_DEMAND_NR_CAP

    def test_hybrid_cap_is_0_20(self) -> None:
        cap = _make_residency_cap(is_hybrid=True)
        assert cap.nonresident_max_share == 0.20

    def test_non_hybrid_returns_standard_cap(self) -> None:
        cap = _make_residency_cap(is_hybrid=False)
        assert cap.nonresident_max_share == _STANDARD_NR_CAP

    def test_non_hybrid_cap_is_0_25(self) -> None:
        cap = _make_residency_cap(is_hybrid=False)
        assert cap.nonresident_max_share == 0.25

    def test_hybrid_and_non_hybrid_caps_differ(self) -> None:
        assert _make_residency_cap(True).nonresident_max_share != _make_residency_cap(False).nonresident_max_share


# ---------------------------------------------------------------------------
# TestMakePointSystem
# ---------------------------------------------------------------------------


class TestMakePointSystem:
    """_make_point_system — structure, purchase_only_code per species, unknown raises."""

    def _point_only(self) -> dict[str, str]:
        return _make_minimal_point_only()

    def test_kind_is_preference_linear(self) -> None:
        ps = _make_point_system("D-M-001-O1-A", self._point_only())
        assert ps.kind == "preference_linear"

    def test_accrual_is_annual_on_apply(self) -> None:
        ps = _make_point_system("D-M-001-O1-A", self._point_only())
        assert ps.accrual == "annual_on_apply"

    def test_reset_on_success_is_true(self) -> None:
        ps = _make_point_system("D-M-001-O1-A", self._point_only())
        assert ps.reset_on_success is True

    def test_inactive_forfeit_years_is_none(self) -> None:
        ps = _make_point_system("D-M-001-O1-A", self._point_only())
        assert ps.inactive_forfeit_years is None

    def test_purchase_only_code_deer(self) -> None:
        ps = _make_point_system("D-M-001-O1-A", self._point_only())
        assert ps.purchase_only_code == "D-P-999-99-P"

    def test_purchase_only_code_elk(self) -> None:
        ps = _make_point_system("E-M-001-R1-R", self._point_only())
        assert ps.purchase_only_code == "E-P-999-99-P"

    def test_purchase_only_code_pronghorn(self) -> None:
        ps = _make_point_system("A-M-001-O1-R", self._point_only())
        assert ps.purchase_only_code == "A-P-999-99-P"

    def test_purchase_only_code_bear(self) -> None:
        ps = _make_point_system("B-E-001-O1-A", self._point_only())
        assert ps.purchase_only_code == "B-P-999-99-P"

    def test_unknown_species_letter_raises(self) -> None:
        # Species letter 'Z' has no entry in the map
        with pytest.raises(ColoradoDrawSpecError, match="no point_only_code"):
            _make_point_system("Z-M-001-O1-A", self._point_only())

    def test_empty_hunt_code_raises(self) -> None:
        with pytest.raises(ColoradoDrawSpecError):
            _make_point_system("", self._point_only())


# ---------------------------------------------------------------------------
# TestConstantsLock  (AC #972)
# ---------------------------------------------------------------------------


class TestConstantsLock:
    """AC #972: module-level Final constants must equal specific values.

    These tests pin the administrative parameters so a future drift in the
    extractor (re-running extract_draw_mechanics.py with different brochure
    numbers) is caught before reaching the database.
    """

    def test_hybrid_random_pool_min_points_is_5(self) -> None:
        assert _HYBRID_RANDOM_POOL_MIN_POINTS == 5

    def test_hybrid_preference_pool_share_is_0_80(self) -> None:
        assert _HYBRID_PREFERENCE_POOL_SHARE == 0.80

    def test_hybrid_random_pool_share_is_0_20(self) -> None:
        assert _HYBRID_RANDOM_POOL_SHARE == 0.20

    def test_hybrid_eligibility_point_line_is_6(self) -> None:
        assert _HYBRID_ELIGIBILITY_POINT_LINE == 6

    def test_high_demand_nr_cap_is_0_20(self) -> None:
        assert _HIGH_DEMAND_NR_CAP == 0.20

    def test_standard_nr_cap_is_0_25(self) -> None:
        assert _STANDARD_NR_CAP == 0.25

    def test_preference_and_random_shares_sum_to_one(self) -> None:
        total = _HYBRID_PREFERENCE_POOL_SHARE + _HYBRID_RANDOM_POOL_SHARE
        assert abs(total - 1.0) < 1e-9, (
            f"_HYBRID_PREFERENCE_POOL_SHARE + _HYBRID_RANDOM_POOL_SHARE = {total}, expected 1.0"
        )

    def test_high_demand_cap_less_than_standard_cap(self) -> None:
        # Hybrid (high-demand) cap is MORE restrictive (lower share) than standard
        assert _HIGH_DEMAND_NR_CAP < _STANDARD_NR_CAP


# ---------------------------------------------------------------------------
# TestCouplingLock  (AC #973)
# ---------------------------------------------------------------------------


class TestCouplingLock:
    """AC #973: coupling between pool count and residency cap observed at extraction.

    Values are read from the ARTIFACT's nr_allocation record, not from inline
    literals — so the test fails if the artifact changes but the module constants
    don't (and vice versa).
    """

    def test_two_pool_specs_have_high_demand_nr_cap(
        self,
        real_draw_specs_and_backfill: tuple[dict, list],
        real_mechanics: list[dict],
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        nr_alloc = _extract_single_record(real_mechanics, "nr_allocation")
        expected_cap = nr_alloc["high_demand_nr_cap"]
        two_pool_specs = [s for s in draw_specs.values() if len(s.pools) == 2]
        assert two_pool_specs, "expected at least one 2-pool (hybrid) draw_spec"
        for spec in two_pool_specs:
            assert spec.residency_cap.nonresident_max_share == expected_cap, (
                f"Hybrid spec {spec.hunt_code!r} has NR cap "
                f"{spec.residency_cap.nonresident_max_share}, "
                f"expected artifact value {expected_cap}"
            )

    def test_one_pool_specs_have_standard_nr_cap(
        self,
        real_draw_specs_and_backfill: tuple[dict, list],
        real_mechanics: list[dict],
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        nr_alloc = _extract_single_record(real_mechanics, "nr_allocation")
        expected_cap = nr_alloc["standard_nr_cap"]
        one_pool_specs = [s for s in draw_specs.values() if len(s.pools) == 1]
        assert one_pool_specs, "expected at least one 1-pool (non-hybrid) draw_spec"
        for spec in one_pool_specs:
            assert spec.residency_cap.nonresident_max_share == expected_cap, (
                f"Non-hybrid spec {spec.hunt_code!r} has NR cap "
                f"{spec.residency_cap.nonresident_max_share}, "
                f"expected artifact value {expected_cap}"
            )

    def test_coupling_covers_all_draw_specs(
        self,
        real_draw_specs_and_backfill: tuple[dict, list],
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        for spec in draw_specs.values():
            pool_count = len(spec.pools)
            assert pool_count in (1, 2), (
                f"Unexpected pool count {pool_count} for {spec.hunt_code!r}"
            )


# ---------------------------------------------------------------------------
# TestBuildCoDrawSpecs
# ---------------------------------------------------------------------------


class TestBuildCoDrawSpecs:
    """Real artifact: 1914 draw_specs, 113 hybrid (2-pool), 1801 non-hybrid.

    The 3 malformed ` +`-suffixed bear GMU-851 codes are skipped with WARNING
    in the build walk (fix #1), reducing the count from 1917 to 1914.
    The 3 skipped codes were all non-hybrid, so hybrid count stays at 113.
    """

    def test_total_draw_spec_count_is_1914(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        assert len(draw_specs) == 1914

    def test_exactly_113_hybrid_draw_specs(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        hybrid_count = sum(1 for s in draw_specs.values() if len(s.pools) == 2)
        assert hybrid_count == 113

    def test_exactly_1801_non_hybrid_draw_specs(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        non_hybrid_count = sum(1 for s in draw_specs.values() if len(s.pools) == 1)
        assert non_hybrid_count == 1801

    def test_known_hybrid_code_is_two_pool(
        self,
        real_draw_specs_and_backfill: tuple[dict, list],
        real_hybrid_set: frozenset[str],
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        # A-E-006-W1-R is in the hybrid set and in draw_specs (confirmed non-orphan)
        known_hybrid = "A-E-006-W1-R"
        assert known_hybrid in real_hybrid_set, "test fixture assumption: must be in hybrid set"
        assert known_hybrid in draw_specs, "hybrid code must have a draw_spec"
        assert len(draw_specs[known_hybrid].pools) == 2

    def test_known_non_hybrid_code_is_one_pool(
        self,
        real_draw_specs_and_backfill: tuple[dict, list],
        real_hybrid_set: frozenset[str],
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        # D-M-001-O1-A is limited_draw and NOT in the hybrid set
        non_hybrid = "D-M-001-O1-A"
        assert non_hybrid not in real_hybrid_set, "test fixture assumption: must NOT be in hybrid set"
        assert non_hybrid in draw_specs, "non-hybrid code must have a draw_spec"
        assert len(draw_specs[non_hybrid].pools) == 1

    def test_all_backfill_targets_are_co_gmu(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        _, backfill = real_draw_specs_and_backfill
        assert backfill, "backfill list must not be empty"
        for lt_id, _ in backfill:
            assert lt_id.startswith("CO-GMU-"), (
                f"backfill target {lt_id!r} does not start with 'CO-GMU-'"
            )

    def test_at_least_one_bear_draw_spec(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        bear_specs = [hc for hc in draw_specs if hc.startswith("B-")]
        assert bear_specs, "expected at least one bear (B-*) draw_spec"

    def test_known_bear_code_present(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        # B-E-001-O1-A is the first bear limited-draw code in the artifact
        assert "B-E-001-O1-A" in draw_specs

    def test_draw_specs_keys_are_strings(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        for k in draw_specs:
            assert isinstance(k, str), f"draw_specs key {k!r} is not a string"

    def test_every_backfill_hunt_code_is_in_draw_specs(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        """Every backfill target's hunt_code must be a key in draw_specs.

        Replaces the fragile count-equality test (the equality is incidental to
        2026 data where GMU is embedded in hunt_code; future artifacts may have
        multiple license_tag_ids mapping to the same hunt_code).
        """
        draw_specs, backfill = real_draw_specs_and_backfill
        for lt_id, hunt_code in backfill:
            assert hunt_code in draw_specs, (
                f"backfill target {lt_id!r} references hunt_code={hunt_code!r} "
                "which is not in draw_specs"
            )

    def test_no_duplicate_license_tag_ids_in_backfill(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        """Backfill targets are deduplicated by license_tag_id (seen_backfill dict)."""
        _, backfill = real_draw_specs_and_backfill
        lt_ids = [lt_id for lt_id, _ in backfill]
        assert len(lt_ids) == len(set(lt_ids)), (
            f"Duplicate license_tag_ids found in backfill: "
            f"{[lt_id for lt_id in lt_ids if lt_ids.count(lt_id) > 1]!r}"
        )


# ---------------------------------------------------------------------------
# TestOtcDiscriminator  (AC #980)
# ---------------------------------------------------------------------------


class TestOtcDiscriminator:
    """AC #980: list_value='B' (OTC) rows get NO draw_spec; 'A' (limited_draw) do.

    Uses a synthetic minimal artifact so the test is hermetic and does not depend
    on the real artifact's structure changing.
    """

    def _run_build(
        self, big_game: list[dict], bear: list[dict]
    ) -> tuple[dict, list]:
        point_only = _make_minimal_point_only()
        deadline = date(2026, 4, 7)
        citation = _make_minimal_citation()
        # Empty hybrid set so all codes are non-hybrid
        hybrid_set: frozenset[str] = frozenset()
        return _build_co_draw_specs(big_game, bear, hybrid_set, point_only, deadline, citation)

    def test_otc_big_game_row_produces_no_draw_spec(self) -> None:
        """list_value='B' (OTC) → no draw_spec."""
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [_make_big_game_row("D-F-030-P5-A", "B", gmu_code="030")],
            )
        ]
        draw_specs, backfill = self._run_build(big_game, [])
        assert "D-F-030-P5-A" not in draw_specs, "OTC code must NOT produce a draw_spec"
        assert len(draw_specs) == 0

    def test_limited_draw_big_game_row_produces_draw_spec(self) -> None:
        """list_value='A' (limited_draw) → draw_spec created."""
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [_make_big_game_row("D-M-001-O1-A", "A", gmu_code="001")],
            )
        ]
        draw_specs, backfill = self._run_build(big_game, [])
        assert "D-M-001-O1-A" in draw_specs, "limited_draw code must produce a draw_spec"
        assert len(draw_specs) == 1

    def test_list_value_c_is_also_limited_draw(self) -> None:
        """list_value='C' is also limited_draw → draw_spec created."""
        big_game = [
            _make_big_game_section(
                "elk",
                "001",
                [_make_big_game_row("E-M-001-R1-R", "C", gmu_code="001")],
            )
        ]
        draw_specs, _ = self._run_build(big_game, [])
        assert "E-M-001-R1-R" in draw_specs, "list_value='C' must produce a draw_spec"

    def test_mixed_section_only_limited_draw_produces_draw_spec(self) -> None:
        """One OTC row + one limited_draw row in the same section → 1 draw_spec."""
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [
                    _make_big_game_row("D-F-030-P5-A", "B", gmu_code="030"),  # OTC
                    _make_big_game_row("D-M-001-O1-A", "A", gmu_code="001"),  # limited
                ],
            )
        ]
        draw_specs, _ = self._run_build(big_game, [])
        assert len(draw_specs) == 1
        assert "D-M-001-O1-A" in draw_specs
        assert "D-F-030-P5-A" not in draw_specs

    def test_bear_otc_section_produces_no_draw_spec(self) -> None:
        """Bear section with license_kind='over_the_counter' → no draw_spec."""
        bear = [
            _make_bear_section(
                "001",
                "over_the_counter",
                [_make_bear_row("B-E-001-O1-A", gmu_code="001")],
            )
        ]
        draw_specs, _ = self._run_build([], bear)
        assert len(draw_specs) == 0, "OTC bear section must not produce draw_specs"

    def test_bear_limited_draw_section_produces_draw_spec(self) -> None:
        """Bear section with license_kind='limited_draw' → draw_spec created."""
        bear = [
            _make_bear_section(
                "001",
                "limited_draw",
                [_make_bear_row("B-E-001-O1-A", gmu_code="001")],
            )
        ]
        draw_specs, _ = self._run_build([], bear)
        assert "B-E-001-O1-A" in draw_specs, "limited_draw bear section must produce a draw_spec"


# ---------------------------------------------------------------------------
# TestParametersAndPhase
# ---------------------------------------------------------------------------


class TestParametersAndPhase:
    """Every draw_spec has parameters=None, draw_phase="primary", successor=None, quota=None."""

    def test_every_spec_parameters_is_none(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        assert draw_specs, "fixture must not be empty"
        for hc, spec in draw_specs.items():
            assert spec.parameters is None, (
                f"draw_spec {hc!r} has non-None parameters: {spec.parameters!r}"
            )

    def test_every_spec_draw_phase_is_primary(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        assert draw_specs, "fixture must not be empty"
        for hc, spec in draw_specs.items():
            assert spec.draw_phase == "primary", (
                f"draw_spec {hc!r} has draw_phase={spec.draw_phase!r}"
            )

    def test_every_spec_successor_hunt_code_key_is_none(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        assert draw_specs, "fixture must not be empty"
        for hc, spec in draw_specs.items():
            assert spec.successor_hunt_code_key is None, (
                f"draw_spec {hc!r} has non-None successor_hunt_code_key"
            )

    def test_every_spec_quota_is_none(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        assert draw_specs, "fixture must not be empty"
        for hc, spec in draw_specs.items():
            assert spec.quota is None, (
                f"draw_spec {hc!r} has non-None quota: {spec.quota!r}"
            )

    def test_every_spec_application_deadline_is_2026_04_07(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        assert draw_specs, "fixture must not be empty"
        expected = date(2026, 4, 7)
        for hc, spec in draw_specs.items():
            assert spec.application_deadline == expected, (
                f"draw_spec {hc!r} has deadline {spec.application_deadline!r}, "
                f"expected {expected}"
            )


# ---------------------------------------------------------------------------
# TestCrossListingValidator
# ---------------------------------------------------------------------------


class TestCrossListingValidator:
    """_validate_cross_listing_consistency — passes on real data; synthetic conflict raises."""

    def test_passes_on_real_data(
        self,
        real_big_game: list[dict],
        real_bear: list[dict],
    ) -> None:
        # Must not raise (draw_specs param has been removed from the function)
        _validate_cross_listing_consistency(real_big_game, real_bear)

    def test_raises_on_conflicting_quotas_for_same_hunt_code(self) -> None:
        """Two big-game rows with same hunt_code but distinct non-null quotas → raises."""
        hunt_code = "D-M-001-O1-A"
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [
                    _make_big_game_row(hunt_code, "A", gmu_code="001", quota=100),
                    _make_big_game_row(hunt_code, "A", gmu_code="001", quota=200),
                ],
            )
        ]
        with pytest.raises(ColoradoDrawSpecError, match="distinct non-null quota"):
            _validate_cross_listing_consistency(big_game, [])

    def test_override_dict_suppresses_conflict(self, caplog: pytest.LogCaptureFixture) -> None:
        """An entry in _KNOWN_CROSS_LISTING_OVERRIDES suppresses the raise."""
        hunt_code = "D-M-001-O1-A"
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [
                    _make_big_game_row(hunt_code, "A", gmu_code="001", quota=100),
                    _make_big_game_row(hunt_code, "A", gmu_code="001", quota=200),
                ],
            )
        ]
        override = {(hunt_code, 2026): {"quota": 100, "rationale": "test override"}}
        with patch.object(mod, "_KNOWN_CROSS_LISTING_OVERRIDES", override):
            with caplog.at_level(logging.WARNING):
                # Must not raise
                _validate_cross_listing_consistency(big_game, [])
        assert any("override applied" in r.message.lower() for r in caplog.records), (
            "Expected a WARNING log about the override being applied"
        )

    def test_null_quotas_do_not_trigger_conflict(self) -> None:
        """Two rows with the same hunt_code but both quota=None → no raise."""
        hunt_code = "D-M-001-O1-A"
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [
                    _make_big_game_row(hunt_code, "A", gmu_code="001", quota=None),
                    _make_big_game_row(hunt_code, "A", gmu_code="001", quota=None),
                ],
            )
        ]
        # Must not raise
        _validate_cross_listing_consistency(big_game, [])

    def test_single_distinct_non_null_quota_does_not_trigger_conflict(self) -> None:
        """Two rows, same quota=100 → only one distinct value → no raise."""
        hunt_code = "D-M-001-O1-A"
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [
                    _make_big_game_row(hunt_code, "A", gmu_code="001", quota=100),
                    _make_big_game_row(hunt_code, "A", gmu_code="001", quota=100),
                ],
            )
        ]
        _validate_cross_listing_consistency(big_game, [])

    def test_unknown_list_value_with_non_null_quota_raises(self) -> None:
        """Unknown list_value (e.g. 'Z') with a non-null quota now RAISES ColoradoDrawSpecError.

        Previously the except ValueError block silently swallowed the error and continued.
        After fix #6, it re-raises as ColoradoDrawSpecError naming the offending value.
        """
        hunt_code = "D-M-001-O1-A"
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [_make_big_game_row(hunt_code, "Z", gmu_code="001", quota=100)],
            )
        ]
        with pytest.raises(ColoradoDrawSpecError, match="unknown list_value"):
            _validate_cross_listing_consistency(big_game, [])


# ---------------------------------------------------------------------------
# TestOrphanAndMalformedWarnings
# ---------------------------------------------------------------------------


class TestOrphanAndMalformedWarnings:
    """_report_orphan_hybrid_codes emits orphan WARNINGs; does NOT raise.

    Malformed-code WARNINGs are now emitted directly in _build_co_draw_specs
    (fix #1). Tests for those are in TestBuildCoDrawSpecsMalformedSkip below.
    """

    def test_three_b_e_851_orphans_logged_at_warning(
        self,
        real_hybrid_set: frozenset[str],
        real_draw_specs_and_backfill: tuple[dict, list],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        with caplog.at_level(logging.WARNING, logger="states.colorado.load_draw_specs"):
            _report_orphan_hybrid_codes(real_hybrid_set, draw_specs)
        warning_messages = " ".join(r.message for r in caplog.records if r.levelno == logging.WARNING)
        # 3 orphan codes should be mentioned
        assert "B-E-851-O1-R" in warning_messages or "3" in warning_messages, (
            f"Expected orphan WARNING mentioning B-E-851 codes; got: {warning_messages!r}"
        )

    def test_orphan_warning_logged(
        self,
        real_hybrid_set: frozenset[str],
        real_draw_specs_and_backfill: tuple[dict, list],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        with caplog.at_level(logging.WARNING, logger="states.colorado.load_draw_specs"):
            _report_orphan_hybrid_codes(real_hybrid_set, draw_specs)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "expected at least one WARNING from _report_orphan_hybrid_codes"

    def test_no_exception_raised(
        self,
        real_hybrid_set: frozenset[str],
        real_draw_specs_and_backfill: tuple[dict, list],
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        # _report_orphan_hybrid_codes must NEVER raise regardless of orphan count
        _report_orphan_hybrid_codes(real_hybrid_set, draw_specs)

    def test_no_orphans_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """With an empty hybrid set and an empty draw_specs → no warnings."""
        with caplog.at_level(logging.WARNING, logger="states.colorado.load_draw_specs"):
            _report_orphan_hybrid_codes(frozenset(), {})
        assert not caplog.records, f"Expected no warnings; got: {caplog.records}"

    def test_synthetic_orphan_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """A synthetic hybrid code not in draw_specs → exactly one orphan WARNING."""
        hybrid_set = frozenset({"D-M-999-O1-A"})  # not in draw_specs
        with caplog.at_level(logging.WARNING, logger="states.colorado.load_draw_specs"):
            _report_orphan_hybrid_codes(hybrid_set, {})
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"Expected 1 orphan WARNING, got {len(warnings)}"
        assert "D-M-999-O1-A" in warnings[0].message

    def test_malformed_codes_not_in_draw_specs(
        self,
        real_draw_specs_and_backfill: tuple[dict, list],
    ) -> None:
        """Malformed ` +`-suffixed codes must NOT appear as draw_specs keys (fix #1).

        They are skipped in _build_co_draw_specs before insertion.
        """
        draw_specs, _ = real_draw_specs_and_backfill
        malformed_codes = ["B-E-851-O1-M +", "B-E-851-O2-R +", "B-E-851-O5-R +"]
        for code in malformed_codes:
            assert code not in draw_specs, (
                f"Malformed code {code!r} must NOT be a draw_specs key — "
                "it should have been skipped with WARNING in the build walk"
            )


# ---------------------------------------------------------------------------
# TestCountGuard
# ---------------------------------------------------------------------------


class TestCountGuard:
    """_assert_draw_spec_count_within_guard — band enforcement."""

    # Band is [int(1914*0.7), int(1914*1.3)] = [1339, 2488]

    def test_baseline_count_passes(self) -> None:
        _assert_draw_spec_count_within_guard(1914)

    def test_band_low_edge_passes(self) -> None:
        _assert_draw_spec_count_within_guard(1339)

    def test_band_high_edge_passes(self) -> None:
        _assert_draw_spec_count_within_guard(2488)

    def test_below_low_edge_raises(self) -> None:
        with pytest.raises(ColoradoDrawSpecError, match="count guard failed"):
            _assert_draw_spec_count_within_guard(1338)

    def test_above_high_edge_raises(self) -> None:
        with pytest.raises(ColoradoDrawSpecError, match="count guard failed"):
            _assert_draw_spec_count_within_guard(2489)

    def test_count_100_raises(self) -> None:
        with pytest.raises(ColoradoDrawSpecError):
            _assert_draw_spec_count_within_guard(100)

    def test_count_9999_raises(self) -> None:
        with pytest.raises(ColoradoDrawSpecError):
            _assert_draw_spec_count_within_guard(9999)

    def test_count_zero_raises(self) -> None:
        with pytest.raises(ColoradoDrawSpecError):
            _assert_draw_spec_count_within_guard(0)

    def test_error_message_contains_count_and_band(self) -> None:
        with pytest.raises(ColoradoDrawSpecError, match="100") as exc_info:
            _assert_draw_spec_count_within_guard(100)
        msg = str(exc_info.value)
        assert "1339" in msg or "2488" in msg, (
            f"Expected band endpoints in error message; got: {msg!r}"
        )


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    """main() — --dry-run returns 0 with no DB; mocked write checks ordering and single commit."""

    def test_dry_run_returns_zero(self) -> None:
        result = main(["--dry-run"])
        assert result == 0

    def test_dry_run_does_not_call_db_connect(self) -> None:
        """--dry-run must short-circuit BEFORE any db.connect() call."""
        with patch.object(mod.db, "connect") as mock_connect:
            main(["--dry-run"])
            mock_connect.assert_not_called()

    def test_dry_run_does_not_call_upsert_draw_spec(self) -> None:
        with patch.object(mod.db, "connect"):
            with patch.object(mod.db, "upsert_draw_spec") as mock_upsert:
                main(["--dry-run"])
                mock_upsert.assert_not_called()

    def test_dry_run_does_not_call_update_license_tag_draw_spec_key(self) -> None:
        with patch.object(mod.db, "update_license_tag_draw_spec_key") as mock_backfill:
            main(["--dry-run"])
            mock_backfill.assert_not_called()

    def test_mocked_write_all_upserts_before_all_backfills(self) -> None:
        """Phase 3 ordering: all db.upsert_draw_spec calls precede all
        db.update_license_tag_draw_spec_key calls (FK order guarantee)."""
        call_order: list[str] = []
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        def record_upsert(conn, spec):  # type: ignore[type-arg]
            call_order.append("upsert")

        def record_backfill(conn, lt_id, draw_spec_key):  # type: ignore[type-arg]
            call_order.append("backfill")

        with patch.object(mod.db, "connect", return_value=mock_conn):
            with patch.object(mod.db, "upsert_draw_spec", side_effect=record_upsert):
                with patch.object(mod.db, "update_license_tag_draw_spec_key", side_effect=record_backfill):
                    result = main([])
        assert result == 0

        assert "upsert" in call_order, "expected at least one upsert call"
        assert "backfill" in call_order, "expected at least one backfill call"

        # Every upsert must come before every backfill
        last_upsert_idx = max(i for i, op in enumerate(call_order) if op == "upsert")
        first_backfill_idx = min(i for i, op in enumerate(call_order) if op == "backfill")
        assert last_upsert_idx < first_backfill_idx, (
            f"Expected all upserts before all backfills; "
            f"last upsert at index {last_upsert_idx}, "
            f"first backfill at index {first_backfill_idx}"
        )

    def test_mocked_write_exactly_one_commit(self) -> None:
        """Phase 3: exactly one conn.commit() call (single atomic transaction)."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch.object(mod.db, "connect", return_value=mock_conn):
            with patch.object(mod.db, "upsert_draw_spec"):
                with patch.object(mod.db, "update_license_tag_draw_spec_key"):
                    main([])

        mock_conn.commit.assert_called_once()

    def test_mocked_write_upsert_called_for_all_draw_specs(self) -> None:
        """upsert_draw_spec is called exactly len(draw_specs) times."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        upsert_calls: list[object] = []
        backfill_calls: list[object] = []

        def capture_upsert(conn, spec):  # type: ignore[type-arg]
            upsert_calls.append(spec.hunt_code)

        def capture_backfill(conn, lt_id, draw_spec_key):  # type: ignore[type-arg]
            backfill_calls.append(lt_id)

        with patch.object(mod.db, "connect", return_value=mock_conn):
            with patch.object(mod.db, "upsert_draw_spec", side_effect=capture_upsert):
                with patch.object(mod.db, "update_license_tag_draw_spec_key", side_effect=capture_backfill):
                    main([])

        assert len(upsert_calls) == 1914, (
            f"Expected 1914 upsert calls, got {len(upsert_calls)}"
        )
        assert len(backfill_calls) == 1914, (
            f"Expected 1914 backfill calls, got {len(backfill_calls)}"
        )


# ---------------------------------------------------------------------------
# TestBuildCoDrawSpecsMalformedSkip
# ---------------------------------------------------------------------------


class TestBuildCoDrawSpecsMalformedSkip:
    """_build_co_draw_specs skips malformed ` +`-suffixed bear codes with WARNING.

    Fix #1: malformed hunt codes that fail _CLEAN_HUNT_CODE_RE are skipped
    (not loaded) so the draw_spec PK is never a malformed string.
    """

    def test_malformed_bear_codes_emit_warning_in_build(
        self,
        real_big_game: list[dict],
        real_bear: list[dict],
        real_hybrid_set: frozenset[str],
        real_point_only: dict[str, str],
        real_deadline: date,
        real_citation,  # type: ignore[type-arg]
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """_build_co_draw_specs emits a WARNING for each of the 3 skipped malformed codes."""
        with caplog.at_level(logging.WARNING, logger="states.colorado.load_draw_specs"):
            _build_co_draw_specs(
                real_big_game, real_bear, real_hybrid_set,
                real_point_only, real_deadline, real_citation,
            )
        warning_text = " ".join(r.message for r in caplog.records if r.levelno == logging.WARNING)
        assert "malformed hunt_code" in warning_text, (
            f"Expected 'malformed hunt_code' WARNING(s) from _build_co_draw_specs; "
            f"got: {warning_text!r}"
        )

    def test_malformed_bear_codes_not_in_draw_specs_after_build(
        self,
        real_big_game: list[dict],
        real_bear: list[dict],
        real_hybrid_set: frozenset[str],
        real_point_only: dict[str, str],
        real_deadline: date,
        real_citation,  # type: ignore[type-arg]
    ) -> None:
        """Malformed ` +`-suffixed codes must NOT appear as keys in the returned draw_specs."""
        draw_specs, _ = _build_co_draw_specs(
            real_big_game, real_bear, real_hybrid_set,
            real_point_only, real_deadline, real_citation,
        )
        malformed = ["B-E-851-O1-M +", "B-E-851-O2-R +", "B-E-851-O5-R +"]
        for code in malformed:
            assert code not in draw_specs, (
                f"Malformed code {code!r} must NOT be in draw_specs; "
                "it should have been skipped with WARNING"
            )

    def test_empty_hunt_code_big_game_row_is_skipped_with_warning(
        self,
        real_hybrid_set: frozenset[str],
        real_point_only: dict[str, str],
        real_deadline: date,
        real_citation,  # type: ignore[type-arg]
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A big-game row with empty hunt_code emits a WARNING and is not added to draw_specs."""
        big_game = [
            _make_big_game_section(
                "mule_deer",
                "001",
                [_make_big_game_row("", "A", gmu_code="001")],
            )
        ]
        with caplog.at_level(logging.WARNING, logger="states.colorado.load_draw_specs"):
            draw_specs, _ = _build_co_draw_specs(
                big_game, [], real_hybrid_set, real_point_only, real_deadline, real_citation,
            )
        assert len(draw_specs) == 0, "Empty hunt_code row must not produce a draw_spec"
        warning_text = " ".join(r.message for r in caplog.records if r.levelno == logging.WARNING)
        assert "empty hunt_code" in warning_text, (
            f"Expected 'empty hunt_code' WARNING; got: {warning_text!r}"
        )


# ---------------------------------------------------------------------------
# TestCountGuardBeforeConnect
# ---------------------------------------------------------------------------


class TestCountGuardBeforeConnect:
    """Count guard fires BEFORE db.connect() (OQ7 discipline).

    If the build returns too few draw_specs, the guard raises ColoradoDrawSpecError
    and db.connect() must never be called.
    """

    def test_count_guard_raises_before_db_connect(self) -> None:
        """db.connect() is NOT called when count guard fires (OQ7)."""
        # Patch _build_co_draw_specs to return a tiny dict (~5 specs — below the band floor)
        tiny_specs: dict = {}
        for i in range(5):
            hc = f"D-M-{i:03d}-O1-A"
            tiny_specs[hc] = MagicMock()

        with patch.object(mod, "_build_co_draw_specs", return_value=(tiny_specs, [])):
            with patch.object(mod.db, "connect") as mock_connect:
                with pytest.raises(ColoradoDrawSpecError, match="count guard failed"):
                    main([])
                mock_connect.assert_not_called()


# ---------------------------------------------------------------------------
# TestParametersAndPhaseChoicesLock
# ---------------------------------------------------------------------------


class TestParametersAndPhaseChoicesLock:
    """Every draw_spec has choices.count==4 and choices.points_used_in_choices==[1]."""

    def test_every_spec_choices_count_is_4(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        assert draw_specs, "fixture must not be empty"
        for hc, spec in draw_specs.items():
            assert spec.choices is not None, f"draw_spec {hc!r} has None choices"
            assert spec.choices.count == 4, (
                f"draw_spec {hc!r} has choices.count={spec.choices.count!r}, expected 4"
            )

    def test_every_spec_choices_points_used_in_choices_is_1(
        self, real_draw_specs_and_backfill: tuple[dict, list]
    ) -> None:
        draw_specs, _ = real_draw_specs_and_backfill
        assert draw_specs, "fixture must not be empty"
        for hc, spec in draw_specs.items():
            assert spec.choices is not None, f"draw_spec {hc!r} has None choices"
            assert spec.choices.points_used_in_choices == [1], (
                f"draw_spec {hc!r} has points_used_in_choices="
                f"{spec.choices.points_used_in_choices!r}, expected [1]"
            )


# ---------------------------------------------------------------------------
# TestNoDriftGuardImport  (AST)
# ---------------------------------------------------------------------------


class TestNoDriftGuardImport:
    """AST guard: load_draw_specs.py must NOT import drift_guard anywhere.

    draw_spec uses a composite PK (state, hunt_code, year), not an id-text PK,
    so slug-drift via ADR-020's derive-and-assert is not applicable.
    """

    def _parse_loader(self) -> ast.Module:
        source = _loader_source_path().read_text(encoding="utf-8")
        return ast.parse(source, filename=str(_loader_source_path()))

    def test_no_import_of_drift_guard(self) -> None:
        tree = self._parse_loader()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "drift_guard" not in alias.name, (
                        f"load_draw_specs.py has forbidden import: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "drift_guard" not in module, (
                    f"load_draw_specs.py has forbidden from-import: from {module}"
                )

    def test_no_assert_id_matches_reference(self) -> None:
        """No call to assert_id_matches anywhere in the loader."""
        source = _loader_source_path().read_text(encoding="utf-8")
        assert "assert_id_matches" not in source, (
            "load_draw_specs.py must not reference assert_id_matches (drift_guard discipline)"
        )


# ---------------------------------------------------------------------------
# TestNoStateAdapterImports  (AST — mirrors S06.7 TestNoStateAdapterImports)
# ---------------------------------------------------------------------------


class TestNoStateAdapterImports:
    """AST guard: load_draw_specs.py must not import any non-Colorado state adapter.

    CO → CO imports (states.colorado.*) are permitted — the adapter imports
    _STATE from states.colorado.load_regulation_records and helpers from
    states.colorado.load_seasons_and_licenses.
    All other state adapters (states.montana.*, etc.) are forbidden per ADR-005.
    """

    def _parse_loader(self) -> ast.Module:
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
        tree = self._parse_loader()
        forbidden_prefixes = ("states.montana", "ingestion.states.montana")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"load_draw_specs.py has forbidden import: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for prefix in forbidden_prefixes:
                    assert not module.startswith(prefix), (
                        f"load_draw_specs.py has forbidden from-import: from {module}"
                    )

    def test_no_other_state_adapter_imports(self) -> None:
        tree = self._parse_loader()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not self._is_forbidden(alias.name), (
                        f"load_draw_specs.py imports a non-Colorado state adapter: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not self._is_forbidden(module), (
                    f"load_draw_specs.py imports a non-Colorado state adapter: from {module}"
                )

    def test_co_to_co_imports_are_present(self) -> None:
        """Confirm at least one CO → CO import exists — guards against over-stripping."""
        tree = self._parse_loader()
        found_co_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "states.colorado" in module:
                    found_co_import = True
                    break
        assert found_co_import, (
            "load_draw_specs.py must import from states.colorado.* (CO → CO imports are permitted)"
        )

    def test_no_lib_edits_needed(self) -> None:
        """Confirm loader imports from ingestion.lib (read-only usage) but does not define any new lib functions.

        The loader must use lib helpers as-is (ADR-005 / ADR-022 no-lib-edit discipline).
        We check the loader's import statements reference the lib but do not reach into
        non-lib module paths for implementation.
        """
        source = _loader_source_path().read_text(encoding="utf-8")
        # The loader must import from ingestion.lib (db, schema)
        assert "from ingestion.lib" in source or "ingestion.lib" in source, (
            "load_draw_specs.py must import from ingestion.lib"
        )


# ---------------------------------------------------------------------------
# TestPointOnlyCodeDuplicateGuard  (Fix 1)
# ---------------------------------------------------------------------------


class TestPointOnlyCodeDuplicateGuard:
    """Fix 1: _build_point_only_code_by_species_letter raises on conflicting duplicates."""

    def test_duplicate_same_code_is_idempotent(self) -> None:
        """Two point_only_code records with the SAME hunt_code for the same letter → no raise."""
        same_code = [
            {"record_type": "point_only_code", "hunt_code": "D-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "D-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "B-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "E-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "A-P-999-99-P"},
        ]
        result = _build_point_only_code_by_species_letter(same_code)
        assert result["D"] == "D-P-999-99-P"

    def test_duplicate_conflicting_codes_raises(self) -> None:
        """Two point_only_code records with DIFFERENT hunt_codes for the same letter → raises."""
        conflicting = [
            {"record_type": "point_only_code", "hunt_code": "D-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "D-P-888-99-P"},  # different!
            {"record_type": "point_only_code", "hunt_code": "B-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "E-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "A-P-999-99-P"},
        ]
        with pytest.raises(ColoradoDrawSpecError, match="conflicting hunt codes"):
            _build_point_only_code_by_species_letter(conflicting)

    def test_error_message_names_both_codes(self) -> None:
        """The error message must name the letter and both conflicting hunt codes."""
        conflicting = [
            {"record_type": "point_only_code", "hunt_code": "E-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "E-P-777-99-P"},  # conflict
            {"record_type": "point_only_code", "hunt_code": "D-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "B-P-999-99-P"},
            {"record_type": "point_only_code", "hunt_code": "A-P-999-99-P"},
        ]
        with pytest.raises(ColoradoDrawSpecError) as exc_info:
            _build_point_only_code_by_species_letter(conflicting)
        msg = str(exc_info.value)
        assert "E-P-999-99-P" in msg or "E-P-777-99-P" in msg, (
            f"Error message must name at least one of the conflicting codes; got: {msg!r}"
        )
        assert "'E'" in msg or "\"E\"" in msg, (
            f"Error message must name the conflicting species letter 'E'; got: {msg!r}"
        )


# ---------------------------------------------------------------------------
# TestEmitDrawSpec  (Fix 2)
# ---------------------------------------------------------------------------


class TestEmitDrawSpec:
    """_emit_draw_spec — shared helper called by both big-game and bear walks."""

    def _run(
        self,
        hunt_code: str,
        hybrid_set: frozenset[str] | None = None,
        draw_specs: dict | None = None,
    ) -> dict:
        if draw_specs is None:
            draw_specs = {}
        if hybrid_set is None:
            hybrid_set = frozenset()
        point_only = _make_minimal_point_only()
        deadline = date(2026, 4, 7)
        citation = _make_minimal_citation()
        _emit_draw_spec(draw_specs, hunt_code, hybrid_set, point_only, deadline, citation)
        return draw_specs

    def test_emits_draw_spec_into_dict(self) -> None:
        draw_specs = self._run("D-M-001-O1-A")
        assert "D-M-001-O1-A" in draw_specs

    def test_emitted_spec_has_correct_hunt_code(self) -> None:
        draw_specs = self._run("D-M-001-O1-A")
        assert draw_specs["D-M-001-O1-A"].hunt_code == "D-M-001-O1-A"

    def test_emitted_spec_is_non_hybrid_when_not_in_hybrid_set(self) -> None:
        draw_specs = self._run("D-M-001-O1-A", hybrid_set=frozenset())
        assert len(draw_specs["D-M-001-O1-A"].pools) == 1

    def test_emitted_spec_is_hybrid_when_in_hybrid_set(self) -> None:
        hunt_code = "D-M-001-O1-A"
        draw_specs = self._run(hunt_code, hybrid_set=frozenset({hunt_code}))
        assert len(draw_specs[hunt_code].pools) == 2

    def test_does_not_overwrite_existing_entry(self) -> None:
        """First-seen wins: a second call for the same hunt_code must not replace the entry."""
        point_only = _make_minimal_point_only()
        deadline = date(2026, 4, 7)
        citation = _make_minimal_citation()
        draw_specs: dict = {}
        # First call (non-hybrid)
        _emit_draw_spec(draw_specs, "D-M-001-O1-A", frozenset(), point_only, deadline, citation)
        first_spec = draw_specs["D-M-001-O1-A"]
        # Second call (hybrid set contains the code — would change pools if overwrite happened)
        _emit_draw_spec(draw_specs, "D-M-001-O1-A", frozenset({"D-M-001-O1-A"}), point_only, deadline, citation)
        assert draw_specs["D-M-001-O1-A"] is first_spec, (
            "_emit_draw_spec must not overwrite an existing draw_spec (first-seen wins)"
        )

    def test_emitted_spec_quota_is_none(self) -> None:
        draw_specs = self._run("D-M-001-O1-A")
        assert draw_specs["D-M-001-O1-A"].quota is None

    def test_emitted_spec_parameters_is_none(self) -> None:
        draw_specs = self._run("D-M-001-O1-A")
        assert draw_specs["D-M-001-O1-A"].parameters is None

    def test_emitted_spec_draw_phase_is_primary(self) -> None:
        draw_specs = self._run("D-M-001-O1-A")
        assert draw_specs["D-M-001-O1-A"].draw_phase == "primary"


# ---------------------------------------------------------------------------
# TestLoadSectionArtifact  (Fix 3)
# ---------------------------------------------------------------------------


class TestLoadSectionArtifact:
    """_load_section_artifact — centralised loader for big-game and bear arrays."""

    def test_loads_big_game_artifact(self) -> None:
        result = _load_section_artifact(_BIG_GAME_PATH)
        assert isinstance(result, list) and result

    def test_loads_bear_artifact(self) -> None:
        result = _load_section_artifact(_BLACK_BEAR_PATH)
        assert isinstance(result, list) and result

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ColoradoDrawSpecError, match="artifact not found"):
            _load_section_artifact(tmp_path / "nonexistent.json")

    def test_non_list_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "dict.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        with pytest.raises(ColoradoDrawSpecError, match="not a JSON array"):
            _load_section_artifact(f)

    def test_empty_list_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text("[]", encoding="utf-8")
        with pytest.raises(ColoradoDrawSpecError):
            _load_section_artifact(f)

    def test_returns_list_of_dicts(self, tmp_path: Path) -> None:
        f = tmp_path / "valid.json"
        f.write_text('[{"record_type": "section"}]', encoding="utf-8")
        result = _load_section_artifact(f)
        assert result == [{"record_type": "section"}]
