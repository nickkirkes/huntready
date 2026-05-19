"""Montana season_definition + license_tag + license_season ingestion adapter.

Reads two extraction artifacts produced by S03.3-S03.4 and writes five tables
in one atomic transaction:

1. ``season_definition`` rows — one per unique (species, hd/bmu, season_key),
   shared across the DB species fan-out for deer (mule_deer + whitetail
   reference the same row via the link tables).
2. ``license_tag`` rows — one per artifact license row (DEA 1190 + bear 35 = 1225).
3. ``license_season`` link rows — per ADR-018 §1, this is the per-license
   season-coverage truth (DEA 2936 + bear ~140 ≈ 3076 rows).
4. ``regulation_season`` link rows — per regulation_record × unique seasons.
5. ``regulation_license`` link rows — per regulation_record × license_tag (DEA
   fan-out 1448 deer + 142 elk/antelope + 35 bear ≈ 1625 rows).

Per ADR-010 (decomposed-entity model), these are child entities whose FK target
is the 436 ``regulation_record`` rows landed by S03.6.

Per ADR-018 §1, ``license_season`` and ``regulation_season`` are distinct link
tables that coexist — each answers a different join question. Both are written
here in the same atomic transaction.

``license_tag.draw_spec_key`` is intentionally left NULL — S03.8 backfills
limited-draw spec references once the draw_spec table is populated.

Open-question decision codes OQ-S7-1 through OQ-S7-11 are documented in the
full implementation plan at ``docs/plans/S03.7-season-license-ingestion-plan.md``.

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/load_seasons_and_licenses.py

Required env: ``DATABASE_URL``.

Optional flag: ``--dry-run`` — build all records and run the count guards,
but do not write to the DB. Useful for CI smoke-testing the loader logic
without requiring DB connectivity.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
from pathlib import Path

import yaml

from ingestion.lib import db, pdf
from ingestion.lib.schema import (
    ClosurePredicate,
    LicenseSeason,
    LicenseTag,
    RegulationLicense,
    RegulationSeason,
    SeasonDefinition,
    SourceCitation,
    WeaponType,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_MONTANA_DIR = Path(__file__).resolve().parent
_EXTRACTED_DIR = _MONTANA_DIR / "extracted"
_DEA_ARTIFACT = _EXTRACTED_DIR / "dea-2026.json"
_BEAR_ARTIFACT = _EXTRACTED_DIR / "black-bear-2026.json"
_SOURCES_YAML = _MONTANA_DIR / "sources.yaml"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MT_STATE_CODE = "US-MT"
_LICENSE_YEAR = 2026
_DEA_CITATION_ID = "mt-fwp-dea-2026-booklet"
_BEAR_BOOKLET_CITATION_ID = "mt-fwp-black-bear-2026-booklet"
_BEAR_CORRECTION_CITATION_ID = "mt-fwp-black-bear-2026-correction-2026-03-18"

# Montana FWP evergreen license-purchase entry point (OQ-S7-11).
# Points at the routing page rather than a deep link so the URL survives
# downstream FWP site rotations without a code edit.
_PURCHASE_URL = "https://fwp.mt.gov/hunt/licensing/buy"


# ---------------------------------------------------------------------------
# Module data lookups
# ---------------------------------------------------------------------------

# Maps DEA artifact species_group label to DB-side species_group value(s).
# Mirrors the S03.6 precedent in load_regulation_records.py.  Deer fans out
# to mule_deer + whitetail at the link-table layer; the season_definition and
# license_tag rows themselves use the artifact-level "deer" label (OQ-S7-1/2).
_DEA_SPECIES_FANOUT: dict[str, tuple[str, ...]] = {
    "deer":     ("mule_deer", "whitetail"),
    "elk":      ("elk",),
    "antelope": ("pronghorn",),
}

# Title-case display names matching the FWP DEA column headers.  Used to
# populate ``season_definition.name`` from the artifact's ``SeasonCoverage``
# keys (OQ-S7-4).
_SEASON_NAME_BY_KEY: dict[str, str] = {
    "archery_only":          "Archery Only",
    "general":               "General",
    "heritage_muzzleloader": "Heritage Muzzleloader",
    "late":                  "Late",
    "early_season":          "Early Season",
}

# Maps bear artifact season-field names to (season_key, season_name) tuples.
# `season_key` is used in the season_definition id (the slug); `season_name`
# is the title-cased display name written to season_definition.name.
# season_keys are hyphenated so they match _bear_season_definition_id's slug
# construction directly (replace("_", "-") is a no-op on hyphenated input).
_BEAR_SEASON_FIELDS: dict[str, tuple[str, str]] = {
    "general_season":         ("general",         "General Season"),
    "archery_only_season":    ("archery-only",    "Archery Only Season"),
    "spring_season":          ("spring",          "Spring Season"),
    "hound_training_season":  ("hound-training",  "Hound Training Season"),
}


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
    (``extract_black_bear.py``, ``extract_legal_descriptions.py``,
    ``load_regulation_records.py``, this file).
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
            supersedes=None,
            page_reference=None,
        )

    raise RuntimeError(
        f"sources.yaml has no entry with id={citation_id!r}"
    )


# ---------------------------------------------------------------------------
# Jurisdiction-code helper
# ---------------------------------------------------------------------------


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
            # (per ADR-018 §3 — antelope's `900-20` row).  A mule_deer /
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


# ---------------------------------------------------------------------------
# Row-count fail-loud guards (OQ7)
# ---------------------------------------------------------------------------

# Row-count fail-loud guards (OQ7).  Expected values derived from spot-checks
# against the actual extraction artifacts (S03.7 implementation, 2026-05-15).
# Concrete bounds after int() truncation are computed in the assert functions.
# Outside-band raises RuntimeError BEFORE any DB writes (S03.6 precedent).
_SEASON_DEFINITION_EXPECTED: int = 978    # DEA 874 + bear 104
_LICENSE_TAG_EXPECTED: int = 1225          # DEA 1190 + bear 35
_LICENSE_SEASON_EXPECTED: int = 3040       # DEA 2936 + bear 104
_REGULATION_SEASON_EXPECTED: int = 1385    # DEA 1281 + bear 104
_REGULATION_LICENSE_EXPECTED: int = 1914   # DEA 1879 + bear 35
_COUNT_GUARD_MIN_RATIO = 0.70
_COUNT_GUARD_MAX_RATIO = 1.30


# ---------------------------------------------------------------------------
# Window + quota + slug parsers (T4)
# ---------------------------------------------------------------------------


def _parse_window(
    window_str: str, license_year: int
) -> tuple[datetime.date, datetime.date]:
    """Parse a DEA/bear season-window string into (opens_date, closes_date).

    Handles three formats:
    - Dotless:  ``"Sep 05-Oct 18"``              (most DEA rows)
    - Dotted:   ``"Aug. 15-Nov. 08"``            (antelope STATEWIDE 900-20)
    - Bear-style with embedded newlines: ``"Sep.\\n15-Nov.\\n29"``

    Normalization: strip dots, collapse all whitespace runs to a single space.
    After normalization each half is ``"Mon DD"`` parseable via ``%b %d %Y``.

    Year-wrap rule: if closes < opens (e.g. ``"Nov 30-Jan 01"`` crosses a
    calendar year boundary), closes is re-parsed with ``license_year + 1``.

    Raises:
        ValueError: for malformed input (wrong number of ``-`` segments,
                    unparseable month abbreviation, etc.).  Fail-loud.
    """
    # Strip dots, collapse all whitespace (including embedded newlines) to " ".
    # Also normalize "Sept" → "Sep" (FWP antelope tables use the 4-letter form
    # in dotted notation, e.g. "Sept. 05-Oct. 09"; strptime %b requires 3 chars).
    normalized = re.sub(r"\s+", " ", window_str.replace(".", "")).strip()
    normalized = re.sub(r"\bSept\b", "Sep", normalized)

    # Split on the first "-" to get exactly two halves: "Mon DD" each.
    parts = normalized.split("-", 1)
    if len(parts) != 2:
        raise ValueError(
            f"_parse_window: expected exactly one '-' separator; got {window_str!r}"
        )
    opens_half, closes_half = parts

    opens = datetime.datetime.strptime(
        f"{opens_half.strip()} {license_year}", "%b %d %Y"
    ).date()
    closes = datetime.datetime.strptime(
        f"{closes_half.strip()} {license_year}", "%b %d %Y"
    ).date()

    # Year-wrap: season window crosses a calendar year boundary.
    if closes < opens:
        closes = datetime.datetime.strptime(
            f"{closes_half.strip()} {license_year + 1}", "%b %d %Y"
        ).date()

    return (opens, closes)


def _parse_quota_range(raw: str | None) -> tuple[int, int] | None:
    """Parse a DEA quota-range string like ``"1-7,500"`` into ``(1, 7500)``.

    Returns:
        ``None`` for None input or whitespace-only strings.
        ``(min_quota, max_quota)`` as integers, allowing comma thousand-separators.

    Raises:
        ValueError: if the string cannot be split into exactly two integer halves
                    or if either half is non-numeric.  Fail-loud.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None

    parts = stripped.split("-")
    if len(parts) != 2:
        raise ValueError(
            f"_parse_quota_range: expected exactly one '-' separator; got {raw!r}"
        )
    lo_str, hi_str = parts
    return (int(lo_str.replace(",", "").strip()), int(hi_str.replace(",", "").strip()))


