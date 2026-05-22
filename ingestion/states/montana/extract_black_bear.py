"""
Extract the Montana Black Bear regulations booklet (16 pages, 2026/2027 cycle)
into structured JSON for downstream ingestion (S03.6–S03.9). Walks the BMU
regulation table on pp. 9–12 (35 BMU columns, transposed layout — see
"Text reversal" rule below), the closure-rules prose on p. 7, and the
region-specific reporting prose on p. 7. A separate correction PDF (1 page,
2026-03-18) is parsed for the hound-training-season-column removal. Three
artifacts are emitted: ``black-bear-2026-base.json`` (booklet only),
``corrections-2026-03-18.json`` (correction operations), and
``black-bear-2026.json`` (per-cell date-arbitrated merge — what S03.6–S03.9
consume).

ADR references:
  ADR-001  Authority preserved, not replaced — fail loud; no invented values.
  ADR-005  Python ingestion / TypeScript serving language split.
  ADR-008  Verbatim regulation text — section-level ``verbatim_text`` retains
           pdfplumber's word-grouped output without additional normalization.
           Only the structured ``rows`` payload uses the cleanup regexes below.
  ADR-014  ``SourceCitation.document_type`` — correction PDF carries
           ``document_type='correction'`` and a ``supersedes`` reference to
           the booklet citation id.
  ADR-017  Confidence calibration + parent-inheritance rule — per-row
           ``extraction_confidence`` is assigned here; correction-touched rows
           are demoted one tier via ``demote_one_tier``.
  ADR-018  E03 schema additions (``license_season`` link table,
           ``geometry.legal_description``, ``geometry.kind='state'`` value).

Text-reversal pre-step (unique to this PDF — the headline cleanup rule):

  The Black Bear PDF prints the BMU regulation table as physically rotated text:
  pdfplumber returns each cell with line order and character order both reversed
  (e.g., "Sep.15-Nov.29" extracts as "92.voN-51.peS"). page.rotation reports 0.
  EVERY cell value extracted from the BMU table must be passed through
  ``_reverse_cell_text`` BEFORE any normalization. Tests in test_extract_black_bear.py
  ::TestReverseCellText lock this behavior.

Cleanup rules (applied only to structured ``rows`` cells, never to
``verbatim_text``):

  Text reversal (applied first, only to BMU table cells from pp. 9–12):
      Split on ``\\n``, reverse line order, reverse each line's characters,
      re-join with ``\\n``. Implemented as ``_reverse_cell_text(s)``. Closure
      prose (p. 7) and the correction PDF do NOT need reversal — they are
      normal-orientation text.

  Cell padding (applied after reversal):
      ``re.sub(r'\\s{3,}', ' ', cell.strip())``
      Collapses internal runs of 3+ whitespace characters and trims leading /
      trailing whitespace. Identical semantics to ``extract_dea._normalize_cell``.

  Empty cells:
      ``_normalize_cell`` returns ``None`` (not ``""``) for cells that are
      ``None``, empty, or whitespace-only. Per ADR-001, absent data is
      represented as explicit null — an empty string is ambiguous.

  Section-level ``verbatim_text`` retains source whitespace + characters:
      Only the structured row payload uses the cleanup regexes above. The
      ``verbatim_text`` field at the section level carries pdfplumber's output
      without additional normalization per ADR-008.

  Statewide-rule body whitespace collapse (page-2 right-column prose only):
      ``re.sub(r"\\s+", " ", body)``
      Scope: the substring of page-2 right-column text bounded between
      ``_BEAR_ID_START_RE`` and ``_BEAR_ID_END_RE`` anchors only.
      Rationale: extras-only whitespace collapse. pdfplumber's word-grouping
      can introduce multi-space or newline runs within paragraph prose; the
      collapse is ADR-008-safe because paraphrase prevention applies to lexical
      content and numeric tokens, not incidental whitespace runs.
      Tests that lock this rule:
        ``TestExtractStatewideRules::test_whitespace_collapse_extras_only``

  Dash sentinel:
      ``-`` in season/quota cells means "absent" — handled by
      ``_is_season_cell_absent``, identical semantics to ``extract_dea``.

  Quota-cell word order (T7 discovery — unique to the rotated table):
      pdfplumber produces at least three word orderings for the same quota
      phrase depending on how it splits multi-line cells during extraction
      of the rotated table.  ``_parse_quota_cell`` tries the primary regex
      (``_QUOTA_CELL_REGEX``, standard order ``"= N Female subquota"``) first,
      then falls back to component extraction (``_QUOTA_COUNT_REGEX`` +
      ``_QUOTA_KIND_REGEX``) which is word-order-invariant.  The component
      fallback fires for Pattern B (``"= N quota Harvest"``) and Pattern C
      (``"quota = Harvest N"``) cases — both observed in the live 2026 PDF.

Anti-patterns (full list in ``.roughly/known-pitfalls.md`` updated by T16):
  - Do NOT iterate ``pdfplumber.Table.rows`` as if rows were BMUs — rows are
    field types; columns are BMUs.
  - Do NOT use first-observation-wins on region tracking — track
    ``current_region`` left-to-right as columns are scanned.
  - Do NOT call ``int(quota_cell)`` — quota cells embed subquota type
    (``"= 4 Female subquota"``); use the regex parser in T7.
  - Do NOT ignore the Permit Managed columns silently — explicitly skip them
    in T6 (V1) with a ``_logger.info`` for traceability.
  - Do NOT apply text reversal to closure prose (p. 7) or the correction PDF —
    only the BMU table cells on pp. 9–12 are rotated.
"""

# State-specific module — must NOT import from ingestion.states.<other_state>.
# Cross-state imports violate ADR-005 isolation (each state adapter is fully
# self-contained). The state-agnostic guard test in T15 enforces this via AST
# walk at CI time.

import argparse  # noqa: F401
import copy  # noqa: F401
import datetime
import json  # noqa: F401
import logging
import re
from collections.abc import Iterator  # noqa: F401
from pathlib import Path
from typing import TypedDict, cast  # noqa: F401 — TypedDict used by exported TypedDicts; cast used in _load_citation_from_sources_yaml

import yaml  # noqa: F401  # for sources.yaml citation lookup
from ingestion.lib.pdf import (
    ConfidenceTier,  # noqa: F401
    PageReference,  # noqa: F401
    PdfDocument,  # noqa: F401
    PdfExtractionError,  # noqa: F401
    TableMatch,  # noqa: F401
    demote_one_tier,  # noqa: F401
    extract_tables,  # noqa: F401
    extract_text,  # noqa: F401
    iter_pages,  # noqa: F401
    open_pdf,  # noqa: F401
)

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MONTANA_DIR = _REPO_ROOT / "ingestion" / "states" / "montana"
_SOURCES_YAML = _MONTANA_DIR / "sources.yaml"

_BOOKLET_PDF_FILENAME = "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf"
_CORRECTION_PDF_FILENAME = "mt-fwp-black-bear-2026-correction-2026-03-18-2026-03-18.pdf"
_BOOKLET_PDF_PATH = _MONTANA_DIR / "fixtures" / _BOOKLET_PDF_FILENAME
_CORRECTION_PDF_PATH = _MONTANA_DIR / "fixtures" / _CORRECTION_PDF_FILENAME

_OUTPUT_DIR = _MONTANA_DIR / "extracted"
_BASE_OUTPUT_PATH = _OUTPUT_DIR / "black-bear-2026-base.json"
_CORRECTION_OUTPUT_PATH = _OUTPUT_DIR / "corrections-2026-03-18.json"
_MERGED_OUTPUT_PATH = _OUTPUT_DIR / "black-bear-2026.json"

# Citation ids in sources.yaml. T2 reads sources.yaml at runtime; these are
# documented constants for traceability and for the merge-pass guards.
_BOOKLET_CITATION_ID = "mt-fwp-black-bear-2026-booklet"
_CORRECTION_CITATION_ID = "mt-fwp-black-bear-2026-correction-2026-03-18"

# BMU table is on pp. 9-12 (NOT pp. 10-11 as the spec claims). Verified
# against the live PDF during S03.4 discovery 2026-05-10.
_BMU_TABLE_PAGES = (9, 12)

# Closure prose + reporting prose page (right column).
_CLOSURE_PROSE_PAGE = 7
# "Obtain a License" / Bear ID Test page (right column, same letter-page geometry).
_STATEWIDE_RULES_PAGE = 2
# Right-column bbox for two-column page layouts (left col 0–306, right
# col 306–612). 612 is the standard letter-size width in PDF units.
_RIGHT_COLUMN_BBOX: tuple[float, float, float, float] = (306.0, 0.0, 612.0, 792.0)

_LICENSE_YEAR = 2026
_SPECIES_GROUP = "black_bear"

# Fail-loud guard threshold: 35 BMUs expected; <30 is catastrophic regression.
_MIN_EXPECTED_BMU_COUNT = 30
_EXPECTED_BMU_COUNT = 35

# Quota-closure BMUs (8 — NOT 9 as spec claims; BMU 530 does NOT appear in
# the 2026 PDF anywhere, neither in the table nor in the closure prose).
_QUOTA_CLOSURE_BMUS: tuple[int, ...] = (411, 420, 440, 450, 510, 520, 600, 700)

# Female sub-quota BMUs (4); 37% threshold; "after May 31" temporal anchor
# stays in verbatim_rule per V1 deferral (see closure-temporal-anchors.md).
_FEMALE_SUBQUOTA_BMUS: tuple[int, ...] = (300, 301, 319, 580)
_FEMALE_SUBQUOTA_THRESHOLD_PERCENT = 37.0

# Transposed-table row indices (verified 2026-05-10 against live PDF).
# Row 0 is the topmost row in pdfplumber's Table.extract() output.
_ROW_OPPORTUNITY = 0       # per-BMU descriptive text + REGION N markers
_ROW_GENERAL_SEASON = 1
_ROW_ARCHERY_SEASON = 2
_ROW_SPRING_SEASON = 3
_ROW_HOUND_TRAINING = 4    # the column the correction removes
_ROW_HOUND_NR_LICENSE = 5
_ROW_HOUND_NR_MAX = 6
_ROW_FALL_QUOTA = 7
_ROW_SPRING_QUOTA = 8
_ROW_BMU_ID = 9            # the BMU number identifier row

# Region marker regex (case-sensitive; the PDF prints "REGION 1", "REGION 2",
# etc. as multi-line text in Row 0 — after reversal the marker reads
# "REGION N" with possibly an embedded space or newline).
_REGION_MARKER_REGEX = re.compile(r"REGION\s+(?P<num>[1-7])\b")

