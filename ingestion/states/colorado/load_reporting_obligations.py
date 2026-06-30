"""Colorado reporting_obligation ingestion adapter.

Reads ``ingestion/states/colorado/extracted/black-bear-2026.json`` (the flat-
list CO bear artifact produced by S06.4) and writes exactly **1 STATEWIDE
``mandatory_check`` ``reporting_obligation`` row** (entity only — no
``regulation_reporting`` link rows written here; links are S06.10's job).

Group A / Group B split
-----------------------
Group A (build / dry-run):  satisfied at merge — loader code + mocked /
    dry-run tests compile and pass the count guard against the committed
    extraction artifact without DB connectivity.
Group B (operator-pending): live DB write depends on the outstanding E05
    operator geometry writes (CO geometry rows must exist in the target DB
    before S06.10's binding loader can FK to them).  Run once the E05
    Group B session and the S06.6 / S06.7 / S06.8 writes have landed.

S06.9 vs S06.10 scope boundary
--------------------------------
**S06.9 writes the reporting_obligation entity row ONLY.**
``regulation_reporting`` link rows (one per CO bear ``regulation_record``)
are S06.10's job.  This mirrors the MT split where S03.9 wrote the entity
rows and S03.10/load_regulation_records.py generated the link rows as part
of the binding sweep.

verbatim_rule limitation
-------------------------
The committed bear artifact (``extracted/black-bear-2026.json``) currently
carries a heading-only ``verbatim_rule`` for the reporting-obligation entry
(``"Mandatory Bear Inspections & Seals"``).  This loader consumes it
faithfully per ADR-008 (no fabrication, no paraphrase).  The full-prose
verbatim rule (brochure pp. 77–78 inspection + seal prose) is a separate
flagged ``extract_black_bear.py`` carve-out candidate (analogous to S06.3.1
for the big-game extractor) and is NOT addressed here.  S06.10 UAT should
note this limitation and flag the carve-out if the prose is load-bearing for
downstream queries.

Inputs
------
- ``ingestion/states/colorado/extracted/black-bear-2026.json``
  - flat list of dicts; each dict has a ``record_type`` discriminator.
  - ``record_type == "reporting_obligation"`` entries are the entity source.
  - ``sources`` field on each entry carries the SourceCitation dict inline
    (same flat-list structure as S06.4 / S06.6; no top-level ``sources``
    key, unlike the MT bear artifact).
- ``ingestion/states/colorado/sources.yaml``
  - used to resolve the ``co-cpw-big-game-2026-brochure`` citation when
    the artifact entry does not carry an inline ``sources`` dict (fallback).

Outputs (dry-run or live)
--------------------------
- **1 reporting_obligation row** written via UPSERT (idempotent).

Row 1 — STATEWIDE mandatory_check
    ``id``                ``co-bear-mandatory-check-5day-statewide``
    ``kind``              ``"mandatory_check"``
    ``deadline``          ``"5 working days"``
    ``deadline_hours``    ``120``
    ``submission_method`` ``"agency_office"``
    ``submission_url``    ``None``
    ``submission_phone``  ``None``
    ``applies_to_regions``  ``None``  (statewide — all CO bear records)
    ``what_to_present``   ``["bear head", "hide"]``

Cleanup rules
-------------
None.  ``verbatim_rule`` is preserved byte-faithful per ADR-008.  This
empty cleanup-rules statement is intentional and enforced by tests.

Confidence
----------
None.  ``reporting_obligation`` has no confidence column; child entities
inherit confidence from the parent ``regulation_record`` per ADR-017.

Transaction structure (three phases)
--------------------------------------
1. **Build** — construct the entity row entirely in memory from the bear
   artifact; all Pydantic validation fires here.
2. **Guards** — OQ7 row-count band fires BEFORE ``db.connect()``; any band
   violation raises ``RuntimeError`` so no partial write occurs.
3. **Conn open → upsert entity → commit**; rollback on any exception;
   close in finally.

State-agnostic posture
-----------------------
This adapter imports ONLY from ``ingestion.lib.*``.  It does NOT import from
any other state adapter (no cross-state or cross-Colorado-adapter imports).
Locked by ``TestNoLibImports`` in the test suite.

Invocation
----------
    ingestion/.venv/bin/python ingestion/states/colorado/load_reporting_obligations.py [--dry-run] [-v]

NOT ``python -m`` (state package is non-subpackage per S03.1 pitfall).

Required env: ``DATABASE_URL``.

Optional flags:
    ``--dry-run``   Build all records and run the count guard, but do not
                    write to the DB.  Useful for CI smoke-testing without DB
                    connectivity.
    ``-v``/``--verbose``  Enable DEBUG-level logging.

Relevant ADRs
-------------
- ADR-001: Authority preserved, not replaced (no invented field values).
- ADR-008: Verbatim discipline (verbatim_rule byte-faithful; no cleanup rules
  applied in this adapter; see verbatim_rule limitation note above).
- ADR-010: Decomposed entities (reporting_obligation as child entity of
  regulation_record; regulation_reporting links are S06.10's job).
- ADR-017: Confidence inheritance (reporting_obligation has no confidence
  column; confidence is the parent regulation_record's responsibility).
- ADR-020: Derive-and-assert id text-PK slug discipline (see module-level
  ``assert_dispatch_dict_drift_free`` call below; see also Q19 in
  docs/open-questions.md for the project-wide pre-M2 fix).
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from typing import Final, Literal, TypedDict

import yaml

from ingestion.lib import db, pdf
from ingestion.lib.drift_guard import assert_dispatch_dict_drift_free
from ingestion.lib.schema import ReportingObligation, SourceCitation


# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All CO loaders use ``_STATE``. The four geometry-era loaders (load_state_boundary,
# load_gmus, load_restricted_areas, build_overlay_fixture) were renamed from
# ``CO_STATE_CODE`` in S06.10 per S06.0/D3.
_STATE: Final[str] = "US-CO"

_LICENSE_YEAR: Final[int] = 2026

_BEAR_ARTIFACT_PATH: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parent / "extracted" / "black-bear-2026.json"
)

_SOURCES_YAML: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parent / "sources.yaml"
)

_ID_PREFIX: Final[str] = "co-bear"

_BIG_GAME_CITATION_ID: Final[str] = "co-cpw-big-game-2026-brochure"

_KNOWN_BEAR_RECORD_TYPES: Final[frozenset[str]] = frozenset(
    {"section", "statewide_rule", "reporting_obligation"}
)

_ALLOWED_DOCUMENT_TYPES: Final[frozenset[str]] = frozenset(
    {"annual_regulations", "correction"}
)

_EXPECTED_REPORTING_OBLIGATION_COUNT: Final[int] = 1

# Exact-match single-row band: (1, 1).
# Note: ±30% of 1 would yield (0, 1), which would admit a zero-write
# silently.  The single-row S03.6.1 pattern uses exact-match instead.
# This guard fires BEFORE db.connect() per OQ7 discipline.
_REPORTING_OBLIGATION_COUNT_GUARD_BAND: Final[tuple[int, int]] = (1, 1)


# ---------------------------------------------------------------------------
# Dispatch dictionary for reporting_obligation entity construction
# ---------------------------------------------------------------------------


class _RowSpec(TypedDict):
    """Structured-field values for a single reporting_obligation row.

    The dispatch dict maps (region_scope, kind_hint) tuples to these specs.
    All structured-field interpretation lives in the dispatch dict; the build
    function reads verbatim_rule + source from the artifact and applies the
    spec verbatim.  Locked values are in the S06.9 closure note at
    docs/planning/epics/E06-confidence-findings/S06.9.md; drift-guard
    discipline is encoded via the module-level
    ``assert_dispatch_dict_drift_free`` call (imported from
    ``ingestion.lib.drift_guard``; see ADR-020).
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
    ("STATEWIDE", "mandatory_inspection"): {
        "id_suffix": "mandatory-check-5day-statewide",
        "kind": "mandatory_check",
        "deadline": "5 working days",
        "deadline_hours": 120,
        "submission_method": "agency_office",
        "submission_url": None,
        "submission_phone": None,
        "applies_to_regions": None,
        "what_to_present": ["bear head", "hide"],
    },
}


