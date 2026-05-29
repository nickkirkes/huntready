"""Unit tests for ``ingestion.lib.drift_guard``.

Coverage:
- TestAssertDispatchDictDriftFree — 8 tests for assert_dispatch_dict_drift_free
- TestAssertIdMatches             — 5 tests for assert_id_matches
- TestNoStateAdapterImports       — 1 AST guard confirming no state-adapter imports
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from ingestion.lib.drift_guard import assert_dispatch_dict_drift_free, assert_id_matches

# ---------------------------------------------------------------------------
# Path constant for AST guard
# ---------------------------------------------------------------------------

_DRIFT_GUARD_PATH = (
    Path(__file__).resolve().parent.parent / "ingestion" / "lib" / "drift_guard.py"
)


# ---------------------------------------------------------------------------
# TestAssertDispatchDictDriftFree
# ---------------------------------------------------------------------------


class TestAssertDispatchDictDriftFree:
    """Tests for assert_dispatch_dict_drift_free."""

    def _make_dispatch(self) -> dict[str, dict[str, Any]]:
        """Toy dispatch with 3 entries whose ids match the key prefixed with 'entry-'."""
        return {
            "alpha": {"id": "entry-alpha", "value": 1},
            "beta": {"id": "entry-beta", "value": 2},
            "gamma": {"id": "entry-gamma", "value": 3},
        }

    def _identity_derive(self, key: Any, entry: Mapping[str, Any]) -> str:
        """Return the stored id unchanged — simulates a correct derivation."""
        return str(entry["id"])

    def _prefixed_derive(self, key: Any, entry: Mapping[str, Any]) -> str:
        """Derive id by prefixing key — matches the toy dispatch's id scheme."""
        return f"entry-{key}"

    def test_passes_when_all_entries_match(self) -> None:
        """No exception when every entry's id matches the derivation."""
        dispatch = self._make_dispatch()
        # Should complete silently.
        assert_dispatch_dict_drift_free(
            dispatch,
            self._identity_derive,
            helper_name="test_helper",
        )

    def test_raises_on_first_drifted_entry(self) -> None:
        """RuntimeError raised when one entry's id has drifted."""
        dispatch: dict[str, dict[str, Any]] = {
            "alpha": {"id": "entry-alpha", "value": 1},
            "beta": {"id": "WRONG-VALUE", "value": 2},
        }
        with pytest.raises(RuntimeError):
            assert_dispatch_dict_drift_free(
                dispatch,
                self._prefixed_derive,
                helper_name="test_helper",
            )

    def test_error_message_names_helper_name(self) -> None:
        """RuntimeError message contains the helper_name argument exactly."""
        dispatch: dict[str, dict[str, Any]] = {
            "x": {"id": "BAD", "value": 0},
        }

        def _always_good(key: Any, entry: Mapping[str, Any]) -> str:
            return "GOOD"

        with pytest.raises(RuntimeError) as excinfo:
            assert_dispatch_dict_drift_free(
                dispatch,
                _always_good,
                helper_name="my_special_helper",
            )
        assert "my_special_helper" in str(excinfo.value)

    def test_error_message_names_offending_key(self) -> None:
        """RuntimeError message contains the drifted entry's key in repr() form."""
        dispatch: dict[str, dict[str, Any]] = {
            "offending-key": {"id": "BAD", "value": 0},
        }

        def _always_good(key: Any, entry: Mapping[str, Any]) -> str:
            return "GOOD"

        with pytest.raises(RuntimeError) as excinfo:
            assert_dispatch_dict_drift_free(
                dispatch,
                _always_good,
                helper_name="test_helper",
            )
        assert repr("offending-key") in str(excinfo.value)

    def test_error_message_shows_stored_and_derived(self) -> None:
        """RuntimeError message contains both the stored and derived id values."""
        dispatch: dict[str, dict[str, Any]] = {
            "k": {"id": "stored-value", "value": 0},
        }

        def _always_derived(key: Any, entry: Mapping[str, Any]) -> str:
            return "derived-value"

        with pytest.raises(RuntimeError) as excinfo:
            assert_dispatch_dict_drift_free(
                dispatch,
                _always_derived,
                helper_name="test_helper",
            )
        message = str(excinfo.value)
        assert repr("stored-value") in message
        assert repr("derived-value") in message

    def test_missing_id_field_raises_diagnostic_runtime_error(self) -> None:
        """Missing id_field in an entry raises a diagnostic RuntimeError, not a raw KeyError.

        The helper's whole purpose is fail-loud-with-diagnostic; bare
        KeyError would defeat that. The error must name the helper, the
        offending key, the missing field, and the entry's present keys so
        an operator can locate the drift without re-reading the code.
        """
        dispatch: dict[str, dict[str, Any]] = {
            "row1": {"id": "id-row1", "kind": "obligation"},
            "row2": {"kind": "obligation"},  # missing "id"
        }

        def derive_from_key(key: Any, entry: Mapping[str, Any]) -> str:
            # Pass row1's id-match so iteration reaches row2's missing field.
            return f"id-{key}"

        with pytest.raises(RuntimeError) as excinfo:
            assert_dispatch_dict_drift_free(
                dispatch,
                derive_from_key,
                helper_name="_TEST_SPEC",
            )

        message = str(excinfo.value)
        assert "_TEST_SPEC" in message
        assert repr("row2") in message
        assert repr("id") in message
        assert "present keys" in message

    def test_empty_dispatch_no_op(self) -> None:
        """Empty dispatch dict passes silently with no exception."""

        def _never_called(key: Any, entry: Mapping[str, Any]) -> str:
            return "anything"  # pragma: no cover

        assert_dispatch_dict_drift_free(
            {},
            _never_called,
            helper_name="test_helper",
        )

    def test_supports_custom_id_field(self) -> None:
        """Works with a custom id_field parameter (e.g. 'id_suffix')."""
        dispatch: dict[str, dict[str, Any]] = {
            "row1": {"id_suffix": "suffix-row1", "kind": "obligation"},
            "row2": {"id_suffix": "suffix-row2", "kind": "obligation"},
        }

        def derive_suffix(key: Any, entry: Mapping[str, Any]) -> str:
            return f"suffix-{key}"

        # Should pass silently — all ids match.
        assert_dispatch_dict_drift_free(
            dispatch,
            derive_suffix,
            helper_name="test_helper",
            id_field="id_suffix",
        )

        # Introduce a drift and confirm RuntimeError is raised.
        dispatch["row2"]["id_suffix"] = "WRONG"
        with pytest.raises(RuntimeError):
            assert_dispatch_dict_drift_free(
                dispatch,
                derive_suffix,
                helper_name="test_helper",
                id_field="id_suffix",
            )

    def test_derive_callable_receives_key_and_entry(self) -> None:
        """derive_id is called with both (key, entry) per dispatch item."""
        dispatch: dict[str, dict[str, Any]] = {
            "a": {"id": "a"},
            "b": {"id": "b"},
            "c": {"id": "c"},
        }
        calls: list[tuple[Any, Mapping[str, Any]]] = []

        def spy_derive(key: Any, entry: Mapping[str, Any]) -> str:
            calls.append((key, entry))
            return str(entry["id"])

        assert_dispatch_dict_drift_free(dispatch, spy_derive, helper_name="test_helper")

        assert len(calls) == 3
        called_keys = {k for k, _ in calls}
        assert called_keys == {"a", "b", "c"}
        for key, entry in calls:
            assert entry is dispatch[str(key)]


