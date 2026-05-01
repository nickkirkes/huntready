"""Unit tests for the S02.6 geometry overlay fixture builder.

All tests are pure-function: the DB connection is stubbed via ``MagicMock``
and shapely runs in-process. No real Postgres, no real network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

import states.montana.build_overlay_fixture as build_fixture
from ingestion.lib.overlays import OverlayFixtureRow
from states.montana.build_overlay_fixture import (
    COVER_DROP_THRESHOLD,
    COVER_RELABEL_THRESHOLD,
    EXPECTED_RA_ORPHAN_IDS,
    OverlayFixtureError,
    _build_hd_self_rows,
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
    return Polygon([(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)])


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
    child_kind: str = "portion",
    relationship: str = "covers",
    role: str = "portion",
) -> OverlayFixtureRow:
    return {  # type: ignore[typeddict-item]
        "parent_geometry_id": parent_id,
        "child_geometry_id": child_id,
        "parent_kind": "hunting_district",
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
        rows = [("geom-1", "hunting_district", wkt_polygon)]
        conn = _conn_mock_with_fetchall(rows)
        result = _load_geometries(conn)
        assert len(result) == 1
        assert result[0][0] == "geom-1"
        assert result[0][1] == "hunting_district"
        assert isinstance(result[0][2], BaseGeometry)
        assert result[0][2].area == pytest.approx(1.0)

    def test_sql_filters_by_montana_state(self) -> None:
        conn = _conn_mock_with_fetchall([])
        _load_geometries(conn)
        cursor = conn.cursor.return_value
        called_args = cursor.execute.call_args
        # Params bound as ("US-MT",)
        assert called_args[0][1] == ("US-MT",)
        # SQL uses geography-native ST_AsText (no ::geometry cast)
        sql = called_args[0][0]
        assert "ST_AsText(geom)" in sql
        assert "::geometry" not in sql


# ---------------------------------------------------------------------------
# TestBuildHdSelfRows
# ---------------------------------------------------------------------------


class TestBuildHdSelfRows:
    def test_empty_input_returns_empty_list(self) -> None:
        assert _build_hd_self_rows([]) == []

    def test_single_hd_produces_correct_self_row(self) -> None:
        rows = _build_hd_self_rows(["MT-HD-1"])
        assert len(rows) == 1
        row = rows[0]
        assert row["parent_geometry_id"] == "MT-HD-1"
        assert row["child_geometry_id"] == "MT-HD-1"
        assert row["parent_kind"] == "hunting_district"
        assert row["child_kind"] == "hunting_district"
        assert row["relationship"] == "self"
        assert row["role_for_e03"] == "primary_unit"

    def test_multiple_hds_preserves_order(self) -> None:
        rows = _build_hd_self_rows(["A", "B", "C"])
        assert [r["parent_geometry_id"] for r in rows] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# TestBuildOverlayPairs
# ---------------------------------------------------------------------------


class TestBuildOverlayPairs:
    def test_empty_children_returns_empty_lists(self) -> None:
        hds = [("HD-1", _square(0, 0))]
        kept, dropped = _build_overlay_pairs(hds, [], "portion")
        assert kept == []
        assert dropped == []

    def test_strict_cover_produces_covers_relationship(self) -> None:
        # HD fully contains a smaller portion.
        hd = _square(0, 0, 10)
        portion = _square(2, 2, 1)
        kept, dropped = _build_overlay_pairs([("HD-1", hd)], [("P-1", portion)], "portion")
        assert dropped == []
        assert len(kept) == 1
        assert kept[0]["relationship"] == "covers"
        assert kept[0]["child_kind"] == "portion"
        assert kept[0]["role_for_e03"] == "portion"

    def test_partial_overlap_produces_intersects_relationship(self) -> None:
        # 40% of the child overlaps the parent.
        hd = _square(0, 0, 1)
        portion = _square(0.6, 0, 1)  # x in [0.6, 1.6], so 40% overlap
        kept, dropped = _build_overlay_pairs([("HD-1", hd)], [("P-1", portion)], "portion")
        pct = _make_pct_pair(hd, portion)
        assert COVER_DROP_THRESHOLD <= pct < COVER_RELABEL_THRESHOLD
        assert dropped == []
        assert len(kept) == 1
        assert kept[0]["relationship"] == "intersects"

    def test_no_intersection_skipped(self) -> None:
        hd = _square(0, 0, 1)
        portion = _square(10, 10, 1)
        kept, dropped = _build_overlay_pairs([("HD-1", hd)], [("P-1", portion)], "portion")
        assert kept == []
        assert dropped == []

    def test_below_drop_threshold_added_to_audit(self) -> None:
        # Tiny overlap — child is mostly outside parent.
        hd = _square(0, 0, 1)
        portion = _square(0.999, 0, 1)  # 0.1% overlap
        kept, dropped = _build_overlay_pairs([("HD-1", hd)], [("P-1", portion)], "portion")
        assert kept == []
        assert len(dropped) == 1
        d = dropped[0]
        assert d["parent_geometry_id"] == "HD-1"
        assert d["child_geometry_id"] == "P-1"
        assert d["parent_kind"] == "hunting_district"
        assert d["child_kind"] == "portion"
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
    def _run_with_overlap(target_pct: float) -> tuple[list, list]:
        """Construct an HD/child pair whose intersection ratio is exactly ``target_pct``.

        Child is a unit square at origin; parent is a rectangle that covers
        the leftmost ``target_pct`` of it. Intersection.area / child.area ==
        target_pct exactly (within float precision).
        """
        child = _square(0, 0, 1)  # area = 1
        parent = Polygon(
            [(0, 0), (target_pct, 0), (target_pct, 1), (0, 1)]
        )  # area = target_pct, fully overlapping the leftmost stripe
        return _build_overlay_pairs([("HD-1", parent)], [("C-1", child)], "portion")

    def test_zero_area_child_kept_as_intersects(self) -> None:
        # Defensive: a zero-area child cannot produce a meaningful ratio.
        hd = _square(0, 0, 10)
        # A degenerate "polygon" — collapsed to a line.
        zero = Polygon([(1, 1), (2, 1), (2, 1), (1, 1)])
        assert zero.area == 0
        # shapely STRtree query must include this candidate; intersects is True
        # because the line is on the HD interior.
        kept, dropped = _build_overlay_pairs([("HD-1", hd)], [("Z-1", zero)], "portion")
        assert dropped == []
        # Either kept (if intersects) or skipped (if shapely says no intersection).
        # Behavior: kept as intersects.
        if kept:
            assert kept[0]["relationship"] == "intersects"

    def test_role_for_e03_matches_child_kind(self) -> None:
        # Spot-check the role-mapping for each child kind that exercises the function.
        hd = _square(0, 0, 10)
        child = _square(2, 2, 1)
        for child_kind, expected_role in [
            ("portion", "portion"),
            ("cwd_zone", "cwd_management_zone"),
            ("restricted_area", "restricted_area"),
        ]:
            kept, _ = _build_overlay_pairs([("HD", hd)], [("C", child)], child_kind)  # type: ignore[arg-type]
            assert kept[0]["role_for_e03"] == expected_role


# ---------------------------------------------------------------------------
# TestValidateCoverage
# ---------------------------------------------------------------------------


class TestValidateCoverage:
    def _parsed(self, *triples: tuple[str, str]) -> list[tuple[str, str, BaseGeometry]]:
        return [(geom_id, kind, _square(0, 0)) for geom_id, kind in triples]

    def test_all_children_covered_no_raise(self) -> None:
        parsed = self._parsed(
            ("HD-1", "hunting_district"),
            ("P-1", "portion"),
            ("CWD-1", "cwd_zone"),
            ("RA-1", "restricted_area"),
        )
        rows: list[OverlayFixtureRow] = [
            _sample_kept_row("HD-1", "P-1", "portion", "covers", "portion"),
            _sample_kept_row("HD-1", "CWD-1", "cwd_zone", "intersects", "cwd_management_zone"),
            _sample_kept_row("HD-1", "RA-1", "restricted_area", "covers", "restricted_area"),
        ]
        _validate_coverage(parsed, rows)  # no raise

    def test_portion_orphan_raises_with_id_and_kind(self) -> None:
        parsed = self._parsed(
            ("HD-1", "hunting_district"),
            ("P-1", "portion"),
            ("P-orphan", "portion"),
        )
        rows = [_sample_kept_row("HD-1", "P-1", "portion", "covers", "portion")]
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        assert "orphan portion" in str(exc.value)
        assert "P-orphan" in str(exc.value)

    def test_cwd_orphan_raises_with_id_and_kind(self) -> None:
        parsed = self._parsed(
            ("HD-1", "hunting_district"),
            ("CWD-orphan", "cwd_zone"),
        )
        rows: list[OverlayFixtureRow] = []
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        assert "orphan cwd_zone" in str(exc.value)
        assert "CWD-orphan" in str(exc.value)

    def test_allowlisted_restricted_area_orphan_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Per ADR-016: allowlisted no-hunt zones (national parks, game
        # preserves) are surfaced via INFO log, not raised. Use an actual
        # entry from EXPECTED_RA_ORPHAN_IDS so the test exercises the
        # real allowlist contract.
        import logging
        allowlisted_id = next(iter(EXPECTED_RA_ORPHAN_IDS))
        caplog.set_level(logging.INFO, logger="states.montana.build_overlay_fixture")
        parsed = self._parsed(
            ("HD-1", "hunting_district"),
            (allowlisted_id, "restricted_area"),
        )
        rows: list[OverlayFixtureRow] = []
        _validate_coverage(parsed, rows)  # no raise
        assert any("ADR-016 allowlist" in r.message for r in caplog.records)
        assert any(allowlisted_id in r.message for r in caplog.records)

    def test_unexpected_restricted_area_orphan_raises(self) -> None:
        # Per ADR-016: an RA orphan NOT on the allowlist is a real data
        # regression and must fail the build. This is the protection
        # against silent-tolerance regressions.
        not_allowlisted = "MT-restricted-bigame-some-internal-archery-zone-geom"
        assert not_allowlisted not in EXPECTED_RA_ORPHAN_IDS
        parsed = self._parsed(
            ("HD-1", "hunting_district"),
            (not_allowlisted, "restricted_area"),
        )
        rows: list[OverlayFixtureRow] = []
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        assert "orphan restricted_area" in str(exc.value)
        assert not_allowlisted in str(exc.value)

    def test_mixed_ra_orphans_only_unexpected_blocks(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # If both allowlisted and unexpected RA orphans exist, the
        # allowlisted ones still get logged but the unexpected one raises.
        import logging
        allowlisted_id = next(iter(EXPECTED_RA_ORPHAN_IDS))
        unexpected_id = "MT-restricted-bigame-regression-target-geom"
        caplog.set_level(logging.INFO, logger="states.montana.build_overlay_fixture")
        parsed = self._parsed(
            ("HD-1", "hunting_district"),
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
        parsed = self._parsed(("HD-1", "hunting_district"))
        rows = [_sample_kept_row("HD-1", "FAKE-CHILD", "portion", "covers", "portion")]
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        assert "unknown geometry ids" in str(exc.value)
        assert "FAKE-CHILD" in str(exc.value)

    def test_both_orphan_and_unknown_id_raises_with_both(self) -> None:
        parsed = self._parsed(
            ("HD-1", "hunting_district"),
            ("P-orphan", "portion"),
        )
        rows = [_sample_kept_row("HD-1", "FAKE-CHILD", "portion", "covers", "portion")]
        with pytest.raises(OverlayFixtureError) as exc:
            _validate_coverage(parsed, rows)
        msg = str(exc.value)
        assert "orphan portion" in msg and "P-orphan" in msg
        assert "unknown geometry ids" in msg and "FAKE-CHILD" in msg

    def test_dropped_pairs_do_not_count_toward_coverage(self) -> None:
        # A child appearing in the audit (dropped) is NOT considered covered.
        parsed = self._parsed(
            ("HD-1", "hunting_district"),
            ("P-1", "portion"),
        )
        # rows is the KEPT list — no entry for P-1, so it's an orphan
        with pytest.raises(OverlayFixtureError):
            _validate_coverage(parsed, [])


# ---------------------------------------------------------------------------
# TestCollectOverlayRows
# ---------------------------------------------------------------------------


class TestCollectOverlayRows:
    def test_empty_hd_list_raises_overlay_fixture_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=[]))
        conn = MagicMock()
        with pytest.raises(OverlayFixtureError) as exc:
            _collect_overlay_rows(conn)
        assert "no hunting_district rows" in str(exc.value)
        assert "US-MT" in str(exc.value)

    def test_returns_kept_and_dropped_tuples(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Stub _load_geometries with a small parsed dataset
        hd = ("HD-1", "hunting_district", _square(0, 0, 10))
        portion = ("P-1", "portion", _square(2, 2, 1))   # fully inside HD → covers
        cwd = ("CWD-1", "cwd_zone", _square(8, 0, 4))    # half inside HD → intersects
        ra = ("RA-1", "restricted_area", _square(2, 2, 1))  # fully inside HD → covers
        parsed = [hd, portion, cwd, ra]
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=parsed))
        conn = MagicMock()
        kept, dropped = _collect_overlay_rows(conn)
        # 1 self + 1 portion + 1 cwd + 1 ra = 4 kept
        assert len(kept) == 4
        # No drops at this scale (all overlaps >= 1%)
        assert dropped == []

    def test_concatenation_order_self_portion_cwd_ra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hd = ("HD-1", "hunting_district", _square(0, 0, 10))
        parsed = [hd]
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=parsed))
        conn = MagicMock()
        kept, dropped = _collect_overlay_rows(conn)
        # Only self row should be present; no children to overlay
        assert len(kept) == 1
        assert kept[0]["relationship"] == "self"


# ---------------------------------------------------------------------------
# TestWriteOutputs
# ---------------------------------------------------------------------------


def _audit_dict(parent: str, child: str, pct: float) -> dict:
    return {
        "parent_geometry_id": parent,
        "child_geometry_id": child,
        "parent_kind": "hunting_district",
        "child_kind": "portion",
        "overlap_pct": pct,
    }


class TestWriteOutputs:
    def _redirect_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
        fixture_path = tmp_path / "geometry-overlays.json"
        audit_path = tmp_path / "geometry-overlays-dropped.json"
        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", tmp_path)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", fixture_path)
        monkeypatch.setattr(build_fixture, "DROPPED_AUDIT_PATH", audit_path)
        return fixture_path, audit_path

    def test_writes_both_files_atomically(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fix_p, aud_p = self._redirect_paths(tmp_path, monkeypatch)
        kept = [_sample_kept_row("HD-1", "P-1")]
        dropped = [_audit_dict("HD-1", "P-2", 0.001)]
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
        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", path_a)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", path_a / "fixture.json")
        monkeypatch.setattr(build_fixture, "DROPPED_AUDIT_PATH", path_a / "audit.json")
        rows_a: list[OverlayFixtureRow] = [
            _sample_kept_row("HD-2", "P-2"),
            _sample_kept_row("HD-1", "P-1"),
        ]
        _write_outputs(rows_a, [])
        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", path_b)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", path_b / "fixture.json")
        monkeypatch.setattr(build_fixture, "DROPPED_AUDIT_PATH", path_b / "audit.json")
        _write_outputs(list(reversed(rows_a)), [])
        assert (path_a / "fixture.json").read_bytes() == (path_b / "fixture.json").read_bytes()

    def test_audit_sorted_by_parent_then_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, aud_p = self._redirect_paths(tmp_path, monkeypatch)
        dropped = [
            _audit_dict("HD-2", "C-1", 0.005),
            _audit_dict("HD-1", "C-2", 0.005),
            _audit_dict("HD-1", "C-1", 0.005),
        ]
        _write_outputs([], dropped)  # type: ignore[arg-type]
        loaded = json.loads(aud_p.read_text())
        order = [(r["parent_geometry_id"], r["child_geometry_id"]) for r in loaded]
        assert order == [("HD-1", "C-1"), ("HD-1", "C-2"), ("HD-2", "C-1")]

    def test_fixture_sort_tie_break_on_relationship(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fix_p, _ = self._redirect_paths(tmp_path, monkeypatch)
        rows: list[OverlayFixtureRow] = [
            _sample_kept_row("HD-1", "C-1", "portion", "intersects", "portion"),
            _sample_kept_row("HD-1", "C-1", "portion", "covers", "portion"),
        ]
        _write_outputs(rows, [])
        loaded = json.loads(fix_p.read_text())
        assert loaded[0]["relationship"] == "covers"
        assert loaded[1]["relationship"] == "intersects"

    def test_trailing_newlines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fix_p, aud_p = self._redirect_paths(tmp_path, monkeypatch)
        _write_outputs([_sample_kept_row("HD", "C")], [_audit_dict("HD", "X", 0.001)])  # type: ignore[arg-type]
        assert fix_p.read_text().endswith("\n")
        assert aud_p.read_text().endswith("\n")

    def test_audit_write_failure_does_not_update_fixture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The reviewer's case: if the audit write fails after the fixture
        # tmp is created but before either is renamed, neither final file
        # should change. Pre-populate the destinations with sentinel content
        # so we can detect any write.
        fix_p, aud_p = self._redirect_paths(tmp_path, monkeypatch)
        sentinel_fixture = "PRIOR_FIXTURE_CONTENT\n"
        sentinel_audit = "PRIOR_AUDIT_CONTENT\n"
        fix_p.write_text(sentinel_fixture)
        aud_p.write_text(sentinel_audit)

        # Force the audit .tmp write to fail by making DROPPED_AUDIT_PATH
        # point at a path whose parent doesn't exist (and bypass mkdir).
        # Easier: monkeypatch Path.write_text on the audit tmp file to raise.
        original_write_text = Path.write_text
        audit_tmp_name = "geometry-overlays-dropped.json.tmp"

        def selective_fail(self: Path, data: str, **kwargs: Any) -> int:
            if self.name == audit_tmp_name:
                raise OSError("simulated audit write failure")
            return original_write_text(self, data, **kwargs)

        monkeypatch.setattr(Path, "write_text", selective_fail)

        with pytest.raises(OSError, match="simulated audit write failure"):
            _write_outputs(
                [_sample_kept_row("HD", "C")],
                [_audit_dict("HD", "X", 0.001)],  # type: ignore[arg-type]
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
        kept_rows = [_sample_kept_row("HD-1", "HD-1", "hunting_district", "self", "primary_unit")]
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
        # The --explain flag was removed during the shapely refactor.
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
        # Realistic mini-Montana: 1 HD, 1 portion fully inside, 1 portion edge-touching
        # (boundary noise — should be dropped), 1 RA half-inside, 1 RA orphan (no overlap).
        hd_geom = _square(0, 0, 10)
        inside_portion = _square(2, 2, 1)             # ~1.0 of child inside → covers
        edge_portion = _square(9.999, 0, 1)           # ~0.001 → dropped
        # But edge_portion would orphan unless it has another HD parent. Add another
        # HD that fully contains it.
        hd2_geom = _square(9, 0, 5)
        # half_ra: 50% inside HD → intersects (kept)
        half_ra = _square(8, 0, 4)
        # Use a completely orphan RA (no HD overlap) — must be on the
        # ADR-016 allowlist to be allowed without raising.
        orphan_ra_id = next(iter(EXPECTED_RA_ORPHAN_IDS))
        orphan_ra = _square(100, 100, 1)
        # CWD inside HD
        cwd = _square(3, 3, 1)

        parsed: list[tuple[str, str, BaseGeometry]] = [
            ("HD-1", "hunting_district", hd_geom),
            ("HD-2", "hunting_district", hd2_geom),
            ("P-1", "portion", inside_portion),
            ("P-edge", "portion", edge_portion),
            ("CWD-1", "cwd_zone", cwd),
            ("RA-half", "restricted_area", half_ra),
            (orphan_ra_id, "restricted_area", orphan_ra),
        ]
        monkeypatch.setattr(build_fixture, "_load_geometries", MagicMock(return_value=parsed))
        kept, dropped = _collect_overlay_rows(MagicMock())

        kept_ids = {(r["child_kind"], r["child_geometry_id"], r["relationship"]) for r in kept}

        # Self rows for both HDs
        assert ("hunting_district", "HD-1", "self") in kept_ids
        assert ("hunting_district", "HD-2", "self") in kept_ids
        # P-1 covered by HD-1
        assert ("portion", "P-1", "covers") in kept_ids
        # P-edge covered by HD-2 (its real parent), audit-dropped relative to HD-1
        assert ("portion", "P-edge", "covers") in kept_ids
        # CWD covered
        assert ("cwd_zone", "CWD-1", "covers") in kept_ids
        # RA-half intersects HD-1
        assert ("restricted_area", "RA-half", "intersects") in kept_ids
        # Allowlisted RA orphan absent (no HD overlap), no raise — ADR-016 carve-out
        assert all(r["child_geometry_id"] != orphan_ra_id for r in kept)
        # Audit contains the boundary edge case
        assert any(d["child_geometry_id"] == "P-edge" and d["parent_geometry_id"] == "HD-1" for d in dropped)


class TestMultiPolygonGeometry:
    """The geom column is geography(MultiPolygon, 4326). Confirm shapely handles it."""

    def test_multipolygon_input_is_handled(self) -> None:
        a = _square(0, 0, 1)
        b = _square(2, 0, 1)
        mp = MultiPolygon([a, b])
        wkt = mp.wkt
        rows = [("MP-1", "hunting_district", wkt)]
        conn = _conn_mock_with_fetchall(rows)
        result = _load_geometries(conn)
        assert isinstance(result[0][2], BaseGeometry)
        assert result[0][2].area == pytest.approx(2.0)
