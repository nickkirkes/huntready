"""
Extract per-HD regulation rows from the Montana DEA hunting regulations booklet
(141 pages) into structured JSON for downstream ingestion (S03.6–S03.9).
The extractor walks the deer/elk page range (pp. 48–123) and the antelope page
range (pp. 136–141), locates each HD section by the ``HD NNN - Name`` heading
regex, pulls the regulation table per section, and emits one
``DeaSectionExtraction`` per HD per species. A separate statewide antelope
overlay (license 900-20) is extracted from prose and emitted as
``hd_number="STATEWIDE"``. All output is written to a deterministic JSON
artifact at ``ingestion/states/montana/extracted/dea-2026.json``.

ADR references:
  ADR-001  Authority preserved, not replaced — fail loud; no invented values.
  ADR-005  Python ingestion / TypeScript serving language split.
  ADR-008  Verbatim regulation text — section-level ``verbatim_text`` retains
           pdfplumber's word-grouped output without additional normalization.
           Only the structured ``rows`` payload uses the cleanup regexes below.
  ADR-017  Confidence calibration + parent-inheritance rule — per-row
           ``extraction_confidence`` is assigned here; HD-level MIN aggregation
           is S03.6's job.
  ADR-018  E03 schema additions (``license_season`` link table,
           ``geometry.legal_description``, ``geometry.kind='state'`` value).

Cleanup rules (applied only to structured ``rows`` cells, never to
``verbatim_text``):

  Cell padding:
      ``re.sub(r'\\s{3,}', ' ', cell.strip())``
      Collapses internal runs of 3+ whitespace characters (spaces, tabs, or
      newlines) that pdfplumber inserts at column edges, and trims leading /
      trailing whitespace. The ``\\s`` class matches spaces, tabs, and newlines
      — that breadth is intentional so multi-line cell content is also
      collapsed.

  Hyphenated line-break rejoin:
      ``re.sub(r'(?<=[a-z])-\\n(?=[a-z])', '', text)``
      Rejoins a soft hyphen at a line break when BOTH neighbors are lowercase
      ASCII letters (e.g. "regu-\\nlation" → "regulation"). This is
      intentionally narrow:
        - "9/7-10/20" is NOT rejoined (digit neighbors on both sides).
        - "262-50" is NOT rejoined (digit neighbors).
        - "ARCHERY-\\nONLY" is NOT rejoined (uppercase neighbors).

  Empty cells:
      ``_normalize_cell`` returns ``None`` (not ``""``) for cells that are
      ``None``, empty, or whitespace-only. Per ADR-001, absent data is
      represented as explicit null — an empty string is ambiguous.
"""

# State-specific module — must NOT import from ingestion.states.<other_state>.
# Cross-state imports violate ADR-005 isolation (each state adapter is fully
# self-contained). The state-agnostic guard test in T12 enforces this via AST
# walk at CI time.

import argparse
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict  # noqa: F401 — TypedDict used by exported TypedDicts

from ingestion.lib.pdf import (
    ConfidenceTier,
    PageReference,
    PdfDocument,
    PdfExtractionError,
    TableMatch,
    extract_tables,
    extract_text,
    iter_pages,
    open_pdf,
)

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path / file constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]

_DEA_PDF_PATH = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "montana"
    / "fixtures"
    / "mt-fwp-dea-2026-booklet-2026-04-27.pdf"
)

_OUTPUT_PATH = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "montana"
    / "extracted"
    / "dea-2026.json"
)

# Basename used in PageReference.pdf_filename fields.
_PDF_FILENAME_FOR_REF = "mt-fwp-dea-2026-booklet-2026-04-27.pdf"

# ---------------------------------------------------------------------------
# Page-range constants (1-based inclusive, per iter_pages convention)
# ---------------------------------------------------------------------------

_DEER_ELK_PAGES = (48, 123)
# NOTE: Plan originally stated (136, 142); PDF only has 141 pages — corrected.
# Antelope HD content runs pp. 136–138; pp. 139–141 are contacts/index/tables.
_ANTELOPE_PAGES = (136, 141)

# ---------------------------------------------------------------------------
# Metadata constants
# ---------------------------------------------------------------------------

_LICENSE_YEAR = 2026

# ---------------------------------------------------------------------------
# Column-header constants
# ---------------------------------------------------------------------------

_SEASON_COLUMNS: tuple[str, ...] = (
    "EARLY SEASON DATES",
    "ARCHERY ONLY SEASON DATES",
    "GENERAL SEASON DATES",
    "HERITAGE MUZZLELOADER SEASON DATES",
    "LATE SEASON DATES",
)

_SEASON_COLUMN_TO_KEY: dict[str, str] = {
    # Deer/elk format (uppercase multi-word with "DATES" suffix)
    "EARLY SEASON DATES": "early_season",
    "ARCHERY ONLY SEASON DATES": "archery_only",
    "GENERAL SEASON DATES": "general",
    "HERITAGE MUZZLELOADER SEASON DATES": "heritage_muzzleloader",
    "LATE SEASON DATES": "late",
    # Antelope format (different column names — discovered T10 live, 2026-05-07)
    "ARCHERY SEASON DATES": "archery_only",
    "SEASON DATES": "general",  # antelope "regular" season → general
}

_WEAPON_TYPE_OVERRIDE_BY_COLUMN: dict[str, str | None] = {
    # Deer/elk format
    "EARLY SEASON DATES": None,
    "ARCHERY ONLY SEASON DATES": "archery",
    "GENERAL SEASON DATES": None,
    "HERITAGE MUZZLELOADER SEASON DATES": "muzzleloader",
    "LATE SEASON DATES": None,
    # Antelope format
    "ARCHERY SEASON DATES": "archery",
    "SEASON DATES": None,
}

_NON_SEASON_COLUMNS: tuple[str, ...] = (
    # Deer/elk format
    "LICENSE/PERMIT",
    "OPPORTUNITY",
    "APPLY BY DATE",
    "QUOTA",
    "QUOTA RANGE",
    "OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS",
    # Antelope format (column names differ — normalized versions below)
    "LICENSE",
    "APPLY BY DATE",
    "OPPORTUNITY SPECIFC INFORMATION/ RESTRICTIONS",
)

# Matches "HD 262 - Madison Valley" (and variants with extra whitespace).
_HD_HEADING_REGEX = re.compile(
    r"^HD\s+(?P<num>\d{3})\s*-\s*(?P<name>.+?)\s*$", re.MULTILINE
)

# The statewide antelope overlay license code; emitted as hd_number="STATEWIDE".
_STATEWIDE_ANTELOPE_LICENSE = "900-20"

# ---------------------------------------------------------------------------
# TypedDicts — output JSON contract for S03.6 / S03.7
# (order: SeasonCoverage → SeasonWindow → DeaRowExtraction → DeaSectionExtraction)
# ---------------------------------------------------------------------------


class SeasonCoverage(TypedDict):
    """Boolean coverage flags — one per DEA season column.

    ``True`` means this license/permit row has a date window for that season;
    ``False`` means the cell was empty (the license does not cover that season).
    """

    early_season: bool
    archery_only: bool
    general: bool
    heritage_muzzleloader: bool
    late: bool


class SeasonWindow(TypedDict):
    """A single season's date window plus any weapon-type constraint.

    ``weapon_type_override`` is ``None`` for unrestricted seasons (e.g. GENERAL,
    LATE), ``"archery"`` for ARCHERY ONLY, and ``"muzzleloader"`` for HERITAGE
    MUZZLELOADER.
    """

    window: str
    weapon_type_override: str | None  # "archery" | "muzzleloader" | None