# Permit Managed sub-table marker (Row 0 cell value after reversal).
# Skip these columns in V1 — they have different row semantics.
_PERMIT_MANAGED_REGEX = re.compile(r"Permit\s+Managed\s+Opportunities", re.IGNORECASE)

# Quota-cell parsing uses two separate component extractors rather than a single
# monolithic regex.  pdfplumber's multi-line extraction of the rotated BMU table
# produces at least three distinct word orderings for the same logical phrase
# ("= N Female subquota" / "= N Harvest quota"):
#
#   Pattern A (standard):  "= N Female subquota"  or "= N Harvest quota"
#   Pattern B (inverted):  "= N quota Female"     or "= N quota\nHarvest"
#   Pattern C (reversed):  "quota\n=\nFemale\nN"  or "quota\n=\nHarvest\nN"
#
# Rather than encoding all orderings in one regex, _parse_quota_cell extracts
# the numeric count and the type keyword independently from the flattened cell text.
_QUOTA_COUNT_REGEX = re.compile(r"(?<!=)\b(?P<n>\d+)\b")  # first standalone integer
_QUOTA_KIND_REGEX = re.compile(r"\b(?P<kind>Female|Harvest)\b", re.IGNORECASE)

# Keep _QUOTA_CELL_REGEX for backwards-compatibility with tests that reference it;
# it still handles Pattern A and is tried first by _parse_quota_cell.
_QUOTA_CELL_REGEX = re.compile(
    r"=\s*(?P<n>\d+)\s+(?P<kind>Female|Harvest)\s+(?:sub)?quota",
    re.IGNORECASE,
)

# BMU number regex (Row 9 cell after reversal — three digits with optional
# trailing asterisk). The asterisk is a footnote marker in the PDF for
# female-sub-quota BMUs (300, 301, 319, 580); group(1) captures the 3-digit
# id without the asterisk.
_BMU_NUMBER_REGEX = re.compile(r"^(\d{3})\*?$")

# ---------------------------------------------------------------------------
# T2: TypedDicts for output JSON shape + citation / manifest helpers
# ---------------------------------------------------------------------------


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


class BmuQuotaCell(TypedDict):
    """Parsed quota-cell value (from "= 4 Female subquota" or "= 18 Harvest quota")."""

    count: int | None
    kind: str | None  # "female_subquota" | "harvest_quota" | None (= "-" sentinel)
    verbatim: str     # the raw cell text (post-reversal, pre-normalize)


class BmuRowExtraction(TypedDict):
    bmu_number: int
    hd_region: str  # "R1".."R7"
    opportunity: str | None
    general_season: str | None
    archery_only_season: str | None
    spring_season: str | None
    hound_training_season: str | None
    hound_nr_license: str | None
    hound_nr_max: int | None
    fall_quota: BmuQuotaCell
    spring_quota: BmuQuotaCell
    page_reference: PageReference
    verbatim_text: str
    extraction_confidence: ConfidenceTier
    source_id: str                # citation id from sources.yaml
    source_publication_date: str  # ISO date from sources.yaml
    applied_correction: bool      # set True in merged artifact for correction-touched rows
    supersedes: str | None        # set in merged artifact for correction-touched rows


class ClosurePredicateCandidate(TypedDict):
    bmu_numbers: list[int]
    kind: str                           # "quota_threshold" | "sex_threshold"
    threshold_percent: float | None
    threshold_sex: str | None           # "female" | None
    notification_channel: str           # "agency_phone"
    observation_channel: str | None     # "mandatory_reporting" | None
    verbatim_rule: str
    page_reference: PageReference
    source_id: str
    source_publication_date: str
    extraction_confidence: ConfidenceTier  # "medium" per ADR-017 prose interpretation


class ReportingObligationCandidate(TypedDict):
    region_scope: str   # "STATEWIDE" | "R1" | "R2-7"
    kind_hint: str      # "harvest_report" | "tooth_submission" | "hide_skull_presentation"
    deadline_hint: str  # "48 hours" | "10 days"
    verbatim_rule: str
    page_reference: PageReference
    source_id: str
    source_publication_date: str
    extraction_confidence: ConfidenceTier


class StatewideRuleCandidate(TypedDict):
    """Carries statewide pre-purchase prerequisites (e.g., Bear ID Test) extracted from prose outside the BMU table."""

    rule_hint: str
    verbatim_text: str
    page_reference: PageReference
    source_id: str
    source_publication_date: str
    extraction_confidence: ConfidenceTier


class CorrectionOperation(TypedDict):
    """A single cell-level correction operation parsed from the correction PDF prose."""

    target_bmu: int                     # which BMU this op addresses
    target_field: str                   # e.g., "hound_training_season"
    change: str                         # "remove" | "set" | "replace"
    new_value: str | None               # None for "remove"
    verbatim_correction_text: str       # source sentence from correction PDF
    source_id: str                      # correction citation id
    source_publication_date: str        # 2026-03-18


class BlackBearBaseExtraction(TypedDict):
    """Pass-1 base extraction artifact (booklet only, pre-correction-merge)."""

    state: str
    species_group: str
    license_year: int
    schema_version: int
    extracted_at: str
    source: SourceCitationDict
    rows: list[BmuRowExtraction]
    closures: list[ClosurePredicateCandidate]
    reporting_obligations: list[ReportingObligationCandidate]
    statewide_rules: list[StatewideRuleCandidate]


class CorrectionExtraction(TypedDict):
    """Pass-2 correction artifact (correction PDF parsed into operations)."""

    extracted_at: str
    source: SourceCitationDict
    operations: list[CorrectionOperation]


class BlackBearMergedExtraction(TypedDict):
    """Pass-3 merged artifact — what S03.6–S03.9 consume."""

    state: str
    species_group: str
    license_year: int
    schema_version: int
    extracted_at: str
    sources: list[SourceCitationDict]    # both booklet and correction citations
    rows: list[BmuRowExtraction]         # rows with applied_correction tags + demoted confidence
    closures: list[ClosurePredicateCandidate]
    reporting_obligations: list[ReportingObligationCandidate]
    statewide_rules: list[StatewideRuleCandidate]


def _load_citation_from_sources_yaml(citation_id: str) -> SourceCitationDict:
    """Load a single SourceCitation entry from sources.yaml by id.

    Fail-loud per ADR-001: if the id is missing, or publication_date is
    missing/unparseable as ISO-8601, raise PdfExtractionError. This is
    the gate referenced in spec § "Date-collision tiebreaker and
    missing-date handling": malformed dates never reach the merge stage.
    """
    with _SOURCES_YAML.open() as f:
        data = yaml.safe_load(f)
    entries = data.get("pdfs", [])
    for entry in entries:
        if entry.get("id") == citation_id:
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
            return cast(SourceCitationDict, {
                "id": entry["id"],
                "agency": entry["agency"],
                "title": entry["title"],
                "url": entry["url"],
                "publication_date": pub_date,
                "document_type": entry["document_type"],
            })
    raise PdfExtractionError(
        f"sources.yaml has no entry with id={citation_id!r}"
    )


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


# ---------------------------------------------------------------------------
# T3: Text reversal + cell normalization helpers
# ---------------------------------------------------------------------------


def _reverse_cell_text(s: str | None) -> str | None:
    """Reverse line order then character order within each line.

    The Black Bear booklet prints the BMU regulation table physically rotated.
    pdfplumber returns each multi-line cell with both line and character order
    reversed (e.g., "Sep.15-Nov.29" extracts as "92.voN-51.peS"). This
    helper restores readable text BEFORE any normalization or regex matching.

    None and empty strings are passed through unchanged.
    """
    if s is None:
        return None
    if not s:
        return s
    lines = s.split("\n")
    lines.reverse()
    return "\n".join(line[::-1] for line in lines)


def _normalize_cell(cell: str | None) -> str | None:
    """Return None for None/whitespace-only input; otherwise collapse 3+ whitespace runs.

    Applies ``re.sub(r"\\s{3,}", " ", cell.strip())`` — identical semantics to
    ``extract_dea._normalize_cell`` except this version does NOT call
    ``_rejoin_hyphenated_linebreaks`` internally (hyphen-rejoin applies only to
    closure-prose / reporting-prose verbatim_rule strings, not BMU-table cells).

    Caller contract for BMU-table cells: callers MUST call ``_reverse_cell_text``
    BEFORE calling ``_normalize_cell``. Passing an unreversed BMU cell produces
    reversed text that merely has its whitespace collapsed — functionally wrong.
    """
    if cell is None:
        return None
    stripped = cell.strip()
    if not stripped:
        return None
    return re.sub(r"\s{3,}", " ", stripped)


def _is_season_cell_absent(cell: str | None) -> bool:
    """Return True if ``cell`` represents an absent season value.

    The Black Bear booklet PDF uses a literal dash ``"-"`` as a sentinel meaning
    "this season does not apply to this BMU" rather than leaving the cell empty.
    Both ``None`` and ``"-"`` must be treated as absent. Identical semantics to
    ``extract_dea._is_season_cell_absent``.

    Input must already be reversed (via ``_reverse_cell_text``) before this check.
    """
    if cell is None:
        return True
    return cell.strip() == "-"


def _rejoin_hyphenated_linebreaks(text: str) -> str:
    """Re-join words split across lines by a soft hyphen in closure/reporting prose.

    Applies ``re.sub(r"(?<=[a-z])-\\n(?=[a-z])", "", text)`` to collapse
    hyphenated line-breaks (e.g., ``"man-\\ndatory"`` → ``"mandatory"``).

    Scope: applies ONLY to closure-prose / reporting-prose ``verbatim_rule``
    strings extracted from p. 7. Do NOT apply to BMU-table cells (pp. 9–12) —
    those cells are reversed first via ``_reverse_cell_text``, which means the
    ``-\\n`` pattern would not be meaningful in that context.
    """
    return re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)


# ---------------------------------------------------------------------------
# T4: Region detection + Permit Managed detection helpers
# ---------------------------------------------------------------------------


