# ADR-020: Derive-and-Assert for id text-PK Slug Drift

**Date:** 2026-05-28
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** ingestion, storage

---

## Context

Three `id text`-PK UPSERT helpers in `ingestion/ingestion/lib/db.py` allow the DO UPDATE clause to rewrite slug-encoded fields on conflict: `_UPSERT_SEASON_DEFINITION_SQL`, `_UPSERT_LICENSE_TAG_SQL`, and `_UPSERT_REPORTING_OBLIGATION_SQL`. The drift-vulnerable id inputs per helper: `reporting_obligation` — `(kind, deadline_hours, region_scope)`; `season_definition` — `(species, hd_number, season_key)` for DEA rows, `(bmu_number, season_key)` for bear rows; `license_tag` — `(species, hd_number, license_code)` for DEA rows, `(bmu_number,)` for bear rows. The `license_year` portion of every id comes from the module constant `_LICENSE_YEAR`, not a per-row field, so it is not drift-vulnerable.

The risk is silent: changing one slug-encoded field without updating the id constructor causes the same `id` to UPSERT cleanly with shifted identity. Link-table rows already pointing at that `id` then reference an entity whose meaning has changed, with no error at write time.

S03.9 cubic-review round 3 surfaced the risk and shipped a local guard in `load_reporting_obligations.py`; this ADR generalizes that seed. S03.7 differs: its id constructors are per-row callables inside four build functions, so the assert lives at construction time rather than module load. `db.upsert_jurisdiction_binding` (S03.6.1) excludes identity fields from UPDATE entirely; that schema-level exclusion is strictly stronger than an application-level assert, so the pattern does not extend there.

## Decision

For every `id text`-PK entity helper whose UPSERT ON CONFLICT DO UPDATE clause can rewrite slug-encoded fields, the id derivation is encoded as a pure callable, and an assertion verifies that every stored or constructed entity's id matches its derivation. The assertion fires at module load for compile-time dispatch dicts and at row-construction time for runtime-built entities — drift becomes impossible by construction.

## Reasoning

Without a guard, year-over-year re-ingestion is the first opportunity to surface drift — by which point link-table rows already reference the shifted entity. The derive-and-assert pattern closes the gap by making the id a function of its slug-encoded fields rather than a separately maintained string. The assertion lives at the adapter layer and fires on every CI run before any database connection opens; a contributor who manually builds an id at a new call site, bypassing the constructor, raises at construction time.

Two assert primitives serve different shapes: `assert_dispatch_dict_drift_free` fires once at module load over a compile-time dispatch dict (S03.9 `_REPORTING_ROW_SPEC`); `assert_id_matches` fires per entity before append over a runtime-constructed entity (S03.7 build functions). Both live in `drift_guard.py`; adapter authors pick based on their surface.

## Alternatives Considered

**Option B — Remove slug-encoded fields from the UPDATE clause.** Forces a new `id` via INSERT on any slug-field change, but leaves the old row and its link-table references orphaned. Trades semantic-drift risk for orphan-link risk. Rejected.

**Option C — Drop UPSERT; require TRUNCATE before re-runs.** Eliminates the conflict clause entirely, but loses the "re-run without disruption" property S03.6/S03.7/S03.8 cultivated. Rejected.

## Consequences

### Positive

- Drift is caught at import or build time in CI, not at year-over-year re-ingestion against production
- Operator-facing errors name the offending key plus stored vs. derived id, making the fix path obvious
- Generalizes to any future `id text`-PK helper via `drift_guard.py`

### Negative

- Any legitimate id change requires updating the derivation callable and every call-site in the same commit
- A CI configuration that skips importing the affected modules would not catch drift; mitigation is that the `test_load_*.py` files import their adapters at top level, so pytest collection fires the import-time assert before any test runs
- The construction-time assert adds three lines to each of four instrumented build functions in `load_seasons_and_licenses.py` (two DEA + two bear)

### Neutral

- The three affected SQL constants in `db.py` remain unchanged; future readers debugging drift look at `drift_guard.py` and the adapter files, not `db.py`
- Q19 should be marked RESOLVED in a separate PM commit after this ADR flips to Accepted; the local `_assert_dispatch_dict_drift_free` in `load_reporting_obligations.py` is superseded by the shared primitive

## Links

- [Q19 in `docs/open-questions.md`](../open-questions.md) — originating risk analysis
- [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md) — state-agnostic-clean discipline placing the helper in `ingestion/ingestion/lib/`
- [ADR-010](ADR-010-decomposed-entity-model.md) — entity model introducing the entities Q19 protects
- [ADR-019](ADR-019-doc-type-precedence-multi-source-merge.md) — prior fail-loud pattern
- [`ingestion/ingestion/lib/drift_guard.py`](../../ingestion/ingestion/lib/drift_guard.py) — shared helper
- [`ingestion/states/montana/load_reporting_obligations.py`](../../ingestion/states/montana/load_reporting_obligations.py) — dispatch-dict surface (S03.9 seed)
- [`ingestion/states/montana/load_seasons_and_licenses.py`](../../ingestion/states/montana/load_seasons_and_licenses.py) — 4 instrumented build functions
