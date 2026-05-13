"""
Montana FWP Legal Descriptions PDF extraction (S03.5).

Extraction approach
-------------------
The Legal Descriptions PDF (``mt-fwp-legal-descriptions-2026-2027-2026-02-03.pdf``,
56 pages, biennial citation id ``mt-fwp-legal-descriptions-2026-2027``) is a
three-column document. The TOC on page 2 enumerates nine sections; only three
have matching geometry rows in the V1 Montana DB:

  Section              PDF pages   V1 in scope?  Namespace
  ─────────────────    ─────────   ────────────  ─────────────────────────────
  Region Descriptions  3–4         No            (no geometry rows)
  Antelope HDs         5–9         Yes           ``antelope``
  Bighorn Sheep HDs    10–12       No            (no geometry rows)
  Bison HDs            13          No            (no geometry rows)
  Black Bear MUs       14–18       Yes           ``bear``
  Deer and Elk HDs     19–35       Yes           ``deer-elk-lion``
  Moose HDs            36–42       No            (no geometry rows)
  Mountain Goat HDs    43–45       No            (no geometry rows)
  Mountain Lion HDs    46–53       No            (no geometry rows)
  Contacts             54–56       —             (skip)

**V1 scope decision:** this extractor walks ONLY V1 pages (5–9, 14–18, 19–35).
Bighorn Sheep, Bison, Moose, Mountain Goat, and Mountain Lion sections are
explicitly excluded (no geometry rows to match against) and their headings are
NOT surfaced as ``unmatched``. This keeps the 10% fail-loud threshold
meaningful — the rate is computed over V1 candidates only.

Three-column layout
-------------------
Each content page is split into three columns at approximately:
  col1: x 36–195 pt
  col2: x 210–355 pt
  col3: x 390–555 pt
Column bboxes are derived from S03.5 discovery (see T3 for the exact
cropping primitive). Rotated sidebar banners (chapter labels) are excluded
by filtering to upright chars only.

Matching rule
-------------
For HD sections:
  - Extract HD number from ``\\d{2,3}`` regex in the heading line.
  - Determine species namespace from V1 section page-range context (antelope /
    bear / deer-elk-lion — set as the page-walk advances through sections).
  - geometry_id pattern: ``MT-HD-{namespace}-{number}-geom``

For named CWD zones (appear within deer-elk-lion pages 19–35):
  - ``Libby CWD Management Zone``     → ``MT-CWD-zone-libby-cwd-management-zone-geom``
  - ``Kalispell Area CWD Management Zone`` → ``MT-CWD-zone-kalispell-cwd-management-zone-geom``
  - Lookup is hardcoded (the "Area" word is dropped in the geometry slug —
    discovered during S03.5 planning).

Explicitly out of V1 scope (land in ``unlinked``)
-------------------------------------------------
- All 55 ``portion`` geometry rows (suffixes like ``elPt22`` / ``wtPt12`` are
  not derivable from PDF heading text).
- All 54 ``restricted_area`` geometry rows (no headed sections in this PDF;
  they appear only as prose modifiers inside HD descriptions).
- ``MT-STATEWIDE-geom`` (kind=state; no boundary prose in this booklet).
- "Portion of HD NNN" sub-headings inside the PDF (~50 occurrences): captured
  but surfaced as ``unmatched`` (no automatic resolution to opaque Pt suffixes).

Cleanup rules (S03.3 UAT discipline — every rule documented here)
-----------------------------------------------------------------
All cleanup rules are applied to the assembled ``verbatim_description`` field
only. The body text inside each extraction artifact is the source of truth for
downstream ``geometry.legal_description`` writes (S03.6).

  Rule A — internal whitespace collapse:
      ``re.sub(r"\\s+", " ", body).strip()``
      Scope: assembled ``verbatim_description`` only.
      Rationale: three-column extraction interpolates line breaks and tab gaps
      that are not meaningful prose boundaries. All source words, numeric
      tokens, and units are preserved byte-exact; only repeated whitespace
      (including newlines) collapses to a single space.
      Per ADR-008 § "pdfplumber baseline": this whitespace collapse is
      acceptable because numeric tokens, units, and lexical words are preserved.
      Locked by test ``TestBuildArtifact::test_whitespace_collapse_applied``.

  Rule B — heading text stripped:
      The heading regex match's end-position is where the body begins, so the
      heading text itself is naturally excluded from the body. Body = the prose
      after the colon and trailing keyword phrase ("Beginning at the junction
      of US-89 and..." onward). No explicit strip call needed — the regex
      anchor handles it.
      Locked by test ``TestBuildArtifact::test_heading_text_not_in_body``.

Fail-loud threshold
-------------------
``unmatched_rate = len(unmatched) / (len(matched) + len(unmatched))``
If > 0.10 (10%), raise ``PdfExtractionError`` and exit 1. Below threshold:
WARN log only.

Single-writer contract
----------------------
S03.5 emits JSON only (``legal-descriptions-2026.json``). NO database writes.
NO regulation_record / season_definition / license_tag / reporting_obligation
rows. S03.6 reads the artifact and writes ``geometry.legal_description``.

ADR references
--------------
  ADR-001  Authority preserved, not replaced — fail loud; no invented values.
  ADR-005  Python ingestion / TypeScript serving language split.
  ADR-008  Verbatim regulation text — Rule A whitespace collapse is the only
           normalization applied; all source words are byte-exact preserved.
  ADR-017  Confidence calibration + parent-inheritance rule — ``high`` for
           clean unambiguous match; ``low`` for multiple candidates within one
           namespace (should be impossible, but guarded). ``medium`` is NOT
           used for heading-to-geometry matching.
  ADR-018  E03 schema additions — ``geometry.legal_description`` is the target
           column that S03.6 populates from this artifact.
"""

