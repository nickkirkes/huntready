> **Status:** Historical — implemented and merged in commit 43504276cd0118d9368ea2e5e885e95ff43a341d on 2026-05-28. This plan was an active build/fix artifact; treat as historical reference only.

# Implementation Plan: Q19 — id text-PK UPSERT slug-drift project-wide fix

Plan-format-version: 1

## Context

Q19 in `docs/open-questions.md` (lines 388-437) describes an architectural correctness bug in three `id text`-PK UPSERT helpers in `ingestion/ingestion/lib/db.py`. The fix is locked to **Option A — derive-and-assert** (Options B and C are documented as rejected). User decision after Stage 2 discovery: proceed with **split-shape plan** — shared helper exposes both surfaces (compile-time dispatch-dict for S03.9, single-entity assert for S03.7's runtime-constructed entities).

Discovery surfaced a key correction to the spec's framing: only `_REPORTING_ROW_SPEC` is a compile-time dispatch dict. S03.7's `season_definition` and `license_tag` ids are produced by **pure id-constructor functions** (`_season_definition_id`, `_bear_season_definition_id`, `_license_tag_id`, `_bear_license_tag_id`) called per extraction row inside 4 build functions. The construction-time assert re-calls the pure id-constructor with the entity's own structured fields and compares to `entity.id` — it preserves the V1-safe-by-construction property because the assert fires on every test run that imports/exercises the builders, before any DB write.

Discovery also clarified the scope of drift-vulnerable id-encoded fields:
- `season_definition`: id-encoded fields are `species`, `hd_number`, `season_key`, `_LICENSE_YEAR`. `name` is indirectly tied via `_SEASON_NAME_BY_KEY[season_key]`. `weapon_type` and `residency` are pure UPDATE-only fields (NOT id-encoded; not drift-vulnerable in the slug-identity sense).
- `license_tag`: id-encoded fields are `species`, `hd_number`, `license_code` (via `_license_code_slug`), `_LICENSE_YEAR`. `name` and `kind` are pure UPDATE-only fields.
- `reporting_obligation`: id_suffix is hand-encoded from `kind`, `deadline_hours`, `region_scope` (all drift-vulnerable; all in UPDATE clause).

## File Table

| File | Action | Task(s) |
|------|--------|---------|
| `ingestion/ingestion/lib/drift_guard.py` | Create | T1 |
| `ingestion/tests/test_drift_guard.py` | Create | T2 |
| `ingestion/states/montana/load_reporting_obligations.py` | Modify | T3 |
| `ingestion/tests/test_load_reporting_obligations.py` | Modify | T4 |
| `ingestion/states/montana/load_seasons_and_licenses.py` | Modify | T5 |
| `ingestion/tests/test_load_seasons_and_licenses.py` | Modify | T6 |
| `docs/adrs/ADR-020-id-text-pk-slug-derivation.md` | Create | T7 |
| `docs/adrs/README.md` | Modify | T8 |

## Pre-flight: Feature branch

Before any task: `git checkout -b fix/Q19-id-text-pk-slug-drift` from `main`. Verify `git branch --show-current` returns the feature branch name. m1 tag (`e11e7bb`) is on `main`; this branch begins post-m1, pre-M2.

## Tasks

### T1: Create shared drift-guard helper module (~5 min)

**Files:** `ingestion/ingestion/lib/drift_guard.py` (CREATE)

**Action:** New state-agnostic library module exposing two assert surfaces — one for compile-time dispatch dicts (the S03.9 case) and one for single-entity construction-time checks (the S03.7 case). Both raise `RuntimeError` on mismatch with full diagnostic context.

**Details:**

Module structure:

```python
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
```

Design constraints:
- `derive_id` callable for the dispatch-dict surface receives `(key, entry)` so it can use either or both — `_derive_expected_id_suffix` in S03.9 uses fields from both. The S03.9 wrapper passes a small lambda.
- `id_field` defaults to `"id"` but S03.9's case uses `"id_suffix"` (the dict entry doesn't carry a full id — the prefix `mt-bear-` is concatenated at write time). Allowing override keeps the helper general.
- Diagnostic surface mirrors the S03.9 local guard's existing format closely so the refactor preserves operator-facing error messages.
- No state-adapter imports. The helper imports only from stdlib (`collections.abc`, `typing`).