# ---------------------------------------------------------------------------
# Slug-override and region-scope lookup tables
# ---------------------------------------------------------------------------

# CO's one kind (mandatory_check) slugs cleanly to "mandatory-check" via
# the default _.replace("_", "-") path — no override needed.  Future verbose
# kinds (e.g., hide_skull_presentation → "hide-skull") get an entry here.
_KIND_SLUG_OVERRIDES: Final[dict[str, str]] = {}

_REGION_SCOPE_SLUG: Final[dict[str, str]] = {"STATEWIDE": "statewide"}

# Known heading-only verbatim_rule from the current committed artifact. The
# full inspection prose is pending an extract_black_bear.py carve-out (the
# END-anchor matched early in the multi-column layout). Surfaced at WARNING
# so an operator running the live loader sees the gap. See the module
# docstring "verbatim_rule limitation" note.
_KNOWN_HEADING_ONLY_VERBATIM: Final[str] = "Mandatory Bear Inspections & Seals"


# ---------------------------------------------------------------------------
# Pure id-derivation function (copied verbatim from MT precedent)
# ---------------------------------------------------------------------------


def _derive_expected_id_suffix(
    kind: str, deadline_hours: int, region_scope: str,
) -> str:
    """Derive the canonical id_suffix from the slug-encoded fields.

    Mirrors the encoding currently locked in ``_REPORTING_ROW_SPEC``:

    - kind: ``_`` → ``-``; verbose kinds consult ``_KIND_SLUG_OVERRIDES``
      for shortened forms.
    - deadline_hours: ``<= 48`` → ``"{N}hr"``; otherwise ``"{N//24}day"``.
      Must divide evenly into days for the > 48 branch (raises otherwise —
      the encoding doesn't represent fractional days).
    - region_scope: looked up in ``_REGION_SCOPE_SLUG``.
    - Ordering: ``STATEWIDE`` is suffix-positioned
      (``{kind}-{deadline}-statewide``); specific regions sit between kind
      and deadline (``{kind}-{region}-{deadline}``).

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


# ---------------------------------------------------------------------------
# Drift guard for _REPORTING_ROW_SPEC's id_suffix encoding (ADR-020)
# ---------------------------------------------------------------------------
#
# The reporting_obligation.id is hand-encoded as a slug that bakes in kind,
# deadline_hours, and region_scope (e.g., "co-bear-mandatory-check-5day-
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
# guarding against here at module load.  This guard is S06.9-LOCAL — see Q19
# in docs/open-questions.md for the project-wide fix planned pre-M2, which
# will generalize the pattern across season_definition + license_tag +
# reporting_obligation.

assert_dispatch_dict_drift_free(
    _REPORTING_ROW_SPEC,
    lambda key, entry: _derive_expected_id_suffix(
        entry["kind"], entry["deadline_hours"], key[0],  # key[0] is region_scope
    ),
    helper_name="_REPORTING_ROW_SPEC",
    id_field="id_suffix",
)


# ---------------------------------------------------------------------------
# Citation loader
# ---------------------------------------------------------------------------


def _load_citation_from_sources_yaml(
    citation_id: str, *, page_reference: str | None = None
) -> SourceCitation:
    """Load a single SourceCitation entry from sources.yaml by id.

    Returns a fully-constructed ``schema.SourceCitation`` Pydantic instance
    (frozen). Pydantic validates every field, including the
    ``document_type`` Literal and the ``publication_date`` string.

    The optional ``page_reference`` keyword argument is threaded into the
    ``SourceCitation`` constructor so callers can attach a per-row page
    reference (e.g. ``"co-cpw-big-game-2026-brochure-2026-03-04.pdf:p73"``).

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
            page_reference=page_reference,
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
# Reporting obligation builder
# ---------------------------------------------------------------------------