# State-specific module — must NOT import from ingestion.states.<other_state>.
# Cross-state imports violate ADR-005 isolation (each state adapter is fully
# self-contained). The state-agnostic guard test enforces this via AST walk.

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator, Literal, TypedDict, cast

import yaml
from ingestion.lib.pdf import (
    ConfidenceTier,
    PageReference,
    PdfExtractionError,
    iter_pages,
    open_pdf,
)

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants (mirrors extract_black_bear.py:127-136 naming)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MONTANA_DIR = _REPO_ROOT / "ingestion" / "states" / "montana"
_SOURCES_YAML = _MONTANA_DIR / "sources.yaml"
_PDF_FILENAME = "mt-fwp-legal-descriptions-2026-2027-2026-02-03.pdf"
_PDF_PATH = _MONTANA_DIR / "fixtures" / _PDF_FILENAME
_OUTPUT_DIR = _MONTANA_DIR / "extracted"
_OUTPUT_PATH = _OUTPUT_DIR / "legal-descriptions-2026.json"
_GEOMETRY_FIXTURE_PATH = _MONTANA_DIR / "fixtures" / "geometry-overlays.json"
_CITATION_ID = "mt-fwp-legal-descriptions-2026-2027"

# Hardcoded CWD zone heading → geometry_id mapping.
# The "Area" word in the Kalispell heading is dropped in the geometry slug —
# discovered during S03.5 planning. This constant is verified against the
# fixture at runtime by ``_load_geometry_lookup``.
_CWD_HEADING_TO_GEOMETRY_ID: dict[str, str] = {
    "Libby CWD Management Zone": "MT-CWD-zone-libby-cwd-management-zone-geom",
    "Kalispell Area CWD Management Zone": "MT-CWD-zone-kalispell-cwd-management-zone-geom",
}

# V1 species-section page ranges (1-based, half-open Python ranges).
# Python ranges are half-open: range(5, 10) yields 5,6,7,8,9 (inclusive 5..9).
# Section boundaries from TOC inspection (PDF page 2):
#   antelope:       pp. 5..9      (5 content pages)
#   bear (BMUs):    pp. 14..18    (5 content pages; last bear page = 18)
#   deer-elk-lion:  pp. 19..35    (17 content pages; first DEL page = 19)
# Pages 10..13 (bighorn sheep + bison) and 36..53 (moose, goat, lion) are
# OUT of V1 scope — no geometry rows to match against.
_V1_SECTIONS: tuple[tuple[str, range], ...] = (
    ("antelope", range(5, 10)),
    ("bear", range(14, 19)),
    ("deer-elk-lion", range(19, 36)),
)

# Column boundaries on the 594pt-wide Legal Descriptions PDF page,
# derived during S03.5 discovery (PDF inspection 2026-05-12). The PDF
# uses a three-column layout for all content pages (5-53).
# Header strip top=40pt removes running title; footer strip bottom=20pt
# removes page number.
_COLUMN_LEFT_X = (36.0, 195.0)
_COLUMN_MIDDLE_X = (210.0, 355.0)
_COLUMN_RIGHT_X = (390.0, 555.0)
_HEADER_STRIP_PT = 40.0
_FOOTER_STRIP_PT = 20.0

# ---------------------------------------------------------------------------
# TypedDicts
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


class LegalDescriptionEntry(TypedDict):
    """One matched heading → geometry binding with extracted prose body."""

    geometry_id: str
    geometry_kind: str
    verbatim_description: str
    page_reference: PageReference
    extraction_confidence: str


class UnmatchedEntry(TypedDict):
    """A heading that was recognized but could not be resolved to a geometry_id."""

    heading_text: str
    page_reference: PageReference
    reason: str


class UnlinkedEntry(TypedDict):
    """A geometry_id in the V1 fixture that had no corresponding heading in the PDF."""

    geometry_id: str
    geometry_kind: str
    reason: str


class LegalDescriptionsArtifact(TypedDict):
    """Root envelope written to ``legal-descriptions-2026.json``."""

    source_id: str
    extracted_at: str
    matched: list[LegalDescriptionEntry]
    unmatched: list[UnmatchedEntry]
    unlinked: list[UnlinkedEntry]


# ---------------------------------------------------------------------------
# Helper functions (copied verbatim from extract_black_bear.py:341 and :381)
# ---------------------------------------------------------------------------


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
    try:
        datetime.datetime.fromisoformat(fetched_at)
    except ValueError as exc:
        raise PdfExtractionError(
            f"manifest at {manifest_path} has 'fetched_at' value {fetched_at!r} "
            f"that is not a valid ISO-8601 timestamp ({exc})"
        ) from exc
    return fetched_at


# Regex for filtering HD geometry IDs to only the three V1 namespaces.
# Prevents accidental inclusion of portion-kinded rows whose IDs may also
# start with the ``MT-HD-`` prefix.
_HD_GEOMETRY_ID_RE = re.compile(
    r"^MT-HD-(antelope|bear|deer-elk-lion)-(\d+)-geom$"
)