class DeaRowExtraction(TypedDict):
    """One license/permit row from a per-HD DEA regulation table.

    ``season_coverage`` records which seasons this row covers (boolean per
    column). ``season_windows`` carries only the keys where coverage is True,
    with the date-window string and weapon-type override. ``weapon_types`` is
    the row-level weapon eligibility (typically ``["any_legal_weapon"]`` for
    general licenses; ``["archery"]`` for the 900-series statewide overlay).
    ``extras`` captures the OPPORTUNITY SPECIFIC DETAILS cell verbatim.
    ``extraction_confidence`` is a ``ConfidenceTier`` string value assigned by
    ``_assign_row_confidence`` after section assembly.
    ``page_reference`` anchors the row to its source page in the PDF. Every
    row inherits the ``page_reference`` of its enclosing section (the section's
    starting page). For multi-page HDs, continuation rows from page N+1 are
    tagged with page N's reference — per-row page-accurate provenance is a
    deferred follow-up (see ``docs/planning/epics/E03-confidence-findings/S03.3.md``).
    """

    license_code: str
    opportunity: str
    apply_by: str | None
    quota: int | None
    quota_range: str | None
    season_coverage: SeasonCoverage
    season_windows: dict[str, SeasonWindow]  # keys are SeasonCoverage keys; only seasons this license covers
    weapon_types: list[str]
    extras: str | None
    extraction_confidence: str  # ConfidenceTier value: "high" | "medium" | "low"
    page_reference: PageReference  # inherited from enclosing section (section's starting page)


class DeaSectionExtraction(TypedDict):
    """All extracted rows for one HD + species combination.

    ``hd_number`` is the three-digit string (e.g. ``"262"``) or ``"STATEWIDE"``
    for the antelope overlay. ``verbatim_text`` retains the full page text for
    the section's starting page, un-normalized per ADR-008 — only ``rows``
    cells are cleaned up. ``page_reference`` anchors the section to its first
    page in the source PDF.
    """

    hd_number: str  # "262" or "STATEWIDE"
    hd_name: str
    species_group: str  # "deer" | "elk" | "antelope"
    license_year: int
    page_reference: PageReference
    verbatim_text: str
    rows: list[DeaRowExtraction]


# ---------------------------------------------------------------------------
# T2: Cleanup utility helpers
# ---------------------------------------------------------------------------


def _normalize_cell(text: str | None) -> str | None:
    """Return None for None/whitespace-only input; otherwise rejoin soft hyphens then collapse 3+ whitespace runs.

    Cleanup order is intentional:
    1. ``_rejoin_hyphenated_linebreaks`` must run BEFORE whitespace collapse so
       that the ``-\\n`` pattern is still intact when the rejoin regex fires.
    2. Collapse 3+ whitespace runs (spaces, tabs, newlines produced by pdfplumber
       at column edges).
    """
    if text is None:
        return None
    rejoined = _rejoin_hyphenated_linebreaks(text)
    stripped = rejoined.strip()
    if not stripped:
        return None
    return re.sub(r"\s{3,}", " ", stripped)


def _is_season_cell_absent(cell: str | None) -> bool:
    """Return True if ``cell`` represents an absent season value.

    The DEA PDF uses a literal dash ``"-"`` as a sentinel meaning "this license
    does not cover this season" rather than leaving the cell empty. Both ``None``
    and ``"-"`` must be treated as absent for season_coverage and season_windows.
    """
    normalized = _normalize_cell(cell)
    return normalized is None or normalized == "-"


def _is_species_banner_row(row: list[str | None]) -> bool:
    """Return True if ``row`` is a species-banner row embedded in the DEA table.

    The DEA PDF inserts banner rows like ``['DEER', None, None, ...]`` and
    ``['ELK', None, None, ...]`` as section dividers within the multi-HD table.
    These rows have a species name in the first cell and all other cells empty.
    They must be skipped during license extraction — they carry no license data.
    """
    _SPECIES_BANNERS = frozenset({"DEER", "ELK", "ANTELOPE"})
    if not row:
        return False
    first = _normalize_cell(row[0])
    if first is None or first.upper() not in _SPECIES_BANNERS:
        return False
    # All remaining cells must be absent/None.
    return all(_normalize_cell(cell) is None for cell in row[1:])


def _rejoin_hyphenated_linebreaks(text: str) -> str:
    """Rejoin soft hyphens at line breaks only when both neighbors are lowercase letters.

    Intentionally narrow: does NOT rejoin date ranges like `9/7-10/20` (digit neighbors)
    or license codes like `262-50` (digit neighbors). Only lowercase-letter-bordered hyphens.
    """
    return re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)


def _is_900_20_overlay_row(row: list[str | None]) -> bool:
    """Return True if ``row`` is the antelope statewide 900-20 overlay row.

    Matches the literal substring "900-20" anywhere in any cell of the row,
    not just the first cell. The overlay row is extracted separately via
    ``_extract_statewide_antelope_overlay`` and must not appear inside per-HD
    antelope sections; this filter guards against layout drift that would
    otherwise duplicate the overlay across per-HD sections.
    """
    if not row:
        return False
    for cell in row:
        normalized = _normalize_cell(cell)
        if normalized is not None and "900-20" in normalized:
            return True
    return False


def _is_region_footer_row(row: list[str | None]) -> bool:
    """Return True if ``row`` is an FWP "Region N" footer row in the antelope tables.

    The DEA antelope tables include rows whose LICENSE column reads
    ``"Region 4"``, ``"Region 5"``, ``"Region 6"``, ``"Region 7"`` (the FWP
    administrative region designators). These are scope footers, not
    regulation rows, and they have no licensed seasons. They must be filtered
    at extraction time to keep the intermediate artifact consumer-clean.
    Match: first cell starts with ``"Region "`` followed by a single digit.
    """
    if not row:
        return False
    first = _normalize_cell(row[0])
    if first is None:
        return False
    return bool(re.match(r"^Region\s+\d+$", first))


# Detects "Portions of HDs A, B, C ... <directional qualifier>" rows in the
# antelope table. These are sub-section delimiters that follow a Region N
# row and bind a single set of regulation rows to multiple sibling HDs
# (e.g., HDs 700, 701, 703 in Region 7). UAT defect D2 (2026-05-08) revealed
# the prior slicer absorbed the rows under these delimiters into the
# preceding HD-numbered section. Per directive option (a): emit one
# ``DeaSectionExtraction`` per listed HD with the same row content; S03.6
# dedups via license_code at ingestion.
_PORTIONS_HEADER_RE = re.compile(
    r"^Portions\s+of\s+HDs?\b", re.IGNORECASE
)


def _parse_portions_hd_list(text: str | None) -> list[str] | None:
    """Extract the HD numbers from a "Portions of HDs A, B, C ..." header.

    Returns a list of HD numbers as strings (preserving source order), or
    ``None`` if the text does not match the Portions pattern.

    Observed source forms (live DEA PDF, p138):
      - ``"Portions of HDs 700, 701, and 703 North of the Yellowstone River"``
      - ``"Portions of HDs 701, 702, 703, 704, and 705 South of the Yellowstone River"``

    The directional qualifier (``"North of the Yellowstone River"``) is NOT
    parsed here — it survives in the section's ``verbatim_text`` so S03.10
    binding generation can decide whether the qualifier matters geometrically.
    """
    if text is None:
        return None
    norm = _normalize_cell(text)
    if norm is None:
        return None
    m = re.match(r"^Portions\s+of\s+HDs?\b(?P<rest>.*)$", norm, re.IGNORECASE)
    if m is None:
        return None
    rest = m.group("rest")
    # Stop the digit search at the first directional qualifier word so a future
    # qualifier containing digits (e.g., "Highway 2") doesn't pollute the list.
    qualifier = re.search(r"\b(?:North|South|East|West)\b", rest, re.IGNORECASE)
    list_text = rest[: qualifier.start()] if qualifier else rest
    hds = re.findall(r"\d+", list_text)
    return hds if hds else None


def _is_portions_subsection_row(row: list[str | None]) -> bool:
    """Return True if ``row`` is a "Portions of HDs ..." subsection delimiter."""
    if not row:
        return False
    first = _normalize_cell(row[0])
    if first is None:
        return False
    return _PORTIONS_HEADER_RE.match(first) is not None


