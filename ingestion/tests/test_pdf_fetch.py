"""Unit tests for ingestion.lib.pdf_fetch."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests as requests_lib

from ingestion.lib import pdf_fetch
from ingestion.lib.pdf_fetch import PdfFetchError, fetch_pdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_pdf_bytes() -> bytes:
    """Return a tiny valid 1-page PDF that pypdf can parse.

    Constructs the PDF freshly via pypdf.PdfWriter on each call. Output is
    deterministic within a single pypdf version (a pypdf upgrade can shift
    timestamps or object IDs and change the SHA-256). Tests assert against
    `hashlib.sha256(sample_pdf_bytes).hexdigest()` rather than a hardcoded
    digest, so version drift is absorbed; the 1-page-vs-2-page structural
    difference exercised by the drift tests cannot collide.
    """
    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    return _minimal_pdf_bytes()


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mock_session_returning(content: bytes, status: int = 200) -> MagicMock:
    """Build a MagicMock requests.Session whose .get() returns a response with `content`."""
    resp = MagicMock(spec=requests_lib.Response)
    resp.status_code = status
    resp.content = content
    resp.text = content[:200].decode("utf-8", errors="replace")
    if status >= 400:
        resp.raise_for_status.side_effect = requests_lib.HTTPError(
            f"HTTP {status}", response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    session = MagicMock(spec=requests_lib.Session)
    session.get.return_value = resp
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFetchPdfHappyPath:
    def test_writes_pdf_and_manifest(
        self, fixture_dir: Path, sample_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = _mock_session_returning(sample_pdf_bytes)
        meta = fetch_pdf(
            citation_id="test-doc-2026",
            url="https://example.com/doc.pdf",
            publication_date="2026-01-01",
            document_type="annual_regulations",
            fixture_dir=fixture_dir,
            session=session,
        )
        # PDF written
        pdf_path = fixture_dir / "test-doc-2026-2026-01-01.pdf"
        assert pdf_path.exists()
        assert pdf_path.read_bytes() == sample_pdf_bytes
        # Manifest written
        manifest_path = fixture_dir / "test-doc-2026-2026-01-01-pdf-manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        # Returned metadata matches manifest
        assert meta.pdf_sha256 == hashlib.sha256(sample_pdf_bytes).hexdigest()
        assert meta.page_count == 1
        assert meta.citation_id == "test-doc-2026"
        assert meta.document_type == "annual_regulations"
        assert meta.publication_date == "2026-01-01"
        # Manifest carries all 8 fields
        assert set(manifest.keys()) == {
            "filename",
            "pdf_sha256",
            "page_count",
            "fetched_at",
            "source_url",
            "document_type",
            "publication_date",
            "citation_id",
        }


class TestFetchPdf404:
    def test_404_raises_pdf_fetch_error(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = _mock_session_returning(b"not found", status=404)
        with pytest.raises(PdfFetchError):
            fetch_pdf(
                citation_id="test-404",
                url="https://example.com/missing.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
                session=session,
            )
        # No fixture written on failure
        assert not (fixture_dir / "test-404-2026-01-01.pdf").exists()
        assert not (fixture_dir / "test-404-2026-01-01-pdf-manifest.json").exists()


class TestFetchPdfNetworkError:
    """A network error (ConnectionError, Timeout, etc.) must surface as
    PdfFetchError so the orchestrator's aggregation loop catches it. A bare
    requests.RequestException would escape the loop and abort the run."""

    def test_connection_error_wrapped_as_pdf_fetch_error(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = requests_lib.ConnectionError("name resolution failed")
        with pytest.raises(PdfFetchError, match="network error"):
            fetch_pdf(
                citation_id="test-conn-err",
                url="https://example.com/x.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
                session=session,
            )

    def test_timeout_wrapped_as_pdf_fetch_error(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = MagicMock(spec=requests_lib.Session)
        session.get.side_effect = requests_lib.Timeout("read timed out")
        with pytest.raises(PdfFetchError, match="network error"):
            fetch_pdf(
                citation_id="test-timeout",
                url="https://example.com/x.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
                session=session,
            )


class TestFetchPdfCorruptPriorManifest:
    """A truncated or unparseable prior manifest must fail loud rather than
    be silently treated as 'no prior state' — the on-disk PDF may already
    have been extracted from, and proceeding silently would overwrite it
    without any drift signal."""

    def test_truncated_prior_manifest_raises(
        self,
        fixture_dir: Path,
        sample_pdf_bytes: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        # Pre-stage a corrupt manifest at the path that fetch_pdf will check.
        manifest_path = fixture_dir / "corrupt-doc-2026-01-01-pdf-manifest.json"
        manifest_path.write_text("{not valid json", encoding="utf-8")

        session = _mock_session_returning(sample_pdf_bytes)
        with pytest.raises(PdfFetchError, match="corrupt"):
            fetch_pdf(
                citation_id="corrupt-doc",
                url="https://example.com/x.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
                session=session,
            )


class TestFetchPdfShaDrift:
    def test_drift_raises_and_writes_marker(
        self,
        fixture_dir: Path,
        sample_pdf_bytes: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)

        # First fetch — establishes the prior SHA in the manifest
        session1 = _mock_session_returning(sample_pdf_bytes)
        fetch_pdf(
            citation_id="drift-doc-2026",
            url="https://example.com/doc.pdf",
            publication_date="2026-01-01",
            document_type="annual_regulations",
            fixture_dir=fixture_dir,
            session=session1,
        )

        # Second fetch — different content, so SHA differs
        # Build a different valid PDF (2 pages instead of 1)
        import pypdf

        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.add_blank_page(width=72, height=72)
        buf = io.BytesIO()
        writer.write(buf)
        different_bytes = buf.getvalue()
        assert different_bytes != sample_pdf_bytes

        session2 = _mock_session_returning(different_bytes)
        with pytest.raises(PdfFetchError, match="drift"):
            fetch_pdf(
                citation_id="drift-doc-2026",
                url="https://example.com/doc.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
                session=session2,
            )
        # Marker was written
        marker = fixture_dir / "drift-doc-2026-2026-01-01-pending-reextraction.flag"
        assert marker.exists()
        marker_content = marker.read_text()
        assert "drift-doc-2026" in marker_content
        assert "prior_sha256" in marker_content
        assert "current_sha256" in marker_content

    def test_existing_marker_blocks_fetch(
        self,
        fixture_dir: Path,
        sample_pdf_bytes: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        marker = fixture_dir / "blocked-doc-2026-01-01-pending-reextraction.flag"
        marker.write_text("operator must resolve")
        session = _mock_session_returning(sample_pdf_bytes)
        with pytest.raises(PdfFetchError, match="marker"):
            fetch_pdf(
                citation_id="blocked-doc",
                url="https://example.com/doc.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
                session=session,
            )

    def test_re_fetch_with_same_sha_preserves_manifest_modulo_fetched_at(
        self,
        fixture_dir: Path,
        sample_pdf_bytes: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = _mock_session_returning(sample_pdf_bytes)
        fetch_pdf(
            citation_id="stable-doc",
            url="https://example.com/doc.pdf",
            publication_date="2026-01-01",
            document_type="annual_regulations",
            fixture_dir=fixture_dir,
            session=session,
        )
        manifest_path = fixture_dir / "stable-doc-2026-01-01-pdf-manifest.json"
        first_manifest = json.loads(manifest_path.read_text())

        # Re-fetch with same content
        session2 = _mock_session_returning(sample_pdf_bytes)
        fetch_pdf(
            citation_id="stable-doc",
            url="https://example.com/doc.pdf",
            publication_date="2026-01-01",
            document_type="annual_regulations",
            fixture_dir=fixture_dir,
            session=session2,
        )
        second_manifest = json.loads(manifest_path.read_text())
        # Everything modulo fetched_at is identical
        for key in first_manifest:
            if key == "fetched_at":
                continue
            assert first_manifest[key] == second_manifest[key], f"key {key} drifted"


class TestFetchPdfThrottling:
    def test_throttle_invoked_with_url_host(
        self,
        fixture_dir: Path,
        sample_pdf_bytes: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        calls: list[str] = []
        monkeypatch.setattr(
            "ingestion.lib.arcgis._throttle",
            lambda host, *a, **kw: calls.append(host),
        )
        session = _mock_session_returning(sample_pdf_bytes)
        fetch_pdf(
            citation_id="t-doc",
            url="https://fwp.mt.gov/doc.pdf",
            publication_date="2026-01-01",
            document_type="annual_regulations",
            fixture_dir=fixture_dir,
            session=session,
        )
        assert "fwp.mt.gov" in calls


class TestFetchPdfValidation:
    @pytest.mark.parametrize("bad_url", ["", None])
    def test_empty_url_raises(
        self, fixture_dir: Path, bad_url: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        with pytest.raises(PdfFetchError, match="url"):
            fetch_pdf(
                citation_id="x",
                url=bad_url,
                publication_date="2026-01-01",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
            )

    def test_bad_publication_date_raises(self, fixture_dir: Path) -> None:
        with pytest.raises(PdfFetchError, match="publication_date"):
            fetch_pdf(
                citation_id="x",
                url="https://example.com/x.pdf",
                publication_date="not-a-date",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
            )

    def test_bad_document_type_raises(self, fixture_dir: Path) -> None:
        with pytest.raises(PdfFetchError, match="document_type"):
            fetch_pdf(
                citation_id="x",
                url="https://example.com/x.pdf",
                publication_date="2026-01-01",
                document_type="not-a-type",
                fixture_dir=fixture_dir,
            )

    def test_corrupt_pdf_raises(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = _mock_session_returning(b"not a pdf at all")
        with pytest.raises(PdfFetchError):
            fetch_pdf(
                citation_id="corrupt",
                url="https://example.com/x.pdf",
                publication_date="2026-01-01",
                document_type="annual_regulations",
                fixture_dir=fixture_dir,
                session=session,
            )


class TestFetchPdfCitationRoundTrip:
    """Verify the manifest's citation_id, document_type, and publication_date
    are preserved exactly so downstream stories (S03.6+) can construct a
    SourceCitation from manifest contents alone."""

    def test_correction_document_type_preserved(
        self,
        fixture_dir: Path,
        sample_pdf_bytes: bytes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("ingestion.lib.arcgis.time.sleep", lambda _s: None)
        session = _mock_session_returning(sample_pdf_bytes)
        meta = fetch_pdf(
            citation_id="mt-fwp-black-bear-2026-correction-2026-03-18",
            url="https://example.com/correction.pdf",
            publication_date="2026-03-18",
            document_type="correction",
            fixture_dir=fixture_dir,
            session=session,
        )
        assert meta.document_type == "correction"
        assert meta.publication_date == "2026-03-18"
        assert meta.citation_id == "mt-fwp-black-bear-2026-correction-2026-03-18"
        # And the manifest on disk carries them
        manifest_path = (
            fixture_dir
            / "mt-fwp-black-bear-2026-correction-2026-03-18-2026-03-18-pdf-manifest.json"
        )
        manifest = json.loads(manifest_path.read_text())
        assert manifest["document_type"] == "correction"
        assert manifest["citation_id"] == "mt-fwp-black-bear-2026-correction-2026-03-18"


class TestFetchPdfNoStateAdapterImports:
    """The shared library must not import from ingestion.states.* per ADR-005."""

    def test_no_state_adapter_imports_in_pdf_fetch(self) -> None:
        source = Path(pdf_fetch.__file__).read_text()
        assert "from ingestion.states" not in source
        assert "import ingestion.states" not in source
        assert "Montana" not in source  # case-sensitive guard against state-specific text
        assert "montana" not in source
