"""
Extract draw-mechanics front-matter from the CPW Big Game brochure into a
deterministic JSON artifact for downstream ingestion (S06.8).

The extractor reads two categories of front-matter from the brochure:

1.  **Hybrid draw table** (brochure content pp. 18–19, PDF pp. 28–29):
    Lists all hunt codes that participate in the CPW preference-point hybrid
    draw system.  The table encodes the residency category (Resident /
    Nonresident), species, GMU, season code, method, list type (A / B / C),
    and a low-availability ``*`` marker.  Each row yields one
    ``DrawMechanicsRow`` in the output artifact.

2.  **Application dates table** (brochure content p. 4, PDF p. 14):
    Lists the primary and secondary draw application deadlines per species.
    Captured for ``draw_spec.application_deadline`` population by S06.8.

3.  **Preference-points-only table** per species (PDF pages 30, 45, 63, 72
    for deer / elk / pronghorn / bear respectively):
    The first table on each species' first page lists hunt codes that require
    a minimum number of preference points to draw.  These ``point_only``
    records are modeled separately from hybrid-draw rows because they carry a
    minimum-points threshold, not a pools/caps structure.

    Moose (content p. 58, PDF p. 68, hunt code prefix ``M-P-999-99-P``) is
    deliberately excluded — out of PRD 002 V1 scope (moose uses a
    weighted-preference system, not the hybrid system).

ADR references:
  ADR-001  Authority preserved, not replaced — fail loud; no invented values.
  ADR-005  Python ingestion / TypeScript serving language split.
  ADR-008  Verbatim regulation text — ``verbatim_text`` retains pdfplumber's
           word-grouped output without additional normalization.  Only the
           structured fields use the cleanup rules below.
  ADR-017  Confidence calibration + parent-inheritance rule — per-row
           ``extraction_confidence`` is assigned here.
  ADR-022  Single-Module Per-State PDF Extractors — this module follows the
           monolithic per-extractor convention; do not split into sub-modules.

# probed 2026-06-24

Structural notes from live probe of
``co-cpw-big-game-2026-brochure-2026-03-04.pdf`` (84 pages):

  Hybrid table layout (PDF pp. 28–29 / brochure content pp. 18–19):
    All hybrid hunt-code tables are on PDF page 29; page 28 carries the
    prose "How It Works" column, extracted separately via
    ``_extract_hybrid_mechanics``.  The table columns are approximately:
    ``Res/NR | Species | GMU | Season Code | Method | List``.
    A leading ``*`` on a hunt code signals low availability
    (``low_availability=True``).

  Application dates page (PDF p. 14 / brochure content p. 4):
    Single-page table with columns
    ``Species | Primary Draw Deadline | Secondary Draw Deadline``.
    Date values are month/day strings (e.g. ``April 7``).
    Bbox column crops may be needed to avoid pdfplumber column interleaving.

  Point-only tables (first table on each species' first page):
    Small tables at the top of each species chapter listing hunt codes
    that require a threshold number of preference points to enter.
    Columns: ``Hunt Code | Minimum Points | List``.

  116 total hybrid codes observed across 2 pages (2026-06-24 probe):
    Count band set to (80, 160) — ±38% slack around 116 to absorb
    minor CPW layout changes without a false-positive fail-loud.

Cleanup rules (applied to structured row fields, never to verbatim text):

  Rule R1: detect and strip a leading ``*`` immediately preceding a hunt code
      scope: Hunt Code cell in the hybrid draw table
      rationale: ``*`` is a low-availability marker printed immediately before
                 the hunt code (e.g. ``*D-M-001-O1-A``), with no space between
                 ``*`` and the code.  Detected by inspecting the character
                 immediately before each code match in the cell string, captured
                 as a boolean ``low_availability`` field; the code itself must
                 be clean for ``_HUNT_CODE_RE`` parsing (ADR-001: no data lost
                 — the marker moves to a structured field, not dropped).
      locked by: TestHybridRowParse::test_asterisk_stripped_and_flagged

  Rule R2: collapse internal whitespace in extracted verbatim prose
      regex: ``re.sub(r"\\s+", " ", text).strip()``
      scope: notes / prose cells ONLY (e.g. application-dates footnotes)
      rationale: multi-line pdfplumber output in prose cells embeds ``\\n``
                 between clauses; the natural reading is a single
                 space-separated paragraph.  Applied only to prose cells — NOT
                 globally — because newline preservation is required for
                 structured cell parsing elsewhere.
      locked by: TestNormalize::test_whitespace_collapse_prose

  Rule R3: use bbox column crops for multi-column pages (pp. 14, 29)
      regex: n/a (structural: ``page.crop(bbox)`` before ``extract_text``)
      scope: PDF pages 14 (application dates) and 29 (hybrid draw, right half)
      rationale: pdfplumber's default ``extract_text`` interleaves columns on
                 two-column pages, producing garbled output.  Cropping to each
                 column's x-range before extraction keeps left and right halves
                 separate and parseable.
      locked by: TestColumnCrop::test_right_column_crop_isolates_second_page
"""

# State-specific module — must NOT import from ingestion.states.<other_state>
# or from ingestion.states.colorado.<other_extractor>.
# Cross-state / cross-extractor imports violate ADR-005 isolation.
# The state-agnostic guard test enforces this via AST walk.

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
from pathlib import Path
from typing import Final