def _detect_column_region(row0_cell: str | None) -> str | None:
    """Return ``"R<N>"`` if *row0_cell* contains a ``"REGION N"`` marker; else ``None``.

    Applies ``_REGION_MARKER_REGEX`` to the input.  Digits 1–7 are accepted;
    ``"REGION 8"`` and above return ``None`` because Montana has 7 FWP regions.

    Caller contract: *row0_cell* MUST already be reversed via
    ``_reverse_cell_text`` before this function is called.  Passing an
    unreversed cell produces meaningless results — the regex will not match
    because the source text is stored backwards.
    """
    if row0_cell is None:
        return None
    m = _REGION_MARKER_REGEX.search(row0_cell)
    if m is None:
        return None
    return f"R{m.group('num')}"


def _is_permit_managed_column(row0_cell: str | None) -> bool:
    """Return ``True`` if *row0_cell* marks a Permit Managed sub-table column.

    Applies ``_PERMIT_MANAGED_REGEX`` to the input.  Returns ``False`` if the
    input is ``None`` or the regex does not match.

    Caller contract: *row0_cell* MUST already be reversed via
    ``_reverse_cell_text`` before this function is called.  These columns
    appear on p. 11; their Row 0 cell reads ``"Permit Managed Opportunities"``
    after reversal.  In V1 these columns are skipped (not extracted) — callers
    use this predicate to gate that skip with an explicit ``_logger.info`` for
    traceability.
    """
    if row0_cell is None:
        return False
    return bool(_PERMIT_MANAGED_REGEX.search(row0_cell))


# ---------------------------------------------------------------------------
# T7: Quota cell parser
# ---------------------------------------------------------------------------


def _parse_quota_cell(text: str | None) -> BmuQuotaCell:
    """Parse a quota cell value into a structured ``BmuQuotaCell``.

    Caller contract: *text* MUST already be reversed via ``_reverse_cell_text``
    before this function is called.  The quota pattern (``"= N Female subquota"``
    or ``"= N Harvest quota"``) is only meaningful after reversal — passing an
    unreversed BMU-table cell produces gibberish that will never match
    ``_QUOTA_CELL_REGEX``.

    Parsing rules:

    1. Dash sentinel: if ``_is_season_cell_absent(text)`` is True (i.e. *text*
       is ``None`` or ``"-"``), return ``{"count": None, "kind": None,
       "verbatim": text or ""}``.  The empty string covers the ``None`` case so
       the ``verbatim`` field is always a ``str``.

    2. Normalize: apply ``_normalize_cell(text)`` to collapse internal
       whitespace.

    3. Primary regex match: apply ``_QUOTA_CELL_REGEX`` (Pattern A — standard
       word order) to the cell text.  This covers ``"= N Female subquota"`` and
       ``"= N Harvest quota"`` cases where all tokens appear on consecutive lines
       in the standard order after reversal.

    4. Component fallback: if the primary regex does not match, extract the
       numeric count (``_QUOTA_COUNT_REGEX``) and the kind keyword
       (``_QUOTA_KIND_REGEX``) independently.  This handles Pattern B
       (``"= N quota Female/Harvest"``) and Pattern C
       (``"quota = Female/Harvest N"``), which arise when pdfplumber splits the
       quota phrase across multiple lines in the rotated table and the per-line
       character reversal scrambles the inter-line word order.  Both ``"Female"``
       and ``"Harvest"`` tokens are unambiguous, so independent extraction is
       safe regardless of surrounding word order.

    5. No match: emit a ``WARNING`` log (``_logger.warning``) and return
       ``{"count": None, "kind": None, "verbatim": text}``.  Do NOT raise —
       keep the unstructured value visible for downstream review.

    ``verbatim`` is always the ORIGINAL *text* (post-reversal, pre-normalize) to
    preserve source fidelity per ADR-008.
    """
    if _is_season_cell_absent(text):
        return {"count": None, "kind": None, "verbatim": text or ""}

    # Past _is_season_cell_absent: text is a non-None, non-"-" string.
    text_str: str = text  # type: ignore[assignment]  # narrowed above; mypy needs a hint

    # Step 3: primary regex (Pattern A — standard word order).
    primary = _QUOTA_CELL_REGEX.search(text_str)
    if primary:
        count = int(primary.group("n"))
        kind = "female_subquota" if primary.group("kind").lower() == "female" else "harvest_quota"
        return {"count": count, "kind": kind, "verbatim": text_str}

    # Step 4: component fallback (Patterns B + C — scrambled word order).
    # Flatten newlines to spaces first so both component regexes operate on a
    # single whitespace-collapsed string (avoids edge cases with \n in \b contexts).
    flattened = text_str.replace("\n", " ")
    count_match = _QUOTA_COUNT_REGEX.search(flattened)
    kind_match = _QUOTA_KIND_REGEX.search(flattened)
    if count_match and kind_match and ("quota" in flattened.lower()):
        count = int(count_match.group("n"))
        kind = (
            "female_subquota"
            if kind_match.group("kind").lower() == "female"
            else "harvest_quota"
        )
        return {"count": count, "kind": kind, "verbatim": text_str}

    _logger.warning("unparseable quota cell: %r", text_str)
    return {"count": None, "kind": None, "verbatim": text_str}


# ---------------------------------------------------------------------------
# T5: BMU column iterator over pp. 9–12
# ---------------------------------------------------------------------------


def _get_row_cell(table: TableMatch, row_idx: int, col_idx: int) -> str | None:
    """Return the cell at logical row *row_idx* and column *col_idx*.

    Probe performed 2026-05-09 against page 9 of the live PDF:
    ``extract_tables`` returns ``headers`` = logical Row 0 (opportunity text)
    plus ``rows[0..8]`` = logical Rows 1–9.  This is **Case A** — 10 logical
    rows total, split as 1 header + 9 data rows.

    Mapping:
      - ``row_idx == 0``     → ``table["headers"][col_idx]``   (Row 0, opportunity)
      - ``row_idx == 1``     → ``table["rows"][0][col_idx]``   (Row 1, General Season)
      - ``row_idx == 9``     → ``table["rows"][8][col_idx]``   (Row 9, BMU ID)

    Case B (headers = ``[None, None, …]``, all 10 rows in ``rows``) was NOT
    observed — the opportunity-text row is always captured as ``headers`` by
    pdfplumber's table-finder on these pages.  If a future PDF edition changes
    the layout and this function starts returning wrong values, re-run the
    one-shot probe from the T5 implementation notes and adjust accordingly.
    """
    if row_idx == 0:
        return table["headers"][col_idx]
    return table["rows"][row_idx - 1][col_idx]


def _iter_bmu_columns(
    pdf: PdfDocument,
) -> Iterator[tuple[int, TableMatch, int, str, str | None]]:
    """Walk pp. 9–12, yielding one tuple per BMU column.

    Tracks ``current_region`` left-to-right per page: a "REGION N" cell in
    Row 0 (after reversal) sets ``current_region`` for all subsequent columns
    until the next marker.  ``current_region`` is reset to ``""`` at each page
    boundary so a state that bleeds unintentionally from one page to the next
    becomes a visible diagnostic — Row 0 is re-scanned fresh on every page.

    Skips:
      - Columns where Row 0 is ``None`` or contains only ``"-"`` (empty/absent
        cells between BMUs — not a BMU column).
      - Region-marker columns (Row 0 reversed matches ``_REGION_MARKER_REGEX``).
      - Permit Managed sub-table columns (Row 0 reversed matches
        "Permit Managed Opportunities" — and all subsequent columns on the same
        page until the next REGION marker, which form the sub-table body).
        "Quota Managed Opportunities" (p. 11 col 8) is NOT skipped — it is
        the Row 0 opportunity text for main BMU columns 510 and 520.
      - Columns where Row 9 (BMU ID) does not match a 3-digit number after
        reversal and normalisation (label columns such as "BMU", row-0 label
        columns, blank separators).

    Yields:
      ``(page_num_1based, table, column_index, current_region, row0_reversed)``

      ``column_index`` is the 0-based column index into ``table["headers"]``
      and each inner list of ``table["rows"]``.

    Multiple-table pages:
      The expected case is one table per page.  If ``extract_tables`` returns
      more than one (e.g., a sidebar or annotation block pdfplumber treats as a
      table), the iterator selects the largest table by total cell count
      (``len(headers) + sum(len(r) for r in rows)``).  This selection is
      logged at DEBUG level for operator traceability.

    Note on ``pdf_filename`` and ``extracted_at`` parameters:
      They are NOT passed into this function because the iterator only yields
      positional data — it does not build ``PageReference`` or cite sources.
      Those responsibilities belong to the T6 ``_extract_bmu_row`` caller,
      which receives the per-column tuple and constructs the full
      ``BmuRowExtraction``.  This keeps T5 narrowly focused on column
      enumeration.
    """
    # Regex for the Permit Managed sub-table header column found on p. 11 col 13.
    # "Quota Managed Opportunities" (col 8 on p. 11) is NOT a sub-table header —
    # it is the Row 0 opportunity text for the main BMU columns 510 and 520 that
    # follow it (those columns have valid 3-digit BMU IDs and normal row semantics).
    # Only the "Permit Managed" marker introduces a sub-table with different row
    # semantics (apply-by / permit-range / license-codes) that must be skipped in V1.
    # Probe 2026-05-09 confirmed: p. 11 col 13 = "Permit Managed Opportunities"
    # (sub-table header; BMU ID row is None); p. 11 col 8 = "Quota Managed
    # Opportunities" (opportunity description; BMU ID row has real BMU numbers).
    # Detection uses _is_permit_managed_column (the canonical helper).

    for page_num, page in iter_pages(pdf, _BMU_TABLE_PAGES[0], _BMU_TABLE_PAGES[1]):
        tables = extract_tables(page)
        if not tables:
            _logger.warning("page %d: no tables found on BMU table page", page_num)
            continue

        if len(tables) > 1:
            table = max(
                tables,
                key=lambda t: len(t["headers"]) + sum(len(r) for r in t["rows"]),
            )
            _logger.debug(
                "page %d: %d tables found; selected largest (%d header cols, %d rows)",
                page_num,
                len(tables),
                len(table["headers"]),
                len(table["rows"]),
            )
        else:
            table = tables[0]

        num_rows = len(table["rows"])
        if num_rows < 9:
            raise PdfExtractionError(
                f"page {page_num}: expected at least 9 data rows (Case A layout), "
                f"got {num_rows} — FWP may have changed the table format"
            )

        current_region: str = ""
        # When a "Permit Managed Opportunities" header column is encountered,
        # all subsequent columns on the same page belong to the sub-table and
        # must be skipped until a new REGION marker resets the context.
        # Probe 2026-05-09 confirmed: on page 11 col 13 is the Permit Managed
        # marker and cols 14–16 are the sub-table label + 510/520 data columns
        # — all four must be skipped.
        in_managed_block: bool = False

        for c in range(len(table["headers"])):
            row0_raw = _get_row_cell(table, _ROW_OPPORTUNITY, c)
            row0_reversed = _reverse_cell_text(row0_raw)

            # --- Region-marker check (takes priority; resets managed block) ---
            if region := _detect_column_region(row0_reversed):
                current_region = region
                in_managed_block = False
                continue

            # --- Permit Managed sub-table check ---
            if _is_permit_managed_column(row0_reversed):
                # row0_reversed is non-None here: _is_permit_managed_column
                # only returns True after a successful regex match against
                # a non-None string.
                preview = (row0_reversed or "")[:60]
                _logger.info(
                    "page %d col %d: entering managed-opportunity block (%r); "
                    "skipping all subsequent columns until next REGION marker",
                    page_num,
                    c,
                    preview,
                )
                in_managed_block = True
                continue

            # --- Managed-block propagation: skip columns inside sub-table ---
            if in_managed_block:
                _logger.debug(
                    "page %d col %d: skipping — inside managed-opportunity block",
                    page_num,
                    c,
                )
                continue

            # --- BMU-column validation: Row 9 must be a 3-digit BMU number ---
            bmu_id_raw = _get_row_cell(table, _ROW_BMU_ID, c)
            bmu_id_reversed = _reverse_cell_text(bmu_id_raw)
            bmu_id_normalized = _normalize_cell(bmu_id_reversed)

            if not bmu_id_normalized:
                # Empty / None BMU ID cell — label column or blank separator; skip.
                _logger.debug(
                    "page %d col %d: skipping — BMU ID cell is empty (row0=%r)",
                    page_num,
                    c,
                    row0_reversed,
                )
                continue

            m = _BMU_NUMBER_REGEX.match(bmu_id_normalized)
            if not m:
                _logger.warning(
                    "page %d col %d: skipping — BMU ID %r does not match 3-digit "
                    "pattern after reversal (row0=%r)",
                    page_num,
                    c,
                    bmu_id_normalized,
                    row0_reversed,
                )
                continue

            # --- Region-required guard (fail-loud) ---
            if current_region == "":
                raise PdfExtractionError(
                    f"BMU column at page {page_num} col {c} (BMU "
                    f"{bmu_id_normalized!r}) has no preceding REGION marker — "
                    f"check that the REGION N column on this page is being parsed "
                    f"correctly and that the iterator resets current_region at each "
                    f"page boundary"
                )

            yield (page_num, table, c, current_region, row0_reversed)