# ---------------------------------------------------------------------------
# T3: Column-header → SeasonCoverage key + weapon_type_override mapping helpers
# ---------------------------------------------------------------------------


def _normalize_header(header: str | None) -> str:
    """Return uppercase, whitespace-collapsed header; empty string for None/whitespace-only."""
    if header is None or not header.strip():
        return ""
    return re.sub(r"\s+", " ", header.strip()).upper()


def _season_key_for_column(header: str | None) -> str | None:
    """Return the SeasonCoverage key for a season column header, or None for non-season columns."""
    normalized = _normalize_header(header)
    if not normalized:
        return None
    return _SEASON_COLUMN_TO_KEY.get(normalized)


def _weapon_override_for_column(header: str | None) -> str | None:
    """Return the weapon_type_override for a season column, None for non-season columns.

    Raises PdfExtractionError if the header maps to a known season column that is
    missing from the override map — defensive invariant lock.
    """
    normalized = _normalize_header(header)
    if not normalized:
        return None
    if normalized in _SEASON_COLUMN_TO_KEY and normalized not in _WEAPON_TYPE_OVERRIDE_BY_COLUMN:
        raise PdfExtractionError(f"season column {header!r} missing from weapon override map")
    return _WEAPON_TYPE_OVERRIDE_BY_COLUMN.get(normalized)


# ---------------------------------------------------------------------------
# T4: HD section locator
# ---------------------------------------------------------------------------

# Minimum number of DEA header signature tokens that must appear in a table's
# normalized header row for the table to be recognized as the per-HD regulation
# table. The real DEA PDF uses multi-word column names with "DATES" appended
# (e.g. "EARLY SEASON DATES", "ARCHERY ONLY SEASON DATES"), discovered during
# T13 live inspection. Threshold of 4 keeps the match tolerant to minor column
# variation while rejecting unrelated tables.
# Tunable: if T13's live run shows false negatives, lower to 3 and add a note
# in E03-confidence-findings/S03.3.md.
_DEA_HEADER_SIGNATURE: frozenset[str] = frozenset(
    {
        "LICENSE/PERMIT",
        "OPPORTUNITY",
        "GENERAL SEASON DATES",
        "ARCHERY ONLY SEASON DATES",
        "HERITAGE MUZZLELOADER SEASON DATES",
        "LATE SEASON DATES",
        "EARLY SEASON DATES",
        "QUOTA",
    }
)
_DEA_HEADER_SIGNATURE_MIN_MATCHES = 4

# The antelope section uses a distinct, smaller table format with different
# column names (discovered during T10 live inspection, 2026-05-07). The
# header normalization uppercases all values, so "License" → "LICENSE" etc.
_ANTELOPE_HEADER_SIGNATURE: frozenset[str] = frozenset(
    {
        "LICENSE",
        "OPPORTUNITY",
        "QUOTA",
        "ARCHERY SEASON DATES",
        "SEASON DATES",
    }
)
_ANTELOPE_HEADER_SIGNATURE_MIN_MATCHES = 3


def _iter_hd_sections(
    pdf: PdfDocument,
    page_range: tuple[int, int],
    species_group: str,
) -> Iterator[tuple[str, str, str, int, tuple[float, float, float, float] | None]]:
    """Walk ``page_range`` and yield one tuple per HD heading found.

    Yields ``(hd_number, hd_name, species_group, page_num_1based, section_bbox)``.
    ``section_bbox`` is always ``None`` here — the HD is anchored to its starting
    page only; T5's table extraction reads from that page forward until the next
    HD heading appears, making per-section sub-cropping unnecessary.

    Deduplication: each ``hd_number`` is yielded at most once, on the first page
    where its heading regex matches. Real DEA pages contain three regex-matchable
    forms of an HD's heading when the section spans pages:
      1. ``"HD NNN - Name"`` — canonical heading at the section's start.
      2. ``"HD NNN - Name - Continued on the Next Page"`` — footer annotation
         on the start page.
      3. ``"HD NNN - Name - Continued"`` — repeated heading at the top of the
         continuation page.
    Yielding all three would produce duplicate ``DeaSectionExtraction`` rows for
    the same HD/species (observed: 20 deer/elk HDs duplicated across the live
    DEA PDF before this dedup). T5's ``_extract_hd_table`` already handles
    multi-page continuation correctly when invoked once per HD, so first-match-
    wins is sufficient and produces the canonical ``hd_name`` (without any
    ``- Continued`` suffix) for the artifact.
    """
    seen: set[str] = set()
    for page_num, page in iter_pages(pdf, *page_range):
        text = extract_text(page)
        for match in _HD_HEADING_REGEX.finditer(text):
            hd_number = match.group("num")
            if hd_number in seen:
                continue
            seen.add(hd_number)
            hd_name = match.group("name").strip()
            yield (hd_number, hd_name, species_group, page_num, None)


# ---------------------------------------------------------------------------
# T5: Per-HD table extraction
# ---------------------------------------------------------------------------


def _matches_dea_header(headers: list[str | None]) -> bool:
    """Return True if the headers match either the deer/elk or antelope DEA signature.

    The deer/elk table uses ``LICENSE/PERMIT``, ``GENERAL SEASON DATES``, etc.
    The antelope table uses a different, smaller set: ``LICENSE``, ``SEASON DATES``,
    etc. Both formats are valid DEA tables and both need to be recognized here.
    """
    normalized = {_normalize_header(h) for h in headers}
    if len(_DEA_HEADER_SIGNATURE & normalized) >= _DEA_HEADER_SIGNATURE_MIN_MATCHES:
        return True
    return len(_ANTELOPE_HEADER_SIGNATURE & normalized) >= _ANTELOPE_HEADER_SIGNATURE_MIN_MATCHES


def _is_hd_header_row(row: list[str | None], hd_number: str) -> bool:
    """Return True if ``row`` is the header row for the given HD number.

    The DEA PDF embeds HD section headers as table rows whose first cell
    matches the ``HD NNN - Name`` pattern (e.g. ``"HD 124 - Arvilla"``).
    """
    first_cell = row[0] if row else None
    if first_cell is None:
        return False
    normalized = _normalize_cell(first_cell)
    if normalized is None:
        return False
    m = _HD_HEADING_REGEX.match(normalized)
    return m is not None and m.group("num") == hd_number


def _is_any_hd_header_row(row: list[str | None]) -> bool:
    """Return True if ``row`` is any HD header row (any HD number)."""
    first_cell = row[0] if row else None
    if first_cell is None:
        return False
    normalized = _normalize_cell(first_cell)
    if normalized is None:
        return False
    return _HD_HEADING_REGEX.match(normalized) is not None


def _slice_hd_rows(
    all_rows: list[list[str | None]],
    target_hd: str,
) -> tuple[bool, list[list[str | None]], bool]:
    """Slice rows belonging to ``target_hd`` from a full-page table row list.

    Returns ``(header_found, data_rows, found_next_hd_before_end)``.

    - ``header_found``: True if the target HD header row was encountered.
    - ``data_rows``: rows between the HD header and the next HD header (exclusive).
    - ``found_next_hd_before_end``: True if a new HD header terminated the slice
      (False if the slice ran to the end of ``all_rows`` with no next-HD marker —
      caller should check the next page for continuation).
    """
    in_section = False
    hd_rows: list[list[str | None]] = []
    found_next = False
    for row in all_rows:
        if not in_section:
            if _is_hd_header_row(row, target_hd):
                in_section = True
            # Skip rows until we find the target HD header.
            continue
        # Inside the section — stop at the next HD header.
        if _is_any_hd_header_row(row):
            found_next = True
            break
        hd_rows.append(row)
    return in_section, hd_rows, found_next


