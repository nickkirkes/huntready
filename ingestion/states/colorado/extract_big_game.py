"""
Extract per-GMU regulation rows from the CPW Big Game brochure
(deer / elk / pronghorn) into a deterministic JSON artifact for downstream
ingestion (S06.6–S06.9).

The extractor walks the deer page range (PDF pp. 30–44), the elk page range
(PDF pp. 45–62), and the pronghorn page range (PDF pp. 63–67), locates each
hunt-code table by pdfplumber ``find_tables()``, and emits one
``CpwSectionExtraction`` per (GMU × method × residency) block.  All output is
written to a deterministic JSON artifact at
``ingestion/states/colorado/extracted/big-game-2026.json``.

ADR references:
  ADR-001  Authority preserved, not replaced — fail loud; no invented values.
  ADR-005  Python ingestion / TypeScript serving language split.
  ADR-008  Verbatim regulation text — ``verbatim_text`` retains pdfplumber's
           word-grouped output without additional normalization.  Only the
           structured ``rows`` payload uses the cleanup regexes below.
  ADR-017  Confidence calibration + parent-inheritance rule — per-row
           ``extraction_confidence`` is assigned here; GMU-level MIN
           aggregation is S06.6's job.

# probed 2026-06-09

Structural notes from live probe of
``co-cpw-big-game-2026-brochure-2026-03-04.pdf`` (84 pages):

  Character-doubling artifact (GMU-20-area pages):
    pdfplumber double-renders certain pages in the GMU-20-area deer/elk
    tables — every glyph (letter, digit, punctuation, space) is emitted
    exactly twice.  For example, the valid hunt code ``"D-M-020-O2-R"``
    arrives as ``"DD--MM--002200--OO22--RR"``, and a Dates cell
    ``"Oct. 24–Nov. 1"`` arrives as ``"OOcctt.. 2244––NNoovv.. 11"``.
    This produces ~44 LOW-confidence rows when unrecovered.
    Rule R14 (``_undouble_text`` + ``_looks_doubled_row``) detects and
    recovers these rows before column mapping so the hunt code parser sees
    the true text and assigns HIGH/MEDIUM confidence.

  Page ranges (1-based PDF page numbers, confirmed 2026-06-09):
    Deer:      PDF pages 30–44  (brochure content pages 20–34; offset = 10)
    Elk:       PDF pages 45–62  (brochure content pages 35–52)
    Pronghorn: PDF pages 63–67  (brochure content pages 53–57)
    (Moose starts at PDF page 68; out of V1 scope)

  Column-count observation:
    The CPW hunt-code tables use a dual-column-block layout.  pdfplumber
    ``find_tables()`` typically detects this as ONE table with 12 columns —
    two side-by-side 6-column blocks with headers
    ``Unit | Valid GMUs | Dates | Sex | Hunt Code | List`` repeated twice.
    In some cases pdfplumber also returns a second 6-column table for one
    half of the dual-block (observed on pronghorn muzzleloader, PDF page 66).
    Callers must handle both the 12-column and 6-column cases; the 6-column
    case arises when pdfplumber resolves the block boundaries differently.

    The season-choice tables (a subset of deer/elk pages) use a different
    column layout: ``Unit | Archery Dates | Muzzleloader Dates | Rifle Dates
    | Sex | Hunt Code | List`` (8 columns total with a leading None cell).

    Ranching for Wildlife tables use: ``Ranch/Units | Dates | Sex | Hunt
    Codes | List`` (10-column dual-block or 5-column single-block).

  No quota or apply_by columns found:
    A full scan of all table headers across PDF pages 30–67 (deer + elk +
    pronghorn) found NO ``Quota``, ``Apply By``, or ``Apply By Date`` column
    headers in any hunt-code table.  CPW encodes draw mechanics in the ``List``
    column (``A`` / ``B`` / ``C``) and in the ``Res`` / ``NR`` list values in
    the hunt code itself; per-row quota figures are not published in the
    brochure tables.  Consequently ``apply_by``, ``quota``, and
    ``quota_range`` are universally ``None`` for all V1 CPW rows.

Cleanup rules (applied only to structured ``rows`` cells, never to
``verbatim_text``):

  Rule R1: bare ``-`` → None
      regex: ``^\\s*-\\s*$``
      scope: all value cells (``apply_by``, ``quota_range``, ``extras``,
             and any nullable string field)
      rationale: CPW tables use a literal hyphen as the absence sentinel,
                 matching the FWP DEA convention — absent data must be explicit
                 null per ADR-001.
      locked by: TestNormalizeCell::test_dash_sentinel_nulled

  Rule R2: None / empty / whitespace-only → None
      regex: n/a (``not text or not text.strip()``)
      scope: all cells
      rationale: pdfplumber returns ``None`` for merged-cell continuations;
                 empty strings are ambiguous (ADR-001: absent data is null).
      locked by: TestNormalizeCell::test_whitespace_nulled

  Rule R3: hyphenated line-break rejoin (``"word-\\nword"`` → ``"word-word"``)
      regex: ``(?<=[a-zA-Z0-9])-\\n(?=[a-zA-Z0-9])``
      scope: all cells (applied before whitespace collapse)
      rationale: pdfplumber introduces soft-hyphen line breaks in multi-line
                 cells (e.g. date ranges like ``Oct. 1–23\\nNov. 4–30`` are
                 NOT affected because neither neighbor is a letter; only
                 genuine hyphenated words are rejoined).
      locked by: TestNormalizeCell::test_hyphen_rejoin

  Rule R4: extras/notes whitespace collapse
      regex: ``re.sub(r"\\s+", " ", text).strip()``
      scope: notes/extras cells ONLY (applied after R1–R3)
      rationale: multi-line footnote text in CPW tables embeds ``\\n`` between
                 sentences; the natural reading is a single space-separated
                 paragraph.  Applied only to extras — NOT globally — because
                 preservation of single newlines is required elsewhere for cell
                 parsing.
      locked by: TestRejoinAndCollapse::test_collapse_whitespace_multi_space,
                 TestRejoinAndCollapse::test_collapse_whitespace_newlines

  Rule R5: ``See Unit N`` cross-reference rows skipped
      regex: ``(?i)^\\s*see\\s+unit\\s+\\d+``
      scope: ``Valid GMUs`` cell (first data cell after ``Unit``)
      rationale: many CPW rows carry ``see unit NNN`` instead of data, meaning
                 the unit shares regulations with another — these are not
                 regulation rows and must be skipped.
      locked by: TestRowFilters::test_see_unit_skipped

  Rule R6: ``■`` footnote rows skipped
      regex: ``^\\s*■``  (startswith ``■`` after strip)
      scope: first cell of row (``Unit`` cell)
      rationale: footnote rows (e.g. ``■Units 12, 13 are valid for add-on
                 bear licenses``) use a leading ``■`` bullet and are not
                 regulation rows.
      locked by: TestRowFilters::test_footnote_skipped

  Rule R7: season date from section header attached to all rows in the method
           block (elk archery)
      regex: n/a (parsed from the section-header cell, e.g.
             ``Season Dates: Sept. 2–30 (Unless otherwise noted)``)
      scope: ``season_windows`` for all rows on a page whose season date is
             uniform across all rows (archery / muzzleloader pages)
      rationale: CPW states the overall season date in a page header rather
                 than repeating it per row; the extractor attaches it to every
                 row in the block.
      locked by: TestSeasonWindow::test_header_date

  Rule R8: hunt-code component parse
      regex: ``^([A-Z])-([A-Z])-([0-9]{3,4})-([A-Z0-9]+)-([A-Z])$``
      scope: ``Hunt Code`` cell
      rationale: CPW hunt codes encode species letter, sex code, GMU code,
                 season/option code, and method letter in a fixed format
                 (e.g. ``D-M-001-O1-A``).  Parsing them is the primary source
                 of ``species_letter``, ``sex_code``, ``gmu_code``,
                 ``season_code``, and ``method_letter``.
      locked by: TestParseHuntCode::test_valid_code

  Rule R9: ``OTC`` in List columns preserved (NOT nulled)
      regex: n/a
      scope: ``List`` cell
      rationale: ``OTC`` is a valid list type (over the counter), not an
                 absence sentinel.  R1's ``-`` sentinel rule must not apply to
                 cells whose only content is a list-type token.
      locked by: TestNormalizeCell::test_otc_preserved

  Rule R10: map-page skip (zero tables + short / garbled text)
      regex: n/a (structural: ``len(page.find_tables()) == 0`` and
             ``len(extract_text(page).strip()) < 200``)
      scope: pages in the deer/elk/pronghorn range
      rationale: map pages (e.g. CWD prevalence maps, OTC maps) contain no
                 regulation tables and produce garbled rotated text.  They
                 must be skipped to avoid empty-section artifacts.
      locked by: TestRowFilters::test_map_page_skipped

  Rule R11: whitetail boundary heading switches species_group
             mule_deer → whitetail
      regex: ``(?i)white[- ]?tailed\\s+deer\\s+only``
      scope: page-level section heading (``Limited Licenses —
             White-Tailed Deer Only``, PDF page 44)
      rationale: deer pages include a whitetail-only sub-section (PDF page 44,
                 brochure content page 34) that must be tagged
                 ``species_group='whitetail'`` rather than ``'mule_deer'``.
      locked by: TestParseHuntCode::test_species_group_whitetail

  Rule R12: resident / nonresident page attribution sets residency_scope
      regex: n/a (structural: section heading contains ``Resident`` or
             ``Nonresident``, or page-level text matches)
      scope: page-level (e.g. elk OTC archery resident page vs. nonresident
             page)
      rationale: some CPW pages are explicitly resident-only or
                 nonresident-only; the extractor must tag
                 ``residency_scope='resident'``, ``'nonresident'``, or
                 ``'either'`` accordingly.
      locked by: TestSectionAttribution::test_residency_scope

  Rule R13: leading/trailing whitespace strip on all cells
      regex: n/a (``text.strip()``)
      scope: all cells (applied first, before all other rules)
      rationale: pdfplumber introduces edge whitespace at column boundaries;
                 stripping prevents false non-match on downstream regexes.
      locked by: TestNormalizeCell::test_strip

  Rule R14: uniform character-doubling recovery
      regex: n/a (positional s[::2]==s[1::2] test)
      scope: whole row when a long cell is uniformly doubled (pdfplumber
             double-renders certain GMU-20-area pages — every glyph emitted
             twice, including spaces, punctuation, and digits; e.g. the hunt
             code ``"D-M-020-O2-R"`` arrives as ``"DD--MM--002200--OO22--RR"``)
      rationale: recovers the true source text (ADR-008 faithful; mirrors MT
                 ``_reverse_cell_text`` rotated-table recovery) so real
                 regulation rows are not lost as garbled LOW-confidence rows.
      locked by: TestUndouble::test_undouble_hunt_code,
                 TestUndouble::test_not_doubled_unchanged,
                 TestUndouble::test_short_even_paired_left_alone

  Rule R15: strip the CPW ``■`` OTC-marker glyph from structured cells
      regex: ``\\s*■\\s*``
      scope: all structured cells via _normalize_cell (NOT season-window
             raw_text)
      rationale: ``■`` (U+25A0) is a presentation marker meaning "OTC add-on
                 available"; it is not part of a unit/GMU value.  It polluted
                 136 unit/valid_gmus fields (e.g. ``valid_gmus='■1'``,
                 ``unit='3\\n■'``).  Season-window ``raw_text`` passes through
                 ``_parse_season_window``, not ``_normalize_cell``, so ADR-008
                 verbatim discipline for date text is preserved.
      locked by: TestNormalizeCell::test_strips_otc_bullet
"""

# State-specific module — must NOT import from ingestion.states.<other_state>.
# Cross-state imports violate ADR-005 isolation (each state adapter is fully
# self-contained).  The state-agnostic guard test enforces this via AST walk.

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import TypedDict

from ingestion.lib.pdf import (
    ConfidenceTier,
    PageReference,
    PdfExtractionError,
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

_PDF_FILENAME = "co-cpw-big-game-2026-brochure-2026-03-04.pdf"

_PDF_PATH = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "colorado"
    / "fixtures"
    / _PDF_FILENAME
)

_OUTPUT_PATH = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "colorado"
    / "extracted"
    / "big-game-2026.json"
)

# ---------------------------------------------------------------------------
# Metadata constants
# ---------------------------------------------------------------------------

_SOURCE_ID = "co-cpw-big-game-2026-brochure"
_LICENSE_YEAR = 2026

# ---------------------------------------------------------------------------
# Page-range constants (1-based inclusive, per iter_pages convention)
# Confirmed via live probe of the PDF on 2026-06-09.
# Brochure "content page" numbering starts at content page 1 = PDF page 11
# (after cover + corrections pp. 2–3 + photo spreads pp. 4–9 + ToC p. 10).
# Offset = PDF page number − content page number = 10.
#
# Source: Table of Contents (PDF page 10):
#   Deer      content pp. 20–34  →  PDF pages 30–44
#   Elk       content pp. 35–52  →  PDF pages 45–62
#   Pronghorn content pp. 53–57  →  PDF pages 63–67
# ---------------------------------------------------------------------------

_DEER_PAGES = (30, 44)
_ELK_PAGES = (45, 62)
_PRONGHORN_PAGES = (63, 67)

# ---------------------------------------------------------------------------
# Cleanup-utility compiled regex constants (used by T2 helpers)
# ---------------------------------------------------------------------------

# Rule R3: rejoin hyphenated line-breaks when both neighbors are alphanumeric.
# Broader than MT's lowercase-only pattern because CPW tables include date
# ranges with digits on both sides of hyphens that should NOT be rejoined
# (e.g. "Oct. 1-23") but also uppercase abbreviations like "Sept.-\nOct."
# that should be rejoined.  Alphanumeric neighbours precisely targets genuine
# soft-hyphen word-splits.
_HYPHEN_LINEBREAK_RE = re.compile(r"(?<=[a-zA-Z0-9])-\n(?=[a-zA-Z0-9])")