# ---------------------------------------------------------------------------
# T6: Per-BMU column row extraction → BmuRowExtraction
# ---------------------------------------------------------------------------


def _extract_bmu_row(
    table: TableMatch,
    col_idx: int,
    page_num: int,
    current_region: str,
    pdf_filename: str,
    extracted_at: str,
    source_citation: SourceCitationDict,
) -> BmuRowExtraction:
    """Extract one BMU column from the transposed BMU table into a BmuRowExtraction.

    Caller contract: *table* comes from ``_iter_bmu_columns`` which has already
    validated that Row 9 of *col_idx* matches ``_BMU_NUMBER_REGEX``.  This
    function performs a second match anyway (defensive programming — fail-loud if
    the BMU ID is missing or malformed at this stage).

    Text-reversal rule (headline cleanup rule): every raw cell from the BMU
    table MUST pass through ``_reverse_cell_text`` before normalization or
    regex matching.  Season cells are additionally checked via
    ``_is_season_cell_absent`` AFTER reversal but BEFORE ``_normalize_cell``.

    Verbatim text: the ``verbatim_text`` field is assembled from the 10
    post-reversal, pre-normalize cell values (joined with ``\\n`` separators)
    to preserve source fidelity per ADR-008.

    Confidence: ``ConfidenceTier.HIGH`` for all base-extraction rows — structured
    table cells per ADR-017.  Correction-touched rows are demoted in the T12
    merge pass; this function does not know which rows will be touched.
    """
    # --- Collect all 10 row cells (reversed, pre-normalize) ---
    raw_cells: list[str | None] = []
    for row_idx in range(10):
        raw = _get_row_cell(table, row_idx, col_idx)
        reversed_cell = _reverse_cell_text(raw)
        raw_cells.append(reversed_cell)

    # Named aliases for each row (reversed, pre-normalize).
    opportunity_raw = raw_cells[_ROW_OPPORTUNITY]
    general_season_raw = raw_cells[_ROW_GENERAL_SEASON]
    archery_season_raw = raw_cells[_ROW_ARCHERY_SEASON]
    spring_season_raw = raw_cells[_ROW_SPRING_SEASON]
    hound_training_raw = raw_cells[_ROW_HOUND_TRAINING]
    hound_nr_license_raw = raw_cells[_ROW_HOUND_NR_LICENSE]
    hound_nr_max_raw = raw_cells[_ROW_HOUND_NR_MAX]
    fall_quota_raw = raw_cells[_ROW_FALL_QUOTA]
    spring_quota_raw = raw_cells[_ROW_SPRING_QUOTA]
    bmu_id_raw = raw_cells[_ROW_BMU_ID]

    # --- BMU number (Row 9) ---
    bmu_id_normalized = _normalize_cell(bmu_id_raw)
    bmu_match = _BMU_NUMBER_REGEX.match(bmu_id_normalized or "")
    if not bmu_match:
        raise PdfExtractionError(
            f"page {page_num} col {col_idx}: BMU ID {bmu_id_normalized!r} does not "
            f"match 3-digit pattern — this should have been caught by _iter_bmu_columns"
        )
    bmu_number = int(bmu_match.group(1))

    # --- Season fields (Rows 1–4): dash-sentinel → None ---
    # Check _is_season_cell_absent on the reversed-but-pre-normalized value.
    # If absent, emit None directly.  Otherwise normalize.
    if _is_season_cell_absent(general_season_raw):
        general_season: str | None = None
    else:
        general_season = _normalize_cell(general_season_raw)

    if _is_season_cell_absent(archery_season_raw):
        archery_only_season: str | None = None
    else:
        archery_only_season = _normalize_cell(archery_season_raw)

    if _is_season_cell_absent(spring_season_raw):
        spring_season: str | None = None
    else:
        spring_season = _normalize_cell(spring_season_raw)

    if _is_season_cell_absent(hound_training_raw):
        hound_training_season: str | None = None
    else:
        hound_training_season = _normalize_cell(hound_training_raw)

    # --- Hound NR license (Row 5) ---
    hound_nr_license = _normalize_cell(hound_nr_license_raw)

    # --- Hound NR max (Row 6): numeric or None ---
    if _is_season_cell_absent(hound_nr_max_raw):
        hound_nr_max: int | None = None
    else:
        hound_nr_max_normalized = _normalize_cell(hound_nr_max_raw)
        if hound_nr_max_normalized is None:
            hound_nr_max = None
        else:
            try:
                hound_nr_max = int(hound_nr_max_normalized)
            except ValueError:
                raise PdfExtractionError(
                    f"BMU {bmu_number} col {col_idx}: hound_nr_max not numeric: "
                    f"{hound_nr_max_normalized!r}"
                )

    # --- Quota cells (Rows 7–8): parse via _parse_quota_cell ---
    fall_quota: BmuQuotaCell = _parse_quota_cell(fall_quota_raw)
    spring_quota: BmuQuotaCell = _parse_quota_cell(spring_quota_raw)

    # --- Opportunity (Row 0): normalize ---
    opportunity: str | None = _normalize_cell(opportunity_raw)

    # --- Verbatim text: join 10 post-reversal, pre-normalize values ---
    verbatim_parts: list[str] = []
    for rc in raw_cells:
        verbatim_parts.append(rc if rc is not None else "")
    verbatim_text = "\n".join(verbatim_parts)

    # --- Page reference ---
    page_reference: PageReference = {
        "pdf_filename": pdf_filename,
        "page_num_1based": page_num,
        "bbox": tuple(table["bbox"]),  # type: ignore[typeddict-item]
        "extracted_at": extracted_at,
    }

    return BmuRowExtraction(
        bmu_number=bmu_number,
        hd_region=current_region,
        opportunity=opportunity,
        general_season=general_season,
        archery_only_season=archery_only_season,
        spring_season=spring_season,
        hound_training_season=hound_training_season,
        hound_nr_license=hound_nr_license,
        hound_nr_max=hound_nr_max,
        fall_quota=fall_quota,
        spring_quota=spring_quota,
        page_reference=page_reference,
        verbatim_text=verbatim_text,
        extraction_confidence=ConfidenceTier.HIGH,
        source_id=source_citation["id"],
        source_publication_date=source_citation["publication_date"],
        applied_correction=False,
        supersedes=None,
    )


# ---------------------------------------------------------------------------
# T8: Closure prose extraction → ClosurePredicateCandidate
# ---------------------------------------------------------------------------
#
# Live-PDF probe results (2026-05-09, p. 7 right column via _RIGHT_COLUMN_BBOX):
#
#   Spring Season Closure paragraph (verbatim from pdfplumber):
#     "Spring Season Closure: BMUs 300, 301, 319, and 580 are subject\n"
#     "to close, with regular public notice, at any point after May 31 if the\n"
#     "cumulative spring harvest exceeds 37% female black bears."
#
#   Quota closure paragraph (verbatim from pdfplumber):
#     "In BMUs 411, 420, 440, 450, 510, 520, 600, and 700 when the quota\n"
#     "is reached or approached in each of these districts, the black bear\n"
#     "season in that district will close. For quota status, call 1-800-385-\n"
#     "7826 or 406-444-1989."
#
#   BMU 530 does NOT appear anywhere in the 2026 PDF (neither table nor prose).
#   The spec's claim of "9 quota-closure BMUs" is wrong. Constants and drift
#   guard encode the correct 2026 reality (8 BMUs).
#
#   The phone number "1-800-385-7826" is split across a line break as
#   "1-800-385-\n7826". _rejoin_hyphenated_linebreaks uses the pattern
#   r"(?<=[a-z])-\n(?=[a-z])" which only fires on lowercase letters — it does
#   NOT collapse the digit-hyphen-digit break. A second pass with
#   r"(\d)-\n(\d)" → r"\1-\2" is applied after _rejoin_hyphenated_linebreaks
#   to rejoin digit-spanning line breaks within the quota prose. The captured
#   dash is preserved (not stripped) because the hyphen in phone-number-style
#   sequences ("385-\n7826") is a structural separator that must survive
#   line-rejoin — yielding "385-7826", not "3857826". Locked by
#   TestExtractClosures::test_phone_number_preserved_across_linebreak.