def _find_dea_table_on_page(
    pdf: PdfDocument, page_1based: int, context_hd: str, start_page_1based: int
) -> TableMatch | None:
    """Return the first DEA-signature table on ``page_1based``, or ``None``.

    Raises ``PdfExtractionError`` if ``page_1based == start_page_1based`` and
    no tables exist at all (fail-loud for the mandatory start page).
    """
    page = pdf.pages[page_1based - 1]
    tables = extract_tables(page)
    if not tables:
        if page_1based == start_page_1based:
            raise PdfExtractionError(
                f"HD {context_hd} on p{start_page_1based}: no tables found on start page"
            )
        return None
    for tm in tables:
        if tm["headers"] and _matches_dea_header(tm["headers"]):
            return tm
    return None


def _extract_hd_table(
    pdf: PdfDocument,
    start_page_1based: int,
    hd_number: str,
) -> tuple[list[str], list[list[str | None]], int]:
    """Locate the regulation rows for ``hd_number`` starting at ``start_page_1based``.

    Returns ``(header_row, data_rows, last_page_consumed_1based)``.

    Structural note (discovered during T4/T5 live inspection, 2026-05-06):
    The DEA PDF uses one large table per page that spans all HDs on that page.
    HD sections are delimited by embedded header rows within the table — the
    first cell matches "HD NNN - Name". This function locates the full-page
    table, finds the rows belonging to ``hd_number``, and returns them.

    Multi-page continuation: some HDs span multiple pages. When the end of the
    current page's data is reached without finding the next HD header, look
    ahead up to 2 pages for continuation rows (cap per the spec).

    ``header_row`` is the table column header list (``None`` cells converted to
    ``""``). ``data_rows`` has ``_normalize_cell`` applied to every cell.
    ``last_page_consumed_1based`` reports the highest page from which rows were
    collected.

    Fail-loud cases (ADR-001):
    - No tables on the start page → raises ``PdfExtractionError``.
    - No DEA-signature table on the start page → raises ``PdfExtractionError``.
    - HD header row for ``hd_number`` not found in the table → raises
      ``PdfExtractionError`` (signals the caller passed the wrong start page).
    """
    total_pages = len(pdf.pages)

    start_tm = _find_dea_table_on_page(pdf, start_page_1based, hd_number, start_page_1based)
    if start_tm is None:
        raise PdfExtractionError(
            f"HD {hd_number} on p{start_page_1based}: no DEA table with expected headers"
        )

    # Column header row: convert None cells to "".
    header_row: list[str] = [h if h is not None else "" for h in start_tm["headers"]]

    # Slice data rows for this HD from the full-page table.
    header_found, raw_rows, found_next_hd = _slice_hd_rows(start_tm["rows"], hd_number)

    if not header_found:
        # The target HD header was not found in the start page table at all —
        # this means the caller resolved the wrong start page (or the regex
        # didn't match because the heading is formatted differently in the source).
        raise PdfExtractionError(
            f"HD {hd_number} on p{start_page_1based}: HD header row not found in "
            f"the DEA table — wrong start page or heading format mismatch"
        )

    last_page_consumed = start_page_1based
    data_rows: list[list[str | None]] = [
        [_normalize_cell(cell) for cell in row] for row in raw_rows
    ]

    # Multi-page continuation: if no next-HD header terminated the slice, the
    # section may continue on the next page(s). Cap at 2 lookahead pages — if
    # an intervening page has no DEA-format table (interstitial blank/footer/
    # photo page), continue probing rather than aborting the lookahead, since
    # the docstring's "2-page cap" intent must be honored even when a non-DEA
    # page sits between the HD's start and continuation.
    if not found_next_hd:
        for lookahead in range(1, 3):
            next_page_1based = start_page_1based + lookahead
            if next_page_1based > total_pages:
                break
            cont_tm = _find_dea_table_on_page(
                pdf, next_page_1based, hd_number, start_page_1based
            )
            if cont_tm is None:
                # Interstitial page with no DEA table — keep probing within
                # the lookahead cap; do NOT abort.
                continue
            cont_found, cont_raw_rows, cont_found_next = _slice_hd_rows(
                cont_tm["rows"], hd_number
            )
            if cont_found and cont_raw_rows:
                # Continuation rows found for this HD on the next page.
                data_rows.extend(
                    [_normalize_cell(cell) for cell in row] for row in cont_raw_rows
                )
                last_page_consumed = next_page_1based
                if cont_found_next:
                    break
            else:
                # The page has a DEA table but it belongs to a different HD —
                # our section ended at the prior page. Stop looking.
                break

    _logger.debug(
        "HD %s p%d: %d rows, ended p%d",
        hd_number,
        start_page_1based,
        len(data_rows),
        last_page_consumed,
    )
    return header_row, data_rows, last_page_consumed


# ---------------------------------------------------------------------------
# T5b: Species-banner row splitter (deer/elk interleaved within each HD)
# ---------------------------------------------------------------------------


def _split_rows_by_species(
    data_rows: list[list[str | None]],
) -> dict[str, list[list[str | None]]]:
    """Split an HD's data rows into per-species sub-lists using banner rows.

    The DEA PDF embeds species banner rows (e.g. ``['DEER', None, ...]``,
    ``['ELK', None, ...]``) within each HD's row list. This function walks
    the rows, tracks the current species from each banner it encounters, and
    partitions non-banner rows into per-species buckets.

    Returns a dict keyed by lowercase species name (``"deer"``, ``"elk"``,
    ``"antelope"``). Missing species produce empty lists rather than missing
    keys — callers can rely on ``result.get("deer", [])`` semantics.

    Rows before the first species banner are assigned to a ``"_unknown"``
    bucket and logged at WARNING (structural anomaly; should not occur in
    well-formed DEA booklets).
    """
    result: dict[str, list[list[str | None]]] = {
        "deer": [],
        "elk": [],
        "antelope": [],
    }
    current_species: str | None = None
    unknown_rows: list[list[str | None]] = []

    _BANNER_MAP = {"DEER": "deer", "ELK": "elk", "ANTELOPE": "antelope"}

    for row in data_rows:
        # Check if this row is a species banner.
        first = _normalize_cell(row[0] if row else None)
        if first is not None and first.upper() in _BANNER_MAP:
            # Only count as a banner if all other cells are absent.
            if all(_normalize_cell(cell) is None for cell in row[1:]):
                current_species = _BANNER_MAP[first.upper()]
                continue

        # Regular data row — route to current species bucket.
        if current_species is None:
            unknown_rows.append(row)
        else:
            result.setdefault(current_species, []).append(row)

    if unknown_rows:
        _logger.warning(
            "_split_rows_by_species: %d rows appeared before any species banner "
            "and were dropped — this is a structural anomaly; inspect the source page",
            len(unknown_rows),
        )

    return result


# ---------------------------------------------------------------------------
# T7: Per-HD season_windows aggregator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T6: Row → license-extraction with per-row season_coverage AND per-row windows
# ---------------------------------------------------------------------------
#
# UAT-fix note (2026-05-08, defect D1): we used to compute section-level
# windows here via ``_aggregate_section_season_windows`` (first-observation-wins
# across all rows in the section), then filter per-row by ``season_coverage``.
# That approach replaced source data with a paraphrase: HD 124 deer has three
# distinct General Season windows (Oct 24-Oct 30, Oct 24-Nov 29, Oct 31-Nov 29)
# but the artifact carried only the first observation for all rows. ADR-008
# requires verbatim per-row preservation. Per-row windows now read directly
# from each row's column cells; the divergence-warning branch was deleted
# because divergence is the data, not an anomaly.


