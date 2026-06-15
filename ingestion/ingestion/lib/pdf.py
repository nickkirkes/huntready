"""
State-agnostic PDF extraction primitives (shared library).

Provides low-level building blocks for pulling structured text and tables out
of regulation PDFs that have already been fetched and stored on disk by
`pdf_fetch.py`. Where `pdf_fetch.py` handles network I/O and manifest writing,
this module handles everything that happens after the file is on disk.

Per ADR-001 (authority preserved, not replaced): regulation text must be
carried verbatim. Extraction functions return raw strings and table cells as
found in the PDF — callers are responsible for deciding what to keep. Nothing
here summarizes, paraphrases, or infers meaning.

Per ADR-005 (Python ingestion / TypeScript serving language split): this
module is state-agnostic and lives under `ingestion/lib/` for reuse by every
state adapter that extracts text from PDFs. No state-specific logic lives
here.

Per ADR-008 (verbatim regulation text): `extract_text` and `find_section`
return text exactly as pdfplumber sees it, with no normalization beyond
Unicode NFC (applied by callers when needed). Whitespace and hyphenation
artifacts are the caller's problem.

Per ADR-017 (confidence calibration + parent-inheritance rule): `ConfidenceTier`
encodes the three-tier vocabulary (HIGH / MEDIUM / LOW) used by normalizer
code to annotate how reliably a value was extracted. `min_tier` and
`demote_one_tier` are pure helpers for composing tier logic across multiple
extraction steps without hard-coding string comparisons throughout adapter
code.

Public API:
    PdfExtractionError  — raised when PDF open, table parse, or section search fails
    PageReference       — TypedDict: {page_number, extracted_at, source_pdf}
    TableMatch          — TypedDict: {headers, rows, page_reference}
    ConfidenceTier      — Enum: HIGH | MEDIUM | LOW
    open_pdf            — open a PDF file, returning a pdfplumber.PDF context manager
    iter_pages          — yield pdfplumber Page objects from an open PDF
    extract_text        — extract plain text from a single Page, stripping control chars
    extract_tables      — extract all tables from a single Page as lists of cell strings
    find_section        — search pages for a regex pattern, return matching PageReferences
    page_reference_to_str — format a PageReference as a human-readable citation string
    min_tier            — return the lower-confidence tier of two ConfidenceTiers
    demote_one_tier     — return the next-lower tier (HIGH→MEDIUM, MEDIUM→LOW, LOW→LOW)
    write_extraction_artifact — atomically write a list of records as a JSON
                          array, one record per line (committed-fixture format)
"""

from __future__ import annotations

import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator, Sequence, TypedDict, cast

import pdfplumber
from pdfplumber.page import Page

_logger = logging.getLogger(__name__)


class PdfExtractionError(Exception):
    """Raised when PDF extraction fails (open, table parse, section search)."""


class PageReference(TypedDict):
    """Rich page-reference for in-extraction artifacts.

    Bbox is for re-extraction cropping; the str collapse via
    ``page_reference_to_str`` drops bbox per the ``SourceCitation.page_reference``
    schema constraint (``str | None``). The rich form survives in extraction
    artifacts; the collapse is one-way for V1.
    """

    pdf_filename: str
    page_num_1based: int
    bbox: tuple[float, float, float, float] | None
    extracted_at: str


def page_reference_to_str(ref: PageReference) -> str:
    """Collapse a `PageReference` to the ``SourceCitation.page_reference`` string form.

    Format: ``f"{pdf_filename}:p{page_num_1based}"`` — deterministic, sortable,
    human-readable, bbox-stripped.
    """
    return f"{ref['pdf_filename']}:p{ref['page_num_1based']}"


