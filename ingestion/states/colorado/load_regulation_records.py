"""Colorado regulation_record ingestion adapter.

Reads two extraction artifacts produced by S06.3-S06.4 and writes:
    ``regulation_record`` rows to Postgres (V1 Colorado × elk/mule_deer/
    whitetail/pronghorn/bear × license_year=2026 — approximately 398 rows).

Q15 / ADR-018 §3 note
----------------------
The ``regulation_record`` table has no ``verbatim_rule`` column by design.
Section-level ``verbatim_text`` from the big-game artifact is NOT written
to the DB; it decomposes into S06.7's ``season_definition.verbatim_rule``
and ``license_tag.verbatim_rule``. This loader writes only the row anchor
(source + confidence + schema_version) plus ``additional_rules`` populated
from NOTE-style lines in verbatim_text (zero NOTE lines in CO V1 data;
the NOTE extraction path is preserved for correctness and future safety).
See ``docs/open-questions.md`` Q15 for the full rationale and ADR-008 for
the verbatim decomposition discipline.

Group A / Group B split
-----------------------
Group A (build / dry-run):  satisfied at merge — loader code + mocked/
    dry-run tests compile and pass the count guard against the committed
    extraction artifacts without DB connectivity.
Group B (operator-pending): live DB write depends on the outstanding E05
    operator geometry writes (CO geometry rows must exist in production
    before ``regulation_record`` rows are written, because S06.10's binding
    loader FKs to both). Run once the E05 Group B session has landed.

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/colorado/load_regulation_records.py

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
from collections import defaultdict
from pathlib import Path
from typing import Final, cast

import yaml

from ingestion.lib import db, pdf
from ingestion.lib.pdf import ConfidenceTier
from ingestion.lib.schema import Confidence, RegulationRecord, SourceCitation, VerbatimRule


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_COLORADO_DIR = Path(__file__).resolve().parent
_EXTRACTED_DIR = _COLORADO_DIR / "extracted"
_BIG_GAME_ARTIFACT = _EXTRACTED_DIR / "big-game-2026.json"
_BEAR_ARTIFACT = _EXTRACTED_DIR / "black-bear-2026.json"
_SOURCES_YAML = _COLORADO_DIR / "sources.yaml"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Naming note: the four existing CO loaders use ``CO_STATE_CODE = "US-CO"``.
# This loader uses ``_STATE`` to mirror MT precedent (montana/load_regulation_records.py)
# and the S05.6 scaffold (colorado/load_jurisdiction_bindings.py:55), ahead of the
# S06.0/D3 rename of those four loaders that ships bundled with S06.10.
_STATE: Final[str] = "US-CO"

_LICENSE_YEAR: Final[int] = 2026
_SCHEMA_VERSION: Final[int] = 2

# Single shared source_id for both big-game sections and bear sections.
_BIG_GAME_CITATION_ID: Final[str] = "co-cpw-big-game-2026-brochure"

# ADR-019 §Decision item 5: any document_type outside this set requires a
# flag-and-discuss + ADR-019 amendment before participation. The CO brochure
# is ``annual_regulations`` → passes. Guarded by ``_assert_document_type_allowed``.
_ALLOWED_DOCUMENT_TYPES: Final[frozenset[str]] = frozenset(
    {"annual_regulations", "correction"}
)

# Per-record-count fail-loud guard (OQ7 resolution / S06.6 analog).
# Baseline: 352 big-game (gmu, species) pairs (non-blank gmu_code) +
#           46 bear gmu unique values = 398 rows.
# Acceptable range: ±30% via int() truncation → [278, 517].
_SPEC_ESTIMATE_TOTAL: Final[int] = 398  # = 352 big-game + 46 bear
_COUNT_GUARD_MIN_RATIO = 0.70
_COUNT_GUARD_MAX_RATIO = 1.30

# Known informational bear ``statewide_rule`` hints. Both are summaries
# (season dates calendar, List A/B/C explanation), NOT pre-purchase coursework
# / Bear ID Test prerequisites — so they do NOT trigger a ``CO-STATEWIDE-bear``
# anchor (epic AC #549). Any OTHER ``rule_hint`` value is an undeclared
# statewide candidate that fails loud via ``_assert_no_undeclared_statewide_anchors``.
_KNOWN_STATEWIDE_RULE_HINTS: Final[frozenset[str]] = frozenset(
    {"season_dates_summary", "list_abc_explanation"}
)

# All valid ``record_type`` discriminator values in the CO bear flat-list artifact.
# Used by ``_build_co_bear_records`` to fail loud on missing or misspelled keys
# before silently filtering to ``"section"`` entries only.
_KNOWN_BEAR_RECORD_TYPES: Final[frozenset[str]] = frozenset(
    {"section", "statewide_rule", "reporting_obligation"}
)

# Binding id format — byte-identical to MT's ``load_regulation_records.py:115``.
#
# Encoded: PK-equivalent fields (state, jurisdiction_code, species_group,
# license_year) + role + geometry_id. Fields that may update freely without
# a PK change (verbatim_rule, source) are intentionally NOT encoded.
#
# Defined here for S06.10 to import for its symmetric derive-and-assert
# UPSERT no-op contract. CO V1 writes 0 statewide anchors so no bindings
# are produced by this loader; the constant is a forward-reference contract
# only. S06.10 must use this exact format string when deriving binding ids
# so that any future statewide anchor written here is a stable UPSERT no-op.
_JURISDICTION_BINDING_ID_FORMAT: Final[str] = (
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
        RuntimeError: if ``citation_id`` is not found in the ``pdfs:`` section
            of sources.yaml.

    This loader is intentionally duplicated across state adapters per the
    Literal-duplication convention in ``.roughly/known-pitfalls.md`` — each
    adapter owns its own source-citation deserialization to keep adapter
    modules self-contained.
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
        f"sources.yaml has no entry with id={citation_id!r} in the 'pdfs:' section"
    )


# ---------------------------------------------------------------------------
# Document-type guard (ADR-019 §Decision item 5)
# ---------------------------------------------------------------------------


def _assert_document_type_allowed(citation: SourceCitation) -> None:
    """Fail loud if citation.document_type is not in the allowed set.

    ADR-019 §Decision item 5 states that any document_type outside
    ``{"annual_regulations", "correction"}`` requires a flag-and-discuss
    session and an ADR-019 amendment before the citation may participate
    in a regulation_record write. Raising here surfaces the issue immediately
    rather than silently widening the type space.

    Raises:
        ValueError: if ``citation.document_type`` is not in
            ``_ALLOWED_DOCUMENT_TYPES``.
    """
    if citation.document_type not in _ALLOWED_DOCUMENT_TYPES:
        raise ValueError(
            f"citation {citation.id!r} has document_type={citation.document_type!r}, "
            f"which is not in the allowed set {sorted(_ALLOWED_DOCUMENT_TYPES)}. "
            "Per ADR-019 §Decision item 5, adding a new document_type requires a "
            "flag-and-discuss session and an ADR-019 amendment before adoption."
        )


# ---------------------------------------------------------------------------
# NOTE-line capture (HD-wide additional rules from section verbatim_text)
# ---------------------------------------------------------------------------

# Matches a NOTE: prefixed line and any continuation lines that follow,
# up to (but not including) the next NOTE: line or an ALL-CAPS-LIKE line
# (e.g. table column headers) or end of string. Byte-identical to
# montana/load_regulation_records.py:182-185.
#
# Continuation rule: pdfplumber's word grouping breaks the NOTE prose
# across physical lines; we capture the whole logical NOTE then collapse
# inter-line whitespace at the call site (extras-only whitespace collapse,
# per S03.3's cleanup convention — ADR-008-safe because the content is
# identical, only run-length-encoded whitespace is normalized).
# Note: the prefix-consume class is ``[ \t]*`` (horizontal whitespace only).
# Using greedy ``\s*`` would eat newlines and absorb a downstream NOTE: line
# into the current match when sections have whitespace-only spacer lines
# between NOTEs.
_NOTE_LINE_RE = re.compile(
    r"^NOTE:[ \t]*(?P<body>.*?)(?=\n^NOTE:|\n^[A-Z]{3,}|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _extract_note_lines(
    verbatim_text: str,
    citation: SourceCitation,
    confidence: Confidence,
) -> list[VerbatimRule]:
    """Parse ``NOTE:`` prefixed lines out of a section's verbatim_text.

    Each match becomes one VerbatimRule with text formatted as
    ``"NOTE: <collapsed-body>"`` so the literal source prefix is preserved
    for downstream readers of ``regulation_record.additional_rules``.

    Whitespace collapse: each captured body has internal whitespace runs
    (including newlines from pdfplumber's line-breaking) normalized to
    single spaces. ADR-008-safe.

    Empty bodies (defensive — should not occur on real CO data) are skipped
    so we never emit an empty NOTE rule.

    Returns the list of VerbatimRule entries in source order. Empty list
    if no NOTE lines were found (expected for all CO V1 sections).
    """
    rules: list[VerbatimRule] = []
    for match in _NOTE_LINE_RE.finditer(verbatim_text):
        body = match.group("body").strip()
        body = re.sub(r"\s+", " ", body)
        if not body:
            continue
        rules.append(
            VerbatimRule(
                text=f"NOTE: {body}",
                page_reference=citation.page_reference,
                confidence=confidence,
                source=citation,
            )
        )
    return rules


# ---------------------------------------------------------------------------
# Jurisdiction-code helper
# ---------------------------------------------------------------------------


def _co_gmu_jurisdiction_code(gmu_code: str) -> str:
    """Derive the regulation_record jurisdiction_code from an artifact gmu_code.

    Artifact gmu_codes are zero-padded strings (e.g. ``"001"``, ``"020"``,
    ``"082"``). The geometry id written by S05.2's ``load_gmus.py`` uses the
    un-padded integer form: ``CO-GMU-{int(GMUID)}-geom`` (e.g. ``CO-GMU-1-geom``,
    ``CO-GMU-20-geom``, ``CO-GMU-82-geom``). To ensure S06.10 can map
    ``jurisdiction_code → geometry_id`` by simply appending ``"-geom"``,
    this function applies the same ``int()`` normalization to strip leading zeros.

    ``int()`` will raise ``ValueError`` on a non-numeric gmu_code. Callers
    must guard against blank gmu_codes upstream (blank sections are skipped
    before calling this helper).
    """
    return f"CO-GMU-{int(gmu_code)}"


# ---------------------------------------------------------------------------
# Count guard
# ---------------------------------------------------------------------------


def _assert_count_within_guard(written: int) -> None:
    """Fail loud if the regulation_record write count is outside the 70%-130%
    band of the baseline (398 = 352 big-game (gmu, species) pairs + 46 bear
    gmu unique values). Concrete bounds after int() truncation: [278, 517].
    Below or above indicates a catastrophic regression in one of the extraction
    artifacts — investigate before re-running.
    """
    lower = int(_SPEC_ESTIMATE_TOTAL * _COUNT_GUARD_MIN_RATIO)
    upper = int(_SPEC_ESTIMATE_TOTAL * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"regulation_record count guard failed: wrote {written} rows; "
            f"expected approximately {_SPEC_ESTIMATE_TOTAL} (acceptable range "
            f"{lower}-{upper}, ±30% of baseline (352 big-game + 46 bear)). "
            "This indicates a catastrophic regression in one of the extraction "
            "artifacts. Investigate before re-running."
        )


# ---------------------------------------------------------------------------
# Statewide-anchor flag-and-discuss guard (AC #549)
# ---------------------------------------------------------------------------


def _assert_no_undeclared_statewide_anchors(
    big_game_artifact: list[dict],  # type: ignore[type-arg]
    bear_artifact: list[dict],  # type: ignore[type-arg]
) -> None:
    """Fail loud if either artifact contains an undeclared statewide candidate.

    Two classes of undeclared statewide anchor are checked:

    (a) Big-game sections with ``gmu_code == "STATEWIDE"`` (case-insensitive /
        stripped). CO V1 has zero such sections; if one appears it is a new
        pronghorn-statewide analog (MT ``900-20``) requiring PM review before
        a ``CO-STATEWIDE-pronghorn`` anchor is written.

    (b) Bear ``statewide_rule`` records whose ``rule_hint`` is not in
        ``_KNOWN_STATEWIDE_RULE_HINTS``. The two known hints are informational
        summaries (``"season_dates_summary"`` and ``"list_abc_explanation"``),
        NOT pre-purchase coursework / Bear ID Test prerequisites. Any other
        hint is a possible Bear-ID-Test-style prerequisite requiring a
        flag-and-discuss before a ``CO-STATEWIDE-bear`` anchor is written.

    Raises:
        ValueError: if an undeclared statewide candidate is found.
    """
    for section in big_game_artifact:
        raw_gmu = str(section.get("gmu_code", "")).strip().upper()
        if raw_gmu == "STATEWIDE":
            raise ValueError(
                f"big-game artifact contains a section with gmu_code='STATEWIDE' "
                f"(species_group={section.get('species_group')!r}, "
                f"method_group={section.get('method_group')!r}). "
                "This is an undeclared pronghorn-statewide analog (MT 900-20 pattern) "
                "requiring PM review before a CO-STATEWIDE anchor is written. "
                "Flag-and-discuss before proceeding."
            )

    for record in bear_artifact:
        if record.get("record_type") != "statewide_rule":
            continue
        hint = record.get("rule_hint", "")
        if hint not in _KNOWN_STATEWIDE_RULE_HINTS:
            raise ValueError(
                f"bear artifact contains a statewide_rule record with "
                f"rule_hint={hint!r}, which is not in the known-informational "
                f"allowlist {sorted(_KNOWN_STATEWIDE_RULE_HINTS)}. "
                "This may be a Bear ID Test / pre-purchase coursework prerequisite "
                "analog of MT's Bear ID Test (S03.6.1), requiring a flag-and-discuss "
                "before a CO-STATEWIDE-bear anchor is written. "
                "If this hint is genuinely informational, add it to "
                "_KNOWN_STATEWIDE_RULE_HINTS with a rationale comment."
            )


# ---------------------------------------------------------------------------
# Summary logging
# ---------------------------------------------------------------------------


def _log_summary(
    records: list[RegulationRecord],
    logger: logging.Logger,
) -> None:
    """Emit a count-by-(species_group, document_type, confidence) cross-tab.

    This is the in-memory precursor of the SQL UAT-prep queries that will
    run against the DB. The breakdown helps operators spot extraction drift
    at-load before the cost of a DB write.

    No ``legal_description`` line — CO V1 has no legal descriptions.
    """
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

    for line in lines:
        logger.info(line)


# ---------------------------------------------------------------------------
# Big-game record builder (collapse by (gmu_code, species_group))
# ---------------------------------------------------------------------------


def _build_big_game_records(
    big_game_artifact: list[dict],  # type: ignore[type-arg]
    citation: SourceCitation,
    logger: logging.Logger,
) -> list[RegulationRecord]:
    """Build regulation_record rows from the big-game extraction artifact.

    Collapses all sections sharing a ``(gmu_code, species_group)`` tuple into
    one ``regulation_record`` (the anchor entity keyed by
    ``(state, jurisdiction_code, species_group, license_year)``). Method /
    season / license detail decomposes to S06.7 child entities.

    Blank ``gmu_code`` sections are skipped with a warning (one expected: the
    S06.3.1 documented heading-absorption residual at GMU 020 elk archery page
    52; its GMU is already covered by 3 proper non-blank elk sections so no
    anchor is lost).

    CO V1 has NO fan-out dict (species_group values are ``mule_deer``,
    ``whitetail``, ``elk``, ``pronghorn`` — pre-separated by the extractor;
    no ``"deer"`` label requiring expansion to two rows).
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)  # type: ignore[type-arg]
    skipped = 0
    for idx, section in enumerate(big_game_artifact):
        # Fail loud on non-dict entries or missing required keys before any access.
        if not isinstance(section, dict):
            raise RuntimeError(
                f"big-game artifact[{idx}] is not a dict "
                f"(got {type(section).__name__}); "
                "re-run extract_big_game.py and inspect the artifact"
            )
        try:
            species_group_val = section["species_group"]
        except KeyError as exc:
            raise RuntimeError(
                f"big-game artifact[{idx}] missing required key {exc.args[0]!r}; "
                f"keys present: {sorted(section.keys())!r}; "
                "re-run extract_big_game.py and inspect the artifact"
            ) from exc

        gmu_code = section.get("gmu_code", "")
        if not gmu_code:
            logger.warning(
                "skipping big-game section with blank gmu_code: "
                "species=%s method=%s page=%s "
                "(heading-absorption residual; GMU is covered by other sections)",
                section.get("species_group"),
                section.get("method_group"),
                section.get("page_reference", {}).get("page_num_1based"),
            )
            skipped += 1
            continue
        groups[(gmu_code, species_group_val)].append(section)

    if skipped:
        logger.warning("skipped %d big-game section(s) with blank gmu_code", skipped)

    # Validate every group key is numeric before the sort — a non-numeric non-blank
    # gmu_code would raise a bare ValueError inside the sort lambda with no context.
    for gmu_code, _species in groups:
        try:
            int(gmu_code)
        except ValueError:
            raise RuntimeError(
                f"big-game builder: gmu_code={gmu_code!r} is non-numeric and non-blank; "
                "expected a zero-padded integer string (e.g. '020'). "
                "Investigate extract_big_game.py output."
            )

    records: list[RegulationRecord] = []
    for gmu_code, species_group in sorted(groups, key=lambda k: (int(k[0]), k[1])):
        sections = groups[(gmu_code, species_group)]

        # Guard: each section must have a 'rows' key and each row an
        # 'extraction_confidence' key. Wrap with diagnostic RuntimeError so a
        # missing key names the builder, section index, gmu_code, and species_group.
        try:
            tier_list = [
                ConfidenceTier(row["extraction_confidence"])
                for sec in sections
                for row in sec["rows"]
            ]
        except KeyError as exc:
            raise RuntimeError(
                f"big-game builder: gmu={gmu_code!r} species={species_group!r}: "
                f"section is missing required key {exc.args[0]!r} "
                f"(check 'rows' exists on each section and 'extraction_confidence' "
                f"exists on each row); re-run extract_big_game.py"
            ) from exc

        # MIN over all rows across all sections in the group — NOT bare min() on
        # strings (lexicographic trap: min(["high", "low"]) returns "high").
        try:
            confidence = cast(Confidence, pdf.min_tier(tier_list))
        except pdf.PdfExtractionError as exc:
            raise RuntimeError(
                f"big-game builder: gmu={gmu_code!r} species={species_group!r}: {exc}"
            ) from exc

        # Representative section: smallest (page_num_1based, method_group) — deterministic.
        try:
            rep = min(
                sections,
                key=lambda s: (s["page_reference"]["page_num_1based"], s["method_group"]),
            )
            page_ref_str = pdf.page_reference_to_str(rep["page_reference"])
        except KeyError as exc:
            raise RuntimeError(
                f"big-game builder: gmu={gmu_code!r} species={species_group!r}: "
                f"section missing required key {exc.args[0]!r} "
                f"(expected 'page_reference' dict with 'page_num_1based' and 'method_group'); "
                "re-run extract_big_game.py"
            ) from exc
        section_citation = citation.model_copy(update={"page_reference": page_ref_str})

        # Collect NOTE lines across all sections in deterministic order. Each
        # NOTE is attributed to its OWN section's page (a group may span multiple
        # pages), so per-NOTE provenance is preserved — the representative
        # `section_citation` is only the anchor row's source. (CO V1 has zero
        # NOTE lines; this path is kept correct for future safety.)
        additional_rules: list[VerbatimRule] = []
        for sec in sorted(
            sections,
            key=lambda s: (s["page_reference"]["page_num_1based"], s["method_group"]),
        ):
            try:
                verbatim = sec["verbatim_text"]
                sec_page_ref = pdf.page_reference_to_str(sec["page_reference"])
            except KeyError as exc:
                raise RuntimeError(
                    f"big-game builder: gmu={gmu_code!r} species={species_group!r}: "
                    f"section missing required key {exc.args[0]!r}; "
                    "re-run extract_big_game.py"
                ) from exc
            sec_citation = citation.model_copy(update={"page_reference": sec_page_ref})
            additional_rules.extend(
                _extract_note_lines(verbatim, sec_citation, confidence)
            )

        records.append(
            RegulationRecord(
                state=_STATE,
                jurisdiction_code=_co_gmu_jurisdiction_code(gmu_code),
                species_group=species_group,
                license_year=_LICENSE_YEAR,
                schema_version=_SCHEMA_VERSION,
                source=section_citation,
                confidence=confidence,
                additional_rules=additional_rules,
            )
        )

    return records