# Rule R15: strip CPW OTC-marker glyph (U+25A0, BLACK SQUARE) from structured
# cells.  The glyph is a presentation indicator meaning "OTC add-on available"
# and must not appear in structured unit/valid_gmus values.  Applied inside
# _normalize_cell only (NOT to season-window raw_text per ADR-008).
_OTC_BULLET: str = "■"  # U+25A0 BLACK SQUARE
_OTC_BULLET_RE = re.compile(r"\s*■\s*")  # Rule R15

# FIX 2: compiled fragment regex for _is_garbage_row.
# Matches a hunt-code-shaped substring (e.g. "D-M-082") within any text.
# Rows with species_letter == "" AND no fragment like this are garbage (map-OCR
# leakage); rows with a multi-code cell like "D-M-082-O2-R\nD-M-082-O3-R" DO
# contain this pattern and are NOT garbage.
_HUNT_CODE_FRAGMENT_RE = re.compile(r"[A-Z]-[A-Z]-\d{3}")

# Rule R5: "See Unit NNN" cross-reference rows in the Valid-GMUs cell.
_SEE_UNIT_RE = re.compile(r"(?i)^\s*see\s+unit\s+\d+")

# Rule R8: CPW hunt-code format — {Species}-{Sex}-{GMU}-{Season}-{Method}
# Five capture groups: (species_letter, sex_code, gmu_code, season_code,
# method_letter).  GMU codes are 3–4 digits; season/option codes mix letters
# and digits (e.g. "O1", "OA", "LS").
# Examples confirmed from live PDF 2026-06-09:
#   D-M-001-O1-A  (deer, male, GMU 001, option 1, archery)
#   E-F-044-O1-R  (elk, female, GMU 044, option 1, rifle)
#   A-M-012-O1-M  (pronghorn/antelope, male, GMU 012, option 1, muzzleloader)
# NOTE: CPW uses "A" (Antelope) as the pronghorn species letter — not "P".
_HUNT_CODE_RE = re.compile(r"^([A-Z])-([A-Z])-(\d{3,4})-([A-Z0-9]+)-([A-Z])$")  # Rule R8

# Rule R10: threshold for classifying a page as a map/non-table page.
# When a page has zero tables AND its extracted text (stripped) is shorter than
# this many characters, the page is a map or photo page and must be skipped.
# 120 chars is conservative: a single CPW regulation row produces ≥ 40 chars,
# and even a sparsely-worded section header produces ≥ 30.  Map pages produce
# garbled rotated glyphs totalling < 100 chars or nothing at all.
_MAP_PAGE_MIN_TEXT_CHARS: int = 120

# Rule R14: de-doubling thresholds.
# ``_UNDOUBLE_MIN_LEN`` — minimum length a string must have before the
# uniform-doubling test is applied.  Short even-length strings that happen
# to be pair-equal by chance (e.g. ``"AABB"`` → ``s[::2]=="AB" == s[1::2]``)
# are left alone.  Real doubled cells are long: a doubled CPW hunt code such
# as ``"DD--MM--002200--OO22--RR"`` is 24 chars; a doubled date
# ``"OOcctt.. 2244––NNoovv.. 11"`` is ≥ 26 chars.  Threshold of 6 is
# conservative enough to leave all 2- and 4-char normal tokens untouched.
_UNDOUBLE_MIN_LEN: int = 6
# ``_DOUBLED_ROW_MIN_CELL_LEN`` — minimum stripped length a cell must have
# for it to count as evidence that the whole row is doubled.  10 chars
# ensures a bare ``"2200"`` (4 chars doubled = 8 chars) won't false-trigger
# the row-level gate, while a doubled ``"DD--"`` (4 chars → 8 chars) also
# stays below the gate.  A real doubled hunt-code or date cell is ≥ 20 chars.
_DOUBLED_ROW_MIN_CELL_LEN: int = 10

# ---------------------------------------------------------------------------
# TypedDicts — output JSON contract for S06.6 / S06.7
# (order: CpwSeasonWindow → CpwRowExtraction → CpwSectionExtraction)
# ---------------------------------------------------------------------------


class CpwSeasonWindow(TypedDict):
    """A single season's date window for a CPW hunt-code row.

    ``start_date`` is the begin date exactly as printed in the brochure
    (e.g. ``"Sept. 2"``).  ``end_date`` is the end date — but note that for a
    SAME-MONTH range, where CPW drops the redundant month on the end token
    (``"Sept. 2–30"`` prints a bare ``"30"``), the month is INFERRED from
    ``start_date`` so the field is an unambiguous standalone date
    (``"Sept. 30"``, never a bare ``"30"``); cross-month ends already carry
    their own printed month and are left as-is.  ``raw_text`` carries the full
    unparsed cell text verbatim per ADR-008 (e.g. ``"Sept. 2–30"`` or
    ``"Sept. 2–30 (Unless otherwise noted)"``) and is AUTHORITATIVE for exactly
    what the brochure printed — a consumer that needs to distinguish a printed
    month from an inferred one compares ``end_date`` against ``raw_text``.
    Both ``start_date`` and ``end_date`` may be ``None`` when the range cannot
    be parsed (e.g. a future CPW format change surfaces as a parse failure, NOT
    a silent inference — ``raw_text`` is preserved); ``raw_text`` is always
    populated when the window is present.
    """

    start_date: str | None
    end_date: str | None
    raw_text: str | None


class CpwRowExtraction(TypedDict):
    """One hunt-code row from a per-GMU CPW Big Game regulation table.

    ``hunt_code`` is the raw string from the ``Hunt Code`` column
    (e.g. ``"D-M-001-O1-A"``).  The component fields ``species_letter``,
    ``sex_code``, ``gmu_code``, ``season_code``, and ``method_letter`` are
    derived by parsing the hunt code via Rule R8.  All five are ``""`` when
    the hunt code cannot be parsed; ``hunt_code`` is always the verbatim cell
    text per ADR-008.

    ``unit`` carries the ``Unit`` column verbatim (normalized via R1/R2/R3).
    ``valid_gmus`` carries the ``Valid GMUs`` column verbatim (normalized).
    Both are ``None`` when the cell is absent or a See-Unit cross-reference row
    has been skipped.

    ``season_windows`` carries the date windows for this row; for CPW
    archery/muzzleloader tables the season date comes from the section header
    (Rule R7) and is attached to every row in the block.

    ``list_value`` carries the ``List`` column value: ``"A"``, ``"B"``,
    ``"C"``, ``"OTC"``, or ``None``.  This is the draw-mechanic indicator
    for downstream S06.8; it is the ONLY draw-indicator column in CPW tables
    (no separate resident / nonresident List columns exist).

    NOTE on apply_by / quota / quota_range:
        A full scan of all table headers across PDF pages 30–67 (deer + elk
        + pronghorn) found NO ``Quota``, ``Apply By``, or ``Apply By Date``
        column in any hunt-code table (confirmed 2026-06-09).  CPW encodes
        draw mechanics in the ``List`` column and in the hunt code itself;
        per-row quota figures are not published in the brochure tables.
        Consequently ``apply_by``, ``quota``, and ``quota_range`` are
        universally ``None`` for all V1 CPW rows.  If a future year's
        brochure adds these columns, this TypedDict must be extended and the
        None assumption removed.

    ``weapon_types`` is derived from ``method_letter`` (e.g. ``"A"`` →
    ``["archery"]``, ``"M"`` → ``["muzzleloader"]``, ``"R"`` →
    ``["rifle"]``).

    ``residency_scope`` is set from section/page context (``"resident"``,
    ``"nonresident"``, or ``"both"``).  It is NOT derived from a column —
    CPW does not print residency in the row data.

    ``extras`` captures any leftover or footnote text attached to the row
    (e.g. ``"■Units 12, 13 are valid for add-on bear licenses"``), collapsed
    per Rule R4.

    ``extraction_confidence`` is a ``ConfidenceTier`` string value
    (``"high"`` | ``"medium"`` | ``"low"``) assigned by T6; set to ``""`` as
    a placeholder here.

    ``page_reference`` anchors the row to its source page in the PDF.
    """

    hunt_code: str
    species_letter: str  # from hunt code; "" if unparseable
    sex_code: str  # from hunt code; "" if unparseable
    gmu_code: str  # from hunt code; "" if unparseable
    season_code: str  # from hunt code; "" if unparseable
    method_letter: str  # from hunt code; "" if unparseable
    unit: str | None  # "Unit" column verbatim (normalized)
    valid_gmus: str | None  # "Valid GMUs" column verbatim (normalized)
    season_windows: list[CpwSeasonWindow]
    list_value: str | None  # "List" column: "A"/"B"/"C"/"OTC"/None
    apply_by: str | None  # universally None for CPW V1 (no apply_by column)
    quota: int | None  # universally None for CPW V1 (no quota column)
    quota_range: str | None  # universally None for CPW V1 (no quota_range column)
    weapon_types: list[str]
    method_group: str  # "archery" | "muzzleloader" | "rifle"
    residency_scope: str  # "resident" | "nonresident" | "both" — from section context
    extras: str | None  # leftover/notes text, whitespace-collapsed (R4)
    extraction_confidence: str  # ConfidenceTier value; "" placeholder until T6
    page_reference: PageReference


class CpwSectionExtraction(TypedDict):
    """All extracted rows for one GMU × method × residency block.

    Each section represents a unique combination of ``(species_group,
    method_group, gmu_code, residency_scope)``.  Splitting on
    ``residency_scope`` ensures that resident-only and nonresident-only rows
    for the same GMU/method are never conflated into a single section.

    ``gmu_code`` is the three- or four-digit string from the ``Unit`` column
    (e.g. ``"001"``).  ``method_group`` names the method block the section
    came from (e.g. ``"archery"``, ``"muzzleloader"``, ``"first_rifle"``).
    ``species_group`` is ``"mule_deer"``, ``"whitetail"``, ``"elk"``, or
    ``"pronghorn"``.  ``residency_scope`` is ``"resident"``,
    ``"nonresident"``, or ``"both"`` — from the page/section heading context
    (Rule R12); all rows in a section share the same ``residency_scope``
    by construction.

    ``verbatim_text`` is a per-section reconstruction of that section's own
    source row cells — NOT the entire page text (which would duplicate one
    page's text across dozens of GMU sections and bloat the artifact).  For
    each row in the section, the verbatim source cells (``unit``,
    ``valid_gmus``, each ``season_windows[].raw_text``, ``sex_code``,
    ``hunt_code``, ``list_value``) are joined with ``" | "`` separators, and
    rows are joined with ``"\n"``.  ADR-008 is preserved: the authoritative
    verbatim date text lives in ``season_windows[].raw_text`` (always the
    unmodified PDF cell), and structured cells use only R1/R2/R3 cleanup.
    ``raw_text`` values in season windows are always verbatim.

    ``extracted_at`` carries the ISO timestamp from the PDF manifest's
    ``fetched_at`` field (mirrors MT ``DeaSectionExtraction``'s convention);
    it provides artifact-level provenance without re-introducing wall-clock
    non-determinism.

    ``page_reference`` anchors the section to its first page in the source PDF.
    """

    source_id: str
    species_group: str  # "mule_deer" | "whitetail" | "elk" | "pronghorn"
    method_group: str
    gmu_code: str
    residency_scope: str  # "resident" | "nonresident" | "both" — from section context (Rule R12)
    license_year: int
    extracted_at: str  # ISO timestamp from PDF manifest fetched_at
    page_reference: PageReference
    verbatim_text: str
    rows: list[CpwRowExtraction]


# ---------------------------------------------------------------------------
# T2: Cleanup utility pure helpers
# ---------------------------------------------------------------------------


def _normalize_cell(text: str | None) -> str | None:
    """Return a cleaned cell value, or ``None`` for absent/empty input.

    Cleanup order (Rules R13 → R2 → R1 → R3):

    1. **R13** — strip leading/trailing whitespace first so downstream regexes
       fire on trimmed text.
    2. **R2** — empty or whitespace-only string → ``None`` (absent data is
       explicit null per ADR-001).
    3. **R1** — bare ``"-"`` sentinel → ``None`` (CPW tables use a literal
       hyphen for absence, matching the FWP DEA convention).
    4. **R3** — rejoin hyphenated line-breaks via ``_HYPHEN_LINEBREAK_RE``
       (alphanumeric neighbours only; date-range hyphens like ``"Oct. 1-23"``
       are untouched because their neighbors are a space and a digit
       respectively — only genuine word-splits are rejoined).

    **R9** — ``"OTC"`` is preserved verbatim.  R1 only nulls a bare ``"-"``;
    ``"OTC"`` never matches that pattern and is never a whitespace-only string,
    so it passes through unchanged.

    **R15** — strips the CPW ``■`` OTC-marker glyph (U+25A0) from the result.
    Applies after R3 so the cleaned text has no stray bullet fragments in
    unit/valid_gmus values.  Season-window ``raw_text`` does NOT pass through
    this function (it goes through ``_parse_season_window`` instead), so ADR-008
    verbatim discipline for date text is preserved.  A cell whose only content
    is ``■`` (e.g. a trailing-bullet-only cell) returns ``None``.

    Does NOT collapse internal whitespace globally (that is Rule R4, applied
    only to notes/extras cells via ``_collapse_whitespace``).

    # Rule R1 / Rule R2 / Rule R3 / Rule R9 / Rule R13 / Rule R15
    """
    # R13: strip leading/trailing whitespace
    if text is None:
        return None
    stripped = text.strip()
    # R2: empty or whitespace-only → None
    if not stripped:
        return None
    # R1: bare dash sentinel → None
    if stripped == "-":
        return None
    # R3: rejoin hyphenated line-breaks (alphanumeric neighbours);
    # replace "-\n" with "-" (keep the hyphen, drop the newline)
    rejoined = _HYPHEN_LINEBREAK_RE.sub("-", stripped)
    # R15: strip CPW OTC-marker glyph (■, U+25A0) from structured cells.
    # Replace every occurrence of whitespace?+■+whitespace? with a single space,
    # then strip ends.  If the result is empty (cell was only ■), return None.
    if _OTC_BULLET in rejoined:
        rejoined = _OTC_BULLET_RE.sub(" ", rejoined).strip()
        if not rejoined:
            return None  # Rule R15: ■-only cell → None
    return rejoined