from ingestion.lib.pdf import (
    PdfDocument,
    PdfExtractionError,
    TableMatch,
    extract_tables,
    extract_text,
    iter_pages,
    open_pdf,
    write_extraction_artifact,
)

# ---------------------------------------------------------------------------
# Cleanup rules parity constant
# Every ``Rule R{n}:`` entry in the module docstring above must be reflected
# here.  A test will count the ``Rule R`` entries in the docstring and assert
# ``_RULE_COUNT`` matches.
# ---------------------------------------------------------------------------

_RULE_COUNT: Final[int] = 3

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path / file constants
# ---------------------------------------------------------------------------

# parents[3] from ingestion/states/colorado/ reaches the repo root:
#   [0] colorado/  [1] states/  [2] ingestion/  [3] repo root
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

_PDF_FILENAME: Final[str] = "co-cpw-big-game-2026-brochure-2026-03-04.pdf"

_PDF_PATH: Final[Path] = (
    _REPO_ROOT / "ingestion" / "states" / "colorado" / "fixtures" / _PDF_FILENAME
)

_OUTPUT_PATH: Final[Path] = (
    _REPO_ROOT / "ingestion" / "states" / "colorado" / "extracted" / "draw-mechanics-2026.json"
)

# ---------------------------------------------------------------------------
# Metadata constants
# ---------------------------------------------------------------------------

_SOURCE_ID: Final[str] = "co-cpw-big-game-2026-brochure"
_LICENSE_YEAR: Final[int] = 2026

# ---------------------------------------------------------------------------
# Page constants (1-based PDF page numbers, confirmed 2026-06-24 probe)
# Content-page offset = +10 (PDF page = content page + 10).
# ---------------------------------------------------------------------------

# Hybrid draw table: brochure content pp. 18–19 → PDF pages 28–29.
_HYBRID_PAGE: Final[int] = 29

# Application dates table: brochure content p. 4 → PDF page 14.
_DATES_PAGE: Final[int] = 14

# First page of each species chapter (preference-points-only table location).
# Moose (PDF page 68, hunt code prefix M-P-999-99-P) is deliberately excluded —
# out of PRD 002 V1 scope (weighted-preference species, not hybrid draw).
_POINT_ONLY_PAGES: Final[dict[str, int]] = {
    "deer": 30,
    "elk": 45,
    "pronghorn": 63,
    "bear": 72,
}

# ---------------------------------------------------------------------------
# Species mapping
# ---------------------------------------------------------------------------

_SPECIES_LETTER: Final[dict[str, str]] = {
    "deer": "D",
    "elk": "E",
    "pronghorn": "A",
    "bear": "B",
}

# ---------------------------------------------------------------------------
# Count guard (fires pre-db.connect() per OQ7 discipline)
# Empirical from 2026-06-24 live probe: 116 hybrid codes observed.
# Band is (80, 160) — ±38% slack around 116.
# ---------------------------------------------------------------------------

_HYBRID_COUNT_BAND: Final[tuple[int, int]] = (80, 160)

# ---------------------------------------------------------------------------
# Hunt-code grammar
# Mirrors extract_big_game._HUNT_CODE_GRAMMAR and extract_black_bear._HUNT_CODE_RE
# but kept LOCAL per ADR-022 — sibling CO extractors must not cross-import.
# ---------------------------------------------------------------------------

# Five capture groups: (species_letter, sex_code, gmu_code, season_code, method_letter)
# GMU codes are 3–4 digits (e.g. D-M-001-O1-A or D-M-1030-O1-A).
_HUNT_CODE_GRAMMAR: Final[str] = r"([A-Z])-([A-Z])-(\d{3,4})-([A-Z0-9]+)-([A-Z])"

# Anchored parser — matches an entire cell that is exactly one hunt code.
_HUNT_CODE_RE: Final[re.Pattern[str]] = re.compile(rf"^{_HUNT_CODE_GRAMMAR}$")

# Unanchored embedded parser — finds a hunt code as a substring of a prose cell
# (e.g. a cell with a leading ``*`` marker or a prose prefix).
# (Because _HUNT_CODE_GRAMMAR carries component capture groups, we do NOT wrap
# in an additional capturing group — the five inner groups are the API.)
_HUNT_CODE_EMBEDDED_RE: Final[re.Pattern[str]] = re.compile(_HUNT_CODE_GRAMMAR)

# ---------------------------------------------------------------------------
# Error class
# ---------------------------------------------------------------------------


class ColoradoDrawMechanicsError(PdfExtractionError):
    """Raised when draw-mechanics extraction encounters a fatal inconsistency.

    Subclasses ``PdfExtractionError`` so callers catching the base class see
    errors from this module as well (consistent with sibling CO extractors).
    """


# ---------------------------------------------------------------------------
# Manifest loader
# Verbatim port of extract_big_game._load_extracted_at_from_manifest to avoid
# cross-extractor imports (ADR-022 / ADR-005).
# ---------------------------------------------------------------------------


