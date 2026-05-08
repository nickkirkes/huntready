"""Unit tests for `states.montana.extract_dea` — DEA booklet extraction (S03.3 T11 + T12).

Test philosophy:
- All tests are hermetic: no real DEA PDF required. Tests that need a PDF use
  synthesized fixtures (``_synthesize_antelope_overlay_pdf``). The full DEA
  integration run is handled by T13's manual operator step.
- Only T12.7 (TestStatewideAntelopeOverlay) synthesizes a PDF; all other tests
  drive the public helpers directly with hand-crafted dict/list inputs.
- The determinism test is skipped in this unit-test file; it is validated
  end-to-end by T13's manual run (re-run + diff step).
"""

from __future__ import annotations

import ast
import json
import logging
from io import BytesIO
from pathlib import Path

import pytest

import states.montana.extract_dea as extract_dea
from ingestion.lib.pdf import (
    ConfidenceTier,
    PageReference,
    PdfExtractionError,
    open_pdf,
)
from states.montana.extract_dea import (
    DeaRowExtraction,
    DeaSectionExtraction,
    SeasonCoverage,
    SeasonWindow,
    _aggregate_section_season_windows,
    _assign_row_confidence,
    _extract_statewide_antelope_overlay,
    _normalize_cell,
    _normalize_header,
    _rejoin_hyphenated_linebreaks,
    _row_season_windows,
    _rows_to_license_extractions,
    _season_key_for_column,
    _sort_key,
    _weapon_override_for_column,
)

# ---------------------------------------------------------------------------
# T11: Test fixture helpers
# ---------------------------------------------------------------------------


def _simple_dea_table_data() -> tuple[list[str | None], list[list[str | None]]]:
    """Return (header_row, data_rows) matching the real DEA deer/elk table shape.

    Rows reflect real-PDF quirks discovered during T13 reconnaissance:
    - Column names carry "... SEASON DATES" suffix (not bare "GENERAL" etc.)
    - "-" is the absent-season sentinel (not empty string)
    - Species banner rows (["DEER", None, ...]) are skipped by the extractor
    - License code carry-forward: row 2 has None in LICENSE/PERMIT → inherits row 1
    """
    header_row: list[str | None] = [
        "LICENSE/PERMIT",
        "OPPORTUNITY",
        "APPLY BY DATE",
        "QUOTA",
        "QUOTA RANGE",
        "EARLY SEASON DATES",
        "ARCHERY ONLY SEASON DATES",
        "GENERAL SEASON DATES",
        "HERITAGE MUZZLELOADER SEASON DATES",
        "LATE SEASON DATES",
        "OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS",
    ]
    data_rows: list[list[str | None]] = [
        # Row 1: General Deer License — Either-sex WT (archery + general)
        [
            "General Deer License",
            "Either-sex White-tailed Deer",
            None,
            None,
            None,
            "-",
            "Sep 05-Oct 18",
            "Oct 24-Oct 30",
            "-",
            "-",
            None,
        ],
        # Row 2: same license (None → carry-forward), Antlered Buck MD
        # (asymmetric: also has heritage muzzleloader)
        [
            None,
            "Antlered Buck Mule Deer",
            None,
            None,
            None,
            "-",
            "Sep 05-Oct 18",
            "Oct 24-Nov 29",
            "Dec 12-Dec 20",
            "-",
            None,
        ],
        # Row 3: Deer B License (general only, with quota)
        [
            "124-00",
            "Antlerless WT",
            "Jun 1",
            "25",
            "25-500",
            "-",
            "-",
            "Oct 24-Nov 29",
            "-",
            "-",
            None,
        ],
    ]
    return header_row, data_rows


def _text_bearing_pdf_bytes(text: str) -> bytes:
    """Synthesize a minimal single-page PDF containing ``text``.

    Mirrors the identical helper in test_pdf.py — copied here because pytest
    test files are not import-stable (they are not importable as modules via
    normal imports).
    """
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines = escaped.split("\n")
    content_ops = ["BT", "/F1 12 Tf", "50 750 Td"]
    for i, line in enumerate(lines):
        if i > 0:
            content_ops.append("0 -14 Td")
        content_ops.append(f"({line}) Tj")
    content_ops.append("ET")
    stream = "\n".join(content_ops).encode("latin-1")

    objs: list[bytes] = []
    objs.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objs.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objs.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
        b"/BaseFont /Helvetica >> >> >> /Contents 4 0 R >>\nendobj\n"
    )
    objs.append(
        b"4 0 obj\n<< /Length "
        + str(len(stream)).encode("latin-1")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n"
    )

    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objs:
        offsets.append(out.tell())
        out.write(obj)
    xref_offset = out.tell()
    out.write(b"xref\n0 5\n")
    out.write(b"0000000000 65535 f\n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n\n".encode("latin-1"))
    out.write(
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("latin-1")
        + b"\n%%EOF\n"
    )
    return out.getvalue()