def _rejoin_hyphenated_linebreaks(text: str) -> str:
    """Rejoin soft hyphens at line-breaks when both neighbours are alphanumeric.

    E.g. ``"mule-\\ndeer"`` → ``"mule-deer"`` (both ``"e"`` before the hyphen
    and ``"d"`` after the newline are alphanumeric, so the newline is removed
    and the hyphen is preserved).

    Intentionally narrow:
    - ``"Sept.-\\nOct."`` is **not** rejoined — the character immediately before
      the hyphen is ``"."`` (a period), not alphanumeric.
    - ``"Oct. 1-23"`` is **not** rejoined — there is a space before ``"1"``, so
      the hyphen sits between a digit and another digit but the pattern requires
      both immediate neighbours to be alphanumeric with no intervening space.
    - ``"262-50"`` is **not** rejoined — no ``\\n`` after the hyphen.

    Operates on a non-``None`` string; caller is responsible for the None guard.

    # Rule R3
    """
    return _HYPHEN_LINEBREAK_RE.sub("-", text)


def _collapse_whitespace(text: str) -> str:
    """Collapse all whitespace runs to a single space and strip ends.

    Intended for **notes / extras cells ONLY** (Rule R4).  Do NOT apply this
    globally — preservation of single newlines is required elsewhere for cell
    parsing (e.g. ``_normalize_cell`` deliberately does not collapse single
    newlines that are load-bearing delimiters in multi-line cells).

    Multi-line footnote text in CPW tables embeds ``\\n`` between sentences;
    the natural reading is a single space-separated paragraph.

    Operates on a non-``None`` string; caller is responsible for the None guard.

    # Rule R4
    """
    return re.sub(r"\s+", " ", text).strip()


def _is_see_unit_row(row: list[str | None]) -> bool:
    """Return ``True`` if the row is a "See Unit NNN" cross-reference row.

    CPW tables frequently contain rows whose ``Valid GMUs`` cell reads
    ``"See Unit 123"`` (or ``"see unit 123"``, case-insensitive), meaning
    the unit shares regulations with unit 123.  These are not regulation rows
    and must be skipped to avoid empty-section artifacts.

    Rule R5 anchors the check to the ``Valid GMUs`` cell, but pdfplumber may
    place the see-unit text in any non-first cell (e.g. unit cell ``"8"`` +
    valid_gmus cell ``"see unit 7"``).  To handle both patterns robustly this
    function returns ``True`` when ANY cell in *row* exactly matches the
    see-unit pattern (i.e. the cell's normalised text begins with
    ``"see unit N"``).  Only the cell whose entire content is the cross-
    reference triggers the skip — cells that merely mention "see unit" in
    passing text (not as the whole value) are not matched because the regex is
    anchored at the start and the see-unit rows never carry any other content
    beyond the cross-reference.

    # Rule R5
    """
    for cell in row:
        normalized = _normalize_cell(cell)
        if normalized is not None and _SEE_UNIT_RE.match(normalized):
            return True
    return False


def _is_footnote_row(row: list[str | None]) -> bool:
    """Return ``True`` if the row is a ``■``-prefixed footnote row.

    CPW regulation tables include footnote rows whose first non-empty cell
    starts with the ``■`` bullet character (e.g.
    ``"■Units 12, 13 are valid for add-on bear licenses"``).  These are
    annotations, not regulation rows, and must be skipped.

    Matches against the first non-empty cell in *row* after stripping
    leading/trailing whitespace.

    # Rule R6
    """
    for cell in row:
        if cell is None:
            continue
        stripped = cell.strip()
        if stripped:
            return stripped.startswith("■")
    return False


def _is_map_page_text(text: str | None, table_count: int) -> bool:
    """Return ``True`` when a page should be skipped as a map / photo page.

    A page is classified as a map/photo page when **both** conditions hold:

    1. ``table_count == 0`` — pdfplumber found no regulation tables on the page.
    2. The stripped ``text`` is shorter than ``_MAP_PAGE_MIN_TEXT_CHARS``
       (120 chars) or is ``None`` / empty.

    Rationale: map pages (e.g. CWD prevalence maps, OTC maps) in the CPW Big
    Game brochure contain no regulation tables and produce either empty text or
    short garbled rotated glyphs totalling < 100 characters.  The 120-char
    threshold is conservative — a single CPW regulation row produces ≥ 40 chars
    and a sparsely-worded section header ≥ 30 chars.  Only genuinely empty or
    garbled pages fall below the threshold.

    **Positive-content safeguard:** the negative signals above (no table + short
    text) could in principle drop a legitimate regulation page if a future CPW
    layout change made pdfplumber miss its table AND its text happened to be
    short.  To prevent that silent loss, a page whose text contains ANY
    hunt-code-shaped token (``_HUNT_CODE_FRAGMENT_RE``) is treated as regulation
    content and is NEVER classified as a map page, regardless of table detection
    or text length — ``extract_text`` returns cell words even when table
    detection fails, so a real regulation page always carries hunt codes while a
    genuine map/photo page carries none.

    This is a pure function (caller supplies the already-extracted text and
    table count) so it can be unit-tested without a live PDF.

    # Rule R10
    """
    if table_count != 0:
        return False
    if text is None:
        return True
    stripped = text.strip()
    # Positive-content safeguard: regulation pages always carry hunt codes.
    if _HUNT_CODE_FRAGMENT_RE.search(stripped):
        return False
    return len(stripped) < _MAP_PAGE_MIN_TEXT_CHARS


def _is_garbage_row(row: "CpwRowExtraction") -> bool:
    """Return ``True`` when a row is map-OCR / unparseable garbage.

    Of the LOW-confidence rows in the artifact, the vast majority are pure
    garbage from map-page OCR leakage (e.g. ``hunt_code='Tee'``,
    ``list_value='rrms'``, ``hunt_code='£¤385\\n93'``).  A small number are
    real multi-hunt-code cells like ``'D-M-082-O2-R\\nD-M-082-O3-R'`` that DO
    contain a valid hunt-code pattern but could not be parsed as a single code.

    A row is garbage when ALL three conditions hold:

    (a) ``row["species_letter"] == ""``  — the hunt code did not parse at all.
    (b) No hunt-code-shaped substring in ``hunt_code`` — i.e.
        ``_HUNT_CODE_FRAGMENT_RE.search(row["hunt_code"] or "")`` is ``None``.
        This keeps real multi-code cells (condition b fails) and discards pure
        OCR noise (no fragment at all).
    (c) ``row["list_value"] not in {"A", "B", "C", "OTC"}`` — no salvageable
        draw-mechanic indicator.  Garbage rows from map pages carry junk text
        or ``None``; real rows carry a list letter.

    Garbage rows are WARNING-logged by the caller (ADR-001 loud, not silent)
    and omitted from their section.  Real multi-code LOW rows are preserved.
    """
    # (a) Hunt code did not parse
    if row["species_letter"] != "":
        return False
    # (b) No hunt-code-shaped fragment present
    if _HUNT_CODE_FRAGMENT_RE.search(row["hunt_code"] or ""):
        return False
    # (c) No salvageable list value
    if row["list_value"] in {"A", "B", "C", "OTC"}:
        return False
    return True


def _undouble_text(text: str | None) -> str | None:
    """Recover the true cell text when pdfplumber has uniformly doubled every glyph.

    A string is "uniformly doubled" iff ALL three conditions hold:

    1. ``len(s) >= _UNDOUBLE_MIN_LEN`` (short even all-paired strings —
       e.g. a hypothetical 4-char cell ``"AABB"`` — are left alone to avoid
       false positives; real doubled cells are long: a doubled hunt code is
       ≥ 22 chars, a doubled date ≥ 16 chars).
    2. ``len(s) % 2 == 0`` (odd-length strings cannot be uniformly doubled).
    3. ``s[::2] == s[1::2]`` (every even-index char equals the following
       odd-index char — the defining property of uniform character doubling).

    When all three hold, returns ``s[::2]`` — the recovered (undoubled) text.

    TOKEN-LEVEL FALLBACK: cells that contain whitespace (e.g. date cells like
    ``"Oct. 24–Nov. 1"``) defeat the whole-string test because pdfplumber
    collapses the *doubled* spaces back to single spaces (a documented
    word-grouping behaviour — see known-pitfalls "extract_text collapses
    repeated spaces"), which misaligns the pairing after the first space.
    Space-free cells like hunt codes are unaffected and recover via the
    whole-string path. For the whitespace case, split on whitespace and
    undouble each token independently, but ONLY when EVERY token is itself
    uniformly doubled (even length + pair-equal) AND at least one token is
    long enough (``>= _UNDOUBLE_MIN_LEN``) to anchor the detection — this
    guards against short coincidences (e.g. a real ``"11 22"`` is left alone
    because neither token reaches the anchor length). Normal multi-word text
    ("Limited Licenses", "Sept. 2–30") fails the all-tokens-doubled gate and
    is returned unchanged.

    Returns *text* unchanged when neither path applies, and ``None`` when
    *text* is ``None``.

    Pure function, no side effects; mirrors Montana's ``_reverse_cell_text``
    rotated-table recovery pattern.

    Examples::

        _undouble_text("DD--MM--002200--OO22--RR") → "D-M-020-O2-R"
        _undouble_text("OOcctt.. 2244––NNoovv.. 11") → "Oct. 24–Nov. 1"
        _undouble_text("D-M-001-O1-A")               → "D-M-001-O1-A"  (unchanged)
        _undouble_text("Limited Licenses")           → "Limited Licenses"  (unchanged)
        _undouble_text("AA")                          → "AA"  (too short)
        _undouble_text(None)                          → None

    # Rule R14
    """
    if text is None:
        return None
    s = text
    # Whole-string uniform doubling (space-free cells, e.g. hunt codes).
    if (
        len(s) >= _UNDOUBLE_MIN_LEN
        and len(s) % 2 == 0
        and s[::2] == s[1::2]
    ):
        return s[::2]
    # Token-level fallback for whitespace-bearing cells (e.g. dates) whose
    # doubled spaces pdfplumber collapsed to single spaces.
    # Safety assumption: real CPW tokens (hunt codes, month names, digits) are
    # NOT coincidentally pair-equal unless they were actually doubled by
    # pdfplumber.  The anchor-length gate (_UNDOUBLE_MIN_LEN) guards against
    # short coincidences like "11 22".  Normal multi-token text such as
    # "Limited Licenses" or "Sept. 2–30" fails the all-tokens-pair-equal gate
    # and is left unchanged.
    tokens = s.split()
    if (
        len(tokens) >= 2
        and any(len(t) >= _UNDOUBLE_MIN_LEN for t in tokens)
        and all(len(t) % 2 == 0 and t[::2] == t[1::2] for t in tokens)
    ):
        return " ".join(t[::2] for t in tokens)
    return text