def _license_code_slug(license_code: str) -> str:
    """Extract a stable, lowercase, URL-safe slug from a DEA license code.

    Examples:
    - ``"General Elk License"``      → ``"general"``
    - ``"Elk B License: 124-00"``    → ``"elk-b-124-00"``
    - ``"Deer B License: 262-50"``   → ``"deer-b-262-50"``
    - ``"Antelope License: 900-20"`` → ``"antelope-900-20"``
    - ``"Antelope License: 471-20"`` → ``"antelope-471-20"``
    - ``"Deer Permit: 262-51"``      → ``"deer-permit-262-51"``
    - ``"Elk Permit: 999-99"``       → ``"elk-permit-999-99"``

    Strategy (per OQ-S7-7 closed-set discipline):
    1. ``"General "`` prefix → return ``"general"`` (the section's species_group
       distinguishes "General Elk License" vs "General Deer License" at the
       license_tag id layer; no within-section general-vs-general collisions
       observed in the V1 artifact).
    2. Numeric suffix ``DDD-DD`` present → return the license-type prefix
       (lowercased, hyphenated, with trailing ``" License"`` word dropped as
       noise) joined with the numeric suffix.  This includes the license-type
       prefix so two licenses sharing the same numeric code (e.g. the same
       deer-section containing ``"Deer B License: 410-00"`` AND
       ``"Elk B License: 410-00"`` cross-listed) produce DISTINCT slugs.
       Without this disambiguation 6 cross-license collisions occur in the
       live V1 artifact (cubic-review P1, 2026-05-16).
    3. Anything else → ``ValueError`` (fail-loud).
    """
    if license_code.startswith("General "):
        return "general"
    m = re.search(r"(\d+-\d+)", license_code)
    if not m:
        raise ValueError(f"unrecognized license_code format: {license_code!r}")
    numeric = m.group(1)
    prefix_text = license_code[: m.start()].rstrip(": ").strip()
    # Drop a redundant trailing " License" word — it's a noisy suffix shared
    # by most codes that adds no disambiguating value.  Keep "Permit" since
    # it discriminates from "License" kinds.
    if prefix_text.endswith(" License"):
        prefix_text = prefix_text[: -len(" License")].strip()
    prefix_slug = re.sub(r"\s+", "-", prefix_text.lower())
    if not prefix_slug:
        raise ValueError(
            f"license_code {license_code!r} produced empty prefix slug "
            f"(numeric={numeric!r}); is the code missing a license-type prefix?"
        )
    return f"{prefix_slug}-{numeric}"


# ---------------------------------------------------------------------------
# ID constructors
# ---------------------------------------------------------------------------


def _season_definition_id(species: str, hd_number: str, season_key: str) -> str:
    """Deterministic season_definition.id constructor.

    Format: ``MT-HD-{hd}-{species}-{slug}-{year}`` for per-HD;
            ``MT-STATEWIDE-{species}-{slug}-{year}`` when hd_number == "STATEWIDE".

    `species` is the ARTIFACT-level species label ("deer" | "elk" | "antelope" | "bear"),
    NOT the DB species_group granularity ("mule_deer" | "whitetail" | "elk" | "pronghorn" | "bear").
    Per OQ-S7-2: a single season_definition is shared across the DB species fan-out
    via the regulation_season link table.
    """
    slug = season_key.replace("_", "-")
    if hd_number == "STATEWIDE":
        return f"MT-STATEWIDE-{species}-{slug}-{_LICENSE_YEAR}"
    return f"MT-HD-{hd_number}-{species}-{slug}-{_LICENSE_YEAR}"


