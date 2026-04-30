"""Unit tests for ingestion.lib.db."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from psycopg.types.json import Json

from ingestion.lib.db import connect, upsert_geometries, upsert_geometry
from ingestion.lib.schema import Geometry, SourceCitation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SQUARE_WKT = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"

# The Geometry validator coerces a Polygon to MultiPolygon, so we must use the
# coerced WKT when asserting the SQL parameter value.
_COERCED_WKT = Geometry(
    id="test-geom-coerce",
    name="coerce check",
    kind="hunting_district",
    geom=_SQUARE_WKT,
    state="MT",
    source=SourceCitation(
        id="src-coerce",
        agency="MFWP",
        title="MT HD Layer",
        url="https://example.com",
        publication_date="2026-01-01",
        document_type="gis_layer",
    ),
).geom  # the post-validator WKT string (MultiPolygon)


def _make_source() -> SourceCitation:
    return SourceCitation(
        id="src-001",
        agency="Montana Fish, Wildlife & Parks",
        title="Montana Hunting Districts GIS Layer",
        url="https://example.com/mt-hd.geojson",
        publication_date="2026-01-01",
        document_type="gis_layer",
    )


def _make_geometry(
    geom_id: str = "mt-hd-262",
    *,
    license_year: int | None = 2026,
    verbatim_rule: str | None = "Elk hunting district 262.",
) -> Geometry:
    return Geometry(
        id=geom_id,
        name=f"HD {geom_id}",
        kind="hunting_district",
        geom=_SQUARE_WKT,
        state="MT",
        license_year=license_year,
        verbatim_rule=verbatim_rule,
        source=_make_source(),
    )


def _make_mock_conn() -> tuple[MagicMock, MagicMock]:
    """Return (mock_conn, mock_cursor) with psycopg3 context-manager wiring."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# connect() — env-var guard
# ---------------------------------------------------------------------------


def test_connect_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """connect() must raise RuntimeError with 'DATABASE_URL' in the message."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        connect()


# ---------------------------------------------------------------------------
# upsert_geometry — SQL string assertions
# ---------------------------------------------------------------------------


def test_upsert_geometry_sql_contains_st_geomfromtext() -> None:
    """SQL must use ST_GeomFromText(%s, 4326)::geography for the geom column."""
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, _make_geometry())
    sql: str = mock_cursor.execute.call_args[0][0]
    assert "ST_GeomFromText(%s, 4326)::geography" in sql


def test_upsert_geometry_sql_contains_on_conflict_update() -> None:
    """SQL must contain ON CONFLICT upsert with the expected updated columns."""
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, _make_geometry())
    sql: str = mock_cursor.execute.call_args[0][0]
    assert "ON CONFLICT (id) DO UPDATE SET" in sql
    assert "geom" in sql
    assert "name" in sql
    assert "source" in sql
    assert "license_year" in sql
    assert "verbatim_rule" in sql


# ---------------------------------------------------------------------------
# upsert_geometry — parameter assertions
# ---------------------------------------------------------------------------


def test_upsert_geometry_correct_param_order() -> None:
    """Parameters tuple must be (id, name, kind, geom_wkt, state, license_year, source, verbatim_rule)."""
    geom = _make_geometry(geom_id="mt-hd-262", license_year=2026, verbatim_rule="Rule text.")
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, geom)
    params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]

    assert len(params) == 8
    assert params[0] == geom.id
    assert params[1] == geom.name
    assert params[2] == geom.kind
    assert params[3] == _COERCED_WKT  # post-validator WKT
    assert params[4] == geom.state
    assert params[5] == geom.license_year
    # params[6] is the Json-wrapped source (asserted separately)
    assert params[7] == geom.verbatim_rule


def test_upsert_geometry_source_wrapped_in_json() -> None:
    """The source parameter (index 6) must be wrapped with psycopg Json."""
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, _make_geometry())
    params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
    assert isinstance(params[6], Json)


def test_upsert_geometry_none_license_year_passed_through() -> None:
    """license_year=None must be passed through to the SQL params as None."""
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, _make_geometry(license_year=None))
    params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
    assert params[5] is None


def test_upsert_geometry_none_verbatim_rule_passed_through() -> None:
    """verbatim_rule=None must be passed through to the SQL params as None."""
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, _make_geometry(verbatim_rule=None))
    params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
    assert params[7] is None


# ---------------------------------------------------------------------------
# upsert_geometries — batch behaviour
# ---------------------------------------------------------------------------


def test_upsert_geometries_calls_execute_once_per_row() -> None:
    """upsert_geometries over 3 geometries must call cursor.execute exactly 3 times."""
    mock_conn, mock_cursor = _make_mock_conn()
    geoms = [
        _make_geometry(geom_id="mt-hd-262"),
        _make_geometry(geom_id="mt-hd-263"),
        _make_geometry(geom_id="mt-hd-264"),
    ]
    upsert_geometries(mock_conn, geoms)
    assert mock_cursor.execute.call_count == 3


def test_upsert_geometries_returns_count() -> None:
    """upsert_geometries must return the number of rows processed."""
    mock_conn, mock_cursor = _make_mock_conn()
    geoms = [
        _make_geometry(geom_id="mt-hd-262"),
        _make_geometry(geom_id="mt-hd-263"),
        _make_geometry(geom_id="mt-hd-264"),
    ]
    result = upsert_geometries(mock_conn, geoms)
    assert result == 3
