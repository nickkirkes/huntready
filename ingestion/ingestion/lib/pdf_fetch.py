"""
State-agnostic PDF fetch infrastructure (shared library).

Mirrors `arcgis.py` for non-ArcGIS PDF sources. Where `arcgis.py` handles
paginated ArcGIS MapServer feature services, this module handles direct PDF
downloads from state agency CDNs and document portals.

Per ADR-001 (authority preserved, not replaced): regulation text is carried
verbatim; source provenance is mandatory. `fetch_pdf` writes the PDF and a
manifest (SHA-256, page count, source URL, publication date) so downstream
stories can verify they are working from an unaltered source.

Per ADR-003 (ingestion upstream and offline): this module is part of the
Python ingestion pipeline only. The TypeScript serving stack never imports it.

Per ADR-005 (Python ingestion / TypeScript serving language split): this
module is state-agnostic and lives under `ingestion/lib/` for reuse by every
state adapter that fetches PDFs.

Per ADR-014 (`document_type` type enforcement): the `document_type` parameter
is validated against `_VALID_DOCUMENT_TYPES` before any network I/O occurs.

Why `arcgis._build_session` / `arcgis._throttle` are imported rather than
reimplemented here: shared HTTP discipline — both modules must use the same
User-Agent (carrying `HUNTREADY_INGESTION_CONTACT` when set) and the same
per-host throttle dict so a fetch script that calls both ArcGIS and PDF
endpoints does not inadvertently double-hit a host within the minimum
interval. If a third consumer of these helpers arrives, refactor them into
`ingestion/lib/http.py` and have both `arcgis.py` and `pdf_fetch.py` import
from there.

Public API:
    PdfFetchError  — raised on fetch, page-count read, or SHA verification failures
    PdfMetadata    — 8-field frozen dataclass written to *-pdf-manifest.json
    fetch_pdf      — fetch a PDF, drift-check, write fixture + manifest, return metadata
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pypdf
import requests

from ingestion.lib import arcgis

_logger = logging.getLogger(__name__)

_VALID_DOCUMENT_TYPES: frozenset[str] = frozenset({"annual_regulations", "correction"})


class PdfFetchError(Exception):
    """Raised when a PDF fetch, page-count read, or SHA verification fails."""


@dataclass(frozen=True)
class PdfMetadata:
    """The 8 fields written to <id>-<publication_date>-pdf-manifest.json."""

    filename: str           # basename of the on-disk PDF (no directory)
    pdf_sha256: str         # 64-char hex
    page_count: int         # via pypdf.PdfReader
    fetched_at: str         # ISO 8601 UTC, e.g., "2026-05-04T20:15:00+00:00"
    source_url: str
    document_type: str      # "annual_regulations" | "correction"
    publication_date: str   # ISO date "YYYY-MM-DD"
    citation_id: str        # mirrors SourceCitation.id


def _utc_iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string with +00:00 offset."""
    return datetime.now(tz=timezone.utc).isoformat()


