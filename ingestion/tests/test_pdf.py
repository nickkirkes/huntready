"""Unit tests for `ingestion.lib.pdf` — state-agnostic PDF extraction primitives."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pypdf
import pytest

from ingestion.lib import pdf
from ingestion.lib.pdf import (
    ConfidenceTier,
    PageReference,
    PdfExtractionError,
    demote_one_tier,
    extract_tables,
    extract_text,
    find_section,
    iter_pages,
    min_tier,
    open_pdf,
    page_reference_to_str,
    split_valid_gmus,
)


# --------------------------------------------------------------------------- #
# Test helpers (module-local, mirroring `test_pdf_fetch.py`'s pattern)        #
# --------------------------------------------------------------------------- #


def _blank_pdf_bytes() -> bytes:
    """A minimal valid 1-page PDF with no text content (via `pypdf.PdfWriter`)."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _multi_blank_pdf_bytes(n: int) -> bytes:
    """A minimal valid n-page PDF with no text content."""
    writer = pypdf.PdfWriter()
    for _ in range(n):
        writer.add_blank_page(width=612, height=792)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _text_bearing_pdf_bytes(text: str) -> bytes:
    """A minimal hand-crafted PDF with a single-page text content stream
    containing ``text``.

    Used for testing whitespace and line-break preservation in
    ``extract_text``. pypdf has no convenient text-write API and adding
    ``reportlab`` as a test dep is overkill for one fixture, so we hand-craft
    the PDF byte-stream. The text is embedded as a literal in a ``BT … ET``
    content stream; parens and backslashes in ``text`` are escaped per the
    PDF spec. Newlines split into separate ``Tj`` calls separated by ``Td``
    line moves.
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


def _write_pdf(tmp_path: Path, name: str, data: bytes) -> Path:
    out = tmp_path / name
    out.write_bytes(data)
    return out


# --------------------------------------------------------------------------- #
# ConfidenceTier framework tests (ADR-017)                                    #
# --------------------------------------------------------------------------- #


class TestConfidenceTier:
    def test_string_value_round_trips_with_confidence_literal(self) -> None:
        # The `str, Enum` mixin makes instances == their string values, so
        # a tier can be written directly to `regulation_record.confidence`.
        assert ConfidenceTier.HIGH == "high"
        assert ConfidenceTier.MEDIUM == "medium"
        assert ConfidenceTier.LOW == "low"

    def test_rank_ordering(self) -> None:
        assert ConfidenceTier.LOW.rank < ConfidenceTier.MEDIUM.rank
        assert ConfidenceTier.MEDIUM.rank < ConfidenceTier.HIGH.rank

    def test_lt_uses_rank_not_string(self) -> None:
        # Custom __lt__ takes precedence over the `str` mixin's __lt__ in MRO.
        assert ConfidenceTier.LOW < ConfidenceTier.MEDIUM
        assert ConfidenceTier.MEDIUM < ConfidenceTier.HIGH
        # Sanity: the lexicographic ordering would put HIGH between LOW and
        # MEDIUM (h < l < m). Our __lt__ does NOT do that.
        assert not ConfidenceTier.HIGH < ConfidenceTier.LOW

    def test_lt_returns_notimplemented_for_non_tier(self) -> None:
        # Comparing to a non-tier should not assert True/False.
        result = ConfidenceTier.HIGH.__lt__("medium")
        assert result is NotImplemented


class TestMinTier:
    """AC #5: tier-rank MIN, NOT lexicographic — explicit trap cases."""

    def test_high_low_returns_low(self) -> None:
        assert min_tier([ConfidenceTier.HIGH, ConfidenceTier.LOW]) is ConfidenceTier.LOW

    def test_medium_high_returns_medium(self) -> None:
        assert min_tier([ConfidenceTier.MEDIUM, ConfidenceTier.HIGH]) is ConfidenceTier.MEDIUM

    def test_three_high_returns_high(self) -> None:
        tiers = [ConfidenceTier.HIGH, ConfidenceTier.HIGH, ConfidenceTier.HIGH]
        assert min_tier(tiers) is ConfidenceTier.HIGH

    def test_single_low_returns_low(self) -> None:
        assert min_tier([ConfidenceTier.LOW]) is ConfidenceTier.LOW

    def test_lexicographic_trap_explicit(self) -> None:
        """Direct guard against the lexicographic regression — three checks:

        1. `min_tier` returns LOW (the rank-correct answer for HIGH+MEDIUM+LOW).
        2. `min(tiers, key=lambda t: t.value)` (a stand-in for "what would happen
           if a refactor compared by string value") returns HIGH. This proves
           the trap is real for THIS enum, not just for plain strings.
        3. Bare `min` on the raw strings returns "high" — documentation of the
           original Python idiom that motivated the explicit `key=` form.
        """
        tiers = [ConfidenceTier.HIGH, ConfidenceTier.MEDIUM, ConfidenceTier.LOW]
        assert min_tier(tiers) is ConfidenceTier.LOW
        assert min(tiers, key=lambda t: t.value) is ConfidenceTier.HIGH
        assert min(["high", "low", "medium"]) == "high"

    def test_empty_iterable_raises(self) -> None:
        with pytest.raises(PdfExtractionError, match="empty"):
            min_tier([])

    def test_iterator_consumed_once(self) -> None:
        # Generator input must work even though min_tier converts to list internally.
        gen = (t for t in [ConfidenceTier.HIGH, ConfidenceTier.LOW])
        assert min_tier(gen) is ConfidenceTier.LOW


