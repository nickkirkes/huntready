"""Unit tests for states.montana.build_overlay_fixture — pure-function, no real DB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from ingestion.lib.overlays import (
    GeometryRoleForE03,
    OverlayChildKind,
    OverlayRelationship,
)

import pytest

import states.montana.build_overlay_fixture as build_fixture
from ingestion.lib.overlays import (
    ROLE_FOR_E03_BY_CHILD_KIND,
    OverlayFixtureRow,
)
from states.montana.build_overlay_fixture import (
    MT_STATE_CODE,
    OverlayFixtureError,
    _build_hd_overlay_rows,
    _build_hd_portion_rows,
    _build_hd_self_rows,
    _collect_overlay_rows,
    _emit_explain,
    _validate_coverage,
    _write_fixture,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn_mock(fetchall_return: Any = None) -> tuple[MagicMock, MagicMock]:
    """Return (mock_conn, mock_cursor) wired up for `with conn.cursor() as cur:`."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    if fetchall_return is not None:
        mock_cursor.fetchall.return_value = fetchall_return
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


def _make_db_connect_mock(mock_conn: MagicMock) -> MagicMock:
    """Return a context-manager mock that yields mock_conn from `with db.connect() as conn:`."""
    connect_cm = MagicMock()
    connect_cm.__enter__ = MagicMock(return_value=mock_conn)
    connect_cm.__exit__ = MagicMock(return_value=False)
    return connect_cm


def _sample_row(
    parent_id: str = "MT-HD-1",
    child_id: str = "MT-HD-1",
    child_kind: OverlayChildKind = "hunting_district",
    relationship: OverlayRelationship = "self",
    role: GeometryRoleForE03 = "primary_unit",
) -> OverlayFixtureRow:
    return OverlayFixtureRow(
        parent_geometry_id=parent_id,
        child_geometry_id=child_id,
        parent_kind="hunting_district",
        child_kind=child_kind,
        relationship=relationship,
        role_for_e03=role,
    )


# ---------------------------------------------------------------------------
# TestBuildHdSelfRows
# ---------------------------------------------------------------------------


class TestBuildHdSelfRows:
    def test_empty_input_returns_empty_list(self) -> None:
        result = _build_hd_self_rows([])
        assert result == []

    def test_single_hd_produces_correct_self_row(self) -> None:
        hd_id = "MT-HD-deer-elk-lion-100-geom"
        result = _build_hd_self_rows([hd_id])
        assert len(result) == 1
        row = result[0]
        assert row["parent_geometry_id"] == hd_id
        assert row["child_geometry_id"] == hd_id
        assert row["parent_kind"] == "hunting_district"
        assert row["child_kind"] == "hunting_district"
        assert row["relationship"] == "self"
        assert row["role_for_e03"] == "primary_unit"

    def test_multiple_hds_preserves_order(self) -> None:
        ids = ["MT-HD-1", "MT-HD-2", "MT-HD-3"]
        result = _build_hd_self_rows(ids)
        assert len(result) == 3
        for i, row in enumerate(result):
            assert row["parent_geometry_id"] == ids[i]
            assert row["child_geometry_id"] == ids[i]
            assert row["role_for_e03"] == "primary_unit"


# ---------------------------------------------------------------------------
# TestBuildHdPortionRows
# ---------------------------------------------------------------------------


class TestBuildHdPortionRows:
    def test_two_rows_produced_with_correct_fields(self) -> None:
        mock_conn, mock_cursor = _make_conn_mock(
            fetchall_return=[("MT-HD-1", "MT-portion-A"), ("MT-HD-2", "MT-portion-B")]
        )
        result = _build_hd_portion_rows(mock_conn)
        assert len(result) == 2
        for row in result:
            assert row["relationship"] == "covers"
            assert row["child_kind"] == "portion"
            assert row["role_for_e03"] == ROLE_FOR_E03_BY_CHILD_KIND["portion"]
            assert row["parent_kind"] == "hunting_district"

    def test_first_row_parent_child_ids(self) -> None:
        mock_conn, mock_cursor = _make_conn_mock(
            fetchall_return=[("MT-HD-1", "MT-portion-A")]
        )
        result = _build_hd_portion_rows(mock_conn)
        assert result[0]["parent_geometry_id"] == "MT-HD-1"
        assert result[0]["child_geometry_id"] == "MT-portion-A"

    def test_cursor_execute_receives_correct_params(self) -> None:
        mock_conn, mock_cursor = _make_conn_mock(
            fetchall_return=[("MT-HD-1", "MT-portion-A")]
        )
        _build_hd_portion_rows(mock_conn)
        mock_cursor.execute.assert_called_once()
        args = mock_cursor.execute.call_args
        # Second arg to execute() is the params tuple
        params = args[0][1]
        assert params == (MT_STATE_CODE, MT_STATE_CODE)

    def test_sql_uses_st_covers_without_geometry_cast(self) -> None:
        mock_conn, mock_cursor = _make_conn_mock(fetchall_return=[])
        _build_hd_portion_rows(mock_conn)
        sql = mock_cursor.execute.call_args[0][0]
        assert "ST_Covers" in sql
        assert "::geometry" not in sql