# ---------------------------------------------------------------------------
# Heading-detection regexes (T4)
# ---------------------------------------------------------------------------

# Matches numeric HD headings, e.g.:
#   "215 East Deer Lodge: Those portions of Granite County lying within..."
# Group 1: HD number (2–3 digits)
# Group 2: HD name text (3–80 chars, not containing ":" or newline)
# ``[^:\n]`` (not ``[^:]``) prevents the lazy name capture from crossing
# newlines: a stray "93 in Missoula County." prior-body fragment must not
# swallow the next line's "261 East Bitterroot: That portion..." heading.
# Discovered 2026-05-12 — without the ``\n`` exclusion, HD 261/262 silently
# surfaced as unmatched and HD 93 (not in the DB) appeared instead.
_HD_HEADING_RE = re.compile(
    r"^\s*(\d{2,3})\s+([^:\n]{3,80}?):\s+(?:Those portions?|That portion)\b",
    re.MULTILINE,
)

# Matches the two V1 CWD named-zone headings. Discovery 2026-05-12: narrow
# three-column layout wraps the "Those portions of..." anchor phrase (and
# even the trailing "Zone:" for Kalispell) onto a continuation line, so we
# CANNOT require the colon or anchor phrase here — only the zone name prefix.
# The "Zone" suffix on Kalispell is optional because page 21 col 2 reads
# 'Kalispell Area CWD Management' on its own line with "Zone:" wrapped off.
# The literal zone names are unique enough; false positives are not credible.
# Group 1: zone name (may lack "Zone" suffix for Kalispell). T7 normalizes.
_CWD_HEADING_RE = re.compile(
    r"^\s*(Libby CWD Management Zone|Kalispell Area CWD Management(?:\s+Zone)?)\b",
    re.MULTILINE,
)

# Matches "Portion of HD NNN" sub-headings (~50 per PDF).
# These are captured and surfaced as ``unmatched`` (no automatic resolution
# to opaque ``Pt{N}`` suffixes — see plan § "Out of scope").
# Group 1: HD number (2–3 digits)
_PORTION_HEADING_RE = re.compile(
    r"^\s*Portion of HD\s+(\d{2,3})\b",
    re.MULTILINE,
)


def _load_geometry_lookup(
    fixture_path: Path,
) -> tuple[
    dict[tuple[str, int], str],   # hd_lookup: (species_namespace, hd_number) → geometry_id
    dict[str, str],                # cwd_lookup: heading_text → geometry_id
    list[tuple[str, str]],         # all_v1_ids: (geometry_id, geometry_kind) for the union
]:
    """Load ``geometry-overlays.json`` and build the lookup structures for T3–T8.

    Returns:
        hd_lookup:   Maps ``(species_namespace_str, hd_number_int)`` to
                     ``geometry_id``.  Species namespace values are
                     ``"antelope"``, ``"bear"``, and ``"deer-elk-lion"``.
        cwd_lookup:  Maps normalized heading text (verbatim PDF heading) to
                     ``geometry_id`` for the two V1 CWD zones.  Populated
                     from the ``_CWD_HEADING_TO_GEOMETRY_ID`` constant and
                     verified against the fixture.
        all_v1_ids:  List of ``(geometry_id, geometry_kind)`` tuples covering
                     every in-scope V1 ID: all HD rows in the three namespaces
                     plus the 2 CWD zones.  Used by T8 to compute the
                     ``unlinked`` array.

    Fail-loud invariants (ADR-001):
        - If ``hd_lookup`` is empty after construction → ``PdfExtractionError``.
        - If ``cwd_lookup`` is empty after construction → ``PdfExtractionError``.
        - If a hardcoded CWD target ID is absent from the fixture →
          ``PdfExtractionError`` naming the missing ID.
    """
    with fixture_path.open() as fh:
        entries: list[dict[str, str]] = json.load(fh)

    # --- HD lookup (filter to V1 namespaces only) ---------------------------
    hd_lookup: dict[tuple[str, int], str] = {}
    hd_v1_ids: list[tuple[str, str]] = []

    for entry in entries:
        child_kind = entry.get("child_kind", "")
        child_id = entry.get("child_geometry_id", "")
        if child_kind != "hunting_district":
            continue
        m = _HD_GEOMETRY_ID_RE.match(child_id)
        if not m:
            continue
        namespace = m.group(1)   # "antelope" | "bear" | "deer-elk-lion"
        hd_number = int(m.group(2))
        key = (namespace, hd_number)
        hd_lookup[key] = child_id
        hd_v1_ids.append((child_id, child_kind))

    if not hd_lookup:
        raise PdfExtractionError(
            f"Geometry HD lookup is empty — fixture regression or fixture path wrong: "
            f"{fixture_path}"
        )

    # --- CWD lookup — verify hardcoded targets exist in the fixture ---------
    fixture_cwd_ids = {
        entry["child_geometry_id"]
        for entry in entries
        if entry.get("child_kind") == "cwd_zone"
    }
    missing = [
        target_id
        for target_id in _CWD_HEADING_TO_GEOMETRY_ID.values()
        if target_id not in fixture_cwd_ids
    ]
    if missing:
        raise PdfExtractionError(
            f"CWD geometry IDs hardcoded in _CWD_HEADING_TO_GEOMETRY_ID are absent from "
            f"the fixture: {missing!r}. Fixture path: {fixture_path}"
        )

    cwd_lookup: dict[str, str] = dict(_CWD_HEADING_TO_GEOMETRY_ID)

    if not cwd_lookup:
        raise PdfExtractionError(
            f"CWD lookup is empty — fixture regression or fixture path wrong: "
            f"{fixture_path}"
        )

    # --- all_v1_ids: HD rows + CWD zones ------------------------------------
    cwd_v1_ids: list[tuple[str, str]] = [
        (geom_id, "cwd_zone") for geom_id in cwd_lookup.values()
    ]
    all_v1_ids: list[tuple[str, str]] = hd_v1_ids + cwd_v1_ids

    return hd_lookup, cwd_lookup, all_v1_ids