**Verify:**
```bash
cd ingestion && .venv/bin/ruff check ingestion/lib/drift_guard.py && .venv/bin/mypy ingestion/lib/drift_guard.py
```

**UI:** no

---

### T2: Tests for shared drift-guard helper (~7 min)

**Files:** `ingestion/tests/test_drift_guard.py` (CREATE)

**Depends on:** T1

**Action:** Comprehensive unit tests for the shared helper covering both surfaces, fault injection, diagnostic message content, and a state-agnostic-clean AST guard.

**Details:**

Test classes (~12-14 tests total):

1. `TestAssertDispatchDictDriftFree`:
   - `test_passes_when_all_entries_match` — toy dispatch with 3 entries, identity derive function, no exception
   - `test_raises_on_first_drifted_entry` — toy dispatch with 1 drifted entry, RuntimeError raised
   - `test_error_message_names_helper_name` — RuntimeError message contains the `helper_name` argument
   - `test_error_message_names_offending_key` — RuntimeError message contains the drifted key
   - `test_error_message_shows_stored_and_derived` — RuntimeError message contains both stored and derived values
   - `test_empty_dispatch_no_op` — empty mapping passes silently (no exception, no iteration)
   - `test_supports_custom_id_field` — works with `id_field="id_suffix"` (the S03.9 case)
   - `test_derive_callable_receives_key_and_entry` — derive callable signature verified via spy

2. `TestAssertIdMatches`:
   - `test_passes_when_ids_match` — matching id + expected, no exception
   - `test_raises_on_mismatch` — RuntimeError raised
   - `test_error_message_names_helper_name` — RuntimeError contains helper_name
   - `test_error_message_includes_context_fields` — RuntimeError contains all context dict keys + values in `k=v` form
   - `test_error_message_shows_entity_and_derived` — RuntimeError contains both `entity_id` and `expected_id`

3. `TestNoStateAdapterImports`:
   - AST-walk `ingestion/ingestion/lib/drift_guard.py`, parse imports, assert none reference `ingestion.states.*` or path `ingestion/states/`. Mirrors S03.10's `TestNoLibImports` pattern but inverted (lib-side guard rather than test-side state guard).

**Verify:**
```bash
cd ingestion && .venv/bin/pytest tests/test_drift_guard.py -v
```

**UI:** no

---

### T3: Refactor `load_reporting_obligations.py` to use shared helper (~5 min)

**Files:** `ingestion/states/montana/load_reporting_obligations.py`

**Depends on:** T1

**Action:** Replace the local `_assert_dispatch_dict_drift_free` (line 339-365) with a call to the shared helper at module load. Keep `_derive_expected_id_suffix` (line 293-336) as the local derivation function — it's reasonably specific to MT's reporting scheme. Wrap it in a small lambda that adapts to the shared helper's `(key, entry) -> str` callable signature.

**Details:**

1. Add import: `from ingestion.lib.drift_guard import assert_dispatch_dict_drift_free`
2. Delete the entire `_assert_dispatch_dict_drift_free` function definition (lines 339-365).
3. Replace the module-level call at line 370 with:
   ```python
   # V1 drift guard — see ADR-020 and Q19 in docs/open-questions.md.
   assert_dispatch_dict_drift_free(
       _REPORTING_ROW_SPEC,
       lambda key, entry: _derive_expected_id_suffix(
           entry["kind"], entry["deadline_hours"], key[0],  # key[0] is region_scope
       ),
       helper_name="_REPORTING_ROW_SPEC",
       id_field="id_suffix",
   )
   ```
4. Verify the existing `_REPORTING_ROW_SPEC` is unchanged; verify `_derive_expected_id_suffix` is unchanged.
5. Verify module imports cleanly: `cd ingestion && .venv/bin/python -c "from ingestion.states.montana import load_reporting_obligations"` must succeed.
6. Verify existing tests still pass: `cd ingestion && .venv/bin/pytest tests/test_load_reporting_obligations.py -v`.

**Verify:**
```bash
cd ingestion && .venv/bin/ruff check ingestion/states/montana/load_reporting_obligations.py && .venv/bin/mypy ingestion/states/montana/load_reporting_obligations.py && .venv/bin/pytest tests/test_load_reporting_obligations.py -v
```

**UI:** no

---