def _build_reporting_obligations(
    bear_artifact: list[dict],  # type: ignore[type-arg]
) -> list[ReportingObligation]:
    """Build ReportingObligation entity rows from the CO bear flat-list artifact.

    CO artifact structure differs from MT:
    - CO is a **flat list** of dicts, each with a ``record_type`` discriminator.
    - MT is a dict with a top-level ``reporting_obligations`` list and a
      ``sources`` list.

    This function filters the flat list to entries where
    ``record_type == "reporting_obligation"``, then constructs Pydantic
    ``ReportingObligation`` rows via the ``_REPORTING_ROW_SPEC`` dispatch dict.

    Fail-loud disciplines:
    - Non-dict entry → RuntimeError naming index + actual type.
    - Missing ``record_type`` key → RuntimeError naming index + present keys.
    - Unknown ``record_type`` value → RuntimeError naming index + known types
      (catches misspellings like ``"Reporting_Obligation"``).
    - Unknown ``(region_scope, kind_hint)`` combo → RuntimeError naming the
      combo + all known keys in ``_REPORTING_ROW_SPEC``.
    - ``source_id`` does not match ``_BIG_GAME_CITATION_ID`` → RuntimeError.
    - Missing required keys in the obligation entry → RuntimeError naming the
      missing key + present keys.
    - Duplicate ``id`` values in the built result → RuntimeError (two artifact
      entries mapping to the same dispatch key would silently overwrite each
      other via ``ON CONFLICT (id) DO UPDATE`` in
      ``db.upsert_reporting_obligation``).

    NOTE: no in-builder exact-count check. The OQ7 count guard in ``main()``
    is the canonical count authority (S03.9 / MT cubic-review-round-6 lesson:
    an in-builder exact-count check wrongly rejects in-band drift before the
    OQ7 guard can evaluate).

    Returns obligation rows in artifact iteration order.
    Writes the obligation **entity** only — ``regulation_reporting`` link rows
    are S06.10's job.
    """
    # Fix 4: fail loud if the artifact is not a list (catches callers that pass
    # the wrong value, e.g. a dict from json.loads on a non-array JSON file).
    if not isinstance(bear_artifact, list):
        raise RuntimeError(
            f"CO bear artifact must be a JSON list (got "
            f"{type(bear_artifact).__name__}); re-run extract_black_bear.py and "
            f"inspect states/colorado/extracted/black-bear-2026.json"
        )

    result: list[ReportingObligation] = []
    for idx, entry in enumerate(bear_artifact):
        # --- record-type validation + filter (mirror _build_co_bear_records) ---
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"bear artifact[{idx}] is not a dict "
                f"(got {type(entry).__name__}); "
                "re-run extract_black_bear.py and inspect the artifact"
            )
        if "record_type" not in entry:
            raise RuntimeError(
                f"bear artifact[{idx}] is missing the 'record_type' key; "
                f"keys present: {sorted(entry.keys())!r}; "
                "re-run extract_black_bear.py and inspect the artifact"
            )
        if entry["record_type"] not in _KNOWN_BEAR_RECORD_TYPES:
            raise RuntimeError(
                f"bear artifact[{idx}] has unknown "
                f"record_type={entry['record_type']!r}; "
                f"known types: {sorted(_KNOWN_BEAR_RECORD_TYPES)!r}; "
                "this may be a misspelling — "
                "re-run extract_black_bear.py and inspect the artifact"
            )
        if entry["record_type"] != "reporting_obligation":
            continue

        # --- extract required keys from the filtered entry ---
        try:
            region_scope = entry["region_scope"]
            kind_hint = entry["kind_hint"]
            source_id = entry["source_id"]
            page_reference = entry["page_reference"]
            verbatim_rule = entry["verbatim_rule"]
        except KeyError as exc:
            raise RuntimeError(
                f"bear artifact reporting_obligation entry[{idx}] missing "
                f"required key {exc.args[0]!r}; "
                f"entry keys present: {sorted(entry.keys())!r}; "
                "re-run extract_black_bear.py and inspect the artifact"
            ) from exc

        # --- dispatch lookup ---
        spec_key = (region_scope, kind_hint)
        spec = _REPORTING_ROW_SPEC.get(spec_key)
        if spec is None:
            raise RuntimeError(
                f"bear artifact reporting_obligation entry[{idx}] has unknown "
                f"combo (region_scope={region_scope!r}, kind_hint={kind_hint!r}); "
                f"expected one of {sorted(_REPORTING_ROW_SPEC.keys())!r}"
            )

        # --- source_id guard ---
        if source_id != _BIG_GAME_CITATION_ID:
            raise RuntimeError(
                f"bear artifact reporting_obligation entry[{idx}] has "
                f"source_id={source_id!r}; expected {_BIG_GAME_CITATION_ID!r}"
            )

        # --- Fix 3: source-of-truth cross-check on deadline_hint ---
        # The artifact's deadline_hint must agree with the spec's authoritative
        # deadline. The spec is the authority for the typed fields; if a future
        # extraction changes the published deadline, this fails loud rather than
        # silently writing the stale spec value. Skipped when the artifact omits
        # deadline_hint (older/other extraction shapes).
        deadline_hint = entry.get("deadline_hint")
        if deadline_hint is not None and deadline_hint != spec["deadline"]:
            raise RuntimeError(
                f"reporting_obligation entry deadline_hint={deadline_hint!r} disagrees "
                f"with spec deadline={spec['deadline']!r} for combo {spec_key!r}; "
                f"update _REPORTING_ROW_SPEC if the published deadline changed, or "
                f"re-run extract_black_bear.py and inspect the artifact"
            )

        # --- construct per-row citation with page reference threaded in ---
        page_ref_str = pdf.page_reference_to_str(page_reference)
        citation = _load_citation_from_sources_yaml(
            _BIG_GAME_CITATION_ID, page_reference=page_ref_str
        )

        # --- Fix 2: assert document_type on the citation that is actually written ---
        # (moved from the pre-loop citation_base check so it runs on the real
        # per-row citation, consistent with the doc-type guard discipline used
        # in load_regulation_records.py)
        _assert_document_type_allowed(citation)

        # --- construct entity row (Pydantic frozen/extra=forbid validates) ---
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

        # --- Fix 5: warn when verbatim_rule is the known heading-only value ---
        if obligation.verbatim_rule == _KNOWN_HEADING_ONLY_VERBATIM:
            _LOGGER.warning(
                "reporting_obligation id=%s has a heading-only verbatim_rule (%r); "
                "the full inspection prose is pending an extract_black_bear.py "
                "carve-out — see module docstring",
                obligation.id, obligation.verbatim_rule,
            )

        result.append(obligation)

    # --- duplicate-id guard ---
    # Two artifact entries that collapse to the same dispatch key would produce
    # two ReportingObligation rows with identical `id`s. At DB write time,
    # db.upsert_reporting_obligation's ON CONFLICT (id) DO UPDATE would
    # silently overwrite the first row with the second — corrupting data.
    # Fail loud here at build time, before any write attempt.
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for obligation in result:
        if obligation.id in seen_ids:
            duplicate_ids.add(obligation.id)
        seen_ids.add(obligation.id)
    if duplicate_ids:
        raise RuntimeError(
            f"_build_reporting_obligations produced duplicate ReportingObligation "
            f"ids: {sorted(duplicate_ids)!r}; two artifact entries mapped to the "
            f"same (region_scope, kind_hint) dispatch key, which would silently "
            f"overwrite each other via ON CONFLICT (id) DO UPDATE in "
            f"db.upsert_reporting_obligation. "
            "Re-run extract_black_bear.py and inspect the artifact."
        )

    # --- Fix 6: warn when zero obligations were built ---
    if not result:
        _LOGGER.warning(
            "_build_reporting_obligations produced 0 rows from %d artifact entries; "
            "the count guard will reject this — check for a misspelled record_type "
            "or a removed reporting_obligation entry in "
            "states/colorado/extracted/black-bear-2026.json",
            len(bear_artifact),
        )

    return result


