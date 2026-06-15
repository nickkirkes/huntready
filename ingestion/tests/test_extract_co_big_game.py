"""Unit tests for `states.colorado.extract_big_game` — CPW Big Game brochure
extraction structural guards (S06.3 T9).

This file contains ONLY the mandatory structural guard tests:
  1. AST-level foreign-state-import guard (ADR-005 adapter isolation).
  2. No-DB-import guard (single-writer contract — S06.3 produces JSON only).
  3. No-``layout=True`` regression guard (ADR-008 verbatim discipline).
  4. Cleanup-rules docstring parity — every rule R1–R15 must appear in the
     module docstring's "Cleanup rules" section.

Tests T10 and T11 (functional unit tests) will be appended to this file by
subsequent tasks.

Test philosophy:
- All tests are hermetic: no real PDF required, no network, no live parsing.
- Source-level / AST scans only — static analysis of the module file.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import states.colorado.extract_big_game as extract_big_game
from states.colorado.extract_big_game import _split_valid_gmus

# ---------------------------------------------------------------------------
# Re-use the AST-walk helper from test_extract_dea (state-agnostic by design).
# ---------------------------------------------------------------------------
from tests.test_extract_dea import _find_foreign_state_imports  # noqa: E402


# ---------------------------------------------------------------------------
# 1. TestNoForeignStateAdapterImports
# ---------------------------------------------------------------------------


class TestNoForeignStateAdapterImports:
    """AST-walk guard: extract_big_game.py must not import from other states'
    adapters, and must not import from ingestion.lib.db.

    Rules per ADR-005 (adapter isolation) and the single-writer contract
    (S06.3 emits JSON only; downstream loaders write to DB):
      - Colorado adapter may import from ``states.colorado.*`` or
        ``ingestion.lib.*``, but NEVER from ``states.<other_state>.*`` or
        ``ingestion.states.<other_state>.*``.
      - extract_big_game.py must NOT import from ``ingestion.lib.db``
        (no database writes in S06.3).
    """

    _ALLOWED_STATE: str = "colorado"

    def test_no_foreign_state_imports(self) -> None:
        """extract_big_game.py itself is clean of foreign state imports."""
        source_path = Path(extract_big_game.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        violations = _find_foreign_state_imports(source, self._ALLOWED_STATE)
        assert not violations, (
            "extract_big_game.py contains foreign state adapter imports:\n"
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

    def test_no_db_imports(self) -> None:
        """extract_big_game.py has no ingestion.lib.db imports.

        Single-writer contract: S06.3 produces JSON only. No database writes.
        Downstream loaders (S06.6–S06.9) read the artifact and write to DB.
        DB imports in S06.3 would violate this isolation.
        """
        source_path = Path(extract_big_game.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        assert "from ingestion.lib.db" not in source, (
            "extract_big_game.py imports from ingestion.lib.db — "
            "violates S06.3 single-writer contract"
        )
        assert "import ingestion.lib.db" not in source, (
            "extract_big_game.py imports ingestion.lib.db — "
            "violates S06.3 single-writer contract"
        )


# ---------------------------------------------------------------------------
# 2. TestNoLayoutTrue
# ---------------------------------------------------------------------------


class TestNoLayoutTrue:
    """Source-text guard: extract_big_game.py must never call pdfplumber's
    extract_text with ``layout=True``.

    Passing ``layout=True`` injects synthetic spaces and violates the
    no-additional-normalization posture (ADR-008 verbatim discipline).
    This guard scans the module source text for the literal string
    ``layout=True`` and fails if it appears.
    """

    def test_no_layout_true_regression_guard(self) -> None:
        """The literal ``layout=True`` must not appear in extract_big_game.py."""
        source_path = Path(extract_big_game.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        assert "layout=True" not in source, (
            "extract_big_game.py contains 'layout=True' — passing layout=True "
            "to pdfplumber's extract_text injects synthetic spaces and violates "
            "ADR-008 verbatim discipline."
        )


# ---------------------------------------------------------------------------
# 3. TestCleanupRulesDocstringParity
# ---------------------------------------------------------------------------


class TestCleanupRulesDocstringParity:
    """Docstring parity guard: the module docstring must document every cleanup
    rule R1 through R15.

    Per the S03.3 AC #547 analog (grep-parity discipline): every cleanup rule
    applied to row cells must appear in the module docstring's "Cleanup rules"
    section.  This prevents silent divergence where a rule is implemented but
    not documented (or vice versa).

    The exact format used in the module docstring is ``Rule RN:``
    (e.g., ``Rule R1:``, ``Rule R14:``).
    """

    _RULE_COUNT: int = 15

    def test_every_rule_has_a_docstring_entry(self) -> None:
        """Rule R1 through R15 must each appear in the module docstring."""
        docstring = extract_big_game.__doc__ or ""
        assert docstring, "extract_big_game module has no docstring"

        missing: list[str] = []
        for n in range(1, self._RULE_COUNT + 1):
            marker = f"Rule R{n}:"
            if marker not in docstring:
                missing.append(marker)

        assert not missing, (
            "The following cleanup rules are missing from extract_big_game.py's "
            "module docstring (grep-parity discipline — every rule must be "
            "documented):\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_rule_count_locked(self) -> None:
        """Exactly 15 rule entries appear in the docstring (no silent additions).

        If a new rule is added to the implementation, both the docstring AND
        this test's ``_RULE_COUNT`` must be updated intentionally.
        """
        docstring = extract_big_game.__doc__ or ""
        found = [n for n in range(1, 50) if f"Rule R{n}:" in docstring]
        assert len(found) == self._RULE_COUNT, (
            f"Expected {self._RULE_COUNT} cleanup rules in the module docstring, "
            f"found {len(found)}: {found}.  Update _RULE_COUNT if intentional."
        )

    def test_locked_by_citations_exist(self) -> None:
        """Every 'locked by: ClassName::method' citation in the module docstring
        must refer to a class and method that actually exist in this test module.

        Systemic fix for the project's 'grep-verify spec-named locations' pitfall:
        phantom citations in the docstring are caught immediately rather than
        silently lying about test coverage.
        """
        docstring = extract_big_game.__doc__ or ""
        # Match all "locked by: ClassName::method_name" references (may be
        # comma-separated on the same line or across continuations).
        citation_re = re.compile(r"([A-Z][A-Za-z0-9_]+)::([a-z][A-Za-z0-9_]+)")
        citations = citation_re.findall(docstring)
        assert citations, "No 'ClassName::method' citations found in docstring — check the regex"

        # Build the set of (class_name, method_name) pairs available in this
        # test module.
        this_module = sys.modules[__name__]
        missing: list[str] = []
        for cls_name, method_name in citations:
            cls = getattr(this_module, cls_name, None)
            if cls is None:
                missing.append(f"{cls_name}::{method_name}  (class not found)")
                continue
            if not (inspect.isclass(cls) and hasattr(cls, method_name)):
                missing.append(f"{cls_name}::{method_name}  (method not found on class)")

        assert not missing, (
            "The following 'locked by' citations in extract_big_game.py's module "
            "docstring point to non-existent test classes or methods:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


# ---------------------------------------------------------------------------
# T10: Unit tests for pure helpers (appended by task T10)
# ---------------------------------------------------------------------------

from states.colorado.extract_big_game import (  # noqa: E402
    CpwRowExtraction,
    CpwSeasonWindow,
    _assign_row_confidence,
    _collapse_whitespace,
    _is_footnote_row,
    _is_garbage_row,
    _is_map_page_text,
    _is_see_unit_row,
    _looks_doubled_row,
    _method_group_for,
    _normalize_cell,
    _parse_header_date,
    _parse_hunt_code,
    _parse_season_window,
    _rejoin_hyphenated_linebreaks,
    _residency_scope_from_text,
    _species_group_for,
    _undouble_text,
    _weapon_types_for,
)
from ingestion.lib.pdf import ConfidenceTier, PageReference, PdfExtractionError  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: build a minimal PageReference for tests that need one.
# ---------------------------------------------------------------------------


def _make_page_ref(page: int = 30) -> PageReference:
    return PageReference(
        pdf_filename="co-cpw-big-game-2026-brochure-2026-03-04.pdf",
        page_num_1based=page,
        bbox=None,
        extracted_at="2026-06-09T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Helper: build a minimal CpwRowExtraction for confidence tests.
# ---------------------------------------------------------------------------


def _make_row(
    hunt_code: str = "D-M-001-O1-A",
    species_letter: str = "D",
    list_value: str | None = "A",
    season_windows: list[CpwSeasonWindow] | None = None,
) -> CpwRowExtraction:
    if season_windows is None:
        season_windows = [
            CpwSeasonWindow(
                start_date="Sept. 2",
                end_date="Sept. 30",
                raw_text="Sept. 2–30",
            )
        ]
    return CpwRowExtraction(
        hunt_code=hunt_code,
        species_letter=species_letter,
        sex_code="M",
        gmu_code="001",
        season_code="O1",
        method_letter="A",
        unit="1",
        valid_gmus="1",
        season_windows=season_windows,
        list_value=list_value,
        apply_by=None,
        quota=None,
        quota_range=None,
        weapon_types=["archery"],
        method_group="archery",
        residency_scope="both",
        extras=None,
        extraction_confidence="",
        page_reference=_make_page_ref(),
    )


# ---------------------------------------------------------------------------
# 4. TestSectionAttribution  (F1a — locks Rule R12 residency_scope)
# ---------------------------------------------------------------------------


class TestSectionAttribution:
    """Unit tests for ``_residency_scope_from_text`` — Rule R12.

    Method name locked by module docstring:
      TestSectionAttribution::test_residency_scope
    """

    def test_residency_scope(self) -> None:
        """Rule R12: residency_scope derived from page/section heading text.

        Four cases:
          - Nonresident-only heading       → 'nonresident'
          - Resident-only heading          → 'resident'
          - Combined resident+nonresident  → 'both'
          - Neutral / no residency word    → 'both' (default)
        """
        # Nonresident-only
        assert (
            _residency_scope_from_text("Rifle — Limited Nonresident Licenses")
            == "nonresident"
        )
        # Resident-only
        assert (
            _residency_scope_from_text("Rifle — Limited Resident Licenses")
            == "resident"
        )
        # Both present — combined heading
        assert (
            _residency_scope_from_text(
                "Archery — Limited Resident & Nonresident Licenses"
            )
            == "both"
        )
        # Neither — neutral default
        assert (
            _residency_scope_from_text("Muzzleloader — Limited Licenses")
            == "both"
        )


# ---------------------------------------------------------------------------
# 5. TestNormalizeCell
# ---------------------------------------------------------------------------


class TestNormalizeCell:
    """Unit tests for ``_normalize_cell`` — Rules R1/R2/R9/R13 (+R3 via helper)."""

    def test_dash_sentinel_nulled(self) -> None:
        """Rule R1: bare '-' → None."""
        assert _normalize_cell("-") is None

    def test_dash_with_whitespace_nulled(self) -> None:
        """Rule R1: '  -  ' (surrounded by whitespace) → None."""
        assert _normalize_cell("  -  ") is None

    def test_whitespace_nulled(self) -> None:
        """Rule R2: empty/whitespace-only → None."""
        assert _normalize_cell("") is None
        assert _normalize_cell("   ") is None
        assert _normalize_cell("\t\n") is None

    def test_none_input_nulled(self) -> None:
        """Rule R2: None input → None."""
        assert _normalize_cell(None) is None

    def test_strip(self) -> None:
        """Rule R13: leading/trailing whitespace stripped."""
        assert _normalize_cell("  hello  ") == "hello"

    def test_otc_preserved(self) -> None:
        """Rule R9: 'OTC' is a valid list value — not nulled by R1."""
        assert _normalize_cell("OTC") == "OTC"

    def test_hyphen_rejoin(self) -> None:
        """Rule R3: alphanumeric-neighboured hyphen-newline rejoined.

        'mule-\\ndeer' → 'mule-deer' (both neighbours are alphanumeric).
        """
        assert _normalize_cell("mule-\ndeer") == "mule-deer"

    def test_period_hyphen_not_rejoined(self) -> None:
        """Rule R3 narrow: 'Sept.-\\nOct.' is NOT rejoined (period fails lookbehind).

        The lookbehind is ``[a-zA-Z0-9]`` — a period is not alphanumeric, so
        the pattern does not fire.
        """
        result = _normalize_cell("Sept.-\nOct.")
        # The '-\n' is NOT replaced; stripping the leading/trailing whitespace
        # (R13) still fires, but the hyphen-linebreak stays.
        assert "-\n" in result  # type: ignore[operator]

    def test_whitespace_not_collapsed_globally(self) -> None:
        """Rule R4 does NOT apply to _normalize_cell — internal spaces preserved.

        'Sept. 2\\n  Oct. 3' should not be collapsed to 'Sept. 2 Oct. 3'
        by _normalize_cell (R4 is a separate function for extras only).
        """
        # Internal newlines in a value cell survive _normalize_cell unchanged
        # (unless they're part of a hyphen-linebreak that R3 catches).
        result = _normalize_cell("Sept. 2\nOct. 3")
        assert result == "Sept. 2\nOct. 3"

    def test_plain_text_preserved(self) -> None:
        """Ordinary cell text is returned unchanged (after strip)."""
        assert _normalize_cell("Limited") == "Limited"
        assert _normalize_cell("D-M-001-O1-A") == "D-M-001-O1-A"

    def test_strips_otc_bullet(self) -> None:
        """Rule R15: CPW ■ OTC-marker glyph is stripped from structured cells.

        Three cases:
          - '■1'    → '1'   (leading bullet before digit)
          - '3\\n■'  → '3'   (trailing bullet after value with newline)
          - '■'     → None  (bullet-only cell → absent per ADR-001)

        Locked by module docstring citation:
          TestNormalizeCell::test_strips_otc_bullet
        """
        assert _normalize_cell("■1") == "1"
        assert _normalize_cell("3\n■") == "3"
        assert _normalize_cell("■") is None


# ---------------------------------------------------------------------------
# 5. TestRejoinAndCollapse
# ---------------------------------------------------------------------------


class TestRejoinAndCollapse:
    """Unit tests for ``_rejoin_hyphenated_linebreaks`` and ``_collapse_whitespace``."""

    def test_rejoin_alphanumeric_neighbours(self) -> None:
        """Soft hyphen between alphanumeric chars: newline dropped, hyphen kept."""
        assert _rejoin_hyphenated_linebreaks("word-\nword") == "word-word"

    def test_rejoin_no_newline_unchanged(self) -> None:
        """'262-50' has no newline — unchanged."""
        assert _rejoin_hyphenated_linebreaks("262-50") == "262-50"

    def test_rejoin_period_before_hyphen_unchanged(self) -> None:
        """Period before hyphen: 'Sept.-\\nOct.' NOT rejoined (period not alphanumeric)."""
        assert _rejoin_hyphenated_linebreaks("Sept.-\nOct.") == "Sept.-\nOct."

    def test_collapse_whitespace_multi_space(self) -> None:
        """Multiple spaces collapsed to one."""
        assert _collapse_whitespace("a  b   c") == "a b c"

    def test_collapse_whitespace_newlines(self) -> None:
        """Newlines in notes/extras collapsed to a single space."""
        assert _collapse_whitespace("line one\nline two") == "line one line two"

    def test_collapse_whitespace_strip_ends(self) -> None:
        """Leading/trailing whitespace stripped."""
        assert _collapse_whitespace("  hello  ") == "hello"

    def test_collapse_whitespace_empty_string(self) -> None:
        """Empty string returns empty string (no crash)."""
        assert _collapse_whitespace("") == ""


# ---------------------------------------------------------------------------
# 6. TestRowFilters
# ---------------------------------------------------------------------------


class TestRowFilters:
    """Unit tests for ``_is_see_unit_row``, ``_is_footnote_row``, ``_is_map_page_text``."""

    # --- _is_see_unit_row ---

    def test_see_unit_skipped(self) -> None:
        """Rule R5: row containing 'See Unit 7' → True."""
        assert _is_see_unit_row(["8", "see unit 7", None, None, None, None]) is True

    def test_see_unit_case_insensitive(self) -> None:
        """Rule R5: 'SEE UNIT 123' (uppercase) → True."""
        assert _is_see_unit_row([None, "SEE UNIT 123"]) is True

    def test_see_unit_not_matched_partial(self) -> None:
        """A cell that merely mentions 'see unit' mid-sentence is not matched
        because the regex is anchored at the start."""
        # 'For details, see unit 5 regulations' — does NOT start with 'see unit'
        assert _is_see_unit_row(["For details, see unit 5 regulations"]) is False

    def test_normal_row_not_see_unit(self) -> None:
        """A normal data row returns False."""
        assert _is_see_unit_row(["1", "1", "Sept. 2–30", "M", "D-M-001-O1-A", "A"]) is False

    def test_all_none_row_not_see_unit(self) -> None:
        """Row of all None cells returns False."""
        assert _is_see_unit_row([None, None, None]) is False

    # --- _is_footnote_row ---

    def test_footnote_skipped(self) -> None:
        """Rule R6: first non-empty cell starts with ■ → True."""
        assert _is_footnote_row(["■Units 12, 13 are valid for add-on bear licenses"]) is True

    def test_footnote_with_leading_whitespace(self) -> None:
        """Rule R6: cell with leading whitespace before ■ is still caught."""
        assert _is_footnote_row(["  ■ Some footnote text"]) is True

    def test_non_footnote_row(self) -> None:
        """A normal data row does not start with ■ → False."""
        assert _is_footnote_row(["1", "1", "Sept. 2–30", "M", "D-M-001-O1-A", "A"]) is False

    def test_none_only_row_not_footnote(self) -> None:
        """Row of all None cells → False."""
        assert _is_footnote_row([None, None, None]) is False

    # --- _is_map_page_text ---

    def test_map_page_skipped(self) -> None:
        """Rule R10: zero tables + short text → True (map/photo page)."""
        assert _is_map_page_text("abc", table_count=0) is True

    def test_map_page_none_text_skipped(self) -> None:
        """Rule R10: zero tables + None text → True."""
        assert _is_map_page_text(None, table_count=0) is True

    def test_map_page_empty_text_skipped(self) -> None:
        """Rule R10: zero tables + empty/whitespace text → True."""
        assert _is_map_page_text("   ", table_count=0) is True

    def test_non_map_page_has_tables(self) -> None:
        """Rule R10: page with tables is NOT skipped regardless of text length."""
        assert _is_map_page_text("abc", table_count=1) is False

    def test_non_map_page_long_text(self) -> None:
        """Rule R10: zero tables but text ≥ 120 chars → NOT a map page."""
        long_text = "x" * 120
        assert _is_map_page_text(long_text, table_count=0) is False

    def test_map_page_threshold_boundary(self) -> None:
        """Rule R10: 119 chars → map page; 120 chars → not a map page."""
        assert _is_map_page_text("x" * 119, table_count=0) is True
        assert _is_map_page_text("x" * 120, table_count=0) is False

    def test_short_page_with_hunt_code_not_dropped(self) -> None:
        """Rule R10 safeguard: a short, no-table page that contains a hunt code
        is regulation content and must NOT be classified as a map page (guards
        against silently dropping a real page if pdfplumber misses its table).
        """
        assert _is_map_page_text("D-M-001-O1-A A", table_count=0) is False
        # Genuine map page (short, no table, no hunt code) is still skipped.
        assert _is_map_page_text("Colorado map legend", table_count=0) is True

    # --- _is_garbage_row ---

    def _make_garbage_row(
        self,
        hunt_code: str = "Tee",
        list_value: str | None = "rrms",
    ) -> CpwRowExtraction:
        """Build a minimal CpwRowExtraction that represents a garbage/OCR row."""
        return CpwRowExtraction(
            hunt_code=hunt_code,
            species_letter="",   # did not parse
            sex_code="",
            gmu_code="",
            season_code="",
            method_letter="",
            unit=None,
            valid_gmus=None,
            season_windows=[],
            list_value=list_value,
            apply_by=None,
            quota=None,
            quota_range=None,
            weapon_types=[],
            method_group="rifle",
            residency_scope="both",
            extras=None,
            extraction_confidence="low",
            page_reference=_make_page_ref(),
        )

    def test_garbage_row_detected(self) -> None:
        """FIX 2: a Tee/rrms-style map-OCR row is detected as garbage.

        Conditions: species_letter=="" AND no hunt-code fragment AND
        list_value not in {A, B, C, OTC}.
        """
        row = self._make_garbage_row(hunt_code="Tee", list_value="rrms")
        assert _is_garbage_row(row) is True

    def test_garbage_row_with_none_list_value(self) -> None:
        """FIX 2: garbage row with list_value=None is also detected."""
        row = self._make_garbage_row(hunt_code="£¤385\n93", list_value=None)
        assert _is_garbage_row(row) is True

    def test_multi_hunt_code_row_not_garbage(self) -> None:
        """FIX 2: a multi-hunt-code cell containing 'D-M-082' is NOT garbage.

        The hunt-code fragment pattern fires on 'D-M-082-O2-R\\nD-M-082-O3-R',
        so condition (b) fails and the row is preserved.
        """
        row = self._make_garbage_row(
            hunt_code="D-M-082-O2-R\nD-M-082-O3-R",
            list_value=None,
        )
        assert _is_garbage_row(row) is False

    def test_valid_parsed_row_not_garbage(self) -> None:
        """FIX 2: a row with a parsed hunt code (species_letter != '') is not garbage.

        Condition (a) fails immediately when species_letter is non-empty.
        """
        row = _make_row(hunt_code="D-M-001-O1-A", species_letter="D")
        assert _is_garbage_row(row) is False

    def test_garbage_row_with_valid_list_value_not_garbage(self) -> None:
        """FIX 2: a LOW row with species_letter='' but list_value='A' is NOT garbage.

        Condition (c) fails when list_value is a known draw-mechanic token —
        the row carries a salvageable value and should be preserved.
        """
        row = self._make_garbage_row(hunt_code="GARBLED", list_value="A")
        assert _is_garbage_row(row) is False


# ---------------------------------------------------------------------------
# 7. TestParseHuntCode
# ---------------------------------------------------------------------------


class TestParseHuntCode:
    """Unit tests for ``_parse_hunt_code`` — Rule R8."""

    def test_valid_code(self) -> None:
        """Standard deer code parses to all five components."""
        result = _parse_hunt_code("D-M-001-O1-A")
        assert result is not None
        assert result["species_letter"] == "D"
        assert result["sex_code"] == "M"
        assert result["gmu_code"] == "001"
        assert result["season_code"] == "O1"
        assert result["method_letter"] == "A"

    def test_elk_female_rifle_code(self) -> None:
        """Elk female rifle code parses correctly."""
        result = _parse_hunt_code("E-F-044-O1-R")
        assert result is not None
        assert result["species_letter"] == "E"
        assert result["sex_code"] == "F"
        assert result["gmu_code"] == "044"
        assert result["method_letter"] == "R"

    def test_pronghorn_code(self) -> None:
        """Pronghorn uses 'A' (Antelope) as species letter — not 'P'."""
        result = _parse_hunt_code("A-M-012-O1-M")
        assert result is not None
        assert result["species_letter"] == "A"
        assert result["gmu_code"] == "012"
        assert result["method_letter"] == "M"

    def test_four_digit_gmu_code(self) -> None:
        """Four-digit GMU codes (e.g. '0201') are valid per regex."""
        result = _parse_hunt_code("D-M-0201-O1-A")
        assert result is not None
        assert result["gmu_code"] == "0201"

    def test_malformed_code_returns_none(self) -> None:
        """Malformed codes return None — no raise, caller degrades confidence."""
        assert _parse_hunt_code("INVALID") is None
        assert _parse_hunt_code("D-M-01-O1-A") is None  # GMU too short (2 digits)
        assert _parse_hunt_code("") is None
        assert _parse_hunt_code("D-M-001-O1") is None  # missing method

    def test_species_group_whitetail(self) -> None:
        """Rule R11: 'D' + is_whitetail=True → 'whitetail'."""
        assert _species_group_for("D", is_whitetail=True) == "whitetail"

    def test_returns_dict_with_exactly_five_keys(self) -> None:
        """Parsed result has exactly the five expected keys."""
        result = _parse_hunt_code("D-M-001-O1-A")
        assert result is not None
        assert set(result.keys()) == {
            "species_letter",
            "sex_code",
            "gmu_code",
            "season_code",
            "method_letter",
        }


# ---------------------------------------------------------------------------
# 8. TestWeaponAndSpecies
# ---------------------------------------------------------------------------


class TestWeaponAndSpecies:
    """Unit tests for ``_method_group_for``, ``_weapon_types_for``, ``_species_group_for``."""

    # --- _method_group_for ---

    def test_method_group_archery(self) -> None:
        assert _method_group_for("A") == "archery"

    def test_method_group_muzzleloader(self) -> None:
        assert _method_group_for("M") == "muzzleloader"

    def test_method_group_rifle(self) -> None:
        assert _method_group_for("R") == "rifle"

    def test_method_group_season_choice(self) -> None:
        """CPW 'X' (Season Choice) → 'season_choice' (its own method group)."""
        assert _method_group_for("X") == "season_choice"

    def test_method_group_unknown_returns_none(self) -> None:
        """A genuinely unknown method letter returns None — does not raise."""
        assert _method_group_for("Z") is None
        assert _method_group_for("") is None

    # --- _weapon_types_for ---

    def test_weapon_types_archery(self) -> None:
        assert _weapon_types_for("A") == ["archery"]

    def test_weapon_types_muzzleloader(self) -> None:
        assert _weapon_types_for("M") == ["muzzleloader"]

    def test_weapon_types_rifle_maps_to_any_legal_weapon(self) -> None:
        """Rule: CPW 'R' (rifle) → ['any_legal_weapon'], not ['rifle']."""
        assert _weapon_types_for("R") == ["any_legal_weapon"]

    def test_weapon_types_season_choice(self) -> None:
        """CPW 'X' (Season Choice) → union of the three choosable methods."""
        assert _weapon_types_for("X") == [
            "archery",
            "muzzleloader",
            "any_legal_weapon",
        ]

    def test_weapon_types_unknown_returns_empty_list(self) -> None:
        """A genuinely unknown letter → [] (does not raise)."""
        assert _weapon_types_for("Z") == []
        assert _weapon_types_for("") == []

    # --- _species_group_for ---

    def test_species_group_D_mule_deer(self) -> None:
        assert _species_group_for("D") == "mule_deer"

    def test_species_group_D_whitetail_flag(self) -> None:
        """Rule R11: is_whitetail=True flips 'D' to 'whitetail'."""
        assert _species_group_for("D", is_whitetail=True) == "whitetail"

    def test_species_group_E_elk(self) -> None:
        assert _species_group_for("E") == "elk"

    def test_species_group_A_pronghorn(self) -> None:
        """CPW uses 'A' (Antelope) for pronghorn — not 'P'."""
        assert _species_group_for("A") == "pronghorn"

    def test_species_group_unexpected_letter_raises(self) -> None:
        """Any unrecognised species letter raises PdfExtractionError (ADR-001 fail-loud)."""
        import pytest

        with pytest.raises(PdfExtractionError):
            _species_group_for("P")

        with pytest.raises(PdfExtractionError):
            _species_group_for("B")

        with pytest.raises(PdfExtractionError):
            _species_group_for("X")


# ---------------------------------------------------------------------------
# 9. TestSeasonWindow
# ---------------------------------------------------------------------------


class TestSeasonWindow:
    """Unit tests for ``_parse_season_window``, ``_parse_header_date``, ``_parse_date_range``."""

    def test_same_month_range(self) -> None:
        """'Sept. 2–30' parses start='Sept. 2', end='Sept. 30'.

        Same-month ranges drop the month on the source end token ("30"); the
        parser inherits the start's month so end_date is unambiguous (P1-4).
        raw_text stays verbatim per ADR-008.
        """
        w = _parse_season_window("Sept. 2–30")
        assert w is not None
        assert w["start_date"] == "Sept. 2"
        assert w["end_date"] == "Sept. 30"
        assert w["raw_text"] == "Sept. 2–30"

    def test_cross_month_range(self) -> None:
        """'Oct. 24–Nov. 1' parses start and end with month tokens."""
        w = _parse_season_window("Oct. 24–Nov. 1")
        assert w is not None
        assert w["start_date"] == "Oct. 24"
        assert w["end_date"] == "Nov. 1"

    def test_cross_month_with_newline(self) -> None:
        """'Aug. 15–\\nJan. 15' — newline in cell handled."""
        w = _parse_season_window("Aug. 15–\nJan. 15")
        assert w is not None
        assert w["start_date"] == "Aug. 15"
        assert w["end_date"] == "Jan. 15"

    def test_newline_before_dash(self) -> None:
        """'Aug. 31\\n– Sept. 28' — newline before en-dash handled."""
        w = _parse_season_window("Aug. 31\n– Sept. 28")
        assert w is not None
        assert w["start_date"] == "Aug. 31"
        assert w["end_date"] == "Sept. 28"

    def test_unparseable_preserves_raw_text(self) -> None:
        """OCR artifact: 'NNoovv.. 1188––2222' → raw_text preserved, dates None."""
        w = _parse_season_window("NNoovv.. 1188––2222")
        assert w is not None
        assert w["start_date"] is None
        assert w["end_date"] is None
        assert w["raw_text"] == "NNoovv.. 1188––2222"

    def test_none_input_returns_none(self) -> None:
        """None input → None (R2: None/empty/whitespace → not present)."""
        assert _parse_season_window(None) is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string → None (R2)."""
        assert _parse_season_window("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Whitespace-only string → None (R2)."""
        assert _parse_season_window("   ") is None

    def test_leading_bullet_stripped(self) -> None:
        """'■Aug. 15–25' — leading ■ bullet stripped before parsing."""
        w = _parse_season_window("■Aug. 15–25")
        assert w is not None
        assert w["start_date"] == "Aug. 15"
        assert w["end_date"] == "Aug. 25"
        # raw_text is always the original verbatim string per ADR-008
        assert w["raw_text"] == "■Aug. 15–25"

    def test_header_date(self) -> None:
        """Rule R7: _parse_header_date extracts season window from section heading."""
        heading = "Archery — Limited Resident & Nonresident Licenses — Season Dates: Sept. 2–30"
        w = _parse_header_date(heading)
        assert w is not None
        assert w["start_date"] == "Sept. 2"
        assert w["end_date"] == "Sept. 30"
        # raw_text is the full heading string
        assert w["raw_text"] == heading

    def test_header_date_no_date_returns_none(self) -> None:
        """'Rifle — Limited Licenses' has no inline date → None."""
        assert _parse_header_date("Rifle — Limited Licenses") is None

    def test_header_date_muzzleloader(self) -> None:
        """Muzzleloader heading with Season Dates parses correctly."""
        heading = "Muzzleloader — Limited Licenses — Season Dates: Sept. 12–20"
        w = _parse_header_date(heading)
        assert w is not None
        assert w["start_date"] == "Sept. 12"
        assert w["end_date"] == "Sept. 20"

    def test_cross_year_range(self) -> None:
        """'Aug. 15–\\nJan. 15, 2027' — year suffix on end date handled."""
        w = _parse_season_window("Aug. 15–\nJan. 15, 2027")
        assert w is not None
        assert w["start_date"] == "Aug. 15"
        assert w["end_date"] is not None
        assert "Jan. 15" in w["end_date"]


# ---------------------------------------------------------------------------
# 10. TestAssignConfidence
# ---------------------------------------------------------------------------


class TestAssignConfidence:
    """Unit tests for ``_assign_row_confidence`` — ADR-017 CPW adaptation."""

    def test_high_all_conditions_met(self) -> None:
        """HIGH: parsed hunt code + list_value present + resolved window."""
        row = _make_row(
            species_letter="D",
            list_value="A",
            season_windows=[
                CpwSeasonWindow(start_date="Sept. 2", end_date="Sept. 30", raw_text="Sept. 2–30")
            ],
        )
        assert _assign_row_confidence(row) == ConfidenceTier.HIGH

    def test_high_with_otc_list_value(self) -> None:
        """HIGH: 'OTC' is a valid list_value for the HIGH condition."""
        row = _make_row(list_value="OTC")
        assert _assign_row_confidence(row) == ConfidenceTier.HIGH

    def test_medium_no_list_value(self) -> None:
        """MEDIUM: parsed hunt code but list_value is None."""
        row = _make_row(list_value=None)
        assert _assign_row_confidence(row) == ConfidenceTier.MEDIUM

    def test_medium_no_resolved_window(self) -> None:
        """MEDIUM: parsed hunt code + list_value present but window unresolved."""
        row = _make_row(
            list_value="B",
            season_windows=[
                CpwSeasonWindow(start_date=None, end_date=None, raw_text="NNoovv.. 1188––2222")
            ],
        )
        assert _assign_row_confidence(row) == ConfidenceTier.MEDIUM

    def test_medium_empty_season_windows(self) -> None:
        """MEDIUM: no season windows at all."""
        row = _make_row(list_value="A", season_windows=[])
        assert _assign_row_confidence(row) == ConfidenceTier.MEDIUM

    def test_low_unparseable_hunt_code(self) -> None:
        """LOW: species_letter == '' means hunt code did not parse."""
        row = _make_row(hunt_code="GARBLED", species_letter="")
        assert _assign_row_confidence(row) == ConfidenceTier.LOW

    def test_high_header_derived_window(self) -> None:
        """HIGH condition 3: header-derived window with resolved dates satisfies HIGH.

        Per the implementation docstring: header-derived windows count just as
        well as inline per-row Dates cells (this is a deliberate CPW refinement
        over the original plan's 'header → MEDIUM' sketch).
        """
        row = _make_row(
            list_value="A",
            season_windows=[
                CpwSeasonWindow(
                    start_date="Sept. 2",
                    end_date="30",
                    raw_text="Season Dates: Sept. 2–30 (Unless otherwise noted)",
                )
            ],
        )
        assert _assign_row_confidence(row) == ConfidenceTier.HIGH


# ---------------------------------------------------------------------------
# 11. TestUndouble
# ---------------------------------------------------------------------------


class TestUndouble:
    """Unit tests for ``_undouble_text`` — Rule R14.

    Method names are locked by the module docstring:
      TestUndouble::test_undouble_hunt_code
      TestUndouble::test_not_doubled_unchanged
      TestUndouble::test_short_even_paired_left_alone
    """

    def test_undouble_hunt_code(self) -> None:
        """Uniformly doubled hunt code is recovered to the true text."""
        assert _undouble_text("DD--MM--002200--OO22--RR") == "D-M-020-O2-R"

    def test_not_doubled_unchanged(self) -> None:
        """Normal strings that are not uniformly doubled pass through unchanged."""
        assert _undouble_text("D-M-001-O1-A") == "D-M-001-O1-A"
        assert _undouble_text("Limited Licenses") == "Limited Licenses"

    def test_short_even_paired_left_alone(self) -> None:
        """Strings below _UNDOUBLE_MIN_LEN (6) are left alone even if pair-equal.

        'AA' (len 2) would pass s[::2]==s[1::2] but is below the minimum
        length guard — must be returned unchanged.
        """
        assert _undouble_text("AA") == "AA"

    def test_token_level_date_recovery(self) -> None:
        """Token-level fallback: doubled date cell with whitespace is recovered.

        pdfplumber collapses doubled spaces to single spaces, breaking the
        whole-string path.  The token-level fallback splits on whitespace,
        undoubles each token, and rejoins.
        """
        assert _undouble_text("OOcctt.. 2244––NNoovv.. 11") == "Oct. 24–Nov. 1"

    def test_none_input_returns_none(self) -> None:
        """None → None."""
        assert _undouble_text(None) is None

    def test_real_date_string_unchanged(self) -> None:
        """A real (non-doubled) date string passes through unchanged."""
        assert _undouble_text("Sept. 2–30") == "Sept. 2–30"

    def test_four_char_pair_equal_left_alone(self) -> None:
        """'AABB' (len 4, pair-equal s[::2]=='AB'==s[1::2]) is below min length — unchanged."""
        # len('AABB') == 4 < _UNDOUBLE_MIN_LEN (6); must pass through unchanged
        assert _undouble_text("AABB") == "AABB"

    def test_token_level_requires_at_least_one_long_token(self) -> None:
        """Token fallback only fires when at least one token reaches min length.

        '11 22' — both tokens are len 2 (below min); neither reaches
        _UNDOUBLE_MIN_LEN so the whole string must be left unchanged.
        """
        assert _undouble_text("11 22") == "11 22"

    def test_anchor_length_gate_real_date_unchanged(self) -> None:
        """Safety boundary: a real date string with no doubling is unchanged.

        'Sept. 2–30' is NOT pair-equal (s[::2] != s[1::2]), so it must
        pass through unchanged.  Documents the anchor-length gate invariant.
        """
        assert _undouble_text("Sept. 2–30") == "Sept. 2–30"

    def test_normal_multiword_text_unchanged(self) -> None:
        """Safety boundary: normal multi-word text is never corrupted.

        'Limited A' — the tokens are not pair-equal, so neither the
        whole-string nor token-level path fires.  Must be unchanged.
        Exercises the safety assumption that real CPW tokens are not
        coincidentally pair-equal unless actually doubled.
        """
        assert _undouble_text("Limited A") == "Limited A"

    def test_long_genuinely_doubled_token_recovers(self) -> None:
        """Anchor-length gate: a string where the only long token IS genuinely
        doubled is recovered, proving the gate does not over-block.

        'DDAABB 11' — first token is len 6 (>= _UNDOUBLE_MIN_LEN) and
        pair-equal (D,D,A,A,B,B → s[::2]='DAB'==s[1::2]='DAB'); second token
        is len 2 but also pair-equal ('11' → s[::2]='1'==s[1::2]='1').
        Token fallback fires and recovers to 'DAB 1'.
        """
        assert _undouble_text("DDAABB 11") == "DAB 1"


# ---------------------------------------------------------------------------
# 12. TestLooksDoubledRow
# ---------------------------------------------------------------------------


class TestLooksDoubledRow:
    """Unit tests for ``_looks_doubled_row`` — Rule R14 row-level gate."""

    def test_doubled_hunt_code_cell_triggers(self) -> None:
        """A row containing a long uniformly-doubled cell → True."""
        # 'DD--MM--002200--OO22--RR' is 24 chars and pair-equal
        row: list[str | None] = ["22", "22", None, "FF", "DD--MM--002200--OO22--RR", "AA"]
        assert _looks_doubled_row(row) is True

    def test_normal_row_not_doubled(self) -> None:
        """A normal regulation row → False."""
        row = ["1", "1", "Sept. 2–30", "M", "D-M-001-O1-A", "A"]
        assert _looks_doubled_row(row) is False

    def test_all_none_row_not_doubled(self) -> None:
        """Row of all None cells → False."""
        assert _looks_doubled_row([None, None, None]) is False

    def test_short_pair_equal_cell_not_enough(self) -> None:
        """A short pair-equal cell below _DOUBLED_ROW_MIN_CELL_LEN does NOT trigger.

        '2200' (len 4, stripped) is below the 10-char gate.
        """
        row = ["2200", "1", None, "M", "D-M-001-O1-A", "A"]
        assert _looks_doubled_row(row) is False

    def test_long_non_pair_equal_cell_not_doubled(self) -> None:
        """A long cell that is NOT pair-equal does not trigger the gate."""
        row = ["1", "Sept. 2–30 through the season and beyond", "M", "D-M-001-O1-A", "A", None]
        assert _looks_doubled_row(row) is False


# ---------------------------------------------------------------------------
# 11a. TestArtifactRegression
# ---------------------------------------------------------------------------


class TestArtifactRegression:
    """Pin the committed big-game-2026.json artifact to known-good stats.

    These tests load the committed JSON directly via ``extract_big_game._OUTPUT_PATH``
    (the same path the extractor writes to) and assert the exact stats produced by the
    real extraction run.  No live PDF required — the artifact is committed and small
    enough to load in CI.
    """

    @staticmethod
    def _load() -> list[dict]:  # type: ignore[type-arg]
        import json

        import pytest

        if not extract_big_game._OUTPUT_PATH.exists():
            pytest.skip(
                "artifact not generated — run extract_big_game.py to produce "
                "ingestion/states/colorado/extracted/big-game-2026.json"
            )
        with open(extract_big_game._OUTPUT_PATH) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_section_and_row_counts(self) -> None:
        """Artifact contains exactly 737 sections and 2758 total rows.

        P1-1 (Rule R15 ■ strip): 136 unit/valid_gmus fields cleaned — row count
        unchanged but field VALUES updated.
        P1-2 (garbage-row filter): 31 map-OCR garbage rows removed from sections,
        4 empty sections dropped.  Row count 2789 → 2758; section count 729 → 725.
        P1-3 (residency_scope in section key): 6 elk-archery sections that mixed
        ``both`` + ``nonresident`` rows split into separate sections; section
        count 725 → 731 (row count unchanged).
        Season Choice ('X'): the 10 season-choice deer rows now group into their
        own ``season_choice`` method sections (separate from the rifle sections
        they previously fell into), raising the section count 731 → 737 (row
        count unchanged).
        """
        data = self._load()
        assert len(data) == 737
        total_rows = sum(len(s.get("rows", [])) for s in data)
        assert total_rows == 2758

    def test_confidence_distribution(self) -> None:
        """Confidence distribution is pinned: high=2069, medium=684, low=5.

        P1-2 (garbage-row filter): 31 of the previous 36 LOW rows were pure
        map-OCR garbage.  After filtering, 5 real LOW rows remain (all
        multi-hunt-code cells containing a valid hunt-code-shaped fragment).
        F2 (header_window cross-method bleed fix): before that fix, a stale
        archery ``Season Dates`` header window bled into following rifle sections,
        causing 522 rifle rows to be mis-classified HIGH.  Old pre-F2 distribution:
        high=2591, medium=162, low=36.  Post-F2 pre-P1-2: high=2069, medium=684, low=36.
        Post-P1-2: high=2069, medium=684, low=5.
        P1-5 (RFW column-shift recovery): ~160 RFW/private-land rows had their
        per-row Dates value mis-mapped into ``valid_gmus`` with an empty (or
        wrong header) window. Recovering the date into ``season_windows`` moved
        them MEDIUM→HIGH: high 2069→2229, medium 684→524 (low unchanged at 5).
        P1-6 (method-aware header windows): a muzzleloader ``Season dates:``
        header no longer bleeds onto rifle rows (those lose the wrong window →
        MEDIUM), while muzzleloader rows correctly retain it. Net: high
        2229→2170, medium 524→583 (low unchanged at 5).
        """
        from collections import Counter

        data = self._load()
        dist = Counter(
            row["extraction_confidence"]
            for s in data
            for row in s.get("rows", [])
        )
        assert dict(dist) == {"high": 2170, "medium": 583, "low": 5}

    def test_no_rifle_header_window_bleed(self) -> None:
        """P1-6 lock: no rifle row carries a header-style season window.

        Header windows ("Season dates: …") are an archery/muzzleloader
        convention (those tables lack a per-row Dates column). Rifle rows get
        their date from a per-row Dates cell or the RFW column-shift recovery,
        never from another method's header. A rifle row whose ``raw_text``
        contains a "Season dates" header signature means a cross-method bleed.
        """
        import re

        sig = re.compile(r"Season [Dd]ates", re.IGNORECASE)
        data = self._load()
        offenders = [
            (row["hunt_code"], w.get("raw_text", "")[:50])
            for s in data
            for row in s.get("rows", [])
            if row.get("method_group") == "rifle"
            for w in row.get("season_windows", [])
            if sig.search(w.get("raw_text") or "")
        ]
        assert not offenders, f"rifle rows with bled header window: {offenders[:8]}"

    def test_all_four_species_present(self) -> None:
        """All four V1 species are present; per-species section counts are pinned.

        P1-2 (garbage-row filter): sections that had only garbage rows were dropped,
        reducing mule_deer 306→305, whitetail 32→31, elk 256→254 (4 sections total).
        P1-3 (residency_scope in section key): 6 elk-archery sections split on
        residency, raising elk 254→260 (other species unchanged).
        Season Choice ('X'): the 10 season-choice deer rows split into their own
        season_choice sections; the units explicitly marked "white-tailed only"
        become whitetail (whitetail 31→34) and the rest stay mule_deer
        (mule_deer 305→308). elk/pronghorn unchanged.
        """
        from collections import Counter

        data = self._load()
        assert {s["species_group"] for s in data} == {
            "mule_deer",
            "whitetail",
            "elk",
            "pronghorn",
        }
        section_counts = Counter(s["species_group"] for s in data)
        assert section_counts["mule_deer"] == 308
        assert section_counts["whitetail"] == 34
        assert section_counts["elk"] == 260
        assert section_counts["pronghorn"] == 135

    def test_season_choice_rows_classified(self) -> None:
        """Season Choice ('X') rows are method_group='season_choice' with the
        union weapon_types, not a silent rifle fallback with empty weapon_types.
        """
        data = self._load()
        x_rows = [
            r
            for s in data
            for r in s.get("rows", [])
            if r.get("method_letter") == "X"
        ]
        assert x_rows, "no Season Choice ('X') rows found in artifact"
        for r in x_rows:
            assert r["method_group"] == "season_choice", (
                f"{r['hunt_code']} should be season_choice, got {r['method_group']}"
            )
            assert r["weapon_types"] == [
                "archery",
                "muzzleloader",
                "any_legal_weapon",
            ], f"{r['hunt_code']} weapon_types={r['weapon_types']}"

    def test_no_mixed_residency_sections(self) -> None:
        """P1-3 lock: no section mixes more than one residency_scope.

        The section key includes residency_scope, so every section is a single
        GMU × method × residency block. Section-level verbatim_text / page_reference
        therefore represent one logical block (no resident/nonresident conflation).
        """
        data = self._load()
        offenders = [
            (s["species_group"], s["method_group"], s["gmu_code"])
            for s in data
            if len({r["residency_scope"] for r in s.get("rows", [])}) > 1
        ]
        assert not offenders, f"sections mixing residency_scope: {offenders[:10]}"

    def test_dedouble_recovery_locked(self) -> None:
        """R14 de-doubling end-to-end: D-M-020-O2-R is present with correct window."""
        data = self._load()
        matched = [
            row
            for s in data
            for row in s.get("rows", [])
            if row.get("hunt_code") == "D-M-020-O2-R"
        ]
        assert matched, "hunt_code D-M-020-O2-R not found in artifact — R14 regression"
        row = matched[0]
        assert row["extraction_confidence"] == "high"
        windows = row.get("season_windows", [])
        assert windows, "D-M-020-O2-R has no season_windows"
        # Exact strings produced by the parser (cross-month range Oct. 24–Nov. 1).
        assert any(
            w.get("start_date") == "Oct. 24" and w.get("end_date") == "Nov. 1"
            for w in windows
        ), f"Expected start_date='Oct. 24', end_date='Nov. 1'; got windows={windows}"

    def test_no_date_shaped_valid_gmus(self) -> None:
        """P1-5 lock: no row carries a date in ``valid_gmus``.

        RFW/private-land tables (pages 32/44/51) lack a Valid GMUs column, so
        the standard column map wrote the Dates value into ``valid_gmus``. The
        column-shift recovery moves a date-shaped ``valid_gmus`` into
        ``season_windows`` and nulls the field, so no row should retain a
        month-abbreviation in ``valid_gmus``.
        """
        import re

        month = re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Oct|Nov|Dec)\.")
        data = self._load()
        offenders = [
            (s["species_group"], row["hunt_code"], row["valid_gmus"])
            for s in data
            for row in s.get("rows", [])
            if row.get("valid_gmus") and month.search(row["valid_gmus"])
        ]
        assert not offenders, f"date-shaped valid_gmus rows remain: {offenders[:8]}"

    def test_pronghorn_per_row_windows(self) -> None:
        """Pronghorn row A-M-012-O1-A exists; male and female windows differ."""
        data = self._load()

        def _find(hunt_code: str) -> dict | None:  # type: ignore[type-arg]
            for s in data:
                for row in s.get("rows", []):
                    if row.get("hunt_code") == hunt_code:
                        return row  # type: ignore[return-value]
            return None

        male_row = _find("A-M-012-O1-A")
        assert male_row is not None, "hunt_code A-M-012-O1-A not found in artifact"
        assert male_row["extraction_confidence"] == "high"

        female_row = _find("A-F-012-O1-A")
        assert female_row is not None, (
            "hunt_code A-F-012-O1-A not found in artifact — per-row window "
            "divergence test would be vacuous without it"
        )
        # Male: Aug. 15–Sept. 20; Female: Sept. 1–20 — windows must differ.
        male_windows = male_row.get("season_windows", [])
        female_windows = female_row.get("season_windows", [])
        assert male_windows != female_windows, (
            "A-M-012-O1-A and A-F-012-O1-A share identical season_windows "
            "— per-row window divergence lost"
        )

    def test_confidence_values_are_plain_strings(self) -> None:
        """extraction_confidence values are plain strings, not enum repr."""
        data = self._load()
        valid = {"high", "medium", "low"}
        bad: list[str] = []
        for s in data:
            for row in s.get("rows", []):
                val = row.get("extraction_confidence", "")
                if val not in valid:
                    bad.append(repr(val))
        assert not bad, (
            f"Found {len(bad)} row(s) with non-plain extraction_confidence: {bad[:5]}"
        )