def _rows_to_license_extractions(
    header_row: list[str | None],
    data_rows: list[list[str | None]],
    page_reference: PageReference,
    *,
    is_statewide_overlay: bool = False,
) -> list[DeaRowExtraction]:
    """Convert raw table rows to a list of ``DeaRowExtraction`` records.

    Each row in ``data_rows`` (already cell-normalized by T5) becomes one
    ``DeaRowExtraction``. Per-row ``season_coverage`` and ``season_windows``
    are read directly from each row's own column cells — see the module
    block comment above for the UAT-fix rationale (D1, 2026-05-08).

    ``is_statewide_overlay``: when True, the universal "900-20 overlay row"
    filter is bypassed. Used by the orchestrator's STATEWIDE section path
    where the input row IS the 900-20 row by design (UAT-fix D3+D4+D5+D6,
    2026-05-08); per-HD paths leave this False so 900-20 rows continue to
    be filtered from per-HD sections.

    Fail-loud cases (ADR-001):
    - A non-empty row missing a ``LICENSE/PERMIT`` value → raises
      ``PdfExtractionError``.
    - A non-empty row missing an ``OPPORTUNITY`` value → raises
      ``PdfExtractionError``.

    Unknown column headers (not in ``_SEASON_COLUMN_TO_KEY`` or
    ``_NON_SEASON_COLUMNS``) are logged at WARNING and ignored.
    """
    # ------------------------------------------------------------------
    # Build column-name → index maps
    # ------------------------------------------------------------------
    # Maps normalized header → column index for season columns.
    season_col_map: dict[str, int] = {}
    # Maps normalized header → column index for non-season named columns.
    named_col_map: dict[str, int] = {}

    for col_idx, raw_header in enumerate(header_row):
        norm = _normalize_header(raw_header)
        if not norm:
            continue
        if norm in _SEASON_COLUMN_TO_KEY:
            season_col_map[norm] = col_idx
        elif norm in _NON_SEASON_COLUMNS:
            named_col_map[norm] = col_idx
        else:
            _logger.warning("unknown column header %r", raw_header)

    # Column-name aliases: the antelope section uses shortened column names
    # that differ from the deer/elk format. Inject canonical → alias mappings
    # so _get_cell("LICENSE/PERMIT") also resolves the antelope "LICENSE" column,
    # and the extras column resolves regardless of spelling variation.
    # Only inject if the canonical name is absent AND the alias is present.
    _COLUMN_ALIASES: dict[str, str] = {
        "LICENSE/PERMIT": "LICENSE",
        "OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS": "OPPORTUNITY SPECIFC INFORMATION/ RESTRICTIONS",
    }
    for canonical, alias in _COLUMN_ALIASES.items():
        if canonical not in named_col_map and alias in named_col_map:
            named_col_map[canonical] = named_col_map[alias]

    # ------------------------------------------------------------------
    # Helper: safe cell access by normalized header name
    # ------------------------------------------------------------------
    def _get_cell(row: list[str | None], norm_header: str) -> str | None:
        col_idx = named_col_map.get(norm_header)
        if col_idx is None:
            return None
        try:
            return row[col_idx]
        except IndexError:
            return None

    # ------------------------------------------------------------------
    # Per-row processing
    # ------------------------------------------------------------------
    results: list[DeaRowExtraction] = []
    # License code carry-forward: the DEA PDF groups sub-opportunity rows under
    # a single license code. Rows after the first may have None in the
    # LICENSE/PERMIT cell — they inherit the most recent non-None license code.
    # Opportunity carry-forward: similarly, some sub-rows carry only season/extras
    # data without repeating the opportunity text (e.g. CWD-zone variants of the
    # same license). They inherit the most recent non-None opportunity.
    last_license_code: str | None = None
    last_opportunity: str | None = None

    for row in data_rows:
        # Skip rows where every cell is empty/whitespace.
        if all(_normalize_cell(cell) is None for cell in row):
            continue
        # Skip the 900-20 statewide overlay row from per-HD sections.
        # Universal filter — guards against the overlay row appearing in
        # any per-HD section due to layout drift. Bypassed when this call
        # is constructing the STATEWIDE section itself, where the 900-20
        # row IS the intended input (UAT-fix D3+D4+D5+D6, 2026-05-08).
        if not is_statewide_overlay and _is_900_20_overlay_row(row):
            continue
        # Skip "Region N" footer rows. These are FWP region designators that
        # appear at the bottom of antelope tables and (rarely) elk tables —
        # scope footers, not regulation rows. They have no licensed seasons
        # and would otherwise contaminate the artifact with all-False
        # season_coverage rows that downstream consumers must each filter.
        if _is_region_footer_row(row):
            _logger.debug(
                "skipping Region footer row: %r", _normalize_cell(row[0])
            )
            continue

        # Skip label-only rows: any row where the first cell has content but
        # every other cell is None. These are sub-section headers / scope
        # labels embedded in the multi-HD table (e.g. "ELK Hunting by Drawing
        # Only" — a sub-section heading inside the elk regulation pages, not
        # a license row). The species-banner detector below catches the strict
        # ['DEER'/'ELK'/'ANTELOPE', None, ...] form; this filter generalizes
        # to any single-cell label whose remaining cells are empty.
        #
        # IMPORTANT: filter ONLY rows whose first cell does NOT contain an
        # HD-code pattern (\b\d{3}-\d{2}\b). A row like "Deer B License:
        # 124-00" with all other cells None is almost certainly a pdfplumber
        # parse failure on a real regulation row, NOT a label — the HD code
        # is the primary key. Such rows fall through to the carry-forward
        # logic and fail loud at the missing-OPPORTUNITY guard per ADR-001,
        # giving an operator-visible signal rather than silent data loss.
        if len(row) > 1:
            first_cell = _normalize_cell(row[0])
            if (
                first_cell is not None
                and not re.search(r"\b\d{3}-\d{2}\b", first_cell)
                and all(_normalize_cell(cell) is None for cell in row[1:])
            ):
                _logger.debug("skipping label-only row: %r", first_cell)
                continue

        # Skip species-banner rows (e.g. ['DEER', None, ...], ['ELK', None, ...]).
        if _is_species_banner_row(row):
            continue

        # --- Required fields (carry-forward on None within a license group) ---
        raw_license = _get_cell(row, "LICENSE/PERMIT")
        license_code = _normalize_cell(raw_license)
        if license_code:
            # New license code — update carry-forward state AND reset the
            # opportunity carry-forward, since opportunity carry-forward is
            # scoped to a single license group. Without this reset, a new
            # license whose first row is missing OPPORTUNITY (pdfplumber drop)
            # would silently inherit the previous license's opportunity and
            # corrupt the extracted record.
            last_license_code = license_code
            last_opportunity = None
        elif last_license_code is not None:
            # Inherit from the previous row (sub-opportunity pattern).
            license_code = last_license_code
        else:
            raise PdfExtractionError(f"row missing LICENSE/PERMIT: {row}")

        raw_opp = _get_cell(row, "OPPORTUNITY")
        opportunity = _normalize_cell(raw_opp)
        if opportunity:
            # New opportunity — update carry-forward state.
            last_opportunity = opportunity
        elif last_opportunity is not None:
            # Inherit from the previous row in the same license group
            # (season-variant sub-row pattern). Carry-forward is reset above
            # whenever a new license_code arrives, so this branch only fires
            # for legitimate sub-rows under the current license.
            opportunity = last_opportunity
        else:
            raise PdfExtractionError(f"row missing OPPORTUNITY: {row}")

        # --- Nullable fields ---
        # NOTE: _is_season_cell_absent also applies here — "-" is the universal
        # DEA absence sentinel, not just a season-column sentinel.  Apply it
        # before _normalize_cell so "-" is treated as null, not a string value.
        apply_by_raw = _get_cell(row, "APPLY BY DATE")
        apply_by = None if _is_season_cell_absent(apply_by_raw) else _normalize_cell(apply_by_raw)

        raw_quota = _normalize_cell(_get_cell(row, "QUOTA"))
        quota: int | None = None
        if raw_quota is not None and not _is_season_cell_absent(raw_quota):
            # Strip commas before parsing — DEA tables format thousands as
            # "5,600" (e.g. the antelope statewide overlay's pool size). The
            # naive `int(raw_quota)` and `re.match(r"^\d+", ...)` fallback
            # would silently truncate "5,600" to 5, losing 99.9% of the
            # quota's value.
            stripped = raw_quota.replace(",", "")
            if stripped.isdigit():
                quota = int(stripped)
            else:
                # Match a leading number that may include thousand-separator
                # commas (e.g. "5,600 (limited entry)" → 5600).
                m = re.match(r"^[\d,]+", raw_quota)
                if m:
                    digits = m.group().replace(",", "")
                    if digits.isdigit():
                        quota = int(digits)
                # else quota stays None

        quota_range_raw = _get_cell(row, "QUOTA RANGE")
        quota_range = None if _is_season_cell_absent(quota_range_raw) else _normalize_cell(quota_range_raw)

        # Extras: column-cell normalize, then collapse ALL whitespace runs
        # (including single newlines) to a single space. The DEA antelope
        # extras column embeds multi-sentence prose with `\n` between
        # sentences (e.g., the 900-20 row's "First and only
        # choice.\nArchEquip only."); the natural reading is a single
        # space-separated paragraph. _normalize_cell intentionally
        # preserves single newlines (the HD heading detector depends on
        # that) so this extra collapse is applied only at the extras
        # write-site.
        extras_raw = _get_cell(row, "OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS")
        if _is_season_cell_absent(extras_raw):
            extras: str | None = None
        else:
            normalized_extras = _normalize_cell(extras_raw)
            extras = (
                re.sub(r"\s+", " ", normalized_extras)
                if normalized_extras is not None
                else None
            )

        # --- season_coverage AND season_windows: read each row's own cells ---
        # The DEA PDF uses "-" as a sentinel for "not applicable" in season
        # columns. Both None and "-" map to coverage=False.
        # Per-row windows are sourced from each row's own column cells, NOT
        # from a section-level aggregator (UAT-fix D1, 2026-05-08). This
        # preserves natural per-license-row date variation that was previously
        # collapsed by first-observation-wins.
        coverage = SeasonCoverage(
            early_season=False,
            archery_only=False,
            general=False,
            heritage_muzzleloader=False,
            late=False,
        )
        row_windows: dict[str, SeasonWindow] = {}
        for season_col_name, col_idx in season_col_map.items():
            season_key = _SEASON_COLUMN_TO_KEY[season_col_name]
            try:
                raw_season_cell = row[col_idx]
            except IndexError:
                raw_season_cell = None
            if _is_season_cell_absent(raw_season_cell):
                # SeasonCoverage keys match the season_key strings exactly.
                coverage[season_key] = False  # type: ignore[literal-required]
                continue
            coverage[season_key] = True  # type: ignore[literal-required]
            cell_norm = _normalize_cell(raw_season_cell)
            if cell_norm is not None:
                row_windows[season_key] = SeasonWindow(
                    window=cell_norm,
                    weapon_type_override=_WEAPON_TYPE_OVERRIDE_BY_COLUMN[
                        season_col_name
                    ],
                )

        results.append(
            DeaRowExtraction(
                license_code=license_code,
                opportunity=opportunity,
                apply_by=apply_by,
                quota=quota,
                quota_range=quota_range,
                season_coverage=coverage,
                season_windows=row_windows,
                weapon_types=["any_legal_weapon"],
                extras=extras,
                extraction_confidence=ConfidenceTier.HIGH,
                page_reference=page_reference,
            )
        )

    return results


