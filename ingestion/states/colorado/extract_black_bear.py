"""
Extract per-GMU Black Bear regulation rows from the CPW Big Game brochure
into deterministic JSON artifacts for downstream ingestion (S06.6–S06.9).

The extractor walks bear pages (PDF pp. 72–77), locates hunt-code tables via
pdfplumber ``find_tables()``, and emits one ``CpwBearSectionExtraction`` per
(GMU × method × residency) block.  Three artifacts are produced:

# Artifact shape decision (T3)

The base artifact (``black-bear-2026-base.json``) is a **flat list-of-records**
where each element carries a ``record_type`` discriminator key:

  ``"section"``               — one ``CpwBearSectionExtraction`` record (hunt-code rows)
  ``"reporting_obligation"``  — one ``BearReportingObligationCandidate`` (mandatory inspection prose)
  ``"statewide_rule"``        — one ``BearStatewideRuleCandidate`` (List A/B/C explanation + season summary)

Rationale: ``write_extraction_artifact`` takes a list; downstream S06.6 filters
by ``record_type == "section"`` and S06.9 filters by ``record_type ==
"reporting_obligation"``.  A flat list avoids an envelope wrapper that would
require special-casing in ``write_extraction_artifact``.  The ``record_type``
key is always the first key in each dict for easy visual scanning.

# OTC license_kind discriminator

``CpwBearRowExtraction.license_kind`` (new in T3) disambiguates limited-draw
vs. over-the-counter rows so S06.6/S06.7 can assign the correct
``license_tag.kind``:

  ``"limited_draw"``     — rows from limited tables (pp. 73–75); List A, B, or C
  ``"add_on_otc"``       — rows from Add-On OTC tables (p. 76); require a matching
                          deer/elk license of the same method
  ``"over_the_counter"`` — rows from standalone OTC tables (p. 77); no prerequisite
                          license beyond the bear license itself
  ``"private_land_otc"`` — rows from Private-Land-Only OTC tables (p. 77, Table 2/3)
  ``"plains_otc"``       — rows from Rifle Plains OTC (p. 77, Table 4)

  ``ingestion/states/colorado/extracted/black-bear-2026-base.json``
      Pass 1: flat list-of-records from the brochure (``annual_regulations``
      source only).  Each element has ``record_type`` ∈ {``"section"``,
      ``"reporting_obligation"``, ``"statewide_rule"``}.

  ``ingestion/states/colorado/extracted/corrections-2026-02-19.json``
      Pass 2: per-license-code ``CorrectionOperation`` dicts from the
      correction PDF (ADR-019 doc-type-precedence merge).

  ``ingestion/states/colorado/extracted/black-bear-2026.json``
      Pass 3: fully merged artifact (correction rows applied to base per
      ADR-019 §"Decision" — ``correction`` always supersedes
      ``annual_regulations`` for the same structured field; S06.6–S06.9
      consume only this artifact).

ADR references:
  ADR-001  Authority preserved, not replaced — fail loud; no invented values.
  ADR-005  Python ingestion / TypeScript serving language split.
  ADR-008  Verbatim regulation text — ``verbatim_text`` retains pdfplumber's
           word-grouped output without additional normalization.  Only the
           structured ``rows`` payload uses the cleanup regexes below.
  ADR-017  Confidence calibration + parent-inheritance rule — per-row
           ``extraction_confidence`` is assigned here; section-level MIN
           aggregation is S06.6's job.
  ADR-019  Doc-type precedence in multi-source regulation merge — the
           correction PDF wins field-by-field over the brochure for the same
           ``license_code``.

# Three-pass correction merge (T4)

Three artifacts are produced by the full pipeline (T5 drives the writes):

  ``black-bear-2026-base.json``  (Pass 1 — base brochure extraction, annual_regulations source)
  ``corrections-2026-02-19.json`` (Pass 2 — operations list from the correction PDF)
  ``black-bear-2026.json``       (Pass 3 — merged result; S06.6–S06.9 consume this)

The three-pass merge follows ADR-019's doc-type-precedence rule:

  Stage 1 — per-cell arbitration:
    For each ``(target_license_code, target_field)`` targeted by one or more
    ``CorrectionOperation``s, select the winning op by MAX ``publication_date``.
    On equal-date ties raise ``CorrectionConflictError`` (a semantic conflict;
    not a same-field different-field situation).

  Stage 2 — apply value:
    Update the matched base section row's field to the winning op's ``new_value``.

  Stage 3 — row-level provenance + confidence demotion (ADR-017 §4):
    Fire ``demote_one_tier`` EXACTLY ONCE per touched section row regardless of
    how many fields were corrected.  Firing it inside the per-cell loop would
    over-demote a row with N correction operations.  Set ``applied_correction=True``
    and ``supersedes`` to the superseded brochure source id.

# Inert-for-bear finding (confirmed 2026-06-13, correction PDF p.1 + p.2)

The 2026-02-19 correction PDF is 2 pages:
  page 1 — moose hunt-code corrections
  page 2 — an ELK muzzleloader correction (``E-M-…`` hunt codes, brochure p. 44)

Neither page contains any bear hunt code (``B-…``).  Consequently
``_extract_correction`` yields ``operations == []`` for this extractor, and
``_merge_with_corrections`` returns the base records byte-identical (zero
confidence demotions, zero ``applied_correction=True`` rows).

This is the **inert-confirmation pathway** mandated by spec lines 308/341 of
``E06-colorado-regulation-text-ingestion.md``: the correction is parsed in FULL
and the absence of bear operations is EVIDENCED (logged at INFO with the actual
page content summary), not asserted.  Do NOT short-circuit by early-returning
without opening the PDF.

# Probe notes (confirmed 2026-06-13)

Bear section map (CPW Big Game brochure, 84 pages total):
  Content-page offset = +10 (PDF page = content page + 10).

  PDF p. 72 (content p. 62):
    - "Bear Season Dates" 2-column summary table (dates only, no hunt codes)
    - "List A, B & C" explanation prose (archery / muzzleloader / rifle eligibility)

  PDF p. 73 (content p. 63):
    - "Mandatory Bear Inspections & Seals" prose
    - **Archery — Limited Licenses** hunt-code table
      Layout: pdfplumber delivers this as a primary 8-col dual block plus
      two overflow 4-col single-block tables on the same page.
      Each block is 4-col: ``Unit | Valid GMUs | Hunt Code | List``
      (No Dates column — archery season dates are uniform, stated in the
       banner row "Season dates: Sept. 2–30 — Sex: Either"; attached via
       Rule R7 analog using ``_parse_header_date``.)

  PDF p. 74 (content p. 64):
    - **Muzzleloader — Limited Licenses** hunt-code table
      Layout: pdfplumber delivers a primary 8-col dual block plus two
      overflow 4-col single blocks.  Same 4-col structure as archery:
      ``Unit | Valid GMUs | Hunt Code | List``  (no Dates column).
      Banner: "Season dates: Sept. 12–20 — Sex: Either".
    - **Rifle — Limited Licenses** start
      Layout: primary 10-col dual block plus one overflow 5-col single block.
      Each block is 5-col: ``Unit | Valid GMUs | Dates | Hunt Code | List``
      Banner: "Season Dates: See hunt code table below. — Sex: Either"
      (no uniform date; each row has its own ``Dates`` cell).

  PDF p. 75 (content p. 65):
    - **Rifle — Limited** continued (same 10-col + 5-col layout as p. 74).

  PDF p. 76 (content p. 66):
    - **Add-On Over-the-Counter** section (Archery / Muzzleloader / Rifle)
      Layout: no ``Unit`` column:
        ``Valid GMUs | Hunt Code | List``  (3-col single or 6-col dual)
      (GMU list is a long comma-separated string covering all OTC-eligible units)
    - Rifle OTC is 3-col single-block with ``Valid GMU | Hunt Code | List``.

  PDF p. 77 (content p. 67):
    - Standalone **OTC** sub-sections (Rifle, Rifle Private-Land-Only, Rifle Plains)
      Layout: ``Valid GMUs | Dates | Hunt Code | List``  (4-col) and 8-col duals.

Hunt-code grammar (confirmed 2026-06-13):
  ``B-{sex}-{gmu}-{season}-{method}``
  Examples: ``B-E-050-O1-M``  (Bear, Either sex, GMU 050, Option 1, Muzzleloader)
            ``B-E-001-O1-A``  (Bear, Either sex, GMU 001, Option 1, Archery)
            ``B-E-001-O1-R``  (Bear, Either sex, GMU 001, Option 1, Rifle)
  Species letter: ``B`` (Black Bear)
  Sex codes: ``E`` (either); all V1 bear rows use ``E`` (confirmed live probe
             2026-06-13 — no ``M`` or other code observed in pages 73–77).
  Method letters: ``A`` (archery), ``M`` (muzzleloader), ``R`` (rifle)

R14 CHARACTER-DOUBLING STATUS (confirmed live probe 2026-06-13):
  Bear hunt codes arrive CLEAN — ``B-E-001-O1-A``, NOT doubled like
  ``BB--EE--000011--OO11--AA``.  The pdfplumber character-doubling artefact
  documented in ``known-pitfalls.md`` (the "R14" rule in ``extract_big_game.py``)
  does NOT affect any bear page (PDF pp. 72–77).  Consequently,
  ``_undouble_text`` and ``_looks_doubled_row`` are NOT ported to this module.
  If a future brochure year introduces doubling on bear pages, add them then.

Page running-headers are scrambled rotated sidebars (e.g. "HuBnet aPrlan") —
ignore them; they contain no regulation data.

NOTE on species_group:
  ``species_group = 'black_bear'`` is the artifact value used throughout this
  extractor.  Downstream S06.6 maps it to DB ``species_group = 'bear'``
  (the schema.JurisdictionBinding value).  Do NOT write ``'bear'`` here.

# Cleanup rules (applied only to structured ``rows`` cells, never to
# ``verbatim_text``):

  Rule R1: bare ``-`` → None
      regex: ``^\\s*-\\s*$``
      scope: all value cells (``apply_by``, ``extras``, and any nullable
             string field)
      rationale: CPW tables use a literal hyphen as the absence sentinel,
                 matching the FWP DEA convention — absent data must be
                 explicit null per ADR-001.
      locked by: TestNormalizeBearCell::test_dash_sentinel_nulled

  Rule R2: None / empty / whitespace-only → None
      regex: n/a (``not text or not text.strip()``)
      scope: all cells
      rationale: pdfplumber returns ``None`` for merged-cell continuations;
                 empty strings are ambiguous (ADR-001: absent data is null).
      locked by: TestNormalizeBearCell::test_whitespace_nulled

  Rule R3: hyphenated line-break rejoin (``"word-\\nword"`` → ``"word-word"``)
      regex: ``(?<=[a-zA-Z0-9])-\\n(?=[a-zA-Z0-9])``
      scope: all cells (applied before whitespace collapse)
      rationale: pdfplumber introduces soft-hyphen line breaks in multi-line
                 cells; only genuine hyphenated words are rejoined (date-range
                 hyphens like ``Oct. 1-23`` are untouched because their
                 neighbours are not both alphanumeric across the newline).
      locked by: TestNormalizeBearCell::test_hyphen_rejoin

  Rule R4: extras/notes whitespace collapse
      regex: ``re.sub(r"\\s+", " ", text).strip()``
      scope: notes/extras cells ONLY (applied after R1–R3)
      rationale: multi-line footnote text in CPW tables embeds ``\\n`` between
                 sentences; the natural reading is a single space-separated
                 paragraph.
      locked by: TestBearRejoinAndCollapse::test_collapse_whitespace_multi_space,
                 TestBearRejoinAndCollapse::test_collapse_whitespace_newlines

  Rule R5: ``■`` footnote rows skipped
      regex: ``^\\s*■``
      scope: first cell of row
      rationale: footnote rows use a leading ``■`` bullet and are not
                 regulation rows.
      locked by: TestBearRowFilters::test_footnote_bullet_skipped

  Rule R6: strip the CPW ``■`` OTC-marker glyph from structured cells
      regex: ``\\s*■\\s*``
      scope: all structured cells via _normalize_bear_cell (NOT raw_text)
      rationale: ``■`` (U+25A0) is a presentation marker meaning "OTC add-on
                 available"; it is not part of a unit/GMU value.
      locked by: TestNormalizeBearCell::test_strips_otc_bullet

  Rule R7: season-window inheritance from banner row for archery/muzzleloader
      regex: ``(?i)Season\\s+Dates\\s*:\\s*<start>\\s*[–-]\\s*<end>``
             (via ``_parse_header_date``)
      scope: heading-only rows in archery and muzzleloader tables only
      rationale: archery and muzzleloader bear tables have NO per-row Dates
                 column; the season dates appear once in the merged-cell banner
                 row (e.g. "Season dates: Sept. 2–30 — Sex: Either").  All
                 data rows in that table inherit this window.  Rifle rows are
                 EXCLUDED (they have their own per-row Dates cell; a banner
                 saying "See hunt code table below" carries no parseable date).
      locked by: TestBearParseHeaderDate::test_archery_banner_parsed,
                 TestBearParseHeaderDate::test_rifle_banner_no_date

  Rule R8: hunt-code parse via ``_HUNT_CODE_RE``
      regex: ``^([A-Z])-([A-Z])-(\\d{{3,4}})-([A-Z0-9]+)-([A-Z])$``
      scope: ``Hunt Code`` column cells
      rationale: CPW hunt codes follow a fixed 5-component grammar; a successful
                 parse populates all five component fields; failure degrades
                 confidence to LOW per ADR-017.
      locked by: TestBearParseHuntCode::test_valid_bear_code_parsed,
                 TestBearParseHuntCode::test_non_bear_species_letter_logged

  Rule R9: single-code multi-line Hunt Code cell normalisation
      scope: Hunt Code column cells that contain a newline but hold only ONE
             full hunt code (e.g. a wrapped GMU list or a spurious trailing
             newline introduced by pdfplumber).  The first non-empty line is
             used as the canonical ``hunt_code`` value; any remaining lines are
             logged at DEBUG and discarded.  Multi-code cells (two or more full
             hunt codes separated by ``\\n``) are handled by Rule R17, not R9.
      locked by: TestBearExtractBlockRow::test_single_code_multiline_uses_first

  Rule R17: fused multi-row split (``"B-E-058-O1-M\\nB-E-059-O1-M"`` → 2 rows)
      scope: Hunt Code column — confirmed live on PDF p. 74 muzzleloader table:
             cell ``'B-E-058-O1-M\\nB-E-059-O1-M'`` carries TWO full hunt codes
             because pdfplumber merged adjacent PDF rows when the inter-row
             ruling was missing.  ``_split_fused_block_row`` detects N≥2 full
             codes via ``_HUNT_CODE_EMBEDDED_RE.findall`` and splits every
             present block cell on ``\\n``, producing N synthetic rows.  Fails
             loud (``PdfExtractionError``) when a present, non-empty block cell
             does not split into exactly N parts — misalignment would corrupt
             the split.
      locked by: TestFusedRowSplit::test_two_code_fused_row_splits_to_two_rows,
                 TestFusedRowSplit::test_misaligned_cell_raises

  Rule R10: "see unit N" cross-reference rows skipped
      regex: ``(?i)^\\s*see\\s+unit\\s+\\d+``
      scope: any cell in the row (matches on Valid GMUs, Unit, or any cell)
      rationale: these rows reference regulations in another unit; they carry
                 no independent regulation data and must not produce rows.
      locked by: TestBearRowFilters::test_see_unit_row_skipped

  Rule R11: note/annotation rows skipped
      scope: rows where Valid GMUs cell contains ``"Note:"`` prose (e.g.
             "Note: No hunting access to GMU 211.") — these annotate a prior
             unit row and are not regulation rows themselves.
      locked by: TestBearRowFilters::test_note_annotation_row_skipped

  Rule R12: hunt-code cell containing ``" +"`` suffix stripped
      scope: Hunt Code column cells (confirmed live on p. 74/75 cells like
             ``'B-E-851-O1-M +'`` and ``'B-E-851-O1-R +'``).  The trailing
             ``" +"`` is a cross-reference marker, not part of the code.
      locked by: TestBearParseHuntCode::test_plus_suffix_stripped

  Rule R13: OTC multi-window row consolidation (Rifle OTC, p. 77)
      scope: Standalone OTC Rifle tables on p. 77 only.
      rationale: pdfplumber delivers each season-date period as a separate
                 table row (e.g. ``"Oct. 14–18"``, ``"Oct. 24–Nov. 1"``,
                 ``"Nov. 7–15"``, ``"Nov. 18–22"`` as four consecutive rows
                 sharing the same hunt code).  The hunt-code cell is populated
                 in the first row; continuation rows carry ``None`` in the
                 hunt-code column.  ``_extract_otc_rows`` accumulates
                 continuation-row date windows and attaches them all to the
                 primary hunt-code row.
      locked by: TestBearOtcExtraction::test_rifle_otc_multi_window_consolidated

  Rule R14: Add-On OTC prerequisite note captured in ``extras``
      scope: Add-On OTC tables (p. 76) only.
      rationale: the banner row for each Add-On OTC sub-table carries a
                 prerequisite note ("You must hold an archery deer or elk
                 license …") that is not a data field but is regulation-
                 relevant context.  It is stored in the section-level
                 ``notes`` field of ``CpwBearSectionExtraction`` so S06.7
                 can attach it to the license-tag ``extras`` or
                 ``additional_rules`` field.
      locked by: TestBearSectionAssembly::test_add_on_otc_note_captured

  Rule R15: confidence assignment (``_assign_bear_row_confidence``)
      scope: every ``CpwBearRowExtraction`` after OTC and limited extraction.
      rationale: see ``_assign_bear_row_confidence`` docstring (mirrors
                 ``extract_big_game._assign_row_confidence``).
      locked by: TestBearConfidenceAssignment::test_high_confidence_row,
                 TestBearConfidenceAssignment::test_medium_no_window,
                 TestBearConfidenceAssignment::test_low_unparsed_hunt_code

  Rule R16: hunt-code embedded in prose — unanchored search fallback
      regex: ``[A-Z]-[A-Z]-\\d{{3,4}}-[A-Z0-9]+-[A-Z]`` (via
             ``_HUNT_CODE_EMBEDDED_RE``, ``re.search`` on the cell)
      scope: ``Hunt Code`` column cells that fail the anchored
             ``_HUNT_CODE_RE`` match (e.g. ``"Sales agents only: B-E-087-U6-R"``)
      rationale: CPW's Rifle — Plains OTC table prefixes the hunt-code cell
                 with prose (``"Sales agents only: …"``).  The anchored regex
                 fails on the prefix; an unanchored search recovers the
                 embedded full code.  The surrounding prose prefix is stored
                 verbatim in ``extras`` (ADR-008).  A row recovered this way
                 is treated as having a valid hunt code for confidence purposes.
      locked by: TestBearEmbeddedHuntCode::test_plains_otc_code_recovered,
                 TestBearEmbeddedHuntCode::test_prose_prefix_in_extras
"""

