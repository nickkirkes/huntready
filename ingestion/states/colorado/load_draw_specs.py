"""Colorado ``draw_spec`` ingestion adapter (S06.8).

Reads three committed artifacts:

* ``extracted/draw-mechanics-2026.json`` — S06.8.0 artifact; hybrid hunt-code
  list, point-only codes, application deadlines, NR-allocation caps, and hybrid
  pool mechanics.
* ``extracted/big-game-2026.json`` — S06.3/S06.3.1 artifact; per-unit deer /
  elk / pronghorn rows with ``list_value`` OTC discriminator.
* ``extracted/black-bear-2026.json`` — S06.4 artifact; per-unit bear rows with
  section-level ``license_kind`` OTC discriminator.

Writes one ``draw_spec`` row per unique limited-draw CPW hunt code, then
backfills ``license_tag.draw_spec_key`` for every ``(license_tag_id,
hunt_code)`` pair (ADR-012 soft-FK).

Three-phase shape (canonical per AC #969)
-----------------------------------------
Phase 1 — Build (no DB):
    Load artifacts; validate constants against artifact; derive the hybrid-code
    frozenset, point-only-code map, application deadline, and SourceCitation;
    walk both artifacts to build ``draw_specs_by_hunt_code`` and
    ``backfill_targets``.

Phase 2 — Guards (pre-``db.connect()``):
    Cross-listing consistency validator; orphan + malformed WARNING surface;
    row-count guard.  ALL guards fire BEFORE any DB connection opens (OQ7
    discipline).  ``--dry-run`` short-circuits here.

Phase 3 — Write (atomic):
    ``db.upsert_draw_spec`` for all draw_specs, then
    ``db.update_license_tag_draw_spec_key`` for all backfill targets, single
    ``conn.commit()``.

Deviation from MT analog (no Phase-1 license_tag re-upsert)
------------------------------------------------------------
MT's ``load_draw_specs.py`` has a Phase-1 license_tag re-upsert to correct OTC
mis-classification from its ``apply_by``-heuristic.  CO needs NO such re-upsert
— CO's kind classification is already correct at S06.7 from ``list_value`` /
section ``license_kind``.  So the write phase here is just: upsert draw_specs →
backfill ``draw_spec_key`` → single commit.

AC #980 satisfaction note
--------------------------
AC #980 "OTC discriminator via apply_by inspection" is satisfied by the
``list_value`` / section ``license_kind`` discriminator — ``apply_by`` is null
on all 2026 CO rows (verified at ``load_seasons_and_licenses.py:535``); the
discriminator field differs from MT, but the discipline (OTC rows get no
draw_spec) is identical.

Constants are derive-and-asserted from the artifact
----------------------------------------------------
The six named ``Final`` constants (``_HYBRID_RANDOM_POOL_MIN_POINTS``,
``_HYBRID_PREFERENCE_POOL_SHARE``, ``_HYBRID_RANDOM_POOL_SHARE``,
``_HYBRID_ELIGIBILITY_POINT_LINE``, ``_HIGH_DEMAND_NR_CAP``,
``_STANDARD_NR_CAP``) are the single source of truth for all pool / residency-
cap construction.  ``_validate_artifact_constants`` asserts them against the
artifact's ``hybrid_mechanics`` and ``nr_allocation`` records at runtime;
any mismatch raises ``ColoradoDrawSpecError`` immediately.

WARNING surfaces (visibility-only; documented upstream residuals)
-----------------------------------------------------------------
* 3 malformed `` +``-suffixed bear GMU-851 hunt codes (``B-E-851-O1-M +``,
  ``B-E-851-O2-R +``, ``B-E-851-O5-R +``) — skipped with WARNING in the build
  walk; a malformed string as the ``hunt_code`` PRIMARY KEY would be
  un-lookupable in the serving DB.  Root cause: ``extract_black_bear.py``
  row-fusion residual (ADR-022: extractors own extraction; the loader skips to
  protect PK integrity without silently cleaning).
* 3 orphan hybrid codes (``B-E-851-O1-R``, ``B-E-851-O2-R``,
  ``B-E-851-O5-R``) — in the hybrid set but matching no clean limited-draw
  draw_spec.  Reported via ``_report_orphan_hybrid_codes`` WARNING.
* ``load_seasons_and_licenses.py`` GMU 020 elk archery skip — the one big-game
  row with an empty ``hunt_code``; skipped here with WARNING (mirror of S06.6).

``drift_guard`` deliberately NOT imported
-----------------------------------------
``draw_spec`` uses a composite PK ``(state, hunt_code, year)`` rather than an
id-text PK, so there is no slug-drift risk at the UPSERT layer.  ADR-020's
derive-and-assert discipline applies only to id-text-PK entities.  An AST test
(``TestNoDriftGuardImport``) enforces this property going forward.

``parameters`` — Q12 not fired
--------------------------------
Zero 2026 CO hunt codes require a ``parameters`` value.  ``parameters=None``
on every row.

``successor_hunt_code_key`` — all primary phase
------------------------------------------------
The draw-mechanics artifact carries no successor/leftover data.  All rows:
``draw_phase="primary"``, ``successor_hunt_code_key=None``.

Q17 (per-GMU caps) — not fired
--------------------------------
Zero limited-draw rows in the 2026 artifact carry a non-null ``quota`` value,
so the cross-listing consistency validator never raises.  It is implemented
defensively.

Run from the repo root::

    ingestion/.venv/bin/python ingestion/states/colorado/load_draw_specs.py --dry-run

Required env: ``DATABASE_URL`` (not needed for ``--dry-run``).
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import math
import re
import sys
from pathlib import Path
from typing import Final, Literal

from ingestion.lib import db
from ingestion.lib.schema import (
    AllocationPool,
    AllocationPoolEligibility,
    ChoiceConfig,
    DrawSpec,
    DrawSpecKey,
    PointSystem,
    ResidencyCap,
    SourceCitation,
)
from states.colorado.load_regulation_records import _STATE  # type: ignore[import-untyped]
from states.colorado.load_seasons_and_licenses import (  # type: ignore[import-untyped]
    _BIG_GAME_CITATION_ID,
    _LICENSE_YEAR,
    _co_bear_license_kind,
    _co_big_game_license_kind,
    _co_license_tag_id,
    _load_citation_from_sources_yaml,
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------

_COLORADO_DIR: Final[Path] = Path(__file__).resolve().parent
_EXTRACTED_DIR: Final[Path] = _COLORADO_DIR / "extracted"
_DRAW_MECHANICS_ARTIFACT_PATH: Final[Path] = _EXTRACTED_DIR / "draw-mechanics-2026.json"
_BIG_GAME_ARTIFACT_PATH: Final[Path] = _EXTRACTED_DIR / "big-game-2026.json"
_BLACK_BEAR_ARTIFACT_PATH: Final[Path] = _EXTRACTED_DIR / "black-bear-2026.json"


# ---------------------------------------------------------------------------
# Named module-level constants (AC #972 — single source of truth)
#
# These administrative parameters are derive-and-asserted against the artifact
# at runtime via _validate_artifact_constants().  No inline literals for these
# values appear anywhere else in this module.
# ---------------------------------------------------------------------------

_HYBRID_RANDOM_POOL_MIN_POINTS: Final[int] = 5
_HYBRID_PREFERENCE_POOL_SHARE: Final[float] = 0.80
_HYBRID_RANDOM_POOL_SHARE: Final[float] = 0.20
# _HYBRID_ELIGIBILITY_POINT_LINE is a VALIDATE-ONLY constant — a drift guard
# asserted by _validate_artifact_constants against the artifact's
# nr_allocation.high_demand_threshold_points (both 6).  It is intentionally
# NOT consumed in AllocationPoolEligibility construction — the hybrid-vs-non-
# hybrid decision is made UPSTREAM by extract_draw_mechanics.py which classified
# codes into hybrid_code records.  Its equality with high_demand_threshold_points
# is intentional per S06.8 spec L928/L934: "the same upstream brochure-side
# determination drives BOTH the 80/20 pool split AND the 20%/25% residency cap."
# Do NOT remove the assert in _validate_artifact_constants.
_HYBRID_ELIGIBILITY_POINT_LINE: Final[int] = 6
_HIGH_DEMAND_NR_CAP: Final[float] = 0.20   # hybrid residency cap
_STANDARD_NR_CAP: Final[float] = 0.25      # non-hybrid residency cap

_DRAW_PHASE: Final[Literal["primary"]] = "primary"
_CHOICES: Final[ChoiceConfig] = ChoiceConfig(count=4, points_used_in_choices=[1])
_PARAMETERS: None = None

# Row-count fail-loud guard (OQ7 — fires BEFORE db.connect()).
# Baseline: 1914 unique limited-draw hunt codes (113 hybrid / 1801 non-hybrid).
# 3 malformed ` +`-suffixed bear GMU-851 codes are skipped with WARNING in the
# build walk (fix #1); the baseline dropped 1917 → 1914 as a result.
# Band: ±30% via int() truncation → [1339, 2488].
_EXPECTED_DRAW_SPEC_COUNT: Final[int] = 1914
_COUNT_GUARD_MIN_RATIO: Final[float] = 0.7
_COUNT_GUARD_MAX_RATIO: Final[float] = 1.3

# Regex that a well-formed CPW hunt code must match.
# Examples of clean codes:  D-M-001-O1-A  E-F-214-W4-R  B-E-851-O1-M
# Examples of malformed:    B-E-851-O1-M + (space-plus suffix from row-fusion)
_CLEAN_HUNT_CODE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Z]-[A-Z]-\d{3,4}-[A-Z0-9]{2}-[A-Z]$"
)

# Known cross-listing structural-field overrides.
# Format: (hunt_code, year) → {"quota": int | None, "rationale": str}
# Q17 STOP guard: any PK with ≥2 distinct non-null quotas NOT present here
# raises ColoradoDrawSpecError (flag-and-discuss).  Empty in 2026 — no quota
# conflicts observed in the current artifact.
_KNOWN_CROSS_LISTING_OVERRIDES: dict[tuple[str, int], dict[str, object]] = {}

__all__ = ["main"]


# ---------------------------------------------------------------------------
# Module error type
# ---------------------------------------------------------------------------


class ColoradoDrawSpecError(RuntimeError):
    """Raised on any unrecoverable data-integrity or artifact error."""


# ---------------------------------------------------------------------------
# T2: Artifact loaders + derive-and-assert constant validator
# ---------------------------------------------------------------------------


def _load_json_artifact(path: Path) -> object:
    """Load a JSON artifact from *path*.

    Raises:
        ColoradoDrawSpecError: if the file is missing, unreadable, or not
            valid JSON.
    """
    try:
        with path.open() as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ColoradoDrawSpecError(
            f"artifact not found: {path}; "
            "check that the extraction step has been run"
        ) from None
    except json.JSONDecodeError as exc:
        raise ColoradoDrawSpecError(
            f"artifact at {path} is not valid JSON: {exc}"
        ) from exc
    if not data:
        raise ColoradoDrawSpecError(
            f"artifact at {path} is empty; re-run the extractor"
        )
    return data


def _load_section_artifact(path: Path) -> list[dict]:
    """Load a section-records artifact (big-game or bear) from *path*.

    Shared loader for JSON arrays of section-record dicts.  Centralises the
    input contract so a future validation change lands in one place.

    Raises:
        ColoradoDrawSpecError: if the file is missing, unreadable, not valid
            JSON, not a list, or empty.
    """
    data = _load_json_artifact(path)
    if not isinstance(data, list):
        raise ColoradoDrawSpecError(
            f"section artifact at {path} is not a JSON array "
            f"(got {type(data).__name__})"
        )
    if not data:
        raise ColoradoDrawSpecError(
            f"section artifact at {path} is an empty list; re-run the extractor"
        )
    return data  # type: ignore[return-value]


def _load_draw_mechanics(path: Path) -> list[dict]:
    """Load and validate the draw-mechanics artifact."""
    data = _load_json_artifact(path)
    if not isinstance(data, list):
        raise ColoradoDrawSpecError(
            f"draw-mechanics artifact at {path} is not a JSON array "
            f"(got {type(data).__name__})"
        )
    if not data:
        raise ColoradoDrawSpecError(
            f"draw-mechanics artifact at {path} is an empty list"
        )
    return data  # type: ignore[return-value]


def _build_hybrid_code_set(mechanics: list[dict]) -> frozenset[str]:
    """Build the frozenset of hybrid hunt codes from the mechanics artifact.

    Raises:
        ColoradoDrawSpecError: if the artifact contains zero hybrid_code
            records (indicates artifact drift or wrong artifact), or if any
            ``hybrid_code`` record is missing the ``hunt_code`` field.
    """
    codes: set[str] = set()
    for i, r in enumerate(mechanics):
        if r.get("record_type") != "hybrid_code":
            continue
        try:
            codes.add(r["hunt_code"])
        except KeyError:
            raise ColoradoDrawSpecError(
                f"_build_hybrid_code_set: record #{i} has record_type='hybrid_code' "
                f"but is missing the 'hunt_code' field; "
                f"present keys: {sorted(r.keys())}; "
                "re-run extract_draw_mechanics.py"
            ) from None
    if not codes:
        raise ColoradoDrawSpecError(
            "draw-mechanics artifact contains zero 'hybrid_code' records; "
            "artifact drift or wrong file — re-run extract_draw_mechanics.py"
        )
    return frozenset(codes)


def _extract_single_record(mechanics: list[dict], record_type: str) -> dict:
    """Find exactly one record of *record_type* in *mechanics*.

    Raises:
        ColoradoDrawSpecError: if the count is not exactly 1.
    """
    matches = [r for r in mechanics if r.get("record_type") == record_type]
    if len(matches) != 1:
        raise ColoradoDrawSpecError(
            f"expected exactly 1 record with record_type={record_type!r} in "
            f"draw-mechanics artifact; found {len(matches)}"
        )
    return matches[0]


def _build_point_only_code_by_species_letter(mechanics: list[dict]) -> dict[str, str]:
    """Map species first-letter → point-only hunt code.

    E.g. ``{"B": "B-P-999-99-P", "D": "D-P-999-99-P", ...}``.

    Raises:
        ColoradoDrawSpecError: if any of the 4 V1 species letters {A, B, D, E}
            is missing from the artifact.
    """
    by_letter: dict[str, str] = {}
    for i, r in enumerate(mechanics):
        if r.get("record_type") != "point_only_code":
            continue
        try:
            hunt_code: str = r["hunt_code"]
        except KeyError:
            raise ColoradoDrawSpecError(
                f"_build_point_only_code_by_species_letter: record #{i} has "
                f"record_type='point_only_code' but is missing the 'hunt_code' field; "
                f"present keys: {sorted(r.keys())}; "
                "re-run extract_draw_mechanics.py"
            ) from None
        if not hunt_code:
            raise ColoradoDrawSpecError(
                f"_build_point_only_code_by_species_letter: record #{i} has "
                f"an empty 'hunt_code' value; cannot derive species letter"
            )
        letter = hunt_code[0]
        if letter in by_letter and by_letter[letter] != hunt_code:
            raise ColoradoDrawSpecError(
                f"_build_point_only_code_by_species_letter: duplicate species letter "
                f"{letter!r} with conflicting hunt codes: "
                f"existing={by_letter[letter]!r}, new={hunt_code!r}; "
                "artifact has two conflicting point_only_code records for this species — "
                "re-run extract_draw_mechanics.py or investigate the draw-mechanics artifact"
            )
        by_letter[letter] = hunt_code

    required = {"A", "B", "D", "E"}
    missing = required - set(by_letter.keys())
    if missing:
        raise ColoradoDrawSpecError(
            f"draw-mechanics artifact is missing point_only_code records for "
            f"species letters {sorted(missing)}; V1 expects all of {sorted(required)}"
        )
    return by_letter


def _validate_artifact_constants(mechanics: list[dict]) -> None:
    """Assert that module-level named constants match the artifact values.

    This is the S03.8 "defensive safety-net lookup" pattern applied to the
    CO draw-mechanics artifact.  Any mismatch means the artifact was re-
    extracted with different brochure values and the constants here need a
    human review before the loader runs.

    Raises:
        ColoradoDrawSpecError: naming the field + expected vs found.
    """
    hybrid_mech = _extract_single_record(mechanics, "hybrid_mechanics")
    nr_alloc = _extract_single_record(mechanics, "nr_allocation")

    checks: list[tuple[str, object, object, bool]] = [
        # (field_name, expected, found, use_isclose)
        (
            "hybrid_mechanics.min_preference_points",
            _HYBRID_RANDOM_POOL_MIN_POINTS,
            hybrid_mech.get("min_preference_points"),
            False,
        ),
        (
            "hybrid_mechanics.random_pool_share",
            _HYBRID_RANDOM_POOL_SHARE,
            hybrid_mech.get("random_pool_share"),
            True,
        ),
        (
            "nr_allocation.high_demand_nr_cap",
            _HIGH_DEMAND_NR_CAP,
            nr_alloc.get("high_demand_nr_cap"),
            True,
        ),
        (
            "nr_allocation.standard_nr_cap",
            _STANDARD_NR_CAP,
            nr_alloc.get("standard_nr_cap"),
            True,
        ),
        (
            # _HYBRID_ELIGIBILITY_POINT_LINE is validate-only (drift guard).
            # Its equality with high_demand_threshold_points (both 6) is
            # intentional per S06.8 spec L928/L934 — the same upstream
            # brochure-side determination drives BOTH the hybrid classification
            # AND the 20%/25% residency-cap coupling.  Do NOT remove this assert.
            "nr_allocation.high_demand_threshold_points",
            _HYBRID_ELIGIBILITY_POINT_LINE,
            nr_alloc.get("high_demand_threshold_points"),
            False,
        ),
    ]

    for field_name, expected, found, use_isclose in checks:
        if use_isclose:
            if not (
                isinstance(found, (int, float))
                and math.isclose(float(expected), float(found))  # type: ignore[arg-type]
            ):
                raise ColoradoDrawSpecError(
                    f"_validate_artifact_constants: {field_name} mismatch — "
                    f"expected {expected!r} (module constant), "
                    f"found {found!r} (artifact); "
                    "re-run extract_draw_mechanics.py and update constants"
                )
        else:
            if expected != found:
                raise ColoradoDrawSpecError(
                    f"_validate_artifact_constants: {field_name} mismatch — "
                    f"expected {expected!r} (module constant), "
                    f"found {found!r} (artifact); "
                    "re-run extract_draw_mechanics.py and update constants"
                )

    # Also assert implied constant: preference pool share = 1 - random share
    implied_pref = 1.0 - float(hybrid_mech.get("random_pool_share", 0.0))
    if not math.isclose(implied_pref, _HYBRID_PREFERENCE_POOL_SHARE):
        raise ColoradoDrawSpecError(
            f"_validate_artifact_constants: _HYBRID_PREFERENCE_POOL_SHARE "
            f"mismatch — expected {_HYBRID_PREFERENCE_POOL_SHARE!r}, "
            f"implied by artifact (1 - random_pool_share) = {implied_pref!r}"
        )


def _extract_application_deadline(mechanics: list[dict]) -> datetime.date:
    """Parse the primary draw deadline from the important_dates record.

    Raises:
        ColoradoDrawSpecError: if the record is absent, missing the field,
            or the date is malformed.
    """
    record = _extract_single_record(mechanics, "important_dates")
    raw = record.get("primary_draw_deadline")
    if not raw:
        raise ColoradoDrawSpecError(
            "important_dates record has no 'primary_draw_deadline' field"
        )
    try:
        return datetime.date.fromisoformat(str(raw))
    except ValueError as exc:
        raise ColoradoDrawSpecError(
            f"could not parse primary_draw_deadline={raw!r}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# T3: Pure row-component builders
# ---------------------------------------------------------------------------


def _species_letter(hunt_code: str) -> str:
    """Return the first character of *hunt_code* (species letter).

    Raises:
        ColoradoDrawSpecError: if *hunt_code* is empty.
    """
    if not hunt_code:
        raise ColoradoDrawSpecError(
            "_species_letter: hunt_code is empty — cannot derive species letter"
        )
    return hunt_code[0]


def _make_pools(is_hybrid: bool) -> list[AllocationPool]:
    """Build the allocation pool list for a draw_spec.

    Hybrid → 2-pool (80 % rank-ordered by points / 20 % unweighted random
    with min_points eligibility gate).
    Non-hybrid → 1-pool (100 % rank-ordered by points).

    Only module-level ``Final`` constants are used for shares and min_points —
    no inline literals for these administrative parameters.
    """
    if is_hybrid:
        return [
            AllocationPool(
                share=_HYBRID_PREFERENCE_POOL_SHARE,
                selection="rank_ordered_by_points",
                tie_break="random",
            ),
            AllocationPool(
                share=_HYBRID_RANDOM_POOL_SHARE,
                selection="unweighted_random",
                eligibility=AllocationPoolEligibility(
                    min_points=_HYBRID_RANDOM_POOL_MIN_POINTS
                ),
                # No tie_break on the random pool — tie_break=None (default).
            ),
        ]
    return [
        AllocationPool(
            share=1.0,
            selection="rank_ordered_by_points",
            tie_break="random",
        )
    ]


def _make_residency_cap(is_hybrid: bool) -> ResidencyCap:
    """Build the ResidencyCap for a draw_spec.

    Hybrid → ``_HIGH_DEMAND_NR_CAP`` (0.20); non-hybrid → ``_STANDARD_NR_CAP``
    (0.25).  Only module-level constants — no inline literals.
    """
    return ResidencyCap(
        nonresident_max_share=_HIGH_DEMAND_NR_CAP if is_hybrid else _STANDARD_NR_CAP
    )


def _make_point_system(
    hunt_code: str, point_only_by_letter: dict[str, str]
) -> PointSystem:
    """Build the PointSystem for a draw_spec.

    Raises:
        ColoradoDrawSpecError: if the species letter derived from *hunt_code*
            has no entry in *point_only_by_letter* (flag-and-discuss surface).
    """
    letter = _species_letter(hunt_code)
    purchase_only_code = point_only_by_letter.get(letter)
    if purchase_only_code is None:
        raise ColoradoDrawSpecError(
            f"_make_point_system: no point_only_code for species letter "
            f"{letter!r} (from hunt_code={hunt_code!r}); "
            "flag-and-discuss — a new species letter in the artifact needs a "
            "point_only_code entry in draw-mechanics-2026.json"
        )
    return PointSystem(
        kind="preference_linear",
        accrual="annual_on_apply",
        reset_on_success=True,
        purchase_only_code=purchase_only_code,
        inactive_forfeit_years=None,
    )


# ---------------------------------------------------------------------------
# T4: draw_spec builder over both artifacts
# ---------------------------------------------------------------------------


def _emit_draw_spec(
    draw_specs: dict[str, DrawSpec],
    hunt_code: str,
    hybrid_set: frozenset[str],
    point_only_by_letter: dict[str, str],
    deadline: datetime.date,
    citation: SourceCitation,
) -> None:
    """Emit one DrawSpec into *draw_specs* for *hunt_code* if not already present.

    Computes ``is_hybrid`` from *hybrid_set* and delegates to the pure component
    builders for ``point_system``, ``residency_cap``, and ``pools``.  All
    module-level ``Final`` constants are used; no inline literals for
    administrative parameters.

    Called by both the big-game walk and the bear walk in ``_build_co_draw_specs``
    so the 16-line ``DrawSpec(...)`` construction lives in exactly one place.
    Does nothing if *hunt_code* is already a key in *draw_specs* (first-seen wins).
    """
    if hunt_code in draw_specs:
        return
    is_hybrid = hunt_code in hybrid_set
    draw_specs[hunt_code] = DrawSpec(
        state=_STATE,
        hunt_code=hunt_code,
        year=_LICENSE_YEAR,
        quota=None,
        point_system=_make_point_system(hunt_code, point_only_by_letter),
        residency_cap=_make_residency_cap(is_hybrid),
        choices=_CHOICES,
        pools=_make_pools(is_hybrid),
        draw_phase=_DRAW_PHASE,
        successor_hunt_code_key=None,
        application_deadline=deadline,
        parameters=_PARAMETERS,
        source=citation,
    )


def _build_co_draw_specs(
    big_game: list[dict],
    bear: list[dict],
    hybrid_set: frozenset[str],
    point_only_by_letter: dict[str, str],
    deadline: datetime.date,
    citation: SourceCitation,
) -> tuple[dict[str, DrawSpec], list[tuple[str, str]]]:
    """Walk both artifacts and build draw_specs + backfill targets.

    Returns:
        A tuple of:
        - ``draw_specs_by_hunt_code``: dict mapping unique hunt_code →
          ``DrawSpec``; one entry per unique limited-draw hunt code across both
          artifacts.
        - ``backfill_targets``: deduped list of ``(license_tag_id, hunt_code)``
          pairs for the ``license_tag.draw_spec_key`` backfill step.

    Bear ``species_group`` for ``_co_license_tag_id`` is ``"bear"`` (NOT
    ``"black_bear"`` — the artifact value).  See known-pitfalls.md entry
    "Bear DB species_group is 'bear' not 'black_bear'".

    Bear kind is checked at SECTION-level (``record["license_kind"]``) per
    S06.7's ``_build_bear_license_tags`` at :1399.  Big-game kind is checked
    at ROW-level (``row.get("list_value")``).

    Empty hunt_codes are skipped with WARNING (mirrors S06.6 GMU 020 skip).
    """
    draw_specs: dict[str, DrawSpec] = {}
    seen_backfill: dict[str, str] = {}   # license_tag_id → hunt_code

    # --- Big-game walk ---
    for section in big_game:
        for row in (section.get("rows") or []):
            try:
                list_value = row.get("list_value")
                if _co_big_game_license_kind(list_value) != "limited_draw":
                    continue

                hunt_code: str = row.get("hunt_code") or ""
                if not hunt_code.strip():
                    _LOGGER.warning(
                        "_build_co_draw_specs: skipping big-game row with "
                        "empty hunt_code in section gmu=%r species=%r page=%r",
                        section.get("gmu_code"),
                        section.get("species_group"),
                        row.get("page_reference"),
                    )
                    continue

                if not _CLEAN_HUNT_CODE_RE.match(hunt_code):
                    _LOGGER.warning(
                        "_build_co_draw_specs: skipping big-game row with "
                        "malformed hunt_code %r in gmu=%r "
                        "(upstream extract residual — ADR-022, not cleaned here)",
                        hunt_code,
                        section.get("gmu_code"),
                    )
                    continue

                # Row-level gmu_code ONLY (no section fallback) — byte-mirror of
                # S06.7's _build_big_game_license_tags (load_seasons_and_licenses.py:1024
                # uses `row["gmu_code"]`) so the backfill license_tag id derivation is
                # identical to what S06.7 wrote.  Blank gmu_code is skipped-with-WARNING
                # (S06.7 skips such rows; it creates no license_tag, so there is nothing
                # to attach a draw_spec to here).
                gmu_code: str = str(row.get("gmu_code") or "")
                if not gmu_code.strip():
                    _LOGGER.warning(
                        "_build_co_draw_specs: skipping big-game row with empty "
                        "gmu_code (hunt_code=%r) in section species=%r — mirrors "
                        "S06.7's blank-gmu skip",
                        hunt_code,
                        section.get("species_group"),
                    )
                    continue
                species_group: str = section.get("species_group", "")
                if not species_group.strip():
                    raise ColoradoDrawSpecError(
                        f"_build_co_draw_specs (big-game): hunt_code={hunt_code!r} "
                        f"gmu={gmu_code!r} section is missing 'species_group'; "
                        f"section keys: {sorted(section.keys())}; "
                        "upstream extractor regression — investigate extract_big_game.py"
                    )
                lt_id = _co_license_tag_id(species_group, gmu_code, hunt_code)

                if lt_id not in seen_backfill:
                    seen_backfill[lt_id] = hunt_code

                _emit_draw_spec(
                    draw_specs, hunt_code, hybrid_set,
                    point_only_by_letter, deadline, citation,
                )
            except (KeyError, ValueError, TypeError) as exc:
                hunt_code_ctx = row.get("hunt_code", "<unknown>")
                raise ColoradoDrawSpecError(
                    f"_build_co_draw_specs (big-game): error processing "
                    f"hunt_code={hunt_code_ctx!r} in section "
                    f"gmu={section.get('gmu_code')!r} "
                    f"species={section.get('species_group')!r}: {exc}"
                ) from exc

    # --- Bear walk ---
    for record in bear:
        if record.get("record_type") != "section":
            continue
        try:
            section_license_kind: str = record.get("license_kind", "")
            if _co_bear_license_kind(section_license_kind) != "limited_draw":
                continue

            bear_gmu_code: str = str(record.get("gmu_code") or "")
            if not bear_gmu_code.strip():
                raise ColoradoDrawSpecError(
                    "_build_co_draw_specs (bear): section with "
                    f"license_kind={section_license_kind!r} has no gmu_code; "
                    f"section keys: {sorted(record.keys())}; "
                    "upstream extractor regression — investigate extract_black_bear.py"
                )
            bear_species: str = "bear"  # DB key; artifact uses "black_bear"

            for row in (record.get("rows") or []):
                try:
                    bear_hunt_code: str = row.get("hunt_code") or ""
                    if not bear_hunt_code.strip():
                        _LOGGER.warning(
                            "_build_co_draw_specs: skipping bear row with "
                            "empty hunt_code in section gmu=%r",
                            bear_gmu_code,
                        )
                        continue

                    if not _CLEAN_HUNT_CODE_RE.match(bear_hunt_code):
                        _LOGGER.warning(
                            "_build_co_draw_specs: skipping bear row with "
                            "malformed hunt_code %r in gmu=%r "
                            "(upstream extract_black_bear.py residual — "
                            "ADR-022, not cleaned here)",
                            bear_hunt_code,
                            bear_gmu_code,
                        )
                        continue

                    row_gmu: str = str(row["gmu_code"])
                    bear_lt_id = _co_license_tag_id(
                        bear_species, row_gmu, bear_hunt_code
                    )

                    if bear_lt_id not in seen_backfill:
                        seen_backfill[bear_lt_id] = bear_hunt_code

                    _emit_draw_spec(
                        draw_specs, bear_hunt_code, hybrid_set,
                        point_only_by_letter, deadline, citation,
                    )
                except (KeyError, ValueError, TypeError) as exc:
                    bear_hunt_code_ctx = row.get("hunt_code", "<unknown>")
                    raise ColoradoDrawSpecError(
                        f"_build_co_draw_specs (bear): error processing "
                        f"hunt_code={bear_hunt_code_ctx!r} in section "
                        f"gmu={bear_gmu_code!r}: {exc}"
                    ) from exc
        except (KeyError, ValueError, TypeError) as exc:
            raise ColoradoDrawSpecError(
                f"_build_co_draw_specs (bear): error processing section "
                f"gmu={record.get('gmu_code')!r} "
                f"license_kind={record.get('license_kind')!r}: {exc}"
            ) from exc

    backfill_targets = list(seen_backfill.items())
    return draw_specs, backfill_targets


# ---------------------------------------------------------------------------
# T5: Cross-listing consistency validator + orphan/malformed reporter + count guard
# ---------------------------------------------------------------------------


def _validate_cross_listing_consistency(
    big_game: list[dict],
    bear: list[dict],
) -> None:
    """Validate that no limited-draw hunt code has conflicting non-null quotas.

    Builds a ``(hunt_code, _LICENSE_YEAR) → set`` map of distinct non-null
    quotas across ALL limited-draw rows in both artifacts.  Quotas are stored
    as their raw artifact values (no ``int()`` coercion) so semantically
    distinct encodings are never silently collapsed before the conflict check.
    For any PK with ≥2 distinct non-null quotas NOT present in
    ``_KNOWN_CROSS_LISTING_OVERRIDES``, raises ``ColoradoDrawSpecError`` (Q17
    STOP guard — flag-and-discuss).

    On 2026 data this never fires — every quota is null — but the guard is
    implemented defensively per AC #977.

    Note: the ``draw_specs`` parameter has been removed — the validator only
    needs the raw artifact lists (big_game, bear) to scan for conflicting
    quotas; it does not read from the built draw_specs dict.
    """
    quotas_by_pk: dict[tuple[str, int], set[object]] = {}

    for section in big_game:
        for row in (section.get("rows") or []):
            lv = row.get("list_value")
            try:
                if _co_big_game_license_kind(lv) != "limited_draw":
                    continue
            except ValueError as exc:
                raise ColoradoDrawSpecError(
                    f"_validate_cross_listing_consistency (big-game): "
                    f"unknown list_value {lv!r} — {exc}"
                ) from exc
            hunt_code = row.get("hunt_code") or ""
            if not hunt_code.strip():
                continue
            quota = row.get("quota")
            if quota is not None:
                pk = (hunt_code, _LICENSE_YEAR)
                quotas_by_pk.setdefault(pk, set()).add(quota)

    for record in bear:
        if record.get("record_type") != "section":
            continue
        section_kind = record.get("license_kind", "")
        try:
            if _co_bear_license_kind(section_kind) != "limited_draw":
                continue
        except ValueError as exc:
            raise ColoradoDrawSpecError(
                f"_validate_cross_listing_consistency (bear): "
                f"unknown license_kind {section_kind!r} — {exc}"
            ) from exc
        for row in (record.get("rows") or []):
            hunt_code = row.get("hunt_code") or ""
            if not hunt_code.strip():
                continue
            quota = row.get("quota")
            if quota is not None:
                pk = (hunt_code, _LICENSE_YEAR)
                quotas_by_pk.setdefault(pk, set()).add(quota)

    for pk, quota_values in quotas_by_pk.items():
        if len(quota_values) <= 1:
            continue
        if pk in _KNOWN_CROSS_LISTING_OVERRIDES:
            _LOGGER.warning(
                "_validate_cross_listing_consistency: override applied for "
                "PK %r; conflicting quotas=%r; rationale: %s",
                pk,
                quota_values,
                _KNOWN_CROSS_LISTING_OVERRIDES[pk].get("rationale", "(none)"),
            )
            continue
        raise ColoradoDrawSpecError(
            f"_validate_cross_listing_consistency: hunt_code={pk[0]!r} year={pk[1]} "
            f"has {len(quota_values)} distinct non-null quota values: {quota_values!r}. "
            "This indicates a per-GMU allocation cap conflict (Q17). "
            "Flag-and-discuss with the human before proceeding: add an entry to "
            "_KNOWN_CROSS_LISTING_OVERRIDES with the canonical quota + rationale, "
            "or split the conflicting hunt_code into distinct draw_spec rows."
        )


def _report_orphan_hybrid_codes(
    hybrid_set: frozenset[str],
    draw_specs: dict[str, DrawSpec],
) -> None:
    """Emit WARNING-level visibility report for orphan hybrid codes.

    Orphans: hybrid codes in the hybrid set that have no matching limited-draw
    draw_spec.  Expected: 3 (B-E-851-O1-R, B-E-851-O2-R, B-E-851-O5-R).

    These are the clean-grammar counterparts of the `` +``-suffixed malformed
    codes that were skipped in the build walk; they appear in the hybrid set
    but produce no draw_spec because the malformed rows are the only rows
    carrying those hunt codes.  Does not raise — visibility report only.

    The former malformed-scan block has been removed: malformed codes are now
    skipped with WARNING directly in _build_co_draw_specs (fix #1), so
    draw_specs no longer contains any malformed keys.
    """
    orphans = sorted(hybrid_set - set(draw_specs.keys()))
    if orphans:
        _LOGGER.warning(
            "%d hybrid hunt code(s) have no limited-draw draw_spec "
            "(upstream extractor residual — flag-and-discuss if count changes): %s",
            len(orphans),
            orphans,
        )


def _assert_draw_spec_count_within_guard(count: int) -> None:
    """Fail loud if draw_spec count is outside the ±30% band around baseline.

    Baseline: ``_EXPECTED_DRAW_SPEC_COUNT`` = 1914.
    Band: [1339, 2488] after ``int()`` truncation.

    Raises:
        ColoradoDrawSpecError: with the actual count and the acceptable band.
    """
    lo = int(_EXPECTED_DRAW_SPEC_COUNT * _COUNT_GUARD_MIN_RATIO)
    hi = int(_EXPECTED_DRAW_SPEC_COUNT * _COUNT_GUARD_MAX_RATIO)
    if not lo <= count <= hi:
        raise ColoradoDrawSpecError(
            f"draw_spec count guard failed: queued {count} rows; "
            f"expected approximately {_EXPECTED_DRAW_SPEC_COUNT} "
            f"(acceptable range {lo}–{hi}, ±30% of S06.8 baseline). "
            "Investigate before re-running."
        )


# ---------------------------------------------------------------------------
# T6: main() — three-phase orchestration
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for load_draw_specs."""
    parser = argparse.ArgumentParser(
        description=(
            "S06.8 — Write draw_spec rows for Colorado limited-draw hunt codes "
            "and backfill license_tag.draw_spec_key.  "
            "Two-phase write: upsert draw_specs → backfill draw_spec_key → "
            "single commit.  ~1914 draw_spec rows."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Build all records and run the count guard, but do not write to "
            "the DB.  Useful for CI smoke-testing without DB connectivity."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Increase log level from INFO to DEBUG.",
    )
    return parser.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    """Configure root logging level and format."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    """S06.8 entry point.  Returns 0 on success, non-zero on error.

    Three-phase: build → guards (pre-db.connect()) → write.

    Run from repo root::

        ingestion/.venv/bin/python ingestion/states/colorado/load_draw_specs.py

    Required env: ``DATABASE_URL``.
    Optional flags: ``--dry-run``, ``-v``/``--verbose``.
    """
    args = _parse_args(argv)
    _configure_logging(args.verbose)
    _LOGGER.info(
        "S06.8 load_draw_specs starting (dry_run=%s)", args.dry_run
    )

    # ------------------------------------------------------------------ #
    # Phase 1: Build (no DB)                                               #
    # ------------------------------------------------------------------ #
    _LOGGER.info("Phase 1: loading artifacts and building draw_specs")

    mechanics = _load_draw_mechanics(_DRAW_MECHANICS_ARTIFACT_PATH)
    _LOGGER.info("loaded draw-mechanics artifact: %d records", len(mechanics))

    _validate_artifact_constants(mechanics)
    _LOGGER.info("artifact constants validated against module-level Final constants")

    hybrid_set = _build_hybrid_code_set(mechanics)
    _LOGGER.info("hybrid code set: %d codes", len(hybrid_set))

    point_only_by_letter = _build_point_only_code_by_species_letter(mechanics)
    _LOGGER.info("point-only code map: %s", point_only_by_letter)

    deadline = _extract_application_deadline(mechanics)
    _LOGGER.info("application deadline (primary): %s", deadline)

    citation = _load_citation_from_sources_yaml(_BIG_GAME_CITATION_ID)
    _LOGGER.info("citation loaded: %s", citation.id)

    big_game: list[dict] = _load_section_artifact(_BIG_GAME_ARTIFACT_PATH)
    bear: list[dict] = _load_section_artifact(_BLACK_BEAR_ARTIFACT_PATH)

    draw_specs, backfill_targets = _build_co_draw_specs(
        big_game, bear, hybrid_set, point_only_by_letter, deadline, citation
    )
    _LOGGER.info(
        "built %d unique draw_specs (%d hybrid, %d non-hybrid); "
        "%d backfill targets",
        len(draw_specs),
        sum(1 for s in draw_specs.values() if len(s.pools) == 2),
        sum(1 for s in draw_specs.values() if len(s.pools) == 1),
        len(backfill_targets),
    )

    # ------------------------------------------------------------------ #
    # Phase 2: Guards (pre-db.connect() — OQ7)                            #
    # ------------------------------------------------------------------ #
    _LOGGER.info("Phase 2: running pre-connect guards")

    _validate_cross_listing_consistency(big_game, bear)
    _LOGGER.info("cross-listing consistency: OK (no quota conflicts)")

    _report_orphan_hybrid_codes(hybrid_set, draw_specs)

    _assert_draw_spec_count_within_guard(len(draw_specs))
    _LOGGER.info("count guard: %d draw_specs within acceptable band", len(draw_specs))

    if args.dry_run:
        hybrid_count = sum(1 for s in draw_specs.values() if len(s.pools) == 2)
        non_hybrid_count = len(draw_specs) - hybrid_count
        _LOGGER.info(
            "[dry-run] %d draw_specs (%d hybrid, %d non-hybrid), "
            "%d backfill targets; no DB writes.",
            len(draw_specs),
            hybrid_count,
            non_hybrid_count,
            len(backfill_targets),
        )
        return 0

    # ------------------------------------------------------------------ #
    # Phase 3: Write (atomic)                                              #
    # ------------------------------------------------------------------ #
    _LOGGER.info(
        "Phase 3: writing %d draw_specs + %d backfills",
        len(draw_specs),
        len(backfill_targets),
    )
    with db.connect() as conn:
        # Upsert all draw_specs first
        for spec in draw_specs.values():
            db.upsert_draw_spec(conn, spec)
        _LOGGER.info("upserted %d draw_spec rows", len(draw_specs))

        # Backfill draw_spec_key on all license_tags
        for license_tag_id, hunt_code in backfill_targets:
            db.update_license_tag_draw_spec_key(
                conn,
                license_tag_id,
                DrawSpecKey(state=_STATE, hunt_code=hunt_code, year=_LICENSE_YEAR),
            )
        _LOGGER.info(
            "backfilled draw_spec_key on %d license_tag rows",
            len(backfill_targets),
        )

        conn.commit()
        _LOGGER.info("transaction committed")

    _LOGGER.info(
        "S06.8 load_draw_specs complete: %d draw_specs written, "
        "%d draw_spec_key backfills.",
        len(draw_specs),
        len(backfill_targets),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