_DIGIT_LINEBREAK_RE = re.compile(r"(\d)-\n(\d)")


def _extract_closures(
    pdf: PdfDocument,
    pdf_filename: str,
    extracted_at: str,
    source_citation: SourceCitationDict,
) -> list[ClosurePredicateCandidate]:
    """Extract Spring Season Closure + quota closure predicates from p. 7 right column.

    Returns a list of exactly two ClosurePredicateCandidate dicts in deterministic
    order: female sub-quota predicate first (Spring Season Closure), quota predicate
    second (In BMUs 411 …). This order matches the PDF's left-to-right reading order
    on p. 7.

    Drift guard: after capturing each verbatim paragraph, re.findall(r"\\d{3}",
    verbatim) is used to extract all 3-digit BMU numbers from the prose. The
    resulting set is compared against the module-level constants. A mismatch raises
    PdfExtractionError — this is the fail-loud guard against silent FWP edits between
    editions.

    Anchor search: uses str.find (substring search) on the full right-column text.
    Paragraph boundaries are the next double-newline or end-of-text.
    """
    right_col_text: str | None = None
    for _page_num, page in iter_pages(pdf, _CLOSURE_PROSE_PAGE, _CLOSURE_PROSE_PAGE):
        right_col_text = extract_text(page, bbox=_RIGHT_COLUMN_BBOX)
    if right_col_text is None:
        raise PdfExtractionError(
            f"closure prose: iter_pages yielded no pages for p. {_CLOSURE_PROSE_PAGE} "
            f"of {pdf_filename!r} — check that the booklet PDF is on disk and the page "
            "range is valid"
        )

    # --- Spring Season Closure (female sub-quota) ---
    spring_anchor = "Spring Season Closure"
    quota_anchor = "In BMUs 411"
    spring_start = right_col_text.find(spring_anchor)
    if spring_start == -1:
        raise PdfExtractionError(
            f"closure prose anchor '{spring_anchor}' not found in p. 7 right column"
            " — FWP may have changed the prose"
        )

    # Probe (2026-05-09): paragraphs are separated by single \n only (no double-\n).
    # Bound the spring paragraph by the start of the quota anchor (which immediately
    # follows). Fall back to double-newline then end-of-text if anchor is absent.
    quota_start = right_col_text.find(quota_anchor, spring_start)
    if quota_start != -1:
        spring_para_text = right_col_text[spring_start:quota_start].strip()
    else:
        double_nl = right_col_text.find("\n\n", spring_start)
        if double_nl != -1:
            spring_para_text = right_col_text[spring_start:double_nl].strip()
        else:
            spring_para_text = right_col_text[spring_start:].strip()

    # Apply hyphenated-linebreak re-join (lowercase-letter form).
    spring_verbatim = _rejoin_hyphenated_linebreaks(spring_para_text)

    # Drift guard: compare 3-digit BMU numbers in prose against constant. Scope
    # to the first sentence only so that any future contact-number or date
    # (e.g., a hypothetical "the 137% threshold") doesn't yield false positives.
    # Matches the scoping pattern used for the quota predicate below.
    spring_first_sentence = spring_verbatim.split(".", 1)[0]
    spring_extracted_bmus = {int(n) for n in re.findall(r"\d{3}", spring_first_sentence)}
    spring_expected_bmus = set(_FEMALE_SUBQUOTA_BMUS)
    if spring_extracted_bmus != spring_expected_bmus:
        raise PdfExtractionError(
            f"closure prose BMU list drifted: extracted {sorted(spring_extracted_bmus)}, "
            f"constants {sorted(spring_expected_bmus)}"
        )

    female_subquota_predicate: ClosurePredicateCandidate = {
        "bmu_numbers": list(_FEMALE_SUBQUOTA_BMUS),
        "kind": "sex_threshold",
        "threshold_percent": _FEMALE_SUBQUOTA_THRESHOLD_PERCENT,
        "threshold_sex": "female",
        "notification_channel": "agency_website",
        "observation_channel": "mandatory_reporting",
        "verbatim_rule": spring_verbatim,
        "page_reference": {
            "pdf_filename": pdf_filename,
            "page_num_1based": 7,
            "bbox": _RIGHT_COLUMN_BBOX,
            "extracted_at": extracted_at,
        },
        "source_id": source_citation["id"],
        "source_publication_date": source_citation["publication_date"],
        "extraction_confidence": ConfidenceTier.MEDIUM,
    }

    # --- Quota closure (8 BMUs) ---
    # quota_start was already computed above when bounding the spring paragraph.
    if quota_start == -1:
        raise PdfExtractionError(
            f"closure prose anchor '{quota_anchor}' not found in p. 7 right column"
            " — FWP may have changed the prose"
        )

    # Bound the quota paragraph by the next section heading that follows it.
    # Probe (2026-05-09): "Inspection Requirements Region 1 Only:" immediately follows.
    # Use that as the end anchor; fall back to double-newline then end-of-text.
    next_section_anchor = "Inspection Requirements Region 1 Only:"
    next_section_start = right_col_text.find(next_section_anchor, quota_start)
    if next_section_start != -1:
        quota_para_text = right_col_text[quota_start:next_section_start].strip()
    else:
        double_nl = right_col_text.find("\n\n", quota_start)
        if double_nl != -1:
            quota_para_text = right_col_text[quota_start:double_nl].strip()
        else:
            quota_para_text = right_col_text[quota_start:].strip()

    # Apply hyphenated-linebreak re-join (lowercase-letter form), then a second
    # pass to rejoin digit-spanning line breaks (e.g., "1-800-385-\n7826" →
    # "1-800-385-7826"). The structural dash is preserved per ADR-008 verbatim
    # discipline — stripping it would corrupt the phone number.
    quota_verbatim = _rejoin_hyphenated_linebreaks(quota_para_text)
    quota_verbatim = _DIGIT_LINEBREAK_RE.sub(r"\1-\2", quota_verbatim)

    # Drift guard: compare 3-digit BMU numbers in prose against constant.
    # Use only the first sentence (up to first period) to avoid matching phone
    # numbers like "385", "444" in the quota-status contact line.
    quota_first_sentence_end = quota_verbatim.find(".")
    if quota_first_sentence_end != -1:
        quota_first_sentence = quota_verbatim[: quota_first_sentence_end + 1]
    else:
        quota_first_sentence = quota_verbatim
    quota_extracted_bmus = {int(n) for n in re.findall(r"\d{3}", quota_first_sentence)}
    quota_expected_bmus = set(_QUOTA_CLOSURE_BMUS)
    if quota_extracted_bmus != quota_expected_bmus:
        raise PdfExtractionError(
            f"closure prose BMU list drifted: extracted {sorted(quota_extracted_bmus)}, "
            f"constants {sorted(quota_expected_bmus)}"
        )

    quota_predicate: ClosurePredicateCandidate = {
        "bmu_numbers": list(_QUOTA_CLOSURE_BMUS),
        "kind": "quota_threshold",
        "threshold_percent": None,
        "threshold_sex": None,
        "notification_channel": "agency_phone",
        "observation_channel": "mandatory_reporting",
        "verbatim_rule": quota_verbatim,
        "page_reference": {
            "pdf_filename": pdf_filename,
            "page_num_1based": 7,
            "bbox": _RIGHT_COLUMN_BBOX,
            "extracted_at": extracted_at,
        },
        "source_id": source_citation["id"],
        "source_publication_date": source_citation["publication_date"],
        "extraction_confidence": ConfidenceTier.MEDIUM,
    }

    return [female_subquota_predicate, quota_predicate]


# ---------------------------------------------------------------------------
# T9: Region-specific reporting prose → ReportingObligationCandidate
#
# Live-PDF probe results (2026-05-09, p. 7 right column via _RIGHT_COLUMN_BBOX):
#
#   All three reporting paragraphs are present on p. 7 right column.
#
#   "Mandatory Reporting Requirements" starts at position 0 (top of right
#   column). It is bounded on the right by "Spring Season Closure" (the first
#   closure paragraph). The paragraph contains the 48-hour rule:
#     "All successful black bear hunters must\npersonally report their black
#     bear\nharvest within 48 hours."
#   and contact numbers + backcountry exception prose.
#
#   "Inspection Requirements Region 1 Only:" follows the quota-closure paragraph
#   and is bounded on the right by "Inspection Requirements Regions 2-7:".
#
#   "Inspection Requirements Regions 2-7:" is bounded on the right by
#   "\nA person licensed to hunt ..." which begins a separate legal paragraph
#   about transfer of possession.
#
#   Paragraph boundaries: single \n only (no double-\n between paragraphs on
#   this page). End anchors are the next section heading or the "\nA person
#   licensed" paragraph for R2-7.
# ---------------------------------------------------------------------------