# ---------------------------------------------------------------------------
# 11b. TestDeterministicJsonOutput
# ---------------------------------------------------------------------------


class TestDeterministicJsonOutput:
    def test_determinism_requires_real_pdf(self) -> None:
        """Determinism is validated end-to-end by the manual 2-run SHA recipe.

        This test exists as a placeholder and intentional skip so the test
        class surface is visible in CI output.  The full extract() pipeline
        requires the real CPW Big Game PDF (~96 MB, gitignored) which is not
        present in the unit-test environment.

        Two consecutive ``extract()`` runs against the committed PDF produced
        byte-identical output with SHA-256:
            e5c7c33a728a95f3d2845894ce53d4de664ed20bfc40853eaa421ac8d12e6d1e
        """
        import pytest as _pytest

        _pytest.skip(
            "integration — requires real CPW Big Game PDF (~96 MB, gitignored); "
            "determinism verified by manual 2-run SHA recipe "
            "(SHA-256: e5c7c33a728a95f3d2845894ce53d4de664ed20bfc40853eaa421ac8d12e6d1e)"
        )


# ---------------------------------------------------------------------------
# 11c. TestValidGmusClean — valid_gmus carries only the structured GMU list;
#      free-text qualifiers are routed to extras (and preserved in verbatim_text)
#      via the module-private _split_valid_gmus helper.
# ---------------------------------------------------------------------------