# State-specific module — must NOT import from ingestion.states.<other_state>
# or from ingestion.states.colorado.<other_extractor>.
# Cross-state / cross-extractor imports violate ADR-005 isolation.
# The state-agnostic guard test enforces this via AST walk.

from __future__ import annotations

import argparse
import copy
import datetime
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Final, TypedDict, cast

import yaml

from ingestion.lib.pdf import (
    ConfidenceTier,
    PageReference,
    PdfExtractionError,
    demote_one_tier,
    extract_text,
    iter_pages,
    open_pdf,
    write_extraction_artifact,
)

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path / file constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Main brochure PDF (same file as big-game extractor — bear is in the same PDF)
_PDF_FILENAME: Final[str] = "co-cpw-big-game-2026-brochure-2026-03-04.pdf"
_PDF_PATH: Final[Path] = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "colorado"
    / "fixtures"
    / _PDF_FILENAME
)

# Correction PDF
_CORRECTION_FILENAME: Final[str] = (
    "co-cpw-big-game-2026-correction-2026-02-19-2026-02-19.pdf"
)
_CORRECTION_PATH: Final[Path] = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "colorado"
    / "fixtures"
    / _CORRECTION_FILENAME
)

# Output artifact paths
_BASE_OUTPUT_PATH: Final[Path] = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "colorado"
    / "extracted"
    / "black-bear-2026-base.json"
)
_CORRECTIONS_OUTPUT_PATH: Final[Path] = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "colorado"
    / "extracted"
    / "corrections-2026-02-19.json"
)
_MERGED_OUTPUT_PATH: Final[Path] = (
    _REPO_ROOT
    / "ingestion"
    / "states"
    / "colorado"
    / "extracted"
    / "black-bear-2026.json"
)

# sources.yaml path for the CO state adapter
_SOURCES_YAML: Final[Path] = (
    _REPO_ROOT / "ingestion" / "states" / "colorado" / "sources.yaml"
)

# ---------------------------------------------------------------------------
# Metadata constants
# ---------------------------------------------------------------------------

_SOURCE_ID: Final[str] = "co-cpw-big-game-2026-brochure"
_CORRECTION_SOURCE_ID: Final[str] = "co-cpw-big-game-2026-correction-2026-02-19"
_LICENSE_YEAR: Final[int] = 2026
# Artifact species_group value — downstream S06.6 maps this to DB 'bear'.
# Do NOT write 'bear' here; see probe notes above.
_SPECIES_GROUP: Final[str] = "black_bear"

# Bear page range (1-based inclusive, per iter_pages convention).
# Confirmed via live probe of the PDF on 2026-06-13.
# Content-page offset = +10 (PDF page = content page + 10).
#   Bear: content pp. 62–67  →  PDF pages 72–77
_BEAR_PAGES: Final[tuple[int, int]] = (72, 77)

# ---------------------------------------------------------------------------
# Document-type allow-list (ADR-019 §Decision item 5 guard)
# ---------------------------------------------------------------------------

_VALID_DOCUMENT_TYPES: Final[frozenset[str]] = frozenset(
    {"annual_regulations", "correction"}
)

# ---------------------------------------------------------------------------
# Cleanup-utility compiled regex constants
# ---------------------------------------------------------------------------

# Rule R3: rejoin hyphenated line-breaks when both neighbours are alphanumeric.
_HYPHEN_LINEBREAK_RE = re.compile(r"(?<=[a-zA-Z0-9])-\n(?=[a-zA-Z0-9])")

# Rule R6 (OTC-marker glyph strip): ■ (U+25A0 BLACK SQUARE) in structured cells.
_OTC_BULLET: Final[str] = "■"  # U+25A0 BLACK SQUARE
_OTC_BULLET_RE = re.compile(r"\s*■\s*")  # Rule R6

# Hunt-code fragment regex — unanchored, used for garbage-row detection.
# ``\d{3}`` intentionally matches both 3- and 4-digit GMU codes (first 3 digits
# of a 4-digit code always match, so every valid code is detected).
_HUNT_CODE_FRAGMENT_RE = re.compile(r"[A-Z]-[A-Z]-\d{3}")

# Full hunt-code parse regex — ``B-{sex}-{gmu}-{season}-{method}``.
# Five capture groups: (species_letter, sex_code, gmu_code, season_code,
# method_letter).  GMU codes are 3–4 digits.
# Examples confirmed 2026-06-13: B-E-050-O1-M, B-E-001-O1-A, B-E-001-O1-R
_HUNT_CODE_RE = re.compile(r"^([A-Z])-([A-Z])-(\d{3,4})-([A-Z0-9]+)-([A-Z])$")

# Rule R16: full hunt-code embedded in prose — unanchored search fallback.
# Matches a complete 5-component CPW hunt code as a substring of a cell
# whose prose prefix defeats the anchored ``_HUNT_CODE_RE`` (e.g.
# ``"Sales agents only: B-E-087-U6-R"``).  The match group is the extracted
# code; surrounding prose is captured into ``extras`` per ADR-008.
# Unlike ``_HUNT_CODE_FRAGMENT_RE`` (which only matches the first 3 components
# for garbage-row detection), this regex requires all 5 components so a valid
# extractable code is present.
_HUNT_CODE_EMBEDDED_RE = re.compile(r"([A-Z]-[A-Z]-\d{3,4}-[A-Z0-9]+-[A-Z])")

# "See Unit NNN" cross-reference rows in the Valid-GMUs cell.
_SEE_UNIT_RE = re.compile(r"(?i)^\s*see\s+unit\s+\d+")

# ---------------------------------------------------------------------------
# TypedDicts — output JSON contract for S06.6 / S06.7
# (order: CpwSeasonWindow → CpwBearRowExtraction → CpwBearSectionExtraction
#  → CorrectionOperation → SourceCitationDict)
# ---------------------------------------------------------------------------


class CpwSeasonWindow(TypedDict):
    """A single season's date window for a CPW Black Bear hunt-code row.

    ``start_date`` is the begin date exactly as printed in the brochure
    (e.g. ``"Aug. 31"``).  ``end_date`` is the end date; same-month ranges
    where CPW drops the redundant month on the end token have the month
    inferred from ``start_date`` so the field is an unambiguous standalone
    date.  ``raw_text`` carries the full unparsed cell text verbatim per
    ADR-008 and is AUTHORITATIVE for what the brochure printed.

    Both ``start_date`` and ``end_date`` may be ``None`` when the range
    cannot be parsed; ``raw_text`` is always populated when the window is
    present.
    """

    start_date: str | None
    end_date: str | None
    raw_text: str | None


class CpwBearRowExtraction(TypedDict):
    """One hunt-code row from a per-GMU CPW Black Bear regulation table.

    ``hunt_code`` is the raw string from the ``Hunt Code`` column
    (e.g. ``"B-E-050-O1-M"``).  The component fields ``species_letter``,
    ``sex_code``, ``gmu_code``, ``season_code``, and ``method_letter`` are
    derived by parsing the hunt code via ``_HUNT_CODE_RE``.  All five are
    ``""`` when the hunt code cannot be parsed; ``hunt_code`` is always the
    verbatim cell text per ADR-008.

    ``unit`` carries the ``Unit`` column verbatim (normalized via R1/R2/R3),
    or ``None`` for OTC sections that have no ``Unit`` column.
    ``valid_gmus`` carries the ``Valid GMUs`` column verbatim (normalized).

    ``list_value`` carries the ``List`` column value: ``"A"``, ``"B"``,
    ``"C"``, ``"OTC"``, or ``None``.  This is the draw-mechanic indicator
    for downstream S06.8.

    NOTE on apply_by / quota / quota_range:
        A scan of all table headers across PDF pages 72–77 (bear section)
        found NO ``Quota``, ``Apply By``, or ``Apply By Date`` column in any
        bear hunt-code table (confirmed 2026-06-13).  CPW encodes draw
        mechanics in the ``List`` column and in the hunt code itself.
        Consequently ``apply_by``, ``quota``, and ``quota_range`` are
        universally ``None`` for all V1 CPW bear rows.  If a future year's
        brochure adds these columns, this TypedDict must be extended and the
        None assumption removed.

    ``residency_scope`` is set from section/page context (``"resident"``,
    ``"nonresident"``, or ``"both"``).  It is NOT derived from a column —
    CPW bear tables do not print residency in the row data.

    ``license_kind`` discriminates limited-draw vs OTC for S06.6/S06.7:
      ``"limited_draw"``     — rows from pp. 73–75 limited tables
      ``"add_on_otc"``       — rows from p. 76 Add-On OTC tables
      ``"over_the_counter"`` — rows from p. 77 standalone OTC tables
      ``"private_land_otc"`` — rows from p. 77 Private-Land-Only OTC tables
      ``"plains_otc"``       — rows from p. 77 Rifle Plains OTC table

    ``extraction_confidence`` is a ``ConfidenceTier`` string value
    (``"high"`` | ``"medium"`` | ``"low"``) assigned by the confidence
    assignment step; set to ``""`` as a placeholder in the scaffold.
    """

    hunt_code: str
    species_letter: str  # from hunt code; "" if unparseable
    sex_code: str  # from hunt code; "" if unparseable
    gmu_code: str  # from hunt code; "" if unparseable
    season_code: str  # from hunt code; "" if unparseable
    method_letter: str  # from hunt code; "" if unparseable
    unit: str | None  # "Unit" column verbatim (normalized); None for OTC sections
    valid_gmus: str | None  # "Valid GMUs" column verbatim (normalized)
    season_windows: list[CpwSeasonWindow]
    list_value: str | None  # "List" column: "A"/"B"/"C"/"OTC"/None
    apply_by: str | None  # universally None for CPW bear V1 (no apply_by column)
    quota: int | None  # universally None for CPW bear V1 (no quota column)
    quota_range: str | None  # universally None for CPW bear V1 (no quota_range column)
    weapon_types: list[str]
    method_group: str  # "archery" | "muzzleloader" | "rifle"
    residency_scope: str  # "resident" | "nonresident" | "both" — from section context
    license_kind: str  # "limited_draw"|"add_on_otc"|"over_the_counter"|"private_land_otc"|"plains_otc"
    extras: str | None  # leftover/notes text, whitespace-collapsed (R4)
    extraction_confidence: str  # ConfidenceTier value; "" placeholder until assigned
    page_reference: PageReference


class CpwBearSectionExtraction(TypedDict):
    """All extracted rows for one GMU × method × residency block (bear).

    Each section represents a unique combination of
    ``(species_group, method_group, gmu_code, residency_scope)``.

    ``verbatim_text`` is a per-section reconstruction of that section's own
    source row cells — NOT the entire page text.  For each row in the section,
    the verbatim source cells (``unit``, ``valid_gmus``, each
    ``season_windows[].raw_text``, ``hunt_code``, ``list_value``) are joined
    with ``" | "`` separators, and rows are joined with ``"\\n"``.  ADR-008
    is preserved: the authoritative verbatim date text lives in
    ``season_windows[].raw_text`` (always the unmodified PDF cell).

    ``extracted_at`` carries the ISO timestamp from the PDF manifest's
    ``fetched_at`` field — artifact-level provenance without re-introducing
    wall-clock non-determinism.

    ``license_kind`` mirrors the per-row discriminator — all rows in a
    section share the same ``license_kind`` (sections are keyed by
    ``(method_group, gmu_code, residency_scope, license_kind)``).

    ``notes`` carries section-level prerequisite text from OTC banner rows
    (Rule R14).  For Add-On OTC sections this is the
    "You must hold an archery deer or elk license …" constraint string.
    ``None`` for limited and non-add-on OTC sections.
    """

    source_id: str
    species_group: str  # "black_bear" (maps to DB 'bear' in S06.6)
    method_group: str  # "archery" | "muzzleloader" | "rifle"
    gmu_code: str
    residency_scope: str  # "resident" | "nonresident" | "both"
    license_kind: str  # same discriminator as CpwBearRowExtraction.license_kind
    license_year: int
    extracted_at: str  # ISO timestamp from PDF manifest fetched_at
    page_reference: PageReference
    verbatim_text: str
    notes: str | None  # OTC prerequisite note (Rule R14); None for limited sections
    rows: list[CpwBearRowExtraction]


class CorrectionOperation(TypedDict):
    """One field-level correction derived from the correction PDF.

    ``target_license_code`` identifies which base row is being corrected.
    ``target_field`` names the ``CpwBearRowExtraction`` field being updated.
    ``old_value`` is what the base brochure printed (may be ``None`` if the
    correction is additive).  ``new_value`` is the corrected value.
    ``source_id`` and ``publication_date`` anchor the correction to the
    correction PDF for provenance.
    """

    target_license_code: str
    target_field: str
    old_value: str | None
    new_value: str | None
    source_id: str
    publication_date: str


class SourceCitationDict(TypedDict, total=False):
    """Loose-typed citation dict from sources.yaml; matches schema.SourceCitation."""

    id: str
    agency: str
    title: str
    url: str
    publication_date: str
    document_type: str
    supersedes: str | None
    page_reference: str | None


class BearReportingObligationCandidate(TypedDict):
    """A reporting-obligation candidate extracted from bear prose pages.

    Mirrors MT ``extract_black_bear.ReportingObligationCandidate`` but
    adapted for CO's inspection + sealing obligation (not harvest-report).

    ``kind_hint`` is a S06.9 routing hint (not schema-validated here):
      ``"mandatory_inspection"`` — present-head-and-hide-within-5-days rule
                                    (CO's primary post-harvest obligation)

    ``region_scope`` for CO is always ``"STATEWIDE"`` in V1 — the Mandatory
    Bear Inspections & Seals rule applies to all CO bear hunters regardless
    of GMU.

    ``verbatim_rule`` carries the pdfplumber-extracted prose verbatim per
    ADR-008.  ``extraction_confidence`` is ``"high"`` when the verbatim rule
    was cleanly extracted from a well-bounded prose block.
    """

    record_type: str  # always "reporting_obligation"
    region_scope: str  # "STATEWIDE" for CO V1
    kind_hint: str  # "mandatory_inspection"
    deadline_hint: str  # "5 working days" (post-harvest inspection window)
    verbatim_rule: str
    page_reference: PageReference
    source_id: str
    source_publication_date: str
    extraction_confidence: str  # ConfidenceTier value string


class BearStatewideRuleCandidate(TypedDict):
    """A statewide-rule candidate extracted from bear prose pages.

    Carries the List A/B/C explanation and the Bear Season Dates summary
    from PDF p. 72 as statewide context for S06.9's ``regulation_record.
    additional_rules`` population.

    ``rule_hint`` is a S06.9 routing hint:
      ``"list_abc_explanation"`` — the "Get More Than One Bear License"
                                    List A/B/C eligibility prose (p. 72).
      ``"season_dates_summary"`` — the Bear Season Dates table summary (p. 72).

    ``verbatim_text`` carries the prose verbatim per ADR-008.
    """

    record_type: str  # always "statewide_rule"
    rule_hint: str  # "list_abc_explanation" | "season_dates_summary"
    verbatim_text: str
    page_reference: PageReference
    source_id: str
    source_publication_date: str
    extraction_confidence: str  # ConfidenceTier value string


# ---------------------------------------------------------------------------
# T2: Cleanup utility pure helpers
# (byte-identical behaviour to extract_big_game.py — reimplemented inline
#  per ADR-005; do NOT import from extract_big_game.py)
# ---------------------------------------------------------------------------