def _load_extracted_at_from_manifest(pdf_path: Path) -> str:
    """Return ``fetched_at`` from the S06.1 PDF manifest for *pdf_path*.

    Manifest path convention (mirrors S03.1 / MT ``extract_dea``):
    same directory as the PDF, stem + ``"-pdf-manifest.json"``.

    Raises ``PdfExtractionError`` if the manifest is absent or the
    ``fetched_at`` field is missing / invalid — ADR-001 fail-loud; falling
    back to ``datetime.now()`` would silently re-introduce non-determinism.
    """
    manifest_path = pdf_path.with_name(pdf_path.stem + "-pdf-manifest.json")
    if not manifest_path.exists():
        raise PdfExtractionError(
            f"manifest not found at {manifest_path} — has fetch_pdfs.py been run?"
        )
    with manifest_path.open() as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise PdfExtractionError(
                f"manifest at {manifest_path} is not valid JSON: {exc}"
            ) from exc
    if "fetched_at" not in data:
        raise PdfExtractionError(
            f"manifest at {manifest_path} is missing 'fetched_at' field"
        )
    fetched_at = data.get("fetched_at")
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        raise PdfExtractionError(
            f"manifest at {manifest_path} has invalid 'fetched_at' value: "
            f"{fetched_at!r} — expected a non-empty ISO timestamp string"
        )
    return fetched_at


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _codes_from_cells(cells: list[str | None]) -> list[tuple[str, bool]]:
    """Scan a flat list of cells and return ``(hunt_code, low_availability)`` pairs.

    Cells may contain a leading ``*`` marker (Rule R1) and/or stray whitespace.
    Each cell can carry at most one hunt code (the table layout has one code per
    cell); multiple matches within a single cell are extracted in order.
    Duplicate ``hunt_code`` values are deduplicated by the caller.
    """
    results: list[tuple[str, bool]] = []
    for raw_cell in cells:
        if not raw_cell:
            continue
        cell_str = str(raw_cell)
        for m in _HUNT_CODE_EMBEDDED_RE.finditer(cell_str):
            start = m.start()
            # Check for the '*' low-availability marker immediately before the
            # matched code in the cell string (Rule R1).
            low_avail = start > 0 and cell_str[start - 1] == "*"
            results.append((m.group(), low_avail))
    return results


def _flatten_table(table: TableMatch) -> list[str | None]:
    """Flatten a ``TableMatch`` (headers + all row cells) into a single list.

    Accepts a ``TableMatch`` TypedDict and concatenates the ``headers`` list
    with all cells from every row in ``rows``.
    """
    cells: list[str | None] = list(table["headers"])
    for row in table["rows"]:
        cells.extend(row)
    return cells


# ---------------------------------------------------------------------------
# T2: Hybrid hunt-code extraction
# ---------------------------------------------------------------------------