def _license_tag_id(species: str, hd_number: str, license_code: str) -> str:
    """Deterministic license_tag.id constructor.

    Format: ``MT-HD-{hd}-{species}-{slug}-{year}`` per-HD;
            ``MT-STATEWIDE-{species}-{slug}-{year}`` when hd_number == "STATEWIDE".

    `slug` comes from `_license_code_slug(license_code)` (defined below); this
    function uses the placeholder slug until T4 implements the real slug builder.
    """
    slug = _license_code_slug(license_code)
    if hd_number == "STATEWIDE":
        return f"MT-STATEWIDE-{species}-{slug}-{_LICENSE_YEAR}"
    return f"MT-HD-{hd_number}-{species}-{slug}-{_LICENSE_YEAR}"


def _bear_season_definition_id(bmu_number: int, season_key: str) -> str:
    """Deterministic bear season_definition.id constructor.

    Format: ``MT-BMU-{bmu_number}-bear-{slug}-{year}``.
    """
    slug = season_key.replace("_", "-")
    return f"MT-BMU-{bmu_number}-bear-{slug}-{_LICENSE_YEAR}"


def _bear_license_tag_id(bmu_number: int) -> str:
    """Deterministic bear license_tag.id constructor.

    Format: ``MT-BMU-{bmu_number}-bear-{year}``.
    """
    return f"MT-BMU-{bmu_number}-bear-{_LICENSE_YEAR}"


# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bear artifact helpers (shared by T8 and T9)
# ---------------------------------------------------------------------------


def _load_bear_sources_by_id(bear_artifact: dict) -> dict[str, dict]:
    """Build a lookup of bear-artifact sources by id, with fail-loud shape guards.

    Mirrors load_regulation_records.py:322-336 (S03.6 precedent).
    """
    raw_sources = bear_artifact.get("sources")
    if not isinstance(raw_sources, list):
        raise RuntimeError(
            f"bear artifact missing or invalid 'sources' key "
            f"(expected list, got {type(raw_sources).__name__}); "
            f"re-run extract_black_bear.py and inspect the artifact"
        )
    return {s["id"]: s for s in raw_sources}


def _validate_bear_rows(bear_artifact: dict) -> list[dict]:
    """Return the bear artifact's rows list, with fail-loud shape guard."""
    raw_rows = bear_artifact.get("rows")
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            f"bear artifact missing or invalid 'rows' key "
            f"(expected list, got {type(raw_rows).__name__}); "
            f"re-run extract_black_bear.py and inspect the artifact"
        )
    return raw_rows


def _validate_bear_closures(bear_artifact: dict) -> list[dict]:
    """Validate the bear artifact's 'closures' key shape and return the list.

    Mirrors the fail-loud shape guards in _load_bear_sources_by_id and
    _validate_bear_rows for parity. The 'closures' list carries the load-
    bearing per-BMU closure-predicate candidates; a missing or non-list
    value would silently elide all closure_predicate attachments.
    """
    raw_closures = bear_artifact.get("closures")
    if not isinstance(raw_closures, list):
        raise RuntimeError(
            f"bear artifact missing or invalid 'closures' key "
            f"(expected list, got {type(raw_closures).__name__}); "
            f"re-run extract_black_bear.py and inspect the artifact"
        )
    return raw_closures


# ---------------------------------------------------------------------------
# Bear season_definition builder (T8)
# ---------------------------------------------------------------------------


def _build_closure_predicate(c: dict) -> ClosurePredicate:
    """Construct a ClosurePredicate from a raw bear artifact closure dict.

    All required fields (kind, notification_channel, verbatim_rule) are read
    directly from the artifact.  Missing required fields raise ValidationError
    from Pydantic; optional fields use .get() with a None default.

    Raises:
        pydantic.ValidationError: if any required field is absent or invalid.
    """
    return ClosurePredicate(
        kind=c["kind"],
        notification_channel=c["notification_channel"],
        observation_channel=c.get("observation_channel"),
        threshold_percent=c.get("threshold_percent"),
        threshold_sex=c.get("threshold_sex"),
        verbatim_rule=c["verbatim_rule"],
    )


def _build_bear_season_definitions(
    bear_artifact: dict,
) -> list[SeasonDefinition]:
    """Build all SeasonDefinition entities from the bear artifact.

    One SeasonDefinition per (BMU, non-null season field) in source order.
    hound_training_season is None for all 35 V1 BMUs; those rows are skipped.

    ClosurePredicate attachment (OQ-S7-5/-6):
    - general + archery-only seasons: attach quota_threshold closure if the
      BMU appears in ``closures`` with kind="quota_threshold".
    - spring season: attach sex_threshold closure if the BMU appears in
      ``closures`` with kind="sex_threshold".
    - All other combinations: closure_predicate=None.

    Raises:
        RuntimeError: if bear_artifact is missing "sources" or "rows" keys,
                      if a row references an unknown source_id, or if an
                      unhandled closure kind is encountered.
    """
    closures = _validate_bear_closures(bear_artifact)
    quota_closure_by_bmu: dict[int, dict] = {}
    sex_closure_by_bmu: dict[int, dict] = {}
    for c in closures:
        kind = c["kind"]
        for bmu in c["bmu_numbers"]:
            if kind == "quota_threshold":
                quota_closure_by_bmu[bmu] = c
            elif kind == "sex_threshold":
                sex_closure_by_bmu[bmu] = c
            else:
                raise RuntimeError(f"unhandled bear closure kind: {kind!r}")

    sources_by_id = _load_bear_sources_by_id(bear_artifact)
    raw_rows = _validate_bear_rows(bear_artifact)

    definitions: list[SeasonDefinition] = []

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
        bmu_number: int = row["bmu_number"]

        for field_name, (season_key, season_name) in _BEAR_SEASON_FIELDS.items():
            if row[field_name] is None:
                continue

            opens, closes = _parse_window(row[field_name], _LICENSE_YEAR)
            weapon_type: WeaponType | None = "archery" if season_key == "archery-only" else None

            # closure_predicate attachment per OQ-S7-5/-6
            closure_predicate: ClosurePredicate | None
            if season_key == "spring" and bmu_number in sex_closure_by_bmu:
                closure_predicate = _build_closure_predicate(sex_closure_by_bmu[bmu_number])
            elif season_key in ("general", "archery-only") and bmu_number in quota_closure_by_bmu:
                closure_predicate = _build_closure_predicate(quota_closure_by_bmu[bmu_number])
            else:
                closure_predicate = None

            definitions.append(
                SeasonDefinition(
                    id=_bear_season_definition_id(bmu_number, season_key),
                    name=season_name,
                    opens=opens,
                    closes=closes,
                    weapon_type=weapon_type,
                    residency=None,
                    closure_predicate=closure_predicate,
                    verbatim_rule=row["verbatim_text"],
                    page_reference=page_ref_str,
                    source=row_citation,
                )
            )

    return definitions