def _normalize_bear_cell(text: str | None) -> str | None:
    """Return a cleaned cell value, or ``None`` for absent/empty input.

    Cleanup order (strip → R2 → R1 → R3 → R6):

    1. **strip** — strip leading/trailing whitespace first (implicit pre-step,
       not a numbered Cleanup rule).
    2. **R2** — empty or whitespace-only string → ``None``.
    3. **R1** — bare ``"-"`` sentinel → ``None``.
    4. **R3** — rejoin hyphenated line-breaks (alphanumeric neighbours only).
    5. **R6** — strip CPW ``■`` OTC-marker glyph (U+25A0) from structured
       cells.  A cell whose only content is ``■`` returns ``None``.

    ``"OTC"`` is preserved verbatim (R1 only nulls a bare ``"-"``; ``"OTC"``
    never matches that pattern — Rule R9 analog).

    Does NOT collapse internal whitespace globally (that is Rule R4, applied
    only to notes/extras cells via ``_collapse_whitespace``).

    # Rule R1 / Rule R2 / Rule R3 / Rule R6
    """
    # strip: leading/trailing whitespace (implicit pre-step, not a numbered rule)
    if text is None:
        return None
    stripped = text.strip()
    # R2: empty or whitespace-only → None
    if not stripped:
        return None
    # R1: bare dash sentinel → None
    if stripped == "-":
        return None
    # R3: rejoin hyphenated line-breaks (alphanumeric neighbours)
    rejoined = _HYPHEN_LINEBREAK_RE.sub("-", stripped)
    # R6: strip CPW OTC-marker glyph (■, U+25A0) from structured cells.
    if _OTC_BULLET in rejoined:
        rejoined = _OTC_BULLET_RE.sub(" ", rejoined).strip()
        if not rejoined:
            return None  # Rule R6: ■-only cell → None
    return rejoined


def _rejoin_hyphenated_linebreaks(text: str) -> str:
    """Rejoin soft hyphens at line-breaks when both neighbours are alphanumeric.

    Operates on a non-``None`` string; caller is responsible for the None guard.

    # Rule R3
    """
    return _HYPHEN_LINEBREAK_RE.sub("-", text)


def _collapse_whitespace(text: str) -> str:
    """Collapse all whitespace runs to a single space and strip ends.

    Intended for **notes / extras cells ONLY** (Rule R4).  Do NOT apply this
    globally — preservation of single newlines is required elsewhere for cell
    parsing.

    Operates on a non-``None`` string; caller is responsible for the None guard.

    # Rule R4
    """
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# T2: Date parsing constants (reimplemented inline from extract_big_game.py
# per ADR-005 self-contained-extractor convention; do NOT import from there)
# ---------------------------------------------------------------------------

# Month abbreviation canonical set — CPW uses "Mmm." (dot-terminated).
# Confirmed from live bear PDF probe 2026-06-13.
_BEAR_MONTH_ABBREVS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Oct|Nov|Dec)\."

# Core date-range regex — matches "Mmm. D – Mmm. D" or "Mmm. D – D" (same-month).
# Built from real bear brochure dates: "Sept. 2–30", "Oct. 14–18", "Oct. 24–Nov. 1".
_BEAR_DATE_RANGE_RE = re.compile(
    r"(?P<start>"
    + _BEAR_MONTH_ABBREVS
    + r"\s+\d{1,2})"
    + r"\s*[–\-]\s*"
    + r"(?P<end>"
    + r"(?:"
    + _BEAR_MONTH_ABBREVS
    + r"\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}(?:,\s*\d{4})?)"
    + r")"
)

# Season-dates header regex (Rule R7) — matches banner rows like:
#   "Season dates: Sept. 2–30 — Sex: Either"
#   "Season Dates: Sept. 12–20 — Sex: Either"
# (case-insensitive; "See hunt code table below" does NOT match — no date.)
_BEAR_HEADER_DATE_RE = re.compile(
    r"(?i)Season\s+[Dd]ates\s*:\s*"
    + r"(?P<start>"
    + _BEAR_MONTH_ABBREVS
    + r"\s+\d{1,2})"
    + r"\s*[–\-]\s*"
    + r"(?P<end>"
    + r"(?:"
    + _BEAR_MONTH_ABBREVS
    + r"\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}(?:,\s*\d{4})?)"
    + r")"
)

# Method-section heading regex — matches:
#   "Archery — Limited Licenses"
#   "Muzzleloader — Limited Licenses"
#   "Rifle — Limited Licenses"
#   "Archery — Add-On Over-the-Counter Licenses"
# Returns method word for _method_group_from_bear_heading.
_BEAR_METHOD_HEADING_RE = re.compile(
    r"(?i)^\s*(?P<method>Archery|Muzzleloader|Rifle)\b"
)

# Sentinel: column index not present in this variant.
_BEAR_NO_COL = -1

# ---------------------------------------------------------------------------
# T2: Hunt-code parsing
# ---------------------------------------------------------------------------

# Method-letter → method group name (bear subset of CPW method letters).
# Bear V1 uses only A / M / R.  No Season Choice (X) in bear tables.
_BEAR_METHOD_GROUP_BY_LETTER: dict[str, str] = {
    "A": "archery",
    "M": "muzzleloader",
    "R": "rifle",
}


def _parse_hunt_code(code: str) -> dict[str, str] | None:
    """Parse a CPW bear hunt code into its five component fields.

    Matches *code* (stripped, ``" +"`` suffix removed per Rule R12) against
    ``_HUNT_CODE_RE``.  Returns a dict with keys ``"species_letter"``,
    ``"sex_code"``, ``"gmu_code"``, ``"season_code"``, and ``"method_letter"``
    when the code conforms to the CPW format ``B-{Sex}-{GMU}-{Season}-{Method}``.

    For bear extraction, the expected species letter is ``"B"``.  A non-``"B"``
    species letter is allowed through (the dict is returned) — the caller
    (``_extract_bear_block_row``) logs a WARNING and the row is still emitted
    so nothing is silently dropped; ADR-017 confidence degrades to LOW for
    unrecognised hunt codes.

    Returns ``None`` on parse failure (code does not match ``_HUNT_CODE_RE``).
    Does NOT raise.

    # Rule R8, Rule R12
    """
    # Rule R12: strip trailing " +" cross-reference marker before parsing.
    cleaned = code.strip()
    if cleaned.endswith(" +"):
        cleaned = cleaned[:-2].strip()
    m = _HUNT_CODE_RE.match(cleaned)
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
    """Return the bear method group name for *method_letter*, or ``None``.

    Looks up *method_letter* in ``_BEAR_METHOD_GROUP_BY_LETTER``.  Returns
    ``None`` for any unrecognised letter — callers log a WARNING and fall back
    to the table-level method group.  Does NOT raise.

    Known mappings::

        "A" → "archery"
        "M" → "muzzleloader"
        "R" → "rifle"
    """
    return _BEAR_METHOD_GROUP_BY_LETTER.get(method_letter)


def _weapon_types_for(method_letter: str) -> list[str]:
    """Derive the ``weapon_types`` list for a CPW bear method letter.

    Returns a list of ``WeaponType`` literal strings::

        "A" → ["archery"]
        "M" → ["muzzleloader"]
        "R" → ["any_legal_weapon"]

    ``"R"`` maps to ``"any_legal_weapon"`` (CPW rifle seasons are unrestricted
    general-weapon seasons, matching the schema's ``"any_legal_weapon"`` value
    — same convention as ``extract_big_game.py``).

    Returns ``[]`` for an unknown letter.  Does NOT raise.
    """
    _mapping: dict[str, list[str]] = {
        "A": ["archery"],
        "M": ["muzzleloader"],
        "R": ["any_legal_weapon"],
    }
    return _mapping.get(method_letter, [])


# ---------------------------------------------------------------------------
# T2: Season-window parsing (Rule R7)
# ---------------------------------------------------------------------------


def _bear_inherit_end_month(start: str, end: str) -> str:
    """Disambiguate a same-month end token by inheriting the start's month.

    CPW drops the redundant month on a same-month range's end token, so
    "Sept. 2–30" yields a bare-numeric end "30".  This prepends the start's
    month abbreviation so ``end_date`` is an unambiguous standalone date
    ("Sept. 30").  Cross-month ends ("Nov. 1") already carry their own month
    and are returned unchanged.

    Private — used only by ``_parse_bear_date_range`` and
    ``_parse_bear_header_date``.
    """
    if end and end[0].isdigit():
        start_month = start.split(maxsplit=1)[0]
        return f"{start_month} {end}"
    return end


def _parse_bear_date_range(text: str) -> tuple[str | None, str | None]:
    """Extract ``(start_date, end_date)`` from a CPW bear date-range string.

    Normalises whitespace around the separator (handles newlines before/after
    the en-dash), then matches via ``_BEAR_DATE_RANGE_RE``.  Returns
    ``(start, end)`` or ``(None, None)`` when no range can be parsed.

    Called by ``_parse_bear_season_window`` and ``_parse_bear_header_date``.
    """
    normalised = re.sub(r"\s*\n\s*", " ", text)
    m = _BEAR_DATE_RANGE_RE.search(normalised)
    if m is None:
        return None, None
    return m.group("start"), _bear_inherit_end_month(m.group("start"), m.group("end"))


def _parse_bear_season_window(raw: str | None) -> CpwSeasonWindow | None:
    """Parse a CPW bear ``Dates`` column cell into a ``CpwSeasonWindow``.

    Returns ``None`` when *raw* is ``None`` or empty/whitespace-only (R2).
    Returns a ``CpwSeasonWindow`` with ``raw_text`` always set (ADR-008) and
    ``start_date``/``end_date`` from the parsed range (or ``None`` when
    unparseable).

    Handles all observed real-PDF formats from bear rifle tables (p. 74–75):
      - ``"Sept. 2–30"``             — same-month en-dash range
      - ``"Oct. 14–18"``             — same-month
      - ``"Oct. 24–Nov. 1"``         — cross-month
      - ``"Oct. 14–18\\nOct. 24–Nov. 1\\nNov. 7–15\\nNov. 18–22"``
                                     — multi-range: first range is primary

    Per the S03.3 UAT D1 lesson, per-row windows are load-bearing — this
    function parses ONE cell and returns ONE window (the first parseable range).

    # Rule R7 (rifle per-row Dates cell)
    """
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip().lstrip("■").strip()
    start, end = _parse_bear_date_range(cleaned)
    return CpwSeasonWindow(
        start_date=start,
        end_date=end,
        raw_text=raw,  # always verbatim per ADR-008 — use original, not cleaned
    )


def _parse_bear_header_date(header_text: str) -> CpwSeasonWindow | None:
    """Extract a season-date window from a CPW bear section-heading string.

    Rule R7: archery and muzzleloader bear tables state the season date once
    in the merged-cell banner row (e.g. "Season dates: Sept. 2–30 — Sex:
    Either").  All data rows in that table inherit this window when they have
    no per-row Dates cell.

    Confirmed banner formats from live PDF probe 2026-06-13:
      ``"Season dates: Sept. 2–30 — Sex: Either"``   (archery, p. 73)
      ``"Season dates: Sept. 12–20 — Sex: Either"``  (muzzleloader, p. 74)

    ``"Season Dates: See hunt code table below. — Sex: Either"`` (rifle, p. 74)
    does NOT match (no parseable date) — returns ``None``.

    Returns a ``CpwSeasonWindow`` with ``raw_text`` = full *header_text*
    (ADR-008 — the entire heading is the source) or ``None`` when no date is
    found in the heading.

    # Rule R7
    """
    m = _BEAR_HEADER_DATE_RE.search(header_text)
    if m is None:
        return None
    return CpwSeasonWindow(
        start_date=m.group("start"),
        end_date=_bear_inherit_end_month(m.group("start"), m.group("end")),
        raw_text=header_text,  # full heading is the source per ADR-008
    )


def _method_group_from_bear_heading(text: str | None) -> str | None:
    """Detect a CPW bear method-section heading and return the method group.

    Matches headings starting with "Archery", "Muzzleloader", or "Rifle"
    (case-insensitive).  Returns the canonical method group name or ``None``
    when *text* does not start with a recognised method keyword.
    """
    if not text:
        return None
    m = _BEAR_METHOD_HEADING_RE.match(text)
    if m is None:
        return None
    return m.group("method").lower()  # "archery" | "muzzleloader" | "rifle"


# ---------------------------------------------------------------------------
# T2: Table-block classification and column-index machinery
# ---------------------------------------------------------------------------
#
# Bear-specific column layout (confirmed live probe 2026-06-13):
#
#   8-col  — dual block, archery/muzzleloader (NO Dates):
#              Unit | Valid GMUs | Hunt Code | List  ×2
#              Left block: (0, 1, 2, 3), Right block: (4, 5, 6, 7)
#              (no Sex column — bear tables differ from deer/elk/pronghorn)
#
#   10-col — dual block, rifle (WITH per-row Dates):
#              Unit | Valid GMUs | Dates | Hunt Code | List  ×2
#              Left block: (0, 1, 2, 3, 4), Right block: (5, 6, 7, 8, 9)
#
#   4-col  — single block, archery/muzzleloader overflow (NO Dates):
#              Unit | Valid GMUs | Hunt Code | List
#              Single block: (0, 1, 2, 3)
#
#   5-col  — single block, rifle overflow (WITH per-row Dates):
#              Unit | Valid GMUs | Dates | Hunt Code | List
#              Single block: (0, 1, 2, 3, 4)
#
#   6-col  — dual block, OTC add-on (NO Unit column):
#              Valid GMUs | Hunt Code | List  ×2
#              Left block: (0, 1, 2), Right block: (3, 4, 5)
#
#   3-col  — single block, OTC (NO Unit column):
#              Valid GMUs | Hunt Code | List  OR
#              Valid GMU  | Hunt Code | List
#              Single block: (0, 1, 2)
#
#   4-col (OTC with Dates) — OTC Rifle / Private-Land-Only OTC:
#              Valid GMUs | Dates | Hunt Code | List
#
#   8-col (OTC Rifle dual) — OTC Rifle dual block with Dates:
#              Valid GMUs | Dates | Hunt Code | List  ×2
#
# This module handles only the LIMITED rows from pages 73–75 in T2.
# OTC tables on pp. 76–77 are handled in T3 (OTC extraction).
# ---------------------------------------------------------------------------


def _bear_classify_table_variant(ncols: int) -> str:
    """Return a short label identifying the bear table variant by column count.

    Bear-specific column layout (confirmed live probe 2026-06-13):

    Returns one of:
      ``"bear_8col"``  — dual block, archery/muzzleloader (no Dates)
      ``"bear_10col"`` — dual block, rifle (with per-row Dates)
      ``"bear_4col"``  — single block, archery/muzzleloader overflow (no Dates)
      ``"bear_5col"``  — single block, rifle overflow (with per-row Dates)
      ``"bear_6col"``  — dual block, OTC add-on (no Unit column)
      ``"bear_3col"``  — single block, OTC (no Unit column)
      ``"bear_4col_otc_dates"`` — OTC single block with Dates column
      ``"bear_8col_otc_dates"`` — OTC dual block with Dates column
      ``"unknown"``    — not recognised; caller logs WARNING and skips

    The 4-col ambiguity (limited no-Dates vs OTC with-Dates) is resolved by
    the caller: a 4-col table on pages 73–74 is always a limited block; on
    pages 76–77 it is always an OTC block with Dates.  The variant string is
    used as a routing key, not to fully encode the ambiguity; callers that
    have page context use it directly.
    """
    _MAP: dict[int, str] = {
        3: "bear_3col",
        4: "bear_4col",
        5: "bear_5col",
        6: "bear_6col",
        8: "bear_8col",
        10: "bear_10col",
    }
    return _MAP.get(ncols, "unknown")