def _looks_doubled_row(row: list[str | None]) -> bool:
    """Return ``True`` iff the row appears to be uniformly pdfplumber-doubled.

    A row is classified as doubled when AT LEAST ONE cell satisfies all three:

    1. ``cell`` is not ``None``.
    2. ``len(cell.strip()) >= _DOUBLED_ROW_MIN_CELL_LEN`` (length ≥ 10 after
       stripping — short cells like ``"2200"`` are 4-char doubled = 8 chars,
       below the gate; real doubled hunt codes or dates are ≥ 20 chars).
    3. The stripped cell is uniformly doubled per the ``s[::2] == s[1::2]``
       positional test (even length + pair-equal).

    A single long uniformly-doubled cell is an unambiguous signal that
    pdfplumber double-rendered the whole row (the probability of a real
    ≥ 10-char text being perfectly pair-equal by chance is negligible).

    Using a row-level gate rather than per-cell application prevents
    false positives on short or coincidentally pair-equal cells like lone
    ``"2200"`` or ``"AABB"``.  Within a doubled row, ALL cells are doubled,
    and ``_undouble_text``'s per-cell length+even guard leaves any
    non-doubled cell untouched.

    # Rule R14
    """
    for cell in row:
        if cell is None:
            continue
        stripped = cell.strip()
        n = len(stripped)
        if (
            n >= _DOUBLED_ROW_MIN_CELL_LEN
            and n % 2 == 0
            and stripped[::2] == stripped[1::2]
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# T3: Hunt-code parsing
# ---------------------------------------------------------------------------

# Method-letter → method group name.
# Used by ``_method_group_for`` and exported for downstream tests.
_METHOD_GROUP_BY_LETTER: dict[str, str] = {
    "A": "archery",
    "M": "muzzleloader",
    "R": "rifle",
}


def _parse_hunt_code(code: str) -> dict[str, str] | None:
    """Parse a CPW hunt code into its five component fields.

    Matches *code* (stripped) against ``_HUNT_CODE_RE`` (Rule R8).  Returns a
    dict with keys ``"species_letter"``, ``"sex_code"``, ``"gmu_code"``,
    ``"season_code"``, and ``"method_letter"`` when the code conforms to the
    CPW format ``{Species}-{Sex}-{GMU}-{Season}-{Method}``
    (e.g. ``"D-M-001-O1-A"``).

    Returns ``None`` on a parse failure — the caller keeps the raw hunt code
    verbatim and demotes ``extraction_confidence`` to ``"medium"`` per
    ADR-017.  Does NOT raise; raising here would abort row-level loops on
    malformed codes rather than gracefully degrading confidence.

    # Rule R8
    """
    m = _HUNT_CODE_RE.match(code.strip())
    if m is None:
        return None
    species_letter, sex_code, gmu_code, season_code, method_letter = m.groups()
    return {
        "species_letter": species_letter,
        "sex_code": sex_code,
        "gmu_code": gmu_code,
        "season_code": season_code,
        "method_letter": method_letter,
    }


def _method_group_for(method_letter: str) -> str | None:
    """Return the method group name for *method_letter*, or ``None`` if unknown.

    Looks up *method_letter* in ``_METHOD_GROUP_BY_LETTER``.  Returns
    ``None`` for any letter not in the table — the caller decides how to
    handle unknown method letters (typically by logging a warning and
    demoting confidence) and must NOT raise here.

    Known mappings::

        "A" → "archery"
        "M" → "muzzleloader"
        "R" → "rifle"
    """
    return _METHOD_GROUP_BY_LETTER.get(method_letter)


def _weapon_types_for(method_letter: str) -> list[str]:
    """Derive the ``weapon_types`` list from a CPW method letter.

    Returns a list of ``WeaponType`` literal strings (from
    ``ingestion.lib.schema.WeaponType``) appropriate for the given method::

        "A" → ["archery"]
        "M" → ["muzzleloader"]
        "R" → ["any_legal_weapon"]

    The ``"R"`` (rifle) method maps to ``"any_legal_weapon"`` — not
    ``"rifle"`` — because CPW rifle seasons are unrestricted general-weapon
    seasons (matching the schema's ``"any_legal_weapon"`` value, which the
    Montana DEA adapter also uses for general/unrestricted seasons).  The
    ``WeaponType`` Literal in ``ingestion/ingestion/lib/schema.py`` defines
    both ``"rifle"`` and ``"any_legal_weapon"``; ``"any_legal_weapon"`` is
    the correct choice for CPW rifle seasons.

    Returns ``[]`` for an unknown letter — the caller handles unknown method
    letters (typically by logging a warning and demoting confidence).  Does
    NOT raise.
    """
    mapping: dict[str, list[str]] = {
        "A": ["archery"],
        "M": ["muzzleloader"],
        "R": ["any_legal_weapon"],
    }
    return mapping.get(method_letter, [])


def _species_group_for(species_letter: str, is_whitetail: bool = False) -> str:
    """Map a CPW species letter to the canonical ``species_group`` string.

    ``"D"`` maps to ``"whitetail"`` when *is_whitetail* is ``True`` (Rule R11
    — the whitetail-only sub-section on PDF page 44 switches the species
    context for the remainder of the deer page range), or to ``"mule_deer"``
    otherwise.  ``"E"`` maps to ``"elk"``.  ``"A"`` maps to ``"pronghorn"``
    (CPW hunt codes use ``"A"`` for Antelope / pronghorn — confirmed from live
    PDF hunt codes on pronghorn pages 64–67, e.g. ``"A-M-004-W2-R"``,
    ``"A-M-012-O1-M"``; the earlier ``"P"`` assumption was incorrect).

    Any other species letter raises ``PdfExtractionError`` immediately per
    ADR-001 (fail-loud; no invented values).  A new CPW species letter in a
    future year's brochure must be explicitly added here before ingestion
    proceeds.

    # Rule R11 (whitetail branch)

    :param species_letter: Single uppercase letter from the hunt-code
        ``species_letter`` component (e.g. ``"D"``, ``"E"``, ``"A"``).
    :param is_whitetail: When ``True``, ``"D"`` rows are tagged
        ``'whitetail'`` rather than ``'mule_deer'``.  Defaults to ``False``.
    :raises PdfExtractionError: On an unrecognised *species_letter*.
    """
    if species_letter == "D":
        return "whitetail" if is_whitetail else "mule_deer"
    if species_letter == "E":
        return "elk"
    if species_letter == "A":
        return "pronghorn"
    raise PdfExtractionError(f"unexpected CPW species letter: {species_letter!r}")


def _first_table_method(rows: list[list[str | None]]) -> str | None:
    """Return the ``method_group`` of the first parseable hunt code in *rows*.

    Used to attribute a method-less ``Season dates:`` heading-only row to the
    method of the table it actually heads (derived from the hunt codes' method
    letter), rather than the page-advanced ``current_method_group`` which may
    have moved past this table on a multi-section page where a muzzleloader
    header would otherwise be mis-tagged as rifle (cubic P1-6). Returns ``None``
    when no parseable hunt code is found.
    """
    for row in rows:
        for cell in row:
            if not cell:
                continue
            for token in cell.split():
                parsed = _parse_hunt_code(token)
                if parsed is not None:
                    return _method_group_for(parsed["method_letter"])
    return None


# ---------------------------------------------------------------------------
# T4: Section headings + season-window parsing
# ---------------------------------------------------------------------------
#
# Probed 2026-06-09 against live PDF
# ``co-cpw-big-game-2026-brochure-2026-03-04.pdf``.
#
# Real observed Dates column formats (sample pages noted):
#   'Sept. 2–30'                    — same-month, en-dash, no surrounding spaces
#   'Oct. 24–Nov. 1'                — cross-month, single line
#   'Aug. 15–\nJan. 15'            — cross-month with newline in cell
#   'Aug. 31\n– Sept. 28'          — newline BEFORE the en-dash
#   'Aug. 15–\nJan. 15, 2027'      — cross-year (year only on end date)
#   'Dec. 1–14\nLate'              — trailing label after newline
#   'Oct. 24–Nov. 1\nNov. 7–15'   — TWO ranges on one row (first is primary)
#   'NNoovv.. 1188––2222'          — doubled-char OCR artifact (unparseable → raw_text)
#   '■Aug. 15–25'                  — leading ■ bullet (strip before parse)
#
# Real section heading strings (first-row cell of section-header tables):
#   'Archery — Limited Licenses'                                    (p33–p34)
#   'Muzzleloader — Limited Licenses'                               (p35–p36)
#   'Rifle — Limited Licenses'                                      (p37–p42)
#   'Archery — Limited Resident & Nonresident Licenses — Season Dates: Sept. 2–30'  (p52)
#   'Archery — Limited Nonresident Licenses — Season Dates: Sept. 2–30'             (p53)
#   'Muzzleloader — Limited Licenses — Season Dates: Sept. 12–20'                   (p53–p54)
#
# Real Season Dates in page text (Rule R7 fallback):
#   'Season Dates: Sept. 2–30 (Unless otherwise noted )'           (p33, p34)
#   'Season Dates: Sept. 12–20 (unless otherwise noted )'          (p35, p36)
#
# Real whitetail heading in page text:
#   'Limited Licenses — White-Tailed Deer Only'                    (p44)

# ---------------------------------------------------------------------------
# Month abbreviation canonical set (used in regex alternation).
# CPW uses the three-letter abbreviated form with a period, e.g. "Sept." for
# September (four letters) and "Jan." / "Feb." etc. for the rest.
# Confirmed from live PDF: all months appear as "Mmm." (dot-terminated).
# ---------------------------------------------------------------------------

_MONTH_ABBREVS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Oct|Nov|Dec)\."

# ---------------------------------------------------------------------------
# Core date-range regex.
#
# Matches a CPW date range after:
#   1. Collapsing newlines around the en-dash (–, U+2013) or regular hyphen
#      that separates the start date from the end date.
#   2. Stripping leading ■ bullets and trailing label suffixes ("Late",
#      "Early", "youth only", parenthetical notes, etc.).
#
# Pattern anatomy (verbatim from live-PDF observation):
#   Start date:  "Mmm. D"  (e.g. "Sept. 2")
#   Separator:   optional whitespace, then "–" (en-dash, U+2013) or "-"
#                (regular hyphen), then optional whitespace
#   End date:    "Mmm. D" or "D"  (e.g. "Nov. 1" or "30"; same-month end
#                drops the month abbrev)
#   Optional:    ", YYYY" (year suffix on cross-year ranges, e.g. ", 2027")
#
# Two capture groups:
#   group 1 — full start token, e.g. "Sept. 2"
#   group 2 — full end token, e.g. "Nov. 1" or "30" or "Jan. 15, 2027"
#
# Built from the real format `'Sept. 2–30'`, `'Oct. 24–Nov. 1'`, etc.
# The (?:\s*[–-]\s*) separator handles:
#   - 'Sept. 2–30'       (en-dash, no spaces)
#   - 'Oct. 24–\nNov. 1' (en-dash, newline absorbed by pre-normalisation)
#   - 'Aug. 31\n– Sept.' (newline before en-dash, absorbed by pre-normalisation)
# ---------------------------------------------------------------------------

_DATE_RANGE_RE = re.compile(
    r"(?P<start>"
    + _MONTH_ABBREVS
    + r"\s+\d{1,2})"
    + r"\s*[–\-]\s*"
    + r"(?P<end>"
    + r"(?:"
    + _MONTH_ABBREVS
    + r"\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}(?:,\s*\d{4})?)"
    + r")"
)

# ---------------------------------------------------------------------------
# Method-section heading regex.
#
# Matches section-header strings like:
#   'Archery — Limited Licenses'
#   'Muzzleloader — Limited Licenses'
#   'Rifle — Limited Licenses'
#   'Archery — Limited Resident & Nonresident Licenses — Season Dates: Sept. 2–30'
#
# The method word appears at the start of the string (after optional
# whitespace), followed by optional continuation text.  Case-insensitive so
# future brochure-year capitalisation changes don't silently drop rows.
# ---------------------------------------------------------------------------

_METHOD_HEADING_RE = re.compile(
    r"(?i)^\s*(?P<method>Archery|Muzzleloader|Rifle)\b"
)

# ---------------------------------------------------------------------------
# Whitetail boundary heading regex.
#
# Matches the page-level heading that signals the switch from mule_deer to
# whitetail species context (Rule R11).  Confirmed from live PDF page 44:
#   'Limited Licenses — White-Tailed Deer Only'
#
# Pattern is intentionally broad (whitespace-collapsed, case-insensitive) to
# tolerate minor formatting variations across future brochure years:
#   "White-Tailed Deer Only"
#   "White Tailed Deer Only"
#   "White-tailed Deer Only"
# ---------------------------------------------------------------------------

_WHITETAIL_HEADING_RE = re.compile(
    r"(?i)white[- ]?tailed\s+deer\s+only"
)

# ---------------------------------------------------------------------------
# Season Dates header regex (Rule R7 fallback).
#
# Matches strings like:
#   'Archery — Limited Resident & Nonresident Licenses — Season Dates: Sept. 2–30'
#   'Season Dates: Sept. 2–30 (Unless otherwise noted)'
# ---------------------------------------------------------------------------

_HEADER_DATE_RE = re.compile(
    r"(?i)Season\s+Dates\s*:\s*"
    + r"(?P<start>"
    + _MONTH_ABBREVS
    + r"\s+\d{1,2})"
    + r"\s*[–\-]\s*"
    + r"(?P<end>"
    + r"(?:"
    + _MONTH_ABBREVS
    + r"\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}(?:,\s*\d{4})?)"
    + r")"
)


def _parse_date_range(text: str) -> tuple[str | None, str | None]:
    """Extract ``(start_date, end_date)`` strings from a CPW date-range text.

    Normalises whitespace around the en-dash separator (handles newlines that
    appear before *or* after the dash, as observed in multi-line cells), then
    matches via ``_DATE_RANGE_RE``.

    Returns ``(start, end)`` with the verbatim substrings captured from
    *text* when a range is found.  Returns ``(None, None)`` when no range
    can be parsed — the caller is responsible for preserving the raw text as
    ``raw_text`` per ADR-008.

    Private — callers use ``_parse_season_window`` and ``_parse_header_date``.
    """
    # Normalise: collapse newlines + surrounding whitespace around the
    # separator so 'Aug. 31\n– Sept. 28' and 'Aug. 15–\nJan. 15' both
    # become 'Aug. 31– Sept. 28' / 'Aug. 15–Jan. 15' before the regex runs.
    normalised = re.sub(r"\s*\n\s*", " ", text)
    m = _DATE_RANGE_RE.search(normalised)
    if m is None:
        return None, None
    return m.group("start"), _inherit_end_month(m.group("start"), m.group("end"))


def _inherit_end_month(start: str, end: str) -> str:
    """Disambiguate a same-month end token by inheriting the start's month (P1-4).

    CPW drops the redundant month on a same-month range's end token, so
    "Sept. 2–30" yields a bare-numeric end "30". This prepends the start's
    month abbreviation so ``end_date`` is an unambiguous standalone date
    ("Sept. 30"). Cross-month ends ("Nov. 1") already carry their own month
    and are returned unchanged. The verbatim source is preserved by callers in
    ``raw_text`` per ADR-008; this only disambiguates the parsed convenience
    field. Shared by ``_parse_date_range`` and ``_parse_header_date``.
    """
    if end and end[0].isdigit():
        start_month = start.split(maxsplit=1)[0]  # e.g. "Sept."
        return f"{start_month} {end}"
    return end