def _extract_hybrid_codes(pdf: PdfDocument) -> list[dict[str, object]]:
    """Extract all hybrid draw hunt codes from PDF page 29 of the CPW Big Game brochure.

    All hybrid hunt-code tables are on PDF page 29; page 28 carries the prose
    "How It Works" column, extracted separately via ``_extract_hybrid_mechanics``.

    Returns one ``hybrid_code`` record per unique ``(species, hunt_code)`` pair,
    sorted by ``(species, hunt_code)``.  Each record shape::

        {
            "record_type": "hybrid_code",
            "species":        str,   # "bear" | "deer" | "elk" | "pronghorn"
            "hunt_code":      str,   # clean code, e.g. "D-M-010-W1-R"
            "low_availability": bool, # True when the PDF prints a leading ``*``
        }

    Page layout (PDF p. 29, pdfplumber 0-indexed 28):
      - **Bear** — 3 codes on one line in a small 3-row table (Table 2 via
        ``extract_tables``).  Table 2 only captures 1 of the 3 codes (pdfplumber
        splits the inline text across two columns).  The canonical extraction is
        a bbox crop ``(330.0, 415.0, 590.0, 435.0)`` via ``extract_text``
        (confirmed 2026-06-24: returns all 3 codes on one line).
      - **Deer** — 39 codes across Tables 3, 4, 5 (header + 2 headerless
        continuation tables).
      - **Elk** — 38 codes across Tables 6, 7, 8.
      - **Pronghorn** — 36 codes in Table 9 (wide multi-column layout).

    All three table-extracted species use ``_codes_from_cells`` which applies
    Rule R1 (``*``-strip → ``low_availability`` bool).

    Raises:
        ColoradoDrawMechanicsError: if bear does not yield exactly 3 codes,
            if any species yields zero codes, or if the total count is outside
            ``_HYBRID_COUNT_BAND``.
    """
    if not isinstance(pdf, PdfDocument):
        raise ColoradoDrawMechanicsError(
            f"_extract_hybrid_codes expects a PdfDocument, got {type(pdf)!r}"
        )

    _, page = next(iter_pages(pdf, _HYBRID_PAGE, _HYBRID_PAGE))

    # ------------------------------------------------------------------
    # Bear — bbox crop (3 codes inline on one text line)
    # ------------------------------------------------------------------
    _BEAR_BBOX: Final[tuple[float, float, float, float]] = (330.0, 415.0, 590.0, 435.0)
    bear_text = extract_text(page, bbox=_BEAR_BBOX)
    bear_raw = _codes_from_cells([bear_text])

    if not bear_raw:
        # Fallback: search for the Bear section anchor by scanning page words
        # and crop a band below it.  This guards against minor layout drift
        # that shifts the y-coordinates of the bear code line.
        bear_words = page.extract_words()
        anchor_bottom: float | None = None
        for word in bear_words:
            if "Bear" in word.get("text", "") and word.get("top", 0) > 380:
                anchor_bottom = float(word["bottom"])
                break
        if anchor_bottom is not None:
            fallback_bbox = (280.0, anchor_bottom, 600.0, anchor_bottom + 25.0)
            fallback_text = extract_text(page, bbox=fallback_bbox)
            bear_raw = _codes_from_cells([fallback_text])

    if not bear_raw:
        raise ColoradoDrawMechanicsError(
            f"bear: zero hybrid codes found on PDF page {_HYBRID_PAGE} — "
            "layout may have drifted; update _BEAR_BBOX"
        )

    # Dedup bear codes by code string, first-seen low_availability wins
    # (consistent with the deer/elk/pronghorn seen-set dedup path below).
    bear_seen: set[str] = set()
    bear_deduped: list[tuple[str, bool]] = []
    for code, low in bear_raw:
        if code not in bear_seen:
            bear_seen.add(code)
            bear_deduped.append((code, low))

    # Fail-loud: the bear docstring states "3 codes on one line".
    # A partial extraction (1 or 2 codes) would pass the per-species non-zero
    # guard and the total count-band, silently writing a wrong artifact.
    if len(bear_deduped) != 3:
        raise ColoradoDrawMechanicsError(
            f"bear: expected exactly 3 distinct hybrid codes on PDF page "
            f"{_HYBRID_PAGE}, found {len(bear_deduped)} — "
            "layout may have drifted; update _BEAR_BBOX"
        )

    # ------------------------------------------------------------------
    # Deer / Elk / Pronghorn — extract_tables approach
    # ------------------------------------------------------------------
    tables = extract_tables(page)

    # Assign tables to species by walking the table list in order and watching
    # for header cells that match a species heading pattern.
    # Layout (confirmed 2026-06-24):
    #   Table 0: page header (Youth Hunts / Hybrid Draw nav)
    #   Table 1: map image (not code-bearing)
    #   Table 2: Bear header + bear codes row (only 1 of 3 codes)
    #   Tables 3-5: Deer (Table 3 has "Deer — Hybrid Draw Hunt Codes" header)
    #   Tables 6-8: Elk  (Table 6 has "Elk — Hybrid Draw Hunt Codes" header)
    #   Table 9: Pronghorn (Table 9 has "Pronghorn — Hybrid Draw Hunt Codes" header)
    #
    # Strategy: iterate tables; when a species heading is spotted in any cell,
    # record the index.  All subsequent header-less tables belong to that species
    # until the next species heading.

    _SPECIES_HEADING_RE = re.compile(
        r"(Deer|Elk|Pronghorn)\s*[——–\-]\s*Hybrid Draw Hunt Codes",
        re.IGNORECASE,
    )

    # Map species name → list of table indices
    species_table_map: dict[str, list[int]] = {"deer": [], "elk": [], "pronghorn": []}
    current_species: str | None = None

    for idx, table in enumerate(tables):
        # Flatten all cells to look for a species heading
        all_cells = _flatten_table(table)
        heading_match: str | None = None
        for cell in all_cells:
            if cell:
                m = _SPECIES_HEADING_RE.search(str(cell))
                if m:
                    heading_match = m.group(1).lower()
                    break

        if heading_match is not None:
            current_species = heading_match
        # Attribute this table to the current species (even the heading table
        # itself, which often has a code column next to the heading cell)
        if current_species in species_table_map:
            species_table_map[current_species].append(idx)

    # Collect codes per table-species
    table_species_codes: dict[str, list[tuple[str, bool]]] = {
        s: [] for s in ("deer", "elk", "pronghorn")
    }
    for species, idx_list in species_table_map.items():
        seen: set[str] = set()
        for idx in idx_list:
            all_cells = _flatten_table(tables[idx])
            for code, low in _codes_from_cells(all_cells):
                if code not in seen:
                    seen.add(code)
                    table_species_codes[species].append((code, low))

    # ------------------------------------------------------------------
    # Fail-loud: each species must yield at least one code
    # ------------------------------------------------------------------
    all_species_codes: dict[str, list[tuple[str, bool]]] = {
        "bear": bear_deduped,
        **{s: sorted(set(v)) for s, v in table_species_codes.items()},
    }

    for species, codes in all_species_codes.items():
        if not codes:
            raise ColoradoDrawMechanicsError(
                f"{species}: zero hybrid codes found on PDF page {_HYBRID_PAGE} — "
                "check table-assignment logic or PDF layout"
            )

    # ------------------------------------------------------------------
    # Sanity band across all species
    # ------------------------------------------------------------------
    total = sum(len(v) for v in all_species_codes.values())
    lo, hi = _HYBRID_COUNT_BAND
    if not (lo <= total <= hi):
        raise ColoradoDrawMechanicsError(
            f"hybrid code total {total} outside band {_HYBRID_COUNT_BAND} — "
            "PDF layout may have changed or extraction logic has a bug"
        )

    # ------------------------------------------------------------------
    # Build records, validate each code, log summary
    # ------------------------------------------------------------------
    records: list[dict[str, object]] = []
    species_counts: dict[str, int] = {}

    for species in ("bear", "deer", "elk", "pronghorn"):
        codes = all_species_codes[species]
        species_counts[species] = len(codes)
        for hunt_code, low_avail in codes:
            if not _HUNT_CODE_RE.match(hunt_code):
                raise ColoradoDrawMechanicsError(
                    f"{species}: extracted string {hunt_code!r} does not match "
                    f"_HUNT_CODE_RE — pattern or input data is inconsistent"
                )
            records.append(
                {
                    "record_type": "hybrid_code",
                    "species": species,
                    "hunt_code": hunt_code,
                    "low_availability": low_avail,
                }
            )

    _logger.info(
        "hybrid codes extracted: bear=%d deer=%d elk=%d pronghorn=%d total=%d",
        species_counts["bear"],
        species_counts["deer"],
        species_counts["elk"],
        species_counts["pronghorn"],
        total,
    )

    # Sort by (species, hunt_code) for determinism; bear < deer < elk < pronghorn
    records.sort(key=lambda r: (str(r["species"]), str(r["hunt_code"])))
    return records


