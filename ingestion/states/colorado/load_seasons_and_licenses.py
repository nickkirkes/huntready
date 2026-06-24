"""Colorado season_definition + license_tag + license_season ingestion adapter.

Reads two extraction artifacts produced by S06.3-S06.4 (big-game and bear) and
writes five tables in one atomic transaction:

1. ``season_definition`` rows — one per unique (species, gmu, season_key),
   shared across link tables. CO species are pre-separated in the artifact
   (mule_deer / whitetail / elk / pronghorn), so there is no deer fan-out at
   this layer (unlike MT, which fans "deer" → mule_deer + whitetail at the
   link-table level). Bear season_definition rows are derived from the bear
   artifact's per-BMU season fields.

2. ``license_tag`` rows — one per artifact license row.

3. ``license_season`` link rows — per ADR-018 §1, this is the per-license
   season-coverage truth.

4. ``regulation_season`` link rows — per regulation_record × unique seasons.

5. ``regulation_license`` link rows — per regulation_record × license_tag.

Three-phase shape
-----------------
Phase 1 (build): read artifacts, derive all entities and link rows entirely
    in-memory. No DB connectivity required. ``--dry-run`` exits here.
Phase 2 (guards): five row-count guards fire BEFORE ``db.connect()``.
    A guard failure aborts with no partial writes.
Phase 3 (write): one atomic ``db.connect()`` / single ``conn.commit()``.

Season Choice (Q20 — RESOLVED 2026-06-23: per-window fan-out)
------------------------------------------------------------
The S06.3 big-game extractor discovered a ``method_letter="X"`` (Season Choice)
code type in CPW hunt codes. Each Season Choice row carries up to three
``season_windows`` (archery / muzzleloader / rifle), one per method the holder
may choose. Q20 was resolved by human decision to the **per-window fan-out**
model: emit one ``season_definition`` per window (weapon_type taken from that
window's method), one ``license_tag`` carrying
``weapon_types=["archery", "muzzleloader", "any_legal_weapon"]``, and
``license_season`` links the tag to all of its seasons.

Zero-season rows and the WARNING they emit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Rows with ``season_windows == []`` or all-null windows produce zero
``season_definition`` rows but still emit one ``license_tag``.  This is not
limited to Season Choice rows: in the 2026 artifact approximately 477
non-Season-Choice hunt codes (mostly female ``-F-`` rifle rows whose season-date
cell was merged into the corresponding male row by the pdfplumber extractor) also
carry empty ``season_windows``.  S06.7 faithfully loads the artifact and emits a
WARNING for every such row via ``_LOGGER.warning`` naming the builder,
``gmu_code``, ``hunt_code``, ``species_group``, and page.  Whether female-sex
license tags should *inherit* the same-GMU / same-season male row's windows is a
documented carry-forward data-modeling question — it is **not** resolved in
S06.7.

``license_tag.draw_spec_key`` is intentionally left NULL — S06.8 backfills
limited-draw spec references once the draw_spec table is populated (mirroring
MT S03.7's posture for S03.8 backfill).

Per ADR-020, ``assert_id_matches`` is called at EVERY per-row entity-construction
site in the ``season_definition`` and ``license_tag`` build functions — to catch
id-slug drift before a bad PK reaches the DB. The three link-table builders are
deliberately NOT instrumented (link tables have no id-text PK; the M1
regression-guard AST test enforces this carve-out).

Per ADR-008 (verbatim discipline), ``verbatim_rule`` on ``season_definition``
and ``license_tag`` is populated from the artifact's ``verbatim_text`` directly
with no normalization other than stripping leading and trailing whitespace.
No layout=True.

Test classes (added in later tasks)
------------------------------------
- ``TestNoLibImports`` — AST guard (ADR-005 state-agnostic-clean).
- ``TestLoadBigGameSections`` / ``TestLoadBearRecords`` — artifact-loader guards.
- ``TestBuildSeasonDefinitions`` / ``TestBuildLicenseTags`` — builder contracts.
- ``TestCountGuards`` — five band guards fire pre-``db.connect()``.
- ``TestMain`` — dry-run smoke-test against committed artifacts.

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/colorado/load_seasons_and_licenses.py

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
from collections import Counter
from pathlib import Path
from typing import Any, Final, NamedTuple, cast, get_args

import yaml

from ingestion.lib import db
from ingestion.lib.drift_guard import assert_id_matches
from ingestion.lib.schema import (
    LicenseSeason,
    LicenseTag,
    RegulationLicense,
    RegulationSeason,
    Residency,
    SeasonDefinition,
    SourceCitation,
    WeaponType,
)

# Re-use the CO jurisdiction-code helper and state constant from the S06.6
# regulation_record loader — do NOT redeclare these.
from states.colorado.load_regulation_records import (
    _STATE,
    _co_gmu_jurisdiction_code,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_COLORADO_DIR = Path(__file__).resolve().parent
_EXTRACTED_DIR = _COLORADO_DIR / "extracted"
_BIG_GAME_ARTIFACT: Final[Path] = _EXTRACTED_DIR / "big-game-2026.json"
_BEAR_ARTIFACT: Final[Path] = _EXTRACTED_DIR / "black-bear-2026.json"
_SOURCES_YAML: Final[Path] = _COLORADO_DIR / "sources.yaml"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LICENSE_YEAR: Final[int] = 2026

# CPW license purchase / application entry point.
# Points at the routing page so the URL survives CPW site rotations without a
# code edit (mirrors MT's ``_PURCHASE_URL`` evergreen convention, OQ-S7-11).
# No deeper apply/purchase URL is recorded in sources.yaml (the YAML tracks
# regulation PDFs and GIS layers, not the transactional portal); the CPW
# "Buy/Apply" portal root is the authoritative evergreen entry point.
_PURCHASE_URL: Final[str] = "https://www.cpw.state.co.us/buyapply"

# Citation ids — must match the ``id:`` fields in sources.yaml ``pdfs:`` section.
_BIG_GAME_CITATION_ID: Final[str] = "co-cpw-big-game-2026-brochure"
_BEAR_CITATION_ID: Final[str] = "co-cpw-big-game-2026-brochure"

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Citation builder
# ---------------------------------------------------------------------------


def _load_citation_from_sources_yaml(citation_id: str) -> SourceCitation:
    """Load a single SourceCitation from the ``pdfs:`` section of sources.yaml.

    This function is intentionally replicated from ``load_regulation_records.py``
    rather than imported, per the adapter self-containment convention: each
    adapter owns its own source-citation deserialization. Importing a private
    function across adapter modules would create a cross-adapter coupling that
    ADR-005 and the ``TestNoLibImports`` AST guard are meant to prevent.

    Raises:
        RuntimeError: if ``citation_id`` is not found in the ``pdfs:`` section.
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
# Artifact loaders
# ---------------------------------------------------------------------------


def _load_big_game_sections() -> list[dict[str, Any]]:
    """Load and validate the big-game extraction artifact.

    Returns:
        The top-level JSON array from ``big-game-2026.json`` — a list of
        section dicts as produced by ``extract_big_game.py``.

    Raises:
        RuntimeError: if the artifact file is missing or is not a JSON array.
    """
    _LOGGER.info("loading big-game artifact: %s", _BIG_GAME_ARTIFACT)
    with _BIG_GAME_ARTIFACT.open() as f:
        data: Any = json.load(f)
    if not isinstance(data, list):
        raise RuntimeError(
            f"big-game artifact at {_BIG_GAME_ARTIFACT} is not a JSON array "
            f"(got {type(data).__name__}); "
            "re-run extract_big_game.py and inspect the artifact"
        )
    return data  # type: ignore[return-value]


def _load_bear_records() -> list[dict[str, Any]]:
    """Load and validate the bear extraction artifact.

    The bear artifact is a flat list with a ``record_type`` discriminator
    (NOT the MT-style top-level ``sources``/``rows`` lookup dict). Each element
    is a dict with a ``record_type`` key in
    ``{"section", "statewide_rule", "reporting_obligation"}``.

    Returns:
        The top-level JSON array from ``black-bear-2026.json``.

    Raises:
        RuntimeError: if the artifact file is missing or is not a JSON array.
    """
    _LOGGER.info("loading bear artifact: %s", _BEAR_ARTIFACT)
    with _BEAR_ARTIFACT.open() as f:
        data: Any = json.load(f)
    if not isinstance(data, list):
        raise RuntimeError(
            f"bear artifact at {_BEAR_ARTIFACT} is not a JSON array "
            f"(got {type(data).__name__}); "
            "re-run extract_black_bear.py and inspect the artifact"
        )
    return data  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Pure id-derivation and name-rendering functions
#
# These are the SINGLE SOURCE OF TRUTH for season_definition and license_tag
# id construction.  ADR-020 drift_guard.assert_id_matches re-derives ids from
# these functions at every per-row entity-construction site in the builders
# (added in T3/T4) to catch slug drift before a bad PK reaches the DB.
#
# All three functions are pure — they read only their arguments and the module-
# level constant _LICENSE_YEAR.  No I/O.  Bear records and big-game records
# share the same id format (both carry gmu_code / hunt_code / season_code in
# the same schema), so separate bear-specific functions are not needed.
# ---------------------------------------------------------------------------