# ---------------------------------------------------------------------------
# Bear record builder (collapse by gmu_code; flat list artifact)
# ---------------------------------------------------------------------------


def _build_co_bear_records(
    bear_artifact: list[dict],  # type: ignore[type-arg]
    citation: SourceCitation,
    logger: logging.Logger,
) -> list[RegulationRecord]:
    """Build regulation_record rows from the CO bear extraction artifact.

    The CO bear artifact is a **flat list** (NOT a dict with top-level
    ``sources``/``rows`` keys like MT). Filter to ``record_type == "section"``,
    group by ``gmu_code``, collapse per group to one record.

    Bear DB ``species_group`` is ``"bear"`` (NOT ``"black_bear"`` — that is the
    artifact value; see `.roughly/known-pitfalls.md` "Bear DB species_group").

    All sections share the single brochure citation; no per-row citation lookup.
    """
    # Fail loud on non-dict entries, missing ``record_type``, or an unknown
    # ``record_type`` value (catches misspellings like "Section"/"sections").
    # Then keep only ``record_type == "section"`` entries.
    sections: list[dict] = []  # type: ignore[type-arg]
    for idx, r in enumerate(bear_artifact):
        if not isinstance(r, dict):
            raise RuntimeError(
                f"bear artifact[{idx}] is not a dict "
                f"(got {type(r).__name__}); "
                "re-run extract_black_bear.py and inspect the artifact"
            )
        if "record_type" not in r:
            raise RuntimeError(
                f"bear artifact[{idx}] is missing the 'record_type' key; "
                f"keys present: {sorted(r.keys())!r}; "
                "re-run extract_black_bear.py and inspect the artifact"
            )
        if r["record_type"] not in _KNOWN_BEAR_RECORD_TYPES:
            raise RuntimeError(
                f"bear artifact[{idx}] has unknown record_type={r['record_type']!r}; "
                f"known types: {sorted(_KNOWN_BEAR_RECORD_TYPES)!r}; "
                "this may be a misspelling — re-run extract_black_bear.py and inspect the artifact"
            )
        if r["record_type"] == "section":
            sections.append(r)

    groups: dict[str, list[dict]] = defaultdict(list)  # type: ignore[type-arg]
    blank_skipped = 0
    for section in sections:
        gmu_code = section.get("gmu_code", "")
        if not gmu_code:
            # Defensive — none expected in the CO bear artifact.
            logger.warning(
                "skipping bear section with blank gmu_code: "
                "method=%s page=%s "
                "(defensive; not expected in CO V1)",
                section.get("method_group"),
                section.get("page_reference", {}).get("page_num_1based"),
            )
            blank_skipped += 1
            continue
        groups[gmu_code].append(section)

    if blank_skipped:
        logger.warning("skipped %d bear section(s) with blank gmu_code", blank_skipped)

    # Validate every group key is numeric before the sort.
    for gmu_code in groups:
        try:
            int(gmu_code)
        except ValueError:
            raise RuntimeError(
                f"bear builder: gmu_code={gmu_code!r} is non-numeric and non-blank; "
                "expected a zero-padded integer string (e.g. '082'). "
                "Investigate extract_black_bear.py output."
            )

    records: list[RegulationRecord] = []
    for gmu_code in sorted(groups, key=lambda k: int(k)):
        gmu_sections = groups[gmu_code]

        # Guard: each section must have a 'rows' key and each row an
        # 'extraction_confidence' key. Wrap with diagnostic RuntimeError.
        try:
            tier_list = [
                ConfidenceTier(row["extraction_confidence"])
                for sec in gmu_sections
                for row in sec["rows"]
            ]
        except KeyError as exc:
            raise RuntimeError(
                f"bear builder: gmu={gmu_code!r}: "
                f"section is missing required key {exc.args[0]!r} "
                f"(check 'rows' exists on each section and 'extraction_confidence' "
                f"exists on each row); re-run extract_black_bear.py"
            ) from exc

        # MIN over all rows across all sections in the group.
        try:
            confidence = cast(Confidence, pdf.min_tier(tier_list))
        except pdf.PdfExtractionError as exc:
            raise RuntimeError(
                f"bear builder: gmu={gmu_code!r}: {exc}"
            ) from exc

        # Representative section: smallest (page_num_1based, method_group) — deterministic.
        try:
            rep = min(
                gmu_sections,
                key=lambda s: (s["page_reference"]["page_num_1based"], s["method_group"]),
            )
            page_ref_str = pdf.page_reference_to_str(rep["page_reference"])
        except KeyError as exc:
            raise RuntimeError(
                f"bear builder: gmu={gmu_code!r}: "
                f"section missing required key {exc.args[0]!r} "
                f"(expected 'page_reference' dict with 'page_num_1based' and 'method_group'); "
                "re-run extract_black_bear.py"
            ) from exc
        section_citation = citation.model_copy(update={"page_reference": page_ref_str})

        # Collect NOTE lines across all sections in deterministic order. Each
        # NOTE is attributed to its OWN section's page (a group may span multiple
        # pages), so per-NOTE provenance is preserved — the representative
        # `section_citation` is only the anchor row's source. (CO V1 has zero
        # NOTE lines; this path is kept correct for future safety.)
        additional_rules: list[VerbatimRule] = []
        for sec in sorted(
            gmu_sections,
            key=lambda s: (s["page_reference"]["page_num_1based"], s["method_group"]),
        ):
            try:
                verbatim = sec["verbatim_text"]
                sec_page_ref = pdf.page_reference_to_str(sec["page_reference"])
            except KeyError as exc:
                raise RuntimeError(
                    f"bear builder: gmu={gmu_code!r}: "
                    f"section missing required key {exc.args[0]!r}; "
                    "re-run extract_black_bear.py"
                ) from exc
            sec_citation = citation.model_copy(update={"page_reference": sec_page_ref})
            additional_rules.extend(
                _extract_note_lines(verbatim, sec_citation, confidence)
            )

        records.append(
            RegulationRecord(
                state=_STATE,
                jurisdiction_code=_co_gmu_jurisdiction_code(gmu_code),
                # Artifact field is "black_bear"; DB value is "bear".
                # See .roughly/known-pitfalls.md "Bear DB species_group is 'bear' not 'black_bear'".
                species_group="bear",
                license_year=_LICENSE_YEAR,
                schema_version=_SCHEMA_VERSION,
                source=section_citation,
                confidence=confidence,
                additional_rules=additional_rules,
            )
        )

    return records