def _validate_publication_date(s: str) -> None:
    """Raise PdfFetchError if `s` is not a valid YYYY-MM-DD date string."""
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError as exc:
        raise PdfFetchError(
            f"invalid publication_date {s!r} — expected YYYY-MM-DD"
        ) from exc


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` atomically via a .tmp sibling, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write `payload` as formatted JSON to `path` atomically via a .tmp sibling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)


def fetch_pdf(
    *,
    citation_id: str,
    url: str,
    publication_date: str,
    document_type: str,
    fixture_dir: Path,
    session: requests.Session | None = None,
) -> PdfMetadata:
    """Fetch a PDF, drift-check against prior manifest, write fixture + manifest.

    Parameters
    ----------
    citation_id:
        Identifier for this source document; mirrors ``SourceCitation.id``
        (e.g. ``"mt-fwp-dea-2026-2027-booklet"``). Used as the filename stem
        and recorded in the manifest.
    url:
        Direct URL to the PDF. Must be non-empty — if the URL has not yet been
        discovered, leave the entry out of ``sources.yaml`` rather than passing
        an empty string; the error message names ``citation_id`` so the
        operator knows which entry to populate.
    publication_date:
        ISO date string ``"YYYY-MM-DD"`` matching the document's official
        publication date (not the fetch date).
    document_type:
        One of ``{"annual_regulations", "correction"}``.
    fixture_dir:
        Directory where the PDF and manifest are written. Created if absent.
    session:
        Optional pre-built ``requests.Session``. If ``None``, a session is
        constructed via ``arcgis._build_session()`` so that this call and any
        sibling ArcGIS calls share the same User-Agent and throttle state.

    Returns
    -------
    PdfMetadata
        The 8-field descriptor written to the manifest.

    Raises
    ------
    PdfFetchError
        On any of: empty/None ``url``; invalid ``publication_date`` format;
        unknown ``document_type``; stale drift-detection marker present;
        HTTP >= 400; pypdf parse failure; SHA-256 drift against prior manifest.
    """
    # --- 1. Validate inputs ---
    if not url:
        raise PdfFetchError(
            f"url for {citation_id} is empty or missing — populate before fetching"
        )

    _validate_publication_date(publication_date)

    if document_type not in _VALID_DOCUMENT_TYPES:
        raise PdfFetchError(
            f"unknown document_type {document_type!r} for {citation_id} — "
            f"must be one of {sorted(_VALID_DOCUMENT_TYPES)}"
        )

    # --- 2. Resolve target paths ---
    pdf_path = fixture_dir / f"{citation_id}-{publication_date}.pdf"
    manifest_path = fixture_dir / f"{citation_id}-{publication_date}-pdf-manifest.json"
    marker_path = fixture_dir / f"{citation_id}-{publication_date}-pending-reextraction.flag"

    # --- 3. Stale marker check ---
    if marker_path.exists():
        raise PdfFetchError(
            f"drift marker present at {marker_path} — resolve the source change "
            f"and delete the marker before re-fetching {citation_id}"
        )

    # --- 4. Build session ---
    effective_session = session if session is not None else arcgis._build_session()

    # --- 5. Throttle ---
    host = urlparse(url).hostname or ""
    arcgis._throttle(host)

    # --- 6. Fetch ---
    # Wrap the network call so connection errors / timeouts surface as
    # PdfFetchError (caught by the orchestrator) rather than as a bare
    # requests.RequestException that escapes the aggregation loop.
    try:
        response = effective_session.get(url, timeout=60)
    except requests.RequestException as exc:
        raise PdfFetchError(
            f"network error fetching {url} for {citation_id}: {exc}"
        ) from exc
    if response.status_code >= 400:
        raise PdfFetchError(
            f"HTTP {response.status_code} fetching {url}: {response.text[:200]}"
        )
    content = response.content

    # --- 7. SHA-256 ---
    pdf_sha256 = hashlib.sha256(content).hexdigest()

    # --- 8. Page count ---
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        page_count = len(reader.pages)
    except Exception as exc:
        raise PdfFetchError(
            f"failed to read PDF for {citation_id} from {url}: {exc}"
        ) from exc

    # --- 9. Drift check ---
    if manifest_path.exists():
        # A truncated / corrupt prior manifest (e.g. a previous run killed
        # mid-write before .replace() completed) must fail loud rather than
        # be silently treated as "no prior state" — the existing PDF on disk
        # may already have been extracted from, and proceeding silently would
        # overwrite it without a drift signal.
        try:
            prior_data: dict[str, Any] = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            raise PdfFetchError(
                f"prior manifest for {citation_id} is unreadable or corrupt at "
                f"{manifest_path}: {exc} — investigate (likely an interrupted "
                f"prior run) and delete the file to force a clean re-fetch"
            ) from exc
        prior_sha = prior_data.get("pdf_sha256")
        if prior_sha != pdf_sha256:
            detected_at = _utc_iso_now()
            marker_text = (
                f"SHA-256 drift detected on re-fetch.\n"
                f"  citation_id:    {citation_id}\n"
                f"  url:            {url}\n"
                f"  prior_sha256:   {prior_sha}\n"
                f"  current_sha256: {pdf_sha256}\n"
                f"  detected_at:    {detected_at}\n"
                f"\n"
                f"Operator: investigate the source change, decide whether to "
                f"re-extract downstream artifacts, then DELETE this file to "
                f"unblock downstream stories.\n"
            )
            # Write marker BEFORE raising so the marker exists even if the
            # raise's caller swallows the exception. Wrap the write so a
            # disk-full or permission error surfaces as PdfFetchError carrying
            # the drift details — losing the marker file is a real risk that
            # must not silently downgrade to a generic OSError traceback.
            try:
                marker_path.write_text(marker_text, encoding="utf-8")
            except OSError as write_exc:
                raise PdfFetchError(
                    f"SHA-256 drift for {citation_id} AND failed to write marker "
                    f"to {marker_path}: {write_exc}. "
                    f"Drift: prior={prior_sha} current={pdf_sha256}."
                ) from write_exc
            raise PdfFetchError(
                f"SHA-256 drift for {citation_id}: prior={prior_sha} "
                f"current={pdf_sha256}. Marker written at {marker_path}."
            )

    # --- 10. Write PDF atomically ---
    _atomic_write_bytes(pdf_path, content)

    # --- 11. Build metadata ---
    metadata = PdfMetadata(
        filename=pdf_path.name,
        pdf_sha256=pdf_sha256,
        page_count=page_count,
        fetched_at=_utc_iso_now(),
        source_url=url,
        document_type=document_type,
        publication_date=publication_date,
        citation_id=citation_id,
    )

    # --- 12. Write manifest atomically ---
    _atomic_write_json(manifest_path, asdict(metadata))

    _logger.info(
        "fetched %s: %d pages, sha256=%s..., written to %s",
        citation_id,
        page_count,
        pdf_sha256[:12],
        pdf_path,
    )

    # --- 13. Return ---
    return metadata