def _bear_block_slices(variant: str) -> list[tuple[int, ...]]:
    """Return column-index tuples for each block within a bear table row.

    Each returned tuple encodes the column indices for one block:

    For limited tables (``"bear_8col"``, ``"bear_10col"``,
    ``"bear_4col"``, ``"bear_5col"``):
      ``(unit_idx, valid_gmus_idx, dates_idx, hunt_code_idx, list_idx)``
      ``_BEAR_NO_COL`` == -1 means the field is absent in this variant.

    For OTC tables (``"bear_6col"``, ``"bear_3col"``,
    ``"bear_4col_otc_dates"``, ``"bear_8col_otc_dates"``):
      ``(_BEAR_NO_COL, valid_gmus_idx, dates_idx, hunt_code_idx, list_idx)``
      (unit is always absent in OTC tables)

    Returns ``[]`` for ``"unknown"``.
    """
    # Bear limited (no Dates): (unit, valid_gmus, dates, hunt_code, list_col)
    #   8-col dual: left block indices 0-3, right block 4-7
    #   4-col single: indices 0-3
    _BEAR_4_NO_DATES = (0, 1, _BEAR_NO_COL, 2, 3)
    _BEAR_4_NO_DATES_RIGHT = (4, 5, _BEAR_NO_COL, 6, 7)

    # Bear limited with Dates: (unit, valid_gmus, dates, hunt_code, list_col)
    #   10-col dual: left block 0-4, right block 5-9
    #   5-col single: indices 0-4
    _BEAR_5_DATES = (0, 1, 2, 3, 4)
    _BEAR_5_DATES_RIGHT = (5, 6, 7, 8, 9)

    # OTC single (no Unit, no Dates): (_BEAR_NO_COL, valid_gmus, dates, hunt_code, list_col)
    _BEAR_OTC_3 = (_BEAR_NO_COL, 0, _BEAR_NO_COL, 1, 2)
    # OTC dual (no Unit, no Dates): left 0-2, right 3-5
    _BEAR_OTC_6_LEFT = (_BEAR_NO_COL, 0, _BEAR_NO_COL, 1, 2)
    _BEAR_OTC_6_RIGHT = (_BEAR_NO_COL, 3, _BEAR_NO_COL, 4, 5)
    # OTC with Dates single 4-col: (no Unit, valid_gmus=0, dates=1, hunt_code=2, list=3)
    _BEAR_OTC_4_DATES = (_BEAR_NO_COL, 0, 1, 2, 3)
    # OTC with Dates dual 8-col: left 0-3, right 4-7
    _BEAR_OTC_8_DATES_LEFT = (_BEAR_NO_COL, 0, 1, 2, 3)
    _BEAR_OTC_8_DATES_RIGHT = (_BEAR_NO_COL, 4, 5, 6, 7)

    _routing: dict[str, list[tuple[int, ...]]] = {
        "bear_8col": [_BEAR_4_NO_DATES, _BEAR_4_NO_DATES_RIGHT],
        "bear_10col": [_BEAR_5_DATES, _BEAR_5_DATES_RIGHT],
        "bear_4col": [_BEAR_4_NO_DATES],
        "bear_5col": [_BEAR_5_DATES],
        "bear_6col": [_BEAR_OTC_6_LEFT, _BEAR_OTC_6_RIGHT],
        "bear_3col": [_BEAR_OTC_3],
        "bear_4col_otc_dates": [_BEAR_OTC_4_DATES],
        "bear_8col_otc_dates": [_BEAR_OTC_8_DATES_LEFT, _BEAR_OTC_8_DATES_RIGHT],
    }
    return _routing.get(variant, [])


# ---------------------------------------------------------------------------
# T2: Row-level skip filters
# ---------------------------------------------------------------------------


def _bear_is_header_row(row: list[str | None]) -> bool:
    """Return ``True`` if *row* is a column-header row (not a data row).

    Detects bear column-header rows by looking for the string ``"Hunt Code"``
    (or ``"Hunt\\nCode"`` from pdfplumber cell merging) in any cell.
    This is robust because no CPW bear data value looks like "Hunt Code".
    """
    for cell in row:
        if cell is None:
            continue
        stripped = cell.strip()
        if "Hunt Code" in stripped or "Hunt\nCode" in stripped:
            return True
    return False


def _bear_is_heading_only_row(row: list[str | None]) -> bool:
    """Return ``True`` if the row is a merged-cell section heading.

    Bear tables start with rows like::

        ['Archery — Limited Licenses', None, None, ...]
        ['Season dates: Sept. 2–30 — Sex: Either', None, None, ...]

    These rows have exactly ONE non-None cell (at column 0), all others None.
    They carry section context but are not data rows.

    Guard: a single-cell row that matches ``_HUNT_CODE_RE`` is a genuine
    data row (lone hunt code in a continuation row) — returns ``False``.
    """
    non_none = [c for c in row if c is not None]
    if len(non_none) != 1:
        return False
    sole = non_none[0]
    if isinstance(sole, str) and _HUNT_CODE_RE.match(sole.strip()):
        return False
    return True


def _bear_is_see_unit_row(block_cells: list[str | None]) -> bool:
    """Return ``True`` if the block slice is a "see unit N" cross-reference row.

    Rule R10: bear tables contain rows whose Valid GMUs cell reads
    "see unit 83" (case-insensitive).  These reference another unit's
    regulations and must not produce extraction rows.

    Operates on the block-level cell slice to avoid false positives from the
    opposite block in a dual-block row.

    # Rule R10
    """
    for cell in block_cells:
        normalized = _normalize_bear_cell(cell)
        if normalized is not None and _SEE_UNIT_RE.match(normalized):
            return True
    return False


def _bear_is_footnote_row(block_cells: list[str | None]) -> bool:
    """Return ``True`` if the block slice is a ``■``-prefixed footnote row.

    Rule R5: footnote rows start with ``■`` in their first non-empty cell.
    These are annotations, not regulation rows.

    Operates on the block-level cell slice.

    # Rule R5
    """
    for cell in block_cells:
        if cell is None:
            continue
        stripped = cell.strip()
        if stripped:
            return stripped.startswith("■")
    return False


def _bear_is_note_annotation_row(block_cells: list[str | None]) -> bool:
    """Return ``True`` if the block slice is a "Note:" annotation row.

    Rule R11: rows where the Valid GMUs cell contains a "Note:" prose
    annotation (e.g. "Note: No hunting access to GMU 211.") annotate a
    prior unit row and are not independent regulation rows.

    Checks any cell in the block for a "Note:" prefix.

    # Rule R11
    """
    for cell in block_cells:
        if cell is None:
            continue
        stripped = cell.strip()
        if re.match(r"(?i)^note\s*:", stripped):
            return True
    return False


# ---------------------------------------------------------------------------
# T2: Safe indexed cell accessor
# ---------------------------------------------------------------------------


def _bear_get_cell(row: list[str | None], idx: int) -> str | None:
    """Return ``row[idx]`` safely, or ``None`` for ``_BEAR_NO_COL`` / OOB."""
    if idx == _BEAR_NO_COL:
        return None
    if idx < 0 or idx >= len(row):
        return None
    return row[idx]


# ---------------------------------------------------------------------------
# T2: Fused-row splitter (Rule R17)
# ---------------------------------------------------------------------------


def _split_fused_block_row(
    row: list[str | None],
    block: tuple[int, ...],
) -> list[list[str | None]]:
    """Rule R17: split a pdfplumber-merged multi-row block into N logical rows.

    When the Hunt Code cell of *block* contains 2+ full hunt codes separated
    by ``\\n`` — a pdfplumber artifact where two adjacent PDF rows were merged
    because the inter-row ruling was missing — split every present block cell
    on ``\\n`` and return N synthetic copies of *row*, each carrying one part
    in this block's columns.  Returns ``[row]`` unchanged when the Hunt Code
    cell has 0 or 1 full hunt code (the common case).

    Parameters
    ----------
    row:
        The original pdfplumber table row (all columns).
    block:
        5-tuple ``(unit_idx, valid_gmus_idx, dates_idx, hunt_code_idx,
        list_idx)`` where ``_BEAR_NO_COL`` (-1) means the field is absent.

    Returns
    -------
    list of rows — either ``[row]`` (no fusion detected) or N synthetic rows.

    Raises
    ------
    PdfExtractionError
        When a present, non-empty block cell does not split into exactly N
        parts (ADR-001 fail-loud — misalignment would corrupt the split).

    # Rule R17
    Locked by: TestFusedRowSplit::test_two_code_fused_row_splits_to_two_rows,
               TestFusedRowSplit::test_misaligned_cell_raises
    """
    hunt_code_idx = block[3]
    raw_hunt = _bear_get_cell(row, hunt_code_idx)
    codes = _HUNT_CODE_EMBEDDED_RE.findall(raw_hunt or "")
    if len(codes) < 2:
        # Zero or one full hunt code — no row fusion; return unchanged.
        return [row]

    n = len(codes)
    # For each present block column, split its cell value on '\n' and verify
    # the split count matches n.  Absent (_BEAR_NO_COL) or None cells produce
    # [None] * n without splitting.
    col_parts: dict[int, list[str | None]] = {}
    for idx in block:
        if idx == _BEAR_NO_COL:
            continue
        cell = _bear_get_cell(row, idx)
        if cell is None:
            col_parts[idx] = [None] * n
        else:
            parts = cell.split("\n")
            if len(parts) != n:
                raise PdfExtractionError(
                    f"_split_fused_block_row (Rule R17): block column {idx} "
                    f"has {len(parts)} newline-separated parts but Hunt Code "
                    f"cell contains {n} full codes.  "
                    f"Cell value: {cell!r}.  "
                    f"Hunt Code cell: {raw_hunt!r}.  "
                    f"Codes found: {codes}.  "
                    f"Cannot split without corrupting row alignment (ADR-001)."
                )
            col_parts[idx] = [p.strip() if p.strip() else None for p in parts]

    # Build n synthetic rows, each a shallow copy of the original row with the
    # block columns replaced by the k-th part for each column.
    synthetic_rows: list[list[str | None]] = []
    for k in range(n):
        srow: list[str | None] = list(row)
        for col_idx, col_part_list in col_parts.items():
            srow[col_idx] = col_part_list[k]
        synthetic_rows.append(srow)

    _logger.debug(
        "_split_fused_block_row (Rule R17): fused block with %d codes %r → "
        "%d synthetic rows",
        n,
        codes,
        n,
    )
    return synthetic_rows


# ---------------------------------------------------------------------------
# T2: Per-block row extractor
# ---------------------------------------------------------------------------


def _extract_bear_block_row(
    row: list[str | None],
    block: tuple[int, ...],
    header_window: CpwSeasonWindow | None,
    method_group: str,
    residency_scope: str,
    page_ref: PageReference,
    license_kind: str = "limited_draw",
) -> CpwBearRowExtraction | None:
    """Extract one ``CpwBearRowExtraction`` from a single bear block slice.

    *block* is a 5-tuple ``(unit_idx, valid_gmus_idx, dates_idx,
    hunt_code_idx, list_idx)`` where any index == ``_BEAR_NO_COL`` means that
    field is not present in this table variant.

    Returns ``None`` for orphan-fragment blocks (no hunt code, no extras, no
    identifying content in unit/valid_gmus/list).

    Season-window logic (per-row is load-bearing — S03.3 UAT D1 lesson):
      - Rifle rows: window from the per-row ``Dates`` cell (``_parse_bear_season_window``).
      - Archery/muzzleloader rows: window inherited from *header_window* (Rule R7).
      - Rifle rows with empty Dates cell still fall back to *header_window*
        only if it is already ``None`` (rifle's "See hunt code table below"
        banner parses to ``None`` so the fallback path is never reached in
        practice for rifle).

    Hunt-code single-code multi-line handling (Rule R9): if the Hunt Code
    cell contains a newline but only ONE full hunt code, the first non-empty
    line is used and any remainder is logged at DEBUG.  Cells with TWO or
    more full hunt codes (pdfplumber row-fusion artifact) are split into
    separate logical rows by ``_split_fused_block_row`` (Rule R17) BEFORE
    this function is called — by the time this function runs, the cell
    contains at most one valid code.
    """
    unit_idx, valid_gmus_idx, dates_idx, hunt_code_idx, list_idx = block

    # Determine the contiguous column range of this block.
    valid_indices = [i for i in block if i != _BEAR_NO_COL]
    if valid_indices:
        block_min, block_max = min(valid_indices), max(valid_indices)
    else:
        block_min, block_max = 0, len(row) - 1

    raw_hunt = _bear_get_cell(row, hunt_code_idx)

    # Rule R9: single-code multi-line Hunt Code cell — use first non-empty line.
    # By the time this runs, _split_fused_block_row (Rule R17) has already
    # split any cell that contained 2+ full hunt codes.  Cells reaching here
    # with a newline have only one valid code (wrapped text, trailing newline,
    # etc.) — take the first non-empty line and log any remainder at DEBUG.
    if raw_hunt and "\n" in raw_hunt:
        lines = [ln.strip() for ln in raw_hunt.split("\n") if ln.strip()]
        if len(lines) > 1:
            _logger.debug(
                "_extract_bear_block_row: Rule R9 single-code multi-line cell %r "
                "— using first line %r, discarding remainder",
                raw_hunt,
                lines[0],
            )
        raw_hunt = lines[0] if lines else raw_hunt

    hunt_code_norm = _normalize_bear_cell(raw_hunt)

    # Rule R16: if the hunt-code cell did not match the anchored regex directly
    # (e.g. it is prefixed by prose like "Sales agents only: B-E-087-U6-R"),
    # attempt an unanchored search for a full 5-component hunt code embedded in
    # the cell text.  When found, extract the code and store the surrounding
    # prose verbatim in extras (ADR-008).
    prose_prefix_for_extras: str | None = None
    if hunt_code_norm is not None and _parse_hunt_code(hunt_code_norm) is None:
        # The normalised cell is non-None but failed the anchored parse — try
        # the unanchored embedded-code search.
        embedded_m = _HUNT_CODE_EMBEDDED_RE.search(hunt_code_norm)
        if embedded_m is not None:
            extracted_code = embedded_m.group(1)
            # The prose surrounding the extracted code becomes extras.
            prose_prefix = hunt_code_norm[: embedded_m.start()].strip().rstrip(":").strip()
            prose_suffix = hunt_code_norm[embedded_m.end():].strip().lstrip(":").strip()
            prose_parts = [p for p in [prose_prefix, prose_suffix] if p]
            if prose_parts:
                prose_prefix_for_extras = _collapse_whitespace(" ".join(prose_parts))
            hunt_code_norm = extracted_code
            _logger.debug(
                "_extract_bear_block_row: Rule R16 — extracted embedded hunt code %r "
                "from prose cell %r; prose prefix stored in extras",
                extracted_code,
                raw_hunt,
            )

    # --- Extras: cells within block range not mapped to named fields ---
    mapped_indices = {i for i in block if i != _BEAR_NO_COL}
    extra_parts: list[str] = []
    for ci in range(block_min, block_max + 1):
        if ci in mapped_indices:
            continue
        v = _normalize_bear_cell(_bear_get_cell(row, ci))
        if v is not None:
            extra_parts.append(v)
    extras_raw = " ".join(extra_parts) if extra_parts else None
    extras = _collapse_whitespace(extras_raw) if extras_raw else None

    # Merge Rule R16 prose prefix into extras (prepend; verbatim per ADR-008).
    if prose_prefix_for_extras is not None:
        extras = (
            prose_prefix_for_extras
            if extras is None
            else f"{prose_prefix_for_extras} {extras}"
        )

    # Skip orphan-fragment blocks: no hunt code, no extras, and no identifying content.
    # Excludes dates_idx from the content check (pdfplumber row-split artifacts
    # can land a bare date with no hunt code / unit / list — not a regulation row).
    if hunt_code_norm is None and extras is None:
        has_content = any(
            _normalize_bear_cell(_bear_get_cell(row, i)) is not None
            for i in (unit_idx, valid_gmus_idx, list_idx)
            if i != _BEAR_NO_COL
        )
        if not has_content:
            _logger.debug("_extract_bear_block_row: skipping orphan-fragment block: %r", block)
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
        # Warn on unexpected species letter but do not drop the row (ADR-001).
        if species_letter != "B":
            _logger.warning(
                "_extract_bear_block_row: unexpected species letter %r in hunt code %r "
                "(expected 'B' for Black Bear) — row emitted at LOW confidence",
                species_letter,
                hunt_code_str,
            )
    else:
        species_letter = ""
        sex_code = ""
        gmu_code = ""
        season_code = ""
        method_letter = ""

    # Derive weapon_types from method_letter; fall back to method_group.
    if method_letter:
        weapon_types = _weapon_types_for(method_letter)
        if not weapon_types:
            _logger.warning(
                "_extract_bear_block_row: unrecognised method letter %r in %r "
                "— weapon_types empty",
                method_letter,
                hunt_code_str,
            )
    else:
        _METHOD_GROUP_TO_LETTER: dict[str, str] = {
            "archery": "A",
            "muzzleloader": "M",
            "rifle": "R",
        }
        fallback_letter = _METHOD_GROUP_TO_LETTER.get(method_group, "")
        weapon_types = _weapon_types_for(fallback_letter)

    # Season window (per-row is load-bearing — S03.3 UAT D1 lesson).
    raw_dates = _bear_get_cell(row, dates_idx)
    if raw_dates is not None and raw_dates.strip() and raw_dates.strip() != "-":
        window = _parse_bear_season_window(raw_dates)
        season_windows: list[CpwSeasonWindow] = [window] if window is not None else []
    elif header_window is not None:
        season_windows = [header_window]
    else:
        season_windows = []

    return CpwBearRowExtraction(
        hunt_code=hunt_code_str,
        species_letter=species_letter,
        sex_code=sex_code,
        gmu_code=gmu_code,
        season_code=season_code,
        method_letter=method_letter,
        unit=_normalize_bear_cell(_bear_get_cell(row, unit_idx)),
        valid_gmus=_normalize_bear_cell(_bear_get_cell(row, valid_gmus_idx)),
        season_windows=season_windows,
        list_value=_normalize_bear_cell(_bear_get_cell(row, list_idx)),
        apply_by=None,  # universally None for CPW bear V1 — no apply_by column
        quota=None,  # universally None for CPW bear V1 — no quota column
        quota_range=None,  # universally None for CPW bear V1 — no quota_range column
        weapon_types=weapon_types,
        method_group=method_group,
        residency_scope=residency_scope,
        license_kind=license_kind,
        extras=extras,
        extraction_confidence="",  # T3 assigns confidence
        page_reference=page_ref,
    )


# ---------------------------------------------------------------------------
# T2: Per-table parser
# ---------------------------------------------------------------------------