class TestDemoteOneTier:
    def test_high_demotes_to_medium(self) -> None:
        assert demote_one_tier(ConfidenceTier.HIGH) is ConfidenceTier.MEDIUM

    def test_medium_demotes_to_low(self) -> None:
        assert demote_one_tier(ConfidenceTier.MEDIUM) is ConfidenceTier.LOW

    def test_low_clamps_at_low(self) -> None:
        assert demote_one_tier(ConfidenceTier.LOW) is ConfidenceTier.LOW


# --------------------------------------------------------------------------- #
# PageReference + page_reference_to_str                                       #
# --------------------------------------------------------------------------- #


class TestPageReference:
    def test_collapse_to_str(self) -> None:
        ref: PageReference = {
            "pdf_filename": "deer-elk-antelope-2025-2026.pdf",
            "page_num_1based": 42,
            "bbox": (50.0, 100.0, 500.0, 200.0),
            "extracted_at": "2026-05-05T20:00:00+00:00",
        }
        assert page_reference_to_str(ref) == "deer-elk-antelope-2025-2026.pdf:p42"

    def test_collapse_drops_bbox_when_none(self) -> None:
        ref: PageReference = {
            "pdf_filename": "booklet.pdf",
            "page_num_1based": 7,
            "bbox": None,
            "extracted_at": "2026-05-05T20:00:00+00:00",
        }
        assert page_reference_to_str(ref) == "booklet.pdf:p7"

    def test_collapse_format_is_deterministic(self) -> None:
        # Same inputs → same output, every call. The format string is the
        # entirety of the contract; this test would fail if a future edit
        # introduced a timestamp, hash, or other variability.
        ref: PageReference = {
            "pdf_filename": "x.pdf",
            "page_num_1based": 1,
            "bbox": None,
            "extracted_at": "2026-05-05T20:00:00+00:00",
        }
        assert page_reference_to_str(ref) == page_reference_to_str(ref)
        assert page_reference_to_str(ref) == "x.pdf:p1"


# --------------------------------------------------------------------------- #
# open_pdf + PdfDocument context manager                                      #
# --------------------------------------------------------------------------- #