### T4: Drift-guard tests for `load_reporting_obligations.py` (~5 min)

**Files:** `ingestion/tests/test_load_reporting_obligations.py`

**Depends on:** T3

**Action:** Add (a) a round-trip lock asserting every `_REPORTING_ROW_SPEC` entry round-trips through `_derive_expected_id_suffix`; (b) a fault-injection test verifying the module-load guard raises RuntimeError when a drifted entry is monkeypatched in. The existing fault-injection style — monkeypatch via `importlib.reload` after mutating a copy of `_REPORTING_ROW_SPEC` — must be preserved if it already exists; otherwise add it fresh.

**Details:**

Add a new test class `TestDriftGuardPreservation` (~4-5 tests):

1. `test_dispatch_round_trip_locks` — iterate `_REPORTING_ROW_SPEC.items()`, call `_derive_expected_id_suffix` per entry, assert each `entry["id_suffix"]` matches.
2. `test_module_import_passes_drift_guard` — the import-time assertion already fires when the test module imports `load_reporting_obligations`; this test documents that no exception was raised at import time.
3. `test_fault_injection_drifted_entry_raises_runtime_error` — construct a mutated copy of `_REPORTING_ROW_SPEC` with one entry's `id_suffix` set to `"bogus"`. Call `assert_dispatch_dict_drift_free` directly on the mutated dict. Assert RuntimeError raised with the offending key in the message.
4. `test_error_message_names_q19_and_adr020` — fault-inject and assert RuntimeError message references both Q19 and ADR-020 (cross-reference discipline).
5. `test_semantic_identity_with_prior_local_guard` — since the local `_assert_dispatch_dict_drift_free` is deleted in T3 before T4 runs, this test cannot run both side-by-side. Instead, enumerate a fixed regression baseline of **3 mutation cases** (one per `_REPORTING_ROW_SPEC` entry — the STATEWIDE harvest_report, the R1 tooth_submission, the R2-7 hide_skull_presentation):
   - Mutation 1: `id_suffix="bogus-harvest-id"` for the `("STATEWIDE", "harvest_report")` entry
   - Mutation 2: `id_suffix="bogus-tooth-id"` for the `("R1", "tooth_submission")` entry
   - Mutation 3: `id_suffix="bogus-hide-id"` for the `("R2-7", "hide_skull_presentation")` entry

   For each mutation: build a mutated copy of `_REPORTING_ROW_SPEC` with only that one entry's `id_suffix` overridden, call `assert_dispatch_dict_drift_free` directly on the mutated dict (matching T3's lambda + helper_name + id_field args), assert RuntimeError raised, and assert the error message contains the offending key. This locks the deleted local function's behavior as a 3-case regression baseline, documenting it in the test docstring as "no removal of S03.9's local guard without semantic-identity verification" per the spec's Hard NOs. Without this concrete enumeration, the test would be trivially satisfied by a vacuous import-time check.

**Verify:**
```bash
cd ingestion && .venv/bin/pytest tests/test_load_reporting_obligations.py::TestDriftGuardPreservation -v
```

**UI:** no

---

### T5: Add construction-time asserts to 4 build functions in `load_seasons_and_licenses.py` (~10 min)

**Files:** `ingestion/states/montana/load_seasons_and_licenses.py`

**Depends on:** T1

**Action:** In each of the 4 entity-build functions, immediately after each `SeasonDefinition` / `LicenseTag` is constructed, call `assert_id_matches` with the entity's `.id`, a re-call of the pure id-constructor using the entity's structured fields, the helper name, and a context dict naming the inputs.

**Details:**

1. Add import at top of file:
   ```python
   from ingestion.lib.drift_guard import assert_id_matches
   ```

2. In `_build_dea_season_definitions` (line 817-917), after each `SeasonDefinition` construction (e.g., at line ~861-865 where `season_definition_id = _season_definition_id(...)` is followed by entity construction), add:
   ```python
   # Construction-time drift guard — see ADR-020.
   assert_id_matches(
       sd.id,
       _season_definition_id(species, hd_number, season_key),
       helper_name="_build_dea_season_definitions",
       context={"species": species, "hd_number": hd_number, "season_key": season_key},
   )
   ```
   Place the assert immediately after the `SeasonDefinition(...)` constructor call, BEFORE the entity is appended to the build list. Use the local variables already in scope at the call site — do NOT re-derive from `sd.species` / `sd.hd_number` (those may or may not exist as model fields; the local variables are guaranteed to be the inputs that went into the id construction).