def _co_season_definition_id(
    species_group: str,
    gmu_code: str,
    hunt_code: str,
    window_index: int,
) -> str:
    """Deterministic season_definition.id constructor for Colorado.

    Format::

        CO-GMU-{int(gmu_code)}-{species_group}-{hunt_code}-w{window_index}-{year}

    ``hunt_code`` (e.g. ``"D-M-001-O1-A"``) is required as a discriminator
    because the same ``(gmu_code, species_group)`` pair can carry multiple
    hunt codes from different method groups, all of which collapse to a single
    ``regulation_record`` row in S06.6 but each need distinct
    ``season_definition`` rows here.  ``window_index`` further discriminates
    within a hunt code when a Season Choice row fans out into archery /
    muzzleloader / rifle windows (Q20 resolution: per-window fan-out model).
    MT instead uses a ``season_key`` string because MT does not have the same
    intra-(HD, species) hunt-code multiplicity.

    Note: ``season_code`` (e.g. ``"O1"``) is NOT encoded in the id — it is
    already embedded in ``hunt_code`` (e.g. ``"D-M-001-O1-A"``), so a separate
    ``season_code`` parameter would be redundant and misleading.

    Args:
        species_group: Artifact-level species label
            (``"mule_deer"`` / ``"whitetail"`` / ``"elk"`` / ``"pronghorn"``
            / ``"bear"``).
        gmu_code: Zero-padded GMU string exactly as it appears in the artifact
            (e.g. ``"001"``).  ``int()`` conversion strips leading zeros so
            ``"001"`` and ``"1"`` resolve to the same id.
        hunt_code: Full CPW hunt code (e.g. ``"D-M-001-O1-A"``).
        window_index: Zero-based index of this window within the hunt code's
            ``season_windows`` list.  Always 0 for non-Season-Choice rows.

    Returns:
        A deterministic, collision-free id string suitable as a Postgres
        ``text`` primary key.
    """
    return (
        f"CO-GMU-{int(gmu_code)}-{species_group}-{hunt_code}"
        f"-w{window_index}-{_LICENSE_YEAR}"
    )


def _co_license_tag_id(
    species_group: str,
    gmu_code: str,
    hunt_code: str,
) -> str:
    """Deterministic license_tag.id constructor for Colorado.

    Format::

        CO-GMU-{int(gmu_code)}-{species_group}-{hunt_code}-{year}

    One license_tag is emitted per hunt code regardless of how many season
    windows it spans (Season Choice or otherwise).  All windows for a hunt
    code are linked to the same tag via ``license_season`` rows.

    Args:
        species_group: Artifact-level species label.
        gmu_code: Zero-padded GMU string from the artifact.
        hunt_code: Full CPW hunt code (e.g. ``"D-M-001-O1-A"``).

    Returns:
        A deterministic id string suitable as a Postgres ``text`` primary key.
    """
    return f"CO-GMU-{int(gmu_code)}-{species_group}-{hunt_code}-{_LICENSE_YEAR}"


def _co_season_name(
    species_group: str,
    method_group: str,
    season_code: str,
) -> str:
    """Deterministic human-readable season_definition.name for Colorado.

    Mirrors MT's ``_SEASON_NAME_BY_KEY`` lookup but as a pure function because
    CO's season-name space is much larger (many hunt codes × many GMUs) and a
    static dict would be unmanageable.

    Format::

        {Title Case species} {Title Case method_group} ({season_code})

    Examples::

        _co_season_name("mule_deer", "archery", "O1") → "Mule Deer Archery (O1)"
        _co_season_name("elk", "any_legal_weapon", "R1") → "Elk Any Legal Weapon (R1)"
        _co_season_name("bear", "rifle", "R2") → "Bear Rifle (R2)"

    Args:
        species_group: Artifact-level species label with underscores
            (e.g. ``"mule_deer"``).
        method_group: Weapon/method category with underscores
            (e.g. ``"archery"``, ``"any_legal_weapon"``).
        season_code: CPW season-period code (e.g. ``"O1"``).

    Returns:
        A human-readable name string.
    """
    species_title = species_group.replace("_", " ").title()
    method_title = method_group.replace("_", " ").title()
    return f"{species_title} {method_title} ({season_code})"


# ---------------------------------------------------------------------------
# Window parser (T3)
# ---------------------------------------------------------------------------


def _normalize_co_month_fragment(fragment: str) -> str:
    """Normalize a CPW dotted month-day fragment into ``strptime``-compatible form.

    CPW's artifact fragments are already split (e.g. ``"Sept. 2"``, ``"Oct. 24"``).
    This function:

    1. Strips a trailing dot from the month abbreviation
       (``"Sept."`` → ``"Sept"``, ``"Oct."`` → ``"Oct"``).
    2. Maps ``"Sept"`` → ``"Sep"`` because ``strptime %b`` requires the standard
       3-character English abbreviation; CPW uses the 4-letter form.
    3. Collapses any internal whitespace so ``"Oct.  24"`` (double-space artifact)
       is handled safely.

    Only the month abbreviations observed in the artifact are handled:
    ``Aug.``, ``Sept.``, ``Oct.``, ``Nov.``, ``Dec.``, ``Jan.``  No other
    normalization is applied; an unrecognized abbreviation will propagate to
    ``strptime`` and cause a ``ValueError`` (fail-loud by design).

    Args:
        fragment: A single date fragment from the artifact, e.g. ``"Sept. 2"``.

    Returns:
        A normalized string parseable via ``datetime.strptime(frag, "%b %d")``,
        e.g. ``"Sep 2"``.
    """
    # Strip an explicit ", YYYY" year suffix that the extractor embeds on some
    # year-crossing end_date fragments (e.g. "Jan. 31, 2027").  The year-wrap
    # logic in _parse_co_window re-derives the correct year via calendar
    # comparison, so the embedded year is redundant and would break strptime.
    normalized = re.sub(r",\s*\d{4}\s*$", "", fragment).strip()
    normalized = normalized.replace(".", "").strip()
    # Collapse any multi-space runs that may follow dot-stripping or newlines
    # embedded in raw_text-derived fragments.
    normalized = re.sub(r"\s+", " ", normalized)
    # Map 4-letter "Sept" → 3-letter "Sep" for strptime %b compatibility.
    normalized = re.sub(r"\bSept\b", "Sep", normalized)
    return normalized


def _parse_co_window(
    window: dict[str, Any], license_year: int
) -> tuple[datetime.date, datetime.date] | None:
    """Parse one entry of a CO artifact row's ``season_windows`` list.

    CO ``season_windows`` entries are dicts with three keys::

        {"start_date": "Sept. 2", "end_date": "Sept. 30", "raw_text": "Sept. 2–30"}

    Unlike MT, where the window is a hyphen-joined single string that must be
    split, CO's extractor already provides ``start_date`` and ``end_date`` as
    separate pre-split fragments.  Each fragment is a dotted abbreviated month
    followed by a day number with no year, e.g. ``"Sept. 2"``, ``"Oct. 24"``,
    ``"Jan. 15"``.

    Month abbreviations observed in the CO 2026 artifact:
    - ``"Aug."``   → normalized to ``"Aug"``  (standard; strptime-compatible as-is)
    - ``"Sept."``  → normalized to ``"Sep"``  (4-letter; must map to 3-letter)
    - ``"Oct."``   → normalized to ``"Oct"``  (standard)
    - ``"Nov."``   → normalized to ``"Nov"``  (standard)
    - ``"Dec."``   → normalized to ``"Dec"``  (standard)
    - ``"Jan."``   → normalized to ``"Jan"``  (standard)

    Null case:
        When ``start_date`` or ``end_date`` is ``None`` (extractor garbage rows,
        e.g. ``raw_text="New"``), returns ``None``.  The caller is expected to
        skip the window with a WARNING log.  This is NOT a fail-loud case because
        null windows are a known, bounded extractor artifact (~36 rows in the
        2026 artifact).

    Year-wrap:
        Seasons that span a calendar year boundary (e.g. open in December,
        close in January) are detected by comparing the parsed month/day of
        ``end_date`` against ``opens``.  If ``closes < opens``, ``closes`` is
        re-parsed with ``license_year + 1``.  Mirrors MT's year-wrap logic in
        ``load_seasons_and_licenses._parse_window``.

    Fail-loud:
        A present-but-malformed non-null fragment raises ``ValueError`` naming
        the offending fragment and the ``raw_text`` context.  This is a real
        defect (distinct from the null-garbage case) and must not be silenced.

    Args:
        window: One element of a row's ``season_windows`` list.
        license_year: The regulation year (e.g. 2026).  Used to attach a year
            to both parsed dates and for year-wrap detection.

    Returns:
        ``(opens, closes)`` as ``datetime.date`` objects, or ``None`` if either
        ``start_date`` or ``end_date`` is ``None``.

    Raises:
        ValueError: if a non-null fragment cannot be parsed as a date.
    """
    start_raw: str | None = window.get("start_date")
    end_raw: str | None = window.get("end_date")

    if start_raw is None or end_raw is None:
        return None

    raw_text: str = window.get("raw_text", "<no raw_text>")

    try:
        opens_frag = _normalize_co_month_fragment(start_raw)
        opens = datetime.datetime.strptime(
            f"{opens_frag} {license_year}", "%b %d %Y"
        ).date()
    except ValueError as exc:
        raise ValueError(
            f"_parse_co_window: unparseable start_date fragment {start_raw!r} "
            f"(raw_text={raw_text!r}): {exc}"
        ) from exc

    try:
        closes_frag = _normalize_co_month_fragment(end_raw)
        closes = datetime.datetime.strptime(
            f"{closes_frag} {license_year}", "%b %d %Y"
        ).date()
    except ValueError as exc:
        raise ValueError(
            f"_parse_co_window: unparseable end_date fragment {end_raw!r} "
            f"(raw_text={raw_text!r}): {exc}"
        ) from exc

    # Year-wrap: season crosses a calendar year boundary (e.g. opens Dec, closes Jan).
    if closes < opens:
        closes = datetime.datetime.strptime(
            f"{closes_frag} {license_year + 1}", "%b %d %Y"
        ).date()

    return (opens, closes)