# ---------------------------------------------------------------------------
# Entry point (three-phase: build → guards pre-db.connect() → upsert/commit)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Build and optionally write CO regulation_record rows.

    Three-phase pipeline (per OQ7 discipline):
      1. Build all records and run guards (count guard, document_type guard,
         statewide-anchor guard) — all fire BEFORE ``db.connect()``.
      2. If ``--dry-run``: log the summary cross-tab and exit 0 without any
         DB connectivity.
      3. Else: open a connection, UPSERT all rows, commit atomically, log.

    Group A / Group B split (see module docstring):
    - Group A (build / dry-run): satisfied at merge — no DB required.
    - Group B (operator-pending): live write depends on E05 Group B geometry
      rows existing in production before regulation_record rows are written.
    """
    parser = argparse.ArgumentParser(
        description="Ingest CO regulation_record rows into Supabase Postgres."
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

    # --- citation (shared by both big-game and bear sections) ---
    citation = _load_citation_from_sources_yaml(_BIG_GAME_CITATION_ID)
    _assert_document_type_allowed(citation)
    logger.info(
        "loaded citation: id=%s document_type=%s publication_date=%s",
        citation.id,
        citation.document_type,
        citation.publication_date,
    )

    # --- load artifacts ---
    logger.info("loading big-game artifact: %s", _BIG_GAME_ARTIFACT)
    with _BIG_GAME_ARTIFACT.open() as f:
        big_game_artifact: list[dict] = json.load(f)  # type: ignore[type-arg]
    if not isinstance(big_game_artifact, list):
        raise RuntimeError(
            f"big-game artifact at {_BIG_GAME_ARTIFACT} is not a JSON array "
            f"(got {type(big_game_artifact).__name__}); "
            "re-run extract_big_game.py and inspect the artifact"
        )

    logger.info("loading bear artifact: %s", _BEAR_ARTIFACT)
    with _BEAR_ARTIFACT.open() as f:
        bear_artifact: list[dict] = json.load(f)  # type: ignore[type-arg]
    if not isinstance(bear_artifact, list):
        raise RuntimeError(
            f"bear artifact at {_BEAR_ARTIFACT} is not a JSON array "
            f"(got {type(bear_artifact).__name__}); "
            "re-run extract_black_bear.py and inspect the artifact"
        )

    # --- statewide-anchor flag-and-discuss guard (fires pre-db.connect()) ---
    _assert_no_undeclared_statewide_anchors(big_game_artifact, bear_artifact)
    statewide_rule_count = sum(
        1 for r in bear_artifact if r.get("record_type") == "statewide_rule"
    )
    logger.info(
        "statewide-anchor guard passed: evaluated %d bear statewide_rule hint(s) "
        "(all in known-informational allowlist) → 0 CO-STATEWIDE-bear anchors written",
        statewide_rule_count,
    )

    # --- build records (pre-db.connect()) ---
    records = _build_big_game_records(
        big_game_artifact, citation, logger
    ) + _build_co_bear_records(bear_artifact, citation, logger)
    logger.info("built %d regulation_record rows", len(records))

    # --- count guard (pre-db.connect()) ---
    _assert_count_within_guard(len(records))

    # --- dry-run short-circuit ---
    if args.dry_run:
        logger.info("--dry-run: skipping DB write")
        _log_summary(records, logger)
        return 0

    # --- live write (Phase 3) ---
    with db.connect() as conn:
        for record in records:
            db.upsert_regulation_record(conn, record)
        conn.commit()
    logger.info(
        "wrote %d regulation_record rows (state=%s license_year=%d)",
        len(records),
        _STATE,
        _LICENSE_YEAR,
    )
    _log_summary(records, logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
