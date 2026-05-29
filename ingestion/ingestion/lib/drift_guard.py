"""Drift-guard helpers for id text-PK assertions.

See ADR-020 and Q19 in docs/open-questions.md for the design rationale.
This module is state-agnostic per ADR-005 — no imports from ingestion/states/.
"""

from collections.abc import Callable, Mapping
from typing import Any


def assert_dispatch_dict_drift_free(
    dispatch: Mapping[Any, Mapping[str, Any]],
    derive_id: Callable[[Any, Mapping[str, Any]], str],
    *,
    helper_name: str,
    id_field: str = "id",
) -> None:
    """Assert every dispatch entry's id-field matches its derivation.

    Raises RuntimeError naming the first offending key with both the stored
    id and the derived id, so an operator can locate the drift in seconds.
    """
    for key, entry in dispatch.items():
        if id_field not in entry:
            raise RuntimeError(
                f"{helper_name} drift detected for key={key!r}: "
                f"entry has no {id_field!r} field — present keys: "
                f"{sorted(entry.keys())!r}. See ADR-020 and Q19 in "
                f"docs/open-questions.md."
            )
        stored = entry[id_field]
        derived = derive_id(key, entry)
        if stored != derived:
            raise RuntimeError(
                f"{helper_name} drift detected for key={key!r}: "
                f"stored {id_field}={stored!r} does not match derived "
                f"{id_field}={derived!r}; either update the stored value "
                f"to match or update the derivation function to reflect a "
                f"deliberate slug-encoding change. See ADR-020 and Q19 in "
                f"docs/open-questions.md."
            )


def assert_id_matches(
    entity_id: str,
    expected_id: str,
    *,
    helper_name: str,
    context: Mapping[str, Any],
) -> None:
    """Assert a constructed entity's id matches the derivation re-call.

    For per-row constructed entities (S03.7's runtime case): re-call the
    pure id-constructor with the entity's own structured fields and compare
    to the constructed entity's id. Raises RuntimeError on mismatch with
    full structured-field context.
    """
    if entity_id != expected_id:
        context_parts = ", ".join(f"{k}={v!r}" for k, v in context.items())
        raise RuntimeError(
            f"{helper_name} drift detected: entity.id={entity_id!r} does "
            f"not match derived id={expected_id!r} from fields "
            f"{context_parts}; the entity's structured fields no longer "
            f"agree with the id its constructor would produce. See ADR-020 "
            f"and Q19 in docs/open-questions.md."
        )