class TestOpenPdf:
    def test_open_returns_pdf_document(self, tmp_path: Path) -> None:
        path = _write_pdf(tmp_path, "test.pdf", _blank_pdf_bytes())
        with open_pdf(path) as doc:
            assert doc.filename == "test.pdf"
            assert doc.path == path
            assert len(doc.pages) == 1

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PdfExtractionError, match="not found"):
            open_pdf(tmp_path / "does-not-exist.pdf")

    def test_invalid_pdf_raises(self, tmp_path: Path) -> None:
        bad = _write_pdf(tmp_path, "bad.pdf", b"not a real pdf at all")
        with pytest.raises(PdfExtractionError, match="failed to open PDF"):
            open_pdf(bad)


# --------------------------------------------------------------------------- #
# iter_pages                                                                  #
# --------------------------------------------------------------------------- #


class TestIterPages:
    def test_yields_all_pages_with_1based_numbers(self, tmp_path: Path) -> None:
        path = _write_pdf(tmp_path, "three.pdf", _multi_blank_pdf_bytes(3))
        with open_pdf(path) as doc:
            page_nums = [n for n, _page in iter_pages(doc, 1, 3)]
        assert page_nums == [1, 2, 3]

    def test_yields_single_page_range(self, tmp_path: Path) -> None:
        path = _write_pdf(tmp_path, "three.pdf", _multi_blank_pdf_bytes(3))
        with open_pdf(path) as doc:
            page_nums = [n for n, _page in iter_pages(doc, 2, 2)]
        assert page_nums == [2]

    def test_start_below_one_raises(self, tmp_path: Path) -> None:
        path = _write_pdf(tmp_path, "three.pdf", _multi_blank_pdf_bytes(3))
        with open_pdf(path) as doc:
            with pytest.raises(PdfExtractionError, match=r">= 1"):
                list(iter_pages(doc, 0, 2))

    def test_end_below_start_raises(self, tmp_path: Path) -> None:
        path = _write_pdf(tmp_path, "three.pdf", _multi_blank_pdf_bytes(3))
        with open_pdf(path) as doc:
            with pytest.raises(PdfExtractionError, match=r">= start"):
                list(iter_pages(doc, 2, 1))

    def test_end_exceeds_page_count_raises(self, tmp_path: Path) -> None:
        path = _write_pdf(tmp_path, "three.pdf", _multi_blank_pdf_bytes(3))
        with open_pdf(path) as doc:
            with pytest.raises(PdfExtractionError, match="exceeds PDF page count"):
                list(iter_pages(doc, 1, 5))


# --------------------------------------------------------------------------- #
# extract_text                                                                #
# --------------------------------------------------------------------------- #


class TestExtractText:
    def test_blank_pdf_returns_empty_string(self, tmp_path: Path) -> None:
        path = _write_pdf(tmp_path, "blank.pdf", _blank_pdf_bytes())
        with open_pdf(path) as doc:
            assert extract_text(doc.pages[0]) == ""

    def test_text_and_linebreaks_preserved(self, tmp_path: Path) -> None:
        # Hand-crafted PDF with "hello world\nlinebreak" — the `Td 0 -14` line
        # move yields a `\n` in pdfplumber's extraction. The presence + ordering
        # checks lock the contract WITHOUT asserting specific whitespace counts
        # (pdfplumber's word-grouping collapses repeated spaces — that's a
        # documented platform behavior, not a bug we need to assert against).
        path = _write_pdf(
            tmp_path, "text.pdf", _text_bearing_pdf_bytes("hello world\nlinebreak")
        )
        with open_pdf(path) as doc:
            result = extract_text(doc.pages[0])
        assert "hello" in result
        assert "world" in result
        assert "linebreak" in result
        assert result.index("hello") < result.index("world") < result.index("linebreak")

    def test_bbox_crop_excludes_outside_text(self, tmp_path: Path) -> None:
        # Two text segments at different y-positions (split by `\n`, which
        # `_text_bearing_pdf_bytes` translates into `0 -14 Td` between the two
        # `Tj` calls). Crop to a bbox covering only the top line. Bottom line
        # text must NOT appear in the cropped result.
        path = _write_pdf(
            tmp_path, "two.pdf", _text_bearing_pdf_bytes("topline\nbottomline")
        )
        with open_pdf(path) as doc:
            page = doc.pages[0]
            # pdfplumber character positions (measured from page top):
            #   "topline"    chars: top≈32.5, bottom≈44.5
            #   "bottomline" chars: top≈46.5, bottom≈58.5
            # A bbox y-extent of 45.0 sits between the two bottom edges,
            # capturing "topline" and excluding "bottomline".
            top_only = extract_text(page, bbox=(0.0, 0.0, 612.0, 45.0))
            assert "topline" in top_only
            assert "bottomline" not in top_only

    def test_no_layout_kwarg_passed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # Regression guard: a future edit must NOT pass `layout=True` to
        # pdfplumber's extract_text — that would inject synthetic spaces and
        # violate the no-additional-normalization posture (ADR-008 boundary).
        captured_kwargs: dict[str, object] = {}
        path = _write_pdf(tmp_path, "blank.pdf", _blank_pdf_bytes())
        with open_pdf(path) as doc:
            page = doc.pages[0]
            original = type(page).extract_text

            def spy(self: object, **kwargs: object) -> str:
                captured_kwargs.update(kwargs)
                return original(self, **kwargs)

            monkeypatch.setattr(type(page), "extract_text", spy)
            extract_text(page)
        assert "layout" not in captured_kwargs