# ---------------------------------------------------------------------------
# Pure mapping helpers (T4)
#
# All five functions are pure — they read only their arguments and module-level
# Literal types. No I/O. Fail-loud on any unrecognized input value (ValueError).
# ---------------------------------------------------------------------------


def _co_big_game_license_kind(list_value: str | None) -> str:
    """Map a CPW big-game artifact ``list_value`` to a ``LicenseTag.kind`` Literal.

    CPW encodes the draw tier of a hunt opportunity in the ``list_value`` field
    of every big-game artifact row.  The mapping is::

        "A"  → "limited_draw"   — primary-draw licenses (resident + NR draw pools)
        "B"  → "over_the_counter" — OTC licenses available after-draw; no application
        "C"  → "limited_draw"   — Season Choice (method X) licenses; still draw-
                                   required despite the multi-method flexibility

    ``None`` case:
        Artifact evidence — exactly **one** row in the 2026 big-game artifact
        carries ``list_value=None``: elk GMU 214 W4 rifle (``E-F-214-W4-R``,
        page 51).  The row has no quota, no application deadline, a normal rifle
        season window (Dec. 5–9), and ``weapon_types=["any_legal_weapon"]``.
        The ``W4`` season code ("winter") is reserved for limited late-season
        tags.  Contextual evidence (W4 = late limited season; no OTC indicator)
        points to ``"limited_draw"``.  Mapped accordingly with documentation.

    NOTE: ``apply_by`` is null on every CO big-game row.  Do NOT inspect it
    for kind classification (unlike MT's DEA where ``apply_by`` was the OTC
    discriminator).  CO's OTC tiers are entirely encoded in ``list_value``.

    Classification is driven entirely by ``list_value``; ``season_code`` plays no
    role (the ``None`` case is resolved by ``list_value`` alone), so it is not a
    parameter — a kind decision never depends on the season code.

    Args:
        list_value: The artifact ``list_value`` field (``"A"``, ``"B"``, ``"C"``,
            or ``None`` — the full domain observed in the 2026 artifact).

    Returns:
        A ``LicenseTag.kind`` Literal value.

    Raises:
        ValueError: if ``list_value`` is not in the known domain.
    """
    if list_value == "A":
        # Primary draw license — resident + NR draw pool application required.
        return "limited_draw"
    if list_value == "B":
        # Over-the-counter license — available after draw closes, no application.
        return "over_the_counter"
    if list_value == "C":
        # Season Choice (method_letter="X") — still draw-required; multi-method
        # flexibility granted at time of use, not at application.
        return "limited_draw"
    if list_value is None:
        # Exactly one row observed in the 2026 artifact: E-F-214-W4-R (elk GMU 214
        # W4 late rifle, page 51). No quota/apply_by; W4 = limited late season.
        # Mapped to limited_draw based on W4 contextual evidence.
        return "limited_draw"
    raise ValueError(
        f"_co_big_game_license_kind: unrecognized list_value={list_value!r}; "
        "known values: 'A', 'B', 'C', None"
    )


def _co_bear_license_kind(license_kind: str) -> str:
    """Map a CPW bear artifact section ``license_kind`` to a ``LicenseTag.kind`` Literal.

    CPW bear sections carry a section-level ``license_kind`` field that is more
    granular than the shared schema's ``LicenseTag.kind`` Literal::

        "limited_draw"      → "limited_draw"   — primary bear draw (Lists A/B)
        "over_the_counter"  → "over_the_counter" — standard OTC bear license
        "add_on_otc"        → "over_the_counter" — add-on OTC; same schema kind
        "plains_otc"        → "over_the_counter" — plains-region OTC variant
        "private_land_otc"  → "over_the_counter" — private-land OTC variant

    All OTC variants collapse to ``"over_the_counter"`` because the distinction
    between standard, add-on, plains, and private-land OTC is encoded in the
    season / GMU / hunt-code fields, not in the license kind taxonomy.

    Args:
        license_kind: The artifact ``license_kind`` field from a bear section dict.

    Returns:
        A ``LicenseTag.kind`` Literal value.

    Raises:
        ValueError: if ``license_kind`` is not in the known domain.
    """
    if license_kind == "limited_draw":
        return "limited_draw"
    if license_kind in ("over_the_counter", "add_on_otc", "plains_otc", "private_land_otc"):
        return "over_the_counter"
    raise ValueError(
        f"_co_bear_license_kind: unrecognized license_kind={license_kind!r}; "
        "known values: 'limited_draw', 'over_the_counter', 'add_on_otc', "
        "'plains_otc', 'private_land_otc'"
    )


def _co_residency(scope: str) -> Residency:
    """Validate and cast a residency string to the ``Residency`` Literal type.

    CO V1 artifact evidence:
    - Big-game ``residency_scope``: ``"both"`` and ``"nonresident"`` (section-level)
    - Bear ``residency_scope``: ``"both"`` (all sections)
    - ``"resident"``-only rows are not present in the 2026 CO artifact but are
      valid per the Literal definition and will pass through if they appear in
      a future year.

    Args:
        scope: The raw ``residency_scope`` string from the artifact.

    Returns:
        The same string cast to ``Residency``.

    Raises:
        ValueError: if ``scope`` is not a member of the ``Residency`` Literal.
    """
    valid = get_args(Residency)  # ("resident", "nonresident", "both")
    if scope not in valid:
        raise ValueError(
            f"_co_residency: unrecognized scope={scope!r}; "
            f"valid Residency values: {valid}"
        )
    return cast(Residency, scope)


def _co_window_weapon_type(row: dict[str, Any], window_index: int) -> WeaponType:
    """Return the ``WeaponType`` for a specific window of a big-game or bear row.

    **X-detection field choice — artifact evidence:**
    ``method_letter`` is the reliable discriminator.  All Season Choice rows
    carry ``method_letter="X"`` and ``len(weapon_types)==3``.  All non-Season-
    Choice rows carry a single-letter method (``"A"`` archery, ``"M"``
    muzzleloader, ``"R"`` rifle, ``""`` empty for statewide-style rows) and
    ``len(weapon_types)==1``.  Both checks are equivalent in the 2026 artifact;
    ``len(weapon_types)==1`` is used as the primary branch because it is more
    robust against a hypothetical ``method_letter=""`` edge case.

    Branch logic::

        len(weapon_types) == 1  → return weapon_types[0]   (any non-X row)
        len(weapon_types) >  1  → return weapon_types[window_index]  (X / Season Choice)

    For Season Choice (X) rows, the per-window weapon_types order is:
    ``["archery", "muzzleloader", "any_legal_weapon"]``, matching the
    ``season_windows`` list order produced by the extractor.  ``window_index``
    selects the correct weapon for each fan-out season_definition.

    Args:
        row: A big-game or bear artifact row dict containing ``weapon_types``
            (a ``list[str]``) and ``method_letter`` (a ``str``).
        window_index: Zero-based index into ``row["season_windows"]``, matching
            the ``window_index`` argument passed to ``_co_season_definition_id``.

    Returns:
        A ``WeaponType`` Literal value.

    Raises:
        ValueError: if the resolved weapon type is not in the ``WeaponType``
            Literal, or if ``window_index`` is out of range for multi-weapon rows.
        IndexError: if ``weapon_types`` is empty (extractor contract violation).
    """
    weapon_types: list[str] = row["weapon_types"]
    if not weapon_types:
        raise ValueError(
            "_co_window_weapon_type: empty/missing weapon_types for "
            f"hunt_code={row.get('hunt_code')!r} gmu_code={row.get('gmu_code')!r}; "
            "extractor contract violation — every row must carry at least one weapon_type"
        )
    if len(weapon_types) == 1:
        resolved = weapon_types[0]
    else:
        # Season Choice (method_letter="X"): weapon_types has one entry per window.
        if window_index >= len(weapon_types):
            raise ValueError(
                f"_co_window_weapon_type: window_index={window_index} is out of range "
                f"for weapon_types (len={len(weapon_types)}) on "
                f"hunt_code={row.get('hunt_code')!r} gmu_code={row.get('gmu_code')!r}"
            )
        resolved = weapon_types[window_index]

    valid_weapon_types = get_args(WeaponType)
    if resolved not in valid_weapon_types:
        raise ValueError(
            f"_co_window_weapon_type: resolved weapon_type={resolved!r} is not "
            f"a valid WeaponType; valid values: {valid_weapon_types}"
        )
    return cast(WeaponType, resolved)