# ---------------------------------------------------------------------------
# OQ7 row-count guard
# ---------------------------------------------------------------------------


def _assert_reporting_obligation_count_within_guard(written: int) -> None:
    """OQ7 row-count guard for reporting_obligation.

    Fires BEFORE db.connect() per OQ7 discipline (S03.6/S03.7/S03.8/S03.9
    precedent). The band is exact-match ``(1, 1)`` — ±30% of 1 would yield
    ``(0, 1)``, which would silently admit a zero-write. The single-row
    S03.6.1 pattern uses an exact-match band instead.

    Raises ``RuntimeError`` naming:
    - the guard band ``[lo, hi]``
    - the actual count
    - the expected count ``_EXPECTED_REPORTING_OBLIGATION_COUNT``
    - a hint to inspect ``states/colorado/extracted/black-bear-2026.json``
      if the source changed
    """
    lo, hi = _REPORTING_OBLIGATION_COUNT_GUARD_BAND
    if written < lo or written > hi:
        raise RuntimeError(
            f"reporting_obligation row count {written} outside band [{lo}, {hi}] "
            f"(expected {_EXPECTED_REPORTING_OBLIGATION_COUNT}); "
            f"if the source PDF changed, update _EXPECTED_REPORTING_OBLIGATION_COUNT "
            f"and the guard band, then rerun. If unexpected, inspect "
            f"states/colorado/extracted/black-bear-2026.json"
        )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for the CO reporting_obligation loader."""
    parser = argparse.ArgumentParser(
        description=(
            "Load Colorado reporting_obligation entity rows from the merged "
            "Black Bear artifact. Entity only — regulation_reporting link rows "
            "are S06.10's job."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Build rows + fire the count guard but do NOT open a DB connection "
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point. Three-phase: build → guard → conn/upsert/commit.

    Phase 0: parse args, configure logging.
    Phase 1 (build): load bear artifact, build entity rows.
    Phase 2 (guard): fire OQ7 row-count guard BEFORE opening DB connection.
    Phase 3 (dry-run short-circuit): if --dry-run, log + return 0.
    Phase 4 (write): open conn, upsert obligations, commit.
                     On any exception, rollback, log, re-raise.
    """
    # Phase 0 — parse + configure
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    # Phase 1 — build
    _LOGGER.info("loading bear artifact from %s", _BEAR_ARTIFACT_PATH)
    bear_artifact: list[dict] = json.loads(  # type: ignore[type-arg]
        _BEAR_ARTIFACT_PATH.read_text(encoding="utf-8")
    )
    obligations = _build_reporting_obligations(bear_artifact)
    _LOGGER.info("built %d reporting_obligation rows", len(obligations))

    # Phase 2 — OQ7 guard (BEFORE db.connect())
    _assert_reporting_obligation_count_within_guard(len(obligations))
    _LOGGER.info("row-count guard passed")

    # Phase 3 — dry-run short-circuit
    if args.dry_run:
        _LOGGER.info(
            "DRY RUN — would write %d reporting_obligation rows; skipping DB connect",
            len(obligations),
        )
        return 0

    # Phase 4 — open conn, upsert entities, commit
    conn = db.connect()
    try:
        for obligation in obligations:
            db.upsert_reporting_obligation(conn, obligation)
        _LOGGER.info("upserted %d reporting_obligation rows", len(obligations))

        conn.commit()
        _LOGGER.info("committed S06.9 transaction")
    except Exception:
        conn.rollback()
        _LOGGER.exception("rolled back due to error")
        raise
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
