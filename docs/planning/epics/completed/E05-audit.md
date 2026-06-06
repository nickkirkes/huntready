# Epic Audit: E05 Colorado Geometry Ingestion

**Date:** 2026-06-05
**Auditor:** roughly:build static review (Claude)
**Epic file:** [`E05-colorado-geometry-ingestion.md`](../E05-colorado-geometry-ingestion.md)
**Audit scope:** static, post-implementation review. Reads files and git history only; runs no SQL, no pytest, no operator-side verification.

**Stories audited:** 9 (S05.0, S05.1, S05.2, S05.3, S05.3.5, S05.4, S05.5, S05.6, S05.7)

**Acceptance criteria tally:**

| Classification | Count |
|---|---|
| MET (Group A static / at-merge) | ~80 |
| PARTIAL (Group B operator-pending live verification) | ~43 |
| NOT MET | 0 |

*Counting method: direct checkbox count across all story AC sections in the epic file (`[x]` = MET, `[ ]` = operator-pending/PARTIAL). Exit Criteria and story-level narrative bullets not included in the tally. Group B PARTIAL classification mirrors E02-audit's treatment of UAT ACs — operator-driven live verification cannot be self-evidenced statically and is by design.*

*Note: S05.7 closes in this same PR. Its Group A deliverables (this audit, the runbook `docs/runbooks/E05-colorado-geometry-verification.md`, the working note `docs/planning/epics/E05-confidence-findings/S05.7.md`, and the epic Status/`Audited:` updates) land at-merge and are counted MET; its live-verification ACs (the `spatial-test-points.json` fixture and the 7 spatial-query steps) are Group B operator-pending and counted PARTIAL — identical posture to S05.0/S05.2/S05.4/S05.5.*

---

## Summary

E05 ships clean. All nine stories are closed at-merge (S05.7 — the final story — closes in this same PR, the one that also produces this audit). Every Group A (static, file-level) AC across all nine stories is satisfied on direct inspection. The ~43 PARTIAL ACs are operator-driven Group B live verification steps — the exact same structural posture E02 adopted for its UAT ACs in S02.6/S02.7. No blocking findings surfaced; no Group A ACs are NOT MET.

**Colorado V1 geometry layer composition at S05.6 close:**
- 1 statewide anchor (`CO-STATEWIDE-geom`, S05.0 — `kind='state'`, US Census TIGER 2024, SHA-256 pinned)
- ~186 GMUs (`kind='gmu'`, S05.2 — CPW FeatureServer layer 6, `GMUID`-keyed ids, count-band guard `[167, 205]`)
- **0 CWD zones** (S05.3 — documented gap: CPW publishes no CWD-zone geometry; manages CWD by hunt code/GMU per USGS unit-keyed reporting; investigation report at `ingestion/states/colorado/cwd-source-discovery.md`)
- **10 restricted areas** (`kind='restricted_area'`, S05.4 — 4 NPs + 5 NMs + 1 DOD/AFA from USGS PAD-US 4.1, Curecanti NRA dropped per 36 CFR §2.2, count-band guard exact `(10, 10)`)