# ---------------------------------------------------------------------------
# Bear license_tag + link-row builders (T9)
# ---------------------------------------------------------------------------


def _build_bear_license_tags(bear_artifact: dict) -> list[LicenseTag]:
    """Build one LicenseTag per BMU from the bear artifact.

    One license_tag per artifact row (35 rows → 35 tags).
    species="bear" (DB species_group value — NOT artifact's "black_bear",
    per S03.6 precedent in load_regulation_records.py:350).
    quota is taken from fall_quota["count"]; None passes through if the cell
    was "-" in the original PDF (no quota declared for that BMU).
    """
    sources_by_id = _load_bear_sources_by_id(bear_artifact)
    raw_rows = _validate_bear_rows(bear_artifact)

    tags: list[LicenseTag] = []

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

        bmu_number: int = row["bmu_number"]
        fall_quota = row.get("fall_quota") or {}
        quota_count: int | None = fall_quota.get("count")

        tags.append(
            LicenseTag(
                id=_bear_license_tag_id(bmu_number),
                license_code=f"MT-BMU-{bmu_number}-bear",
                name="Black Bear License",
                kind="general",
                species="bear",
                weapon_types=["any_legal_weapon"],
                residency="both",
                quota=quota_count,
                quota_range=None,
                purchase_url=_PURCHASE_URL,
                draw_spec_key=None,
                reserved_pools=[],
                verbatim_rule=row["verbatim_text"],
                source=row_citation,
            )
        )

    return tags


def _build_bear_license_season_links(bear_artifact: dict) -> list[LicenseSeason]:
    """Build LicenseSeason link rows for the bear artifact.

    One row per (BMU, non-null season field).  hound_training_season is None
    for all 35 V1 BMUs and is always skipped.

    Expected count: 35 × 3 - 1 (BMU 309 missing archery_only) = 104.
    """
    raw_rows = _validate_bear_rows(bear_artifact)

    links: list[LicenseSeason] = []

    for row in raw_rows:
        bmu_number: int = row["bmu_number"]
        license_tag_id = _bear_license_tag_id(bmu_number)

        for field_name, (season_key, _season_name) in _BEAR_SEASON_FIELDS.items():
            if row.get(field_name) is None:
                continue
            season_definition_id = _bear_season_definition_id(bmu_number, season_key)
            links.append(
                LicenseSeason(
                    license_tag_id=license_tag_id,
                    season_definition_id=season_definition_id,
                )
            )

    return links


def _build_bear_regulation_season_links(bear_artifact: dict) -> list[RegulationSeason]:
    """Build RegulationSeason link rows for the bear artifact.

    One row per (BMU, non-null season field), matching the license_season count.
    jurisdiction_code uses the bear-specific pattern written by S03.6:
    ``MT-HD-bear-{bmu_number}``.

    Expected count: 104.
    """
    raw_rows = _validate_bear_rows(bear_artifact)

    links: list[RegulationSeason] = []

    for row in raw_rows:
        bmu_number: int = row["bmu_number"]
        jurisdiction_code = f"MT-HD-bear-{bmu_number}"

        for field_name, (season_key, _season_name) in _BEAR_SEASON_FIELDS.items():
            if row.get(field_name) is None:
                continue
            season_definition_id = _bear_season_definition_id(bmu_number, season_key)
            links.append(
                RegulationSeason(
                    state=_MT_STATE_CODE,
                    jurisdiction_code=jurisdiction_code,
                    species_group="bear",
                    license_year=_LICENSE_YEAR,
                    season_definition_id=season_definition_id,
                )
            )

    return links


def _build_bear_regulation_license_links(bear_artifact: dict) -> list[RegulationLicense]:
    """Build RegulationLicense link rows for the bear artifact.

    One row per BMU.
    jurisdiction_code uses the bear-specific pattern written by S03.6:
    ``MT-HD-bear-{bmu_number}``.

    Expected count: 35.
    """
    raw_rows = _validate_bear_rows(bear_artifact)

    links: list[RegulationLicense] = []

    for row in raw_rows:
        bmu_number: int = row["bmu_number"]
        links.append(
            RegulationLicense(
                state=_MT_STATE_CODE,
                jurisdiction_code=f"MT-HD-bear-{bmu_number}",
                species_group="bear",
                license_year=_LICENSE_YEAR,
                license_tag_id=_bear_license_tag_id(bmu_number),
            )
        )

    return links


# ---------------------------------------------------------------------------
# DEA species-group validator (shared by all four DEA builders)
# ---------------------------------------------------------------------------


def _validate_dea_species_group(species_group: str, hd_number: str) -> None:
    """Fail loud if a DEA section's species_group is not in _DEA_SPECIES_FANOUT.

    Raises RuntimeError with HD context so the operator knows where to look
    in the artifact. Called at the top of every DEA builder so partial output
    is not produced before the species-fanout-aware link builders run.

    Without this guard, an unexpected species_group (e.g., 'black_bear'
    appearing in a DEA section due to an S03.3 extraction regression) would
    either silently produce wrong rows (entity builders) or raise a bare
    KeyError without HD context (link builders).
    """
    if species_group not in _DEA_SPECIES_FANOUT:
        raise RuntimeError(
            f"DEA section species_group={species_group!r} (HD={hd_number!r}) "
            f"is not in _DEA_SPECIES_FANOUT={sorted(_DEA_SPECIES_FANOUT.keys())!r}. "
            f"This indicates a regression in extract_dea.py; investigate before "
            f"re-running."
        )


# ---------------------------------------------------------------------------
# DEA season_definition builders (T5)
# ---------------------------------------------------------------------------


def _select_season_verbatim_rule(
    rows: list[dict],
    season_key: str,
    section_verbatim_text: str,
) -> str:
    """Select the source-faithful verbatim_rule for a season_definition.

    Preference order per OQ-S7-9:
    1. The first row with license_code.startswith("General ") that covers
       this season (season_coverage[season_key] is True) AND has a non-empty
       extras cell.
    2. Else: the first row that covers this season and has non-empty extras
       (any license type).
    3. Else: section_verbatim_text (the full section text — guaranteed
       non-empty per S03.3 extraction discipline).
    """
    general_matches = [
        r for r in rows
        if r["season_coverage"].get(season_key) is True
        and r["license_code"].startswith("General ")
        and isinstance(r.get("extras"), str)
        and r["extras"].strip()
    ]
    if general_matches:
        return general_matches[0]["extras"].strip()
    any_matches = [
        r for r in rows
        if r["season_coverage"].get(season_key) is True
        and isinstance(r.get("extras"), str)
        and r["extras"].strip()
    ]
    if any_matches:
        return any_matches[0]["extras"].strip()
    return section_verbatim_text


