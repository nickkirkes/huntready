"""S03.8 — Write draw_spec rows for Montana DEA limited_draw license_tags; backfill license_tag.draw_spec_key.

Three-phase atomic transaction
-------------------------------
All three phases execute inside a single connection and a single transaction.
Either all writes succeed and are committed, or nothing is committed.

Phase 1 — Re-upsert DEA license_tags.
    S03.7 wrote every DEA license_tag with ``draw_spec_key=None``.  T1 of
    S03.8 amended ``_build_dea_license_tags`` in ``load_seasons_and_licenses.py``
    with the OTC-wins discipline: any license_code that appears in at least one
    DEA artifact row (across ANY HD section) whose ``apply_by`` cell contains
    the substring ``"OTC"`` (i.e., the over-the-counter purchase pattern, e.g.,
    ``"OTC:\nJun 15"``) is reclassified from ``limited_draw`` to
    ``over_the_counter`` for ALL rows of that license_code across ALL HD
    sections.  This reclassifies 162 license_tag identities (corrected from
    160: two license_codes that cross-list across HDs with mixed OTC/non-OTC
    apply_by values are now consistently demoted).  Phase 1 pushes those
    corrected ``kind`` values into the DB via the existing
    ``upsert_license_tag``'s ``kind = EXCLUDED.kind`` clause.  No schema
    change is required.

Phase 2 — Upsert draw_specs.
    Iterate over the 388 DEA ``license_tag`` rows whose post-T1 ``kind`` is
    ``"limited_draw"`` (skipping ``900-20`` STATEWIDE, OTC B Licenses,
    General licenses, and bear, which have no draw mechanics in the DEA).
    For each identity, build a ``DrawSpec`` Pydantic model using the hardcoded
    V1 defaults below and write it via ``db.upsert_draw_spec``.

Phase 3 — Backfill draw_spec_key.
    For every limited_draw ``license_tag`` written in Phase 2, call
    ``db.update_license_tag_draw_spec_key`` to set the soft-FK reference so
    the MCP server can JOIN ``license_tag → draw_spec`` without a NULL gap.

Hardcoded V1 defaults
----------------------
``_DEFAULT_CHOICES = ChoiceConfig(count=1, points_used_in_choices=[1])``
    MT has no preference-point system; one choice, one point consumed per
    choice is the degenerate (no-points) representation.

``_DEFAULT_POOLS = [AllocationPool(share=1.0, selection="unweighted_random")]``
    Single-pool, pure lottery.  This elides MCA Title 87-2-106's 10 % NR cap
    structure, which is a V1 simplification.  See
    ``docs/planning/epics/E03-deferred-items/draw-mechanics.md`` for the
    deferral entry and the M2 upgrade path.

``_DEFAULT_DRAW_PHASE: Literal["primary"] = "primary"``
    MT Surplus Drawing leftover phase is not extracted from S03.3 and is
    deferred to M2; every V1 draw_spec uses the primary phase.

``_PARAMETERS: None = None``
    Q12 hard-defer per ADR-012.  Any case that would require a non-null
    ``parameters`` value triggers flag-and-defer; no state-specific quirks
    are encoded in V1.

OTC-wins discipline
--------------------
S03.7's ``_build_dea_license_tags`` heuristic (amended in T1) is the
canonical source of truth for ``license_tag.kind``.  S03.8 imports
``_build_dea_license_tags`` directly from ``load_seasons_and_licenses`` so
the classification logic is not duplicated.  The cross-row AND cross-HD
OTC-wins check (any artifact row whose ``apply_by`` contains ``"OTC"`` →
the entire license_code reclassified as ``over_the_counter`` across ALL HD
sections that cross-list it) ensures that Phase 2 correctly skips all OTC
rows when building draw_spec candidates; Phase 1's re-upsert then writes the
corrected ``kind`` value to rows already in the DB so the two tables remain
consistent.

Front-matter deadline lookup as defensive safety net
------------------------------------------------------
``_DEA_DEADLINE_LOOKUP`` is populated verbatim from DEA pp. 5/9/10/11.
Page citations are recorded in
``docs/planning/epics/E03-confidence-findings/S03.8.md``.  At runtime,
deadline values are resolved from the extraction artifact where possible;
``_DEA_DEADLINE_LOOKUP`` is consulted only as a fallback when the artifact
carries no deadline for a given (species, kind) pair.  Any runtime hit
generates a WARN log entry and a flag-and-defer drift signal — the
expectation in V1 against the locked baseline is zero hits.

Relevant ADRs
-------------
ADR-001  No invention — every field originates from a source document.
ADR-005  State-agnostic library discipline — no state-specific logic in
         ``ingestion/lib/``; all MT-specific logic lives in this file.
ADR-008  Verbatim source attribution — draw_spec.source carries the DEA
         ``SourceCitation`` with verbatim page references.
ADR-009  Open-questions discipline — unresolved decisions recorded in
         ``docs/open-questions.md`` before being answered here.
ADR-012  draw_spec as sibling entity; ``parameters`` escape hatch is
         state-adapter-only; shared code MUST NOT read ``parameters``.
ADR-017  Confidence inheritance — child entities (draw_spec) carry no
         confidence column; they inherit from their parent regulation_record.
ADR-018  license_season + geometry.legal_description schema; no schema
         changes introduced by S03.8.

Run from the repo root::

    ingestion/.venv/bin/python ingestion/states/montana/load_draw_specs.py

Required env: ``DATABASE_URL``.

Optional flag: ``--dry-run`` — build all records and run the count guards,
but do not write to the DB.  Useful for CI smoke-testing the loader logic
without requiring DB connectivity.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import sys
from pathlib import Path
from typing import Literal

from ingestion.lib.db import (
    connect,
    update_license_tag_draw_spec_key,
    upsert_draw_spec,
    upsert_license_tag,
)
from ingestion.lib.schema import (
    AllocationPool,
    ChoiceConfig,
    DrawSpec,
    DrawSpecKey,
    LicenseTag,
    SourceCitation,
)
from states.montana.load_seasons_and_licenses import (  # type: ignore[import-untyped]
    _build_dea_license_tags,      # used in T5 to get license_tag list
    _license_tag_id,              # used in T6 to build identity → LicenseTag id map
    _load_citation_from_sources_yaml,  # used in T6 to load DEA citation
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_DEFAULT_CHOICES = ChoiceConfig(count=1, points_used_in_choices=[1])
_DEFAULT_POOLS = [AllocationPool(share=1.0, selection="unweighted_random")]
_DEFAULT_DRAW_PHASE: Literal["primary"] = "primary"
_PARAMETERS: None = None

# Front-matter deadline lookup (defensive safety net; expected zero hits in V1).
# Values lifted verbatim from DEA pp. 5/9/10/11. See
# docs/planning/epics/E03-confidence-findings/S03.8.md for page citations.
_DEA_DEADLINE_LOOKUP: dict[tuple[str, str], datetime.date] = {
    ("deer",     "permit"):     datetime.date(2026, 4, 1),
    ("elk",      "permit"):     datetime.date(2026, 4, 1),
    ("deer",     "b_license"):  datetime.date(2026, 6, 1),
    ("elk",      "b_license"):  datetime.date(2026, 6, 1),
    ("antelope", "license"):    datetime.date(2026, 6, 1),
    ("antelope", "b_license"):  datetime.date(2026, 6, 1),
}

# Row-count fail-loud guard (OQ7 — mirrors S03.6/S03.7 pattern).  Fires BEFORE
# db.connect() in main().  Baseline: 388 limited_draw identities post-amended-
# heuristic + dedup.  Corrected from 390 after the P1 cubic-review fix
# broadened OTC-wins keying from (species, hd, license_code) to license_code
# alone, demoting 2 additional cross-HD identities (Deer B License: 395-01;
# Elk B License: 004-00) from limited_draw to over_the_counter.
_EXPECTED_DRAW_SPEC_COUNT: int = 388
_COUNT_GUARD_MIN_RATIO: float = 0.7
_COUNT_GUARD_MAX_RATIO: float = 1.3

# Path to the DEA extraction artifact (relative to this file).
_DEA_ARTIFACT_PATH: Path = (
    Path(__file__).resolve().parent / "extracted" / "dea-2026.json"
)

# Month-name → month-number mapping used by _parse_apply_by.
# Explicit dict (not calendar.month_name) so that the 4-letter "Sept" form
# is covered alongside "Sep" and "September".  See .roughly/known-pitfalls.md
# § "Integration — pdfplumber: DEA 'Sept' 4-letter abbreviation in antelope
# tables" (S03.7 discovery).
_MONTHS: dict[str, int] = {
    "Jan": 1, "January": 1,
    "Feb": 2, "February": 2,
    "Mar": 3, "March": 3,
    "Apr": 4, "April": 4,
    "May": 5,
    "Jun": 6, "June": 6,
    "Jul": 7, "July": 7,
    "Aug": 8, "August": 8,
    "Sep": 9, "Sept": 9, "September": 9,
    "Oct": 10, "October": 10,
    "Nov": 11, "November": 11,
    "Dec": 12, "December": 12,
}

# Single pattern: optional period after month token, mandatory whitespace,
# 1-2 digit day.  The leading [A-Z][a-z]+ anchor ensures only Title-case
# month words pass (DEA always uses Title case).
_APPLY_BY_RE: re.Pattern[str] = re.compile(
    r"^([A-Z][a-z]+)\.?\s+(\d{1,2})$"
)


# Known cross-listing structural-field overrides.
#
# When multiple license_tags share the same (hunt_code, year) PK, the
# consistency validator (_validate_cross_listing_consistency) requires their
# structural fields (quota, application_deadline) to AGREE — or the operator
# must explicitly document the conflict here. The override value is the
# canonical value written to DB; conflicting values from other cross-listings
# are dropped with a WARN log entry.
#
# V1 entries are documented in:
#   docs/planning/epics/E03-confidence-findings/S03.8.md (page citations)
#   docs/open-questions.md (per-HD-cap M2 design question — Q17)
#
# Format: (hunt_code, year) -> {"quota": int | None, "rationale": str}
#
# Each override MUST specify which fields are overridden. Fields not listed
# in the override dict must still pass the consistency check.
_KNOWN_CROSS_LISTING_OVERRIDES: dict[tuple[str, int], dict[str, object]] = {
    ("Elk B License: 210-03", 2026): {
        "quota": 300,
        "rationale": (
            "Home-HD (210) quota=300 is canonical; cross-listed mentions in "
            "HDs 211/212/216 show quota=200 (per-HD allocation cap not modeled "
            "in V1 draw_spec). See DEA p. 53 row 7 (home), p. 53 row 21 (HD "
            "211), p. 54 row 12 (HD 212), p. 57 row 13 (HD 216). Per-HD-cap "
            "semantic is a Q17 / M2 ADR-candidate."
        ),
    },
}


def _parse_apply_by(apply_by: str | None, license_year: int) -> datetime.date | None:
    """Parse a DEA apply_by cell into a datetime.date.

    Returns None for:
    - None input (caller should consult _DEA_DEADLINE_LOOKUP fallback)
    - Strings containing the substring "OTC" (over-the-counter signal; caller
      should skip — these are not draws)

    Otherwise: matches against a fixed set of (month_word, day) patterns
    derived from real DEA artifact values. Year is supplied by caller.

    Raises:
        ValueError: if the string is non-None, non-OTC, and does not match
                    any recognized month/day pattern. Fail-loud — surfaces a
                    new DEA format change immediately rather than silently
                    treating it as a missing deadline.
    """
    if apply_by is None:
        return None
    if "OTC" in apply_by:
        return None
    normalized = re.sub(r"\s+", " ", apply_by.strip())
    match = _APPLY_BY_RE.match(normalized)
    if match is None:
        msg = (
            f"_parse_apply_by: unrecognized format {apply_by!r}; "
            f"expected '<Month> <Day>' (e.g., 'Jun 1', 'April 1', 'Sept 30')"
        )
        raise ValueError(msg)
    month_word, day_str = match.group(1), match.group(2)
    month_num = _MONTHS.get(month_word)
    if month_num is None:
        msg = (
            f"_parse_apply_by: unrecognized month token {month_word!r} "
            f"in input {apply_by!r}; expected one of {sorted(_MONTHS.keys())}"
        )
        raise ValueError(msg)
    return datetime.date(license_year, month_num, int(day_str))


# ---------------------------------------------------------------------------
# Module-level counter (T6) — tracks front-matter deadline lookup fallback hits
# per _build_dea_draw_specs call; reset at top of each call.
# ---------------------------------------------------------------------------

_lookup_fallback_hits: int = 0


# ---------------------------------------------------------------------------
# DEA draw_spec builder (T6)
# ---------------------------------------------------------------------------


def _build_dea_draw_specs(
    dea_artifact: list[dict],
    dea_citation: SourceCitation,
) -> list[tuple[LicenseTag, DrawSpec]]:
    """Build (license_tag, draw_spec) pairs for every DEA limited_draw identity.

    Excludes:
    - 900-20 STATEWIDE (caught by S03.7's STATEWIDE branch → kind='statewide')
    - OTC B Licenses (caught by T1's OTC-wins branch → kind='over_the_counter')
    - General licenses (kind='general')
    - Bear (built by a different path in S03.7 — not present in DEA artifact)

    Determinism: artifact-order preservation via dict insertion order.

    Raises:
        RuntimeError: if a limited_draw identity has no parseable apply_by AND
                      no _DEA_DEADLINE_LOOKUP fallback match (data drift signal).
        RuntimeError: if duplicate rows of the same identity disagree on
                      license_year (artifact corruption signal).
    """
    global _lookup_fallback_hits
    _lookup_fallback_hits = 0

    # --- Step 1: build all license_tags (kind already classified per T1 OTC-wins) ---
    all_tags = _build_dea_license_tags(dea_artifact, dea_citation)

    # --- Step 2: filter to limited_draw only ---
    filtered_tags = [tag for tag in all_tags if tag.kind == "limited_draw"]

    # --- Step 3: dedupe by LicenseTag.id; first-occurrence wins (artifact-order) ---
    unique_tags: dict[str, LicenseTag] = {}
    for tag in filtered_tags:
        if tag.id not in unique_tags:
            unique_tags[tag.id] = tag

    # --- Step 4: build per-identity index of apply_by / license_year values ---
    # Key: (species_group, hd_number, license_code)
    # Value: list of {"apply_by": ..., "license_year": ...} dicts (in artifact order)
    identity_rows: dict[tuple[str, str, str], list[dict]] = {}
    for section in dea_artifact:
        species_group: str = section["species_group"]
        hd_number: str = section["hd_number"]
        license_year: int = section["license_year"]
        for row in section["rows"]:
            key: tuple[str, str, str] = (species_group, hd_number, row["license_code"])
            identity_rows.setdefault(key, []).append(
                {
                    "apply_by": row.get("apply_by"),
                    "license_year": license_year,
                }
            )

    # --- Step 5: build id → (species_group, hd_number, license_code) map ---
    # Reconstructed via the canonical _license_tag_id() to avoid parsing id strings.
    id_to_identity: dict[str, tuple[str, str, str]] = {}
    for section in dea_artifact:
        sg: str = section["species_group"]
        hd: str = section["hd_number"]
        for row in section["rows"]:
            lc: str = row["license_code"]
            tag_id = _license_tag_id(sg, hd, lc)
            if tag_id not in id_to_identity:
                id_to_identity[tag_id] = (sg, hd, lc)

    # --- Main loop: one DrawSpec per unique limited_draw LicenseTag ---
    result: list[tuple[LicenseTag, DrawSpec]] = []

    for tag_id, tag in unique_tags.items():
        identity = id_to_identity[tag_id]
        species_group_artifact, hd_number_artifact, license_code_artifact = identity
        rows_for_identity = identity_rows.get(identity, [])

        # --- Step 6: identity guard + year consistency check ---
        # Theoretically impossible (identity_index was built from the same artifact),
        # but the diagnostic-on-failure value is high.
        if not rows_for_identity:
            msg = (
                f"_build_dea_draw_specs: no artifact rows found for identity "
                f"{identity!r}; broken license_tag.id derivation?"
            )
            raise RuntimeError(msg)

        distinct_years = {r["license_year"] for r in rows_for_identity}
        if len(distinct_years) != 1:
            msg = (
                f"_build_dea_draw_specs: license_year drift within identity "
                f"{identity!r}: {distinct_years!r}"
            )
            raise RuntimeError(msg)
        resolved_license_year: int = distinct_years.pop()

        # --- Step 7: resolve application_deadline ---
        application_deadline: datetime.date | None = None

        # Try parsing apply_by cells in artifact order; take first non-None result.
        for r in rows_for_identity:
            parsed = _parse_apply_by(r["apply_by"], resolved_license_year)
            if parsed is not None:
                application_deadline = parsed
                break

        if application_deadline is None:
            # Consult front-matter deadline lookup (defensive safety net).
            # Derive license_kind_token from license_code.
            lc = license_code_artifact
            if lc.startswith("Antelope License:") and "B License" not in lc:
                license_kind_token = "license"
            elif "B License" in lc:
                license_kind_token = "b_license"
            elif "Permit:" in lc:
                license_kind_token = "permit"
            else:
                msg = (
                    f"_build_dea_draw_specs: cannot derive lookup key for "
                    f"license_code={lc!r}"
                )
                raise RuntimeError(msg)

            lookup_key = (species_group_artifact, license_kind_token)

            _LOGGER.warning(
                "Front-matter deadline-lookup fallback fired for "
                "license_tag.id=%s — drift signal (expected zero hits in V1)",
                tag_id,
            )
            _lookup_fallback_hits += 1

            if lookup_key not in _DEA_DEADLINE_LOOKUP:
                msg = (
                    f"_build_dea_draw_specs: front-matter lookup miss for "
                    f"(species={species_group_artifact!r}, "
                    f"token={license_kind_token!r}) on "
                    f"license_tag.id={tag_id!r}"
                )
                raise RuntimeError(msg)

            application_deadline = _DEA_DEADLINE_LOOKUP[lookup_key]

        # --- Step 8: construct DrawSpec ---
        spec = DrawSpec(
            state="US-MT",
            hunt_code=tag.license_code,
            year=resolved_license_year,
            quota=tag.quota,
            point_system=None,
            residency_cap=None,
            choices=_DEFAULT_CHOICES,
            pools=_DEFAULT_POOLS,
            draw_phase=_DEFAULT_DRAW_PHASE,
            successor_hunt_code_key=None,
            application_deadline=application_deadline,
            parameters=_PARAMETERS,
            source=tag.source,
        )

        # --- Step 9: append pair ---
        result.append((tag, spec))

    return result


# ---------------------------------------------------------------------------
# Cross-listing consistency validator (F1+F2)
# ---------------------------------------------------------------------------


def _validate_cross_listing_consistency(
    pairs: list[tuple[LicenseTag, DrawSpec]],
) -> list[tuple[LicenseTag, DrawSpec]]:
    """Validate that license_tags sharing a (hunt_code, year) PK agree on
    structural fields (quota, application_deadline). Apply documented overrides.

    For each PK with multiple constituent pairs:
    - If all constituents agree on every structural field: pass through.
    - If they disagree AND an override is in _KNOWN_CROSS_LISTING_OVERRIDES:
      - For EACH disagreeing field, check whether the override specifies a
        canonical value. If it does NOT, raise RuntimeError naming the field
        and the missing override key (partial-override fail-loud).
      - Apply the override values that ARE present; log WARN per PK.
    - If they disagree AND no override: raise RuntimeError naming the PK and
      the conflicting values (fail-loud discipline; operator must investigate).

    Returns the pairs list (possibly with overridden field values). Does NOT
    dedupe by PK — Phase 3 still backfills draw_spec_key per license_tag.

    Raises:
        RuntimeError: if any PK has cross-listing structural conflict without
                      a documented override, OR if an override exists but does
                      not cover a field that is actually in conflict.
    """
    # Group pairs by (hunt_code, year)
    by_pk: dict[tuple[str, int], list[tuple[LicenseTag, DrawSpec]]] = {}
    for tag, spec in pairs:
        by_pk.setdefault((spec.hunt_code, spec.year), []).append((tag, spec))

    resolved: list[tuple[LicenseTag, DrawSpec]] = []
    for pk, constituents in by_pk.items():
        if len(constituents) == 1:
            resolved.append(constituents[0])
            continue

        # Multi-constituent PK; check structural-field agreement
        quotas = {c[1].quota for c in constituents}
        deadlines = {c[1].application_deadline for c in constituents}

        if len(quotas) == 1 and len(deadlines) == 1:
            # All agree — pass through unchanged
            resolved.extend(constituents)
            continue

        # Conflict detected — check for override
        override = _KNOWN_CROSS_LISTING_OVERRIDES.get(pk)
        if override is None:
            msg = (
                f"_validate_cross_listing_consistency: PK {pk!r} has "
                f"{len(constituents)} constituent license_tags with conflicting "
                f"structural fields (quotas={quotas!r}, "
                f"deadlines={deadlines!r}); no override documented in "
                f"_KNOWN_CROSS_LISTING_OVERRIDES. Either fix the source data, "
                f"add an override entry, or split the license_code into "
                f"distinct hunt_codes."
            )
            raise RuntimeError(msg)

        # Apply override — rewrite the affected field on every constituent.
        # Field-by-field fail-loud: every DISAGREEING field MUST have a
        # canonical value in the override entry. An override that specifies
        # only one field but leaves another conflicting field unspecified
        # would silently produce last-write-wins via UPSERT on the uncovered
        # field — data drift without any operator signal.
        #
        # Key-presence check (not `.get(...) is None`): an override entry may
        # intentionally specify `{"quota": None}` to force the canonical value
        # to SQL NULL (e.g., removing a quota entirely). Using `.get(...)` would
        # collapse "key absent" and "key present with explicit None" into the
        # same branch — the presence check distinguishes them.
        has_quota_override = "quota" in override
        has_deadline_override = "application_deadline" in override
        override_quota = override.get("quota") if has_quota_override else None
        override_deadline = (
            override.get("application_deadline") if has_deadline_override else None
        )

        if len(quotas) > 1 and not has_quota_override:
            msg = (
                f"_validate_cross_listing_consistency: PK {pk!r} has "
                f"{len(constituents)} constituents with conflicting `quota` "
                f"values {quotas!r}, but the override entry in "
                f"_KNOWN_CROSS_LISTING_OVERRIDES specifies no `quota` key. "
                f"Add `'quota': <canonical_value>` to the override or fix "
                f"the upstream data."
            )
            raise RuntimeError(msg)
        if len(deadlines) > 1 and not has_deadline_override:
            msg = (
                f"_validate_cross_listing_consistency: PK {pk!r} has "
                f"{len(constituents)} constituents with conflicting "
                f"`application_deadline` values {deadlines!r}, but the "
                f"override entry in _KNOWN_CROSS_LISTING_OVERRIDES specifies "
                f"no `application_deadline` key. Add it to the override or "
                f"fix the upstream data."
            )
            raise RuntimeError(msg)
        rationale = override.get("rationale", "(no rationale recorded)")
        _LOGGER.warning(
            "Cross-listing override applied for PK %r: %d constituents with "
            "quotas=%r deadlines=%r; canonical quota=%r deadline=%r. "
            "Rationale: %s",
            pk, len(constituents), quotas, deadlines,
            override_quota if has_quota_override else "(no override)",
            override_deadline if has_deadline_override else "(no override)",
            rationale,
        )
        for tag, spec in constituents:
            spec_updates: dict[str, object] = {}
            tag_updates: dict[str, object] = {}

            if has_quota_override:
                # override_quota may be None — that is intentional (force SQL NULL)
                if spec.quota != override_quota:
                    spec_updates["quota"] = override_quota
                if tag.quota != override_quota:
                    tag_updates["quota"] = override_quota

            if has_deadline_override:
                if spec.application_deadline != override_deadline:
                    spec_updates["application_deadline"] = override_deadline
                # NOTE: LicenseTag has no application_deadline field; deadline
                # overrides apply only to DrawSpec.

            if spec_updates:
                # Pydantic frozen=True — use model_copy(update=...)
                spec = spec.model_copy(update=spec_updates)
            if tag_updates:
                tag = tag.model_copy(update=tag_updates)
            resolved.append((tag, spec))

    return resolved


# ---------------------------------------------------------------------------
# Row-count fail-loud guards (OQ7 — mirrors S03.6/S03.7 pattern)
# ---------------------------------------------------------------------------


def _assert_draw_spec_count_within_guard(written: int) -> None:
    """Fail loud if the draw_spec queued count is outside ±30% band of 388.

    Baseline 388 DEA limited_draw identities post-amended-heuristic (T1) +
    dedup. Corrected from 390 after the P1 cubic-review fix broadened OTC-wins
    keying. Concrete bounds after int() truncation: [271, 504].

    Outside-band indicates a regression in T1's heuristic or in
    _build_dea_draw_specs's dedupe/filter logic. Investigate before re-running.
    """
    lower = int(_EXPECTED_DRAW_SPEC_COUNT * _COUNT_GUARD_MIN_RATIO)
    upper = int(_EXPECTED_DRAW_SPEC_COUNT * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"draw_spec count guard failed: queued {written} rows; "
            f"expected approximately {_EXPECTED_DRAW_SPEC_COUNT} (acceptable "
            f"range {lower}-{upper}, ±30% of S03.8 baseline). This indicates a "
            f"regression in T1's kind heuristic or in _build_dea_draw_specs. "
            f"Investigate before re-running."
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

__all__ = ["main"]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for load_draw_specs."""
    parser = argparse.ArgumentParser(
        description=(
            "S03.8 — Write draw_spec rows for Montana DEA limited_draw license_tags "
            "and backfill license_tag.draw_spec_key.  Three-phase atomic transaction: "
            "(1) re-upsert DEA license_tags (OTC reclassification); "
            "(2) upsert draw_specs; "
            "(3) backfill draw_spec_key references.  "
            "Writes ~388 draw_spec rows atomically (single commit)."
        ),
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=_DEA_ARTIFACT_PATH,
        help="Path to dea-2026.json extraction artifact (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Build all records and run the count guard, but do not write to the DB. "
            "Useful for CI smoke-testing without DB connectivity."
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
    """S03.8 entry point. Returns 0 on success, non-zero on error.

    Three-phase atomic transaction:
      Phase 1 — Re-upsert DEA license_tags (reclassifies ~162 OTC rows).
      Phase 2 — Upsert draw_specs (~388 limited_draw identities).
      Phase 3 — Backfill license_tag.draw_spec_key for each draw_spec written.

    Run from repo root:
        ingestion/.venv/bin/python ingestion/states/montana/load_draw_specs.py

    Required env: DATABASE_URL.
    Optional flags: --dry-run, -v/--verbose, --artifact PATH.
    """
    # Parse args, configure logging
    args = _parse_args(argv)
    _configure_logging(args.verbose)
    _LOGGER.info(
        "S03.8 load_draw_specs starting (artifact=%s, dry_run=%s)",
        args.artifact,
        args.dry_run,
    )

    # 1. Load artifact
    try:
        with open(args.artifact) as f:
            dea_artifact: list[dict] = json.load(f)
    except FileNotFoundError:
        _LOGGER.error("DEA artifact not found at %s", args.artifact)
        return 1
    except json.JSONDecodeError as exc:
        _LOGGER.error(
            "DEA artifact at %s is not valid JSON: %s", args.artifact, exc
        )
        return 1

    # 2. Load DEA citation (from sources.yaml + manifest cross-check)
    try:
        dea_citation = _load_citation_from_sources_yaml("mt-fwp-dea-2026-booklet")
    except FileNotFoundError:
        _LOGGER.error(
            "sources.yaml not found at expected path (run S03.1's fetch or check "
            "working directory)"
        )
        return 1

    # 3. Build DEA license_tags (with T1's OTC-wins discipline applied)
    dea_license_tags = _build_dea_license_tags(dea_artifact, dea_citation)
    _LOGGER.info("Built %d DEA license_tags from artifact", len(dea_license_tags))

    # 4. Build draw_spec pairs
    draw_spec_pairs = _build_dea_draw_specs(dea_artifact, dea_citation)
    _LOGGER.info("Built %d (license_tag, draw_spec) pairs", len(draw_spec_pairs))

    # 4a. Apply cross-listing consistency validation + overrides (fail-loud on
    # undocumented conflicts; override-rewrite logs WARN per applied override)
    draw_spec_pairs = _validate_cross_listing_consistency(draw_spec_pairs)

    # 4b. Propagate any cross-listing license_tag quota overrides from the
    # validator back to the Phase 1 dea_license_tags list so Phase 1 writes
    # the canonical quota value to DB. Without this, Phase 1 would write the
    # original per-HD cap values (e.g., 200) while Phase 2 writes the override
    # value (e.g., 300), producing inconsistent license_tag.quota vs
    # draw_spec.quota for the same logical license.
    # See _KNOWN_CROSS_LISTING_OVERRIDES rationale strings.
    override_quotas_by_tag_id: dict[str, int | None] = {
        tag.id: tag.quota for tag, _spec in draw_spec_pairs
    }
    dea_license_tags = [
        tag.model_copy(update={"quota": override_quotas_by_tag_id[tag.id]})
        if tag.id in override_quotas_by_tag_id
        and tag.quota != override_quotas_by_tag_id[tag.id]
        else tag
        for tag in dea_license_tags
    ]

    # 5. Front-matter fallback drift guard. Fires for BOTH dry-run and real runs:
    # the counter is final after the builder call, and a non-zero count indicates
    # unexpected data state that an operator must investigate BEFORE writes
    # (real run) or BEFORE claiming smoke-test success (dry run).
    if _lookup_fallback_hits > 0:
        msg = (
            f"Front-matter deadline-lookup fallback fired {_lookup_fallback_hits} "
            f"time(s). V1 baseline expects 0 hits — any firing is a drift signal "
            f"indicating S03.3 extraction regression OR a new license type in a "
            f"future PDF revision that bypasses per-row apply_by. Investigate "
            f"before committing (the artifact, the front-matter chart values in "
            f"docs/planning/epics/E03-confidence-findings/S03.8.md § 4, or both)."
        )
        raise RuntimeError(msg)

    # 6. Row-count guard BEFORE db.connect()
    _assert_draw_spec_count_within_guard(len(draw_spec_pairs))

    # 7. Dry-run short-circuit (NOTE: fallback-hit check has already fired above)
    if args.dry_run:
        _LOGGER.info(
            "[dry-run] Would write %d DEA license_tag rows (re-upsert for "
            "OTC reclassification), %d draw_spec rows, %d draw_spec_key "
            "backfills. Front-matter-lookup fallback hits: %d.",
            len(dea_license_tags),
            len(draw_spec_pairs),
            len(draw_spec_pairs),
            _lookup_fallback_hits,
        )
        return 0

    # 8. Open conn, three-phase atomic transaction
    conn = connect()
    try:
        # Phase 1: re-upsert DEA license_tags (reclassifies 162 OTC rows)
        _LOGGER.info("Phase 1: re-upserting %d DEA license_tags", len(dea_license_tags))
        for tag in dea_license_tags:
            upsert_license_tag(conn, tag)
        _LOGGER.info(
            "Phase 1 complete: %d license_tag UPSERTs queued", len(dea_license_tags)
        )

        # Phase 2: upsert draw_specs
        _LOGGER.info("Phase 2: upserting %d draw_specs", len(draw_spec_pairs))
        for _tag, spec in draw_spec_pairs:
            upsert_draw_spec(conn, spec)
        _LOGGER.info(
            "Phase 2 complete: %d draw_spec UPSERTs queued", len(draw_spec_pairs)
        )

        # Phase 3: backfill draw_spec_key
        _LOGGER.info(
            "Phase 3: backfilling %d draw_spec_key references", len(draw_spec_pairs)
        )
        for tag, spec in draw_spec_pairs:
            key = DrawSpecKey(
                state=spec.state,
                hunt_code=spec.hunt_code,
                year=spec.year,
            )
            update_license_tag_draw_spec_key(conn, tag.id, key)
        _LOGGER.info(
            "Phase 3 complete: %d draw_spec_key backfills queued", len(draw_spec_pairs)
        )

        # Commit (fallback-hit check already fired before this block)
        conn.commit()
        _LOGGER.info("Transaction committed.")
    except Exception:
        conn.rollback()
        _LOGGER.exception("Transaction rolled back due to error during phase writes")
        raise
    finally:
        conn.close()

    # 9. Run summary
    _LOGGER.info(
        "S03.8 load complete. license_tags re-upserted: %d. draw_specs written: %d. "
        "draw_spec_key backfills: %d. Front-matter-lookup fallback hits: %d.",
        len(dea_license_tags),
        len(draw_spec_pairs),
        len(draw_spec_pairs),
        _lookup_fallback_hits,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
