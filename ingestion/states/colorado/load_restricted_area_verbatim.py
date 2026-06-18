"""Colorado restricted-area verbatim_rule population adapter (S06.5).

Populates ``geometry.verbatim_rule`` on the 10 S05.4 ``kind='restricted_area'`` rows
from CPW Big Game brochure page 78 ("Land Closures & Use Restrictions").

Decision D5=(b) split-provenance: only ``verbatim_rule`` is written; ``source``
stays the PAD-US citation from S05.4 — no schema change, no migration.

ADR lineage:
    ADR-001 — authority preserved, not replaced (fail-loud on missing anchors)
    ADR-005 — state isolation; no lib/ edits; shared code via ingestion.lib only
    ADR-008 — verbatim regulation text; byte-equivalent pdfplumber output,
              no normalization, no rewording
    ADR-022 — single-module per-state PDF extractors

Run from the repo root (direct path, NOT python -m — see known-pitfalls.md
"state-adapter scripts must be invoked as python <path> not python -m"):
    ingestion/.venv/bin/python ingestion/states/colorado/load_restricted_area_verbatim.py
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Final

from ingestion.lib import db, pdf
from states.colorado.load_restricted_areas import _V1_EXPECTED_IDS

# ---------------------------------------------------------------------------
# Path constants
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

# Print page 78, "Land Closures & Use Restrictions"
_BROCHURE_PAGE_INDEX: Final[int] = 77

# ---------------------------------------------------------------------------
# Column bbox constants
# ---------------------------------------------------------------------------

# Page 78 is a dense 3-column layout.  Full-page extract_text scrambles
# columns; crop each span to its own column band spanning the FULL page
# height (top=0.0 / bottom=page.height) — a partial top cut scrambles the
# AFA first line.
#
# Empirically-tuned column gutters for the 3-column page-78 layout:
_NPS_LEFT_X: Final[float] = 392.0  # right-column left edge
_AFA_RIGHT_X: Final[float] = 200.0  # left-column right edge

# ---------------------------------------------------------------------------
# Anchor regexes
# ---------------------------------------------------------------------------

_NPS_ANCHOR_RE = re.compile(
    r"National parks and monuments.*?for more information\.", re.DOTALL
)

_AFA_ANCHOR_RE = re.compile(
    r"AFA hunters must pay.*?for more details\.", re.DOTALL
)

# ---------------------------------------------------------------------------
# Geometry-id constants
# ---------------------------------------------------------------------------

_AFA_GEOM_ID: Final[str] = "CO-restricted-united-states-air-force-academy-geom"

# Fail loud at import if the AFA id ever drifts from the S05.4 set: otherwise
# the subtraction below would yield a 10-element "NPS" set and the AFA row
# would silently receive the NPS closure text (a 10-NPS + 0-AFA split).
assert _AFA_GEOM_ID in _V1_EXPECTED_IDS, (
    f"_AFA_GEOM_ID {_AFA_GEOM_ID!r} not in load_restricted_areas._V1_EXPECTED_IDS"
    " — the AFA slug drifted; update _AFA_GEOM_ID"
)

# The 9 NPS rows (4 National Parks + 5 National Monuments)
_NPS_GEOM_IDS: Final[frozenset[str]] = _V1_EXPECTED_IDS - {_AFA_GEOM_ID}

assert len(_NPS_GEOM_IDS) == 9, "_NPS_GEOM_IDS must be exactly 9 zones (V1 set minus AFA)"

# ---------------------------------------------------------------------------
# Pure parser functions (testable WITHOUT the PDF)
# ---------------------------------------------------------------------------


def parse_nps_closure_text(right_column_text: str) -> str:
    """Return the NPS closure sentence verbatim from the right-column crop.

    The returned string is a verbatim substring of ``pdf.extract_text`` output
    (ADR-008 — no rewording, no normalization).

    Raises:
        RuntimeError: if the NPS closure anchor is not found, which means the
            brochure layout changed and the extraction must be reviewed.
    """
    m = _NPS_ANCHOR_RE.search(right_column_text)
    if m is None:
        raise RuntimeError(
            "S06.5: NPS closure anchor (Statewide Restrictions item 5) not found"
            " in page-78 right column; brochure layout changed — flag-and-discuss,"
            " do not hand-edit"
        )
    return m.group(0)


def parse_afa_access_text(left_column_text: str) -> str:
    """Return the AFA access-rules prose verbatim from the left-column crop.

    The returned string is a verbatim substring of ``pdf.extract_text`` output
    (ADR-008 — no rewording, no normalization).

    Raises:
        RuntimeError: if the AFA anchor is not found, which means the
            brochure layout changed and the extraction must be reviewed.
    """
    m = _AFA_ANCHOR_RE.search(left_column_text)
    if m is None:
        raise RuntimeError(
            "S06.5: AFA access-rules anchor ('AFA hunters must pay') not found"
            " in page-78 left column; brochure layout changed — flag-and-discuss,"
            " do not hand-edit"
        )
    return m.group(0)


# ---------------------------------------------------------------------------
# PDF-reading function
# ---------------------------------------------------------------------------


def read_brochure_spans(pdf_path: Path = _PDF_PATH) -> tuple[str, str]:
    """Open the CPW Big Game brochure and extract the two page-78 verbatim spans.

    Returns:
        ``(nps_text, afa_text)`` — both are byte-equivalent pdfplumber substrings
        per ADR-008.  ``nps_text`` is the shared closure sentence for all 9 NPS
        rows; ``afa_text`` is the AFA-specific access-rules prose.

    Raises:
        pdf.PdfExtractionError: if the (gitignored) PDF is absent or cannot be
            opened by pdfplumber.
        RuntimeError: if either anchor regex fails to match (layout change).
    """
    with pdf.open_pdf(pdf_path) as doc:
        if len(doc.pages) <= _BROCHURE_PAGE_INDEX:
            raise pdf.PdfExtractionError(
                f"brochure has {len(doc.pages)} pages; _BROCHURE_PAGE_INDEX="
                f"{_BROCHURE_PAGE_INDEX} (print page 78) is out of range — wrong PDF?"
            )
        page = doc.pages[_BROCHURE_PAGE_INDEX]
        right = pdf.extract_text(page, bbox=(_NPS_LEFT_X, 0.0, page.width, page.height))
        left = pdf.extract_text(page, bbox=(0.0, 0.0, _AFA_RIGHT_X, page.height))
    # Distinguish an empty column crop (bad bbox / column gutter shifted between
    # brochure editions) from a genuine layout change, so the operator inspects
    # the right cause. Both fail loud — never write empty/missing text.
    if not right.strip():
        raise RuntimeError(
            "S06.5: page-78 right-column crop returned empty text — check _NPS_LEFT_X"
            f" ({_NPS_LEFT_X}); column gutter may have shifted"
        )
    if not left.strip():
        raise RuntimeError(
            "S06.5: page-78 left-column crop returned empty text — check _AFA_RIGHT_X"
            f" ({_AFA_RIGHT_X}); column gutter may have shifted"
        )
    return (parse_nps_closure_text(right), parse_afa_access_text(left))


# ---------------------------------------------------------------------------
# Build phase
# ---------------------------------------------------------------------------


def build_verbatim_map(nps_text: str, afa_text: str) -> dict[str, str]:
    """Build the geometry-id → verbatim_rule mapping for all 10 restricted-area rows.

    9+1 split: the 9 NPS rows (4 National Parks + 5 National Monuments) share
    one closure sentence; the AFA gets its own access-rules prose.

    Args:
        nps_text: The shared NPS closure sentence extracted from page 78.
        afa_text: The AFA-specific access-rules prose extracted from page 78.

    Returns:
        A dict keyed by geometry id with exactly 10 entries (``_V1_EXPECTED_IDS``).
    """
    result: dict[str, str] = {gid: nps_text for gid in _NPS_GEOM_IDS}
    result[_AFA_GEOM_ID] = afa_text
    return result


# ---------------------------------------------------------------------------
# Pre-connect guards (OQ7 discipline — fire before db.connect())
# ---------------------------------------------------------------------------


def _check_map(verbatim_map: dict[str, str]) -> None:
    """Validate the verbatim map before any DB connection is opened.

    Raises RuntimeError on any of the following conditions:
    - The key set does not exactly equal ``_V1_EXPECTED_IDS``.
    - Any value's ``.strip()`` is empty (never write empty string).
    - The 9 NPS rows do not all share exactly one closure sentence (phrasing case 1).
    - The AFA value equals the shared NPS sentence (9+1 split must hold).
    """
    actual_ids = set(verbatim_map)
    if actual_ids != _V1_EXPECTED_IDS:
        missing = sorted(_V1_EXPECTED_IDS - actual_ids)
        unexpected = sorted(actual_ids - _V1_EXPECTED_IDS)
        raise RuntimeError(
            f"S06.5: verbatim map ids do not match the V1 expected set; "
            f"missing={missing}, unexpected={unexpected}"
        )
    for geom_id, text in verbatim_map.items():
        if not text.strip():
            raise RuntimeError(
                f"S06.5: verbatim_rule for geometry id={geom_id!r} is empty or"
                " whitespace-only; never write an empty verbatim_rule"
            )
    nps_values = {verbatim_map[g] for g in _NPS_GEOM_IDS}
    if len(nps_values) != 1:
        raise RuntimeError(
            "S06.5: the 9 NPS rows must share exactly one closure sentence (phrasing case 1)"
        )
    if verbatim_map[_AFA_GEOM_ID] in nps_values:
        raise RuntimeError(
            "S06.5: AFA verbatim_rule must differ from the NPS closure sentence"
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Extract page-78 verbatim spans and write them to geometry.verbatim_rule."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="extract + validate, skip the DB write",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Phase 1 — build (no DB)
    nps_text, afa_text = read_brochure_spans()
    verbatim_map = build_verbatim_map(nps_text, afa_text)

    # Phase 2 — pre-connect guards
    _check_map(verbatim_map)
    logger.info(
        "S06.5 verbatim map built: 9 NPS rows + 1 AFA row; NPS=%d chars, AFA=%d chars",
        len(nps_text),
        len(afa_text),
    )

    if args.dry_run:
        logger.info("--dry-run: skipping DB write")
        return 0

    # Phase 3 — DB write
    with db.connect() as conn:
        for geom_id in sorted(verbatim_map):
            db.update_geometry_verbatim(conn, geom_id, verbatim_map[geom_id])
        conn.commit()

    logger.info(
        "updated verbatim_rule on %d restricted-area geometries",
        len(verbatim_map),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