def _build_dea_season_definitions(
    dea_artifact: list[dict],
    dea_citation: SourceCitation,
) -> list[SeasonDefinition]:
    """Build all unique SeasonDefinition entities from the DEA artifact.

    Deduplicates by id across the entire artifact (first-occurrence-wins).
    Iterates sections in source order; within each section iterates rows in
    source order; within each row iterates season_windows.items() in dict
    order.

    Defensive WARNING: if the same (HD, species, season_key) reappears with a
    different window string, a warning is logged but the first-occurrence-wins
    dedup still applies.  This should not occur if S03.3 extraction discipline
    holds; the warning surfaces regressions.
    """
    seen_ids: set[str] = set()
    seen_window_by_id: dict[str, str] = {}
    definitions: list[SeasonDefinition] = []

    for section in dea_artifact:
        _validate_dea_species_group(section["species_group"], section["hd_number"])
        page_ref_str = pdf.page_reference_to_str(section["page_reference"])
        section_citation = dea_citation.model_copy(update={"page_reference": page_ref_str})

        for row in section["rows"]:
            for season_key, season_window in row["season_windows"].items():
                if not row["season_coverage"].get(season_key, False):
                    # Drift signal: season_windows carries an entry whose
                    # season_coverage flag is False (or absent).  Discovery
                    # confirmed the invariant (season_windows keys ≡ trues
                    # in season_coverage) holds for the V1 artifact, so this
                    # branch is normally unreachable.  If it fires, an S03.3
                    # extraction regression has decoupled the two fields and
                    # the season_coverage truth value is the source of record
                    # ("this license covers this season").  Skip and warn so
                    # the loud signal surfaces.
                    _logger.warning(
                        "section HD=%s species=%s row %r has season_windows[%r] "
                        "but season_coverage[%r]=False; skipping per coverage truth.",
                        section["hd_number"], section["species_group"],
                        row["license_code"], season_key, season_key,
                    )
                    continue
                season_definition_id = _season_definition_id(
                    section["species_group"],
                    section["hd_number"],
                    season_key,
                )

                if season_definition_id in seen_ids:
                    # Defensive: same (HD, species, season_key) reappearing with a
                    # DIFFERENT window string. This IS expected V1 behavior — per-row
                    # season faithfulness is preserved at S03.3 extraction time, but
                    # season_definition is keyed by (HD, species, season_key) with no
                    # room for per-row variation in the canonical (opens, closes)
                    # pair. First-occurrence-wins is the V1 simplification (see
                    # docs/planning/epics/E03-confidence-findings/S03.3.md for the
                    # "Elk B License: 699-01" canonical case). WARN-and-continue is
                    # the audit trail; NOT a regression signal. Do not promote to
                    # RuntimeError without a deliberate spec change — that would abort
                    # the load on legitimate per-row divergence.
                    if season_window["window"] != seen_window_by_id[season_definition_id]:
                        _logger.warning(
                            "season_definition id %r seen again with a different window "
                            "(%r vs first-occurrence %r) — first-occurrence-wins; "
                            "this may indicate an S03.3 extraction inconsistency.",
                            season_definition_id,
                            season_window["window"],
                            seen_window_by_id[season_definition_id],
                        )
                    continue

                opens, closes = _parse_window(season_window["window"], _LICENSE_YEAR)
                weapon_type = season_window["weapon_type_override"]
                name = _SEASON_NAME_BY_KEY[season_key]  # KeyError = fail-loud on unknown key
                verbatim_rule = _select_season_verbatim_rule(
                    section["rows"],
                    season_key,
                    section["verbatim_text"],
                )

                definitions.append(
                    SeasonDefinition(
                        id=season_definition_id,
                        name=name,
                        opens=opens,
                        closes=closes,
                        weapon_type=weapon_type,
                        residency=None,
                        closure_predicate=None,
                        verbatim_rule=verbatim_rule,
                        page_reference=page_ref_str,
                        source=section_citation,
                    )
                )
                seen_ids.add(season_definition_id)
                seen_window_by_id[season_definition_id] = season_window["window"]

    return definitions


# ---------------------------------------------------------------------------
# OTC row helper (F6) — used by _build_dea_license_tags
# ---------------------------------------------------------------------------


def _row_has_otc(row: dict) -> bool:
    """True if row's apply_by is a string containing the 'OTC' substring.

    Fails loud on absent `apply_by` key OR non-str / non-None value —
    artifact schema drift signal. The absent-key check distinguishes
    "key removed from artifact schema" (drift, must surface) from
    "key present with explicit None value" (legitimate absence of a
    deadline, treated as no-OTC).

    Args:
        row: A single DEA artifact row dict.

    Returns:
        True if apply_by is a non-empty string containing 'OTC', False if
        apply_by is None or a string not containing 'OTC'.

    Raises:
        RuntimeError: if the `apply_by` key is missing from `row` (schema
            drift) or if its value is neither str nor None.
    """
    if "apply_by" not in row:
        msg = (
            f"_row_has_otc: `apply_by` key missing from artifact row "
            f"with license_code={row.get('license_code')!r}. Artifact "
            f"schema drift? Expected str|None."
        )
        raise RuntimeError(msg)
    apply_by = row["apply_by"]
    if apply_by is None:
        return False
    if not isinstance(apply_by, str):
        msg = (
            f"_row_has_otc: expected apply_by to be str|None, got "
            f"{type(apply_by).__name__}: {apply_by!r}. Artifact schema drift?"
        )
        raise RuntimeError(msg)
    return "OTC" in apply_by


# ---------------------------------------------------------------------------
# DEA license_tag builder (T6)
# ---------------------------------------------------------------------------