# T3: Column-cropping primitive. Bboxes from S03.5 discovery; see plan § T3.
def _extract_three_column_text(page: Any) -> tuple[str, str, str]:
    """Extract column text from a three-column FWP Legal Descriptions page.

    Crops the page to each of three column bboxes; filters out non-upright
    chars (rotated sidebar banners like 'klE & reeD'); returns the per-column
    text in left-to-right order.

    Empty/missing column text returns "" rather than None.
    """
    page_height: float = page.height
    columns = (
        (page.crop((_COLUMN_LEFT_X[0], _HEADER_STRIP_PT, _COLUMN_LEFT_X[1], page_height - _FOOTER_STRIP_PT))),
        (page.crop((_COLUMN_MIDDLE_X[0], _HEADER_STRIP_PT, _COLUMN_MIDDLE_X[1], page_height - _FOOTER_STRIP_PT))),
        (page.crop((_COLUMN_RIGHT_X[0], _HEADER_STRIP_PT, _COLUMN_RIGHT_X[1], page_height - _FOOTER_STRIP_PT))),
    )
    col1 = columns[0].filter(lambda c: c.get("upright", True)).extract_text() or ""
    col2 = columns[1].filter(lambda c: c.get("upright", True)).extract_text() or ""
    col3 = columns[2].filter(lambda c: c.get("upright", True)).extract_text() or ""
    return col1, col2, col3


# ---------------------------------------------------------------------------
# HeadedBlock dataclass and column-stream splitter (T4)
# ---------------------------------------------------------------------------


@dataclass
class HeadedBlock:
    """One heading-delimited prose block extracted from a three-column page stream.

    Attributes:
        kind:         ``"hd"`` — numeric district heading (``_HD_HEADING_RE``);
                      ``"cwd"`` — named CWD zone heading (``_CWD_HEADING_RE``);
                      ``"portion"`` — "Portion of HD NNN" sub-heading
                      (``_PORTION_HEADING_RE``);
                      ``"continuation"`` — leading prose before any heading on
                      the page (T8 folds this into the prior page's last block).
        heading_text: The heading line as it appeared in the stream
                      (``stream_text[match.start():match.end()].strip()``).
                      Empty string for ``kind="continuation"``.
        hd_number:    Populated for ``kind="hd"`` and ``kind="portion"``;
                      ``None`` otherwise.
        cwd_name:     Populated for ``kind="cwd"``; ``None`` otherwise.
        body_raw:     Body prose sliced from the stream verbatim — NO whitespace
                      collapse here.  Rule A (``re.sub(r"\\s+", " ", body).strip()``)
                      is applied in T8 at artifact-assembly time.
        page_num_1based: 1-based page number the heading was found on.
    """

    kind: Literal["hd", "cwd", "portion", "continuation"]
    heading_text: str
    hd_number: int | None
    cwd_name: str | None
    body_raw: str
    page_num_1based: int