def _extract_reporting_obligations(
    pdf: PdfDocument,
    pdf_filename: str,
    extracted_at: str,
    source_citation: SourceCitationDict,
) -> list[ReportingObligationCandidate]:
    """Extract statewide + region-specific reporting obligations from p. 7 right column.

    Returns a list of exactly three ReportingObligationCandidate dicts in
    deterministic order: STATEWIDE (broadest scope) first, then R1, then R2-7.

    Paragraph structure on p. 7 right column (single-column layout after
    bbox crop):
      1. "Mandatory Reporting Requirements" — statewide 48-hour harvest report.
         Bounded by the start of "Spring Season Closure" (closure paragraph).
      2. "Inspection Requirements Region 1 Only:" — R1 tooth submission.
         Bounded by the start of "Inspection Requirements Regions 2-7:".
      3. "Inspection Requirements Regions 2-7:" — R2-7 hide+skull presentation.
         Bounded by the start of "A person licensed" (transfer-of-possession
         paragraph that follows); falls back to double-newline then end-of-text.

    Anchor search: uses str.find (substring search) on the full right-column
    text. Missing anchors raise PdfExtractionError — fail-loud against FWP
    prose edits between editions.

    All captured verbatim texts are passed through _rejoin_hyphenated_linebreaks
    to collapse soft hyphenation introduced by pdfplumber line wrapping.
    """
    right_col_text: str | None = None
    for _page_num, page in iter_pages(pdf, _CLOSURE_PROSE_PAGE, _CLOSURE_PROSE_PAGE):
        right_col_text = extract_text(page, bbox=_RIGHT_COLUMN_BBOX)
    if right_col_text is None:
        raise PdfExtractionError(
            f"reporting prose: iter_pages yielded no pages for p. {_CLOSURE_PROSE_PAGE} "
            f"of {pdf_filename!r} — check that the booklet PDF is on disk and the page "
            "range is valid"
        )

    # --- Anchors ---
    mandatory_anchor = "Mandatory Reporting Requirements"
    spring_anchor = "Spring Season Closure"
    r1_anchor = "Inspection Requirements Region 1 Only:"
    r27_anchor = "Inspection Requirements Regions 2-7:"
    # End anchor for R2-7: the transfer-of-possession paragraph that follows.
    r27_end_anchor = "\nA person licensed"

    # --- Locate mandatory paragraph ---
    mandatory_start = right_col_text.find(mandatory_anchor)
    if mandatory_start == -1:
        raise PdfExtractionError(
            f"reporting prose anchor '{mandatory_anchor}' not found in p. 7 right column"
            " — FWP may have changed the prose"
        )

    # Bound the mandatory paragraph: ends at the start of "Spring Season Closure"
    # (the first closure paragraph). Fall back to double-newline then end-of-text.
    spring_start = right_col_text.find(spring_anchor, mandatory_start)
    if spring_start != -1:
        mandatory_para_text = right_col_text[mandatory_start:spring_start].strip()
    else:
        double_nl = right_col_text.find("\n\n", mandatory_start)
        if double_nl != -1:
            mandatory_para_text = right_col_text[mandatory_start:double_nl].strip()
        else:
            mandatory_para_text = right_col_text[mandatory_start:].strip()

    mandatory_verbatim = _rejoin_hyphenated_linebreaks(mandatory_para_text)

    statewide_candidate: ReportingObligationCandidate = {
        "region_scope": "STATEWIDE",
        "kind_hint": "harvest_report",
        "deadline_hint": "48 hours",
        "verbatim_rule": mandatory_verbatim,
        "page_reference": {
            "pdf_filename": pdf_filename,
            "page_num_1based": 7,
            "bbox": _RIGHT_COLUMN_BBOX,
            "extracted_at": extracted_at,
        },
        "source_id": source_citation["id"],
        "source_publication_date": source_citation["publication_date"],
        "extraction_confidence": ConfidenceTier.MEDIUM,
    }

    # --- Locate R1 paragraph ---
    r1_start = right_col_text.find(r1_anchor)
    if r1_start == -1:
        raise PdfExtractionError(
            f"reporting prose anchor '{r1_anchor}' not found in p. 7 right column"
            " — FWP may have changed the prose"
        )

    # Bound the R1 paragraph: ends at the start of "Inspection Requirements Regions 2-7:".
    r27_start = right_col_text.find(r27_anchor, r1_start)
    if r27_start != -1:
        r1_para_text = right_col_text[r1_start:r27_start].strip()
    else:
        double_nl = right_col_text.find("\n\n", r1_start)
        if double_nl != -1:
            r1_para_text = right_col_text[r1_start:double_nl].strip()
        else:
            r1_para_text = right_col_text[r1_start:].strip()

    r1_verbatim = _rejoin_hyphenated_linebreaks(r1_para_text)

    r1_candidate: ReportingObligationCandidate = {
        "region_scope": "R1",
        "kind_hint": "tooth_submission",
        "deadline_hint": "10 days",
        "verbatim_rule": r1_verbatim,
        "page_reference": {
            "pdf_filename": pdf_filename,
            "page_num_1based": 7,
            "bbox": _RIGHT_COLUMN_BBOX,
            "extracted_at": extracted_at,
        },
        "source_id": source_citation["id"],
        "source_publication_date": source_citation["publication_date"],
        "extraction_confidence": ConfidenceTier.MEDIUM,
    }

    # --- Locate R2-7 paragraph ---
    if r27_start == -1:
        r27_start = right_col_text.find(r27_anchor)
    if r27_start == -1:
        raise PdfExtractionError(
            f"reporting prose anchor '{r27_anchor}' not found in p. 7 right column"
            " — FWP may have changed the prose"
        )

    # Bound the R2-7 paragraph: ends at the transfer-of-possession paragraph
    # ("\nA person licensed ...") that immediately follows. Fall back to
    # double-newline then end-of-text.
    r27_end = right_col_text.find(r27_end_anchor, r27_start)
    if r27_end != -1:
        r27_para_text = right_col_text[r27_start:r27_end].strip()
    else:
        double_nl = right_col_text.find("\n\n", r27_start)
        if double_nl != -1:
            r27_para_text = right_col_text[r27_start:double_nl].strip()
        else:
            r27_para_text = right_col_text[r27_start:].strip()

    r27_verbatim = _rejoin_hyphenated_linebreaks(r27_para_text)

    r27_candidate: ReportingObligationCandidate = {
        "region_scope": "R2-7",
        "kind_hint": "hide_skull_presentation",
        "deadline_hint": "10 days",
        "verbatim_rule": r27_verbatim,
        "page_reference": {
            "pdf_filename": pdf_filename,
            "page_num_1based": 7,
            "bbox": _RIGHT_COLUMN_BBOX,
            "extracted_at": extracted_at,
        },
        "source_id": source_citation["id"],
        "source_publication_date": source_citation["publication_date"],
        "extraction_confidence": ConfidenceTier.MEDIUM,
    }

    # Deterministic order: broadest scope first.
    return [statewide_candidate, r1_candidate, r27_candidate]


# ---------------------------------------------------------------------------
# T2: Statewide rules extraction (page 2 right column — Bear ID Test)
# ---------------------------------------------------------------------------

# Anchors for the Bear ID Test paragraph on p. 2 right column.
# Start: the opening sentence of the Bear ID Test requirement.
# End:   the FWP education URL that closes the paragraph.
_BEAR_ID_START_RE = re.compile(r"A hunter may purchase only one Black Bear License per year\.")
_BEAR_ID_END_RE = re.compile(r"fwp\.mt\.gov/hunt/education/bear-identification")


def _extract_statewide_rules(
    pdf: PdfDocument,
    pdf_filename: str,
    source_id: str,
    source_publication_date: str,
    extracted_at: str,
) -> list[StatewideRuleCandidate]:
    """Extract statewide pre-purchase prerequisite prose from p. 2 right column.

    Locates the Bear ID Test paragraph using two compiled regex anchors
    (``_BEAR_ID_START_RE`` / ``_BEAR_ID_END_RE``) and returns a single
    ``StatewideRuleCandidate`` carrying the verbatim text.

    Args:
        pdf: Already-open PdfDocument for the bear booklet.
        pdf_filename: Real PDF basename, threaded from the orchestrator via
            ``booklet_pdf.filename`` (same convention as
            ``_extract_reporting_obligations``). Do NOT synthesize from
            source_id + publication_date — that would leak the canonical name
            into custom ``--booklet-pdf`` operator runs, hiding the actual file.
        source_id: Source citation id string (e.g. "mt-fwp-black-bear-2026-booklet").
        source_publication_date: ISO-8601 date string from the source citation.
        extracted_at: ISO-8601 datetime string from the manifest, threaded from
            the orchestrator (same convention as ``_extract_reporting_obligations``).

    Return value:
      - Exactly one element on success.
      - Empty list if the start anchor is absent (operator-visible via the
        row-count guard ``[1, 1]`` band downstream — fail-loud without a
        RuntimeError here because an absent start anchor may mean the page
        layout shifted rather than a code bug).
      - Raises ``RuntimeError`` if the start anchor is found but the end anchor
        is absent — that combination is a code or PDF-structure bug that
        requires investigation before re-running.

    The captured body is collapsed with ``re.sub(r"\\s+", " ", body)`` (see
    "Statewide-rule body whitespace collapse" in the module docstring cleanup
    rules) — ADR-008-safe extras-only whitespace normalisation.
    """
    right_col_text: str | None = None
    for _page_num, page in iter_pages(pdf, _STATEWIDE_RULES_PAGE, _STATEWIDE_RULES_PAGE):
        right_col_text = extract_text(page, bbox=_RIGHT_COLUMN_BBOX)

    if right_col_text is None:
        raise PdfExtractionError(
            f"statewide rules: iter_pages yielded no pages for p. {_STATEWIDE_RULES_PAGE} "
            f"of {pdf_filename!r} — check that the booklet PDF is on disk and the page "
            "range is valid"
        )

    start_match = _BEAR_ID_START_RE.search(right_col_text)
    if start_match is None:
        _logger.warning(
            "statewide rules: start anchor not found on p%d of %s — "
            "statewide_rules will be empty (downstream row-count guard will fire)",
            _STATEWIDE_RULES_PAGE, source_id,
        )
        return []

    end_match = _BEAR_ID_END_RE.search(right_col_text, pos=start_match.start())
    if end_match is None:
        raise RuntimeError(
            f"_extract_statewide_rules: end anchor missing on p{_STATEWIDE_RULES_PAGE}. "
            "Source PDF may have changed; investigate before re-running."
        )

    raw_body = right_col_text[start_match.start() : end_match.end()]
    body = re.sub(r"\s+", " ", raw_body)

    candidate: StatewideRuleCandidate = {
        "rule_hint": "pre_purchase_prerequisite",
        "verbatim_text": body,
        "page_reference": {
            "pdf_filename": pdf_filename,
            "page_num_1based": _STATEWIDE_RULES_PAGE,
            "bbox": _RIGHT_COLUMN_BBOX,
            "extracted_at": extracted_at,
        },
        "source_id": source_id,
        "source_publication_date": source_publication_date,
        "extraction_confidence": ConfidenceTier.MEDIUM,
    }
    return [candidate]


# ---------------------------------------------------------------------------
# T10: Pass-1 base extraction orchestrator → BlackBearBaseExtraction
# ---------------------------------------------------------------------------

# Deterministic sort order for hd_region values ("R1".."R7").
_REGION_ORDER: dict[str, int] = {
    "R1": 1,
    "R2": 2,
    "R3": 3,
    "R4": 4,
    "R5": 5,
    "R6": 6,
    "R7": 7,
}

# Whitelist of BmuRowExtraction fields a correction operation may target.
# Used by _merge_with_corrections to reject misspelled or invented fields.
# Only data columns are listed — bookkeeping fields (page_reference,
# verbatim_text, extraction_confidence, source_id, source_publication_date,
# applied_correction, supersedes) are NOT correctable; the merge updates
# those itself.
_CORRECTABLE_FIELDS: frozenset[str] = frozenset({
    "bmu_number",
    "hd_region",
    "opportunity",
    "general_season",
    "archery_only_season",
    "spring_season",
    "hound_training_season",
    "hound_nr_license",
    "hound_nr_max",
    "fall_quota",
    "spring_quota",
})