def _build_dea_license_tags(
    dea_artifact: list[dict],
    dea_citation: SourceCitation,
) -> list[LicenseTag]:
    """Build one LicenseTag per artifact license row from the DEA artifact.

    Iterates sections in artifact order; within each section iterates rows in
    artifact order.  Returns all LicenseTag instances in that deterministic
    order.

    Duplicate license_code within a section (e.g. HD 170 elk has two rows
    sharing "General Elk License") produce the SAME id.  Both instances are
    emitted; the DB upsert layer collapses via ON CONFLICT DO UPDATE
    (second-write-wins on structural fields).  Do NOT deduplicate here — the
    semantic payload is the UNION of season_coverage across duplicate rows,
    which the license_season builder (T7) handles via ON CONFLICT DO NOTHING.

    Kind heuristic (OQ-S7-7, first-match-wins):
    (a) hd_number == "STATEWIDE"         → "statewide"
    (b) license_code.startswith("General ") → "general"
    (c) "B License" in license_code       → "over_the_counter" if license_code appears in
                                             ANY artifact row (across ALL HD sections) with
                                             "OTC" in its apply_by; else "limited_draw"
    (d) "Permit:" in license_code         → "limited_draw"
    (e) license_code.startswith("Antelope License:") → "limited_draw"
    (f) else: RuntimeError (fail-loud)

    OTC-wins is cross-row AND cross-HD: any artifact row's `apply_by` containing
    'OTC' demotes ALL rows of that license_code to over_the_counter, regardless
    of which HD section they appear in.

    Raises:
        RuntimeError: if a license_code does not match any kind heuristic.
    """
    # OTC-wins discipline is keyed by license_code (the physical-license identity)
    # rather than by (species, hd, license_code) because the same license_code
    # appears in multiple HD sections in the DEA booklet (cross-listing). All
    # instances of one license_code must classify consistently — if ANY artifact
    # row shows OTC for this license_code, ALL instances demote to over_the_counter.
    _otc_license_codes: frozenset[str] = frozenset(
        row["license_code"]
        for section in dea_artifact
        for row in section["rows"]
        if _row_has_otc(row)
    )

    tags: list[LicenseTag] = []

    for section in dea_artifact:
        hd_number: str = section["hd_number"]
        species_group: str = section["species_group"]
        _validate_dea_species_group(species_group, hd_number)
        verbatim_text: str = section["verbatim_text"]

        for row in section["rows"]:
            license_code: str = row["license_code"]

            # --- kind heuristic (OQ-S7-7, first-match-wins) ---
            if hd_number == "STATEWIDE":
                kind = "statewide"
            elif license_code.startswith("General "):
                kind = "general"
            elif "B License" in license_code:
                kind = (
                    "over_the_counter"
                    if license_code in _otc_license_codes
                    else "limited_draw"
                )
            elif "Permit:" in license_code:
                kind = "limited_draw"
            elif license_code.startswith("Antelope License:"):
                kind = "limited_draw"
            else:
                raise RuntimeError(
                    f"unrecognized license_code kind: {license_code!r} "
                    f"in section HD={hd_number!r} species={species_group!r}"
                )

            # --- name: opportunity with license_code fallback ---
            opportunity = row.get("opportunity")
            name = (opportunity.strip() if isinstance(opportunity, str) and opportunity.strip()
                    else license_code)

            # --- source citation with per-row page_reference ---
            page_ref_str = pdf.page_reference_to_str(row["page_reference"])
            row_citation = dea_citation.model_copy(update={"page_reference": page_ref_str})

            tags.append(
                LicenseTag(
                    id=_license_tag_id(species_group, hd_number, license_code),
                    license_code=license_code,
                    name=name,
                    kind=kind,  # type: ignore[arg-type]
                    species=species_group,
                    weapon_types=row["weapon_types"],
                    residency="both",
                    quota=row.get("quota"),
                    quota_range=_parse_quota_range(row.get("quota_range")),
                    purchase_url=_PURCHASE_URL,
                    draw_spec_key=None,
                    reserved_pools=[],
                    verbatim_rule=verbatim_text,
                    source=row_citation,
                )
            )

    return tags


# ---------------------------------------------------------------------------
# DEA link-row builders (T7)
# ---------------------------------------------------------------------------


def _build_dea_license_season_links(
    dea_artifact: list[dict],
) -> list[LicenseSeason]:
    """Build LicenseSeason link rows — one per (license_tag, season_definition).

    Iterates artifact in source order: sections → rows → season_windows items.
    Duplicate (license_tag_id, season_definition_id) tuples (e.g. HD 170 elk
    two "General Elk License" rows covering the same season) are emitted as-is;
    the DB layer collapses via ON CONFLICT DO NOTHING.  Do NOT deduplicate here
    — source-order emit preserves debuggability.

    Total expected: 2936 (count of season_coverage==True flags across all DEA rows).
    """
    links: list[LicenseSeason] = []
    for section in dea_artifact:
        species_group: str = section["species_group"]
        hd_number: str = section["hd_number"]
        _validate_dea_species_group(species_group, hd_number)
        for row in section["rows"]:
            license_code: str = row["license_code"]
            license_tag_id = _license_tag_id(species_group, hd_number, license_code)
            for season_key in row["season_windows"]:
                if not row["season_coverage"].get(season_key, False):
                    # Drift guard: see _build_dea_season_definitions for context.
                    # season_coverage is the source of truth for "covers this
                    # season"; skip rather than over-emit a license_season link.
                    _logger.warning(
                        "section HD=%s species=%s row %r has season_windows[%r] "
                        "but season_coverage[%r]=False; skipping license_season link.",
                        hd_number, species_group, license_code, season_key, season_key,
                    )
                    continue
                season_definition_id = _season_definition_id(
                    species_group, hd_number, season_key
                )
                links.append(
                    LicenseSeason(
                        license_tag_id=license_tag_id,
                        season_definition_id=season_definition_id,
                    )
                )
    return links


def _build_dea_regulation_season_links(
    dea_artifact: list[dict],
) -> list[RegulationSeason]:
    """Build RegulationSeason link rows — one per (regulation_record, unique season).

    For deer sections the DB species fan-out produces TWO rows per unique season
    (mule_deer + whitetail), both referencing the SAME season_definition_id
    (shared across the fan-out per OQ-S7-2 — season_definition uses
    artifact-level species, not DB species).

    Iterates artifact in source order: sections → unique season_keys (set dedup
    across all rows in the section) → fan-out target species.
    """
    links: list[RegulationSeason] = []
    for section in dea_artifact:
        species_group: str = section["species_group"]
        hd_number: str = section["hd_number"]
        _validate_dea_species_group(species_group, hd_number)

        # Collect unique season_keys present in this section, gated by
        # season_coverage truth values.  Discovery confirmed the invariant
        # (season_windows keys ≡ trues in season_coverage) holds for the V1
        # artifact; the filter is defensive against S03.3 extraction drift
        # that could decouple the two fields.  season_coverage is the source
        # of truth for "this license covers this season" — without the filter,
        # a stale season_windows entry would over-emit a regulation_season link.
        unique_season_keys: set[str] = {
            season_key
            for row in section["rows"]
            for season_key in row["season_windows"]
            if row["season_coverage"].get(season_key, False)
        }

        for target_species in _DEA_SPECIES_FANOUT[species_group]:
            jurisdiction_code = _dea_jurisdiction_code(target_species, hd_number)
            for season_key in sorted(unique_season_keys):  # sorted for determinism
                season_definition_id = _season_definition_id(
                    species_group, hd_number, season_key
                )
                links.append(
                    RegulationSeason(
                        state=_MT_STATE_CODE,
                        jurisdiction_code=jurisdiction_code,
                        species_group=target_species,
                        license_year=_LICENSE_YEAR,
                        season_definition_id=season_definition_id,
                    )
                )
    return links