# --------------------------------------------------------------------------- #
# extract_tables                                                              #
# --------------------------------------------------------------------------- #


class TestExtractTables:
    def test_table_with_headers_and_rows(self) -> None:
        from unittest.mock import MagicMock

        from pdfplumber.page import Page as PdfPlumberPage

        fake_table = MagicMock()
        fake_table.bbox = (10.0, 20.0, 100.0, 200.0)
        fake_table.extract.return_value = [
            ["Hunting District", "REG"],
            ["123", "verbatim text"],
            ["456", "more text"],
        ]
        page = MagicMock(spec=PdfPlumberPage)
        page.find_tables.return_value = [fake_table]

        result = extract_tables(page)
        assert len(result) == 1
        match = result[0]
        assert match["bbox"] == (10.0, 20.0, 100.0, 200.0)
        assert match["headers"] == ["Hunting District", "REG"]
        assert match["rows"] == [["123", "verbatim text"], ["456", "more text"]]
        page.find_tables.assert_called_once_with()

    def test_empty_table_yields_empty_headers_and_rows(self) -> None:
        from unittest.mock import MagicMock

        from pdfplumber.page import Page as PdfPlumberPage

        fake_table = MagicMock()
        fake_table.bbox = (0.0, 0.0, 1.0, 1.0)
        fake_table.extract.return_value = []
        page = MagicMock(spec=PdfPlumberPage)
        page.find_tables.return_value = [fake_table]

        result = extract_tables(page)
        assert result == [
            {"bbox": (0.0, 0.0, 1.0, 1.0), "headers": [], "rows": []}
        ]

    def test_no_tables_yields_empty_list(self) -> None:
        from unittest.mock import MagicMock

        from pdfplumber.page import Page as PdfPlumberPage

        page = MagicMock(spec=PdfPlumberPage)
        page.find_tables.return_value = []

        assert extract_tables(page) == []

    def test_empty_table_emits_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Located-but-unparseable tables silently became empty TableMatch in
        # an earlier draft — that risked downstream silent garbage. The warning
        # surfaces the ambiguity for operators inspecting the log.
        from unittest.mock import MagicMock

        from pdfplumber.page import Page as PdfPlumberPage

        fake_table = MagicMock()
        fake_table.bbox = (10.0, 20.0, 100.0, 200.0)
        fake_table.extract.return_value = []
        page = MagicMock(spec=PdfPlumberPage)
        page.find_tables.return_value = [fake_table]

        with caplog.at_level("WARNING", logger="ingestion.lib.pdf"):
            extract_tables(page)

        assert any(
            "Table.extract() returned no rows" in record.message
            for record in caplog.records
        )

    def test_settings_forwarded_to_find_tables(self) -> None:
        from unittest.mock import MagicMock

        from pdfplumber.page import Page as PdfPlumberPage

        page = MagicMock(spec=PdfPlumberPage)
        page.find_tables.return_value = []

        settings = {"vertical_strategy": "lines"}
        extract_tables(page, settings=settings)

        page.find_tables.assert_called_once_with(table_settings=settings)