def _extract_base(
    booklet_pdf: PdfDocument,
    source_citation: SourceCitationDict,
    extracted_at: str,
) -> BlackBearBaseExtraction:
    """Orchestrate Pass-1 base extraction from the booklet PDF.

    Calls _iter_bmu_columns + _extract_bmu_row to collect all BMU rows, then
    _extract_closures and _extract_reporting_obligations for the prose sections.
    Rows are sorted deterministically by (region_order, bmu_number).

    Fail-loud guard: if len(rows) < _MIN_EXPECTED_BMU_COUNT, raises
    PdfExtractionError. Soft guard: if len(rows) != _EXPECTED_BMU_COUNT, emits
    a WARNING log (not fatal) so operators can investigate without blocking the
    downstream pipeline.

    Takes an already-open PdfDocument (not a Path). The caller is responsible
    for the ``with open_pdf(...)`` context manager.
    """
    rows: list[BmuRowExtraction] = []

    for page_num, table, col_idx, current_region, row0_reversed in _iter_bmu_columns(booklet_pdf):
        row = _extract_bmu_row(
            table=table,
            col_idx=col_idx,
            page_num=page_num,
            current_region=current_region,
            pdf_filename=booklet_pdf.filename,
            extracted_at=extracted_at,
            source_citation=source_citation,
        )
        rows.append(row)

    # Deterministic sort: (region_order, bmu_number). Fail-loud with context if
    # any row carries an unrecognized hd_region — a bare KeyError from the sort
    # would obscure which BMU caused it.
    def _sort_key(r: BmuRowExtraction) -> tuple[int, int]:
        region = r["hd_region"]
        if region not in _REGION_ORDER:
            raise PdfExtractionError(
                f"BMU {r['bmu_number']} has unrecognized hd_region {region!r}; "
                f"valid values are {sorted(_REGION_ORDER)}"
            )
        return (_REGION_ORDER[region], r["bmu_number"])

    rows.sort(key=_sort_key)

    # Fail-loud guard: catastrophic regression if below the minimum floor.
    if len(rows) < _MIN_EXPECTED_BMU_COUNT:
        raise PdfExtractionError(
            f"extracted {len(rows)} BMUs, below floor of {_MIN_EXPECTED_BMU_COUNT} "
            f"(expected {_EXPECTED_BMU_COUNT}); FWP may have changed the table format"
        )

    # Soft guard: visible diagnostic if count differs from expected.
    if len(rows) != _EXPECTED_BMU_COUNT:
        _logger.warning(
            "extracted %d BMUs, expected %d",
            len(rows),
            _EXPECTED_BMU_COUNT,
        )

    closures = _extract_closures(
        booklet_pdf,
        booklet_pdf.filename,
        extracted_at,
        source_citation,
    )

    reporting_obligations = _extract_reporting_obligations(
        booklet_pdf,
        booklet_pdf.filename,
        extracted_at,
        source_citation,
    )

    statewide_rules = _extract_statewide_rules(
        booklet_pdf,
        booklet_pdf.filename,
        source_citation["id"],
        source_citation["publication_date"],
        extracted_at,
    )

    return BlackBearBaseExtraction(
        state="MT",
        species_group="black_bear",
        license_year=_LICENSE_YEAR,
        schema_version=2,
        extracted_at=extracted_at,
        source=source_citation,
        rows=rows,
        closures=closures,
        reporting_obligations=reporting_obligations,
        statewide_rules=statewide_rules,
    )


# ---------------------------------------------------------------------------
# T11: Pass-2 correction parser → CorrectionExtraction
#
# Pre-implementation probe (2026-05-09, correction PDF p. 1):
#
#   Verbatim pdfplumber output (repr):
#   'Corrections to the 2026 Printed Black Bear Regulations\n
#    • Page under Hound Hunting: Persons using hounds to hunt are required to have a valid\n
#    Resident Black Bear License if hunting or chasing during the black bear hunting season, or\n
#    a valid Class D-3 Resident Hound Training License during a training season from the end of\n
#    the spring season for black bear through June 15 of that year as authorized by the\n
#    commission. Nonresidents must also have a Nonresident Hound License during the hunting\n
#    or training season if they are using dogs.\n
#    • Removed the hound training season column from the BMU tables on pages. Statutorily\n
#    the training season begins following the end of spring bear and runs until June 15.'
#
#   The correction has exactly two bullet points:
#   1. Hound license clarification (V1 deferred — no operations generated).
#   2. Column removal notice — this is the anchor bullet that drives operations.
#
#   The plan's stated anchor "Removed the hound training season column" is a
#   SUBSTRING of the actual bullet text "Removed the hound training season column
#   from the BMU tables on pages." — the case-insensitive substring search
#   succeeds as planned.
#
#   The anchoring sentence captured for verbatim_correction_text:
#   "Removed the hound training season column from the BMU tables on pages.
#    Statutorily the training season begins following the end of spring bear and
#    runs until June 15."
#   (after _rejoin_hyphenated_linebreaks — the \n between "Statutorily" and "the"
#   is a word-wrap linebreak but does NOT match the (?<=[a-z])-\n(?=[a-z]) pattern
#   because there is no hyphen; we apply a second collapse for bare-word-wrap \n
#   within the captured sentence only, using re.sub(r"\s*\n\s*", " ", ...) to
#   produce a single-line verbatim_correction_text.)
# ---------------------------------------------------------------------------

# Regex to find the start of the second bullet (column-removal anchor) in the
# correction PDF prose.  Case-insensitive substring match.
_CORRECTION_ANCHOR = "Removed the hound training season column"


def _extract_correction(
    correction_pdf: PdfDocument,
    correction_citation: SourceCitationDict,
    extracted_at: str,
    base_rows: list[BmuRowExtraction],
) -> CorrectionExtraction:
    """Parse the 1-page correction PDF and synthesize per-BMU CorrectionOperations.

    Caller contract: *correction_pdf* is an already-open PdfDocument.  This
    function does NOT call ``open_pdf()`` — the resource lifecycle lives in the
    caller's ``with open_pdf(...) as correction_pdf:`` block (T12's ``main()``).
    The pattern mirrors ``_extract_base``, which also receives an already-open
    PdfDocument.

    Algorithm:
      1. Extract page text from the correction PDF's single page (pp. 1–1).
      2. Locate the anchor substring ``"Removed the hound training season column"``
         (case-insensitive).  Fail-loud if not found — indicates FWP changed the
         prose between editions (cross-edition drift guard per ADR-001).
      3. Capture the full anchoring sentence from the anchor position to the next
         ``"."`` boundary.  Apply ``_rejoin_hyphenated_linebreaks`` first (for
         letter-hyphen-newline collapses), then collapse bare word-wrap newlines
         within the captured text (``re.sub(r"\\s*\\n\\s*", " ", ...)``).
      4. Synthesize one ``CorrectionOperation`` per entry in ``base_rows``.
         All operations share ``target_field="hound_training_season"``,
         ``change="remove"``, and ``new_value=None``.  Order matches ``base_rows``
         (which T10 sorted deterministically by region + bmu_number).

    V1 deferral — first bullet ("Persons using hounds…hound training license…"):
      The first correction bullet clarifies hound-license requirements.  It does
      NOT change any BMU-table cell value; it is a regulatory clarification prose,
      not a table edit.  In V1 we capture its text for audit purposes (logged at
      INFO level) but do NOT generate operations from it.

    Returns a ``CorrectionExtraction`` dict with:
      - ``extracted_at``: from the correction PDF manifest.
      - ``source``: the correction citation dict.
      - ``operations``: list of ``CorrectionOperation`` dicts (one per BMU in
        ``base_rows``).
    """
    # Step 1: extract page text.
    page_text: str | None = None
    for _page_num, page in iter_pages(correction_pdf, 1, 1):
        page_text = extract_text(page)
    if page_text is None:
        raise PdfExtractionError(
            "correction PDF: iter_pages yielded no pages for p. 1 of "
            f"{correction_pdf.filename!r} — check that the correction PDF is on disk"
        )

    # Step 2: locate the column-removal anchor (case-insensitive).
    lower_text = page_text.lower()
    lower_anchor = _CORRECTION_ANCHOR.lower()
    anchor_pos = lower_text.find(lower_anchor)
    if anchor_pos == -1:
        raise PdfExtractionError(
            "correction PDF prose does not contain expected "
            "'Removed the hound training season column' anchor; "
            "FWP may have changed the correction text"
        )

    # V1 deferral: log the first bullet for audit trail.
    first_bullet_anchor = "• "
    second_bullet_start = page_text.rfind("•", 0, anchor_pos)
    if second_bullet_start != -1:
        # Locate the first bullet by searching for the first "•" before the anchor.
        first_bullet_pos = page_text.find(first_bullet_anchor)
        if first_bullet_pos != -1 and first_bullet_pos < second_bullet_start:
            first_bullet_text = page_text[first_bullet_pos:second_bullet_start].strip()
            _logger.info(
                "correction PDF first bullet (V1 deferred — no operations generated): %s",
                first_bullet_text[:120],
            )

    # Step 3: capture the anchoring bullet's full text. The bullet contains TWO
    # sentences separated by a period; we want both for context. To avoid
    # silently capturing unrelated trailing content (a future edition adding a
    # third bullet, a footnote, or any prose after the bullet would have the
    # naive `rfind(".")` swallow it all), bound the capture to the next bullet
    # marker ("•") or end-of-text — whichever comes first — then apply
    # `rfind(".")` within that bounded slice.
    next_bullet_pos = page_text.find("•", anchor_pos + len(_CORRECTION_ANCHOR))
    if next_bullet_pos == -1:
        bullet_end = len(page_text)
    else:
        bullet_end = next_bullet_pos
    sentence_text_raw = page_text[anchor_pos:bullet_end]

    last_period = sentence_text_raw.rfind(".")
    if last_period != -1:
        sentence_raw = sentence_text_raw[: last_period + 1]
    else:
        sentence_raw = sentence_text_raw.strip()

    # Apply hyphenated-linebreak re-join (letter-hyphen-newline pattern).
    sentence_joined = _rejoin_hyphenated_linebreaks(sentence_raw)
    # Collapse bare word-wrap newlines within the sentence to a single space.
    verbatim_sentence = re.sub(r"\s*\n\s*", " ", sentence_joined).strip()

    # Step 4: synthesize one CorrectionOperation per BMU in base_rows.
    operations: list[CorrectionOperation] = []
    for row in base_rows:
        op: CorrectionOperation = {
            "target_bmu": row["bmu_number"],
            "target_field": "hound_training_season",
            "change": "remove",
            "new_value": None,
            "verbatim_correction_text": verbatim_sentence,
            "source_id": correction_citation["id"],
            "source_publication_date": correction_citation["publication_date"],
        }
        operations.append(op)

    return CorrectionExtraction(
        extracted_at=extracted_at,
        source=correction_citation,
        operations=operations,
    )