# ---------------------------------------------------------------------------
# TestBuildHdOverlayRows
# ---------------------------------------------------------------------------


class TestBuildHdOverlayRows:
    @pytest.mark.parametrize("child_kind", ["cwd_zone", "restricted_area"])
    def test_relationship_discriminator_by_is_covered(self, child_kind: str) -> None:
        mock_conn, mock_cursor = _make_conn_mock(
            fetchall_return=[
                ("MT-HD-1", "MT-overlay-X", True),
                ("MT-HD-2", "MT-overlay-Y", False),
            ]
        )
        result = _build_hd_overlay_rows(mock_conn, child_kind)  # type: ignore[arg-type]
        assert len(result) == 2
        assert result[0]["relationship"] == "covers"
        assert result[1]["relationship"] == "intersects"

    @pytest.mark.parametrize("child_kind", ["cwd_zone", "restricted_area"])
    def test_child_kind_and_role_match_parametrized_kind(self, child_kind: str) -> None:
        mock_conn, mock_cursor = _make_conn_mock(
            fetchall_return=[("MT-HD-1", "MT-overlay-X", True)]
        )
        result = _build_hd_overlay_rows(mock_conn, child_kind)  # type: ignore[arg-type]
        assert result[0]["child_kind"] == child_kind
        assert result[0]["role_for_e03"] == ROLE_FOR_E03_BY_CHILD_KIND[child_kind]  # type: ignore[index]

    @pytest.mark.parametrize("child_kind", ["cwd_zone", "restricted_area"])
    def test_execute_params_include_child_kind_and_state(self, child_kind: str) -> None:
        mock_conn, mock_cursor = _make_conn_mock(fetchall_return=[])
        _build_hd_overlay_rows(mock_conn, child_kind)  # type: ignore[arg-type]
        params = mock_cursor.execute.call_args[0][1]
        assert params == (child_kind, MT_STATE_CODE, MT_STATE_CODE)

    @pytest.mark.parametrize("child_kind", ["cwd_zone", "restricted_area"])
    def test_empty_db_returns_empty_list(self, child_kind: str) -> None:
        mock_conn, mock_cursor = _make_conn_mock(fetchall_return=[])
        result = _build_hd_overlay_rows(mock_conn, child_kind)  # type: ignore[arg-type]
        assert result == []


# ---------------------------------------------------------------------------
# TestValidateCoverage
# ---------------------------------------------------------------------------


