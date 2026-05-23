"""Montana regulation_record ingestion adapter.

Reads three extraction artifacts produced by S03.3-S03.5 and writes:
1. ``regulation_record`` rows to Postgres (V1 Montana × elk/mule_deer/whitetail/
   pronghorn/bear × license_year=2026 — approximately 436 rows).
2. ``geometry.legal_description`` updates for the 228 matched legal-description
   entries from S03.5.

OQ1 resolution note (2026-05-14)
--------------------------------
Section-level ``verbatim_text`` from the DEA artifact is NOT written to the DB.
The ``regulation_record`` table has no ``verbatim_rule`` column by design — section
text decomposes into S03.7's ``season_definition.verbatim_rule`` and
``license_tag.verbatim_rule``. This loader writes only the row anchor (source +
confidence + schema_version) plus ``additional_rules`` populated from NOTE-style
lines in the DEA section's ``verbatim_text``. See ``docs/open-questions.md`` for
the full rationale and ``docs/planning/epics/E03-confidence-findings/S03.6.md``
for the working note.

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/load_regulation_records.py

Required env: ``DATABASE_URL``.

Optional flag: ``--dry-run`` — build all records and run the count guard,
but do not write to the DB. Useful for CI smoke-testing the loader logic
without requiring DB connectivity.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import cast

import yaml

from ingestion.lib import db, pdf
from ingestion.lib.pdf import ConfidenceTier
from ingestion.lib.schema import (
    Confidence,
    JurisdictionBinding,
    RegulationRecord,
    SourceCitation,
    VerbatimRule,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_MONTANA_DIR = Path(__file__).resolve().parent
_EXTRACTED_DIR = _MONTANA_DIR / "extracted"
_DEA_ARTIFACT = _EXTRACTED_DIR / "dea-2026.json"
_BEAR_ARTIFACT = _EXTRACTED_DIR / "black-bear-2026.json"
_LEGAL_DESC_ARTIFACT = _EXTRACTED_DIR / "legal-descriptions-2026.json"
_SOURCES_YAML = _MONTANA_DIR / "sources.yaml"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MT_STATE_CODE = "US-MT"
_LICENSE_YEAR = 2026
_SCHEMA_VERSION = 2

# Per-record-count fail-loud guard (OQ7 resolution). Acceptable range is
# 70%-130% of the actual baseline of 437 (= 436 baseline from S03.6 close +
# 1 MT-STATEWIDE-bear anchor added by S03.6.1) — written count outside
# the band indicates a catastrophic regression in one of the extraction
# artifacts. Concrete bounds after int() truncation: [305, 568].
_SPEC_ESTIMATE_TOTAL = 437
_COUNT_GUARD_MIN_RATIO = 0.70
_COUNT_GUARD_MAX_RATIO = 1.30

# Legal-description count guard. The S03.5 final matched count is 228 (per
# the working note). Same ±30% band shape as the regulation_record guard.
# Concrete bounds after int() truncation: [159, 296].
_LEGAL_DESC_EXPECTED_TOTAL = 228

# jurisdiction_binding count guard. S03.6.1 writes exactly one binding row
# (MT-STATEWIDE-bear → MT-STATEWIDE-geom). S03.10 will broaden this band
# when it ships its overlay-derived binding generation. Per spec line 908:
# exact-match [1, 1] for the single-row write expected from S03.6.1 alone.
_JURISDICTION_BINDING_EXPECTED_TOTAL = 1
_JURISDICTION_BINDING_GUARD_MIN = 1
_JURISDICTION_BINDING_GUARD_MAX = 1

_DEA_CITATION_ID = "mt-fwp-dea-2026-booklet"
_LEGAL_DESC_CITATION_ID = "mt-fwp-legal-descriptions-2026-2027"

# S03.6.1 statewide bear anchor constants.
_BEAR_BOOKLET_CITATION_ID = "mt-fwp-black-bear-2026-booklet"

# Geometry id for the MT-STATEWIDE row created by S03.0 (ADR-018 §3).
_MT_STATEWIDE_GEOM_ID = "MT-STATEWIDE-geom"

# Binding id format for jurisdiction_binding rows produced by this adapter
# and by S03.10 (which must use the same format so that S03.10 UPSERTs are
# no-ops for bindings already written here).
#
# Encoded: PK-equivalent fields (state, jurisdiction_code, species_group,
# license_year) + role + geometry_id.  Fields that may update freely without
# a PK change (verbatim_rule, source) are intentionally NOT encoded — a slug
# that embeds a mutable field would silently create a new row on every
# re-ingestion run instead of updating in place (Q19 risk).
#
# S03.10 carry-over note: use this exact format string when deriving binding
# ids for the overlay-fan-out bindings so that the statewide bear binding
# written by S03.6.1 is a stable UPSERT no-op when S03.10 re-derives it.
_JURISDICTION_BINDING_ID_FORMAT = (
    "{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"
)


# ---------------------------------------------------------------------------
# Citation loader
# ---------------------------------------------------------------------------


def _load_citation_from_sources_yaml(citation_id: str) -> SourceCitation:
    """Load a single SourceCitation entry from sources.yaml by id.

    Returns a fully-constructed ``schema.SourceCitation`` Pydantic instance
    (frozen). Pydantic validates every field, including the
    ``document_type`` Literal and the ``publication_date`` string.

    Raises:
        RuntimeError: if ``citation_id`` is not found in sources.yaml.

    This loader is intentionally duplicated across state adapters
    (``extract_black_bear.py``, ``extract_legal_descriptions.py``, this file).
    Per the Literal-duplication convention in ``.roughly/known-pitfalls.md``,
    each adapter owns its own source-citation deserialization to keep
    adapter modules self-contained.
    """
    with _SOURCES_YAML.open() as f:
        data = yaml.safe_load(f)

    for entry in data.get("pdfs", []):
        if entry.get("id") != citation_id:
            continue
        return SourceCitation(
            id=entry["id"],
            agency=entry["agency"],
            title=entry["title"],
            url=entry["url"],
            publication_date=entry["publication_date"],
            document_type=entry["document_type"],
            supersedes=entry.get("supersedes"),
            page_reference=None,
        )

    raise RuntimeError(
        f"sources.yaml has no entry with id={citation_id!r}"
    )


# ---------------------------------------------------------------------------
# NOTE-line capture (HD-wide additional rules from DEA verbatim_text)
# ---------------------------------------------------------------------------

# Matches a NOTE: prefixed line and any continuation lines that follow,
# up to (but not including) the next NOTE: line or an ALL-CAPS-LIKE line
# (e.g. table column headers like "ARCHERY APPLY EARLY ...") or end of
# string. Operates on the raw verbatim_text — line-anchored multiline.
#
# Continuation rule: pdfplumber's word grouping breaks the NOTE prose
# across physical lines; we capture the whole logical NOTE then collapse
# inter-line whitespace at the call site (extras-only whitespace collapse,
# per S03.3's cleanup convention — ADR-008-safe because the content is
# identical, only run-length-encoded whitespace is normalized).
# Note: the prefix-consume class is ``[ \t]*`` (horizontal whitespace only).
# Using greedy ``\s*`` would eat newlines and absorb a downstream NOTE: line
# into the current match when sections have whitespace-only spacer lines
# between NOTEs — no such pattern exists in the V1 DEA corpus but it is a
# latent paraphrase risk we guard against by restricting the consume class.
_NOTE_LINE_RE = re.compile(
    r"^NOTE:[ \t]*(?P<body>.*?)(?=\n^NOTE:|\n^[A-Z]{3,}|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _extract_note_lines(
    verbatim_text: str,
    citation: SourceCitation,
    confidence: Confidence,
) -> list[VerbatimRule]:
    """Parse ``NOTE:`` prefixed lines out of a DEA section's verbatim_text.

    Each match becomes one VerbatimRule with text formatted as
    ``"NOTE: <collapsed-body>"`` so the literal source prefix is preserved
    for downstream readers of ``regulation_record.additional_rules``.

    Whitespace collapse: each captured body has internal whitespace runs
    (including newlines from pdfplumber's line-breaking) normalized to
    single spaces — this matches the extras-only collapse rule documented
    in extract_dea.py's "Cleanup rules" section. ADR-008-safe.

    Empty bodies (defensive — should not occur on real data) are skipped
    so we never emit an empty NOTE rule (which would also be rejected by
    VerbatimRule's non-empty-text validator).

    Returns the list of VerbatimRule entries in source order. Empty list
    if no NOTE lines were found.
    """
    rules: list[VerbatimRule] = []
    for match in _NOTE_LINE_RE.finditer(verbatim_text):
        body = match.group("body").strip()
        body = re.sub(r"\s+", " ", body)
        if not body:
            continue
        rules.append(VerbatimRule(
            text=f"NOTE: {body}",
            page_reference=citation.page_reference,
            confidence=confidence,
            source=citation,
        ))
    return rules


# ---------------------------------------------------------------------------
# DEA section → regulation_record fan-out
# ---------------------------------------------------------------------------

# Maps DEA artifact's species_group label to the DB-side species_group value(s).
# The DEA artifact uses "deer" / "elk" / "antelope" (the species columns in the
# FWP regulation booklet); the DB schema uses "mule_deer" / "whitetail" / "elk"
# / "pronghorn" (the granular species). One DEA "deer" section fans out to
# TWO regulation_record rows — mule_deer and whitetail share the same per-HD
# verbatim text and source. "elk" stays as elk; "antelope" renames to pronghorn.
_DEA_SPECIES_FANOUT: dict[str, tuple[str, ...]] = {
    "deer":     ("mule_deer", "whitetail"),
    "elk":      ("elk",),
    "antelope": ("pronghorn",),
}


def _dea_jurisdiction_code(species_group: str, hd_number: str) -> str:
    """Derive the regulation_record.jurisdiction_code for a DEA-sourced row.

    Mapping (matches the existing geometry id patterns from E02):
    - mule_deer / whitetail / elk → ``MT-HD-deer-elk-lion-{hd_number}``
      (matches geometry id ``MT-HD-deer-elk-lion-{hd_number}-geom``)
    - pronghorn + ``hd_number == "STATEWIDE"`` → ``MT-STATEWIDE-antelope``
      (the ADR-018 statewide anchor for the DEA's ``900-20`` row)
    - pronghorn + numeric hd_number → ``MT-HD-antelope-{hd_number}``

    Any other (species_group, hd_number) combination is a structural fail-loud:
    the DEA fan-out should not produce unknown species values, and an unknown
    statewide jurisdiction would mean an undeclared statewide candidate.
    """
    if species_group in ("mule_deer", "whitetail", "elk"):
        if hd_number == "STATEWIDE":
            # Only pronghorn has a sanctioned MT-STATEWIDE anchor in V1
            # (per ADR-018 §3 — antelope's `900-20` row).  An mule_deer /
            # whitetail / elk STATEWIDE row would be an undeclared statewide
            # candidate that the loader MUST NOT autonomously add — flag and
            # surface for PM review per the same ADR-018 §3 contract.
            raise ValueError(
                f"DEA section {species_group!r} with hd_number='STATEWIDE' "
                f"would map to MT-HD-deer-elk-lion-STATEWIDE, but only "
                f"pronghorn has a sanctioned statewide anchor in V1. "
                f"Surface this in docs/planning/epics/E03-confidence-findings/"
                f"S03.6.md for PM review before adding the row autonomously."
            )
        return f"MT-HD-deer-elk-lion-{hd_number}"
    if species_group == "pronghorn":
        if hd_number == "STATEWIDE":
            return "MT-STATEWIDE-antelope"
        return f"MT-HD-antelope-{hd_number}"
    raise ValueError(
        f"unhandled (species_group, hd_number) combination: "
        f"({species_group!r}, {hd_number!r})"
    )


def _build_dea_records(
    dea_artifact: list[dict],
    dea_citation: SourceCitation,
) -> list[RegulationRecord]:
    """Convert DEA extraction sections into a list of RegulationRecord rows.

    For each section in ``dea_artifact``:
      * Look up the target species (or species pair) via _DEA_SPECIES_FANOUT.
      * Compute confidence as the MIN over per-row extraction_confidence values
        using pdf.ConfidenceTier.min_tier (NOT bare min() over raw strings —
        that returns "high" lexicographically for ["high","low"]; see S03.2's
        trap-case lock).
      * Bind the page_reference into a section-scoped SourceCitation via
        model_copy (SourceCitation is frozen).
      * Populate ``additional_rules`` from NOTE-prefixed lines in the section's
        verbatim_text via ``_extract_note_lines`` (T5).

    Returns records in deterministic artifact order, with deer sections
    producing mule_deer-then-whitetail pairs.
    """
    records: list[RegulationRecord] = []
    for section in dea_artifact:
        target_species = _DEA_SPECIES_FANOUT[section["species_group"]]
        row_tiers = [
            ConfidenceTier(row["extraction_confidence"])
            for row in section["rows"]
        ]
        confidence: Confidence = cast(Confidence, pdf.min_tier(row_tiers))
        page_ref_str = pdf.page_reference_to_str(section["page_reference"])
        section_citation = dea_citation.model_copy(
            update={"page_reference": page_ref_str},
        )
        for target_species_group in target_species:
            records.append(RegulationRecord(
                state=_MT_STATE_CODE,
                jurisdiction_code=_dea_jurisdiction_code(
                    target_species_group, section["hd_number"],
                ),
                species_group=target_species_group,
                license_year=_LICENSE_YEAR,
                schema_version=_SCHEMA_VERSION,
                source=section_citation,
                confidence=confidence,
                additional_rules=_extract_note_lines(
                    section["verbatim_text"], section_citation, confidence,
                ),
            ))
    return records


# ---------------------------------------------------------------------------
# Bear row → regulation_record (with per-row citation lookup)
# ---------------------------------------------------------------------------


def _build_bear_records(bear_artifact: dict) -> list[RegulationRecord]:
    """Convert the merged Black Bear artifact's rows into RegulationRecord rows.

    Per-row citation lookup: each row's ``source_id`` references one of the
    citations in the artifact's top-level ``sources`` list. Correction-touched
    rows carry ``supersedes`` populated (the booklet citation id); non-touched
    rows have ``supersedes=None``. V1 has all 35 rows correction-touched, but
    the loader supports both cases defensively (a future M2 correction may
    only touch a subset).

    Confidence passes through directly from ``row["extraction_confidence"]``
    — S03.4 already demoted correction-touched rows from HIGH to MEDIUM
    per ADR-017 §4. No re-demote here (per epic line 578).

    Returns 35 records in bmu_number order (artifact already sorted; this
    function preserves source order).
    """
    raw_sources = bear_artifact.get("sources")
    if not isinstance(raw_sources, list):
        raise RuntimeError(
            f"bear artifact missing or invalid 'sources' key "
            f"(expected list, got {type(raw_sources).__name__}); "
            f"re-run extract_black_bear.py and inspect the artifact"
        )
    raw_rows = bear_artifact.get("rows")
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            f"bear artifact missing or invalid 'rows' key "
            f"(expected list, got {type(raw_rows).__name__}); "
            f"re-run extract_black_bear.py and inspect the artifact"
        )
    sources_by_id: dict[str, dict] = {s["id"]: s for s in raw_sources}
    if len(sources_by_id) != len(raw_sources):
        seen: set[str] = set()
        duplicates: list[str] = []
        for s in raw_sources:
            if s["id"] in seen:
                duplicates.append(s["id"])
            seen.add(s["id"])
        raise RuntimeError(
            f"bear artifact 'sources' has duplicate ids: {sorted(set(duplicates))!r} — "
            "indicates artifact regeneration produced collision; investigate before re-running"
        )
    records: list[RegulationRecord] = []
    for row in raw_rows:
        source_id = row["source_id"]
        if source_id not in sources_by_id:
            raise RuntimeError(
                f"bear artifact row references unknown source_id={source_id!r}; "
                f"artifact sources are {sorted(sources_by_id.keys())!r}"
            )
        source_dict = sources_by_id[source_id]
        page_ref_str = pdf.page_reference_to_str(row["page_reference"])
        row_citation = SourceCitation(
            id=source_dict["id"],
            agency=source_dict["agency"],
            title=source_dict["title"],
            url=source_dict["url"],
            publication_date=source_dict["publication_date"],
            document_type=source_dict["document_type"],
            supersedes=row["supersedes"],
            page_reference=page_ref_str,
        )
        # Coerce via ConfidenceTier(...) so an invalid string raises ValueError
        # at the row where it appears (naming the bad value), rather than
        # propagating to Pydantic's Literal-validation error which doesn't
        # tell the operator WHICH row had the bad value.  Mirrors the DEA path.
        confidence: Confidence = cast(
            Confidence, ConfidenceTier(row["extraction_confidence"]),
        )
        records.append(RegulationRecord(
            state=_MT_STATE_CODE,
            jurisdiction_code=f"MT-HD-bear-{row['bmu_number']}",
            species_group="bear",  # DB value; the artifact's top-level field is "black_bear" — do not confuse them
            license_year=_LICENSE_YEAR,
            schema_version=_SCHEMA_VERSION,
            source=row_citation,
            confidence=confidence,
            additional_rules=_extract_note_lines(
                row["verbatim_text"], row_citation, confidence,
            ),
        ))
    return records


# ---------------------------------------------------------------------------
# S03.6.1 — MT-STATEWIDE-bear anchor + jurisdiction_binding builder
# ---------------------------------------------------------------------------


def _build_statewide_bear_record(
    bear_artifact: dict,
    bear_citation: SourceCitation,
) -> RegulationRecord:
    """Build the MT-STATEWIDE-bear regulation_record anchor from the bear artifact.

    Reads ``bear_artifact["statewide_rules"]`` — a list expected to contain
    exactly one ``StatewideRuleCandidate`` entry (the Bear ID Test requirement
    from page 2 of the Black Bear booklet).

    Fail-loud cases:
    - Missing ``statewide_rules`` key → RuntimeError (regenerate extraction).
    - Empty list → RuntimeError (extraction regression; investigate).
    - More than 1 entry → RuntimeError (V1 contract; M2 may relax).

    The single ``StatewideRuleCandidate``'s ``verbatim_text`` is written to
    ``additional_rules`` as a raw ``VerbatimRule`` — no NOTE: or REQUIREMENT:
    prefix is added; the adapter preserves the source text verbatim per ADR-008.

    ``confidence="medium"`` matches the bear per-BMU rows: all rows were
    demoted HIGH→MEDIUM by S03.4's correction-touched single-demote-one-tier
    pass; the statewide anchor carries the same calibration.
    """
    raw_statewide = bear_artifact.get("statewide_rules")
    if raw_statewide is None:
        raise RuntimeError(
            "bear artifact missing 'statewide_rules' field — "
            "regenerate via extract_black_bear.py"
        )
    if not isinstance(raw_statewide, list):
        raise RuntimeError(
            f"bear artifact 'statewide_rules' is not a list (got {type(raw_statewide).__name__!r}) — "
            "artifact schema corruption; regenerate via extract_black_bear.py"
        )
    if len(raw_statewide) == 0:
        raise RuntimeError(
            "bear artifact 'statewide_rules' is empty — "
            "extraction regression; investigate before re-running"
        )
    n = len(raw_statewide)
    if n > 1:
        raise RuntimeError(
            f"bear artifact 'statewide_rules' has {n} entries (expected 1) — "
            "V1 contract; M2 may relax"
        )
    statewide_rule = raw_statewide[0]

    # Provenance check: the artifact's source_id + source_publication_date
    # MUST match the bear_citation loaded from sources.yaml. A mismatch means
    # the extractor emitted a different source for this rule than the loader
    # is about to attribute it to — silent provenance corruption. V1 contract:
    # the single statewide rule is the Bear ID Test from the bear booklet.
    rule_source_id = statewide_rule["source_id"]
    if rule_source_id != bear_citation.id:
        raise RuntimeError(
            f"statewide_rules[0] source_id={rule_source_id!r} does not match "
            f"bear_citation.id={bear_citation.id!r} — provenance mismatch; "
            "extractor and loader disagree on the source of the rule"
        )
    rule_publication_date = statewide_rule["source_publication_date"]
    if rule_publication_date != bear_citation.publication_date:
        raise RuntimeError(
            f"statewide_rules[0] source_publication_date={rule_publication_date!r} "
            f"does not match bear_citation.publication_date="
            f"{bear_citation.publication_date!r} — provenance mismatch; "
            "extractor and loader disagree on the source publication date"
        )

    page_ref_str = pdf.page_reference_to_str(statewide_rule["page_reference"])
    bear_citation_at_page = bear_citation.model_copy(
        update={"page_reference": page_ref_str},
    )
    verbatim_rule_obj = VerbatimRule(
        text=statewide_rule["verbatim_text"],
        page_reference=page_ref_str,
        confidence=cast(Confidence, ConfidenceTier(statewide_rule["extraction_confidence"])),
        source=bear_citation_at_page,
    )
    return RegulationRecord(
        state=_MT_STATE_CODE,
        license_year=_LICENSE_YEAR,
        jurisdiction_code="MT-STATEWIDE-bear",
        species_group="bear",
        schema_version=_SCHEMA_VERSION,
        additional_rules=[verbatim_rule_obj],
        source=bear_citation_at_page,
        confidence="medium",
    )


def _build_statewide_bear_binding(record: RegulationRecord) -> JurisdictionBinding:
    """Build the jurisdiction_binding linking MT-STATEWIDE-bear to MT-STATEWIDE-geom.

    The binding id is derived via ``_JURISDICTION_BINDING_ID_FORMAT`` — the
    same format S03.10 must use when re-deriving bindings in its overlay
    fan-out, so this row is a stable UPSERT no-op when S03.10 runs.
    """
    binding_id = _JURISDICTION_BINDING_ID_FORMAT.format(
        state=record.state,
        jurisdiction_code=record.jurisdiction_code,
        species_group=record.species_group,
        license_year=record.license_year,
        role="primary_unit",
        geometry_id=_MT_STATEWIDE_GEOM_ID,
    )
    return JurisdictionBinding(
        id=binding_id,
        regulation_record_state=record.state,
        regulation_record_jurisdiction_code=record.jurisdiction_code,
        regulation_record_species_group=record.species_group,
        regulation_record_license_year=record.license_year,
        geometry_id=_MT_STATEWIDE_GEOM_ID,
        role="primary_unit",
        verbatim_rule=None,
        source=record.source,
    )


# ---------------------------------------------------------------------------
# Legal description writes (from S03.5's legal-descriptions-2026.json)
# ---------------------------------------------------------------------------


def _legal_description_writes(
    legal_desc_artifact: dict,
) -> list[tuple[str, str | None]]:
    """Map S03.5's `matched` entries to (geometry_id, text|None) tuples.

    The text is stripped and whitespace-only-or-empty values are coerced to
    None so the loader writes SQL NULL rather than the empty string (per
    review N4: ``geometry.legal_description`` has no DB-side empty-string
    guard; we enforce it at the call site).

    `unmatched` and `unlinked` entries are skipped — they are by-design
    not-written-to-DB per S03.5's contract.

    Returns a list of (geometry_id, text|None) tuples in source order. The
    caller loops and calls ``db.update_legal_description`` for each tuple.
    """
    writes: list[tuple[str, str | None]] = []
    for entry in legal_desc_artifact["matched"]:
        raw = entry.get("verbatim_description")
        text: str | None = raw.strip() if isinstance(raw, str) else None
        if not text:
            text = None
        writes.append((entry["geometry_id"], text))
    return writes


# ---------------------------------------------------------------------------
# Row-count fail-loud guard (OQ7)
# ---------------------------------------------------------------------------


def _assert_legal_desc_count_within_guard(written: int) -> None:
    """Fail loud if the legal_description write count is outside the 70%-130%
    band of the S03.5 baseline (228). Concrete bounds after int() truncation:
    [159, 296]. Below or above indicates the legal-descriptions extraction
    regressed — investigate before any DB writes (the guard fires before
    db.connect() is called).
    """
    lower = int(_LEGAL_DESC_EXPECTED_TOTAL * _COUNT_GUARD_MIN_RATIO)
    upper = int(_LEGAL_DESC_EXPECTED_TOTAL * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"legal_description count guard failed: queued {written} updates; "
            f"expected approximately {_LEGAL_DESC_EXPECTED_TOTAL} (acceptable "
            f"range {lower}-{upper}, ±30% of S03.5 baseline). This indicates a "
            f"regression in extract_legal_descriptions.py. Investigate before "
            f"re-running."
        )


def _assert_count_within_guard(written: int) -> None:
    """Fail loud if the regulation_record write count is outside the 70%-130%
    band of the actual baseline (437 = 436 from S03.6 + 1 MT-STATEWIDE-bear
    from S03.6.1). Concrete bounds after int() truncation: [305, 568]. Below
    or above indicates a catastrophic regression in one of the extraction
    artifacts — investigate before re-running.
    """
    lower = int(_SPEC_ESTIMATE_TOTAL * _COUNT_GUARD_MIN_RATIO)
    upper = int(_SPEC_ESTIMATE_TOTAL * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"regulation_record count guard failed: wrote {written} rows; "
            f"expected approximately {_SPEC_ESTIMATE_TOTAL} (acceptable range "
            f"{lower}-{upper}, ±30% of baseline). This indicates a "
            f"catastrophic regression in one of the extraction artifacts. "
            f"Investigate before re-running."
        )


def _assert_jurisdiction_binding_count_within_guard(written: int) -> None:
    """Fail loud if the jurisdiction_binding build count is outside the
    exact-match [1, 1] band. S03.6.1 ships the first binding row only
    (MT-STATEWIDE-bear → MT-STATEWIDE-geom); S03.10 will broaden this band
    when it ships its overlay-derived binding generation.
    """
    if not (_JURISDICTION_BINDING_GUARD_MIN <= written <= _JURISDICTION_BINDING_GUARD_MAX):
        raise RuntimeError(
            f"jurisdiction_binding count guard failed: built {written} rows; "
            f"expected exactly {_JURISDICTION_BINDING_EXPECTED_TOTAL} "
            "(S03.6.1 ships the first binding row only; S03.10 will broaden "
            "this band). Investigate before re-running."
        )


# ---------------------------------------------------------------------------
# Summary logging (UAT-prep precursor; S03.12 cross-checks against DB)
# ---------------------------------------------------------------------------


def _log_summary(
    records: list[RegulationRecord],
    legal_writes: list[tuple[str, str | None]],
    logger: logging.Logger,
) -> None:
    """Emit a count-by-(species_group, document_type, confidence) cross-tab.

    This is the in-memory precursor of the SQL UAT-prep queries that S03.12
    runs against the DB. The breakdown helps operators spot extraction drift
    at-load before the cost of a DB write.
    """
    # Aggregate (species_group, document_type, confidence) → count.
    buckets: dict[tuple[str, str, str], int] = {}
    for r in records:
        key = (r.species_group, r.source.document_type, r.confidence)
        buckets[key] = buckets.get(key, 0) + 1

    lines = ["regulation_record summary:"]
    lines.append("  species_group | document_type       | confidence | count")
    lines.append("  --------------+---------------------+------------+------")
    for (sg, dt, conf), n in sorted(buckets.items()):
        lines.append(f"  {sg:<13} | {dt:<19} | {conf:<10} | {n}")
    lines.append("  --------------+---------------------+------------+------")
    lines.append(f"  total                                            | {len(records)}")

    non_null = sum(1 for _, t in legal_writes if t is not None)
    null_set = sum(1 for _, t in legal_writes if t is None)
    lines.append(
        f"legal_description updates: {len(legal_writes)} "
        f"({non_null} non-null, {null_set} null-set)"
    )

    for line in lines:
        logger.info(line)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Load regulation_record rows + populate geometry.legal_description.

    Flow:
    1. Load DEA + legal-descriptions citations from sources.yaml.
    2. Load all three extraction artifacts from disk.
    3. Build regulation_record rows (DEA fan-out + bear per-row citation).
    4. Run the row-count fail-loud guard.
    5. Build the (geometry_id, text|None) tuples for legal_description updates.
    6. If --dry-run: log summary and exit 0 without writing.
    7. Otherwise: open DB connection, upsert regulation_record rows,
       update legal_description for each tuple, commit, log summary.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Load Montana regulation_record rows from the DEA + Black Bear "
            "extraction artifacts and populate geometry.legal_description from "
            "the Legal Descriptions extraction artifact. Writes "
            "~437 regulation_record rows + ~228 geometry UPDATE statements + "
            "1 jurisdiction_binding row atomically (single commit)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Build all records and run the count guard, but do not write to "
            "the DB. Useful for CI smoke-testing without DB connectivity."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("loading sources.yaml citations")
    dea_citation = _load_citation_from_sources_yaml(_DEA_CITATION_ID)
    bear_citation = _load_citation_from_sources_yaml(_BEAR_BOOKLET_CITATION_ID)
    # legal_desc_citation isn't directly used by the loader — it's already
    # baked into the legal-descriptions JSON artifact as `source_id`. We load
    # it here for the fail-loud guard (raises if the citation id is missing
    # from sources.yaml, surfacing a sources.yaml/artifact mismatch loudly).
    _ = _load_citation_from_sources_yaml(_LEGAL_DESC_CITATION_ID)

    logger.info("loading DEA artifact: %s", _DEA_ARTIFACT)
    with _DEA_ARTIFACT.open() as f:
        dea_artifact = json.load(f)
    logger.info("loading bear artifact: %s", _BEAR_ARTIFACT)
    with _BEAR_ARTIFACT.open() as f:
        bear_artifact = json.load(f)
    logger.info("loading legal-descriptions artifact: %s", _LEGAL_DESC_ARTIFACT)
    with _LEGAL_DESC_ARTIFACT.open() as f:
        legal_desc_artifact = json.load(f)

    logger.info("building regulation_record rows")
    statewide_bear_record = _build_statewide_bear_record(bear_artifact, bear_citation)
    records = (
        _build_dea_records(dea_artifact, dea_citation)
        + _build_bear_records(bear_artifact)
        + [statewide_bear_record]
    )
    logger.info("built %d regulation_record rows", len(records))

    _assert_count_within_guard(len(records))

    bindings = [_build_statewide_bear_binding(statewide_bear_record)]
    logger.info("built %d jurisdiction_binding rows", len(bindings))
    _assert_jurisdiction_binding_count_within_guard(len(bindings))

    legal_writes = _legal_description_writes(legal_desc_artifact)
    logger.info("queued %d geometry.legal_description updates", len(legal_writes))
    _assert_legal_desc_count_within_guard(len(legal_writes))

    if args.dry_run:
        logger.info("[dry-run] skipping DB writes")
        _log_summary(records, legal_writes, logger)
        return 0

    with db.connect() as conn:
        # FK ordering: regulation_record must be written before
        # jurisdiction_binding (the binding's composite-FK references the
        # parent record's PK). Single atomic commit — all-or-nothing.
        for record in records:
            db.upsert_regulation_record(conn, record)
        for binding in bindings:
            db.upsert_jurisdiction_binding(conn, binding)
        for geom_id, text in legal_writes:
            db.update_legal_description(conn, geom_id, text)
        conn.commit()

    logger.info(
        "loaded %d regulation_record rows + %d jurisdiction_binding rows + "
        "%d legal_description updates",
        len(records), len(bindings), len(legal_writes),
    )
    _log_summary(records, legal_writes, logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