def _parse_season_window(raw: str | None) -> "CpwSeasonWindow | None":
    """Parse a CPW ``Dates`` column cell into a ``CpwSeasonWindow``.

    Given the raw string from a ``Dates`` column cell, returns a
    ``CpwSeasonWindow`` TypedDict with:

    - ``raw_text`` — the verbatim cell string, always populated when the
      cell is present (ADR-008: never drop source text).
    - ``start_date`` / ``end_date`` — parsed begin/end date strings
      (e.g. ``"Sept. 2"`` / ``"Sept. 30"``), or ``None`` when the cell is
      present but the date range cannot be parsed into a clean two-date form.

    Returns ``None`` when *raw* is ``None`` or empty/whitespace-only (R2).

    Handles all observed real-PDF formats (probed 2026-06-09):

    - ``'Sept. 2–30'`` — same-month en-dash range
    - ``'Oct. 24–Nov. 1'`` — cross-month, single line
    - ``'Aug. 15–\\nJan. 15'`` — cross-month with newline in cell
    - ``'Aug. 31\\n– Sept. 28'`` — newline BEFORE the en-dash
    - ``'Aug. 15–\\nJan. 15, 2027'`` — cross-year with year suffix
    - ``'Dec. 1–14\\nLate'`` — trailing label after newline (stripped)
    - ``'Oct. 24–Nov. 1\\nNov. 7–15'`` — two ranges; first range is primary
    - ``'NNoovv.. 1188––2222'`` — doubled-char OCR artifact → ``raw_text``
      preserved, ``start_date`` / ``end_date`` both ``None``
    - ``'■Aug. 15–25'`` — leading ``■`` bullet stripped before parsing

    Per the S03.3 UAT D1 lesson, per-row windows are load-bearing — this
    function parses **one** cell and returns **one** window; the caller (T5)
    assembles the ``season_windows`` list for each row.  Do NOT raise on
    parse failure — degrade gracefully and preserve ``raw_text``.
    """
    # R2: None / empty / whitespace-only → not present
    if not raw or not raw.strip():
        return None

    # Strip leading ■ bullet (observed: '■Aug. 15–25')
    cleaned = raw.strip().lstrip("■").strip()

    start, end = _parse_date_range(cleaned)
    return CpwSeasonWindow(
        start_date=start,
        end_date=end,
        raw_text=raw,  # always verbatim ADR-008 — use original, not cleaned
    )


def _parse_header_date(header_text: str) -> "CpwSeasonWindow | None":
    """Extract a season-date window from a CPW section-heading string.

    Rule R7 fallback: CPW archery / muzzleloader pages and some elk limited-
    license pages state the overall season date in the section-header text
    (either as a page-level heading or as the first-row cell of a section-
    header table) rather than repeating it per data row.

    Confirmed heading formats from live PDF (probed 2026-06-09):
      ``'Season Dates: Sept. 2–30 (Unless otherwise noted )'``
      ``'Archery — Limited Resident & Nonresident Licenses — Season Dates: Sept. 2–30'``
      ``'Muzzleloader — Limited Licenses — Season Dates: Sept. 12–20'``

    Matches via ``_HEADER_DATE_RE``.  Returns a ``CpwSeasonWindow`` with
    ``raw_text`` set to the full *header_text* string (ADR-008 — the entire
    heading is the source) and ``start_date`` / ``end_date`` from the
    matched range.

    Returns ``None`` when no date range is found in *header_text* (e.g.
    ``'Rifle — Limited Licenses'`` which carries no inline date).

    # Rule R7
    """
    m = _HEADER_DATE_RE.search(header_text)
    if m is None:
        return None
    return CpwSeasonWindow(
        start_date=m.group("start"),
        end_date=_inherit_end_month(m.group("start"), m.group("end")),
        raw_text=header_text,  # full heading is the source per ADR-008
    )


def _method_group_from_heading(text: str | None) -> str | None:
    """Detect a CPW method-section heading and return the method group name.

    Matches section-heading strings like those observed in the live PDF
    (probed 2026-06-09):

      ``'Archery — Limited Licenses'``
      ``'Muzzleloader — Limited Licenses'``
      ``'Rifle — Limited Licenses'``
      ``'Archery — Limited Resident & Nonresident Licenses — Season Dates: ...'``

    Returns one of ``"archery"``, ``"muzzleloader"``, ``"rifle"`` when *text*
    starts with a recognised method word (case-insensitive), or ``None`` when
    no method heading is detected (e.g. data-row text, or a heading that does
    not start with a method keyword).

    Does NOT raise — callers use the ``None`` return to indicate "not a
    method heading" and continue to the next text candidate.
    """
    if not text:
        return None
    m = _METHOD_HEADING_RE.match(text)
    if m is None:
        return None
    method_word = m.group("method").lower()
    # Map the raw method word to the canonical method group name.
    # "archery" and "muzzleloader" are self-mapping; "rifle" is canonical.
    return method_word  # "archery" | "muzzleloader" | "rifle"


def _is_whitetail_heading(text: str | None) -> bool:
    """Return ``True`` if *text* is the whitetail-only boundary heading.

    Detects the page-level section heading that signals the mule_deer →
    whitetail species-context switch (Rule R11).  Confirmed heading from
    live PDF page 44 (probed 2026-06-09):

      ``'Limited Licenses — White-Tailed Deer Only'``

    Matches case-insensitively; tolerates ``"White Tailed"`` (no hyphen) or
    ``"white-tailed"`` (lowercase) variants that may appear in future
    brochure years.

    Returns ``False`` for ``None`` input or any non-matching text.

    # Rule R11
    """
    if not text:
        return False
    return bool(_WHITETAIL_HEADING_RE.search(text))


# ---------------------------------------------------------------------------
# T5: Column-block table parsing
# ---------------------------------------------------------------------------
#
# STEP 1 — Confirmed live-PDF table delivery (probed 2026-06-09):
#
# All hunt-code tables in the deer/elk/pronghorn pages (PDF pp. 30–67) are
# delivered by pdfplumber as ONE table object whose rows have one of the
# following column counts:
#
#   6-col  — single block:  Unit | Valid GMUs | Dates | Sex | Hunt Code | List
#   5-col  — single block (elk archery single half, no Valid GMUs):
#             Unit | Valid GMUs | Sex | Hunt Code | List
#             (confirmed on pp. 52–53 companion 5-col tables)
#   7-col  — single block with an extra None column:
#             Unit | Valid GMUs | Dates | Sex | None | Hunt Code | List
#             (observed on pp. 55–56 elk rifle companion tables)
#   10-col — dual block (archery, NO Dates column):
#             Unit | Valid GMUs | Sex | Hunt Code | List  × 2
#             (pp. 52–53: elk archery resident/nonresident pages)
#   12-col — dual block (standard, WITH Dates):
#             Unit | Valid GMUs | Dates | Sex | Hunt Code | List  × 2
#             (most deer, elk, pronghorn pages; the dominant variant)
#   13-col — dual block with one-side extra None column:
#             Unit | Valid GMUs | [None] | Dates | Sex | Hunt Code | List  (left)
#           + Unit | Valid GMUs | Dates | Sex | Hunt Code | List (right)
#             OR the mirrored version (observed on pp. 40, 55–56)
#   19-col — TRIPLE block (elk rifle pp. 59, pronghorn rifle pp. 66):
#             6-col | "" spacer | 6-col | 6-col
#   8-col  — Season Choice (single block, deer p. 42, possibly elk/pronghorn):
#             None | Unit | Archery Dates | Muzzleloader Dates | Rifle Dates
#                 | Sex | Hunt Code | List
#             (leading None cell; no Valid GMUs column)
#   10-col (Season Choice dual) — not confirmed; treat as two 5-col blocks
#
# Identification key (used by _classify_table_variant):
#   ncols == 6  → single block, 6-col standard  (has Dates)
#   ncols == 5  → single block, 5-col no-Dates   (no Dates col; archery)
#   ncols == 7  → single block, 7-col extra-None
#   ncols == 8  → Season Choice single block
#   ncols == 10 → dual block, 5-col no-Dates × 2
#   ncols == 12 → dual block, 6-col standard × 2
#   ncols == 13 → dual block, one side has extra None column
#   ncols == 19 → triple block, 6-col standard × 3 (with empty string spacer)
#   other       → unrecognised; emit DEBUG and skip
#
# For dual/triple blocks the per-block slice logic is in _block_slices().
# ---------------------------------------------------------------------------

# Sentinel: column not present in this variant.
_NO_COL = -1


def _classify_table_variant(ncols: int) -> str:
    """Return a short string identifying the table variant by column count.

    Used by ``_parse_table_block`` to select the column-index map.

    Returns one of:
      ``"6col"``   — single block, standard 6-column
      ``"5col"``   — single block, 5-column (no Dates; archery header-date)
      ``"7col"``   — single block, 7-column with extra None column
      ``"8col"``   — Season Choice single block
      ``"10col"``  — dual block, 5-column no-Dates × 2
      ``"12col"``  — dual block, standard 6-column × 2
      ``"13col"``  — dual block, 6+None+6 or None+6+6 variant
      ``"19col"``  — triple block, 6-column × 3 (with empty spacer)
      ``"unknown"``— not recognised; caller logs DEBUG and skips
    """
    _MAP: dict[int, str] = {
        6: "6col",
        5: "5col",
        7: "7col",
        8: "8col",
        10: "10col",
        12: "12col",
        13: "13col",
        19: "19col",
    }
    return _MAP.get(ncols, "unknown")


def _block_slices(
    variant: str,
    header_row: list[str | None] | None = None,
) -> list[tuple[int, ...]]:
    """Return the column-index tuples for each block within a row.

    Each element is a tuple of column indices::

        (unit, valid_gmus, dates, sex, hunt_code, list_col)

    ``_NO_COL`` (== -1) means the field is absent in this variant; callers
    treat it as ``None``.

    The Season Choice variant (``"8col"``) returns a single-element list with
    ``valid_gmus = _NO_COL`` and three date indices; callers handle the
    multi-date Season Choice logic separately via
    ``_parse_season_choice_row``.

    Returned order: ``[(unit, valid_gmus, dates, sex, hunt_code, list_col), ...]``
    except for ``"8col"`` which returns
    ``[(unit, valid_gmus, archery_dates, muzz_dates, rifle_dates, sex, hunt_code, list_col)]``.

    For the ``"19col"`` triple-block variant, the *header_row* is used to
    detect the position of the empty-string spacer column (it can be at index
    6 OR at index 12, depending on the page).  Provide the column-header row
    (the row containing ``"Hunt Code"`` cells) for reliable detection.
    """
    # Standard 6-col single block: indices 0-5
    _6COL = (0, 1, 2, 3, 4, 5)
    # 5-col single block (no Dates): Unit=0, Valid GMUs=1, NO Dates, Sex=2, Hunt Code=3, List=4
    _5COL = (0, 1, _NO_COL, 2, 3, 4)
    # 7-col with extra None: Unit=0, Valid GMUs=1, Dates=2, Sex=3, None=4, HuntCode=5, List=6
    _7COL = (0, 1, 2, 3, 5, 6)
    if variant == "6col":
        return [_6COL]
    if variant == "5col":
        return [_5COL]
    if variant == "7col":
        return [_7COL]
    if variant == "8col":
        # Season Choice: None|Unit|ArcheryDates|MuzzDates|RifleDates|Sex|HuntCode|List
        # Return as (unit, valid_gmus, archery_dates, muzz_dates, rifle_dates, sex, hunt_code, list_col)
        return [(1, _NO_COL, 2, 3, 4, 5, 6, 7)]
    if variant == "10col":
        # Dual 5-col no-Dates blocks
        return [(0, 1, _NO_COL, 2, 3, 4), (5, 6, _NO_COL, 7, 8, 9)]
    if variant == "12col":
        # Dual standard 6-col blocks
        return [_6COL, (6, 7, 8, 9, 10, 11)]
    if variant == "13col":
        # Left block: Unit=0, Valid GMUs=1, None=2 (extra), Dates=3, Sex=4, HuntCode=5, List=6
        # Confirmed from pp. 40 and 55:
        # header row: ['Unit', 'Valid GMUs', None, 'Dates', 'Sex', 'Hunt Code', 'List',
        #              'Unit', 'Valid GMUs', 'Dates', 'Sex', 'Hunt Code', 'List']
        # Left: skip col 2 (extra None): (0, 1, 3, 4, 5, 6), right: (7, 8, 9, 10, 11, 12)
        return [(0, 1, 3, 4, 5, 6), (7, 8, 9, 10, 11, 12)]
    if variant == "19col":
        # Triple block layout varies: the empty-string spacer column sits either
        # at index 6 (elk rifle p59) or at index 12 (pronghorn rifle p66):
        #
        #   p59: [A0-A5 | '' at 6 | B7-B12 | C13-C18]
        #   p66: [A0-A5 | B6-B11 | '' at 12 | C13-C18]
        #
        # Detect which layout by finding the first spacer (empty string) in the
        # column-header row.  The spacer is the single empty-string cell between
        # two "Unit" header cells.
        spacer_idx = 6  # default (p59 / elk layout)
        if header_row is not None:
            for ci, cell in enumerate(header_row):
                # The spacer is an empty string (not None) in the header row.
                if ci > 0 and isinstance(cell, str) and cell.strip() == "":
                    # Confirm the cell before and after are both plausible "Unit"
                    # neighbours: the column before the spacer should be a "List"
                    # or None-padded cell and the column after should be "Unit".
                    spacer_idx = ci
                    break
        if spacer_idx == 6:
            # [A: 0-5] | spacer at 6 | [B: 7-12] | [C: 13-18]
            return [(0, 1, 2, 3, 4, 5), (7, 8, 9, 10, 11, 12), (13, 14, 15, 16, 17, 18)]
        elif spacer_idx == 12:
            # [A: 0-5] | [B: 6-11] | spacer at 12 | [C: 13-18]
            return [(0, 1, 2, 3, 4, 5), (6, 7, 8, 9, 10, 11), (13, 14, 15, 16, 17, 18)]
        else:
            raise PdfExtractionError(
                f"_block_slices: unexpected spacer index {spacer_idx} in 19-col "
                "triple-block layout (expected 6 or 12) — ADR-001 fail-loud"
            )
    return []