class TestValidateCoverage:
    def _make_multi_cursor_conn(
        self,
        first_fetchall: list[tuple[Any, ...]],
        second_fetchall: list[tuple[Any, ...]],
    ) -> MagicMock:
        """Wire up a conn whose cursor().fetchall() returns different values per call."""
        cursor1 = MagicMock()
        cursor1.__enter__ = MagicMock(return_value=cursor1)
        cursor1.__exit__ = MagicMock(return_value=False)
        cursor1.fetchall.return_value = first_fetchall

        cursor2 = MagicMock()
        cursor2.__enter__ = MagicMock(return_value=cursor2)
        cursor2.__exit__ = MagicMock(return_value=False)
        cursor2.fetchall.return_value = second_fetchall

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = [cursor1, cursor2]
        return mock_conn

    def test_all_children_covered_no_raise(self) -> None:
        rows: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "P-1", "portion", "covers", "portion"),
            _sample_row("HD-1", "CWD-1", "cwd_zone", "covers", "cwd_management_zone"),
        ]
        # first query (orphan check) returns same pairs as in rows
        first_q = [("P-1", "portion"), ("CWD-1", "cwd_zone")]
        # second query (all ids) returns all ids referenced
        second_q = [("HD-1",), ("P-1",), ("CWD-1",)]
        mock_conn = self._make_multi_cursor_conn(first_q, second_q)
        # Should not raise
        _validate_coverage(mock_conn, rows)

    def test_portion_orphan_raises_with_id_and_kind(self) -> None:
        rows: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "CWD-1", "cwd_zone", "covers", "cwd_management_zone"),
        ]
        # DB has a portion that the rows don't reference
        first_q = [("P-orphan", "portion"), ("CWD-1", "cwd_zone")]
        second_q = [("HD-1",), ("P-orphan",), ("CWD-1",)]
        mock_conn = self._make_multi_cursor_conn(first_q, second_q)
        with pytest.raises(OverlayFixtureError) as exc_info:
            _validate_coverage(mock_conn, rows)
        msg = str(exc_info.value)
        assert "P-orphan" in msg
        assert "portion" in msg

    def test_cwd_orphan_raises_with_id_and_kind(self) -> None:
        rows: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "P-1", "portion", "covers", "portion"),
        ]
        first_q = [("P-1", "portion"), ("CWD-orphan", "cwd_zone")]
        second_q = [("HD-1",), ("P-1",), ("CWD-orphan",)]
        mock_conn = self._make_multi_cursor_conn(first_q, second_q)
        with pytest.raises(OverlayFixtureError) as exc_info:
            _validate_coverage(mock_conn, rows)
        msg = str(exc_info.value)
        assert "CWD-orphan" in msg
        assert "cwd_zone" in msg

    def test_restricted_area_orphan_raises_with_id_and_kind(self) -> None:
        rows: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "P-1", "portion", "covers", "portion"),
        ]
        first_q = [("P-1", "portion"), ("RA-orphan", "restricted_area")]
        second_q = [("HD-1",), ("P-1",), ("RA-orphan",)]
        mock_conn = self._make_multi_cursor_conn(first_q, second_q)
        with pytest.raises(OverlayFixtureError) as exc_info:
            _validate_coverage(mock_conn, rows)
        msg = str(exc_info.value)
        assert "RA-orphan" in msg
        assert "restricted_area" in msg

    def test_empty_cwd_table_and_no_cwd_rows_no_raise(self) -> None:
        rows: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "P-1", "portion", "covers", "portion"),
        ]
        # DB has no cwd_zone rows at all
        first_q = [("P-1", "portion")]
        second_q = [("HD-1",), ("P-1",)]
        mock_conn = self._make_multi_cursor_conn(first_q, second_q)
        _validate_coverage(mock_conn, rows)  # should not raise

    def test_unknown_geometry_id_raises(self) -> None:
        rows: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "UNKNOWN-99", "portion", "covers", "portion"),
        ]
        # Orphan check: DB reports no portion (UNKNOWN-99 not in geometry table)
        first_q: list[tuple[Any, ...]] = []
        # All-ids check: only HD-1 exists (UNKNOWN-99 absent)
        second_q = [("HD-1",)]
        mock_conn = self._make_multi_cursor_conn(first_q, second_q)
        with pytest.raises(OverlayFixtureError) as exc_info:
            _validate_coverage(mock_conn, rows)
        msg = str(exc_info.value)
        assert "UNKNOWN-99" in msg
        assert "unknown geometry ids" in msg

    def test_both_orphan_and_unknown_id_raises_with_both(self) -> None:
        rows: list[OverlayFixtureRow] = [
            # covers an existing HD, but the portion itself is missing from DB
            _sample_row("HD-1", "UNKNOWN-99", "portion", "covers", "portion"),
        ]
        # DB has a portion that rows don't reference → orphan
        # And UNKNOWN-99 doesn't exist in geometry
        first_q = [("P-real", "portion")]
        second_q = [("HD-1",), ("P-real",)]  # UNKNOWN-99 not here
        mock_conn = self._make_multi_cursor_conn(first_q, second_q)
        with pytest.raises(OverlayFixtureError) as exc_info:
            _validate_coverage(mock_conn, rows)
        msg = str(exc_info.value)
        # Both violations must appear
        assert "P-real" in msg
        assert "portion" in msg
        assert "UNKNOWN-99" in msg
        assert "unknown geometry ids" in msg


# ---------------------------------------------------------------------------
# TestWriteFixture
# ---------------------------------------------------------------------------