# --------------------------------------------------------------------------- #
# find_section                                                                #
# --------------------------------------------------------------------------- #


class TestFindSection:
    def test_returns_first_match_with_page_num(self) -> None:
        from unittest.mock import MagicMock

        page1 = MagicMock()
        page1.search.return_value = []
        page2 = MagicMock()
        page2.search.return_value = [
            {
                "x0": 50.0,
                "top": 100.0,
                "x1": 200.0,
                "bottom": 120.0,
                "text": "Section A",
            }
        ]
        page3 = MagicMock()
        page3.search.return_value = []  # never reached

        doc = MagicMock(spec=pdf.PdfDocument)
        doc.pages = [page1, page2, page3]

        result = find_section(doc, r"Section\s+A")
        assert result == (2, (50.0, 100.0, 200.0, 120.0))
        page1.search.assert_called_once()
        page2.search.assert_called_once()
        page3.search.assert_not_called()

    def test_not_found_returns_none(self) -> None:
        from unittest.mock import MagicMock

        page1 = MagicMock()
        page1.search.return_value = []
        page2 = MagicMock()
        page2.search.return_value = []

        doc = MagicMock(spec=pdf.PdfDocument)
        doc.pages = [page1, page2]

        assert find_section(doc, r"Nope") is None

    def test_pattern_forwarded_with_regex_true(self) -> None:
        from unittest.mock import MagicMock

        page1 = MagicMock()
        page1.search.return_value = [
            {"x0": 0.0, "top": 0.0, "x1": 1.0, "bottom": 1.0, "text": "x"}
        ]
        doc = MagicMock(spec=pdf.PdfDocument)
        doc.pages = [page1]

        find_section(doc, r"x")
        # The wrapper must pass `regex=True` so the caller's pattern is treated
        # as a regex (the default). If a refactor switched to `regex=False`,
        # caller patterns containing `\s` etc. would silently be treated as
        # literal — this test catches that.
        call_kwargs = page1.search.call_args.kwargs
        assert call_kwargs.get("regex") is True


# --------------------------------------------------------------------------- #
# State-agnostic guard (ADR-005)                                              #
# --------------------------------------------------------------------------- #