def _synthesize_antelope_overlay_pdf(
    quota: int = 5600,
    range_low: int = 1,
    range_high: int = 7500,
    window: str = "Aug. 15-Nov. 08",
) -> bytes:
    """Synthesize a single-page PDF containing the 900-20 antelope overlay prose.

    The text must satisfy ``re.search(r"900[-\\s]20", text)`` and contain the
    structured fields that ``_extract_statewide_antelope_overlay`` parses.
    The format mirrors the real DEA PDF's two-line block:

        Antelope License: 900-20 Either-sex June 1 {quota} 1-{range_high} - {window}
        ArchEquip only.
    """
    text = (
        f"Antelope License: 900-20 Either-sex June 1 "
        f"{quota:,} {range_low}-{range_high:,} - {window}\n"
        f"ArchEquip only."
    )
    return _text_bearing_pdf_bytes(text)


def _write_pdf(tmp_path: Path, name: str, data: bytes) -> Path:
    """Write ``data`` to ``tmp_path / name`` and return the path."""
    out = tmp_path / name
    out.write_bytes(data)
    return out


def _make_page_reference(page: int = 1) -> PageReference:
    """Return a minimal PageReference for use in tests."""
    return PageReference(
        pdf_filename="test.pdf",
        page_num_1based=page,
        bbox=None,
        extracted_at="2026-05-07T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# T12: Unit tests
# ---------------------------------------------------------------------------


class TestNormalizeCell:
    def test_strips_whitespace(self) -> None:
        assert _normalize_cell("  hello  ") == "hello"

    def test_collapses_internal_whitespace_runs(self) -> None:
        # 3+ spaces collapsed
        assert _normalize_cell("hello   world") == "hello world"
        # tabs and newlines also collapsed when run >= 3
        assert _normalize_cell("hello\t\t\tworld") == "hello world"
        # mixed whitespace run >= 3
        assert _normalize_cell("hello \t\n world") == "hello world"

    def test_returns_none_for_empty_or_whitespace(self) -> None:
        assert _normalize_cell("") is None
        assert _normalize_cell(None) is None
        assert _normalize_cell("   ") is None
        assert _normalize_cell("\t\n") is None

    def test_collapses_multiline(self) -> None:
        # Two-space separations (< 3) are NOT collapsed — only 3+ runs
        assert _normalize_cell("hello\n\n  world") == "hello world"


class TestRejoinHyphenatedLinebreaks:
    def test_rejoins_lowercase_bordered_hyphen(self) -> None:
        assert _rejoin_hyphenated_linebreaks("regu-\nlation") == "regulation"

    def test_does_not_rejoin_date_range(self) -> None:
        # Digit neighbors: not rejoined
        assert _rejoin_hyphenated_linebreaks("9/7-10/20") == "9/7-10/20"
        assert _rejoin_hyphenated_linebreaks("9/7-\n10/20") == "9/7-\n10/20"

    def test_does_not_rejoin_license_code(self) -> None:
        assert _rejoin_hyphenated_linebreaks("262-50") == "262-50"
        assert _rejoin_hyphenated_linebreaks("262-\n50") == "262-\n50"

    def test_does_not_rejoin_uppercase(self) -> None:
        # Uppercase neighbors: not rejoined
        assert _rejoin_hyphenated_linebreaks("ARCHERY-\nONLY") == "ARCHERY-\nONLY"


class TestColumnHeaderMapping:
    @pytest.mark.parametrize(
        "header,expected_season_key,expected_weapon_override",
        [
            ("EARLY SEASON DATES", "early_season", None),
            ("ARCHERY ONLY SEASON DATES", "archery_only", "archery"),
            ("GENERAL SEASON DATES", "general", None),
            ("HERITAGE MUZZLELOADER SEASON DATES", "heritage_muzzleloader", "muzzleloader"),
            ("LATE SEASON DATES", "late", None),
        ],
    )
    def test_season_column_mapping(
        self, header: str, expected_season_key: str, expected_weapon_override: str | None
    ) -> None:
        assert _season_key_for_column(header) == expected_season_key
        assert _weapon_override_for_column(header) == expected_weapon_override

    def test_case_insensitive_variant(self) -> None:
        assert _season_key_for_column("Archery Only Season Dates") == "archery_only"
        assert _weapon_override_for_column("Archery Only Season Dates") == "archery"

    def test_non_season_column_returns_none(self) -> None:
        assert _season_key_for_column("LICENSE/PERMIT") is None


class TestNormalizeHeader:
    def test_uppercases_and_collapses_whitespace(self) -> None:
        assert _normalize_header("  general season  ") == "GENERAL SEASON"

    def test_empty_or_none_returns_empty_string(self) -> None:
        assert _normalize_header("") == ""
        assert _normalize_header(None) == ""
        assert _normalize_header("   ") == ""

    def test_multiline_header_collapses(self) -> None:
        # Real DEA-PDF case: pdfplumber may return multi-line header cells
        assert _normalize_header("EARLY\nSEASON\nDATES") == "EARLY SEASON DATES"


class TestRowsToLicenseExtractions:
    def test_ab_pattern_with_asymmetric_season_coverage(self) -> None:
        """Row 1 has archery+general; row 2 has archery+general+heritage_muzzleloader.

        Tests AC: per-license season_coverage divergence within an HD is
        captured (row 1 heritage_muzzleloader=False, row 2 heritage_muzzleloader=True).
        """
        header_row, data_rows = _simple_dea_table_data()
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        results = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        assert len(results) == 3

        # Row 0: Either-sex WT — archery + general, no heritage
        assert results[0]["season_coverage"]["archery_only"] is True
        assert results[0]["season_coverage"]["general"] is True
        assert results[0]["season_coverage"]["heritage_muzzleloader"] is False

        # Row 1: Antlered Buck MD — archery + general + heritage_muzzleloader
        assert results[1]["season_coverage"]["archery_only"] is True
        assert results[1]["season_coverage"]["general"] is True
        assert results[1]["season_coverage"]["heritage_muzzleloader"] is True

    def test_license_code_carry_forward(self) -> None:
        """Row with None in LICENSE/PERMIT inherits the prior row's license code."""
        header_row, data_rows = _simple_dea_table_data()
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        results = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        # Row 0 has "General Deer License"; row 1 has None → inherits
        assert results[0]["license_code"] == "General Deer License"
        assert results[1]["license_code"] == "General Deer License"

    def test_quota_with_trailing_prose_parses_leading_int(self) -> None:
        """Cell like "75 (limited entry)" → quota=75."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT",
            "OPPORTUNITY",
            "APPLY BY DATE",
            "QUOTA",
            "QUOTA RANGE",
            "GENERAL SEASON DATES",
            "OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS",
        ]
        data_rows: list[list[str | None]] = [
            ["124-00", "Antlerless", None, "75 (limited entry)", None, "Oct 24-Nov 29", None],
        ]
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        results = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        assert results[0]["quota"] == 75

    def test_dash_sentinel_yields_false_coverage(self) -> None:
        """All season cells "-" → all season_coverage values False."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT",
            "OPPORTUNITY",
            "EARLY SEASON DATES",
            "ARCHERY ONLY SEASON DATES",
            "GENERAL SEASON DATES",
            "HERITAGE MUZZLELOADER SEASON DATES",
            "LATE SEASON DATES",
        ]
        data_rows: list[list[str | None]] = [
            ["124-00", "Antlerless", "-", "-", "-", "-", "-"],
        ]
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        results = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        assert len(results) == 1
        cov = results[0]["season_coverage"]
        assert cov["early_season"] is False
        assert cov["archery_only"] is False
        assert cov["general"] is False
        assert cov["heritage_muzzleloader"] is False
        assert cov["late"] is False

    def test_skips_species_banner_rows(self) -> None:
        """['DEER', None, None, ...] banner rows are skipped without raising."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT",
            "OPPORTUNITY",
            "GENERAL SEASON DATES",
        ]
        data_rows: list[list[str | None]] = [
            # Species banner row — should be silently skipped
            ["DEER", None, None],
            # Real data row
            ["124-00", "Antlerless", "Oct 24-Nov 29"],
        ]
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        results = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        # Only the real row should be emitted; banner silently skipped
        assert len(results) == 1
        assert results[0]["license_code"] == "124-00"


class TestAggregateSeasonWindows:
    def test_section_windows_carry_weapon_override(self) -> None:
        """Each season's weapon_type_override must match the column's expected value."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT",
            "OPPORTUNITY",
            "ARCHERY ONLY SEASON DATES",
            "GENERAL SEASON DATES",
            "HERITAGE MUZZLELOADER SEASON DATES",
        ]
        data_rows: list[list[str | None]] = [
            ["124-00", "Antlerless", "Sep 07-Oct 20", "Oct 26-Dec 01", "-"],
            ["124-10", "Buck", "-", "Oct 26-Dec 01", "Dec 02-Dec 15"],
        ]
        result = _aggregate_section_season_windows(header_row, data_rows)

        assert "archery_only" in result
        assert result["archery_only"]["window"] == "Sep 07-Oct 20"
        assert result["archery_only"]["weapon_type_override"] == "archery"

        assert "general" in result
        assert result["general"]["window"] == "Oct 26-Dec 01"
        assert result["general"]["weapon_type_override"] is None

        assert "heritage_muzzleloader" in result
        assert result["heritage_muzzleloader"]["window"] == "Dec 02-Dec 15"
        assert result["heritage_muzzleloader"]["weapon_type_override"] == "muzzleloader"

    def test_dash_sentinels_excluded(self) -> None:
        """Columns where all rows have "-" do not appear in section_windows."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT",
            "OPPORTUNITY",
            "EARLY SEASON DATES",
            "GENERAL SEASON DATES",
        ]
        data_rows: list[list[str | None]] = [
            ["124-00", "Antlerless", "-", "Oct 24-Nov 29"],
        ]
        result = _aggregate_section_season_windows(header_row, data_rows)
        assert "early_season" not in result
        assert "general" in result

    def test_no_season_columns_yields_empty_dict(self) -> None:
        """A header_row with no season columns produces an empty dict."""
        header_row: list[str | None] = ["LICENSE/PERMIT", "OPPORTUNITY", "QUOTA"]
        data_rows: list[list[str | None]] = [
            ["124-00", "Antlerless", "25"],
        ]
        result = _aggregate_section_season_windows(header_row, data_rows)
        assert result == {}


class TestRowSeasonWindows:
    def test_only_true_coverage_keys_returned(self) -> None:
        """season_windows contains only keys where coverage=True."""
        coverage = SeasonCoverage(
            early_season=False,
            archery_only=True,
            general=False,
            heritage_muzzleloader=False,
            late=False,
        )
        section_windows: dict[str, SeasonWindow] = {
            "archery_only": SeasonWindow(window="Sep 07-Oct 20", weapon_type_override="archery"),
            "general": SeasonWindow(window="Oct 26-Dec 01", weapon_type_override=None),
        }
        result = _row_season_windows(coverage, section_windows)
        assert list(result.keys()) == ["archery_only"]
        assert result["archery_only"]["window"] == "Sep 07-Oct 20"

    def test_all_false_coverage_yields_empty_dict(self) -> None:
        """All-False coverage → empty season_windows dict."""
        coverage = SeasonCoverage(
            early_season=False,
            archery_only=False,
            general=False,
            heritage_muzzleloader=False,
            late=False,
        )
        section_windows: dict[str, SeasonWindow] = {
            "general": SeasonWindow(window="Oct 26-Dec 01", weapon_type_override=None),
        }
        result = _row_season_windows(coverage, section_windows)
        assert result == {}


class TestStatewideAntelopeOverlay:
    def test_overlay_extracted_from_synthesized_pdf(self, tmp_path: Path) -> None:
        """Synthesize a PDF with the 900-20 prose; assert DeaSectionExtraction shape."""
        pdf_bytes = _synthesize_antelope_overlay_pdf(
            quota=5600, range_low=1, range_high=7500, window="Aug. 15-Nov. 08"
        )
        pdf_path = _write_pdf(tmp_path, "antelope-test.pdf", pdf_bytes)

        extracted_at = "2026-05-07T00:00:00Z"
        with open_pdf(pdf_path) as pdf:
            result = _extract_statewide_antelope_overlay(pdf, (1, 1), extracted_at)

        assert result["hd_number"] == "STATEWIDE"
        assert result["species_group"] == "antelope"
        assert len(result["rows"]) == 1

        row = result["rows"][0]
        assert row["license_code"] == "900-20"
        assert row["weapon_types"] == ["archery"]
        assert row["season_coverage"]["archery_only"] is True
        assert row["season_coverage"]["early_season"] is False
        assert row["season_coverage"]["general"] is False
        assert row["season_coverage"]["heritage_muzzleloader"] is False
        assert row["season_coverage"]["late"] is False

        # extracted_at is threaded through to the PageReference
        assert result["page_reference"]["extracted_at"] == extracted_at
        assert result["page_reference"]["page_num_1based"] == 1

    def test_overlay_missing_900_20_raises(self, tmp_path: Path) -> None:
        """PDF without 900-20 text → PdfExtractionError."""
        pdf_bytes = _text_bearing_pdf_bytes(
            "Some antelope content without the statewide overlay code here."
        )
        pdf_path = _write_pdf(tmp_path, "no-900-20.pdf", pdf_bytes)

        with open_pdf(pdf_path) as pdf:
            with pytest.raises(PdfExtractionError, match="900-20"):
                _extract_statewide_antelope_overlay(pdf, (1, 1), "2026-05-07T00:00:00Z")


class TestRowConfidence:
    def _make_row(
        self,
        license_code: str = "124-00",
        opportunity: str = "Antlerless",
        archery_only: bool = False,
        general: bool = True,
    ) -> DeaRowExtraction:
        coverage = SeasonCoverage(
            early_season=False,
            archery_only=archery_only,
            general=general,
            heritage_muzzleloader=False,
            late=False,
        )
        windows: dict[str, SeasonWindow] = {}
        if general:
            windows["general"] = SeasonWindow(
                window="Oct 24-Nov 29", weapon_type_override=None
            )
        return DeaRowExtraction(
            license_code=license_code,
            opportunity=opportunity,
            apply_by=None,
            quota=None,
            quota_range=None,
            season_coverage=coverage,
            season_windows=windows,
            weapon_types=["any_legal_weapon"],
            extras=None,
            extraction_confidence=ConfidenceTier.HIGH,
        )

    def test_table_source_with_hd_code_pattern_high(self) -> None:
        """license_code="124-00", non-empty opportunity, has season → HIGH."""
        row = self._make_row(license_code="124-00", opportunity="Antlerless", general=True)
        assert _assign_row_confidence(row, "table") == ConfidenceTier.HIGH

    def test_table_source_with_prose_license_medium(self) -> None:
        """Prose-style license code (e.g. "General Deer License") → MEDIUM."""
        row = self._make_row(
            license_code="General Deer License",
            opportunity="Either-sex WT",
            general=True,
        )
        assert _assign_row_confidence(row, "table") == ConfidenceTier.MEDIUM

    def test_table_source_with_compound_hd_code_high(self) -> None:
        """Compound code with embedded HD pattern (e.g. "Deer B License: 124-00") → HIGH.

        Real DEA cells often embed the HD code inside compound prose. The
        confidence check uses ``re.search`` so the pattern is found wherever
        it appears in the field, not just in pure-code form.
        """
        row = self._make_row(
            license_code="Deer B License: 124-00",
            opportunity="Antlerless",
            general=True,
        )
        assert _assign_row_confidence(row, "table") == ConfidenceTier.HIGH

    def test_table_source_with_zero_coverage_low(self) -> None:
        """HD-code format but all-False season_coverage → LOW."""
        row = self._make_row(
            license_code="124-00",
            opportunity="Antlerless",
            archery_only=False,
            general=False,
        )
        assert _assign_row_confidence(row, "table") == ConfidenceTier.LOW

    def test_prose_source_returns_medium(self) -> None:
        """source="prose" → always MEDIUM regardless of row content."""
        row = self._make_row(license_code="900-20", opportunity="Statewide", general=True)
        assert _assign_row_confidence(row, "prose") == ConfidenceTier.MEDIUM


class TestSortKey:
    def _make_section(self, species: str, hd_number: str) -> DeaSectionExtraction:
        return DeaSectionExtraction(
            hd_number=hd_number,
            hd_name="Test",
            species_group=species,
            license_year=2026,
            page_reference=_make_page_reference(),
            verbatim_text="",
            rows=[],
        )

    def test_species_and_hd_ordering(self) -> None:
        """deer < elk < antelope; numeric HDs sort numerically; STATEWIDE sorts last."""
        sections = [
            self._make_section("antelope", "STATEWIDE"),
            self._make_section("elk", "262"),
            self._make_section("deer", "100"),
            self._make_section("antelope", "501"),
            self._make_section("deer", "50"),
            self._make_section("elk", "001"),
        ]
        sections.sort(key=_sort_key)

        species_order = [s["species_group"] for s in sections]
        # All deer before elk before antelope
        assert species_order == ["deer", "deer", "elk", "elk", "antelope", "antelope"]

        # Within deer: numeric sort (50 < 100)
        deer_hds = [s["hd_number"] for s in sections if s["species_group"] == "deer"]
        assert deer_hds == ["50", "100"]

        # Within elk: numeric sort (001 < 262)
        elk_hds = [s["hd_number"] for s in sections if s["species_group"] == "elk"]
        assert elk_hds == ["001", "262"]

        # Within antelope: numeric before STATEWIDE
        antelope_hds = [s["hd_number"] for s in sections if s["species_group"] == "antelope"]
        assert antelope_hds == ["501", "STATEWIDE"]


class TestDeterministicJsonOutput:
    def test_determinism_requires_real_pdf(self) -> None:
        """Determinism is validated end-to-end by T13's manual run (re-run + diff step).

        This test exists as a placeholder and intentional skip so the test
        class surface is visible in CI output. The full extract() pipeline
        requires the real DEA PDF (gitignored) which is not present in the
        unit-test environment.
        """
        pytest.skip(
            "integration — requires real DEA PDF; determinism verified by T13 manual run"
        )


class TestNoForeignStateAdapterImports:
    """AST-walk guard: extract_dea.py must not import from other states' adapters.

    This is the per-Montana-adapter equivalent of test_pdf.py's
    TestPdfNoStateAdapterImports. The rule: montana's own adapter may import
    from ``states.montana.*`` or ``ingestion.*``, but NEVER from
    ``states.colorado.*``, ``ingestion.states.colorado.*``, or any other
    non-montana state path.
    """

    _ALLOWED_STATE: str = "montana"

    def test_no_foreign_state_adapter_imports(self) -> None:
        source_path = Path(extract_dea.__file__)
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                # Block any states.<other> import
                if module.startswith("states."):
                    state_slug = module.split(".")[1]
                    assert state_slug == self._ALLOWED_STATE, (
                        f"extract_dea.py imports from a foreign state adapter: "
                        f"`from {module} import ...` at line {node.lineno}. "
                        f"Only 'montana' state imports are permitted."
                    )
                # Block ingestion.states.<other> imports
                if module.startswith("ingestion.states."):
                    state_slug = module.split(".")[2]
                    assert state_slug == self._ALLOWED_STATE, (
                        f"extract_dea.py imports from a foreign state adapter: "
                        f"`from {module} import ...` at line {node.lineno}. "
                        f"Only 'montana' state imports are permitted."
                    )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith("states."):
                        state_slug = name.split(".")[1]
                        assert state_slug == self._ALLOWED_STATE, (
                            f"extract_dea.py imports a foreign state adapter: "
                            f"`import {name}` at line {node.lineno}"
                        )
                    if name.startswith("ingestion.states."):
                        state_slug = name.split(".")[2]
                        assert state_slug == self._ALLOWED_STATE, (
                            f"extract_dea.py imports a foreign state adapter: "
                            f"`import {name}` at line {node.lineno}"
                        )


# ---------------------------------------------------------------------------
# Post-review fix tests
# ---------------------------------------------------------------------------


class TestDashSentinelInNullableFields:
    """Fix 1 (CRITICAL): '-' sentinel must yield None in apply_by, quota_range, extras."""

    def test_dash_sentinel_yields_none_in_apply_by_quota_range_extras(self) -> None:
        """Hand-crafted row with '-' in apply_by, quota_range, and extras → all None."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT",
            "OPPORTUNITY",
            "APPLY BY DATE",
            "QUOTA",
            "QUOTA RANGE",
            "GENERAL SEASON DATES",
            "OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS",
        ]
        data_rows: list[list[str | None]] = [
            ["124-00", "Antlerless", "-", "25", "-", "Oct 24-Nov 29", "-"],
        ]
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        results = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        assert len(results) == 1
        row = results[0]
        assert row["apply_by"] is None, "apply_by '-' must become None"
        assert row["quota_range"] is None, "quota_range '-' must become None"
        assert row["extras"] is None, "extras '-' must become None"
        # Quota itself: "25" is a real value (not a dash sentinel)
        assert row["quota"] == 25