class TestValidGmusClean:
    """valid_gmus is a clean GMU list; prose qualifiers live in extras.

    Loads the committed artifact directly (no live PDF). Locks the coordinated
    cross-extractor fix: the 'Valid GMUs' cell's free-text qualifier (e.g.
    'private land only', 'Except Bosque del Oso SWA', 'and private land in
    12, 23, 24') no longer contaminates the structured valid_gmus field.
    """

    @staticmethod
    def _rows() -> list[dict]:  # type: ignore[type-arg]
        import json

        import pytest

        if not extract_big_game._OUTPUT_PATH.exists():
            pytest.skip("artifact not generated — run extract_big_game.py")
        with open(extract_big_game._OUTPUT_PATH) as f:
            recs = json.load(f)
        return [row for r in recs if "rows" in r for row in r["rows"]]

    def test_no_alpha_in_valid_gmus(self) -> None:
        """No section row's valid_gmus contains an alphabetic character."""
        bad = [
            row["valid_gmus"]
            for row in self._rows()
            if row.get("valid_gmus") and re.search(r"[A-Za-z]", row["valid_gmus"])
        ]
        assert not bad, f"{len(bad)} valid_gmus values still carry prose: {bad[:5]}"

    def test_qualifier_routed_to_extras_and_verbatim(self) -> None:
        """An 'Except Bosque del Oso SWA' qualifier is in extras, not valid_gmus."""
        rows = self._rows()
        hits = [
            row
            for row in rows
            if row.get("extras") and "Except Bosque del Oso SWA" in row["extras"]
        ]
        assert hits, "expected at least one row with the SWA exclusion in extras"
        for row in hits:
            assert "Except" not in (row.get("valid_gmus") or ""), (
                f"qualifier leaked back into valid_gmus: {row['valid_gmus']!r}"
            )

    def test_private_land_in_units_not_promoted(self) -> None:
        """'and private land in 12, 23, 24' keeps 12/23/24 OUT of valid_gmus."""
        rows = self._rows()
        hits = [
            row
            for row in rows
            if row.get("extras") and "private land in" in row["extras"]
        ]
        assert hits, "expected a 'private land in N' qualifier row"
        for row in hits:
            # The qualifier (incl. its embedded units) lives in extras; valid_gmus
            # holds only the structured leading GMU run (no connector prose).
            vg = row.get("valid_gmus") or ""
            assert "and" not in vg and not re.search(r"[A-Za-z]", vg), vg