def _bear_parse_table_block(
    rows: list[list[str | None]],
    method_group: str,
    residency_scope: str,
    page_ref: PageReference,
    header_window: CpwSeasonWindow | None = None,
    license_kind: str = "limited_draw",
) -> list[CpwBearRowExtraction]:
    """Parse all regulation rows from a single pdfplumber bear table.

    Handles all observed bear column variants (4-col, 5-col, 8-col, 10-col)
    via ``_bear_classify_table_variant`` and ``_bear_block_slices``.

    Skip rules applied (in order):
      1. Heading-only rows (``_bear_is_heading_only_row``) — merged-cell
         section headings; the heading text is parsed for a header date before
         being skipped, updating *header_window* for subsequent rows.
      2. Column-header rows (``_bear_is_header_row``) — "Unit / Valid GMUs /
         Hunt Code / List" rows.
      3. Per-block: see-unit cross-reference rows (``_bear_is_see_unit_row``).
      4. Per-block: footnote rows (``_bear_is_footnote_row``).
      5. Per-block: "Note:" annotation rows (``_bear_is_note_annotation_row``).
      6. Orphan-fragment blocks (``_extract_bear_block_row`` returns ``None``).

    *header_window* is updated in-place as heading-only rows are encountered,
    so the correct banner date propagates to all data rows that follow it
    within the same table (archery/muzzleloader only; rifle banners parse to
    ``None`` so they correctly do not propagate a date).

    Returns a flat list of ``CpwBearRowExtraction`` dicts (one per parseable
    data row across all blocks in the table).
    """
    if not rows:
        return []

    ncols = len(rows[0]) if rows else 0
    variant = _bear_classify_table_variant(ncols)

    if variant == "unknown":
        _logger.warning(
            "_bear_parse_table_block: unrecognised column count %d on page %d — skipping",
            ncols,
            page_ref.get("page_num_1based", 0),
        )
        return []

    blocks = _bear_block_slices(variant)
    results: list[CpwBearRowExtraction] = []

    # header_window may be updated as we walk heading-only rows; use a mutable
    # container so we can update it from inside the loop.
    current_window: CpwSeasonWindow | None = header_window

    for raw_row in rows:
        # Skip heading-only rows; parse them first to extract banner date.
        if _bear_is_heading_only_row(raw_row):
            sole = next((c for c in raw_row if c is not None), None)
            if sole:
                parsed_window = _parse_bear_header_date(sole)
                if parsed_window is not None:
                    current_window = parsed_window
                    _logger.debug(
                        "_bear_parse_table_block: header date extracted from %r: %r",
                        sole,
                        parsed_window,
                    )
            continue

        if _bear_is_header_row(raw_row):
            continue

        # Per-block extraction.
        for block in blocks:
            block_cells = [_bear_get_cell(raw_row, i) for i in block]

            if _bear_is_see_unit_row(block_cells):
                _logger.debug(
                    "_bear_parse_table_block: skipping see-unit block: %r", block_cells
                )
                continue
            if _bear_is_footnote_row(block_cells):
                _logger.debug(
                    "_bear_parse_table_block: skipping footnote block: %r", block_cells
                )
                continue
            if _bear_is_note_annotation_row(block_cells):
                _logger.debug(
                    "_bear_parse_table_block: skipping note-annotation block: %r",
                    block_cells,
                )
                continue

            # Rule R17: split any pdfplumber row-fusion (2+ hunt codes in one
            # cell) into N logical rows before extraction.  Skip checks above
            # operate on the original raw_row block_cells (pre-split) — the
            # fused row is a real data row, not a see-unit/footnote row, so
            # it passes those checks.  The split is applied here, after skips.
            for srow in _split_fused_block_row(raw_row, block):
                extracted = _extract_bear_block_row(
                    srow,
                    block,
                    current_window,
                    method_group,
                    residency_scope,
                    page_ref,
                    license_kind=license_kind,
                )
                if extracted is not None:
                    results.append(extracted)

    return results


# ---------------------------------------------------------------------------
# T2: Limited-rows extractor (pages 73–75)
# ---------------------------------------------------------------------------


def _extract_limited_rows(
    pdf: object,
    extracted_at: str,
    residency_scope: str = "both",
) -> list[CpwBearRowExtraction]:
    """Extract all LIMITED hunt-code rows from PDF pages 73–75 (bear section).

    Pages targeted (1-based, per ``_BEAR_PAGES`` probe):
      - Page 73: Archery — Limited Licenses (8-col dual + 2 × 4-col overflow)
      - Page 74: Muzzleloader — Limited Licenses (8-col dual + 2 × 4-col overflow)
                 + Rifle — Limited Licenses start (10-col dual + 5-col overflow)
      - Page 75: Rifle — Limited Licenses continued (10-col dual + 5-col overflow)

    OTC tables (pages 76–77) are excluded; this function returns only the
    limited-draw rows.  The caller (T3) handles OTC extraction and section
    grouping.

    Algorithm:
      1. Walk pages 73–75 (0-indexed 72–74).
      2. For each pdfplumber table on the page, determine the current method
         group from the table's heading-only row (first row with a single
         non-None cell matching a method keyword).
      3. Skip tables whose heading indicates OTC (contains "Over-the-Counter"
         or "Add-On") — these belong to T3.
      4. Parse each table via ``_bear_parse_table_block``, passing the current
         method_group and a ``None`` header_window (the function extracts the
         banner date from the heading row internally).
      5. Accumulate and return all rows.

    Parameters
    ----------
    pdf:
        An open ``pdfplumber.PDF`` instance (not a path).
    extracted_at:
        ISO timestamp string from the PDF manifest's ``fetched_at`` field
        (via ``_load_extracted_at_from_manifest``).  Threaded into every
        ``PageReference`` so the artifact is deterministic without wall-clock
        calls.
    residency_scope:
        Residency context for all rows.  CPW bear limited licenses do not
        distinguish residency in the table data; all rows are tagged "both"
        (the default) per the brochure's section headings which say
        "Limited Licenses" without a resident/nonresident qualifier.

    Returns a flat list of ``CpwBearRowExtraction`` dicts (confidence = "").
    T3 fills ``extraction_confidence`` and groups rows into sections.
    """
    limited_rows: list[CpwBearRowExtraction] = []

    # Pages 73–75 are 0-indexed 72–74.
    for page_idx in range(72, 75):
        page = pdf.pages[page_idx]  # type: ignore[attr-defined]
        page_num_1based = page_idx + 1
        page_ref = PageReference(
            pdf_filename=_PDF_FILENAME,
            page_num_1based=page_num_1based,
            bbox=None,
            extracted_at=extracted_at,
        )

        tables = page.find_tables()
        _logger.debug(
            "_extract_limited_rows: page %d — %d table(s) found",
            page_num_1based,
            len(tables),
        )

        # Track current method group AND header window across tables on this
        # page.  The overflow single-block tables (4-col, 5-col) that appear
        # after the primary dual-block table on the same page carry no heading
        # row of their own — they inherit the method group and header window
        # from the preceding primary table on the same page.
        current_method_group: str = "archery"  # default; overridden by heading rows
        current_header_window: CpwSeasonWindow | None = None

        for tbl_idx, tbl in enumerate(tables):
            tbl_rows = tbl.extract()
            if not tbl_rows:
                continue

            # Detect method group and OTC status from heading-only rows.
            table_method_group: str | None = None
            table_header_window: CpwSeasonWindow | None = None
            is_otc_table = False
            for r in tbl_rows:
                non_none = [c for c in r if c is not None]
                if len(non_none) == 1:
                    sole = non_none[0]
                    if isinstance(sole, str):
                        # Check for OTC / Add-On table — skip in T2.
                        if re.search(r"(?i)(over-the-counter|add-on)", sole):
                            is_otc_table = True
                            break
                        # Check for method heading (e.g. "Archery — Limited Licenses").
                        detected = _method_group_from_bear_heading(sole)
                        if detected is not None:
                            table_method_group = detected
                        # Check for season-date banner (Rule R7).
                        parsed_win = _parse_bear_header_date(sole)
                        if parsed_win is not None:
                            table_header_window = parsed_win

            if is_otc_table:
                _logger.debug(
                    "_extract_limited_rows: page %d tbl %d — OTC table, skipping",
                    page_num_1based,
                    tbl_idx,
                )
                continue

            # Update page-level tracking state.
            # A new method heading resets the header window; otherwise the
            # overflow table inherits the window from the primary table.
            if table_method_group is not None:
                current_method_group = table_method_group
                # Rifle banner ("See hunt code table below") produces no window;
                # archery/muzzleloader banners produce a window.  Reset when the
                # method changes — the new method's banner may differ.
                current_header_window = table_header_window  # may be None for rifle
            elif table_header_window is not None:
                # Overflow table with its own banner (unlikely but guard it).
                current_header_window = table_header_window
            # else: overflow table inherits current_header_window unchanged.

            _logger.debug(
                "_extract_limited_rows: page %d tbl %d — method=%r header_window=%r ncols=%d",
                page_num_1based,
                tbl_idx,
                current_method_group,
                current_header_window,
                len(tbl_rows[0]) if tbl_rows else 0,
            )

            table_rows = _bear_parse_table_block(
                tbl_rows,
                method_group=current_method_group,
                residency_scope=residency_scope,
                page_ref=page_ref,
                header_window=current_header_window,
            )
            limited_rows.extend(table_rows)
            _logger.debug(
                "_extract_limited_rows: page %d tbl %d — %d rows extracted",
                page_num_1based,
                tbl_idx,
                len(table_rows),
            )

    return limited_rows


# ---------------------------------------------------------------------------
# T3: OTC table extraction (pages 76–77)
# ---------------------------------------------------------------------------

# OTC sub-section heading patterns used to identify method group and license_kind
# from OTC table heading-only rows.
_OTC_ARCHERY_ADDON_RE = re.compile(r"(?i)archery\s+.*add.on\s+over.the.counter")
_OTC_MUZZ_ADDON_RE = re.compile(r"(?i)muzzleloader\s+.*add.on\s+over.the.counter")
_OTC_RIFLE_ADDON_RE = re.compile(r"(?i)rifle\s+.*add.on\s+over.the.counter")
_OTC_RIFLE_RE = re.compile(r"(?i)^rifle\s+—\s+over.the.counter", re.IGNORECASE)
_OTC_RIFLE_PRIVATE_RE = re.compile(
    r"(?i)rifle\s+.*private\s+land\s+only\s+.*over.the.counter"
)
_OTC_RIFLE_PLAINS_RE = re.compile(r"(?i)rifle\s+.*plains\s+.*over.the.counter")
# Generic "Archery" / "Muzzleloader" / "Rifle" method detection for OTC headings
_OTC_METHOD_RE = re.compile(r"(?i)^(?P<method>archery|muzzleloader|rifle)\b")


def _is_map_garbage_table(rows: list[list[str | None]]) -> bool:
    """Return True if the table appears to be a map legend / OCR garbage.

    The map on p.76 is captured by pdfplumber as a 1-col table with a long
    garbled string of GMU numbers and map labels.  Detect it by checking
    for a 1-column table whose first data cell exceeds 200 characters
    (genuine regulation tables never have cells that long in a 1-col table).
    """
    if not rows:
        return False
    if len(rows[0]) != 1:
        return False
    for row in rows:
        cell = row[0]
        if cell and len(cell) > 200:
            return True
    return False


def _otc_classify_heading(heading: str) -> tuple[str, str, str | None]:
    """Classify an OTC table heading row into (method_group, license_kind, note).

    Returns:
      method_group  — "archery" | "muzzleloader" | "rifle"
      license_kind  — "add_on_otc" | "over_the_counter" | "private_land_otc" | "plains_otc"
      note          — prerequisite text from the banner (Rule R14), or None.

    The note is extracted from the banner for Add-On OTC headings by
    splitting on the em-dash/long-dash separating the season date and
    the prerequisite clause.  Empirical banner formats from live probe
    2026-06-13:
      - Archery:    "Season dates: Sept. 2–30 — Sex: Either — You must hold an archery
                    deer or elk license to purchase one of these licenses. — Do not apply
                    in the draw for these hunts."
      - Muzzleloader: same pattern with "muzzleloader" substituted
      - Rifle add-on: "Season dates: Oct. 1–7 — Sex: Either — You must hold a rifle
                      elk license in hunt code E-E-061-E1-R to purchase this license.
                      — Do not apply in the draw for these hunts."
    """
    note: str | None = None

    if _OTC_RIFLE_PLAINS_RE.search(heading):
        return "rifle", "plains_otc", note
    if _OTC_RIFLE_PRIVATE_RE.search(heading):
        return "rifle", "private_land_otc", note
    if _OTC_ARCHERY_ADDON_RE.search(heading):
        method_group = "archery"
        license_kind = "add_on_otc"
    elif _OTC_MUZZ_ADDON_RE.search(heading):
        method_group = "muzzleloader"
        license_kind = "add_on_otc"
    elif _OTC_RIFLE_ADDON_RE.search(heading):
        method_group = "rifle"
        license_kind = "add_on_otc"
    elif _OTC_RIFLE_RE.match(heading):
        return "rifle", "over_the_counter", note
    else:
        # Fallback: detect method from the heading text.
        m = _OTC_METHOD_RE.match(heading)
        if m is None:
            raise PdfExtractionError(
                f"_otc_classify_heading: unrecognized OTC heading — cannot classify "
                f"method_group or license_kind.  Heading text: {heading!r}.  "
                f"A new CPW heading format must be handled explicitly (ADR-001 fail-loud)."
            )
        method_group = m.group("method").lower()
        license_kind = "over_the_counter"
        return method_group, license_kind, note

    # For Add-On OTC: extract the prerequisite note from the banner text.
    # Rule R14: locate the "You must hold …" clause by splitting on " — ".
    # The note is everything from the "You must hold" clause up to
    # (but not including) "Do not apply in the draw".
    parts = heading.split(" — ")
    note_parts: list[str] = []
    in_note = False
    for part in parts:
        stripped = part.strip()
        if re.match(r"(?i)you must hold", stripped):
            in_note = True
        if in_note:
            if re.match(r"(?i)do not apply", stripped):
                break
            note_parts.append(stripped)
    if note_parts:
        note = " — ".join(note_parts)

    return method_group, license_kind, note