def _select_co_verbatim_rule(row: dict[str, Any], section: dict[str, Any]) -> str:
    """Select the source-faithful ``verbatim_rule`` for a CO season_definition or license_tag.

    Fallback chain (mirrors MT's ``_select_season_verbatim_rule`` from
    ``states/montana/load_seasons_and_licenses.py:794``):

    1. Row ``extras`` — if non-empty after stripping leading and trailing whitespace.
       Row-level extras carry the most specific, per-hunt-code context.
    2. Section ``verbatim_text`` — the full section text captured by the extractor.
       Present on every section (extraction discipline guarantee).
    3. Raises ``ValueError`` if both are empty — a data-contract violation.

    Per ADR-008 (verbatim discipline): stripping leading and trailing whitespace.
    No other normalization.  No ``layout=True``.

    Args:
        row: A big-game or bear artifact row dict with optional ``"extras"`` key.
        section: The parent section dict with a ``"verbatim_text"`` key.

    Returns:
        A non-empty verbatim string suitable for ``verbatim_rule``.

    Raises:
        ValueError: if both row ``extras`` and section ``verbatim_text`` are
            absent or empty after stripping.
    """
    extras = row.get("extras")
    if isinstance(extras, str) and extras.strip():
        return extras.strip()

    verbatim_text = section.get("verbatim_text", "")
    if isinstance(verbatim_text, str) and verbatim_text.strip():
        return verbatim_text.strip()

    raise ValueError(
        "_select_co_verbatim_rule: both row 'extras' and section 'verbatim_text' "
        "are absent or empty; hunt_code="
        f"{row.get('hunt_code')!r}, gmu_code={section.get('gmu_code')!r}"
    )


# ---------------------------------------------------------------------------
# Quota-range parser (shared by big-game and bear license_tag builders)
# ---------------------------------------------------------------------------


