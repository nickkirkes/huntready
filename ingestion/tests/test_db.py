"""Unit tests for ingestion.lib.db."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from psycopg.types.json import Json

from ingestion.lib.db import (
    connect,
    upsert_geometries,
    upsert_geometry,
    upsert_jurisdiction_binding,
    upsert_reporting_obligation,
    write_regulation_reporting,
)
from ingestion.lib.schema import (
    Geometry,
    JurisdictionBinding,
    RegulationReporting,
    ReportingObligation,
    SourceCitation,
)

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
    legal_description: str | None = None,
) -> Geometry:
    return Geometry(
        id=geom_id,
        name=f"HD {geom_id}",
        kind="hunting_district",
        geom=_SQUARE_WKT,
        state="MT",
        license_year=license_year,
        verbatim_rule=verbatim_rule,
        legal_description=legal_description,
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
    assert "legal_description" in sql


# ---------------------------------------------------------------------------
# upsert_geometry — parameter assertions
# ---------------------------------------------------------------------------


def test_upsert_geometry_correct_param_order() -> None:
    """Parameters tuple must be (id, name, kind, geom_wkt, state, license_year, source, verbatim_rule, legal_description)."""
    geom = _make_geometry(geom_id="mt-hd-262", license_year=2026, verbatim_rule="Rule text.")
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, geom)
    params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]

    assert len(params) == 9
    assert params[0] == geom.id
    assert params[1] == geom.name
    assert params[2] == geom.kind
    assert params[3] == _COERCED_WKT  # post-validator WKT
    assert params[4] == geom.state
    assert params[5] == geom.license_year
    # params[6] is the Json-wrapped source (asserted separately)
    assert params[7] == geom.verbatim_rule
    assert params[8] == geom.legal_description  # None → SQL NULL (added by T5)


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


def test_upsert_geometry_legal_description_in_param_position() -> None:
    """legal_description must occupy index 8 (0-indexed) in the params tuple."""
    geom = _make_geometry(legal_description="HD-262 boundary: starting at the intersection of...")
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, geom)
    params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
    assert params[8] == geom.legal_description


def test_upsert_geometry_none_legal_description_passed_through() -> None:
    """legal_description=None must be passed through to SQL params as None (→ SQL NULL)."""
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, _make_geometry(legal_description=None))
    params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
    assert params[8] is None


def test_upsert_geometry_string_legal_description_passed_through() -> None:
    """A non-None legal_description string must be passed through verbatim."""
    description = "HD-262 boundary: starting at the intersection of..."
    mock_conn, mock_cursor = _make_mock_conn()
    upsert_geometry(mock_conn, _make_geometry(legal_description=description))
    params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
    assert params[8] == description


def test_upsert_sql_contains_legal_description_column() -> None:
    """_UPSERT_SQL must declare legal_description in both the INSERT list and UPDATE SET."""
    from ingestion.lib.db import _UPSERT_SQL

    assert "legal_description" in _UPSERT_SQL
    assert "legal_description = EXCLUDED.legal_description" in _UPSERT_SQL


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


# ---------------------------------------------------------------------------
# Fixtures — shared by TestUpsertReportingObligation + TestWriteRegulationReporting
# ---------------------------------------------------------------------------

def _make_bear_source() -> SourceCitation:
    return SourceCitation(
        id="mt-fwp-black-bear-2026-booklet",
        agency="Montana FWP",
        title="Black Bear Booklet 2026",
        url="https://fwp.mt.gov/test",
        publication_date="2026-04-27",
        document_type="annual_regulations",
        supersedes=None,
        page_reference="p. 7",
    )


def _make_statewide_obligation() -> ReportingObligation:
    """STATEWIDE 48-hour harvest_report — values match production _REPORTING_ROW_SPEC."""
    return ReportingObligation(
        id="mt-bear-harvest-report-48hr-statewide",
        kind="harvest_report",
        deadline="48 hours",
        deadline_hours=48,
        submission_method="phone",
        submission_url="https://fwp.mt.gov",
        submission_phone="1-877-FWPWILD",
        applies_to_regions=None,
        what_to_present=None,
        verbatim_rule=(
            "Hunters must report their harvest within 48 hours of killing a bear."
        ),
        source=_make_bear_source(),
    )


def _make_r1_obligation() -> ReportingObligation:
    """Region 1 tooth_submission — values match production _REPORTING_ROW_SPEC."""
    return ReportingObligation(
        id="mt-bear-tooth-submission-r1-10day",
        kind="tooth_submission",
        deadline="10 days",
        deadline_hours=240,
        submission_method="agency_office",
        submission_url=None,
        submission_phone=None,
        applies_to_regions=["R1"],
        what_to_present=["both premolar teeth"],
        verbatim_rule=(
            "Region 1 hunters must submit a tooth within 10 days of harvest."
        ),
        source=_make_bear_source(),
    )


def _make_r2to7_obligation() -> ReportingObligation:
    """Regions 2-7 hide_skull_presentation — values match production _REPORTING_ROW_SPEC."""
    return ReportingObligation(
        id="mt-bear-hide-skull-r2to7-10day",
        kind="hide_skull_presentation",
        deadline="10 days",
        deadline_hours=240,
        submission_method="in_person_check_station",
        submission_url=None,
        submission_phone=None,
        applies_to_regions=["R2", "R3", "R4", "R5", "R6", "R7"],
        what_to_present=["hide", "skull"],
        verbatim_rule=(
            "Regions 2-7 hunters must present the hide and skull within 10 days."
        ),
        source=_make_bear_source(),
    )


def _make_regulation_reporting_link() -> RegulationReporting:
    return RegulationReporting(
        state="US-MT",
        jurisdiction_code="MT-HD-bear-100",
        species_group="bear",
        license_year=2026,
        reporting_obligation_id="mt-bear-harvest-report-48hr-statewide",
    )


# ---------------------------------------------------------------------------
# TestUpsertReportingObligation
# ---------------------------------------------------------------------------


class TestUpsertReportingObligation:
    """Tests for db.upsert_reporting_obligation."""

    def test_upsert_executes_expected_sql_and_params(self) -> None:
        """upsert_reporting_obligation must issue INSERT INTO reporting_obligation … ON CONFLICT (id) DO UPDATE."""
        obligation = _make_statewide_obligation()
        mock_conn, mock_cursor = _make_mock_conn()
        upsert_reporting_obligation(mock_conn, obligation)

        sql: str = mock_cursor.execute.call_args[0][0]
        params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]

        assert "INSERT INTO reporting_obligation" in sql
        assert "ON CONFLICT (id) DO UPDATE" in sql
        assert len(params) == 11
        assert params[0] == obligation.id
        assert isinstance(params[10], Json)  # source is the last param, Json-wrapped

    def test_upsert_does_not_commit(self) -> None:
        """upsert_reporting_obligation must NOT call conn.commit() — caller controls txn."""
        mock_conn, _mock_cursor = _make_mock_conn()
        upsert_reporting_obligation(mock_conn, _make_statewide_obligation())
        mock_conn.commit.assert_not_called()

    def test_upsert_does_not_rollback(self) -> None:
        """upsert_reporting_obligation must NOT call conn.rollback()."""
        mock_conn, _mock_cursor = _make_mock_conn()
        upsert_reporting_obligation(mock_conn, _make_statewide_obligation())
        mock_conn.rollback.assert_not_called()

    def test_json_wrap_for_source(self) -> None:
        """The source column param must be wrapped with Json (not Jsonb)."""
        obligation = _make_statewide_obligation()
        mock_conn, mock_cursor = _make_mock_conn()
        upsert_reporting_obligation(mock_conn, obligation)

        params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
        # source is the last param (index 10)
        source_param = params[10]
        assert isinstance(source_param, Json)
        # The dict inside must match model_dump(exclude_none=True) — matches every
        # other jsonb writer in db.py and avoids emitting explicit JSON nulls for
        # optional SourceCitation fields (supersedes=None, etc.).
        assert source_param.obj == obligation.source.model_dump(exclude_none=True)

    def test_upsert_handles_nullable_fields(self) -> None:
        """Nullable fields must pass through as None to psycopg.

        Uses R1 fixture (production dispatch values): submission_url=None and
        submission_phone=None on R1. (what_to_present is populated on R1 with
        the premolar teeth list, so test_upsert_handles_list_fields covers that
        path via R2-7.) STATEWIDE applies_to_regions=None is also asserted via
        a second sub-case below to cover all three None positions.
        """
        # R1 case — submission_url and submission_phone are None
        r1 = _make_r1_obligation()
        assert r1.submission_url is None
        assert r1.submission_phone is None
        mock_conn, mock_cursor = _make_mock_conn()
        upsert_reporting_obligation(mock_conn, r1)
        params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
        # param order: id, kind, deadline, deadline_hours, submission_method,
        #              submission_url, submission_phone, applies_to_regions,
        #              what_to_present, verbatim_rule, source
        assert params[5] is None   # submission_url
        assert params[6] is None   # submission_phone

        # STATEWIDE case — applies_to_regions=None and what_to_present=None
        statewide = _make_statewide_obligation()
        assert statewide.applies_to_regions is None
        assert statewide.what_to_present is None
        mock_conn2, mock_cursor2 = _make_mock_conn()
        upsert_reporting_obligation(mock_conn2, statewide)
        params2: tuple[object, ...] = mock_cursor2.execute.call_args[0][1]
        assert params2[7] is None   # applies_to_regions
        assert params2[8] is None   # what_to_present

    def test_upsert_handles_list_fields(self) -> None:
        """applies_to_regions and what_to_present are passed as Python lists (psycopg adapts to text[])."""
        obligation = _make_r2to7_obligation()
        mock_conn, mock_cursor = _make_mock_conn()
        upsert_reporting_obligation(mock_conn, obligation)

        params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
        # param order: id, kind, deadline, deadline_hours, submission_method,
        #              submission_url, submission_phone, applies_to_regions,
        #              what_to_present, verbatim_rule, source
        assert params[7] == ["R2", "R3", "R4", "R5", "R6", "R7"]
        assert params[8] == ["hide", "skull"]


# ---------------------------------------------------------------------------
# TestWriteRegulationReporting
# ---------------------------------------------------------------------------


class TestWriteRegulationReporting:
    """Tests for db.write_regulation_reporting."""

    def test_insert_executes_expected_sql_and_params(self) -> None:
        """write_regulation_reporting must issue INSERT INTO regulation_reporting … ON CONFLICT DO NOTHING."""
        link = _make_regulation_reporting_link()
        mock_conn, mock_cursor = _make_mock_conn()
        write_regulation_reporting(mock_conn, link)

        sql: str = mock_cursor.execute.call_args[0][0]
        params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]

        assert "INSERT INTO regulation_reporting" in sql
        assert "ON CONFLICT DO NOTHING" in sql
        assert len(params) == 5
        assert params == (
            link.state,
            link.jurisdiction_code,
            link.species_group,
            link.license_year,
            link.reporting_obligation_id,
        )

    def test_write_does_not_commit(self) -> None:
        """write_regulation_reporting must NOT call conn.commit() — caller controls txn."""
        mock_conn, _mock_cursor = _make_mock_conn()
        write_regulation_reporting(mock_conn, _make_regulation_reporting_link())
        mock_conn.commit.assert_not_called()

    def test_write_does_not_rollback(self) -> None:
        """write_regulation_reporting must NOT call conn.rollback()."""
        mock_conn, _mock_cursor = _make_mock_conn()
        write_regulation_reporting(mock_conn, _make_regulation_reporting_link())
        mock_conn.rollback.assert_not_called()

    def test_idempotent_on_conflict_do_nothing(self) -> None:
        """SQL must contain ON CONFLICT DO NOTHING and must NOT contain DO UPDATE."""
        import re
        mock_conn, mock_cursor = _make_mock_conn()
        write_regulation_reporting(mock_conn, _make_regulation_reporting_link())
        sql: str = mock_cursor.execute.call_args[0][0]
        assert "ON CONFLICT DO NOTHING" in sql
        assert not re.search(r"\bDO UPDATE\b", sql)


# ---------------------------------------------------------------------------
# Fixture — shared by TestUpsertJurisdictionBinding
# ---------------------------------------------------------------------------


def _make_bear_booklet_source_p2() -> SourceCitation:
    """Minimal SourceCitation for the Black Bear booklet, page 2."""
    return SourceCitation(
        id="mt-fwp-black-bear-2026-booklet",
        agency="Montana FWP",
        title="Black Bear Booklet 2026",
        url="https://fwp.mt.gov/hunt/regulations",
        publication_date="2026-04-27",
        document_type="annual_regulations",
        supersedes=None,
        page_reference="p. 2",
    )


def _make_jurisdiction_binding(
    *,
    verbatim_rule: str | None = None,
) -> JurisdictionBinding:
    """Canonical test fixture for JurisdictionBinding (MT-STATEWIDE-bear anchor)."""
    return JurisdictionBinding(
        id="US-MT-MT-STATEWIDE-bear-bear-2026-primary_unit-MT-STATEWIDE-geom",
        regulation_record_state="US-MT",
        regulation_record_jurisdiction_code="MT-STATEWIDE-bear",
        regulation_record_species_group="bear",
        regulation_record_license_year=2026,
        geometry_id="MT-STATEWIDE-geom",
        role="primary_unit",
        verbatim_rule=verbatim_rule,
        source=_make_bear_booklet_source_p2(),
    )


# ---------------------------------------------------------------------------
# TestUpsertJurisdictionBinding
# ---------------------------------------------------------------------------


class TestUpsertJurisdictionBinding:
    """Tests for db.upsert_jurisdiction_binding."""

    def test_inserts_new_row(self) -> None:
        """upsert_jurisdiction_binding must issue INSERT INTO jurisdiction_binding … ON CONFLICT (id) DO UPDATE."""
        binding = _make_jurisdiction_binding()
        mock_conn, mock_cursor = _make_mock_conn()
        upsert_jurisdiction_binding(mock_conn, binding)

        sql: str = mock_cursor.execute.call_args[0][0]
        params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]

        assert "INSERT INTO jurisdiction_binding" in sql
        assert "ON CONFLICT (id) DO UPDATE" in sql
        # 9 params: id, reg_state, reg_jcode, reg_species, reg_year,
        #            geom_id, role, verbatim_rule, source
        assert len(params) == 9
        assert params[0] == binding.id
        assert params[1] == binding.regulation_record_state
        assert params[2] == binding.regulation_record_jurisdiction_code
        assert params[3] == binding.regulation_record_species_group
        assert params[4] == binding.regulation_record_license_year
        assert params[5] == binding.geometry_id
        assert params[6] == binding.role
        assert params[7] == binding.verbatim_rule  # None → SQL NULL
        # params[8] is source — Json-wrapped (asserted separately)

    def test_upserts_existing_row(self) -> None:
        """Writing a second time with a different verbatim_rule must succeed without PK violation.

        Both writes must execute the ON CONFLICT DO UPDATE SQL; the second write's
        verbatim_rule value (index 7) must reflect the updated content.
        """
        binding_v1 = _make_jurisdiction_binding(verbatim_rule=None)
        binding_v2 = _make_jurisdiction_binding(
            verbatim_rule="Bear ID test completion required before hunting."
        )
        mock_conn, mock_cursor = _make_mock_conn()

        upsert_jurisdiction_binding(mock_conn, binding_v1)
        upsert_jurisdiction_binding(mock_conn, binding_v2)

        assert mock_cursor.execute.call_count == 2
        params_v2: tuple[object, ...] = mock_cursor.execute.call_args_list[1][0][1]
        assert params_v2[7] == binding_v2.verbatim_rule

    def test_idempotent_rerun(self) -> None:
        """Writing the same JurisdictionBinding twice must succeed; row content is identical after both writes."""
        binding = _make_jurisdiction_binding()
        mock_conn, mock_cursor = _make_mock_conn()

        upsert_jurisdiction_binding(mock_conn, binding)
        upsert_jurisdiction_binding(mock_conn, binding)

        assert mock_cursor.execute.call_count == 2
        params_first: tuple[object, ...] = mock_cursor.execute.call_args_list[0][0][1]
        params_second: tuple[object, ...] = mock_cursor.execute.call_args_list[1][0][1]
        # All scalar params must be byte-identical across both calls
        for i in range(8):  # indices 0-7 (exclude Json-wrapped source at 8)
            assert params_first[i] == params_second[i], f"param[{i}] differs between runs"

    def test_jsonb_wrap_source(self) -> None:
        """The source parameter (index 8) must be wrapped via Json(binding.source.model_dump(exclude_none=True))."""
        binding = _make_jurisdiction_binding()
        mock_conn, mock_cursor = _make_mock_conn()
        upsert_jurisdiction_binding(mock_conn, binding)

        params: tuple[object, ...] = mock_cursor.execute.call_args[0][1]
        source_param = params[8]
        assert isinstance(source_param, Json)
        assert source_param.obj == binding.source.model_dump(exclude_none=True)

    def test_fail_loud_on_zero_rowcount(self) -> None:
        """Schema-drift tripwire: if the SQL ever changes to DO NOTHING and a
        conflict suppresses the write, the guard must raise with the binding id
        so the loader bug surfaces immediately instead of silently dropping
        writes. For the current DO UPDATE SQL this branch is unreachable;
        monkeypatching rowcount=0 simulates the post-drift state."""
        binding = _make_jurisdiction_binding()
        mock_conn, mock_cursor = _make_mock_conn()
        mock_cursor.rowcount = 0

        with pytest.raises(RuntimeError) as exc_info:
            upsert_jurisdiction_binding(mock_conn, binding)

        error_msg = str(exc_info.value)
        assert "cur.rowcount == 0" in error_msg
        assert binding.id in error_msg

    def test_no_commit_by_helper(self) -> None:
        """upsert_jurisdiction_binding must NOT call conn.commit() — caller controls the transaction boundary."""
        binding = _make_jurisdiction_binding()
        mock_conn, _mock_cursor = _make_mock_conn()
        upsert_jurisdiction_binding(mock_conn, binding)
        mock_conn.commit.assert_not_called()
