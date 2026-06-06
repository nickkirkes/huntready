# Epic Audit: E05 Colorado Geometry Ingestion

**Date:** 2026-06-06
**Auditor:** `/roughly:audit-epic` independent re-run (Claude, 9 parallel per-story review agents + cross-cutting synthesis)
**Epic file:** [`E05-colorado-geometry-ingestion.md`](../E05-colorado-geometry-ingestion.md)
**Audit scope:** static, post-implementation review. Reads files + git history only; runs no SQL, no pytest, no operator-side verification.

> **Supersedes** the at-merge audit produced in S05.7's PR (#62 / `83e4c32`, dated 2026-06-05). This is an independently-dispatched re-run requested 2026-06-06: each story was re-reviewed by a dedicated agent that read the implementing files and verified the epic's claims against the actual source rather than trusting the prior report. **Conclusion is unchanged — E05 ships clean, 0 NOT MET — and several additional non-blocking quality observations are recorded below.**

**Stories audited:** 9 (S05.0, S05.1, S05.2, S05.3, S05.3.5, S05.4, S05.5, S05.6, S05.7)

**Acceptance criteria tally (checkbox-based across all story AC sections):**

| Classification | Count |
|---|---|
| MET (Group A static / at-merge) | ~85 |
| PARTIAL (Group B operator-pending live verification) | ~29 |
| NOT MET | 0 |

*Counting method: `[x]` = MET, `[ ]` = operator-pending/PARTIAL, counted across each story's AC section. S05.3's 10 checkboxes are ticked-as-dispositioned: ~4 are genuinely MET (investigation report, gap resolution, Path-3 ADR-001 rejection, Q18 surface) and ~6 are N/A-by-gap (zero CWD rows = no ingestion ACs to satisfy); they are counted in the MET column as "dispositioned." Exit Criteria and narrative bullets are not in the tally. The prior at-merge audit reported ~80 MET / ~43 PARTIAL; the delta vs this run's ~85 / ~29 is purely a counting-boundary difference (treatment of S05.3 N/A items and the S05.7 Group-A/Group-B split), not a substantive disagreement — both runs agree on 0 NOT MET and on which ACs are operator-pending.*

---

## Summary

E05 ships clean. All nine stories closed at-merge in the correct sequence; the final story (S05.7) produced the runbook, working note, and the audit gate in the same PR. Every Group A (static, file-level) AC is satisfied on direct inspection across all nine stories. The ~29 PARTIAL ACs are Group B operator-driven live-verification steps — the same structural posture E02 adopted for its UAT ACs in S02.6/S02.7. **No Group A AC is NOT MET; no blocking findings surfaced.**

The independent re-run confirmed the load-bearing claims the epic makes about itself:
- **State-adapter isolation held.** `git show --stat <sha> -- ingestion/ingestion/lib/` is empty for S05.1, S05.2, and S05.4. The only `lib/` edit in all of E05 is S05.5's deliberate state-agnostic-clean extension of `overlays.py` (adding `"gmu"` + `ROLE_FOR_BINDING_BY_CHILD_KIND`), which preserves the MT-facing `ROLE_FOR_E03_BY_CHILD_KIND` alias by same-object assignment.
- **The S05.3.5 five-place sync is genuinely consistent.** All five surfaces (DDL migration, `schema.py`, `overlays.py`, `schema.ts`, `architecture.md`) carry the identical 8 role values in identical order; the 3 MT reclassified `geometry_id`s match ADR-021 exactly; migration timestamp `20260603000000` > S04.1's `20260530132727`.
- **The S05.4 outcome-(c) guards are real.** Count-band is exact `(10, 10)`; `_V1_EXPECTED_IDS` is wired as a runtime set-equality guard in `main()` (not merely a module-load length assert); Curecanti is dropped before fixture/manifest writes so all counts agree at 10.
- **The S05.7 runbook's FK-cascade wipe is correct.** It sequences `DELETE FROM jurisdiction_binding WHERE geometry_id IN (SELECT id FROM geometry WHERE state = 'US-CO')` before the geometry delete, and uses the `geometry_id IN (...)` subquery form — NOT a nonexistent `state` column on `jurisdiction_binding` (a bug the prior PR-review cycle caught and fixed). An explicit anti-`TRUNCATE` guard is present.

