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


class TestPendingEntryBlocksRunButReportsDistinctly:
    """An entry with `pending: true` is intentionally not-yet-fetchable (URL
    not yet discovered). It must NOT cause an exit-0 success — exiting 0 with
    a known-unfetched canonical source would mislead downstream extraction
    stories into running against a partial fixture set. But it should be
    surfaced distinctly from a fetch failure (different remediation path:
    locate URL vs. debug fetch error)."""

    def test_pending_entry_blocks_run_with_pending_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        # Single pending entry — the orchestrator must NOT exit 0; it raises
        # PdfFetchError naming the entry as pending (not as a fetch error).
        sources_path.write_text(
            """\
pdfs:
  - id: pending-doc
    agency: Test Agency
    title: "Pending Document"
    url: ""
    expected_page_count: 1
    expected_sha256: unknown
    document_type: correction
    publication_date: "2026-03-18"
    pending: true
""",
            encoding="utf-8",
        )
        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError) as exc_info:
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        msg = str(exc_info.value)
        assert "pending" in msg
        assert "pending-doc" in msg
        # And the pending entry is reported in the "pending" bucket, not
        # under a "failed" header — verify the message structure.
        assert "1 pending" in msg
        assert "0 failed" not in msg  # zero-failures bucket is omitted
        stub.assert_not_called()

    def test_pending_and_succeeded_mix_still_blocks_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 1 fetched, 1 pending — pending alone is enough to block exit 0.
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        sources_path.write_text(
            """\
pdfs:
  - id: fetched-doc
    agency: Test Agency
    title: "Fetched Document"
    url: "https://example.com/x.pdf"
    expected_page_count: 10
    expected_sha256: unknown
    document_type: annual_regulations
    publication_date: "2026-01-01"
  - id: pending-doc
    agency: Test Agency
    title: "Pending Document"
    url: ""
    expected_page_count: 1
    expected_sha256: unknown
    document_type: correction
    publication_date: "2026-03-18"
    pending: true
""",
            encoding="utf-8",
        )
        stub = MagicMock(return_value=_make_metadata(
            citation_id="fetched-doc", page_count=10,
        ))
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError, match="pending"):
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        # The fetched entry was attempted exactly once (not retried)
        stub.assert_called_once()

    def test_pending_with_non_empty_url_is_inconsistent_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `pending: true` AND a real URL is contradictory — the operator
        # likely meant to remove `pending: true` after discovering the URL.
        # Surface the inconsistency so it doesn't silently linger.
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        sources_path.write_text(
            """\
pdfs:
  - id: contradictory-doc
    agency: Test Agency
    title: "Contradictory Document"
    url: "https://example.com/x.pdf"
    expected_page_count: 1
    expected_sha256: unknown
    document_type: annual_regulations
    publication_date: "2026-01-01"
    pending: true
""",
            encoding="utf-8",
        )
        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError, match="mutually exclusive"):
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        stub.assert_not_called()


class TestMalformedEntryShape:
    """A non-mapping entry (scalar, list, None) must be reported as a
    PdfFetchError — not bubble up as a bare AttributeError that escapes
    the orchestrator's aggregation loop."""

    def test_string_entry_is_aggregated_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        # A scalar entry — would crash on `.keys()` / `.get()` without a guard.
        sources_path.write_text(
            """\
pdfs:
  - "not a mapping"
""",
            encoding="utf-8",
        )
        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError, match="not a YAML mapping"):
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        stub.assert_not_called()

    def test_null_entry_is_aggregated_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        sources_path.write_text(
            """\
pdfs:
  - null
""",
            encoding="utf-8",
        )
        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError, match="not a YAML mapping"):
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        stub.assert_not_called()

    def test_malformed_entry_does_not_short_circuit_other_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A malformed entry mixed with a well-formed pending entry: the
        # malformed one is reported under the failures bucket, the pending one
        # under the pending bucket — both surface in the aggregated message
        # and the orchestrator continues past the malformed entry rather than
        # crashing with AttributeError.
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        sources_path.write_text(
            """\
pdfs:
  - "garbage scalar"
  - id: pending-doc
    agency: Test Agency
    title: "Pending Document"
    url: ""
    expected_page_count: 1
    expected_sha256: unknown
    document_type: correction
    publication_date: "2026-03-18"
    pending: true
""",
            encoding="utf-8",
        )
        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError) as exc_info:
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        msg = str(exc_info.value)
        # Malformed entry surfaces as the index-named failure under "failed"
        assert "<entry-0>" in msg
        assert "not a YAML mapping" in msg
        assert "1 failed" in msg
        # The pending entry surfaces under the "pending" bucket — distinct
        # from the failures bucket, but still blocking the run.
        assert "pending-doc" in msg
        assert "1 pending" in msg
        stub.assert_not_called()