def _extract_otc_rows(
    pdf: object,
    extracted_at: str,
    residency_scope: str = "both",
) -> list[tuple[CpwBearRowExtraction, str | None]]:
    """Extract all OTC hunt-code rows from PDF pages 76–77 (bear section).

    Returns a list of (row, section_note) pairs where ``section_note`` is
    the Add-On OTC prerequisite text (Rule R14) or ``None`` for non-add-on
    OTC sections.

    Pages targeted (1-based):
      - Page 76: Add-On OTC (Archery / Muzzleloader / Rifle add-on)
      - Page 77: Standalone OTC (Rifle OTC / Private Land Only / Plains)

    Algorithm for Rifle OTC multi-window rows (Rule R13):
      pdfplumber delivers each season date as a separate row with the hunt
      code populated only in the primary row.  We walk rows sequentially
      and maintain a ``pending`` accumulator:
        - If the hunt-code cell is non-empty → new primary row; flush any
          pending row, emit it, start accumulating for the new primary.
        - If the hunt-code cell is empty BUT the Dates cell is non-empty →
          continuation row; add its window to the pending primary row.
        - All other empty/skip rows → ignored.
    """
    results: list[tuple[CpwBearRowExtraction, str | None]] = []

    for page_idx in range(75, 77):  # 0-indexed 75–76 = PDF pages 76–77
        page = pdf.pages[page_idx]  # type: ignore[attr-defined]
        page_num_1based = page_idx + 1
        page_ref = PageReference(
            pdf_filename=_PDF_FILENAME,
            page_num_1based=page_num_1based,
            bbox=None,
            extracted_at=extracted_at,
        )

        tables = page.find_tables()
        _logger.debug(
            "_extract_otc_rows: page %d — %d table(s) found",
            page_num_1based,
            len(tables),
        )

        # Track method/license_kind across tables on the same page.
        current_method: str = "rifle"
        current_license_kind: str = "over_the_counter"
        current_note: str | None = None
        current_header_window: CpwSeasonWindow | None = None

        for tbl_idx, tbl in enumerate(tables):
            tbl_rows = tbl.extract()
            if not tbl_rows:
                continue
            if _is_map_garbage_table(tbl_rows):
                _logger.debug(
                    "_extract_otc_rows: page %d tbl %d — map/garbage table, skipping",
                    page_num_1based,
                    tbl_idx,
                )
                continue

            ncols = len(tbl_rows[0])
            variant = _bear_classify_table_variant(ncols)
            _logger.debug(
                "_extract_otc_rows: page %d tbl %d — variant=%s ncols=%d",
                page_num_1based,
                tbl_idx,
                variant,
                ncols,
            )

            # Detect heading, banner note, and date from heading-only rows before parsing.
            # Two distinct heading-only rows appear in OTC tables:
            #   Row 0: "Archery — Add-On Over-the-Counter Licenses"  → method + license_kind
            #   Row 1: "Season dates: … — You must hold …"           → banner window + note (Rule R14)
            # We scan ALL heading-only rows in the first pass so both are captured.
            table_method: str | None = None
            table_license_kind: str | None = None
            table_note: str | None = None
            table_header_window: CpwSeasonWindow | None = None

            for r in tbl_rows:
                non_none = [c for c in r if c is not None and str(c).strip()]
                if len(non_none) == 1:
                    sole = str(non_none[0]).strip()
                    if _bear_is_header_row(r):
                        continue
                    # Row 0: OTC section heading — classify method + license_kind.
                    if re.search(r"(?i)(over.the.counter|add.on|plains)", sole):
                        m_grp, l_kind, _nte_from_heading = _otc_classify_heading(sole)
                        table_method = m_grp
                        table_license_kind = l_kind
                        # Note from heading row is always None (the note lives in the
                        # banner row below); set here for completeness but overridden.
                        if table_note is None:
                            table_note = _nte_from_heading
                    # Row 0 or Row 1: extract "You must hold…" prerequisite note.
                    # Rule R14: split on " — " and collect the "You must hold" clause.
                    if re.search(r"(?i)you must hold", sole):
                        parts = sole.split(" — ")
                        note_parts: list[str] = []
                        in_note = False
                        for part in parts:
                            stripped_p = part.strip()
                            if re.match(r"(?i)you must hold", stripped_p):
                                in_note = True
                            if in_note:
                                if re.match(r"(?i)do not apply", stripped_p):
                                    break
                                note_parts.append(stripped_p)
                        if note_parts:
                            table_note = " — ".join(note_parts)
                    # Banner row with season dates (Rule R7 / R13).
                    parsed_win = _parse_bear_header_date(sole)
                    if parsed_win is not None:
                        table_header_window = parsed_win

            # Update page-level tracking.
            if table_method is not None:
                current_method = table_method
                current_license_kind = table_license_kind or current_license_kind
                current_note = table_note
                current_header_window = table_header_window
            elif table_header_window is not None:
                current_header_window = table_header_window

            # Determine block slices for this variant.
            # OTC-specific routing: 4-col tables on pages 76–77 are always
            # OTC-with-Dates (not limited-no-Dates), so override the variant
            # to "bear_4col_otc_dates" when on these pages.
            if variant == "bear_4col" and page_idx >= 75:
                variant = "bear_4col_otc_dates"
            elif variant == "bear_8col" and page_idx >= 75:
                variant = "bear_8col_otc_dates"

            blocks = _bear_block_slices(variant)
            if not blocks:
                _logger.debug(
                    "_extract_otc_rows: page %d tbl %d — no block slices for variant %s",
                    page_num_1based,
                    tbl_idx,
                    variant,
                )
                continue

            # Walk rows, applying multi-window consolidation (Rule R13) for
            # OTC tables that have a Dates column.
            has_dates_col = variant in (
                "bear_4col_otc_dates",
                "bear_8col_otc_dates",
            )

            if has_dates_col:
                # Multi-window consolidation path (Rule R13).
                # Process each block independently.
                for block in blocks:
                    unit_idx, valid_gmus_idx, dates_idx, hunt_code_idx, list_idx = block
                    pending_row: CpwBearRowExtraction | None = None
                    pending_note: str | None = current_note

                    for raw_row in tbl_rows:
                        if _bear_is_heading_only_row(raw_row):
                            continue
                        if _bear_is_header_row(raw_row):
                            continue

                        block_cells = [_bear_get_cell(raw_row, i) for i in block]
                        if _bear_is_footnote_row(block_cells):
                            continue
                        if _bear_is_note_annotation_row(block_cells):
                            continue
                        if _bear_is_see_unit_row(block_cells):
                            continue

                        raw_hunt = _bear_get_cell(raw_row, hunt_code_idx)
                        hunt_norm = _normalize_bear_cell(raw_hunt)
                        raw_dates = _bear_get_cell(raw_row, dates_idx)
                        dates_norm = _normalize_bear_cell(raw_dates)

                        if hunt_norm is not None:
                            # New primary row — flush pending first.
                            if pending_row is not None:
                                results.append((pending_row, pending_note))
                            # Build the new primary row.
                            new_row = _extract_bear_block_row(
                                raw_row,
                                block,
                                current_header_window,
                                current_method,
                                residency_scope,
                                page_ref,
                                license_kind=current_license_kind,
                            )
                            pending_row = new_row
                            pending_note = current_note
                        elif dates_norm is not None and pending_row is not None:
                            # Continuation-dates row (Rule R13) — add window.
                            win = _parse_bear_season_window(dates_norm)
                            if win is not None:
                                pending_row["season_windows"].append(win)
                        # else: empty continuation row — skip.

                    # Flush the last pending row for this block.
                    if pending_row is not None:
                        results.append((pending_row, pending_note))
                        pending_row = None

            else:
                # No Dates column (Add-On OTC archery/muzz/rifle, p. 76).
                # All rows in a sub-table inherit the header date (Rule R7).
                table_rows_extracted = _bear_parse_table_block(
                    tbl_rows,
                    method_group=current_method,
                    residency_scope=residency_scope,
                    page_ref=page_ref,
                    header_window=current_header_window,
                    license_kind=current_license_kind,
                )
                for extracted_row in table_rows_extracted:
                    results.append((extracted_row, current_note))

    return results


# ---------------------------------------------------------------------------
# T3: Confidence assignment (Rule R15)
# ---------------------------------------------------------------------------


def _assign_bear_row_confidence(row: CpwBearRowExtraction) -> str:
    """Assign an extraction confidence tier to one CPW bear row per ADR-017.

    Returns one of the ``ConfidenceTier`` string values (``"high"``,
    ``"medium"``, or ``"low"``).  Mirrors ``extract_big_game._assign_row_confidence``
    (reimplemented inline per ADR-005 — no sibling import).

    Confidence tiers:

    **LOW** — the hunt code did not parse (``species_letter == ""``), meaning
        the row is structurally unidentifiable.  WARNING logged naming the raw
        hunt code and page so the UAT reviewer can audit without manual scan.
        Per ADR-017 §7 / S03.11 FINALIZE: ``low > 0`` is a data-shape signal —
        the LOW tier exists to surface these rows; do NOT alter the framework.

    **HIGH** — all three conditions met:
        1. Hunt code parsed (``species_letter != ""``).
        2. ``list_value`` is not None.
        3. At least one ``season_windows`` entry has both ``start_date`` and
           ``end_date`` non-None.
        Design note: condition 3 keys on whether the dates *resolved*, not on
        whether they came from a per-row Dates cell or a propagated header
        window (Rule R7).  A cleanly-parsed header window satisfies HIGH just
        as well as an inline Dates cell.

    **MEDIUM** — parsed hunt code but something incomplete:
        - No fully resolved season window (empty or only raw_text present).
        - ``list_value`` is None.

    # Rule R15
    """
    hunt_code = row["hunt_code"]
    page_num = row["page_reference"].get("page_num_1based", "?")

    # LOW: structurally unidentifiable — hunt code did not parse.
    if row["species_letter"] == "":
        _logger.warning(
            "_assign_bear_row_confidence: row %r (page %s) has unparseable hunt code "
            "— flagged LOW confidence",
            hunt_code,
            page_num,
        )
        return ConfidenceTier.LOW

    # Check for a fully resolved season window.
    has_resolved_window = any(
        w["start_date"] is not None and w["end_date"] is not None
        for w in row["season_windows"]
    )

    # HIGH: parsed hunt code + list value + resolved window.
    if row["list_value"] is not None and has_resolved_window:
        return ConfidenceTier.HIGH

    # MEDIUM: parsed hunt code but something missing.
    return ConfidenceTier.MEDIUM


# ---------------------------------------------------------------------------
# T3: Verbatim text builder for bear sections
# ---------------------------------------------------------------------------