def _is_header_row(row: list[str | None]) -> bool:
    """Return ``True`` if *row* is a column-header row (not a data row).

    Detects the repeated ``Unit | Valid GMUs | ...`` column-header rows that
    appear at the top of each pdfplumber table (after the section heading rows).
    Also detects Season Choice column-header rows.

    Strategy: a header row contains the string ``"Hunt Code"`` (or ``"Hunt"``
    with ``"Code"`` in the same cell after normalisation) in at least one cell.
    This is robust because no data value in the CPW tables looks like
    ``"Hunt Code"``.
    """
    for cell in row:
        if cell is None:
            continue
        stripped = cell.strip()
        if "Hunt Code" in stripped or "Hunt\nCode" in stripped:
            return True
    return False


def _is_heading_only_row(row: list[str | None]) -> bool:
    """Return ``True`` if the row is a section heading spanning all columns.

    CPW tables start with a merged-cell heading row like::

        ['Archery — Limited Licenses', None, None, ...]
        ['Season Dates: Sept. 2–30 (Unless otherwise noted)', None, None, ...]

    These rows have only ONE non-None cell (at column 0), and all other cells
    are ``None``.  They are not data rows and must be skipped.

    Guard: a single-cell row whose content matches ``_HUNT_CODE_RE`` is a
    genuine data row (lone hunt code), not a heading — return ``False`` so it
    is not incorrectly skipped.
    """
    non_none = [c for c in row if c is not None]
    if len(non_none) != 1:
        return False
    sole = non_none[0]
    # A cell that looks like a hunt code is a data row, not a heading.
    if isinstance(sole, str) and _HUNT_CODE_RE.match(sole.strip()):
        return False
    return True


def _get_cell(row: list[str | None], idx: int) -> str | None:
    """Return ``row[idx]`` if ``idx != _NO_COL`` and the index is in range.

    Returns ``None`` for ``_NO_COL``, out-of-range indices, and ``None``
    cells.  This is the safe indexed accessor used by ``_extract_block_row``.
    """
    if idx == _NO_COL:
        return None
    if idx < 0 or idx >= len(row):
        return None
    return row[idx]


def _extract_block_row(
    row: list[str | None],
    block: tuple[int, ...],
    header_window: "CpwSeasonWindow | None",
    method_group: str,
    residency_scope: str,
    page_ref: "PageReference",
    header_window_method: str | None = None,
) -> "CpwRowExtraction | None":
    """Extract one ``CpwRowExtraction`` from a single 6-col block slice.

    *block* is a 6-tuple ``(unit_idx, valid_gmus_idx, dates_idx, sex_idx,
    hunt_code_idx, list_idx)`` where any index == ``_NO_COL`` means that field
    is not present in this table variant.

    Returns ``None`` when the row has no usable hunt code AND no other
    meaningful content within the block's column range (empty-noise row).
    Rows with a malformed hunt code but other content ARE returned verbatim so
    nothing is silently dropped; the caller's debug-log handles intentional
    skips.

    Applies R1/R2/R3 normalisation via ``_normalize_cell`` to all cell values.
    Applies R4 whitespace collapse only to ``extras``.

    IMPORTANT: extras are scoped to cells WITHIN the block's column range only
    (between ``min(block)`` and ``max(block)`` inclusive), NOT across the
    entire row.  This prevents block A's extras from leaking block B's content
    in dual/triple-block tables.
    """
    unit_idx, valid_gmus_idx, dates_idx, sex_idx, hunt_code_idx, list_idx = block

    # Determine the contiguous range of this block.
    valid_indices = [i for i in block if i != _NO_COL]
    if valid_indices:
        block_min, block_max = min(valid_indices), max(valid_indices)
    else:
        block_min, block_max = 0, len(row) - 1

    raw_hunt = _get_cell(row, hunt_code_idx)
    hunt_code_norm = _normalize_cell(raw_hunt)

    # --- Determine extras (remaining text within this block's column range) ---
    # Scope: only columns between block_min and block_max, excluding the
    # columns already mapped to named fields.  This prevents right-block
    # content from leaking into left-block extras in dual/triple tables.
    mapped_indices = {i for i in block if i != _NO_COL}
    extra_parts: list[str] = []
    for ci in range(block_min, block_max + 1):
        if ci in mapped_indices:
            continue
        v = _normalize_cell(_get_cell(row, ci))
        if v is not None:
            extra_parts.append(v)
    extras_raw = " ".join(extra_parts) if extra_parts else None
    extras = _collapse_whitespace(extras_raw) if extras_raw else None

    # Skip orphan-fragment blocks: no hunt code, no extras, and no
    # *identifying* content. A date cell or a bare sex letter alone is NOT
    # identifying — pdfplumber routinely splits a multi-line Dates cell so its
    # second line lands on its own row carrying only a date (e.g. ``Dec. 15–31``)
    # with unit/valid_gmus/list all empty. Those are row-split artifacts, not
    # regulation rows, so the has-content probe deliberately excludes
    # ``dates_idx`` and ``sex_idx`` — only a hunt code, unit, valid_gmus, or
    # list value makes a hunt-code-less row worth preserving (verbatim, low
    # confidence). Rows with a present-but-malformed hunt code skip this guard
    # entirely (``hunt_code_norm is not None``) and are still emitted.
    if hunt_code_norm is None and extras is None:
        has_content = any(
            _normalize_cell(_get_cell(row, i)) is not None
            for i in (unit_idx, valid_gmus_idx, list_idx)
            if i != _NO_COL
        )
        if not has_content:
            _logger.debug("_extract_block_row: skipping orphan-fragment block: %r", block)
            return None

    hunt_code_str = hunt_code_norm or ""

    # Parse hunt code components.
    parsed = _parse_hunt_code(hunt_code_str) if hunt_code_str else None
    if parsed is not None:
        species_letter = parsed["species_letter"]
        sex_code = parsed["sex_code"]
        gmu_code = parsed["gmu_code"]
        season_code = parsed["season_code"]
        method_letter = parsed["method_letter"]
    else:
        species_letter = ""
        sex_code = ""
        gmu_code = ""
        season_code = ""
        method_letter = ""

    # Derive weapon_types from method_letter; fall back to method_group's letter.
    if method_letter:
        weapon_types = _weapon_types_for(method_letter)
    else:
        # Fall back: convert method_group → its canonical single letter
        _METHOD_GROUP_TO_LETTER = {"archery": "A", "muzzleloader": "M", "rifle": "R"}
        fallback_letter = _METHOD_GROUP_TO_LETTER.get(method_group, "")
        weapon_types = _weapon_types_for(fallback_letter)

    # Dates cell.
    raw_dates = _get_cell(row, dates_idx)
    # The header window (Rule R7) only applies to rows of the SAME method it
    # came from. A "Season Dates:" header set by an archery/muzzleloader
    # section must NOT bleed onto rifle rows on the same page (cubic P1-6):
    # the row's own method (from its hunt code) is authoritative. A legitimate
    # same-method header still applies (header_window_method matches, or is
    # None when provenance is unknown — then fall back to permissive behaviour).
    # The row's own method (from its hunt code) gates the header window; fall
    # back to the table-level method_group only when there is no method letter.
    # (The orchestrator re-derives the emitted ``method_group`` field per-row in
    # extract(); this local value is used only for the header-method match.)
    row_method = _method_group_for(method_letter) if method_letter else method_group
    header_method_ok = header_window_method is None or header_window_method == row_method
    # Use per-row Dates cell if present; otherwise the matching header_window.
    if raw_dates is not None and raw_dates.strip() and raw_dates.strip() != "-":
        window = _parse_season_window(raw_dates)
        season_windows = [window] if window is not None else []
    elif header_window is not None and header_method_ok:
        season_windows = [header_window]
    else:
        season_windows = []

    valid_gmus = _normalize_cell(_get_cell(row, valid_gmus_idx))

    # RFW / private-land column-shift recovery (cubic P1-5). Those tables use
    # ``Ranch/Units | Dates | Sex | Hunt Code | List`` (no separate Valid GMUs
    # column), so the standard 6-column map writes the per-row Dates value into
    # ``valid_gmus``. A date is NEVER a valid GMU list, so when ``valid_gmus``
    # is date-shaped, treat it as the misplaced per-row season date: parse it
    # into ``season_windows`` and null ``valid_gmus``. This wins over any
    # existing window because that window is a generic header fallback (the
    # real per-row date went into ``valid_gmus``) — the per-row date is more
    # specific. Recovers the date AND clears the corrupted field. Parse the RAW
    # cell so ``raw_text`` stays verbatim per ADR-008.
    if valid_gmus and _DATE_RANGE_RE.search(valid_gmus):
        recovered = _parse_season_window(_get_cell(row, valid_gmus_idx))
        if recovered is not None and recovered["start_date"] is not None:
            season_windows = [recovered]
            valid_gmus = None

    return CpwRowExtraction(
        hunt_code=hunt_code_str,
        species_letter=species_letter,
        sex_code=sex_code,
        gmu_code=gmu_code,
        season_code=season_code,
        method_letter=method_letter,
        unit=_normalize_cell(_get_cell(row, unit_idx)),
        valid_gmus=valid_gmus,
        season_windows=season_windows,
        list_value=_normalize_cell(_get_cell(row, list_idx)),
        apply_by=None,  # universally None for CPW V1 — no apply_by column
        quota=None,  # universally None for CPW V1 — no quota column
        quota_range=None,  # universally None for CPW V1 — no quota_range column
        weapon_types=weapon_types,
        method_group=method_group,
        residency_scope=residency_scope,
        extras=extras,
        extraction_confidence="",  # T6 fills this
        page_reference=page_ref,
    )


def _parse_season_choice_row(
    row: list[str | None],
    block: tuple[int, ...],
    page_ref: "PageReference",
    method_group: str,
    residency_scope: str,
) -> "CpwRowExtraction | None":
    """Extract a ``CpwRowExtraction`` from a Season Choice 8-col row.

    Season Choice tables have three date columns (Archery / Muzzleloader /
    Rifle) and no ``Valid GMUs`` column.  The hunt code determines the primary
    method via its method letter; the season_windows list carries one window
    per non-empty date column with the method injected into the raw_text.

    *block* is an 8-tuple:
    ``(unit_idx, valid_gmus_idx, archery_dates_idx, muzz_dates_idx,
    rifle_dates_idx, sex_idx, hunt_code_idx, list_idx)``
    """
    (
        unit_idx, valid_gmus_idx,
        archery_idx, muzz_idx, rifle_idx,
        sex_idx, hunt_code_idx, list_idx,
    ) = block

    raw_hunt = _get_cell(row, hunt_code_idx)
    hunt_code_norm = _normalize_cell(raw_hunt)

    # Skip orphan-fragment rows: no hunt code and no *identifying* content
    # (unit or list). Date columns are excluded for the same reason as
    # _extract_block_row — a stray date line with no hunt code or unit is a
    # pdfplumber row-split artifact, not a regulation row.
    if hunt_code_norm is None and all(
        _normalize_cell(_get_cell(row, i)) is None
        for i in (unit_idx, list_idx)
    ):
        _logger.debug("_parse_season_choice_row: skipping orphan-fragment row: %r", row)
        return None

    hunt_code_str = hunt_code_norm or ""
    parsed = _parse_hunt_code(hunt_code_str) if hunt_code_str else None
    if parsed is not None:
        species_letter = parsed["species_letter"]
        sex_code = parsed["sex_code"]
        gmu_code = parsed["gmu_code"]
        season_code = parsed["season_code"]
        method_letter = parsed["method_letter"]
    else:
        species_letter = sex_code = gmu_code = season_code = method_letter = ""

    # Determine method_group from hunt code method_letter, fall back to caller.
    if method_letter:
        derived_group = _method_group_for(method_letter) or method_group
    else:
        derived_group = method_group

    _METHOD_GROUP_TO_LETTER = {"archery": "A", "muzzleloader": "M", "rifle": "R"}
    fallback_letter = _METHOD_GROUP_TO_LETTER.get(derived_group, "")
    weapon_types = _weapon_types_for(method_letter or fallback_letter)

    # Build season windows: one per non-empty date column.
    season_windows: list[CpwSeasonWindow] = []
    for date_idx, label in [
        (archery_idx, "Archery"),
        (muzz_idx, "Muzzleloader"),
        (rifle_idx, "Rifle"),
    ]:
        raw = _get_cell(row, date_idx)
        if raw is None or not raw.strip() or raw.strip() == "-":
            continue
        win = _parse_season_window(raw)
        if win is not None:
            season_windows.append(win)

    # Extras: cells not in the mapped column set.
    mapped_indices = {
        i for i in (unit_idx, valid_gmus_idx, archery_idx, muzz_idx,
                    rifle_idx, sex_idx, hunt_code_idx, list_idx)
        if i != _NO_COL
    }
    extra_parts = [
        v for ci, cell in enumerate(row)
        if ci not in mapped_indices
        for v in (_normalize_cell(cell),)
        if v is not None
    ]
    extras_raw = " ".join(extra_parts) if extra_parts else None
    extras = _collapse_whitespace(extras_raw) if extras_raw else None

    return CpwRowExtraction(
        hunt_code=hunt_code_str,
        species_letter=species_letter,
        sex_code=sex_code,
        gmu_code=gmu_code,
        season_code=season_code,
        method_letter=method_letter,
        unit=_normalize_cell(_get_cell(row, unit_idx)),
        valid_gmus=_normalize_cell(_get_cell(row, valid_gmus_idx)),
        season_windows=season_windows,
        list_value=_normalize_cell(_get_cell(row, list_idx)),
        apply_by=None,
        quota=None,
        quota_range=None,
        weapon_types=weapon_types,
        method_group=derived_group,
        residency_scope=residency_scope,
        extras=extras,
        extraction_confidence="",  # T6 fills this
        page_reference=page_ref,
    )


