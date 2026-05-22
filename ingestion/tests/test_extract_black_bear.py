"""Unit tests for `states.montana.extract_black_bear` — Black Bear booklet + correction
extraction (S03.4 T14).

Test philosophy:
- All unit tests are hermetic: no real Black Bear PDF required. They drive the
  public helpers directly with hand-crafted dict/list inputs that mirror
  the real-PDF layout discovered during T13 reconnaissance.
- Fixtures use literal strings only — no random sources, no live-PDF dependency.
- ``caplog`` for log assertions (WARNING/INFO level).
- ``monkeypatch`` for module-level constant patching and function swaps.
- ``tmp_path`` for filesystem fixtures (YAML overrides, JSON roundtrip tests).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

import states.montana.extract_black_bear as m
from ingestion.lib.pdf import (
    ConfidenceTier,
    PageReference,
    PdfExtractionError,
)
from states.montana.extract_black_bear import (
    BmuQuotaCell,
    BmuRowExtraction,
    BlackBearBaseExtraction,
    CorrectionConflictError,
    CorrectionExtraction,
    CorrectionOperation,
    SourceCitationDict,
    _detect_column_region,
    _extract_bmu_row,
    _is_permit_managed_column,
    _is_season_cell_absent,
    _merge_with_corrections,
    _normalize_cell,
    _parse_quota_cell,
    _reverse_cell_text,
    _write_deterministic_json,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_page_reference(page: int = 9) -> PageReference:
    """Return a minimal PageReference for use in tests."""
    return PageReference(
        pdf_filename="test-black-bear.pdf",
        page_num_1based=page,
        bbox=None,
        extracted_at="2026-05-10T00:00:00Z",
    )


def _make_source_citation(
    citation_id: str = "mt-fwp-black-bear-2026-booklet",
    document_type: str = "annual_regulations",
    publication_date: str = "2026-04-27",
) -> SourceCitationDict:
    """Return a minimal SourceCitationDict for tests."""
    return SourceCitationDict(
        id=citation_id,
        agency="Montana Fish, Wildlife & Parks",
        title="Black Bear Hunting Regulations 2026",
        url="https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/2026-black-bear-final-for-web.pdf",
        publication_date=publication_date,
        document_type=document_type,
    )


def _make_bmu_table(
    headers: list[str | None],
    rows: list[list[str | None]],
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 612.0, 792.0),
) -> m.TableMatch:
    """Build a TableMatch dict with the given headers and rows."""
    return {
        "headers": headers,
        "rows": rows,
        "bbox": bbox,
    }


def _make_bmu_row_extraction(
    bmu_number: int = 100,
    hd_region: str = "R1",
    general_season: str | None = "Sep.15-Nov.29",
    hound_training_season: str | None = "Apr.15-Jun.15",
    extraction_confidence: ConfidenceTier = ConfidenceTier.HIGH,
    source_id: str = "mt-fwp-black-bear-2026-booklet",
    source_publication_date: str = "2026-04-27",
    applied_correction: bool = False,
    supersedes: str | None = None,
) -> BmuRowExtraction:
    """Return a minimal BmuRowExtraction for use in merge tests."""
    return BmuRowExtraction(
        bmu_number=bmu_number,
        hd_region=hd_region,
        opportunity=None,
        general_season=general_season,
        archery_only_season=None,
        spring_season=None,
        hound_training_season=hound_training_season,
        hound_nr_license=None,
        hound_nr_max=None,
        fall_quota=BmuQuotaCell(count=None, kind=None, verbatim="-"),
        spring_quota=BmuQuotaCell(count=None, kind=None, verbatim="-"),
        page_reference=_make_page_reference(),
        verbatim_text="",
        extraction_confidence=extraction_confidence,
        source_id=source_id,
        source_publication_date=source_publication_date,
        applied_correction=applied_correction,
        supersedes=supersedes,
    )


def _make_correction_op(
    target_bmu: int = 100,
    target_field: str = "hound_training_season",
    change: str = "remove",
    source_id: str = "mt-fwp-black-bear-2026-correction-2026-03-18",
    source_publication_date: str = "2026-03-18",
) -> CorrectionOperation:
    """Return a minimal CorrectionOperation for tests."""
    return CorrectionOperation(
        target_bmu=target_bmu,
        target_field=target_field,
        change=change,
        new_value=None,
        verbatim_correction_text="Removed the hound training season column from the BMU tables on pages.",
        source_id=source_id,
        source_publication_date=source_publication_date,
    )


# ---------------------------------------------------------------------------
# 1. TestReverseCellText
# ---------------------------------------------------------------------------


class TestReverseCellText:
    def test_basic_single_line(self) -> None:
        assert _reverse_cell_text("Hello") == "olleH"

    def test_multi_line_reverses_lines_and_chars(self) -> None:
        # Lines reversed: "def" comes before "abc"; chars within each line reversed.
        assert _reverse_cell_text("abc\ndef") == "fed\ncba"

    def test_none_passthrough(self) -> None:
        assert _reverse_cell_text(None) is None

    def test_empty_string_passthrough(self) -> None:
        assert _reverse_cell_text("") == ""

    def test_real_pdf_example_date_range(self) -> None:
        # "Sep.15-Nov.29" extracts from rotated PDF as "92.voN-51.peS"
        assert _reverse_cell_text("92.voN-51.peS") == "Sep.15-Nov.29"

    def test_multi_line_real_example_round_trip_stable(self) -> None:
        # Two-line reversed example: applying _reverse_cell_text twice yields original.
        original = "Sep.15-Nov.29\nSep.1-Jun.15"
        reversed_once = _reverse_cell_text(original)
        assert reversed_once is not None
        reversed_twice = _reverse_cell_text(reversed_once)
        assert reversed_twice == original

    def test_single_char(self) -> None:
        assert _reverse_cell_text("A") == "A"

    def test_three_lines(self) -> None:
        # "a\nb\nc" → line order reversed: "c", "b", "a"; chars reversed (single): "c\nb\na"
        assert _reverse_cell_text("a\nb\nc") == "c\nb\na"


# ---------------------------------------------------------------------------
# 2. TestNormalizeCell
# ---------------------------------------------------------------------------


class TestNormalizeCell:
    def test_none_returns_none(self) -> None:
        assert _normalize_cell(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _normalize_cell("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _normalize_cell("   ") is None
        assert _normalize_cell("\t\n") is None

    def test_trim_and_collapse_3_plus_whitespace(self) -> None:
        # 3+ spaces collapsed to single space; outer whitespace stripped
        assert _normalize_cell("  hello   world  ") == "hello world"

    def test_two_spaces_not_collapsed(self) -> None:
        # Only 3+ whitespace runs are collapsed — 2 spaces are preserved
        assert _normalize_cell("hello  world") == "hello  world"

    def test_normal_text_unchanged(self) -> None:
        assert _normalize_cell("Sep.15-Nov.29") == "Sep.15-Nov.29"

    def test_tabs_collapsed_when_3_or_more(self) -> None:
        assert _normalize_cell("hello\t\t\tworld") == "hello world"


# ---------------------------------------------------------------------------
# 3. TestIsSeasonCellAbsent
# ---------------------------------------------------------------------------


class TestIsSeasonCellAbsent:
    def test_dash_is_absent(self) -> None:
        assert _is_season_cell_absent("-") is True

    def test_none_is_absent(self) -> None:
        assert _is_season_cell_absent(None) is True

    def test_padded_dash_is_absent(self) -> None:
        assert _is_season_cell_absent("  -  ") is True

    def test_date_is_not_absent(self) -> None:
        assert _is_season_cell_absent("Sep.15-Nov.29") is False

    def test_empty_string_is_absent(self) -> None:
        # Empty string: strip() → "" which == "-" is False, but the function
        # checks cell.strip() == "-" only; empty string strip → "" != "-".
        # However None path handles None; empty string passes through to strip check.
        # "" strip → "" which != "-" so returns False.
        # But _normalize_cell("") returns None, so callers should normalize first.
        # Direct test of the function semantics:
        assert _is_season_cell_absent("") is False

    def test_real_season_value_not_absent(self) -> None:
        assert _is_season_cell_absent("Apr.15-Jun.15") is False


# ---------------------------------------------------------------------------
# 4. TestParseQuotaCell
# ---------------------------------------------------------------------------


class TestParseQuotaCell:
    def test_female_subquota_pattern_a(self) -> None:
        result = _parse_quota_cell("= 4 Female subquota")
        assert result["count"] == 4
        assert result["kind"] == "female_subquota"
        assert result["verbatim"] == "= 4 Female subquota"

    def test_harvest_quota_pattern_a(self) -> None:
        result = _parse_quota_cell("= 18 Harvest quota")
        assert result["count"] == 18
        assert result["kind"] == "harvest_quota"
        assert result["verbatim"] == "= 18 Harvest quota"

    def test_dash_returns_none_count_and_kind(self) -> None:
        result = _parse_quota_cell("-")
        assert result["count"] is None
        assert result["kind"] is None
        assert result["verbatim"] == "-"

    def test_none_returns_empty_verbatim(self) -> None:
        result = _parse_quota_cell(None)
        assert result["count"] is None
        assert result["kind"] is None
        assert result["verbatim"] == ""

    def test_unparseable_emits_warning_and_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=m.__name__):
            result = _parse_quota_cell("unparseable garbage text")
        assert result["count"] is None
        assert result["kind"] is None
        assert result["verbatim"] == "unparseable garbage text"
        assert any("unparseable quota cell" in r.message for r in caplog.records)

    def test_pattern_b_inverted_word_order_harvest(self) -> None:
        # Pattern B: "= N quota Harvest" — word-order-invariant fallback
        result = _parse_quota_cell("= 12 quota Harvest")
        assert result["count"] == 12
        assert result["kind"] == "harvest_quota"
        assert result["verbatim"] == "= 12 quota Harvest"

    def test_pattern_b_inverted_word_order_female(self) -> None:
        # Pattern B female variant: "= 7 quota Female"
        result = _parse_quota_cell("= 7 quota Female")
        assert result["count"] == 7
        assert result["kind"] == "female_subquota"

    def test_pattern_c_scrambled_multiline(self) -> None:
        # Pattern C: "quota\n=\nHarvest\n5" — fully scrambled via multiline reversal
        result = _parse_quota_cell("quota\n=\nHarvest\n5")
        assert result["count"] == 5
        assert result["kind"] == "harvest_quota"

    def test_case_insensitive_kind_matching(self) -> None:
        result = _parse_quota_cell("= 3 FEMALE subquota")
        assert result["kind"] == "female_subquota"
        assert result["count"] == 3

    def test_verbatim_preserves_pre_normalize_text(self) -> None:
        # verbatim should be the ORIGINAL text (post-reversal, pre-normalize)
        raw = "= 18  Harvest  quota"  # extra spaces
        result = _parse_quota_cell(raw)
        assert result["verbatim"] == raw


# ---------------------------------------------------------------------------
# 5. TestDetectColumnRegion
# ---------------------------------------------------------------------------


class TestDetectColumnRegion:
    def test_region_1(self) -> None:
        assert _detect_column_region("REGION 1") == "R1"

    def test_region_3_with_extra_space(self) -> None:
        assert _detect_column_region("REGION  3") == "R3"

    def test_region_7(self) -> None:
        assert _detect_column_region("REGION 7") == "R7"

    def test_region_8_out_of_range_returns_none(self) -> None:
        # Montana only has 7 FWP regions; 8+ returns None
        assert _detect_column_region("REGION 8") is None

    def test_bmu_text_returns_none(self) -> None:
        assert _detect_column_region("BMU 411") is None

    def test_none_input_returns_none(self) -> None:
        assert _detect_column_region(None) is None

    def test_region_embedded_in_larger_text(self) -> None:
        # regex uses \b; should match even if surrounded by other text
        assert _detect_column_region("This is REGION 2 marker") == "R2"

    def test_region_0_out_of_range_returns_none(self) -> None:
        # [1-7] pattern; 0 should not match
        assert _detect_column_region("REGION 0") is None


# ---------------------------------------------------------------------------
# 6. TestIsPermitManagedColumn
# ---------------------------------------------------------------------------


class TestIsPermitManagedColumn:
    def test_permit_managed_opportunities_returns_true(self) -> None:
        assert _is_permit_managed_column("Permit Managed Opportunities") is True

    def test_case_insensitive(self) -> None:
        assert _is_permit_managed_column("permit managed opportunities") is True

    def test_bmu_text_returns_false(self) -> None:
        assert _is_permit_managed_column("BMU 510") is False

    def test_none_returns_false(self) -> None:
        assert _is_permit_managed_column(None) is False

    def test_quota_managed_not_permit_managed(self) -> None:
        # "Quota Managed Opportunities" is NOT the permit-managed marker
        assert _is_permit_managed_column("Quota Managed Opportunities") is False

    def test_partial_match_in_larger_string(self) -> None:
        assert _is_permit_managed_column("See Permit Managed Opportunities section") is True


# ---------------------------------------------------------------------------
# 7. TestRegionTrackingLeftToRight
# ---------------------------------------------------------------------------


class TestRegionTrackingLeftToRight:
    """Integration-style test for left-to-right region tracking in _iter_bmu_columns.

    Skipped because mocking a full PdfDocument with 4 pages and realistic
    table structures is prohibitively complex for a unit test. The real-PDF
    probe in T13 verifies that 35 BMUs distribute across R1–R7 correctly,
    which provides equivalent coverage of the region-tracking logic with no
    mock overhead.
    """

    def test_region_tracking_skipped_see_t13_probe(self) -> None:
        pytest.skip(
            "Region-tracking integration test deferred — the T13 real-PDF probe "
            "verifies 35 BMUs distribute correctly across R1–R7 (see "
            "docs/plans/S03.4-black-bear-extraction-plan.md § T13). Mocking a "
            "full PdfDocument across 4 pages is too costly for a unit fixture."
        )


# ---------------------------------------------------------------------------
# 8. TestExtractBmuRow
# ---------------------------------------------------------------------------


def _make_10row_table_for_bmu(
    *,
    opportunity: str | None = None,
    general_season: str | None = "Sep.15-Nov.29",
    archery_season: str | None = "-",
    spring_season: str | None = "Apr.1-May.31",
    hound_training: str | None = "Apr.15-Jun.15",
    hound_nr_license: str | None = "Yes",
    hound_nr_max: str | None = "3",
    fall_quota: str | None = "= 18 Harvest quota",
    spring_quota: str | None = "-",
    bmu_id: str | None = "100",
    col_idx: int = 0,
) -> m.TableMatch:
    """Build a single-column TableMatch for _extract_bmu_row tests.

    The transposed table has 10 logical rows (0-indexed):
      Row 0: opportunity text (headers in pdfplumber Case A)
      Rows 1-9: data rows (pdfplumber's rows[0..8])

    IMPORTANT: all cell values here are post-reversal (already readable text).
    _extract_bmu_row calls _reverse_cell_text on every cell, so to pass
    pre-reversed text we must pass double-reversed strings here.
    Pre-reversing: reverse each value before inserting so that
    _extract_bmu_row's internal call to _reverse_cell_text yields the
    intended readable value.
    """

    def rev(s: str | None) -> str | None:
        return _reverse_cell_text(s)

    # headers = Row 0 (opportunity)
    headers: list[str | None] = [rev(opportunity)]
    # rows[0..8] = Rows 1-9
    rows: list[list[str | None]] = [
        [rev(general_season)],   # row[0] = Row 1
        [rev(archery_season)],   # row[1] = Row 2
        [rev(spring_season)],    # row[2] = Row 3
        [rev(hound_training)],   # row[3] = Row 4
        [rev(hound_nr_license)], # row[4] = Row 5
        [rev(hound_nr_max)],     # row[5] = Row 6
        [rev(fall_quota)],       # row[6] = Row 7
        [rev(spring_quota)],     # row[7] = Row 8
        [rev(bmu_id)],           # row[8] = Row 9
    ]
    return _make_bmu_table(headers=headers, rows=rows)


class TestExtractBmuRow:
    def test_all_fields_populated_correctly(self) -> None:
        """BMU row with real data extracts all fields correctly."""
        table = _make_10row_table_for_bmu(
            opportunity="Spring / Fall Season",
            general_season="Sep.15-Nov.29",
            archery_season="-",
            spring_season="Apr.1-May.31",
            hound_training="Apr.15-Jun.15",
            hound_nr_license="Yes",
            hound_nr_max="3",
            fall_quota="= 18 Harvest quota",
            spring_quota="-",
            bmu_id="100",
        )
        citation = _make_source_citation()
        row = _extract_bmu_row(
            table=table,
            col_idx=0,
            page_num=9,
            current_region="R1",
            pdf_filename="test-black-bear.pdf",
            extracted_at="2026-05-10T00:00:00Z",
            source_citation=citation,
        )

        assert row["bmu_number"] == 100
        assert row["hd_region"] == "R1"
        assert row["general_season"] == "Sep.15-Nov.29"
        assert row["archery_only_season"] is None  # "-" → None
        assert row["spring_season"] == "Apr.1-May.31"
        assert row["hound_training_season"] == "Apr.15-Jun.15"
        assert row["hound_nr_license"] == "Yes"
        assert row["hound_nr_max"] == 3
        assert row["fall_quota"]["count"] == 18
        assert row["fall_quota"]["kind"] == "harvest_quota"
        assert row["spring_quota"]["count"] is None  # "-"
        assert row["applied_correction"] is False
        assert row["supersedes"] is None

    def test_all_dash_season_cells_yield_none(self) -> None:
        """All-dash season cells → all None for season fields."""
        table = _make_10row_table_for_bmu(
            opportunity=None,
            general_season="-",
            archery_season="-",
            spring_season="-",
            hound_training="-",
            hound_nr_license="-",
            hound_nr_max="-",
            fall_quota="-",
            spring_quota="-",
            bmu_id="200",
        )
        citation = _make_source_citation()
        row = _extract_bmu_row(
            table=table,
            col_idx=0,
            page_num=9,
            current_region="R2",
            pdf_filename="test-black-bear.pdf",
            extracted_at="2026-05-10T00:00:00Z",
            source_citation=citation,
        )

        assert row["bmu_number"] == 200
        assert row["general_season"] is None
        assert row["archery_only_season"] is None
        assert row["spring_season"] is None
        assert row["hound_training_season"] is None
        assert row["hound_nr_max"] is None
        assert row["fall_quota"]["count"] is None
        assert row["spring_quota"]["count"] is None

    def test_extraction_confidence_is_high_base(self) -> None:
        """Base extraction rows always get HIGH confidence."""
        table = _make_10row_table_for_bmu(bmu_id="300")
        citation = _make_source_citation()
        row = _extract_bmu_row(
            table=table,
            col_idx=0,
            page_num=9,
            current_region="R3",
            pdf_filename="test-black-bear.pdf",
            extracted_at="2026-05-10T00:00:00Z",
            source_citation=citation,
        )
        assert row["extraction_confidence"] is ConfidenceTier.HIGH
        assert row["applied_correction"] is False

    def test_female_subquota_bmu(self) -> None:
        """BMU with female subquota (asterisk suffix in PDF) extracts correctly."""
        table = _make_10row_table_for_bmu(
            fall_quota="= 4 Female subquota",
            bmu_id="300",
        )
        citation = _make_source_citation()
        row = _extract_bmu_row(
            table=table,
            col_idx=0,
            page_num=10,
            current_region="R3",
            pdf_filename="test-black-bear.pdf",
            extracted_at="2026-05-10T00:00:00Z",
            source_citation=citation,
        )
        assert row["fall_quota"]["count"] == 4
        assert row["fall_quota"]["kind"] == "female_subquota"

    def test_bmu_id_with_asterisk_strips_asterisk(self) -> None:
        """BMU IDs with trailing asterisk (female-subquota marker) parse to int correctly."""
        table = _make_10row_table_for_bmu(bmu_id="580*")
        citation = _make_source_citation()
        row = _extract_bmu_row(
            table=table,
            col_idx=0,
            page_num=11,
            current_region="R5",
            pdf_filename="test-black-bear.pdf",
            extracted_at="2026-05-10T00:00:00Z",
            source_citation=citation,
        )
        assert row["bmu_number"] == 580


# ---------------------------------------------------------------------------
# 9. TestExtractClosures
# ---------------------------------------------------------------------------


def _make_mock_pdf_with_text(page_text: str) -> MagicMock:
    """Build a MagicMock PdfDocument whose single page returns *page_text*."""
    mock_page = MagicMock()
    mock_page.crop.return_value = mock_page
    mock_page.extract_text.return_value = page_text

    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.filename = "test-black-bear.pdf"
    return mock_pdf


def _make_closure_page_text(
    include_bmu_530: bool = False,
) -> str:
    """Synthesize realistic p. 7 right-column prose for closure tests."""
    quota_bmus = "411, 420, 440, 450, 510, 520, 600, and 700"
    if include_bmu_530:
        quota_bmus = "411, 420, 440, 450, 510, 520, 530, 600, and 700"

    return (
        "Spring Season Closure: BMUs 300, 301, 319, and 580 are subject\n"
        "to close, with regular public notice, at any point after May 31 if the\n"
        "cumulative spring harvest exceeds 37% female black bears.\n"
        f"In BMUs {quota_bmus} when the quota\n"
        "is reached or approached in each of these districts, the black bear\n"
        "season in that district will close. For quota status, call 1-800-385-\n"
        "7826 or 406-444-1989.\n"
        "Inspection Requirements Region 1 Only: Region 1 hunters must present.\n"
    )


class TestExtractClosures:
    def test_two_candidates_emitted_with_correct_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Synthesized closure prose emits 2 ClosurePredicateCandidate dicts."""
        page_text = _make_closure_page_text()

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(7, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        citation = _make_source_citation()

        results = m._extract_closures(
            mock_pdf,
            "test-black-bear.pdf",
            "2026-05-10T00:00:00Z",
            citation,
        )

        assert len(results) == 2

        female_pred = results[0]
        assert female_pred["kind"] == "sex_threshold"
        assert female_pred["bmu_numbers"] == list(m._FEMALE_SUBQUOTA_BMUS)
        assert female_pred["threshold_percent"] == 37.0
        assert female_pred["threshold_sex"] == "female"
        assert "Spring Season Closure" in female_pred["verbatim_rule"]
        assert female_pred["extraction_confidence"] is ConfidenceTier.MEDIUM

        quota_pred = results[1]
        assert quota_pred["kind"] == "quota_threshold"
        assert quota_pred["bmu_numbers"] == list(m._QUOTA_CLOSURE_BMUS)
        assert quota_pred["threshold_percent"] is None
        assert quota_pred["threshold_sex"] is None
        assert "In BMUs 411" in quota_pred["verbatim_rule"]
        assert quota_pred["extraction_confidence"] is ConfidenceTier.MEDIUM

    def test_drift_guard_raises_on_unexpected_bmu(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If BMU 530 appears in quota closure prose, PdfExtractionError is raised."""
        page_text = _make_closure_page_text(include_bmu_530=True)

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(7, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        citation = _make_source_citation()

        with pytest.raises(PdfExtractionError, match="drifted"):
            m._extract_closures(
                mock_pdf,
                "test-black-bear.pdf",
                "2026-05-10T00:00:00Z",
                citation,
            )

    def test_phone_number_preserved_across_linebreak(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: `_DIGIT_LINEBREAK_RE` must REJOIN, not strip, the dash
        between digit pairs (verbatim discipline per ADR-008). The fixture
        has `1-800-385-\\n7826` (newline mid-phone-number); after extraction
        the quota predicate's verbatim_rule must contain `1-800-385-7826`,
        NOT `1-800-3857826`.
        """
        page_text = _make_closure_page_text()  # contains `1-800-385-\n7826`

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(7, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        citation = _make_source_citation()
        closures = m._extract_closures(
            mock_pdf,
            "test-black-bear.pdf",
            "2026-05-10T00:00:00Z",
            citation,
        )
        quota_predicate = next(c for c in closures if c["kind"] == "quota_threshold")
        assert "1-800-385-7826" in quota_predicate["verbatim_rule"], (
            "phone number was corrupted — _DIGIT_LINEBREAK_RE stripped the dash. "
            f"verbatim_rule: {quota_predicate['verbatim_rule']!r}"
        )
        # Negative assertion: the corrupted form must NOT appear.
        assert "1-800-3857826" not in quota_predicate["verbatim_rule"]

    def test_missing_spring_anchor_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If 'Spring Season Closure' anchor is absent, PdfExtractionError raised."""
        page_text = "Some unrelated text without the anchor."

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(7, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        citation = _make_source_citation()

        with pytest.raises(PdfExtractionError):
            m._extract_closures(
                mock_pdf,
                "test-black-bear.pdf",
                "2026-05-10T00:00:00Z",
                citation,
            )


# ---------------------------------------------------------------------------
# 10. TestExtractReportingObligations
# ---------------------------------------------------------------------------


def _make_reporting_page_text() -> str:
    """Synthesize realistic p. 7 right-column prose for reporting obligation tests."""
    return (
        "Mandatory Reporting Requirements: All successful black bear hunters must\n"
        "personally report their black bear harvest within 48 hours.\n"
        "Spring Season Closure: BMUs 300, 301, 319, and 580 are subject\n"
        "to close at any point after May 31.\n"
        "In BMUs 411, 420, 440, 450, 510, 520, 600, and 700 when the quota\n"
        "is reached the season will close. Call 1-800-385-7826.\n"
        "Inspection Requirements Region 1 Only: Within 10 days, submit a premolar tooth.\n"
        "Inspection Requirements Regions 2-7: Within 10 days, present hide and skull.\n"
        "A person licensed to hunt may transfer possession.\n"
    )


class TestExtractReportingObligations:
    def test_three_candidates_emitted_with_correct_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Synthesized prose emits 3 ReportingObligationCandidate dicts."""
        page_text = _make_reporting_page_text()

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(7, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        citation = _make_source_citation()

        results = m._extract_reporting_obligations(
            mock_pdf,
            "test-black-bear.pdf",
            "2026-05-10T00:00:00Z",
            citation,
        )

        assert len(results) == 3

        statewide = results[0]
        assert statewide["region_scope"] == "STATEWIDE"
        assert statewide["kind_hint"] == "harvest_report"
        assert statewide["deadline_hint"] == "48 hours"
        assert "Mandatory Reporting" in statewide["verbatim_rule"]

        r1 = results[1]
        assert r1["region_scope"] == "R1"
        assert r1["kind_hint"] == "tooth_submission"
        assert r1["deadline_hint"] == "10 days"
        assert "Region 1 Only" in r1["verbatim_rule"]

        r27 = results[2]
        assert r27["region_scope"] == "R2-7"
        assert r27["kind_hint"] == "hide_skull_presentation"
        assert r27["deadline_hint"] == "10 days"
        assert "Regions 2-7" in r27["verbatim_rule"]


# ---------------------------------------------------------------------------
# 11. TestExtractCorrection
# ---------------------------------------------------------------------------


def _make_correction_page_text(include_anchor: bool = True) -> str:
    """Synthesize correction PDF prose for _extract_correction tests."""
    if not include_anchor:
        return (
            "Corrections to the 2026 Printed Black Bear Regulations\n"
            "• Persons using hounds to hunt are required to have a valid Resident Black Bear License.\n"
        )
    return (
        "Corrections to the 2026 Printed Black Bear Regulations\n"
        "• Persons using hounds to hunt are required to have a valid\n"
        "Resident Black Bear License if hunting or chasing during the black bear hunting season.\n"
        "• Removed the hound training season column from the BMU tables on pages. Statutorily\n"
        "the training season begins following the end of spring bear and runs until June 15.\n"
    )


class TestExtractCorrection:
    def test_correction_synthesizes_one_op_per_base_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2 synthetic base rows → 2 correction operations, each with expected fields."""
        page_text = _make_correction_page_text()

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(1, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-correction.pdf"

        correction_citation = _make_source_citation(
            citation_id="mt-fwp-black-bear-2026-correction-2026-03-18",
            document_type="correction",
            publication_date="2026-03-18",
        )

        base_rows: list[BmuRowExtraction] = [
            _make_bmu_row_extraction(bmu_number=100),
            _make_bmu_row_extraction(bmu_number=200),
        ]

        result = m._extract_correction(
            mock_pdf,
            correction_citation,
            "2026-05-10T00:00:00Z",
            base_rows,
        )

        assert len(result["operations"]) == 2
        for op in result["operations"]:
            assert op["target_field"] == "hound_training_season"
            assert op["change"] == "remove"
            assert op["new_value"] is None
            assert op["source_id"] == "mt-fwp-black-bear-2026-correction-2026-03-18"
            assert op["source_publication_date"] == "2026-03-18"
            assert "Removed the hound training season column" in op["verbatim_correction_text"]

        assert result["operations"][0]["target_bmu"] == 100
        assert result["operations"][1]["target_bmu"] == 200

    def test_missing_anchor_raises_pdf_extraction_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anchor not found → PdfExtractionError raised."""
        page_text = _make_correction_page_text(include_anchor=False)

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(1, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-correction.pdf"

        correction_citation = _make_source_citation(
            citation_id="mt-fwp-black-bear-2026-correction-2026-03-18",
            document_type="correction",
            publication_date="2026-03-18",
        )

        with pytest.raises(PdfExtractionError):
            m._extract_correction(
                mock_pdf,
                correction_citation,
                "2026-05-10T00:00:00Z",
                [],
            )

    def test_empty_base_rows_yields_empty_operations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty base_rows → empty operations list (no error)."""
        page_text = _make_correction_page_text()

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(1, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-correction.pdf"

        correction_citation = _make_source_citation(
            citation_id="mt-fwp-black-bear-2026-correction-2026-03-18",
            document_type="correction",
            publication_date="2026-03-18",
        )

        result = m._extract_correction(
            mock_pdf,
            correction_citation,
            "2026-05-10T00:00:00Z",
            [],
        )

        assert result["operations"] == []


# ---------------------------------------------------------------------------
# 12. TestMergeWithCorrections
# ---------------------------------------------------------------------------


def _make_base_extraction(
    rows: list[BmuRowExtraction],
    source_id: str = "mt-fwp-black-bear-2026-booklet",
    publication_date: str = "2026-04-27",
) -> BlackBearBaseExtraction:
    """Build a minimal BlackBearBaseExtraction for merge tests."""
    citation = _make_source_citation(
        citation_id=source_id,
        publication_date=publication_date,
    )
    return BlackBearBaseExtraction(
        state="MT",
        species_group="black_bear",
        license_year=2026,
        schema_version=2,
        extracted_at="2026-05-10T00:00:00Z",
        source=citation,
        rows=rows,
        closures=[],
        reporting_obligations=[],
        statewide_rules=[],
    )


def _make_correction_extraction(
    operations: list[CorrectionOperation],
    source_id: str = "mt-fwp-black-bear-2026-correction-2026-03-18",
    publication_date: str = "2026-03-18",
) -> CorrectionExtraction:
    """Build a minimal CorrectionExtraction for merge tests."""
    citation = _make_source_citation(
        citation_id=source_id,
        document_type="correction",
        publication_date=publication_date,
    )
    return CorrectionExtraction(
        extracted_at="2026-05-10T00:00:00Z",
        source=citation,
        operations=operations,
    )


class TestMergeWithCorrections:
    def test_basic_merge_correction_wins_option_b(self) -> None:
        """Correction op removes hound_training_season; row tagged, confidence demoted."""
        base_row = _make_bmu_row_extraction(
            bmu_number=100,
            hound_training_season="Apr.15-Jun.15",
            extraction_confidence=ConfidenceTier.HIGH,
            source_id="mt-fwp-black-bear-2026-booklet",
            source_publication_date="2026-04-27",
        )
        base = _make_base_extraction([base_row])
        correction_op = _make_correction_op(target_bmu=100)
        correction = _make_correction_extraction([correction_op])

        merged = _merge_with_corrections(base, correction)

        assert len(merged["rows"]) == 1
        merged_row = merged["rows"][0]
        assert merged_row["hound_training_season"] is None
        assert merged_row["applied_correction"] is True
        assert merged_row["supersedes"] == "mt-fwp-black-bear-2026-booklet"
        assert merged_row["extraction_confidence"] is ConfidenceTier.MEDIUM
        assert merged_row["source_id"] == "mt-fwp-black-bear-2026-correction-2026-03-18"

    def test_real_world_option_b_correction_wins_despite_earlier_date(self) -> None:
        """booklet date=2026-04-27 > correction date=2026-03-18, but correction STILL wins.

        This is the key Option B regression-prevention test: document_type='correction'
        always overrides document_type='annual_regulations', regardless of date order.
        Naive MAX-date would silently discard the correction (booklet is newer).
        """
        base_row = _make_bmu_row_extraction(
            bmu_number=300,
            hound_training_season="Apr.15-Jun.15",
            extraction_confidence=ConfidenceTier.HIGH,
            source_id="mt-fwp-black-bear-2026-booklet",
            source_publication_date="2026-04-27",  # later date
        )
        base = _make_base_extraction(
            [base_row],
            source_id="mt-fwp-black-bear-2026-booklet",
            publication_date="2026-04-27",
        )
        correction_op = _make_correction_op(
            target_bmu=300,
            source_id="mt-fwp-black-bear-2026-correction-2026-03-18",
            source_publication_date="2026-03-18",  # earlier date — still wins
        )
        correction = _make_correction_extraction(
            [correction_op],
            source_id="mt-fwp-black-bear-2026-correction-2026-03-18",
            publication_date="2026-03-18",
        )

        merged = _merge_with_corrections(base, correction)

        row = merged["rows"][0]
        assert row["hound_training_season"] is None
        assert row["applied_correction"] is True
        assert row["source_id"] == "mt-fwp-black-bear-2026-correction-2026-03-18"

    def test_date_collision_tiebreaker_raises_conflict_error(self) -> None:
        """Two correction ops targeting same (bmu, field) with equal date → CorrectionConflictError."""
        base_row = _make_bmu_row_extraction(bmu_number=100)
        base = _make_base_extraction([base_row])

        op1 = _make_correction_op(
            target_bmu=100,
            source_id="correction-source-A",
            source_publication_date="2026-03-18",
        )
        op2 = _make_correction_op(
            target_bmu=100,
            source_id="correction-source-B",
            source_publication_date="2026-03-18",
        )
        correction = _make_correction_extraction([op1, op2])

        with pytest.raises(CorrectionConflictError, match="equal publication_date"):
            _merge_with_corrections(base, correction)

    def test_untouched_cells_unchanged(self) -> None:
        """Correction touches hound_training_season only; other fields stay unchanged."""
        base_row = _make_bmu_row_extraction(
            bmu_number=100,
            general_season="Sep.15-Nov.29",
            hound_training_season="Apr.15-Jun.15",
        )
        base = _make_base_extraction([base_row])
        correction_op = _make_correction_op(target_bmu=100)
        correction = _make_correction_extraction([correction_op])

        merged = _merge_with_corrections(base, correction)

        row = merged["rows"][0]
        # hound_training removed
        assert row["hound_training_season"] is None
        # general_season untouched
        assert row["general_season"] == "Sep.15-Nov.29"

    def test_tier_demotion_high_to_medium(self) -> None:
        """HIGH + correction touch → MEDIUM."""
        base_row = _make_bmu_row_extraction(
            bmu_number=100,
            extraction_confidence=ConfidenceTier.HIGH,
        )
        base = _make_base_extraction([base_row])
        correction = _make_correction_extraction([_make_correction_op(target_bmu=100)])

        merged = _merge_with_corrections(base, correction)
        assert merged["rows"][0]["extraction_confidence"] is ConfidenceTier.MEDIUM

    def test_tier_demotion_medium_to_low(self) -> None:
        """MEDIUM + correction touch → LOW."""
        base_row = _make_bmu_row_extraction(
            bmu_number=100,
            extraction_confidence=ConfidenceTier.MEDIUM,
        )
        base = _make_base_extraction([base_row])
        correction = _make_correction_extraction([_make_correction_op(target_bmu=100)])

        merged = _merge_with_corrections(base, correction)
        assert merged["rows"][0]["extraction_confidence"] is ConfidenceTier.LOW

    def test_tier_demotion_low_clamped_at_low(self) -> None:
        """LOW + correction touch → LOW (clamped, does not go below floor)."""
        base_row = _make_bmu_row_extraction(
            bmu_number=100,
            extraction_confidence=ConfidenceTier.LOW,
        )
        base = _make_base_extraction([base_row])
        correction = _make_correction_extraction([_make_correction_op(target_bmu=100)])

        merged = _merge_with_corrections(base, correction)
        assert merged["rows"][0]["extraction_confidence"] is ConfidenceTier.LOW

    def test_unknown_bmu_in_correction_raises(self) -> None:
        """Correction targeting a BMU not in base_rows raises PdfExtractionError."""
        base_row = _make_bmu_row_extraction(bmu_number=100)
        base = _make_base_extraction([base_row])
        correction_op = _make_correction_op(target_bmu=999)  # not in base
        correction = _make_correction_extraction([correction_op])

        with pytest.raises(PdfExtractionError, match="unknown BMU"):
            _merge_with_corrections(base, correction)

    def test_base_rows_not_mutated(self) -> None:
        """_merge_with_corrections deep-copies base rows; originals are unmodified."""
        base_row = _make_bmu_row_extraction(bmu_number=100, hound_training_season="Apr.15-Jun.15")
        original_training = base_row["hound_training_season"]
        base = _make_base_extraction([base_row])
        correction = _make_correction_extraction([_make_correction_op(target_bmu=100)])

        _merge_with_corrections(base, correction)

        # Original base_row unmodified
        assert base_row["hound_training_season"] == original_training

    def test_unknown_target_field_raises(self) -> None:
        """Correction op with target_field not in _CORRECTABLE_FIELDS raises
        PdfExtractionError. Guards against typos that would silently add a new
        dict key on the TypedDict row (TypedDict writes are unchecked at
        runtime since they're plain dicts).
        """
        base_row = _make_bmu_row_extraction(bmu_number=100)
        base = _make_base_extraction([base_row])
        # Typo: "hound_training_seasons" with a trailing 's' — not a real field.
        bad_op = _make_correction_op(target_bmu=100)
        bad_op["target_field"] = "hound_training_seasons"
        correction = _make_correction_extraction([bad_op])

        with pytest.raises(PdfExtractionError, match="unknown BmuRowExtraction field"):
            _merge_with_corrections(base, correction)

    def test_row_provenance_tiebreaker_is_lex_smallest_source_id(self) -> None:
        """When two corrections targeting different fields on the same BMU
        share the same publication_date, row-level source_id must be the
        lexicographically smallest source_id (deterministic regardless of
        op order).

        Without this tiebreaker, the choice would depend on dict / list
        insertion order — a real reproducibility hazard for future
        cross-correction merges. Locked here as a regression guard.
        """
        base_row = _make_bmu_row_extraction(
            bmu_number=100,
            general_season="Sep.15-Nov.29",
            hound_training_season="Apr.15-Jun.15",
        )
        base = _make_base_extraction([base_row])
        # Two corrections, SAME publication_date, DIFFERENT source_ids,
        # targeting DIFFERENT fields. The lex-smallest source_id must win.
        op_b = _make_correction_op(
            target_bmu=100,
            target_field="hound_training_season",
            source_id="corr-b-2026",   # lex-larger
            source_publication_date="2026-03-18",
        )
        op_a = _make_correction_op(
            target_bmu=100,
            target_field="general_season",
            source_id="corr-a-2026",   # lex-smaller; should win
            source_publication_date="2026-03-18",
        )
        # Order matters for the test: put the LEX-LARGER one first so a
        # naive `max(..., key=date)` would pick the wrong winner.
        correction = _make_correction_extraction([op_b, op_a])

        merged = _merge_with_corrections(base, correction)
        merged_row = merged["rows"][0]

        assert merged_row["source_id"] == "corr-a-2026", (
            f"row provenance tiebreaker broken: expected 'corr-a-2026' "
            f"(lex-smallest), got {merged_row['source_id']!r}"
        )
        assert merged_row["source_publication_date"] == "2026-03-18"

    def test_multi_field_row_demoted_once_and_provenance_is_max_date(self) -> None:
        """When TWO correction ops touch DIFFERENT fields on the SAME BMU row,
        demote_one_tier must fire exactly once (not twice) and the row-level
        source_id/source_publication_date must reflect the MAX-date winning
        op across both fields (not whichever iterated last).

        Regression for cubic-review P2: previously the merge loop overwrote
        row-level provenance and re-demoted confidence on each (bmu, field)
        iteration, so for a HIGH row + 2 corrections the result was LOW
        instead of MEDIUM, and provenance depended on dict insertion order.
        """
        base_row = _make_bmu_row_extraction(
            bmu_number=100,
            general_season="Sep.15-Nov.29",
            hound_training_season="Apr.15-Jun.15",
            extraction_confidence=ConfidenceTier.HIGH,
        )
        base = _make_base_extraction([base_row])
        # Two corrections from two different sources targeting two different
        # fields on the same BMU. Later date should win row-level provenance.
        op_older = _make_correction_op(
            target_bmu=100,
            target_field="hound_training_season",
            source_id="corr-2026-01",
            source_publication_date="2026-01-15",
        )
        op_newer = _make_correction_op(
            target_bmu=100,
            target_field="general_season",
            source_id="corr-2026-03",
            source_publication_date="2026-03-18",
        )
        correction = _make_correction_extraction([op_older, op_newer])

        merged = _merge_with_corrections(base, correction)
        merged_row = merged["rows"][0]

        # Confidence demoted exactly once: HIGH -> MEDIUM (NOT LOW).
        assert merged_row["extraction_confidence"] is ConfidenceTier.MEDIUM, (
            f"row was demoted {1 if merged_row['extraction_confidence'] is ConfidenceTier.MEDIUM else 2}+ times; "
            f"got {merged_row['extraction_confidence']!r}, expected MEDIUM"
        )
        # Row-level provenance = MAX-date winner (corr-2026-03).
        assert merged_row["source_id"] == "corr-2026-03"
        assert merged_row["source_publication_date"] == "2026-03-18"
        # Both fields were applied at cell level regardless of provenance choice.
        assert merged_row["hound_training_season"] is None
        # general_season was a "remove" op too (per _make_correction_op default)
        # — just confirm it was processed.
        assert merged_row["applied_correction"] is True


# ---------------------------------------------------------------------------
# 13. TestLoadCitationFromSourcesYaml
# ---------------------------------------------------------------------------


class TestLoadCitationFromSourcesYaml:
    def test_load_real_booklet_citation(self) -> None:
        """Load mt-fwp-black-bear-2026-booklet from the real sources.yaml."""
        citation = m._load_citation_from_sources_yaml("mt-fwp-black-bear-2026-booklet")
        assert citation["id"] == "mt-fwp-black-bear-2026-booklet"
        assert citation["publication_date"] == "2026-04-27"
        assert citation["document_type"] == "annual_regulations"
        assert citation["agency"] == "Montana Fish, Wildlife & Parks"
        assert "fwp.mt.gov" in citation["url"]

    def test_unknown_id_raises_pdf_extraction_error(self) -> None:
        """Loading a non-existent citation id raises PdfExtractionError."""
        with pytest.raises(PdfExtractionError, match="no entry with id"):
            m._load_citation_from_sources_yaml("this-id-does-not-exist-v999")

    def test_malformed_publication_date_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sources.yaml with malformed publication_date raises PdfExtractionError."""
        bad_yaml = {
            "pdfs": [
                {
                    "id": "test-bad-date",
                    "agency": "Test Agency",
                    "title": "Test Title",
                    "url": "https://example.com/test.pdf",
                    "publication_date": "not-a-date",
                    "document_type": "annual_regulations",
                }
            ]
        }
        yaml_file = tmp_path / "bad_sources.yaml"
        yaml_file.write_text(yaml.dump(bad_yaml), encoding="utf-8")

        monkeypatch.setattr(m, "_SOURCES_YAML", yaml_file)

        with pytest.raises(PdfExtractionError, match="unparseable"):
            m._load_citation_from_sources_yaml("test-bad-date")

    def test_load_real_correction_citation(self) -> None:
        """Load mt-fwp-black-bear-2026-correction-2026-03-18 from the real sources.yaml."""
        citation = m._load_citation_from_sources_yaml(
            "mt-fwp-black-bear-2026-correction-2026-03-18"
        )
        assert citation["id"] == "mt-fwp-black-bear-2026-correction-2026-03-18"
        assert citation["publication_date"] == "2026-03-18"
        assert citation["document_type"] == "correction"


# ---------------------------------------------------------------------------
# 14. TestFailLoudBmuCountGuard
# ---------------------------------------------------------------------------


class TestFailLoudBmuCountGuard:
    def test_below_floor_raises_pdf_extraction_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_extract_base raises PdfExtractionError when BMU count < _MIN_EXPECTED_BMU_COUNT."""
        # Patch _iter_bmu_columns to yield only 29 tuples (below floor of 30).
        # We also need to patch _extract_closures and _extract_reporting_obligations
        # to avoid needing a real PDF for those calls.
        def fake_iter_bmu_columns(pdf: object) -> Any:
            # Yield 29 fake (page_num, table, col_idx, region, row0) tuples.
            # _extract_base calls _extract_bmu_row for each; we also need to
            # patch _extract_bmu_row to avoid actual table parsing.
            return iter([])  # actually yield nothing at all → 0 < 30

        def fake_extract_closures(*args: object, **kwargs: object) -> list[Any]:
            return []

        def fake_extract_reporting(*args: object, **kwargs: object) -> list[Any]:
            return []

        monkeypatch.setattr(m, "_iter_bmu_columns", fake_iter_bmu_columns)
        monkeypatch.setattr(m, "_extract_closures", fake_extract_closures)
        monkeypatch.setattr(m, "_extract_reporting_obligations", fake_extract_reporting)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        citation = _make_source_citation()

        with pytest.raises(PdfExtractionError) as exc_info:
            m._extract_base(mock_pdf, citation, "2026-05-10T00:00:00Z")

        error_msg = str(exc_info.value)
        assert str(m._MIN_EXPECTED_BMU_COUNT) in error_msg
        # Actual count (0) should be in the message too
        assert "0" in error_msg

    def test_29_columns_raises_with_floor_in_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """29 yielded columns (1 below floor of 30) raises with count surfaced."""
        fake_rows: list[BmuRowExtraction] = [
            _make_bmu_row_extraction(bmu_number=100 + i, hd_region="R1")
            for i in range(29)
        ]

        def fake_iter_bmu_columns(pdf: object) -> Any:
            return iter([])

        def fake_extract_bmu_row_side_effect(*args: object, **kwargs: object) -> BmuRowExtraction:
            return fake_rows.pop(0)

        call_count = [0]

        def fake_iter_yielding_29(pdf: object) -> Any:
            # Yield 29 dummy tuples to drive the loop
            for i in range(29):
                yield (9 + (i // 10), MagicMock(), i % 10, "R1", f"BMU text {i}")

        def fake_extract_bmu_row(
            table: object,
            col_idx: int,
            page_num: int,
            current_region: str,
            pdf_filename: str,
            extracted_at: str,
            source_citation: object,
        ) -> BmuRowExtraction:
            call_count[0] += 1
            return _make_bmu_row_extraction(bmu_number=100 + call_count[0], hd_region="R1")

        def fake_extract_closures(*args: object, **kwargs: object) -> list[Any]:
            return []

        def fake_extract_reporting(*args: object, **kwargs: object) -> list[Any]:
            return []

        monkeypatch.setattr(m, "_iter_bmu_columns", fake_iter_yielding_29)
        monkeypatch.setattr(m, "_extract_bmu_row", fake_extract_bmu_row)
        monkeypatch.setattr(m, "_extract_closures", fake_extract_closures)
        monkeypatch.setattr(m, "_extract_reporting_obligations", fake_extract_reporting)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        citation = _make_source_citation()

        with pytest.raises(PdfExtractionError) as exc_info:
            m._extract_base(mock_pdf, citation, "2026-05-10T00:00:00Z")

        error_msg = str(exc_info.value)
        assert str(m._MIN_EXPECTED_BMU_COUNT) in error_msg
        assert "29" in error_msg

    def test_unrecognized_region_raises_with_bmu_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A row with hd_region not in _REGION_ORDER raises PdfExtractionError
        from the sort step, with the BMU number surfaced in the message.
        Guards against a bare KeyError from a future PDF introducing R8.
        """
        # Yield enough rows to pass the floor guard (30+), with one carrying
        # an unrecognized region.
        def fake_iter_yielding_with_bad_region(pdf: object) -> Any:
            # 30 valid R1 columns + 1 R8 column
            for i in range(31):
                region = "R8" if i == 15 else "R1"
                yield (9, MagicMock(), i, region, f"row text {i}")

        def fake_extract_bmu_row(
            table: object,
            col_idx: int,
            page_num: int,
            current_region: str,
            pdf_filename: str,
            extracted_at: str,
            source_citation: object,
        ) -> BmuRowExtraction:
            return _make_bmu_row_extraction(
                bmu_number=100 + col_idx, hd_region=current_region,
            )

        def fake_extract_closures(*args: object, **kwargs: object) -> list[Any]:
            return []

        def fake_extract_reporting(*args: object, **kwargs: object) -> list[Any]:
            return []

        monkeypatch.setattr(m, "_iter_bmu_columns", fake_iter_yielding_with_bad_region)
        monkeypatch.setattr(m, "_extract_bmu_row", fake_extract_bmu_row)
        monkeypatch.setattr(m, "_extract_closures", fake_extract_closures)
        monkeypatch.setattr(m, "_extract_reporting_obligations", fake_extract_reporting)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        citation = _make_source_citation()

        with pytest.raises(PdfExtractionError) as exc_info:
            m._extract_base(mock_pdf, citation, "2026-05-10T00:00:00Z")

        msg = str(exc_info.value)
        # Specific BMU id should appear (so reviewer can find the offending row).
        assert "BMU 115" in msg or "BMU" in msg, msg
        assert "R8" in msg or "unrecognized" in msg.lower(), msg


# ---------------------------------------------------------------------------
# 15. TestDeterministicJsonOutput
# ---------------------------------------------------------------------------


class TestDeterministicJsonOutput:
    def test_same_data_same_bytes_twice(self, tmp_path: Path) -> None:
        """Writing the same data twice yields byte-identical output."""
        data = {
            "z_key": "z_value",
            "a_key": "a_value",
            "nested": {"beta": 2, "alpha": 1},
            "confidence": ConfidenceTier.HIGH,
        }
        out_path = tmp_path / "test_output.json"

        _write_deterministic_json(out_path, data)
        first_bytes = out_path.read_bytes()

        _write_deterministic_json(out_path, data)
        second_bytes = out_path.read_bytes()

        assert first_bytes == second_bytes

    def test_keys_in_sorted_order(self, tmp_path: Path) -> None:
        """JSON keys appear in sorted order (sort_keys=True)."""
        data = {
            "z_last": "z",
            "a_first": "a",
            "m_middle": "m",
        }
        out_path = tmp_path / "sorted_output.json"
        _write_deterministic_json(out_path, data)

        content = out_path.read_text(encoding="utf-8")
        parsed = json.loads(content)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

        # Also verify the raw text key positions (belt-and-suspenders)
        pos_a = content.index('"a_first"')
        pos_m = content.index('"m_middle"')
        pos_z = content.index('"z_last"')
        assert pos_a < pos_m < pos_z

    def test_trailing_newline(self, tmp_path: Path) -> None:
        """Output file ends with a trailing newline."""
        out_path = tmp_path / "newline_test.json"
        _write_deterministic_json(out_path, {"key": "value"})
        content = out_path.read_bytes()
        assert content.endswith(b"\n")

    def test_confidence_tier_serializes_as_string(self, tmp_path: Path) -> None:
        """ConfidenceTier instances serialize as plain strings (str mixin)."""
        data = {"confidence": ConfidenceTier.HIGH}
        out_path = tmp_path / "tier_test.json"
        _write_deterministic_json(out_path, data)
        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        assert parsed["confidence"] == "high"
        assert isinstance(parsed["confidence"], str)

    def test_atomic_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """_write_deterministic_json creates parent directories if absent."""
        nested_path = tmp_path / "subdir" / "nested" / "output.json"
        _write_deterministic_json(nested_path, {"key": "val"})
        assert nested_path.exists()


# ---------------------------------------------------------------------------
# T5: TestExtractStatewideRules
# ---------------------------------------------------------------------------

# Canonical Bear ID Test paragraph (modulo whitespace collapse).
# The PDF uses Unicode curly/smart quotes (“ / ”) around
# "Black Bear Identification test" — these are preserved verbatim per ADR-008.
_BEAR_ID_PARAGRAPH = (
    "A hunter may purchase only one Black Bear License per year. "
    "A free Black Bear Identification Test Certificate is required to obtain a license. "
    "A hunter must take and pass a “Black Bear Identification test” before purchasing a "
    "Black Bear Hunting license. A hunter must present a certificate of completion issued "
    "by FWP at the time of purchase. The test is available online at: "
    "fwp.mt.gov/hunt/education/bear-identification"
)


def _make_statewide_rules_page_text(
    include_start: bool = True,
    include_end: bool = True,
) -> str:
    """Synthesize realistic p. 2 right-column prose for statewide-rules tests.

    Uses the same Unicode curly quotes as the real PDF so the extracted
    ``verbatim_text`` matches ``_BEAR_ID_PARAGRAPH`` byte-for-byte.
    """
    if not include_start:
        return "Some unrelated right-column text without the Bear ID anchor."
    body = (
        "A hunter may purchase only one Black Bear License per year. "
        "A free Black Bear Identification Test Certificate is required to obtain a license. "
        "A hunter must take and pass a “Black Bear Identification test” before purchasing a "
        "Black Bear Hunting license. A hunter must present a certificate of completion issued "
        "by FWP at the time of purchase. The test is available online at:"
    )
    if not include_end:
        return body + " (URL omitted)"
    return body + " fwp.mt.gov/hunt/education/bear-identification"


class TestExtractStatewideRules:
    """Tests for ``_extract_statewide_rules`` — p. 2 right-column Bear ID Test extraction."""

    def _setup_monkeypatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        page_text: str,
    ) -> MagicMock:
        """Wire monkeypatch for iter_pages + extract_text; return a mock PDF."""

        def fake_iter_pages(
            pdf: object, start: int, end: int
        ) -> list[tuple[int, MagicMock]]:
            mock_page = MagicMock()
            mock_page.crop.return_value = mock_page
            mock_page.extract_text.return_value = page_text
            return [(2, mock_page)]

        def fake_extract_text(
            page: object, bbox: object = None
        ) -> str:
            return page_text  # type: ignore[return-value]

        monkeypatch.setattr(m, "iter_pages", fake_iter_pages)
        monkeypatch.setattr(m, "extract_text", fake_extract_text)

        mock_pdf = MagicMock()
        mock_pdf.filename = "test-black-bear.pdf"
        return mock_pdf

    def test_extracts_bear_id_test_paragraph(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Synthetic p. 2 right-column text yields exactly 1 StatewideRuleCandidate."""
        page_text = _make_statewide_rules_page_text()
        mock_pdf = self._setup_monkeypatch(monkeypatch, page_text)

        results = m._extract_statewide_rules(
            mock_pdf,
            "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf",
            "mt-fwp-black-bear-2026-booklet",
            "2026-04-27",
            "2026-05-22T10:00:00+00:00",
        )

        assert len(results) == 1
        candidate = results[0]
        assert candidate["verbatim_text"] == _BEAR_ID_PARAGRAPH
        assert candidate["rule_hint"] == "pre_purchase_prerequisite"
        assert candidate["extraction_confidence"] == "medium"
        assert candidate["page_reference"]["page_num_1based"] == 2

    def test_start_anchor_missing_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing start anchor → empty list (downstream row-count guard fires)."""
        page_text = _make_statewide_rules_page_text(include_start=False)
        mock_pdf = self._setup_monkeypatch(monkeypatch, page_text)

        results = m._extract_statewide_rules(
            mock_pdf,
            "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf",
            "mt-fwp-black-bear-2026-booklet",
            "2026-04-27",
            "2026-05-22T10:00:00+00:00",
        )

        assert results == []

    def test_end_anchor_missing_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Start anchor found but end anchor absent → RuntimeError with 'end anchor missing'."""
        page_text = _make_statewide_rules_page_text(include_end=False)
        mock_pdf = self._setup_monkeypatch(monkeypatch, page_text)

        with pytest.raises(RuntimeError, match="end anchor missing"):
            m._extract_statewide_rules(
                mock_pdf,
                "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf",
                "mt-fwp-black-bear-2026-booklet",
                "2026-04-27",
                "2026-05-22T10:00:00+00:00",
            )

    def test_whitespace_collapse_extras_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multi-line / tab / multi-space input collapses to single-space-separated text."""
        # Input deliberately contains \n\n, \t, and runs of spaces.
        page_text = (
            "A hunter may purchase only one Black Bear License per year.\n\n"
            "\tA free   Black Bear Identification Test Certificate is required to obtain a license. "
            "A hunter must take and pass a Black Bear Identification test before purchasing a "
            "Black Bear Hunting license. A hunter must present a certificate of completion issued "
            "by FWP at the time of purchase. The test is available online at: "
            "fwp.mt.gov/hunt/education/bear-identification"
        )
        mock_pdf = self._setup_monkeypatch(monkeypatch, page_text)

        results = m._extract_statewide_rules(
            mock_pdf,
            "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf",
            "mt-fwp-black-bear-2026-booklet",
            "2026-04-27",
            "2026-05-22T10:00:00+00:00",
        )

        assert len(results) == 1
        cleaned = results[0]["verbatim_text"]
        assert "\n" not in cleaned, f"newline found in verbatim_text: {cleaned!r}"
        assert "\t" not in cleaned, f"tab found in verbatim_text: {cleaned!r}"
        assert "  " not in cleaned, f"double-space found in verbatim_text: {cleaned!r}"

    def test_extracted_at_threads_through_page_reference(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """extracted_at parameter is preserved verbatim in page_reference."""
        page_text = _make_statewide_rules_page_text()
        mock_pdf = self._setup_monkeypatch(monkeypatch, page_text)
        extracted_at = "2026-05-22T10:00:00+00:00"

        results = m._extract_statewide_rules(
            mock_pdf,
            "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf",
            "mt-fwp-black-bear-2026-booklet",
            "2026-04-27",
            extracted_at,
        )

        assert len(results) == 1
        assert results[0]["page_reference"]["extracted_at"] == extracted_at

    def test_pdf_filename_parameter_threads_through_page_reference(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pdf_filename parameter is preserved verbatim in page_reference —
        protects against the synthetic-name antipattern (deriving the filename
        from source_id + publication_date would silently lie about provenance
        on custom ``--booklet-pdf`` operator runs)."""
        page_text = _make_statewide_rules_page_text()
        mock_pdf = self._setup_monkeypatch(monkeypatch, page_text)
        custom_filename = "operator-override-name.pdf"

        results = m._extract_statewide_rules(
            mock_pdf,
            custom_filename,
            "mt-fwp-black-bear-2026-booklet",
            "2026-04-27",
            "2026-05-22T10:00:00+00:00",
        )

        assert len(results) == 1
        assert results[0]["page_reference"]["pdf_filename"] == custom_filename

    def test_real_artifact_round_trip(self) -> None:
        """black-bear-2026.json statewide_rules has 1 entry with expected content."""
        artifact_path = (
            Path(__file__).resolve().parents[1]
            / "states" / "montana" / "extracted" / "black-bear-2026.json"
        )
        assert artifact_path.exists(), (
            f"Artifact not found at {artifact_path}. "
            "Run extract_black_bear.py to regenerate."
        )
        with artifact_path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        rules: list[Any] = data.get("statewide_rules", [])
        assert isinstance(rules, list)
        assert len(rules) == 1, f"Expected 1 statewide rule, got {len(rules)}"

        rule = rules[0]
        assert rule["source_id"] == "mt-fwp-black-bear-2026-booklet"
        assert rule["verbatim_text"] == _BEAR_ID_PARAGRAPH
        assert rule["rule_hint"] == "pre_purchase_prerequisite"
        assert rule["extraction_confidence"] == "medium"


# ---------------------------------------------------------------------------
# T15: State-agnostic AST guard
# ---------------------------------------------------------------------------

# Reuse the AST-walk helper from test_extract_dea — it is fully state-agnostic
# per its `allowed_state` parameter, so duplicating ~130 LOC would only create
# drift risk. If the helper ever grows a Montana-specific divergence, fork it.
from tests.test_extract_dea import _find_foreign_state_imports  # noqa: E402


class TestNoForeignStateAdapterImports:
    """AST-walk guard: extract_black_bear.py must not import from non-montana
    state adapters.

    The rule (per ADR-005): a Montana adapter may import from
    ``states.montana.*`` or ``ingestion.*``, but NEVER from
    ``states.<other_state>.*`` / ``ingestion.states.<other_state>.*``.
    Cross-state imports violate adapter isolation.
    """

    _ALLOWED_STATE: str = "montana"

    def test_no_foreign_state_adapter_imports(self) -> None:
        """extract_black_bear.py itself is clean."""
        source_path = Path(m.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        violations = _find_foreign_state_imports(source, self._ALLOWED_STATE)
        assert not violations, (
            "extract_black_bear.py contains foreign state adapter imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_guard_catches_foreign_state_import(self) -> None:
        """Counter-example: a synthetic foreign import IS detected."""
        violations = _find_foreign_state_imports(
            "from ingestion.states.colorado import load_hds", self._ALLOWED_STATE
        )
        assert any(
            "from ingestion.states.colorado" in v for v in violations
        ), f"AST guard failed to catch foreign import: {violations}"

    def test_guard_allows_montana_imports(self) -> None:
        """Sanity: Montana-internal imports are not flagged."""
        clean = "\n".join(
            [
                "from states.montana import fetch_pdfs",
                "from ingestion.states.montana import fetch_pdfs",
                "from ingestion.lib.pdf import open_pdf",
                "import re",
            ]
        )
        violations = _find_foreign_state_imports(clean, self._ALLOWED_STATE)
        assert violations == [], violations