def _split_column_stream_into_blocks(
    stream_text: str,
    page_num_1based: int,
) -> list[HeadedBlock]:
    """Split a page's column-concatenated text into headed blocks.

    Detects three heading shapes — HD (numeric), CWD (named zone), and
    Portion-of-HD sub-headings — and emits one HeadedBlock per heading
    with body=text-between-this-heading-and-the-next.

    If the stream begins with prose before any heading match, emits a
    single ``kind="continuation"`` block at the start so T8 can fold
    that prose into the prior page's last block.

    Each block's ``body_raw`` is verbatim (no whitespace collapse here;
    T8's Cleanup Rule A handles that at artifact-assembly time).

    Args:
        stream_text:      Concatenated column text for one page (col1 + col2 + col3).
        page_num_1based:  The 1-based page number this stream came from.

    Returns:
        Ordered list of ``HeadedBlock`` instances.  Empty list when the stream
        is empty or whitespace-only.
    """
    if not stream_text or not stream_text.strip():
        return []

    # Collect all heading matches from all three patterns into a single list,
    # each entry: (start, end, kind, hd_number, cwd_name, heading_text).
    _MatchRecord = tuple[int, int, str, int | None, str | None, str]
    matches: list[_MatchRecord] = []

    for m in _HD_HEADING_RE.finditer(stream_text):
        hd_num = int(m.group(1))
        heading_text = stream_text[m.start():m.end()].strip()
        matches.append((m.start(), m.end(), "hd", hd_num, None, heading_text))

    for m in _CWD_HEADING_RE.finditer(stream_text):
        cwd_name = m.group(1)
        heading_text = stream_text[m.start():m.end()].strip()
        matches.append((m.start(), m.end(), "cwd", None, cwd_name, heading_text))

    for m in _PORTION_HEADING_RE.finditer(stream_text):
        hd_num = int(m.group(1))
        heading_text = stream_text[m.start():m.end()].strip()
        matches.append((m.start(), m.end(), "portion", hd_num, None, heading_text))

    if not matches:
        # No headings at all — entire stream is continuation prose.
        return [
            HeadedBlock(
                kind="continuation",
                heading_text="",
                hd_number=None,
                cwd_name=None,
                body_raw=stream_text,
                page_num_1based=page_num_1based,
            )
        ]

    # Sort by start position; for ties (same start), prefer "hd" over "portion"
    # (more-specific pattern wins).  Ties between non-overlapping patterns
    # shouldn't occur in practice, but guard anyway.
    def _sort_key(rec: _MatchRecord) -> tuple[int, int]:
        start, _end, kind, *_ = rec
        # Lower rank = earlier in sort; "hd" wins ties over "portion".
        priority = 0 if kind == "hd" else (1 if kind == "cwd" else 2)
        return (start, priority)

    matches.sort(key=_sort_key)

    # Deduplicate: if two matches share the same start position, keep only the
    # first (highest-priority) one.
    deduped: list[_MatchRecord] = []
    seen_starts: set[int] = set()
    for rec in matches:
        start = rec[0]
        if start in seen_starts:
            continue
        seen_starts.add(start)
        deduped.append(rec)

    result: list[HeadedBlock] = []

    # Leading continuation block: prose before the first heading.
    first_start = deduped[0][0]
    leading_text = stream_text[:first_start]
    if leading_text.strip():
        result.append(
            HeadedBlock(
                kind="continuation",
                heading_text="",
                hd_number=None,
                cwd_name=None,
                body_raw=leading_text,
                page_num_1based=page_num_1based,
            )
        )

    # Emit one block per heading; body spans from this heading's end to the
    # next heading's start (or end of stream for the last heading).
    for i, (start, end, kind, hd_number, cwd_name, heading_text) in enumerate(deduped):
        if i + 1 < len(deduped):
            next_start = deduped[i + 1][0]
            body_raw = stream_text[end:next_start]
        else:
            body_raw = stream_text[end:]

        result.append(
            HeadedBlock(
                kind=kind,  # type: ignore[arg-type]
                heading_text=heading_text,
                hd_number=hd_number,
                cwd_name=cwd_name,
                body_raw=body_raw,
                page_num_1based=page_num_1based,
            )
        )

    return result


# ---------------------------------------------------------------------------
# V1 page walker (T5)
# ---------------------------------------------------------------------------


def _walk_v1_pages(
    pdf: Any,  # pdfplumber.PDF (or PdfDocument)
    pdf_filename: str,
    extracted_at: str,
) -> Iterator[tuple[HeadedBlock, str, PageReference]]:
    """Walk V1 species sections; yield headed blocks tagged with namespace + page_reference.

    For each V1 section page range, set species namespace; for each page in range,
    extract three columns, concatenate column streams in left-to-right order,
    split into headed blocks via _split_column_stream_into_blocks, and yield
    each block with its (namespace, page_reference) context.

    Continuation blocks are yielded as-is; T8 handles the cross-page merge.
    """
    for namespace, page_range in _V1_SECTIONS:
        # iter_pages accepts 1-based inclusive bounds; page_range is half-open
        # so stop - 1 gives the last inclusive 1-based page number.
        for page_num, page in iter_pages(pdf, page_range.start, page_range.stop - 1):
            col1, col2, col3 = _extract_three_column_text(page)
            stream_text = "\n".join([col1, col2, col3])
            page_reference: PageReference = {
                "pdf_filename": pdf_filename,
                "page_num_1based": page_num,
                "bbox": None,
                "extracted_at": extracted_at,
            }
            blocks = _split_column_stream_into_blocks(stream_text, page_num)
            for block in blocks:
                yield block, namespace, page_reference


# ---------------------------------------------------------------------------
# CWD multi-occurrence consolidation (T6)
# ---------------------------------------------------------------------------


def _consolidate_cwd_blocks(
    blocks: list[tuple[HeadedBlock, str, PageReference]],
) -> list[tuple[HeadedBlock, str, PageReference]]:
    """Merge duplicate CWD heading blocks (one per column) into a single block per zone.

    The three-column FWP Legal Descriptions PDF places the same CWD heading
    text once per column on a page where the zone's description spans all
    three columns (Libby CWD Management Zone on page 19 is the V1 case).
    This function walks the (block, namespace, page_reference) tuples
    returned by ``_walk_v1_pages`` and merges all blocks with the same
    ``cwd_name`` into one — keeping the FIRST occurrence's namespace and
    page_reference, and concatenating subsequent occurrences' ``body_raw``
    in their original order separated by " " (Cleanup Rule A's whitespace
    collapse will normalize it later in T8).

    Non-CWD blocks pass through unchanged.

    Idempotent: running twice yields the same result.

    Defensive merge for CWD multi-occurrence per S03.5 discovery 2026-05-12;
    harmless when stream is single-occurrence.
    """
    result: list[tuple[HeadedBlock, str, PageReference]] = []
    # Maps cwd_name → index in result list for the first occurrence.
    first_seen: dict[str, int] = {}

    for block, namespace, page_reference in blocks:
        if block.kind != "cwd":
            result.append((block, namespace, page_reference))
            continue

        cwd_name = block.cwd_name  # str | None; always str for kind=="cwd"
        assert cwd_name is not None, "HeadedBlock with kind='cwd' must have cwd_name set"

        if cwd_name not in first_seen:
            # First occurrence: record its position and append as canonical entry.
            first_seen[cwd_name] = len(result)
            result.append((block, namespace, page_reference))
        else:
            # Subsequent occurrence: concatenate body_raw onto the first occurrence.
            idx = first_seen[cwd_name]
            prior_block, prior_ns, prior_page_ref = result[idx]
            merged_body = prior_block.body_raw + " " + block.body_raw
            merged_block = replace(prior_block, body_raw=merged_body)
            result[idx] = (merged_block, prior_ns, prior_page_ref)

    return result