# ---------------------------------------------------------------------------
# T8: Statewide antelope overlay handling
# ---------------------------------------------------------------------------
#
# UAT-fix note (2026-05-08, defects D3+D4+D5+D6): the previous implementation
# was a hand-rolled regex parser (``_ANTELOPE_900_ROW_RE`` +
# ``_extract_statewide_antelope_overlay``) that synthesized the STATEWIDE row
# with column-position remap (Aug.15-Nov.08 mapped to ``archery_only`` because
# the extras text said "ArchEquip only", but the date was actually in the
# **Season Dates** column = ``general`` per the column-header mapping). It
# also stripped the ``"Antelope License: "`` prefix, dropped the verbatim
# extras text, and stripped commas from quota_range — every per-HD antelope
# row preserved these. The synthesized form violated ADR-008.
#
# The new design: the antelope orchestrator walks rows, and on the FIRST
# 900-20 row it captures the row data, sets ``hd_number="STATEWIDE"``, and
# emits a section using the same ``_rows_to_license_extractions`` machinery
# as any other antelope row. Subsequent 900-20 rows are deduplicated.
# Inline in ``extract()``; no separate helper.
#
# Confidence tier for the STATEWIDE row: MEDIUM. Despite the row being a
# structured table cell (which would normally yield HIGH via the table-source
# path), the directive specifies MEDIUM to reflect that the row is a
# meta-row summarizing statewide applicability rather than a per-HD
# regulation. The orchestrator forces MEDIUM by passing ``source="prose"``
# to ``_assign_row_confidence``.


# ---------------------------------------------------------------------------
# T9: Per-row confidence assignment
# ---------------------------------------------------------------------------


def _assign_row_confidence(row: "DeaRowExtraction", source: str) -> str:
    """Assign an extraction confidence tier to a single row per ADR-017.

    ``source`` must be ``"table"`` (per-HD table cell) or ``"prose"`` (statewide
    overlay from prose row). All other values raise ``ValueError``.

    Logic:
    - ``"prose"`` → always ``ConfidenceTier.MEDIUM``.
    - ``"table"`` with a well-formed HD code (``\\d{3}-\\d{2}``), non-empty
      opportunity, and at least one ``True`` season_coverage flag → ``HIGH``.
    - ``"table"`` with well-formed code but all-False season_coverage → ``LOW``
      with a WARNING (structural red flag; warrant reviewer attention).
    - ``"table"`` with a prose-style code (no numeric code match) but otherwise
      valid → ``MEDIUM`` (structured cell, but not the codified HD format).
    - ``"table"`` with an empty opportunity → ``LOW`` with a WARNING.
    """
    if source == "prose":
        return ConfidenceTier.MEDIUM

    if source == "table":
        license_code = row["license_code"]
        opportunity = row["opportunity"]
        coverage = row["season_coverage"]

        # Check whether the license code contains a well-formed HD code like
        # "262-50". Use search (not match) because real DEA cells often embed
        # the HD code inside compound prose (e.g. "Deer B License: 124-00").
        # Pure-code cells ("262-50") match too. Prose-only license names
        # ("General Deer License") have no HD code and stay at MEDIUM.
        is_hd_code = bool(re.search(r"\b\d{3}-\d{2}\b", license_code))

        # Empty opportunity is always LOW regardless of code format.
        if not opportunity:
            _logger.warning(
                "row %r has empty opportunity — flagged LOW confidence", license_code
            )
            return ConfidenceTier.LOW

        if not is_hd_code:
            # Prose-style code (e.g. "General Deer License") in a structured table
            # cell — reduce to MEDIUM, not LOW (it is structured data, just not
            # the codified HD code format).
            if not any(coverage.values()):  # type: ignore[arg-type]
                _logger.warning(
                    "row %r (prose-style code) has all-False season_coverage — flagged MEDIUM, "
                    "but no seasons detected; inspect source page",
                    license_code,
                )
            return ConfidenceTier.MEDIUM

        # Well-formed HD code — check season coverage.
        any_coverage = any(coverage[key] for key in coverage)  # type: ignore[literal-required]
        if not any_coverage:
            _logger.warning(
                "row %r has all-False season_coverage — flagged LOW confidence", license_code
            )
            return ConfidenceTier.LOW

        return ConfidenceTier.HIGH

    raise ValueError(f"unknown source {source!r}")


# ---------------------------------------------------------------------------
# T10: Sort key helper
# ---------------------------------------------------------------------------


