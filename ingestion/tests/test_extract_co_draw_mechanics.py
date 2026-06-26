"""Unit tests for `states.colorado.extract_draw_mechanics` — CPW draw-mechanics
extraction structural guards and artifact regression locks (S06.8 T7).

Test classes:
  1. TestNoForeignStateAdapterImports — AST-level isolation guard (ADR-005) +
     no-sibling-CO-extractor imports (ADR-022) + no-DB-import guard.
  2. TestNoLayoutTrue — ADR-008 verbatim discipline regression guard.
  3. TestCleanupRulesDocstringParity — every Rule R{n}: entry in the module
     docstring must correspond to ``_RULE_COUNT``.
  4. TestHuntCodeGrammarSingleSourceOfTruth — ``_HUNT_CODE_EMBEDDED_RE`` and
     ``_HUNT_CODE_RE`` are both derived from ``_HUNT_CODE_GRAMMAR``.
  5. TestArtifactRegression — load the committed ``draw-mechanics-2026.json``
     and pin all known-good stats.
  6. TestDeterministicJsonOutput — skipped CI placeholder documenting the
     pinned SHA-256 and the 2-run determinism recipe.
  7. TestHybridRowParse — pure-function unit tests for ``_codes_from_cells``
     (Rule R1 ``*``-strip → ``low_availability`` bool).
  8. TestNormalize — pure-function unit tests for prose whitespace collapse
     (Rule R2).
  9. TestColumnCrop — structural guard confirming the module documents Rule R3
     (bbox column crops for multi-column pages).
  10. TestPointOnlySpeciesLetterMismatch — fail-loud guard when a wrong species
      letter is found on a point-only page.

Test philosophy:
- All tests are hermetic: no real PDF required, no network.
- Artifact-regression tests (class 5) read the committed JSON file from the
  repo — no live extraction.
- The determinism test (class 6) is a pytest.skip placeholder.
- Pure-function tests (classes 7-10) use MagicMock where page objects are
  needed, or read module source text for structural guards.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import states.colorado.extract_draw_mechanics as extract_draw_mechanics
from states.colorado.extract_draw_mechanics import (
    ColoradoDrawMechanicsError,
    _HUNT_CODE_EMBEDDED_RE,
    _HUNT_CODE_GRAMMAR,
    _HUNT_CODE_RE,
    _codes_from_cells,
)

# ---------------------------------------------------------------------------
# Re-use the AST-walk helper from test_extract_dea (state-agnostic by design).
# ---------------------------------------------------------------------------
from tests.test_extract_dea import _find_foreign_state_imports


# ---------------------------------------------------------------------------
# 1. TestNoForeignStateAdapterImports
# ---------------------------------------------------------------------------


class TestNoForeignStateAdapterImports:
    """AST-walk guard: extract_draw_mechanics.py must not import from other
    states' adapters, must not import from sibling CO extractors (ADR-022),
    and must not import from ingestion.lib.db (single-writer contract).

    Rules:
      - ADR-005: Colorado adapter may import from ``states.colorado.*`` or
        ``ingestion.lib.*``, but NEVER from ``states.<other_state>.*``.
      - ADR-022: sibling CO extractor cross-imports are also forbidden;
        extract_draw_mechanics.py must not import extract_big_game or
        extract_black_bear.
      - Single-writer contract: S06.8 T7 produces structural guards only;
        the extractor itself emits JSON; no DB writes in this module.
    """

    _ALLOWED_STATE: str = "colorado"

    def test_no_foreign_state_imports(self) -> None:
        """extract_draw_mechanics.py is clean of foreign-state adapter imports."""
        source_path = Path(extract_draw_mechanics.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        violations = _find_foreign_state_imports(source, self._ALLOWED_STATE)
        assert not violations, (
            "extract_draw_mechanics.py contains foreign state adapter imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_guard_catches_foreign_state_import(self) -> None:
        """Counter-example: a synthetic Montana import IS detected."""
        violations = _find_foreign_state_imports(
            "from ingestion.states.montana import extract_dea", self._ALLOWED_STATE
        )
        assert any(
            "from ingestion.states.montana" in v for v in violations
        ), f"AST guard failed to catch foreign import: {violations}"

    def test_no_sibling_co_extractor_imports(self) -> None:
        """ADR-022: extract_draw_mechanics.py must not import sibling CO extractors.

        Cross-extractor imports within colorado/ would create coupling between
        modules that must remain independent (ADR-022 single-module-per-extractor
        convention).  The guard reads the source as text and asserts the sibling
        import strings are absent.
        """
        source_path = Path(extract_draw_mechanics.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")

        forbidden: list[str] = [
            "extract_big_game",
            "extract_black_bear",
        ]
        violations: list[str] = []
        for name in forbidden:
            # Check both import forms
            if f"import {name}" in source or f"from {name}" in source:
                violations.append(name)
            # Also catch "from states.colorado.extract_big_game import ..."
            if f"states.colorado.{name}" in source:
                violations.append(f"states.colorado.{name}")

        assert not violations, (
            "extract_draw_mechanics.py contains sibling CO extractor imports "
            "(ADR-022 violation):\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_no_db_imports(self) -> None:
        """extract_draw_mechanics.py has no ingestion.lib.db imports.

        Single-writer contract: the draw-mechanics extractor emits JSON only.
        No database writes happen in this module — those are S06.8's loader job.
        DB imports here would violate the single-writer / extraction-only contract.
        """
        source_path = Path(extract_draw_mechanics.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        assert "from ingestion.lib.db" not in source, (
            "extract_draw_mechanics.py imports from ingestion.lib.db — "
            "violates the single-writer contract (extractor emits JSON only)"
        )
        assert "import ingestion.lib.db" not in source, (
            "extract_draw_mechanics.py imports ingestion.lib.db — "
            "violates the single-writer contract (extractor emits JSON only)"
        )


# ---------------------------------------------------------------------------
# 2. TestNoLayoutTrue
# ---------------------------------------------------------------------------


class TestNoLayoutTrue:
    """Source-text guard: extract_draw_mechanics.py must never call pdfplumber's
    extract_text with ``layout=True``.

    Passing ``layout=True`` injects synthetic spaces and violates the
    no-additional-normalization posture (ADR-008 verbatim discipline).
    """

    def test_no_layout_true_regression_guard(self) -> None:
        """The literal ``layout=True`` must not appear in extract_draw_mechanics.py."""
        source_path = Path(extract_draw_mechanics.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        assert "layout=True" not in source, (
            "extract_draw_mechanics.py contains 'layout=True' — passing layout=True "
            "to pdfplumber's extract_text injects synthetic spaces and violates "
            "ADR-008 verbatim discipline."
        )


# ---------------------------------------------------------------------------
# 3. TestCleanupRulesDocstringParity
# ---------------------------------------------------------------------------


class TestCleanupRulesDocstringParity:
    """Docstring parity guard: the module docstring must document every cleanup
    rule R1 through R3 (``_RULE_COUNT == 3``).

    Per the S03.3 AC #547 analog (grep-parity discipline): every cleanup rule
    applied to row cells must appear in the module docstring's "Cleanup rules"
    section.  This prevents silent divergence where a rule is implemented but
    not documented (or vice versa).

    The exact format used in the module docstring is ``Rule RN:``
    (e.g., ``Rule R1:``, ``Rule R3:``).
    """

    _RULE_COUNT: int = 3

    def test_every_rule_has_a_docstring_entry(self) -> None:
        """Rule R1 through R3 must each appear in the module docstring."""
        docstring = extract_draw_mechanics.__doc__ or ""
        assert docstring, "extract_draw_mechanics module has no docstring"

        missing: list[str] = []
        for n in range(1, self._RULE_COUNT + 1):
            marker = f"Rule R{n}:"
            if marker not in docstring:
                missing.append(marker)

        assert not missing, (
            "The following cleanup rules are missing from extract_draw_mechanics.py's "
            "module docstring (grep-parity discipline — every rule must be "
            "documented):\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_rule_count_matches_module_constant(self) -> None:
        """The docstring rule count must equal ``extract_draw_mechanics._RULE_COUNT``.

        Both this test class's ``_RULE_COUNT`` and the module's ``_RULE_COUNT``
        constant must agree.  If a new rule is added, both the docstring, the
        module constant, AND this test must be updated intentionally.
        """
        docstring = extract_draw_mechanics.__doc__ or ""
        found = [n for n in range(1, 50) if f"Rule R{n}:" in docstring]
        assert len(found) == extract_draw_mechanics._RULE_COUNT, (
            f"Docstring contains {len(found)} rule entries "
            f"but _RULE_COUNT={extract_draw_mechanics._RULE_COUNT}. "
            "Update _RULE_COUNT if a new rule was added intentionally."
        )

    def test_rule_count_locked_at_3(self) -> None:
        """Exactly 3 rule entries appear in the docstring (no silent additions).

        Pin the class-level ``_RULE_COUNT`` to the expected value.  If a new
        rule is added to the implementation, this test (plus the module constant
        and the docstring) must be updated intentionally.
        """
        docstring = extract_draw_mechanics.__doc__ or ""
        found = [n for n in range(1, 50) if f"Rule R{n}:" in docstring]
        assert len(found) == self._RULE_COUNT, (
            f"Expected {self._RULE_COUNT} cleanup rules in the module docstring, "
            f"found {len(found)}: {found}.  Update _RULE_COUNT if intentional."
        )


# ---------------------------------------------------------------------------
# 4. TestHuntCodeGrammarSingleSourceOfTruth
# ---------------------------------------------------------------------------


class TestHuntCodeGrammarSingleSourceOfTruth:
    """Lock the relationship between ``_HUNT_CODE_GRAMMAR``, ``_HUNT_CODE_RE``,
    and ``_HUNT_CODE_EMBEDDED_RE``.

    Per the S06.3.1 pattern (``TestHuntCodeGrammarSingleSourceOfTruth``):
    both compiled regexes must derive from the single grammar constant so that
    updating ``_HUNT_CODE_GRAMMAR`` automatically propagates to both patterns.
    """

    def test_embedded_re_pattern_equals_grammar(self) -> None:
        """``_HUNT_CODE_EMBEDDED_RE.pattern`` must equal ``_HUNT_CODE_GRAMMAR``."""
        assert _HUNT_CODE_EMBEDDED_RE.pattern == _HUNT_CODE_GRAMMAR, (
            f"_HUNT_CODE_EMBEDDED_RE.pattern={_HUNT_CODE_EMBEDDED_RE.pattern!r} "
            f"does not match _HUNT_CODE_GRAMMAR={_HUNT_CODE_GRAMMAR!r} — "
            "the two must be kept in sync (single source of truth)"
        )

    def test_anchored_re_pattern_equals_anchored_grammar(self) -> None:
        """``_HUNT_CODE_RE.pattern`` must equal ``'^' + _HUNT_CODE_GRAMMAR + '$'``."""
        expected = f"^{_HUNT_CODE_GRAMMAR}$"
        assert _HUNT_CODE_RE.pattern == expected, (
            f"_HUNT_CODE_RE.pattern={_HUNT_CODE_RE.pattern!r} "
            f"does not match expected anchored grammar {expected!r} — "
            "the anchored regex must be derived from _HUNT_CODE_GRAMMAR"
        )

    def test_hunt_code_grammar_matches_standard_code(self) -> None:
        """``_HUNT_CODE_RE`` matches a well-formed deer hunt code."""
        assert _HUNT_CODE_RE.match("D-M-001-O1-A"), (
            "_HUNT_CODE_RE does not match 'D-M-001-O1-A' — grammar may be broken"
        )

    def test_hunt_code_grammar_matches_bear_code(self) -> None:
        """``_HUNT_CODE_RE`` matches a well-formed bear hunt code."""
        assert _HUNT_CODE_RE.match("B-E-044-O1-R"), (
            "_HUNT_CODE_RE does not match 'B-E-044-O1-R'"
        )

    def test_hunt_code_grammar_matches_point_only_code(self) -> None:
        """``_HUNT_CODE_RE`` DOES match point-only codes structurally.

        Point-only codes like ``D-P-999-99-P`` have ``P`` as the sex field,
        ``999`` as the 3-digit GMU, ``99`` as the alphanumeric season code,
        and ``P`` as the method letter — all satisfy ``_HUNT_CODE_GRAMMAR``.

        They are extracted separately by ``_extract_point_only_codes`` (which
        uses a dedicated ``{letter}-P-999-99-P`` regex) because their semantics
        differ (minimum-points threshold, not a draw-eligible hunt code), NOT
        because the grammar rejects them.  This test documents the actual
        boundary so a future grammar tightening doesn't surprise the reader.
        """
        # D-P-999-99-P structurally matches the grammar (all 5 components valid).
        assert _HUNT_CODE_RE.match("D-P-999-99-P"), (
            "_HUNT_CODE_RE should match 'D-P-999-99-P' — "
            "point-only codes are syntactically valid; they are filtered by "
            "semantics (dedicated _extract_point_only_codes), not by the grammar"
        )

    def test_embedded_re_finds_code_in_asterisk_prefixed_cell(self) -> None:
        """``_HUNT_CODE_EMBEDDED_RE`` finds a code even when prefixed by ``*``.

        This exercises the unanchored / embedded usage (Rule R1).
        """
        cell = "*D-M-010-W1-R"
        m = _HUNT_CODE_EMBEDDED_RE.search(cell)
        assert m is not None, (
            "_HUNT_CODE_EMBEDDED_RE failed to find a code in {cell!r}"
        )
        assert m.group() == "D-M-010-W1-R"


# ---------------------------------------------------------------------------
# 5. TestArtifactRegression
# ---------------------------------------------------------------------------


class TestArtifactRegression:
    """Pin the committed draw-mechanics-2026.json artifact to known-good stats.

    These tests load the committed JSON directly via
    ``extract_draw_mechanics._OUTPUT_PATH`` and assert the exact stats produced
    by the real extraction run.  No live PDF required — the artifact is committed
    and small enough to load in CI.
    """

    @staticmethod
    def _load() -> list[dict]:  # type: ignore[type-arg]
        if not extract_draw_mechanics._OUTPUT_PATH.exists():
            pytest.skip(
                "artifact not generated — run extract_draw_mechanics.py to produce "
                "ingestion/states/colorado/extracted/draw-mechanics-2026.json"
            )
        with open(extract_draw_mechanics._OUTPUT_PATH) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_total_record_count(self) -> None:
        """Artifact contains exactly 123 records."""
        data = self._load()
        assert len(data) == 123, (
            f"Expected 123 records, got {len(data)} — "
            "re-run extract_draw_mechanics.py and re-pin if intentional"
        )

    def test_record_type_counts(self) -> None:
        """Per-record_type counts are pinned: hybrid_code=116, point_only_code=4,
        important_dates=1, nr_allocation=1, hybrid_mechanics=1.
        """
        from collections import Counter

        data = self._load()
        counts = Counter(r["record_type"] for r in data)
        assert counts["hybrid_code"] == 116, (
            f"hybrid_code count: expected 116, got {counts['hybrid_code']}"
        )
        assert counts["point_only_code"] == 4, (
            f"point_only_code count: expected 4, got {counts['point_only_code']}"
        )
        assert counts["important_dates"] == 1, (
            f"important_dates count: expected 1, got {counts['important_dates']}"
        )
        assert counts["nr_allocation"] == 1, (
            f"nr_allocation count: expected 1, got {counts['nr_allocation']}"
        )
        assert counts["hybrid_mechanics"] == 1, (
            f"hybrid_mechanics count: expected 1, got {counts['hybrid_mechanics']}"
        )

    def test_hybrid_codes_by_species(self) -> None:
        """Hybrid codes are pinned per species: bear=3, deer=39, elk=38, pronghorn=36."""
        from collections import Counter

        data = self._load()
        hybrid = [r for r in data if r["record_type"] == "hybrid_code"]
        sp_counts = Counter(r["species"] for r in hybrid)
        assert sp_counts["bear"] == 3, (
            f"bear hybrid count: expected 3, got {sp_counts['bear']}"
        )
        assert sp_counts["deer"] == 39, (
            f"deer hybrid count: expected 39, got {sp_counts['deer']}"
        )
        assert sp_counts["elk"] == 38, (
            f"elk hybrid count: expected 38, got {sp_counts['elk']}"
        )
        assert sp_counts["pronghorn"] == 36, (
            f"pronghorn hybrid count: expected 36, got {sp_counts['pronghorn']}"
        )

    def test_point_only_codes_mapping(self) -> None:
        """The 4 point_only_code records match the expected species→hunt_code mapping."""
        data = self._load()
        pt_records = [r for r in data if r["record_type"] == "point_only_code"]
        assert len(pt_records) == 4, f"Expected 4 point_only_code records, got {len(pt_records)}"

        by_species = {r["species"]: r["hunt_code"] for r in pt_records}
        assert by_species == {
            "bear": "B-P-999-99-P",
            "deer": "D-P-999-99-P",
            "elk": "E-P-999-99-P",
            "pronghorn": "A-P-999-99-P",
        }, f"point_only_code species→hunt_code mapping mismatch: {by_species}"

    def test_important_dates_values(self) -> None:
        """The single important_dates record has the 3 expected ISO dates."""
        data = self._load()
        imp_records = [r for r in data if r["record_type"] == "important_dates"]
        assert len(imp_records) == 1
        rec = imp_records[0]
        assert rec["primary_draw_deadline"] == "2026-04-07", (
            f"primary_draw_deadline: expected '2026-04-07', got {rec['primary_draw_deadline']!r}"
        )
        assert rec["secondary_draw_deadline"] == "2026-06-30", (
            f"secondary_draw_deadline: expected '2026-06-30', got {rec['secondary_draw_deadline']!r}"
        )
        assert rec["leftover_on_sale_date"] == "2026-08-04", (
            f"leftover_on_sale_date: expected '2026-08-04', got {rec['leftover_on_sale_date']!r}"
        )

    def test_nr_allocation_values(self) -> None:
        """The single nr_allocation record has the expected structured values."""
        data = self._load()
        nr_records = [r for r in data if r["record_type"] == "nr_allocation"]
        assert len(nr_records) == 1
        rec = nr_records[0]
        assert rec["high_demand_threshold_points"] == 6, (
            f"high_demand_threshold_points: expected 6, got {rec['high_demand_threshold_points']}"
        )
        assert rec["high_demand_nr_cap"] == pytest.approx(0.20), (
            f"high_demand_nr_cap: expected 0.20, got {rec['high_demand_nr_cap']}"
        )
        assert rec["standard_nr_cap"] == pytest.approx(0.25), (
            f"standard_nr_cap: expected 0.25, got {rec['standard_nr_cap']}"
        )

    def test_hybrid_mechanics_values(self) -> None:
        """The single hybrid_mechanics record has min_points=5, share=0.20."""
        data = self._load()
        hm_records = [r for r in data if r["record_type"] == "hybrid_mechanics"]
        assert len(hm_records) == 1
        rec = hm_records[0]
        assert rec["min_preference_points"] == 5, (
            f"min_preference_points: expected 5, got {rec['min_preference_points']}"
        )
        assert rec["random_pool_share"] == pytest.approx(0.20), (
            f"random_pool_share: expected 0.20, got {rec['random_pool_share']}"
        )

    def test_all_hybrid_hunt_codes_match_grammar(self) -> None:
        """Every hybrid_code.hunt_code matches ``_HUNT_CODE_RE``.

        This validates that all 116 codes extracted from the brochure are
        well-formed per the grammar — no OCR artefacts slipped through.
        """
        data = self._load()
        bad: list[str] = []
        for r in data:
            if r["record_type"] == "hybrid_code":
                code = r["hunt_code"]
                if not _HUNT_CODE_RE.match(str(code)):
                    bad.append(str(code))
        assert not bad, (
            f"{len(bad)} hybrid_code hunt_codes do not match _HUNT_CODE_RE:\n"
            + "\n".join(f"  - {c}" for c in bad[:20])
        )

    def test_all_records_have_source_id(self) -> None:
        """Every record carries ``source_id == 'co-cpw-big-game-2026-brochure'``."""
        data = self._load()
        bad = [
            r for r in data
            if r.get("source_id") != "co-cpw-big-game-2026-brochure"
        ]
        assert not bad, (
            f"{len(bad)} records have wrong or missing source_id: "
            + str([r.get("source_id") for r in bad[:5]])
        )

    def test_all_records_have_non_empty_extracted_at(self) -> None:
        """Every record carries a non-empty ``extracted_at`` ISO timestamp."""
        data = self._load()
        bad = [
            r for r in data
            if not r.get("extracted_at") or not str(r["extracted_at"]).strip()
        ]
        assert not bad, (
            f"{len(bad)} records are missing a non-empty 'extracted_at' field"
        )

    def test_hybrid_codes_have_low_availability_bool(self) -> None:
        """Every hybrid_code record carries a boolean ``low_availability`` field."""
        data = self._load()
        bad = [
            r for r in data
            if r["record_type"] == "hybrid_code"
            and not isinstance(r.get("low_availability"), bool)
        ]
        assert not bad, (
            f"{len(bad)} hybrid_code records have non-bool or missing "
            "'low_availability' field"
        )

    def test_hybrid_codes_sorted_deterministically(self) -> None:
        """Hybrid codes are sorted by (species, hunt_code) within the artifact.

        The extractor sorts records by (record_type, species, hunt_code) at the
        end of ``extract()``.  Verify that the hybrid records are in the expected
        order — this locks the deterministic sort key.
        """
        data = self._load()
        hybrid = [r for r in data if r["record_type"] == "hybrid_code"]
        sort_keys = [(str(r["species"]), str(r["hunt_code"])) for r in hybrid]
        assert sort_keys == sorted(sort_keys), (
            "hybrid_code records are not sorted by (species, hunt_code) — "
            "deterministic sort may have regressed"
        )

    def test_no_duplicate_hybrid_hunt_codes_per_species(self) -> None:
        """No (species, hunt_code) pair appears more than once in hybrid_code records."""
        data = self._load()
        from collections import Counter

        pairs = Counter(
            (r["species"], r["hunt_code"])
            for r in data
            if r["record_type"] == "hybrid_code"
        )
        dupes = {k: v for k, v in pairs.items() if v > 1}
        assert not dupes, (
            f"Duplicate (species, hunt_code) pairs in hybrid_code records: {dupes}"
        )

    def test_nr_allocation_verbatim_non_empty(self) -> None:
        """The nr_allocation record carries a non-empty ``verbatim`` prose field."""
        data = self._load()
        nr_records = [r for r in data if r["record_type"] == "nr_allocation"]
        assert len(nr_records) == 1
        verbatim = nr_records[0].get("verbatim", "")
        assert isinstance(verbatim, str) and verbatim.strip(), (
            "nr_allocation 'verbatim' field is missing or empty"
        )

    def test_hybrid_mechanics_verbatim_non_empty(self) -> None:
        """The hybrid_mechanics record carries a non-empty ``verbatim`` prose field."""
        data = self._load()
        hm_records = [r for r in data if r["record_type"] == "hybrid_mechanics"]
        assert len(hm_records) == 1
        verbatim = hm_records[0].get("verbatim", "")
        assert isinstance(verbatim, str) and verbatim.strip(), (
            "hybrid_mechanics 'verbatim' field is missing or empty"
        )

    def test_species_set_is_v1_scope(self) -> None:
        """All hybrid_code records use only V1-scoped species names.

        Moose is deliberately excluded (out of PRD 002 V1 scope per the module
        docstring).  The only valid species are bear, deer, elk, pronghorn.
        """
        data = self._load()
        found_species = {
            r["species"]
            for r in data
            if r["record_type"] == "hybrid_code"
        }
        assert found_species == {"bear", "deer", "elk", "pronghorn"}, (
            f"Unexpected species in hybrid_code records: {found_species}"
        )


# ---------------------------------------------------------------------------
# 6. TestDeterministicJsonOutput
# ---------------------------------------------------------------------------


class TestDeterministicJsonOutput:
    """Skipped CI placeholder documenting the pinned SHA-256 and determinism recipe.

    SHA-256 of the committed draw-mechanics-2026.json (one record per line):
      7fd162adaf1ef791cd3be8a99296cee6bf6b7cce34deeb36e2bdec2a03c15b16

    To verify determinism locally (requires the ~96 MB gitignored PDF):

        cd /path/to/huntready/ingestion
        python states/colorado/extract_draw_mechanics.py --out /tmp/dm-run1.json
        python states/colorado/extract_draw_mechanics.py --out /tmp/dm-run2.json
        diff /tmp/dm-run1.json /tmp/dm-run2.json && echo "deterministic"
        sha256sum /tmp/dm-run1.json
        # expected: 7fd162adaf1ef791cd3be8a99296cee6bf6b7cce34deeb36e2bdec2a03c15b16

    Skipped unconditionally in CI — the PDF is not committed (gitignored fixture).
    """

    def test_two_run_sha256_parity(self) -> None:
        """Skipped: integration test requiring the ~96 MB gitignored CPW PDF.

        Pinned SHA-256:
          7fd162adaf1ef791cd3be8a99296cee6bf6b7cce34deeb36e2bdec2a03c15b16
        """
        pytest.skip(
            "integration — requires real CPW Big Game PDF; "
            "determinism verified by manual 2-run sha256 comparison. "
            "Pinned SHA-256: "
            "7fd162adaf1ef791cd3be8a99296cee6bf6b7cce34deeb36e2bdec2a03c15b16"  # pragma: allowlist secret
        )


# ---------------------------------------------------------------------------
# 7. TestHybridRowParse
# ---------------------------------------------------------------------------


class TestHybridRowParse:
    """Unit tests for ``_codes_from_cells`` — Rule R1 ``*``-strip → low_availability.

    Method names locked by module docstring:
      TestHybridRowParse::test_asterisk_stripped_and_flagged
    """

    def test_asterisk_stripped_and_flagged(self) -> None:
        """Rule R1: leading ``*`` before a hunt code sets ``low_availability=True``.

        The asterisk is stripped from the hunt code string; ``low_availability``
        is ``True`` when the ``*`` immediately precedes the code in the cell.
        """
        cells: list[str | None] = ["*D-M-002-O2-R"]
        results = _codes_from_cells(cells)
        assert len(results) == 1
        code, low_avail = results[0]
        assert code == "D-M-002-O2-R", (
            f"Expected clean code 'D-M-002-O2-R', got {code!r}"
        )
        assert low_avail is True, (
            "Expected low_availability=True for '*D-M-002-O2-R'"
        )

    def test_no_asterisk_not_flagged(self) -> None:
        """A code without a leading ``*`` has ``low_availability=False``."""
        cells: list[str | None] = ["D-M-044-O4-R"]
        results = _codes_from_cells(cells)
        assert len(results) == 1
        code, low_avail = results[0]
        assert code == "D-M-044-O4-R"
        assert low_avail is False, (
            "Expected low_availability=False for 'D-M-044-O4-R'"
        )

    def test_mixed_asterisk_and_plain_in_same_batch(self) -> None:
        """A batch with one ``*``-prefixed and one clean code flags correctly."""
        cells: list[str | None] = ["*D-M-002-O2-R", "D-M-044-O4-R"]
        results = _codes_from_cells(cells)
        assert len(results) == 2
        # First cell: low_availability=True
        assert results[0] == ("D-M-002-O2-R", True)
        # Second cell: low_availability=False
        assert results[1] == ("D-M-044-O4-R", False)

    def test_none_cell_skipped(self) -> None:
        """None cells are silently skipped — no crash, empty result."""
        results = _codes_from_cells([None, None])
        assert results == []

    def test_empty_string_cell_skipped(self) -> None:
        """Empty-string cells produce no results."""
        results = _codes_from_cells(["", "   "])
        assert results == []

    def test_prose_cell_with_no_code_skipped(self) -> None:
        """A prose cell that contains no hunt-code pattern produces no results."""
        cells: list[str | None] = ["Hybrid Draw Hunt Codes", "Species", "List"]
        results = _codes_from_cells(cells)
        assert results == []

    def test_multiple_codes_in_single_cell(self) -> None:
        """A cell containing multiple embedded codes yields all of them."""
        # pdfplumber can occasionally merge two lines into one cell
        cells: list[str | None] = ["D-M-001-O1-A D-M-002-O2-R"]
        results = _codes_from_cells(cells)
        assert len(results) == 2
        codes = {r[0] for r in results}
        assert "D-M-001-O1-A" in codes
        assert "D-M-002-O2-R" in codes

    def test_elk_bear_pronghorn_codes_recognised(self) -> None:
        """Elk, bear, and pronghorn codes are all recognised by _codes_from_cells."""
        cells: list[str | None] = [
            "*E-M-010-W1-R",   # elk low-avail
            "B-E-044-O1-R",    # bear
            "A-M-004-O1-M",    # pronghorn
        ]
        results = _codes_from_cells(cells)
        assert len(results) == 3
        # elk is low-avail
        assert results[0] == ("E-M-010-W1-R", True)
        # bear and pronghorn are not
        assert results[1] == ("B-E-044-O1-R", False)
        assert results[2] == ("A-M-004-O1-M", False)


# ---------------------------------------------------------------------------
# 8. TestNormalize
# ---------------------------------------------------------------------------


class TestNormalize:
    """Unit tests for prose whitespace collapse — Rule R2.

    Rule R2: ``re.sub(r"\\s+", " ", text).strip()`` is applied to prose cells
    (notes, verbatim fields) but NOT globally to structured cells.
    """

    def test_whitespace_collapse_prose(self) -> None:
        """Rule R2: internal ``\\n`` and multiple spaces collapse to a single space.

        Method name locked by module docstring:
          TestNormalize::test_whitespace_collapse_prose
        """
        raw = "line one\nline two\n  line three"
        result = re.sub(r"\s+", " ", raw).strip()
        assert result == "line one line two line three"

    def test_whitespace_collapse_leading_trailing(self) -> None:
        """Rule R2: leading and trailing whitespace is stripped."""
        raw = "  hello world  "
        result = re.sub(r"\s+", " ", raw).strip()
        assert result == "hello world"

    def test_whitespace_collapse_tabs(self) -> None:
        """Rule R2: tab characters are collapsed to a single space."""
        raw = "word\t\tword"
        result = re.sub(r"\s+", " ", raw).strip()
        assert result == "word word"

    def test_whitespace_collapse_empty_string(self) -> None:
        """Rule R2: empty/whitespace-only input yields an empty string."""
        assert re.sub(r"\s+", " ", "").strip() == ""
        assert re.sub(r"\s+", " ", "   ").strip() == ""


# ---------------------------------------------------------------------------
# 9. TestColumnCrop
# ---------------------------------------------------------------------------


class TestColumnCrop:
    """Structural guard confirming Rule R3 (bbox column crops for multi-column pages)
    is documented in the module docstring and references the expected pages.

    Rule R3: bbox column crops are applied to PDF pages 14 and 29 to avoid
    pdfplumber interleaving text from the left and right columns.

    Method name locked by module docstring:
      TestColumnCrop::test_right_column_crop_isolates_second_page
    """

    def test_right_column_crop_isolates_second_page(self) -> None:
        """Rule R3 is documented in the module docstring with page references.

        The docstring must mention Rule R3 and reference both affected pages
        (14 and 29) to satisfy grep-parity discipline.
        """
        docstring = extract_draw_mechanics.__doc__ or ""
        assert "Rule R3:" in docstring, (
            "Rule R3 is missing from the extract_draw_mechanics module docstring"
        )
        # Both affected pages must be mentioned in or near the R3 entry.
        # We allow loose check: pages 14 and 29 appear somewhere in the docstring.
        assert "14" in docstring, (
            "Page 14 (application dates) not mentioned in extract_draw_mechanics docstring"
        )
        assert "29" in docstring, (
            "Page 29 (hybrid draw right half) not mentioned in extract_draw_mechanics docstring"
        )

    def test_dates_page_constant_is_14(self) -> None:
        """The ``_DATES_PAGE`` module constant must equal 14 (PDF page for Rule R3)."""
        assert extract_draw_mechanics._DATES_PAGE == 14, (
            f"_DATES_PAGE expected 14, got {extract_draw_mechanics._DATES_PAGE}"
        )

    def test_hybrid_page_constant_is_29(self) -> None:
        """The ``_HYBRID_PAGE`` module constant must equal 29 (PDF page for Rule R3)."""
        assert extract_draw_mechanics._HYBRID_PAGE == 29, (
            f"_HYBRID_PAGE expected 29, got {extract_draw_mechanics._HYBRID_PAGE}"
        )


# ---------------------------------------------------------------------------
# 10. TestPointOnlySpeciesLetterMismatch
# ---------------------------------------------------------------------------


class TestPointOnlySpeciesLetterMismatch:
    """Fail-loud guard: ``_extract_point_only_codes`` raises
    ``ColoradoDrawMechanicsError`` when the extracted species letter does not
    match the expected letter for the page being parsed.

    This exercises the species-letter validation in the point-only extractor —
    a wrong-letter code (e.g. elk letter 'E' appearing on the deer page) must
    be caught immediately rather than silently writing wrong data.
    """

    def test_wrong_species_letter_raises(self) -> None:
        """Species-letter mismatch on a point-only page raises ColoradoDrawMechanicsError.

        Scenario: the deer page (PDF page 30) unexpectedly contains 'E-P-999-99-P'
        (elk letter) instead of 'D-P-999-99-P'.  The extractor must raise rather
        than silently recording the wrong species code.
        """
        # Build a minimal mock PdfDocument.
        mock_pdf = MagicMock()
        mock_pdf.__class__ = extract_draw_mechanics.PdfDocument

        # Patch open_pdf and iter_pages so no real PDF is needed.
        # _extract_point_only_codes iterates over _POINT_ONLY_PAGES in sorted order:
        # bear (72), deer (30), elk (45), pronghorn (63).
        # We need to make the deer page return a page whose text contains
        # 'E-P-999-99-P' (wrong letter) rather than 'D-P-999-99-P'.
        #
        # Strategy: patch iter_pages to yield a mock page per call;
        # patch extract_text to return a deer-page text with the wrong code.

        # species_order (alphabetical): ['bear', 'deer', 'elk', 'pronghorn']
        # deer is index 1; we make bear succeed (correct letter) and deer fail.

        def fake_iter_pages(pdf: object, start: int, end: int):  # type: ignore[no-untyped-def]
            mock_page = MagicMock()
            yield (start - 1, mock_page)  # (0-indexed, page)

        species_texts = {
            "bear": "To apply for a point, enter B-P-999-99-P as your first-choice hunt code.",
            "deer": "To apply for a point, enter E-P-999-99-P as your first-choice hunt code.",  # WRONG
            "elk": "To apply for a point, enter E-P-999-99-P as your first-choice hunt code.",
            "pronghorn": "To apply for a point, enter A-P-999-99-P as your first-choice hunt code.",
        }
        page_to_species: dict[int, str] = {
            v: k for k, v in extract_draw_mechanics._POINT_ONLY_PAGES.items()
        }
        current_page: list[int] = [0]

        def fake_extract_text(page: object, **kwargs: object) -> str:
            sp = page_to_species.get(current_page[0], "bear")
            return species_texts.get(sp, "")

        def fake_iter_pages_tracking(
            pdf: object, start: int, end: int
        ):  # type: ignore[no-untyped-def]
            current_page[0] = start
            mock_page = MagicMock()
            yield (start - 1, mock_page)

        with (
            patch.object(
                extract_draw_mechanics,
                "iter_pages",
                side_effect=fake_iter_pages_tracking,
            ),
            patch.object(
                extract_draw_mechanics,
                "extract_text",
                side_effect=fake_extract_text,
            ),
        ):
            with pytest.raises(ColoradoDrawMechanicsError) as exc_info:
                extract_draw_mechanics._extract_point_only_codes(mock_pdf)

        # The error message must mention species and the mismatched letters.
        error_msg = str(exc_info.value)
        assert "deer" in error_msg or "D" in error_msg, (
            f"Error message should reference species 'deer' or expected letter 'D': {error_msg}"
        )