# ---------------------------------------------------------------------------
# Heading-to-geometry matcher (T7)
# ---------------------------------------------------------------------------


def _canonicalize_cwd_name(raw_name: str) -> str:
    """Normalize a possibly-truncated CWD heading capture to the canonical key.

    The T4 regex's optional ``(?:\\s+Zone)?`` group means a captured name
    may lack the "Zone" suffix when the PDF wraps that word to a continuation
    line. Two normalizations:
      1) Collapse all internal whitespace to single spaces (the regex's
         ``\\s+`` may capture a newline, producing ``"...Management\\nZone"``;
         without this collapse, ``endswith(" Zone")`` would miss).
      2) Append " Zone" if the suffix is absent.
    """
    normalized = re.sub(r"\s+", " ", raw_name).strip()
    if normalized.endswith(" Zone"):
        return normalized
    return f"{normalized} Zone"


def _match_block_to_geometry(
    block: HeadedBlock,
    namespace: str,
    hd_lookup: dict[tuple[str, int], str],
    cwd_lookup: dict[str, str],
) -> tuple[Literal["matched", "unmatched"], dict[str, Any]]:
    """Match a HeadedBlock to a geometry_id using species namespace + HD number,
    or surface as unmatched.

    Returns:
      ("matched", {"geometry_id": ..., "geometry_kind": ..., "extraction_confidence": ...})
      ("unmatched", {"reason": ...})

    Confidence per ADR-017:
      - Clean unambiguous match (HD or CWD) → ``high``.
      - The fuzzy multi-candidate branch is impossible by construction
        (namespace + HD number is unique per V1 species), but guarded for
        future-proofing.

    # ConfidenceTier.HIGH is a str-enum; passes directly through JSON
    # serialization as "high" without .value access.

    Block kinds handled:
      - ``"hd"``: look up ``hd_lookup[(namespace, block.hd_number)]``.
      - ``"cwd"``: look up via ``_canonicalize_cwd_name(block.cwd_name)``
        (Kalispell may lack "Zone" suffix per S03.5 discovery).
      - ``"portion"``: always unmatched (opaque ``Pt{N}`` slug not derivable).
      - ``"continuation"``: programming error — caller MUST merge continuations
        via T8's ``_apply_continuation_merges`` before invoking this.
        Raise ``PdfExtractionError`` (fail loud).
    """
    if block.kind == "continuation":
        raise PdfExtractionError(
            f"continuation block reached matcher unmerged at page "
            f"{block.page_num_1based} — programming error, expected T8 "
            f"_apply_continuation_merges to fold continuations first."
        )

    if block.kind == "hd":
        assert block.hd_number is not None, (
            "HeadedBlock with kind='hd' must have hd_number set"
        )
        key = (namespace, block.hd_number)
        if key in hd_lookup:
            return (
                "matched",
                {
                    "geometry_id": hd_lookup[key],
                    "geometry_kind": "hunting_district",
                    "extraction_confidence": ConfidenceTier.HIGH,
                },
            )
        return ("unmatched", {"reason": "no_matching_hd_in_geometry_table"})

    if block.kind == "cwd":
        assert block.cwd_name is not None, (
            "HeadedBlock with kind='cwd' must have cwd_name set"
        )
        canonical = _canonicalize_cwd_name(block.cwd_name)
        if canonical in cwd_lookup:
            return (
                "matched",
                {
                    "geometry_id": cwd_lookup[canonical],
                    "geometry_kind": "cwd_zone",
                    "extraction_confidence": ConfidenceTier.HIGH,
                },
            )
        return ("unmatched", {"reason": "unknown_cwd_zone"})

    # block.kind == "portion"
    return (
        "unmatched",
        {"reason": "portion_sub_heading_not_resolvable_to_opaque_slug"},
    )


# ---------------------------------------------------------------------------
# T8: Continuation merge, artifact builder, and deterministic JSON writer
# ---------------------------------------------------------------------------