**Colorado V1 geometry layer composition (at S05.7 close):**
- 1 statewide anchor (`CO-STATEWIDE-geom`, S05.0 — `kind='state'`, US Census TIGER 2024, SHA-256 pinned)
- ~186 GMUs (`kind='gmu'`, S05.2 — CPW FeatureServer layer 6, `GMUID`-keyed ids, count-band `[167, 205]`)
- **0 CWD zones** (S05.3 — documented gap: CPW publishes no CWD-zone geometry; manages CWD by hunt code/GMU per USGS unit-keyed reporting; investigation report at `ingestion/states/colorado/cwd-source-discovery.md`)
- **10 restricted areas** (`kind='restricted_area'`, S05.4 — 4 NPs + 5 NMs + 1 DOD/AFA from USGS PAD-US 4.1; Curecanti NRA dropped per 36 CFR §2.2; count-band exact `(10, 10)`)

**Test-baseline trajectory (all additive, no regressions):** 1166 (E04 close) → 1184 (S05.0, +18) → 1187 (S05.1, +3) → 1234 (S05.2, +47) → 1234 (S05.3, +0) → 1234 (S05.3.5, +0) → 1283 (S05.4, +49) → 1331 (S05.5, +48) → 1340 (S05.6, +9) → 1340 (S05.7, +0).

