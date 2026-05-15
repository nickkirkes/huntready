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

import psycopg
from psycopg.types.json import Json

from ingestion.lib.schema import Geometry, RegulationRecord

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
