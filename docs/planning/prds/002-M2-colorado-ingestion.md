# PRD 002 — M2: Colorado Ingestion

**Number:** 002
**Scope:** Milestone M2 (entire milestone; one prerequisites epic + two ingestion epics)
**Status:** Active
**Date:** 2026-05-29
**Author:** Nick Kirkes
**Thinking-layer references:** [`roadmap.md`](../../roadmap.md), [`context.md`](../../context.md), [`architecture.md`](../../architecture.md), [`open-questions.md`](../../open-questions.md)
**Load-bearing ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md), [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-007](../../adrs/ADR-007-montana-and-colorado-seed-states.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-011](../../adrs/ADR-011-shape-c-response-envelope.md), [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md), [ADR-019](../../adrs/ADR-019-doc-type-precedence-multi-source-merge.md), [ADR-020](../../adrs/ADR-020-id-text-pk-slug-derivation.md)

---

## Context

M1 closed at the `m1` tag (`e11e7bb`) on 2026-05-28 with Montana ingestion complete: 350 geometries, 435 regulation records, 825 license tags, 276 draw specs, 3 reporting obligations, 788 jurisdiction bindings (all post-UPSERT DB counts per handoff §8 fix #4's build-vs-DB convention; the build-side projections are larger and collapse via `ON CONFLICT DO UPDATE` / `DO NOTHING`), under 4 applied migrations and 20 accepted ADRs. The M1→M2 handoff document at [`docs/planning/handoffs/M1-to-M2-handoff.md`](../handoffs/M1-to-M2-handoff.md) is the authoritative carry-forward record; this PRD references it by section rather than restating it.

Per [ADR-007](../../adrs/ADR-007-montana-and-colorado-seed-states.md), Colorado is the draw-system stress-test counterpart to Montana's moderate-complexity baseline. M1 proved the schema accommodates Montana's regulation-text complexity (correction PDFs, A/B license splits, closure predicates, region-specific reporting). M2 proves it accommodates CPW's preference-point hybrid draw — and where it doesn't, extends the schema rather than special-cases Colorado. The architectural claim "multi-state" becomes defensible only when two states' worth of real data run against one schema.

This PRD exists because M2 has a non-trivial decomposition: a small but real prerequisites epic carrying forward M1 hygiene debt, followed by two large ingestion epics. The phasing decisions — what depends on what, what gets ADR amendments mid-milestone vs deferred — are worth surfacing here before epic planning begins.

## Outcome

When M2 is complete, the observable state of the world is:

- Colorado regulations are present in Supabase Postgres, validated against the six-entity schema, covering the five V1 species across all applicable Game Management Units (GMUs), CWD zones, and overlay geometries.
- The ingestion pipeline for Colorado is reproducible — `make ingest STATE=colorado` with Supabase credentials in `.env` produces the same loaded state every time.
- Spatial queries against Colorado's GMU boundaries work via PostGIS, including cross-state queries that correctly partition by state.
- Colorado's draw-based tag mechanics are modeled in the `draw_spec` schema (preference points, hybrid draw, allocation pools, residency caps) in a way that generalizes — Wyoming, New Mexico, and Utah can use the same fields without new state-specific branches in shared code.
- The five M1 carry-forward technical-debt items are resolved (handoff §8): `license_season` RLS, jurisdiction_binding count-band narrowing, runbook hygiene, loader logging, and PRD 001 sequencing reconciliation.
- Any schema changes M2 required are documented in new ADRs, propagated to the three-place sync (TypeScript types, Python dataclasses, Postgres DDL), and reflected in timestamped migration files.
- Montana data is unaffected. Every M1 row remains queryable; every M1 test continues to pass.
- The `m2` tag is pushed at the commit where M2 UAT passes.

The milestone exit criterion from the roadmap stands: a reviewer opening the repo sees two states' worth of real data and one schema. "Multi-state" stops being a claim and starts being a property.

## In scope

**States:** Colorado only. Montana is locked at `m1` except for the carry-forward items in E04.

**Species:** Elk, mule deer, whitetail, pronghorn, black bear — parity with M1. If the CPW Big Game brochure incidentally covers additional species, they are filtered out at the adapter layer. V1 species expansion is post-M2.

**Entities:** All six entities from the schema. Every entity is expected to be exercised by Colorado's data; the `draw_spec` entity is the focus of the stress-test.

**Geometries:** CPW ArcGIS FeatureServer at `services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6` per Q4 resolution (186 big-game GMU polygons, `outSR=4326`, no auth). Plus CWD zones and any restricted-area overlays that CPW publishes as distinct layers. `CO-STATEWIDE-geom` populated analogously to `MT-STATEWIDE-geom` per ADR-018.

**Regulation text:** CPW Big Game brochure as the primary source, plus any species-specific supplemental publications (Black Bear brochure if separately published) and any mid-year corrections following the ADR-019 doc-type precedence rule. All text carried verbatim per ADR-001 and ADR-008. Specific source URLs, publication cadence, and PDF discovery are E06 planning concerns — the PRD commits to the source family, not the file inventory. (Lesson from M1 S03.1 / S03.3: pre-validated URL guesses in `sources.yaml` did not survive contact with the live FWP CDN; HEAD-verify and pin URLs at E06 planning time, not at PRD time.)

**Draw mechanics:** Colorado's three-stage draw (primary May, secondary late June, weekly leftovers), preference-point hybrid (80/20 rank-ordered + random for ≥5-point applicants), and non-resident ceilings under the rolling three-year average — modeled in `draw_spec.pools`, `draw_spec.point_system`, `draw_spec.choices`, and `draw_spec.allocation_pool[]`. The `parameters` escape hatch may be exercised; whether and how is an E06 decision.

**M1 carry-forward (E04):** All five items from handoff §8 — license_season RLS migration, jurisdiction_binding count-band narrowing to `[552, 1024]`, seven runbook hygiene fixes, `logging.basicConfig` on `load_jurisdiction_bindings.py:main()`, and the PRD 001 sequencing language reconciliation.

**Phasing:** Three sequential epics (E04, E05, E06) as described below.

## Out of scope

Explicitly named to prevent scope creep:

- **Wyoming, Idaho, Utah, Washington.** Per ADR-007, V1 is Montana + Colorado. Adapter scaffolding for a third state is M5-stretch territory if at all.
- **Block Management Areas, Big Game Distribution layers, FWP Lands locations.** Already deferred from V1 in [`docs/roadmap.md`](../../roadmap.md) § "Deferred from V1." Colorado equivalents (access overlays, habitat layers) are deferred under the same rationale.
- **MCP server implementation.** M3 work. The MCP server scaffold stays at its M0 placeholder during M2.
- **Web companion and Claude Code plugin.** M4 and M5 respectively.
- **RLS beyond deny-all.** E04 closes the `license_season` gap with a deny-all policy. No user-scoped or tenant-scoped RLS is in M2 scope.
- **Re-ingestion of Montana.** Montana data is frozen at `m1`. The only Montana code touched in M2 is the five E04 carry-forward items: a one-line `logging.basicConfig` addition in `load_jurisdiction_bindings.py:main()`, a constant-tuple narrowing of `_BINDING_COUNT_GUARD_BAND`, a new RLS migration for `license_season`, and runbook edits. None re-runs the Montana ingestion pipeline or alters loaded MT rows.
- **MCP tool exposure of Colorado data.** Even though Colorado data will technically be queryable through MCP by M2 end, no MCP tool exposes it during M2. Verification queries during M2 use direct Postgres via the Supabase CLI (`supabase db query --db-url`), matching the M1 UAT pattern.
- **Any species beyond the five V1 species.** Same rule as M1: filter at the adapter, leave the rest in the source documents.
- **Any Colorado-specific logic leaking into `ingestion/ingestion/lib/`.** Shared code stays shared. The `TestNoLibImports` / `TestNoStateAdapterImports` AST guards enforce. Colorado-specific code lives in `ingestion/states/colorado/`.
- **Automated ingestion scheduling.** M2 ships a reproducible manual pipeline. Drift detection is V2.

## Phasing and rationale

M2 decomposes into three sequential epics. The sequencing rationale is documented under "Why sequential" below.

### E04 — M1 carry-forward and Colorado schema preparation

**Outcome:** The five M1 carry-forward items from handoff §8 are resolved. Any Colorado-driven schema additions identified during PRD review are applied as new timestamped migrations and propagated to the three-place sync. Logging and runbook hygiene are restored to parity across all loaders.

**Why first:** The `license_season` RLS gap is a real exploitable data-integrity surface (anyone with the anon key can read/write the table directly). Closing it before any new ingestion work begins matches the discipline that produced E01: get the schema and access posture right before data lands. The other four items are smaller but block clean operator workflows: a future operator hitting the same UAT runbook should not re-derive the seven hygiene fixes.

**Why isolated from ingestion:** E04 is mostly objective work — migration drafting, count-band narrowing, runbook editing, a one-line `logging.basicConfig` add. Bundling it with E05 or E06 would mix low-risk hygiene with the harder ingestion work and make blockers harder to attribute.

**Exit criteria for E04:** New migration deny-alling `license_season` is applied; `information_schema.table_privileges` shows no rights for `anon` / `authenticated` on `license_season` and `pg_policies` carries the two deny-all rows. `_BINDING_COUNT_GUARD_BAND` in `load_jurisdiction_bindings.py` is `[552, 1024]` with AC #1087 footnote updated. All seven runbook hygiene fixes per handoff §8 are landed. `load_jurisdiction_bindings.py:main()` has `logging.basicConfig`. PRD 001 sequencing language is reconciled per the proposal in `docs/planning/epics/completed/E02-geometry-ingestion.md` § "Known issues to escalate" #1. The Montana test suite remains green (1165 + 2 skipped).

### E05 — Colorado geometry ingestion

**Outcome:** All Colorado GMUs, CWD zones, restricted-area overlays, and `CO-STATEWIDE-geom` are loaded into the `geometry` table with correct `jurisdiction_binding` rows expressing overlay relationships. The geometry-overlays fixture (`ingestion/states/colorado/fixtures/geometry-overlays.json`) is the Colorado analog of MT's fixture. Spatial queries work and correctly partition by state (`hd.state = 'US-CO'` discipline mirrored).

**Why second:** Geometries are the anchor for every regulation_record FK target in E06. CPW's FeatureServer is well-documented (verified during the April 2026 research cycle per Q4), and ArcGIS-layer fetching is the lower-risk half of Colorado. Getting it stable before tackling CPW's draw mechanics in E06 means the harder epic doesn't carry geometry risk.

**Why before text:** Same reasoning as M1 E02 — text ingestion's FK targets must already exist. Additionally, Colorado's CWD program is more developed than Montana's (multiple zones, mandatory sampling rules); having CWD geometry in place is the precondition for *implementing* the Q18 decision in E06 if it goes zone-keyed. (The Q18 decision itself — zone-keyed vs license-keyed — is decidable from CPW's publication structure and can be drafted as an ADR before geometry lands; geometry only gates the zone-keyed write path.)