class TestEmptyOrInvalidFieldValuesFailLoud:
    """Fields that are present but empty, null, or the wrong type must be
    caught early with a clear message naming the entry and each offending
    field — not flow silently into downstream stories or surface as cryptic
    errors inside fetch_pdf."""

    def _write_sources_yaml(self, path: Path, **overrides: object) -> None:
        """Write a single-entry sources.yaml with valid defaults, applying
        any per-field overrides supplied as keyword arguments."""
        entry: dict[str, object] = {
            "id": "test-doc",
            "agency": "Test Agency",
            "title": "Test Document",
            "url": "https://example.com/x.pdf",
            "expected_page_count": 10,
            "expected_sha256": "unknown",
            "document_type": "annual_regulations",
            "publication_date": "2026-01-01",
        }
        entry.update(overrides)

        def _yaml_scalar(v: object) -> str:
            if v is None:
                return "null"
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, int):
                return str(v)
            return f'"{v}"'

        lines = ["pdfs:", "  - id: test-doc"]
        for k, v in entry.items():
            if k == "id":
                continue
            lines.append(f"    {k}: {_yaml_scalar(v)}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_empty_string_agency_aggregated_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        self._write_sources_yaml(sources_path, agency="")

        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError) as exc_info:
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        msg = str(exc_info.value)
        assert "agency" in msg
        assert "''" in msg
        stub.assert_not_called()

    def test_null_title_aggregated_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        self._write_sources_yaml(sources_path, title=None)

        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError) as exc_info:
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        msg = str(exc_info.value)
        assert "title" in msg
        assert "None" in msg
        stub.assert_not_called()

    def test_zero_expected_page_count_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        self._write_sources_yaml(sources_path, expected_page_count=0)

        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError) as exc_info:
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        msg = str(exc_info.value)
        assert "expected_page_count" in msg
        stub.assert_not_called()

    def test_string_expected_page_count_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        # YAML: write the value unquoted as a bare string "ten" — safe_load
        # will parse it as a string since it's not a valid YAML integer.
        sources_path.write_text(
            """\
pdfs:
  - id: test-doc
    agency: Test Agency
    title: "Test Document"
    url: "https://example.com/x.pdf"
    expected_page_count: ten
    expected_sha256: unknown
    document_type: annual_regulations
    publication_date: "2026-01-01"
""",
            encoding="utf-8",
        )

        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError) as exc_info:
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        msg = str(exc_info.value)
        assert "expected_page_count" in msg
        stub.assert_not_called()

    def test_multiple_empty_fields_all_reported_in_one_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        self._write_sources_yaml(
            sources_path, agency="", title=None, expected_page_count=0
        )

        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError) as exc_info:
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        msg = str(exc_info.value)
        assert "agency" in msg
        assert "title" in msg
        assert "expected_page_count" in msg
        # All three must appear in a single aggregated error, not separate ones.
        # Count distinct "1 failed" — there is exactly one failure entry.
        assert "1 failed" in msg
        stub.assert_not_called()

    def test_empty_url_with_pending_true_still_passes_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """url is intentionally excluded from the empty-value check so the
        pending flow still works: pending: true + empty url must NOT fire the
        new validation error; it should be reported in the 'pending' bucket."""
        sources_path = tmp_path / "sources.yaml"
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        sources_path.write_text(
            """\
pdfs:
  - id: pending-doc
    agency: Test Agency
    title: "Pending Document"
    url: ""
    expected_page_count: 1
    expected_sha256: unknown
    document_type: correction
    publication_date: "2026-03-18"
    pending: true
""",
            encoding="utf-8",
        )

        stub = MagicMock()
        monkeypatch.setattr(fetch_pdfs, "fetch_pdf", stub)

        with pytest.raises(PdfFetchError) as exc_info:
            fetch_pdfs.main([
                "--sources", str(sources_path),
                "--fixture-dir", str(fixture_dir),
            ])
        msg = str(exc_info.value)
        # Must appear in the pending bucket, NOT the failures bucket.
        assert "1 pending" in msg
        assert "pending-doc" in msg
        # The new empty-value validation must not have fired — no "invalid
        # field values" text, and no failure count line.
        assert "invalid field values" not in msg
        assert "0 failed" not in msg  # zero-failures bucket is omitted
        stub.assert_not_called()


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