def _parse_table_block(
    rows: list[list[str | None]],
    method_group: str,
    residency_scope: str,
    species_group: str,
    page_ref: "PageReference",
    header_window: "CpwSeasonWindow | None" = None,
    header_window_method: str | None = None,
) -> list["CpwRowExtraction"]:
    """Parse all regulation rows from a single pdfplumber-detected table.

    Given the raw rows of ONE pdfplumber table (any of the observed column
    counts), produces ``CpwRowExtraction`` records for all usable data rows.

    Parameters
    ----------
    rows:
        The raw list-of-lists returned by ``tbl.extract()`` for one table.
    method_group:
        The method block this table belongs to (``"archery"``,
        ``"muzzleloader"``, or ``"rifle"``).  Derived by the caller from the
        section heading above the table.
    residency_scope:
        One of ``"resident"``, ``"nonresident"``, or ``"both"``.  Set from
        the page/section heading context by the caller (Rule R12).  NOT a
        column in the table.
    species_group:
        The active species group (``"mule_deer"``, ``"whitetail"``,
        ``"elk"``, or ``"pronghorn"``).  Used only for logging; field values
        come from hunt-code parsing.
    page_ref:
        The ``PageReference`` for the page this table was found on.
    header_window:
        When the section heading carries an explicit season date (Rule R7 —
        e.g. ``'Season Dates: Sept. 2–30'``), this is the pre-parsed
        ``CpwSeasonWindow`` to attach to every row that has no per-row Dates
        cell.  ``None`` if no header date is available.

    Delivery model (from STEP 1 live probe 2026-06-09):
        pdfplumber delivers each CPW hunt-code page as 1–2 table objects.
        The primary table spans the full width (6–19 cols) and contains the
        section heading at row 0, optional boilerplate at row 1, the column
        header row, and all data rows.  A secondary 5-or-6-col single-block
        table appears on the same page when the page content overflows one
        block width; its rows start directly with the column headers.

        This function handles BOTH the primary multi-block table AND the
        secondary single-block table identically: it identifies the variant
        by column count, splits dual/triple blocks, and processes each block.

    Skip rules applied:
        * Section-heading-only rows (``_is_heading_only_row``) — merged cell
          spanning all columns.
        * Column-header rows (``_is_header_row``) — the ``Unit / Valid GMUs
          / Hunt Code / List`` row.
        * See-Unit cross-reference rows (``_is_see_unit_row``) — Rule R5.
        * Footnote rows (``_is_footnote_row``) — Rule R6.
        * Rows with no usable content — ``_extract_block_row`` returns
          ``None`` for these; a DEBUG message is emitted.
    """
    if not rows:
        return []

    ncols = len(rows[0])
    variant = _classify_table_variant(ncols)

    if variant == "unknown":
        _logger.warning(
            "_parse_table_block: unrecognised column count %d for %s on page %d — skipping table",
            ncols,
            species_group,
            page_ref.get("page_num_1based", 0),
        )
        return []

    # For the 19-col triple-block variant, locate the actual column-header row
    # (the row containing "Hunt Code") so _block_slices can detect the spacer
    # position.  The spacer sits at index 6 on some pages and index 12 on
    # others; passing the header row makes detection robust.
    col_header_row: list[str | None] | None = None
    if variant == "19col":
        for candidate in rows:
            if _is_header_row(candidate):
                col_header_row = candidate
                break

    blocks = _block_slices(variant, col_header_row)
    results: list[CpwRowExtraction] = []

    for raw_row in rows:
        # --- Rule R14: uniform character-doubling recovery (FIRST) ---
        # pdfplumber double-renders certain GMU-20-area pages so every glyph
        # (letter, digit, punctuation, space) is emitted exactly twice.
        # _looks_doubled_row gates on a single long uniformly-doubled cell
        # (≥ 10 stripped chars) as an unambiguous signal; _undouble_text
        # recovers each cell independently (the per-cell length guard leaves
        # any short or non-doubled cell untouched).  The recovered row is
        # re-assigned to raw_row so EVERY downstream check — INCLUDING the
        # structural skip filters below — sees the true source text.  This MUST
        # run before _is_heading_only_row / _is_header_row / _is_see_unit_row /
        # _is_footnote_row: on a doubled page those filters would otherwise see
        # garbled text and could (a) fail to recognise a doubled header row (so
        # it is parsed as data) or (b) misread a doubled single-cell data row
        # as a heading (so a real row is dropped).
        if _looks_doubled_row(raw_row):
            raw_row = [_undouble_text(c) for c in raw_row]
            _logger.debug(
                "_parse_table_block: R14 de-doubled row on page %d: %r",
                page_ref.get("page_num_1based", 0),
                raw_row,
            )

        # --- Skip structural / non-data rows (on the recovered text) ---
        if _is_heading_only_row(raw_row):
            continue
        if _is_header_row(raw_row):
            continue

        # --- Apply per-block extraction ---
        if variant == "8col":
            # Season Choice: single block with three date columns.
            if _is_see_unit_row(raw_row) or _is_footnote_row(raw_row):
                continue
            extracted = _parse_season_choice_row(
                raw_row, blocks[0], page_ref, method_group, residency_scope
            )
            if extracted is not None:
                results.append(extracted)
        else:
            # Standard / dual / triple block.
            for block in blocks:
                # Build the sub-row for this block (only the block's columns).
                # Use the full raw_row; _get_cell handles index mapping.
                # Skip and log See-Unit and footnote rows per-block.
                # (Check against the block's first non-_NO_COL cells.)
                block_cells = [_get_cell(raw_row, i) for i in block]
                sub_row = [_get_cell(raw_row, i) for i in range(len(raw_row))]

                # Check skip rules against the block slice specifically.
                # _is_see_unit_row and _is_footnote_row operate on a row;
                # pass the block slice so they check the correct cells.
                if _is_see_unit_row(block_cells):
                    _logger.debug(
                        "_parse_table_block: skipping see-unit block row: %r",
                        block_cells,
                    )
                    continue
                if _is_footnote_row(block_cells):
                    _logger.debug(
                        "_parse_table_block: skipping footnote block row: %r",
                        block_cells,
                    )
                    continue

                extracted = _extract_block_row(
                    sub_row,
                    block,
                    header_window,
                    method_group,
                    residency_scope,
                    page_ref,
                    header_window_method,
                )
                if extracted is not None:
                    results.append(extracted)

    return results


# ---------------------------------------------------------------------------
# T6: Confidence assignment
# ---------------------------------------------------------------------------


def _assign_row_confidence(row: "CpwRowExtraction", source: str = "table") -> str:
    """Assign an extraction confidence tier to a single CPW row per ADR-017.

    Returns one of the ``ConfidenceTier`` string values (``"high"``,
    ``"medium"``, or ``"low"``).  Mirrors ``extract_dea._assign_row_confidence``
    but uses CPW-specific field completeness criteria rather than DEA's
    season_coverage flags.

    Parameters
    ----------
    row:
        The ``CpwRowExtraction`` dict to evaluate.  Must be fully populated
        by T5 (all fields present, ``extraction_confidence`` may be ``""``).
    source:
        Accepted for signature parity and potential future use (e.g. if a
        caller wants to force MEDIUM for a prose-derived row).  The
        completeness rule below is authoritative — ``source`` does NOT by
        itself alter the tier.  The default ``"table"`` matches the only
        CPW V1 call site (per-row table extraction in T7).

    Confidence tiers:

    **LOW** — the hunt code did not parse (``species_letter == ""``) which
        means the row is structurally unidentifiable.  A WARNING is logged
        naming the raw ``hunt_code`` value and the page number so the UAT
        reviewer (T12) can audit every unparse without manually scanning the
        artifact.  Per ADR-017 §7 and the S03.11 FINALIZE decision: ``low > 0``
        is a data-shape signal, NOT a framework problem — the LOW tier exists
        precisely to surface these rows; do NOT alter the framework or exclude
        the tier.

    **HIGH** — all three conditions are met:

        1. The hunt code parsed cleanly (``species_letter != ""``).
        2. ``list_value`` is not ``None`` (the draw-mechanic indicator is
           present).
        3. At least one entry in ``season_windows`` has both ``start_date``
           and ``end_date`` non-``None`` (a fully resolved date window).

        Design note on condition 3: the tier keys on whether the dates
        *resolved*, not on whether they came from a per-row cell or a
        propagated section header (Rule R7).  A cleanly-parsed header window
        (e.g. the elk archery ``Season Dates: Sept. 2–30`` heading attached
        to every row in that block) satisfies the HIGH condition just as well
        as an inline Dates cell.  This avoids penalising an entire faithful
        category (elk archery) with uniform MEDIUM purely on provenance.
        The ``source`` parameter is the hook if a future caller wants to
        override this (e.g. force MEDIUM for a prose row), but the default
        completeness path is authoritative for CPW V1.

        This is a deliberate refinement of the plan's initial "header→MEDIUM"
        sketch; the rationale is recorded here so the T12 UAT reviewer sees
        it without digging through git history.

    **MEDIUM** — everything else where the hunt code did parse but something
        is incomplete or ambiguous:
        - No fully resolved season window (``season_windows`` is empty, or
          every entry has ``start_date`` or ``end_date`` as ``None`` — e.g.
          only ``raw_text`` was preserved because the dates cell was an OCR
          artifact or an unparseable format).
        - ``list_value`` is ``None`` (the draw-mechanic indicator is absent).
    """
    hunt_code = row["hunt_code"]
    page_num = row["page_reference"].get("page_num_1based", "?")

    # LOW: structurally unidentifiable row — hunt code did not parse.
    if row["species_letter"] == "":
        _logger.warning(
            "row %r (page %s) has unparseable hunt code — flagged LOW confidence",
            hunt_code,
            page_num,
        )
        return ConfidenceTier.LOW

    # Check for a fully resolved season window (start_date AND end_date both set).
    has_resolved_window = any(
        w["start_date"] is not None and w["end_date"] is not None
        for w in row["season_windows"]
    )

    # HIGH: parsed hunt code + list value present + at least one resolved window.
    if row["list_value"] is not None and has_resolved_window:
        return ConfidenceTier.HIGH

    # MEDIUM: parsed hunt code but something missing / ambiguous.
    return ConfidenceTier.MEDIUM


# ---------------------------------------------------------------------------
# T7: Orchestrator
# ---------------------------------------------------------------------------

# Regex to detect "Resident" vs "Nonresident" in a page/section heading.
# Used to derive residency_scope (Rule R12).
_RESIDENT_RE = re.compile(r"(?i)\bresident\b")
_NONRESIDENT_RE = re.compile(r"(?i)\bnonresident\b")

# Large sentinel for non-numeric GMU codes in _sort_key so they sort
# deterministically after all numeric GMU codes.
_NON_NUMERIC_GMU_SENTINEL = 999999


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


def _sort_key(section: CpwSectionExtraction) -> tuple[int, int, str, int, str, str]:
    """Return a deterministic sort key for a ``CpwSectionExtraction``.

    Ordering: (species_order, method_order, method_group, gmu_numeric, gmu_code,
    residency_scope)

    - ``species_order``: mule_deer=0, whitetail=1, elk=2, pronghorn=3.
    - ``method_order``: archery=0, muzzleloader=1, rifle=2; unknown=99.
    - ``method_group``: raw string tiebreaker for non-standard method names
      (e.g. ``"first_rifle"``, ``"second_rifle"``).
    - ``gmu_numeric``: ``int(gmu_code)`` when gmu_code is all digits;
      otherwise ``_NON_NUMERIC_GMU_SENTINEL`` (sorts non-numeric/empty
      codes after all numeric ones, deterministically).
    - ``gmu_code``: raw string tiebreaker for non-numeric codes.
    - ``residency_scope``: raw string tiebreaker; ``"both"`` < ``"nonresident"``
      < ``"resident"`` lexicographically, giving a stable total order when two
      sections share the same species/method/GMU but differ in residency.

    Rows within a section preserve PDF order (not re-sorted here).
    """
    species_order = {"mule_deer": 0, "whitetail": 1, "elk": 2, "pronghorn": 3}
    method_order = {"archery": 0, "muzzleloader": 1, "rifle": 2}

    sp = species_order.get(section["species_group"], 99)
    meth_num = method_order.get(section["method_group"], 99)

    gmu_code = section["gmu_code"]
    if gmu_code.isdigit():
        gmu_numeric = int(gmu_code)
    else:
        gmu_numeric = _NON_NUMERIC_GMU_SENTINEL

    return (sp, meth_num, section["method_group"], gmu_numeric, gmu_code, section["residency_scope"])


def _residency_scope_from_text(text: str) -> str:
    """Derive residency_scope from page/section heading text (Rule R12).

    Returns ``"resident"``, ``"nonresident"``, or ``"both"``.

    Detection logic:
    - "Nonresident" (case-insensitive) present  → ``"nonresident"``
      (checked first so "Resident & Nonresident" → ``"nonresident"`` is
      NOT the right call; instead "Resident & Nonresident" → ``"both"``
      because both words are present).
    - Both "Resident" AND "Nonresident" → ``"both"`` (e.g. elk archery
      page 52: ``'Archery — Limited Resident & Nonresident Licenses'``).
    - Only "Resident" present → ``"resident"``.
    - Neither → ``"both"`` (the default; most deer/pronghorn pages).

    Rule R12 locked by TestSectionAttribution::test_residency_scope.
    """
    has_resident = bool(_RESIDENT_RE.search(text))
    has_nonresident = bool(_NONRESIDENT_RE.search(text))
    if has_resident and has_nonresident:
        return "both"
    if has_nonresident:
        return "nonresident"
    if has_resident:
        return "resident"
    return "both"