**Exit criteria for E05:** All V1-relevant Colorado geometries loaded from CPW's FeatureServer plus any additional CWD/restricted-area layers. Every geometry passes `shapely.make_valid()` and `ST_IsValid`. Spot checks using `ST_Contains` against known Colorado coordinates return correct GMU identification. `jurisdiction_binding` rows correctly express GMU → CWD-zone and GMU → restricted-area overlay relationships. `CO-STATEWIDE-geom` is present with `kind='state'`. Fixture committed; manifests committed; raw payloads gitignored per the E02 pattern.

### E06 — Colorado regulation text ingestion

**Outcome:** Every regulation record, season definition, license tag, draw spec, and reporting obligation for Colorado's five V1 species is in Postgres. Source citations populated per ADR-001. Verbatim text per ADR-008. Confidence calibrated per ADR-017's existing framework. CPW's preference-point hybrid draw is modeled in `draw_spec` in a way that generalizes beyond Colorado.

**Why third:** This is the hard half. PDF extraction has real variance. CPW's draw mechanics are the architectural reason M2 exists — exercising them is what makes the multi-state schema claim defensible. Confidence calibration is already FINALIZE per ADR-017; M2 inherits the framework rather than re-litigating it (Colorado may surface `low`-tier rows that V1 Montana didn't; the rule exists and is unit-tested).