class ConfidenceTier(str, Enum):
    """Three-tier confidence per ADR-017.

    Rank ordering (most-uncertain-wins for MIN aggregation):
    ``LOW`` (rank=0) < ``MEDIUM`` (rank=1) < ``HIGH`` (rank=2).

    The ``str`` mixin lets a tier instance serialize directly to the
    ``schema.Confidence = Literal["high", "medium", "low"]`` shape — write
    ``ConfidenceTier.HIGH`` to ``regulation_record.confidence`` without
    converting to ``.value``.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return _TIER_RANKS[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ConfidenceTier):
            return NotImplemented
        return self.rank < other.rank


_TIER_RANKS: dict[ConfidenceTier, int] = {
    ConfidenceTier.LOW: 0,
    ConfidenceTier.MEDIUM: 1,
    ConfidenceTier.HIGH: 2,
}


def min_tier(tiers: Iterable[ConfidenceTier]) -> ConfidenceTier:
    """Most-uncertain-wins MIN over confidence tiers (ADR-017).

    Uses an explicit ``key=lambda t: t.rank`` rather than bare ``min()``
    because Python's default ``min`` on the string mixin's ``__lt__`` would
    compare lexicographically (``"high" < "low" < "medium"`` because
    ``h < l < m``) — the wrong answer. The trap is locked by the unit
    tests in `test_pdf.py::TestMinTier::test_lexicographic_trap_explicit`.

    Raises:
        PdfExtractionError: if ``tiers`` is empty (signals an upstream bug).
    """
    tiers_list = list(tiers)
    if not tiers_list:
        raise PdfExtractionError(
            "min_tier received an empty iterable — caller must supply at least one tier"
        )
    return min(tiers_list, key=lambda t: t.rank)


def demote_one_tier(tier: ConfidenceTier) -> ConfidenceTier:
    """Demote one tier per ADR-017 correction-touched rule.

    ``HIGH -> MEDIUM``, ``MEDIUM -> LOW``, ``LOW -> LOW`` (clamped at floor).
    """
    if tier is ConfidenceTier.HIGH:
        return ConfidenceTier.MEDIUM
    if tier is ConfidenceTier.MEDIUM:
        return ConfidenceTier.LOW
    return ConfidenceTier.LOW


class PdfDocument:
    """Wraps a pdfplumber PDF handle with filename/path traceability.

    Use as a context manager:

        with open_pdf(path) as pdf:
            for page_num, page in iter_pages(pdf, 1, 5):
                ...
    """

    def __init__(self, pdfplumber_pdf: pdfplumber.PDF, path: Path) -> None:
        self._pdf = pdfplumber_pdf
        self.path = path
        self.filename = path.name

    @property
    def pages(self) -> list[Page]:
        return self._pdf.pages

    def __enter__(self) -> PdfDocument:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self._pdf.close()


def open_pdf(path: Path) -> PdfDocument:
    """Open a PDF and return a `PdfDocument` wrapping the pdfplumber handle.

    Raises:
        PdfExtractionError: if the file does not exist or pdfplumber cannot
            parse it. Wraps any underlying exception so callers do not need
            to import pdfplumber's internal error types.
    """
    if not path.exists():
        raise PdfExtractionError(f"PDF not found at {path}")
    try:
        handle = pdfplumber.open(str(path))
    # pdfminer (pdfplumber's backend) raises from several private exception
    # hierarchies with no stable public base class — broad ``Exception`` is
    # intentional so we don't silently miss real parse failures. The original
    # exception is preserved via ``from exc`` for ``__cause__`` inspection.
    except Exception as exc:
        raise PdfExtractionError(f"failed to open PDF {path}: {exc}") from exc
    return PdfDocument(handle, path)


def iter_pages(pdf: PdfDocument, start: int, end: int) -> Iterator[tuple[int, Page]]:
    """Iterate pages with 1-based page numbers (matches print convention).

    Yields ``(page_num_1based, page)`` tuples. ``start`` and ``end`` are
    inclusive 1-based bounds. The page-range checks fail loudly because
    they are at the system boundary (caller-supplied arguments).

    Raises:
        PdfExtractionError: if ``start < 1``, ``end < start``, or ``end``
            exceeds the PDF's page count.
    """
    total = len(pdf.pages)
    if start < 1:
        raise PdfExtractionError(f"start page {start} must be >= 1 (1-based)")
    if end < start:
        raise PdfExtractionError(f"end page {end} must be >= start {start}")
    if end > total:
        raise PdfExtractionError(
            f"end page {end} exceeds PDF page count {total}"
        )
    for page_num in range(start, end + 1):
        yield (page_num, pdf.pages[page_num - 1])


def extract_text(
    page: Page, bbox: tuple[float, float, float, float] | None = None
) -> str:
    """Extract page text via pdfplumber's default word-grouping; optionally
    crop to a bounding box first.

    ADR-008 boundary: this primitive does NO additional normalization on top
    of pdfplumber's default text-map. We do NOT call ``extract_text`` with
    ``layout=True`` (which would inject synthetic spaces to preserve visual
    column alignment) and we do NOT do any post-processing (whitespace squash,
    Unicode normalize, line-break joining). Downstream extractors (S03.3-S03.5)
    are responsible for any cleanup needed for `verbatim_rule` storage.

    Platform note: pdfplumber's word-grouping reassembles glyphs into words
    with a single space between them, so a ``(hello  world)`` content stream
    with two literal spaces is returned as ``"hello world"`` (single space)
    — not byte-for-byte verbatim, but the closest representation pdfplumber
    offers. Newlines at glyph-line-breaks ARE preserved. Callers needing
    truly byte-exact source text would need to walk ``page.chars`` directly,
    which is not the V1 use case.
    """
    target = page.crop(bbox) if bbox is not None else page
    return target.extract_text() or ""


class TableMatch(TypedDict):
    """A single table located on a page, with bbox and content.

    ``headers`` is the first row of the table (raw cell strings; may contain
    ``None`` cells for empty header positions). ``rows`` is the remaining rows.
    Both are returned verbatim — no normalization, no header inference.
    Callers are responsible for header interpretation.
    """

    bbox: tuple[float, float, float, float]
    headers: list[str | None]
    rows: list[list[str | None]]


def extract_tables(
    page: Page,
    settings: dict[str, object] | None = None,
) -> list[TableMatch]:
    """Extract all tables on a page as typed `TableMatch` records.

    Wraps ``page.find_tables(table_settings)`` (NOT pdfplumber's
    ``page.extract_tables()``) because only ``find_tables`` returns ``Table``
    objects with ``.bbox`` attached — required for `TableMatch.bbox`. The
    first row of each extracted table becomes ``headers``; remaining rows
    become ``rows``. An empty table (zero rows) yields ``headers=[]`` and
    ``rows=[]``.

    Args:
        page: the pdfplumber page to scan
        settings: optional pdfplumber ``TableSettings`` dict (e.g.,
            ``{"vertical_strategy": "lines"}``). ``None`` uses pdfplumber
            defaults.
    """
    matches: list[TableMatch] = []
    if settings is not None:
        tables = page.find_tables(table_settings=settings)
    else:
        tables = page.find_tables()
    for table in tables:
        bbox = cast(tuple[float, float, float, float], tuple(table.bbox))
        extracted = table.extract()
        if not extracted:
            # pdfplumber located a table boundary but Table.extract() yielded
            # no cells — could be a genuinely empty table OR an internal parse
            # failure. Surface the ambiguity so a downstream verbatim-text
            # consumer doesn't silently record a regulation row as empty.
            _logger.warning(
                "extract_tables: located table at bbox=%s but Table.extract() "
                "returned no rows; recording empty TableMatch", bbox
            )
            matches.append(TableMatch(bbox=bbox, headers=[], rows=[]))
            continue
        headers = extracted[0]
        data_rows = extracted[1:]
        matches.append(TableMatch(bbox=bbox, headers=headers, rows=data_rows))
    return matches


def find_section(
    pdf: PdfDocument, heading_pattern: str | re.Pattern[str]
) -> tuple[int, tuple[float, float, float, float]] | None:
    """Locate a heading by regex; return ``(page_num_1based, bbox)`` of the
    FIRST match, or ``None`` if not found.

    Iterates pages in order and calls ``page.search(pattern, regex=True)``.
    The bbox is the heading's character-level bounding box per pdfplumber
    semantics — usable downstream as a starting point for cropping the
    section content.

    Returns ``None`` rather than raising — "not found" is a normal callsite
    branch, not an extraction error.
    """
    for page_num_1based, page in enumerate(pdf.pages, start=1):
        matches = page.search(heading_pattern, regex=True)
        if matches:
            first = matches[0]
            bbox = (
                float(first["x0"]),
                float(first["top"]),
                float(first["x1"]),
                float(first["bottom"]),
            )
            return (page_num_1based, bbox)
    return None


def write_extraction_artifact(records: Sequence[object], path: Path) -> None:
    """Atomically write *records* to *path* as a JSON array, ONE record per line.

    This is the canonical serializer for committed extraction artifacts (the
    ``ingestion/states/<state>/extracted/*.json`` fixtures produced by the
    ``extract_*.py`` adapters and consumed by loaders + artifact-regression
    tests). Use it instead of ``json.dumps(..., indent=2)``.

    Why one-record-per-line rather than ``indent=2`` pretty-print: these
    artifacts are large (hundreds–thousands of records) and committed to git.
    Pretty-printing inflates them roughly two orders of magnitude in line count
    (CO's 737-section big-game artifact is ~104k lines pretty-printed vs 739 one
    record per line), which blows past code-review line-count limits — e.g.
    cubic's 50,000-changed-line cap. (``.gitattributes`` does NOT help: GitHub
    counts raw diff lines regardless of ``-diff`` / ``linguist-generated``.)
    One record per line keeps the artifact at ~one line per record while staying
    valid JSON, diffable per record, and ``json.load``-parseable.

    Determinism (so re-runs are byte-identical for regression/SHA pins): pass an
    already-sorted *records* sequence; each record is dumped with
    ``sort_keys=True``. Any newlines inside string values are JSON-escaped
    (``\\n``), so every record occupies exactly one physical line.

    Atomic + state-agnostic (ADR-005): serializes to a ``.tmp`` sibling then
    ``Path.replace()`` (atomic on POSIX, safe on Windows); creates the parent
    directory if needed. No state-specific logic — usable by every adapter.

    :param records: JSON-serializable records, pre-sorted by the caller.
    :param path: destination ``.json`` path (parents created if missing).
    """
    if records:
        body = ",\n".join(
            json.dumps(record, sort_keys=True, ensure_ascii=False)
            for record in records
        )
        payload = "[\n" + body + "\n]\n"
    else:
        payload = "[]\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic ".tmp" sibling — matches the atomic-write convention in
    # build_overlay_fixture.py and extract_black_bear.py, which this helper
    # generalizes. Safe because the ingestion pipeline is offline + single-writer
    # (one extractor per artifact path; ``make ingest-all`` parallelizes across
    # states, never the same path), so there is no concurrent-writer race. A
    # crashed run leaves exactly one predictable ".tmp" that the next run's
    # truncating write_text overwrites (self-healing) — whereas unique tmp names
    # would leak orphan ".tmp" files on every crash. (path.parent / (name +
    # ".tmp") also avoids Path.with_suffix misreading ".json.tmp" as a
    # double-extension.)
    tmp_path = path.parent / (path.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)  # atomic on POSIX; replace() safe on Windows too


def split_valid_gmus(cell: str | None) -> tuple[str | None, str | None]:
    """Split a 'Valid GMUs' table cell into (clean_gmu_list, qualifier).

    A CPW Valid-GMUs cell is a leading run of GMU tokens (1-4 digit numbers,
    each optionally suffixed '+', comma/whitespace separated) optionally
    followed by a free-text qualifier (e.g. 'private land only', 'Except
    Bosque del Oso SWA', 'Note: No hunting access to GMU 211').  A leading
    'New' marker (a what's-new indicator) may precede the GMU run.

    GMU numbers that appear INSIDE the qualifier (the excluded '211'; the
    'private land in 12, 23, 24' units) are part of the prose and stay in the
    qualifier — they are NOT promoted to the clean list.

    Returns:
      - clean_gmu_list: the leading GMU run, comma-joined (', '), or None.
      - qualifier: the free text (any leading 'New' marker + everything from
        the first non-GMU, non-marker word onward), collapsed to single
        spaces, or None.

    A cell with NO qualifier is returned UNCHANGED as (cell, None) — do not
    reformat pure-GMU cells (avoids needless churn in the hundreds of
    newline-wrapped clean cells).
    """
    if cell is None:
        return (None, None)
    if not cell.strip():
        return (None, None)

    tokens = cell.split()

    def _is_gmu_token(t: str) -> bool:
        return re.fullmatch(r"\d{1,4}\+?", t.rstrip(",")) is not None

    _LEADING_MARKERS = {"new"}

    gmu_tokens: list[str] = []
    qualifier_tokens: list[str] = []
    in_leading = True

    for tok in tokens:
        if in_leading:
            if _is_gmu_token(tok):
                gmu_tokens.append(tok.rstrip(","))
            elif tok.rstrip(",").lower() in _LEADING_MARKERS:
                qualifier_tokens.append(tok.rstrip(","))
            else:
                in_leading = False
                qualifier_tokens.append(tok)
        else:
            qualifier_tokens.append(tok)

    if not qualifier_tokens:
        return (cell, None)

    clean: str | None = ", ".join(gmu_tokens) if gmu_tokens else None
    qualifier = " ".join(qualifier_tokens)
    return (clean, qualifier)
