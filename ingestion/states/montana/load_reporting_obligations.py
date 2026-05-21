"""Montana reporting_obligation + regulation_reporting ingestion adapter.

Reads ``ingestion/states/montana/extracted/black-bear-2026.json`` and writes
two tables in one atomic transaction:

1. ``reporting_obligation`` rows — 3 entity rows derived from the bear
   artifact's top-level ``reporting_obligations`` list.
2. ``regulation_reporting`` link rows — 70 rows derived from the bear
   artifact's top-level ``rows`` list (per-BMU ``hd_region`` routing).

Per ADR-010 (decomposed-entity model), these are child entities whose FK
target is the 35 bear ``regulation_record`` rows landed by S03.6.

Inputs
------
- ``ingestion/states/montana/extracted/black-bear-2026.json``
  - ``reporting_obligations`` list — entity construction (3 entries)
  - ``rows`` list — per-BMU ``hd_region`` routing for link rows (35 entries)
  - ``sources`` list — SourceCitation embedding (no ``sources.yaml`` read;
    the bear artifact carries source dicts inline, same pattern as S03.6's
    bear path)

Outputs (atomic)
----------------
- **3 reporting_obligation rows** written via UPSERT (idempotent).
- **70 regulation_reporting link rows** written via ON CONFLICT DO NOTHING.

All writes are in a single transaction — either all succeed or nothing is
committed.

Row construction rules
-----------------------
Three rows are built from the artifact's ``reporting_obligations`` list via a
single dispatch dictionary keyed by ``(region_scope, kind_hint)``.  Fail-loud
on any unknown combo (RuntimeError enumerating the 3 valid combos).

Row 1 — STATEWIDE harvest_report
    ``id``                ``mt-bear-harvest-report-48hr-statewide``
    ``kind``              ``"harvest_report"``
    ``deadline``          ``"48 hours"``
    ``deadline_hours``    ``48``
    ``submission_method`` ``"phone"``
    ``submission_url``    ``"https://fwp.mt.gov"``
    ``submission_phone``  ``"1-877-FWPWILD"``
    ``applies_to_regions``  ``None``  (statewide — all 35 bear records)
    ``what_to_present``   ``None``  (info-submission, not physical-presentation)

Row 2 — R1 tooth_submission
    ``id``                ``mt-bear-tooth-submission-r1-10day``
    ``kind``              ``"tooth_submission"``
    ``deadline``          ``"10 days"``
    ``deadline_hours``    ``240``
    ``submission_method`` ``"agency_office"``
    ``submission_url``    ``None``
    ``submission_phone``  ``None``
    ``applies_to_regions``  ``["R1"]``  (14 R1 bear records)
    ``what_to_present``   ``["both premolar teeth"]``

Row 3 — R2-7 hide_skull_presentation
    ``id``                ``mt-bear-hide-skull-r2to7-10day``
    ``kind``              ``"hide_skull_presentation"``
    ``deadline``          ``"10 days"``
    ``deadline_hours``    ``240``
    ``submission_method`` ``"in_person_check_station"``
    ``submission_url``    ``None``
    ``submission_phone``  ``None``
    ``applies_to_regions``  ``["R2", "R3", "R4", "R5", "R6", "R7"]``  (21 R2-7 records)
    ``what_to_present``   ``["hide", "skull"]``

Cleanup rules
-------------
None.  ``verbatim_rule`` is preserved byte-faithful per ADR-008 (no
whitespace collapse, no normalization).  This empty cleanup-rules statement
is intentional and enforced by tests.

Confidence
----------
None.  ``reporting_obligation`` has no confidence column; child entities
inherit confidence from the parent ``regulation_record`` per ADR-017.

Transaction structure (three phases)
--------------------------------------
1. **Build** — construct entity rows and link rows entirely in memory from
   the bear artifact; all Pydantic validation fires here.
2. **Guards** — OQ7 row-count bands fire BEFORE ``db.connect()``; any band
   violation raises ``RuntimeError`` so no partial write occurs.
3. **Conn open → Phase 4a upsert entities → Phase 4b write links → commit**;
   rollback on any exception; close in finally.

Fail-loud disciplines
---------------------
(a) Pydantic validation failure raises at the row where the bad value appears.
(b) Unknown ``(region_scope, kind_hint)`` combo in the dispatch dict raises
    ``RuntimeError`` with the combo + the 3 valid combos enumerated.
(c) Unknown ``source_id`` in the artifact raises ``RuntimeError`` listing the
    bad id and the valid ids found in the artifact's ``sources`` list.
(d) Unknown ``hd_region`` on a bear artifact row raises ``RuntimeError``.
(e) Count guard violation raises ``RuntimeError`` with the band, the actual
    count, and a hint to update ``_EXPECTED_*_COUNT`` if the source PDF changed.

State-agnostic posture
-----------------------
This adapter imports ONLY from ``ingestion.lib.*``.  It does NOT import from
any other state adapter (no cross-state or cross-Montana-adapter imports).
Locked by ``TestNoLibImports`` (T7).

Invocation
----------
    ingestion/.venv/bin/python ingestion/states/montana/load_reporting_obligations.py [--dry-run] [-v]

NOT ``python -m`` (state package is non-subpackage per S03.1 pitfall).

Required env: ``DATABASE_URL``.

Optional flags:
    ``--dry-run``   Build all records and run the count guards, but do not
                    write to the DB.  Useful for CI smoke-testing without DB
                    connectivity.
    ``-v``/``--verbose``  Enable DEBUG-level logging.

Relevant ADRs
-------------
- ADR-001: Authority preserved, not replaced (no invented field values).
- ADR-008: Verbatim discipline (verbatim_rule byte-faithful; no cleanup rules
  applied in this adapter).
- ADR-009: Open-questions discipline (Q18 CWD-sampling modeling deferred).
- ADR-010: Decomposed entities (reporting_obligation + regulation_reporting as
  child entities of regulation_record).
- ADR-017: Confidence inheritance (reporting_obligation has no confidence
  column; confidence is the parent regulation_record's responsibility).
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from typing import Final, Literal, TypedDict

from ingestion.lib import db, pdf
from ingestion.lib.schema import (
    RegulationReporting,
    ReportingObligation,
    SourceCitation,
)


# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MT_STATE_CODE: Final[str] = "US-MT"
_LICENSE_YEAR: Final[int] = 2026
_BEAR_SPECIES_GROUP: Final[str] = "bear"  # DB value; artifact top-level is "black_bear" — do not confuse

_BEAR_ARTIFACT_PATH: Final[pathlib.Path] = (
    pathlib.Path(__file__).parent / "extracted" / "black-bear-2026.json"
)

_R1_REGIONS: Final[frozenset[str]] = frozenset({"R1"})
_R2_TO_R7_REGIONS: Final[frozenset[str]] = frozenset(
    {"R2", "R3", "R4", "R5", "R6", "R7"}
)

_ID_PREFIX: Final[str] = "mt-bear"

_EXPECTED_REPORTING_OBLIGATION_COUNT: Final[int] = 3
_EXPECTED_REGULATION_REPORTING_COUNT: Final[int] = 70

# ±30% bands fire BEFORE db.connect()
_REPORTING_OBLIGATION_COUNT_GUARD_BAND: Final[tuple[int, int]] = (2, 4)
_REGULATION_REPORTING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (49, 91)


# ---------------------------------------------------------------------------
# Dispatch dictionary for reporting_obligation entity construction (T3)
# ---------------------------------------------------------------------------


class _RowSpec(TypedDict):
    """Structured-field values for a single reporting_obligation row.

    The dispatch dict maps (region_scope, kind_hint) tuples to these specs.
    All structured-field interpretation lives in the dispatch dict; the build
    function reads verbatim_rule + source from the artifact and applies the
    spec verbatim. See docs/planning/epics/E03-confidence-findings/S03.9.md
    § "Row-by-row construction decisions" for the locked values.
    """

    id_suffix: str
    kind: Literal[
        "harvest_report",
        "mandatory_check",
        "tooth_submission",
        "hide_skull_presentation",
        "cwd_sample",
        "other",
    ]
    deadline: str
    deadline_hours: int
    submission_method: Literal[
        "online", "phone", "in_person_check_station", "mail", "agency_office"
    ]
    submission_url: str | None
    submission_phone: str | None
    applies_to_regions: list[str] | None
    what_to_present: list[str] | None


_REPORTING_ROW_SPEC: Final[dict[tuple[str, str], _RowSpec]] = {
    ("STATEWIDE", "harvest_report"): {
        "id_suffix": "harvest-report-48hr-statewide",
        "kind": "harvest_report",
        "deadline": "48 hours",
        "deadline_hours": 48,
        "submission_method": "phone",
        "submission_url": "https://fwp.mt.gov",
        "submission_phone": "1-877-FWPWILD",
        "applies_to_regions": None,
        "what_to_present": None,
    },
    ("R1", "tooth_submission"): {
        "id_suffix": "tooth-submission-r1-10day",
        "kind": "tooth_submission",
        "deadline": "10 days",
        "deadline_hours": 240,
        "submission_method": "agency_office",
        "submission_url": None,
        "submission_phone": None,
        "applies_to_regions": ["R1"],
        "what_to_present": ["both premolar teeth"],
    },
    ("R2-7", "hide_skull_presentation"): {
        "id_suffix": "hide-skull-r2to7-10day",
        "kind": "hide_skull_presentation",
        "deadline": "10 days",
        "deadline_hours": 240,
        "submission_method": "in_person_check_station",
        "submission_url": None,
        "submission_phone": None,
        "applies_to_regions": ["R2", "R3", "R4", "R5", "R6", "R7"],
        "what_to_present": ["hide", "skull"],
    },
}


# ---------------------------------------------------------------------------
# Drift guard for _REPORTING_ROW_SPEC's id_suffix encoding (V1 belt-and-suspenders)
# ---------------------------------------------------------------------------
#
# The reporting_obligation.id is hand-encoded as a slug that bakes in kind,
# deadline_hours, and region_scope (e.g., "mt-bear-harvest-report-48hr-
# statewide" encodes all three). The UPSERT in db.upsert_reporting_obligation
# updates these slug-encoded fields under the same id — so if a future spec
# edit changes one of those structured fields without correspondingly
# updating id_suffix, the DO UPDATE clause would silently rewrite the meaning
# of an existing row that already has regulation_reporting links pointing at
# it. The two states would both satisfy ON CONFLICT (id); the new field
# values win.
#
# V1 risk is theoretical (closed compile-time dispatch dict, no operator-
# runtime mutation path, unit tests lock canonical pairings) but worth
# guarding against here at module load. This guard is S03.9-LOCAL — see Q19
# in docs/open-questions.md for the project-wide fix planned pre-M2, which
# will generalize the pattern across season_definition + license_tag +
# reporting_obligation.

_KIND_SLUG_OVERRIDES: Final[dict[str, str]] = {
    # Drop the "_presentation" suffix for the R2-7 row's slug — the canonical
    # encoding is "hide-skull-r2to7-10day", not
    # "hide-skull-presentation-r2to7-10day". If a future kind value introduces
    # a similarly verbose suffix, add it here.
    "hide_skull_presentation": "hide-skull",
}

_REGION_SCOPE_SLUG: Final[dict[str, str]] = {
    "STATEWIDE": "statewide",
    "R1": "r1",
    "R2-7": "r2to7",
}


def _derive_expected_id_suffix(
    kind: str, deadline_hours: int, region_scope: str,
) -> str:
    """Derive the canonical id_suffix from the slug-encoded fields.

    Mirrors the encoding currently locked in ``_REPORTING_ROW_SPEC``:

    - kind: ``_`` → ``-``; verbose kinds (e.g., ``hide_skull_presentation``)
      consult ``_KIND_SLUG_OVERRIDES`` for shortened forms.
    - deadline_hours: ``<= 48`` → ``"{N}hr"``; otherwise ``"{N//24}day"``.
      Must divide evenly into days for the > 48 branch (raises otherwise —
      the encoding doesn't represent fractional days).
    - region_scope: looked up in ``_REGION_SCOPE_SLUG``.
    - Ordering: ``STATEWIDE`` is suffix-positioned (``{kind}-{deadline}-statewide``);
      specific regions sit between kind and deadline
      (``{kind}-{region}-{deadline}``).

    Raises ``RuntimeError`` if region_scope is unknown or deadline_hours
    doesn't fit the encoding's representable range.
    """
    kind_token = _KIND_SLUG_OVERRIDES.get(kind, kind).replace("_", "-")

    if deadline_hours <= 48:
        deadline_token = f"{deadline_hours}hr"
    elif deadline_hours % 24 == 0:
        deadline_token = f"{deadline_hours // 24}day"
    else:
        raise RuntimeError(
            f"deadline_hours={deadline_hours!r} not representable in the "
            f"slug encoding (must be <= 48 for hours form, or a multiple of "
            f"24 for days form); update _derive_expected_id_suffix() to "
            f"reflect a deliberate encoding extension"
        )

    region_token = _REGION_SCOPE_SLUG.get(region_scope)
    if region_token is None:
        raise RuntimeError(
            f"region_scope={region_scope!r} not in _REGION_SCOPE_SLUG; "
            f"expected one of {sorted(_REGION_SCOPE_SLUG.keys())!r}"
        )

    if region_scope == "STATEWIDE":
        return f"{kind_token}-{deadline_token}-{region_token}"
    return f"{kind_token}-{region_token}-{deadline_token}"


def _assert_dispatch_dict_drift_free(
    spec_dict: dict[tuple[str, str], _RowSpec],
) -> None:
    """Assert every entry's id_suffix matches its derived slug.

    Fires at module load to catch drift between ``_REPORTING_ROW_SPEC``'s
    hand-encoded ``id_suffix`` and the slug derivation implied by its
    ``kind``/``deadline_hours``/region_scope (the tuple-key element).

    Raises ``RuntimeError`` with a diagnostic naming the drifted entry.
    """
    for spec_key, spec in spec_dict.items():
        region_scope, _kind_hint = spec_key
        expected = _derive_expected_id_suffix(
            spec["kind"], spec["deadline_hours"], region_scope,
        )
        if spec["id_suffix"] != expected:
            raise RuntimeError(
                f"_REPORTING_ROW_SPEC drift detected for {spec_key!r}: "
                f"id_suffix={spec['id_suffix']!r} but slug derivation produces "
                f"{expected!r} from kind={spec['kind']!r}, "
                f"deadline_hours={spec['deadline_hours']!r}, "
                f"region_scope={region_scope!r}; either update id_suffix to "
                f"match or update _derive_expected_id_suffix() to reflect a "
                f"deliberate slug-encoding change. See Q19 in "
                f"docs/open-questions.md for the project-wide fix planned pre-M2."
            )


# V1 drift guard — see Q19 in docs/open-questions.md for the project-wide
# fix planned pre-M2.
_assert_dispatch_dict_drift_free(_REPORTING_ROW_SPEC)


# ---------------------------------------------------------------------------
# Stub functions (populated in T3/T4/T5)
# ---------------------------------------------------------------------------


def _build_reporting_obligations(bear_artifact: dict) -> list[ReportingObligation]:
    """Build the 3 ReportingObligation entity rows from the bear artifact.

    Reads the artifact's top-level ``reporting_obligations`` list and the
    ``sources`` list (for SourceCitation construction). For each entry, looks
    up the structured-field spec in ``_REPORTING_ROW_SPEC`` by
    ``(region_scope, kind_hint)`` and constructs a Pydantic ``ReportingObligation``.

    Raises ``RuntimeError`` (fail-loud, naming the bad value):
    - if ``reporting_obligations`` is missing or not a list
    - if ``sources`` is missing or not a list
    - if an entry's ``(region_scope, kind_hint)`` combo is not in the dispatch dict
    - if an entry's ``source_id`` is not in the sources list

    Pydantic validation (``frozen=True, extra="forbid"``, non-empty verbatim_rule)
    runs automatically at construction.

    Returns 3 ReportingObligation rows in source-list iteration order.
    """
    raw_obligations = bear_artifact.get("reporting_obligations")
    if not isinstance(raw_obligations, list):
        raise RuntimeError(
            f"bear artifact missing or invalid 'reporting_obligations' key "
            f"(expected list, got {type(raw_obligations).__name__}); "
            f"re-run extract_black_bear.py and inspect the artifact"
        )

    raw_sources = bear_artifact.get("sources")
    if not isinstance(raw_sources, list):
        raise RuntimeError(
            f"bear artifact missing or invalid 'sources' key "
            f"(expected list, got {type(raw_sources).__name__}); "
            f"re-run extract_black_bear.py and inspect the artifact"
        )

    # Build sources_by_id with per-element shape validation. Bare comprehension
    # `{s["id"]: s for s in raw_sources}` raises an opaque KeyError if any
    # source entry is missing the "id" key — wrap with explicit diagnostics so
    # operators can identify the malformed entry by index. Same fail-loud
    # discipline applied to `raw_rows` row entries in
    # _build_regulation_reporting_links.
    sources_by_id: dict[str, dict] = {}
    for source_index, source_entry in enumerate(raw_sources):
        if not isinstance(source_entry, dict):
            raise RuntimeError(
                f"bear artifact sources[{source_index}] is not a dict "
                f"(got {type(source_entry).__name__}); "
                f"re-run extract_black_bear.py and inspect the artifact"
            )
        try:
            entry_id = source_entry["id"]
        except KeyError as exc:
            raise RuntimeError(
                f"bear artifact sources[{source_index}] missing required key "
                f"{exc.args[0]!r}; entry keys present: "
                f"{sorted(source_entry.keys())!r}; "
                f"re-run extract_black_bear.py and inspect the artifact"
            ) from exc
        sources_by_id[entry_id] = source_entry
    if len(sources_by_id) != len(raw_sources):
        # ADR-001: silent overwrite of citation metadata would embed the wrong
        # authority URL in every downstream read. Fail loud on duplicate ids.
        raise RuntimeError(
            f"bear artifact 'sources' list contains duplicate ids: "
            f"{len(raw_sources)} entries collapsed to {len(sources_by_id)} unique; "
            f"re-run extract_black_bear.py and inspect the artifact"
        )

    result: list[ReportingObligation] = []
    for entry_index, entry in enumerate(raw_obligations):
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"bear artifact reporting_obligations[{entry_index}] is not a "
                f"dict (got {type(entry).__name__}); "
                f"re-run extract_black_bear.py and inspect the artifact"
            )
        try:
            region_scope = entry["region_scope"]
            kind_hint = entry["kind_hint"]
            source_id = entry["source_id"]
            page_reference = entry["page_reference"]
            verbatim_rule = entry["verbatim_rule"]
        except KeyError as exc:
            raise RuntimeError(
                f"bear artifact reporting_obligations[{entry_index}] missing "
                f"required key {exc.args[0]!r}; entry keys present: "
                f"{sorted(entry.keys())!r}; "
                f"re-run extract_black_bear.py and inspect the artifact"
            ) from exc
        spec_key = (region_scope, kind_hint)

        spec = _REPORTING_ROW_SPEC.get(spec_key)
        if spec is None:
            raise RuntimeError(
                f"unknown reporting_obligation combo {spec_key!r}; "
                f"expected one of {sorted(_REPORTING_ROW_SPEC.keys())!r}"
            )

        if source_id not in sources_by_id:
            raise RuntimeError(
                f"reporting_obligation entry references unknown source_id={source_id!r}; "
                f"artifact sources are {sorted(sources_by_id.keys())!r}"
            )
        source_dict = sources_by_id[source_id]
        page_ref_str = pdf.page_reference_to_str(page_reference)

        # Bare key access on source_dict would raise an opaque KeyError if the
        # source entry is missing a required SourceCitation field. Wrap with
        # explicit diagnostic naming the bad source_id + missing key. The
        # `supersedes` field is optional (defaults to None via .get).
        try:
            citation = SourceCitation(
                id=source_dict["id"],
                agency=source_dict["agency"],
                title=source_dict["title"],
                url=source_dict["url"],
                publication_date=source_dict["publication_date"],
                document_type=source_dict["document_type"],
                supersedes=source_dict.get("supersedes"),
                page_reference=page_ref_str,
            )
        except KeyError as exc:
            raise RuntimeError(
                f"bear artifact source entry id={source_id!r} missing required "
                f"key {exc.args[0]!r}; entry keys present: "
                f"{sorted(source_dict.keys())!r}; "
                f"re-run extract_black_bear.py and inspect the artifact"
            ) from exc

        obligation = ReportingObligation(
            id=f"{_ID_PREFIX}-{spec['id_suffix']}",
            kind=spec["kind"],
            deadline=spec["deadline"],
            deadline_hours=spec["deadline_hours"],
            submission_method=spec["submission_method"],
            submission_url=spec["submission_url"],
            submission_phone=spec["submission_phone"],
            applies_to_regions=spec["applies_to_regions"],
            what_to_present=spec["what_to_present"],
            verbatim_rule=verbatim_rule,
            source=citation,
        )
        result.append(obligation)

    if len(result) != _EXPECTED_REPORTING_OBLIGATION_COUNT:
        # Defensive fast-fail; the OQ7 guard in T5 is the formal check
        raise RuntimeError(
            f"expected {_EXPECTED_REPORTING_OBLIGATION_COUNT} reporting_obligation "
            f"rows from bear artifact, got {len(result)}; "
            f"if the source PDF changed, update _EXPECTED_REPORTING_OBLIGATION_COUNT "
            f"and the guard band, then verify the dispatch dict still covers all combos"
        )

    return result


def _build_regulation_reporting_links(
    reporting_obligations: list[ReportingObligation],
    bear_artifact: dict,
) -> list[RegulationReporting]:
    """Build the 70 RegulationReporting link rows via per-BMU hd_region lookup.

    Each of the 35 bear regulation_records (jurisdiction_code MT-HD-bear-<N>)
    gets 2 links:
    - STATEWIDE harvest_report (always — applies to every bear hunter)
    - region-specific inspection (R1 → tooth_submission; R2-7 → hide_skull_presentation)

    Total: 35 + 35 = 70 link rows.

    Link construction key invariants:
    - jurisdiction_code MUST be ``f"MT-HD-bear-{row['bmu_number']}"`` (must match
      load_regulation_records.py:366 byte-for-byte; deviation = silent FK miss
      because regulation_reporting INSERT uses ON CONFLICT DO NOTHING).
    - species_group is ``"bear"`` (DB value), NOT ``"black_bear"`` (the artifact's
      top-level field).

    Raises ``RuntimeError`` if:
    - any required key is missing from the obligation list (T3 regression)
    - bear_artifact['rows'] is missing or not a list
    - any bear row has an unknown hd_region (not in R1-R7)
    - the final row count != _EXPECTED_REGULATION_REPORTING_COUNT
    - any composite PK collides (indicates a duplicate bmu_number in the artifact)

    Returns 70 RegulationReporting rows in source-row iteration order
    (interleaved: STATEWIDE link then region-link per bear row).
    """
    # Step 1: Build obligation_by_id lookup and derive the 3 known IDs from the
    # dispatch dict (single source of truth — no hardcoded strings here)
    obligation_by_id: dict[str, ReportingObligation] = {ob.id: ob for ob in reporting_obligations}

    statewide_id = f"{_ID_PREFIX}-{_REPORTING_ROW_SPEC[('STATEWIDE', 'harvest_report')]['id_suffix']}"
    r1_id = f"{_ID_PREFIX}-{_REPORTING_ROW_SPEC[('R1', 'tooth_submission')]['id_suffix']}"
    r2to7_id = f"{_ID_PREFIX}-{_REPORTING_ROW_SPEC[('R2-7', 'hide_skull_presentation')]['id_suffix']}"

    # Fail loud if T3 didn't produce one of the 3 expected obligations
    missing_ids = {statewide_id, r1_id, r2to7_id} - set(obligation_by_id.keys())
    if missing_ids:
        raise RuntimeError(
            f"reporting_obligations list is missing expected ids {sorted(missing_ids)!r}; "
            f"got {sorted(obligation_by_id.keys())!r}"
        )

    # Step 2: Validate bear_artifact["rows"] shape
    raw_rows = bear_artifact.get("rows")
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            f"bear artifact missing or invalid 'rows' key "
            f"(expected list, got {type(raw_rows).__name__}); "
            f"re-run extract_black_bear.py and inspect the artifact"
        )

    # Step 3: Iterate bear rows and emit 2 links per row
    result: list[RegulationReporting] = []
    all_valid_regions = _R1_REGIONS | _R2_TO_R7_REGIONS

    for row_index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            # Type-check BEFORE the KeyError handler — the handler references
            # row.keys() in its diagnostic, which itself raises AttributeError
            # if row is a non-dict (e.g., a string or list from a corrupted
            # artifact). Fail loud with a descriptive message naming the index
            # + actual type before any indexing is attempted.
            raise RuntimeError(
                f"bear artifact rows[{row_index}] is not a dict "
                f"(got {type(row).__name__}); "
                f"re-run extract_black_bear.py and inspect the artifact"
            )
        try:
            bmu_number = row["bmu_number"]
            hd_region = row["hd_region"]
        except KeyError as exc:
            raise RuntimeError(
                f"bear artifact rows[{row_index}] missing required key {exc.args[0]!r}; "
                f"row keys present: {sorted(row.keys())!r}"
            ) from exc

        if hd_region not in all_valid_regions:
            raise RuntimeError(
                f"bear row bmu_number={bmu_number!r} has unknown hd_region={hd_region!r}; "
                f"expected one of {sorted(all_valid_regions)!r}"
            )

        # jurisdiction_code MUST match load_regulation_records.py:366 byte-for-byte
        jurisdiction_code = f"MT-HD-bear-{bmu_number}"

        # Every bear regulation_record gets the STATEWIDE harvest_report link
        result.append(RegulationReporting(
            state=_MT_STATE_CODE,
            jurisdiction_code=jurisdiction_code,
            species_group=_BEAR_SPECIES_GROUP,
            license_year=_LICENSE_YEAR,
            reporting_obligation_id=statewide_id,
        ))

        # R1 vs R2-7 inspection link
        if hd_region in _R1_REGIONS:
            region_obligation_id = r1_id
        else:
            region_obligation_id = r2to7_id

        result.append(RegulationReporting(
            state=_MT_STATE_CODE,
            jurisdiction_code=jurisdiction_code,
            species_group=_BEAR_SPECIES_GROUP,
            license_year=_LICENSE_YEAR,
            reporting_obligation_id=region_obligation_id,
        ))

    # Step 4: Post-condition checks (defensive — formal guard is in T5)
    if len(result) != _EXPECTED_REGULATION_REPORTING_COUNT:
        raise RuntimeError(
            f"expected {_EXPECTED_REGULATION_REPORTING_COUNT} regulation_reporting rows, "
            f"got {len(result)} (bear rows: {len(raw_rows)}); "
            f"the formula is 2 links per bear row (STATEWIDE + region-specific)"
        )

    # Composite-PK uniqueness guard (each BMU produces 2 distinct obligation_ids, so no dupes
    # possible unless the artifact has duplicate bmu_numbers — fail loud)
    seen_pks: set[tuple[str, str, str, int, str]] = set()
    for link in result:
        pk = (link.state, link.jurisdiction_code, link.species_group,
              link.license_year, link.reporting_obligation_id)
        if pk in seen_pks:
            raise RuntimeError(
                f"duplicate regulation_reporting composite PK {pk!r}; "
                f"check bear_artifact['rows'] for duplicate bmu_number entries"
            )
        seen_pks.add(pk)

    return result


def _assert_reporting_obligation_count_within_guard(written: int) -> None:
    """OQ7 row-count guard for reporting_obligation.

    Fires BEFORE db.connect() per S03.6/S03.7/S03.8 precedent. ±30% band
    around _EXPECTED_REPORTING_OBLIGATION_COUNT. Raises RuntimeError naming
    the band, the actual count, and a hint to update the expected count if
    the source PDF changed.
    """
    lo, hi = _REPORTING_OBLIGATION_COUNT_GUARD_BAND
    if written < lo or written > hi:
        raise RuntimeError(
            f"reporting_obligation row count {written} outside ±30% band [{lo}, {hi}] "
            f"(expected {_EXPECTED_REPORTING_OBLIGATION_COUNT}); "
            f"if the source PDF changed, update _EXPECTED_REPORTING_OBLIGATION_COUNT "
            f"and the guard band, then rerun. If unexpected, inspect "
            f"states/montana/extracted/black-bear-2026.json"
        )


def _assert_regulation_reporting_count_within_guard(written: int) -> None:
    """OQ7 row-count guard for regulation_reporting link table.

    Fires BEFORE db.connect() per S03.6/S03.7/S03.8 precedent. ±30% band
    around _EXPECTED_REGULATION_REPORTING_COUNT. Raises RuntimeError naming
    the band, the actual count, and a hint.
    """
    lo, hi = _REGULATION_REPORTING_COUNT_GUARD_BAND
    if written < lo or written > hi:
        raise RuntimeError(
            f"regulation_reporting row count {written} outside ±30% band [{lo}, {hi}] "
            f"(expected {_EXPECTED_REGULATION_REPORTING_COUNT}); "
            f"if the source PDF changed or bear row count drifted, update "
            f"_EXPECTED_REGULATION_REPORTING_COUNT and the guard band, then rerun. "
            f"If unexpected, inspect states/montana/extracted/black-bear-2026.json"
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Load Montana reporting_obligation + regulation_reporting rows "
            "from the merged Black Bear artifact. Atomic transaction."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Build rows + fire row-count guards but do NOT open a DB connection "
            "or write anything. Useful for CI/pre-commit sanity checks."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    """Configure root logging level and format."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point. Three-phase: build → guards → conn/loops/commit.

    Phase 0: parse args, configure logging.
    Phase 1 (build): load artifact, build entity rows + link rows.
    Phase 2 (guards): fire OQ7 row-count guards BEFORE opening DB connection.
    Phase 3 (dry-run short-circuit): if --dry-run, log + return 0.
    Phase 4 (write): open conn, upsert obligations, write links, commit.
                     On any exception, rollback, log, re-raise.
    """
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    # Phase 1 — build
    _LOGGER.info("loading bear artifact from %s", _BEAR_ARTIFACT_PATH)
    bear_artifact = json.loads(_BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))

    obligations = _build_reporting_obligations(bear_artifact)
    _LOGGER.info("built %d reporting_obligation rows", len(obligations))

    links = _build_regulation_reporting_links(obligations, bear_artifact)
    _LOGGER.info("built %d regulation_reporting link rows", len(links))

    # Phase 2 — OQ7 guards (BEFORE db.connect())
    _assert_reporting_obligation_count_within_guard(len(obligations))
    _assert_regulation_reporting_count_within_guard(len(links))
    _LOGGER.info("row-count guards passed")

    # Phase 3 — dry-run short-circuit
    if args.dry_run:
        _LOGGER.info(
            "DRY RUN — would write %d reporting_obligation rows + "
            "%d regulation_reporting rows; skipping DB connect",
            len(obligations),
            len(links),
        )
        return 0

    # Phase 4 — open conn, write, commit
    conn = db.connect()
    try:
        # Phase 4a — entity upserts
        for obligation in obligations:
            db.upsert_reporting_obligation(conn, obligation)
        _LOGGER.info("upserted %d reporting_obligation rows", len(obligations))

        # Phase 4b — link inserts
        for link in links:
            db.write_regulation_reporting(conn, link)
        _LOGGER.info("wrote %d regulation_reporting link rows", len(links))

        conn.commit()
        _LOGGER.info("committed S03.9 transaction")
    except Exception:
        conn.rollback()
        _LOGGER.exception("rolled back due to error")
        raise
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