def _build_dea_regulation_license_links(
    dea_artifact: list[dict],
) -> list[RegulationLicense]:
    """Build RegulationLicense link rows — one per (regulation_record, license_tag).

    Deer sections fan out to TWO entries per artifact row (mule_deer + whitetail).
    Duplicate license_codes within a section produce duplicate RegulationLicense
    rows; the DB layer collapses via ON CONFLICT DO NOTHING.  Do NOT deduplicate.

    license_tag_id uses artifact-level species (section["species_group"]), NOT
    the DB target_species — the license_tag is shared across the fan-out
    (per OQ-S7-2, mirrors the season_definition sharing pattern).
    """
    links: list[RegulationLicense] = []
    for section in dea_artifact:
        species_group: str = section["species_group"]
        hd_number: str = section["hd_number"]
        _validate_dea_species_group(species_group, hd_number)

        for row in section["rows"]:
            license_code: str = row["license_code"]
            license_tag_id = _license_tag_id(species_group, hd_number, license_code)

            for target_species in _DEA_SPECIES_FANOUT[species_group]:
                jurisdiction_code = _dea_jurisdiction_code(target_species, hd_number)
                links.append(
                    RegulationLicense(
                        state=_MT_STATE_CODE,
                        jurisdiction_code=jurisdiction_code,
                        species_group=target_species,
                        license_year=_LICENSE_YEAR,
                        license_tag_id=license_tag_id,
                    )
                )
    return links


# ---------------------------------------------------------------------------
# Row-count fail-loud guard functions (OQ7 — mirrors S03.6 pattern)
# ---------------------------------------------------------------------------


def _assert_season_definition_count_within_guard(written: int) -> None:
    """Fail loud if the season_definition queued count is outside ±30% band of 978
    (DEA 874 + bear 104).  Concrete bounds after int() truncation: [684, 1271].
    Outside-band indicates a regression in extract_dea.py or extract_black_bear.py.
    """
    lower = int(_SEASON_DEFINITION_EXPECTED * _COUNT_GUARD_MIN_RATIO)
    upper = int(_SEASON_DEFINITION_EXPECTED * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"season_definition count guard failed: queued {written} rows; "
            f"expected approximately {_SEASON_DEFINITION_EXPECTED} (acceptable "
            f"range {lower}-{upper}, ±30% of S03.7 baseline). This indicates a "
            f"regression in extract_dea.py or extract_black_bear.py. Investigate "
            f"before re-running."
        )


def _assert_license_tag_count_within_guard(written: int) -> None:
    """Fail loud if the license_tag queued count is outside ±30% band of 1225
    (DEA 1190 + bear 35).  Concrete bounds after int() truncation: [857, 1592].
    Outside-band indicates a regression in extract_dea.py or extract_black_bear.py.
    """
    lower = int(_LICENSE_TAG_EXPECTED * _COUNT_GUARD_MIN_RATIO)
    upper = int(_LICENSE_TAG_EXPECTED * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"license_tag count guard failed: queued {written} rows; "
            f"expected approximately {_LICENSE_TAG_EXPECTED} (acceptable "
            f"range {lower}-{upper}, ±30% of S03.7 baseline). This indicates a "
            f"regression in extract_dea.py or extract_black_bear.py. Investigate "
            f"before re-running."
        )


def _assert_license_season_count_within_guard(written: int) -> None:
    """Fail loud if the license_season queued count is outside ±30% band of 3040
    (DEA 2936 + bear 104).  Concrete bounds after int() truncation: [2128, 3952].
    Outside-band indicates a regression in the per-row season_coverage truth values
    in extract_dea.py.
    """
    lower = int(_LICENSE_SEASON_EXPECTED * _COUNT_GUARD_MIN_RATIO)
    upper = int(_LICENSE_SEASON_EXPECTED * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"license_season count guard failed: queued {written} rows; "
            f"expected approximately {_LICENSE_SEASON_EXPECTED} (acceptable "
            f"range {lower}-{upper}, ±30% of S03.7 baseline). This indicates a "
            f"regression in extract_dea.py per-row season_coverage truth values. "
            f"Investigate before re-running."
        )


def _assert_regulation_season_count_within_guard(written: int) -> None:
    """Fail loud if the regulation_season queued count is outside ±30% band of 1385
    (DEA 1281 + bear 104).  Concrete bounds after int() truncation: [969, 1800].
    Outside-band indicates a regression in the unique-season-per-HD computation
    in _build_dea_regulation_season_links or _build_bear_regulation_season_links.
    """
    lower = int(_REGULATION_SEASON_EXPECTED * _COUNT_GUARD_MIN_RATIO)
    upper = int(_REGULATION_SEASON_EXPECTED * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"regulation_season count guard failed: queued {written} rows; "
            f"expected approximately {_REGULATION_SEASON_EXPECTED} (acceptable "
            f"range {lower}-{upper}, ±30% of S03.7 baseline). This indicates a "
            f"regression in the unique-season-per-HD computation in T7's builder. "
            f"Investigate before re-running."
        )


def _assert_regulation_license_count_within_guard(written: int) -> None:
    """Fail loud if the regulation_license queued count is outside ±30% band of 1914
    (DEA 1879 + bear 35).  Concrete bounds after int() truncation: [1339, 2488].
    Outside-band indicates a regression in the DEA species fan-out in T7's builder
    or in the bear rows.
    """
    lower = int(_REGULATION_LICENSE_EXPECTED * _COUNT_GUARD_MIN_RATIO)
    upper = int(_REGULATION_LICENSE_EXPECTED * _COUNT_GUARD_MAX_RATIO)
    if not (lower <= written <= upper):
        raise RuntimeError(
            f"regulation_license count guard failed: queued {written} rows; "
            f"expected approximately {_REGULATION_LICENSE_EXPECTED} (acceptable "
            f"range {lower}-{upper}, ±30% of S03.7 baseline). This indicates a "
            f"regression in DEA species fan-out in T7's builder or bear rows. "
            f"Investigate before re-running."
        )


# ---------------------------------------------------------------------------
# Summary logging
# ---------------------------------------------------------------------------