**Open decisions surfacing in E06:** Q12 (`parameters` enforcement), Q16 (species granularity if CPW publishes mule-deer-only vs whitetail-valid licenses), Q17 (per-GMU allocation caps in `draw_spec`), and Q18 (CWD sampling target-table — zone-keyed vs license-keyed). The PRD does not pre-decide these; the E06 planning agent surfaces the trigger conditions to the human as they arise and drafts ADRs where the schema needs to extend.

**Exit criteria for E06:** All five V1 species have `regulation_record` rows for every applicable GMU. Every row has a source citation. `verbatim_rule` fields decompose per ADR-018 / Q15 (per-license-row text → `license_tag`, per-season-window text → `season_definition`, HD-wide NOTE lines → `regulation_record.additional_rules`). `draw_spec` rows model preference points (`point_system.kind='preference_linear'` per `architecture.md:341-347`), hybrid draw (non-empty `allocation_pool[]` with one pool's `selection='rank_ordered_by_points'` for the 80% share and another's `selection='unweighted_random'` for the 20% share per `architecture.md:356-369`), and `residency_cap` populated where CPW publishes it. Reporting obligations populated. ADR-020 `drift_guard` pattern adopted for `season_definition`, `license_tag`, and `reporting_obligation` UPSERTs per the M2 mandate in handoff §8.

