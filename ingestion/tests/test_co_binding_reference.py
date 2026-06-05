"""Regression guards for S05.6's CO binding-loader reference scaffold.

Locks the cross-state spatial-filter discipline (handoff §8 #5, S03.10 precedent)
so E06's CO binding loader inherits a SQL block that cannot cross-bind CO zones
to MT geometry. Reference-only — no DB connection is made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from states.colorado.load_jurisdiction_bindings import (
    _NO_HUNT_ZONE_NEARBY_DISTANCE_M,
    _QUERY_NEARBY_GMUS_FOR_ZONE_SQL,
    _STATE,
    query_nearby_gmus_for_zone,
)


class TestCoBindingReferenceSql:
    def test_state_constant_is_us_co(self) -> None:
        assert _STATE == "US-CO"

    def test_nearby_distance_inherits_mt_5000(self) -> None:
        assert _NO_HUNT_ZONE_NEARBY_DISTANCE_M == 5000

    def test_co_binding_loader_sql_filters_by_state_co_pollution_guard(self) -> None:
        # AC-3: positive substrings present, MT-state-leak absent.
        sql = _QUERY_NEARBY_GMUS_FOR_ZONE_SQL
        assert "WHERE gmu.state =" in sql
        # The state filter must be %s-parameter-bound, NOT a hardcoded literal
        # like `WHERE gmu.state = 'US-CO'` (which would pass the substring check
        # above but leave _STATE unused and the query unredirectable).
        assert "WHERE gmu.state = %s" in sql
        assert "AND gmu.kind = 'gmu'" in sql
        assert "'US-MT'" not in sql, (
            "Reference SQL must not hardcode the MT state code — the state "
            "filter is parameter-bound via _STATE to avoid cross-state pollution."
        )

    def test_sql_uses_extensions_prefix_not_bare_name(self) -> None:
        # AC-4: every ST_* call is extensions.-prefixed.
        sql = _QUERY_NEARBY_GMUS_FOR_ZONE_SQL
        # >= 1 kills the vacuous-zero case (0 == 0 would pass if ST_DWithin
        # were absent entirely).
        assert sql.count("extensions.ST_DWithin") >= 1
        # No bare ST_DWithin: every occurrence must be extensions.-prefixed.
        assert sql.count("ST_DWithin") == sql.count("extensions.ST_DWithin")

    def test_sql_is_boundary_to_boundary_not_centroid(self) -> None:
        # AC-5: ST_DWithin (boundary-to-boundary), not centroid ST_Distance.
        sql = _QUERY_NEARBY_GMUS_FOR_ZONE_SQL
        assert "ST_DWithin" in sql
        assert "ST_Distance" not in sql
        assert "ST_Centroid" not in sql

    def test_sql_filters_kind_gmu_not_state(self) -> None:
        # AC-6: filters kind='gmu' (excludes the kind='state' CO-STATEWIDE-geom row).
        sql = _QUERY_NEARBY_GMUS_FOR_ZONE_SQL
        assert "gmu.kind = 'gmu'" in sql

    def test_sql_binds_distance_threshold_not_hardcoded(self) -> None:
        # Distance is a bound %s, not a hardcoded 5000 literal — so E06's
        # recalibration of _NO_HUNT_ZONE_NEARBY_DISTANCE_M takes effect without
        # editing the SQL string (mirrors MT binding the constant as a param).
        sql = _QUERY_NEARBY_GMUS_FOR_ZONE_SQL
        assert "gmu.geom, %s)" in sql
        assert "gmu.geom, 5000)" not in sql
        # Three bind placeholders: state, zone geom, distance.
        assert sql.count("%s") == 3

    def test_reference_function_binds_state_and_distance_params(self) -> None:
        # Locks that _STATE (param[0]) and _NO_HUNT_ZONE_NEARBY_DISTANCE_M
        # (param[2]) are actually *used* — not just defined.
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        query_nearby_gmus_for_zone(conn, "SRID=4326;POINT(-105.5 39.5)")
        executed_sql = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert executed_sql is _QUERY_NEARBY_GMUS_FOR_ZONE_SQL
        assert params[0] == "US-CO"
        assert params[2] == _NO_HUNT_ZONE_NEARBY_DISTANCE_M
        assert "US-MT" not in str(params)