def _sort_key(section: "DeaSectionExtraction") -> tuple[int, tuple[int, int]]:
    """Return a deterministic sort key for a ``DeaSectionExtraction``.

    Ordering: (species_order, hd_sort_key)
    - ``species_order``: deer=0, elk=1, antelope=2.
    - ``hd_sort_key``: ``(0, int(hd_number))`` for numeric HDs; ``(1, 0)`` for
      ``"STATEWIDE"`` — sorts last within species.
    """
    species_order = {"deer": 0, "elk": 1, "antelope": 2}
    sp = species_order.get(section["species_group"], 99)

    hd_number = section["hd_number"]
    if hd_number == "STATEWIDE":
        hd_sort: tuple[int, int] = (1, 0)
    else:
        hd_sort = (0, int(hd_number))

    return (sp, hd_sort)


# ---------------------------------------------------------------------------
# T10: Manifest helper + public extraction function
# ---------------------------------------------------------------------------


def _load_extracted_at_from_manifest(pdf_path: Path) -> str:
    """Return ``fetched_at`` from the S03.1 PDF manifest for *pdf_path*.

    Manifest path convention (mirrors S03.1): same directory as the PDF,
    stem + ``"-pdf-manifest.json"``.  Raises ``PdfExtractionError`` if the
    manifest is absent or the ``fetched_at`` field is missing — ADR-001
    fail-loud; falling back to ``datetime.now()`` would silently re-introduce
    non-determinism.
    """
    manifest_path = pdf_path.with_name(pdf_path.stem + "-pdf-manifest.json")
    if not manifest_path.exists():
        raise PdfExtractionError(
            f"manifest not found at {manifest_path} — has fetch_pdfs.py been run?"
        )
    with manifest_path.open() as fh:
        data = json.load(fh)
    if "fetched_at" not in data:
        raise PdfExtractionError(
            f"manifest at {manifest_path} is missing 'fetched_at' field"
        )
    fetched_at = data.get("fetched_at")
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        raise PdfExtractionError(
            f"manifest at {manifest_path} has invalid 'fetched_at' value: {fetched_at!r} "
            f"— expected a non-empty ISO timestamp string"
        )
    return fetched_at