# ---------------------------------------------------------------------------
# T12: Pass-3 date-arbitrated merge + collision guard + CLI main
# ---------------------------------------------------------------------------


class CorrectionConflictError(Exception):
    """Raised when two correction operations target the same cell with equal publication_date."""


def _merge_with_corrections(
    base: BlackBearBaseExtraction,
    correction: CorrectionExtraction,
) -> BlackBearMergedExtraction:
    """Merge the base extraction with correction operations using doc-type precedence.

    **Option B — doc-type precedence (NOT literal MAX-date as spec says):**

    The spec states "MAX publication_date wins" for per-cell arbitration.  In
    the 2026 V1 reality this rule inverts operator intent: the booklet date
    (2026-04-27) is *later* than the correction date (2026-03-18), so a naive
    MAX-date implementation would treat the booklet as the winner and the
    correction would never apply — silently discarding the correction.

    Option B: ``document_type='correction'`` ALWAYS wins over
    ``document_type='annual_regulations'``, regardless of publication_date.
    Date comparison is used ONLY for tiebreaking among multiple corrections
    targeting the same (bmu, field) cell.  If multiple corrections share the
    MAX date for the same cell, ``CorrectionConflictError`` is raised.

    V1 simplification: per-row ``source_id`` / ``source_publication_date`` is
    a single value (not per-cell).  When a correction touches a row, the row's
    source attribution is updated to the winning correction's source.  Full
    per-cell source attribution would require a cell-level structure that
    S03.6's ``RegulationRecord`` schema does not currently support.

    Args:
        base:       Pass-1 artifact (booklet-only extraction).
        correction: Pass-2 artifact (correction PDF parsed into operations).

    Returns:
        Pass-3 merged artifact with ``applied_correction=True`` and demoted
        ``extraction_confidence`` for every row touched by a correction op.

    Raises:
        PdfExtractionError:      if a correction op targets an unknown BMU.
        CorrectionConflictError: if two ops target the same cell with equal
                                 ``source_publication_date``.
    """
    # Deep-copy base rows so the base artifact stays immutable.
    merged_rows: list[BmuRowExtraction] = [copy.deepcopy(r) for r in base["rows"]]

    # Index correction operations by (target_bmu, target_field). Validate the
    # target_field against the known BmuRowExtraction column set so a typo in
    # a future correction (e.g., "hound_training_seasons") fails loud rather
    # than silently adding a new dict key — TypedDict writes are unchecked at
    # runtime because they're plain dicts under the hood.
    ops_by_target: dict[tuple[int, str], list[CorrectionOperation]] = {}
    for op in correction["operations"]:
        op_field = op["target_field"]
        if op_field not in _CORRECTABLE_FIELDS:
            raise PdfExtractionError(
                f"correction operation targets unknown BmuRowExtraction field "
                f"{op_field!r} for BMU {op['target_bmu']}; valid fields are "
                f"{sorted(_CORRECTABLE_FIELDS)}"
            )
        key = (op["target_bmu"], op_field)
        ops_by_target.setdefault(key, []).append(op)

    # Stage 1 — per-cell arbitration: for each (bmu, field) targeted by one or
    # more ops, select the winning op by MAX source_publication_date among
    # same-doc-type sources. Raise CorrectionConflictError on equal-date ties.
    # The winning-op map is keyed by (bmu, field).
    winning_op_by_cell: dict[tuple[int, str], CorrectionOperation] = {}
    for (bmu, field), ops in ops_by_target.items():
        if not any(r["bmu_number"] == bmu for r in merged_rows):
            raise PdfExtractionError(f"correction targets unknown BMU {bmu}")
        max_date = max(op["source_publication_date"] for op in ops)
        winners = [op for op in ops if op["source_publication_date"] == max_date]
        if len(winners) > 1:
            raise CorrectionConflictError(
                f"BMU {bmu} field {field}: equal publication_date {max_date} "
                f"for source_ids {[op['source_id'] for op in winners]}"
            )
        winning_op_by_cell[(bmu, field)] = winners[0]

    # Stage 2 — apply field-level value changes.
    for (bmu, field), winning_op in winning_op_by_cell.items():
        row = next(r for r in merged_rows if r["bmu_number"] == bmu)
        if winning_op["change"] == "remove":
            row[field] = None  # type: ignore[literal-required]
        else:
            # "set" or "replace"
            row[field] = winning_op["new_value"]  # type: ignore[literal-required]

    # Stage 3 — row-level provenance and confidence demotion: apply EXACTLY
    # ONCE per touched BMU, regardless of how many fields were touched.
    # Previously this lived inside the per-(bmu, field) loop, which caused:
    #   (a) source_id/source_publication_date to be overwritten on each
    #       iteration, so the final row-level provenance depended on dict
    #       insertion order rather than a deterministic rule;
    #   (b) demote_one_tier to fire N times for a row touched by N
    #       field-level ops, e.g., a HIGH row + 2 corrections would demote
    #       to LOW (over-demotion), violating ADR-017 §4's single-step rule.
    # Row-level source attribution reflects the MAX-date winning op across
    # ALL ops touching the row — "the latest authoritative source touching
    # this row". On equal-date ties (two corrections targeting different
    # fields with identical publication_date), break by lexicographically
    # smallest source_id so the choice is fully deterministic regardless of
    # dict / list iteration order. A lex tiebreaker is preferred over
    # CorrectionConflictError here because equal-date different-field ops
    # are not a semantic conflict — both ops are applied at the cell level;
    # only the row-level "last touched by" provenance needs a single answer.
    bmu_touched_ops: dict[int, list[CorrectionOperation]] = {}
    for (bmu, _field), winning_op in winning_op_by_cell.items():
        bmu_touched_ops.setdefault(bmu, []).append(winning_op)
    for bmu, winning_ops in bmu_touched_ops.items():
        row = next(r for r in merged_rows if r["bmu_number"] == bmu)
        # Two-pass selection: first find the latest date, then break date-ties
        # by lexicographically smallest source_id. This avoids relying on
        # list / dict iteration order for a deterministic outcome.
        row_max_date = max(op["source_publication_date"] for op in winning_ops)
        row_date_ties = [
            op for op in winning_ops if op["source_publication_date"] == row_max_date
        ]
        row_winner = min(row_date_ties, key=lambda op: op["source_id"])
        row["applied_correction"] = True
        row["supersedes"] = base["source"]["id"]
        row["source_id"] = row_winner["source_id"]
        row["source_publication_date"] = row_winner["source_publication_date"]
        row["extraction_confidence"] = demote_one_tier(row["extraction_confidence"])

    return BlackBearMergedExtraction(
        state="MT",
        species_group=_SPECIES_GROUP,
        license_year=_LICENSE_YEAR,
        schema_version=2,
        extracted_at=base["extracted_at"],
        sources=[base["source"], correction["source"]],
        rows=merged_rows,
        closures=base["closures"],
        reporting_obligations=base["reporting_obligations"],
        statewide_rules=base["statewide_rules"],
    )


def _write_deterministic_json(path: Path, data: object) -> None:
    """Write ``data`` to ``path`` as deterministic JSON with atomic .tmp rename.

    Uses sort_keys=True, indent=2, ensure_ascii=False, trailing newline.
    Atomic .tmp rename prevents partial writes from corrupting the artifact
    if the process is interrupted mid-write.

    Note on serialization:
      - ``ConfidenceTier`` values are ``str`` subclasses so ``json.dumps``
        serializes them as plain strings (e.g., ``"high"``, not
        ``"ConfidenceTier.HIGH"``).
      - ``bbox`` is a ``tuple`` in the TypedDict; ``json.dumps`` serializes
        tuples as JSON arrays, so the deserialized form is a list, not a tuple.
        This is expected and documented V1 behavior.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(serialized, encoding="utf-8")
    tmp_path.replace(path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the Black Bear extractor.

    Usage::

        ingestion/.venv/bin/python ingestion/states/montana/extract_black_bear.py
        ingestion/.venv/bin/python ingestion/states/montana/extract_black_bear.py \\
            --booklet-pdf /path/to/booklet.pdf \\
            --correction-pdf /path/to/correction.pdf
    """
    parser = argparse.ArgumentParser(description="Extract Montana Black Bear regulations")
    parser.add_argument("--booklet-pdf", type=Path, default=_BOOKLET_PDF_PATH)
    parser.add_argument("--correction-pdf", type=Path, default=_CORRECTION_PDF_PATH)
    parser.add_argument("--out-base", type=Path, default=_BASE_OUTPUT_PATH)
    parser.add_argument("--out-correction", type=Path, default=_CORRECTION_OUTPUT_PATH)
    parser.add_argument("--out-merged", type=Path, default=_MERGED_OUTPUT_PATH)
    args = parser.parse_args(argv)

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    booklet_citation = _load_citation_from_sources_yaml(_BOOKLET_CITATION_ID)
    correction_citation = _load_citation_from_sources_yaml(_CORRECTION_CITATION_ID)

    booklet_extracted_at = _load_extracted_at_from_manifest(args.booklet_pdf)
    correction_extracted_at = _load_extracted_at_from_manifest(args.correction_pdf)

    with open_pdf(args.booklet_pdf) as booklet_pdf:
        base = _extract_base(booklet_pdf, booklet_citation, booklet_extracted_at)

    with open_pdf(args.correction_pdf) as correction_pdf:
        correction = _extract_correction(
            correction_pdf, correction_citation, correction_extracted_at, base["rows"]
        )

    merged = _merge_with_corrections(base, correction)

    _write_deterministic_json(args.out_base, base)
    _write_deterministic_json(args.out_correction, correction)
    _write_deterministic_json(args.out_merged, merged)

    _logger.info("wrote %d BMU rows to %s", len(merged["rows"]), args.out_merged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