def _apply_continuation_merges(
    blocks: list[tuple[HeadedBlock, str, PageReference]],
) -> list[tuple[HeadedBlock, str, PageReference]]:
    """Fold continuation blocks into the prior heading block's body.

    The page-walk in T5 emits a ``HeadedBlock(kind="continuation", ...)`` at
    the start of any page whose column stream begins with prose (no heading
    anchor before that prose). A continuation block represents prose that
    is the trailing text of the previous page's last heading block (cross-page
    body bleed).

    This function walks the block list; for each kind="continuation" block:
      - If there is a prior block AND its namespace matches the continuation's
        namespace: append the continuation's ``body_raw`` (separated by " ")
        to the prior block's ``body_raw``.
      - Otherwise (no prior block, OR namespace mismatch — i.e., this is the
        first page of a new species section, and the leading prose is either
        a section header or out-of-scope bleed from the prior section's last
        page): log a WARNING with a body-preview snippet and drop. ADR-001
        fail-loud discipline: surface the dropped content so operators can
        verify it is not regulation text. Cross-section continuation merge
        would silently corrupt the prior section's last block (a real
        ADR-008 violation — verbatim_description would carry foreign-section
        prose). Discovered by S03.5 silent-failure review 2026-05-12.

    Returns a list with all continuation blocks removed.
    """
    result: list[tuple[HeadedBlock, str, PageReference]] = []

    for block, namespace, page_reference in blocks:
        if block.kind == "continuation":
            if result and result[-1][1] == namespace:
                prev_block, prev_ns, prev_pref = result[-1]
                updated_body = prev_block.body_raw + " " + block.body_raw
                updated_prev_block = replace(prev_block, body_raw=updated_body)
                result[-1] = (updated_prev_block, prev_ns, prev_pref)
            else:
                prior_ns = result[-1][1] if result else None
                _logger.warning(
                    "Dropping cross-section / orphan continuation block at page %d "
                    "(this_ns=%s prior_ns=%s); body_preview=%r",
                    block.page_num_1based,
                    namespace,
                    prior_ns,
                    block.body_raw[:120],
                )
        else:
            result.append((block, namespace, page_reference))

    return result


def _build_artifact(
    merged_blocks: list[tuple[HeadedBlock, str, PageReference]],
    extracted_at: str,
    hd_lookup: dict[tuple[str, int], str],
    cwd_lookup: dict[str, str],
    all_v1_ids: list[tuple[str, str]],
) -> LegalDescriptionsArtifact:
    """Assemble the final extraction artifact from merged blocks.

    Walks merged_blocks (continuation-free); per block:
      - Apply Cleanup Rule A (whitespace collapse) to the body.
      - Call _match_block_to_geometry to classify as matched or unmatched.
      - On match: append to matched[] with geometry_id, geometry_kind,
        verbatim_description (collapsed body), page_reference, extraction_confidence.
      - On unmatched: append to unmatched[] with heading_text reconstructed
        from block fields, page_reference, reason.

    After all blocks processed: compute the set of matched geometry_ids, then
    iterate ``all_v1_ids`` and append every (gid, kind) NOT in matched to
    ``unlinked[]`` with reason="no_heading_in_pdf".

    Returns the LegalDescriptionsArtifact envelope. The matched/unmatched/
    unlinked arrays are SORTED for deterministic output:
      - matched: by (geometry_kind, geometry_id)
      - unmatched: by (page_num_1based, heading_text)
      - unlinked: by (geometry_kind, geometry_id)
    """
    matched: list[LegalDescriptionEntry] = []
    unmatched: list[UnmatchedEntry] = []

    for block, namespace, page_reference in merged_blocks:
        # Cleanup Rule A: collapse internal whitespace to single spaces.
        body_collapsed = re.sub(r"\s+", " ", block.body_raw).strip()

        status, payload = _match_block_to_geometry(block, namespace, hd_lookup, cwd_lookup)

        if status == "matched":
            matched.append(
                LegalDescriptionEntry(
                    geometry_id=payload["geometry_id"],
                    geometry_kind=payload["geometry_kind"],
                    verbatim_description=body_collapsed,
                    page_reference=page_reference,
                    extraction_confidence=payload["extraction_confidence"],
                )
            )
        else:
            # Reconstruct heading_text from the block's heading_text field.
            # For CWD, fall back to cwd_name if heading_text is empty (shouldn't happen).
            if block.kind == "cwd" and not block.heading_text:
                heading_text = block.cwd_name or "<unknown CWD>"
            else:
                heading_text = block.heading_text.strip() if block.heading_text else ""
            unmatched.append(
                UnmatchedEntry(
                    heading_text=heading_text,
                    page_reference=page_reference,
                    reason=payload["reason"],
                )
            )

    # Compute unlinked: all_v1_ids not represented in matched.
    matched_ids: set[str] = {entry["geometry_id"] for entry in matched}
    unlinked: list[UnlinkedEntry] = []
    for gid, kind in all_v1_ids:
        if gid not in matched_ids:
            unlinked.append(
                UnlinkedEntry(
                    geometry_id=gid,
                    geometry_kind=kind,
                    reason="no_heading_in_pdf",
                )
            )

    # Sort for deterministic output.
    matched.sort(key=lambda e: (e["geometry_kind"], e["geometry_id"]))
    unmatched.sort(key=lambda e: (e["page_reference"]["page_num_1based"], e["heading_text"]))
    unlinked.sort(key=lambda e: (e["geometry_kind"], e["geometry_id"]))

    artifact: LegalDescriptionsArtifact = {
        "source_id": _CITATION_ID,
        "extracted_at": extracted_at,
        "matched": matched,
        "unmatched": unmatched,
        "unlinked": unlinked,
    }
    return artifact