class TestWriteFixture:
    def _make_rows(self) -> list[OverlayFixtureRow]:
        return [
            _sample_row("HD-B", "P-2", "portion", "covers", "portion"),
            _sample_row("HD-A", "P-1", "portion", "covers", "portion"),
            _sample_row("HD-A", "CWD-1", "cwd_zone", "intersects", "cwd_management_zone"),
        ]

    def test_determinism_different_input_orders(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        rows = self._make_rows()
        reversed_rows = list(reversed(rows))

        dir_a = tmp_path / "a" / "fixtures"
        dir_b = tmp_path / "b" / "fixtures"
        path_a = dir_a / "geometry-overlays.json"
        path_b = dir_b / "geometry-overlays.json"

        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", dir_a)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", path_a)
        _write_fixture(rows)

        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", dir_b)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", path_b)
        _write_fixture(reversed_rows)

        assert path_a.read_bytes() == path_b.read_bytes()

    def test_trailing_newline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        fixture_dir = tmp_path / "fixtures"
        fixture_path = fixture_dir / "geometry-overlays.json"
        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", fixture_dir)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", fixture_path)

        _write_fixture(self._make_rows())
        content = fixture_path.read_text(encoding="utf-8")
        assert content.endswith("\n")

    def test_sort_key_tie_break_relationship(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Rows with same (parent, child) but different relationship must sort deterministically."""
        rows_order_1: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "OV-1", "cwd_zone", "intersects", "cwd_management_zone"),
            _sample_row("HD-1", "OV-1", "cwd_zone", "covers", "cwd_management_zone"),
        ]
        rows_order_2: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "OV-1", "cwd_zone", "covers", "cwd_management_zone"),
            _sample_row("HD-1", "OV-1", "cwd_zone", "intersects", "cwd_management_zone"),
        ]

        dir_a = tmp_path / "tie_a" / "fixtures"
        dir_b = tmp_path / "tie_b" / "fixtures"
        path_a = dir_a / "geometry-overlays.json"
        path_b = dir_b / "geometry-overlays.json"

        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", dir_a)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", path_a)
        _write_fixture(rows_order_1)

        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", dir_b)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", path_b)
        _write_fixture(rows_order_2)

        assert path_a.read_bytes() == path_b.read_bytes()

    def test_output_is_valid_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        fixture_dir = tmp_path / "fixtures"
        fixture_path = fixture_dir / "geometry-overlays.json"
        monkeypatch.setattr(build_fixture, "MT_FIXTURE_DIR", fixture_dir)
        monkeypatch.setattr(build_fixture, "OVERLAY_FIXTURE_PATH", fixture_path)

        _write_fixture(self._make_rows())
        parsed = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert isinstance(parsed, list)
        assert len(parsed) == 3


# ---------------------------------------------------------------------------
# TestCollectOverlayRows
# ---------------------------------------------------------------------------


class TestCollectOverlayRows:
    def _make_wired_conn(self) -> MagicMock:
        mock_conn = MagicMock()
        return mock_conn

    def test_calls_helpers_in_order_and_concatenates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hd_ids = ["HD-1", "HD-2"]
        self_rows: list[OverlayFixtureRow] = [
            _sample_row("HD-1", "HD-1"),
            _sample_row("HD-2", "HD-2"),
        ]
        portion_rows: list[OverlayFixtureRow] = [_sample_row("HD-1", "P-1", "portion", "covers", "portion")]
        cwd_rows: list[OverlayFixtureRow] = [_sample_row("HD-1", "CWD-1", "cwd_zone", "covers", "cwd_management_zone")]
        ra_rows: list[OverlayFixtureRow] = [_sample_row("HD-1", "RA-1", "restricted_area", "intersects", "restricted_area")]

        mock_fetch_ids = MagicMock(return_value=hd_ids)
        mock_self_rows = MagicMock(return_value=self_rows)
        mock_portion = MagicMock(return_value=portion_rows)
        mock_overlay = MagicMock(side_effect=[cwd_rows, ra_rows])
        mock_validate = MagicMock()

        monkeypatch.setattr(build_fixture, "_fetch_hd_ids", mock_fetch_ids)
        monkeypatch.setattr(build_fixture, "_build_hd_self_rows", mock_self_rows)
        monkeypatch.setattr(build_fixture, "_build_hd_portion_rows", mock_portion)
        monkeypatch.setattr(build_fixture, "_build_hd_overlay_rows", mock_overlay)
        monkeypatch.setattr(build_fixture, "_validate_coverage", mock_validate)

        mock_conn = self._make_wired_conn()
        result = _collect_overlay_rows(mock_conn, explain=False)

        # Assert each helper was called
        mock_fetch_ids.assert_called_once_with(mock_conn)
        mock_self_rows.assert_called_once_with(hd_ids)
        mock_portion.assert_called_once_with(mock_conn)
        assert mock_overlay.call_count == 2

        expected = self_rows + portion_rows + cwd_rows + ra_rows
        assert result == expected

    def test_validate_coverage_called_with_full_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hd_ids = ["HD-1"]
        portion_rows: list[OverlayFixtureRow] = [_sample_row("HD-1", "P-1", "portion", "covers", "portion")]
        cwd_rows: list[OverlayFixtureRow] = []
        ra_rows: list[OverlayFixtureRow] = []

        monkeypatch.setattr(build_fixture, "_fetch_hd_ids", MagicMock(return_value=hd_ids))
        monkeypatch.setattr(build_fixture, "_build_hd_portion_rows", MagicMock(return_value=portion_rows))
        monkeypatch.setattr(build_fixture, "_build_hd_overlay_rows", MagicMock(side_effect=[cwd_rows, ra_rows]))
        mock_validate = MagicMock()
        monkeypatch.setattr(build_fixture, "_validate_coverage", mock_validate)

        mock_conn = self._make_wired_conn()
        result = _collect_overlay_rows(mock_conn, explain=False)

        mock_validate.assert_called_once()
        validate_conn_arg, validate_rows_arg = mock_validate.call_args[0]
        assert validate_conn_arg is mock_conn
        assert validate_rows_arg == result

    def test_explain_false_does_not_call_emit_explain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(build_fixture, "_fetch_hd_ids", MagicMock(return_value=["HD-1"]))
        monkeypatch.setattr(build_fixture, "_build_hd_portion_rows", MagicMock(return_value=[]))
        monkeypatch.setattr(build_fixture, "_build_hd_overlay_rows", MagicMock(side_effect=[[], []]))
        monkeypatch.setattr(build_fixture, "_validate_coverage", MagicMock())
        mock_emit = MagicMock()
        monkeypatch.setattr(build_fixture, "_emit_explain", mock_emit)

        _collect_overlay_rows(self._make_wired_conn(), explain=False)
        mock_emit.assert_not_called()

    def test_empty_hd_ids_raises_overlay_fixture_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(build_fixture, "_fetch_hd_ids", MagicMock(return_value=[]))
        # No other helpers should be called; if the guard misses, these would fire.
        mock_portion = MagicMock()
        mock_overlay = MagicMock()
        mock_validate = MagicMock()
        monkeypatch.setattr(build_fixture, "_build_hd_portion_rows", mock_portion)
        monkeypatch.setattr(build_fixture, "_build_hd_overlay_rows", mock_overlay)
        monkeypatch.setattr(build_fixture, "_validate_coverage", mock_validate)

        with pytest.raises(build_fixture.OverlayFixtureError) as exc_info:
            _collect_overlay_rows(self._make_wired_conn(), explain=False)
        assert "no hunting_district rows" in str(exc_info.value)
        assert "US-MT" in str(exc_info.value)
        mock_portion.assert_not_called()
        mock_overlay.assert_not_called()
        mock_validate.assert_not_called()

    def test_explain_true_calls_emit_explain_three_times_before_data_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_log: list[str] = []

        def fake_emit(conn: Any, label: str, sql: str, params: Any) -> None:
            call_log.append(f"emit:{label}")

        def fake_fetch_ids(conn: Any) -> list[str]:
            call_log.append("fetch_ids")
            return ["HD-1"]

        def fake_portion(conn: Any) -> list[OverlayFixtureRow]:
            call_log.append("portion")
            return []

        def fake_overlay(conn: Any, child_kind: str) -> list[OverlayFixtureRow]:
            call_log.append(f"overlay:{child_kind}")
            return []

        monkeypatch.setattr(build_fixture, "_emit_explain", fake_emit)
        monkeypatch.setattr(build_fixture, "_fetch_hd_ids", fake_fetch_ids)
        monkeypatch.setattr(build_fixture, "_build_hd_portion_rows", fake_portion)
        monkeypatch.setattr(build_fixture, "_build_hd_overlay_rows", fake_overlay)
        monkeypatch.setattr(build_fixture, "_validate_coverage", MagicMock())

        _collect_overlay_rows(self._make_wired_conn(), explain=True)

        # All three emits before any data-fetch call
        emit_indices = [i for i, x in enumerate(call_log) if x.startswith("emit:")]
        first_data_index = next(
            i for i, x in enumerate(call_log)
            if x in ("fetch_ids", "portion") or x.startswith("overlay:")
        )
        assert len(emit_indices) == 3
        assert all(i < first_data_index for i in emit_indices)


# ---------------------------------------------------------------------------
# TestEmitExplain
# ---------------------------------------------------------------------------


class TestEmitExplain:
    def test_stderr_output_contains_marker_and_plan_lines(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan_lines = [("Seq Scan on geometry ...",), ("  ->  Filter: ...",)]
        mock_conn, mock_cursor = _make_conn_mock(fetchall_return=plan_lines)

        _emit_explain(mock_conn, "HD→Portion", "SELECT 1", (MT_STATE_CODE, MT_STATE_CODE))

        captured = capsys.readouterr()
        stderr = captured.err
        assert "# EXPLAIN ANALYZE: HD→Portion" in stderr
        assert "Seq Scan on geometry ..." in stderr
        assert "  ->  Filter: ..." in stderr

    def test_stderr_ends_with_trailing_blank_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan_lines = [("Seq Scan on geometry ...",)]
        mock_conn, mock_cursor = _make_conn_mock(fetchall_return=plan_lines)

        _emit_explain(mock_conn, "HD→Portion", "SELECT 1", (MT_STATE_CODE,))

        captured = capsys.readouterr()
        assert captured.err.endswith("\n\n")

    def test_sql_prefixed_with_explain_analyze(self) -> None:
        mock_conn, mock_cursor = _make_conn_mock(fetchall_return=[])

        original_sql = "SELECT a.id FROM geometry a"
        _emit_explain(mock_conn, "HD→Portion", original_sql, (MT_STATE_CODE,))

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert executed_sql.startswith("EXPLAIN (ANALYZE, FORMAT TEXT) ")
        assert original_sql in executed_sql

    def test_nothing_written_to_stdout(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_conn, mock_cursor = _make_conn_mock(fetchall_return=[("Plan line",)])
        _emit_explain(mock_conn, "Label", "SELECT 1", ())
        captured = capsys.readouterr()
        assert captured.out == ""


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    def _setup_main_stubs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        collect_return: list[OverlayFixtureRow] | None = None,
        collect_side_effect: Any = None,
    ) -> tuple[MagicMock, MagicMock, MagicMock]:
        """Returns (mock_connect_cm, mock_collect, mock_write)."""
        mock_conn = MagicMock()
        connect_cm = _make_db_connect_mock(mock_conn)
        mock_db_connect = MagicMock(return_value=connect_cm)
        monkeypatch.setattr(build_fixture.db, "connect", mock_db_connect)

        rows = collect_return or []
        mock_collect = MagicMock(return_value=rows, side_effect=collect_side_effect)
        monkeypatch.setattr(build_fixture, "_collect_overlay_rows", mock_collect)

        mock_write = MagicMock()
        monkeypatch.setattr(build_fixture, "_write_fixture", mock_write)

        return mock_db_connect, mock_collect, mock_write

    def test_main_no_args_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, _ = self._setup_main_stubs(monkeypatch)
        result = main([])
        assert result == 0

    def test_main_calls_collect_and_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [_sample_row()]
        _, mock_collect, mock_write = self._setup_main_stubs(
            monkeypatch, collect_return=rows
        )
        main([])
        mock_collect.assert_called_once()
        mock_write.assert_called_once_with(rows)

    def test_main_no_args_passes_explain_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, mock_collect, _ = self._setup_main_stubs(monkeypatch)
        main([])
        _, kwargs = mock_collect.call_args
        assert kwargs.get("explain") is False

    def test_main_explain_flag_passes_explain_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, mock_collect, _ = self._setup_main_stubs(monkeypatch)
        main(["--explain"])
        _, kwargs = mock_collect.call_args
        assert kwargs.get("explain") is True

    def test_overlay_fixture_error_propagates_from_main(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_main_stubs(
            monkeypatch,
            collect_side_effect=OverlayFixtureError("orphan portion: ['P-99']"),
        )
        with pytest.raises(OverlayFixtureError):
            main([])