# ---------------------------------------------------------------------------
# T3: Point-only hunt-code extraction (preference-points-only codes)
# ---------------------------------------------------------------------------


def _extract_point_only_codes(pdf: PdfDocument) -> list[dict[str, object]]:
    """Extract the preference-point-only hunt code for each V1 species.

    Each species chapter opens with a prose sentence of the form:
    "To apply for a point, enter D-P-999-99-P as your first-choice hunt code."
    This function locates that sentence on the species' first PDF page and
    captures the code verbatim.

    Pages (1-based, from ``_POINT_ONLY_PAGES``):
      - deer     → PDF page 30  → D-P-999-99-P
      - elk      → PDF page 45  → E-P-999-99-P
      - pronghorn → PDF page 63 → A-P-999-99-P
      - bear     → PDF page 72  → B-P-999-99-P

    Moose (PDF page 68, ``M-P-999-99-P``) is deliberately excluded — out of
    PRD 002 V1 scope.

    Returns one ``point_only_code`` record per species where the code is found,
    sorted by species name.  Each record shape::

        {
            "record_type": "point_only_code",
            "species":    str,   # "bear" | "deer" | "elk" | "pronghorn"
            "hunt_code":  str,   # e.g. "D-P-999-99-P"
        }

    Source / extracted_at stamping is deferred to T5 (global stamp).

    Raises:
        ColoradoDrawMechanicsError: if the extracted species-letter does not
            match ``_SPECIES_LETTER[species]`` — wrong data is fail-loud.

    Warns (log WARNING) but does not raise if no code is found on a page;
    the record for that species is omitted (``purchase_only_code: str | None``
    permits null, but absence from a live brochure page is unexpected).
    """
    if not isinstance(pdf, PdfDocument):
        raise ColoradoDrawMechanicsError(
            f"_extract_point_only_codes expects a PdfDocument, got {type(pdf)!r}"
        )

    # Unanchored pattern — the point-only codes follow the pattern
    # {species_letter}-P-999-99-P embedded inside a prose sentence.
    _POINT_ONLY_CODE_RE = re.compile(r"([A-Z])-P-999-99-P")

    records: list[dict[str, object]] = []

    for species in sorted(_POINT_ONLY_PAGES):
        page_1based = _POINT_ONLY_PAGES[species]
        expected_letter = _SPECIES_LETTER[species]

        _, page = next(iter_pages(pdf, page_1based, page_1based))
        text = extract_text(page)

        m = _POINT_ONLY_CODE_RE.search(text)
        if m is None:
            _logger.warning(
                "point_only_code: no code found for species=%s on PDF page %d — "
                "brochure layout may have changed",
                species,
                page_1based,
            )
            continue

        found_letter = m.group(1)
        if found_letter != expected_letter:
            raise ColoradoDrawMechanicsError(
                f"point_only_code: species={species!r} page={page_1based} — "
                f"expected species letter {expected_letter!r} but found "
                f"{found_letter!r} in code {m.group(0)!r}; "
                "wrong code may be on this page or _SPECIES_LETTER is stale"
            )

        records.append(
            {
                "record_type": "point_only_code",
                "species": species,
                "hunt_code": m.group(0),
            }
        )

    if not records:
        raise ColoradoDrawMechanicsError(
            "point_only_codes: no codes found on ANY species page — "
            "anchor phrase likely drifted"
        )

    _logger.info(
        "point_only_codes extracted: %d record(s) — %s",
        len(records),
        ", ".join(f"{r['species']}={r['hunt_code']}" for r in records),
    )

    # Already sorted by species via ``sorted(_POINT_ONLY_PAGES)`` iteration order;
    # sort explicitly for clarity and defence against dict-order assumptions.
    records.sort(key=lambda r: str(r["species"]))
    return records


# ---------------------------------------------------------------------------
# Month-name → integer mapping (used by _extract_important_dates)
# Includes full names and the three-letter abbreviations with optional trailing
# dot (e.g. "Aug.") that CPW uses in the Important Dates table.
# ---------------------------------------------------------------------------