class TestNormalizeCellRejoinsHyphenatedLinebreaks:
    """Fix 2: _normalize_cell must wire through _rejoin_hyphenated_linebreaks."""

    def test_normalize_cell_rejoins_lowercase_hyphen(self) -> None:
        """'regu-\\nlation' → 'regulation' after cell normalization."""
        from states.montana.extract_dea import _normalize_cell

        assert _normalize_cell("regu-\nlation") == "regulation"

    def test_normalize_cell_preserves_date_range_hyphen(self) -> None:
        """'9/7-\\n10/20' — digit neighbors, NOT rejoined; single \\n survives strip."""
        from states.montana.extract_dea import _normalize_cell

        # The rejoin regex does NOT match digit-bordered hyphens; the \n stays
        # but a single \n is < 3 whitespace chars so it isn't collapsed by the
        # \s{3,} rule. strip() removes leading/trailing only.
        result = _normalize_cell("9/7-\n10/20")
        assert result is not None
        assert "-" in result  # hyphen preserved
        # The digit-neighbor case does NOT collapse the hyphen
        assert "9/7-" in result


class TestLoadExtractedAtFromManifest:
    """Fix 6: _load_extracted_at_from_manifest must validate type and non-empty."""

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        """No manifest file → PdfExtractionError."""
        from states.montana.extract_dea import _load_extracted_at_from_manifest

        fake_pdf = tmp_path / "test-2026-01-01.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        with pytest.raises(PdfExtractionError, match="manifest not found"):
            _load_extracted_at_from_manifest(fake_pdf)

    def test_missing_fetched_at_key_raises(self, tmp_path: Path) -> None:
        """Manifest present but missing 'fetched_at' key → PdfExtractionError."""
        from states.montana.extract_dea import _load_extracted_at_from_manifest

        fake_pdf = tmp_path / "test-2026-01-01.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        manifest = tmp_path / "test-2026-01-01-pdf-manifest.json"
        manifest.write_text(json.dumps({"pdf_sha256": "abc123"}))
        with pytest.raises(PdfExtractionError, match="missing 'fetched_at'"):
            _load_extracted_at_from_manifest(fake_pdf)

    def test_null_fetched_at_raises(self, tmp_path: Path) -> None:
        """fetched_at=null (JSON null) → PdfExtractionError (fix 6: type validation)."""
        from states.montana.extract_dea import _load_extracted_at_from_manifest

        fake_pdf = tmp_path / "test-2026-01-01.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        manifest = tmp_path / "test-2026-01-01-pdf-manifest.json"
        manifest.write_text(json.dumps({"fetched_at": None}))
        with pytest.raises(PdfExtractionError, match="invalid 'fetched_at'"):
            _load_extracted_at_from_manifest(fake_pdf)

    def test_empty_string_fetched_at_raises(self, tmp_path: Path) -> None:
        """fetched_at='' → PdfExtractionError (fix 6: non-empty validation)."""
        from states.montana.extract_dea import _load_extracted_at_from_manifest

        fake_pdf = tmp_path / "test-2026-01-01.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        manifest = tmp_path / "test-2026-01-01-pdf-manifest.json"
        manifest.write_text(json.dumps({"fetched_at": ""}))
        with pytest.raises(PdfExtractionError, match="invalid 'fetched_at'"):
            _load_extracted_at_from_manifest(fake_pdf)

    def test_valid_fetched_at_returns_string(self, tmp_path: Path) -> None:
        """Valid non-empty fetched_at string is returned as-is."""
        from states.montana.extract_dea import _load_extracted_at_from_manifest

        fake_pdf = tmp_path / "test-2026-01-01.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        manifest = tmp_path / "test-2026-01-01-pdf-manifest.json"
        manifest.write_text(json.dumps({"fetched_at": "2026-04-27T12:00:00Z"}))
        result = _load_extracted_at_from_manifest(fake_pdf)
        assert result == "2026-04-27T12:00:00Z"