3. In `_build_bear_season_definitions` (line 500-590), at line ~577 where bear `SeasonDefinition` is constructed via `_bear_season_definition_id(bmu_number, season_key)`, add the equivalent assert:
   ```python
   assert_id_matches(
       sd.id,
       _bear_season_definition_id(bmu_number, season_key),
       helper_name="_build_bear_season_definitions",
       context={"bmu_number": bmu_number, "season_key": season_key},
   )
   ```

4. In `_build_dea_license_tags` (line 969-1075), at line ~1058 where `LicenseTag` is constructed via `_license_tag_id(species_group, hd_number, license_code)`:
   ```python
   assert_id_matches(
       lt.id,
       _license_tag_id(species_group, hd_number, license_code),
       helper_name="_build_dea_license_tags",
       context={"species_group": species_group, "hd_number": hd_number, "license_code": license_code},
   )
   ```

5. In `_build_bear_license_tags` (line 598-655), at line ~638 where bear `LicenseTag` is constructed via `_bear_license_tag_id(bmu_number)`:
   ```python
   assert_id_matches(
       lt.id,
       _bear_license_tag_id(bmu_number),
       helper_name="_build_bear_license_tags",
       context={"bmu_number": bmu_number},
   )
   ```

6. Do NOT add asserts to the link-table builders (`_build_*_license_season_links`, `_build_*_regulation_season_links`, `_build_*_regulation_license_links`). Link tables reference id strings but don't construct new entity ids — the constructor calls there are lookups to compute the FK value, not entity id construction. Asserting there would be tautological and noisy.

7. **REQUIRED STRUCTURAL CHANGE AT ALL 4 SITES** (per review-fix C1): All four build functions construct entities INLINE inside `list.append(...)` calls — none of them currently bind to a local variable. Specifically:
   - `_build_dea_season_definitions` at L900-913: `definitions.append(SeasonDefinition(id=season_definition_id, ...))`
   - `_build_bear_season_definitions` at L575-588: `definitions.append(SeasonDefinition(...))`
   - `_build_dea_license_tags` at L1056-1073: `tags.append(LicenseTag(id=_license_tag_id(...), ...))`
   - `_build_bear_license_tags` at L636-653: `tags.append(LicenseTag(id=_bear_license_tag_id(...), ...))`

   At EACH site, the refactor is mandatory: (a) extract the constructor call into a local variable (`sd = SeasonDefinition(...)` or `lt = LicenseTag(...)`), (b) add the `assert_id_matches` call, (c) `definitions.append(sd)` or `tags.append(lt)`. This is a 3-line refactor per site, not a one-line addition. Verify each site's existing argument set is preserved exactly (no field reordering, no formatting drift).

**Verify:**
```bash
cd ingestion && .venv/bin/ruff check ingestion/states/montana/load_seasons_and_licenses.py && .venv/bin/mypy ingestion/states/montana/load_seasons_and_licenses.py && .venv/bin/pytest tests/test_load_seasons_and_licenses.py -v
```

**UI:** no

---

### T6: Drift-guard tests for `load_seasons_and_licenses.py` (~10 min)

**Files:** `ingestion/tests/test_load_seasons_and_licenses.py`

**Depends on:** T5