def _verbatim_text_for_section(rows: list[CpwRowExtraction]) -> str:
    """Build a per-section verbatim text reconstruction from its rows.

    ADR-008 compliance: ``verbatim_text`` on ``CpwSectionExtraction`` is a
    faithful per-section reconstruction of that section's own source row
    cells — NOT the entire page text (which would duplicate one page's text
    across dozens of GMU sections and bloat the artifact).

    For each row, the verbatim source cells are joined with ``" | "``
    separators in this order:
        unit, valid_gmus, [season_windows[0].raw_text, ...], sex_code,
        hunt_code, list_value

    Rows are joined with ``"\\n"``.  ``None`` cells are emitted as empty
    strings so the structure is preserved (a consumer can split on ``" | "``
    and recover the column layout).  ``raw_text`` values in season windows
    are always verbatim (never normalised).

    This preserves the section's verbatim source faithfully without
    page-level duplication; the authoritative verbatim date text already
    lives in ``season_windows[].raw_text``.
    """
    lines: list[str] = []
    for row in rows:
        parts: list[str] = [
            row["unit"] or "",
            row["valid_gmus"] or "",
        ]
        for win in row["season_windows"]:
            parts.append(win["raw_text"] or "")
        parts.extend([
            row["sex_code"],
            row["hunt_code"],
            row["list_value"] or "",
        ])
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def extract(pdf_path: Path = _PDF_PATH) -> list[CpwSectionExtraction]:
    """Extract all per-GMU regulation rows from the CPW Big Game brochure.

    Reads the PDF at *pdf_path*, walks the deer (pp. 30–44), elk
    (pp. 45–62), and pronghorn (pp. 63–67) page ranges, and returns a
    sorted list of ``CpwSectionExtraction`` records.

    Structural notes (confirmed via live probe 2026-06-09):
    - Method headings appear in the **page text** (e.g. ``'Archery —
      Limited Licenses\\nSeason Dates: Sept. 2–30'``), not only in a
      table row.  Each page is scanned for heading lines before tables
      are processed.
    - ``'Limited Licenses — White-Tailed Deer Only'`` appears in page 44
      text; it switches ``is_whitetail`` for that page and all subsequent
      deer-range pages (Rule R11).
    - Resident/Nonresident context is derived from the page text heading
      (Rule R12).  Default is ``"both"`` when neither word is present.
    - The ``header_window`` (Rule R7) is extracted from the page text
      heading or from the first heading-only table row that contains a
      ``Season Dates: ...`` pattern.
    - Pages 31, 43, 45, 46, 63 are map/intro pages; they are skipped by
      ``_is_map_page_text`` (zero tables AND short/garbled text) or
      because all tables have 0 rows.

    Section grouping keyed by ``(species_group, method_group, gmu_code, residency_scope)``:
    - ``species_group`` is derived per-row via
      ``_species_group_for(row.species_letter, is_whitetail)``.
    - ``method_group`` is derived per-row from the row's ``method_letter``
      (via ``_method_group_for``); falls back to the current page-level
      ``current_method_group`` when the hunt code did not parse.
    - ``gmu_code`` comes from the parsed hunt code; empty for unparseable
      rows (they still group by ``""``, preserving every row).

    ``verbatim_text`` is a per-section reconstruction (see
    ``_verbatim_text_for_section``); it preserves verbatim source cells
    without bloating the artifact with full-page text duplicates.

    ``extracted_at`` carries the ``fetched_at`` ISO timestamp from the
    PDF manifest (mirrors MT ``DeaSectionExtraction``'s provenance
    convention; no wall-clock calls).

    Fail-loud cases (ADR-001):
    - PDF not found → ``PdfExtractionError`` from ``open_pdf``.
    - Manifest not found / invalid → ``PdfExtractionError`` from
      ``_load_extracted_at_from_manifest``.
    - Unrecognised species letter in a parsed hunt code →
      ``PdfExtractionError`` from ``_species_group_for``.
    """
    extracted_at = _load_extracted_at_from_manifest(pdf_path)

    # sections_map: (species_group, method_group, gmu_code, residency_scope) →
    #   (first_page_ref, accumulated rows)
    # Keyed by all four discriminants so resident-only and nonresident-only rows
    # for the same GMU/method are never conflated into one section.
    sections_map: dict[
        tuple[str, str, str, str],
        tuple[PageReference, list[CpwRowExtraction]],
    ] = {}

    species_ranges: list[tuple[tuple[int, int], str]] = [
        (_DEER_PAGES, "mule_deer"),
        (_ELK_PAGES, "elk"),
        (_PRONGHORN_PAGES, "pronghorn"),
    ]

    with open_pdf(pdf_path) as pdf:
        for page_range, default_species in species_ranges:
            # Reset whitetail flag and context at the start of each species range.
            is_whitetail = False
            current_method_group: str = ""
            current_header_window: CpwSeasonWindow | None = None
            # The method the current header window belongs to — a header date
            # set by an archery/muzzleloader section must not apply to rifle
            # rows (cubic P1-6). None = unknown provenance (permissive).
            current_header_window_method: str | None = None
            current_residency_scope: str = "both"

            for page_num_1based, page in iter_pages(pdf, page_range[0], page_range[1]):
                page_ref = PageReference(
                    pdf_filename=_PDF_FILENAME,
                    page_num_1based=page_num_1based,
                    bbox=None,
                    extracted_at=extracted_at,
                )
                page_text = extract_text(page)
                tables = extract_tables(page)
                table_count = len(tables)

                # Rule R10: skip map / photo pages.
                if _is_map_page_text(page_text, table_count):
                    # INFO (not DEBUG) so the set of skipped pages is observable
                    # in normal runs — a regression that drops a real page would
                    # otherwise be invisible at the default log level.
                    _logger.info(
                        "page %d: no tables + no hunt codes + short text — "
                        "skipping as map/photo page",
                        page_num_1based,
                    )
                    continue

                # --- Scan page text for heading context ---
                # Method headings, whitetail boundary, residency scope, and
                # season-date header all appear in the page text before the
                # tables on the same page.  Walk each line of the page text
                # to update running context.
                if page_text:
                    for line in page_text.splitlines():
                        line_stripped = line.strip()
                        if not line_stripped:
                            continue

                        # Rule R11: detect whitetail boundary heading.
                        if _is_whitetail_heading(line_stripped):
                            is_whitetail = True
                            _logger.debug(
                                "page %d: whitetail boundary heading detected",
                                page_num_1based,
                            )

                        # Method heading detection: update current_method_group
                        # and current_header_window for this page.
                        detected_method = _method_group_from_heading(line_stripped)
                        if detected_method is not None:
                            current_method_group = detected_method
                            # Also try to extract a header date from this line
                            # (Rule R7: e.g. 'Archery — Limited Resident &
                            # Nonresident Licenses — Season Dates: Sept. 2–30').
                            hw = _parse_header_date(line_stripped)
                            if hw is not None:
                                current_header_window = hw
                                current_header_window_method = detected_method
                            else:
                                # No inline date on this heading line.
                                # Clear the header window so a stale archery
                                # Season Dates does NOT bleed into the next
                                # method block (e.g. rifle).  A standalone
                                # "Season Dates: …" line on this same page will
                                # re-set it via the R7 fallback below.
                                current_header_window = None
                                current_header_window_method = None

                        # Rule R7 fallback: a standalone "Season Dates: ..."
                        # line sets the header window without a method word.
                        # Attribute it to the current method section.
                        sd_win = _parse_header_date(line_stripped)
                        if sd_win is not None and detected_method is None:
                            current_header_window = sd_win
                            current_header_window_method = current_method_group

                    # Rule R12: derive residency_scope from the full page text.
                    current_residency_scope = _residency_scope_from_text(page_text)

                # Reset header_window at the start of each new page so a
                # prior page's header doesn't bleed into a different method's
                # page (only keep it when still on the same method section).
                # In practice each page carries its own heading, but for
                # pages that inherit the method from the previous page (e.g.
                # continuation rifle pages without a re-stated heading) we
                # do NOT reset — the current_header_window stays.
                # The above line-scan already updates it when a new heading
                # is found; no explicit reset needed here.

                # --- Process each table on this page ---
                for tbl in tables:
                    tbl_rows: list[list[str | None]] = tbl["rows"]
                    if not tbl_rows:
                        continue

                    # Detect a header window from the first heading-only row
                    # in this table (e.g. 'Season Dates: Sept. 12–20' as the
                    # single-cell row 0 of the muzzleloader table on p66).
                    # This supplements the page-text scan above.
                    for raw_row in tbl_rows[:2]:
                        if _is_heading_only_row(raw_row):
                            cell_text = raw_row[0]
                            if cell_text:
                                hw = _parse_header_date(cell_text)
                                # Also update method group from table heading.
                                dm = _method_group_from_heading(cell_text)
                                if dm is not None:
                                    current_method_group = dm
                                if hw is not None:
                                    current_header_window = hw
                                    # Attribute to this heading's method word, or
                                    # — when the heading has none (e.g. a bare
                                    # "Season dates: …" row) — to the table's own
                                    # method derived from its hunt codes. Using
                                    # the table's method (not the page-advanced
                                    # current_method_group) prevents a
                                    # muzzleloader header on a multi-section page
                                    # from being mis-tagged as rifle (cubic P1-6).
                                    current_header_window_method = (
                                        dm
                                        if dm is not None
                                        else _first_table_method(tbl_rows)
                                        or current_method_group
                                    )

                    # Parse all rows from this table.
                    # species_group is determined per-row from the parsed hunt
                    # code (species_letter + is_whitetail flag); we pass the
                    # default_species as a logging hint only.
                    extracted_rows = _parse_table_block(
                        tbl_rows,
                        method_group=current_method_group or "rifle",
                        residency_scope=current_residency_scope,
                        species_group=default_species,
                        page_ref=page_ref,
                        header_window=current_header_window,
                        header_window_method=current_header_window_method,
                    )

                    # Assign confidence and group into sections.
                    for row in extracted_rows:
                        row["extraction_confidence"] = _assign_row_confidence(row)

                        # FIX 2: skip map-OCR / unparseable garbage rows.
                        # _is_garbage_row returns True for LOW rows with no
                        # hunt-code-shaped fragment and no salvageable list value
                        # (pure map-page OCR leakage).  WARNING-logged per ADR-001.
                        if _is_garbage_row(row):
                            _logger.warning(
                                "skipping garbage row (map-OCR / unparseable) on page %d: "
                                "hunt_code=%r",
                                row["page_reference"].get("page_num_1based", 0),
                                (row["hunt_code"] or "")[:60],
                            )
                            continue

                        # Derive species_group per-row from the hunt code.
                        species_letter = row["species_letter"]
                        if species_letter:
                            row_species = _species_group_for(species_letter, is_whitetail)
                        else:
                            # Unparseable hunt code: use the current context
                            # species based on the page range.
                            row_species = "whitetail" if is_whitetail else default_species

                        # Derive method_group per-row from method_letter.
                        row_method_letter = row["method_letter"]
                        if row_method_letter:
                            row_method = _method_group_for(row_method_letter) or current_method_group or "rifle"
                        else:
                            row_method = current_method_group or "rifle"

                        # Keep the row's method_group field in sync.
                        row["method_group"] = row_method

                        gmu_code = row["gmu_code"]
                        row_residency = row["residency_scope"]
                        key = (row_species, row_method, gmu_code, row_residency)

                        if key not in sections_map:
                            sections_map[key] = (page_ref, [])
                        sections_map[key][1].append(row)

    # --- Build CpwSectionExtraction list ---
    sections: list[CpwSectionExtraction] = []
    for (species_group, method_group, gmu_code, residency_scope), (first_page_ref, rows) in sections_map.items():
        verbatim = _verbatim_text_for_section(rows)
        sections.append(
            CpwSectionExtraction(
                source_id=_SOURCE_ID,
                species_group=species_group,
                method_group=method_group,
                gmu_code=gmu_code,
                residency_scope=residency_scope,
                license_year=_LICENSE_YEAR,
                extracted_at=extracted_at,
                page_reference=first_page_ref,
                verbatim_text=verbatim,
                rows=rows,
            )
        )

    # Deterministic sort (no set-iteration order in output).
    sections.sort(key=_sort_key)

    # --- Summary log ---
    total_rows = sum(len(s["rows"]) for s in sections)
    conf_counts: dict[str, int] = defaultdict(int)
    for s in sections:
        for r in s["rows"]:
            conf_counts[r["extraction_confidence"]] += 1
    _logger.info(
        "extract: %d sections, %d rows — confidence: high=%d medium=%d low=%d",
        len(sections),
        total_rows,
        conf_counts.get("high", 0),
        conf_counts.get("medium", 0),
        conf_counts.get("low", 0),
    )

    return sections


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the CPW Big Game brochure extractor.

    Usage:
        ingestion/.venv/bin/python ingestion/states/colorado/extract_big_game.py
        ingestion/.venv/bin/python ingestion/states/colorado/extract_big_game.py \\
            --pdf /path/to/brochure.pdf --out /tmp/big-game-2026.json
    """
    parser = argparse.ArgumentParser(
        description="Extract per-GMU regulations from the CPW Big Game brochure",
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
        help="Output JSON path (default: ingestion/states/colorado/extracted/big-game-2026.json)",
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
        sections = extract(args.pdf)
    except PdfExtractionError as e:
        _logger.error("extraction failed: %s", e)
        return 2

    # Run-summary: log section/row counts + confidence distribution.
    total_rows = sum(len(s["rows"]) for s in sections)
    _logger.info("extracted %d sections, %d rows total", len(sections), total_rows)

    # ConfidenceTier is a str-subclass enum, so its instances ARE strings and
    # hash/compare equal to their plain-string values ("high", "medium", "low").
    # Using the field directly as Counter keys means .get("high", 0) resolves
    # correctly via string equality.  (str() would give the repr
    # "ConfidenceTier.HIGH", which would NOT match; .value would be correct but
    # mypy sees extraction_confidence as plain str in the TypedDict.)
    dist: Counter[str] = Counter(
        r["extraction_confidence"] for s in sections for r in s["rows"]
    )
    _logger.info(
        "confidence distribution: high=%d medium=%d low=%d",
        dist.get("high", 0),
        dist.get("medium", 0),
        dist.get("low", 0),
    )

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
