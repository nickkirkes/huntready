# ADR-020: Derive-and-Assert for id text-PK Slug Drift

**Date:** 2026-05
**Status:** Proposed
**Decider:** Nick Kirkes
**Tags:** ingestion, storage

---

## Context

Three `id text`-PK UPSERT helpers in `ingestion/ingestion/lib/db.py` allow the DO UPDATE clause to rewrite slug-encoded fields on conflict: `_UPSERT_SEASON_DEFINITION_SQL`, `_UPSERT_LICENSE_TAG_SQL`, and `_UPSERT_REPORTING_OBLIGATION_SQL`. The slug-encoded fields differ across helpers: `reporting_obligation` encodes `kind`, `deadline_hours`, and `region_scope`; `season_definition` encodes `species`, `hd_number`, `season_key`, and `license_year`; `license_tag` encodes `species`, `hd_number`, `license_code`, and `license_year`. This ADR is the canonical reference for which fields are drift-vulnerable; the Q19 framing in `docs/open-questions.md` is imprecise on this point.

The risk is silent: a spec edit that changes one slug-encoded field without updating the id constructor causes the same `id` to UPSERT cleanly with shifted row identity. Link-table rows already pointing at that `id` (`license_season`, `regulation_season`, `regulation_license`, `regulation_reporting`) then reference an entity whose meaning has changed, with no error at write time.

S03.9 cubic-review round 3 surfaced the risk and shipped a local `_assert_dispatch_dict_drift_free` in `load_reporting_obligations.py` as belt-and-suspenders. That local pattern is the seed template. The S03.7 surface differs: id constructors are per-row callables inside four build functions, so the assert surface is at row-construction time rather than module load. `db.upsert_jurisdiction_binding` (S03.6.1) excludes identity fields from UPDATE entirely — Q19 does not apply.

## Decision

For every `id text`-PK entity helper whose UPSERT ON CONFLICT DO UPDATE clause can rewrite slug-encoded fields, the id derivation is encoded as a pure callable, and an assertion verifies that every stored or constructed entity's id matches its derivation. The assertion fires at module load for compile-time dispatch dicts and at row-construction time for runtime-built entities — drift becomes impossible by construction.

## Reasoning

The failure mode is silent: a UPSERT cannot detect that a slug was minted from field values that have since changed. The conflict clause sees matching `id` values and applies DO UPDATE without inspecting the semantic relationship. The first symptom is a year-over-year re-ingestion producing rows whose structured fields disagree with ids that link-table rows already reference — a non-trivial repair at the start of a season cycle.

The derive-and-assert pattern closes the gap by making the id a function of the slug-encoded fields rather than a separately maintained string. The assertion lives at the adapter layer (not the SQL layer) and fires on every CI run before any database connection is opened. A future contributor who manually constructs an id string at a new call site, bypassing the pure constructor, trips the assert as soon as the structured fields disagree.

Two assert surfaces are necessary because the dispatch-dict case (S03.9 `_REPORTING_ROW_SPEC`) and the construction-time case (S03.7 build functions) have different shapes. The dispatch-dict form fires once at module load; the construction-time form fires per entity before append. A unified API would force an awkward shape onto one case without adding safety. The shared `drift_guard.py` module exposes `assert_dispatch_dict_drift_free` and `assert_id_matches`; adapter authors choose based on their surface.

## Alternatives Considered

**Option B — Remove slug-encoded fields from the UPDATE clause.** Prevents the silent-update path by forcing a new `id` via INSERT on any slug-field change, but leaves the old row and all its link-table references orphaned. Trades semantic-drift risk for orphan-link risk. Rejected.

**Option C — Drop UPSERT; require TRUNCATE before re-runs.** Mandates a clean slate before each re-ingestion, eliminating the conflict clause entirely. Loses the "re-run without disruption" property that S03.6/S03.7/S03.8 explicitly cultivated. Rejected.

## Consequences

### Positive

- Drift is caught at import or build time in CI, not at year-over-year re-ingestion against production
- Operator-facing errors name the offending key plus stored vs. derived id, making the fix path obvious
- Generalizes to any future `id text`-PK helper via `drift_guard.py`

### Negative

- Any legitimate id change (adding a slug component) requires updating the derivation callable and every call-site in the same commit
- A CI configuration that skips importing the affected modules would not catch drift; mitigation is that `test_load_*.py` files import all adapter modules transitively
- The construction-time assert adds three boilerplate lines per build call-site; four call-sites in `load_seasons_and_licenses.py` pay this cost

### Neutral

- The three affected SQL constants in `db.py` remain unchanged; future readers debugging drift look at `drift_guard.py` and the adapter files, not `db.py`
- `drift_guard.py` exposes two primitives; M2 adapter authors choose compile-time or runtime form based on their dispatch surface
- Q19 should be marked RESOLVED in a separate PM commit after this ADR flips to Accepted; the local `_assert_dispatch_dict_drift_free` in `load_reporting_obligations.py` is superseded by the shared primitive

## Links

- [Q19 in `docs/open-questions.md`](../open-questions.md) — the originating risk analysis; to be marked RESOLVED in a separate PM commit AFTER this ADR's status flips to Accepted
- [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md) — state-agnostic-clean discipline that places the shared helper in `ingestion/ingestion/lib/`
- [ADR-010](ADR-010-decomposed-entity-model.md) — decomposed entity model that introduces the entities Q19 protects
- [ADR-019](ADR-019-doc-type-precedence-multi-source-merge.md) — most recent ADR with a fail-loud architectural pattern; style reference
- [`ingestion/ingestion/lib/drift_guard.py`](../../ingestion/ingestion/lib/drift_guard.py) — the shared helper module
- [`ingestion/states/montana/load_reporting_obligations.py`](../../ingestion/states/montana/load_reporting_obligations.py) — dispatch-dict surface (S03.9 seed template)
- [`ingestion/states/montana/load_seasons_and_licenses.py`](../../ingestion/states/montana/load_seasons_and_licenses.py) — 4 construction-time surfaces
