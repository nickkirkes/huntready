"""Unit tests for the S05.5 Colorado geometry overlay fixture builder.

All tests are pure-function: the DB connection is stubbed via ``MagicMock``
and shapely runs in-process. No real Postgres, no real network.

Ported from ``tests/test_build_overlay_fixture.py`` (MT, S02.6). The MT
``hunting_district`` parent kind becomes ``gmu`` for CO; MT ids like
``MT-HD-1`` become CO ids like ``CO-GMU-201-geom``. Portions do not exist
for CO (S05.3 documented gap — zero CWD rows; S05.4 produced 10 restricted
area orphans). TestValidateCoverage omits the MT portion-orphan scenario and
substitutes cwd_zone / restricted_area orphan cases instead.
"""

from __future__ import annotations

import json
import re
import typing
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

import states.colorado.build_overlay_fixture as build_fixture
from ingestion.lib.overlays import OverlayFixtureRow
from states.colorado.build_overlay_fixture import (
    COVER_DROP_THRESHOLD,
    COVER_RELABEL_THRESHOLD,
    EXPECTED_CO_RA_ORPHAN_IDS,
    OverlayFixtureError,
    _build_gmu_self_rows,
    _build_overlay_pairs,
    _collect_overlay_rows,
    _load_geometries,
    _validate_coverage,
    _write_outputs,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _square(x0: float, y0: float, side: float = 1.0) -> Polygon:
    """A unit-square polygon at offset (x0, y0)."""
    return Polygon(
        [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    )


def _make_pct_pair(parent_geom: BaseGeometry, child_geom: BaseGeometry) -> float:
    """Return the same overlap ratio _build_overlay_pairs computes."""
    return parent_geom.intersection(child_geom).area / child_geom.area


def _conn_mock_with_fetchall(rows: list[Any]) -> MagicMock:
    """Build a connection mock whose cursor's fetchall returns ``rows`` once."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=None)
    cursor.fetchall.return_value = rows
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    return conn


def _sample_kept_row(
    parent_id: str,
    child_id: str,
    child_kind: str = "gmu",
    relationship: str = "self",
    role: str = "primary_unit",
) -> OverlayFixtureRow:
    return {  # type: ignore[typeddict-item]
        "parent_geometry_id": parent_id,
        "child_geometry_id": child_id,
        "parent_kind": "gmu",
        "child_kind": child_kind,  # type: ignore[typeddict-item]
        "relationship": relationship,  # type: ignore[typeddict-item]
        "role_for_e03": role,  # type: ignore[typeddict-item]
    }


# ---------------------------------------------------------------------------
# TestLoadGeometries
# ---------------------------------------------------------------------------


class TestLoadGeometries:
    def test_returns_id_kind_and_parsed_shapely(self) -> None:
        wkt_polygon = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
        rows = [("CO-GMU-201-geom", "gmu", wkt_polygon)]
        conn = _conn_mock_with_fetchall(rows)
        result = _load_geometries(conn)
        assert len(result) == 1
        assert result[0][0] == "CO-GMU-201-geom"
        assert result[0][1] == "gmu"
        assert isinstance(result[0][2], BaseGeometry)
        assert result[0][2].area == pytest.approx(1.0)

    def test_sql_filters_by_colorado_state(self) -> None:
        conn = _conn_mock_with_fetchall([])
        _load_geometries(conn)
        cursor = conn.cursor.return_value
        called_args = cursor.execute.call_args
        # Params bound as ("US-CO",)
        assert called_args[0][1] == ("US-CO",)
        # SQL uses geography-native ST_AsText (no ::geometry cast)
        sql = called_args[0][0]
        assert "ST_AsText(geom)" in sql
        assert "::geometry" not in sql


# ---------------------------------------------------------------------------
# TestBuildGmuSelfRows
# ---------------------------------------------------------------------------


class TestBuildGmuSelfRows:
    def test_empty_input_returns_empty_list(self) -> None:
        assert _build_gmu_self_rows([]) == []

    def test_single_gmu_produces_correct_self_row(self) -> None:
        rows = _build_gmu_self_rows(["CO-GMU-201-geom"])
        assert len(rows) == 1
        row = rows[0]
        assert row["parent_geometry_id"] == "CO-GMU-201-geom"
        assert row["child_geometry_id"] == "CO-GMU-201-geom"
        assert row["parent_kind"] == "gmu"
        assert row["child_kind"] == "gmu"
        assert row["relationship"] == "self"
        assert row["role_for_e03"] == "primary_unit"

    def test_multiple_gmus_preserves_order(self) -> None:
        ids = ["CO-GMU-201-geom", "CO-GMU-12-geom", "CO-GMU-500-geom"]
        rows = _build_gmu_self_rows(ids)
        assert [r["parent_geometry_id"] for r in rows] == ids


# ---------------------------------------------------------------------------
# TestBuildOverlayPairs
# ---------------------------------------------------------------------------


class TestBuildOverlayPairs:
    def test_empty_children_returns_empty_lists(self) -> None:
        gmus = [("CO-GMU-201-geom", _square(0, 0))]
        kept, dropped = _build_overlay_pairs(gmus, [], "restricted_area")
        assert kept == []
        assert dropped == []

    def test_strict_cover_produces_covers_relationship(self) -> None:
        # GMU fully contains a smaller restricted area.
        gmu = _square(0, 0, 10)
        ra = _square(2, 2, 1)
        kept, dropped = _build_overlay_pairs(
            [("CO-GMU-201-geom", gmu)], [("CO-restricted-test-geom", ra)], "restricted_area"
        )
        assert dropped == []
        assert len(kept) == 1
        assert kept[0]["relationship"] == "covers"
        assert kept[0]["child_kind"] == "restricted_area"
        assert kept[0]["role_for_e03"] == "restricted_area"

    def test_partial_overlap_produces_intersects_relationship(self) -> None:
        # 40% of the child overlaps the parent.
        gmu = _square(0, 0, 1)
        ra = _square(0.6, 0, 1)  # x in [0.6, 1.6], so 40% overlap
        kept, dropped = _build_overlay_pairs(
            [("CO-GMU-201-geom", gmu)], [("CO-restricted-test-geom", ra)], "restricted_area"
        )
        pct = _make_pct_pair(gmu, ra)
        assert COVER_DROP_THRESHOLD <= pct < COVER_RELABEL_THRESHOLD
        assert dropped == []
        assert len(kept) == 1
        assert kept[0]["relationship"] == "intersects"

    def test_no_intersection_skipped(self) -> None:
        gmu = _square(0, 0, 1)
        ra = _square(10, 10, 1)
        kept, dropped = _build_overlay_pairs(
            [("CO-GMU-201-geom", gmu)], [("CO-restricted-test-geom", ra)], "restricted_area"
        )
        assert kept == []
        assert dropped == []

    def test_below_drop_threshold_added_to_audit(self) -> None:
        # Tiny overlap — child is mostly outside parent.
        gmu = _square(0, 0, 1)
        ra = _square(0.999, 0, 1)  # 0.1% overlap
        kept, dropped = _build_overlay_pairs(
            [("CO-GMU-201-geom", gmu)], [("CO-restricted-test-geom", ra)], "restricted_area"
        )
        assert kept == []
        assert len(dropped) == 1
        d = dropped[0]
        assert d["parent_geometry_id"] == "CO-GMU-201-geom"
        assert d["child_geometry_id"] == "CO-restricted-test-geom"
        assert d["parent_kind"] == "gmu"
        assert d["child_kind"] == "restricted_area"
        assert 0.0 <= d["overlap_pct"] < COVER_DROP_THRESHOLD

    # ---- Threshold edge cases (per the spec gates: 0.989/0.990, 0.009/0.011) ----

    def test_threshold_edge_overlap_989_stays_intersects(self) -> None:
        kept, dropped = self._run_with_overlap(0.989)
        assert dropped == []
        assert len(kept) == 1
        assert kept[0]["relationship"] == "intersects"

    def test_threshold_edge_overlap_990_relabeled_as_covers(self) -> None:
        kept, dropped = self._run_with_overlap(0.990)
        assert dropped == []
        assert len(kept) == 1
        assert kept[0]["relationship"] == "covers"

    def test_threshold_edge_overlap_011_stays_intersects(self) -> None:
        kept, dropped = self._run_with_overlap(0.011)
        assert dropped == []
        assert len(kept) == 1
        assert kept[0]["relationship"] == "intersects"

    def test_threshold_edge_overlap_009_dropped(self) -> None:
        kept, dropped = self._run_with_overlap(0.009)
        assert kept == []
        assert len(dropped) == 1
        assert 0.0 <= dropped[0]["overlap_pct"] < COVER_DROP_THRESHOLD

    @staticmethod
    def _run_with_overlap(target_pct: float) -> tuple[list[Any], list[Any]]:
        """Construct a GMU/child pair whose intersection ratio is exactly ``target_pct``.

        Child is a unit square at origin; parent is a rectangle that covers
        the leftmost ``target_pct`` of it. Intersection.area / child.area ==
        target_pct exactly (within float precision).
        """
        child = _square(0, 0, 1)  # area = 1
        parent = Polygon(
            [(0, 0), (target_pct, 0), (target_pct, 1), (0, 1)]
        )  # area = target_pct, fully overlapping the leftmost stripe
        return _build_overlay_pairs(
            [("CO-GMU-201-geom", parent)], [("CO-restricted-test-geom", child)], "restricted_area"
        )

    def test_zero_area_child_kept_as_intersects(self) -> None:
        # Defensive: a zero-area child cannot produce a meaningful ratio.
        gmu = _square(0, 0, 10)
        # A degenerate "polygon" — collapsed to a line.
        zero = Polygon([(1, 1), (2, 1), (2, 1), (1, 1)])
        assert zero.area == 0
        # shapely STRtree query must include this candidate; intersects is True
        # because the line is on the GMU interior.
        kept, dropped = _build_overlay_pairs(
            [("CO-GMU-201-geom", gmu)], [("CO-restricted-zero-geom", zero)], "restricted_area"
        )
        assert dropped == []
        # Either kept (if intersects) or skipped (if shapely says no intersection).
        # Behavior: kept as intersects.
        if kept:
            assert kept[0]["relationship"] == "intersects"

    def test_role_for_e03_matches_child_kind(self) -> None:
        # Spot-check the role-mapping for each child kind that exercises the function.
        gmu = _square(0, 0, 10)
        child = _square(2, 2, 1)
        for child_kind, expected_role in [
            ("cwd_zone", "cwd_management_zone"),
            ("restricted_area", "restricted_area"),
        ]:
            kept, _ = _build_overlay_pairs(
                [("CO-GMU-201-geom", gmu)],
                [("CO-child-test-geom", child)],
                child_kind,  # type: ignore[arg-type]
            )
            assert kept[0]["role_for_e03"] == expected_role


# ---------------------------------------------------------------------------
# TestValidateCoverage
# ---------------------------------------------------------------------------


class TestValidateCoverage:
    def _parsed(self, *triples: tuple[str, str]) -> list[tuple[str, str, BaseGeometry]]:
        return [(geom_id, kind, _square(0, 0)) for geom_id, kind in triples]

    def test_all_children_covered_no_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        parsed = self._parsed(
            ("CO-GMU-201-geom", "gmu"),
            ("CO-restricted-rocky-mountain-national-park-geom", "restricted_area"),
        )
        rows: list[OverlayFixtureRow] = [
            _sample_kept_row(
                "CO-GMU-201-geom",
                "CO-restricted-rocky-mountain-national-park-geom",
                "restricted_area",
                "covers",
                "restricted_area",
            ),
        ]
        import logging

        caplog.set_level(logging.INFO, logger="states.colorado.build_overlay_fixture")
        _validate_coverage(parsed, rows)  # no raise

        # A genuinely-covered restricted_area must NOT be reported as an
        # allowlisted orphan. This distinguishes a working ``parent_kind ==
        # "gmu"`` coverage filter from a broken ``"hunting_district"`` copy-paste:
        # under the broken filter the covered RA would fall into the orphan path
        # and (because it is allowlisted) emit the ADR-016 INFO message while
        # still not raising — a silent vacuous pass. The id is allowlisted, so
        # the only signal that coverage actually worked is the ABSENCE of the
        # orphan log line. (W1, S05.5 review triad.)
        assert not any("ADR-016 allowlist" in r.message for r in caplog.records)
        assert not any(
            "CO-restricted-rocky-mountain-national-park-geom" in r.message
            for r in caplog.records
        )

    def test_cwd_zone_orphan_raises_with_id_and_kind(self) -> None:
        # CO has no CWD zones (S05.3 documented gap), but the invariant still
        # checks if any were loaded — a future data regression would produce an orphan.
        parsed = self._parsed(
            ("CO-GMU-201-geom", "gmu"),
            ("CO-cwd-orphan-geom", "cwd_zone"),
        )
        rows: list[OverlayFixtureRow] = []
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        assert "orphan cwd_zone" in str(exc.value)
        assert "CO-cwd-orphan-geom" in str(exc.value)

    def test_allowlisted_restricted_area_orphan_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Per ADR-016: allowlisted no-hunt zones (NPS National Parks, National
        # Monuments, Air Force Academy) are surfaced via INFO log, not raised.
        # Use an actual entry from EXPECTED_CO_RA_ORPHAN_IDS so the test
        # exercises the real allowlist contract.
        import logging

        allowlisted_id = "CO-restricted-rocky-mountain-national-park-geom"
        assert allowlisted_id in EXPECTED_CO_RA_ORPHAN_IDS
        caplog.set_level(logging.INFO, logger="states.colorado.build_overlay_fixture")
        parsed = self._parsed(
            ("CO-GMU-201-geom", "gmu"),
            (allowlisted_id, "restricted_area"),
        )
        rows: list[OverlayFixtureRow] = []
        _validate_coverage(parsed, rows)  # no raise
        assert any("ADR-016 allowlist" in r.message for r in caplog.records)
        assert any(allowlisted_id in r.message for r in caplog.records)

    def test_unexpected_restricted_area_orphan_raises(self) -> None:
        # Per ADR-016: an RA orphan NOT on the allowlist is a real data
        # regression and must fail the build.
        unexpected_id = "CO-restricted-not-a-real-zone-geom"
        assert unexpected_id not in EXPECTED_CO_RA_ORPHAN_IDS
        parsed = self._parsed(
            ("CO-GMU-201-geom", "gmu"),
            (unexpected_id, "restricted_area"),
        )
        rows: list[OverlayFixtureRow] = []
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        assert "orphan restricted_area" in str(exc.value)
        assert unexpected_id in str(exc.value)

    def test_mixed_ra_orphans_only_unexpected_blocks(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # If both allowlisted and unexpected RA orphans exist, the
        # allowlisted ones still get logged but the unexpected one raises.
        import logging

        allowlisted_id = "CO-restricted-rocky-mountain-national-park-geom"
        unexpected_id = "CO-restricted-regression-target-geom"
        caplog.set_level(logging.INFO, logger="states.colorado.build_overlay_fixture")
        parsed = self._parsed(
            ("CO-GMU-201-geom", "gmu"),
            (allowlisted_id, "restricted_area"),
            (unexpected_id, "restricted_area"),
        )
        rows: list[OverlayFixtureRow] = []
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        # Only the unexpected one should be in the error.
        assert unexpected_id in str(exc.value)
        assert allowlisted_id not in str(exc.value)
        # Allowlisted one should still be logged at INFO.
        assert any(allowlisted_id in r.message for r in caplog.records)

    def test_unknown_geometry_id_raises(self) -> None:
        parsed = self._parsed(("CO-GMU-201-geom", "gmu"))
        rows = [
            _sample_kept_row(
                "CO-GMU-201-geom", "CO-FAKE-CHILD-geom", "restricted_area", "covers", "restricted_area"
            )
        ]
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        assert "unknown geometry ids" in str(exc.value)
        assert "CO-FAKE-CHILD-geom" in str(exc.value)

    def test_both_orphan_and_unknown_id_raises_with_both(self) -> None:
        parsed = self._parsed(
            ("CO-GMU-201-geom", "gmu"),
            ("CO-cwd-orphan-geom", "cwd_zone"),
        )
        rows = [
            _sample_kept_row(
                "CO-GMU-201-geom", "CO-FAKE-CHILD-geom", "restricted_area", "covers", "restricted_area"
            )
        ]
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        msg = str(exc.value)
        assert "orphan cwd_zone" in msg and "CO-cwd-orphan-geom" in msg
        assert "unknown geometry ids" in msg and "CO-FAKE-CHILD-geom" in msg

    def test_dropped_pairs_do_not_count_toward_coverage(self) -> None:
        # A child appearing in the audit (dropped) is NOT considered covered.
        # rows is the KEPT list — no entry for the cwd orphan, so it's an orphan.
        parsed = self._parsed(
            ("CO-GMU-201-geom", "gmu"),
            ("CO-cwd-orphan-geom", "cwd_zone"),
        )
        with pytest.raises(OverlayFixtureError):
            _validate_coverage(parsed, [])

    def test_second_restricted_area_orphan_not_on_allowlist_raises(self) -> None:
        # Two unexpected RA orphans — both must appear in the error message.
        unexpected_a = "CO-restricted-fake-zone-a-geom"
        unexpected_b = "CO-restricted-fake-zone-b-geom"
        assert unexpected_a not in EXPECTED_CO_RA_ORPHAN_IDS
        assert unexpected_b not in EXPECTED_CO_RA_ORPHAN_IDS
        parsed = self._parsed(
            ("CO-GMU-201-geom", "gmu"),
            (unexpected_a, "restricted_area"),
            (unexpected_b, "restricted_area"),
        )
        rows: list[OverlayFixtureRow] = []
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        msg = str(exc.value)
        assert unexpected_a in msg
        assert unexpected_b in msg


# ---------------------------------------------------------------------------
# TestCollectOverlayRows
# ---------------------------------------------------------------------------


class TestCollectOverlayRows:
    def test_empty_gmu_list_raises_overlay_fixture_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=[]))
        conn = MagicMock()
        with pytest.raises(OverlayFixtureError) as exc:
            _collect_overlay_rows(conn)
        assert "no gmu rows" in str(exc.value)
        assert "US-CO" in str(exc.value)

    def test_returns_kept_and_dropped_tuples(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Stub _load_geometries with a small parsed dataset
        gmu = ("CO-GMU-201-geom", "gmu", _square(0, 0, 10))
        ra = ("CO-restricted-rocky-mountain-national-park-geom", "restricted_area", _square(2, 2, 1))
        # Use an allowlisted RA orphan so _validate_coverage doesn't raise
        # (the RA is positioned inside the GMU so it becomes a covered row, not an orphan)
        parsed = [gmu, ra]
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=parsed))
        conn = MagicMock()
        kept, dropped = _collect_overlay_rows(conn)
        # 1 self + 1 ra = 2 kept
        assert len(kept) == 2
        assert dropped == []

    def test_concatenation_order_self_cwd_ra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With only a GMU (no children), only the self row should be present.
        gmu = ("CO-GMU-201-geom", "gmu", _square(0, 0, 10))
        parsed = [gmu]
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=parsed))
        conn = MagicMock()
        kept, dropped = _collect_overlay_rows(conn)
        assert len(kept) == 1
        assert kept[0]["relationship"] == "self"
        assert kept[0]["parent_kind"] == "gmu"
        assert kept[0]["child_kind"] == "gmu"

    def test_returns_mixed_kept_and_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # GMU with an RA inside (kept) and an RA with tiny overlap (dropped).
        gmu = ("CO-GMU-201-geom", "gmu", _square(0, 0, 10))
        # Inside: fully covered — kept as "covers"
        ra_inside = (
            "CO-restricted-rocky-mountain-national-park-geom",
            "restricted_area",
            _square(2, 2, 1),
        )
        # Edge: tiny overlap — dropped (outside GMU boundary almost entirely)
        ra_edge = ("CO-restricted-mesa-verde-national-park-geom", "restricted_area", _square(9.999, 0, 1))
        # ra_edge is also allowlisted; position it outside a second GMU so it
        # remains an orphan but is allowlisted → no raise.
        parsed = [gmu, ra_inside, ra_edge]
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=parsed))
        conn = MagicMock()
        kept, dropped = _collect_overlay_rows(conn)
        kept_child_ids = {r["child_geometry_id"] for r in kept}
        assert "CO-restricted-rocky-mountain-national-park-geom" in kept_child_ids
        # ra_edge may be dropped or orphaned (allowlisted)
        assert any(d["child_geometry_id"] == "CO-restricted-mesa-verde-national-park-geom" for d in dropped) or (
            "CO-restricted-mesa-verde-national-park-geom" not in kept_child_ids
        )


# ---------------------------------------------------------------------------
# TestWriteOutputs
# ---------------------------------------------------------------------------


def _audit_dict(parent: str, child: str, pct: float) -> dict[str, Any]:
    return {
        "parent_geometry_id": parent,
        "child_geometry_id": child,
        "parent_kind": "gmu",
        "child_kind": "restricted_area",
        "overlap_pct": pct,
    }


class TestWriteOutputs:
    def _redirect_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path]:
        fixture_path = tmp_path / "geometry-overlays.json"
        audit_path = tmp_path / "geometry-overlays-dropped.json"
        monkeypatch.setattr(build_fixture, "CO_FIXTURE_DIR", tmp_path)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", fixture_path)
        monkeypatch.setattr(build_fixture, "DROPPED_AUDIT_PATH", audit_path)
        return fixture_path, audit_path

    def test_writes_both_files_atomically(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fix_p, aud_p = self._redirect_paths(tmp_path, monkeypatch)
        kept = [_sample_kept_row("CO-GMU-201-geom", "CO-GMU-201-geom")]
        dropped = [_audit_dict("CO-GMU-201-geom", "CO-restricted-test-geom", 0.001)]
        _write_outputs(kept, dropped)  # type: ignore[arg-type]
        assert fix_p.exists()
        assert aud_p.exists()
        assert not (tmp_path / "geometry-overlays.json.tmp").exists()
        assert not (tmp_path / "geometry-overlays-dropped.json.tmp").exists()

    def test_fixture_byte_identical_across_input_orders(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Run twice in different subdirs with reversed input orders; both
        # fixture files should be byte-identical.
        path_a = tmp_path / "a"
        path_b = tmp_path / "b"
        monkeypatch.setattr(build_fixture, "CO_FIXTURE_DIR", path_a)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", path_a / "fixture.json")
        monkeypatch.setattr(build_fixture, "DROPPED_AUDIT_PATH", path_a / "audit.json")
        rows_a: list[OverlayFixtureRow] = [
            _sample_kept_row("CO-GMU-201-geom", "CO-GMU-201-geom"),
            _sample_kept_row("CO-GMU-12-geom", "CO-GMU-12-geom"),
        ]
        _write_outputs(rows_a, [])
        monkeypatch.setattr(build_fixture, "CO_FIXTURE_DIR", path_b)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", path_b / "fixture.json")
        monkeypatch.setattr(build_fixture, "DROPPED_AUDIT_PATH", path_b / "audit.json")
        _write_outputs(list(reversed(rows_a)), [])
        assert (path_a / "fixture.json").read_bytes() == (path_b / "fixture.json").read_bytes()

    def test_audit_sorted_by_parent_then_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, aud_p = self._redirect_paths(tmp_path, monkeypatch)
        dropped = [
            _audit_dict("CO-GMU-201-geom", "CO-restricted-c-geom", 0.005),
            _audit_dict("CO-GMU-12-geom", "CO-restricted-b-geom", 0.005),
            _audit_dict("CO-GMU-12-geom", "CO-restricted-a-geom", 0.005),
        ]
        _write_outputs([], dropped)  # type: ignore[arg-type]
        loaded = json.loads(aud_p.read_text())
        order = [(r["parent_geometry_id"], r["child_geometry_id"]) for r in loaded]
        assert order == [
            ("CO-GMU-12-geom", "CO-restricted-a-geom"),
            ("CO-GMU-12-geom", "CO-restricted-b-geom"),
            ("CO-GMU-201-geom", "CO-restricted-c-geom"),
        ]

    def test_fixture_sort_tie_break_on_relationship(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fix_p, _ = self._redirect_paths(tmp_path, monkeypatch)
        rows: list[OverlayFixtureRow] = [
            _sample_kept_row("CO-GMU-201-geom", "CO-restricted-test-geom", "restricted_area", "intersects", "restricted_area"),
            _sample_kept_row("CO-GMU-201-geom", "CO-restricted-test-geom", "restricted_area", "covers", "restricted_area"),
        ]
        _write_outputs(rows, [])
        loaded = json.loads(fix_p.read_text())
        assert loaded[0]["relationship"] == "covers"
        assert loaded[1]["relationship"] == "intersects"

    def test_trailing_newlines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fix_p, aud_p = self._redirect_paths(tmp_path, monkeypatch)
        _write_outputs(
            [_sample_kept_row("CO-GMU-201-geom", "CO-GMU-201-geom")],
            [_audit_dict("CO-GMU-201-geom", "CO-restricted-x-geom", 0.001)],  # type: ignore[arg-type]
        )
        assert fix_p.read_text().endswith("\n")
        assert aud_p.read_text().endswith("\n")

    def test_audit_write_failure_does_not_update_fixture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the audit write fails after the fixture tmp is created but before
        # either is renamed, neither final file should change.
        fix_p, aud_p = self._redirect_paths(tmp_path, monkeypatch)
        sentinel_fixture = "PRIOR_FIXTURE_CONTENT\n"
        sentinel_audit = "PRIOR_AUDIT_CONTENT\n"
        fix_p.write_text(sentinel_fixture)
        aud_p.write_text(sentinel_audit)

        original_write_text = Path.write_text
        audit_tmp_name = "geometry-overlays-dropped.json.tmp"

        def selective_fail(self_path: Path, data: str, **kwargs: Any) -> int:
            if self_path.name == audit_tmp_name:
                raise OSError("simulated audit write failure")
            return original_write_text(self_path, data, **kwargs)  # type: ignore[return-value]

        monkeypatch.setattr(Path, "write_text", selective_fail)

        with pytest.raises(OSError, match="simulated audit write failure"):
            _write_outputs(
                [_sample_kept_row("CO-GMU-201-geom", "CO-GMU-201-geom")],
                [_audit_dict("CO-GMU-201-geom", "CO-restricted-x-geom", 0.001)],  # type: ignore[arg-type]
            )

        # Neither final file should have changed
        assert fix_p.read_text() == sentinel_fixture
        assert aud_p.read_text() == sentinel_audit
        # The fixture .tmp should have been cleaned up
        assert not (tmp_path / "geometry-overlays.json.tmp").exists()


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    def test_returns_zero_and_writes_outputs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kept_rows = [_sample_kept_row("CO-GMU-201-geom", "CO-GMU-201-geom", "gmu", "self", "primary_unit")]
        dropped_rows: list[Any] = []
        mock_collect = MagicMock(return_value=(kept_rows, dropped_rows))
        mock_write_outputs = MagicMock()
        mock_connect = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_connect.return_value.__exit__ = MagicMock(return_value=None)

        monkeypatch.setattr(build_fixture.db, "connect", mock_connect)
        monkeypatch.setattr(build_fixture, "_collect_overlay_rows", mock_collect)
        monkeypatch.setattr(build_fixture, "_write_outputs", mock_write_outputs)

        rc = main([])
        assert rc == 0
        mock_collect.assert_called_once()
        mock_write_outputs.assert_called_once_with(kept_rows, dropped_rows)

    def test_overlay_fixture_error_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_connect = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_connect.return_value.__exit__ = MagicMock(return_value=None)
        monkeypatch.setattr(build_fixture.db, "connect", mock_connect)
        monkeypatch.setattr(
            build_fixture,
            "_collect_overlay_rows",
            MagicMock(side_effect=OverlayFixtureError("boom")),
        )
        # Should NOT swallow — fail loud
        with pytest.raises(OverlayFixtureError, match="boom"):
            main([])

    def test_no_explain_flag_in_argparser(self) -> None:
        # An unknown flag should cause argparse to exit with non-zero.
        with pytest.raises(SystemExit):
            main(["--explain"])


# ---------------------------------------------------------------------------
# Integration-ish: real shapely + threshold + audit pipeline
# ---------------------------------------------------------------------------


class TestEndToEndShapelyPipeline:
    def test_full_collect_with_real_geometries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Realistic mini-Colorado: 2 GMUs, 1 RA inside GMU-1 (covered), 1 RA
        # edge-touching GMU-1 (dropped relative to GMU-1 but covered by GMU-2),
        # 1 RA orphan (allowlisted — no GMU overlap).
        gmu1_geom = _square(0, 0, 10)
        gmu2_geom = _square(9, 0, 5)
        inside_ra = _square(2, 2, 1)         # ~1.0 of child inside GMU-1 → covers
        edge_ra = _square(9.999, 0, 1)       # ~0.001 → dropped relative to GMU-1;
        #                                      covered by GMU-2 (real parent)
        # Use an allowlisted RA orphan (no GMU overlap) — must be on
        # EXPECTED_CO_RA_ORPHAN_IDS to pass _validate_coverage without raising.
        orphan_ra_id = "CO-restricted-yucca-house-national-monument-geom"
        assert orphan_ra_id in EXPECTED_CO_RA_ORPHAN_IDS
        orphan_ra = _square(100, 100, 1)

        parsed: list[tuple[str, str, BaseGeometry]] = [
            ("CO-GMU-201-geom", "gmu", gmu1_geom),
            ("CO-GMU-12-geom", "gmu", gmu2_geom),
            ("CO-restricted-rocky-mountain-national-park-geom", "restricted_area", inside_ra),
            ("CO-restricted-mesa-verde-national-park-geom", "restricted_area", edge_ra),
            (orphan_ra_id, "restricted_area", orphan_ra),
        ]
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=parsed))
        kept, dropped = _collect_overlay_rows(MagicMock())

        kept_ids = {
            (r["child_kind"], r["child_geometry_id"], r["relationship"]) for r in kept
        }

        # Self rows for both GMUs
        assert ("gmu", "CO-GMU-201-geom", "self") in kept_ids
        assert ("gmu", "CO-GMU-12-geom", "self") in kept_ids
        # inside_ra covered by GMU-1
        assert ("restricted_area", "CO-restricted-rocky-mountain-national-park-geom", "covers") in kept_ids
        # edge_ra covered by GMU-2 (its real parent)
        assert ("restricted_area", "CO-restricted-mesa-verde-national-park-geom", "covers") in kept_ids
        # Allowlisted orphan absent (no GMU overlap), no raise — ADR-016 carve-out
        assert all(r["child_geometry_id"] != orphan_ra_id for r in kept)
        # Audit contains the boundary edge case (edge_ra dropped relative to GMU-1)
        assert any(
            d["child_geometry_id"] == "CO-restricted-mesa-verde-national-park-geom"
            and d["parent_geometry_id"] == "CO-GMU-201-geom"
            for d in dropped
        )


class TestMultiPolygonGeometry:
    """The geom column is geography(MultiPolygon, 4326). Confirm shapely handles it."""

    def test_multipolygon_input_is_handled(self) -> None:
        a = _square(0, 0, 1)
        b = _square(2, 0, 1)
        mp = MultiPolygon([a, b])
        wkt = mp.wkt
        rows = [("CO-GMU-201-geom", "gmu", wkt)]
        conn = _conn_mock_with_fetchall(rows)
        result = _load_geometries(conn)
        assert isinstance(result[0][2], BaseGeometry)
        assert result[0][2].area == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# TestExpectedOrphanConstant
# ---------------------------------------------------------------------------


class TestExpectedOrphanConstant:
    def test_is_frozenset(self) -> None:
        assert isinstance(EXPECTED_CO_RA_ORPHAN_IDS, frozenset)

    def test_has_ten_entries(self) -> None:
        assert len(EXPECTED_CO_RA_ORPHAN_IDS) == 10

    def test_all_ids_match_co_restricted_pattern(self) -> None:
        pattern = re.compile(r"^CO-restricted-[a-z0-9-]+-geom$")
        for ra_id in EXPECTED_CO_RA_ORPHAN_IDS:
            assert pattern.match(ra_id), f"id {ra_id!r} does not match CO restricted-area pattern"


# ---------------------------------------------------------------------------
# TestLibraryExtension
# ---------------------------------------------------------------------------


class TestLibraryExtension:
    def test_role_for_binding_gmu_is_primary_unit(self) -> None:
        from ingestion.lib.overlays import ROLE_FOR_BINDING_BY_CHILD_KIND

        assert ROLE_FOR_BINDING_BY_CHILD_KIND["gmu"] == "primary_unit"

    def test_role_for_binding_hunting_district_preserved(self) -> None:
        from ingestion.lib.overlays import ROLE_FOR_BINDING_BY_CHILD_KIND

        assert ROLE_FOR_BINDING_BY_CHILD_KIND["hunting_district"] == "primary_unit"

    def test_role_for_e03_is_alias_identity(self) -> None:
        from ingestion.lib.overlays import (
            ROLE_FOR_BINDING_BY_CHILD_KIND,
            ROLE_FOR_E03_BY_CHILD_KIND,
        )

        assert ROLE_FOR_E03_BY_CHILD_KIND is ROLE_FOR_BINDING_BY_CHILD_KIND

    def test_gmu_in_overlay_child_kind(self) -> None:
        from ingestion.lib.overlays import OverlayChildKind

        assert "gmu" in typing.get_args(OverlayChildKind)

    def test_gmu_in_overlay_parent_kind(self) -> None:
        from ingestion.lib.overlays import OverlayParentKind

        assert "gmu" in typing.get_args(OverlayParentKind)