class TestRowConfidenceProseCodeZeroCoverage:
    """Fix 9: prose-code rows with all-False season_coverage must emit WARNING."""

    def test_table_source_with_prose_code_zero_coverage_emits_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Prose-style license code + all-False coverage → MEDIUM + WARNING logged."""
        coverage = SeasonCoverage(
            early_season=False,
            archery_only=False,
            general=False,
            heritage_muzzleloader=False,
            late=False,
        )
        row = DeaRowExtraction(
            license_code="Region 5",
            opportunity="Doe/Fawn",
            apply_by=None,
            quota=None,
            quota_range=None,
            season_coverage=coverage,
            season_windows={},
            weapon_types=["any_legal_weapon"],
            extras=None,
            extraction_confidence=ConfidenceTier.MEDIUM,
        )
        with caplog.at_level(logging.WARNING, logger="states.montana.extract_dea"):
            result = _assign_row_confidence(row, "table")

        assert result == ConfidenceTier.MEDIUM
        assert any("all-False season_coverage" in msg for msg in caplog.messages), (
            f"Expected WARNING about all-False season_coverage; got: {caplog.messages}"
        )


class TestSkipFooterAndOverlayRows:
    """Verify row-level filters: 900-20 overlay and "Region N" footer rows.

    Both filters apply universally inside `_rows_to_license_extractions`,
    not just in the antelope branch. Cubic flagged these as P2: the overlay
    filter was previously hardcoded to position 0 (brittle to layout drift),
    and footer rows were deferred to S03.6 ingestion (which would require
    every downstream consumer to add its own filter).
    """

    def test_900_20_overlay_row_filtered_anywhere_in_row(self) -> None:
        """The overlay row is filtered regardless of which cell holds the code."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT", "OPPORTUNITY", "GENERAL SEASON DATES",
        ]
        # Two rows: a normal HD row + an overlay row where 900-20 is in cell 0
        data_rows: list[list[str | None]] = [
            ["124-00", "Antlerless", "Oct 24-Nov 29"],
            ["Antelope License: 900-20", "Either-sex", "Aug 15-Nov 8"],
        ]
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        result = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        assert len(result) == 1
        assert result[0]["license_code"] == "124-00"

    def test_900_20_overlay_filtered_when_in_non_zero_cell(self) -> None:
        """Overlay code in a non-zero cell is also filtered (layout-drift guard)."""
        header_row: list[str | None] = [
            "OPPORTUNITY", "LICENSE/PERMIT", "GENERAL SEASON DATES",
        ]
        data_rows: list[list[str | None]] = [
            ["Either-sex", "Antelope License: 900-20", "Aug 15-Nov 8"],
            ["Antlerless", "124-00", "Oct 24-Nov 29"],
        ]
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        result = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        assert len(result) == 1
        assert result[0]["license_code"] == "124-00"

    def test_region_footer_row_filtered(self) -> None:
        """Rows whose first cell is "Region N" are filtered as scope footers."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT", "OPPORTUNITY", "GENERAL SEASON DATES",
        ]
        data_rows: list[list[str | None]] = [
            ["124-00", "Antlerless", "Oct 24-Nov 29"],
            ["Region 4", "Antlerless Elk", None],  # footer — must be skipped
            ["Region 5", "Antlerless Elk", None],  # another footer
        ]
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        result = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        assert len(result) == 1
        assert result[0]["license_code"] == "124-00"
        assert all(
            not r["license_code"].startswith("Region ") for r in result
        )

    def test_region_footer_does_not_match_partial_strings(self) -> None:
        """The "Region N" filter is anchored — it doesn't match "Regional X" etc."""
        header_row: list[str | None] = [
            "LICENSE/PERMIT", "OPPORTUNITY", "GENERAL SEASON DATES",
        ]
        # "Regional Park" is not a footer — it's a (hypothetical) license name.
        data_rows: list[list[str | None]] = [
            ["Regional Park 5", "Antlerless", "Oct 24-Nov 29"],
        ]
        page_ref = _make_page_reference()
        section_windows = _aggregate_section_season_windows(header_row, data_rows)
        result = _rows_to_license_extractions(
            header_row, data_rows, page_ref, section_windows
        )
        # The non-footer row survives — the regex is anchored to ^Region\s+\d+$
        assert len(result) == 1
        assert result[0]["license_code"] == "Regional Park 5"