**Merge order verified (git log):** S05.0 (#54 `7f3b071`) → S05.1 (#55 `ba6ef1c`) → S05.2 (#56 `d7ba731`) → S05.3 (#57 `9fd5c61`) → S05.3.5 (#58 `3344971`) → S05.4 (#59 `dc9d5b2`) → S05.5 (#60 `e7ba3d4`) → S05.6 (#61 `1b55bfd`) → S05.7 (#62 `83e4c32`).

---

## Per-Story Results

### S05.0: Schema preparation — write `CO-STATEWIDE-geom`
**✅ 8/8 Group A MET · ⚠️ 2 Group B PARTIAL**

`load_state_boundary.py` (326 LOC) + 18 tests confirmed on disk. TIGER 2024 source locked with SHA-256 `ad00cbe6…` pinned; `id='co-census-tiger-state-2024'`, `kind='state'`, `state='US-CO'`, `license_year=NULL`, `publication_date='2026-01-01'`, `document_type='gis_layer'` all verified in code + tests. The Stage-4 load-bearing `gdf = gdf.to_crs(4326)` reassignment fix is present (`:202`) with its load-bearing comment; non-MultiPolygon-post-`make_valid` raises; `_verify_sha256` fails loud with both digests. **Group B (operator-pending):** post-write verification queries; `area_km2` within 1% of ~269,837 km².

**Finding (non-blocking, P3):** three fail-loud guards are implemented but **untested** — multiple `.shp` in the TIGER ZIP (`:179-185`), NULL geometry on the CO row (`:219-225`), missing `STATEFP` column (`:190-197`). All three are unreachable with the pinned TIGER file, so low operational risk, but they are a test-contract gap relative to the project's fail-loud discipline.

### S05.1: CPW ArcGIS fetch infrastructure + Colorado adapter scaffold
**✅ 8/8 MET**

All 5 scaffold files confirmed: `__init__.py` (byte-identical to S05.0), `README.md` (113 LOC, 8 h2 sections), `sources.yaml` (1 `gis_layers:` entry at merge with anti-direct-read comment on `id_template`), `fixtures/.gitignore` (17 LOC), and `TestNoColoradoLeakIntoSharedLib` appended to `test_arcgis.py` (walks `lib/` via `rglob`, scans `colorado` + 3 CPW host literals, class-body lowercase invariant + per-method non-empty guards). **`git show --stat ba6ef1c -- ingestion/ingestion/lib/` is empty — zero lib edits confirmed.** The PM-approved spec deviations (codebase-actual import form; `CO_STATE_CODE` documented with S05.6 forward-reference) are present. No gaps.

### S05.2: GMU ingestion
**✅ Group A MET · ⚠️ 4 Group B PARTIAL**

`load_gmus.py` (409 LOC) + 47 tests (confirmed by `grep -c def test_`). `id` derived from `GMUID` not `OBJECTID` (regression test asserts `GMUID=201` tracked and `OBJECTID=999` never leaks); `kind='gmu'`; count-band `[167,205]` and `_duplicate_ids` both fire before `db.connect()`; `license_year=None` on row, `SourceCitation.license_year=2026` → `publication_date='2026-01-01'`; citation id `co-cpw-arcgis-CPWAdminData-6-2026` case-preserved (derive-and-assert); AC #235 EDIT_DATE/INPUT_DATE LOG-ONLY; `multipart-gmus.json` schema with deliberate `total_area_sq_km=None`; no `--service-url`. **Group B (operator-pending):** `ST_IsValid` round-trip; UPSERT idempotency; metadata + manifest fixture commits.

**Findings (non-blocking):**
- **P2 / consistency:** `_feature_to_geometry` uses a raw `feature["properties"]` subscript (`:152`) — a malformed/null-`properties` feature yields a bare `KeyError` instead of `ColoradoGeometryError`. **The identical pattern was fixed in S05.4** (`load_restricted_areas.py`), so `load_gmus.py` now carries known, already-diagnosed tech debt. This is the M2-hygiene-item-#3 candidate; should be folded into the hygiene sweep.
- **P3:** no `caplog` test locks the AC #235 INFO emission (correctness is enforced structurally by `extra="forbid"`, but an explicit emission assertion would complete coverage).

### S05.3: CWD zone discovery (documented gap)
**✅ MET (gap rigorously substantiated) · N/A-by-gap items dispositioned**

The gap closure is substantive, not paperwork. `cwd-source-discovery.md` (135 LOC) documents all 3 paths with distinct live evidence: a full 30-row CPWAdminData catalog table (Path 1), two org-scoped query URLs with result counts (Path 2), and regulatory-document citations with page numbers (Path 3). Path-3 hand-trace rejection is grounded explicitly in ADR-001. `git show --stat 9fd5c61` shows exactly one file added (the report) — no `load_cwd_zones.py`, no `sources.yaml` CWD entry, zero geometry rows. Q18 has a dated 2026-06-03 empirical-trigger breadcrumb in `open-questions.md` with status correctly left Open (the formal decision is E06's).

**Finding (cosmetic):** `sources.yaml` still carries an S05.1 scaffold comment promising a CWD entry that (correctly) never materialized — a stale placeholder a reader could briefly trip over. Harmless; the AC is unambiguously met.

### S05.3.5: `jurisdiction_binding.role` migration + MT V1 reclassification (ADR-021)
**✅ 12/12 Group A MET · ⚠️ 5 Group B PARTIAL**

The five-place sync is verified byte-consistent — all five surfaces carry `primary_unit, portion, restricted_area, cwd_management_zone, bear_management_unit, block_management_area, other_overlay, no_hunt_zone` in identical order (count = 8, no mismatches). Migration is transactional in the required order (DROP CHECK → ADD 8-value CHECK → UPDATE), keys the UPDATE on `geometry_id` (not binding `id`) to catch fan-out rows, and targets exactly the 3 MT ids ADR-021 names. The 6th sync surface caught at Stage-2 discovery (the `cast(Literal[…], role_e03)` in `_build_overlay_bindings`) is extended to 8 values. ADR-021 flipped Proposed → Accepted and is now in the `adrs/README.md` index. `_VALID_ROLE_FOR_E03` deliberately NOT widened (logged as E06 Known Issue #6). `git show --stat 3344971 -- ingestion/states/colorado/` empty. **Group B (operator-pending):** `supabase db push`; `information_schema.check_constraints` 8-value shape; `SELECT DISTINCT role` subset; 3 MT rows read `no_hunt_zone`; row count unchanged. No gaps.

### S05.4: Restricted-area / no-hunt-zone overlay discovery + ingestion
**✅ 11/11 Group A MET · ⚠️ 4 Group B PARTIAL**

`load_restricted_areas.py` (545 LOC) + 49 tests. Research-doc prerequisite confirmed present. Count-band exact `(10, 10)`; `_V1_EXPECTED_IDS` wired as a runtime set-equality guard in `main()` (the Stage-6 C1 Critical) AND a module-load length assert; Curecanti dropped before fixture/manifest writes (the C2 Critical) so all counts agree at 10; `_feature_to_geometry` guards null/malformed properties → `ColoradoGeometryError` (post-merge `2715bb9`). Single shared citation `co-usgs-padus-arcgis-Federal_Fee_Managers_Authoritative_PADUS-0-2026` derive-and-asserted; `verbatim_rule=None` (PM deferral, no fabricated text); boundary-to-boundary `ST_DWithin(...,5000)` predicate + 10-id orphan allowlist seeded in the discovery doc for S05.5. `git show --stat dc9d5b2 -- ingestion/ingestion/lib/` empty; no `db.py` edits. **Group B (operator-pending):** live fetch 11→10; `returnCountOnly` cross-check; `ST_IsValid`; `GIS_Acres` ±10%; fixture+manifest commits. No gaps — strongest-executed loader in the epic.

### S05.5: `geometry-overlays.json` fixture build
**✅ 9/9 Group A MET · ⚠️ 6 Group B PARTIAL**

`build_overlay_fixture.py` (404 LOC) + 46–48 tests. Bulk `SELECT … ST_AsText(geom) … WHERE state = %s` geography-native (no `::geometry` cast); three-band discriminator carried forward; `EXPECTED_CO_RA_ORPHAN_IDS` frozenset of 10 with `assert len()==10` (byte-identical to S05.4's `_V1_EXPECTED_IDS`); coverage invariant enforced (gmu self-row=`primary_unit`; cwd_zone vacuously satisfied; RA child OR allowlisted OR fail-loud); the W1 absence-of-log `caplog` lock present; no statewide rows pre-emitted; `_JURISDICTION_BINDING_ID_FORMAT` contract documented. Library extension verified state-agnostic-clean with the deprecated-alias identity preserved. **Group B (operator-pending):** the live `geometry-overlays.json` + `-dropped.json` cannot be generated at-merge because the geometry rows they read are themselves Group B writes; threshold recalibration check; UAT spot-check; FK + byte-reproducibility checks.

**Findings (non-blocking):**
- **P3 / doc-rot:** `OverlayFixtureRow.parent_geometry_id` docstring (`overlays.py:~102`) still says "always a hunting district in V1" — stale now that `gmu` is a valid parent kind. The sibling docstrings were refreshed (I1 fix) but this line was missed.
- **P3:** one threshold test (`test_zero_area_child_kept_as_intersects`) uses a conditional `if kept:` assertion that passes silently if the collection is empty — a slightly weakened lock (likely intentional for the degenerate-geometry defensive case).
- **Minor:** spec claims +48 tests; an independent method count came to ~46. Cosmetic; baseline (1331) is what matters and is consistent elsewhere.

### S05.6: Cross-state spatial discipline + binding-loader reference
**✅ 9/9 MET**

Scaffold-only. `load_jurisdiction_bindings.py` (106 LOC, import-only — no `main()`, no `db.connect()`, no argparse, no network). `_STATE: Final[str] = "US-CO"`; `_NO_HUNT_ZONE_NEARBY_DISTANCE_M = 5000`; module-level `_QUERY_NEARBY_GMUS_FOR_ZONE_SQL` with `WHERE gmu.state = %s`, `AND gmu.kind = 'gmu'`, `extensions.ST_DWithin(%s::geography, gmu.geom, %s)` (distance `%s`-bound, not hardcoded), `ORDER BY gmu.id`. The headline pollution-guard test asserts `'US-MT'` absent; a runtime-binding test additionally locks `params[0] == "US-CO"`. No gaps. No bare `ST_*` calls.

### S05.7: Spatial query verification + epic exit
**✅ 5 MET · ⚠️ 7 Group B PARTIAL**

Runbook (387 LOC) confirmed. All executable `ST_*` calls are `extensions.`-prefixed; every spatial query carries `AND state = 'US-CO'`; Section 5 is the CO-bounds `ST_Envelope` check against `[-109.06, -102.04] × [36.99, 41.00]` (exact); the reproducibility/wipe section sequences the `jurisdiction_binding` delete via the `geometry_id IN (...)` subquery before the geometry delete, with an explicit anti-`TRUNCATE` guard. PRD 002 SC#4/#6/#7 mapped inline. `E05-audit.md` exists and the epic `Audited:` field is populated (the `/plan-next-epic` gate). **Group B (operator-pending, Option A):** `spatial-test-points.json` is deliberately NOT committed at-merge (generated from live `ST_PointOnSurface` so points are real, not invented) — confirmed absent via `git show --stat 83e4c32 -- …/fixtures/`; the 7 live spatial-query steps are operator-driven.

**Finding (cosmetic, P3):** one `ST_PointOnSurface` mention at runbook `:75` lacks the `extensions.` prefix — but it sits inside a JSON `"notes"` string value, not executable SQL. Technically inconsistent with the runbook's stated discipline; functionally irrelevant.

---

## Cross-Cutting Findings

**1. Consistency — strong, with one named naming-drift.** Every CO loader follows the established adapter shape (pure helpers → guards fire pre-`db.connect()` → `with db.connect()` + explicit commit), honors the no-`--service-url` silent-lie precedent, and keeps `ingestion/ingestion/lib/` untouched (the sole exception being S05.5's sanctioned state-agnostic `overlays.py` extension). The one real inconsistency is the **`_STATE` (S05.6) vs `CO_STATE_CODE` (S05.0–S05.5) constant-name split** — confirmed by direct inspection in both this run's S05.5 and S05.6 reviews. It is already logged as an E06 cleanup candidate and was deliberately not retrofitted in S05.6's scaffold-only scope. No functional impact (both equal `"US-CO"`).

**2. Integration — clean handoffs.** S05.4 → S05.5: the 10-id orphan set is byte-identical between `load_restricted_areas.py._V1_EXPECTED_IDS` and `build_overlay_fixture.py.EXPECTED_CO_RA_ORPHAN_IDS`. S05.3.5 → S05.4: the `no_hunt_zone` enum (5-place-synced) is the schema precondition S05.4's outcome (c) relies on (S05.4 writes geometry only; the role assignment is E06's). S05.5 → E06 and S05.6 → E06: the overlay fixture, the `_JURISDICTION_BINDING_ID_FORMAT` import contract, and the cross-state reference SQL are all staged for E06's binding loader. No integration mismatch found.

**3. Gaps — the entire live-write/verification chain is operator-pending (by design, but standing).** ~29 PARTIAL ACs span S05.0, S05.2, S05.3.5, S05.4, S05.5, and S05.7. The practical consequence: **no E05 geometry has yet been written to or verified against the production database, and no overlay fixture / spatial-test-points fixture exists on disk.** This is the intended Group A/Group B split (mirrors E02's UAT posture) and is correctly non-blocking for story/epic closure — but it is the single largest standing risk for E06, which FK-depends on those live rows + the live-generated overlay fixture. The batched operator live-write session (`load_state_boundary` → `load_gmus` → `load_restricted_areas` → `build_overlay_fixture` → generate `spatial-test-points.json` → run the 7 verification steps) is the hard precondition before E06's binding loader can run, and should be sequenced before/with E06.

**4. Regressions — none.** Test baseline is monotonically additive (1166 → 1340). S05.3.5 is the only story that touched MT code + MT V1 production data; it carries N=0 test delta (rewrites only) and the MT role-enum tests were re-pointed to the 8-value set. The MT `load_jurisdiction_bindings.py` reclassification keeps binding-`id` slugs encoding `other_overlay` while `role` becomes `no_hunt_zone` — verified inert (no code parses `role` from `id`; UPSERT omits `role` from `ON CONFLICT SET`).

---

## Recommendations

Priority order. None block E05 closure; E05 is correctly Complete + Audited.

1. **(Operator, gating for E06)** Run the batched Group B live-write + verification session and capture results in the `E05-confidence-findings/S05.*.md` working notes, then tick the Group B ACs + S05.3.5's CHECK-constraint verification in a follow-up doc-only commit. This is the hard FK precondition for E06's binding loader.
2. **(Hygiene sweep, P2)** Fix `load_gmus.py`'s raw `feature["properties"]` subscript (`:152`) to the guarded form S05.4 already uses — the diagnosed-but-unfixed instance is the clearest consistency drift in the epic. Bundle with the two carried S05.0 candidates (`db.upsert_geometry` rowcount==0 guard; MT `load_state_boundary.py --service-url` removal) and Known Issue #7 (narrow overlay-builder shared-lib extraction) into one post-E05 hygiene PR.
3. **(P3, test-contract)** Add the three missing S05.0 fail-loud guard tests (multiple `.shp`, NULL geometry, missing `STATEFP`) and a `caplog` lock for S05.2's AC #235 INFO emission, to bring guard coverage in line with the project's fail-loud discipline.
4. **(P3, doc-rot)** Refresh the stale `OverlayFixtureRow.parent_geometry_id` docstring in `overlays.py` ("always a hunting district in V1" → now also `gmu`); remove the stale CWD placeholder comment in `colorado/sources.yaml`; prefix the `ST_PointOnSurface` mention in the runbook's JSON `notes` string (or rephrase to prose) for runbook-discipline consistency.
5. **(E06 decision, tracked)** Resolve Known Issue #6 (`_VALID_ROLE_FOR_E03` subset-gate vs CO no-hunt-zone path) before E06's binding-loader spec drafts; carry the `_STATE`/`CO_STATE_CODE` unification into E06's CO-loader cleanup.

---

*HuntReady · E05 audit · M2 — Colorado Ingestion · independent re-run 2026-06-06 · verdict: ships clean, 0 NOT MET, 0 blocking findings.*