**Action:** Add construction-time drift-guard tests covering all 4 build functions: round-trip locks (real-artifact data passes the assert end-to-end) + fault-injection (monkeypatch the id-constructor to return a wrong value mid-build; confirm RuntimeError raises with the offending entity's context).

**Details:**

Add a new test class `TestConstructionTimeDriftGuard` (~16-20 tests):

For EACH of the 4 build functions, add 4 tests:

1. **Round-trip lock (real artifact)** — build entities from real or fixture artifact data; assert no RuntimeError raised; assert the build returned the expected entity count. Locks the contract that the as-shipped builders satisfy the drift guard.

2. **Fault-injection via constructor monkeypatch** — `monkeypatch.setattr` on the relevant id-constructor (e.g., `load_seasons_and_licenses._season_definition_id`). Run the build; assert RuntimeError raised; assert the error message contains the structured-field context (e.g., `species`, `hd_number`, `season_key`).

   **Important fault-injection design note:** The id-constructor is called TWICE for each entity now — once when constructing the entity (line ~861-865 for DEA seasons), and once in the assert. We need the fault to fire on ONE call but not the other. Two approaches:
   - (a) Monkeypatch returns the real value on first call, bogus on second call (using a counter closure). The entity is constructed with the real id; the assert re-derives a bogus id; the assert raises.
   - (b) Monkeypatch returns bogus on first call, real on second call. The entity is constructed with bogus id; the assert re-derives real id; the assert raises.

   Approach (b) is more representative of the real drift scenario (entity.id is wrong, derivation is correct). Use (b).

   **Use a boolean-flip monkeypatch, NOT a counter** (per review-fix S3). The implementation pattern:
   ```python
   real = load_seasons_and_licenses._season_definition_id
   first_call = [True]
   def spy(species, hd_number, season_key):
       if first_call[0]:
           first_call[0] = False
           return "MT-BOGUS-DRIFT-SENTINEL-id"
       return real(species, hd_number, season_key)
   monkeypatch.setattr(load_seasons_and_licenses, "_season_definition_id", spy)
   ```
   Reason: a counter-based monkeypatch is non-deterministic about WHICH entity triggers the error if the builder loops over many rows in non-deterministic order. A boolean flip guarantees exactly the first entity construction triggers the error regardless of artifact row count. Tests should document this choice in the docstring.

3. **Error message contains helper_name** — verify the RuntimeError message names the build function (`_build_dea_season_definitions` etc.).

4. **Error message contains all context fields** — verify every field passed to the `context` dict appears in the error message in `k=v` form.

After the 4 builders are tested, add:

5. **`test_no_link_builders_have_asserts_regression_guard`** — AST-walk `load_seasons_and_licenses.py`, find the exact 6 link-builder functions and assert no `assert_id_matches` call appears in their function bodies. Locks the design decision in T5 step 6 against future drift. The exact function names to enumerate (per N2):
   - `_build_bear_license_season_links` (L658)
   - `_build_bear_regulation_season_links` (L688)
   - `_build_bear_regulation_license_links` (L722)
   - `_build_dea_license_season_links` (L1083)
   - `_build_dea_regulation_season_links` (L1127)
   - `_build_dea_regulation_license_links` (L1178)

Test count delta target for this task: +16 to +20.

**Verify:**
```bash
cd ingestion && .venv/bin/pytest tests/test_load_seasons_and_licenses.py::TestConstructionTimeDriftGuard -v
```

**UI:** no

---

### T7: Draft ADR-020 (~7 min)

**Files:** `docs/adrs/ADR-020-id-text-pk-slug-derivation.md` (CREATE)

**Action:** Draft ADR-020 at **Status: Proposed** — NOT Accepted. PM does not commit ADR decisions autonomously; user reviews before status flips per the DRAFT-file pattern from S03.11. Use the project's TEMPLATE.md as the structural baseline (read it first; do not deviate from the section order or names); 300-700 word target per README.md line 95.

**Details:**

Frontmatter (per TEMPLATE.md L1-7):
- Title: `ADR-020: Derive-and-Assert for id text-PK Slug Drift`
- **Date:** `2026-05` (current month, YYYY-MM form)
- **Status:** `Proposed`
- **Decider:** `Nick Kirkes`
- **Tags:** `ingestion, storage`

Required sections IN THIS EXACT ORDER (per TEMPLATE.md L10-43, per review-fix S1):

1. **Context** (TEMPLATE.md L10-12): One to three paragraphs. Frame:
   - Summarize Q19's framing: 3 affected helpers (`_UPSERT_SEASON_DEFINITION_SQL`, `_UPSERT_LICENSE_TAG_SQL`, `_UPSERT_REPORTING_OBLIGATION_SQL`) in `ingestion/ingestion/lib/db.py`
   - Note that across these 3 helpers, the slug-encoded id fields are NOT a uniform set: `reporting_obligation` encodes `kind` / `deadline_hours` / `region_scope` (all also in UPDATE clause); `season_definition` encodes `species` / `hd_number` / `season_key` / `_LICENSE_YEAR` (where `name` is indirectly tied via `_SEASON_NAME_BY_KEY[season_key]` but `weapon_type` / `residency` are pure UPDATE-only and NOT id-encoded); `license_tag` encodes `species` / `hd_number` / `license_code` / `_LICENSE_YEAR` (where `name` / `kind` are pure UPDATE-only and NOT id-encoded). This per-N1 disambiguation matters because the Q19 table is imprecise on which UPDATEd columns are actually drift-vulnerable in the slug-identity sense.
   - Note S03.9 cubic-review round 3 surfaced the risk via the duplicate-id guard discussion, leading to the local `_assert_dispatch_dict_drift_free` pattern in `load_reporting_obligations.py:339-365` as the seed template
   - Note S03.7 surfaces are **runtime-constructed** (not compile-time dispatch dicts) — pure id-constructors `_season_definition_id` / `_license_tag_id` / `_bear_season_definition_id` / `_bear_license_tag_id` called per artifact row inside 4 build functions
   - Note S03.6.1's `db.upsert_jurisdiction_binding` has a stronger contract (UPDATE clause excludes identity fields per OQ-S6.1-4) so Q19 does NOT apply — but the same derive-and-assert pattern applies if a future helper writes to `jurisdiction_binding` with mutable identity

2. **Decision** (TEMPLATE.md L14-16, 1-2 sentences):
   > For every `id text`-PK entity helper whose UPSERT ON CONFLICT DO UPDATE clause can rewrite slug-encoded fields, the id derivation is encoded as a pure callable, and an assertion verifies that every stored or constructed entity's id matches its derivation. The assertion fires at module load for compile-time dispatch dicts and at row-construction time for runtime-built entities — drift becomes impossible by construction.

3. **Reasoning** (TEMPLATE.md L18-20, loadbearing section — prose):
   - Why derive-and-assert (versus relying on convention or code review): the failure mode is silent — a stored id that no longer matches its structured fields will UPSERT cleanly with the wrong row identity, with no error at write time. The first symptom would be a year-over-year re-ingestion producing wrong-looking rows in production.
   - Why two assert surfaces: the dispatch-dict case (S03.9) and the construction-time case (S03.7) have genuinely different shapes — the dispatch-dict case asserts a pre-built association between key and stored id; the construction-time case asserts an entity's own field-to-id consistency. A single API would force one case to wear an awkward shape. The shared module exposes both as primitives.
   - Why the construction-time assert has tripwire value despite the id-constructor being pure: it locks the constructor-as-single-source-of-truth contract. A future contributor who manually constructs an id string at a new call site (bypassing the pure constructor) will trip the assert as soon as the entity's structured fields don't agree with the manual id.

4. **Alternatives Considered** (TEMPLATE.md L22-24, two to four sentences per alternative):
   - **Option B — Remove slug-encoded fields from UPDATE clause:** Removes the silent-update path by forcing INSERT-only for slug-encoded changes. A spec edit that changes them would mint a new id via INSERT, leaving the old row plus its link-table references orphaned and pointing at stale data. Trades semantic-drift risk for orphan-link risk; not a clean improvement. Rejected.
   - **Option C — Drop UPSERT, require TRUNCATE before re-runs:** Removes the UPDATE clause entirely by mandating a clean slate before each re-ingestion. Loses the "re-run without disruption" property that S03.6/S03.7/S03.8 explicitly cultivated — operators must coordinate TRUNCATE with downstream consumers, and partial-update scenarios become impossible. Rejected.

5. **Consequences** (TEMPLATE.md L26-38, three subsections required):

   **Positive:**
   - Drift is caught at import time (S03.9 case) or build time (S03.7 case) in CI, not at year-over-year re-ingestion against production data
   - Operator-facing error messages name the offending key plus stored vs. derived id, so the fix path is obvious without re-reading the code
   - The pattern generalizes to any future `id text`-PK helper via the shared `drift_guard.py` module

   **Negative:**
   - Any spec edit that legitimately moves an id (e.g., adding a new slug component to encode a new disambiguator) requires updating the derivation function AND the dispatch dict or call-site in the same commit
   - The assertion catches mismatch at import/build, not at write — a misconfigured CI environment that doesn't import the affected modules wouldn't catch the drift; mitigation is that every test run imports the modules transitively via the test_load_*.py files
   - The construction-time assert for S03.7 adds 3 lines of boilerplate (constructor extracted to local + assert + append) to each of the 4 entity-build call sites in `load_seasons_and_licenses.py`; the cost is paid in readability for the tripwire value

   **Neutral** (per TEMPLATE.md L36-38, "often the most informative section"):
   - The 3 affected SQL constants in `db.py` remain unchanged — the assertion lives at the dispatch-dict layer and the entity-construction layer, NOT in the SQL. Future readers debugging drift should look at `drift_guard.py` and the adapter files, not at `db.py`.
   - The shared helper exposes two surfaces (`assert_dispatch_dict_drift_free` for compile-time, `assert_id_matches` for construction-time). M2 adapter authors choose which to use based on whether their dispatch surface is module-level data or runtime-constructed entities.

6. **Links** (TEMPLATE.md L40-43):
   - [Q19 in `docs/open-questions.md`](../open-questions.md) — the originating risk analysis; to be marked RESOLVED in a separate PM commit AFTER this ADR's status flips to Accepted
   - [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md) — state-agnostic-clean discipline that places the shared helper in `ingestion/ingestion/lib/`
   - [ADR-010](ADR-010-decomposed-entity-model.md) — decomposed entity model that introduces the entities Q19 protects
   - [ADR-019](ADR-019-doc-type-precedence-multi-source-merge.md) — most recent ADR with a fail-loud architectural pattern; style reference
   - [`ingestion/ingestion/lib/drift_guard.py`](../../ingestion/ingestion/lib/drift_guard.py) — the shared helper module
   - [`ingestion/states/montana/load_reporting_obligations.py`](../../ingestion/states/montana/load_reporting_obligations.py) — dispatch-dict surface (S03.9 seed template)
   - [`ingestion/states/montana/load_seasons_and_licenses.py`](../../ingestion/states/montana/load_seasons_and_licenses.py) — 4 construction-time surfaces

Word count target: 500-650 (extractive ADR — most reasoning is upstream in Q19 and the discovery report).

**Verify:**
Read the file back; confirm Status line reads exactly `**Status:** Proposed`; confirm word count is within 300-700 (rough `wc -w` over the file body); confirm both `ingestion` and `storage` tags appear.

**UI:** no

---

### T8: Update `docs/adrs/README.md` index (~2 min)

**Files:** `docs/adrs/README.md`

**Depends on:** T7

**Action:** Append a new row to the ADR index table (line 62-81) for ADR-020.

**Details:**

Open `docs/adrs/README.md`, find the existing ADR index table (lines 62-81), and measure the actual column widths of the existing rows (count characters between pipe positions). Construct the ADR-020 row with padding that matches the widest existing row in each column so the table continues to render cleanly. Do NOT copy a pre-built example row from this plan file — measure first against the live file (per review-fix S4).

Row content (without padding):
- `#` column: `020`
- `Title` column: `Derive-and-Assert for id text-PK Slug Drift`
- `Status` column: `Proposed`
- `Tags` column: `ingestion, storage`

Insertion point: immediately after the ADR-019 row (line 81). Use `Edit` with `replace_all: false`; the unique `old_string` should be the ADR-019 row exactly as it appears.

Do NOT update CLAUDE.md's ADR list under "Key documents" (line ~228). That list currently shows ADR-001 through ADR-019. ADR-020 is Proposed, not Accepted — the CLAUDE.md update belongs to the PM commit that flips Q19 to RESOLVED after the ADR is accepted.

**Verify:**
```bash
grep -n "ADR-020\|020 | Derive" docs/adrs/README.md
```

**UI:** no

---

## Blast Radius

- **Do NOT modify:**
  - `ingestion/ingestion/lib/db.py` — the 3 affected SQL constants and all helper functions remain unchanged. The assertion layer lives at the dispatch-dict / construction-time layer, not in the SQL.
  - `db.upsert_jurisdiction_binding` or `_JURISDICTION_BINDING_ID_FORMAT` in `load_regulation_records.py` — per Hard NOs, the binding helper has a stronger contract already (excludes identity fields from UPDATE per OQ-S6.1-4).
  - `docs/open-questions.md` Q19 — per Hard NOs, Q19 resolution is a separate PM commit AFTER the ADR is Accepted.
  - CLAUDE.md `docs/adrs/` list under "Key documents" — ADR-020 is Proposed, not Accepted; CLAUDE.md update waits for status flip.
  - The link-table builders (`_build_*_license_season_links`, `_build_*_regulation_season_links`, `_build_*_regulation_license_links`) in `load_seasons_and_licenses.py` — they reference ids but don't construct entity ids.
  - All extraction artifacts (`dea-2026.json`, `black-bear-2026.json`, `legal-descriptions-2026.json`) — no upstream changes.

- **Watch for:**
  - Variable-naming collisions in `load_seasons_and_licenses.py` build loops — binding entity construction to local variables (`sd`, `lt`) may collide with existing local names. Inspect each call site before adding the assert.
  - Mypy errors on Pydantic frozen+extra="forbid" models — the assert reads `entity.id`, which is a frozen field; reads are fine, no mutation involved.
  - `_REPORTING_ROW_SPEC`'s `_RowSpec` TypedDict — the lambda in T3 step 3 reads `entry["kind"]` and `entry["deadline_hours"]`; mypy should infer these from the `_RowSpec` definition. If not, add explicit type annotations.
  - The Pydantic models for `SeasonDefinition` / `LicenseTag` may carry `frozen=True` + `extra="forbid"` — verify that the entity binding to a local variable (then asserting on `.id`) doesn't trigger validation errors. The constructor call already validates; the assert is read-only.

## Conventions

- **ADR-005** — state-agnostic-clean: `ingestion/ingestion/lib/drift_guard.py` MUST NOT import from `ingestion/states/`. AST-based test guard (T2's `TestNoStateAdapterImports`) locks this; mirrors S03.10's `TestNoLibImports` pattern.
- **ADR-009** — documentation as handoff: ADR-020 captures the decision; Q19's resolution follows in a separate PM commit; CLAUDE.md update waits for the status flip.
- **ADR-017** — confidence inheritance: no impact (drift_guard.py touches no confidence fields).
- **S03.9's seed template** — `_REPORTING_ROW_SPEC` + `_derive_expected_id_suffix` + module-level call. The shared helper generalizes the assert mechanism; the derivation function stays local to the adapter (specific to MT's reporting scheme).
- **Three-phase adapter pattern** (S03.6 / S03.7 / S03.8 / S03.9 / S03.10) — not affected; this is doc + helper work, no new DB-write adapter.
- **mypy per-file discipline** (S03.7 lesson, repeated in spec) — after EVERY task that modifies a Python file, run `mypy <file>` and confirm clean before reporting done. Agents have previously claimed "ruff + mypy clean" while leaving type errors.
- **Fail-loud diagnostics** (S03.10 pitfall G) — every RuntimeError must name (a) helper label, (b) offending key or entity context, (c) stored / entity id, (d) derived id. Operator-facing errors need enough context to fix without re-reading the code.
- **No "while we're here" refactors** — this work is Q19 + ADR only. Adjacent cleanups go to separate PRs.

## Test count budget

| Task | Test delta |
|------|-----------|
| T2 (shared helper) | +12 to +14 |
| T4 (S03.9 preservation) | +4 to +5 |
| T6 (S03.7 construction-time) | +16 to +20 (4 builders × 4 tests + 1 regression guard) |
| **Total** | **+32 to +39** |

Target band per spec: +25 to +40. This plan lands inside the band.

Pre-change baseline: 1128 passed + 2 skipped. Post-change expected: 1160-1167 passed + 2 skipped.

## Definition of done (per spec)

- `ruff check` clean across all modified files
- `mypy` clean per-file across all modified files (PM-discipline; verify, don't trust)
- Test suite shows +25 to +40 new tests; no `failed`; no regression in 1128 baseline
- `cubic review --json` returns `{"issues": []}` or all surfaced issues are demonstrably invalid
- ADR-020 file exists with **Status: Proposed**
- `docs/adrs/README.md` index updated
- The 3 affected SQL constants in `db.py` are **unchanged**
- Sanity smoke: importing `ingestion.states.montana.load_seasons_and_licenses` and `ingestion.states.montana.load_reporting_obligations` at the REPL succeeds; mutating a dispatch entry's `id_suffix` in a throwaway monkeypatch and re-importing raises `RuntimeError` naming the offending key
- Final commit SHA reported to PM; PM owns push, PR creation, ADR-Accepted flip, and Q19 RESOLVED PM commit