**Library and schema hygiene:**
- S05.5 shipped a state-agnostic-clean `ingestion/ingestion/lib/overlays.py` extension (`OverlayParentKind` + `OverlayChildKind` + `ROLE_FOR_BINDING_BY_CHILD_KIND`; `ROLE_FOR_E03_BY_CHILD_KIND` retained as deprecated alias for MT compat); `OverlayFixtureRow.role_for_e03` field name preserved for MT fixture-data compatibility.
- S05.3.5 shipped ADR-021 end-to-end: 8th `no_hunt_zone` role enum value via 5-place sync (DDL migration `20260603000000_jurisdiction_binding_no_hunt_zone_role.sql` + Pydantic + TypeScript + `architecture.md` + `overlays.py`); 3 MT V1 bindings reclassified `other_overlay` → `no_hunt_zone`.
- `TestNoColoradoLeakIntoSharedLib` (S05.1) locks ADR-005 isolation: `git diff --stat ingestion/ingestion/lib/` empty across all CO loader PRs.
- **Test-baseline trajectory:** 1166 (E04 close) → 1184 (S05.0, +18) → 1187 (S05.1, +3) → 1234 (S05.2, +47) → 1234 (S05.3, +0) → 1234 (S05.3.5, +0) → 1283 (S05.4, +49) → 1331 (S05.5, +48) → 1340 (S05.6, +9). All shifts are deliberate quality additions; no regressions.
- **Merge order verified (git log):** S05.0 (#54 `7f3b071`) → S05.1 (#55 `ba6ef1c`) → S05.2 (#56 `d7ba731`) → S05.3 (#57 `9fd5c61`) → S05.3.5 (#58 `3344971`) → S05.4 (#59 `dc9d5b2`) → S05.5 (#60 `e7ba3d4`) → S05.6 (#61 `1b55bfd`) — all squash-merged in the correct sequence.

---

## Per-Story Results

### S05.0: Schema preparation — write `CO-STATEWIDE-geom`

**Status:** ✅ 7/9 MET, ⚠️ 2 PARTIAL (Group B — operator-pending live verification)

PR #54 / `7f3b071` from `feat/S05.0-write-co-statewide-geom-row`. New loader `ingestion/states/colorado/load_state_boundary.py` (326 LOC) + 18 tests at `ingestion/tests/test_load_co_state_boundary.py` verified on file system. Source locked to US Census TIGER 2024 (`https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip`, SHA-256 pinned, `SourceCitation.id='co-census-tiger-state-2024'`). Stage-4 Blocker (bare `gdf.to_crs(4326)` → ~100m NAD83-as-WGS84 offset) caught and fixed with explicit reassignment; 9 fail-loud guards including `_verify_sha256`, non-MultiPolygon post-`make_valid`, and 7 structural guards. No `kind='state'` schema change needed (already valid from S03.0). Test baseline shifted 1166 → 1184.

**Partials (Group B — by design):**
- AC #7: Post-write verification queries against live Supabase — operator-pending.
- AC #8: `area_km2` within 1% of ~269,837 km² — operator-pending (requires live DB write).

### S05.1: CPW ArcGIS fetch infrastructure + Colorado adapter scaffold

**Status:** ✅ 8/8 MET

PR #55 / `ba6ef1c` from `feat/S05.1-cpw-arcgis-fetch-infra`. Scaffold-only story — all 5 deliverable files confirmed on disk: `ingestion/states/colorado/__init__.py` (unchanged), `README.md` (113 LOC, 8 h2 sections), `sources.yaml` (35 LOC, `gis_layers:` top-level key, anti-direct-read inline comment on `id_template`), `fixtures/.gitignore` (17 LOC, confirmed at `ingestion/states/colorado/fixtures/.gitignore`), and `TestNoColoradoLeakIntoSharedLib` appended to `ingestion/tests/test_arcgis.py` (+95 insertions; walks `ingestion/ingestion/lib/` via `rglob("*.py")`; scans for `colorado` case-insensitive + 3 CPW host literals). No Group A/B split — scaffold only, no live verification required. Stage-6 mid-cubic-fix (`-> list[Path]` hoisted to module-level per PEP 563/ruff F821) + one rejected post-merge finding (class-body `assert all(...)` empirically valid). PM-approved spec deviations documented: import path codebase-actual form; `CO_STATE_CODE` vs `_STATE` naming with S05.6 forward-reference. Test baseline shifted 1184 → 1187.

### S05.2: GMU ingestion

**Status:** ✅ 11/15 MET, ⚠️ 4 PARTIAL (Group B — operator-pending live verification)

PR #56 / `d7ba731` from `feat/S05.2-GMU-ingestion`. Loader `ingestion/states/colorado/load_gmus.py` (409 LOC) + 47 tests in `ingestion/tests/test_load_gmus.py` (733 LOC) confirmed on disk. Key correctness decisions locked by tests: `test_geometry_id_derived_from_gmuid_not_objectid` prevents `OBJECTID` leak; `test_main_no_commit_on_count_band_guard` + `test_main_no_commit_on_duplicate_id_guard` lock OQ7 pre-`db.connect()` ordering; `test_no_other_state_adapter_imports` broadens ADR-005 isolation guard beyond MT. Stage-6 Critical (`kind='hunting_district'` docstring corrected; was never wrong in code) and `_collect_multipart_gmus` wrapped in fail-loud try/except. AC #235 (CPW `EDIT_DATE`/`INPUT_DATE`) satisfied as LOG-ONLY per documented deviation footnote — genuine schema constraint (`SourceCitation` frozen with `extra="forbid"`). Test baseline shifted 1187 → 1234.

**Partials (Group B — by design):**
- `ST_IsValid` round-trip verification on all rows — operator-pending.
- UPSERT idempotency confirmation (two live runs) — operator-pending.
- Layer metadata fixture committed — operator-pending (live fetch artifact).
- Per-fetch manifest committed — operator-pending (live fetch artifact).

### S05.3: CWD zone discovery + ingestion

**Status:** ✅ 9/9 MET (all ACs dispositioned; gap-branch is a valid first-class closure)

PR #57 / `9fd5c61` from `feat/S05.3-cwd-zone-discovery`. Documented-gap outcome: zero `geometry` rows written; no loader created; `sources.yaml` not extended. Investigation report at `ingestion/states/colorado/cwd-source-discovery.md` (confirmed on disk) documents all 3 investigation paths: Path 1 (30-layer CPWAdminData catalog, no CWD match), Path 2 (~200-service CPW org listing, no CWD zone layer), Path 3 (PDF hand-trace rejected per ADR-001 — CO manages CWD by hunt code/GMU, not mapped polygon). Q18 empirical trigger fired and breadcrumb dated in `docs/open-questions.md`. Test suite unchanged at 1234 + 2 skipped (correct — no code written). Stage-6 review independently re-ran live ArcGIS probes confirming report byte-accurate. Ingestion-shaped ACs are N/A-by-gap and labeled inline; all investigation + Q18 ACs are fully MET.

### S05.3.5: `jurisdiction_binding.role` migration + MT V1 reclassification (ADR-021)

**Status:** ✅ 12/17 MET, ⚠️ 5 PARTIAL (Group B — operator-pending post-`supabase db push`)

PR #58 / `3344971` from `feat/S05.3.5-no-hunt-zone-role`. Migration `supabase/migrations/20260603000000_jurisdiction_binding_no_hunt_zone_role.sql` confirmed on disk. All 5 sync surfaces verified: DDL (DROP + ADD 8-value CHECK + UPDATE 3 MT rows); `schema.py` `JurisdictionBinding.role` Literal (8 values); `schema.ts` `GeometryRole` union; `architecture.md` §"Schema types"; `overlays.py` `GeometryRoleForE03` alias. Spec gap closed at Stage-2 discovery: the `cast(Literal[…], role_e03)` 6th consumer in `_build_overlay_bindings` was absent from the spec's 5-site list — caught and folded into T5. MT test rewrites (4 sites, 0 delta) preserve 1234 + 2 skipped baseline exactly. ADR-021 flipped Proposed → Accepted; added to `docs/adrs/README.md` index. `_VALID_ROLE_FOR_E03` deliberately NOT widened (intentional subset gate — E06 decision per Known Issue #6). Binding-id slug drift (`other_overlay` substring in id) confirmed inert via grep.

**Partials (Group B — by design, mirrors S04.1 "operator verifies live" pattern):**
- `supabase db push` applies migration cleanly — operator-pending.
- `information_schema.check_constraints` shows 8-value check — operator-pending.
- `SELECT DISTINCT role` ⊆ 8-value set — operator-pending.
- 3 MT rows now read `role = 'no_hunt_zone'` — operator-pending.
- Row count unchanged pre/post — operator-pending.

### S05.4: Restricted-area / no-hunt-zone overlay discovery + ingestion

**Status:** ✅ 10/15 MET, ⚠️ 5 PARTIAL (Group B — operator-pending live verification)

PR #59 / `dc9d5b2` from `feat/S05.4-restricted-area-no-hunt-zone-overlay-discovery`. Loader `ingestion/states/colorado/load_restricted_areas.py` (~520 LOC) + 49 tests at `ingestion/tests/test_load_co_restricted_areas.py` confirmed on disk. Research-doc prerequisite (`docs/research/colorado-restricted-areas-evaluation.md` at `ed721c4`) confirmed. Discovery report at `ingestion/states/colorado/restricted-area-discovery.md` confirmed. The 10 V1 ids (`CO-restricted-{slug}-geom`) seeded for S05.5's `EXPECTED_CO_RA_ORPHAN_IDS` frozenset. Two Stage-6 Criticals resolved in 1 review-fix cycle: `_V1_EXPECTED_IDS` set-equality guard wired into `main()`; Curecanti drop moved before fixture/manifest writes so all counts agree at 10. Two post-merge-review fixes: malformed-properties guard (`2715bb9`); discovery-report MT-contrast accuracy correction (`31cbc24`). Research-doc 9→10 count correction documented (arithmetic slip at 3 prose sites; enumerated list + math both give 10). `verbatim_rule=None` for V1 (PAD-US carries geometry only; CPW brochure URL unresolved 404; no text fabricated per ADR-001). Test baseline shifted 1234 → 1283.

**Partials (Group B — by design):**
- Live PAD-US fetch: 11 features, Curecanti dropped, 10 rows UPSERTed — operator-pending.
- `returnCountOnly=true` cross-check — operator-pending.
- `ST_IsValid` round-trip on all 10 rows — operator-pending.
- `GIS_Acres` ±10% acreage sanity check — operator-pending.
- Live-run metadata fixture + manifest committed — operator-pending.

### S05.5: `geometry-overlays.json` fixture build

**Status:** ✅ 8/14 MET, ⚠️ 6 PARTIAL (Group B — operator-pending; upstream geometry rows are themselves Group B-pending)

PR #60 / `e7ba3d4` from `feat/S05.5-geometry-overlays-fixture-build`. Builder `ingestion/states/colorado/build_overlay_fixture.py` (~390 LOC) + 48 tests at `ingestion/tests/test_build_co_overlay_fixture.py` confirmed on disk. Library extension confirmed: `ingestion/ingestion/lib/overlays.py` `OverlayParentKind` + `OverlayChildKind` + `ROLE_FOR_BINDING_BY_CHILD_KIND` + deprecated alias `ROLE_FOR_E03_BY_CHILD_KIND` (same-object assignment — zero MT disruption). `EXPECTED_CO_RA_ORPHAN_IDS` (10 ids, `assert len()==10`) confirmed. W1 absence-of-log lock (`caplog` assertion that orphan INFO log is absent for genuinely-covered RAs) confirmed in test suite. Four threshold edge-locks (0.989/0.990/0.011/0.009) present. W2 proposed-and-rejected (documented): `if ras and not ra_rows: raise` would false-positive on the expected CO zero-RA-pairs case. Two post-build P3 review fixes: hardcoded personal path → generic placeholder (`5b4d146`); overlay-builder duplication → Known Issue #7 (`fe1fcd3`). Epic snippet line-citation-drift flags corrected in closure commit (type annotation `Mapping[OverlayChildKind, GeometryRole]` and missing `"hunting_district"` entry corrected to byte-parity). `geometry-overlays.json` and `geometry-overlays-dropped.json` NOT committed (correctly — upstream CO geometry rows are themselves operator-pending Group B writes). Test baseline shifted 1283 → 1331.

**Partials (Group B — by design; structurally dependent on S05.2 + S05.4 Group B live writes completing first):**
- `geometry-overlays.json` generated and committed — operator-pending.
- Paired `geometry-overlays-dropped.json` committed — operator-pending.
- Threshold recalibration check (borderline audit-log inspection) — operator-pending.
- UAT visual spot-check (multi-part GMU self-rows + no-hunt-zone orphans) — operator-pending.
- Every fixture-referenced `geometry_id` FK-checked — operator-pending.
- Byte-identical reproducibility across two runs — operator-pending.

### S05.6: Cross-state spatial discipline + binding-loader reference

**Status:** ✅ 9/9 MET

PR #61 / `1b55bfd` from `feat/S05.6-cross-state-binding-reference`. Scaffold/reference-only story — no Group A/B split needed (SQL never executes in E05). Three deliverables confirmed on disk: `ingestion/states/colorado/load_jurisdiction_bindings.py` (~100 LOC, import-only scaffold); `ingestion/tests/test_co_binding_reference.py` (9 tests in `TestCoBindingReferenceSql`); `docs/planning/epics/E05-confidence-findings/S05.6.md` (closure note). Stage-6 Critical resolved: distance was hardcoded `5000` literal in spec's illustrative SQL while `_NO_HUNT_ZONE_NEARBY_DISTANCE_M` sat unused — fixed by binding as 3rd `%s` param, mirroring MT at `:588`. Post-merge-review P3: `ORDER BY gmu.id` added for determinism, locked by `test_sql_orders_by_gmu_id_for_determinism`. `git diff --stat ingestion/ingestion/lib/` confirmed empty (ADR-005 + CO-leak guard held). `_STATE` vs `CO_STATE_CODE` naming tension documented as E06 cleanup candidate (deliberately not retrofitted). Test baseline shifted 1331 → 1340.

### S05.7: Spatial query verification + epic exit

**Status:** ✅ Group A MET (closed at-merge in this PR), ⚠️ Group B operator-pending live verification

S05.7 is the final E05 story; it closes in the same PR that produces this audit. **Group A deliverables landed at-merge:** the runbook `docs/runbooks/E05-colorado-geometry-verification.md` (363 LOC — 7 verification sections + a CO-specific Section 0 fixture-generation step + the Section 5 `ST_Envelope` CO-bounds check; every `ST_*` call `extensions.`-prefixed; every query carries `AND state = 'US-CO'`; the reproducibility section sequences `DELETE FROM jurisdiction_binding WHERE state = 'US-CO'` before `DELETE FROM geometry WHERE state = 'US-CO'` with an explicit `TRUNCATE` guard); the working note `docs/planning/epics/E05-confidence-findings/S05.7.md` (with the Group B verification-record table); this audit document itself (satisfying the final AC, "Post-implementation audit produced … exists with verdict"); and the epic Status + `Audited:` field + AC-tick updates. The cross-state filter regression AC is also effectively green at-merge — `test_co_binding_loader_sql_filters_by_state_co_pollution_guard` (S05.6, `ingestion/tests/test_co_binding_reference.py`) is a mocked test passing in CI.

**Group B (operator-pending, by design — identical posture to S05.0/S05.2/S05.4/S05.5):** the `ingestion/states/colorado/fixtures/spatial-test-points.json` fixture (generated from live geometry via `extensions.ST_PointOnSurface` per runbook Section 0 — deferred so coordinates are real `representative_point`s, not invented, per AC #2) plus the seven live spatial-query steps (`ST_Covers` spot-checks, `ST_IsValid` topology, named multi-part anchor `ST_NumGeometries > 1`, `EXPLAIN ANALYZE` index reachability, `ST_Envelope` CO-bounds, wipe + re-ingest reproducibility). These require live CO geometry rows, which are themselves Group B-pending from S05.0/S05.2/S05.4; the operator resolves them in the batched live-write session documented in S05.7.md.

---

## Cross-Cutting Findings

### Recurring post-merge fix-up theme — convention-maturing, not quality regression

Nine post-merge fix-up commits appear across E05's 8 closed stories (2 cubic-fix iterations in S05.0; 1 mid-Stage-6 cubic-fix in S05.1; 1 review-fix-to-review-fix correction in S05.3.5; 2 post-merge-review fixes in S05.4; 2 post-build PR-review P3 fixes in S05.5; 1 post-merge-review P3 fix in S05.6). All were caught pre-production by reviewers or cubic review. The pattern matches E04's observation: deliberate convention-maturing in response to discovered traps, not recurring quality issues. The growing `.roughly/known-pitfalls.md` corpus (1029 LOC at S05.6 close, up from ~887 at E05 start) is the concrete evidence that each fix-up became a durable convention.

### `.roughly/known-pitfalls.md` growth — healthy signal

The file grew from ~887 LOC (S05.0 open) to 1029 LOC (S05.6 close), adding entries across 7 new sections or sub-entries: Integration — Census TIGER + geopandas (S05.0); Conventions — Python + Testing new sections (S05.1); Conventions — Ingestion adapters new entries (S05.1, S05.2, S05.3.5, S05.4, S05.5, S05.6); Conventions — Documentation & planning discipline (S05.3); Integration — ArcGIS (S05.4); Conventions — Testing (S05.4, S05.5). The recurring doc-writer flag at 964/995/1015/1029 LOC documents the need for a future reorg/dedup pass — this is appropriate maintenance debt, not a blocking finding.

### Group B operator-pending pattern — recognized V1 posture, not a defect

Every story with live DB writes (S05.0, S05.2, S05.3.5, S05.4, S05.5) and the migration story (S05.3.5) carry open Group B ACs. This is the project's established "operator verifies live" pattern (S04.1 precedent, P RD-006-style), identical to E02's treatment of S02.6/S02.7 UAT ACs. The Group B verification sessions for S05.0 + S05.2 + S05.3.5 + S05.4 + S05.5 should be sequenced together as a batched operator run before or alongside E06. S05.7's runbook (`docs/runbooks/E05-colorado-geometry-verification.md`) will serve as the operator-facing protocol for this batch, exactly as `docs/runbooks/E02-geometry-verification.md` served for MT. No blocking finding.

### Three carried M2 hygiene candidates

Three items from S05.0 (first two) and S05.4 (third) remain open as PM-flagged candidates — none are E05's to resolve; all require an `ingestion/` implementation decision:

1. `db.upsert_geometry` missing `cur.rowcount == 0` fail-loud guard (inconsistent with `update_legal_description` / `upsert_jurisdiction_binding` pattern; low-risk today under ON CONFLICT DO UPDATE, but surfaces if DDL changes to ON CONFLICT DO NOTHING).
2. MT `load_state_boundary.py --service-url` removal (same latent silent-lie-citation issue cubic-fixed in CO's S05.0).
3. `load_gmus.py` raw-`feature["properties"]` subscript (same pattern S05.4's `load_restricted_areas.py` fixed via the `_feature_to_geometry` guard).

Recommended: bundle all three into a single hygiene PR alongside the overlay-builder extraction candidate (Known Issue #7) as the M2 hygiene sweep.

### Known Issue #6 — `_VALID_ROLE_FOR_E03` subset gate (E06 decision point)

MT's `_VALID_ROLE_FOR_E03` frozenset in `ingestion/states/montana/load_jurisdiction_bindings.py` deliberately does not carry `no_hunt_zone` — it is an intentional subset gate for overlay-fixture rows only. MT's 3 no-hunt zones are orphans handled by the separate `_build_no_hunt_zone_bindings` builder (zero MT impact). **E06's CO binding-loader must decide** whether CO no-hunt zones flow through its overlay-fixture path (gate must admit `no_hunt_zone`) or a separate hardcoded path (gate stays narrow). Surface to the PM and human at E06 binding-loader spec time before drafting S06.X.

### Known Issue #7 — Overlay-builder duplication (post-E05 tech debt)

`ingestion/states/colorado/build_overlay_fixture.py` (~390 LOC) is a near-verbatim port of `ingestion/states/montana/build_overlay_fixture.py`. Accepted as the established per-state ADR-005 pattern for now. The narrow extraction (hoist only `_build_overlay_pairs` + `_write_outputs` into `lib/overlays.py` and migrate both MT+CO) is the recommended scope for a post-E05 standalone refactor story. Leave orchestration, thresholds, and allowlists per-state (ADR-016 §4 anticipates per-state threshold recalibration).

---

## Verdict

**E05 ships clean.** No blocking findings. No NOT-MET Group A ACs across any of the 9 stories (S05.0–S05.7 + S05.3.5; S05.7 closes in this PR).

| Classification | Count | Notes |
|---|---|---|
| MET (Group A — static, at-merge) | ~80 | All static ACs for S05.0–S05.7 + S05.3.5 satisfied on direct inspection |
| PARTIAL (Group B — operator-pending) | ~43 | Live verification by design; mirrors E02 UAT posture |
| NOT MET | 0 | |

All PARTIALs are operator-driven-by-design Group B live verification steps. They are not defects — they are the structural posture of a project where the operator controls production DB writes per ADR-001 / ADR-003 discipline.

**Actionable recommendations (all non-blocking):**

1. **[P2, Hygiene, post-E05]** Bundle the three M2 hygiene candidates (`db.upsert_geometry` rowcount guard + MT `load_state_boundary.py --service-url` removal + `load_gmus.py` raw-properties guard) with the Known Issue #7 overlay-builder extraction into a single M2 hygiene sweep PR after S05.7 closes. All are implementation-territory changes requiring operator decision.
2. **[P2, E06-planning]** Resolve Known Issue #6 (`_VALID_ROLE_FOR_E03` subset gate) before E06's CO binding-loader spec is drafted. The decision affects whether CO no-hunt zones flow through the overlay-fixture path or a separate hardcoded path.
3. **[P3, docs]** `.roughly/known-pitfalls.md` is at 1029 LOC at S05.6 close; the recurring doc-writer reorg/dedup flag is actionable in a low-risk documentation session (no code changes required).
4. **[P3, docs]** `docs/research/colorado-restricted-areas-evaluation.md:249` still carries the softer MT-contrast phrasing (the discovery-report accuracy was corrected in S05.4's `31cbc24` but the research doc was left out of scope per the no-autonomous-research-doc rule). A one-line accuracy fix is deferred to a human-driven or research-session pass.

---

## Audit method (for reproducibility)

- Static review against the epic file (`docs/planning/epics/E05-colorado-geometry-ingestion.md`), `git log --oneline -20`, directory listings (`ingestion/states/colorado/`, `ingestion/tests/`, `supabase/migrations/`, `docs/planning/epics/completed/`), and AC checkbox counts (`grep -c "^\- \[x\]"` / `"^\- \[ \]"`).
- Per-story evidence drawn from the epic's `**Status:** Closed at-merge …` closure blocks (commit SHAs, PR numbers, LOC counts, quality-gate statements).
- No source code modified. This audit report is the only artifact written.
- This audit also covers its own production (S05.7 T3) — expected and matching how E02/E04 audited their final stories.