# ---------------------------------------------------------------------------
# TestAssertIdMatches
# ---------------------------------------------------------------------------


class TestAssertIdMatches:
    """Tests for assert_id_matches."""

    def test_passes_when_ids_match(self) -> None:
        """No exception when entity_id equals expected_id."""
        assert_id_matches(
            "US-MT-abc-bear-2026",
            "US-MT-abc-bear-2026",
            helper_name="test_helper",
            context={"state": "US-MT", "species": "bear"},
        )

    def test_raises_on_mismatch(self) -> None:
        """RuntimeError raised when entity_id differs from expected_id."""
        with pytest.raises(RuntimeError):
            assert_id_matches(
                "US-MT-abc-bear-2026",
                "US-MT-abc-elk-2026",
                helper_name="test_helper",
                context={"state": "US-MT"},
            )

    def test_error_message_names_helper_name(self) -> None:
        """RuntimeError message contains the helper_name argument."""
        with pytest.raises(RuntimeError) as excinfo:
            assert_id_matches(
                "entity-id",
                "expected-id",
                helper_name="my_unique_helper_name",
                context={},
            )
        assert "my_unique_helper_name" in str(excinfo.value)

    def test_error_message_includes_context_fields(self) -> None:
        """RuntimeError message contains all context dict keys and values in k=v form."""
        ctx = {"state": "US-MT", "species_group": "elk", "license_year": 2026}
        with pytest.raises(RuntimeError) as excinfo:
            assert_id_matches(
                "entity-id",
                "expected-id",
                helper_name="test_helper",
                context=ctx,
            )
        message = str(excinfo.value)
        for k, v in ctx.items():
            assert f"{k}={v!r}" in message, (
                f"Expected '{k}={v!r}' in error message, got: {message}"
            )

    def test_error_message_shows_entity_and_derived(self) -> None:
        """RuntimeError message contains both entity_id and expected_id in repr() form."""
        entity = "stored-entity-id"
        expected = "freshly-derived-id"
        with pytest.raises(RuntimeError) as excinfo:
            assert_id_matches(
                entity,
                expected,
                helper_name="test_helper",
                context={},
            )
        message = str(excinfo.value)
        assert repr(entity) in message
        assert repr(expected) in message


# ---------------------------------------------------------------------------
# TestNoStateAdapterImports
# ---------------------------------------------------------------------------


class TestNoStateAdapterImports:
    """AST guard: drift_guard.py must not import from any state adapter module.

    This is the inverted form of S03.10's TestNoLibImports pattern — here we
    confirm a *library* module has no *state-adapter* imports.
    """

    def test_drift_guard_has_no_state_imports(self) -> None:
        """drift_guard.py contains no imports from ingestion.states or states.*."""
        source = _DRIFT_GUARD_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("ingestion.states"), (
                    f"drift_guard.py imports from ingestion.states: {module!r}"
                )
                assert "states." not in module, (
                    f"drift_guard.py imports module containing 'states.': {module!r}"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name or ""
                    assert not name.startswith("ingestion.states"), (
                        f"drift_guard.py imports from ingestion.states: {name!r}"
                    )
                    assert "states." not in name, (
                        f"drift_guard.py imports module containing 'states.': {name!r}"
                    )