def extract(pdf_path: Path) -> list["DeaSectionExtraction"]:
    """Extract all per-HD regulation rows from the Montana DEA booklet.

    Real-PDF structural note (discovered during T10 live run, 2026-05-07):
    The DEA booklet does NOT have a single "ELK REGULATIONS" banner page that
    splits the deer/elk section. Instead, deer and elk HDs are interleaved
    within the same per-HD table rows using species banner rows (e.g.
    ``['DEER', None, ...]``, ``['ELK', None, ...]``). Each HD heading on pages
    48–123 is followed by separate DEER and ELK sub-sections in that order.

    Strategy: iterate all HDs in the deer/elk range (48–123); for each HD call
    ``_extract_hd_table`` to get ALL rows (both deer and elk), then use
    ``_split_rows_by_species`` to partition by the embedded species banners.
    This produces one ``DeaSectionExtraction`` per (HD, species) combination —
    the same output schema as the plan intended, just via a different splitting
    strategy.

    Antelope HDs (136–141) contain only ``['ANTELOPE', None, ...]`` banners;
    the same split mechanism is used but only the "antelope" bucket is non-empty.

    Fail-loud cases (ADR-001):
    - Any per-HD table extraction failure → ``PdfExtractionError`` with context.
    - Antelope statewide overlay not found → ``PdfExtractionError``.
    """
    extracted_at = _load_extracted_at_from_manifest(pdf_path)
    sections: list[DeaSectionExtraction] = []

    with open_pdf(pdf_path) as pdf:
        # ------------------------------------------------------------------
        # Deer/elk HDs: pp. 48–123 (interleaved per HD via species banners).
        # ------------------------------------------------------------------
        for hd_number, hd_name, _sg, page_num, _section_bbox in _iter_hd_sections(
            pdf, _DEER_ELK_PAGES, "deer"  # species arg unused here; split below
        ):
            try:
                headers, data_rows, _last_page = _extract_hd_table(
                    pdf, page_num, hd_number
                )
            except PdfExtractionError as e:
                raise PdfExtractionError(
                    f"HD={hd_number} ({hd_name}) p{page_num}: {e}"
                ) from e

            # Capture verbatim page text for the section's starting page.
            page_text = ""
            for _pn, page in iter_pages(pdf, page_num, page_num):
                page_text = extract_text(page)
                break

            # Split the HD's rows into per-species buckets.
            species_rows = _split_rows_by_species(data_rows)

            # Build one DeaSectionExtraction per species that has rows.
            headers_nullable: list[str | None] = list(headers)
            for species in ("deer", "elk"):
                sp_rows = species_rows.get(species, [])
                if not sp_rows:
                    # This HD has no data for this species — skip silently.
                    continue

                page_reference = PageReference(
                    pdf_filename=_PDF_FILENAME_FOR_REF,
                    page_num_1based=page_num,
                    bbox=None,
                    extracted_at=extracted_at,
                )

                rows = _rows_to_license_extractions(
                    headers_nullable, sp_rows, page_reference
                )

                for row in rows:
                    row["extraction_confidence"] = _assign_row_confidence(row, "table")

                sections.append(
                    DeaSectionExtraction(
                        hd_number=hd_number,
                        hd_name=hd_name,
                        species_group=species,
                        license_year=_LICENSE_YEAR,
                        page_reference=page_reference,
                        verbatim_text=page_text,
                        rows=rows,
                    )
                )

        # ------------------------------------------------------------------
        # Antelope HDs: pp. 136–141.
        #
        # Walks the antelope tables row-by-row, building "logical sections":
        #   - HD-numbered: ``HD NNN - Name`` delimiter → 1 section per delimiter
        #   - Portions: ``Portions of HDs A, B, C ... <directional>`` delimiter
        #     → 1 section per listed HD with the same row content (option (a)
        #     per UAT-fix directive 2026-05-08). License codes disambiguate at
        #     S03.6 ingestion.
        #
        # ``Region N`` rows are skipped (not regulation rows). The first 900-20
        # row encountered becomes the STATEWIDE section; subsequent 900-20 rows
        # are filtered (deduplication).
        # ------------------------------------------------------------------
        antelope_pending: list[
            tuple[
                list[str],  # hd_numbers
                str,  # hd_name
                str,  # verbatim_text
                int,  # page_num
                list[str | None],  # headers
                list[list[str | None]],  # data_rows for this logical section
            ]
        ] = []
        statewide_row: list[str | None] | None = None
        statewide_headers: list[str | None] | None = None
        statewide_page_num: int | None = None

        # Walking state for the current logical section.
        cur_hd_numbers: list[str] | None = None
        cur_hd_name: str = ""
        cur_verbatim: str = ""
        cur_page_num: int = 0
        cur_headers: list[str | None] | None = None
        cur_rows: list[list[str | None]] = []

        def _flush_current() -> None:
            nonlocal cur_hd_numbers, cur_hd_name, cur_verbatim
            nonlocal cur_page_num, cur_headers, cur_rows
            if cur_hd_numbers and cur_rows and cur_headers is not None:
                antelope_pending.append(
                    (
                        list(cur_hd_numbers),
                        cur_hd_name,
                        cur_verbatim,
                        cur_page_num,
                        list(cur_headers),
                        list(cur_rows),
                    )
                )
            cur_hd_numbers = None
            cur_hd_name = ""
            cur_verbatim = ""
            cur_page_num = 0
            cur_headers = None
            cur_rows = []

        for page_num, page in iter_pages(pdf, *_ANTELOPE_PAGES):
            page_text = extract_text(page)
            tables = extract_tables(page)
            for tm in tables:
                if not tm["headers"] or not _matches_dea_header(tm["headers"]):
                    continue
                table_headers = tm["headers"]
                for data_row in tm["rows"]:
                    # HD-numbered delimiter: "HD NNN - Name" in first cell.
                    if _is_any_hd_header_row(data_row):
                        _flush_current()
                        first_norm = _normalize_cell(data_row[0]) or ""
                        m = _HD_HEADING_REGEX.match(first_norm)
                        if m is None:
                            continue
                        cur_hd_numbers = [m.group("num")]
                        cur_hd_name = m.group("name").strip()
                        cur_verbatim = page_text
                        cur_page_num = page_num
                        cur_headers = table_headers
                        cur_rows = []
                        continue
                    # Portions sub-section delimiter: "Portions of HDs A, B, C ..."
                    if _is_portions_subsection_row(data_row):
                        _flush_current()
                        portions_text = _normalize_cell(data_row[0]) or ""
                        hd_list = _parse_portions_hd_list(portions_text)
                        if not hd_list:
                            _logger.warning(
                                "antelope p%d: failed to parse Portions HD list "
                                "from %r — skipping section",
                                page_num,
                                portions_text,
                            )
                            continue
                        cur_hd_numbers = hd_list
                        cur_hd_name = ""
                        # Preserve the directional qualifier in verbatim_text
                        # so S03.10 binding generation can decide whether the
                        # qualifier matters geometrically.
                        cur_verbatim = portions_text
                        cur_page_num = page_num
                        cur_headers = table_headers
                        cur_rows = []
                        continue
                    # Region N footer/header row: skip (not a regulation row).
                    if _is_region_footer_row(data_row):
                        continue
                    # 900-20 row: capture as STATEWIDE on first sighting; else skip.
                    if _is_900_20_overlay_row(data_row):
                        if statewide_row is None:
                            statewide_row = data_row
                            statewide_headers = table_headers
                            statewide_page_num = page_num
                        continue
                    # Regular regulation row: append to current section.
                    if cur_hd_numbers is not None:
                        cur_rows.append(data_row)
        _flush_current()

        # Emit one DeaSectionExtraction per logical section per HD listed.
        for (
            hd_numbers,
            hd_name,
            verbatim_text,
            page_num,
            section_headers,
            section_data_rows,
        ) in antelope_pending:
            page_reference = PageReference(
                pdf_filename=_PDF_FILENAME_FOR_REF,
                page_num_1based=page_num,
                bbox=None,
                extracted_at=extracted_at,
            )
            try:
                rows = _rows_to_license_extractions(
                    section_headers, section_data_rows, page_reference
                )
            except PdfExtractionError as e:
                raise PdfExtractionError(
                    f"species=antelope HD={hd_numbers} ({hd_name}) p{page_num}: {e}"
                ) from e
            if not rows:
                continue
            for row in rows:
                row["extraction_confidence"] = _assign_row_confidence(row, "table")
            for hd_num in hd_numbers:
                sections.append(
                    DeaSectionExtraction(
                        hd_number=hd_num,
                        hd_name=hd_name,
                        species_group="antelope",
                        license_year=_LICENSE_YEAR,
                        page_reference=page_reference,
                        verbatim_text=verbatim_text,
                        # Shallow copy: each emitted section gets its own list
                        # but rows themselves are shared (TypedDicts are
                        # immutable enough for downstream consumers; if a
                        # consumer mutates a row we want those mutations to
                        # propagate to all HDs that bind to the same regulation).
                        rows=list(rows),
                    )
                )

        # ------------------------------------------------------------------
        # STATEWIDE 900-20 antelope overlay: column-faithful row construction.
        # Per UAT-fix D3+D4+D5+D6 (2026-05-08), the STATEWIDE row uses the
        # SAME _rows_to_license_extractions machinery as any other antelope
        # row. The hand-rolled parser was deleted because it remapped the
        # date column (Aug.15-Nov.08 lives in Season Dates = general, NOT
        # in Archery Season Dates), dropped the verbatim extras text,
        # stripped the "Antelope License: " prefix, and stripped commas.
        # All four of those defects vanish when the row goes through the
        # same path as per-HD antelope rows.
        # ------------------------------------------------------------------
        if statewide_row is not None and statewide_headers is not None and statewide_page_num is not None:
            statewide_page_reference = PageReference(
                pdf_filename=_PDF_FILENAME_FOR_REF,
                page_num_1based=statewide_page_num,
                bbox=None,
                extracted_at=extracted_at,
            )
            statewide_rows = _rows_to_license_extractions(
                statewide_headers,
                [statewide_row],
                statewide_page_reference,
                is_statewide_overlay=True,
            )
            if statewide_rows:
                # weapon_types override: the extras column ("First and only
                # choice. ArchEquip only.") is the source-of-truth for the
                # archery restriction. Per directive Fix 3, weapon_types stays
                # ["archery"] for STATEWIDE despite the row having coverage
                # in the general column. The default ["any_legal_weapon"] is
                # overridden post-construction.
                statewide_rows[0]["weapon_types"] = ["archery"]
                # Confidence: directive specifies MEDIUM (a meta-row
                # summarizing statewide applicability, not a per-HD
                # regulation). Pass source="prose" through the existing
                # path which always returns MEDIUM.
                statewide_rows[0]["extraction_confidence"] = (
                    _assign_row_confidence(statewide_rows[0], "prose")
                )
                # verbatim_text: capture the page text where the 900-20 row
                # was first seen. The row's first cell alone ("Antelope
                # License: 900-20") would be too narrow to satisfy ADR-008
                # for an artifact that downstream stories use as faithfulness
                # ground truth. Page-level text matches the per-HD antelope
                # section convention.
                statewide_page = pdf.pages[statewide_page_num - 1]
                statewide_verbatim = extract_text(statewide_page)
                sections.append(
                    DeaSectionExtraction(
                        hd_number="STATEWIDE",
                        hd_name="",
                        species_group="antelope",
                        license_year=_LICENSE_YEAR,
                        page_reference=statewide_page_reference,
                        verbatim_text=statewide_verbatim,
                        rows=[statewide_rows[0]],
                    )
                )
        else:
            raise PdfExtractionError(
                f"antelope STATEWIDE 900-20 overlay row not found in pp."
                f"{_ANTELOPE_PAGES[0]}-{_ANTELOPE_PAGES[1]}"
            )

    # Sort deterministically by (species_order, hd_sort_key).
    sections.sort(key=_sort_key)

    return sections


# ---------------------------------------------------------------------------
# T10: CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the DEA extractor.

    Usage:
        ingestion/.venv/bin/python ingestion/states/montana/extract_dea.py
        ingestion/.venv/bin/python ingestion/states/montana/extract_dea.py \\
            --pdf /path/to/dea.pdf --out /tmp/dea-2026.json
    """
    parser = argparse.ArgumentParser(
        description="Extract DEA per-HD regulations from the Montana DEA booklet",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=_DEA_PDF_PATH,
        help="Path to DEA PDF (default: fetched fixture)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_OUTPUT_PATH,
        help="Output JSON path (default: ingestion/states/montana/extracted/dea-2026.json)",
    )
    args = parser.parse_args(argv)

    # Configure logging only if no handlers are already registered (avoids
    # double-init when this module is imported by tests or orchestrators).
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

    if not args.pdf.exists():
        _logger.error("DEA PDF not found at %s — run fetch_pdfs.py first", args.pdf)
        return 1

    try:
        sections = extract(args.pdf)
    except PdfExtractionError as e:
        _logger.error("extraction failed: %s", e)
        return 2

    # Ensure output directory exists.
    args.out.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: serialize to a .tmp sibling, then replace.
    # Using args.out.parent / (args.out.name + ".tmp") avoids Path.with_suffix
    # misinterpreting ".json.tmp" as a double-extension.
    payload = json.dumps(sections, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp_path = args.out.parent / (args.out.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(args.out)  # atomic on POSIX; replace() safe on Windows too

    _logger.info("wrote %d sections to %s", len(sections), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