### Why sequential

E04 → E05 → E06 has one hard technical dependency and two soft operator-discipline orderings:

- **E06 depends on E05 (hard).** E06 writes `jurisdiction_binding` rows (in its S03.10-equivalent story); per the initial schema migration (`supabase/migrations/20260425000000_initial_schema.sql:193-216`) those binding rows carry FKs to BOTH `regulation_record` (the binding's anchor) AND `geometry(id)`. Regulation records are written earlier within E06; geometry rows must exist from E05 before binding writes can commit. CWD geometry being present from E05 is also the precondition for *implementing* a zone-keyed Q18 decision; the decision itself is decidable from CPW publication structure. (This corrects a PRD 001 sequencing-language bug that handoff §8 flagged for reconciliation in E04 — PRDs sometimes phrase the dependency as "regulation_record FKs to jurisdiction_binding," which is backwards.)
- **E05 should follow E04 (soft).** The `license_season` RLS migration in E04 is order-neutral with E05's geometry writes; E05 does not FK to `license_season`. But the runbook hygiene + loader logging fixes in E04 materially improve operator verification of E05's outputs. Order matters for workflow clarity, not for technical correctness.
- **E06 should follow E04 (soft).** The `license_season` link table is heavily exercised by E06's S03.7-equivalent story. Writing to a table whose RLS is incompletely closed is acceptable from the write-path perspective (service-role bypasses RLS), but the gap should be closed before more rows land. Recommended sequencing, not a technical block.

Only the E06→E05 dependency is FK-hard; the other two are operator-discipline orderings. Per handoff §8, E04's `_BINDING_COUNT_GUARD_BAND` narrowing is explicitly the "first M2 PR" — meaning E04 ships first chronologically — but its remaining items (RLS migration, runbook edits, loader logging) can land in parallel with E05's planning if capacity allows.

## Success criteria for the milestone (UAT level)

M2 is done when the following can be verified by hand or by script (M2 UAT runbook drafted at the end of E06, following the M1 UAT pattern):

1. A query to `regulation_record` for (state=`US-CO`, jurisdiction_code=`CO-GMU-<representative-GMU>`, species_group=`elk`, license_year=2026) returns a row with populated `source`. Joining outward, the row resolves to at least one downstream `season_definition` and at least one `license_tag` via the appropriate link tables. (`additional_rules` may legitimately be empty for a given GMU — parity with M1's Q15 disposition; absence of NOTE-line content is not a failure.)
2. A query joining `regulation_record` → `license_tag` → `license_season` → `season_definition` for a representative Colorado GMU (named at E06 planning time per CPW publication coverage, mirroring M1's HD 262 → HD 124 substitution lesson) returns the CPW-published weapon-window seasons as separate `season_definition` rows. The expected vocabulary is archery / muzzleloader / rifle but the actual published names are normalized at the adapter and verified at E06 planning; the criterion passes when the join returns the seasons CPW actually publishes for that GMU, faithfully named. If Colorado's data exercises an asymmetric license-coverage pattern analogous to MT's A/B split, that pattern is observable in the join; if Colorado's data has no asymmetric pattern (CPW does not split deer or elk into A/B equivalents), the asymmetric clause is marked N/A in the UAT runbook with an operator note rather than treated as a failure.
3. A query joining `license_tag` → `draw_spec` for a preference-point Colorado hunt returns a `draw_spec` row with `point_system.kind='preference_linear'`, a non-empty `allocation_pool[]` whose entries use `selection='rank_ordered_by_points'` and `selection='unweighted_random'`, and `residency_cap` populated where CPW publishes it.
4. A PostGIS `ST_Contains` query with a coordinate inside a known Colorado GMU returns that GMU as the matching geometry, plus any overlay CWD zone or restricted area the coordinate falls within. The query's SQL includes an explicit `state = 'US-CO'` filter, mirroring `load_jurisdiction_bindings.py`'s `_STATE` filter discipline from M1 S03.10 — partitioning is enforced by the filter, not by `ST_Contains` alone (raw `ST_Contains` happens to exclude MT for inside-CO points because the polygons don't overlap, but a state-line coordinate or future cross-state polygon would fan out without the explicit filter). Verification: grep `ingestion/states/colorado/load_jurisdiction_bindings.py` for `_STATE = "US-CO"` and verify the constant is interpolated into the relevant SQL string (same source-review pattern M1 used during S03.10 closure).
5. A `regulation_record` row for Colorado with no `source` does not exist.
6. A `geometry` row for Colorado with invalid topology does not exist.
7. Re-running `make ingest STATE=colorado` against an already-loaded database produces the same result (idempotent).
8. `information_schema.table_privileges` shows no rights for `authenticated` or `anon` on `license_season` or on any of Colorado's newly-populated tables, and `pg_policies` shows deny-all rows for each (matching the M1 UAT canonical query pattern).
9. The Montana test suite continues to pass; M1 row counts in Postgres are unchanged.
10. For every ADR accepted during M2 (Q12 / Q16 / Q17 / Q18 resolutions; the `role='no_hunt_zone'` enum addition if exercised; any other schema additions), the coupled-PR discipline from `architecture.md` is observable in git: the ADR file, the migration SQL, the Python schema edit, and the TypeScript-type edit all land in the same commit (verifiable via `git log --follow --name-only -- <migration>` to find the commit SHA, then `git show <sha> --name-only` to confirm the four file kinds appear together). No migration timestamp lacks a paired Python and TypeScript edit in the same commit.

The build-vs-DB count footnote convention from M1 UAT criterion #6 carries forward — entity tables collapse via `ON CONFLICT DO UPDATE`; link tables collapse via `ON CONFLICT DO NOTHING`. M2 success criteria distinguish build counts from post-UPSERT DB counts.

## Known risks and mitigations

**R0 — Schema revision likely during M2.** Per ADR-006's "schema is the contract" discipline, the default response to real-data stress is to improve the schema, not special-case the state. Q12, Q16, Q17, and Q18 are all explicit ADR-candidates per the open-questions doc; the `role='no_hunt_zone'` enum addition and multi-source geometry provenance are also schema-extension candidates. Treat ADR drafting as routine M2 work, not exceptional. Concrete schema-revision triggers are decomposed in R3 (Q17), R4 (Q18), R5 (Q16), and R6 (CPW `emergency_order` doc-type expansion of ADR-019) below; R1 (PDF variance) and R7 (cross-state filter) are process/discipline risks, not schema triggers. This umbrella exists so a reader scanning for "where will the schema change?" sees a single signal.

**R1 — PDF extraction variance against CPW publications.** CPW's Big Game brochure and any species-specific or correction PDFs have not yet been extracted. M1's S03.3–S03.5 closure cycles were dominated by real-PDF discoveries (the pdfplumber-specific pitfalls catalogue in `.roughly/known-pitfalls.md` plus UAT-discovered defects like Region 7 portion absorption, per-row window divergence, anchor-phrase line-wrap). Mitigation: budget review-triad iterations on the first CPW extractor; treat the cubic-review + silent-failure-hunter pattern from S03.X as default; surface discoveries in a working-note directory analogous to `E03-confidence-findings/` (deleted at m2 tag per the same ADR-017 §6 discipline).

**R2 — CPW draw mechanics may exercise `parameters` escape hatch (Q12).** CPW publishes annual draw statistics that may reference state-specific quirks (landowner preference vouchers, ranching-for-wildlife allocations, leftover sale mechanics) the structured `draw_spec` fields don't cover. Mitigation: surface every candidate `parameters` use to the human before adopting; prefer extending the structured schema over expanding `parameters` use. If `parameters` IS the right answer for an irreducibly CPW-specific quirk, document it in [`docs/planning/epics/completed/E03-deferred-items/draw-mechanics.md`](../epics/completed/E03-deferred-items/draw-mechanics.md) with rationale.

**R3 — Per-GMU allocation caps in `draw_spec` (Q17).** Colorado may publish per-GMU allocation caps that the current `draw_spec` schema cannot express (the MT HD 210 V1 case is the precedent). Mitigation: the `_KNOWN_CROSS_LISTING_OVERRIDES` pattern from S03.8 is the established workaround; if Colorado scales the pattern beyond override-table tolerance, Q17 becomes an ADR with a schema extension and migration.

**R4 — CWD sampling modeling (Q18).** Colorado is the trigger state for Q18 per the deferred-items file. CPW likely surfaces zone-keyed CWD sampling (mandatory testing in specific zones) AND license-keyed sampling (license type X requires sampling regardless of zone). Mitigation: surface the decision early in E06 planning; if Colorado data forces zone-keyed `reporting_obligation` rows, draft the ADR before the load_reporting_obligations adapter is implemented.

**R5 — Species granularity (Q16).** CPW may issue mule-deer-only licenses that don't validate for whitetail (Colorado has limited whitetail range). The M1 schema treats `species_group` as opaque. Mitigation: surface the first observed case; if it's a single-species pattern, current schema handles it; if it's a structured "valid for X, not for Y" pattern, ADR-010 needs an amendment.

**R6 — CPW source publication cadence.** Unknown whether CPW issues mid-year corrections analogous to MT FWP's 1-page Black Bear correction (the doc-type precedence trigger for ADR-019). Mitigation: ADR-019 is already in place; if Colorado doesn't exercise it, the rule is dormant. If Colorado introduces a new doc-type ranking (e.g., `emergency_order`), an ADR-019 amendment is required per its own Decision item #5 ("V1 rank table is exhaustive; other doc-types fail loud").

**R7 — Cross-state spatial pollution.** Colorado's `load_jurisdiction_bindings.py` must mirror MT's `_STATE = 'US-MT'` SQL filter discipline from `_query_nearby_hds_for_zone` (S03.10) with `_STATE = 'US-CO'`. Without it, future cross-state spatial queries silently under-bind. Mitigation: pattern is established; the E06 planning agent treats it as a hard discipline, not a defensible omission. Reinforced by success criterion #4's explicit `state = 'US-CO'` filter requirement.

**R8 — Test-suite regression.** Adding Colorado tests should not require modifying Montana tests. Mitigation: Colorado tests are additive; the test count baseline grows from 1165 without subtracting. Any Montana-test edit during M2 is a flag-and-discuss event.

## Decisions already made

Load-bearing decisions that the PM agent and implementation agents should treat as fixed and reference rather than re-derive:

- **CPW ArcGIS FeatureServer for geometries.** Q4 resolution. Layer 6, 186 big-game GMU polygons, `outSR=4326`.
- **CPW Big Game brochure as primary regulation text source.** Cadence and exact URLs are E06 discovery work; source family is committed.
- **Six-entity schema reused from M1.** ADR-010. No re-litigation.
- **`geography(MultiPolygon, 4326)` for all geometries.** ADR-010, ADR-012.
- **Verbatim regulation text; no paraphrasing.** ADR-001, ADR-008.
- **`schema_version` on every row.** ADR-006.
- **Deny-all RLS on all tables (including new tables added during M2).** E04 closes the license_season gap; any new M2 migrations include deny-all in the same file.
- **State-adapter isolation.** Colorado code lives in `ingestion/states/colorado/`. AST guards enforce.
- **ADR-019 doc-type precedence applies as-is to CPW publications.** New doc-types require ADR-019 amendment.
- **ADR-020 drift_guard pattern is mandatory for `season_definition`, `license_tag`, and `reporting_obligation` UPSERTs.** Per handoff §8. The pattern ships two primitives in `ingestion/ingestion/lib/drift_guard.py`: `assert_id_matches` for runtime row-construction surfaces (use for `season_definition` + `license_tag`, where ids are built per-row from extracted data) and `assert_dispatch_dict_drift_free` for compile-time dispatch-dict surfaces (use for `reporting_obligation`, where ids come from a module-level `_REPORTING_ROW_SPEC`-style dict). Carve-out for `db.upsert_jurisdiction_binding` stands (the UPSERT excludes identity fields from the UPDATE clause — schema-level guarantee strictly stronger than the application-level assert).
- **OQ7 row-count guard pattern.** Every Colorado adapter's `main()` fires ±30% band guards before `db.connect()`.
- **Three-phase adapter shape (build → guards → conn/loops/commit).** Established across S03.6–S03.10; Colorado adapters mirror.

## Open decisions resolved during M2

Resolved during or by the end of M2:

- **Q12 `parameters` enforcement.** Likely exercised by CPW draw mechanics. Decision either way (use `parameters` for specific CPW quirks, or extend structured fields) is captured in an ADR at the point of first exercise.
- **Q16 species granularity.** If CPW surfaces mule-deer-only licenses, decision is captured in an ADR-010 amendment.
- **Q17 per-GMU allocation caps in `draw_spec`.** Decision triggered when CPW data exceeds the override-table workaround tolerance. ADR-candidate.
- **Q18 CWD sampling target-table.** Decision triggered by first CPW CWD sampling row that doesn't fit `regulation_record.additional_rules`. ADR-candidate.
- **`role='no_hunt_zone'` enum addition.** Decision triggered if Colorado introduces no-hunt zones requiring a more precise role than `other_overlay`. ADR + migration.
- **Multi-source geometry provenance.** Decision triggered if CPW splits a single GMU's geometry across multiple data sources requiring multi-source attribution. ADR-candidate.

Not resolved during M2; remain open for V2 or later:

- **Cell-level source attribution.** V1 simplification stands per ADR-019. M2 ADR-candidate only if Colorado data forces it.
- **Free-prose non-NOTE HD-wide content.** V1 simplification stands. Same trigger condition as MT.
- **Q10 product name, Q13 public/license posture.** Out of ingestion scope.

## Handoffs

### What M3 inherits from M1 + M2

- Two states' data queryable from Postgres. M3's MCP tools read from the same tables and cannot distinguish between Montana and Colorado at the schema layer (correctness property of the multi-state claim).
- A source-citation discipline that every M3 tool response honors.
- A confidence calibration that M3 surfaces consistently — Colorado's confidence values mean the same thing as Montana's per ADR-017's FINALIZE verdict.
- Any schema additions M2 introduced are reflected in the TypeScript types under `mcp-server/src/types/`. M3 inherits a stable schema contract.

### What the `m2` tag signals

`m2` on the commit where M2 UAT passes. The tag is the authoritative marker that Colorado is done. Everything tagged `m2` or later can assume both Montana and Colorado are in Postgres, validated, queryable, and schema-consistent.

## Non-goals beyond out-of-scope

Things the milestone is not optimizing for:

- **Not optimizing for ingestion speed.** Same as M1.
- **Not optimizing for storage efficiency.** Same as M1.
- **Not optimizing for query performance.** Indexes per schema definitions; no performance tuning beyond that.
- **Not retrofitting *new* M1 patterns.** If E06 surfaces a better pattern than S03.x used, the better pattern is documented; Montana is not retro-migrated to it. Pattern propagation happens in V2. (E04's count-band narrowing and license_season RLS gap-close are planned M1 hygiene-debt closeout from handoff §8 — not new-pattern retrofit, and explicitly in scope.)
- **Not producing external-consumer documentation.** Same as M1.

## What changes after this PRD

The following artifacts update when M2 progresses:

- `docs/planning/epics/` gains three epic files (E04, E05, E06) as each epic is planned.
- `docs/planning/README.md` updates to reflect M2 progress.
- `docs/adrs/` gains new ADRs as Q12/Q16/Q17/Q18 (and any other M2-surfaced questions) resolve. ADR numbering continues sequentially (ADR-021 onward).
- `docs/open-questions.md` removes resolved questions and adds any newly-surfaced M2 questions per the parking-lot discipline.
- `CLAUDE.md` updates with M2 status as the milestone progresses.
- `CHANGELOG.md` accumulates M2 entries as stories merge.
- `architecture.md` may gain addenda if M2 schema additions are material.
- The `docs/planning/epics/completed/E03-deferred-items/` directory may gain new files following the 4-step flag protocol if M2 surfaces deferrable items beyond Q12/Q16/Q17/Q18.

This PRD itself does not typically update during M2 execution. If M2 scope changes materially (e.g., E06 discovers that Colorado requires three new ADRs whose interaction needs a re-scope), this PRD updates. Edits are tracked by commit history; no revision metadata block is needed.