def _parse_quota_range(raw: str | None) -> tuple[int, int] | None:
    """Parse a CPW quota-range string like ``"1-50"`` into ``(1, 50)``.

    Returns:
        ``None`` for None input or whitespace-only strings.
        ``(min_quota, max_quota)`` as integers, allowing comma thousand-separators.

    Raises:
        ValueError: if a non-null, non-empty string cannot be split into exactly
            two integer halves, or if either half is non-numeric.  Fail-loud.
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


# ---------------------------------------------------------------------------
# Lossy-dedup content comparison (single source of truth for all 4 builders)
# ---------------------------------------------------------------------------


def _season_def_lossy_diffs(
    existing: SeasonDefinition, new: SeasonDefinition
) -> list[str]:
    """Regulatory-content fields whose disagreement across a same-id dedup
    collision signals real data drift worth a WARNING.

    Shared by both season_definition builders so the comparison set cannot
    drift between big-game and bear.

    ``page_reference`` is deliberately EXCLUDED: the same season legitimately
    recurs across multiple GMU-section pages (157 such benign collisions in the
    2026 artifact), so a page-only difference is provenance metadata, not a
    regulation change, and warning on it would drown the real signal.
    """
    diffs: list[str] = []
    if existing.opens != new.opens:
        diffs.append(f"opens: {existing.opens!r} vs {new.opens!r}")
    if existing.closes != new.closes:
        diffs.append(f"closes: {existing.closes!r} vs {new.closes!r}")
    if existing.weapon_type != new.weapon_type:
        diffs.append(f"weapon_type: {existing.weapon_type!r} vs {new.weapon_type!r}")
    if existing.residency != new.residency:
        diffs.append(f"residency: {existing.residency!r} vs {new.residency!r}")
    if existing.verbatim_rule != new.verbatim_rule:
        diffs.append("verbatim_rule differs")
    return diffs


def _license_tag_lossy_diffs(existing: LicenseTag, new: LicenseTag) -> list[str]:
    """Regulatory-content fields whose disagreement across a same-id license_tag
    dedup collision signals real data drift worth a WARNING.

    Shared by both license_tag builders. The id-encoded fields (species,
    gmu, hunt_code via ``license_code``), the constant ``purchase_url``, the
    always-``None`` ``draw_spec_key``, and the shared ``source`` citation cannot
    meaningfully differ for the same id and are not compared.
    """
    diffs: list[str] = []
    if existing.kind != new.kind:
        diffs.append(f"kind: {existing.kind!r} vs {new.kind!r}")
    if existing.quota != new.quota:
        diffs.append(f"quota: {existing.quota!r} vs {new.quota!r}")
    if existing.quota_range != new.quota_range:
        diffs.append(f"quota_range: {existing.quota_range!r} vs {new.quota_range!r}")
    if existing.weapon_types != new.weapon_types:
        diffs.append(f"weapon_types: {existing.weapon_types!r} vs {new.weapon_types!r}")
    if existing.residency != new.residency:
        diffs.append(f"residency: {existing.residency!r} vs {new.residency!r}")
    if existing.verbatim_rule != new.verbatim_rule:
        diffs.append("verbatim_rule differs")
    return diffs


# ---------------------------------------------------------------------------
# Big-game season_definition builder
# ---------------------------------------------------------------------------


def _build_big_game_season_definitions(
    sections: list[dict[str, Any]],
    citation: SourceCitation,
) -> list[SeasonDefinition]:
    """Build unique SeasonDefinition entities from the big-game extraction artifact.

    Iterates sections → rows → season_windows (by index).  One
    ``SeasonDefinition`` is emitted per unique ``_co_season_definition_id`` —
    first-occurrence-wins deduplication (keyed by id).

    Season Choice rows (``method_letter="X"``) can carry up to three windows;
    each window fans out into its own ``SeasonDefinition`` with the
    window-specific weapon_type (Q20 per-window fan-out resolution).

    Null-window skip: windows whose ``start_date`` or ``end_date`` is ``None``
    (known extractor garbage, ~36 rows in the 2026 artifact) are logged at
    WARNING level and skipped — they do NOT trigger a fail-loud error.

    ADR-020: ``assert_id_matches`` is called immediately after every
    ``SeasonDefinition`` construction, before the dedup check.

    Args:
        sections: Top-level JSON array from ``big-game-2026.json``.
        citation: The ``SourceCitation`` for the big-game brochure.

    Returns:
        Deduplicated list of ``SeasonDefinition`` instances in first-occurrence
        order.
    """
    seen: dict[str, SeasonDefinition] = {}

    for section in sections:
        species_group: str = section["species_group"]
        method_group: str = section["method_group"]
        section_residency: str = section.get("residency_scope") or "both"

        for row in section["rows"]:
            gmu_code: str = row["gmu_code"]
            hunt_code: str = row["hunt_code"]
            season_code: str = row["season_code"]

            # Skip blank-GMU rows (the S06.6-known single blank-GMU elk section;
            # no id can be constructed without a valid gmu_code).
            if not gmu_code.strip() or not hunt_code.strip():
                _LOGGER.warning(
                    "_build_big_game_season_definitions: skipping row with empty "
                    "gmu_code or hunt_code in section species=%r section_gmu=%r",
                    species_group,
                    section.get("gmu_code"),
                )
                continue

            row_residency: str | None = row.get("residency_scope")
            residency_str = row_residency if row_residency else section_residency

            raw_weapon_types_bg: list[str] = row.get("weapon_types") or []
            if not raw_weapon_types_bg:
                raise RuntimeError(
                    f"_build_big_game_season_definitions: hunt_code={hunt_code!r} "
                    f"gmu_code={gmu_code!r} has empty/missing weapon_types; "
                    "extractor contract violation"
                )

            seasons_emitted_for_row = 0
            page_ref_bg: dict[str, Any] | None = row.get("page_reference")
            page_ref_bg_str: str | None = (
                f"p.{page_ref_bg['page_num_1based']}" if page_ref_bg else None
            )
            for window_index, window in enumerate(row.get("season_windows", [])):
                parsed = _parse_co_window(window, _LICENSE_YEAR)
                if parsed is None:
                    _LOGGER.warning(
                        "_build_big_game_season_definitions: null window skipped — "
                        "gmu_code=%r hunt_code=%r window_index=%d raw_text=%r",
                        gmu_code,
                        hunt_code,
                        window_index,
                        window.get("raw_text"),
                    )
                    continue

                opens, closes = parsed
                sd_id = _co_season_definition_id(
                    species_group, gmu_code, hunt_code, window_index
                )
                name = _co_season_name(species_group, method_group, season_code)
                weapon_type = _co_window_weapon_type(row, window_index)
                residency = _co_residency(residency_str)
                verbatim_rule = _select_co_verbatim_rule(row, section)
                row_citation = citation.model_copy(
                    update={"page_reference": page_ref_bg_str}
                )

                sd = SeasonDefinition(
                    id=sd_id,
                    name=name,
                    opens=opens,
                    closes=closes,
                    weapon_type=weapon_type,
                    residency=residency,
                    closure_predicate=None,
                    verbatim_rule=verbatim_rule,
                    page_reference=page_ref_bg_str,
                    source=row_citation,
                )
                # ADR-020: construction-time drift guard — re-derive the id from
                # structured fields and assert it matches the entity's stored id.
                assert_id_matches(
                    sd.id,
                    _co_season_definition_id(
                        species_group, gmu_code, hunt_code, window_index
                    ),
                    helper_name="_build_big_game_season_definitions",
                    context={
                        "gmu_code": gmu_code,
                        "hunt_code": hunt_code,
                        "window_index": window_index,
                    },
                )
                # First-occurrence-wins dedup; warn on lossy collisions.
                if sd_id not in seen:
                    seen[sd_id] = sd
                else:
                    existing = seen[sd_id]
                    diffs = _season_def_lossy_diffs(existing, sd)
                    if diffs:
                        _LOGGER.warning(
                            "_build_big_game_season_definitions: lossy dedup — "
                            "id=%r already seen with different fields; keeping first "
                            "occurrence. page=%r diffs: %s",
                            sd_id,
                            page_ref_bg_str,
                            "; ".join(diffs),
                        )
                seasons_emitted_for_row += 1

            if seasons_emitted_for_row == 0:
                _LOGGER.warning(
                    "_build_big_game_season_definitions: row produced no "
                    "season_definition (empty/all-null season_windows) — "
                    "gmu_code=%r hunt_code=%r species=%r page=%r",
                    gmu_code,
                    hunt_code,
                    species_group,
                    page_ref_bg_str,
                )

    return list(seen.values())


# ---------------------------------------------------------------------------
# Big-game license_tag builder
# ---------------------------------------------------------------------------


def _build_big_game_license_tags(
    sections: list[dict[str, Any]],
    citation: SourceCitation,
) -> list[LicenseTag]:
    """Build unique LicenseTag entities from the big-game extraction artifact.

    One ``LicenseTag`` is emitted per unique ``_co_license_tag_id`` — first-
    occurrence-wins deduplication (keyed by id).  Season Choice (X) rows emit
    one tag covering all three windows; the ``weapon_types`` field carries all
    three weapon types (``["archery", "muzzleloader", "any_legal_weapon"]``).

    ``weapon_types`` is validated: each entry must be a member of the
    ``WeaponType`` Literal; an unrecognized value raises ``ValueError``.

    ADR-020: ``assert_id_matches`` is called immediately after every
    ``LicenseTag`` construction, before the dedup check.

    Args:
        sections: Top-level JSON array from ``big-game-2026.json``.
        citation: The ``SourceCitation`` for the big-game brochure.

    Returns:
        Deduplicated list of ``LicenseTag`` instances in first-occurrence order.
    """
    valid_weapon_types = get_args(WeaponType)
    seen: dict[str, LicenseTag] = {}

    for section in sections:
        species_group: str = section["species_group"]
        section_residency: str = section.get("residency_scope") or "both"

        for row in section["rows"]:
            gmu_code: str = row["gmu_code"]
            hunt_code: str = row["hunt_code"]

            # Skip blank-GMU rows (the S06.6-known single blank-GMU elk section;
            # no id can be constructed without a valid gmu_code).
            if not gmu_code.strip() or not hunt_code.strip():
                _LOGGER.warning(
                    "_build_big_game_license_tags: skipping row with empty "
                    "gmu_code or hunt_code in section species=%r section_gmu=%r",
                    species_group,
                    section.get("gmu_code"),
                )
                continue

            row_residency: str | None = row.get("residency_scope")
            residency_str = row_residency if row_residency else section_residency

            lt_id = _co_license_tag_id(species_group, gmu_code, hunt_code)

            # Validate all weapon_types against the WeaponType Literal.
            raw_weapon_types: list[str] = row.get("weapon_types") or []
            if not raw_weapon_types:
                raise RuntimeError(
                    f"_build_big_game_license_tags: hunt_code={hunt_code!r} "
                    f"gmu_code={gmu_code!r} has empty/missing weapon_types; "
                    "extractor contract violation"
                )
            for wt in raw_weapon_types:
                if wt not in valid_weapon_types:
                    raise ValueError(
                        f"_build_big_game_license_tags: unrecognized weapon_type "
                        f"{wt!r} on hunt_code={hunt_code!r}; "
                        f"valid values: {valid_weapon_types}"
                    )
            weapon_types = cast(list[WeaponType], raw_weapon_types)

            # Name: "{species} {hunt_code}" — readable and unique per tag.
            species_title = species_group.replace("_", " ").title()
            name = f"{species_title} {hunt_code}"

            page_ref: dict[str, Any] | None = row.get("page_reference")
            page_ref_str: str | None = (
                f"p.{page_ref['page_num_1based']}" if page_ref else None
            )
            row_citation = citation.model_copy(
                update={"page_reference": page_ref_str}
            )

            lt = LicenseTag(
                id=lt_id,
                license_code=hunt_code,
                name=name,
                kind=_co_big_game_license_kind(  # type: ignore[arg-type]
                    row.get("list_value")
                ),
                species=species_group,
                weapon_types=weapon_types,
                residency=_co_residency(residency_str),
                quota=row.get("quota"),
                quota_range=_parse_quota_range(row.get("quota_range")),
                purchase_url=_PURCHASE_URL,
                draw_spec_key=None,
                reserved_pools=[],
                verbatim_rule=_select_co_verbatim_rule(row, section),
                source=row_citation,
            )
            # ADR-020: construction-time drift guard — re-derive the id from
            # structured fields and assert it matches the entity's stored id.
            assert_id_matches(
                lt.id,
                _co_license_tag_id(species_group, gmu_code, hunt_code),
                helper_name="_build_big_game_license_tags",
                context={
                    "gmu_code": gmu_code,
                    "hunt_code": hunt_code,
                },
            )
            # First-occurrence-wins dedup; warn on lossy collisions.
            if lt_id not in seen:
                seen[lt_id] = lt
            else:
                existing_lt = seen[lt_id]
                lt_diffs = _license_tag_lossy_diffs(existing_lt, lt)
                if lt_diffs:
                    _LOGGER.warning(
                        "_build_big_game_license_tags: lossy dedup — "
                        "id=%r already seen with different fields; keeping first "
                        "occurrence. page=%r diffs: %s",
                        lt_id,
                        page_ref_str,
                        "; ".join(lt_diffs),
                    )

    return list(seen.values())


# ---------------------------------------------------------------------------
# Bear season_definition builder
# ---------------------------------------------------------------------------


def _build_bear_season_definitions(
    records: list[dict[str, Any]],
    citation: SourceCitation,
) -> list[SeasonDefinition]:
    """Build unique SeasonDefinition entities from the bear extraction artifact.

    The bear artifact is a **flat list** with a ``record_type`` discriminator.
    Only records with ``record_type == "section"`` carry rows; statewide_rule
    and reporting_obligation records are skipped entirely.

    Bear rows carry ``species_group="black_bear"`` in the artifact; the DB
    species key is ``"bear"`` — this builder passes ``"bear"`` to every id /
    name function (not the raw artifact value).

    artifact ``quota_range`` observation:
        Every bear row in the 2026 artifact carries ``quota_range=None``.
        No parsing is needed; ``SeasonDefinition`` has no quota_range field so
        this is informational only.

    artifact ``season_windows``:
        Most bear rows carry 1 window; some carry 4 (multiple non-overlapping
        hunt periods for the same hunt code). Each window fans out into its own
        ``SeasonDefinition`` — the same per-window fan-out model used for the
        big-game Season Choice path (Q20 resolution).

    No Season Choice (X) rows exist in the 2026 CO bear artifact; the
    ``_co_window_weapon_type`` helper handles both the single-weapon (len==1)
    and multi-weapon (len>1) branches uniformly.

    ADR-020: ``assert_id_matches`` is called immediately after every
    ``SeasonDefinition`` construction, before the dedup check.

    Args:
        records: Top-level JSON array from ``black-bear-2026.json``.
        citation: The ``SourceCitation`` for the big-game brochure.

    Returns:
        Deduplicated list of ``SeasonDefinition`` instances in first-occurrence
        order.
    """
    seen: dict[str, SeasonDefinition] = {}
    # Bear DB species key — artifact value is "black_bear" but every id, name,
    # and DB write must use "bear". See known-pitfalls.md "Bear DB species_group".
    species_group = "bear"

    for record in records:
        if record.get("record_type") != "section":
            continue

        method_group: str = record["method_group"]
        section_residency: str = record.get("residency_scope") or "both"

        for row in record["rows"]:
            gmu_code: str = row["gmu_code"]
            hunt_code: str = row["hunt_code"]
            season_code: str = row["season_code"]

            # Skip blank-GMU rows (defensive — none expected in CO bear artifact).
            if not gmu_code.strip() or not hunt_code.strip():
                _LOGGER.warning(
                    "_build_bear_season_definitions: skipping row with empty "
                    "gmu_code or hunt_code in section gmu=%r method=%r",
                    record.get("gmu_code"),
                    method_group,
                )
                continue

            row_residency: str | None = row.get("residency_scope")
            residency_str = row_residency if row_residency else section_residency

            raw_weapon_types_bear: list[str] = row.get("weapon_types") or []
            if not raw_weapon_types_bear:
                raise RuntimeError(
                    f"_build_bear_season_definitions: hunt_code={hunt_code!r} "
                    f"gmu_code={gmu_code!r} has empty/missing weapon_types; "
                    "extractor contract violation"
                )

            seasons_emitted_for_bear_row = 0
            page_ref_bear: dict[str, Any] | None = row.get("page_reference")
            page_ref_bear_str: str | None = (
                f"p.{page_ref_bear['page_num_1based']}" if page_ref_bear else None
            )
            for window_index, window in enumerate(row.get("season_windows", [])):
                parsed = _parse_co_window(window, _LICENSE_YEAR)
                if parsed is None:
                    _LOGGER.warning(
                        "_build_bear_season_definitions: null window skipped — "
                        "gmu_code=%r hunt_code=%r window_index=%d raw_text=%r",
                        gmu_code,
                        hunt_code,
                        window_index,
                        window.get("raw_text"),
                    )
                    continue

                opens, closes = parsed
                sd_id = _co_season_definition_id(
                    species_group, gmu_code, hunt_code, window_index
                )
                name = _co_season_name(species_group, method_group, season_code)
                weapon_type = _co_window_weapon_type(row, window_index)
                residency = _co_residency(residency_str)
                verbatim_rule = _select_co_verbatim_rule(row, record)
                row_citation = citation.model_copy(
                    update={"page_reference": page_ref_bear_str}
                )

                sd = SeasonDefinition(
                    id=sd_id,
                    name=name,
                    opens=opens,
                    closes=closes,
                    weapon_type=weapon_type,
                    residency=residency,
                    closure_predicate=None,
                    verbatim_rule=verbatim_rule,
                    page_reference=page_ref_bear_str,
                    source=row_citation,
                )
                # ADR-020: construction-time drift guard — re-derive the id from
                # structured fields and assert it matches the entity's stored id.
                assert_id_matches(
                    sd.id,
                    _co_season_definition_id(
                        species_group, gmu_code, hunt_code, window_index
                    ),
                    helper_name="_build_bear_season_definitions",
                    context={
                        "gmu_code": gmu_code,
                        "hunt_code": hunt_code,
                        "window_index": window_index,
                    },
                )
                # First-occurrence-wins dedup; warn on lossy collisions.
                if sd_id not in seen:
                    seen[sd_id] = sd
                else:
                    existing_bear = seen[sd_id]
                    bear_diffs = _season_def_lossy_diffs(existing_bear, sd)
                    if bear_diffs:
                        _LOGGER.warning(
                            "_build_bear_season_definitions: lossy dedup — "
                            "id=%r already seen with different fields; keeping first "
                            "occurrence. page=%r diffs: %s",
                            sd_id,
                            page_ref_bear_str,
                            "; ".join(bear_diffs),
                        )
                seasons_emitted_for_bear_row += 1

            if seasons_emitted_for_bear_row == 0:
                _LOGGER.warning(
                    "_build_bear_season_definitions: row produced no "
                    "season_definition (empty/all-null season_windows) — "
                    "gmu_code=%r hunt_code=%r species=%r page=%r",
                    gmu_code,
                    hunt_code,
                    species_group,
                    page_ref_bear_str,
                )

    return list(seen.values())


# ---------------------------------------------------------------------------
# Bear license_tag builder
# ---------------------------------------------------------------------------


def _build_bear_license_tags(
    records: list[dict[str, Any]],
    citation: SourceCitation,
) -> list[LicenseTag]:
    """Build unique LicenseTag entities from the bear extraction artifact.

    Only ``record_type == "section"`` records are processed; all other
    record types (statewide_rule, reporting_obligation) are skipped.

    One ``LicenseTag`` is emitted per unique ``_co_license_tag_id`` — first-
    occurrence-wins deduplication (keyed by id). Because bear rows have at
    most one weapon_type per row (no Season Choice X rows in the 2026 artifact),
    the ``weapon_types`` list is always a single-element list.

    Bear DB ``species`` is ``"bear"`` (NOT ``"black_bear"`` — that is the
    artifact value). See ``.roughly/known-pitfalls.md``
    "Bear DB species_group is 'bear' not 'black_bear'".

    ``quota_range`` artifact observation:
        Every row in the 2026 CO bear artifact carries ``quota_range=None``.
        This builder passes ``None`` directly — ``_parse_quota_range`` is NOT
        called (it is correct to call it, but since the artifact consistently
        carries ``None``, the result is identical and the call is skipped for
        clarity). If a future year introduces non-null ``quota_range`` strings,
        replace the hardcoded ``None`` with
        ``_parse_quota_range(row.get("quota_range"))``.

    ADR-020: ``assert_id_matches`` is called immediately after every
    ``LicenseTag`` construction, before the dedup check.

    Args:
        records: Top-level JSON array from ``black-bear-2026.json``.
        citation: The ``SourceCitation`` for the big-game brochure.

    Returns:
        Deduplicated list of ``LicenseTag`` instances in first-occurrence order.
    """
    valid_weapon_types = get_args(WeaponType)
    seen: dict[str, LicenseTag] = {}
    # Bear DB species key — artifact value is "black_bear" but every id and DB
    # write must use "bear". See known-pitfalls.md "Bear DB species_group".
    species_group = "bear"

    for record in records:
        if record.get("record_type") != "section":
            continue

        section_residency: str = record.get("residency_scope") or "both"

        for row in record["rows"]:
            gmu_code: str = row["gmu_code"]
            hunt_code: str = row["hunt_code"]

            # Skip blank-GMU rows (defensive — none expected in CO bear artifact).
            if not gmu_code.strip() or not hunt_code.strip():
                _LOGGER.warning(
                    "_build_bear_license_tags: skipping row with empty "
                    "gmu_code or hunt_code in section gmu=%r",
                    record.get("gmu_code"),
                )
                continue

            row_residency: str | None = row.get("residency_scope")
            residency_str = row_residency if row_residency else section_residency

            lt_id = _co_license_tag_id(species_group, gmu_code, hunt_code)

            # Validate all weapon_types against the WeaponType Literal.
            raw_weapon_types: list[str] = row.get("weapon_types") or []
            if not raw_weapon_types:
                raise RuntimeError(
                    f"_build_bear_license_tags: hunt_code={hunt_code!r} "
                    f"gmu_code={gmu_code!r} has empty/missing weapon_types; "
                    "extractor contract violation"
                )
            for wt in raw_weapon_types:
                if wt not in valid_weapon_types:
                    raise ValueError(
                        f"_build_bear_license_tags: unrecognized weapon_type "
                        f"{wt!r} on hunt_code={hunt_code!r}; "
                        f"valid values: {valid_weapon_types}"
                    )
            weapon_types = cast(list[WeaponType], raw_weapon_types)

            # Name: "Bear {hunt_code}" — mirrors big-game builder's "{species_title} {hunt_code}".
            name = f"Bear {hunt_code}"

            page_ref: dict[str, Any] | None = row.get("page_reference")
            page_ref_str: str | None = (
                f"p.{page_ref['page_num_1based']}" if page_ref else None
            )
            row_citation = citation.model_copy(
                update={"page_reference": page_ref_str}
            )

            # quota_range: every 2026 bear row carries quota_range=None.
            # Pass None directly. If a future year introduces non-null strings,
            # replace with _parse_quota_range(row.get("quota_range")).
            # (See docstring for rationale.)
            lt = LicenseTag(
                id=lt_id,
                license_code=hunt_code,
                name=name,
                kind=_co_bear_license_kind(  # type: ignore[arg-type]
                    record["license_kind"]
                ),
                species=species_group,
                weapon_types=weapon_types,
                residency=_co_residency(residency_str),
                quota=row.get("quota"),
                quota_range=None,
                purchase_url=_PURCHASE_URL,
                draw_spec_key=None,
                reserved_pools=[],
                verbatim_rule=_select_co_verbatim_rule(row, record),
                source=row_citation,
            )
            # ADR-020: construction-time drift guard — re-derive the id from
            # structured fields and assert it matches the entity's stored id.
            assert_id_matches(
                lt.id,
                _co_license_tag_id(species_group, gmu_code, hunt_code),
                helper_name="_build_bear_license_tags",
                context={
                    "gmu_code": gmu_code,
                    "hunt_code": hunt_code,
                },
            )
            # First-occurrence-wins dedup; warn on lossy collisions.
            if lt_id not in seen:
                seen[lt_id] = lt
            else:
                existing_bear_lt = seen[lt_id]
                bear_lt_diffs = _license_tag_lossy_diffs(existing_bear_lt, lt)
                if bear_lt_diffs:
                    page_ref_bear_lt: dict[str, Any] | None = row.get("page_reference")
                    page_ref_bear_lt_str: str | None = (
                        f"p.{page_ref_bear_lt['page_num_1based']}"
                        if page_ref_bear_lt
                        else None
                    )
                    _LOGGER.warning(
                        "_build_bear_license_tags: lossy dedup — "
                        "id=%r already seen with different fields; keeping first "
                        "occurrence. page=%r diffs: %s",
                        lt_id,
                        page_ref_bear_lt_str,
                        "; ".join(bear_lt_diffs),
                    )

    return list(seen.values())

# ---------------------------------------------------------------------------
# Shared iterator for link-row builders (T7)
#
# All three link builders below consume _iter_co_entity_rows to guarantee that
# their row/window selection is byte-identical to the entity builders above.
# Normalisation logic lives ONCE here; the three callers are thin consumers.
#
# ADR-020 carve-out: this iterator and the three link builders MUST NOT call
# assert_id_matches or reference drift_guard in any way.  An AST regression
# test (T10) enforces this.  They re-derive ids via the pure id functions —
# that is fine; only the guard wrapper is excluded.
# ---------------------------------------------------------------------------


class _CoEntityRowCtx(NamedTuple):
    """Normalised per-artifact-row context yielded by ``_iter_co_entity_rows``.

    Fields
    ------
    species_group:
        DB species key — ``"bear"`` (NOT ``"black_bear"``) for bear rows;
        artifact ``species_group`` for big-game rows.
    gmu_code:
        Raw zero-padded GMU string from the artifact row (e.g. ``"001"``).
    hunt_code:
        Full CPW hunt code (e.g. ``"D-M-001-O1-A"``).
    season_code:
        CPW season-period code embedded in the hunt code (e.g. ``"O1"``).
    valid_window_indices:
        Indices of ``row["season_windows"]`` entries for which
        ``_parse_co_window`` returns a non-None result — i.e. the windows
        that produced a ``SeasonDefinition`` in the entity builders.  A row
        with zero valid windows yields one context object with an empty list
        (still needed for ``_build_regulation_licenses``, which links tags
        regardless of windows).
    """

    species_group: str
    gmu_code: str
    hunt_code: str
    season_code: str
    valid_window_indices: list[int]


def _is_valid_co_row(gmu_code: str, hunt_code: str) -> bool:
    """Return True iff both gmu_code and hunt_code are non-blank.

    Centralises the blank-row predicate used by both the entity builders and
    the shared link iterator.  The entity builders log WARNING messages when
    they skip; the iterator skips silently to avoid double-logging.
    """
    return bool(gmu_code.strip()) and bool(hunt_code.strip())


def _iter_co_entity_rows(
    sections: list[dict[str, Any]],
    bear_records: list[dict[str, Any]],
) -> list[_CoEntityRowCtx]:
    """Yield one normalised context object per artifact row across both artifacts.

    Covers the big-game artifact (all sections/rows) and the bear artifact
    (``record_type == "section"`` records only).  Applies the same skip rules
    as the entity builders:

    * Big-game: blank ``gmu_code`` or ``hunt_code`` → silently skip (entity
      builders already logged WARNING).
    * Bear: non-``"section"`` ``record_type`` → skip entirely.
    * Bear: blank ``gmu_code`` or ``hunt_code`` → silently skip.

    ``valid_window_indices`` is computed by calling ``_parse_co_window`` for
    each window.  Null-window entries (``_parse_co_window`` returns ``None``)
    are excluded from the list, guaranteeing parity with the entity builders'
    null-window skip logic.

    Args:
        sections: Top-level JSON array from ``big-game-2026.json``.
        bear_records: Top-level JSON array from ``black-bear-2026.json``.

    Returns:
        List of ``_CoEntityRowCtx`` instances in artifact-source order
        (big-game first, then bear).
    """
    result: list[_CoEntityRowCtx] = []

    # --- big-game ---
    for section in sections:
        species_group: str = section["species_group"]
        for row in section["rows"]:
            gmu_code: str = row["gmu_code"]
            hunt_code: str = row["hunt_code"]
            if not _is_valid_co_row(gmu_code, hunt_code):
                # Entity builders already emitted WARNING; skip silently here.
                continue
            season_code: str = row["season_code"]
            valid_window_indices: list[int] = [
                idx
                for idx, window in enumerate(row.get("season_windows", []))
                if _parse_co_window(window, _LICENSE_YEAR) is not None
            ]
            result.append(
                _CoEntityRowCtx(
                    species_group=species_group,
                    gmu_code=gmu_code,
                    hunt_code=hunt_code,
                    season_code=season_code,
                    valid_window_indices=valid_window_indices,
                )
            )

    # --- bear ---
    bear_species_group = "bear"  # artifact says "black_bear"; DB key is "bear"
    for record in bear_records:
        if record.get("record_type") != "section":
            continue
        for row in record["rows"]:
            gmu_code = row["gmu_code"]
            hunt_code = row["hunt_code"]
            if not _is_valid_co_row(gmu_code, hunt_code):
                continue
            season_code = row["season_code"]
            valid_window_indices = [
                idx
                for idx, window in enumerate(row.get("season_windows", []))
                if _parse_co_window(window, _LICENSE_YEAR) is not None
            ]
            result.append(
                _CoEntityRowCtx(
                    species_group=bear_species_group,
                    gmu_code=gmu_code,
                    hunt_code=hunt_code,
                    season_code=season_code,
                    valid_window_indices=valid_window_indices,
                )
            )

    return result


# ---------------------------------------------------------------------------
# Link-row builders (T7)
#
# All three builders are deliberately NOT instrumented with assert_id_matches
# (ADR-020 carve-out — link tables carry no id-text PK; AST test T10 enforces
# the absence of assert_id_matches / drift_guard references in these functions).
# ---------------------------------------------------------------------------


def _build_license_seasons(
    sections: list[dict[str, Any]],
    bear_records: list[dict[str, Any]],
) -> list[LicenseSeason]:
    """Build deduplicated LicenseSeason link rows across big-game and bear.

    One ``LicenseSeason`` is emitted per (``license_tag_id``,
    ``season_definition_id``) pair.  Rows with zero valid windows (e.g. some
    Season Choice female rows whose ``season_windows`` list is entirely null)
    contribute no ``LicenseSeason`` entries but still appear in
    ``_build_regulation_licenses``.

    This is where the asymmetric-coverage pattern manifests: a GMU 001 mule
    deer tag (one ``license_tag_id``) is linked to all three of its method
    season definitions.

    Dedup is set-based; first-occurrence order is preserved via an
    ordered dict.

    CO does NOT fan out deer → mule_deer + whitetail at this layer (unlike
    MT).  Species are pre-separated in the artifact.

    Args:
        sections: Top-level JSON array from ``big-game-2026.json``.
        bear_records: Top-level JSON array from ``black-bear-2026.json``.

    Returns:
        Deduplicated list of ``LicenseSeason`` instances.
    """
    seen: dict[tuple[str, str], LicenseSeason] = {}
    for ctx in _iter_co_entity_rows(sections, bear_records):
        lt_id = _co_license_tag_id(ctx.species_group, ctx.gmu_code, ctx.hunt_code)
        for window_index in ctx.valid_window_indices:
            sd_id = _co_season_definition_id(
                ctx.species_group,
                ctx.gmu_code,
                ctx.hunt_code,
                window_index,
            )
            key = (lt_id, sd_id)
            if key not in seen:
                seen[key] = LicenseSeason(
                    license_tag_id=lt_id,
                    season_definition_id=sd_id,
                )
    return list(seen.values())


def _build_regulation_seasons(
    sections: list[dict[str, Any]],
    bear_records: list[dict[str, Any]],
) -> list[RegulationSeason]:
    """Build deduplicated RegulationSeason link rows across big-game and bear.

    One ``RegulationSeason`` is emitted per (``state``, ``jurisdiction_code``,
    ``species_group``, ``license_year``, ``season_definition_id``) tuple.

    CO does NOT fan out species at this layer.  The ``jurisdiction_code`` is
    derived from the GMU code via ``_co_gmu_jurisdiction_code`` (e.g.
    ``"001"`` → ``"CO-GMU-1"``), matching S06.6's ``regulation_record`` PK.

    Rows with zero valid windows produce no ``RegulationSeason`` entries
    (a license tag exists without a parseable season window).

    Args:
        sections: Top-level JSON array from ``big-game-2026.json``.
        bear_records: Top-level JSON array from ``black-bear-2026.json``.

    Returns:
        Deduplicated list of ``RegulationSeason`` instances.
    """
    seen: dict[tuple[str, str, str, int, str], RegulationSeason] = {}
    for ctx in _iter_co_entity_rows(sections, bear_records):
        jurisdiction_code = _co_gmu_jurisdiction_code(ctx.gmu_code)
        for window_index in ctx.valid_window_indices:
            sd_id = _co_season_definition_id(
                ctx.species_group,
                ctx.gmu_code,
                ctx.hunt_code,
                window_index,
            )
            key = (_STATE, jurisdiction_code, ctx.species_group, _LICENSE_YEAR, sd_id)
            if key not in seen:
                seen[key] = RegulationSeason(
                    state=_STATE,
                    jurisdiction_code=jurisdiction_code,
                    species_group=ctx.species_group,
                    license_year=_LICENSE_YEAR,
                    season_definition_id=sd_id,
                )
    return list(seen.values())


def _build_regulation_licenses(
    sections: list[dict[str, Any]],
    bear_records: list[dict[str, Any]],
) -> list[RegulationLicense]:
    """Build deduplicated RegulationLicense link rows across big-game and bear.

    One ``RegulationLicense`` is emitted per (``state``, ``jurisdiction_code``,
    ``species_group``, ``license_year``, ``license_tag_id``) tuple.

    Unlike ``_build_license_seasons`` and ``_build_regulation_seasons``, this
    builder emits a row for EVERY valid artifact row regardless of whether any
    season windows parsed — a license tag exists even if its windows were
    entirely null (e.g. some Season Choice female rows).

    CO does NOT fan out species at this layer.

    Args:
        sections: Top-level JSON array from ``big-game-2026.json``.
        bear_records: Top-level JSON array from ``black-bear-2026.json``.

    Returns:
        Deduplicated list of ``RegulationLicense`` instances.
    """
    seen: dict[tuple[str, str, str, int, str], RegulationLicense] = {}
    for ctx in _iter_co_entity_rows(sections, bear_records):
        jurisdiction_code = _co_gmu_jurisdiction_code(ctx.gmu_code)
        lt_id = _co_license_tag_id(ctx.species_group, ctx.gmu_code, ctx.hunt_code)
        key = (_STATE, jurisdiction_code, ctx.species_group, _LICENSE_YEAR, lt_id)
        if key not in seen:
            seen[key] = RegulationLicense(
                state=_STATE,
                jurisdiction_code=jurisdiction_code,
                species_group=ctx.species_group,
                license_year=_LICENSE_YEAR,
                license_tag_id=lt_id,
            )
    return list(seen.values())

# ---------------------------------------------------------------------------
# Row-count bands (fires pre-db.connect() per OQ7 discipline)
#
# 2026 empirical counts (orchestrator-verified against the committed artifacts):
#   season_definition : 2013
#   license_tag       : 2470
#   license_season    : 2013
#   regulation_season : 2013
#   regulation_license: 2470
#
# Each band is ±30% around the empirical center, rounded to ints.
# ---------------------------------------------------------------------------

_SEASON_DEFINITION_BAND: Final[tuple[int, int]] = (1409, 2617)
_LICENSE_TAG_BAND: Final[tuple[int, int]] = (1729, 3211)
_LICENSE_SEASON_BAND: Final[tuple[int, int]] = (1409, 2617)
_REGULATION_SEASON_BAND: Final[tuple[int, int]] = (1409, 2617)
_REGULATION_LICENSE_BAND: Final[tuple[int, int]] = (1729, 3211)


def _check_count_band(name: str, count: int, band: tuple[int, int]) -> None:
    """Fail loud if *count* falls outside *band*.

    Mirrors MT's per-entity count guards.  Must be called BEFORE ``db.connect()``
    so a regression in an upstream extractor aborts with no partial writes.

    Args:
        name: Human-readable table name (used in the error message).
        count: Number of rows built by the in-memory builder.
        band: ``(lower, upper)`` inclusive bounds derived from ±30% of the
            2026 empirical baseline.

    Raises:
        RuntimeError: if ``count < band[0]`` or ``count > band[1]``.
    """
    lower, upper = band
    if count < lower or count > upper:
        raise RuntimeError(
            f"{name} count guard failed: built {count} rows; "
            f"acceptable range is [{lower}, {upper}] (±30% of 2026 empirical "
            f"baseline). This indicates a regression in an upstream extractor. "
            f"Investigate before re-running."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Build and optionally write CO season/license rows atomically.

    Three-phase pipeline (OQ7 discipline):

    Phase 1 — build: load both extraction artifacts entirely in-memory and
        derive all five entity/link lists.  No DB connectivity required.
    Phase 2 — guards: five row-count bands fire BEFORE ``db.connect()``.
        A guard failure aborts with no partial writes.
    Phase 3 — write: one atomic ``db.connect()`` / single ``conn.commit()``.
        Skipped under ``--dry-run``.

    Required env: ``DATABASE_URL``.

    Optional flag: ``--dry-run`` — build + guard + summary; no DB writes.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Ingest CO season_definition + license_tag + license_season + "
            "regulation_season + regulation_license rows from the big-game and "
            "bear extraction artifacts.  Writes ~2013 season_definition + ~2470 "
            "license_tag + ~2013 license_season + ~2013 regulation_season + "
            "~2470 regulation_license rows atomically (single commit)."
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

    # ------------------------------------------------------------------
    # Phase 1: build (no DB connectivity)
    # ------------------------------------------------------------------
    logger.info("loading sources.yaml citations")
    big_game_cit = _load_citation_from_sources_yaml(_BIG_GAME_CITATION_ID)
    bear_cit = _load_citation_from_sources_yaml(_BEAR_CITATION_ID)

    logger.info("loading artifacts")
    secs = _load_big_game_sections()
    recs = _load_bear_records()

    logger.info("building entity rows + link rows")
    season_definitions = (
        _build_big_game_season_definitions(secs, big_game_cit)
        + _build_bear_season_definitions(recs, bear_cit)
    )
    license_tags = (
        _build_big_game_license_tags(secs, big_game_cit)
        + _build_bear_license_tags(recs, bear_cit)
    )
    license_seasons = _build_license_seasons(secs, recs)
    regulation_seasons = _build_regulation_seasons(secs, recs)
    regulation_licenses = _build_regulation_licenses(secs, recs)

    # Belt-and-suspenders: assert no id collisions across the concatenated lists.
    # Bear ids carry "-bear-" so collisions with big-game are structurally
    # impossible, but we verify explicitly rather than relying on that invariant.
    sd_ids = [sd.id for sd in season_definitions]
    if len(sd_ids) != len(set(sd_ids)):
        dupes = [k for k, v in Counter(sd_ids).items() if v > 1]
        logger.error("season_definition id collision(s) detected: %s", dupes)
        raise RuntimeError(
            f"season_definition id collisions across big-game + bear concatenation: "
            f"{dupes}"
        )
    lt_ids = [lt.id for lt in license_tags]
    if len(lt_ids) != len(set(lt_ids)):
        dupes = [k for k, v in Counter(lt_ids).items() if v > 1]
        logger.error("license_tag id collision(s) detected: %s", dupes)
        raise RuntimeError(
            f"license_tag id collisions across big-game + bear concatenation: {dupes}"
        )

    logger.info(
        "built: %d season_definition, %d license_tag, %d license_season, "
        "%d regulation_season, %d regulation_license",
        len(season_definitions),
        len(license_tags),
        len(license_seasons),
        len(regulation_seasons),
        len(regulation_licenses),
    )

    # ------------------------------------------------------------------
    # Phase 2: guards (MUST run before db.connect())
    # ------------------------------------------------------------------
    _check_count_band("season_definition", len(season_definitions), _SEASON_DEFINITION_BAND)
    _check_count_band("license_tag", len(license_tags), _LICENSE_TAG_BAND)
    _check_count_band("license_season", len(license_seasons), _LICENSE_SEASON_BAND)
    _check_count_band("regulation_season", len(regulation_seasons), _REGULATION_SEASON_BAND)
    _check_count_band("regulation_license", len(regulation_licenses), _REGULATION_LICENSE_BAND)
    logger.info("all five count guards passed")

    # ------------------------------------------------------------------
    # Phase 3: write (or dry-run short-circuit)
    # ------------------------------------------------------------------
    if args.dry_run:
        logger.info("--dry-run: skipping DB write")
        logger.info(
            "dry-run summary: season_definition=%d  license_tag=%d  "
            "license_season=%d  regulation_season=%d  regulation_license=%d",
            len(season_definitions),
            len(license_tags),
            len(license_seasons),
            len(regulation_seasons),
            len(regulation_licenses),
        )
        return 0

    with db.connect() as conn:
        for season in season_definitions:
            db.upsert_season_definition(conn, season)
        for tag in license_tags:
            db.upsert_license_tag(conn, tag)
        for ls_link in license_seasons:
            db.write_license_season(conn, ls_link)
        for rs_link in regulation_seasons:
            db.write_regulation_season(conn, rs_link)
        for rl_link in regulation_licenses:
            db.write_regulation_license(conn, rl_link)
        conn.commit()

    logger.info(
        "wrote %d season_definition + %d license_tag + %d license_season "
        "+ %d regulation_season + %d regulation_license rows (state=%s "
        "license_year=%d)",
        len(season_definitions),
        len(license_tags),
        len(license_seasons),
        len(regulation_seasons),
        len(regulation_licenses),
        _STATE,
        _LICENSE_YEAR,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