def _verbatim_text_for_bear_section(rows: list[CpwBearRowExtraction]) -> str:
    """Build a per-section verbatim text reconstruction from bear rows.

    ADR-008 compliance: the verbatim text is a faithful per-section
    reconstruction of source row cells — NOT the full page text.

    For each row the verbatim source cells are joined with `` | `` separators
    in this order:
        unit, valid_gmus, [season_windows[0].raw_text, ...], hunt_code, list_value

    (No ``sex_code`` field: bear tables have no Sex column — all V1 bear rows
    are ``E``/Either, confirmed 2026-06-13.)  Rows joined with ``"\\n"``.
    ``None`` cells emitted as empty strings so the column structure is preserved.
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
            row["hunt_code"],
            row["list_value"] or "",
        ])
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# T3: Deterministic sort key for bear sections
# ---------------------------------------------------------------------------

# Large sentinel for non-numeric GMU codes in _bear_sort_key.
_BEAR_NON_NUMERIC_GMU_SENTINEL = 999999


def _bear_sort_key(
    section: CpwBearSectionExtraction,
) -> tuple[int, str, int, str, str, str, int]:
    """Deterministic sort key for a ``CpwBearSectionExtraction``.

    Ordering: (method_order, method_group, gmu_numeric, gmu_code,
    residency_scope, license_kind, page)

    - ``method_order``: archery=0, muzzleloader=1, rifle=2; unknown=99.
    - ``method_group``: raw string tiebreaker.
    - ``gmu_numeric``: ``int(gmu_code)`` when all-digits; otherwise sentinel
      (non-numeric / empty codes sort after numeric ones).
    - ``gmu_code``: raw string tiebreaker.
    - ``residency_scope``: raw string tiebreaker.
    - ``license_kind``: raw string tiebreaker (limited before OTC).
    - ``page``: first-page tiebreaker (disambiguates empty-GMU sections).

    Bear has a single species (``black_bear``) so no species_order component.
    Rows within a section preserve PDF order (not re-sorted here).
    """
    method_order = {"archery": 0, "muzzleloader": 1, "rifle": 2}
    meth_num = method_order.get(section["method_group"], 99)
    gmu_code = section["gmu_code"]
    gmu_numeric = int(gmu_code) if gmu_code.isdigit() else _BEAR_NON_NUMERIC_GMU_SENTINEL
    return (
        meth_num,
        section["method_group"],
        gmu_numeric,
        gmu_code,
        section["residency_scope"],
        section["license_kind"],
        section["page_reference"]["page_num_1based"],
    )


# ---------------------------------------------------------------------------
# T3: Prose extraction — reporting obligation candidate
# ---------------------------------------------------------------------------

# Anchors for the "Mandatory Bear Inspections & Seals" prose block (p. 73).
# The block starts immediately after the heading and ends at a blank line
# or at the "Multiple Options" heading which begins the right column.
_BEAR_INSPECTION_START_RE = re.compile(
    r"(?i)mandatory\s+bear\s+inspections\s+[&and]+\s+seals"
)
_BEAR_INSPECTION_END_RE = re.compile(
    r"(?i)multiple\s+options\s+for\s+hunting\s+bear"
)


def _extract_mandatory_inspection_candidate(
    pdf: object,
    extracted_at: str,
    source_id: str,
    source_publication_date: str,
) -> BearReportingObligationCandidate | None:
    """Extract the "Mandatory Bear Inspections & Seals" prose as a reporting-
    obligation candidate.

    Reads PDF p. 73 (0-indexed page 72), finds the "Mandatory Bear
    Inspections & Seals" prose block via ``_BEAR_INSPECTION_START_RE`` +
    ``_BEAR_INSPECTION_END_RE`` anchors, and returns a
    ``BearReportingObligationCandidate`` with the verbatim text per ADR-008.

    Returns ``None`` if the prose block cannot be found — logged at WARNING.

    The verbatim text from the live PDF probe 2026-06-13 (shortened, actual
    extraction is full verbatim):
      "Hunters must personally present their bear head and hide to any CPW
      office (see inside front cover) during normal business hours, or by
      appointment with a CPW officer, for a free inspection, check report
      and sealing within five working days after harvest. …"

    ``deadline_hint`` is set to ``"5 working days"`` which is the literal
    window stated in the brochure.

    # Rule R15 (confidence: HIGH — cleanly bounded prose block)
    """
    page_num_1based = 73
    page = pdf.pages[page_num_1based - 1]  # type: ignore[attr-defined]
    page_ref = PageReference(
        pdf_filename=_PDF_FILENAME,
        page_num_1based=page_num_1based,
        bbox=None,
        extracted_at=extracted_at,
    )

    raw_text = page.extract_text() or ""

    # Find the start of the inspection block.
    start_m = _BEAR_INSPECTION_START_RE.search(raw_text)
    if start_m is None:
        _logger.warning(
            "_extract_mandatory_inspection_candidate: "
            "could not find 'Mandatory Bear Inspections & Seals' heading on p. 73"
        )
        return None

    # Extract from the heading onward; stop at the right-column heading.
    block_text = raw_text[start_m.start():]
    end_m = _BEAR_INSPECTION_END_RE.search(block_text)
    if end_m is not None:
        block_text = block_text[: end_m.start()]

    # Collapse whitespace for prose readability (Rule R4 analog for prose).
    verbatim_rule = re.sub(r"\s+", " ", block_text).strip()

    if not verbatim_rule:
        _logger.warning(
            "_extract_mandatory_inspection_candidate: "
            "extracted empty inspection prose block on p. 73"
        )
        return None

    return BearReportingObligationCandidate(
        record_type="reporting_obligation",
        region_scope="STATEWIDE",
        kind_hint="mandatory_inspection",
        deadline_hint="5 working days",
        verbatim_rule=verbatim_rule,
        page_reference=page_ref,
        source_id=source_id,
        source_publication_date=source_publication_date,
        extraction_confidence=ConfidenceTier.HIGH,
    )


# ---------------------------------------------------------------------------
# T3: Prose extraction — statewide rule candidates
# ---------------------------------------------------------------------------

# Anchors for the "Bear Season Dates" summary table (p. 72 left column).
_BEAR_SEASON_DATES_HEADING_RE = re.compile(r"(?i)bear\s+season\s+dates")
# Anchors for "List A, B & C" explanation (p. 72 right column).
_BEAR_LIST_ABC_HEADING_RE = re.compile(
    r"(?i)list\s+a[,\s]+b\s*[&and]+\s*c\s*:\s*get\s+more\s+than\s+one"
)
_BEAR_LIST_ABC_END_RE = re.compile(
    r"(?i)need\s+to\s+know|sample\s+rifle\s+bear\s+table|attention\s*:"
)


def _extract_statewide_rule_candidates(
    pdf: object,
    extracted_at: str,
    source_id: str,
    source_publication_date: str,
) -> list[BearStatewideRuleCandidate]:
    """Extract statewide rule candidates from PDF p. 72 (content p. 62).

    Returns up to two candidates:
      1. ``"season_dates_summary"`` — the Bear Season Dates summary table
         text (left column, p. 72).
      2. ``"list_abc_explanation"`` — the List A/B/C eligibility explanation
         prose (right column, p. 72).

    Uses pdfplumber tables to extract the verbatim content of each block
    faithfully per ADR-008.  If a table cannot be found the candidate is
    omitted (logged at WARNING rather than raised — these are informational
    candidates, not primary regulation rows; a missing statewide rule is a
    signal but not a blocking error).

    The List A/B/C table (Table 1 on p. 72, confirmed via live probe) has
    a 3-col layout where the full explanation is in cell [1][0].  The Season
    Dates table (Table 0 on p. 72) has 2 cols; the dates are in column 1.

    # Rule R15 (confidence: HIGH for cleanly extracted prose tables)
    """
    page_num_1based = 72
    page = pdf.pages[page_num_1based - 1]  # type: ignore[attr-defined]
    page_ref = PageReference(
        pdf_filename=_PDF_FILENAME,
        page_num_1based=page_num_1based,
        bbox=None,
        extracted_at=extracted_at,
    )

    candidates: list[BearStatewideRuleCandidate] = []
    tables = page.find_tables()

    # --- Season Dates summary (Table 0: 2-col) ---
    season_dates_text: str | None = None
    for tbl in tables:
        rows = tbl.extract()
        if not rows:
            continue
        # Check if this looks like the Bear Season Dates table.
        heading_row = rows[0]
        heading_cell = heading_row[0] if heading_row else None
        if heading_cell and _BEAR_SEASON_DATES_HEADING_RE.search(str(heading_cell)):
            # Reconstruct verbatim text: heading + each "method: date" row.
            parts: list[str] = []
            for r in rows:
                row_parts = [str(c).strip() for c in r if c is not None and str(c).strip()]
                if row_parts:
                    parts.append(" ".join(row_parts))
            season_dates_text = "\n".join(parts)
            break

    if season_dates_text:
        candidates.append(
            BearStatewideRuleCandidate(
                record_type="statewide_rule",
                rule_hint="season_dates_summary",
                verbatim_text=season_dates_text,
                page_reference=page_ref,
                source_id=source_id,
                source_publication_date=source_publication_date,
                extraction_confidence=ConfidenceTier.HIGH,
            )
        )
    else:
        _logger.warning(
            "_extract_statewide_rule_candidates: "
            "could not find 'Bear Season Dates' table on p. 72"
        )

    # --- List A/B/C explanation (Table 1: 3-col) ---
    list_abc_text: str | None = None
    for tbl in tables:
        rows = tbl.extract()
        if not rows:
            continue
        heading_row = rows[0]
        heading_cell = heading_row[0] if heading_row else None
        if heading_cell and _BEAR_LIST_ABC_HEADING_RE.search(str(heading_cell)):
            # The explanation body is in rows[1][0] (long prose cell).
            parts = []
            for r in rows:
                row_parts = [str(c).strip() for c in r if c is not None and str(c).strip()]
                if row_parts:
                    parts.append(" ".join(row_parts))
            list_abc_text = "\n".join(parts)
            break

    if list_abc_text:
        candidates.append(
            BearStatewideRuleCandidate(
                record_type="statewide_rule",
                rule_hint="list_abc_explanation",
                verbatim_text=list_abc_text,
                page_reference=page_ref,
                source_id=source_id,
                source_publication_date=source_publication_date,
                extraction_confidence=ConfidenceTier.HIGH,
            )
        )
    else:
        _logger.warning(
            "_extract_statewide_rule_candidates: "
            "could not find 'List A, B & C' table on p. 72"
        )

    return candidates


# ---------------------------------------------------------------------------
# T3: Section assembly + confidence pass
# ---------------------------------------------------------------------------


def _assemble_bear_sections(
    limited_rows: list[CpwBearRowExtraction],
    otc_pairs: list[tuple[CpwBearRowExtraction, str | None]],
    extracted_at: str,
    source_id: str,
) -> list[CpwBearSectionExtraction]:
    """Group bear rows (limited + OTC) into ``CpwBearSectionExtraction`` records.

    Section grouping key: ``(method_group, gmu_code, residency_scope, license_kind)``.

    Per S06.3 empty-GMU lesson: rows with empty ``gmu_code`` (unparseable
    hunt code) are disambiguated by page so they form per-page sections
    rather than coalescing across pages.  A NUL-prefixed key component is
    used (cannot collide with a real gmu_code).  The section's own
    ``gmu_code`` field is always taken from the rows (``""``) not the key.

    Confidence is assigned per-row via ``_assign_bear_row_confidence``
    BEFORE grouping so every row has a valid tier when the section is built.

    The per-section ``notes`` field is set from the OTC prerequisite note
    (Rule R14).  For a section all rows share the same license_kind, so the
    note from the first OTC pair in that group is representative.

    Returns a deterministically sorted list.
    """
    # section_map key → (first_page_ref, rows, note)
    section_map: dict[
        tuple[str, str, str, str],
        tuple[PageReference, list[CpwBearRowExtraction], str | None],
    ] = {}

    def _add_row(
        row: CpwBearRowExtraction,
        note: str | None,
    ) -> None:
        # Assign confidence before grouping.
        row["extraction_confidence"] = _assign_bear_row_confidence(row)

        # Garbage-row guard (Defect 2 / big_game._is_garbage_row analog):
        # A row with no parseable hunt code (gmu_code == "", hunt_code == "")
        # is a pdfplumber parsing artifact — a page-76 banner/legend footnote
        # spill or empty continuation row.  Even when pdfplumber puts non-empty
        # prose into ``valid_gmus`` (e.g. page-76 footnote text like "39, 46
        # See 'Land Closures …'"), the row is not a regulation row because it
        # has no hunt code at all.
        #
        # Preserved rows: any row with a non-empty ``hunt_code`` (i.e. a real
        # extracted code) passes through unconditionally.  The Plains OTC row
        # recovered via Rule R16 has hunt_code="B-E-087-U6-R" and gmu_code="087"
        # — it will NOT be dropped here.
        if (
            not row["hunt_code"].strip()
            and row["gmu_code"] == ""
        ):
            _logger.debug(
                "_assemble_bear_sections: dropping garbage row "
                "(no hunt code, no valid_gmus, empty hunt_code): %r",
                row,
            )
            return

        method_group = row["method_group"]
        gmu_code = row["gmu_code"]
        residency_scope = row["residency_scope"]
        license_kind = row["license_kind"]
        page_ref = row["page_reference"]

        # Disambiguate empty-gmu sections by page (S06.3 lesson).
        gmu_key = gmu_code or f"\x00unparsed-p{page_ref.get('page_num_1based', 0)}"
        key = (method_group, gmu_key, residency_scope, license_kind)

        if key not in section_map:
            section_map[key] = (page_ref, [], note)
        section_map[key][1].append(row)

    for row in limited_rows:
        _add_row(row, None)

    for row, note in otc_pairs:
        _add_row(row, note)

    # Build the section list.
    sections: list[CpwBearSectionExtraction] = []
    for (method_group, _gmu_key, residency_scope, license_kind), (
        first_page_ref,
        rows,
        note,
    ) in section_map.items():
        verbatim = _verbatim_text_for_bear_section(rows)
        sections.append(
            CpwBearSectionExtraction(
                source_id=source_id,
                species_group=_SPECIES_GROUP,
                method_group=method_group,
                gmu_code=rows[0]["gmu_code"],
                residency_scope=residency_scope,
                license_kind=license_kind,
                license_year=_LICENSE_YEAR,
                extracted_at=extracted_at,
                page_reference=first_page_ref,
                verbatim_text=verbatim,
                notes=note,
                rows=rows,
            )
        )

    sections.sort(key=_bear_sort_key)
    return sections


# ---------------------------------------------------------------------------
# T3: Base record list builder
# ---------------------------------------------------------------------------


def _build_base_records(
    pdf: object,
    extracted_at: str,
    source_id: str,
    source_publication_date: str,
    residency_scope: str = "both",
) -> list[dict]:  # type: ignore[type-arg]
    """Build the full flat list-of-records for the base artifact (Pass 1).

    Orchestrates limited extraction (T2) + OTC extraction (T3) + section
    assembly + confidence assignment + prose candidate extraction.

    Artifact shape decision (see module docstring §"Artifact shape decision"):
    Each element is a plain dict with a ``"record_type"`` discriminator key:
      ``"section"``               → ``CpwBearSectionExtraction`` (as dict)
      ``"reporting_obligation"``  → ``BearReportingObligationCandidate`` (as dict)
      ``"statewide_rule"``        → ``BearStatewideRuleCandidate`` (as dict)

    Section records come first (sorted by ``_bear_sort_key``), then
    reporting-obligation candidates, then statewide-rule candidates.
    This ordering is deterministic and downstream-friendly: S06.6 reads
    only ``"section"`` records; S06.9 reads only ``"reporting_obligation"``
    records; statewide rules are available at the end.

    Parameters
    ----------
    pdf:
        An open ``pdfplumber.PDF`` instance.
    extracted_at:
        ISO timestamp from the PDF manifest (ADR-001 determinism).
    source_id:
        ``SourceCitation.id`` for the brochure (``_SOURCE_ID``).
    source_publication_date:
        Publication date string from sources.yaml (for candidate provenance).
    residency_scope:
        Residency context for all rows.  CPW bear tables do not encode
        residency in the row data; all rows default to ``"both"``.
    """
    # --- Extract rows ---
    limited_rows = _extract_limited_rows(pdf, extracted_at, residency_scope)
    _logger.info(
        "_build_base_records: limited rows extracted: %d", len(limited_rows)
    )

    otc_pairs = _extract_otc_rows(pdf, extracted_at, residency_scope)
    otc_rows = [r for r, _ in otc_pairs]
    _logger.info(
        "_build_base_records: OTC rows extracted: %d", len(otc_rows)
    )

    # --- Assemble sections (assigns confidence per row) ---
    sections = _assemble_bear_sections(
        limited_rows, otc_pairs, extracted_at, source_id
    )
    _logger.info(
        "_build_base_records: sections assembled: %d", len(sections)
    )

    # --- Summary log ---
    total_rows = sum(len(s["rows"]) for s in sections)
    conf_counts: dict[str, int] = defaultdict(int)
    for s in sections:
        for r in s["rows"]:
            conf_counts[r["extraction_confidence"]] += 1
    limited_count = sum(
        len(s["rows"]) for s in sections if s["license_kind"] == "limited_draw"
    )
    otc_count = total_rows - limited_count
    _logger.info(
        "_build_base_records: %d sections, %d rows total "
        "(limited=%d OTC=%d) — confidence: high=%d medium=%d low=%d",
        len(sections),
        total_rows,
        limited_count,
        otc_count,
        conf_counts.get("high", 0),
        conf_counts.get("medium", 0),
        conf_counts.get("low", 0),
    )

    # --- Extract prose candidates ---
    inspection_candidate = _extract_mandatory_inspection_candidate(
        pdf, extracted_at, source_id, source_publication_date
    )
    statewide_candidates = _extract_statewide_rule_candidates(
        pdf, extracted_at, source_id, source_publication_date
    )

    # --- Fail-loud guards: prose candidate sets must not be empty ---
    # A brochure reformat that breaks the page-anchoring regexes must surface
    # here at extraction time, not produce a silently-incomplete artifact for
    # downstream S06.9 (reporting obligations) or S06.6 (statewide rules).
    # The current artifact has 1 reporting_obligation candidate and 2
    # statewide_rule candidates — these guards do NOT fire on current data.
    if inspection_candidate is None:
        raise PdfExtractionError(
            "_build_base_records: reporting-obligation candidate set is empty — "
            "'Mandatory Bear Inspections & Seals' prose could not be located on "
            "PDF p. 73.  A brochure reformat must be handled explicitly (ADR-001 fail-loud)."
        )
    if not statewide_candidates:
        raise PdfExtractionError(
            "_build_base_records: statewide-rule candidate set is empty — "
            "no statewide-rule candidates were extracted from PDF p. 72.  "
            "A brochure reformat must be handled explicitly (ADR-001 fail-loud)."
        )

    # --- Build flat list ---
    # Inject "record_type" into each section dict so downstream consumers can
    # filter by discriminator without special-casing the section/candidate split.
    # ``CpwBearSectionExtraction`` does not carry a ``record_type`` field
    # (sections are typed independently of candidates), so we add it here when
    # converting to a plain dict.  ``BearReportingObligationCandidate`` and
    # ``BearStatewideRuleCandidate`` already carry ``record_type`` as a field.
    records: list[dict] = []  # type: ignore[type-arg]
    for section in sections:
        section_dict = dict(section)
        section_dict["record_type"] = "section"
        records.append(section_dict)
    if inspection_candidate is not None:
        records.append(dict(inspection_candidate))
    for candidate in statewide_candidates:
        records.append(dict(candidate))

    return records


# ---------------------------------------------------------------------------
# T4: Three-pass correction merge
# ---------------------------------------------------------------------------

# Fields of CpwBearRowExtraction that a correction may legitimately target.
# A correction operation referencing any field NOT in this set raises a
# fail-loud PdfExtractionError so a future brochure with unexpected correction
# text cannot silently add arbitrary keys to the row dict.
#
# For CO 2026 V1 no correction targets any of these fields — the correction
# PDF (moose p.1 + elk muzzleloader p.2) contains no ``B-…`` hunt codes.
# The set is defined here so the validation path is exercised by tests even
# when the live run is inert.
_CORRECTABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "hunt_code",
        "unit",
        "valid_gmus",
        "list_value",
        "method_group",
        "residency_scope",
        "extras",
        "apply_by",
    }
)


class CorrectionConflictError(Exception):
    """Raised when two correction ops target the same (license_code, field) with equal publication_date."""


def _extract_base(
    pdf: object,
    extracted_at: str,
    brochure_citation: SourceCitationDict,
) -> list[dict]:  # type: ignore[type-arg]
    """Thin Pass-1 wrapper: build and return the base records list.

    Calls ``_build_base_records`` with the citation's id and publication_date
    and returns its flat list-of-records.

    ``pdf`` must be an already-open pdfplumber PDF instance.  The caller owns
    the ``with open_pdf(...)`` context manager lifecycle.
    """
    return _build_base_records(
        pdf=pdf,
        extracted_at=extracted_at,
        source_id=brochure_citation["id"],
        source_publication_date=brochure_citation["publication_date"],
    )


def _extract_correction(
    correction_pdf_path: Path,
    base_records: list[dict],  # type: ignore[type-arg]  # base_records: carried for API symmetry; consulted only when real bear-correction field-parsing is implemented (V1 inert path never reads it)
    correction_citation: SourceCitationDict,
    extracted_at: str,
) -> list[CorrectionOperation]:
    """Parse the FULL correction PDF and return any bear-targeting operations.

    Opens and parses both pages of the correction PDF via ``ingestion.lib.pdf``
    primitives (the verbatim word-grouping baseline; the synthetic-space layout
    flag is never set).  Scans every page's text for hunt codes
    that match the bear pattern (``B-…``).  For each bear-targeting line,
    attempts to build a ``CorrectionOperation``; for each non-bear code the
    page content is accumulated into the INFO summary.

    For CO 2026 the correction PDF has:
      page 1 — moose hunt-code corrections (``M-…`` species letter)
      page 2 — an elk muzzleloader correction (``E-M-…`` hunt codes)

    Neither page contains any ``B-…`` hunt code, so the function returns ``[]``
    and logs an INFO line such as::

        INFO: correction PDF parsed (2 pages); content: moose (p.1),
        elk muzzleloader E-M-... (p.2); 0 bear-targeting operations — inert

    This is the inert-confirmation pathway: the absence of bear operations is
    EVIDENCED by full parsing, not asserted by an early return.

    ``correction_citation`` is loaded via ``_load_citation_from_sources_yaml``
    before this call, which already runs the ADR-019 §Decision item 5
    document_type guard (``ValueError`` on non-allowed values).  The citation is
    passed in here (not re-loaded) so the guard fires exactly once in the
    caller path.

    Inert-confirmation is fully implemented and tested: for CO 2026 the
    correction PDF (moose p.1 + elk muzzleloader p.2) contains no ``B-…``
    bear codes, so ``operations == []`` is returned (inert path).

    A real bear-targeting correction fails loud (``PdfExtractionError``) —
    this is a deliberate V1 limitation per ADR-001 fail-loud.  Real
    bear-correction field-parsing is not implemented; the error forces the
    operator to implement it rather than silently accepting a sentinel op.

    Validates every operation's ``target_field`` against ``_CORRECTABLE_FIELDS``;
    an unknown field raises ``PdfExtractionError`` fail-loud.

    Parameters
    ----------
    correction_pdf_path:
        Path to the correction PDF on disk.
    base_records:
        The Pass-1 base records list (used to validate target_license_code
        against known hunt codes; ignored when operations is empty).
    correction_citation:
        Already-loaded SourceCitationDict for the correction (document_type
        guard already run by the caller's ``_load_citation_from_sources_yaml``
        call).
    extracted_at:
        ISO timestamp from the correction PDF's manifest.

    Returns
    -------
    list[CorrectionOperation]
        Empty list for the CO 2026 inert case.  Non-empty only when a future
        correction PDF targets a bear hunt code.
    """
    # Bear hunt-code fragment detector: matches B-<sex>-<gmu>-<season>-<method>
    # as an unanchored substring (same logic as _HUNT_CODE_FRAGMENT_RE but bear-specific).
    _BEAR_CODE_RE = re.compile(r"\bB-[A-Z]-\d{3,4}-[A-Z0-9]+-[A-Z]\b")

    page_summaries: list[str] = []
    operations: list[CorrectionOperation] = []

    with open_pdf(correction_pdf_path) as corr_pdf:
        # Determine page count; iter_pages is 1-based inclusive.
        num_pages = len(corr_pdf.pages)  # type: ignore[attr-defined]

        for page_num, page in iter_pages(corr_pdf, 1, num_pages):
            page_text = extract_text(page)
            if not page_text:
                page_summaries.append(f"(p.{page_num}: no text)")
                continue

            # Scan for bear hunt codes (B-…) on this page.
            bear_codes_found = _BEAR_CODE_RE.findall(page_text)

            if bear_codes_found:
                # This page targets bear rows — V1 does NOT implement real
                # bear-correction field parsing.  Raising here is ADR-001
                # fail-loud: a silent sentinel CorrectionOperation would
                # produce a hunt_code self-assignment that mis-handles the
                # correction rather than surfacing it for human review.
                #
                # If a future CO correction PDF genuinely targets a B-… hunt
                # code, this error fires, the operator investigates the
                # correction prose, implements field-level parsing, and removes
                # this guard.  Do NOT remove this guard without implementing
                # the full field-parse path.
                raise PdfExtractionError(
                    f"_extract_correction: correction PDF page {page_num} contains "
                    f"bear hunt code(s) {bear_codes_found!r} — real bear-correction "
                    f"field-parsing is not implemented for V1 and must be added "
                    f"before such a correction can be ingested (ADR-001 fail-loud). "
                    f"Implement field-level parsing for each bear correction field "
                    f"before re-running."
                )
            else:
                # No bear codes on this page — gather a short content summary
                # for the INFO log (first ~80 chars of meaningful text).
                summary_text = re.sub(r"\s+", " ", page_text).strip()[:80]
                page_summaries.append(f"non-bear content (p.{page_num}): {summary_text!r}")

    # Emit the evidenced INFO line regardless of whether operations is empty.
    _logger.info(
        "_extract_correction: correction PDF parsed (%d page(s)); content summary: %s; "
        "%d bear-targeting operation(s) — %s",
        num_pages,
        " | ".join(page_summaries),
        len(operations),
        "inert for black bear" if not operations else "ACTIVE — bear rows will be updated",
    )

    return operations


def _merge_with_corrections(
    base_records: list[dict],  # type: ignore[type-arg]
    operations: list[CorrectionOperation],
    brochure_source_id: str,
) -> list[dict]:  # type: ignore[type-arg]
    """Merge base records with correction operations using three-stage arbitration.

    For CO 2026 ``operations`` is always ``[]`` (inert-confirmation pathway).
    The function returns a deep copy of *base_records* with ``applied_correction``
    and ``supersedes`` fields injected into every ``"section"`` record's rows:

      ``applied_correction=False``  — row was not touched by any correction op
      ``supersedes=None``           — no superseded source

    When operations IS non-empty (future non-inert case), the three stages are:

      Stage 1 — per-(target_license_code, target_field) arbitration:
        For each unique (code, field) key, select the winning op by MAX
        ``publication_date``.  Raise ``CorrectionConflictError`` on equal-date ties
        (ADR-017-aligned; same doc-type same-date same-cell = conflict).

      Stage 2 — apply field-level value change to the matched row.

      Stage 3 — row-level provenance + confidence demotion:
        Fire ``demote_one_tier`` EXACTLY ONCE per touched row (ADR-017 §4 single-
        step rule).  Set ``applied_correction=True``, ``supersedes`` to
        ``brochure_source_id``.  Row-level source attribution uses the
        MAX-date winning op across all ops touching the row; equal-date ties
        broken by lexicographically smallest ``source_id`` (deterministic).

    Parameters
    ----------
    base_records:
        Pass-1 flat list-of-records from ``_build_base_records``.
    operations:
        Pass-2 list of ``CorrectionOperation`` dicts (may be empty).
    brochure_source_id:
        The base brochure's ``SourceCitation.id`` (written into ``supersedes``
        on touched rows so downstream consumers know which source was superseded).

    Returns
    -------
    list[dict]
        Pass-3 merged flat list-of-records.  Each ``"section"`` record's rows
        carry ``applied_correction`` (bool) and ``supersedes`` (str|None).
        Non-section records are passed through unchanged.
    """
    # Deep-copy so the original base_records stays immutable.
    merged: list[dict] = copy.deepcopy(base_records)  # type: ignore[type-arg]

    # Inject applied_correction / supersedes into every section row (inert default).
    for record in merged:
        if record.get("record_type") == "section":
            for row in record.get("rows", []):
                row["applied_correction"] = False
                row["supersedes"] = None

    if not operations:
        # Inert case (CO 2026): return base unchanged.
        return merged

    # --- Stage 1: per-cell arbitration ---
    # Build a map from (target_license_code, target_field) → [ops].
    ops_by_target: dict[tuple[str, str], list[CorrectionOperation]] = {}
    for op in operations:
        op_field = op["target_field"]
        if op_field not in _CORRECTABLE_FIELDS:
            raise PdfExtractionError(
                f"_merge_with_corrections: operation targets unknown "
                f"CpwBearRowExtraction field {op_field!r}; "
                f"valid fields are {sorted(_CORRECTABLE_FIELDS)}"
            )
        key = (op["target_license_code"], op_field)
        ops_by_target.setdefault(key, []).append(op)

    # For each cell, select the winning op by MAX publication_date.
    winning_op_by_cell: dict[tuple[str, str], CorrectionOperation] = {}
    for (code, field), ops in ops_by_target.items():
        max_date = max(op["publication_date"] for op in ops)
        winners = [op for op in ops if op["publication_date"] == max_date]
        if len(winners) > 1:
            raise CorrectionConflictError(
                f"hunt_code={code!r} field={field!r}: equal publication_date "
                f"{max_date!r} for source_ids "
                f"{[op['source_id'] for op in winners]}"
            )
        winning_op_by_cell[(code, field)] = winners[0]

    # --- Stage 2: apply field-level value changes ---
    # Build a row index by hunt_code across all section records.
    row_index: dict[str, dict] = {}  # type: ignore[type-arg]
    for record in merged:
        if record.get("record_type") == "section":
            for row in record.get("rows", []):
                hc = row.get("hunt_code", "")
                if hc:
                    row_index[hc] = row

    for (code, field), winning_op in winning_op_by_cell.items():
        row = row_index.get(code)
        if row is None:
            raise PdfExtractionError(
                f"_merge_with_corrections: correction targets unknown hunt_code "
                f"{code!r} (not found in base records)"
            )
        row[field] = winning_op["new_value"]

    # --- Stage 3: row-level provenance + confidence demotion (exactly once per touched row) ---
    # Group winning ops by which hunt_code they touch.
    code_touched_ops: dict[str, list[CorrectionOperation]] = {}
    for (code, _field), winning_op in winning_op_by_cell.items():
        code_touched_ops.setdefault(code, []).append(winning_op)

    for code, winning_ops in code_touched_ops.items():
        row = row_index.get(code)
        if row is None:
            continue  # already raised above in Stage 2; guard for safety
        # Two-pass: max date, then lex-smallest source_id to break date ties.
        row_max_date = max(op["publication_date"] for op in winning_ops)
        row_date_ties = [op for op in winning_ops if op["publication_date"] == row_max_date]
        row_winner = min(row_date_ties, key=lambda op: op["source_id"])

        row["applied_correction"] = True
        row["supersedes"] = brochure_source_id
        row["source_id"] = row_winner["source_id"]
        row["source_publication_date"] = row_winner["publication_date"]
        # ADR-017 §4: fire demote_one_tier EXACTLY ONCE per touched row.
        current_conf = row.get("extraction_confidence", "")
        if current_conf:
            row["extraction_confidence"] = demote_one_tier(
                ConfidenceTier(current_conf)
            )

    return merged


# ---------------------------------------------------------------------------
# Citation / manifest helpers
# ---------------------------------------------------------------------------


def _load_citation_from_sources_yaml(citation_id: str) -> SourceCitationDict:
    """Load a single SourceCitation entry from sources.yaml by id.

    Fail-loud per ADR-001: raises ``PdfExtractionError`` if the id is not
    found, ``publication_date`` is missing/malformed, or ``document_type``
    is not in ``_VALID_DOCUMENT_TYPES`` (ADR-019 §Decision item 5 guard —
    any non-``{annual_regulations, correction}`` value requires an ADR-019
    amendment before participation).
    """
    with _SOURCES_YAML.open() as fh:
        data = yaml.safe_load(fh)
    entries = data.get("pdfs", [])
    for entry in entries:
        if entry.get("id") == citation_id:
            # ADR-019 §Decision item 5: document_type guard.
            doc_type = entry.get("document_type")
            if doc_type not in _VALID_DOCUMENT_TYPES:
                raise ValueError(
                    f"sources.yaml entry '{citation_id}' has document_type="
                    f"{doc_type!r} which is not in the allowed set "
                    f"{sorted(_VALID_DOCUMENT_TYPES)!r}. "
                    f"Amend ADR-019 before adding a new document_type."
                )
            pub_date = entry.get("publication_date")
            if not pub_date or not isinstance(pub_date, str):
                raise PdfExtractionError(
                    f"sources.yaml entry '{citation_id}' missing or non-string "
                    f"publication_date (got {pub_date!r})"
                )
            # Validate ISO-8601 date.
            try:
                datetime.date.fromisoformat(pub_date)
            except ValueError as exc:
                raise PdfExtractionError(
                    f"sources.yaml entry '{citation_id}' has unparseable "
                    f"publication_date {pub_date!r}: {exc}"
                ) from exc
            return cast(
                SourceCitationDict,
                {
                    "id": entry["id"],
                    "agency": entry["agency"],
                    "title": entry["title"],
                    "url": entry["url"],
                    "publication_date": pub_date,
                    "document_type": doc_type,
                },
            )
    raise PdfExtractionError(
        f"sources.yaml has no entry with id={citation_id!r}"
    )


def _load_extracted_at_from_manifest(pdf_path: Path) -> str:
    """Return ``fetched_at`` from the S06.1 PDF manifest for *pdf_path*.

    Manifest path convention: same directory as the PDF, stem +
    ``"-pdf-manifest.json"``.  Raises ``PdfExtractionError`` if the manifest
    is absent or the ``fetched_at`` field is missing — ADR-001 fail-loud;
    falling back to ``datetime.datetime.now()`` would silently re-introduce
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
            f"manifest at {manifest_path} has invalid 'fetched_at' value: "
            f"{fetched_at!r} — expected a non-empty ISO timestamp string"
        )
    return fetched_at


