"""Canonical write path for the ``geometry`` and ``regulation_record`` tables.

This module is the single authoritative place for persisting ``Geometry``
and ``RegulationRecord`` records to Postgres. Future stories MUST extend this
module rather than implement a parallel write path. See ADR-003 (ingestion
upstream and offline) and ADR-004 (Supabase Postgres + PostGIS).

Future stories S03.7-S03.10 will extend this module with helpers for
``season_definition``, ``license_tag``, ``license_season``, ``draw_spec``,
``reporting_obligation``, and ``jurisdiction_binding``. This is the documented
extension point — do not implement a parallel write path.

WKT cast precedent
------------------
All geography-column writes use the pattern::

    ST_GeomFromText(%s, 4326)::geography

``ST_GeomFromText`` accepts WKT and a SRID, then the explicit ``::geography``
cast stores the result in the ``geography(MultiPolygon, 4326)`` column.
Future callers writing to other geography columns in this schema MUST follow
the same pattern — do NOT use ``ST_GeomFromGeoJSON`` or bare literals.

Transaction discipline
----------------------
Neither ``upsert_geometry`` nor ``upsert_geometries`` commits. Callers control
the transaction boundary so that a single commit can atomically write all three
layers (geometry + jurisdiction_binding + regulation_record + season_definition
+ license_tag + ... — the full set lands across S02.3–S03.10).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg.types.json import Json
from pydantic import TypeAdapter

from ingestion.lib.schema import (
    DrawSpec,
    DrawSpecKey,
    Geometry,
    LicenseSeason,
    LicenseTag,
    RegulationLicense,
    RegulationRecord,
    RegulationReporting,
    RegulationSeason,
    ReportingObligation,
    SeasonDefinition,
)

# JSON-safe serialization for DrawSpec.parameters per ADR-012's escape-hatch
# discipline. parameters is `dict[str, Any]`; a state adapter may legitimately
# write `date`, `Decimal`, `UUID`, etc. into it. Raw `Json(dict_with_date)`
# would raise at execute time because psycopg's default JSON encoder uses
# stdlib `json.dumps`, which can't serialize those types. Pydantic's
# TypeAdapter `dump_python(..., mode="json")` converts to a JSON-safe dict
# (dates → ISO strings, UUIDs → strings, etc.) using the same encoders the
# Pydantic models elsewhere in this file rely on.
_PARAMETERS_TYPE_ADAPTER: TypeAdapter[dict[str, Any]] = TypeAdapter(dict[str, Any])

_logger = logging.getLogger(__name__)

_UPSERT_SQL = """
INSERT INTO geometry (id, name, kind, geom, state, license_year, source, verbatim_rule, legal_description)
VALUES (%s, %s, %s, ST_GeomFromText(%s, 4326)::geography, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    geom = EXCLUDED.geom,
    name = EXCLUDED.name,
    source = EXCLUDED.source,
    license_year = EXCLUDED.license_year,
    verbatim_rule = EXCLUDED.verbatim_rule,
    legal_description = EXCLUDED.legal_description
-- kind and state are intentionally NOT in the UPDATE clause: both are
-- structural identity, not data. Reclassifying a row across kinds (e.g.
-- 'hunting_district' to 'cwd_zone') means the ID's identity has changed
-- and a new row should be created instead.
"""

_UPSERT_REGULATION_RECORD_SQL = """
INSERT INTO regulation_record (
    state, jurisdiction_code, species_group, license_year,
    schema_version, source, confidence, additional_rules
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (state, jurisdiction_code, species_group, license_year) DO UPDATE SET
    schema_version = EXCLUDED.schema_version,
    source = EXCLUDED.source,
    confidence = EXCLUDED.confidence,
    additional_rules = EXCLUDED.additional_rules
-- ingested_at is intentionally NOT in the UPDATE clause: it records the first
-- successful ingest time; re-runs preserve the original timestamp. The PK
-- columns are also excluded (no-op on conflict); explicit documentation
-- here parallels the kind/state exclusion comment on _UPSERT_SQL above.
"""

_UPDATE_LEGAL_DESCRIPTION_SQL = """
UPDATE geometry SET legal_description = %s WHERE id = %s
"""

_UPDATE_LICENSE_TAG_DRAW_SPEC_KEY_SQL = """
UPDATE license_tag SET draw_spec_key = %s::jsonb WHERE id = %s
"""

_UPSERT_SEASON_DEFINITION_SQL = """
INSERT INTO season_definition (
    id, name, opens, closes, weapon_type, residency,
    closure_predicate, verbatim_rule, page_reference, source
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    name               = EXCLUDED.name,
    opens              = EXCLUDED.opens,
    closes             = EXCLUDED.closes,
    weapon_type        = EXCLUDED.weapon_type,
    residency          = EXCLUDED.residency,
    closure_predicate  = EXCLUDED.closure_predicate,
    verbatim_rule      = EXCLUDED.verbatim_rule,
    page_reference     = EXCLUDED.page_reference,
    source             = EXCLUDED.source
-- id (PK) is intentionally NOT in the UPDATE clause: it is the conflict
-- discriminator and a no-op to update. Parallels the kind/state exclusion
-- comment on _UPSERT_SQL and ingested_at exclusion on
-- _UPSERT_REGULATION_RECORD_SQL above.
"""

_UPSERT_LICENSE_TAG_SQL = """
INSERT INTO license_tag (
    id, license_code, name, kind, species, weapon_types, residency,
    quota, quota_range, purchase_url, draw_spec_key,
    reserved_pools, verbatim_rule, source
)
VALUES (
    %s, %s, %s, %s, %s, %s, %s,
    %s,
    CASE WHEN %s::int IS NULL THEN NULL ELSE int4range(%s, %s, '[]') END,
    %s, %s,
    %s, %s, %s
)
ON CONFLICT (id) DO UPDATE SET
    license_code   = EXCLUDED.license_code,
    name           = EXCLUDED.name,
    kind           = EXCLUDED.kind,
    species        = EXCLUDED.species,
    weapon_types   = EXCLUDED.weapon_types,
    residency      = EXCLUDED.residency,
    quota          = EXCLUDED.quota,
    quota_range    = EXCLUDED.quota_range,
    purchase_url   = EXCLUDED.purchase_url,
    draw_spec_key  = EXCLUDED.draw_spec_key,
    reserved_pools = EXCLUDED.reserved_pools,
    verbatim_rule  = EXCLUDED.verbatim_rule,
    source         = EXCLUDED.source
-- id (PK) is intentionally NOT in the UPDATE clause: same discipline as
-- _UPSERT_SEASON_DEFINITION_SQL above.
"""

_UPSERT_DRAW_SPEC_SQL = """
INSERT INTO draw_spec (
    state, hunt_code, year, schema_version, quota, point_system,
    residency_cap, choices, pools, draw_phase, successor_hunt_code_key,
    application_deadline, parameters, source
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (state, hunt_code, year) DO UPDATE SET
    schema_version          = EXCLUDED.schema_version,
    quota                   = EXCLUDED.quota,
    point_system            = EXCLUDED.point_system,
    residency_cap           = EXCLUDED.residency_cap,
    choices                 = EXCLUDED.choices,
    pools                   = EXCLUDED.pools,
    draw_phase              = EXCLUDED.draw_phase,
    successor_hunt_code_key = EXCLUDED.successor_hunt_code_key,
    application_deadline    = EXCLUDED.application_deadline,
    parameters              = EXCLUDED.parameters,
    source                  = EXCLUDED.source
-- PK columns (state, hunt_code, year) are intentionally NOT in the UPDATE
-- clause: same discipline as _UPSERT_SEASON_DEFINITION_SQL and
-- _UPSERT_LICENSE_TAG_SQL above.
"""

_INSERT_LICENSE_SEASON_SQL = "INSERT INTO license_season (license_tag_id, season_definition_id) VALUES (%s, %s) ON CONFLICT DO NOTHING"

_INSERT_REGULATION_SEASON_SQL = "INSERT INTO regulation_season (state, jurisdiction_code, species_group, license_year, season_definition_id) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING"

_INSERT_REGULATION_LICENSE_SQL = "INSERT INTO regulation_license (state, jurisdiction_code, species_group, license_year, license_tag_id) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING"

_UPSERT_REPORTING_OBLIGATION_SQL = """
INSERT INTO reporting_obligation (
    id, kind, deadline, deadline_hours, submission_method,
    submission_url, submission_phone, applies_to_regions,
    what_to_present, verbatim_rule, source
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    kind               = EXCLUDED.kind,
    deadline           = EXCLUDED.deadline,
    deadline_hours     = EXCLUDED.deadline_hours,
    submission_method  = EXCLUDED.submission_method,
    submission_url     = EXCLUDED.submission_url,
    submission_phone   = EXCLUDED.submission_phone,
    applies_to_regions = EXCLUDED.applies_to_regions,
    what_to_present    = EXCLUDED.what_to_present,
    verbatim_rule      = EXCLUDED.verbatim_rule,
    source             = EXCLUDED.source
-- id (PK) is intentionally NOT in the UPDATE clause: same discipline as
-- _UPSERT_SEASON_DEFINITION_SQL above.
-- ingested_at is NOT present on this table (no auto-timestamp column).
"""

_INSERT_REGULATION_REPORTING_SQL = "INSERT INTO regulation_reporting (state, jurisdiction_code, species_group, license_year, reporting_obligation_id) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING"


def connect() -> psycopg.Connection[tuple[object, ...]]:
    """Open a psycopg3 connection using ``DATABASE_URL`` from the environment.

    Raises ``RuntimeError`` if the environment variable is absent.  The caller
    is responsible for the connection lifecycle (commit, rollback, close).
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required for ingestion DB writes"
        )
    return psycopg.connect(url)


def upsert_geometry(conn: psycopg.Connection[tuple[object, ...]], geom: Geometry) -> None:
    """INSERT … ON CONFLICT UPDATE a single ``Geometry`` row.

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        geom: The ``Geometry`` instance to persist.
    """
    source_json = Json(geom.source.model_dump(exclude_none=True))
    params: tuple[object, ...] = (
        geom.id,
        geom.name,
        geom.kind,
        geom.geom,              # WKT — passed to ST_GeomFromText(%s, 4326)::geography
        geom.state,
        geom.license_year,      # None → SQL NULL (nullable column)
        source_json,
        geom.verbatim_rule,     # None → SQL NULL; empty-string guard is caller's responsibility
        geom.legal_description, # None → SQL NULL
    )
    with conn.cursor() as cur:
        cur.execute(_UPSERT_SQL, params)
    _logger.debug("upserted geometry id=%s name=%r", geom.id, geom.name)


def upsert_geometries(
    conn: psycopg.Connection[tuple[object, ...]],
    geoms: Iterable[Geometry],
) -> int:
    """Upsert an iterable of ``Geometry`` rows and return the count processed.

    Calls ``upsert_geometry`` for each item so every row benefits from
    identical parameter handling and logging.  Does NOT commit.

    Args:
        conn: An open psycopg3 connection.
        geoms: Any iterable of ``Geometry`` instances.

    Returns:
        The number of rows processed (i.e. len of the iterable consumed).
    """
    count = 0
    for geom in geoms:
        upsert_geometry(conn, geom)
        count += 1
    _logger.info("upserted %d geometry rows", count)
    return count


def upsert_regulation_record(
    conn: psycopg.Connection[tuple[object, ...]],
    record: RegulationRecord,
) -> None:
    """INSERT … ON CONFLICT UPDATE a single ``RegulationRecord`` row.

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        record: The ``RegulationRecord`` instance to persist.
    """
    source_json = Json(record.source.model_dump(exclude_none=True))
    additional_rules_json = Json(
        [rule.model_dump(exclude_none=True) for rule in record.additional_rules]
    )
    params: tuple[object, ...] = (
        record.state,
        record.jurisdiction_code,
        record.species_group,
        record.license_year,
        record.schema_version,
        source_json,
        record.confidence,
        additional_rules_json,
    )
    with conn.cursor() as cur:
        cur.execute(_UPSERT_REGULATION_RECORD_SQL, params)
    _logger.debug(
        "upserted regulation_record state=%s code=%s species=%s year=%d",
        record.state, record.jurisdiction_code,
        record.species_group, record.license_year,
    )


def update_legal_description(
    conn: psycopg.Connection[tuple[object, ...]],
    geometry_id: str,
    text: str | None,
) -> None:
    """UPDATE ``geometry.legal_description`` for a single row by ``id``.

    ``text=None`` writes SQL NULL (explicit null-out for de-flagging an old
    description). Empty-string guarding is the caller's responsibility —
    a caller wanting NULL semantics should pass None, not "".

    Fails loud if the WHERE clause matches no row: raises ``RuntimeError``
    with the unmatched geometry_id. This catches loader bugs where the
    matcher emits a geometry_id that doesn't exist in the DB (e.g., E02
    fixture drift introducing a new id the legal-descriptions extractor
    didn't see).

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        geometry_id: The PK of the geometry row to update.
        text: The legal-description prose to write, or None for SQL NULL.
    """
    params: tuple[object, ...] = (text, geometry_id)
    with conn.cursor() as cur:
        cur.execute(_UPDATE_LEGAL_DESCRIPTION_SQL, params)
        if cur.rowcount == 0:
            raise RuntimeError(
                f"update_legal_description: no geometry row with id={geometry_id!r}"
            )
    _logger.debug(
        "updated legal_description for geometry id=%s (%d chars)",
        geometry_id,
        len(text or ""),
    )


def update_license_tag_draw_spec_key(
    conn: psycopg.Connection[tuple[object, ...]],
    license_tag_id: str,
    key: DrawSpecKey,
) -> None:
    """Backfill license_tag.draw_spec_key with the soft-FK reference per ADR-012.

    Fails loud on cur.rowcount == 0: that indicates the license_tag row was not
    written by S03.7 (S03.7→S03.8 id contract broken) or the id derivation in
    load_draw_specs.py diverged from load_seasons_and_licenses._license_tag_id.

    No commit; caller owns the transaction.

    Args:
        conn: An open psycopg3 connection.
        license_tag_id: The PK of the license_tag row to update.
        key: The ``DrawSpecKey`` soft-FK value to write.
    """
    key_json = Json(key.model_dump(exclude_none=True))
    with conn.cursor() as cur:
        cur.execute(
            _UPDATE_LICENSE_TAG_DRAW_SPEC_KEY_SQL,
            (key_json, license_tag_id),
        )
        if cur.rowcount == 0:
            msg = (
                f"update_license_tag_draw_spec_key: no license_tag row found "
                f"with id={license_tag_id!r}. The S03.7→S03.8 id contract is "
                f"broken: either the license_tag was not written by S03.7, or "
                f"the id derivation in load_draw_specs.py diverged from "
                f"load_seasons_and_licenses._license_tag_id. Investigate before "
                f"re-running."
            )
            raise RuntimeError(msg)
    _logger.debug(
        "updated draw_spec_key for license_tag id=%s",
        license_tag_id,
    )


def upsert_season_definition(
    conn: psycopg.Connection[tuple[object, ...]],
    season: SeasonDefinition,
) -> None:
    """INSERT … ON CONFLICT UPDATE a single ``SeasonDefinition`` row.

    Part of the decomposed entity model (ADR-010). Written by S03.7 alongside
    ``upsert_license_tag`` as child entities whose FK target is the
    ``regulation_record`` rows landed in S03.6.

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        season: The ``SeasonDefinition`` instance to persist.
    """
    closure_predicate_json = (
        Json(season.closure_predicate.model_dump(exclude_none=True))
        if season.closure_predicate
        else None
    )
    source_json = Json(season.source.model_dump(exclude_none=True))
    params: tuple[object, ...] = (
        season.id,
        season.name,
        season.opens,
        season.closes,
        season.weapon_type,       # None → SQL NULL (nullable column)
        season.residency,         # None → SQL NULL (nullable column)
        closure_predicate_json,   # None → SQL NULL (nullable jsonb)
        season.verbatim_rule,
        season.page_reference,    # None → SQL NULL (nullable column)
        source_json,
    )
    with conn.cursor() as cur:
        cur.execute(_UPSERT_SEASON_DEFINITION_SQL, params)
    _logger.debug("upserted season_definition id=%s name=%r", season.id, season.name)


def upsert_license_tag(
    conn: psycopg.Connection[tuple[object, ...]],
    tag: LicenseTag,
) -> None:
    """INSERT … ON CONFLICT UPDATE a single ``LicenseTag`` row.

    Part of the decomposed entity model (ADR-010). Written by S03.7 alongside
    ``upsert_season_definition`` as child entities whose FK target is the
    ``regulation_record`` rows landed in S03.6.

    ``quota_range`` is an ``int4range`` column. The SQL uses a CASE expression
    so that a None Python value produces SQL NULL rather than an empty range.
    Three params are passed for the CASE+int4range fragment: the first is the
    NULL sentinel (cast to int); the second and third are the inclusive lower
    and upper bounds.

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        tag: The ``LicenseTag`` instance to persist.
    """
    if tag.quota_range is not None:
        qr_sentinel: int | None = tag.quota_range[0]
        qr_lo: int | None = tag.quota_range[0]
        qr_hi: int | None = tag.quota_range[1]
    else:
        qr_sentinel = None
        qr_lo = None
        qr_hi = None

    draw_spec_key_json = (
        Json(tag.draw_spec_key.model_dump(exclude_none=True))
        if tag.draw_spec_key
        else None
    )
    reserved_pools_json = Json([rp.model_dump(exclude_none=True) for rp in tag.reserved_pools])
    source_json = Json(tag.source.model_dump(exclude_none=True))

    params: tuple[object, ...] = (
        tag.id,
        tag.license_code,
        tag.name,
        tag.kind,
        tag.species,
        tag.weapon_types,          # list[str] — psycopg3 maps to text[] natively
        tag.residency,
        tag.quota,                 # int | None → SQL NULL when None
        qr_sentinel,               # CASE sentinel — None → NULL range
        qr_lo,                     # int4range lower bound
        qr_hi,                     # int4range upper bound
        tag.purchase_url,
        draw_spec_key_json,        # None → SQL NULL (S03.8 backfills draw_spec_key)
        reserved_pools_json,
        tag.verbatim_rule,
        source_json,
    )
    with conn.cursor() as cur:
        cur.execute(_UPSERT_LICENSE_TAG_SQL, params)
    _logger.debug(
        "upserted license_tag id=%s code=%r kind=%s",
        tag.id, tag.license_code, tag.kind,
    )


def upsert_draw_spec(conn: psycopg.Connection[tuple[object, ...]], spec: DrawSpec) -> None:
    """Upsert a draw_spec row. No commit; caller owns txn.

    Per ADR-012, ``parameters`` is the state-adapter escape hatch — only state
    adapters in ``ingestion/states/<state>/`` may pass a non-None value, and
    shared code MUST NOT read it.

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        spec: The ``DrawSpec`` instance to persist.
    """
    # nullable jsonbs: serialize as None (SQL NULL) when the field is None,
    # else wrap in Json with exclude_none=True
    point_system_json = (
        Json(spec.point_system.model_dump(exclude_none=True))
        if spec.point_system is not None
        else None
    )
    residency_cap_json = (
        Json(spec.residency_cap.model_dump(exclude_none=True))
        if spec.residency_cap is not None
        else None
    )
    successor_key_json = (
        Json(spec.successor_hunt_code_key.model_dump(exclude_none=True))
        if spec.successor_hunt_code_key is not None
        else None
    )
    parameters_json = (
        Json(_PARAMETERS_TYPE_ADAPTER.dump_python(spec.parameters, mode="json"))
        if spec.parameters is not None
        else None
    )

    choices_json = Json(spec.choices.model_dump(exclude_none=True))
    pools_json = Json([p.model_dump(exclude_none=True) for p in spec.pools])
    source_json = Json(spec.source.model_dump(exclude_none=True))

    with conn.cursor() as cur:
        cur.execute(
            _UPSERT_DRAW_SPEC_SQL,
            (
                spec.state,
                spec.hunt_code,
                spec.year,
                spec.schema_version,
                spec.quota,
                point_system_json,
                residency_cap_json,
                choices_json,
                pools_json,
                spec.draw_phase,
                successor_key_json,
                spec.application_deadline,
                parameters_json,
                source_json,
            ),
        )
    _logger.debug(
        "upserted draw_spec state=%s hunt_code=%r year=%d",
        spec.state, spec.hunt_code, spec.year,
    )


def write_license_season(
    conn: psycopg.Connection[tuple[object, ...]],
    link: LicenseSeason,
) -> None:
    """INSERT … ON CONFLICT DO NOTHING for a ``license_season`` link row.

    Per ADR-018 §1, ``license_season`` records per-license season coverage —
    distinct from ``regulation_season`` which records per-regulation_record
    coverage. Both link tables coexist; each answers a different join question.
    Written by S03.7 as part of the decomposed entity link-table population.

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        link: The ``LicenseSeason`` instance to persist.
    """
    params: tuple[object, ...] = (link.license_tag_id, link.season_definition_id)
    with conn.cursor() as cur:
        cur.execute(_INSERT_LICENSE_SEASON_SQL, params)
    _logger.debug(
        "inserted license_season license_tag=%s season=%s",
        link.license_tag_id, link.season_definition_id,
    )


def write_regulation_season(
    conn: psycopg.Connection[tuple[object, ...]],
    link: RegulationSeason,
) -> None:
    """INSERT … ON CONFLICT DO NOTHING for a ``regulation_season`` link row.

    Part of the canonical decomposed-entity link-table pattern (ADR-010).
    Written by S03.7 as part of the season/license entity population that
    targets the ``regulation_record`` rows landed in S03.6.

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        link: The ``RegulationSeason`` instance to persist.
    """
    params: tuple[object, ...] = (
        link.state,
        link.jurisdiction_code,
        link.species_group,
        link.license_year,
        link.season_definition_id,
    )
    with conn.cursor() as cur:
        cur.execute(_INSERT_REGULATION_SEASON_SQL, params)
    _logger.debug(
        "inserted regulation_season state=%s code=%s species=%s year=%d season=%s",
        link.state, link.jurisdiction_code,
        link.species_group, link.license_year,
        link.season_definition_id,
    )


def write_regulation_license(
    conn: psycopg.Connection[tuple[object, ...]],
    link: RegulationLicense,
) -> None:
    """INSERT … ON CONFLICT DO NOTHING for a ``regulation_license`` link row.

    Part of the canonical decomposed-entity link-table pattern (ADR-010).
    Written by S03.7 as part of the season/license entity population that
    targets the ``regulation_record`` rows landed in S03.6.

    Does NOT commit — the caller controls the transaction boundary.

    Args:
        conn: An open psycopg3 connection.
        link: The ``RegulationLicense`` instance to persist.
    """
    params: tuple[object, ...] = (
        link.state,
        link.jurisdiction_code,
        link.species_group,
        link.license_year,
        link.license_tag_id,
    )
    with conn.cursor() as cur:
        cur.execute(_INSERT_REGULATION_LICENSE_SQL, params)
    _logger.debug(
        "inserted regulation_license state=%s code=%s species=%s year=%d tag=%s",
        link.state, link.jurisdiction_code,
        link.species_group, link.license_year,
        link.license_tag_id,
    )


def upsert_reporting_obligation(
    conn: psycopg.Connection[tuple[object, ...]],
    obligation: ReportingObligation,
) -> None:
    """INSERT … ON CONFLICT UPDATE a single ``ReportingObligation`` row.

    DDL table: reporting_obligation

    Persists post-harvest or in-season reporting duties (check stations,
    tooth submissions, harvest reports, etc.) to the ``reporting_obligation``
    table. Written by S03.9 as part of the decomposed entity population.

    Does NOT commit — the caller controls the transaction boundary.

    Idempotent: ON CONFLICT (id) DO UPDATE SET overwrites all mutable fields
    on re-runs; re-runs preserve row identity without duplicating rows.

    References ADR-010 (decomposed entity model) and ADR-017 (no confidence
    column on child entities — confidence lives on regulation_record only).

    Args:
        conn: An open psycopg3 connection.
        obligation: The ``ReportingObligation`` instance to persist.
    """
    source_json = Json(obligation.source.model_dump(mode="json"))
    params: tuple[object, ...] = (
        obligation.id,
        obligation.kind,
        obligation.deadline,
        obligation.deadline_hours,
        obligation.submission_method,
        obligation.submission_url,
        obligation.submission_phone,
        obligation.applies_to_regions,
        obligation.what_to_present,
        obligation.verbatim_rule,
        source_json,
    )
    with conn.cursor() as cur:
        cur.execute(_UPSERT_REPORTING_OBLIGATION_SQL, params)
    _logger.debug(
        "upserted reporting_obligation id=%s kind=%s",
        obligation.id, obligation.kind,
    )


def write_regulation_reporting(
    conn: psycopg.Connection[tuple[object, ...]],
    link: RegulationReporting,
) -> None:
    """INSERT … ON CONFLICT DO NOTHING for a ``regulation_reporting`` link row.

    DDL table: regulation_reporting

    Part of the canonical decomposed-entity link-table pattern (ADR-010).
    Written by S03.9 to link regulation_record rows to reporting_obligation
    entities.

    Does NOT commit — the caller controls the transaction boundary.

    Idempotent: ON CONFLICT DO NOTHING skips duplicate inserts; re-runs are
    safe without pre-deletion.

    Args:
        conn: An open psycopg3 connection.
        link: The ``RegulationReporting`` instance to persist.
    """
    params: tuple[object, ...] = (
        link.state,
        link.jurisdiction_code,
        link.species_group,
        link.license_year,
        link.reporting_obligation_id,
    )
    with conn.cursor() as cur:
        cur.execute(_INSERT_REGULATION_REPORTING_SQL, params)
    _logger.debug(
        "inserted regulation_reporting state=%s code=%s species=%s year=%d obligation=%s",
        link.state, link.jurisdiction_code,
        link.species_group, link.license_year,
        link.reporting_obligation_id,
    )