_MONTH_TO_NUM: Final[dict[str, int]] = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _month_day_to_iso(month_str: str, day_str: str, year: int = _LICENSE_YEAR) -> str:
    """Convert a CPW month/day string pair to an ISO 8601 date string.

    Strips trailing dots from month abbreviations (e.g. ``"Aug."`` → ``"Aug"``).
    Raises ``ColoradoDrawMechanicsError`` on unknown month names.
    """
    month_clean = month_str.rstrip(".")
    month_num = _MONTH_TO_NUM.get(month_clean)
    if month_num is None:
        raise ColoradoDrawMechanicsError(
            f"_month_day_to_iso: unrecognised month {month_str!r} — "
            "_MONTH_TO_NUM may need updating"
        )
    day_int = int(day_str)
    try:
        datetime.date(year, month_num, day_int)
    except ValueError as exc:
        raise ColoradoDrawMechanicsError(
            f"_month_day_to_iso: {month_str!r} {day_str!r} {year} is not a valid "
            f"calendar date — {exc}"
        ) from exc
    return f"{year}-{month_num:02d}-{day_int:02d}"


# ---------------------------------------------------------------------------
# T4a: Important-dates extraction (PDF page 14 / brochure content p. 4)
# ---------------------------------------------------------------------------


def _extract_important_dates(pdf: PdfDocument) -> dict[str, object]:
    """Extract primary/secondary draw deadlines and leftover on-sale date.

    Source: the "Important Dates" table on PDF page 14 (brochure content p. 4),
    extracted via ``extract_tables`` (Table 1 on that page).

    Returns a single record dict::

        {
            "record_type": "important_dates",
            "primary_draw_deadline":   "2026-04-07",
            "secondary_draw_deadline": "2026-06-30",
            "leftover_on_sale_date":   "2026-08-04",
        }

    Extraction method: ``extract_tables(page)`` is used rather than
    ``extract_text`` because the Important Dates column on page 14 is a
    right-side table with a single merged cell per section; the table
    boundary keeps it isolated from the left-column prose (Rule R3).
    Date values are parsed from bullet lines using anchored regexes.
    Both the month name and day integer are captured and converted to ISO
    format via ``_month_day_to_iso`` — no hard-coded dates (ADR-001).

    Cross-check: after parsing, each computed ISO date is compared against
    the expected value from the 2026 brochure; mismatches raise so that
    year-over-year drift is caught immediately (fail-loud per ADR-001).

    Raises:
        ColoradoDrawMechanicsError: if any anchor phrase is absent from the
            table text, if the month is unrecognised, or if a parsed date
            disagrees with the 2026 cross-check expectation.
    """
    if not isinstance(pdf, PdfDocument):
        raise ColoradoDrawMechanicsError(
            f"_extract_important_dates expects a PdfDocument, got {type(pdf)!r}"
        )

    _, page = next(iter_pages(pdf, _DATES_PAGE, _DATES_PAGE))
    tables = extract_tables(page)

    # Page 14 has exactly 2 tables; Table 1 (index 1) is the Important Dates
    # right-side table.  Extract and concatenate all cell strings from it.
    if len(tables) < 2:
        raise ColoradoDrawMechanicsError(
            f"_extract_important_dates: expected at least 2 tables on PDF page "
            f"{_DATES_PAGE}, found {len(tables)} — layout may have changed"
        )
    dates_table = tables[1]
    # Flatten all cells into a single text blob (newlines preserved for regex)
    cells: list[str | None] = list(dates_table["headers"])
    for row in dates_table["rows"]:
        cells.extend(row)
    dates_text = "\n".join(c for c in cells if c)

    # -- Primary draw deadline -----------------------------------------------
    # Bullet: "■ Application & correction deadline ....April 7 (8 p.m. MT)"
    # We anchor on the "Primary Draw" section header and then find the bullet.
    _PRIMARY_RE = re.compile(
        r"Application\s*&\s*correction\s+deadline[^A-Za-z]+([A-Za-z]+\.?)\s+(\d+)",
        re.IGNORECASE,
    )
    primary_matches = list(_PRIMARY_RE.finditer(dates_text))
    if not primary_matches:
        raise ColoradoDrawMechanicsError(
            f"_extract_important_dates: 'Application & correction deadline' not "
            f"found on PDF page {_DATES_PAGE} — anchor phrase may have drifted"
        )
    # First match → Primary draw; second match (if present) → Secondary draw
    prim_m = primary_matches[0]
    primary_iso = _month_day_to_iso(prim_m.group(1), prim_m.group(2))

    # -- Secondary draw deadline ---------------------------------------------
    if len(primary_matches) < 2:
        raise ColoradoDrawMechanicsError(
            f"_extract_important_dates: only one 'Application & correction "
            f"deadline' found on PDF page {_DATES_PAGE}; expected two (primary "
            f"and secondary) — layout may have changed"
        )
    sec_m = primary_matches[1]
    secondary_iso = _month_day_to_iso(sec_m.group(1), sec_m.group(2))

    # -- Leftover / reissued on-sale date ------------------------------------
    # Bullet: "■ Leftover/reissued licenses go on sale ....Aug. 4 (9 a.m. MT)"
    _LEFTOVER_RE = re.compile(
        r"Leftover/reissued\s+licenses\s+go\s+on\s+sale[^A-Za-z]+([A-Za-z]+\.?)\s+(\d+)",
        re.IGNORECASE,
    )
    leftover_m = _LEFTOVER_RE.search(dates_text)
    if leftover_m is None:
        raise ColoradoDrawMechanicsError(
            f"_extract_important_dates: 'Leftover/reissued licenses go on sale' "
            f"not found on PDF page {_DATES_PAGE} — anchor phrase may have drifted"
        )
    leftover_iso = _month_day_to_iso(leftover_m.group(1), leftover_m.group(2))

    # -- Cross-check against known 2026 values (fail-loud drift guard) -------
    _EXPECTED = {
        "primary_draw_deadline":   "2026-04-07",
        "secondary_draw_deadline": "2026-06-30",
        "leftover_on_sale_date":   "2026-08-04",
    }
    parsed = {
        "primary_draw_deadline":   primary_iso,
        "secondary_draw_deadline": secondary_iso,
        "leftover_on_sale_date":   leftover_iso,
    }
    mismatches = {k: (parsed[k], _EXPECTED[k]) for k in _EXPECTED if parsed[k] != _EXPECTED[k]}
    if mismatches:
        raise ColoradoDrawMechanicsError(
            f"_extract_important_dates: parsed dates disagree with 2026 "
            f"cross-check expectations — possible brochure drift: {mismatches!r}"
        )

    _logger.info(
        "important_dates extracted: primary=%s secondary=%s leftover=%s",
        primary_iso,
        secondary_iso,
        leftover_iso,
    )

    return {
        "record_type": "important_dates",
        "primary_draw_deadline":   primary_iso,
        "secondary_draw_deadline": secondary_iso,
        "leftover_on_sale_date":   leftover_iso,
    }