def _write_deterministic_json(path: Path, payload: LegalDescriptionsArtifact) -> None:
    """Atomic, deterministic JSON write.

    Writes JSON with sorted keys, indent=2, ensure_ascii=False, trailing
    newline. Writes to <path>.tmp then renames to <path> via Path.replace().
    Mirrors extract_dea.py's pattern (using parent / name + ".tmp" convention
    to avoid double-extension misinterpretation).
    """
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp_path = path.parent / (path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(body, encoding="utf-8")
    tmp_path.replace(path)


# ---------------------------------------------------------------------------
# Fail-loud threshold constant
# ---------------------------------------------------------------------------

# By-design unresolvable reason: portion sub-headings cannot be matched to
# geometry_ids because the opaque Pt{N} slugs are not derivable from PDF
# heading text. Explicitly excluded from the 10% regression threshold.
_PORTION_UNMATCHED_REASON = "portion_sub_heading_not_resolvable_to_opaque_slug"


# ---------------------------------------------------------------------------
# main (T9)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Extract Montana FWP Legal Descriptions PDF → JSON artifact.

    Single-writer contract: produces JSON only; no database writes.
    Fail-loud invariants: any missing input (citation, manifest, fixture)
    raises PdfExtractionError. Regression-unmatched rate > 10% raises
    PdfExtractionError. Successful run returns 0.
    """
    parser = argparse.ArgumentParser(
        description="Extract Montana FWP Legal Descriptions PDF to JSON artifact (S03.5)."
    )
    parser.add_argument("--pdf", type=Path, default=_PDF_PATH)
    parser.add_argument("--out", type=Path, default=_OUTPUT_PATH)
    args = parser.parse_args(argv)

    # Configure logging only if no handlers are already registered (avoids
    # double-init when this module is imported by tests or orchestrators).
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

    _logger.info("S03.5: extracting %s", args.pdf)

    # Load all inputs first — fail loud on any missing dependency before opening PDF.
    citation = _load_citation_from_sources_yaml(_CITATION_ID)
    extracted_at = _load_extracted_at_from_manifest(args.pdf)
    hd_lookup, cwd_lookup, all_v1_ids = _load_geometry_lookup(_GEOMETRY_FIXTURE_PATH)
    _logger.info(
        "Loaded citation %s; manifest extracted_at=%s; geometry lookup: %d HDs + %d CWDs (V1 scope)",
        _CITATION_ID,
        extracted_at,
        len(hd_lookup),
        len(cwd_lookup),
    )
    _ = citation  # citation is loaded for fail-loud invariant only;
    # T8's artifact envelope uses _CITATION_ID directly.

    with open_pdf(args.pdf) as pdf:
        raw_blocks = list(_walk_v1_pages(pdf, args.pdf.name, extracted_at))
    consolidated = _consolidate_cwd_blocks(raw_blocks)
    merged = _apply_continuation_merges(consolidated)

    artifact = _build_artifact(merged, extracted_at, hd_lookup, cwd_lookup, all_v1_ids)

    # Threshold scope decision (per spec § 483 and working note S03.5.md):
    # the 10% threshold counts regression-unmatched only (HD + CWD heading
    # parse failures). Portion sub-headings are by-design unresolvable per
    # the plan's "Out of V1 scope" list and are tallied separately.
    # spec § 483 explicitly invites threshold adjustment during implementation.
    regression_unmatched = [
        u for u in artifact["unmatched"] if u["reason"] != _PORTION_UNMATCHED_REASON
    ]
    portion_unmatched_count = len(artifact["unmatched"]) - len(regression_unmatched)

    matched_count = len(artifact["matched"])
    regression_unmatched_count = len(regression_unmatched)
    threshold_denominator = matched_count + regression_unmatched_count

    if threshold_denominator == 0:
        raise PdfExtractionError(
            "No V1 headings extracted — parser failure or empty PDF."
        )

    unmatched_rate = regression_unmatched_count / threshold_denominator

    _logger.info(
        "V1 extraction: matched=%d unmatched_regression=%d unmatched_portion=%d "
        "unlinked=%d threshold_rate=%.3f (excludes by-design portion sub-headings)",
        matched_count,
        regression_unmatched_count,
        portion_unmatched_count,
        len(artifact["unlinked"]),
        unmatched_rate,
    )

    if unmatched_rate > 0.10:
        raise PdfExtractionError(
            f"Regression-unmatched rate {unmatched_rate:.1%} exceeds 10% threshold "
            f"({regression_unmatched_count}/{threshold_denominator}). "
            f"Portion sub-heading unmatches are NOT counted toward the threshold "
            f"(they are by-design unresolvable). Investigate the {regression_unmatched_count} "
            f"non-portion unmatched entries for parser regression."
        )

    if regression_unmatched_count > 0:
        _logger.warning(
            "Regression-unmatched headings (below 10%% threshold): %d. See working note.",
            regression_unmatched_count,
        )
    if portion_unmatched_count > 0:
        _logger.info(
            "Portion sub-headings surfaced as unmatched (by-design, not counted toward threshold): %d.",
            portion_unmatched_count,
        )

    _write_deterministic_json(args.out, artifact)
    _logger.info(
        "Wrote %s (matched=%d, unmatched=%d, unlinked=%d)",
        args.out,
        matched_count,
        len(artifact["unmatched"]),
        len(artifact["unlinked"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