def _log_summary(
    season_definitions: list[SeasonDefinition],
    license_tags: list[LicenseTag],
    license_season_links: list[LicenseSeason],
    regulation_season_links: list[RegulationSeason],
    regulation_license_links: list[RegulationLicense],
    logger: logging.Logger,
) -> None:
    """Emit summary cross-tabs over the queued / written rows.

    Three breakdowns:
    1. season_definition by (weapon_type, has_closure_predicate) — surfaces
       the bear vs DEA distribution at a glance.
    2. license_tag by (species, kind) — locks the DEA fan-out + bear singleton
       + statewide overlay.
    3. Link-row totals — for operator cross-check against the count-guard
       baselines.
    """
    # 1. season_definition: (weapon_type, has_closure_predicate)
    sd_buckets: dict[tuple[str | None, bool], int] = {}
    for sd in season_definitions:
        key = (sd.weapon_type, sd.closure_predicate is not None)
        sd_buckets[key] = sd_buckets.get(key, 0) + 1
    lines = ["season_definition summary:"]
    lines.append("  weapon_type           | closure_predicate | count")
    lines.append("  ----------------------+-------------------+------")
    for (wt, has_cp), n in sorted(sd_buckets.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        lines.append(f"  {wt or 'NULL':<21} | {'yes' if has_cp else 'no':<17} | {n}")
    lines.append(f"  total: {len(season_definitions)}")

    # 2. license_tag: (species, kind)
    lt_buckets: dict[tuple[str, str], int] = {}
    for lt in license_tags:
        lt_key = (lt.species, lt.kind)
        lt_buckets[lt_key] = lt_buckets.get(lt_key, 0) + 1
    lines.append("")
    lines.append("license_tag summary:")
    lines.append("  species   | kind             | count")
    lines.append("  ----------+------------------+------")
    for (sp, kd), n in sorted(lt_buckets.items()):
        lines.append(f"  {sp:<9} | {kd:<16} | {n}")
    lines.append(f"  total: {len(license_tags)}")

    # 3. Link totals
    lines.append("")
    lines.append("link-row totals:")
    lines.append(f"  license_season:     {len(license_season_links)}")
    lines.append(f"  regulation_season:  {len(regulation_season_links)}")
    lines.append(f"  regulation_license: {len(regulation_license_links)}")

    for line in lines:
        logger.info(line)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Load Montana season_definition + license_tag + license_season + ...

    Reads dea-2026.json + black-bear-2026.json; writes five tables atomically.
    Bear closure_predicate populated for the 8 quota-closure BMUs + 4 female-
    sub-quota BMUs.  license_tag.draw_spec_key left NULL (S03.8 backfills).

    Run from repo root:
        ingestion/.venv/bin/python ingestion/states/montana/load_seasons_and_licenses.py

    Required env: DATABASE_URL.

    Optional flag: --dry-run  (build + guard + summary; no DB writes).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Load Montana season_definition + license_tag rows + license_season "
            "links + regulation_season + regulation_license links from the DEA "
            "+ Black Bear extraction artifacts.  Writes ~978 season_definition "
            "+ ~1225 license_tag + ~3040 license_season + ~1385 regulation_season "
            "+ ~1914 regulation_license rows atomically (single commit)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Build all entities and run the five count guards, but do not write "
            "to the DB.  Useful for CI smoke-testing without DB connectivity."
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
    # bear_booklet_citation and bear_correction_citation aren't directly consumed
    # by the builders — source_ids are already baked into the artifact per row.
    # We load them here as fail-loud guards against sources.yaml drift
    # (raises RuntimeError if the citation id is missing from sources.yaml).
    _ = _load_citation_from_sources_yaml(_BEAR_BOOKLET_CITATION_ID)
    _ = _load_citation_from_sources_yaml(_BEAR_CORRECTION_CITATION_ID)

    logger.info("loading DEA artifact: %s", _DEA_ARTIFACT)
    with _DEA_ARTIFACT.open() as f:
        dea_artifact = json.load(f)
    logger.info("loading bear artifact: %s", _BEAR_ARTIFACT)
    with _BEAR_ARTIFACT.open() as f:
        bear_artifact = json.load(f)

    logger.info("building entity rows + link rows")
    season_definitions = (
        _build_dea_season_definitions(dea_artifact, dea_citation)
        + _build_bear_season_definitions(bear_artifact)
    )
    license_tags = (
        _build_dea_license_tags(dea_artifact, dea_citation)
        + _build_bear_license_tags(bear_artifact)
    )
    license_season_links = (
        _build_dea_license_season_links(dea_artifact)
        + _build_bear_license_season_links(bear_artifact)
    )
    regulation_season_links = (
        _build_dea_regulation_season_links(dea_artifact)
        + _build_bear_regulation_season_links(bear_artifact)
    )
    regulation_license_links = (
        _build_dea_regulation_license_links(dea_artifact)
        + _build_bear_regulation_license_links(bear_artifact)
    )

    logger.info(
        "built: %d season_definition, %d license_tag, %d license_season, "
        "%d regulation_season, %d regulation_license",
        len(season_definitions), len(license_tags),
        len(license_season_links), len(regulation_season_links),
        len(regulation_license_links),
    )

    _assert_season_definition_count_within_guard(len(season_definitions))
    _assert_license_tag_count_within_guard(len(license_tags))
    _assert_license_season_count_within_guard(len(license_season_links))
    _assert_regulation_season_count_within_guard(len(regulation_season_links))
    _assert_regulation_license_count_within_guard(len(regulation_license_links))

    if args.dry_run:
        logger.info("[dry-run] skipping DB writes")
        _log_summary(
            season_definitions, license_tags,
            license_season_links, regulation_season_links, regulation_license_links,
            logger,
        )
        return 0

    with db.connect() as conn:
        for season in season_definitions:
            db.upsert_season_definition(conn, season)
        for tag in license_tags:
            db.upsert_license_tag(conn, tag)
        for ls_link in license_season_links:
            db.write_license_season(conn, ls_link)
        for rs_link in regulation_season_links:
            db.write_regulation_season(conn, rs_link)
        for rl_link in regulation_license_links:
            db.write_regulation_license(conn, rl_link)
        conn.commit()

    logger.info(
        "loaded %d season_definition + %d license_tag + %d license_season "
        "+ %d regulation_season + %d regulation_license rows",
        len(season_definitions), len(license_tags),
        len(license_season_links), len(regulation_season_links),
        len(regulation_license_links),
    )
    _log_summary(
        season_definitions, license_tags,
        license_season_links, regulation_season_links, regulation_license_links,
        logger,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