# ---------------------------------------------------------------------------
# T4b: Nonresident allocation extraction (PDF page 14 right-column sidebar)
# ---------------------------------------------------------------------------


def _extract_nr_allocation(pdf: PdfDocument) -> dict[str, object]:
    """Extract the nonresident license allocation caps from the page-14 sidebar.

    Source: the "Nonresident License Allocations" sidebar on PDF page 14,
    right column, bbox ``(363.0, 435.0, 590.0, 763.0)`` (Rule R3 column crop).

    Returns a single record dict::

        {
            "record_type":                 "nr_allocation",
            "high_demand_threshold_points": 6,
            "high_demand_nr_cap":           0.20,
            "standard_nr_cap":              0.25,
            "verbatim":                     <whitespace-collapsed prose (Rule R2)>,
        }

    The two caps are derived from the CPW rule text:
      - Hunt codes that required **six or more** preference points → up to
        **20 percent** of licenses may go to nonresidents.
      - Hunt codes that required **fewer than six** preference points → up to
        **25 percent** may go to nonresidents.

    These structured values are hard-checked against the verbatim text (items
    "six or more", "fewer than six", "20", "25" must all appear) rather than
    parsed by regex, because the plain-English phrasing is authoritative and
    the numeric values are a deliberate, stable policy.

    Raises:
        ColoradoDrawMechanicsError: if the required anchor phrases are absent
            from the cropped text, signalling bbox drift or PDF layout change.
    """
    if not isinstance(pdf, PdfDocument):
        raise ColoradoDrawMechanicsError(
            f"_extract_nr_allocation expects a PdfDocument, got {type(pdf)!r}"
        )

    _, page = next(iter_pages(pdf, _DATES_PAGE, _DATES_PAGE))

    # Rule R3 — right-column crop for the NR allocations sidebar.
    _NR_BBOX: Final[tuple[float, float, float, float]] = (363.0, 435.0, 590.0, 763.0)
    raw_text = extract_text(page, bbox=_NR_BBOX)

    if not raw_text.strip():
        raise ColoradoDrawMechanicsError(
            f"_extract_nr_allocation: bbox {_NR_BBOX} returned empty text on PDF "
            f"page {_DATES_PAGE} — bbox may need adjustment after a PDF layout change"
        )

    # Fail-loud anchor assertions (ADR-001)
    for phrase in ("six or more", "fewer than six", "20", "25"):
        if phrase not in raw_text:
            raise ColoradoDrawMechanicsError(
                f"_extract_nr_allocation: expected phrase {phrase!r} not found in "
                f"NR allocations sidebar on PDF page {_DATES_PAGE} — "
                "PDF may have changed; update extraction logic"
            )

    # Rule R2 — collapse internal whitespace for the verbatim prose field.
    verbatim = re.sub(r"\s+", " ", raw_text).strip()

    _logger.info(
        "nr_allocation extracted: high_demand_threshold=6pts cap=20%% standard_cap=25%%"
    )

    return {
        "record_type":                  "nr_allocation",
        "high_demand_threshold_points": 6,
        "high_demand_nr_cap":           0.20,
        "standard_nr_cap":              0.25,
        "verbatim":                     verbatim,
    }


# ---------------------------------------------------------------------------
# T4c: Hybrid-mechanics prose extraction (PDF page 29 left column)
# ---------------------------------------------------------------------------