class TestPdfNoStateAdapterImports:
    """The shared library must remain state-agnostic per ADR-005 — no imports
    from any state adapter and no state-specific identifiers in the source.
    Mirrors `test_pdf_fetch.py::TestFetchPdfNoStateAdapterImports` exactly,
    one class per lib file (the `__file__` differs).

    State adapters live at `states/<slug>/` and are imported as
    `from states.<slug>.X import Y` (the actual project form per the
    namespace-package layout documented in `.roughly/known-pitfalls.md`).
    The legacy `from ingestion.states.X import Y` form is also blocked
    because it neither resolves at runtime nor would be acceptable if it did.
    """

    # ADR-007 V1 seed states. Add new state slugs here as they are introduced
    # — the test will then guard the shared library against accidental
    # state-specific identifiers for the new state.
    _KNOWN_STATE_SLUGS: tuple[str, ...] = ("montana", "colorado")

    def test_no_state_adapter_imports_in_pdf(self) -> None:
        import ast

        source = Path(pdf.__file__).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("states."), (
                    f"pdf.py imports from a state adapter: "
                    f"`from {module} import ...` at line {node.lineno}"
                )
                assert not module.startswith("ingestion.states."), (
                    f"pdf.py imports from a state adapter: "
                    f"`from {module} import ...` at line {node.lineno}"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    assert name != "states" and not name.startswith("states."), (
                        f"pdf.py imports a state adapter: "
                        f"`import {name}` at line {node.lineno}"
                    )
                    assert not name.startswith("ingestion.states."), (
                        f"pdf.py imports a state adapter: "
                        f"`import {name}` at line {node.lineno}"
                    )

    def test_no_state_specific_identifiers_in_pdf(self) -> None:
        source_lower = Path(pdf.__file__).read_text().lower()
        for slug in self._KNOWN_STATE_SLUGS:
            assert slug not in source_lower, (
                f"pdf.py contains the state slug {slug!r} — "
                f"state-specific code belongs in states/{slug}/, not in the "
                f"shared library (ADR-005)."
            )


class TestWriteExtractionArtifact:
    """Unit tests for ``pdf.write_extraction_artifact`` — the canonical
    one-record-per-line serializer for committed extraction artifacts."""

    def test_one_record_per_array_line(self, tmp_path: Path) -> None:
        out = tmp_path / "a.json"
        pdf.write_extraction_artifact([{"b": 1, "a": 2}, {"c": 3}], out)
        lines = out.read_text(encoding="utf-8").splitlines()
        # "[" + one line per record + "]" = 4 lines for 2 records.
        assert lines[0] == "["
        assert lines[-1] == "]"
        assert len(lines) == 4

    def test_roundtrips_via_json_load(self, tmp_path: Path) -> None:
        import json

        records = [{"x": 1}, {"y": "two"}]
        out = tmp_path / "a.json"
        pdf.write_extraction_artifact(records, out)
        assert json.loads(out.read_text(encoding="utf-8")) == records

    def test_keys_sorted_within_each_record(self, tmp_path: Path) -> None:
        out = tmp_path / "a.json"
        pdf.write_extraction_artifact([{"b": 1, "a": 2}], out)
        # sort_keys=True → "a" precedes "b" in the serialized record.
        record_line = out.read_text(encoding="utf-8").splitlines()[1]
        assert record_line.index('"a"') < record_line.index('"b"')

    def test_embedded_newline_escaped_stays_one_line(self, tmp_path: Path) -> None:
        import json

        out = tmp_path / "a.json"
        pdf.write_extraction_artifact([{"v": "line1\nline2"}], out)
        # The newline inside the value is JSON-escaped, so the record is still
        # exactly one physical line: "[" + record + "]" = 3 lines.
        assert len(out.read_text(encoding="utf-8").splitlines()) == 3
        assert json.loads(out.read_text(encoding="utf-8")) == [{"v": "line1\nline2"}]

    def test_empty_records(self, tmp_path: Path) -> None:
        out = tmp_path / "a.json"
        pdf.write_extraction_artifact([], out)
        assert out.read_text(encoding="utf-8") == "[]\n"

    def test_deterministic_same_bytes(self, tmp_path: Path) -> None:
        records = [{"b": 1, "a": 2}, {"z": [3, 2, 1]}]
        o1, o2 = tmp_path / "1.json", tmp_path / "2.json"
        pdf.write_extraction_artifact(records, o1)
        pdf.write_extraction_artifact(records, o2)
        assert o1.read_bytes() == o2.read_bytes()

    def test_creates_parent_and_leaves_no_tmp(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "dir" / "a.json"
        pdf.write_extraction_artifact([{"a": 1}], out)
        assert out.exists()
        assert not (out.parent / (out.name + ".tmp")).exists()


# --------------------------------------------------------------------------- #
# split_valid_gmus                                                             #
# --------------------------------------------------------------------------- #


class TestSplitValidGmus:
    """Unit tests for ``pdf.split_valid_gmus`` — CPW Valid-GMUs cell splitter."""

    # --- None / empty inputs ------------------------------------------------

    def test_none_returns_none_none(self) -> None:
        assert split_valid_gmus(None) == (None, None)

    def test_whitespace_only_returns_none_none(self) -> None:
        assert split_valid_gmus("   ") == (None, None)

    # --- Pure GMU cells (no qualifier) — must be returned UNCHANGED ----------

    def test_pure_gmu_list_returned_unchanged(self) -> None:
        # No reformatting: the original string is returned as-is.
        assert split_valid_gmus("83, 85, 140") == ("83, 85, 140", None)

    def test_pure_gmu_list_with_newline_returned_unchanged(self) -> None:
        # Newlines inside a pure-GMU cell must be preserved verbatim.
        assert split_valid_gmus("83, 85,\n140") == ("83, 85,\n140", None)

    def test_pure_gmu_list_multi_newline_unchanged(self) -> None:
        # Several GMUs split across multiple lines — still pure, still unchanged.
        assert split_valid_gmus("12, 13,\n23,\n24") == ("12, 13,\n23,\n24", None)

    # --- GMUs + exclusion-clause qualifier ----------------------------------

    def test_gmus_with_except_qualifier(self) -> None:
        assert split_valid_gmus(
            "83, 85, 140, 851\nExcept Bosque del Oso SWA"
        ) == ("83, 85, 140, 851", "Except Bosque del Oso SWA")

    def test_gmus_with_private_land_qualifier(self) -> None:
        assert split_valid_gmus(
            "12, 13, 23, 24\nprivate land only"
        ) == ("12, 13, 23, 24", "private land only")

    # --- Leading 'New' marker -----------------------------------------------

    def test_new_marker_before_gmus_goes_to_qualifier(self) -> None:
        # 'New' is a leading marker: it moves to qualifier_tokens, not gmu_tokens.
        assert split_valid_gmus(
            "New 3, 11,\n211, 301\nprivate land only"
        ) == ("3, 11, 211, 301", "New private land only")

    def test_new_alone_returns_none_qualifier(self) -> None:
        # 'New' with no GMUs → clean is None, qualifier is 'New'.
        assert split_valid_gmus("New") == (None, "New")

    # --- Embedded GMU numbers in qualifier must NOT be promoted --------------

    def test_embedded_gmu_in_note_stays_in_qualifier(self) -> None:
        result = split_valid_gmus(
            "12, 13, 23, 24, 25, 26,\n33, 34, 131, 231\n"
            "Note: No hunting access to\nGMU 211."
        )
        assert result == (
            "12, 13, 23, 24, 25, 26, 33, 34, 131, 231",
            "Note: No hunting access to GMU 211.",
        )

    def test_embedded_exclusion_211_not_in_clean_list(self) -> None:
        # Explicit assertion that 211 (mentioned in the Note) is NOT a valid GMU.
        clean, _qualifier = split_valid_gmus(
            "12, 13, 23, 24, 25, 26,\n33, 34, 131, 231\n"
            "Note: No hunting access to\nGMU 211."
        )
        assert clean is not None
        assert "211" not in clean.split(", ")

    def test_private_land_in_gmus_stay_in_qualifier(self) -> None:
        # 'and' triggers qualifier; the 12/23/24 that follow are NOT promoted.
        assert split_valid_gmus(
            "11, 13, 22, 131, 211, 231 and private land in 12, 23, 24"
        ) == ("11, 13, 22, 131, 211, 231", "and private land in 12, 23, 24")

    # --- '+' connector / named-area qualifier --------------------------------

    def test_gmu_plus_named_area(self) -> None:
        assert split_valid_gmus("851 + Bosque del Oso SWA only") == (
            "851",
            "+ Bosque del Oso SWA only",
        )

    def test_gmu_plus_named_area_with_newlines(self) -> None:
        # '+' token is not a GMU token → qualifier boundary; prose collapsed.
        assert split_valid_gmus("851 +\nBosque del Oso\nSWA only") == (
            "851",
            "+ Bosque del Oso SWA only",
        )

    # --- No leading GMUs (qualifier only) ------------------------------------

    def test_qualifier_only_no_gmus_returns_none_clean(self) -> None:
        assert split_valid_gmus("private land only") == (None, "private land only")

    # --- GMUs without comma separators (space-only separation) --------------

    def test_gmus_with_inline_prose_no_comma(self) -> None:
        # 'private' is not a GMU token → boundary fires immediately after 441.
        assert split_valid_gmus(
            "4, 5, 14, 214, 441 private land only"
        ) == ("4, 5, 14, 214, 441", "private land only")