# ---------------------------------------------------------------------------
# T5: Three-pass orchestrator
# ---------------------------------------------------------------------------


def extract(
    pdf_path: Path = _PDF_PATH,
    correction_path: Path = _CORRECTION_PATH,
) -> tuple[list[dict], list[CorrectionOperation], list[dict]]:  # type: ignore[type-arg]
    """Run the three-pass bear extraction and return all three artifact lists.

    Pass 1 — base extraction from the CPW Big Game brochure (annual_regulations):
        Opens the brochure, loads its citation + extracted_at timestamp, then
        calls ``_extract_base`` → ``_build_base_records`` to produce the flat
        list-of-records with ``record_type`` ∈ {``"section"``,
        ``"reporting_obligation"``, ``"statewide_rule"``}.

    Pass 2 — correction-PDF parsing (correction):
        Loads the correction citation via ``_load_citation_from_sources_yaml``
        (this fires the ADR-019 ``document_type`` fail-loud guard), opens the
        correction PDF, and calls ``_extract_correction`` which scans every page
        for bear hunt codes (``B-…``).  For CO 2026 the correction PDF is
        moose + elk only — ``operations`` returns ``[]`` (inert-confirmation
        pathway).  The inert INFO line is emitted by ``_extract_correction``
        regardless.

    Pass 3 — merge:
        Calls ``_merge_with_corrections(base_records, operations, brochure_source_id)``
        which deep-copies the base records, injects ``applied_correction=False``
        and ``supersedes=None`` on every section row, and returns the merged
        list (byte-identical to base for the CO 2026 inert case).

    Returns
    -------
    tuple of (base_records, operations, merged_records):
        base_records   — Pass-1 flat list-of-records (``black-bear-2026-base.json``)
        operations     — Pass-2 list of ``CorrectionOperation`` dicts
                         (``corrections-2026-02-19.json``; ``[]`` for inert CO 2026)
        merged_records — Pass-3 merged flat list-of-records (``black-bear-2026.json``;
                         S06.6–S06.9 consume ONLY this artifact)

    Artifact contents:
        ``black-bear-2026-base.json``
            Pass-1 records from the brochure only (no correction applied).
            ``"section"`` records carry ``extraction_confidence`` but NOT
            ``applied_correction`` / ``supersedes`` (those are Pass-3 fields).

        ``corrections-2026-02-19.json``
            Pass-2 ``CorrectionOperation`` list.  An empty list ``[]`` is
            written (not skipped) to evidence the inert-confirmation finding.

        ``black-bear-2026.json``
            Pass-3 merged records.  ``"section"`` rows carry the additional
            ``applied_correction`` (bool) and ``supersedes`` (str|None) fields.
            This is the authoritative artifact for downstream ingestion.

    Fail-loud cases:
        - PDF or correction PDF not found → ``PdfExtractionError`` from ``open_pdf``.
        - Manifest not found / invalid → ``PdfExtractionError`` from
          ``_load_extracted_at_from_manifest``.
        - ``document_type`` not in allowed set → ``ValueError`` from
          ``_load_citation_from_sources_yaml``.
        - ``CorrectionConflictError`` from ``_merge_with_corrections`` when two
          correction ops for the same (license_code, field) have equal dates.
    """
    # --- Pass 1: base extraction ---
    brochure_citation = _load_citation_from_sources_yaml(_SOURCE_ID)
    extracted_at = _load_extracted_at_from_manifest(pdf_path)

    with open_pdf(pdf_path) as pdf:
        base_records = _extract_base(pdf, extracted_at, brochure_citation)

    _logger.info(
        "extract: Pass 1 complete — %d base records (%d sections)",
        len(base_records),
        sum(1 for r in base_records if r.get("record_type") == "section"),
    )

    # --- Pass 2: correction parsing (ADR-019 document_type guard fires here) ---
    correction_citation = _load_citation_from_sources_yaml(_CORRECTION_SOURCE_ID)
    correction_extracted_at = _load_extracted_at_from_manifest(correction_path)

    operations = _extract_correction(
        correction_pdf_path=correction_path,
        base_records=base_records,
        correction_citation=correction_citation,
        extracted_at=correction_extracted_at,
    )

    _logger.info(
        "extract: Pass 2 complete — %d correction operation(s)",
        len(operations),
    )

    # --- Pass 3: merge ---
    merged_records = _merge_with_corrections(
        base_records=base_records,
        operations=operations,
        brochure_source_id=brochure_citation["id"],
    )

    _logger.info(
        "extract: Pass 3 complete — %d merged records",
        len(merged_records),
    )

    return base_records, operations, merged_records


# ---------------------------------------------------------------------------
# T5: CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the CO Black Bear extractor.

    Runs the three-pass extraction (base → correction → merge) and writes
    three deterministic JSON artifacts via ``write_extraction_artifact``:

        ``ingestion/states/colorado/extracted/black-bear-2026-base.json``
            Pass 1 flat list-of-records from the brochure.

        ``ingestion/states/colorado/extracted/corrections-2026-02-19.json``
            Pass 2 correction-operation list (empty ``[]`` for CO 2026 — inert).

        ``ingestion/states/colorado/extracted/black-bear-2026.json``
            Pass 3 merged artifact; S06.6–S06.9 consume this file.

    Usage::

        python states/colorado/extract_black_bear.py
        python states/colorado/extract_black_bear.py --dry-run

    Flags:
        ``--dry-run``   Run extraction + log summary; write NO files.
                        Use this to verify the extractor without committing
                        artifacts (T6 owns the canonical artifact write + commit).
    """
    parser = argparse.ArgumentParser(
        description="Extract CO Black Bear regulations from the CPW Big Game brochure",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run extraction and log summary without writing any output files.",
    )
    args = parser.parse_args(argv)

    # Configure logging only if no handlers are already registered (avoids
    # double-init when this module is imported by tests or orchestrators).
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

    if not _PDF_PATH.exists():
        _logger.error(
            "CPW Big Game PDF not found at %s — run fetch_pdfs.py first", _PDF_PATH
        )
        return 1
    if not _CORRECTION_PATH.exists():
        _logger.error(
            "Correction PDF not found at %s — run fetch_pdfs.py first", _CORRECTION_PATH
        )
        return 1

    try:
        base_records, operations, merged_records = extract()
    except (PdfExtractionError, CorrectionConflictError, ValueError) as exc:
        _logger.error("extraction failed: %s", exc)
        return 2

    # --- Run summary ---
    section_records = [r for r in merged_records if r.get("record_type") == "section"]
    total_rows = sum(len(s.get("rows", [])) for s in section_records)

    # Row counts by license_kind.
    limited_rows = sum(
        len(s.get("rows", []))
        for s in section_records
        if s.get("license_kind") == "limited_draw"
    )
    add_on_otc_rows = sum(
        len(s.get("rows", []))
        for s in section_records
        if s.get("license_kind") == "add_on_otc"
    )
    otc_rows = sum(
        len(s.get("rows", []))
        for s in section_records
        if s.get("license_kind") == "over_the_counter"
    )
    private_land_otc_rows = sum(
        len(s.get("rows", []))
        for s in section_records
        if s.get("license_kind") == "private_land_otc"
    )
    plains_otc_rows = sum(
        len(s.get("rows", []))
        for s in section_records
        if s.get("license_kind") == "plains_otc"
    )

    # Method-group row counts.
    method_counts: Counter[str] = Counter(
        r["method_group"]
        for s in section_records
        for r in s.get("rows", [])
    )

    # Confidence distribution across all merged section rows.
    conf_dist: Counter[str] = Counter(
        r["extraction_confidence"]
        for s in section_records
        for r in s.get("rows", [])
    )

    # Inert-correction evidence count.
    bear_ops_count = len(operations)

    _logger.info(
        "summary: %d sections, %d rows total",
        len(section_records),
        total_rows,
    )
    _logger.info(
        "summary: by license_kind — limited=%d add_on_otc=%d over_the_counter=%d "
        "private_land_otc=%d plains_otc=%d",
        limited_rows,
        add_on_otc_rows,
        otc_rows,
        private_land_otc_rows,
        plains_otc_rows,
    )
    _logger.info(
        "summary: by method_group — archery=%d muzzleloader=%d rifle=%d",
        method_counts.get("archery", 0),
        method_counts.get("muzzleloader", 0),
        method_counts.get("rifle", 0),
    )
    _logger.info(
        "summary: confidence distribution — high=%d medium=%d low=%d",
        conf_dist.get("high", 0),
        conf_dist.get("medium", 0),
        conf_dist.get("low", 0),
    )
    _logger.info(
        "summary: correction operations targeting bear: %d — %s",
        bear_ops_count,
        "inert" if bear_ops_count == 0 else "ACTIVE — bear rows updated",
    )

    if args.dry_run:
        _logger.info("--dry-run: extraction complete; no files written")
        return 0

    # --- Write artifacts (non-dry-run only) ---
    _BASE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_extraction_artifact(base_records, _BASE_OUTPUT_PATH)
    _logger.info("wrote %d base records to %s", len(base_records), _BASE_OUTPUT_PATH)

    write_extraction_artifact(operations, _CORRECTIONS_OUTPUT_PATH)
    _logger.info(
        "wrote %d correction operation(s) to %s",
        len(operations),
        _CORRECTIONS_OUTPUT_PATH,
    )

    write_extraction_artifact(merged_records, _MERGED_OUTPUT_PATH)
    _logger.info(
        "wrote %d merged records to %s", len(merged_records), _MERGED_OUTPUT_PATH
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
