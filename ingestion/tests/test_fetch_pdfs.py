"""Unit tests for states.montana.fetch_pdfs orchestrator.

Focused on orchestrator-level behavior that is not covered by test_pdf_fetch.py:
the aggregation loop, the page-count drift-marker write, and the empty-yaml
fail-loud guard. The pdf_fetch.fetch_pdf call is mocked — its behavior is
covered by test_pdf_fetch.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ingestion.lib.pdf_fetch import PdfFetchError, PdfMetadata
from states.montana import fetch_pdfs


def _make_metadata(
    *,
    citation_id: str = "test-doc",
    publication_date: str = "2026-01-01",
    page_count: int = 10,
) -> PdfMetadata:
    """Build a PdfMetadata for stubbing fetch_pdf return values."""
    return PdfMetadata(
        filename=f"{citation_id}-{publication_date}.pdf",
        pdf_sha256="0" * 64,
        page_count=page_count,
        fetched_at="2026-05-04T22:00:00+00:00",
        source_url="https://example.com/x.pdf",
        document_type="annual_regulations",
        publication_date=publication_date,
        citation_id=citation_id,
    )


def _write_minimal_sources_yaml(path: Path, *, expected_pages: int) -> None:
    """Write a single-entry sources.yaml at ``path``."""
    path.write_text(
        f"""\
pdfs:
  - id: test-doc
    agency: Test Agency
    title: "Test Document"
    url: "https://example.com/x.pdf"
    expected_page_count: {expected_pages}
    expected_sha256: unknown
    document_type: annual_regulations
    publication_date: "2026-01-01"
""",
        encoding="utf-8",
    )


class TestPageCountMismatchWritesMarker:
    """When fetch_pdf returns a page_count that disagrees with sources.yaml's
    expected_page_count, the orchestrator must write a *-pending-reextraction.flag
    so subsequent runs (and downstream stories) block until the operator
    acknowledges the structural drift."""

    def test_writes_marker_with_expected_and_observed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        _write_minimal_sources_yaml(sources_path, expected_pages=10)

        # Stub fetch_pdf so it returns a metadata with a *different* page count.
        # The PDF / manifest writes are not exercised here — only the
        # orchestrator's reaction to the mismatch is.
        stub = MagicMock(return_value=_make_metadata(page_count=9))
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError, match="page count mismatch"):
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])

        marker_path = fixture_dir / "test-doc-2026-01-01-pending-reextraction.flag"
        assert marker_path.exists(), "page-count mismatch must write a drift marker"
        marker_text = marker_path.read_text(encoding="utf-8")
        assert "Page count mismatch" in marker_text
        assert "expected_pages: 10" in marker_text
        assert "observed_pages: 9" in marker_text
        assert "test-doc" in marker_text


class TestEmptyYamlFailsLoud:
    """An empty sources.yaml must raise rather than silently succeed."""

    def test_no_pdfs_key_raises(self, tmp_path: Path) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        sources_path.write_text("other_top_level_key: []\n", encoding="utf-8")

        with pytest.raises(PdfFetchError, match="no entries"):
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])

    def test_empty_pdfs_list_raises(self, tmp_path: Path) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        sources_path.write_text("pdfs: []\n", encoding="utf-8")

        with pytest.raises(PdfFetchError, match="no entries"):
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])


class TestEmptyUrlEntryFailsLoud:
    """An entry with an empty url must produce an aggregated failure rather
    than being silently skipped."""

    def test_empty_url_in_entry_aggregated_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        sources_path.write_text(
            """\
pdfs:
  - id: empty-url-doc
    agency: Test Agency
    title: "Empty URL Document"
    url: ""
    expected_page_count: 1
    expected_sha256: unknown
    document_type: annual_regulations
    publication_date: "2026-01-01"
""",
            encoding="utf-8",
        )
        # fetch_pdf must not be called — the empty-url guard fires first.
        # If it were called, MagicMock would return a Mock object, which would
        # fail the page-count check downstream — test would still flag a bug.
        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError, match="empty"):
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        stub.assert_not_called()