# ---------------------------------------------------------------------------
# 11d. TestSplitValidGmus — unit tests for the module-private _split_valid_gmus
# ---------------------------------------------------------------------------


class TestSplitValidGmus:
    """Unit tests for ``extract_big_game._split_valid_gmus`` — CPW Valid-GMUs cell splitter."""

    # --- None / empty inputs ------------------------------------------------

    def test_none_returns_none_none(self) -> None:
        assert _split_valid_gmus(None) == (None, None)

    def test_whitespace_only_returns_none_none(self) -> None:
        assert _split_valid_gmus("   ") == (None, None)

    # --- Pure GMU cells (no qualifier) — must be returned UNCHANGED ----------

    def test_pure_gmu_list_returned_unchanged(self) -> None:
        # No reformatting: the original string is returned as-is.
        assert _split_valid_gmus("83, 85, 140") == ("83, 85, 140", None)

    def test_pure_gmu_list_with_newline_returned_unchanged(self) -> None:
        # Newlines inside a pure-GMU cell must be preserved verbatim.
        assert _split_valid_gmus("83, 85,\n140") == ("83, 85,\n140", None)

    def test_pure_gmu_list_multi_newline_unchanged(self) -> None:
        # Several GMUs split across multiple lines — still pure, still unchanged.
        assert _split_valid_gmus("12, 13,\n23,\n24") == ("12, 13,\n23,\n24", None)

    # --- GMUs + exclusion-clause qualifier ----------------------------------

    def test_gmus_with_except_qualifier(self) -> None:
        assert _split_valid_gmus(
            "83, 85, 140, 851\nExcept Bosque del Oso SWA"
        ) == ("83, 85, 140, 851", "Except Bosque del Oso SWA")

    def test_gmus_with_private_land_qualifier(self) -> None:
        assert _split_valid_gmus(
            "12, 13, 23, 24\nprivate land only"
        ) == ("12, 13, 23, 24", "private land only")

    # --- Leading 'New' marker -----------------------------------------------

    def test_new_marker_before_gmus_goes_to_qualifier(self) -> None:
        # 'New' is a leading marker: it moves to qualifier_tokens, not gmu_tokens.
        assert _split_valid_gmus(
            "New 3, 11,\n211, 301\nprivate land only"
        ) == ("3, 11, 211, 301", "New private land only")

    def test_new_alone_returns_none_qualifier(self) -> None:
        # 'New' with no GMUs → clean is None, qualifier is 'New'.
        assert _split_valid_gmus("New") == (None, "New")

    # --- Embedded GMU numbers in qualifier must NOT be promoted --------------

    def test_embedded_gmu_in_note_stays_in_qualifier(self) -> None:
        result = _split_valid_gmus(
            "12, 13, 23, 24, 25, 26,\n33, 34, 131, 231\n"
            "Note: No hunting access to\nGMU 211."
        )
        assert result == (
            "12, 13, 23, 24, 25, 26, 33, 34, 131, 231",
            "Note: No hunting access to GMU 211.",
        )

    def test_embedded_exclusion_211_not_in_clean_list(self) -> None:
        # Explicit assertion that 211 (mentioned in the Note) is NOT a valid GMU.
        clean, _qualifier = _split_valid_gmus(
            "12, 13, 23, 24, 25, 26,\n33, 34, 131, 231\n"
            "Note: No hunting access to\nGMU 211."
        )
        assert clean is not None
        assert "211" not in clean.split(", ")

    def test_private_land_in_gmus_stay_in_qualifier(self) -> None:
        # 'and' triggers qualifier; the 12/23/24 that follow are NOT promoted.
        assert _split_valid_gmus(
            "11, 13, 22, 131, 211, 231 and private land in 12, 23, 24"
        ) == ("11, 13, 22, 131, 211, 231", "and private land in 12, 23, 24")

    # --- '+' connector / named-area qualifier --------------------------------

    def test_gmu_plus_named_area(self) -> None:
        assert _split_valid_gmus("851 + Bosque del Oso SWA only") == (
            "851",
            "+ Bosque del Oso SWA only",
        )

    def test_gmu_plus_named_area_with_newlines(self) -> None:
        # '+' token is not a GMU token → qualifier boundary; prose collapsed.
        assert _split_valid_gmus("851 +\nBosque del Oso\nSWA only") == (
            "851",
            "+ Bosque del Oso SWA only",
        )

    # --- No leading GMUs (qualifier only) ------------------------------------

    def test_qualifier_only_no_gmus_returns_none_clean(self) -> None:
        assert _split_valid_gmus("private land only") == (None, "private land only")

    # --- GMUs without comma separators (space-only separation) --------------

    def test_gmus_with_inline_prose_no_comma(self) -> None:
        # 'private' is not a GMU token → boundary fires immediately after 441.
        assert _split_valid_gmus(
            "4, 5, 14, 214, 441 private land only"
        ) == ("4, 5, 14, 214, 441", "private land only")
