"""Canonical write path for the ``geometry`` table.

This module is the single authoritative place for persisting ``Geometry``
records to Postgres. Future stories (S02.3–S02.5) MUST extend this module
rather than implement a parallel write path. See ADR-003 (ingestion upstream
and offline) and ADR-004 (Supabase Postgres + PostGIS).

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
layers (geometry + jurisdiction_binding + regulation_record) when S02.3–S02.5
are implemented.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

import psycopg
from psycopg.types.json import Json

from ingestion.lib.schema import Geometry

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
