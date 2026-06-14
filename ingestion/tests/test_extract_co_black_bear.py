"""Unit tests for `states.colorado.extract_black_bear` — CPW Black Bear regulation
extraction structural guards and functional unit tests (S06.4 T7).

Test philosophy:
- All tests are hermetic: no real PDF required, no live network.
- Static / AST-level guards, pure-helper unit tests, and artifact-structure
  invariants loaded from the committed JSON artifacts (no PDF parsing).
- Mirrors the conventions of ``test_extract_co_big_game.py`` exactly.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

import pytest

import states.colorado.extract_black_bear as extract_black_bear
from ingestion.lib.pdf import ConfidenceTier, PageReference, PdfExtractionError
from states.colorado.extract_black_bear import (
    CorrectionConflictError,
    CorrectionOperation,
    CpwBearRowExtraction,
    CpwBearSectionExtraction,
    CpwSeasonWindow,
    _CORRECTABLE_FIELDS,
    _VALID_DOCUMENT_TYPES,
    _assign_bear_row_confidence,
    _bear_classify_table_variant,
    _bear_is_footnote_row,
    _bear_is_note_annotation_row,
    _bear_is_see_unit_row,
    _collapse_whitespace,
    _merge_with_corrections,
    _method_group_for,
    _normalize_bear_cell,
    _parse_bear_header_date,
    _parse_bear_season_window,
    _parse_hunt_code,
    _rejoin_hyphenated_linebreaks,
    _weapon_types_for,
)

# ---------------------------------------------------------------------------
# Re-use the AST-walk helper from test_extract_dea (state-agnostic by design).
# ---------------------------------------------------------------------------
from tests.test_extract_dea import _find_foreign_state_imports  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_page_ref(page: int = 73) -> PageReference:
    return PageReference(
        pdf_filename="co-cpw-big-game-2026-brochure-2026-03-04.pdf",
        page_num_1based=page,
        bbox=None,
        extracted_at="2026-06-13T00:00:00Z",
    )


def _make_bear_row(
    hunt_code: str = "B-E-050-O1-A",
    species_letter: str = "B",
    list_value: str | None = "A",
    season_windows: list[CpwSeasonWindow] | None = None,
    method_group: str = "archery",
    license_kind: str = "limited_draw",
) -> CpwBearRowExtraction:
    if season_windows is None:
        season_windows = [
            CpwSeasonWindow(
                start_date="Sept. 2",
                end_date="Sept. 30",
                raw_text="Sept. 2–30",
            )
        ]
    return CpwBearRowExtraction(
        hunt_code=hunt_code,
        species_letter=species_letter,
        sex_code="E",
        gmu_code="050",
        season_code="O1",
        method_letter="A",
        unit="50",
        valid_gmus="50",
        season_windows=season_windows,
        list_value=list_value,
        apply_by=None,
        quota=None,
        quota_range=None,
        weapon_types=["archery"],
        method_group=method_group,
        residency_scope="both",
        license_kind=license_kind,
        extras=None,
        extraction_confidence="",
        page_reference=_make_page_ref(),
    )


def _make_section(
    rows: list[CpwBearRowExtraction] | None = None,
    method_group: str = "archery",
    gmu_code: str = "050",
    license_kind: str = "limited_draw",
) -> CpwBearSectionExtraction:
    if rows is None:
        rows = [_make_bear_row()]
    return CpwBearSectionExtraction(
        source_id="co-cpw-big-game-2026-brochure",
        species_group="black_bear",
        method_group=method_group,
        gmu_code=gmu_code,
        residency_scope="both",
        license_kind=license_kind,
        license_year=2026,
        extracted_at="2026-06-13T00:00:00Z",
        page_reference=_make_page_ref(),
        verbatim_text="50 | 50 | Sept. 2–30 | B-E-050-O1-A | A",
        notes=None,
        rows=rows,
    )


def _make_correction_op(
    target_license_code: str = "B-E-050-O1-A",
    target_field: str = "list_value",
    old_value: str | None = "A",
    new_value: str | None = "B",
    publication_date: str = "2026-02-19",
) -> CorrectionOperation:
    return CorrectionOperation(
        target_license_code=target_license_code,
        target_field=target_field,
        old_value=old_value,
        new_value=new_value,
        source_id="co-cpw-big-game-2026-correction-2026-02-19",
        publication_date=publication_date,
    )


# ---------------------------------------------------------------------------
# 1. TestNoForeignStateAdapterImports
# ---------------------------------------------------------------------------


class TestNoForeignStateAdapterImports:
    """AST-walk guard: extract_black_bear.py must not import from other states'
    adapters, and must not import from ingestion.lib.db.

    Per ADR-005 (adapter isolation) and the single-writer contract:
    extract_black_bear.py produces JSON only; no DB writes in S06.4.
    """

    _ALLOWED_STATE: str = "colorado"

    def test_no_foreign_state_imports(self) -> None:
        """extract_black_bear.py itself is clean of foreign state imports."""
        source_path = Path(extract_black_bear.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        violations = _find_foreign_state_imports(source, self._ALLOWED_STATE)
        assert not violations, (
            "extract_black_bear.py contains foreign state adapter imports:\n"
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
        """extract_black_bear.py has no ingestion.lib.db imports.

        Single-writer contract: S06.4 produces JSON only. No database writes.
        Downstream loaders (S06.6–S06.9) read the artifact and write to DB.
        """
        source_path = Path(extract_black_bear.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        assert "from ingestion.lib.db" not in source, (
            "extract_black_bear.py imports from ingestion.lib.db — "
            "violates S06.4 single-writer contract"
        )
        assert "import ingestion.lib.db" not in source, (
            "extract_black_bear.py imports ingestion.lib.db — "
            "violates S06.4 single-writer contract"
        )


# ---------------------------------------------------------------------------
# 2. TestNoLayoutTrue
# ---------------------------------------------------------------------------


class TestNoLayoutTrue:
    """Source-text guard: extract_black_bear.py must never call pdfplumber's
    extract_text with ``layout=True``.

    Passing ``layout=True`` injects synthetic spaces and violates ADR-008
    verbatim discipline.
    """

    def test_no_layout_true_regression_guard(self) -> None:
        """The literal ``layout=True`` must not appear in extract_black_bear.py."""
        source_path = Path(extract_black_bear.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        assert "layout=True" not in source, (
            "extract_black_bear.py contains 'layout=True' — passing layout=True "
            "to pdfplumber's extract_text injects synthetic spaces and violates "
            "ADR-008 verbatim discipline."
        )


# ---------------------------------------------------------------------------
# 3. TestCleanupRulesDocstringParity
# ---------------------------------------------------------------------------


class TestCleanupRulesDocstringParity:
    """Docstring parity guard: the module docstring must document every cleanup
    rule R1 through R17.

    Per the S03.3 AC #547 analog (grep-parity discipline): every cleanup rule
    applied to row cells must appear in the module docstring's "Cleanup rules"
    section.  The exact format used in the module docstring is ``Rule RN:``.
    """

    _RULE_COUNT: int = 17

    def test_every_rule_has_a_docstring_entry(self) -> None:
        """Rule R1 through R17 must each appear in the module docstring."""
        docstring = extract_black_bear.__doc__ or ""
        assert docstring, "extract_black_bear module has no docstring"

        missing: list[str] = []
        for n in range(1, self._RULE_COUNT + 1):
            marker = f"Rule R{n}:"
            if marker not in docstring:
                missing.append(marker)

        assert not missing, (
            "The following cleanup rules are missing from extract_black_bear.py's "
            "module docstring:\n" + "\n".join(f"  - {m}" for m in missing)
        )

    def test_rule_count_locked(self) -> None:
        """Exactly 17 rule entries appear in the docstring (no silent additions)."""
        docstring = extract_black_bear.__doc__ or ""
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
        docstring = extract_black_bear.__doc__ or ""
        citation_re = re.compile(r"([A-Z][A-Za-z0-9_]+)::([a-z][A-Za-z0-9_]+)")
        citations = citation_re.findall(docstring)
        assert citations, (
            "No 'ClassName::method' citations found in docstring — check the regex"
        )

        this_module = sys.modules[__name__]
        missing: list[str] = []
        for cls_name, method_name in citations:
            cls = getattr(this_module, cls_name, None)
            if cls is None:
                missing.append(f"{cls_name}::{method_name}  (class not found)")
                continue
            if not (inspect.isclass(cls) and hasattr(cls, method_name)):
                missing.append(
                    f"{cls_name}::{method_name}  (method not found on class)"
                )

        assert not missing, (
            "The following 'locked by' citations in extract_black_bear.py's module "
            "docstring point to non-existent test classes or methods:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


# ---------------------------------------------------------------------------
# 4. TestNormalizeBearCell  (Rules R1 / R2 / R3 / R6 / R13)
# ---------------------------------------------------------------------------


class TestNormalizeBearCell:
    """Unit tests for ``_normalize_bear_cell``.

    Method names locked by module docstring citations:
      TestNormalizeBearCell::test_dash_sentinel_nulled
      TestNormalizeBearCell::test_whitespace_nulled
      TestNormalizeBearCell::test_hyphen_rejoin
      TestNormalizeBearCell::test_strips_otc_bullet
    """

    def test_dash_sentinel_nulled(self) -> None:
        """Rule R1: bare '-' → None."""
        assert _normalize_bear_cell("-") is None

    def test_dash_with_whitespace_nulled(self) -> None:
        """Rule R1: '  -  ' (surrounded by whitespace) → None."""
        assert _normalize_bear_cell("  -  ") is None

    def test_whitespace_nulled(self) -> None:
        """Rule R2: empty/whitespace-only → None."""
        assert _normalize_bear_cell("") is None
        assert _normalize_bear_cell("   ") is None
        assert _normalize_bear_cell("\t\n") is None

    def test_none_input_nulled(self) -> None:
        """Rule R2: None input → None."""
        assert _normalize_bear_cell(None) is None

    def test_strip(self) -> None:
        """Rule R13: leading/trailing whitespace stripped."""
        assert _normalize_bear_cell("  hello  ") == "hello"

    def test_otc_preserved(self) -> None:
        """Rule R9 analog: 'OTC' is a valid list value — not nulled by R1."""
        assert _normalize_bear_cell("OTC") == "OTC"

    def test_hyphen_rejoin(self) -> None:
        """Rule R3: alphanumeric-neighboured hyphen-newline rejoined."""
        assert _normalize_bear_cell("B-E-\n050") == "B-E-050"

    def test_period_hyphen_not_rejoined(self) -> None:
        """Rule R3 narrow: period before hyphen is NOT alphanumeric — not rejoined."""
        result = _normalize_bear_cell("Sept.-\nOct.")
        assert result is not None
        assert "-\n" in result

    def test_whitespace_not_collapsed_globally(self) -> None:
        """R4 does NOT apply to _normalize_bear_cell — internal spaces preserved."""
        result = _normalize_bear_cell("Sept. 2\nOct. 3")
        assert result == "Sept. 2\nOct. 3"

    def test_plain_text_preserved(self) -> None:
        """Ordinary cell text is returned unchanged (after strip)."""
        assert _normalize_bear_cell("Limited") == "Limited"
        assert _normalize_bear_cell("B-E-050-O1-A") == "B-E-050-O1-A"

    def test_strips_otc_bullet(self) -> None:
        """Rule R6: CPW ■ OTC-marker glyph stripped from structured cells.

        Three cases:
          - '■50'   → '50'    (leading bullet before digit)
          - '3\\n■'  → '3'    (trailing bullet with newline)
          - '■'     → None    (bullet-only cell → absent per ADR-001)

        Locked by module docstring citation:
          TestNormalizeBearCell::test_strips_otc_bullet
        """
        assert _normalize_bear_cell("■50") == "50"
        assert _normalize_bear_cell("3\n■") == "3"
        assert _normalize_bear_cell("■") is None


# ---------------------------------------------------------------------------
# 5. TestBearRejoinAndCollapse
# ---------------------------------------------------------------------------


class TestBearRejoinAndCollapse:
    """Unit tests for ``_rejoin_hyphenated_linebreaks`` and ``_collapse_whitespace``.

    Method names locked by module docstring citations:
      TestBearRejoinAndCollapse::test_collapse_whitespace_multi_space
      TestBearRejoinAndCollapse::test_collapse_whitespace_newlines
    """

    def test_rejoin_alphanumeric_neighbours(self) -> None:
        """Soft hyphen between alphanumeric chars: newline dropped, hyphen kept."""
        assert _rejoin_hyphenated_linebreaks("word-\nword") == "word-word"

    def test_rejoin_no_newline_unchanged(self) -> None:
        """'B-E-050' has no newline — unchanged."""
        assert _rejoin_hyphenated_linebreaks("B-E-050") == "B-E-050"

    def test_rejoin_period_before_hyphen_unchanged(self) -> None:
        """Period before hyphen: NOT rejoined (period not alphanumeric)."""
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
# 6. TestBearRowFilters  (Rules R5 / R10 / R11)
# ---------------------------------------------------------------------------


class TestBearRowFilters:
    """Unit tests for ``_bear_is_footnote_row``, ``_bear_is_see_unit_row``,
    ``_bear_is_note_annotation_row``.

    Method names locked by module docstring citations:
      TestBearRowFilters::test_footnote_bullet_skipped
      TestBearRowFilters::test_see_unit_row_skipped
      TestBearRowFilters::test_note_annotation_row_skipped
    """

    # --- _bear_is_footnote_row (Rule R5) ---

    def test_footnote_bullet_skipped(self) -> None:
        """Rule R5: first non-empty cell starts with ■ → True."""
        assert _bear_is_footnote_row(["■Units 12, 13 are valid for add-on bear licenses"]) is True

    def test_footnote_with_leading_whitespace(self) -> None:
        """Rule R5: cell with leading whitespace before ■ is still caught."""
        assert _bear_is_footnote_row(["  ■ Some footnote text"]) is True

    def test_non_footnote_row(self) -> None:
        """A normal data row does not start with ■ → False."""
        assert _bear_is_footnote_row(["50", "50", "B-E-050-O1-A", "A"]) is False

    def test_none_only_row_not_footnote(self) -> None:
        """Row of all None cells → False."""
        assert _bear_is_footnote_row([None, None, None]) is False

    # --- _bear_is_see_unit_row (Rule R10) ---

    def test_see_unit_row_skipped(self) -> None:
        """Rule R10: 'see unit 83' in any cell → True."""
        assert _bear_is_see_unit_row([None, "see unit 83", None, None]) is True

    def test_see_unit_case_insensitive(self) -> None:
        """Rule R10: 'SEE UNIT 12' (uppercase) → True."""
        assert _bear_is_see_unit_row(["SEE UNIT 12"]) is True

    def test_normal_row_not_see_unit(self) -> None:
        """A normal data row returns False."""
        assert _bear_is_see_unit_row(["50", "50", "B-E-050-O1-A", "A"]) is False

    def test_none_only_not_see_unit(self) -> None:
        """Row of all None cells → False."""
        assert _bear_is_see_unit_row([None, None, None]) is False

    # --- _bear_is_note_annotation_row (Rule R11) ---

    def test_note_annotation_row_skipped(self) -> None:
        """Rule R11: 'Note: No hunting access to GMU 211.' → True."""
        assert _bear_is_note_annotation_row([None, "Note: No hunting access to GMU 211.", None]) is True

    def test_note_case_insensitive(self) -> None:
        """Rule R11: 'NOTE: ...' (uppercase) → True."""
        assert _bear_is_note_annotation_row(["NOTE: Some annotation"]) is True

    def test_non_note_row(self) -> None:
        """A regular row is not a note-annotation row."""
        assert _bear_is_note_annotation_row(["50", "50, 51", "B-E-050-O1-A", "A"]) is False


# ---------------------------------------------------------------------------
# 7. TestBearParseHuntCode  (Rules R8 / R12)
# ---------------------------------------------------------------------------


class TestBearParseHuntCode:
    """Unit tests for ``_parse_hunt_code``.

    Method names locked by module docstring citations:
      TestBearParseHuntCode::test_valid_bear_code_parsed
      TestBearParseHuntCode::test_non_bear_species_letter_logged
      TestBearParseHuntCode::test_plus_suffix_stripped
    """

    def test_valid_bear_code_parsed(self) -> None:
        """Rule R8: standard bear code parses to all five components."""
        result = _parse_hunt_code("B-E-050-O1-M")
        assert result is not None
        assert result["species_letter"] == "B"
        assert result["sex_code"] == "E"
        assert result["gmu_code"] == "050"
        assert result["season_code"] == "O1"
        assert result["method_letter"] == "M"

    def test_non_bear_species_letter_logged(self) -> None:
        """Rule R8: a non-'B' species letter (e.g. 'D') still parses — caller logs WARNING."""
        result = _parse_hunt_code("D-E-050-O1-A")
        assert result is not None
        assert result["species_letter"] == "D"

    def test_plus_suffix_stripped(self) -> None:
        """Rule R12: trailing ' +' cross-reference marker stripped before parse."""
        result = _parse_hunt_code("B-E-851-O1-M +")
        assert result is not None
        assert result["species_letter"] == "B"
        assert result["gmu_code"] == "851"

    def test_archery_code(self) -> None:
        """Archery method letter 'A' parses correctly."""
        result = _parse_hunt_code("B-E-001-O1-A")
        assert result is not None
        assert result["method_letter"] == "A"

    def test_rifle_code(self) -> None:
        """Rifle method letter 'R' parses correctly."""
        result = _parse_hunt_code("B-E-001-O1-R")
        assert result is not None
        assert result["method_letter"] == "R"

    def test_four_digit_gmu_code(self) -> None:
        """Four-digit GMU codes are valid per regex."""
        result = _parse_hunt_code("B-E-0201-O1-A")
        assert result is not None
        assert result["gmu_code"] == "0201"

    def test_malformed_code_returns_none(self) -> None:
        """Malformed codes return None — no raise."""
        assert _parse_hunt_code("INVALID") is None
        assert _parse_hunt_code("B-E-01-O1-A") is None  # GMU too short
        assert _parse_hunt_code("") is None
        assert _parse_hunt_code("B-E-050-O1") is None  # missing method

    def test_returns_dict_with_exactly_five_keys(self) -> None:
        """Parsed result has exactly the five expected keys."""
        result = _parse_hunt_code("B-E-050-O1-A")
        assert result is not None
        assert set(result.keys()) == {
            "species_letter",
            "sex_code",
            "gmu_code",
            "season_code",
            "method_letter",
        }


# ---------------------------------------------------------------------------
# 8. TestMethodAndWeapon
# ---------------------------------------------------------------------------


class TestMethodAndWeapon:
    """Unit tests for ``_method_group_for`` and ``_weapon_types_for``."""

    # --- _method_group_for ---

    def test_method_group_archery(self) -> None:
        assert _method_group_for("A") == "archery"

    def test_method_group_muzzleloader(self) -> None:
        assert _method_group_for("M") == "muzzleloader"

    def test_method_group_rifle(self) -> None:
        assert _method_group_for("R") == "rifle"

    def test_method_group_unknown_returns_none(self) -> None:
        """Bear V1 has no Season Choice — unknown letter returns None, not raises."""
        assert _method_group_for("X") is None
        assert _method_group_for("Z") is None
        assert _method_group_for("") is None

    # --- _weapon_types_for ---

    def test_weapon_types_archery(self) -> None:
        assert _weapon_types_for("A") == ["archery"]

    def test_weapon_types_muzzleloader(self) -> None:
        assert _weapon_types_for("M") == ["muzzleloader"]

    def test_weapon_types_rifle_maps_to_any_legal_weapon(self) -> None:
        """CPW 'R' (rifle) → ['any_legal_weapon'], not ['rifle']."""
        assert _weapon_types_for("R") == ["any_legal_weapon"]

    def test_weapon_types_unknown_returns_empty_list(self) -> None:
        """Unknown letter → [] (does not raise)."""
        assert _weapon_types_for("Z") == []
        assert _weapon_types_for("") == []


# ---------------------------------------------------------------------------
# 9. TestBearParseHeaderDate  (Rule R7)
# ---------------------------------------------------------------------------


class TestBearParseHeaderDate:
    """Unit tests for ``_parse_bear_header_date``.

    Method names locked by module docstring citations:
      TestBearParseHeaderDate::test_archery_banner_parsed
      TestBearParseHeaderDate::test_rifle_banner_no_date
    """

    def test_archery_banner_parsed(self) -> None:
        """Rule R7: archery banner 'Season dates: Sept. 2–30 — Sex: Either' parses correctly."""
        w = _parse_bear_header_date("Season dates: Sept. 2–30 — Sex: Either")
        assert w is not None
        assert w["start_date"] == "Sept. 2"
        assert w["end_date"] == "Sept. 30"
        # raw_text is the full heading per ADR-008
        assert w["raw_text"] == "Season dates: Sept. 2–30 — Sex: Either"

    def test_muzzleloader_banner_parsed(self) -> None:
        """Rule R7: muzzleloader banner 'Season dates: Sept. 12–20 — Sex: Either' parses."""
        w = _parse_bear_header_date("Season dates: Sept. 12–20 — Sex: Either")
        assert w is not None
        assert w["start_date"] == "Sept. 12"
        assert w["end_date"] == "Sept. 20"

    def test_rifle_banner_no_date(self) -> None:
        """Rule R7: rifle banner 'Season Dates: See hunt code table below' has no parseable date → None."""
        assert _parse_bear_header_date("Season Dates: See hunt code table below. — Sex: Either") is None

    def test_no_date_heading_returns_none(self) -> None:
        """A heading without 'Season dates:' → None."""
        assert _parse_bear_header_date("Archery — Limited Licenses") is None

    def test_cross_month_banner(self) -> None:
        """A banner with a cross-month range parses both start and end months."""
        w = _parse_bear_header_date("Season dates: Oct. 24–Nov. 1 — Sex: Either")
        assert w is not None
        assert w["start_date"] == "Oct. 24"
        assert w["end_date"] == "Nov. 1"

    def test_case_insensitive(self) -> None:
        """'Season Dates:' (capital D) is matched case-insensitively."""
        w = _parse_bear_header_date("Season Dates: Sept. 2–30 — Sex: Either")
        assert w is not None
        assert w["start_date"] == "Sept. 2"


# ---------------------------------------------------------------------------
# 10. TestBearSeasonWindow  (Rule R7 — per-row Dates cell)
# ---------------------------------------------------------------------------


class TestBearSeasonWindow:
    """Unit tests for ``_parse_bear_season_window``."""

    def test_same_month_range(self) -> None:
        """'Sept. 2–30' parses start='Sept. 2', end='Sept. 30'."""
        w = _parse_bear_season_window("Sept. 2–30")
        assert w is not None
        assert w["start_date"] == "Sept. 2"
        assert w["end_date"] == "Sept. 30"
        assert w["raw_text"] == "Sept. 2–30"

    def test_cross_month_range(self) -> None:
        """'Oct. 24–Nov. 1' parses start and end with month tokens."""
        w = _parse_bear_season_window("Oct. 24–Nov. 1")
        assert w is not None
        assert w["start_date"] == "Oct. 24"
        assert w["end_date"] == "Nov. 1"

    def test_none_input_returns_none(self) -> None:
        """None input → None (R2)."""
        assert _parse_bear_season_window(None) is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string → None (R2)."""
        assert _parse_bear_season_window("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Whitespace-only → None (R2)."""
        assert _parse_bear_season_window("   ") is None

    def test_unparseable_preserves_raw_text(self) -> None:
        """OCR artifact: raw_text preserved, dates None."""
        w = _parse_bear_season_window("NNoovv..1188--2222")
        assert w is not None
        assert w["start_date"] is None
        assert w["end_date"] is None
        assert w["raw_text"] == "NNoovv..1188--2222"

    def test_leading_bullet_stripped(self) -> None:
        """Leading ■ bullet stripped before parsing; raw_text stays verbatim."""
        w = _parse_bear_season_window("■Oct. 14–18")
        assert w is not None
        assert w["start_date"] == "Oct. 14"
        assert w["end_date"] == "Oct. 18"
        assert w["raw_text"] == "■Oct. 14–18"


# ---------------------------------------------------------------------------
# 11. TestBearClassifyTableVariant
# ---------------------------------------------------------------------------


class TestBearClassifyTableVariant:
    """Unit tests for ``_bear_classify_table_variant``."""

    def test_8col_dual_archery_muzzleloader(self) -> None:
        assert _bear_classify_table_variant(8) == "bear_8col"

    def test_10col_dual_rifle(self) -> None:
        assert _bear_classify_table_variant(10) == "bear_10col"

    def test_4col_single_limited(self) -> None:
        assert _bear_classify_table_variant(4) == "bear_4col"

    def test_5col_single_rifle(self) -> None:
        assert _bear_classify_table_variant(5) == "bear_5col"

    def test_6col_dual_otc_addon(self) -> None:
        assert _bear_classify_table_variant(6) == "bear_6col"

    def test_3col_single_otc(self) -> None:
        assert _bear_classify_table_variant(3) == "bear_3col"

    def test_unknown_column_count(self) -> None:
        """An unrecognised column count returns 'unknown' — caller logs WARNING and skips."""
        assert _bear_classify_table_variant(7) == "unknown"
        assert _bear_classify_table_variant(1) == "unknown"
        assert _bear_classify_table_variant(99) == "unknown"


# ---------------------------------------------------------------------------
# 12. TestBearConfidenceAssignment  (Rule R15)
# ---------------------------------------------------------------------------


class TestBearConfidenceAssignment:
    """Unit tests for ``_assign_bear_row_confidence`` — ADR-017 bear adaptation.

    Method names locked by module docstring citations:
      TestBearConfidenceAssignment::test_high_confidence_row
      TestBearConfidenceAssignment::test_medium_no_window
      TestBearConfidenceAssignment::test_low_unparsed_hunt_code
    """

    def test_high_confidence_row(self) -> None:
        """HIGH: parsed hunt code + list_value present + resolved window."""
        row = _make_bear_row(
            species_letter="B",
            list_value="A",
            season_windows=[
                CpwSeasonWindow(
                    start_date="Sept. 2", end_date="Sept. 30", raw_text="Sept. 2–30"
                )
            ],
        )
        assert _assign_bear_row_confidence(row) == ConfidenceTier.HIGH

    def test_high_with_otc_list_value(self) -> None:
        """HIGH: 'OTC' is a valid list_value."""
        row = _make_bear_row(species_letter="B", list_value="OTC")
        assert _assign_bear_row_confidence(row) == ConfidenceTier.HIGH

    def test_high_list_b(self) -> None:
        """HIGH: list_value='B' satisfies the list_value non-None condition."""
        row = _make_bear_row(species_letter="B", list_value="B")
        assert _assign_bear_row_confidence(row) == ConfidenceTier.HIGH

    def test_medium_no_window(self) -> None:
        """MEDIUM: parsed hunt code + list_value but empty season_windows."""
        row = _make_bear_row(species_letter="B", list_value="A", season_windows=[])
        assert _assign_bear_row_confidence(row) == ConfidenceTier.MEDIUM

    def test_medium_no_list_value(self) -> None:
        """MEDIUM: parsed hunt code but list_value is None."""
        row = _make_bear_row(species_letter="B", list_value=None)
        assert _assign_bear_row_confidence(row) == ConfidenceTier.MEDIUM

    def test_medium_unresolved_window(self) -> None:
        """MEDIUM: parsed hunt code + list_value but window has no resolved dates."""
        row = _make_bear_row(
            species_letter="B",
            list_value="A",
            season_windows=[
                CpwSeasonWindow(start_date=None, end_date=None, raw_text="NNoovv..")
            ],
        )
        assert _assign_bear_row_confidence(row) == ConfidenceTier.MEDIUM

    def test_low_unparsed_hunt_code(self) -> None:
        """LOW: species_letter == '' means hunt code did not parse."""
        row = _make_bear_row(hunt_code="GARBLED", species_letter="")
        assert _assign_bear_row_confidence(row) == ConfidenceTier.LOW


# ---------------------------------------------------------------------------
# 13. TestExtractCorrection (inert-confirmation pathway)
# ---------------------------------------------------------------------------


class TestExtractCorrection:
    """Tests for the inert-confirmation pathway of the correction PDF.

    The CO 2026 correction PDF is moose + elk only — ``operations == []``.
    Since the test environment has no real PDF, we verify the guard surfaces
    by inspecting the committed ``corrections-2026-02-19.json`` artifact.
    """

    @staticmethod
    def _load_corrections() -> list[dict]:  # type: ignore[type-arg]
        p = extract_black_bear._CORRECTIONS_OUTPUT_PATH
        if not p.exists():
            pytest.skip(
                "corrections-2026-02-19.json not generated — run extract_black_bear.py first"
            )
        with open(p) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_corrections_artifact_is_empty_list(self) -> None:
        """The inert-confirmation artifact contains exactly [] (no bear operations)."""
        ops = self._load_corrections()
        assert ops == [], (
            f"Expected [] from corrections-2026-02-19.json (inert for bear); "
            f"got {len(ops)} operation(s): {ops[:3]}"
        )

    def test_corrections_artifact_is_a_list(self) -> None:
        """corrections-2026-02-19.json is always a JSON list (not null or dict)."""
        ops = self._load_corrections()
        assert isinstance(ops, list), (
            f"Expected list from corrections-2026-02-19.json; got {type(ops)}"
        )


# ---------------------------------------------------------------------------
# 14. TestMergeWithCorrections
# ---------------------------------------------------------------------------


class TestMergeWithCorrections:
    """Unit tests for ``_merge_with_corrections``.

    Tests the three-stage arbitration logic directly with synthetic inputs —
    no real PDF required.
    """

    def _make_base_record(
        self,
        hunt_code: str = "B-E-050-O1-A",
        list_value: str | None = "A",
    ) -> dict:  # type: ignore[type-arg]
        """Build a minimal base 'section' record dict."""
        typed_row = _make_bear_row(hunt_code=hunt_code, list_value=list_value, species_letter="B")
        section: dict[str, object] = dict(_make_section(rows=[typed_row]))  # type: ignore[arg-type]
        # Convert section rows to mutable dicts so _merge_with_corrections can update them.
        row_dict: dict[str, object] = dict(typed_row)
        row_dict["extraction_confidence"] = "high"
        section["rows"] = [row_dict]
        section["record_type"] = "section"
        return section

    def test_inert_correction_produces_zero_applied_correction_rows(self) -> None:
        """Empty operations list: every section row has applied_correction=False."""
        base = [self._make_base_record()]
        merged = _merge_with_corrections(base, [], "co-cpw-big-game-2026-brochure")
        for record in merged:
            if record.get("record_type") == "section":
                for row in record.get("rows", []):
                    assert row["applied_correction"] is False, (
                        f"Expected applied_correction=False for inert correction; got True: {row}"
                    )

    def test_inert_correction_all_supersedes_none(self) -> None:
        """Empty operations list: every section row has supersedes=None."""
        base = [self._make_base_record()]
        merged = _merge_with_corrections(base, [], "co-cpw-big-game-2026-brochure")
        for record in merged:
            if record.get("record_type") == "section":
                for row in record.get("rows", []):
                    assert row["supersedes"] is None

    def test_applied_correction_sets_true_on_touched_row(self) -> None:
        """A correction op on a real row sets applied_correction=True."""
        base = [self._make_base_record("B-E-050-O1-A", "A")]
        op = _make_correction_op(
            target_license_code="B-E-050-O1-A",
            target_field="list_value",
            new_value="B",
        )
        merged = _merge_with_corrections(base, [op], "co-cpw-big-game-2026-brochure")
        touched = [
            row
            for record in merged
            if record.get("record_type") == "section"
            for row in record.get("rows", [])
            if row.get("hunt_code") == "B-E-050-O1-A"
        ]
        assert touched, "No row found for B-E-050-O1-A"
        assert touched[0]["applied_correction"] is True
        assert touched[0]["list_value"] == "B"

    def test_demote_fires_exactly_once_per_touched_row(self) -> None:
        """Two correction ops on one row → confidence demoted exactly once (ADR-017 §4).

        If demote fired N times the result would be LOW for N=2 starting from HIGH.
        Firing exactly once from HIGH → MEDIUM.
        """
        base = [self._make_base_record("B-E-050-O1-A", "A")]
        # Set row confidence to HIGH before merge.
        for record in base:
            for row in record.get("rows", []):
                row["extraction_confidence"] = "high"

        op1 = _make_correction_op(
            target_license_code="B-E-050-O1-A",
            target_field="list_value",
            new_value="B",
        )
        op2 = _make_correction_op(
            target_license_code="B-E-050-O1-A",
            target_field="unit",
            old_value="50",
            new_value="51",
        )
        merged = _merge_with_corrections(
            base, [op1, op2], "co-cpw-big-game-2026-brochure"
        )
        touched = [
            row
            for record in merged
            if record.get("record_type") == "section"
            for row in record.get("rows", [])
            if row.get("hunt_code") == "B-E-050-O1-A"
        ]
        assert touched, "No row found after merge"
        # HIGH → MEDIUM (exactly one demotion)
        assert touched[0]["extraction_confidence"] == "medium", (
            f"Expected exactly one demotion HIGH→MEDIUM; got {touched[0]['extraction_confidence']}"
        )

    def test_supersedes_set_on_touched_row(self) -> None:
        """A correction op sets supersedes to the brochure source id."""
        base = [self._make_base_record("B-E-050-O1-A")]
        op = _make_correction_op("B-E-050-O1-A")
        merged = _merge_with_corrections(base, [op], "co-cpw-big-game-2026-brochure")
        touched = [
            row
            for record in merged
            if record.get("record_type") == "section"
            for row in record.get("rows", [])
            if row.get("hunt_code") == "B-E-050-O1-A"
        ]
        assert touched[0]["supersedes"] == "co-cpw-big-game-2026-brochure"

    def test_equal_date_tie_raises_conflict_error(self) -> None:
        """Two ops targeting same (license_code, field) with equal dates → CorrectionConflictError."""
        base = [self._make_base_record("B-E-050-O1-A")]
        op1 = CorrectionOperation(
            target_license_code="B-E-050-O1-A",
            target_field="list_value",
            old_value="A",
            new_value="B",
            source_id="source-one",
            publication_date="2026-02-19",
        )
        op2 = CorrectionOperation(
            target_license_code="B-E-050-O1-A",
            target_field="list_value",
            old_value="A",
            new_value="C",
            source_id="source-two",
            publication_date="2026-02-19",
        )
        with pytest.raises(CorrectionConflictError):
            _merge_with_corrections(base, [op1, op2], "co-cpw-big-game-2026-brochure")

    def test_unknown_field_op_raises_pdf_extraction_error(self) -> None:
        """A correction op targeting a field not in _CORRECTABLE_FIELDS raises PdfExtractionError."""
        base = [self._make_base_record("B-E-050-O1-A")]
        op = CorrectionOperation(
            target_license_code="B-E-050-O1-A",
            target_field="nonexistent_field",
            old_value=None,
            new_value="whatever",
            source_id="co-cpw-big-game-2026-correction-2026-02-19",
            publication_date="2026-02-19",
        )
        with pytest.raises(PdfExtractionError):
            _merge_with_corrections(base, [op], "co-cpw-big-game-2026-brochure")

    def test_non_section_records_passed_through_unchanged(self) -> None:
        """reporting_obligation and statewide_rule records are not modified."""
        non_section = {
            "record_type": "reporting_obligation",
            "region_scope": "STATEWIDE",
            "verbatim_rule": "Hunters must present their bear…",
        }
        base = [non_section, self._make_base_record()]
        merged = _merge_with_corrections(base, [], "co-cpw-big-game-2026-brochure")
        assert merged[0]["record_type"] == "reporting_obligation"
        assert "applied_correction" not in merged[0]

    def test_base_records_not_mutated(self) -> None:
        """_merge_with_corrections deep-copies — original base_records unmodified."""
        base = [self._make_base_record("B-E-050-O1-A")]
        op = _make_correction_op("B-E-050-O1-A")
        _merge_with_corrections(base, [op], "co-cpw-big-game-2026-brochure")
        # The original row dict should not have applied_correction
        assert "applied_correction" not in base[0]["rows"][0]


# ---------------------------------------------------------------------------
# 15. TestDocumentTypeGuard  (ADR-019 §Decision item 5)
# ---------------------------------------------------------------------------


class TestDocumentTypeGuard:
    """Tests for the _VALID_DOCUMENT_TYPES allow-list guard."""

    def test_valid_document_types_are_correct(self) -> None:
        """_VALID_DOCUMENT_TYPES contains exactly 'annual_regulations' and 'correction'."""
        assert _VALID_DOCUMENT_TYPES == frozenset({"annual_regulations", "correction"})

    def test_correctable_fields_nonempty(self) -> None:
        """_CORRECTABLE_FIELDS is non-empty and contains expected bear-row fields."""
        assert len(_CORRECTABLE_FIELDS) > 0
        assert "hunt_code" in _CORRECTABLE_FIELDS
        assert "list_value" in _CORRECTABLE_FIELDS
        assert "unit" in _CORRECTABLE_FIELDS

    def test_correctable_fields_excludes_readonly(self) -> None:
        """_CORRECTABLE_FIELDS does not include non-updatable row fields."""
        assert "extraction_confidence" not in _CORRECTABLE_FIELDS
        assert "page_reference" not in _CORRECTABLE_FIELDS
        assert "season_windows" not in _CORRECTABLE_FIELDS


# ---------------------------------------------------------------------------
# 16. TestArtifactStructureInvariants
# ---------------------------------------------------------------------------


class TestArtifactStructureInvariants:
    """Pin the committed black-bear-2026.json artifact to known-good structural stats.

    Loads the committed artifact directly (no live PDF required).
    """

    @staticmethod
    def _load() -> list[dict]:  # type: ignore[type-arg]
        p = extract_black_bear._MERGED_OUTPUT_PATH
        if not p.exists():
            pytest.skip(
                "black-bear-2026.json not generated — run extract_black_bear.py first"
            )
        with open(p) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_record_type_present_on_every_record(self) -> None:
        """Every record in the artifact carries a 'record_type' discriminator key."""
        data = self._load()
        missing = [i for i, r in enumerate(data) if "record_type" not in r]
        assert not missing, f"records missing 'record_type' at indices: {missing}"

    def test_record_type_values_are_expected(self) -> None:
        """Only the three expected record_type values appear."""
        data = self._load()
        types = {r["record_type"] for r in data}
        assert types <= {"section", "reporting_obligation", "statewide_rule"}, (
            f"Unexpected record_type values: {types - {'section', 'reporting_obligation', 'statewide_rule'}}"
        )

    def test_record_counts_pinned(self) -> None:
        """Artifact: 173 records = 170 section + 1 reporting_obligation + 2 statewide_rule.

        Section count rose 169→170 because Rule R17 (fused-row split) now produces
        two sections for the previously fused GMU 058+059 muzzleloader row on p. 74.
        """
        from collections import Counter

        data = self._load()
        assert len(data) == 173, f"Expected 173 records; got {len(data)}"
        ct = Counter(r["record_type"] for r in data)
        assert ct["section"] == 170, f"Expected 170 section records; got {ct['section']}"
        assert ct["reporting_obligation"] == 1
        assert ct["statewide_rule"] == 2

    def test_total_row_count_pinned(self) -> None:
        """All section rows total 215.

        Change from 214:
          +1  Rule R17 fused-row split: B-E-058-O1-M + B-E-059-O1-M are now
              two separate rows (previously only B-E-058-O1-M was kept)
          = 215 net
        """
        data = self._load()
        total = sum(len(r.get("rows", [])) for r in data if r["record_type"] == "section")
        assert total == 215, f"Expected 215 rows total; got {total}"

    def test_confidence_distribution_pinned(self) -> None:
        """Confidence distribution: high=215, medium=0, low=0.

        All rows are HIGH confidence:
          - Plains OTC B-E-087-U6-R recovered via Rule R16 → HIGH
          - 3 former LOW empty noise rows eliminated by garbage-row guard
          - Rule R17 new B-E-059-O1-M row is HIGH (parsed code + list + window)
        """
        from collections import Counter

        data = self._load()
        dist = Counter(
            row["extraction_confidence"]
            for r in data
            if r["record_type"] == "section"
            for row in r.get("rows", [])
        )
        assert dict(dist) == {"high": 215}, (
            f"Confidence distribution mismatch: {dict(dist)}"
        )

    def test_license_kind_distribution_pinned(self) -> None:
        """License-kind breakdown: limited_draw=138, add_on_otc=29, over_the_counter=10,
        private_land_otc=37, plains_otc=1.

        limited_draw rose 137→138: Rule R17 fused-row split produces one extra
        B-E-059-O1-M muzzleloader limited_draw row.
        """
        from collections import Counter

        data = self._load()
        dist = Counter(
            row["license_kind"]
            for r in data
            if r["record_type"] == "section"
            for row in r.get("rows", [])
        )
        assert dist["limited_draw"] == 138
        assert dist["add_on_otc"] == 29
        assert dist["over_the_counter"] == 10
        assert dist["private_land_otc"] == 37
        assert dist["plains_otc"] == 1

    def test_all_section_rows_have_applied_correction(self) -> None:
        """Every section row carries the 'applied_correction' field (Pass-3 field)."""
        data = self._load()
        missing = [
            (r["gmu_code"], row.get("hunt_code", "?"))
            for r in data
            if r["record_type"] == "section"
            for row in r.get("rows", [])
            if "applied_correction" not in row
        ]
        assert not missing, f"Rows missing 'applied_correction': {missing[:5]}"

    def test_no_applied_correction_true_rows_inert_case(self) -> None:
        """Inert correction: zero rows have applied_correction=True."""
        data = self._load()
        touched = [
            (r["gmu_code"], row.get("hunt_code", "?"))
            for r in data
            if r["record_type"] == "section"
            for row in r.get("rows", [])
            if row.get("applied_correction") is True
        ]
        assert not touched, (
            f"Expected 0 rows with applied_correction=True for inert CO 2026 correction; "
            f"found {len(touched)}: {touched[:5]}"
        )

    def test_all_section_rows_have_species_group_black_bear(self) -> None:
        """Every section carries species_group='black_bear' (not 'bear')."""
        data = self._load()
        bad = [
            r.get("gmu_code")
            for r in data
            if r["record_type"] == "section" and r.get("species_group") != "black_bear"
        ]
        assert not bad, f"Section(s) with wrong species_group: {bad[:5]}"

    def test_reporting_obligation_has_mandatory_inspection(self) -> None:
        """The reporting_obligation record has kind_hint='mandatory_inspection'."""
        data = self._load()
        obs = [r for r in data if r["record_type"] == "reporting_obligation"]
        assert len(obs) == 1
        assert obs[0]["kind_hint"] == "mandatory_inspection"
        assert obs[0]["region_scope"] == "STATEWIDE"

    def test_statewide_rule_hints_present(self) -> None:
        """The two statewide_rule records have the expected rule_hint values."""
        data = self._load()
        hints = {r["rule_hint"] for r in data if r["record_type"] == "statewide_rule"}
        assert hints == {"season_dates_summary", "list_abc_explanation"}, (
            f"Expected both statewide rule hints; got {hints}"
        )

    def test_confidence_values_are_plain_strings(self) -> None:
        """extraction_confidence values are plain strings, not enum repr."""
        data = self._load()
        valid = {"high", "medium", "low"}
        bad: list[str] = []
        for r in data:
            if r["record_type"] != "section":
                continue
            for row in r.get("rows", []):
                val = row.get("extraction_confidence", "")
                if val not in valid:
                    bad.append(repr(val))
        assert not bad, (
            f"Found {len(bad)} row(s) with non-plain extraction_confidence: {bad[:5]}"
        )


# ---------------------------------------------------------------------------
# 17. TestBearOtcExtraction  (Rule R13 invariant check on artifact)
# ---------------------------------------------------------------------------


class TestBearOtcExtraction:
    """Artifact-level lock for Rule R13: Rifle OTC multi-window consolidation.

    Method name locked by module docstring citation:
      TestBearOtcExtraction::test_rifle_otc_multi_window_consolidated
    """

    @staticmethod
    def _load() -> list[dict]:  # type: ignore[type-arg]
        p = extract_black_bear._MERGED_OUTPUT_PATH
        if not p.exists():
            pytest.skip(
                "black-bear-2026.json not generated — run extract_black_bear.py first"
            )
        with open(p) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_rifle_otc_multi_window_consolidated(self) -> None:
        """Rule R13: at least one OTC rifle row has multiple season_windows consolidated.

        pdfplumber delivers each date period as a separate row; Rule R13 accumulates
        them all onto the primary hunt-code row.  Any OTC rifle row with >1 window
        proves consolidation ran correctly.
        """
        data = self._load()
        otc_rifle_rows = [
            row
            for r in data
            if r["record_type"] == "section"
            and r.get("method_group") == "rifle"
            and r.get("license_kind") in ("over_the_counter", "private_land_otc", "plains_otc")
            for row in r.get("rows", [])
        ]
        assert otc_rifle_rows, "No OTC rifle rows found in artifact"
        multi_window = [r for r in otc_rifle_rows if len(r.get("season_windows", [])) > 1]
        assert multi_window, (
            "Rule R13 lock: expected at least one OTC rifle row with multiple "
            "season_windows consolidated; found none."
        )


# ---------------------------------------------------------------------------
# 18a. TestOtcHeadingFailLoud  (Fix 2 — unrecognized OTC heading raises)
# ---------------------------------------------------------------------------


class TestOtcHeadingFailLoud:
    """Fail-loud guard for _otc_classify_heading: an unrecognized OTC heading
    must raise PdfExtractionError rather than silently defaulting to 'rifle'.

    ADR-001: a new CPW heading format must surface at extraction time.
    """

    def test_unrecognized_heading_raises(self) -> None:
        """A fabricated OTC heading that matches none of the known patterns raises
        PdfExtractionError naming the offending heading text."""
        from states.colorado.extract_black_bear import _otc_classify_heading

        fabricated = "Crossbow — Alien License Only — Season dates: Nov. 1–5"
        with pytest.raises(PdfExtractionError, match="unrecognized OTC heading"):
            _otc_classify_heading(fabricated)

    def test_unrecognized_heading_message_includes_text(self) -> None:
        """The PdfExtractionError message includes the offending heading verbatim."""
        from states.colorado.extract_black_bear import _otc_classify_heading

        fabricated = "Spear Hunting OTC — Season dates: Oct. 1–7"
        with pytest.raises(PdfExtractionError, match=re.escape(fabricated)):
            _otc_classify_heading(fabricated)


# ---------------------------------------------------------------------------
# 18b. TestProseCanidateFailLoud  (Fix 3 — empty prose candidates raise)
# ---------------------------------------------------------------------------


class TestProseCandidateFailLoud:
    """Fail-loud guards in _build_base_records: empty reporting-obligation or
    statewide-rule candidate sets must raise PdfExtractionError.

    These guards fire only when the page-anchoring regexes produce no results.
    The current artifact has 1 reporting_obligation and 2 statewide_rule
    candidates so the guards do NOT fire on current data.
    """

    def test_empty_inspection_candidate_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If _extract_mandatory_inspection_candidate returns None, PdfExtractionError
        is raised naming the reporting-obligation candidate set as empty."""
        import states.colorado.extract_black_bear as mod

        monkeypatch.setattr(mod, "_extract_mandatory_inspection_candidate", lambda *a, **kw: None)
        monkeypatch.setattr(mod, "_extract_statewide_rule_candidates", lambda *a, **kw: [object()])
        monkeypatch.setattr(mod, "_extract_limited_rows", lambda *a, **kw: [])
        monkeypatch.setattr(mod, "_extract_otc_rows", lambda *a, **kw: [])
        monkeypatch.setattr(mod, "_assemble_bear_sections", lambda *a, **kw: [])

        fake_pdf = object()
        with pytest.raises(PdfExtractionError, match="reporting-obligation candidate set is empty"):
            mod._build_base_records(fake_pdf, "2026-01-01T00:00:00Z", "src-id", "2026-01-01")

    def test_empty_statewide_candidates_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If _extract_statewide_rule_candidates returns [], PdfExtractionError
        is raised naming the statewide-rule candidate set as empty."""
        import states.colorado.extract_black_bear as mod

        sentinel = object()  # non-None so inspection guard passes
        monkeypatch.setattr(mod, "_extract_mandatory_inspection_candidate", lambda *a, **kw: sentinel)
        monkeypatch.setattr(mod, "_extract_statewide_rule_candidates", lambda *a, **kw: [])
        monkeypatch.setattr(mod, "_extract_limited_rows", lambda *a, **kw: [])
        monkeypatch.setattr(mod, "_extract_otc_rows", lambda *a, **kw: [])
        monkeypatch.setattr(mod, "_assemble_bear_sections", lambda *a, **kw: [])

        fake_pdf = object()
        with pytest.raises(PdfExtractionError, match="statewide-rule candidate set is empty"):
            mod._build_base_records(fake_pdf, "2026-01-01T00:00:00Z", "src-id", "2026-01-01")


# ---------------------------------------------------------------------------
# 18. TestBearSectionAssembly  (Rule R14 — OTC prerequisite note)
# ---------------------------------------------------------------------------


class TestBearSectionAssembly:
    """Artifact-level lock for Rule R14: Add-On OTC prerequisite note captured.

    Method name locked by module docstring citation:
      TestBearSectionAssembly::test_add_on_otc_note_captured
    """

    @staticmethod
    def _load() -> list[dict]:  # type: ignore[type-arg]
        p = extract_black_bear._MERGED_OUTPUT_PATH
        if not p.exists():
            pytest.skip(
                "black-bear-2026.json not generated — run extract_black_bear.py first"
            )
        with open(p) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_add_on_otc_note_captured(self) -> None:
        """Rule R14: at least one add_on_otc section carries a non-None 'notes' field.

        The Add-On OTC banner rows carry prerequisite text ("You must hold an
        archery deer or elk license…") stored in the section-level 'notes' field.
        """
        data = self._load()
        addon_sections = [
            r for r in data
            if r.get("record_type") == "section" and r.get("license_kind") == "add_on_otc"
        ]
        assert addon_sections, "No add_on_otc sections found in artifact"
        has_note = [s for s in addon_sections if s.get("notes") is not None]
        assert has_note, (
            "Rule R14 lock: expected at least one add_on_otc section with a "
            "non-None 'notes' field; found none."
        )


# ---------------------------------------------------------------------------
# 19. TestBearExtractBlockRow  (Rule R9 — single-code multiline hunt code)
# ---------------------------------------------------------------------------


class TestBearExtractBlockRow:
    """Tests for hunt-code cell handling in _extract_bear_block_row.

    Method name locked by module docstring citation:
      TestBearExtractBlockRow::test_single_code_multiline_uses_first
    """

    def test_single_code_multiline_uses_first(self) -> None:
        """Rule R9: single-code multi-line cell uses first non-empty line.

        When the Hunt Code cell has a newline but only ONE full hunt code
        (e.g. a trailing newline or wrapped text), _extract_bear_block_row
        takes the first non-empty line and discards the rest.

        This is distinct from Rule R17 (two+ full codes → split into two rows).
        Here the cell has one code followed by empty/whitespace.
        """
        from states.colorado.extract_black_bear import _extract_bear_block_row, _BEAR_NO_COL

        # Simulate a 4-col single block: (unit=0, valid_gmus=1, dates=-1, hunt_code=2, list=3)
        block = (0, 1, _BEAR_NO_COL, 2, 3)
        # Single code with a trailing newline (not a fused row — only 1 full code)
        row: list[str | None] = ["58", "58, 581", "B-E-058-O1-M\n", "A"]

        header_window = CpwSeasonWindow(
            start_date="Sept. 12", end_date="Sept. 20", raw_text="Sept. 12–20"
        )
        result = _extract_bear_block_row(
            row,
            block,
            header_window,
            method_group="muzzleloader",
            residency_scope="both",
            page_ref=_make_page_ref(74),
        )
        assert result is not None
        assert result["hunt_code"] == "B-E-058-O1-M"
        assert result["gmu_code"] == "058"


# ---------------------------------------------------------------------------
# 20. TestBearEmbeddedHuntCode  (Rule R16 — embedded hunt code in prose)
# ---------------------------------------------------------------------------


class TestBearEmbeddedHuntCode:
    """Tests for Rule R16: hunt-code embedded in prose — unanchored search fallback.

    Method names locked by module docstring citations:
      TestBearEmbeddedHuntCode::test_plains_otc_code_recovered
      TestBearEmbeddedHuntCode::test_prose_prefix_in_extras
    """

    @staticmethod
    def _load() -> list[dict]:  # type: ignore[type-arg]
        p = extract_black_bear._MERGED_OUTPUT_PATH
        if not p.exists():
            pytest.skip(
                "black-bear-2026.json not generated — run extract_black_bear.py first"
            )
        with open(p) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_plains_otc_code_recovered(self) -> None:
        """Rule R16: the Plains OTC section contains exactly one row with
        hunt_code='B-E-087-U6-R', gmu_code='087', list_value='C', confidence HIGH.

        The brochure cell reads 'Sales agents only: B-E-087-U6-R'.  The anchored
        _HUNT_CODE_RE fails on the prose prefix; Rule R16's unanchored search
        recovers the embedded code.  Prior to this fix the row was dropped
        (collapsed to low-confidence empty) — a real license silently missing.
        """
        data = self._load()
        plains_rows = [
            row
            for r in data
            if r.get("record_type") == "section" and r.get("license_kind") == "plains_otc"
            for row in r.get("rows", [])
        ]
        assert len(plains_rows) == 1, (
            f"Expected exactly 1 plains_otc row; got {len(plains_rows)}"
        )
        row = plains_rows[0]
        assert row["hunt_code"] == "B-E-087-U6-R", (
            f"Expected hunt_code='B-E-087-U6-R'; got {row['hunt_code']!r}"
        )
        assert row["gmu_code"] == "087", (
            f"Expected gmu_code='087'; got {row['gmu_code']!r}"
        )
        assert row["list_value"] == "C", (
            f"Expected list_value='C'; got {row['list_value']!r}"
        )
        assert row["extraction_confidence"] == "high", (
            f"Rule R16 recovered row must be HIGH confidence; got {row['extraction_confidence']!r}"
        )

    def test_prose_prefix_in_extras(self) -> None:
        """Rule R16: the prose prefix 'Sales agents only' is stored verbatim in extras.

        ADR-008: no prose is discarded.  The cell text surrounding the embedded code
        is captured into the row's extras field so downstream S06.7 can surface it
        to the operator / license-tag extras field.
        """
        data = self._load()
        plains_rows = [
            row
            for r in data
            if r.get("record_type") == "section" and r.get("license_kind") == "plains_otc"
            for row in r.get("rows", [])
        ]
        assert plains_rows, "No plains_otc rows found — run extract_black_bear.py first"
        row = plains_rows[0]
        extras = row.get("extras")
        assert extras is not None, (
            "Rule R16: extras must be non-None for the prose-prefixed Plains OTC row"
        )
        assert "Sales agents only" in extras, (
            f"Rule R16: expected 'Sales agents only' in extras; got {extras!r}"
        )

    def test_no_low_confidence_rows_in_artifact(self) -> None:
        """After Defect 1 + Defect 2 fixes: zero LOW-confidence rows remain.

        - Plains OTC row recovered (Rule R16) → HIGH.
        - 3 empty add_on_otc noise rows dropped by garbage-row guard.
        """
        data = self._load()
        low_rows = [
            (r.get("gmu_code"), row.get("hunt_code", "?"))
            for r in data
            if r["record_type"] == "section"
            for row in r.get("rows", [])
            if row.get("extraction_confidence") == "low"
        ]
        assert not low_rows, (
            f"Expected 0 LOW-confidence rows after defect fixes; "
            f"got {len(low_rows)}: {low_rows[:5]}"
        )

    def test_no_empty_verbatim_rows_in_artifact(self) -> None:
        """After Defect 2 fix: zero rows with empty hunt_code remain in any section.

        The 3 page-76 banner/legend spill rows that previously produced empty
        add_on_otc rows are now dropped by the garbage-row guard before assembly.
        """
        data = self._load()
        empty_code_rows = [
            (r.get("gmu_code"), r.get("license_kind"))
            for r in data
            if r["record_type"] == "section"
            for row in r.get("rows", [])
            if not row.get("hunt_code", "x").strip()
        ]
        assert not empty_code_rows, (
            f"Expected 0 rows with empty hunt_code; "
            f"got {len(empty_code_rows)}: {empty_code_rows[:5]}"
        )


# ---------------------------------------------------------------------------
# 21. TestExtractCorrectionFailLoud
# ---------------------------------------------------------------------------


class TestExtractCorrectionFailLoud:
    """Tests for the fail-loud guard in _extract_correction when bear codes appear.

    Rule: if the correction PDF ever yields a B-… bear hunt code, _extract_correction
    raises PdfExtractionError naming the offending code + page (ADR-001 fail-loud,
    not silent sentinel).

    These tests use the committed corrections artifact (which is []) to verify
    the inert-confirmation path, and verify the fail-loud guard is present in
    the source code.
    """

    def test_bear_correction_guard_present_in_source(self) -> None:
        """The fail-loud guard text is present in extract_black_bear.py source.

        Structural guard: the old silent-sentinel TODO was replaced with a
        PdfExtractionError raise.  This test confirms the guard is present so
        a future refactor cannot accidentally reintroduce the silent sentinel.
        """
        source_path = Path(extract_black_bear.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        assert "field-parsing is not implemented for V1 and must be added" in source, (
            "The fail-loud bear-correction guard is missing from extract_black_bear.py "
            "— the silent sentinel TODO must not be reintroduced."
        )
        # The old silent sentinel (CorrectionOperation with target_field='hunt_code'
        # as a placeholder) must not be present.
        assert "placeholder for real parse" not in source, (
            "The silent-sentinel TODO comment 'placeholder for real parse' is still "
            "present — Defect 3 fix was not applied."
        )

    def test_inert_correction_artifact_is_empty(self) -> None:
        """The inert-confirmation artifact contains exactly [] (no bear operations)."""
        p = extract_black_bear._CORRECTIONS_OUTPUT_PATH
        if not p.exists():
            pytest.skip(
                "corrections-2026-02-19.json not generated — run extract_black_bear.py first"
            )
        with open(p) as f:
            ops = json.load(f)
        assert ops == [], (
            f"Expected [] from corrections-2026-02-19.json; got {ops[:3]}"
        )


# ---------------------------------------------------------------------------
# 22. TestFusedRowSplit  (Rule R17 — unit tests for _split_fused_block_row)
# ---------------------------------------------------------------------------


class TestFusedRowSplit:
    """Unit tests for ``_split_fused_block_row`` (Rule R17).

    Method names locked by module docstring citations:
      TestFusedRowSplit::test_two_code_fused_row_splits_to_two_rows
      TestFusedRowSplit::test_misaligned_cell_raises
    """

    def _make_block_no_dates(self) -> tuple[int, ...]:
        """4-col no-Dates block: (unit=0, valid_gmus=1, dates=-1, hunt_code=2, list=3)."""
        from states.colorado.extract_black_bear import _BEAR_NO_COL
        return (0, 1, _BEAR_NO_COL, 2, 3)

    def test_single_code_returns_unchanged(self) -> None:
        """A cell with only one full hunt code → [row] unchanged (no split needed)."""
        from states.colorado.extract_black_bear import _split_fused_block_row
        block = self._make_block_no_dates()
        row: list[str | None] = ["58", "58, 581", "B-E-058-O1-M", "B"]
        result = _split_fused_block_row(row, block)
        assert result == [row]
        assert result[0] is row  # same object — no copy

    def test_no_hunt_code_returns_unchanged(self) -> None:
        """A cell with no full hunt code → [row] unchanged."""
        from states.colorado.extract_black_bear import _split_fused_block_row
        block = self._make_block_no_dates()
        row: list[str | None] = ["58", "58, 581", None, "B"]
        result = _split_fused_block_row(row, block)
        assert result == [row]

    def test_two_code_fused_row_splits_to_two_rows(self) -> None:
        """Rule R17: a fused cell with 2 full hunt codes → 2 synthetic rows.

        Mirrors the confirmed live PDF p. 74 muzzleloader fused row:
          ['58\\n59', '58, 581\\n59, 511, 591', 'B-E-058-O1-M\\nB-E-059-O1-M', 'B\\nB']

        After split:
          row 0: unit='58', valid_gmus='58, 581', hunt_code='B-E-058-O1-M', list='B'
          row 1: unit='59', valid_gmus='59, 511, 591', hunt_code='B-E-059-O1-M', list='B'
        """
        from states.colorado.extract_black_bear import _split_fused_block_row
        block = self._make_block_no_dates()
        fused_row: list[str | None] = [
            "58\n59",
            "58, 581\n59, 511, 591",
            "B-E-058-O1-M\nB-E-059-O1-M",
            "B\nB",
        ]
        result = _split_fused_block_row(fused_row, block)
        assert len(result) == 2, f"Expected 2 rows; got {len(result)}"
        # Row 0
        assert result[0][0] == "58"
        assert result[0][1] == "58, 581"
        assert result[0][2] == "B-E-058-O1-M"
        assert result[0][3] == "B"
        # Row 1
        assert result[1][0] == "59"
        assert result[1][1] == "59, 511, 591"
        assert result[1][2] == "B-E-059-O1-M"
        assert result[1][3] == "B"

    def test_none_block_cell_becomes_n_nones(self) -> None:
        """A None block cell in a fused row → [None, None] for each synthetic row."""
        from states.colorado.extract_black_bear import _split_fused_block_row
        # Block with dates present (5-col): (unit=0, valid_gmus=1, dates=2, hunt_code=3, list=4)
        block = (0, 1, 2, 3, 4)
        fused_row: list[str | None] = [
            "58\n59",
            "58, 581\n59, 511, 591",
            None,  # Dates column absent in this muzzleloader table
            "B-E-058-O1-M\nB-E-059-O1-M",
            "B\nB",
        ]
        result = _split_fused_block_row(fused_row, block)
        assert len(result) == 2
        # Dates column is None in both synthetic rows
        assert result[0][2] is None
        assert result[1][2] is None

    def test_misaligned_cell_raises(self) -> None:
        """Rule R17: a block cell with wrong part count raises PdfExtractionError.

        If the Hunt Code cell has 2 codes but a parallel cell only has 1 part
        (or 3 parts), the split would corrupt row alignment — must fail loud
        per ADR-001.
        """
        from states.colorado.extract_black_bear import _split_fused_block_row
        block = self._make_block_no_dates()
        # Hunt code has 2 codes but unit only has 1 part (no '\n')
        misaligned_row: list[str | None] = [
            "58",            # unit — only 1 part, but 2 codes present
            "58, 581\n59, 511, 591",
            "B-E-058-O1-M\nB-E-059-O1-M",
            "B\nB",
        ]
        with pytest.raises(PdfExtractionError, match="Cannot split without corrupting"):
            _split_fused_block_row(misaligned_row, block)

    def test_three_code_fused_row_splits_to_three_rows(self) -> None:
        """Rule R17: generalises to N>2 codes — 3 codes → 3 synthetic rows."""
        from states.colorado.extract_black_bear import _split_fused_block_row
        block = self._make_block_no_dates()
        fused_row: list[str | None] = [
            "58\n59\n60",
            "58, 581\n59, 511, 591\n60",
            "B-E-058-O1-M\nB-E-059-O1-M\nB-E-060-O1-M",
            "B\nB\nB",
        ]
        result = _split_fused_block_row(fused_row, block)
        assert len(result) == 3
        assert result[0][2] == "B-E-058-O1-M"
        assert result[1][2] == "B-E-059-O1-M"
        assert result[2][2] == "B-E-060-O1-M"

    def test_non_block_columns_preserved_unchanged(self) -> None:
        """Columns outside the block tuple are copied unchanged to all synthetic rows."""
        from states.colorado.extract_black_bear import _split_fused_block_row, _BEAR_NO_COL
        # 8-col dual block: left block is (0, 1, -1, 2, 3); right block exists at (4, 5, -1, 6, 7)
        # We test the left block only; right-block columns (4-7) must be unchanged.
        block = (0, 1, _BEAR_NO_COL, 2, 3)
        fused_row: list[str | None] = [
            "58\n59",           # col 0 — unit (in block)
            "58, 581\n59, 511", # col 1 — valid_gmus (in block)
            "B-E-058-O1-M\nB-E-059-O1-M",  # col 2 — hunt_code (in block)
            "B\nB",             # col 3 — list (in block)
            "right_unit",       # col 4 — NOT in this block; must be copied verbatim
            "right_gmus",       # col 5
            "B-E-999-O1-M",     # col 6
            "A",                # col 7
        ]
        result = _split_fused_block_row(fused_row, block)
        assert len(result) == 2
        # Right-block columns unchanged in both synthetic rows
        for srow in result:
            assert srow[4] == "right_unit"
            assert srow[5] == "right_gmus"
            assert srow[6] == "B-E-999-O1-M"
            assert srow[7] == "A"


# ---------------------------------------------------------------------------
# 23. TestFusedRowArtifactLock  (Rule R17 — artifact-level lock)
# ---------------------------------------------------------------------------


class TestFusedRowArtifactLock:
    """Artifact-level lock for Rule R17: the fused muzzleloader row on PDF p. 74
    is now split into two correct well-formed rows.

    Locked by: the committed black-bear-2026.json artifact.
    """

    @staticmethod
    def _load() -> list[dict]:  # type: ignore[type-arg]
        p = extract_black_bear._MERGED_OUTPUT_PATH
        if not p.exists():
            pytest.skip(
                "black-bear-2026.json not generated — run extract_black_bear.py first"
            )
        with open(p) as f:
            return json.load(f)  # type: ignore[no-any-return]

    def test_b_e_058_o1_m_is_separate_well_formed_row(self) -> None:
        """Rule R17: B-E-058-O1-M is a separate row with unit='58', valid_gmus='58, 581',
        list_value='B', and HIGH confidence.
        """
        data = self._load()
        rows = [
            row
            for r in data if r["record_type"] == "section"
            for row in r["rows"]
            if row["hunt_code"] == "B-E-058-O1-M" and r.get("method_group") == "muzzleloader"
        ]
        assert len(rows) == 1, (
            f"Expected exactly 1 muzzleloader row for B-E-058-O1-M; got {len(rows)}"
        )
        r = rows[0]
        assert r["unit"] == "58", f"unit: {r['unit']!r}"
        assert r["valid_gmus"] == "58, 581", f"valid_gmus: {r['valid_gmus']!r}"
        assert r["list_value"] == "B", f"list_value: {r['list_value']!r}"
        assert r["extraction_confidence"] == "high"

    def test_b_e_059_o1_m_is_separate_well_formed_row(self) -> None:
        """Rule R17: B-E-059-O1-M is now a separate row with unit='59',
        valid_gmus='59, 511, 591', list_value='B', and HIGH confidence.

        Previously this row was silently dropped by Rule R9's 'first line only'
        approach — the confirmed P1 defect.
        """
        data = self._load()
        rows = [
            row
            for r in data if r["record_type"] == "section"
            for row in r["rows"]
            if row["hunt_code"] == "B-E-059-O1-M" and r.get("method_group") == "muzzleloader"
        ]
        assert len(rows) == 1, (
            f"Expected exactly 1 muzzleloader row for B-E-059-O1-M; got {len(rows)}: "
            f"previously this row was silently dropped by old Rule R9"
        )
        r = rows[0]
        assert r["unit"] == "59", f"unit: {r['unit']!r}"
        assert r["valid_gmus"] == "59, 511, 591", f"valid_gmus: {r['valid_gmus']!r}"
        assert r["list_value"] == "B", f"list_value: {r['list_value']!r}"
        assert r["extraction_confidence"] == "high"

    def test_no_row_has_newline_in_list_value(self) -> None:
        """Rule R17: no artifact row has a newline in list_value.

        Before the fix the fused row produced list_value='B\\nB' — malformed.
        """
        data = self._load()
        bad = [
            (r.get("gmu_code"), row.get("hunt_code"), row.get("list_value"))
            for r in data if r["record_type"] == "section"
            for row in r.get("rows", [])
            if row.get("list_value") and "\n" in str(row.get("list_value", ""))
        ]
        assert not bad, (
            f"Found {len(bad)} row(s) with newline in list_value (pre-fix artifact): {bad}"
        )

    def test_no_row_has_newline_in_unit(self) -> None:
        """Rule R17: no artifact row has a newline in unit (e.g. '58\\n59')."""
        data = self._load()
        bad = [
            (r.get("gmu_code"), row.get("hunt_code"), row.get("unit"))
            for r in data if r["record_type"] == "section"
            for row in r.get("rows", [])
            if row.get("unit") and "\n" in str(row.get("unit", ""))
        ]
        assert not bad, (
            f"Found {len(bad)} row(s) with newline in unit (pre-fix artifact): {bad}"
        )


# ---------------------------------------------------------------------------
# 24. TestDeterministicJsonOutput
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
            95b98358f80197eccfd3f45003b7093f6f6f1875275c02a062c6689205c274bd  # pragma: allowlist secret
        """
        pytest.skip(
            "integration — requires real CPW Big Game PDF (~96 MB, gitignored); "
            "determinism verified by manual 2-run SHA recipe "
            "(SHA-256: 95b98358f80197eccfd3f45003b7093f6f6f1875275c02a062c6689205c274bd)"  # pragma: allowlist secret
        )
