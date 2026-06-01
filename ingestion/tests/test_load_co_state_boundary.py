"""Unit tests for states.colorado.load_state_boundary — pure-function, no real HTTP or DB."""

from __future__ import annotations

import hashlib
import io
import pathlib
import tempfile
import zipfile
from unittest.mock import MagicMock, patch

import geopandas  # type: ignore[import-untyped]
import pytest
import shapely.geometry
from shapely.geometry import MultiPolygon, Polygon

from ingestion.lib import db as db_module
from ingestion.lib.db import _UPSERT_SQL
from states.colorado.load_state_boundary import (
    _build_source_citation,
    _parse_to_multipolygon_wkt,
    _verify_sha256,
    main,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_mock_conn() -> tuple[MagicMock, MagicMock]:
    """Return (mock_conn, mock_cursor) with psycopg3 context-manager wiring."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


def _make_tiger_zip(
    geometries_with_statefp: list[tuple[str, shapely.geometry.base.BaseGeometry]],
    *,
    crs: str = "EPSG:4269",
) -> bytes:
    """Synthesize a minimal valid TIGER-shaped ZIP using geopandas.GeoDataFrame.to_file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)
        gdf = geopandas.GeoDataFrame(
            {"STATEFP": [statefp for statefp, _ in geometries_with_statefp]},
            geometry=[g for _, g in geometries_with_statefp],
            crs=crs,
        )
        shp_path = tmpdir_path / "tl_2024_us_state.shp"
        gdf.to_file(shp_path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in tmpdir_path.iterdir():
                zf.write(p, arcname=p.name)
        return buf.getvalue()


def _simple_co_polygon() -> Polygon:
    """Polygon approximating Colorado's bounding box."""
    return Polygon(
        [(-109.06, 36.99), (-102.04, 36.99), (-102.04, 41.00), (-109.06, 41.00), (-109.06, 36.99)]
    )


def _bowtie_co_polygon() -> Polygon:
    """A self-intersecting bowtie polygon (invalid geometry — make_valid should repair it)."""
    return Polygon([(-109, 37), (-102, 41), (-102, 37), (-109, 41), (-109, 37)])


def _simple_co_multipolygon() -> MultiPolygon:
    """A 2-part MultiPolygon (non-adjacent parts) for testing the no-double-wrap passthrough.

    Parts must be non-adjacent (have a gap between them) so the shapefile
    round-trip does not collapse them into a GeometryCollection.
    """
    part1 = Polygon(
        [(-109.06, 36.99), (-106.00, 36.99), (-106.00, 39.00), (-109.06, 39.00), (-109.06, 36.99)]
    )
    # Leave a 1-degree gap at x=-105 so the parts don't share an edge.
    part2 = Polygon(
        [(-104.00, 36.99), (-102.04, 36.99), (-102.04, 41.00), (-104.00, 41.00), (-104.00, 36.99)]
    )
    return MultiPolygon([part1, part2])


# ---------------------------------------------------------------------------
# Module-level canned payloads — built once at import time for speed.
# Three features: CO (filtered in) + MT + CA (both filtered out).
# ---------------------------------------------------------------------------

_CANNED_TIGER_ZIP: bytes = _make_tiger_zip(
    [
        ("08", _simple_co_polygon()),  # Colorado — kept
        ("30", _simple_co_polygon()),  # Montana  — filtered out
        ("06", _simple_co_polygon()),  # California — filtered out
    ]
)
_CANNED_SHA256: str = hashlib.sha256(_CANNED_TIGER_ZIP).hexdigest()


# ---------------------------------------------------------------------------
# TestVerifySha256
# ---------------------------------------------------------------------------


class TestVerifySha256:
    def test_match_returns_observed_digest(self) -> None:
        """Matching SHA-256 returns the observed digest string."""
        payload = b"colorado state boundary test payload"
        expected = hashlib.sha256(payload).hexdigest()
        observed = _verify_sha256(payload, expected)
        assert observed == expected

    def test_mismatch_raises_with_both_digests(self) -> None:
        """SHA-256 mismatch raises RuntimeError containing both observed and expected digests."""
        payload = b"colorado state boundary test payload"
        observed_sha = hashlib.sha256(payload).hexdigest()
        bogus_expected = "0" * 64

        with pytest.raises(RuntimeError) as exc_info:
            _verify_sha256(payload, bogus_expected)

        message = str(exc_info.value)
        assert observed_sha in message
        assert bogus_expected in message


# ---------------------------------------------------------------------------
# TestParseToMultipolygonWkt
# ---------------------------------------------------------------------------


class TestParseToMultipolygonWkt:
    def test_filters_to_statefp_08_and_returns_multipolygon_wkt(self) -> None:
        """CANNED ZIP (CO + MT + CA rows) → only CO row used → WKT starts with MULTIPOLYGON."""
        wkt = _parse_to_multipolygon_wkt(_CANNED_TIGER_ZIP)
        assert wkt.startswith("MULTIPOLYGON")

    def test_reprojects_from_4269_to_4326(self) -> None:
        """Loader reprojects NAD83 → WGS84; resulting WKT coordinates lie within CO bbox."""
        # Default crs="EPSG:4269" simulates the actual TIGER source CRS.
        zip_4269 = _make_tiger_zip([("08", _simple_co_polygon())], crs="EPSG:4269")
        wkt = _parse_to_multipolygon_wkt(zip_4269)
        geom = shapely.from_wkt(wkt)
        assert geom is not None
        bounds = geom.bounds  # (minx, miny, maxx, maxy)
        # Allow ±0.5° tolerance for reprojection drift (NAD83↔WGS84 difference for CO is sub-meter).
        assert bounds[0] >= -109.06 - 0.5  # minx (west)
        assert bounds[2] <= -102.04 + 0.5  # maxx (east)
        assert bounds[1] >= 36.99 - 0.5    # miny (south)
        assert bounds[3] <= 41.00 + 0.5    # maxy (north)

        # Also verify that input already in EPSG:4326 does not break the loader
        # (unconditional to_crs(4326) on already-WGS84 input is a no-op).
        zip_4326 = _make_tiger_zip([("08", _simple_co_polygon())], crs="EPSG:4326")
        wkt_4326 = _parse_to_multipolygon_wkt(zip_4326)
        geom_4326 = shapely.from_wkt(wkt_4326)
        assert geom_4326 is not None
        assert wkt_4326.startswith("MULTIPOLYGON")

    def test_singleton_polygon_wrapped_as_multipolygon(self) -> None:
        """A single Polygon feature for CO is wrapped into a MultiPolygon."""
        zip_bytes = _make_tiger_zip([("08", _simple_co_polygon())])
        wkt = _parse_to_multipolygon_wkt(zip_bytes)
        assert wkt.startswith("MULTIPOLYGON")

    def test_already_multipolygon_passthrough(self) -> None:
        """A CO feature already typed MultiPolygon passes through without double-wrapping."""
        mp = _simple_co_multipolygon()
        zip_bytes = _make_tiger_zip([("08", mp)])
        wkt = _parse_to_multipolygon_wkt(zip_bytes)
        assert wkt.startswith("MULTIPOLYGON")
        # Part count must equal the original input's parts — no double-wrap.
        result_geom = shapely.from_wkt(wkt)
        assert isinstance(result_geom, MultiPolygon)
        assert len(result_geom.geoms) == len(mp.geoms)

    def test_bowtie_repaired_via_make_valid(self) -> None:
        """Self-intersecting bowtie polygon is repaired by make_valid and returns valid WKT."""
        bowtie = _bowtie_co_polygon()
        assert not bowtie.is_valid, "fixture must be invalid for this test to be meaningful"

        zip_bytes = _make_tiger_zip([("08", bowtie)])
        # Should not raise — make_valid repairs the bowtie.
        wkt = _parse_to_multipolygon_wkt(zip_bytes)
        assert isinstance(wkt, str)
        result_geom = shapely.from_wkt(wkt)
        assert result_geom is not None
        assert result_geom.is_valid

    def test_zero_co_features_raises(self) -> None:
        """ZIP with only non-CO STATEFP rows raises RuntimeError naming STATEFP filter '08'."""
        zip_bytes = _make_tiger_zip(
            [
                ("30", _simple_co_polygon()),  # Montana only
                ("06", _simple_co_polygon()),  # California only
            ]
        )
        with pytest.raises(RuntimeError) as exc_info:
            _parse_to_multipolygon_wkt(zip_bytes)
        message = str(exc_info.value)
        assert "08" in message

    def test_multiple_co_features_raises(self) -> None:
        """ZIP with two STATEFP='08' rows raises RuntimeError naming count 2."""
        zip_bytes = _make_tiger_zip(
            [
                ("08", _simple_co_polygon()),
                ("08", _simple_co_polygon()),  # duplicate
            ]
        )
        with pytest.raises(RuntimeError) as exc_info:
            _parse_to_multipolygon_wkt(zip_bytes)
        message = str(exc_info.value)
        assert "2" in message
        assert "08" in message

    def test_zip_missing_shp_raises(self) -> None:
        """ZIP that contains no .shp file raises RuntimeError naming the missing .shp."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README.txt", "no shapefile here")
        zip_bytes = buf.getvalue()

        with pytest.raises(RuntimeError) as exc_info:
            _parse_to_multipolygon_wkt(zip_bytes)
        message = str(exc_info.value)
        assert "TIGER ZIP missing .shp file" in message

    def test_invalid_zip_payload_raises(self) -> None:
        """Non-ZIP payload raises RuntimeError wrapping BadZipFile; message names the source URL."""
        with pytest.raises(RuntimeError) as exc_info:
            _parse_to_multipolygon_wkt(b"not a zip")
        assert "not a valid ZIP archive" in str(exc_info.value)


# ---------------------------------------------------------------------------
# TestBuildSourceCitation
# ---------------------------------------------------------------------------


class TestBuildSourceCitation:
    def test_returns_source_citation_with_pinned_id(self) -> None:
        citation = _build_source_citation()
        assert citation.id == "co-census-tiger-state-2024"

    def test_document_type_is_gis_layer(self) -> None:
        citation = _build_source_citation()
        assert citation.document_type == "gis_layer"

    def test_publication_date_is_2026_01_01(self) -> None:
        citation = _build_source_citation()
        assert citation.publication_date == "2026-01-01"

    def test_agency_is_us_census_bureau(self) -> None:
        citation = _build_source_citation()
        assert citation.agency == "US Census Bureau"


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


def _make_connect_cm(mock_conn: MagicMock) -> MagicMock:
    """Wrap mock_conn in a context manager so `with db.connect() as conn:` yields mock_conn."""
    connect_cm = MagicMock()
    connect_cm.__enter__ = MagicMock(return_value=mock_conn)
    connect_cm.__exit__ = MagicMock(return_value=False)
    return connect_cm


class TestMain:
    def _run_main_with_mocks(self, mock_conn: MagicMock) -> None:
        """Patch _fetch_source_bytes, STATE_BOUNDARY_SHA256, and db.connect; run main([])."""
        connect_cm = _make_connect_cm(mock_conn)
        with (
            patch(
                "states.colorado.load_state_boundary._fetch_source_bytes",
                return_value=_CANNED_TIGER_ZIP,
            ),
            patch(
                "states.colorado.load_state_boundary.STATE_BOUNDARY_SHA256",
                _CANNED_SHA256,
            ),
            patch.object(db_module, "connect", return_value=connect_cm),
        ):
            main([])

    def test_main_writes_one_geometry_row(self) -> None:
        """main([]) calls cursor.execute exactly once with the upsert SQL."""
        mock_conn, mock_cursor = _make_mock_conn()
        self._run_main_with_mocks(mock_conn)

        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args

        # First positional arg is the SQL string.
        sql: str = call_args[0][0]
        assert sql == _UPSERT_SQL

        # Second positional arg is the params tuple.
        params: tuple[object, ...] = call_args[0][1]

        # Parameter order from _UPSERT_SQL:
        # (id, name, kind, geom_wkt, state, license_year, source_json, verbatim_rule, legal_description)
        id_val = params[0]
        kind_val = params[2]
        state_val = params[4]
        license_year_val = params[5]

        assert id_val == "CO-STATEWIDE-geom"
        assert kind_val == "state"
        assert state_val == "US-CO"
        assert license_year_val is None

    def test_main_commits_after_upsert(self) -> None:
        """main([]) commits exactly once after the upsert (single atomic commit)."""
        mock_conn, _mock_cursor = _make_mock_conn()
        self._run_main_with_mocks(mock_conn)
        mock_conn.commit.assert_called_once()

    def test_main_raises_on_sha_mismatch_and_does_not_commit(self) -> None:
        """SHA mismatch → RuntimeError; commit must NOT be called (write gate holds)."""
        mock_conn, mock_cursor = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)

        with (
            patch(
                "states.colorado.load_state_boundary._fetch_source_bytes",
                return_value=_CANNED_TIGER_ZIP,
                # _CANNED_SHA256 != production STATE_BOUNDARY_SHA256 → mismatch
            ),
            patch.object(db_module, "connect", return_value=connect_cm),
            pytest.raises(RuntimeError),
        ):
            main([])

        mock_conn.commit.assert_not_called()
        mock_cursor.execute.assert_not_called()