def _extract_hybrid_mechanics(pdf: PdfDocument) -> dict[str, object]:
    """Extract the hybrid-draw mechanics description from page 29's left column.

    Source: the "How It Works" + surrounding prose in the left column of PDF
    page 29, bbox ``(0.0, 387.0, 340.0, 760.0)`` (Rule R3 column crop).
    Page 29 is a two-column layout; the right column holds the hunt-code
    tables extracted by ``_extract_hybrid_codes``.

    Returns a single record dict::

        {
            "record_type":          "hybrid_mechanics",
            "min_preference_points": 5,
            "random_pool_share":     0.20,
            "verbatim":              <whitespace-collapsed prose (Rule R2)>,
        }

    The two structured values are derived from:
      - "minimum of **five preference points**" → ``min_preference_points=5``
      - "up to **20 percent** of the available licenses may be issued through
        a random drawing" → ``random_pool_share=0.20``

    Both assertions are anchored against the verbatim crop text (fail-loud if
    absent).

    Raises:
        ColoradoDrawMechanicsError: if either "five preference points" or
            "20 percent" is absent from the cropped text, signalling bbox
            drift or a PDF layout change.
    """
    if not isinstance(pdf, PdfDocument):
        raise ColoradoDrawMechanicsError(
            f"_extract_hybrid_mechanics expects a PdfDocument, got {type(pdf)!r}"
        )

    _, page = next(iter_pages(pdf, _HYBRID_PAGE, _HYBRID_PAGE))

    # Rule R3 — left-column crop for the hybrid-mechanics prose.
    _HYBRID_MECH_BBOX: Final[tuple[float, float, float, float]] = (0.0, 387.0, 340.0, 760.0)
    raw_text = extract_text(page, bbox=_HYBRID_MECH_BBOX)

    if not raw_text.strip():
        raise ColoradoDrawMechanicsError(
            f"_extract_hybrid_mechanics: bbox {_HYBRID_MECH_BBOX} returned empty "
            f"text on PDF page {_HYBRID_PAGE} — bbox may need adjustment after a "
            "PDF layout change"
        )

    # Fail-loud anchor assertions (ADR-001)
    for phrase in ("five preference points", "20 percent"):
        if phrase not in raw_text:
            raise ColoradoDrawMechanicsError(
                f"_extract_hybrid_mechanics: expected phrase {phrase!r} not found "
                f"in left-column crop on PDF page {_HYBRID_PAGE} — "
                "PDF may have changed; update extraction logic"
            )

    # Rule R2 — collapse internal whitespace for the verbatim prose field.
    verbatim = re.sub(r"\s+", " ", raw_text).strip()

    _logger.info(
        "hybrid_mechanics extracted: min_preference_points=5 random_pool_share=0.20"
    )

    return {
        "record_type":           "hybrid_mechanics",
        "min_preference_points": 5,
        "random_pool_share":     0.20,
        "verbatim":              verbatim,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract(pdf_path: Path = _PDF_PATH) -> list[dict[str, object]]:
    """Extract draw-mechanics records from *pdf_path*.

    Opens the PDF once, calls all five sub-extractors, stamps every record with
    ``source_id`` and ``extracted_at``, sorts the concatenated list
    deterministically, and returns it.

    Sort key: ``(record_type, species, hunt_code)`` — all three fields cast to
    ``str`` so records without those keys (singletons) sort stably at the top of
    their ``record_type`` bucket.

    Raises:
        ColoradoDrawMechanicsError: propagated from any sub-extractor on a
            fatal extraction inconsistency.
        PdfExtractionError: if the PDF or its manifest cannot be opened.
    """
    extracted_at = _load_extracted_at_from_manifest(pdf_path)

    with open_pdf(pdf_path) as pdf:
        hybrid_records = _extract_hybrid_codes(pdf)
        point_only_records = _extract_point_only_codes(pdf)
        dates_record = _extract_important_dates(pdf)
        nr_alloc_record = _extract_nr_allocation(pdf)
        hybrid_mech_record = _extract_hybrid_mechanics(pdf)

    records: list[dict[str, object]] = (
        hybrid_records
        + point_only_records
        + [dates_record, nr_alloc_record, hybrid_mech_record]
    )

    # Stamp every record with provenance fields (ADR-014 / S06.3 convention).
    for rec in records:
        rec["source_id"] = _SOURCE_ID
        rec["extracted_at"] = extracted_at

    # Deterministic sort — required for byte-stable output because
    # write_extraction_artifact sorts keys WITHIN each record but does NOT sort
    # the records themselves.
    records.sort(
        key=lambda r: (
            str(r.get("record_type", "")),
            str(r.get("species", "")),
            str(r.get("hunt_code", "")),
        )
    )

    return records


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the CPW draw-mechanics extractor.

    Usage:
        ingestion/.venv/bin/python ingestion/states/colorado/extract_draw_mechanics.py
        ingestion/.venv/bin/python ingestion/states/colorado/extract_draw_mechanics.py \\
            --pdf /path/to/brochure.pdf --out /tmp/draw-mechanics-2026.json
    """
    parser = argparse.ArgumentParser(
        description="Extract draw-mechanics front-matter from the CPW Big Game brochure",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=_PDF_PATH,
        help="Path to CPW Big Game PDF (default: fetched fixture)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_OUTPUT_PATH,
        help=(
            "Output JSON path "
            "(default: ingestion/states/colorado/extracted/draw-mechanics-2026.json)"
        ),
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
        _logger.error(
            "CPW Big Game PDF not found at %s — run fetch_pdfs.py first", args.pdf
        )
        return 1

    try:
        records = extract(args.pdf)
    except PdfExtractionError as e:
        _logger.error("extraction failed: %s", e)
        return 2

    write_extraction_artifact(records, args.out)

    # Per-record_type summary log.
    type_counts: dict[str, int] = {}
    for rec in records:
        rt = str(rec.get("record_type", "unknown"))
        type_counts[rt] = type_counts.get(rt, 0) + 1
    _logger.info(
        "extracted %d records total: %s",
        len(records),
        " ".join(f"{k}={v}" for k, v in sorted(type_counts.items())),
    )
    _logger.info("wrote %d records to %s", len(records), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
