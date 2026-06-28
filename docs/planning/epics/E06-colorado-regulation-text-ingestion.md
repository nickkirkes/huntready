# E06: Colorado Regulation Text Ingestion

**Status:** In Progress — 11 of 16 stories closed (S06.0 / S06.1 / S06.3 / S06.4 / S06.3.1 / S06.5 / S06.6 / S06.6.1 / S06.6.2 / S06.7 Group A / **S06.8.0**; S06.2 omitted by design at S06.3 Stage-1 discovery); **S06.8.0 closed at-merge 2026-06-26** via PR #77 / `68e0c04` from `feat/S06.8.0-draw-mechanics-extraction` (mid-epic carve-out resolving the Phase-A "no draw-mechanics data in per-unit artifacts" gap; new `extract_draw_mechanics.py` ~1,102 LOC + 50 new tests; deterministic artifact `extracted/draw-mechanics-2026.json` 123 records SHA `7fd162ad…c15b16`; composition: 116 hybrid_code + 4 point_only_code + 1 important_dates + 1 nr_allocation + 1 hybrid_mechanics; pytest 1907 → 1957 + 5 skipped; no lib/schema/MT/TS changes; 3 new pitfalls; Q12/Q17 remain Open and surface at S06.8). **S06.8 now unblocked** — its ACs consume `draw-mechanics-2026.json` (Phase C; faithful-V1 fallback retired). **S06.7 Group A complete at-merge 2026-06-24** (first CO multi-link adapter `load_seasons_and_licenses.py`: season_definition 2013 + license_tag 2470 + license_season 2013 + regulation_season 2013 + regulation_license 2470 dry-run-verified; Q20 Season Choice resolved → per-window fan-out; PRD 002 SC #2 asymmetric-coverage locked on GMU 001 mule_deer; ADR-020 drift-guard at 4 entity sites, link builders carved out; pytest 1787 → 1907 + 4 skipped; no lib/schema/MT/TS changes; new Known Issue #13 for the ~477 female-row empty-windows extractor gap; Group B live-write operator-pending). **S06.8.0 carved out 2026-06-24 (15 → 16 stories) — closed 2026-06-26.** At S06.8 build Stage-2 discovery + an independent Phase-A brochure probe, the CO extraction artifacts were found to carry **zero draw-mechanics data** (`apply_by`/`quota` null on all 2,762 rows; no `draw_phase`/`successor_hunt_code`/hybrid/residency fields) — S06.8's 80/20-hybrid + 20/25-residency premise needs the brochure draw-instructions front matter (pp. 8–32) the per-unit extractor never captured. Per user decision 2026-06-24, **S06.8.0** (CPW draw-instructions front-matter extraction → committed `draw-mechanics-2026.json`) is carved out **before S06.8** (mirrors S06.3.1 / S06.6.1 / S06.6.2). Phase A is complete + **outcome (a) confirmed extractable**: hybrid eligibility is an explicit per-hunt-code table (p. 29), deadlines on p. 14, point-only codes per species section, weighted-preference is moose/sheep/goat-only (out of V1). **S06.8 is blocked on S06.8.0**; its ACs are revised (Phase C) to consume the artifact once S06.8.0 merges. S06.7's `license_tag` rows remain the `draw_spec_key` backfill targets; S06.8 live execution still gated on operator Group B
**Milestone:** M2 — Colorado Ingestion
**Dependencies:** E04 (M1 carry-forward + CO schema prep), E05 (CO geometry ingestion — all 9 stories closed + audited 2026-06-06; epic at [`completed/E05-colorado-geometry-ingestion.md`](completed/E05-colorado-geometry-ingestion.md))
**Validated:** 2026-06-08 (E06 validation triad: Source Faithfulness + Draw-Mechanics & Confidence + Schema Stress-Test & Drift-Guard; verdicts LAND-WITH-MINOR-EDITS + LAND-WITH-EDITS + LAND-WITH-MINOR-EDITS; **all 11 MUST-FIX findings applied at draft time** — broken ADR-020 link sweep [5 occurrences]; S06.0 Last-Modified/Content-Length header capture + cover-page confirmation + multi-source option (a)/(c) consequence chains + conditional 6th `db.update_geometry_verbatim` decision + schema-gap enum-extension precision; S06.1 `pending: true` drift-marker semantics; S06.3/S06.4/S06.5 ADR-008 paraphrase-prohibition + no-`layout=True` AST guard + docstring grep-parity discipline; S06.4/S06.6/S06.9 `SourceCitation.document_type` silent-widening guard per ADR-019 §"Decision" item 5; S06.6 `_JURISDICTION_BINDING_ID_FORMAT` 3-test lock + statewide-anchor 3rd-candidate flag tighten + ADR-017 FINALIZE lock; S06.7 `drift_guard.assert_id_matches` every-build-function-site language + pure id-derivation function AC + Q16/Q17/closure-temporal-anchors pre-code flag protocols; S06.8 `successor_hunt_code_key` composite-key form + 20%/25% coupling rule + `application_deadline` location lock + `purchase_only_code` per-species string + `inactive_forfeit_years=null` + module-level `Final` constants for `_HYBRID_*` parameters + `draw_spec` composite-PK exclusion AC + Q17 per-GMU caps flag; S06.9 `assert_dispatch_dict_drift_free` module-top timing + pure `_derive_reporting_obligation_id` callable; S06.10 `drift_guard` NOT imported AC + AST guard + `%s`-bound distance lock + 4-builder portion code-path preservation. Plus the most load-bearing SHOULD-FIX items.)
**Completed:** —
**Estimated Stories:** 16 (S06.0 through S06.11, plus S06.3.1 carved out 2026-06-16 post-S06.4-closure to address Known Issues #10 + #11, plus **S06.6.1 carved out 2026-06-21** post-S06.6-closure to address the M2-build operator-pass Step 4 PAD-US OBJECTID drift, plus **S06.6.2 carved out 2026-06-22** post-S06.6.1-closure to address the second-consecutive PAD-US drift surfaced during the operator-pass resume (GeometryCollection area-preservation in `lib/arcgis`), plus **S06.8.0 carved out 2026-06-24** at S06.8 build discovery — the CO artifacts carry no draw-mechanics data, so the brochure draw-instructions front matter (pp. 8–32) is extracted into `draw-mechanics-2026.json` before S06.8 builds — all per the S03.6.1 / S05.3.5 mid-epic carve-out precedent; carve-outs added at sequencing slots if surfaced mid-epic)
**UAT Gating:** S06.3 / S06.4 (extraction faithfulness), S06.8 (draw_spec faithfulness against CPW publication), S06.11 (M2 milestone UAT). Most other stories are `UAT: no` — verification-gated against SQL counts deferred to S06.11. S06.5, S06.9 may flip to `UAT: yes` mid-epic if extraction surfaces faithfulness ambiguities.

---

## Objective

E06 ingests all Colorado regulation text into Postgres so every V1 species (elk, mule deer, whitetail, pronghorn, black bear) has populated `regulation_record`, `season_definition`, `license_tag`, `license_season`, `draw_spec`, `reporting_obligation`, and `jurisdiction_binding` rows for every applicable CO GMU. CPW's preference-point hybrid draw is modeled in `draw_spec` using the schema verified by [`docs/research/colorado-draw-schema-proposal.md`](../../research/colorado-draw-schema-proposal.md) — no state-specific shared-code branches. Verbatim discipline per ADR-001 / ADR-008; confidence calibration per ADR-017 (FINALIZE, unmodified — CO inherits the framework); ADR-019 doc-type precedence for any CPW multi-source merge; ADR-020 `drift_guard` mandatory on the appropriate UPSERT helpers.

E06 is the third and final M2 epic. It is the most variable epic in the milestone — Q12 / Q16 / Q17 / Q18 may all resolve here, and the M2 PM expects to revise mid-epic if real CPW data forces re-thinking (mirroring E03's S03.3 / S03.4 / S03.5 closure cycles). The PM surfaces every trigger condition to the human as a flag-and-discuss event; the PM does not silently decide and does not draft ADRs autonomously.

---

## Architectural commitments inherited from M1, E04, E05, and the 21 accepted ADRs

| Commitment | Source | Implication for E06 |
|---|---|---|
| Verbatim regulation text — no paraphrase, no summarization | [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md) | Every `regulation_record.additional_rules` entry + every `season_definition.verbatim_rule` + every `license_tag.verbatim_rule` + every `reporting_obligation.verbatim_rule` is verbatim per pdfplumber word-grouping boundary clarified in S03.2. No `layout=True` regressions. |
| Decomposed entity model | [ADR-010](../adrs/ADR-010-decomposed-entity-model.md) | Six entities populated, not three. Cross-shared license/season entities possible (CO B-license-equivalents if CPW publishes them); link tables `license_season` + `regulation_season` + `regulation_license` + `regulation_reporting` carry the join semantics. |
| Schema versioned from day one + three-place sync | [ADR-006](../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-018](../adrs/ADR-018-e03-schema-additions.md) | Any schema revision during E06 ships DDL + Pydantic + TypeScript in the same PR. New migration includes deny-all RLS inline (the `license_season` lesson). |
| Source citation discipline | [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-019](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md) | Every `regulation_record` has populated `source` with `document_type` ∈ `{annual_regulations, rule_change, emergency_order, correction, gis_layer}`. Multi-source merges follow `correction > annual_regulations` ranking; new doc-types (e.g., `emergency_order`) fail loud and require ADR-019 amendment before they may participate. |
| Confidence calibration FINALIZE | [ADR-017](../adrs/ADR-017-confidence-calibration.md) | Framework unchanged from S03.11 verdict. `low`-tier rows that V1 MT didn't have are normal and not a framework signal. Correction-touched rows demote one tier (ADR-017 §4) — single demote per row regardless of count of corrections. |
| Derive-and-assert drift-guard | [ADR-020](../adrs/ADR-020-id-text-pk-slug-derivation.md) | **Mandatory:** `assert_id_matches` in CO `season_definition` and `license_tag` build functions (S06.6 + S06.7); `assert_dispatch_dict_drift_free` at module-load on the CO `reporting_obligation` dispatch dict (S06.9). **Carve-out preserved:** `db.upsert_jurisdiction_binding` is NOT instrumented (the helper already excludes identity fields from UPDATE — schema-level exclusion is strictly stronger). Link-table builders NOT instrumented (M1 regression-guard AST test enforces). |
| `role='no_hunt_zone'` enum | [ADR-021](../adrs/ADR-021-jurisdiction-binding-no-hunt-zone-role.md) (Accepted via S05.3.5) | E06's S06.10 binding-loader writes `role='no_hunt_zone'` directly for the **9 genuine no-hunt-zone S05.4 rows** (4 NPs + 5 NMs); DDL CHECK constraint permits the value. **⚠️ AFA carve-out (Known Issue #12, surfaced via S06.5 2026-06-18)**: the 10th S05.4 row (`CO-restricted-united-states-air-force-academy-geom`) is a regulated-access HUNTING area (GMU 512 carries CPW hunt codes; escorted rifle deer hunts) — **NOT a no-hunt zone**. S06.10 must NOT bind AFA `role='no_hunt_zone'`; PM-recommended option (a) for V1 is `role='other_overlay'` for that single row (option (b) `kind` reclassification deferred to V2). S06.10 implementer splits the loop: 9 rows → `no_hunt_zone`, 1 row → `other_overlay`. See Known Issue #12 + the S06.10 spec's inline forward-note. |
| State-adapter isolation | [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) | All CO-specific code in `ingestion/states/colorado/`. Zero `ingestion/ingestion/lib/` edits unless extending a state-agnostic primitive (S05.5 set the precedent for this; same pattern applies if E06 surfaces a CPW-only pdfplumber idiom). `TestNoLibImports` / `TestNoColoradoLeakIntoSharedLib` AST guards stay green. |
| Cross-state spatial discipline | Handoff §8 #5; M1 S03.10 pattern | Every E06 SQL query that scopes to GMUs carries an explicit `state = 'US-CO'` filter (param-bound). The S05.6 scaffold at [`ingestion/states/colorado/load_jurisdiction_bindings.py`](../../../ingestion/states/colorado/load_jurisdiction_bindings.py) pre-ships `_STATE: Final[str] = "US-CO"` + `_QUERY_NEARBY_GMUS_FOR_ZONE_SQL` for S06.10 to import + extend. Cross-state pollution regression test `test_co_binding_loader_sql_filters_by_state_co_pollution_guard` passes in CI; PRD 002 success criterion #4 verifies the discipline. |
| `parameters` jsonb escape hatch | [ADR-012](../adrs/ADR-012-draw-mechanics-sibling-entity.md) | `draw_spec.parameters` is a CO-adapter-only escape hatch. Shared code never reads it. Every CO `draw_spec` ships `parameters=null` until a CPW quirk genuinely requires it; every candidate is a flag-and-discuss event per R2 mitigation. |
| Test-suite regression posture | Handoff §8 #8; R8 | Additive tests only. M1 + E05 baseline at **1346 + 2 skipped** (post-PR #63 hygiene fixes); E06 grows the baseline without subtracting. Any Montana-test edit is a flag-and-discuss event. |
| Recurring-RLS-gap discipline | M2 open question (E04 §"Known Issues to Escalate" #1) | If E06 adds any new `public.*` table (e.g., via Q18 resolution), the migration includes its own deny-all RLS inline + RLS verification queries follow the M1 UAT canonical pattern. RLS gap persists for any future M2/M3 work that adds tables. |

### "Flag" operational definition (used throughout)

Per [`docs/planning/epics/completed/E03-deferred-items/README.md`](completed/E03-deferred-items/README.md), an E06 implementer who "flags" a finding **must** do all four:

1. Append a structured artifact entry to the relevant file under `docs/planning/epics/completed/E03-deferred-items/<topic>.md` (durable) OR to the active story's working note under `docs/planning/epics/E06-confidence-findings/<story>.md` (calibration; deletes at `m2` tag).
2. Emit a `_LOGGER.warning(...)` at ingest with row id + source span + matched pattern.
3. Once a second entry lands in any deferred-items file, add a one-line pointer in [`docs/open-questions.md`](../open-questions.md) (the 2+-entries trigger).
4. Surface flagged counts in the run summary (e.g., `TOTAL: NNN bindings; FLAGGED: M deferrals`) and list them by category in the PR description.

Flags are never silently dropped, special-cased, or committed without PM consolidation. The PM consolidates and authors any new open-questions entry after review.

---

## Inputs from E05

| Artifact | Source | Use |
|---|---|---|
| CO GMU geometry rows | S05.2 production write (~186 polygons, `kind='gmu'`, ids `CO-GMU-{GMUID}-geom`) | S06.10 binding loader FKs to these from `jurisdiction_binding.geometry_id`. Group B operator-pending write is the hard precondition. |
| CO statewide geometry | S05.0 production write (`CO-STATEWIDE-geom`, `kind='state'`) | S06.6 statewide-anchor `regulation_record` rows (CO analog of `MT-STATEWIDE-bear` / `MT-STATEWIDE-antelope`) bind to this. |
| CO federal restricted-area rows (10) | S05.4 production write (`kind='restricted_area'`, ids `CO-restricted-{slug}-geom`, `verbatim_rule=None`) | S06.5 populated `verbatim_rule` 2026-06-18 (Group B operator-pending; D5=(b) split-provenance — `source` stays PAD-US `gis_layer`). **S06.10 binding loader splits the role assignment** (per Known Issue #12, S06.5 closure 2026-06-18): the **9 NPS rows** (4 NPs + 5 NMs) get `role='no_hunt_zone'` per ADR-021; the **1 AFA row** (`CO-restricted-united-states-air-force-academy-geom`) gets `role='other_overlay'` per PM-recommended V1 option (a) — AFA is a regulated-access HUNTING area (GMU 512 carries CPW hunt codes; escorted rifle deer hunts), NOT a no-hunt zone. |
| `geometry-overlays.json` fixture + `geometry-overlays-dropped.json` audit log | S05.5 Group B operator-pending generation | S06.10 binding loader reads the kept fixture as `geometry-overlays.json × regulation_record` cross product (mirrors S03.10's MT pattern). |
| `EXPECTED_CO_RA_ORPHAN_IDS` frozenset (10 ids) | S05.5 `build_overlay_fixture.py` constant | S06.10 binding loader's no-hunt-zone-nearby-binding logic uses this allowlist to identify the 10 orphans that get the `_QUERY_NEARBY_GMUS_FOR_ZONE_SQL` "nearby" treatment. |
| `_STATE` + `_NO_HUNT_ZONE_NEARBY_DISTANCE_M` + `_QUERY_NEARBY_GMUS_FOR_ZONE_SQL` + `query_nearby_gmus_for_zone()` reference function | S05.6 scaffold at `ingestion/states/colorado/load_jurisdiction_bindings.py` | S06.10 binding loader imports these directly (the scaffold has no `main()` yet — S06.10 adds it). Distance is `%s`-bound to the named constant per the S05.6 Stage-6 Critical fix; recalibration in E06 flows via the constant. |
| `spatial-test-points.json` | S05.7 Group B operator-pending generation via `extensions.ST_PointOnSurface` | Available for S06.10 regression/UAT spot-checks if needed (not a hard dependency). |
| `multipart-gmus.json` analytics fixture | S05.2 Group B operator-pending fixture | Available for S06.10 multi-part GMU verification (not a hard dependency). |

**Operator Group B precondition.** S05.0 + S05.2 + S05.3.5 + S05.4 + S05.5 + S05.7 Group B writes remain outstanding at E06 plan time. **S06.6 onward cannot execute against live state until the operator runs:** `supabase db push` (S05.3.5 migration) → `load_state_boundary` (S05.0) → `load_gmus` (S05.2) → `load_restricted_areas` (S05.4) → `build_overlay_fixture` (S05.5) → generate `spatial-test-points.json` (S05.7). Once captured, PM ticks Group B ACs in follow-up doc-only commits. **E06 implementation can begin against dry-run state for S06.0 through S06.5** (PDF fetch + extraction + schema prep are decoupled from CO geometry rows); S06.6 onward requires live state.

---

## Working artifacts and deferred items

| Directory | Retention | Use |
|---|---|---|
| `docs/planning/epics/E06-confidence-findings/` | Deletes at `m2` tag per ADR-017 §6 | Per-story closure notes (working scratch), Group B verification records, UAT capture, calibration spot-checks. PM creates per story as it closes. The durable synthesis (if any) migrates to a M2-level synthesis report outside this dir at milestone close — analog of M1's `E03-confidence-calibration-synthesis.md` (which survived `m1` because it lives outside `E03-confidence-findings/`). |
| `docs/planning/epics/completed/E03-deferred-items/` | Survives past `m2` | New entries land here per the 4-step flag protocol when an E06 finding extends one of the four existing files (`draw-mechanics.md`, `cwd-sampling-modeling.md`, `closure-temporal-anchors.md`, `README.md` protocol). PM may also flag a brand-new deferral file here only after the human approves the topic and naming. |

---

## Stories

### S06.0: Pre-E06 decisions + schema-prep gate

**Status:** Complete — decisions captured 2026-06-08; decision memo at [`E06-confidence-findings/S06.0.md`](E06-confidence-findings/S06.0.md). All 6 decisions resolved to a no-code path: D1=(c) license-keyed, D2=hardcoded path, D3=`_STATE` (rename ships alongside S06.10), D4=CPW URL **RESOLVED 2026-06-08** (Artemis-hosted 2026 brochure pinned + SHA-256 + cover-2026 confirmed; S06.1 fully unblocked), D5=(b) split-provenance, D6=helper built in S06.5. Schema-gap read-through: **no gap fires → no migration**; test baseline unchanged (1346 + 2 skipped). All 12 S06.0 ACs satisfied (AC #132/#133 closed by the D4 resolution captured in the memo §D4).

**As a** developer entering E06
**I want** the human-decided answers to the pre-registered decisions captured below, plus any pre-CO-data schema gaps closed by a new timestamped migration, before story-spec drafting for S06.1+ begins
**So that** E06's story specs reference firm decisions and the schema is ready for the regulation-text adapters

**UAT: no** (verification-gated against the 5 decision items + the schema-gap read-through)

**Context:**

S05.4 + S05.5 + S05.6 surfaced 5 pre-registered decisions that the PM cannot resolve autonomously. Each requires a human decision before the downstream story spec drafts. The PM drafts a decision memo per item and surfaces all 5 to the human in one flag-and-discuss session at S06.0 open; the human's answers go into the relevant story specs as locked constraints.

This story also re-reads PRD 002 + the M2 PM prompt for any pre-CO-data schema gaps surfaced by the architecture-vs-CO-data delta. If a gap exists (analog of S04.6 if-it-had-fired), S06.0 ships a new timestamped migration with three-place sync (Python + TS + DDL) + inline deny-all RLS in the same PR. If no gap exists, S06.0 documents the read-through in the closure note and ships no migration.

**Pre-registered decisions (5):**

1. **Q18 license-keyed disposition** — E05 S05.3 empirically confirmed CO publishes no CWD-zone geometry (license/hunt-code-keyed model). PM recommendation surfaced at S05.3 closure: retain Q18's V1 license-keyed disposition (option (c) — 0 typed CWD `reporting_obligation` rows; text in `regulation_record.additional_rules`). **E06's final call is required BEFORE S06.9 spec drafts.** If the human selects (a) zone-keyed or (b) license-keyed-as-typed-rows, S06.9's spec changes materially.
2. **Known Issue #6 — `_VALID_ROLE_FOR_E03` subset gate for CO no-hunt zones** (per [E05 epic Known Issues item #6](completed/E05-colorado-geometry-ingestion.md)). MT's `_VALID_ROLE_FOR_E03` frozenset deliberately does NOT carry `no_hunt_zone` — it gates only overlay-**fixture** child rows. E06's CO binding-loader (S06.10) must decide whether CO no-hunt zones flow through the overlay-fixture path with `role_for_e03='no_hunt_zone'` (requires the gate widened) or a separate hardcoded path (gate stays narrow; mirrors MT's `_build_no_hunt_zone_bindings`). **Decision required BEFORE S06.10 spec drafts.**
3. **`_STATE` vs `CO_STATE_CODE` naming unification** — the S05.6 scaffold introduces `_STATE = "US-CO"` to mirror MT's binding-loader convention; the 4 existing CO loaders (S05.0/S05.2/S05.4/S05.5 + `build_overlay_fixture.py`) use `CO_STATE_CODE = "US-CO"`. **E06 picks one and migrates** — surface to human at S06.0 open. If `_STATE` wins (E06 PM recommendation: yes, matches MT precedent), the unification ships as a small follow-up edit alongside S06.10. If `CO_STATE_CODE` wins, the S05.6 scaffold gets renamed alongside S06.10.
4. **CPW Big Game brochure URL is a hard precondition for S06.1** — all four candidate URLs returned 404 on 2026-06-03 per `docs/research/colorado-restricted-areas-evaluation.md`. The operator must resolve the canonical 2026 brochure URL (the brochure is the primary source for E06 regulation_record text AND the deferred `verbatim_rule` population for the 10 S05.4 no-hunt-zone geometry rows). **PM cannot guess the URL**; surface this as the first item in the S06.0 decision memo and pause S06.1 until URL HEAD-verified live.
5. **Single-source-field provenance for the 10 S05.4 no-hunt zones** — the `geometry.source` field on those rows is currently the PAD-US citation (`co-usgs-padus-arcgis-Federal_Fee_Managers_Authoritative_PADUS-0-2026`, `document_type='gis_layer'`). When E06 populates `verbatim_rule` from the CPW Big Game brochure, the regulatory authority for the prohibition is CPW (`document_type='annual_regulations'`) — the geometry provenance is PAD-US. **Single-field on `geometry` forces a choice:** (a) UPDATE `source` to the CPW brochure citation when `verbatim_rule` populates (geometry provenance lost from `source` field); (b) accept split-provenance with PAD-US winning the `source` field; (c) ADR + migration adding a multi-source provenance field. The research doc flagged this as unresolved; PM surfaces to human as a third candidate trigger for the multi-source-geometry-provenance Q (PRD 002 § "Open decisions resolved during M2"). **Decision required BEFORE S06.5 spec drafts.**

**Schema-gap read-through:**

Re-read PRD 002 §"Decisions already made" + §"Open decisions resolved during M2" + the architecture.md data model + the [`colorado-draw-schema-proposal.md`](../../research/colorado-draw-schema-proposal.md) for any pre-CO-data schema gap that would block S06.6 → S06.10. Candidate gaps to evaluate (none expected to fire; record the read-through in the closure note either way):

- `PointSystem.kind` enum is currently 3 values (`preference_linear | bonus_squared | bonus_weighted`); **CO V1 ships every `draw_spec.point_system.kind = 'preference_linear'` per `colorado-draw-schema-proposal.md` §6**. The enum is read-only for E06 — any candidate to add a 4th value is a flag-and-discuss event requiring ADR + three-place sync + a new migration; the PM does NOT adopt silently
- `AllocationPool.selection` enum is currently 4 values (`rank_ordered_by_points | unweighted_random | squared_weighted_random | linear_weighted_random`); **CO V1 ships only `rank_ordered_by_points` + `unweighted_random`** (the 80/20 hybrid + non-hybrid 100/0 single-pool shapes per the proposal §1); `linear_weighted_random` is reserved for V2 moose/sheep/goat per the proposal §8 #5 (out of V1 species scope). Any 5th value is a flag-and-discuss event requiring ADR
- `ReportingObligation.kind` enum is currently 6 values (`harvest_report | mandatory_check | tooth_submission | hide_skull_presentation | cwd_sample | other`); any new value is flag-and-discuss before adopting (per S06.9 ADR-required-amendment discipline)
- `SourceCitation.document_type` enum is currently 5 values (`annual_regulations | rule_change | emergency_order | correction | gis_layer`); **two flag-and-discuss surfaces apply**: (a) literal extension (rare; new `document_type` value), (b) ADR-019 rank extension (more likely; existing value newly participates in a regulation-text merge — `rule_change` / `emergency_order` / `gis_layer` cases per ADR-019 §"Decision" item 5). Either case requires ADR-019 amendment before participation
- `ClosurePredicate` needs `effective_after: date | None` (the `closure-temporal-anchors.md` ADR-candidate; trigger condition: CO closure conditional on BOTH a quota threshold AND a calendar gate)
- New `public.*` table for the Q18 outcome if the human picks option (a) or (b) over (c)
- `draw_spec` needs new structured fields per the Q12 outcome if a CPW quirk genuinely requires `parameters` use

If any gap fires, S06.0 ships a coupled-PR migration; otherwise S06.0 is decision-memo + closure-note only.

**Deliverables:**

- `docs/planning/epics/E06-confidence-findings/S06.0.md` — decision memo with the 5 pre-registered items, human answers captured verbatim, schema-gap read-through results, and any migration plan
- (Conditional) `supabase/migrations/<timestamp>_e06_schema_additions.sql` if a schema gap fires
- (Conditional) Pydantic + TypeScript edits in the same PR if a migration ships

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-006](../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-017](../adrs/ADR-017-confidence-calibration.md), [ADR-018](../adrs/ADR-018-e03-schema-additions.md), [ADR-019](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md), [ADR-020](../adrs/ADR-020-id-text-pk-slug-derivation.md), [ADR-021](../adrs/ADR-021-jurisdiction-binding-no-hunt-zone-role.md).

**Depends on:** E05 audit closure (✅ 2026-06-06). **Operator Group B writes from E05 are NOT a precondition for S06.0** — decisions + schema-prep are dry-run-decoupled.

**Unblocks:** S06.1 (CPW Big Game brochure URL resolved; resolves the S06.1 hard precondition), S06.5 (multi-source provenance for the 10 no-hunt zones decided), S06.9 (Q18 disposition decided), S06.10 (`_VALID_ROLE_FOR_E03` decision + `_STATE`/`CO_STATE_CODE` naming decided).

**Acceptance Criteria:**

- [x] `docs/planning/epics/E06-confidence-findings/S06.0.md` exists with the **5 pre-registered decisions plus the conditional 6th** (`db.update_geometry_verbatim`, the AC below) captured verbatim from the human's response (the 5 are enumerated under "Pre-registered decisions (5)" above and in the Open Questions section; the 6th is conditional on the S06.5 UPDATE-helper choice) — memo §"Pre-registered decisions (5 + conditional 6th)" D1–D6
- [x] CPW Big Game brochure 2026 URL resolved + HEAD-verified live (Content-Type: `application/pdf`, 200 response, **`Last-Modified` and `Content-Length` headers captured verbatim**) by the operator; URL + headers captured in S06.0.md. S06.1's first fetch compares actual response headers against the captured baseline and surfaces drift loudly before pinning `publication_date`. **The SHA-256 byte pin (S06.1's `expected_sha256` contract) is the authoritative drift gate; `Last-Modified` is a useful corroborating signal; `Content-Length` is INFORMATIONAL only — a `Content-Length` delta with a matching SHA-256 (benign CDN re-compression / transfer-encoding variance) must NOT raise `PdfFetchError`, only a SHA-256 mismatch does** — **RESOLVED 2026-06-08** (memo §D4 Resolution): Artemis URL `…/nr14312026internet.pdf` + `expected_sha256` byte-pin (authoritative gate) + ~96.7 MB/84pp metadata; **`Last-Modified: Wed, 04 Mar 2026 18:17:05 GMT` and `Content-Length: 96660296` HEAD-captured verbatim in the memo** (the drift baseline S06.1 inherits — `Content-Length` matches the operator's downloaded byte count exactly).
- [x] CPW Big Game brochure 2026 URL points to the **2026 brochure specifically** (not 2025, not a generic CPW publication): operator opens the PDF and confirms the cover page reads "2026" (or carries explicit 2026 regulatory-year text); confirmation captured in S06.0.md alongside the URL (per the S03.3 lesson: confirm cadence by reading the PDF, not the URL) — **RESOLVED 2026-06-08** (memo §D4): page 1 reads "2026 Colorado Big Game — Deer / Elk / Pronghorn / Moose / Bear / Bison; Primary draw deadline April 7, Secondary June 30."
- [x] Q18 disposition recorded: license-keyed option (c) confirmed OR option (a)/(b) chosen with rationale; S06.9 spec implications noted — **option (c) license-keyed confirmed** (memo §D1; 0 typed CWD `reporting_obligation` rows, CWD text in `regulation_record.additional_rules`; S06.9 implications noted)
- [x] Known Issue #6 decision recorded: subset-gate vs hardcoded path for CO no-hunt zones; S06.10 spec implications noted — **hardcoded path confirmed** (memo §D2; gate stays narrow at 4 values, CO mirrors MT `_build_no_hunt_zone_bindings`; S06.10 implications noted)
- [x] `_STATE` vs `CO_STATE_CODE` decision recorded with migration plan named — **`_STATE` wins** (memo §D3; 4 CO loaders renamed `CO_STATE_CODE → _STATE` alongside S06.10, not in S06.0)
- [x] Multi-source provenance decision recorded for the 10 S05.4 no-hunt-zone geometry rows; **if option (a) [UPDATE `source` to CPW] is chosen, the decision memo names every downstream consumer of `geometry.source.document_type` that would observe the `gis_layer` → `annual_regulations` transition** (grep `geometry.source.document_type` across `mcp-server/` + `web/` + `ingestion/`) and documents the semantic-drift consequence; **if option (c) [new multi-source provenance field] is chosen, ADR drafted + Pydantic `Geometry` model amended + TypeScript `Geometry` type amended + `architecture.md` § Schema types updated, all in the same PR as the migration** (three-place sync per ADR-006); S06.5 spec implications noted — **option (b) split-provenance confirmed** (memo §D5; PAD-US wins `source`, CPW text via `verbatim_rule` only; no migration. Option-(a) consumer grep recorded anyway: zero runtime consumers, only the type def at `mcp-server/src/types/schema.ts:50`)
- [x] **Conditional 6th decision** — fail-loud `db.update_geometry_verbatim` helper for S06.5's targeted UPDATE: decision recorded (add new `db.py` helper analog of `update_legal_description` vs in-script UPDATE); if helper added, fail-loud on `cur.rowcount == 0` (matches post-S03.6 pattern) — **decision recorded: targeted helper built in S06.5, not S06.0** (memo §D6; no cross-story encoding contract to lock; fail-loud on `cur.rowcount == 0`, touches only `verbatim_rule`)
- [x] Schema-gap read-through completed and documented; if no gap: closure note records "no schema additions"; if gap: timestamped migration + inline RLS shipped in same PR — **no gap fires** (memo §"Schema-gap read-through"; all 7 candidates evaluated against live schema with file:line evidence; no migration)
- [x] **If schema-gap fires:** three-place sync verified — every new DDL value/column/type appears in `ingestion/ingestion/lib/schema.py` Pydantic dataclasses + `mcp-server/src/types/schema.ts` TypeScript types + `docs/architecture.md` § Schema types in the same PR (verified by grep across all three; mirrors S03.0 / S05.3.5 precedent); RLS verification queries (`pg_policies` + `information_schema.table_privileges`) executed against the migration target table — **vacuously satisfied: no gap fires → no migration → no sync/RLS needed**
- [x] Test baseline unchanged (1346 + 2 skipped) if no migration ships; if migration ships, additive tests only; no regressions — **unchanged at 1346 + 2 skipped** (no Python edits; verified 2026-06-08)
- [x] No production-DB writes from the build session (S06.0 is decision-memo + optional schema migration only; live `supabase db push` is operator-driven) — **none; decision-memo only**

---

### S06.1: CPW PDF fetch infrastructure + CO sources.yaml `pdfs:` section

**Status:** Closed at-merge 2026-06-09 — squash-merged to main as **PR #66 / `abc6c21`** from `feat/S06.1-cpw-pdf-fetch-infra` (5 pre-squash commits). **Second E06 PR**. **Group A satisfied at-merge**; **Group B operator-pending** (AC #188 per-PDF manifest commits at first fetch — S03.1 "infrastructure-met, fixture-deferred" posture). **What shipped**: (1) `ingestion/states/colorado/fetch_pdfs.py` (new, ~285 LOC, fail-loud aggregating orchestrator) — path/docstring/argparse-substituted copy of `states/montana/fetch_pdfs.py` with byte-identical fail-loud aggregation logic, plus one post-review line passing `expected_sha256=entry.get(...)` to `fetch_pdf`; reuses shared-lib `pdf_fetch.fetch_pdf` + `PdfMetadata` + `PdfFetchError`. (2) `ingestion/states/colorado/sources.yaml` — new top-level `pdfs:` key alongside the existing `gis_layers:` (S05.1), with **two operator-resolved fully-pinned CPW PDFs** (both on the CO State Publications Library "Artemis" serial NR14.31/INTERNET; both SHA pins carry `# pragma: allowlist secret`; no `pending: true` entries — both URLs resolved at S06.0/D4): `co-cpw-big-game-2026-brochure` (`annual_regulations`, 84 pp, SHA-256 `38cf26e1…3582b3`, `publication_date='2026-03-04'`); `co-cpw-big-game-2026-correction-2026-02-19` (`correction`, 2 pp, SHA-256 `8eddff70…71dbf0`, `publication_date='2026-02-19'`). (3) `ingestion/states/colorado/fixtures/.gitignore` — `*.pdf` + `*-pending-reextraction.flag` rules added; per-PDF manifests committable. (4) Tests: `ingestion/tests/test_fetch_co_pdfs.py` NEW (24 tests); `test_pdf_fetch.py` +6 lib pin-gate tests. (5) `docs/planning/epics/E06-confidence-findings/S06.1.md` closure note (Group A/B split + S06.4 moose-only forward-note + pin-enforcement record; deletes at `m2` tag per ADR-017 §6). **Two post-merge-review fixes** (both folded into the branch before merge): (i) **Unenforced SHA pin** (P2, fixed root-cause). The orchestrator never passed `expected_sha256` to `fetch_pdf`, and the lib had no param for it — the only SHA gate compared a re-fetch against a prior committed manifest, so the first fetch accepted any bytes as baseline. CO was the first state with real pins, so this had teeth. Fixed by adding a **state-agnostic, opt-in `expected_sha256` param** to `pdf_fetch.fetch_pdf` that enforces a real pin before any write on every fetch (incl. first); `"unknown"`/absent skips (so MT, all-unknown, is unaffected); malformed/non-string fails loud. **Complements — does not replace — the manifest re-fetch drift gate**. Locked by 8 new tests. (ii) **Doc scope contradiction** (P2, doc-only). The closure note claimed "zero lib edits" (true for the initial build) while also describing the post-review lib edit. Reconciled to the shipped state. **Scope guarantees / decisions**: **ADR-005 holds** — the one shared-lib edit is state-agnostic; `TestNoColoradoLeakIntoSharedLib` + `TestFetchPdfNoStateAdapterImports` green. **But S06.1 as shipped is NOT a zero-lib-edit story** (noted in the closure note); the spec's AC #192 zero-lib-edit constraint is amended in this closure to reflect the state-agnostic lib extension shipped via post-review fix-up (precedent: S05.5 set the analogous pattern for state-agnostic-clean expansions to `overlays.py`). **No ADRs created**; refines ADR-001 (SHA-pin fail-loud), ADR-005 (state-adapter isolation — the lib edit is state-agnostic-clean expansion, same pattern as S05.5's `overlays.py` extension), ADR-014 (`document_type`), ADR-019 (correction precedence — registered; expected CO V1 no-op — see S06.4 forward-note). **No schema / three-place-sync changes; no `db.py` touches; no MT-code behavior change; no TS-stack diffs; no production-DB writes; no live network in the build session.** **Test baseline shifted 1346 → 1376 + 2 skipped** (+30 additive: 24 from `test_fetch_co_pdfs.py` + 6 from `test_pdf_fetch.py` lib pin-gate tests; new 1376 baseline holds going forward across S06.2–S06.11). ruff + mypy clean; `mcp-server` + `web` tsc exit 0; detect-secrets passed. **Updated `.roughly/known-pitfalls.md`**: rewrote the S03.1 `expected_sha256` pitfall into a **two-gates model**; added a "fork-a-state-adapter-module → port its test classes" pitfall. **doc-writer re-flagged `known-pitfalls.md` at ~1065 LOC** as reorg/dedup candidate (recurring since S05.x). **S06.4 forward-note (carry into S06.4 spec)**: the 2026 corrections PDF is **moose-only** (two omitted moose hunt codes, p.61) → **out of V1 scope** → the ADR-019 `correction > annual_regulations` merge is expected to be a **CO V1 no-op**. Registered for provenance; S06.4 should confirm inert against the full 2-page extract before declaring it so. **Unblocks: S06.2 (conditional), S06.3 (Big Game brochure extraction), S06.4 (Black Bear), S06.5 (no-hunt-zone `verbatim_rule`)**. Note S06.3+ are still gated on the operator's first live `fetch_pdfs.py` run producing the committed manifests (Group B; the first-fetch SHA pin is now auto-enforced lib-side, so no manual SHA-verification step is needed on the operator's first run).

**As a** developer preparing to extract CPW regulation text
**I want** CPW PDF fetch infrastructure operational, with HEAD-verified URLs pinned in `sources.yaml`, SHA-256-anchored fixtures, drift-detection markers, and per-PDF manifests
**So that** S06.3 / S06.4 / S06.5 extraction stories execute against pinned source artifacts with operator-confirmable provenance

**UAT: no** (verification-gated against URL HEAD checks + manifest commits)

**Context:**

Mirrors M1's S03.1 PDF fetch infrastructure pattern, reused at the shared-library level. The shared lib (`ingestion/ingestion/lib/pdf_fetch.py` and `pdf.py`) was built and locked at M1; CO inherits the same primitives. State-adapter code lives in `ingestion/states/colorado/`. Per M1's S03.1/S03.3 lesson, **pre-validated URLs do not survive contact with the live CDN**: every URL is HEAD-verified live before pinning, and a SHA-256 drift on re-fetch raises `PdfFetchError` and writes a `<id>-<publication_date>-pending-reextraction.flag` marker that S06.3/S06.4/S06.5 refuse to start against.

S05.4 closure noted that the CPW Big Game brochure URL is unresolved (404 on all 4 candidate URLs as of 2026-06-03). **The URL is resolved as part of S06.0 and is hard-precondition for S06.1.** S06.1 does not start until S06.0 records the live-HEAD-verified URL.

CO `sources.yaml` already has the `gis_layers:` section (S05.1) and a reserved comment for the `pdfs:` section. S06.1 adds the `pdfs:` section with entries for:

- **CPW Big Game brochure 2026** (primary regulation text) — `document_type: annual_regulations`; `publication_date` set to the HTTP `Last-Modified` header (per M1's S03.1 pitfall — slug ≠ cadence; confirm by reading the PDF itself, not the URL)
- **Any CPW species-specific supplements** (TBD — Black Bear may or may not be a separate brochure; structural-discovery happens at S06.1)
- **Any 2026 correction PDFs** (analog of MT's 2026-03-18 black bear correction; ADR-019 doc-type-precedence applies if a correction exists; entries with `pending: true` if URL is TBD — S06.3/S06.4/S06.5 won't start until populated)

**Deliverables:**

- `ingestion/states/colorado/fetch_pdfs.py` (new, ~230 LOC, fail-loud aggregating orchestrator) — mirrors `ingestion/states/montana/fetch_pdfs.py` shape; reuses `ingestion/ingestion/lib/pdf_fetch.py:fetch_pdf` + `PdfMetadata` + `PdfFetchError`
- `ingestion/states/colorado/sources.yaml` — extended with new `pdfs:` top-level key alongside the existing `gis_layers:`
- Per-PDF manifests committed at first fetch (mirrors S05.0/S05.2/S05.4 manifest-commit pattern); raw PDFs gitignored at ~MB per source per the existing fetch-pdfs convention
- Drift-marker policy reused as-is — SHA-256 drift on re-fetch raises `PdfFetchError` and writes a `<id>-<publication_date>-pending-reextraction.flag` marker

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-019](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md).

**Depends on:** S06.0 (CPW Big Game brochure URL resolved + live-HEAD-verified).

**Unblocks:** S06.2 (conditional pdfplumber extension), S06.3 (Big Game brochure extraction), S06.4 (Black Bear extraction if separate), S06.5 (no-hunt-zone `verbatim_rule` population).

**Acceptance Criteria:**

**Group A — file-level / static (satisfied at-merge `abc6c21`):**

- [x] `ingestion/states/colorado/fetch_pdfs.py` exists (~285 LOC), mirrors MT's `fetch_pdfs.py` shape, reuses shared-lib primitives; `TestNoColoradoLeakIntoSharedLib` stays green
- [x] `ingestion/states/colorado/sources.yaml` `pdfs:` section added with the 2026 CPW Big Game brochure entry (URL HEAD-verified live at S06.0/D4; Content-Type: `application/pdf`, 200; cover-page-2026 confirmed)
- [x] 2026 CPW Big Game correction PDF entered with HEAD-verified URL (`co-cpw-big-game-2026-correction-2026-02-19`; ⚠️ originally characterized as "moose-only" at S06.1 close — **S06.4 closure 2026-06-15 corrected this**: the correction is **moose + elk** (page 2 is an elk-muzzleloader correction `E-M-…`, p.44). Inert for bear (S06.4 confirmed); **but S06.3 elk re-extraction question is open — see Known Issue #10**); no `pending: true` entries — both URLs operator-resolved at S06.0/D4
- [x] **`pending: true` entries semantics defined** (no `pending: true` entries shipped in S06.1 — but `fetch_pdfs.py` raises `PdfFetchError` if invoked against any future `pending: true` entry, naming the source id; downstream stories S06.3 / S06.4 / S06.5 refuse to start against any `pending: true` entry in their declared source set)
- [x] The drift-marker policy fires on a transition from `pending: true` → resolved URL (the first-fetch manifest is committed in the same PR as the URL resolution; later fetches compare against the committed manifest per the standard SHA-256 pin contract)
- [x] `expected_sha256` in `sources.yaml` per non-`pending` entry (`38cf26e1…3582b3` for brochure; `8eddff70…71dbf0` for correction); **first-fetch SHA-256 mismatch now raises `PdfFetchError` (post-review state-agnostic lib edit — see closure narrative; locked by 8 new tests in `test_pdf_fetch.py`)**; complements the manifest re-fetch drift gate (two-gates model)
- [x] Drift-marker creation behavior verified via unit test (24 tests in `test_fetch_co_pdfs.py`)
- [x] Test baseline grows additively only; new tests at **1346 → 1376 + 2 skipped** (+30: 24 in `test_fetch_co_pdfs.py` + 6 lib pin-gate tests in `test_pdf_fetch.py`); ruff + mypy clean; tsc exit 0; detect-secrets passed
- [x] **AC amended at closure** — `ingestion/ingestion/lib/pdf_fetch.py` received **one state-agnostic lib edit** post-merge-review (the SHA-pin enforcement primitive); the edit is state-agnostic-clean per `TestFetchPdfNoStateAdapterImports` (mirrors S05.5's `overlays.py` state-agnostic expansion precedent); AST CO-leak guard test passes; ADR-005 holds (lib expansion, NOT CO-specific contamination)

**Group B — operator-driven (open; not blocking S06.1 close per S03.1 "infrastructure-met, fixture-deferred" posture):**

- [ ] Per-PDF manifests committed at first fetch (analog of S05.0/S05.2 manifest commits) — *operator-pending; first-fetch SHA pin is now auto-enforced lib-side, so no manual SHA-verification step needed on the operator's first run*

Operator runbook for first-fetch lands in `docs/planning/epics/E06-confidence-findings/S06.1.md`; once captured, PM ticks the Group B box in a follow-up doc-only commit.

---

### S06.2 (conditional): pdfplumber primitives extension

**Status:** Not Started; **may be omitted if no CPW-specific table shape requires a primitive extension** (PM expectation per M2 PM prompt line 198)

**As a** developer extending state-agnostic PDF extraction primitives
**I want** any CPW-specific table shape M1's pdfplumber primitives don't already handle to be supported by extending `ingestion/ingestion/lib/pdf.py`
**So that** S06.3 / S06.4 extraction adapters consume shared primitives, not state-specific extraction code in `ingestion/ingestion/lib/`

**UAT: no**

**Context:**

Most CO extraction is expected to reuse M1's primitives (`PdfDocument`, `open_pdf`, `iter_pages`, `extract_text`, `extract_tables`, `find_section`, `PageReference` + `page_reference_to_str` + `ConfidenceTier` + `min_tier` + `demote_one_tier` + `PdfExtractionError`) as-is. The library has 8 pitfalls accumulated against `pdfplumber` 0.11.x: column-collapse vs. byte-exact text; `find_tables()` not `extract_tables()` for bbox; lexicographic-trap on raw tier strings; `-` as universal absence sentinel; merged-cell carry-forward via `None`; one-table-per-page-not-per-HD; FWP three-column layout; rotated chapter sidebars + multi-page headings.

**Trigger condition for S06.2 to ship:** the S06.3 implementer (during Stage-1 discovery against the live PDF) finds a CPW table shape that doesn't fit the M1 primitives' contract. Examples of triggers: a CPW table cell uses a non-`-` absence sentinel; a CPW page uses 4-column layout instead of 3; CPW carries species fan-out via a column not a row.

If no trigger fires, S06.2 is omitted entirely (story header removed mid-epic; closure note records "no primitive extension needed; M1 primitives sufficient"). If a trigger fires, S06.2 ships as a state-agnostic-clean extension with `TestNoColoradoLeakIntoSharedLib` (S05.1's CO-isolation guard) staying green and 1+ unit test in `ingestion/tests/test_pdf.py` per new primitive.

**Acceptance Criteria (only if S06.2 ships):**

- [ ] Extension to `ingestion/ingestion/lib/pdf.py` is state-agnostic-clean (no CO-specific strings, no CPW-specific URLs, no CO-state-code constants); `TestNoColoradoLeakIntoSharedLib` stays green
- [ ] New primitive has 1+ unit test in `ingestion/tests/test_pdf.py`; lexicographic-trap-style regression test if applicable
- [ ] Module docstring at `pdf.py` documents the new primitive + cleanup rule scope
- [ ] No regression to M1's 8 existing pitfalls; M1 test count grows additively

**If omitted:** closure note in `docs/planning/epics/E06-confidence-findings/S06.2.md` records "M1 pdfplumber primitives sufficient; no CPW-specific extension needed at S06.3 discovery time."

---

### S06.3: CPW Big Game brochure extraction (deer + elk + pronghorn)

**Status:** Closed at-merge 2026-06-13 — squash-merged to main as **PR #67 / `08bf396`** from `feat/S06.3-cpw-big-game-extraction` (**third E06 PR**). **The load-bearing E06 extraction story.** New `ingestion/states/colorado/extract_big_game.py` (**2,685 LOC**, state-agnostic-clean) parses the 84-page CPW Big Game brochure into a deterministic committed artifact `extracted/big-game-2026.json` — structural analog of MT's `extract_dea.py`. Documentation + extraction only — no DB writes, no schema/migration, no `db.py` touches. **Dry-run-decoupled** from the outstanding E05 operator Group-B geometry writes. Merge diff: 12 files, **+5,210 / −3 LOC**. **Artifact**: JSON array of **737 section records / 2,758 rows total**; confidence split `{high: 2170, medium: 583, low: 5}`; SHA-256 at-S06.3-close `3c2ecd90066cad3ec527f5ff18d054083d0f827485adae2337cde9f63cca015d` <!-- pragma: allowlist secret -->. **⚠️ Updated 2026-06-15 to `e5c7c33a728a95f3d2845894ce53d4de664ed20bfc40853eaa421ac8d12e6d1e`** <!-- pragma: allowlist secret --> via S06.4's coordinated `valid_gmus` cleanup (counts + confidence UNCHANGED; only field contents moved — prose qualifiers routed out of `valid_gmus` to `extras` per the "no broken windows" call). Two PDF manifests committed (brochure 2026-03-04 + correction 2026-02-19); raw PDF gitignored. **Test baseline shifted 1376 → 1498 + 3 skipped** (+122: 1,334-LOC `test_extract_co_big_game.py` + 7 `TestWriteExtractionArtifact` tests in `test_pdf.py`; new 1498 baseline holds going into S06.4). **Key decisions / real-PDF discoveries baked in** (per the S03.3 lesson — ≥9 real-PDF discoveries expected; CO surfaced its own constellation): (1) **CPW hunt-code grammar** `{Species}-{Sex}-{GMU}-{Season}-{Method}` (e.g. `D-M-020-O2-R`); pronghorn species letter = `A`; 3- and 4-digit GMUs both handled; `_HUNT_CODE_FRAGMENT_RE = [A-Z]-[A-Z]-\d{3}` is an unanchored fragment matcher with a clarifying comment explaining it intentionally matches inside 4-digit GMUs (dual-purpose: map-page safeguard + garbage-row filter); (2) **Season Choice (method letter `X`)** discovered live → mapped to `method_group="season_choice"`, `weapon_types=["archery", "muzzleloader", "any_legal_weapon"]`; how `X` licenses become `season_definition`/`license_tag` rows is **deferred to S06.7 — logged as Q20** in `docs/open-questions.md`; (3) **Plains whitetail detection** via `_WHITETAIL_UNIT_RE`; (4) **R14 uniform character-doubling recovery** at top of the table-row loop (a CPW PDF artifact); (5) **Empty-GMU sections page-disambiguated** so unparseable rows can't coalesce cross-page; `_section_sort_key` carries a page tiebreaker; section `gmu_code` is read from `rows[0]`, **NOT the map key**. **Cross-cutting infra change (affects future extractors — new convention)**: mid-story, cubic refused to review the PR ("108,187 changed lines" — the `indent=2` artifact was 103,854 lines, past cubic's 50k cap). `.gitattributes` did not help (GitHub counts raw diff lines). Resolved by **one-record-per-line serialization** (→739 lines), then **generalized into a shared helper**: `ingestion/ingestion/lib/pdf.write_extraction_artifact(records, path)` — state-agnostic, atomic, deterministic one-record-per-line serializer. **New extractors MUST use it** (S06.4 inherits as mandatory). Documented as a convention pitfall. **Carry-forward flag for PM**: MT's `dea-2026.json` is **47,956 lines (still `indent=2`)** — one bigger brochure from the 50k cap. Pitfall recommends migrating MT's three extractors to the helper at their next re-extraction (format-only, data-unchanged, re-pin SHA). **NOT done in S06.3** — surfaced as M2 hygiene candidate (see Known Issues to Escalate item #8 below). **Recurring-review note (PM awareness)**: the "monolithic extractor module" P2 was raised three times against this 2,685-LOC file. **Declined all three** (uniform single-module convention across all 4 MT + future CO extractors; coupling is test-mitigated; modularization is an ADR-level project-wide call, not an in-review per-story refactor). Rationale now recorded in `.roughly/known-pitfalls.md` so it stops being re-litigated. **ADRs / Q-status**: no ADRs created; refines ADR-001 (fail-loud), ADR-005 (state-adapter isolation — the new `write_extraction_artifact` lib helper is state-agnostic-clean; `TestNoColoradoLeakIntoSharedLib` green; mirrors the S05.5 / S06.1 state-agnostic lib-expansion precedent), ADR-008 (verbatim discipline), ADR-017 (confidence calibration unmodified per FINALIZE — `low=5` is data-shape signal not framework signal; PM surfaces counts, does NOT propose framework changes). **Q20 opened** in `docs/open-questions.md`: Season Choice → `season_definition`/`license_tag` modeling; decision deferred to S06.7. **UAT**: PM-run spot-check is the closure step (Group A code shipped + 1,341-LOC of tests verify determinism + structural invariants; faithfulness UAT against ≥4 representative GMUs across deer/elk/pronghorn ticks the final AC; runbook in `docs/planning/epics/E06-confidence-findings/S06.3.md` when captured). **S06.4 (Black Bear)** is next — **must use `write_extraction_artifact` from the start** per the new convention.

**As a** developer extracting CPW Big Game brochure regulation data
**I want** every applicable CO GMU's per-species regulation rows extracted into a deterministic JSON artifact with verbatim text + section context + confidence per ADR-017
**So that** S06.6 / S06.7 / S06.8 ingestion stories consume a structured artifact, not raw PDFs

**UAT: yes** — faithfulness review against the source PDF; mirrors M1's S03.3 DEA UAT pattern. PM-run UAT spot-check against ≥4 representative GMUs across the 3 species (deer / elk / pronghorn) before close.

**Context:**

CPW Big Game brochure is the primary source. CPW publishes structured per-GMU regulation tables analogous to MT's DEA booklet (S03.3). The exact table structure is TBD at S06.3 entry — Stage-1 discovery against the live PDF will surface: how species are partitioned (one section per species vs. unified table); how GMU codes are coded (CPW uses numeric GMU IDs; check whether GMU range syntax appears); whether per-GMU sections carry per-row apply-by / quota / weapon-type / season-window columns; whether antelope (pronghorn) has a STATEWIDE-equivalent row analog of MT's `900-20`.

**The S03.3 lesson is load-bearing: do not trust the spec's research notes against the live PDF.** Stage-1 discovery against the actual 2026 brochure surfaces all per-PDF reality. The implementer should expect ≥3 deviations from any pre-spec research notes (S03.3 had 9 real-PDF discoveries baked into the implementation; some PRs are larger than expected because real-PDF reality only surfaces at extraction time).

**Cleanup rules** (mirrors S03.3 module-docstring pattern; the implementer documents each rule with regex + scope + rationale + locking test name):

1. `-` as universal absence sentinel — null-out `-` in apply_by / quota_range / extras
2. Merged-cell `None` carry-forward for license codes (S03.3 pattern) IF CPW uses the same convention; document deviation otherwise
3. Multi-page section continuation suffix handling (S03.3 ` - Continued` pattern; check for CPW equivalent)
4. Whitespace collapse rule for extras-text only (S03.3 `re.sub(r"\s+", " ", ...)` per row at write-site)
5. ANY ADDITIONAL CPW-specific cleanup rule discovered mid-implementation lands as a 5th+ rule in the module docstring; AC #547 strict-parity discipline applies

**Output artifact:**

- `ingestion/states/colorado/extracted/big-game-2026.json` — list of `CpwSectionExtraction` (or species-specific structure surfaced at Stage-1; CO will likely use a sibling artifact split per species if CPW publishes them that way)
- Per-row schema: species, gmu_number, license_code, apply_by, quota, quota_range, weapon_types, residency, season_windows (1 row per row, NOT 1 row per HD — the per-row windows lesson from S03.3 UAT D1; per-row windows are LOAD-BEARING for license_season asymmetric coverage in S06.7), extras, page_reference, extraction_confidence (per ADR-017 `_assign_row_confidence` logic)
- Confidence rules: `high` for rows where every value field is present + non-`-`; `medium` for rows with ≥1 null/absent value; `low` reserved for genuinely-ambiguous rows (M1 had zero `low`; if E06 has even one, surface as Q18-style framework-vs-data signal to the human — ADR-017 §7 Trigger 2 may fire, but per S03.11 FINALIZE, the trigger is data-shape not framework-shape and the framework stays unmodified)

**Deliverables:**

- `ingestion/states/colorado/extract_big_game.py` (new, structural analog of MT's `extract_dea.py`; expected 1000-1500 LOC depending on CPW table-shape complexity)
- `ingestion/states/colorado/extracted/big-game-2026.json` — deterministic SHA-256 across re-runs; committed as the durable text-side fixture
- 30-100 unit tests in `ingestion/tests/test_extract_co_big_game.py` (new file; mirror S03.3's 84-test structure)

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md), [ADR-017](../adrs/ADR-017-confidence-calibration.md).

**Depends on:** S06.1 (CPW Big Game brochure pinned + HEAD-verified + fetched at known SHA).

**Unblocks:** S06.6 (regulation_record ingestion), S06.7 (link-table ingestion), S06.8 (draw_spec ingestion).

**Acceptance Criteria:**

**Group A — file-level / static (satisfied at-merge `08bf396`):**

- [x] `ingestion/states/colorado/extract_big_game.py` exists (**2,685 LOC**), state-agnostic-clean per `TestNoColoradoLeakIntoSharedLib` (the new `lib/pdf.write_extraction_artifact` helper is state-agnostic-clean expansion — mirrors S05.5/S06.1 precedent); single-writer contract (no DB imports — locked by AST guard test)
- [x] `extracted/big-game-2026.json` deterministic SHA-256 across two consecutive extraction runs. **⚠️ SHA pin lineage**: original at S06.3 close `3c2ecd90…015d` → S06.4 `valid_gmus` cleanup 2026-06-15 `e5c7c33a728a95f3d2845894ce53d4de664ed20bfc40853eaa421ac8d12e6d1e` <!-- pragma: allowlist secret --> → **S06.3.1 hygiene 2026-06-16 `9312e2595071a80cc317250504e4ba6a7eaaae33a201a313db275aa0f0c8bb2f`** <!-- pragma: allowlist secret --> (current). **Counts at S06.3 close: 737 sections / 2,758 rows. Counts at S06.3.1 close: 736 sections / 2,762 rows** (a now-empty mule_deer placeholder section collapsed once R16 gave its fused rows real GMU codes; +4 from R16-recovered codes). Confidence at S06.3 close: `{high: 2170, medium: 583, low: 5}`. **Confidence at S06.3.1 close: `{high: 2178, medium: 583, low: 1}`** (per S03.11 FINALIZE this remains data-shape signal not framework signal — ADR-017 unmodified; the single remaining LOW is section 416 heading-absorption residual, documented out of R16 scope). Re-pinned in `test_extract_co_big_game.py`. **⚠️ SHA pin advanced again 2026-06-16 via S06.3.1 R17 port + re-extraction**: `e5c7c33a…6d1e` → `9312e2595071a80cc317250504e4ba6a7eaaae33a201a313db275aa0f0c8bb2f` <!-- pragma: allowlist secret -->. Full lineage: `3c2ecd90…015d` (S06.3 close) → `e5c7c33a…6d1e` (S06.4 `valid_gmus` cleanup) → `9312e259…bb2f` (S06.3.1 R17 port). Counts: sections 737→736, rows 2758→2762; confidence high 2170→2178 / medium 583 / low 5→1; 4 previously-fused codes recovered (`D-M-082-O3-R`, `D-F-107-O1-R`, `A-M-004-O1-M`, `A-F-118-O1-R`).
- [x] Per-row windows extracted faithfully (the S03.3 UAT D1 lesson preserved — per-row variable fields are interpretive; section-level first-observation-wins is NOT faithful)
- [x] **ADR-008 paraphrase prohibition (extraction surface):** `verbatim_text` and `verbatim_rule` fields on every emitted row are byte-equivalent to `pdf.extract_text` output (S03.2 word-grouping baseline) for the source span; cleanup rules are the only permitted normalizations; cleanup-rules docstring grep-verified against runtime-applied normalizations
- [x] `pdf.extract_text` invoked WITHOUT `layout=True` anywhere in the extractor; AST guard test asserts no `layout=True` literal in the extraction module
- [x] Cleanup rules documented in module docstring with regex + scope + rationale + locking test name; AC #547 strict-parity discipline holds across the 5 documented CPW-specific discoveries (CPW hunt-code grammar + Season Choice X mapping + plains whitetail detection + R14 character-doubling recovery + empty-GMU page-disambiguation)
- [x] Confidence distribution in run summary: **`{high: 2170, medium: 583, low: 5}`**. Per S03.11 FINALIZE, `low=5` is data-shape signal NOT framework signal — surfaced for human review; ADR-017 framework unmodified
- [x] **1,341-LOC of tests** (1,334 in `test_extract_co_big_game.py` + 7 `TestWriteExtractionArtifact` tests in `test_pdf.py`); test baseline shifted 1376 → **1498** + 3 skipped (+122 additive)
- [x] **NEW shared lib helper** `ingestion/ingestion/lib/pdf.write_extraction_artifact(records, path)` — state-agnostic, atomic, deterministic one-record-per-line serializer (cubic 50k-line-cap workaround turned into a reusable primitive); **S06.4 must use it from the start** (new convention)

**UAT — PM-pending:**

- [ ] PM-run spot-check on ≥4 representative GMUs across the 3 species (deer / elk / pronghorn) cross-checked against the source PDF; closure note in `docs/planning/epics/E06-confidence-findings/S06.3.md` records the verification — *PM-pending; not blocking S06.4 dispatch since S06.4 is independent on its source PDF*

---

### S06.4: Black Bear extraction (CPW Black Bear brochure OR Big Game brochure section)

**Status:** Closed at-merge 2026-06-15 — squash-merged to main as **PR #68 / `51f6aa7`** from `feat/S03.4-black-bear-extraction` (**⚠️ branch-name caveat**: the branch is literally named `feat/S03.4-…` — a human typo at branch creation since S03.4 was M1's Montana black bear story in E03; the branch holds the S06.4 Colorado work; user acknowledged and chose to keep the name; commit messages are correctly scoped S06.4). **Fourth E06 PR.** Merge diff vs the S06.3-close base (`c3eb40b`): 11 files, **+7,561 / −744 LOC**. **Shipped as a separate extractor** (NOT folded into S06.3) — satisfies AC #344. Structural analog of MT's `extract_black_bear.py` for the correction-merge machinery; table parsing is big-game-like (CPW hunt-code grid, NOT MT's rotated per-BMU table). **What shipped**: new `ingestion/states/colorado/extract_black_bear.py` (**3,603 LOC**, state-agnostic-clean) parses the CPW Big Game brochure's bear section (PDF pages 72–77) into deterministic committed artifacts via the S06.3 `lib/pdf.write_extraction_artifact` helper (mandatory per new convention). **Artifacts (all committed)**: `extracted/black-bear-2026.json` — **172 records (169 sections + 1 reporting-obligation + 2 statewide-rule candidates) / 215 rows**; confidence `{high: 215, medium: 0, low: 0}`; **SHA-256 `7b35c202fd614f37fb529c2cc308fbf0004192eefd07fdf6963772dcc867d5f6`** <!-- pragma: allowlist secret --> (determinism-pinned). Plus `extracted/black-bear-2026-base.json` (Pass-1 base) + `extracted/corrections-2026-02-19.json` (Pass-2 operations `[]`, **inert for bear**). **Composition**: 137 limited_draw + 78 OTC rows across archery/muzzleloader/rifle × {limited, add-on OTC, standalone OTC, private-land OTC, plains OTC}. Hunt-code grammar `B-{sex}-{gmu}-{season}-{method}`; `species_group='black_bear'` (downstream S06.6 maps to DB `'bear'` per S03.6 fan-out convention). **Test baseline shifted 1498 → 1669 + 4 skipped** (+171 additive). ruff + mypy clean; detect-secrets clean. **⚠️ cubic was unavailable during the late post-restart review cycle** — gates rested on ruff/mypy/1669-suite + manual SHA/count/exclusion verification; PM may want a cubic pass when the environment is restored (the PM commit run below will re-confirm). **Key decisions / real-PDF discoveries (Cleanup Rules R1–R17)**: bear tables have **NO Sex column** (4-col Unit|Valid GMUs|Hunt Code|List; 5-col rifle adds Dates) — unlike deer/elk/pronghorn's 6-col; R14 character-doubling N/A for bear (codes extract clean). **Rule R16 — hunt-code embedded in prose**: recovered the Plains-OTC `B-E-087-U6-R` ("Sales agents only:" prefix) that an anchored regex was dropping. **Rule R17 — fused-row split**: pdfplumber merged two muzzleloader rows (missing inter-row ruling) into one cell-pair; split on multi-hunt-code cells, fail-loud on misalignment. Wired into all three row-walking paths (limited, OTC no-Dates, OTC has-Dates). **Three-pass correction merge** preserved as the inert-confirmation pathway (NOT bypassed); demote-once-per-row (ADR-017 §4); fail-loud on a future bear-targeting correction. **⚠️ Cross-story item — coordinated `valid_gmus` fix touched merged S06.3 code**: a review finding (prose like "private land only" / "Except Bosque del Oso SWA" / "Note: No hunting access to GMU 211" contaminating the structured `valid_gmus`) was real and present in **both CO extractors**. Per the "no broken windows" call, it was fixed in both: `valid_gmus` now holds the clean GMU list only; free-text qualifier routed to `extras` and appended to each section's `verbatim_text` (ADR-008 preserved). Embedded exclusion units (the excluded GMU 211; private land in 12, 23, 24) correctly stay in the qualifier. **`big-game-2026.json` was regenerated** — counts UNCHANGED (737 sections / 2758 rows), confidence UNCHANGED (`{high: 2170, medium: 583, low: 5}`), only field contents moved. **Its determinism SHA changed `3c2ecd90…015d` → `e5c7c33a728a95f3d2845894ce53d4de664ed20bfc40853eaa421ac8d12e6d1e`** <!-- pragma: allowlist secret --> and is re-pinned in `test_extract_co_big_game.py`. The S06.3 closure record's pinned SHA is now stale — annotated in this S06.4 closure for audit-trail clarity. The split logic was first placed in `lib/pdf.py`, then (second review finding) relocated out of lib into each CO extractor as a private `_split_valid_gmus` (CPW-specific; matches the per-extractor-duplication convention). **Net change to `ingestion/lib/pdf.py` is zero**. **No ADRs created**; refines ADR-001 (fail-loud), ADR-005 (state-adapter isolation; lib net-zero), ADR-008 (verbatim discipline), ADR-017 (confidence; `low=0` is data-shape signal not framework signal per FINALIZE), ADR-019 (correction precedence — confirmed inert for bear; **but see Known Issue #10 below** for the moose-only → moose+elk correction-content correction discovered by S06.4). **`.roughly/known-pitfalls.md` +56 LOC** — entries for: per-species column layouts differ; hunt-code-in-prose (R16); pdfplumber row-fusion split (R17, incl. the big-game-latent note); duplicate hunt codes are faithful (loader collapses); correction-PDF-contradicts-forward-note. **No schema/migration/three-place-sync/`db.py`/TS-stack changes; no production-DB writes.** **Group A satisfied at-merge**; **UAT (AC #343) PM-pending** (non-blocking for S06.5 dispatch — S06.5 depends on S06.0 provenance + S06.3 brochure, not bear). **S06.5 (no-hunt-zone `verbatim_rule` population) is next active.**

**As a** developer extracting CPW black bear regulation data
**I want** every CPW black-bear-applicable region's regulation rows extracted into a deterministic JSON artifact with verbatim text + section context + confidence
**So that** S06.6 / S06.7 / S06.9 ingestion stories consume the structured artifact

**UAT: yes** — faithfulness review against the source PDF; mirrors M1's S03.4 Black Bear UAT.

**Context:**

CPW black bear regulations may be a separate publication or a section of the Big Game brochure. The S06.1 discovery pass against the live brochure structure decides which. If separate, S06.4 ships as its own extractor following S03.4's pattern (which evolved through 12 real-PDF discoveries + a UAT-driven fix cycle); if integrated, S06.4 is folded into S06.3 as a per-species section (the species fan-out pattern stays the same).

**S06.1 forward-note (2026-06-09; ⚠️ CORRECTED 2026-06-15 by S06.4 closure):** S06.1 pinned the **2026 CPW Big Game correction PDF** (`co-cpw-big-game-2026-correction-2026-02-19`, 2 pp, `document_type='correction'`). S06.1's initial discovery characterized this as **moose-only** (two omitted moose hunt codes, p.61). **S06.4 build subsequently discovered this was incorrect**: page 2 of the correction PDF is an **elk-muzzleloader correction** (`E-M-…`, p.44). The correction is therefore **moose + elk**, not moose-only. **Inert for bear** (Pass-2 operations `[]`; S06.4 confirmed inert-for-bear at closure); **but S06.3's elk extraction may need to apply this elk correction** — S06.3 closed treating the correction as moose-only inert and may have missed the elk-muzzleloader update. **Flagged as Known Issue #10 (PM decision pending)** — see Known Issues to Escalate section. The canonical merge machinery from S03.4 (three-pass arbitration: Pass 1 base extraction; Pass 2 correction operations per BMU; Pass 3 merge with `applied_correction=true` + confidence demote-one-tier per ADR-017 §4) is preserved as the inert-confirmation pathway and applies bear-side (where the operations list is genuinely empty). The elk re-extraction question is S06.3 territory, not S06.4's; it's a latent gap the PM consolidates.

**S06.4 folds into S06.3 ONLY IF (a) Black Bear is a section of the Big Game brochure AND (b) no separate Black Bear correction PDF exists for 2026.** If a correction PDF exists for the Big Game brochure as a whole (touching Black Bear and other species), the three-pass arbitration scaffolding lives in S06.3 — but S06.4 still ships separately to encapsulate the per-species correction-handling logic.

**ADR-019 correction handling:** If CPW publishes a mid-year correction (analog of MT's 2026-03-18 black bear correction), the doc-type-precedence rule applies: `correction > annual_regulations`. The three-pass arbitration pattern from S03.4 (Pass 1: base extraction; Pass 2: correction operations per BMU; Pass 3: merge with `applied_correction=true` + confidence demote-one-tier per ADR-017 §4) carries forward as-is.

**Cleanup rules:** Mirror S03.4's 8 pitfalls — rotated-table handling; correction-merge per-BMU touched-once-only; quota cell word-orderings; female-sub-quota `*` footnote suffix; etc. — and document any CPW-specific deviations.

**Output artifact:**

- `ingestion/states/colorado/extracted/black-bear-2026.json` if separate publication, OR section of `big-game-2026.json` if integrated
- Per-row schema mirrors S03.3/S03.4 with CO-specific fields surfaced at Stage-1
- If a correction PDF exists: `corrections-{date}.json` + merged `black-bear-2026.json` (three-pass arbitration per S03.4)

**Deliverables:**

- `ingestion/states/colorado/extract_black_bear.py` (if separate brochure)
- `ingestion/states/colorado/extracted/black-bear-2026.json` (if separate brochure)
- 30-100 unit tests in `ingestion/tests/test_extract_co_black_bear.py`

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md), [ADR-017](../adrs/ADR-017-confidence-calibration.md), [ADR-019](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md).

**Depends on:** S06.1 (Black Bear brochure OR Big Game brochure pinned).

**Unblocks:** S06.6, S06.7, S06.9.

**Acceptance Criteria:**

**Group A — file-level / static (satisfied at-merge `51f6aa7`):**

- [x] Extractor shipped as **separate file** (`ingestion/states/colorado/extract_black_bear.py`, 3,603 LOC, state-agnostic-clean per AST guard); satisfies AC #344
- [x] Deterministic SHA-256 across two consecutive runs — `7b35c202…d5f6` pinned in `test_extract_co_black_bear.py`; 172 records / 215 rows committed
- [x] Per-row windows + per-region structure preserved faithfully (137 limited_draw + 78 OTC across archery/muzzleloader/rifle × method-class)
- [x] **ADR-008 paraphrase prohibition (extraction surface):** `verbatim_text` byte-equivalent to `pdf.extract_text` output per S03.2 word-grouping boundary; no `layout=True` (AST guard); cleanup-rules docstring grep-parity verified against runtime normalizations (R1–R17)
- [x] **Cleanup rules R1–R17 documented** in module docstring with regex + scope + rationale + locking test name; AC #547 strict-parity discipline (S03.3) holds. **CO-specific discoveries**: bear tables have NO Sex column (4-col limited / 5-col rifle vs deer/elk/pronghorn's 6-col); R14 character-doubling N/A for bear; **R16 hunt-code embedded in prose** (Plains-OTC `B-E-087-U6-R` "Sales agents only:" prefix recovery); **R17 fused-row split** (pdfplumber merged 2 muzzleloader rows; split on multi-hunt-code cells, fail-loud on misalignment)
- [x] **Three-pass arbitration preserved** as inert-confirmation pathway (NOT bypassed): Pass-1 `black-bear-2026-base.json` + Pass-2 `corrections-2026-02-19.json` (operations `[]` for bear) + Pass-3 merged `black-bear-2026.json`. `applied_correction=true` + `supersedes` field machinery present; ADR-017 §4 demote-once-per-row preserved; fail-loud on future bear-targeting correction
- [x] `SourceCitation.document_type` ∈ `{annual_regulations, correction}` enforced; any other value raises `ValueError` naming source id + `document_type`; ADR-019 §"Decision" item 5 amendment required before participation — no silent enum participation
- [x] **`big-game-2026.json` regenerated** via the coordinated `valid_gmus` cleanup; counts UNCHANGED (737/2758); confidence UNCHANGED (`{high: 2170, medium: 583, low: 5}`); **SHA shifted `3c2ecd90…015d` → `e5c7c33a…6d1e`** and re-pinned in `test_extract_co_big_game.py`; per-extractor `_split_valid_gmus` duplication (matches convention; `lib/pdf.py` net-zero change)
- [x] Test baseline shifted **1498 → 1669 + 4 skipped** (+171 additive); ruff + mypy + detect-secrets clean

**UAT — PM-pending:**

- [ ] PM-run spot-check on ≥3 representative bear regions cross-checked against source PDF (AC #343); runbook in `docs/planning/epics/E06-confidence-findings/S06.4.md` when captured — *PM-pending; not blocking S06.5 dispatch since S06.5 depends on S06.0 provenance + S06.3 brochure, not bear*

- [x] Closure note (AC #345) documents: S06.4 shipped as **separate extractor** (not folded into S06.3); correction confirmed inert-for-bear; **correction-content correction surfaced**: the 2026 correction PDF is **moose + elk** (not moose-only as the S06.1 forward-note claimed) — page 2 is an elk-muzzleloader correction (E-M-…, p.44). Inert for bear, but **S06.3's elk extraction may need to apply this elk correction** — flagged as Known Issue #10 (PM decision pending)

---

### S06.3.1: Big Game extractor hygiene — R17 port + elk-correction investigation (carve-out post-S06.4 closure)

**Status:** Closed at-merge 2026-06-16 — squash-merged to main as **PR #69 / `bfeb60a`** from `feat/S06.3.1-big-game-extractor-hygiene` (**sixth E06 PR**; mid-epic carve-out resolving Known Issues #10 + #11 as one coordinated SHA shift, per the S03.6.1 / S05.3.5 precedent). Documentation + extraction-side only — no DB writes, no schema/migration, no `db.py` touches, no `ingestion/lib/` edits. **Phase A — Elk-correction investigation → OUTCOME (b), structurally inert** (NOT outcome (a) as PM expected). The big-game extractor has no correction machinery (the three-pass merge lives only in `extract_black_bear.py`) — **and needs none**. The brochure PDF (`publication_date='2026-03-04'`) **postdates all four corrections** (2026-02-13/17/19), and the correction PDF states the online brochure was updated. **The two V1-scope elk corrections are already correct in the committed artifact**: `E-M-059-O1-M` → `list_value='A'`; `E-F-044-O1-R` → `list_value='B'`. The other two corrections are moose (out of V1 scope). No correction-merge built; **~400 LOC of three-pass infra avoided**. **Documented deviation from spec's PM-expected outcome (a)** — the spec assumed the brochure predated the correction; it does not. Durable record is the existing S03.4 "correction-PDF-contradicts-forward-note" pitfall. **Phase B — R17 row-fusion split ported as big-game "Rule R16"**. New `_split_fused_block_row` in `extract_big_game.py` (state-agnostic-clean preserved; R16 stays per-extractor like `_split_valid_gmus`, no lib edits). **Adapted, not verbatim from bear**: big-game fusion is partial-column (some cells carry one shared value), so the rule is `{N parts → distribute | 1 → broadcast | else → fail-loud}` rather than bear's strict raise-on-any-mismatch. Wired into the single standard-block path in `_parse_table_block`; Season Choice (8-col) deliberately excluded (verified non-fusing). **4 previously-dropped codes recovered**: `D-M-082-O3-R`, `D-F-107-O1-R`, `A-M-004-O1-M`, `A-F-118-O1-R`. ⚠️ **The S06.4 closure narrative's "9 dropped codes" was an unmeasured estimate** — the empirical count is **4**. Reconciled to 4 per the "name the source-of-truth before copying numbers" discipline (S06.4 closure narrative annotated in this PM commit). **Phase C — Re-extraction + SHA re-pin**: deterministic (two-run byte-identical). **SHA lineage**: `3c2ecd90…015d` (S06.3 close) → `e5c7c33a…6d1e` (S06.4 `valid_gmus` cleanup) → **`9312e2595071a80cc317250504e4ba6a7eaaae33a201a313db275aa0f0c8bb2f`** <!-- pragma: allowlist secret --> (S06.3.1). Counts: sections **737 → 736** (a now-empty mule_deer placeholder section collapsed once R16 gave its fused rows real GMU codes); rows **2758 → 2762** (+4 from the recovered codes); confidence shift **high 2170 → 2178** / medium 583 / **low 5 → 1** (per S03.11 FINALIZE, this remains data-shape signal not framework signal — ADR-017 unmodified). Re-pinned in `test_extract_co_big_game.py`; **S06.3 AC #279 annotated with the full SHA lineage in this PM commit**. **PR-review hardening (3 cycles, all addressed in-branch)**: five findings raised; two genuine → fixed, three correct-by-design → declined with rationale. **(fixed)** duplicated hunt-code grammar → single `_HUNT_CODE_GRAMMAR` fragment; both `_HUNT_CODE_RE` (anchored parser) and `_HUNT_CODE_EMBEDDED_RE` (unanchored scanner) derive from it; scanner switched to `finditer()`/`group(0)`. Detection-equivalent (SHA unchanged). Locked by `TestHuntCodeGrammarSingleSourceOfTruth`. **(fixed)** Ambiguous shared-cell mis-distribution → continuation-comma fail-loud guard (a distributed part ending in `,` is a line-wrapped single value, not N per-row values → raise). False-positive-free on all 4 real rows. Narrower residual (non-comma wraps) documented. **(fixed earlier, W1)** No-`\n` collapsed-separator hunt-code cell → fail-loud guard ("Hunt Code cell is the authority"). **(declined)** "Monolithic 2.9k-LOC module" → **formalized as ADR-022 (Accepted): Single-Module Per-State PDF Extractors** — the recurring finding now has a canonical citation; modularization reopens only via a superseding ADR applied uniformly across all extractors. `known-pitfalls.md:481` + Known Issue #9 point at it. **(declined)** empty-split-part → `None` AND hunt-code-keyed detection → both correct/intentional (byte-identical to audited bear convention; empty→None is the codebase-wide normalization; misalignment already raises; verbatim preserved per ADR-008). **Quality gates**: ruff + mypy clean; full suite **1681 passed / 4 skipped** (post-merge baseline; +`TestFusedRowSplit` ~10 tests, +comma-guard test, +`TestHuntCodeGrammarSingleSourceOfTruth` 2 tests, +`_RULE_COUNT` 15→16 parity); cubic `{"issues":[]}`; detect-secrets clean (routine `.secrets.baseline` refresh). TS serving stack untouched. **NEW: ADR-022 created (Accepted)** — single-module per-state extractor convention. `docs/adrs/README.md` index updated; `known-pitfalls.md:481` + epic Known Issue #9 updated. **No other ADRs.** Refines ADR-001 (fail-loud), ADR-005 (state-adapter isolation — no lib edits; `TestNoColoradoLeakIntoSharedLib` green), ADR-008 (verbatim; no `layout=True`; R16 splits already-extracted cells), ADR-017 §4 (N/A — Phase A outcome (b)), ADR-019 (correction precedence — documented inert for big-game). **Known Issues #10 + #11 → RESOLVED via S06.3.1**; Known Issue #9 → **formalized as ADR-022**. **UAT PM-pending** (AC left unchecked per Group-A/B posture): spot-check the 4 recovered codes against the source PDF + confirm Phase A inertness (no elk rows changed by a merge). **Distinct residual at section 416** (elk archery: `E-M-020-O1-A` / `E-F-020-O1-A` in `verbatim_text` but no row — heading-absorption, NOT row-fusion). Documented in the closure memo as out of R16 scope; it is the single remaining LOW row. Not a silent gap (LOW + WARNING + verbatim preserved). **Narrow R16 residual** (a shared cell wrapping to exactly N parts without a comma signal) — documented in `known-pitfalls.md`; no such case in the 2026 brochure. **Sequencing**: S06.3.1 landed before S06.5 per plan; `big-game-2026.json` artifact-state-of-truth is now correct for downstream S06.6 regulation_record ingestion. **Next active work-front: S06.5** (restricted-area `verbatim_rule` population). **Deliverables on disk**: `docs/planning/epics/E06-confidence-findings/S06.3.1.md` (closure memo + SHA-lineage chronicle; deletes at `m2` per ADR-017 §6); modified `extract_big_game.py` + `test_extract_co_big_game.py` + regenerated `big-game-2026.json`; `docs/adrs/ADR-022-single-module-per-state-extractors.md` + ADR README index; epic + known-pitfalls annotations.

**Carved out 2026-06-16** post-S06.4 closure to address Known Issues #10 (latent S06.3 elk-correction-content gap) + #11 (latent big-game R17 row-fusion defect) as a single coherent carve-out. Mirrors the S03.6.1 / S05.3.5 mid-epic carve-out precedent. Combining both findings into one PR avoids two sequential SHA shifts on `big-game-2026.json` (which already absorbed one SHA shift via S06.4's coordinated `valid_gmus` cleanup `3c2ecd90…015d` → `e5c7c33a…6d1e`).

**As a** developer fixing latent gaps in the S06.3 CPW Big Game extraction before downstream consumers (S06.6 regulation_record ingestion) touch the artifact
**I want** the elk-correction-content gap resolved + the R17 pdfplumber row-fusion bug ported from `extract_black_bear.py` to `extract_big_game.py` + a single coordinated re-extraction with both fixes applied
**So that** `big-game-2026.json` accurately reflects CPW's published regulations (post-correction merge if applicable) AND captures the 9 previously-dropped hunt codes that R17 silently lost, with one SHA shift documented as the final pre-S06.6 pin

**UAT: yes** — PM-run spot-check on (a) the 9 newly-captured codes (whatever they prove to be) cross-checked against the source PDF + (b) any elk-muzzleloader rows updated by the correction merge (per Phase A outcome).

**Context:**

S06.4's build surfaced two findings about S06.3's already-merged `extract_big_game.py` + `big-game-2026.json`:

- **Known Issue #10**: the 2026 CPW Big Game correction PDF is **moose + elk** (page 2 carries an elk-muzzleloader correction `E-M-…`, p.44), NOT moose-only as the S06.1 forward-note claimed. S06.3 closed treating the correction as moose-only inert and may have failed to apply the elk-muzzleloader correction merge. The `extract_big_game.py` three-pass arbitration scaffolding was wired but the question is whether S06.3's actual run produced a non-empty Pass-2 operations list for elk.
- **Known Issue #11**: the same pdfplumber row-fusion bug that S06.4 Rule R17 fixed in bear extraction exists in `extract_big_game.py`; **9 fused cells in `big-game-2026.json` silently dropped codes**. R17 logic ports directly.

Both findings affect the same code and the same committed artifact. Combining into one carve-out:

- One PR, one SHA shift (third one on `big-game-2026.json`: original `3c2ecd90…015d` → S06.4 cleanup `e5c7c33a…6d1e` → S06.3.1 `<new>`)
- Less audit churn
- Phase A investigation outcome dictates whether the elk-correction merge actually fires; either way Phase B R17 port unconditionally fires
- Phase C coordinated re-extraction + re-pin happens once

**Sequencing**: lands **before S06.5** (PM + user decision 2026-06-16 — carve-out first sequencing keeps the artifact-state-of-truth correct before downstream consumers touch it; S06.5 is bear-independent so it doesn't block on this carve-out). Merge order updates to: S06.0 ✓ → S06.1 ✓ → S06.2 (omitted) → S06.3 ✓ → S06.4 ✓ → **S06.3.1 (NEW; next active)** → S06.5 → S06.6 → S06.7 → S06.8 → S06.9 → S06.10 → S06.11.

**Phase A — Elk-correction investigation gate (Known Issue #10):**

The Phase A implementer probes whether `extract_big_game.py`'s S06.3 run produced a non-empty Pass-2 operations list for elk-muzzleloader, and **what the actual elk-muzzleloader correction content does**. The investigation resolves to one of three outcomes:

- **(a) Re-extract with elk correction applied** — Pass-2 has a non-empty elk-muzzleloader operations list AND the correction was NOT actually applied in S06.3's merged artifact. Phase C re-extracts with the correction applied; `applied_correction=true` + `supersedes` populated on the affected rows; confidence demote-one-tier per ADR-017 §4
- **(b) Confirm structurally-outside-V1-scope** — the elk-muzzleloader correction targets non-V1 content (e.g., a hunt code not in V1 species scope per PRD 002); document the deviation in the S06.3.1.md memo + the closure note; no re-extraction merge action needed
- **(c) Defer to S06.6 ingestion** — the correction is in scope but is better applied at load time than at extraction time (e.g., the structure of the correction maps better to a `regulation_record.additional_rules` annotation than to a per-row merge); document the deferral + carry forward to S06.6 spec

The PM expectation is outcome (a) given S06.3 demonstrably wired the three-pass arbitration but the original S06.1 forward-note characterization led the S06.3 implementer to assume moose-only inert; if (b) or (c) fires, the S03.4 lesson "correction-PDF-contradicts-forward-note" pitfall (already in known-pitfalls.md) is the durable record.

**Phase B — R17 port (Known Issue #11):**

The Phase B implementer ports the R17 pdfplumber row-fusion split logic from `ingestion/states/colorado/extract_black_bear.py` to `ingestion/states/colorado/extract_big_game.py`:

- Pattern: detect cells whose content contains multiple hunt-code fragments matching `_HUNT_CODE_FRAGMENT_RE` (the deer/elk/pronghorn analog of bear's matcher); split on multi-hunt-code cells; fail-loud on misalignment with the row's other column counts
- Wire into all relevant row-walking paths in big-game (the analog of bear's "all three row-walking paths: limited, OTC no-Dates, OTC has-Dates")
- Add an R17-equivalent docstring section + a locking test (`test_r17_fused_row_split_big_game` or similar) that pins ≥3 representative fused-cell cases discovered in `big-game-2026.json`
- Pre-pre-fix snapshot: enumerate the 9 fused cells currently silently dropping codes; the test verifies all 9 are captured post-fix

**Phase C — Coordinated re-extraction + re-pin:**

Once Phase A outcome is locked AND Phase B R17 port is wired:

- Re-run `python -m ingestion.states.colorado.extract_big_game` to regenerate `extracted/big-game-2026.json` (and `big-game-2026-base.json` + `corrections-2026-02-19.json` if Phase A outcome (a))
- Verify counts: 737 sections (unchanged) + 2,758 rows + the 9 newly-captured codes (so the row count rises by at least 9 — TBD by R17 outcome); confidence distribution TBD by both fixes
- Compute new SHA-256; re-pin in `test_extract_co_big_game.py`
- Update the S06.3 closure narrative + S06.3 AC #279 to point at the new pin (third documented SHA on this artifact); annotate the lineage explicitly: `3c2ecd90…015d` (S06.3 close) → `e5c7c33a…6d1e` (S06.4 `valid_gmus` cleanup) → `<new>` (S06.3.1)
- Capture a per-fix count delta in the S06.3.1.md closure memo: "Phase A applied N rows" + "Phase B captured 9 previously-dropped codes" so the closure note is the durable record of what changed

**Deliverables:**

- `docs/planning/epics/E06-confidence-findings/S06.3.1.md` — Phase A investigation memo + Phase B R17 port summary + Phase C re-extraction record + SHA-lineage chronicle (deletes at `m2` tag per ADR-017 §6)
- Modified `ingestion/states/colorado/extract_big_game.py` with R17 logic ported (state-agnostic-clean preserved; `TestNoColoradoLeakIntoSharedLib` stays green)
- Regenerated `ingestion/states/colorado/extracted/big-game-2026.json` (+ Pass-1 + corrections artifact if Phase A outcome (a))
- Re-pinned SHA in `ingestion/tests/test_extract_co_big_game.py`
- R17 locking test (analog of S06.4's R17 test)
- Updated module docstring with the R17 cleanup rule entry (AC #547 strict-parity discipline)

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md) (fail-loud on misalignment), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md) (paraphrase prohibition preserved across the re-extraction), [ADR-017](../adrs/ADR-017-confidence-calibration.md) (demote-one-tier per ADR-017 §4 if Phase A outcome (a) fires), [ADR-019](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md) (correction precedence — outcome (a) makes the merge concrete; outcome (b) / (c) leave it as documented gap).

**Depends on:** S06.3 closure (✓ 2026-06-13), S06.4 closure (✓ 2026-06-15 — surfaced both findings).

**Unblocks:** S06.5 (sequencing only — S06.5 is bear-independent so technically NOT blocked, but PM decision is to sequence carve-out first to keep artifact-state-of-truth clean before S06.6); S06.6 regulation_record ingestion (avoids downstream silent gaps from the 9 lost codes).

**Acceptance Criteria:**

- [x] `docs/planning/epics/E06-confidence-findings/S06.3.1.md` exists with Phase A investigation outcome captured verbatim (one of (a) / (b) / (c)) + Phase B R17 port summary + Phase C SHA-lineage chronicle
- [x] **Phase A**: implementer probes S06.3 run's actual Pass-2 elk-muzzleloader operations behavior; outcome documented; if (a), elk-muzzleloader correction merged into `big-game-2026.json` with `applied_correction=true` + `supersedes` populated + ADR-017 §4 demote-once-per-row applied; if (b) / (c), deviation documented + S06.6 spec implications noted (for (c)) — outcome **(b)**: the two V1-scope elk corrections (`E-M-059-O1-M` → List A, `E-F-044-O1-R` → List B) are already incorporated in the committed artifact because the brochure PDF (2026-03-04) postdates the corrections (2026-02-13/17/19) and is the post-correction online edition; the other two corrections are moose (out of V1 scope); inert, no correction-merge machinery built
- [x] **Phase B**: R17 pdfplumber row-fusion split logic ported to `extract_big_game.py` from `extract_black_bear.py`; wired into all relevant row-walking paths; fail-loud on misalignment; locking test pins ≥3 representative fused-cell cases; module docstring updated with the R17 entry (AC #547 strict-parity discipline)
- [x] **9 previously-dropped codes captured**: pre-fix snapshot enumerates the 9; post-fix `big-game-2026.json` contains them; locking test verifies (mirrors the S06.4 R17 test pattern) — reconciled to **4** empirical (`D-M-082-O3-R`, `D-F-107-O1-R`, `A-M-004-O1-M`, `A-F-118-O1-R`); spec's "9" was an unmeasured approximation
- [x] `big-game-2026.json` regenerated; SHA computed + re-pinned in `test_extract_co_big_game.py`; SHA lineage `3c2ecd90…015d` → `e5c7c33a…6d1e` → `9312e259…bb2f` documented in the closure note + S06.3 closure narrative annotated
- [x] `extract_big_game.py` remains state-agnostic-clean per AST guard; `TestNoColoradoLeakIntoSharedLib` stays green; no `ingestion/lib/` edits (R17 logic stays per-extractor per CPW-specific convention, mirroring `_split_valid_gmus`)
- [x] **ADR-008 paraphrase prohibition** preserved across re-extraction: `verbatim_text` byte-equivalent to `pdf.extract_text` output for the source span; no `layout=True` (AST guard); cleanup-rules docstring grep-parity with runtime normalizations
- [x] Test baseline grows additively only; new test(s) for R17 + (conditional) Phase A correction-merge verification; ruff + mypy + detect-secrets clean; cubic clean
- [ ] **UAT (PM-pending at story close):** PM-run spot-check on (a) the **4 newly-captured codes** (`D-M-082-O3-R`, `D-F-107-O1-R`, `A-M-004-O1-M`, `A-F-118-O1-R`) cross-checked against the source PDF + (b) confirm Phase A inertness — no elk rows changed by a merge (no merge built; verify by inspection that `E-M-059-O1-M` reads List A and `E-F-044-O1-R` reads List B in `big-game-2026.json`) *(PM-pending at close per Group-A/B posture)*
- [x] Closure note documents per-fix count delta: "Phase A applied 0 rows (outcome (b) — structurally inert)" + "Phase B captured **4** previously-dropped codes (reconciled from spec's unmeasured estimate of 9)"
- [x] Epic Known Issues #10 + #11 annotated as **RESOLVED via S06.3.1** (mirrors S05.3.5 → Known Issue #2 RESOLVED pattern)
- [x] No production-DB writes from the build session (S06.3.1 is documentation + extraction-side only; no DB)

---

### S06.5: Restricted-area `verbatim_rule` population for the 10 S05.4 no-hunt zones

**Status:** Closed at-merge 2026-06-18 — squash-merged to main as **PR #70 / `207f31d`** from `feat/S06.5-restricted-area-verbatim-rule` (**seventh E06 PR**). Merge diff: 8 files, **+1,120 / −2 LOC**. **Group A satisfied at-merge**; **Group B operator-pending** (ACs #482/#483/#486 — live UPDATE + SQL spot-checks). **What shipped**: (1) new `ingestion/states/colorado/load_restricted_area_verbatim.py` (**297 LOC**, state-agnostic-clean per AST guard) — single-purpose targeted-UPDATE loader. Populates `geometry.verbatim_rule` on the 10 `kind='restricted_area'` rows (`CO-restricted-{slug}-geom`) by reading CPW Big Game brochure page 78 ("Land Closures & Use Restrictions") at runtime via `lib/pdf.open_pdf` + `lib/pdf.extract_text(page, bbox=…)` column crops + regex anchors. Three-phase `main()` (build → pre-`db.connect()` guards (OQ7) → conn/commit); `--dry-run`; **no `--service-url` flag** (S05.0 silent-lie-citation precedent); function-level logger. (2) **NEW `ingestion/ingestion/lib/db.py` helper `update_geometry_verbatim(conn, geometry_id, text)`** (S06.0/D6 delivered). Exact analog of `update_legal_description`: `UPDATE geometry SET verbatim_rule = %s WHERE id = %s`; fail-loud `RuntimeError` on `cur.rowcount == 0`; no commit (caller owns txn). **State-agnostic write-path extension** per the `db.py` extension-point convention — NOT a state-specific lib edit (ADR-005 / ADR-022 hold). (3) Tests: `test_db.py` +4 (`TestUpdateGeometryVerbatim`); new `test_load_co_restricted_area_verbatim.py` +17 (parsers, phrasing-case lock, `_check_map` guards, `main()` mocks, AST guards incl. no-`layout=True`, skip-if-absent live-PDF byte-equivalence lock). **Test baseline shifted 1681 → 1702 + 4 skipped** (+21 additive; new 1702 baseline holds going into S06.6). (4) Closure note / operator runbook: `docs/planning/epics/E06-confidence-findings/S06.5.md` (deletes at `m2` per ADR-017 §6). **Key decisions baked in**: **D5 = (b) split-provenance honored** — loader UPDATEs **only** `verbatim_rule`; `source` stays the PAD-US citation (`document_type='gis_layer'`) on all 10 rows. No schema / three-place-sync / migration. Option-(a) UPDATE-source explicitly NOT taken; multi-source provenance remains a deferred PRD-002 ADR-candidate. **Phrasing case (1) + a 9+1 split**: CPW publishes **one generic sentence** for NPS lands, shared across the 9 NPS rows (4 NPs + 5 NMs): *"National parks and monuments managed by the National Park Service are closed to hunting. Check park websites for more information."* The AFA row gets its own distinct page-78 access-rules prose (regulated access, NOT a closure). Locked by a regression test (9 NPS values collapse to one unique string; AFA differs). **ADR-008 byte-equivalence** — both spans are verbatim substrings of `pdf.extract_text` output (newlines + mandatory soft-hyphen preserved; no normalization, no rewording). Column-crop bbox + regex anchor; fail-loud on missing anchor / empty crop / wrong PDF — **never hand-edit**. **ADR-015 REG+COMMENTS combiner: N/A** (single brochure-page source). **🚩 Carried forward — PM action needed at S06.10**: **AFA classification flag** (user-decided 2026-06-17; cubic's lone P2 = documented-deferral). The Air Force Academy (`CO-restricted-united-states-air-force-academy-geom`) is a **regulated-access HUNTING area**, NOT a no-hunt zone (GMU 512 carries CPW hunt codes; escorted rifle deer hunts). Its `verbatim_rule` now describes *how to hunt there*. **S06.10 must NOT bind it `role='no_hunt_zone'`** — recommend `role='other_overlay'` (restricted-access) or revisiting the S05.4 "federal no-hunt zone" classification. User intent: **AFA must remain protected as a huntable zone in query results**. The other 9 (NPS) zones are genuine no-hunt zones; `no_hunt_zone` is correct for them. New Known Issue #12 below; S06.10 spec carries an inline forward-note (added in this PM closure commit). **Quality gates at-merge**: ruff clean; mypy `ingestion/lib/` clean (8 files); pytest 1702 + 4 skipped (no regressions); cubic's lone P2 = the documented AFA→S06.10 candidate; detect-secrets passed; no TS-stack diffs. **No ADRs created**; refines ADR-001 (fail-loud), ADR-008 (verbatim, no `layout=True`), ADR-005 / ADR-022 (state-agnostic-clean; no state-specific lib edit), ADR-015 (combiner N/A). Q-statuses unchanged. **1 new pitfall** in `.roughly/known-pitfalls.md` (now ~1,222 LOC — re-flagged for reorg/dedup): multi-column PDF prose extraction — crop by column, keep crop edges out of text lines. (Note: a post-merge internal-consistency fix corrected an initial over-generalization in this entry that had contradicted the S03.5 header/footer-strip guidance — the failure mode is crop-edge-placed-mid-line, NOT "non-zero top"; S03.5's 25pt/50pt strips remain correct. Code unaffected.) **Group B operator-pending** (per S05.4/S05.0/S05.2/S05.5/S05.7 batched live-write session pattern): operator must — after the E05 Group B geometry writes land — `fetch_pdfs.py` → `load_restricted_area_verbatim.py` → SQL spot-check all 10 rows non-null (AC #482), `source` still `gis_layer` (AC #483, D5=b), 9 NPS share the closure sentence, AFA carries its own prose; PM-run spot-check ≥3 zones (AC #486). Runbook + SQL in `S06.5.md`. PM ticks Group B ACs (#482/#483/#486) in a follow-up doc-only commit once captured. **Next active work-front: S06.6** (regulation_record ingestion) — first DB-write story for the regulation-text entities; gated on the outstanding E05 operator Group B geometry writes for live execution.

**As a** developer populating regulatory text for the 10 federal no-hunt zones from S05.4
**I want** `geometry.verbatim_rule` populated for each of the 10 `kind='restricted_area'` rows from the CPW Big Game brochure + the S06.0-decided `source` field updated per the chosen multi-source provenance disposition
**So that** the regulatory authority for each prohibition is preserved verbatim per ADR-001/ADR-008 and the 10 zones carry their regulatory-text-source provenance correctly

**UAT: no** (verification-gated against SQL spot-checks; faithfulness verified at SQL-row level against the brochure)

**Context:**

S05.4 shipped 10 PAD-US-sourced `kind='restricted_area'` geometry rows with `verbatim_rule=None` deliberately deferred. S06.0 resolved the unresolved CPW Big Game brochure URL + the multi-source provenance question (PRD 002 § "Open decisions resolved during M2" candidate). S06.5 executes the deferred text-population pass.

S06.5's exact shape depends on the S06.0 multi-source provenance decision:

- **If (a) UPDATE `source` to CPW citation** — the loader UPDATEs both `verbatim_rule` AND `source` to the CPW Big Game brochure citation (`document_type='annual_regulations'`); the PAD-US geometry-provenance citation is lost from the `source` field and lives in the discovery report only
- **If (b) accept split-provenance, PAD-US wins `source`** — the loader UPDATEs only `verbatim_rule`; `source` stays as the PAD-US citation
- **If (c) ADR + migration for multi-source provenance** — S06.0 would have already shipped the migration; S06.5 populates both citations via the new field

**Phrasing question** (resolved at extraction time): the brochure may publish (1) a single generic sentence covering "national parks are closed" (one shared string across all 9 NPS rows) or (2) per-park named sentences (9 distinct strings). The text-extraction script reads the brochure and writes per-row verbatim text accordingly. If REG + COMMENTS-style annotation both exist for a zone, combine per ADR-015's `\n\n--- COMMENTS ---\n\n` separator.

**Deliverables:**

- `ingestion/states/colorado/load_restricted_area_verbatim.py` (new, ~150-200 LOC, single-purpose loader; mirrors S05.0's small-table-UPDATE pattern with `db.update_geometry_verbatim` analog OR an in-script targeted UPDATE per the S06.0 decision)
- 5-15 unit tests in `ingestion/tests/test_load_co_restricted_area_verbatim.py`
- (Conditional) new `db.py` helper if a fail-loud UPDATE primitive is needed analog of `update_legal_description` from S03.6 (PM-cannot-land-autonomously; flag-and-discuss at S06.5 entry)

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md), [ADR-015](../adrs/ADR-015-geometry-verbatim-rule-and-reg-comments-handling.md), [ADR-019](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md), [ADR-021](../adrs/ADR-021-jurisdiction-binding-no-hunt-zone-role.md) (context — `no_hunt_zone` role bound in S06.10 against these geometry rows).

**Depends on:** S06.0 (multi-source provenance decision), S06.3 (CPW Big Game brochure extracted; verbatim text available for the 10 zones).

**Unblocks:** S06.10 (binding loader writes `role='no_hunt_zone'` against geometry rows with populated `verbatim_rule`).

**Acceptance Criteria:**

**Group A — file-level / static (satisfied at-merge `207f31d`):**

- [x] `ingestion/states/colorado/load_restricted_area_verbatim.py` exists (297 LOC); state-agnostic-clean per AST guard; `TestNoColoradoLeakIntoSharedLib` stays green
- [x] **ADR-008 paraphrase prohibition (UPDATE surface):** the brochure-source string for each of the 10 zones is **byte-equivalent to `pdf.extract_text` output** (S03.2 word-grouping baseline) for the source span; column-crop bbox + regex anchor; fail-loud on missing anchor / empty crop / wrong PDF — never hand-edit. No `layout=True` (AST guard). Locked by skip-if-absent live-PDF byte-equivalence test
- [x] **Phrasing case (1) locked + 9+1 split** recorded in closure note: CPW publishes **one generic sentence** for NPS lands (4 NPs + 5 NMs = 9 NPS rows collapse to one unique string): "National parks and monuments managed by the National Park Service are closed to hunting. Check park websites for more information." The **AFA row gets its own distinct page-78 access-rules prose** (regulated-access HUNTING area, NOT a closure). Locked by regression test asserting 9 NPS values share one unique string + AFA differs
- [x] **REG + COMMENTS combiner: N/A** for S06.5 (single brochure-page source; no per-zone REG+COMMENTS pairs)
- [x] **NEW `db.update_geometry_verbatim(conn, geometry_id, text)` helper** in `ingestion/ingestion/lib/db.py` per S06.0/D6 conditional 6th decision — exact analog of `update_legal_description`; `UPDATE geometry SET verbatim_rule = %s WHERE id = %s`; fail-loud `RuntimeError` on `cur.rowcount == 0`; no commit (caller owns txn). State-agnostic write-path extension per `db.py` extension-point convention (not a state-specific lib edit; ADR-005 / ADR-022 hold). Locked by `TestUpdateGeometryVerbatim` (+4 tests)
- [x] Test suite grows additively: +21 tests (`test_load_co_restricted_area_verbatim.py` +17 + `test_db.py` +4); baseline shifted **1681 → 1702 + 4 skipped**; ruff + mypy + cubic + detect-secrets all clean (cubic's lone P2 is the documented AFA → S06.10 deferral)
- [x] No production-DB writes from the build session; three-phase `main()` (build → pre-`db.connect()` OQ7 guards → conn/commit); no `--service-url` flag (S05.0 silent-lie-citation precedent honored); operator runbook in `docs/planning/epics/E06-confidence-findings/S06.5.md`

**Group B — operator-driven post live-fetch + UPDATE (open; not blocking S06.5 close per S05.0 / S05.2 / S05.4 pattern; shares precondition with the outstanding E05 operator Group B geometry writes):**

- [x] All 10 S05.4 geometry rows (`CO-restricted-{slug}-geom`) have `verbatim_rule` populated post-load; SQL spot-check verifies non-null across all 10 — *closed via M2-build operator pass 2026-06-23 (PR #74 / `a6cec6b`; env=dev / M2-build); verbatim outputs in `docs/runbooks/M2-operator-pass.md` capture form*
- [x] `source` field retained as PAD-US citation per **D5 = (b) split-provenance** (NOT updated to CPW); SQL verifies `source.document_type='gis_layer'` on all 10 rows — *closed via M2-build operator pass 2026-06-23 (env=dev / M2-build); verbatim outputs in capture form*
- [x] Per-row text faithful to source PDF; PM-run spot-check on **≥3 of the 10 zones** (e.g., Rocky Mountain NP, Mesa Verde NP, AFA) cross-checks against CPW brochure page 78 — *closed via PM spot-check 2026-06-23 (env=dev / M2-build)*: Rocky Mountain NP + Mesa Verde NP both carry the NPS shared closure sentence "National parks and monuments managed by the National Park Service are closed to hunting. Check park websites for more information." (130 chars; locked by the loader's `_check_map` 9-NPS-collapse-to-1 regression test + the `TestNoColoradoLeakIntoSharedLib` skip-if-absent live-PDF byte-equivalence lock); AFA carries its own distinct 397-char access-rules prose describing escorted-rifle-hunting + archery white-tail permit + AFA access fee + safety orientation — confirms AFA is a regulated-access HUNTING area (Known Issue #12 RESOLVED, baked into S06.10 as a hard constraint). Verbatim dev outputs in `docs/runbooks/M2-operator-pass.md` Step 8 capture form ((d) + (e))

Group B verification captured in `docs/planning/epics/E06-confidence-findings/S06.5.md` § "Group B verification record" (analog of S05.0/S04.1 records); PM ticks Group B boxes in a follow-up doc-only commit once operator results land.

---

### S06.6: `regulation_record` ingestion (5 V1 species × applicable CO GMUs + statewide anchors)

**Status:** Closed at-merge 2026-06-19 — squash-merged to main as **PR #71 / `4ecd47d`** from `feat/S06.6-regulation-record-ingestion` (**eighth E06 PR**). **Group A satisfied at-merge**; **Group B operator-pending** (live `supabase` row-count / SQL-shape verification ACs share the outstanding E05 operator Group B geometry-write precondition). **The first E06 DB-write story.** **What shipped**: (1) new `ingestion/states/colorado/load_regulation_records.py` (**848 LOC**, state-agnostic-clean per AST guard) — structural analog of MT's S03.6 loader, **simpler**: no legal-descriptions artifact, no fan-out dict, no statewide anchors in V1, no `jurisdiction_binding` writes (S06.10 territory). Three-phase shape: build → guards pre-`db.connect()` → upsert loop → single `conn.commit()`. (2) New `ingestion/tests/test_load_co_regulation_records.py` (**1,182 LOC, 72 tests**). (3) Reads the two committed extraction artifacts (`extracted/big-game-2026.json` array + `extracted/black-bear-2026.json` flat list); writes **398 `regulation_record` rows** in one atomic transaction. **Final record composition** (dry-run verified): mule_deer 141 (h=55/m=86) + elk 115 (h=38/m=77) + pronghorn 77 (h=25/m=52) + whitetail 19 (h=2/m=17) + bear 46 (h=46/m=0) = **398 total**; all `document_type='annual_regulations'`; confidence via `pdf.min_tier` (**no `low` rows** — the only `low` row was the skipped blank-GMU section); **0 `CO-STATEWIDE` rows**. **Key design decisions (load-bearing for S06.7–S06.10)**: (a) **Collapse by `(gmu_code, species_group)`** — CO artifacts have one section per `(gmu, species, method_group)`; `regulation_record` is the anchor (no `method_group`), so per-method sections collapse → **398 records, NOT 906 sections**. This matches the epic's "~300–500" estimate and confirms collapse is the intended design. **S06.7 link-table builders must group-and-collapse the same way or key off the written PKs.** (b) **No fan-out dict** — CO species are pre-separated in the artifact (`mule_deer`/`whitetail`/`elk`/`pronghorn`); there is **no `deer` label**. **Q16 does NOT fire for CO** (separation is section-level — Q16 status updated below). (c) `jurisdiction_code = CO-GMU-{int(gmu_code)}` (e.g. `"001"` → `CO-GMU-1`), mapping to S05.2's `CO-GMU-{int}-geom` geometry id by appending `-geom`. (d) Bear `species_group="bear"` (artifact says `black_bear`); bear artifact is a **flat list with a `record_type` discriminator** (NOT MT-style top-level `sources`/`rows` lookup). (e) **0 statewide anchors** — no pronghorn `900-20` analog; the 2 bear `statewide_rule` records (`season_dates_summary`, `list_abc_explanation`) are informational, NOT Bear-ID-Test prerequisites. Flag-and-discuss guard wired (fails loud on any new candidate). (f) **`_STATE: Final = "US-CO"`** (matches MT precedent + S05.6 scaffold, ahead of the S06.0/D3 rename which still bundles with S06.10). (g) **`_JURISDICTION_BINDING_ID_FORMAT` defined byte-identical to MT** for S06.10 to import (locked by 3 tests per the S03.6.1 pattern). **Deviations to record at closure**: (i) **AC #544 fan-out test reframed** — the AC's "artifact `deer` → 2 DB rows" doesn't apply (CO pre-separates species); shipped as a **no-accidental-fan-out test** instead. The AC was drafted before extraction confirmed CO's pre-separation. Plan-reviewer confirmed this is a correct divergence. (ii) **1 blank-GMU big-game section skipped-with-warning** — GMU 020 elk archery page 52 (the S06.3.1 heading-absorption residual at section 416; already covered by 3 proper elk sections, so **no anchor lost**). (iii) `_STATE` vs `CO_STATE_CODE` — uses `_STATE`; the 4 existing CO loaders' rename remains bundled with S06.10 per S06.0/D3. **Scope guarantees**: NO new `db.py` helpers (reuses `upsert_regulation_record`); NO `ingestion/lib/` edits; NO schema/migration/three-place-sync; NO MT-file touches; NO TS-stack diffs; NO production-DB writes from the build session. **Review history (all in the merged PR)**: 3-agent review found 1 Critical (silent drop on missing/misspelled bear `record_type`) + High/Warning fail-loud-context gaps → fixed in 1 cycle (`record_type` validation, diagnostic-wrapped artifact access, contextualized `min_tier`/shape guards); re-review confirmed all RESOLVED. Cubic → 1 P2 (NOTE page provenance in multi-section groups) → fixed + locked. **Maintainability refactor** — extracted shared `_collapse_sections_to_record` helper (both builders inlined the same ~80-line collapse body; divergence risk). Companion "split the module" finding declined per **ADR-022 / single-module-per-loader convention**. Two more fail-loud fixes: `statewide` guard `isinstance(dict)` hardening (ran before the builders; would have raised a low-context `AttributeError`); `gmu_code` grouping canonicalization (strip + canonical-collision guard — raw group key was finer than the `int()`-canonicalized PK, a silent UPSERT-collapse surface). **Test baseline shifted 1702 → 1774 + 4 skipped** (+72 additive; new 1774 baseline holds going into S06.7). ruff + mypy clean; `mcp-server` + `web` tsc exit 0; cubic `{"issues":[]}`. **No new ADRs**; refines ADR-001 (fail-loud), ADR-005 / ADR-022 (state-adapter isolation; no lib edits), ADR-008 (verbatim; no `layout=True`; per-NOTE provenance), ADR-010 (decomposed anchor), ADR-017 (FINALIZE — `min_tier` / `ConfidenceTier`, no framework change), ADR-018 §3/Q15 (no `verbatim_rule` column on `regulation_record`), ADR-019 §"Decision" item 5 (`document_type` widening guard). **3 new pitfalls landed in `.roughly/known-pitfalls.md`** (1,221 → 1,260 LOC; doc-writer re-flagged for reorg/dedup): (i) CO regulation_records collapse per-method-group sections (section count ≠ record count); (ii) CO big-game species pre-separated (no deer fan-out); (iii) CO bear artifact is a flat list with `record_type` discriminator (don't port MT's dict-with-sources shape; validate loudly). **Next active work-front: S06.7** (`season_definition` + `license_tag` + `license_season` ingestion — first multi-link-table adapter; `drift_guard.assert_id_matches` mandatory at every per-row entity-construction site; **Q20 (Season Choice `X` method modeling) surfaces here** as flag-and-discuss). S06.7 implementation can begin against the dry-run path; live execution still gated on outstanding E05 operator Group B writes.

**As a** developer writing the canonical anchor entity for CO regulations
**I want** every applicable CO GMU's per-species `regulation_record` row written with verbatim text + source citation + confidence per ADR-017, plus CO statewide-anchor rows analogous to MT's `MT-STATEWIDE-bear`/`MT-STATEWIDE-antelope`
**So that** S06.7 / S06.8 / S06.9 / S06.10 link-table + sibling-entity ingestion stories have an anchor to FK to

**UAT: no** (verification-gated against SQL counts; faithfulness verified at S06.3 / S06.4)

**Context:**

First E06 DB-write story. Mirrors M1's S03.6 pattern with CO species fan-out (artifact may use `deer` → DB `mule_deer` + `whitetail`; check CPW's structure at S06.3 closure). Atomic three-phase transaction: build → guards pre-`db.connect()` → conn loop / commit / rollback / close. Row-count fail-loud guard via OQ7 ±30% band fires pre-`db.connect()`.

**Group-A-at-merge / Group-B-operator-pending AC posture (applies to S06.6 through S06.10).** Because S06.6 onward depend on live CO geometry rows that are themselves operator-pending E05 Group B writes (see "Operator Group B precondition" above + Known Issues #1), each of these stories closes in two parts — mirroring the E05 / S04.1 split: **Group A** (loader code + mocked/dry-run tests + all quality gates) is satisfied **at merge**; **Group B** (live `supabase` row-count / SQL-shape verification ACs marked "operator-driven") is **operator-pending** and ticked by the PM in follow-up doc-only commits once the operator runs the loader against the production service-role DSN. A future PM must NOT read an unticked Group B live-verification AC as incomplete work — it is deferred-by-design. Each story's closure note records which ACs are Group A (closed) vs Group B (operator-pending).

**Statewide anchors:** CO statewide-anchor `regulation_record` rows analog of MT's `MT-STATEWIDE-bear` / `MT-STATEWIDE-antelope` are populated when the data requires:

- If CPW publishes a brochure-wide "STATEWIDE" antelope (pronghorn) row analog of MT's `900-20`, a `CO-STATEWIDE-pronghorn` regulation_record FK'd to `CO-STATEWIDE-geom` is written (mirrors S03.6 logic for MT antelope `900-20`)
- If CPW publishes statewide bear coursework / Bear ID Test / pre-purchase prerequisites analog of MT's Bear ID Test (S03.6.1 carve-out), a `CO-STATEWIDE-bear` regulation_record is written via a similar pattern
- If CPW publishes other species-statewide content, additional rows are added per the data; **the flag operational definition fires for any new statewide-anchor candidate not pre-registered here**

**Species fan-out:** DEA-style `deer` species in the artifact may fan out to `mule_deer` + `whitetail` in the DB (per S03.7's `_DEA_SPECIES_FANOUT` precedent). The fan-out is artifact-level → DB-level only — `season_definition.species` + `license_tag.species` stay at artifact-level granularity per S03.7 OQ-S7-1/2. If CPW separates `mule_deer` from `whitetail` at row-level (Q16 trigger), this is a flag-and-discuss event.

**Verbatim decomposition** per ADR-018 / Q15: per-license-row text → `license_tag.verbatim_rule` (S06.7); per-season-window text → `season_definition.verbatim_rule` (S06.7); GMU-wide NOTE lines → `regulation_record.additional_rules` (this story); the `regulation_record` row itself has no `verbatim_rule` column (Q15 / ADR-018 §3 disposition).

**Deliverables:**

- `ingestion/states/colorado/load_regulation_records.py` (new, structural analog of MT's; expected 500-700 LOC)
- ~300-500 `regulation_record` rows written in one atomic transaction (estimate: 5 species × ~186 GMUs filtered down to applicable rows; expected band documented in closure note)
- Statewide-anchor row(s) for pronghorn (if `STATEWIDE` row exists in CPW brochure) + bear (if statewide coursework analog exists)
- `_JURISDICTION_BINDING_ID_FORMAT` constant defined for S06.10 to import (mirrors S03.6.1's lock; format string for binding ids per the symmetric derive-and-assert UPSERT no-op contract)
- 50-80 tests in `ingestion/tests/test_load_co_regulation_records.py`

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../adrs/ADR-010-decomposed-entity-model.md), [ADR-017](../adrs/ADR-017-confidence-calibration.md), [ADR-018](../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S06.3 (Big Game brochure extracted), S06.4 (Black Bear extracted; folded into S06.3 OR separate), S05.0 (CO statewide geometry exists for statewide-anchor FK), S05.2 (CO GMU geometry exists for per-GMU FK).

**Unblocks:** S06.7 (link tables FK regulation_record), S06.8 (draw_spec referenced from license_tag in S06.7), S06.9 (reporting_obligation linked via regulation_reporting in S06.10), S06.10 (binding loader FKs to regulation_record).

**Acceptance Criteria:**

**Group A — file-level / static (satisfied at-merge `4ecd47d`):**

- [x] `ingestion/states/colorado/load_regulation_records.py` exists (**848 LOC**), state-agnostic-clean per AST guard; three-phase shape (build → guards → conn loop / `conn.commit()`)
- [x] **AC #544 fan-out reframed at closure** (Group-A-shipped deviation): the original AC's "artifact `deer` → 2 DB rows" doesn't apply — CO species are **pre-separated** in the artifact (`mule_deer` / `whitetail` / `elk` / `pronghorn`; no `deer` label). Shipped as a **no-accidental-fan-out test** instead, asserting each artifact species is emitted as exactly one DB row per `(gmu_code, species_group)`. Plan-reviewer confirmed this is a correct divergence; **Q16 does NOT fire for CO** (separation is section-level)
- [x] Bear DB `species_group="bear"` not `"black_bear"` (per S03.6 pitfall); bear artifact is a **flat list with a `record_type` discriminator** — `record_type` validation guards against missing/misspelled values (Critical-from-3-agent-review fix; locked by test)
- [x] **Row-count fail-loud guard ±30% band** fires pre-`db.connect()` (OQ7); **398 records written** in one atomic transaction (mule_deer 141 + elk 115 + pronghorn 77 + whitetail 19 + bear 46), within the epic's "~300–500" estimate
- [x] Atomic transaction: all rows commit OR rollback together (single `conn.commit()`)
- [x] Source citation populated on every row; `SourceCitation.document_type='annual_regulations'` on every row; ADR-019 §"Decision" item 5 silent-widening guard wired (any other value raises `ValueError` at build time)
- [x] **CO statewide-anchor analysis recorded at closure** (Group-A-confirmed): **0 statewide-anchor rows written** for V1. No pronghorn `900-20` analog in CPW; the 2 bear `statewide_rule` records (`season_dates_summary`, `list_abc_explanation`) are informational, NOT Bear-ID-Test prerequisites. Flag-and-discuss guard wired (fails loud on any new candidate). PM expectation of "0-2" satisfied at 0
- [x] **`_JURISDICTION_BINDING_ID_FORMAT` constant defined** in module **byte-identical to MT's** `_JURISDICTION_BINDING_ID_FORMAT` in `load_regulation_records.py`; locked by **3 tests** per S03.6.1 pattern (format string byte-identical; importable by S06.10; symmetric derive-and-assert UPSERT no-op contract). S06.10 imports this directly
- [x] **Collapse design recorded** (load-bearing for S06.7-S06.10): CO artifacts have one section per `(gmu, species, method_group)`; `regulation_record` is the anchor (no `method_group`), so per-method sections collapse **906 sections → 398 records**. **S06.7 link-table builders must group-and-collapse the same way or key off the written PKs.** `_collapse_sections_to_record` shared helper extracted (single-module convention preserved per ADR-022; "split the module" companion finding declined)
- [x] NOTE-line extraction follows S03.6's hardened `^NOTE:[ \t]*` regex (cross-NOTE absorption guard); per-NOTE page-provenance preserved across multi-section groups (cubic P2 fix)
- [x] No `db.py` helper additions (reuses `upsert_regulation_record`); no `ingestion/lib/` edits; `TestNoColoradoLeakIntoSharedLib` stays green
- [x] **ADR-017 FINALIZE lock**: framework unmodified per S03.11 FINALIZE; CO `regulation_record` confidence assigned via `pdf.min_tier` / `ConfidenceTier`; **no `low`-tier rows** (the only `low` row was the skipped blank-GMU section — section-skipped-with-warning per the S06.3.1 heading-absorption residual at section 416; already covered by 3 proper elk sections, no anchor lost)
- [x] Test baseline shifted **1702 → 1774 + 4 skipped** (+72 additive: 72 tests in `test_load_co_regulation_records.py`); ruff + mypy + cubic + detect-secrets all clean
- [x] **3 new pitfalls landed in `.roughly/known-pitfalls.md`** (1,221 → 1,260 LOC): CO records collapse per-method-group sections; CO big-game species pre-separated (no deer fan-out); CO bear artifact is flat list with `record_type` discriminator (don't port MT's dict-with-sources shape; validate loudly)

**Group B — operator-driven post live-fetch + UPSERT (open; not blocking S06.6 close per E05/S04.1 pattern; shares precondition with the outstanding E05 operator Group B geometry writes):**

- [x] Live `supabase` row count: `SELECT COUNT(*) FROM regulation_record WHERE state='US-CO'` returns **398** post-load — *closed via M2-build operator pass 2026-06-23 (PR #74 / `a6cec6b`; env=dev / M2-build); 398 confirmed live*
- [x] SQL-shape verification: every row has populated `source` jsonb (`document_type='annual_regulations'`); `confidence` ∈ `{high, medium}` (no `low` rows); `jurisdiction_code` matches `^CO-GMU-\d+$` for the 398 per-GMU records (0 CO-STATEWIDE rows in V1) — *closed via M2-build operator pass 2026-06-23 (env=dev / M2-build); shape confirmed*
- [x] Per-species count verification: mule_deer 141 / elk 115 / pronghorn 77 / whitetail 19 / bear 46 (sum 398) — *closed via M2-build operator pass 2026-06-23 (env=dev / M2-build); per-species counts + confidence breakdown match dry-run exactly*
- [x] FK validity: every `regulation_record.jurisdiction_code` resolves to a `geometry.id` via the append-`-geom` convention (e.g., `CO-GMU-1` → `CO-GMU-1-geom`); requires CO GMU geometry to exist (E05 Group B precondition) — *closed via M2-build operator pass 2026-06-23 (env=dev / M2-build); 0 dangling FK confirmed*

Group B verification captured in `docs/planning/epics/E06-confidence-findings/S06.6.md` § "Group B verification record"; PM ticks Group B boxes in a follow-up doc-only commit once operator results land.

---

### S06.6.1: PAD-US OBJECTID outFields hardening (operator-pass-discovered carve-out post-S06.6 closure)

**Status:** Closed at-merge 2026-06-22 — squash-merged to main as **PR #72 / `0506831`** from `feat/S06.6.1-padus-objectid-hardening` (9th E06 PR; mid-epic hygiene carve-out closing the M2-build operator pass Step 4 PAD-US OBJECTID drift). **4-commit pre-squash chain**: `b25a9e2` feat → `e2ca357` plan-historical → `b6da979` pitfall → `d8bae0a` post-review strict-coercion P1 fix. **State-agnostic ArcGIS-fetch hardening + the CO restricted-area loader's immediate workaround** shipped clean. **Key design call — strict helper, not a `_read_objectid` mutation** (Stage-4 + Stage-6 endorsed; AC #624's "or its raising caller" sanctions): new `_require_objectid(feature, *, oid_field=None) -> int | str` in `lib/arcgis.py` scans only `properties`/`attributes` (no `feature["id"]` fallback) and raises `ArcGISError` with a diagnostic naming the failure mode + the republish/`outFields` root cause + forensic feature-keys context. `_read_objectid` is unchanged (keeps the fallback) — it has **6 error-message-context callers** (`arcgis.py:335/490/499/510/527/559`) + a dedup loop that legitimately tolerate `None`; mutating the shared helper would have masked errors. Behavior change is **localized to the two OID-critical manifest-hash loops** (`fetch_features` + the CO restricted-area loader's manifest-hash path); both already treated `None` as fatal, now they also refuse the masking `feature["id"]` fallback. Behavior-preserving for GMU/MT in practice (their features carry OBJECTID in `properties`; locked by the new AST test). **Post-review P1 fix (`d8bae0a`)**: the strict helper inherited `_read_objectid`'s `else str(val)` coercion, so a null/non-scalar OBJECTID became `"None"`/`str(obj)` and was accepted — a manifest hash-collision risk. Now `_require_objectid` accepts **only scalar `int`/`str`**; present-but-unusable candidates fall through to siblings (`{"OBJECTID": null, "FID": 42}` → `42`); fails loud otherwise with an enriched diagnostic. **Three spec deviations** (reviewer-confirmed; none blocked at-merge; annotated inline below): **AC #622** `_GMU_OUT_FIELDS` does not exist — `load_gmus.py` (and `load_state_boundary.py`) delegate `outFields` to `fetch_features` via `metadata.out_fields` (server-reported `fields[]`), so `OBJECTID` is naturally requested. Only `_RA_OUT_FIELDS` is a hardcoded tuple. **This is why operator-pass Step 3 (GMUs) succeeded while Step 4 (RA) failed** — different fetch shape, different vulnerability surface. **AC #629** pinned-SHA constant does not exist in `test_load_co_restricted_areas.py` (it mocks `compute_feature_hash`); N/A (the SHA-pin discipline is inherited from extraction-artifact stories, but this story doesn't write extraction artifacts). **AC #627/#628** fixture + manifest regen deferred — requires live PAD-US network + `DATABASE_URL`; the loader has no `--dry-run` flag and no committed PAD-US fixtures exist (S05.4 left them operator-pending Group B). → operator-pass-resume artifact, mirrors S05.0/S05.2/S05.4 posture. **Quality gates (final, on main)**: pytest **1774 → 1783 + 4 skipped** (+9: 8 `TestReadObjectidFailsLoud` + 1 `TestStateAdapterOutFieldsIncludeObjectid`; **spec predicted ~1779 — the +4 strictness tests from the post-review fix make it 1783**); ruff + mypy clean (8 lib files); cubic `{"issues": []}`; detect-secrets passed (1 routine `.secrets.baseline` line-number refresh on the pitfall commit). MT-touched, schema, `db.py`, TS-stack all empty per AC #631-#634. `TestNoColoradoLeakIntoSharedLib` + `TestNoStateAdapterImports` green (ADR-005 state-agnostic-clean preserved despite the `lib/arcgis` edit). **No new ADRs**; refines ADR-001 (fail-loud-over-silent-fallback) + ADR-005 (state-agnostic-clean lib edit). **1 new pitfall** in `.roughly/known-pitfalls.md` § "Integration — ArcGIS" (~lines 107-116; file now ~1270 LOC — doc-writer re-flagged for reorg/dedup): ArcGIS host republish drops top-level `id` unless `OBJECTID` in `outFields`; forensic signal = response CRS shift (PAD-US `4269 → 3857`) captured by `_check_and_fix_projection`; mitigation = `OBJECTID` in every hardcoded `_*_OUT_FIELDS` (locked by the AST test) + `_require_objectid` on OID-critical paths. **No open questions touched.** **Group A satisfied at-merge** (with AC #622 / #627 / #628 / #629 deviation annotations); **Group B operator-pending** (operator resumes M2-build pass from Step 4 against dev; writes 10 CO geometry rows; SHA cross-check; then Steps 5/7/8 unblock). **One M2 hygiene candidate carried for future MT-touching PR**: `ingestion/states/montana/backfill_manifests.py:175-178` carries a now-stale comment ("Mirror the OID-extraction strategy used by fetch_features's manifest path") — the two paths now intentionally diverge (backfill keeps `_read_objectid` because older committed MT fixtures store the OID under `feature["id"]`). Couldn't fix in S06.6.1 (AC #631 MT-untouched). Fold a one-line comment fix into a future MT-touching PR. Closure memo at [`E06-confidence-findings/S06.6.1.md`](E06-confidence-findings/S06.6.1.md) (deletes at `m2` tag per ADR-017 §6).

**Carved out 2026-06-21** during the M2-build operator pass (against the dev Supabase project on branch `test/m2-operator-pass` @ `1f52932`). Step 4 (`ingestion/states/colorado/load_restricted_areas.py` against PAD-US 4.1) failed loud — every feature resolved to `OBJECTID=None` → 0 rows written. Root cause: PAD-US was republished between S05.4 close (2026-06-04) and the operator pass (forensic signal: response CRS shifted `4269 → 3857`, captured by `lib/arcgis._check_and_fix_projection`); the republished service now omits the top-level GeoJSON `id` field unless `OBJECTID` is in the request's `outFields`. The loader's `_RA_OUT_FIELDS` doesn't include `"OBJECTID"`; `lib/arcgis._read_objectid` silently falls back to `feature["id"]` (now empty) → returns `None` → downstream fail-loud. Bug lives in S05.4 territory (E05) but discovered during E06's operator pass, gates S06.7 dispatch, and follows the mid-epic-carve-out convention rather than reopening closed E05. Operator's verbatim root-cause diagnosis is recorded in `docs/runbooks/M2-operator-pass.md` capture form "Step 4 failure" section.

**As a** developer hardening the CO state-adapter ArcGIS fetch surface against upstream republishes
**I want** every CO `_*_OUT_FIELDS` tuple to explicitly include `"OBJECTID"` and `lib/arcgis._read_objectid` to fail loud (not silently fall back to `feature["id"]`) when both OID sites are absent
**So that** future ArcGIS-host republishes surface at the right layer with the right diagnostic, the M2 operator pass resumes from Step 4 against `load_restricted_areas.py`, and S06.7 dispatch unblocks

**UAT: no** (verification-gated against ACs + the operator-pass resume; the resume IS the live verification)

**Context:**

S05.4 closed clean 2026-06-04 with `_RA_OUT_FIELDS = ("Unit_Nm", "Des_Tp", "Mang_Name", "Pub_Access", "GIS_Acres", "Src_Date")`. The PAD-US 4.1 service was republished in the 17-day gap before the operator pass. The republish coupled two upstream changes: (a) native CRS shifted `4269 → 3857` (already handled by `lib/arcgis._check_and_fix_projection` with a warning); (b) GeoJSON top-level `id` field is now omitted unless `OBJECTID` is in `outFields`. Change (b) is the silent-failure trigger. The lib's `feature["id"]` fallback in `_read_objectid` was the masking mechanism that let change (b) bite. Fix-side: (i) immediate workaround — add `"OBJECTID"` to `_RA_OUT_FIELDS`; (ii) lib discipline — `_read_objectid` fails loud with a diagnostic when both sites are absent, removing the silent fallback; (iii) audit other CO `_*_OUT_FIELDS` tuples for the same vulnerability; (iv) lock the convention with an AST-walk regression test.

**Sequencing:** lands **before S06.7** so that the M2 operator pass can resume from Step 4 → 10 against `main`. S06.7 dispatch unblocks once the pass resumes (live S06.6 verification informs S06.7 planning against actual env state).

**Tasks:**

- **T1**: Add `"OBJECTID"` to `_RA_OUT_FIELDS` in `ingestion/states/colorado/load_restricted_areas.py` (append-not-prepend).
- **T2**: Audit `_GMU_OUT_FIELDS` in `load_gmus.py` + any other CO `_*_OUT_FIELDS` tuples (`grep -rn '_OUT_FIELDS' ingestion/states/colorado/`); add `"OBJECTID"` if absent. Operator-pass Step 3 succeeded today so `_GMU_OUT_FIELDS` likely already includes it — confirm in closure note. **Do NOT audit MT** (out of scope; dev-env Steps 0 + 1 confirmed MT loaders are working).
- **T3**: Tighten `lib/arcgis._read_objectid` (or its raising caller) to raise `ArcGISError` immediately when both `properties.OBJECTID` and top-level `id` are absent. Diagnostic message must contain (a) the failure mode, (b) the typical root cause (republish + `outFields` discipline), (c) forensic context: feature's top-level keys + first ~10 property keys. **Behavior change**: removes the silent `feature["id"]` fallback.
- **T4**: New `TestReadObjectidFailsLoud` class in `ingestion/tests/test_arcgis.py` with three tests: (a) `properties.OBJECTID=42` → returns `42`; (b) top-level `id` only, no `properties.OBJECTID` → raises (locks the behavior change); (c) neither present → raises with diagnostic containing literal `"OBJECTID"` + `"outFields"`.
- **T5**: New `TestStateAdapterOutFieldsIncludeObjectid` AST-walk test (mirrors `TestNoColoradoLeakIntoSharedLib` pattern) — walks every `_*_OUT_FIELDS` module-level tuple in `ingestion/states/colorado/load_restricted_areas.py` + `load_gmus.py` (+ any others discovered in T2); asserts `"OBJECTID"` membership in each. Future loader without OBJECTID fails this at PR-time.
- **T6**: Regenerate S05.4 features fixture + manifest via `ingestion/.venv/bin/python ingestion/states/colorado/load_restricted_areas.py --dry-run` from repo root; commit fresh fixture + manifest. **SHA change is expected** (new outFields → new fetch hash; not a determinism regression). Update the pinned-SHA constant in `ingestion/tests/test_load_co_restricted_areas.py` to the new value. Document old SHA → new SHA in closure note (matches S06.3 / S06.4 / S06.3.1 SHA-lineage discipline).
- **T7**: New pitfall under `.roughly/known-pitfalls.md` § "Integration — ArcGIS" naming both the failure mode AND the CRS-republish forensic signal. Doc-writer dispatched in Stage 8 lands the final wording; implementer surfaces the candidate in the closure note (per project convention).

**Deliverables:**

- Modified `ingestion/states/colorado/load_restricted_areas.py` (`_RA_OUT_FIELDS` includes `"OBJECTID"`).
- Modified `ingestion/states/colorado/load_gmus.py` if `_GMU_OUT_FIELDS` missing `"OBJECTID"` (confirmed in closure note either way).
- Modified `ingestion/ingestion/lib/arcgis.py` — `_read_objectid` (or caller) fails loud with diagnostic.
- New `TestReadObjectidFailsLoud` class in `test_arcgis.py` (3 tests).
- New `TestStateAdapterOutFieldsIncludeObjectid` AST-walk regression test.
- Regenerated PAD-US features fixture + manifest with new pinned SHA.
- Updated pinned-SHA constant in `test_load_co_restricted_areas.py`.
- New pitfall candidate surfaced in closure note; doc-writer lands final wording in `.roughly/known-pitfalls.md` § "Integration — ArcGIS".
- `docs/planning/epics/E06-confidence-findings/S06.6.1.md` closure memo with old SHA → new SHA lineage + audit findings + Phase-equivalent decisions log (deletes at `m2` tag per ADR-017 §6).

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md) (fail-loud-over-silent-fallback), [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) (state-adapter isolation — the `lib/arcgis` edit is state-agnostic-clean; `TestNoColoradoLeakIntoSharedLib` + `TestNoStateAdapterImports` stay green).

**Depends on:** S06.6 closure (✓ 2026-06-19); M2 operator pass Step 4 failure forensics captured in `docs/runbooks/M2-operator-pass.md` (✓ 2026-06-21).

**Unblocks:** M2 operator pass resume from Step 4 → 10 (live verification of S05.0 + S05.2 + S05.3.5 + S05.4 + S05.5 + S05.7 + S06.5 + S06.6 Group B writes against dev); S06.7 dispatch.

**Acceptance Criteria:**

**Group A — at-merge:**

- [x] `_RA_OUT_FIELDS` in `ingestion/states/colorado/load_restricted_areas.py` contains `"OBJECTID"` (T1 shipped; multi-line tuple, append-not-prepend).
- [N/A] `_GMU_OUT_FIELDS` in `ingestion/states/colorado/load_gmus.py` contains `"OBJECTID"` (whether pre-existing or newly added — confirm in closure note). **→ DEVIATION (closure-confirmed):** `_GMU_OUT_FIELDS` does not exist as a hardcoded tuple — `load_gmus.py` (and `load_state_boundary.py`) delegate `outFields` to `fetch_features` via `metadata.out_fields` (server-reported `fields[]`), so `OBJECTID` is naturally requested. Only `_RA_OUT_FIELDS` is a hardcoded tuple. This is why operator-pass Step 3 (GMUs) succeeded while Step 4 (RA) failed — different fetch shape, different vulnerability surface. No GMU code change required.
- [x] Any other CO state-adapter `_*_OUT_FIELDS` tuples discovered in T2 contain `"OBJECTID"` (T2 audit found only `_RA_OUT_FIELDS`; AST test locks the convention going forward — any future hardcoded `_*_OUT_FIELDS` without `"OBJECTID"` fails at PR-time).
- [x] `lib/arcgis._read_objectid` (or its raising caller) raises `ArcGISError` with a diagnostic message containing the literal strings `"OBJECTID"` + `"outFields"` when both `properties.OBJECTID` and top-level `id` are absent. **Shipped as new strict helper `_require_objectid(feature, *, oid_field=None) -> int | str`** (not a mutation of `_read_objectid`) — Stage-4 + Stage-6 endorsed; AC's "or its raising caller" sanctions the separate helper. `_read_objectid` is unchanged (keeps the fallback for 6 error-message-context callers + the dedup loop that legitimately tolerate `None`); mutating the shared helper would have masked errors. Behavior change is localized to the two OID-critical manifest-hash loops (`fetch_features` + the CO restricted-area loader's manifest-hash path).
- [x] New `TestReadObjectidFailsLoud` class in `test_arcgis.py` covers all three sub-cases: properties-OBJECTID returns int; top-level-id-only raises (locks the behavior change from the old silent fallback); neither-present raises with diagnostic. **Actual: 8 tests** (3 spec'd + 5 added across implementation + the post-review strict-coercion P1 fix: scalar-only `int`/`str` enforcement; fall-through to siblings on present-but-unusable; null/non-scalar fail-loud with enriched diagnostic).
- [x] New `TestStateAdapterOutFieldsIncludeObjectid` AST-walk test asserts `"OBJECTID"` membership in every `_*_OUT_FIELDS` tuple in the CO state-adapter dir; a future loader omitting OBJECTID fails this test (1 test; AST walk over the entire CO adapter dir, not just `load_restricted_areas.py` + `load_gmus.py`).
- [Deferred] `ingestion/states/colorado/fixtures/Federal_Fee_Managers_Authoritative_PADUS-0-features-*.geojson` regenerated + committed (new SHA, expected — not a determinism regression). **→ DEFERRED to operator-pass-resume (Group B equivalent):** the loader has no `--dry-run` flag and no committed PAD-US fixtures exist (S05.4 left them operator-pending Group B). Operator regenerates + commits on pass resume; mirrors S05.0/S05.2/S05.4 posture.
- [Deferred] `ingestion/states/colorado/fixtures/Federal_Fee_Managers_Authoritative_PADUS-0-manifest-*.json` regenerated + committed (new SHA, expected). **→ DEFERRED to operator-pass-resume** (paired with the features fixture above).
- [N/A] Pinned-SHA constant in `test_load_co_restricted_areas.py` updated to the new fixture SHA; old SHA → new SHA lineage documented in `docs/planning/epics/E06-confidence-findings/S06.6.1.md`. **→ DEVIATION:** pinned-SHA constant does not exist — `test_load_co_restricted_areas.py` mocks `compute_feature_hash`. SHA-pin discipline is inherited from extraction-artifact stories (S06.3/S06.4/S06.3.1); this story doesn't write extraction artifacts. No constant to update.
- [x] New pitfall candidate surfaced in closure note; doc-writer dispatched in Stage 8 lands the final wording in `.roughly/known-pitfalls.md` § "Integration — ArcGIS" — names both the failure mode AND the CRS-republish forensic signal. Landed at `b6da979` (file now ~1270 LOC — doc-writer re-flagged for reorg/dedup).
- [x] `git diff --stat ingestion/states/montana/` empty at merge (PRD 002 SC #9 — MT untouched).
- [x] `git diff --stat supabase/migrations/` empty (no schema changes).
- [x] `git diff --stat ingestion/ingestion/lib/db.py` empty (no DB-write semantics change).
- [x] `git diff --stat mcp-server/ web/` empty (TS-stack untouched).
- [x] No new ADRs.
- [x] ruff + mypy clean across edited files (8 lib files clean).
- [x] `cubic review --json` returns `{"issues": []}` on uncommitted changes (per session hook; iterate until clean).
- [x] detect-secrets passes (1 routine `.secrets.baseline` line-number refresh on the pitfall commit).
- [x] Test baseline shifts approximately **1774 → ~1779 + 4 skipped** (+3 from `TestReadObjectidFailsLoud` + 1 from `TestStateAdapterOutFieldsIncludeObjectid` + ~1 SHA-pin-update test; net pytest count grows by ~5; no regressions on the M2-build floor of 1774). **Actual: 1774 → 1783 + 4 skipped (+9)** — the +4 strictness tests from the post-review P1 fix made it 1783 not 1779; no regressions.
- [x] `TestNoColoradoLeakIntoSharedLib` + `TestNoStateAdapterImports` both green (ADR-005 state-agnostic-clean preserved despite the `lib/arcgis` edit).

**Group B — operator-pending (closes via the M2 operator-pass resume from Step 4):**

- [x] Operator resumes the M2 operator pass from Step 4 against the dev Supabase project; `load_restricted_areas.py` writes **10 CO geometry rows** (the V1 federal no-hunt zones: 4 NPs + 5 NMs + AFA, Curecanti dropped per 36 CFR §2.2); all fail-loud guards hold; the live-fetch SHA matches the regenerated committed fixture (Deferred AC #627/#628 + N/A AC #629 fold here on resume) — *closed via M2-build operator pass 2026-06-23 (PR #74 / `a6cec6b`; env=dev / M2-build); 10 zones written; live PAD-US fetch worked under the new `_require_objectid` strict path; AC #627/#628 already closed via S06.6.2 Phase D metadata+manifest commits at the corrected gitignore convention*
- [x] M2 operator pass Steps 5 / 7 / 8 (overlay fixture / spatial verification / S06.5 verbatim_rule) unblock and complete clean. *Closed via M2-build operator pass 2026-06-23 — Steps 5/7/8 all PASS (env=dev / M2-build).*

---

### S06.6.2: PAD-US GeometryCollection area-preservation handling for 10 V1 no-hunt zones (second operator-pass-discovered carve-out)

**Status:** Group A complete at-merge 2026-06-23 (3-commit chain `161d339` feat → `9878f33` plan-historical → `303fade` pitfalls; on `feat/S06.6.2-padus-geometrycollection-area-preservation`); Group B operator-pending (closes via the M2-build operator-pass second resume from Step 4). Carved out 2026-06-22 post-S06.6.1 closure during the M2-build operator-pass resume (mirrors S03.6.1 / S05.3.5 / S06.3.1 / S06.6.1 mid-epic carve-out precedent; **second consecutive carve-out triggered by PAD-US 4.1 drift after the same upstream republish**). **Outcome (a)** locked: `geojson_to_multipolygon_wkt` area-preservation epsilon relaxed `rel_tol=1e-6 → 1e-3` (RMNP's 0.0676% benign ring-self-intersection cleanup artifact recovers; genuine loss > 0.1% still raises). Deferred S06.6.1 AC #627/#628 closed (metadata + manifest committed; features payload gitignored per Option A). Test baseline 1783 → 1787 + 4 skipped. Closure memo at `docs/planning/epics/E06-confidence-findings/S06.6.2.md`.

**Carved out 2026-06-22** during the M2-build operator-pass second resume attempt. After S06.6.1's PR #72 / `0506831` cleared the OBJECTID/outFields raise, the operator resumed Step 4 against dev — and immediately hit a second, distinct PAD-US 4.1 republish drift. Specifically: the first feature in the fetch loop (Rocky Mountain National Park) passed `_require_objectid` but raised inside `lib/arcgis.geojson_to_multipolygon_wkt` (`arcgis.py:349-374`) — the existing fail-loud GeometryCollection area-preservation guard fired with `"polygonal parts do not preserve area"`. The raise is **correct per the existing discipline** (`math.isclose(recovered.area, parsed.area, rel_tol=1e-6, abs_tol=1e-12)` — meaningful area loss is a data-quality issue, not benign cleanup). The discipline did its job. The question is whether the new RMNP shape returned by republished PAD-US 4.1 carries genuinely-lossy topology (in which case ingest is questionable until upstream cleans up) or whether the area-loss is a sub-percent artifact of stricter `make_valid()` behavior on the new tessellation (in which case the epsilon may warrant per-feature documented relaxation). **Critically: only RMNP was reached before the raise; the other 9 zones are unvalidated against the republished layer.** This story validates ALL 10 V1 federal no-hunt zones (4 NPs + 5 NMs + AFA — Curecanti dropped per 36 CFR §2.2) in one pass to avoid a third resume-time blocker.

**As a** developer hardening CO restricted-area ingestion against PAD-US 4.1 republish drift in geometry topology
**I want** all 10 V1 federal no-hunt zones live-fetched + characterized for area-preservation behavior, the `lib/arcgis.geojson_to_multipolygon_wkt` GeometryCollection branch updated per the investigation outcome (epsilon-loosen with documented threshold, re-source affected zones, or pre-process geometry differently), and the deferred S06.6.1 fixture + manifest committed
**So that** the M2-build operator pass resumes from Step 4 → 10 cleanly without further upstream-drift surprises, the existing fail-loud discipline is preserved, and MT loaders aren't regressed by the lib edit

**UAT: no** (verification-gated against ACs + the operator-pass resume Step 4 → 10; the resume IS the live verification across all 10 zones)

**Context:**

S06.6.1's PR #72 fixed the OID-extraction silent-fallback failure mode. The operator's second resume attempt now surfaces a different failure mode in the same upstream feed: **post-republish RMNP geometry, when canonicalized via `shapely.make_valid()`, returns a `GeometryCollection` whose polygonal-component area diverges from the parsed input area by more than `rel_tol=1e-6`**. The lib's strict area-preservation check (`arcgis.py:352-374`) raises on this — by design — because the docstring's intent is: *"lossy cases (partial overlaps, slivers carrying real area) still raise; the WARNING captures benign cleanup (e.g., make_valid leaving an isolated LineString edge)."*

The story does NOT presume the fix. **Investigation precedes implementation** (S06.3.1 Phase A/B/C precedent). The investigation outcome dictates the lib edit; the spec doesn't lock in epsilon-loosening, re-sourcing, or pre-processing-refactor a priori — those are Phase B branches.

**Two-drift pattern note for the M2 PM ledger** (carry-forward; not in this story's scope to resolve): two distinct PAD-US 4.1 republish drift hits in 18 calendar days (2026-06-04 close → 2026-06-21 OID drift → 2026-06-22 GeometryCollection drift). The strategic question — pin a PAD-US snapshot fixture + cache forever vs continue patching live-fetch drift vs re-source — surfaces as a **separate M2-release / M3 candidate** for the user to consider at their convenience. This story is purely tactical: get all 10 zones converting cleanly so the operator pass completes.

**Sequencing:** lands **before S06.7** so the M2-build operator pass can resume from Step 4 → 10 against `main`. S06.7 dispatch unblocks once the pass resumes (live S06.6 Group B verification informs S06.7 planning).

**Phases:**

**Phase A — Investigate (10-zone live characterization):**

The implementation agent live-fetches all 10 V1 PAD-US no-hunt zones from the republished Federal Fee Managers Authoritative FeatureServer and characterizes geometry behavior for each:

For each of the 10 zones (4 NPs: Rocky Mountain, Mesa Verde, Great Sand Dunes, Black Canyon of the Gunnison; 5 NMs: Dinosaur, Colorado NM, Florissant Fossil Beds, Hovenweep, Yucca House; 1 DOD: AFA), capture:

1. Raw GeoJSON geometry type (Polygon / MultiPolygon / other).
2. `shapely.shape(geom_dict)` parsed type + area.
3. `shapely.make_valid()` output type (Polygon / MultiPolygon / GeometryCollection).
4. If GeometryCollection: unioned polygonal-parts area + `(recovered.area - parsed.area) / parsed.area` relative discrepancy + count + types of non-polygonal artifacts.
5. Whether the current `geojson_to_multipolygon_wkt` path raises or passes.

Record findings in `docs/planning/epics/E06-confidence-findings/S06.6.2.md` § "Phase A characterization" as a 10-row table.

**Phase B — Decide (outcome locks in Phase C scope):**

Based on Phase A findings, lock one of three outcomes (or document hybrid):

- **Outcome (a) Documented epsilon relaxation** — if all affected zones have relative area-loss below a defensible threshold (e.g., `1e-4` = 0.01% relative tolerance), loosen the epsilon in `lib/arcgis.geojson_to_multipolygon_wkt` with an inline comment explaining the threshold + the PAD-US republish trigger + the per-zone max-observed area-loss (lock in a regression test). Preserves fail-loud for anything worse than the threshold.
- **Outcome (b) Re-source affected zones** — if any zone has relative area-loss > 0.1% (a real data-quality concern), re-source those specific zones from a more authoritative layer (e.g., NPS Boundary Service, USFWS Cadastral, or a direct download cached as a fixture). This is heavier (multi-source provenance touches PRD 002 L176 ADR-candidate; ADR may be required). PM surfaces the trigger to the human for ADR decision before Phase C ships if outcome (b) fires.
- **Outcome (c) Pre-process differently** — if a smarter geometry-normalization path (e.g., `buffer(0)` before `make_valid`, `simplify(0)` to coalesce duplicate rings, or alternative shapely call sequence) preserves area for affected zones without epsilon relaxation, refactor the lib's geometry path. Requires lib + test changes.

The PM expectation is **outcome (a)** with a documented small epsilon relaxation IF the area-loss is genuinely sub-percent. **Outcome (b)** fires only if a zone is genuinely lossy (>0.1%). **Outcome (c)** is the cleanest if a no-cost geometry pre-process exists.

**Phase C — Implement (state-agnostic-clean lib edit + tests):**

Apply Phase B outcome to `ingestion/ingestion/lib/arcgis.geojson_to_multipolygon_wkt`. State-agnostic-clean preserved per ADR-005 + ADR-022; `TestNoColoradoLeakIntoSharedLib` + `TestNoStateAdapterImports` must stay green. **MT-regression-guard**: the existing `test_arcgis.py` `TestGeojsonToMultipolygonWkt` suite + the broader MT loader tests provide the regression surface; lib edit must NOT change MT behavior. (Note: MT raw features payloads are gitignored per the uniform `*-features-*.geojson` discipline — the durable regression-guard surface is the existing unit tests + each MT loader's existing tests, not the gitignored features files.) New unit tests lock the chosen outcome (epsilon value, pre-process step, or re-source manifest).

**Phase D — Commit deferred S06.6.1 fixture + manifest:**

During Phase A's live fetch, the implementation agent captures the 10-zone **manifest + metadata fixtures** (the canonical drift-detection artifacts per the established `ingestion/states/colorado/fixtures/.gitignore` convention: metadata `~7KB` + manifest `~5KB` ARE committed; `*-features-*.geojson` `~1.4MB` payload stays gitignored under the uniform-with-MT discipline documented in the gitignore preamble). Commit the manifest + metadata alongside the lib fix; this closes S06.6.1's deferred AC #627/#628 (the operator-pass-resume artifact moves from "deferred" to "shipped" inline with S06.6.2). SHA + provenance lineage documented in the S06.6.2 closure memo. **Note**: S06.6.1's literal AC #627 wording ("features-*.geojson committed") was spec drift — S06.6.1's surrounding narrative correctly framed the deferral as "mirrors S05.0/S05.2/S05.4 posture" (which is metadata + manifest only). S06.6.2 closes both ACs per convention; the deviation is documented in S06.6.2's closure memo.

**Phase E — Pre-merge 10-zone validation:**

Before merge, the implementation agent runs the integration test (locally, mocked from the captured Phase A fixture) to confirm **all 10 zones convert cleanly** through the updated lib path. The live operator-pass-resume Step 4 is the final live verification (operator-pending Group B AC). If Phase B chose outcome (b) and one or more zones are re-sourced, the integration test covers the new source path too.

**Tasks:**

- **T1**: Phase A — live-fetch all 10 V1 PAD-US no-hunt zones; characterize geometry behavior per the 5 data points above; record in `docs/planning/epics/E06-confidence-findings/S06.6.2.md` § "Phase A characterization" as a 10-row table.
- **T2**: Phase B — based on T1 findings, lock outcome (a) / (b) / (c) (or document hybrid) in the closure memo § "Phase B decision". If outcome (b), pause + surface to PM (flag-and-discuss) before continuing.
- **T3**: Phase C — apply T2 outcome to `ingestion/ingestion/lib/arcgis.geojson_to_multipolygon_wkt`. State-agnostic-clean preserved. If outcome (a), update the `math.isclose(...)` epsilon with an inline comment naming the threshold + PAD-US republish trigger + per-zone area-loss table. If outcome (c), refactor geometry pre-process step with comment.
- **T4**: New unit tests for the T3 lib change (lock the outcome — epsilon value or pre-process step). MT-regression-guard: existing tests in `test_arcgis.py` (`TestGeojsonToMultipolygonWkt`) stay green; new tests cover the post-republish RMNP shape.
- **T5**: New integration test (mocked from Phase A captures) that runs all 10 zones through the updated `geojson_to_multipolygon_wkt` path; asserts all 10 convert cleanly (no raise) + asserts the expected MultiPolygon WKT shape for each.
- **T6**: Phase D — commit fresh PAD-US **manifest + metadata fixtures** captured during T1 live-fetch (the `*-features-*.geojson` payload stays gitignored per `fixtures/.gitignore` convention; do NOT force-add past the gitignore — that would break the uniform-with-MT discipline). SHA lineage documented in closure memo. Closes deferred S06.6.1 AC #627/#628 per convention (with the spec-drift deviation noted in the closure memo).
- **T7**: New pitfall candidate under `.roughly/known-pitfalls.md` § "Integration — ArcGIS" naming the second-drift pattern (PAD-US 4.1 republish on 2026-06-22 changed both OID-emission AND geometry topology; lib's strict area-preservation discipline correctly surfaces lossy topology — the fix is to characterize the loss + document the threshold, not to loosen discipline broadly). Doc-writer dispatched in Stage 8 lands final wording.
- **T8**: Closure memo at `docs/planning/epics/E06-confidence-findings/S06.6.2.md` with Phase A characterization table + Phase B decision + outcome rationale + per-zone area-loss numbers (if outcome (a)) + SHA lineage (Phase D) + deferred S06.6.1 AC closure note (deletes at `m2` tag per ADR-017 §6).

**Deliverables:**

- Modified `ingestion/ingestion/lib/arcgis.py` (`geojson_to_multipolygon_wkt` GeometryCollection branch updated per Phase B outcome; inline rationale comment with PAD-US republish trigger + per-zone area-loss data).
- New tests in `ingestion/tests/test_arcgis.py` locking the outcome + the 10-zone integration test.
- Committed `ingestion/states/colorado/fixtures/Federal_Fee_Managers_Authoritative_PADUS-0-manifest-*.json` + `Federal_Fee_Managers_Authoritative_PADUS-0-metadata-*.json` (the canonical drift-detection artifacts per `fixtures/.gitignore` convention; closes deferred S06.6.1 AC #627/#628). The `*-features-*.geojson` raw payload stays gitignored per the uniform-with-MT discipline documented in the `fixtures/.gitignore` preamble.
- New pitfall under `.roughly/known-pitfalls.md` § "Integration — ArcGIS" (doc-writer-polished wording).
- Closure memo `docs/planning/epics/E06-confidence-findings/S06.6.2.md`.

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md) (fail-loud-over-silent-fallback; the area-preservation guard is the canonical enforcement; this story preserves the discipline with documented thresholds, not erosion). [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) (state-adapter isolation — the `lib/arcgis` edit is state-agnostic-clean; `TestNoColoradoLeakIntoSharedLib` + `TestNoStateAdapterImports` stay green; MT-regression-guard via existing MT committed fixtures). **Conditional ADR**: if Phase B outcome (b) fires (re-source one or more zones from a non-PAD-US authoritative layer), a new ADR is required addressing multi-source provenance for the 10 federal no-hunt zones (currently a deferred PRD 002 L176 ADR-candidate; D5 = (b) split-provenance from S06.0 covers single-source-per-row; a per-zone source split needs schema decision). PM surfaces this flag-and-discuss before Phase C ships if outcome (b) fires.

**Depends on:** S06.6.1 closure (✓ 2026-06-22 — PR #72 / `0506831`); M2 operator pass second-resume Step 4 failure forensics captured in `docs/runbooks/M2-operator-pass.md` capture form (✓ 2026-06-22).

**Unblocks:** M2 operator pass second resume from Step 4 → 10 (live verification of S05.0 + S05.2 + S05.3.5 + S05.4 + S05.5 + S05.7 + S06.5 + S06.6 + S06.6.1 + S06.6.2 Group B writes against dev); S06.7 dispatch.

**Acceptance Criteria:**

**Group A — at-merge:**

- [x] Phase A 10-zone characterization table committed in `docs/planning/epics/E06-confidence-findings/S06.6.2.md`; every V1 zone (4 NPs + 5 NMs + 1 DOD = 10) covered with the 5 data points (raw geom type / parsed type / make_valid output type / area-loss / current-path raises-or-passes).
- [x] Phase B decision locked in closure memo — outcome (a) documented with rationale + per-zone numbers (max area-loss RMNP −0.0676%; no zone > 0.1%; outcome (b) did NOT fire so no PM flag-and-discuss / no ADR).
- [x] `ingestion/ingestion/lib/arcgis.geojson_to_multipolygon_wkt` edited per Phase B outcome (a) — `rel_tol=1e-6 → 1e-3`; inline comment names the PAD-US republish trigger + per-zone area-loss summary + threshold rationale.
- [x] New unit tests in `test_arcgis.py` lock the Phase B outcome (a) — two epsilon-boundary tests (−0.05% recovers / −0.2% raises) + a real `make_valid`→GeometryCollection self-intersection test exercising the genuine RMNP mechanism.
- [x] New 10-zone integration test in `test_arcgis.py` (`TestPadusTenZoneIntegration`) confirms all 10 V1 PAD-US no-hunt zones convert cleanly through the updated `geojson_to_multipolygon_wkt` path (no raise on any of the 10) — passes locally against the captured fixture (skips in CI where the gitignored payload is absent; live operator-pass Step 4 is the final verification).
- [x] Existing `TestGeojsonToMultipolygonWkt` tests stay green (MT-regression-guard — the ~12.5% overlapping-polygon raise-test still raises at 1e-3).
- [x] `ingestion/states/colorado/fixtures/Federal_Fee_Managers_Authoritative_PADUS-0-metadata-*.json` committed — the drift-detection artifact per `fixtures/.gitignore` convention; closes deferred S06.6.1 AC #627 per convention (the literal "features-*.geojson committed" wording in S06.6.1 AC #627 was spec drift against the established `fixtures/.gitignore` rule that gitignores `*-features-*.geojson`; S06.6.1's surrounding deferral narrative correctly framed the posture as "mirrors S05.0/S05.2/S05.4" which committed metadata + manifest only; deviation documented in S06.6.2 closure memo).
- [x] `ingestion/states/colorado/fixtures/Federal_Fee_Managers_Authoritative_PADUS-0-manifest-*.json` committed — the drift-detection artifact per `fixtures/.gitignore` convention; closes deferred S06.6.1 AC #628.
- [x] `*-features-*.geojson` raw payload NOT committed (stays gitignored per the uniform-with-MT discipline in `fixtures/.gitignore`; `git check-ignore` confirmed).
- [x] New pitfall under `.roughly/known-pitfalls.md` § "Integration — ArcGIS" — names the second-drift pattern + the discipline-preservation rationale (doc-writer landed final wording; stale `rel_tol=1e-6` reference at the existing make_valid entry also refreshed to `1e-3`).
- [x] `git diff --stat ingestion/states/montana/` empty at merge (PRD 002 SC #9 — MT untouched).
- [x] `git diff --stat supabase/migrations/` empty (no schema changes; outcome (b) did not fire).
- [x] `git diff --stat ingestion/ingestion/lib/db.py` empty (no DB-write semantics change).
- [x] `git diff --stat mcp-server/ web/` empty (TS-stack untouched).
- [x] No new ADRs (outcome (a) needs none).
- [x] ruff + mypy clean across edited files.
- [x] `cubic review --json` — **NOTE: not literally `{issues: []}`.** 3 iterations; the integration-test-CI-skip and test-readability findings were fixed. The sole residual finding (P1) is the deliberate `1e-3` relaxation tradeoff, accepted-by-design as documented-deferral per the Stage-6 cubic-termination option (c). See closure memo § "Cubic review disposition".
- [x] detect-secrets passes (2 false-positive hex entries — `layer_hash` SHA-256 + ArcGIS `serviceItemId` GUID in the committed fixtures — added to `.secrets.baseline`).
- [x] Test baseline shifts additively, no regressions — **1783 → 1787 + 4 skipped (+4)**. (Actual +4 is just under the spec's +5–15 estimate; outcome (a) was a minimal one-literal fix needing fewer new tests than a heavier outcome would have.)
- [x] `TestNoColoradoLeakIntoSharedLib` + `TestNoStateAdapterImports` green (ADR-005 state-agnostic-clean preserved despite the `lib/arcgis` edit).
- [x] Closure memo at `docs/planning/epics/E06-confidence-findings/S06.6.2.md` complete (Phase A table + Phase B decision + Phase C summary + Phase D fixture lineage + Phase E pre-merge validation summary + Cubic disposition).

**Group B — operator-pending (closes via the M2-build operator-pass second resume from Step 4):**

- [x] Operator resumes the M2-build operator pass from Step 4 against the dev Supabase project; `load_restricted_areas.py` writes **10 CO geometry rows** (the V1 federal no-hunt zones: 4 NPs + 5 NMs + AFA, Curecanti dropped per 36 CFR §2.2); all fail-loud guards hold; live-fetch SHA matches the committed fixture from Phase D — *closed via M2-build operator pass 2026-06-23 (PR #74 / `a6cec6b`; env=dev / M2-build); 10 zones written; live PAD-US fetch worked under the relaxed `rel_tol=1e-3` epsilon; RMNP recovered via `make_valid()` → `GeometryCollection` → `MultiPolygon` with 0.0676% area-loss WARNING logged as expected; computed acres match PAD-US `GIS_Acres`*
- [x] M2-build operator pass Steps 5 / 7 / 8 (overlay fixture / spatial verification / S06.5 verbatim_rule) unblock and complete clean. *Closed via M2-build operator pass 2026-06-23 — Steps 5/7/8 all PASS (env=dev / M2-build).*

**Notes for the implementation agent:**

- **Read `docs/runbooks/M2-operator-pass.md` capture form "Step 4 failure (second)" section** for the operator's verbatim diagnosis. The forensic-signal detail (CRS `4269 → 3857` confirmed; new failure mode is GeometryCollection area-preservation, not OID-extraction) is worth preserving in the closure memo.
- **Live network access required** for Phase A (live-fetch all 10 from the republished PAD-US 4.1 FeatureServer). If the agent doesn't have network access, surface to PM immediately — the spec is unworkable without it.
- **Stage-4 plan review must explicitly endorse the Phase B outcome** before Phase C implementation. The decision is load-bearing for the lib's fail-loud discipline.
- **Stage-6 review triad should pay particular attention to**: (a) whether the chosen epsilon (outcome a) is documented with per-zone evidence and not over-loose; (b) whether MT committed fixtures still pass the updated path (MT-regression-guard); (c) whether the inline rationale comment captures enough forensic context for a future PAD-US drift to be diagnosed faster.
- **The branch this story merges to is `main`**. The operator-pass branch `test/m2-operator-pass` will merge `main` forward after merge to pick up the fix.
- **Branch naming convention:** `feat/S06.6.2-padus-geometrycollection-handling` off `main`.
- **PM does NOT autonomously draft an ADR even if outcome (b) fires** — the implementation agent surfaces the trigger via the closure memo's "PM flag-and-discuss event" entry; the PM then surfaces it to the human for ADR decision before Phase C ships.
- **The strategic question** "PAD-US 4.1 source stability — pin vs re-source vs continue patching" is **out of scope for this story** but worth flagging in the closure memo as a separate M2-release / M3 candidate the PM tracks.

---

### S06.7: `season_definition` + `license_tag` + `license_season` ingestion (drift_guard.assert_id_matches mandatory)

**Status:** **Group A closed at-merge 2026-06-24** — squash-merged to main as **PR #75 / `433ea73`** from `feat/S06.7-season-definition-license-tag-ingestion` (**11th E06 PR**; 7-commit pre-squash chain: `569941c` impl + `b8f0cae` plan-historical + `2ccb73d` pitfalls + `891fc5b` closure docs + `98b2776` + `0b70b83` + `0107e2b` 3 post-review hardening commits including the round-2 widened lossy-dedup comparison + the round-3 declined-with-rationale `TestInterleavedNullWindowIndexAlignment` AC-equivalent lock for the "Season Choice window-index drift" finding the PM jointly investigated 2026-06-24 and rejected as invalid by construction). New `ingestion/states/colorado/load_seasons_and_licenses.py` (~1700 LOC, state-agnostic-clean, three-phase) + `ingestion/tests/test_load_co_seasons_and_licenses.py` (111 tests). **Dry-run row counts** (real artifacts): `season_definition=2013`, `license_tag=2470`, `license_season=2013`, `regulation_season=2013`, `regulation_license=2470`; 5 ±30% band guards fire pre-`db.connect()` (`_SEASON_DEFINITION_BAND=(1409,2617)`, `_LICENSE_TAG_BAND=(1729,3211)`, `_LICENSE_SEASON_BAND=(1409,2617)`, `_REGULATION_SEASON_BAND=(1409,2617)`, `_REGULATION_LICENSE_BAND=(1729,3211)`). **Q20 (Season Choice `X`) resolved → per-window fan-out** (human decision 2026-06-23; see `docs/open-questions.md` Q20 RESOLVED + the S06.7 closure memo): one `season_definition` per method-window, one `license_tag` carrying the weapon-type union, `license_season` links the tag to all its seasons; 0-window X rows emit the tag + WARNING, no silent gap. **Q16 does NOT fire** (CO species pre-separated — no `deer` fan-out; verified by a no-accidental-fan-out test). **Q17 does NOT fire** at the season/license layer (repeated hunt_codes are legit multi-GMU listings). **closure-temporal `effective_after` does NOT fire** (no bear closures in CO V1). **Asymmetric-coverage demonstrator (PRD 002 SC #2) locked** on GMU 001 mule_deer (archery `D-M-001-O1-A` / muzzleloader `D-M-001-O1-M` / rifle `D-M-001-O2-R` → 3 distinct seasons + 3 tags under one regulation_record) via `test_license_season_asymmetric_coverage_m2_criterion`. **ADR-020**: `assert_id_matches` at all 4 entity-builder construction sites; 3 link builders NOT instrumented (AST-locked by `TestDriftGuardCallSites` + `TestLinkTableNotInstrumented`). **`apply_by` is null on every CO row** → the kind heuristic derives from `list_value` (big-game A→limited_draw / B→over_the_counter / C→limited_draw, fail-loud else) and the bear section-level `license_kind` field (the spec's "inspect `apply_by` for OTC" is N/A for CO; documented deviation). **Review** (3-agent + 1 fix cycle) resolved 2 Critical + 4 Warning findings — most notably visibility WARNINGs for the ~477 female-row empty-`season_windows` gap (see Known Issue #13) and for lossy dedup of differing content; fail-loud guards on empty `weapon_types`; removed a dead `season_code` param from `_co_season_definition_id`. Quality gates: ruff + mypy clean (`states.colorado` 14 files + `lib` 8 files); **pytest 1787 → 1907 + 4 skipped** (+120 additive, zero regressions). No `ingestion/lib/` edits, no schema/migration/three-place-sync, no `db.py` changes (reused the 5 existing helpers), no MT touches, no TS-stack diffs, no ADRs. `license_tag.draw_spec_key=None` on every row (S06.8 backfills per ADR-012). **Group B (live DB write)** remains operator-pending — gated on the M2-build operator pass; the dry-run path is fully verified. Closure memo at `docs/planning/epics/E06-confidence-findings/S06.7.md`.

**Status (original):** Not Started

**As a** developer writing CO's per-season + per-license entities + their cross-shared link table
**I want** `season_definition`, `license_tag`, `license_season`, `regulation_season`, `regulation_license` rows written with verbatim per-season-window + per-license text, with ADR-020 `drift_guard.assert_id_matches` instrumenting the row-construction surfaces
**So that** S06.8 (draw_spec) has FK targets in `license_tag`, S06.10 (binding) sees the full multi-link picture, and id-text-PK drift is impossible at runtime

**UAT: no** (verification at SQL-count level; faithfulness already established at S06.3)

**Context:**

Mirrors M1's S03.7 pattern. CO's multi-link adapter — the first E06 story producing two link tables alongside two entities. Atomic three-phase transaction; guards fire pre-`db.connect()`.

**ADR-020 drift_guard mandate:** per the helper-to-table mapping:

- `db.upsert_season_definition` UPSERT → `season_definition` id is built from `(state, hunt_code_or_gmu, season_key)` or analog; the `season_definition` build function MUST call `drift_guard.assert_id_matches(season_def, expected_id_template)` per ADR-020's `assert_id_matches` primitive
- `db.upsert_license_tag` UPSERT → `license_tag` id is built from `(state, gmu_number_or_similar, license_code)` or analog; the `license_tag` build function MUST call `drift_guard.assert_id_matches(license_tag, expected_id_template)` per ADR-020
- `db.write_license_season` link-table write → NOT instrumented (link-table builder carve-out preserved; M1 regression-guard AST test enforces)
- `db.write_regulation_season` / `db.write_regulation_license` → NOT instrumented (same carve-out)

**11 decisions to bake in** (per S03.7 OQ-S7-1 through OQ-S7-11 — CO-specific values; surface every divergence from MT to human via flag-and-discuss):

1. **License-tag species granularity** — CO artifact-level `deer` vs DB `mule_deer`/`whitetail` — flag if CPW separates at row level (Q16 trigger)
2. **Season-definition species granularity** — same Q16 trigger
3. **Asymmetric license-coverage demonstrator** — find a CO equivalent of MT HD 170 elk where A-license-coverage ≠ B-license-coverage; lock in test (PRD 002 success criterion #2 — milestone-level UAT)
4. **Season-name rendering** — `_SEASON_NAME_BY_KEY` analog for CO season keys
5. **Bear closure_predicate attachment** — if CO publishes bear quotas with sex/threshold predicates (M1's `sex_threshold` / `quota_threshold` patterns), check if CO uses the same shape; if CO surfaces a closure conditional on calendar gate AND quota threshold, the `effective_after` ADR-candidate triggers (closure-temporal-anchors.md)
6. **License-tag kind heuristic** — 5-ordered-branch heuristic from S03.7 OQ-S7-7 + S03.8's `apply_by`-inspection fix; check CPW's `apply_by` cell format for OTC discriminator
7. **Window parser** — handles CPW date formats (DEA-style "Aug. 15-Nov. 08" or different convention)
8. **verbatim_rule fallback chain** — per-row text → per-section text → null (S03.7 OQ-S7-9 pattern)
9. **draw_spec_key=None on every row at S06.7** — S06.8 backfills per ADR-012
10. **purchase_url evergreen** vs per-row — CO convention TBD at extraction; the artifact-level URL is likely correct
11. **Bear → NULL quota_range** vs DEA-style int range — per CPW's bear publication

**Output artifact-shape question:** the S03.7 license_tag fan-out for cross-listed B-licenses (S03.8 amendment) is a likely CO trigger — surface every CO cross-listing during build; if CO has cross-listed structural conflicts mirroring MT HD 210, the `_KNOWN_CROSS_LISTING_OVERRIDES` workaround applies (PRD 002 R3 Q17 trigger).

**Asymmetric license-coverage demonstrator** (PRD 002 success criterion #2): find a CO equivalent of MT HD 170 elk where two licenses covering the same GMU+species have different weapon-type / season-window coverage sets. Lock in test as `test_license_season_asymmetric_coverage_m2_criterion` (mirrors S03.7 M1 lock). If CO doesn't have asymmetric A/B-license-equivalents, document the deviation and PM flags-and-discusses with human.

**Deliverables:**

- `ingestion/states/colorado/load_seasons_and_licenses.py` (new, structural analog of MT's ~1180 LOC; CO loader expected at 800-1200 LOC depending on cross-listing complexity)
- Five entity/link DB write counts surfaced in run summary (e.g., MT shipped 8542 rows total); CO band documented in closure note
- 80-120 tests in `ingestion/tests/test_load_co_seasons_and_licenses.py`
- (Conditional) `db.upsert_season_definition` / `db.upsert_license_tag` / `db.write_license_season` / `db.write_regulation_season` / `db.write_regulation_license` helpers if extension needed; reuse M1's pattern as-is if CO doesn't surface a new shape

**Relevant ADRs:** [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../adrs/ADR-010-decomposed-entity-model.md), [ADR-012](../adrs/ADR-012-draw-mechanics-sibling-entity.md), [ADR-017](../adrs/ADR-017-confidence-calibration.md), [ADR-018](../adrs/ADR-018-e03-schema-additions.md), [ADR-020](../adrs/ADR-020-id-text-pk-slug-derivation.md).

**Depends on:** S06.6 (regulation_record exists; FK target).

**Unblocks:** S06.8 (license_tag exists for draw_spec_key backfill), S06.10 (link tables seen by binding loader for the cross-product picture).

**Acceptance Criteria:**

- [x] `ingestion/states/colorado/load_seasons_and_licenses.py` exists, state-agnostic-clean, three-phase shape
- [x] **ADR-020 `assert_id_matches`** invoked **in every per-row entity-construction site** inside the `season_definition` and `license_tag` build functions (4 call sites: `_build_big_game_season_definitions` / `_build_big_game_license_tags` / `_build_bear_season_definitions` / `_build_bear_license_tags`). Each re-derives via the pure module-level `_co_season_definition_id` / `_co_license_tag_id`. `TestDriftGuardCallSites` enumerates every `_build_*_season_definitions`/`_build_*_license_tags` function and asserts each is instrumented — a new uninstrumented build function fails it. **MET**
- [x] Link-table builders NOT instrumented (`assert_id_matches`/`drift_guard` not referenced in `_build_license_seasons` / `_build_regulation_seasons` / `_build_regulation_licenses` / `_iter_co_entity_rows`; `TestLinkTableNotInstrumented` AST guard green). **MET**
- [x] 5 row-count fail-loud guards fire pre-`db.connect()` (one per entity/link table); bands documented (above + closure memo). **MET**
- [x] All UPSERTs atomic in one transaction (`with db.connect()` + single `conn.commit()`, FK-safe entity-before-link order — `TestMain` asserts ordering + single commit); CO `license_tag.draw_spec_key = None` on every row (S06.8 backfills per ADR-012; locked by test). **MET** (live execution Group-B-operator-pending; transaction contract verified via dry-run + mocked-write test)
- [x] **Asymmetric coverage demonstrator** locked by `test_license_season_asymmetric_coverage_m2_criterion` on GMU 001 mule_deer (real artifact). **MET**
- [x] **License-tag species fan-out** (Q16 trigger): CO artifact pre-separates `mule_deer`/`whitetail`/`elk`/`pronghorn` — no `deer` label; **Q16 does NOT fire**; no CO-specific fan-out branch added; verified by a no-accidental-fan-out test. **MET (Q16 N/A — documented)**
- [x] License-tag kind heuristic — **deviation documented**: CO `apply_by` is null on every row, so the OTC discriminator is NOT `apply_by`-based. Big-game kind derives from `list_value` (A→limited_draw / B→over_the_counter / C→limited_draw); bear kind from the section-level `license_kind` field. Both are ordered-branch heuristics with a fail-loud `else`. The spec's "inspect `apply_by`" is N/A for CO. **MET (adapted)**
- [x] **Closure-predicate `effective_after` trigger:** documented — no bear closures in CO V1; zero "after [date]" closure prose; the trigger does NOT fire; no `closure_predicate` rows written; no STOP needed. **MET (does not fire — documented)**
- [x] **Cross-listing structural agreement** — **Q17 does NOT fire** at the season/license layer (repeated hunt_codes are legitimate multi-GMU listings; regulation_record keys by `(gmu, species)` not hunt_code; no `_KNOWN_CROSS_LISTING_OVERRIDES`-equivalent needed). Any draw-side cross-listing conflict is S06.8 territory. **MET (Q17 N/A here — documented)**
- [x] Test baseline grows additively; **111 tests** in `test_load_co_seasons_and_licenses.py` (suite 1787 → 1907 + 4 skipped). **MET**

---

### S06.8.0: CPW draw-instructions front-matter extraction (pp. 8–32) — mid-epic carve-out, prerequisite for S06.8

**Status:** Closed at-merge 2026-06-26 — squash-merged to main as **PR #77 / `68e0c04`** from `feat/S06.8.0-draw-mechanics-extraction` (**eleventh E06 PR**; mid-epic carve-out resolving the Phase-A "no draw-mechanics data in per-unit artifacts" gap surfaced at S06.8 build Stage-2 discovery; mirrors S06.3.1 / S06.6.1 / S06.6.2 mid-epic carve-out precedent). **Phase A outcome (a) confirmed**: hybrid eligibility table extractable from the brochure's draw-instructions front matter (pp. 28–29), deadlines from p. 14, per-species point-only codes per the species-section anchors. New `ingestion/states/colorado/extract_draw_mechanics.py` (~1,102 LOC, state-agnostic-clean per AST guard, single-module per ADR-022, ADR-008 verbatim discipline — no `layout=True`) emits the deterministic committed artifact `extracted/draw-mechanics-2026.json` via `lib/pdf.write_extraction_artifact` (one-record-per-line per the S06.3 convention). **Artifact**: 123 records / **SHA-256 `7fd162adaf1ef791cd3be8a99296cee6bf6b7cce34deeb36e2bdec2a03c15b16`** <!-- pragma: allowlist secret --> determinism-pinned in `test_extract_co_draw_mechanics.py` (961 LOC, 50 new tests). Composition: 116 `hybrid_code` records (the per-species hybrid hunt-code list from pp. 28–29) + 4 `point_only_code` records (one per species) + 1 `important_dates` record (primary April 7 / secondary June 30 / leftover Aug 4 2026) + 1 `nr_allocation` record (residency-cap coupling: hybrid → 0.20, non-hybrid → 0.25) + 1 `hybrid_mechanics` record (`_HYBRID_RANDOM_POOL_MIN_POINTS=5` + `_HYBRID_PREFERENCE_POOL_SHARE=0.80` + `_HYBRID_RANDOM_POOL_SHARE=0.20` + `_HYBRID_ELIGIBILITY_POINT_LINE=6` administrative parameters). **Test baseline shifted 1907 → 1957 + 5 skipped** (+50 additive; new 1957 baseline holds going into S06.8). ruff + mypy + cubic clean; detect-secrets passed. **No `ingestion/lib/` edits beyond consuming existing `write_extraction_artifact`; no schema/migration/three-place-sync; no `db.py` touches; no MT-file touches; no TS-stack diffs; no production-DB writes from the build session.** **3 new pitfalls in `.roughly/known-pitfalls.md`** (file now ~1,389 LOC; doc-writer re-flagged for reorg/dedup — recurring since S05.x). **Cubic review iteration during build** caught two correctness-of-strictness items in the dedup/lookup path and tightened both to fail-loud on conflicting code occurrences + raise `ColoradoDrawMechanicsError` on missing point-only-code matches (schema-permitted null is expressed by NOT listing a species in the enumerated set, not by a soft miss); artifact SHA unchanged through both fixes (no-ops on real data). **⚠️ Merge-bundle caveat**: the merged branch also carried unrelated permissions-config work (`docs/claude-code-permissions.md`, `.claude/settings.json` blocks, `.gitignore` rule, removal of an incomplete settings backup) and a small chore commit; these are **NOT** S06.8.0 scope and should not be attributed to the story when re-reading the merge. The 3 stale-M3-references cherry-pick (`4332b9c`) that landed on main earlier in the day is also present in this PR's first commit; that's a re-application from the M3 prompt-fix sweep, not S06.8.0 work either. **Q12 / Q17 remain Open** — they will surface at S06.8 (which now consumes this artifact). **Phase C revisions to S06.8** (next active work-front): S06.8's ACs #908 hybrid pools / #910 coupling / #913 deadline-count / #907 `purchase_only_code` now consume `draw-mechanics-2026.json` (no more faithful-V1 fallback). **UAT spot-check (AC #905) is PM-pending** — faithfulness of the extracted hybrid set + point-only codes + deadlines against brochure pp. 14/29/30/45/63/72; runbook in `docs/planning/epics/E06-confidence-findings/S06.8.0.md` (~84 LOC; deletes at m2 tag per ADR-017 §6). **No ADRs created** — refines ADR-001 (fail-loud), ADR-005 (state-agnostic-clean), ADR-008 (verbatim discipline), ADR-022 (single-module per-state extractor).

**Carve-out provenance:** Surfaced 2026-06-24 at S06.8 build Stage-2 discovery + an independent Phase-A brochure probe. The committed CO extraction artifacts (`big-game-2026.json`, `black-bear-2026.json`) carry the per-unit hunt tables (brochure pp. 33–71) but **zero draw-mechanics data**: `apply_by`, `quota`, `quota_range` are null on all 2,762 big-game rows; there is no `draw_phase`, `successor_hunt_code`, hybrid-eligibility flag, or residency-cap field on any row. S06.8's premise (80/20 hybrid pools, 20%/25% residency caps, successor chains, application deadlines) is written against data the per-unit extractor never captured — it lives in the brochure's draw-instructions front matter (pp. 8–32). Per the user decision 2026-06-24 ("carve out re-extraction first") + the project's mid-epic carve-out precedent (S06.3.1 / S06.6.1 / S06.6.2), this story extracts that front matter into a committed reference artifact **before** S06.8 builds. Mirrors the S06.3 / S06.4 extraction-story shape (deterministic committed JSON + SHA pin), structurally a sibling of those extractors rather than a fix to S06.7.

**As a** developer modeling CPW's preference-point hybrid draw mechanics
**I want** the brochure's draw-instructions front matter (hybrid hunt-code set, per-species point-only codes, draw deadlines, residency-cap coupling) extracted into a committed `draw-mechanics-2026.json` reference artifact
**So that** S06.8 joins it against the per-unit hunt codes to build faithful `draw_spec` rows instead of inventing hybrid/residency/deadline data

**UAT: yes** — PM-run faithfulness spot-check of the extracted hybrid hunt-code set + point-only codes + deadlines against the source brochure pages.

**Phase A — probe gate (COMPLETE; outcome (a) confirmed):** Phase A read the brochure and characterized what CPW publishes in machine-extractable form. Findings (working note to capture the page-by-page detail):

- **Hybrid eligibility = explicit per-hunt-code table (p. 29 "Hybrid Draw Hunt Codes"):** CPW lists the hybrid-draw hunt codes for Bear / Deer / Elk / Pronghorn by name (`*B-E-851-O1-R`, `D-M-002-O2-R`, `D-M-142-L1-R`, …). The `*`-prefix legend + full per-species lists span pp. 28–29 (possibly 30). Qualification rule: "minimum of five preference points" → confirms `_HYBRID_RANDOM_POOL_MIN_POINTS = 5`. The table is real but multi-column and graphics-overlapped — pdfplumber raw `extract_text` interleaves columns (same class of challenge as S06.3); table-aware extraction (`find_tables` / bbox crops) is required.
- **Deadlines (p. 14):** Primary draw **April 7** (8 p.m. MT), Secondary draw **June 30** (8 p.m. MT), Leftover/reissued OTC **Aug. 4**. Primary species: deer/elk/pronghorn/moose/bear; Secondary: deer/elk/pronghorn/bear. "The secondary draw has replaced the leftover draw of previous years."
- **Point-only / preference-point codes (pp. 13, 19 + per species-section headers):** "specific preference-point hunt codes are listed at the beginning of each species section." The per-species `P-999`-style point-only codes are published (pp. 30/45/63/68/72 carry `P-999` hits). Preference points apply to the **primary draw only**, not secondary (p. 19).
- **Residency 20% / 25% (p. 14 "Nonresident License Allocations" + coupling):** the 20%-vs-25% nonresident cap couples to the rolling-three-year ≥6-point determination (research §1); the **same upstream determination drives both the hybrid 80/20 pool split and the 20% cap** (hybrid set → 0.20; everything else → 0.25). The hybrid-participate floor (5 points) and the residency-coupling line (6 rolling points) are deliberately distinct constants per the S06.8 spec.
- **Weighted preference (`linear_weighted_random`) = moose/sheep/goat only (p. 19)** — all out of PRD 002 V1 scope; CO V1 ships zero weighted rows. No extraction needed.

**Phase A outcome: (a) extractable.** The data exists in published per-hunt-code / per-species form; a real extractor is justified (not the degraded faithful-V1 fallback). Phase A's evidence-first read replaces the spec's prior research-note assumptions.

**Phase B — build the extractor:**

- New `ingestion/states/colorado/extract_draw_mechanics.py` (state-agnostic-clean per AST guard; ADR-008 verbatim discipline — no `layout=True`; cleanup-rules docstring grep-parity; single-module per ADR-022) reads the committed brochure PDF (`fixtures/co-cpw-big-game-2026-brochure-2026-03-04.pdf`) and emits a deterministic committed artifact via `lib/pdf.write_extraction_artifact` (one-record-per-line per the S06.3 convention).
- **Artifact `extracted/draw-mechanics-2026.json`** shape (final field set locked at plan time against the live pages): the **hybrid hunt-code set** (list of hunt codes, per species, that use the 80/20 hybrid pools + 20% residency cap); the **per-species point-only / preference-point codes**; the **deadline set** (primary / secondary / leftover dates); the **residency-cap coupling** (hybrid → 0.20, non-hybrid → 0.25) as published; SHA-256 determinism-pinned in tests.
- Fail-loud guards: hybrid-table anchor missing → raise; species-section point-only-code anchor missing → raise (do NOT silently emit an empty set); count-band guard on the extracted hybrid hunt-code count.
- **Flag-and-discuss any datum that doesn't fit the published shape** (e.g., a per-hunt-code residency value contradicting the hybrid coupling → Q17 / multi-source-provenance candidate; a hybrid code that doesn't appear in the per-unit tables → STOP and surface).

**Phase C — revise S06.8 to consume the artifact:** after S06.8.0 merges, S06.8's ACs (#908 hybrid pools, #910 coupling, #913 deadline-count, #907 `purchase_only_code`) are revised to read the `draw-mechanics-2026.json` reference set: hunt codes in the hybrid set get `pools=[{0.80 rank_ordered_by_points},{0.20 unweighted_random, min_points:5}]` + `residency_cap={nonresident_max_share:0.20}`; all other limited-draw codes get `pools=[{1.0 rank_ordered_by_points}]` + `{nonresident_max_share:0.25}`; `application_deadline` from the extracted deadline set per `draw_phase`; `purchase_only_code` per species from the extracted point-only codes. S06.8's faithful-V1 fallback is no longer needed — the data is real.

**Deliverables:**

- `ingestion/states/colorado/extract_draw_mechanics.py` (new; expected 400–900 LOC depending on the p.28–29 table complexity)
- `ingestion/states/colorado/extracted/draw-mechanics-2026.json` (new committed artifact + SHA pin)
- `ingestion/tests/test_extract_co_draw_mechanics.py` (new; 30–60 tests incl. determinism SHA lock + hybrid-set count lock + per-species point-only-code presence)
- `docs/planning/epics/E06-confidence-findings/S06.8.0.md` working note with the Phase A page-by-page findings table (deletes at `m2` tag per ADR-017 §6)

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md) (no invented data — extract what CPW publishes; fail loud on missing anchors), [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) (state-agnostic-clean; no `lib/` edits beyond the existing `write_extraction_artifact`), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md) (no `layout=True`; verbatim cleanup-rules grep-parity), [ADR-022](../adrs/ADR-022-single-module-per-state-extractors.md) (single-module per-state extractor).

**Depends on:** S06.0 (brochure URL/SHA pinned + PDF on disk), S06.1 (PDF-fetch infra). The brochure PDF is already committed-locally (`fixtures/co-cpw-big-game-2026-brochure-2026-03-04.pdf`, SHA `38cf26e1…3582b3`); no operator fetch needed.

**Unblocks:** S06.8 (`draw_spec` ingestion consumes `draw-mechanics-2026.json`).

**Acceptance Criteria:**

- [x] `ingestion/states/colorado/extract_draw_mechanics.py` exists, state-agnostic-clean (AST guard), single-module (ADR-022), ADR-008-faithful (no `layout=True`; cleanup-rules docstring grep-parity; AST guard locks no `layout=True`)
- [x] Emits `extracted/draw-mechanics-2026.json` via `lib/pdf.write_extraction_artifact` (one-record-per-line); deterministic — two consecutive runs produce byte-identical output; SHA-256 pinned in the test file
- [x] **Hybrid hunt-code set extracted** from the p.28–29 "Hybrid Draw Hunt Codes" table for each of Bear / Deer / Elk / Pronghorn; count-band guard on the total; locked by a real-artifact count test. Every extracted hybrid hunt code is verified to be a syntactically valid CPW hunt code (`_HUNT_CODE_GRAMMAR` analog)
- [x] **Per-species point-only / preference-point codes extracted** (or explicitly recorded as absent for a species CPW does not publish one for — do NOT invent a code; null is permitted per `PointSystem.purchase_only_code: str | None`)
- [x] **Deadline set extracted** (primary April 7 / secondary June 30 / leftover Aug 4 2026) as structured dates; the dates are read from the brochure, not hard-coded blind (a constant cross-checked against the extracted value is acceptable, with the extracted value authoritative)
- [x] **Residency-cap coupling recorded** (hybrid → 0.20, non-hybrid → 0.25) per the published rule; any per-hunt-code published value contradicting the coupling routes to flag-and-discuss (Q17 / multi-source-provenance candidate) before adoption — **silent adoption is a process violation**
- [x] Fail-loud on missing hybrid-table anchor or missing species point-only-code anchor (no silent empty-set emit)
- [x] Zero `linear_weighted_random` / weighted-preference extraction (moose/sheep/goat are out of V1 scope; documented)
- [x] `docs/planning/epics/E06-confidence-findings/S06.8.0.md` working note exists with the Phase A page-by-page findings
- [x] No `ingestion/lib/` edits beyond consuming existing helpers; no schema/migration/three-place-sync; no `db.py` touches; no MT-file touches; no TS-stack diffs; no production-DB writes (extraction-only, dry-run-decoupled)
- [x] Test baseline grows additively; 30+ tests in `test_extract_co_draw_mechanics.py` (50 new tests; baseline 1907 → 1957 + 5 skipped)
- [ ] **UAT:** PM-run faithfulness spot-check of the extracted hybrid set + point-only codes + deadlines against the source brochure pages (PM-pending; non-blocking for S06.8 dispatch — S06.8 consumes the structured artifact, faithfulness review is the closure step)

**Sequencing:** lands **before S06.8**. Merge order updates to: `… → S06.7 ✓ → S06.8.0 (NEW; next active) → S06.8 → S06.9 → S06.10 → S06.11`. E06 estimated stories 15 → 16. After S06.8.0 closes, S06.8's ACs are revised (Phase C) to consume the artifact; S06.8's earlier faithful-V1 fallback framing is retired (the data is extractable).

---

### S06.8: `draw_spec` ingestion (CPW preference-point hybrid — Q12/Q17 trigger surface)

**Status:** Blocked on S06.8.0 (carved out 2026-06-24 — the CO artifacts carry no draw-mechanics data; S06.8.0 extracts the brochure front matter into `draw-mechanics-2026.json` first). Once S06.8.0 merges, the ACs below are revised (Phase C) to consume that artifact: hunt codes in the extracted hybrid set get the 80/20 pools + `nonresident_max_share=0.20`, all other limited-draw codes get the single 1.0 pool + `0.25`; `application_deadline` + `purchase_only_code` come from the extracted deadline / point-only-code sets.

**As a** developer modeling CPW's preference-point hybrid draw mechanics
**I want** every applicable CO hunt code's `draw_spec` row written with `point_system.kind='preference_linear'`, 80/20 split allocation pools (`rank_ordered_by_points` + `unweighted_random`), `residency_cap.nonresident_max_share` populated where CPW publishes it, three-stage draw chained via `successor_hunt_code`
**So that** PRD 002 success criterion #3 verifies, the multi-state schema claim is defensible on the CO axis, and any Q12/Q17 trigger surfaces as flag-and-discuss

**UAT: yes** — draw-mechanics faithfulness review against the CPW Big Game brochure for ≥5 representative hunt codes (rank-ordered preference-point, hybrid 80/20, leftover-phase chain, residency-cap hunt, weighted-points moose/sheep/goat if any). PM-run UAT spot-check on hunt-code structure + brochure cross-reference.

**Context:**

CPW's draw is the M2 stress-test for the multi-state schema claim. The committed schema accommodates the mechanics per [`docs/research/colorado-draw-schema-proposal.md`](../../research/colorado-draw-schema-proposal.md). CO ships:

- `point_system.kind="preference_linear"` with `accrual="annual_on_apply"`, `reset_on_success=true`, **`inactive_forfeit_years=null` on every row** (CPW does not forfeit points on inactivity per proposal §1 and §3 contrast with WY; explicit `null`, not omitted), `purchase_only_code` set per species to the CPW point-only hunt-code STRING (NOT a composite key — `PointSystem.purchase_only_code: string | null` per `architecture.md` `PointSystem` definition): elk=`E-P-999-99-P`, deer=`D-P-999-99-P`, pronghorn=`A-P-999-99-P` if CPW publishes (HEAD-verify at S06.3 brochure read; flag-and-discuss if pronghorn species code is not `A`), bear=`B-P-999-99-P` if CPW publishes a point-only bear code (some CPW species have no point-only code — leave `null`, do NOT invent a code; the schema explicitly permits null)
- `pools[0]: {share: 0.80, selection: "rank_ordered_by_points", tie_break: "random"}` (no `eligibility.min_points`) + `pools[1]: {share: 0.20, selection: "unweighted_random", eligibility: {min_points: 5}}` for hybrid-eligible hunt codes
- Non-hybrid hunt codes: single `pools[0]: {share: 1.0, selection: "rank_ordered_by_points", tie_break: "random"}`
- **`residency_cap: {nonresident_max_share: 0.20}` when the hunt code is hybrid-eligible (rolling-three-year ≥6 points), `{nonresident_max_share: 0.25}` when not** (per `colorado-draw-schema-proposal.md` §1: "up to 20% if the three-year rolling point requirement is six or more, or up to 25% if it is fewer than six"). **The same upstream brochure-side determination drives BOTH the 80/20 vs 100/0 pool split AND the 20% vs 25% residency cap; if CPW publishes a per-hunt-code value that contradicts this coupling, flag-and-discuss as Q17/multi-source-provenance candidate before adopting**
- `choices: {count: 4, points_used_in_choices: [1]}` — CPW's 4-choice convention; `points_used_in_choices: [1]` means "choice number 1 uses points" (1-indexed choice number, NOT a count of points); only the 1st choice consumes a preference point on draw; choices 2-4 are random draws against remaining licenses
- `draw_phase ∈ {primary, secondary, leftover}` chained via `successor_hunt_code_key: {state: "US-CO", hunt_code: <leftover-code>, year: 2026}` (**composite-key object** per `architecture.md` `DrawSpec` definition, NOT a bare string; the research-doc §6 uses an older bare-string `successor_hunt_code?: string` form that is stale relative to the committed schema)
- `application_deadline` populated on `draw_spec` (not `tag_info`/`license_tag`) per `architecture.md` `DrawSpec` definition and `colorado-draw-schema-proposal.md` §9 deprecation recommendation
- `parameters=null` on every row — PM expects zero Q12 triggers; every CPW quirk surfaces as a flag-and-discuss event

**Hybrid eligibility determination is UPSTREAM of the schema:** the rolling-three-year ≥6-point gate is an upstream brochure-side determination — it decides *whether* the 80/20 split applies to a given hunt code at all; the schema only encodes the resulting pools (per the proposal §"Out of scope for schema"). The implementer must NOT shoehorn this into `eligibility.min_points` — that field is for the within-hybrid 20%-pool gate, not the hybrid-vs-non-hybrid decision. **Flag if CPW publishes an eligibility shape that doesn't fit this dichotomy.**

**Named module-level Final constants (recalibration discipline):** The `min_points=5` 20%-pool floor and the `0.80/0.20` split are CPW administrative parameters per proposal §1 — named module-level constants in `load_draw_specs.py` (e.g., `_HYBRID_RANDOM_POOL_MIN_POINTS: Final[int] = 5`; `_HYBRID_PREFERENCE_POOL_SHARE: Final[float] = 0.80`; `_HYBRID_RANDOM_POOL_SHARE: Final[float] = 0.20`; `_HYBRID_ELIGIBILITY_POINT_LINE: Final[int] = 6`), NOT inlined per row. If the 2026 brochure publishes a different floor or split, flag-and-discuss before changing the constant (the 2028 50/50 reform is a known coming change per proposal §8 #1).

**V1 species scope:** V1 species (elk, mule_deer, whitetail, pronghorn, bear) do NOT include moose / sheep / goat — these species are explicitly out of PRD 002 V1 scope. CO ships zero `linear_weighted_random` `draw_spec` rows in E06. If a future story extends scope, the proposal §8 formula `random_number / (weighted_points + 1)` is the canonical CPW implementation; flag-and-discuss for a V2 ADR.

**Leftover-phase rows — `choices` shape:** CPW's leftover phase is first-come-first-served, weekly; there is no application-with-4-choices. The `choices` field on leftover-phase `draw_spec` rows: **TBD at first encounter; flag-and-discuss if CPW's leftover phase doesn't fit the `{count, points_used_in_choices}` shape** (likely `count=0` or `null`; PM does not pre-decide).

**Q12 / Q17 surface area:**

- **Q12 `parameters` use** — every CO `draw_spec` row ships `parameters=null`. If a row genuinely needs `parameters` (e.g., a CPW point system shape outside the 3 enum values OR an eligibility shape the schema doesn't carry), the implementer **must flag the candidate to the human before adopting `parameters`** per the 4-step protocol. PRD 002 R2: every candidate is flag-and-discuss; the PM consolidates and either drafts an ADR amendment or accepts `parameters` use per the human's call.
- **Q17 per-GMU allocation caps** — if CPW publishes per-GMU allocation caps that don't fit the `pools[].share` (numeric share sums to 1.0) shape (e.g., absolute count cap per GMU within a multi-GMU hunt code), the `_KNOWN_CROSS_LISTING_OVERRIDES`-equivalent workaround from S03.8 applies V1; PM flags as Q17 trigger.

**S03.8 amendments carry forward:** the OTC discriminator via `apply_by` inspection (S03.8 fix at `_DEA_LICENSE_KIND_HEURISTIC`); the cross-listing consistency validator pattern; the defensive safety-net lookup pattern; the override-dispatch table pattern.

**CPW special cases to surface explicitly** (per the draw-schema research):

- **Moose / sheep / goat exponential weighting** — `linear_weighted_random` selection variant (the proposal §8 #5 flag); record explicitly at first CO ingestion sprint per the proposal note
- **2028 50/50 reform** — value change only, no schema change (proposal §8 #1); not a V1 concern but note in closure note

**Deliverables:**

- `ingestion/states/colorado/load_draw_specs.py` (new, structural analog of MT's; expected 600-900 LOC depending on CPW complexity)
- `draw_spec` rows for every applicable CO hunt code (band documented in closure note; expected hundreds)
- `license_tag.draw_spec_key` backfilled for every limited-draw `license_tag` row (per ADR-012)
- 80-130 tests in `ingestion/tests/test_load_co_draw_specs.py`

**Relevant ADRs:** [ADR-010](../adrs/ADR-010-decomposed-entity-model.md), [ADR-012](../adrs/ADR-012-draw-mechanics-sibling-entity.md), [ADR-018](../adrs/ADR-018-e03-schema-additions.md), [ADR-020](../adrs/ADR-020-id-text-pk-slug-derivation.md) (drift_guard NOT applicable to `draw_spec` — composite-PK is `(state, hunt_code, year)` not id-text-PK; `db.upsert_draw_spec` uses native composite-PK ON CONFLICT, no drift risk).

**Depends on:** S06.7 (license_tag exists for `draw_spec_key` backfill).

**Unblocks:** S06.11 (M2 milestone UAT verifies draw_spec shape).

**Acceptance Criteria:**

- [ ] `ingestion/states/colorado/load_draw_specs.py` exists, state-agnostic-clean, three-phase shape
- [ ] Every CO `draw_spec` row has `point_system.kind="preference_linear"`, `accrual="annual_on_apply"`, `reset_on_success=true`, **`inactive_forfeit_years IS NULL`** (locked by SQL-count test — CPW does not forfeit on inactivity), `purchase_only_code` populated per species per the table above (or `null` for species CPW does not publish a point-only code for; verified against the CPW brochure's published point-only-code table)
- [ ] Hybrid hunt codes have `pools=[{share:0.80, selection:"rank_ordered_by_points", tie_break:"random"}, {share:0.20, selection:"unweighted_random", eligibility:{min_points:_HYBRID_RANDOM_POOL_MIN_POINTS}}]`; non-hybrid have `pools=[{share:1.0, selection:"rank_ordered_by_points", tie_break:"random"}]`; verified by per-row test against the module-level Final constants
- [ ] **`min_points`, pool shares, the hybrid-eligibility rolling-window point line, and the rolling-window length are named module-level `Final` constants** (`_HYBRID_RANDOM_POOL_MIN_POINTS = 5`; `_HYBRID_PREFERENCE_POOL_SHARE = 0.80`; `_HYBRID_RANDOM_POOL_SHARE = 0.20`; `_HYBRID_ELIGIBILITY_POINT_LINE = 6`); locked by test against the proposal §1 V1 values; recalibration in M3+ flows via the constant, not edits to per-row logic
- [ ] **Coupling lock (observed-at-extraction, not a-priori):** `residency_cap.nonresident_max_share` populated per CPW's per-hunt-code 20% / 25% determination. The proposal §1 coupling (`len(pools)==2 ⇒ 0.20`, `len(pools)==1 ⇒ 0.25`) is the **expected** shape; lock it **as observed against the 2026 brochure** by a test asserting `pools[0].selection=='rank_ordered_by_points' AND len(pools)==2 ⇒ residency_cap.nonresident_max_share==0.20` and `len(pools)==1 ⇒ ==0.25` over the rows the extractor actually produced. **Per the "don't trust research notes against the live PDF" principle (S06.3) and the L522 coupling note, any hunt code whose published residency cap contradicts the pool-count coupling is routed to flag-and-discuss (Q17 / multi-source-provenance candidate) BEFORE the row is adopted** — the test locks the coupling that survives extraction, it does not pre-commit the biconditional as an immutable invariant
- [ ] `choices={count:4, points_used_in_choices:[1]}` populated per CPW convention for primary-phase rows; leftover-phase rows TBD at first encounter (flag-and-discuss if shape diverges from `{count, points_used_in_choices}`)
- [ ] `draw_phase` set per CPW publication; **`successor_hunt_code_key` is the composite `{state, hunt_code, year}` object form (not bare string)**, chains primary → leftover for the 3-stage hunt codes; locked by test against the schema type
- [ ] **`application_deadline` populated on `draw_spec` (not `tag_info`/`license_tag`) per `architecture.md` and `colorado-draw-schema-proposal.md` §9**; verified by SQL `SELECT COUNT(*) FROM draw_spec WHERE application_deadline IS NOT NULL` matching the drawable hunt-code count; `license_tag.application_deadline` (if the field exists) is NULL for CO rows
- [ ] `parameters=null` on every row; if any row needs `parameters`, flag-and-discuss surfaced to PM + recorded in `draw-mechanics.md` per 4-step protocol
- [ ] **Q17 per-GMU allocation caps:** if CPW publishes per-GMU absolute caps within a multi-GMU hunt code (e.g., HD 210-style structural conflict per MT precedent), the implementer **STOPS**, files a flag-and-discuss event documenting the per-GMU shape + a candidate ADR-disposition (override-table V1 stopgap vs schema extension); PM surfaces to human BEFORE adopting `_KNOWN_CROSS_LISTING_OVERRIDES`-equivalent OR `parameters` use. The V1 stopgap is acceptable only with human approval; **silent adoption of either is a process violation**
- [ ] License-tag `draw_spec_key` backfilled for limited-draw rows (per ADR-012)
- [ ] OTC discriminator via `apply_by` inspection (S03.8 fix); cross-listing structural-agreement validator (S03.8 pattern)
- [ ] **`db.upsert_draw_spec` uses composite-PK `(state, hunt_code, year)` ON CONFLICT**; `drift_guard` is NOT imported by `load_draw_specs.py` (verified by AST guard test); the composite-PK is strictly stronger than slug-encoded drift protection per ADR-020 §"Decision"
- [ ] Row-count fail-loud guard ±30% band fires pre-`db.connect()`
- [ ] **UAT:** PM-run draw-mechanics faithfulness review against ≥5 representative CPW hunt codes (1 rank-ordered preference-point, 1 hybrid 80/20, 1 leftover-phase chain, 1 residency-cap split case, 1 point-only purchase code)
- [ ] Test baseline grows additively; 80+ tests in `test_load_co_draw_specs.py`

---

### S06.9: `reporting_obligation` ingestion (drift_guard.assert_dispatch_dict_drift_free mandatory; Q18 trigger surface)

**Status:** Not Started

**As a** developer writing CO's post-harvest / in-season reporting duties
**I want** every applicable CO `reporting_obligation` row written with verbatim text + region scope + dispatch-dict at module load instrumented per ADR-020 `assert_dispatch_dict_drift_free`, plus Q18 disposition (license-keyed per S06.0 decision) applied
**So that** S06.10 binding loader writes `regulation_reporting` links and PRD 002 success criteria pass

**UAT: yes** if CWD sampling rules surface; otherwise UAT: no (verification at SQL-count level)

**Context:**

Mirrors M1's S03.9 pattern. CO `reporting_obligation` rows come from the Big Game brochure (hunter reporting, harvest survey, mandatory check, CWD sampling, etc.).

**Q18 disposition** (resolved at S06.0): the PM recommendation was license-keyed option (c) — 0 typed `reporting_obligation` rows for CWD sampling; verbatim CWD text stays in `regulation_record.additional_rules` from S06.6. **If S06.0 confirmed option (c):** S06.9 ships zero CWD `reporting_obligation` rows for CO; non-CWD reporting obligations (mandatory check, harvest survey, etc.) ship normally. **If S06.0 selected (a) zone-keyed or (b) license-keyed-as-typed-rows:** the spec for S06.9 changes materially per the S06.0 decision memo.

**ADR-020 drift_guard mandate:** `assert_dispatch_dict_drift_free` called at module load on the CO `_REPORTING_ROW_SPEC` dispatch dict (mirrors S03.9 pattern). The carve-out for `db.upsert_reporting_obligation` is the table where `drift_guard` is specifically required per the helper-to-table mapping; `assert_dispatch_dict_drift_free` is the correct primitive (compile-time dispatch dict). The runtime `assert_id_matches` does NOT apply here.

**S03.9 lessons carry forward:**

- Per-(`region_scope`, `kind_hint`) dispatch dict
- Three-phase shape (build → guards pre-`db.connect()` → conn loop / commit)
- Source-audit upstream artifacts BEFORE planning; if CPW surfaces a reporting obligation type that doesn't fit the existing `kind` enum (`harvest_report | mandatory_check | tooth_submission | hide_skull_presentation | cwd_sample | other`), flag-and-discuss; do NOT silently widen the enum
- `reporting_obligation.kind` semantic boundary — post-harvest / in-season only; pre-purchase prerequisites (e.g., the bear-coursework analog) go in `regulation_record.additional_rules` via a STATEWIDE anchor (the S03.6.1 carve-out pattern)

**Deliverables:**

- `ingestion/states/colorado/load_reporting_obligations.py` (new, structural analog of MT's ~600 LOC; CO loader expected at 400-600 LOC depending on CPW publication structure)
- `reporting_obligation` rows for CO (band documented in closure note; expected 3-10 rows by analogy with MT's 3)
- `regulation_reporting` link rows (written by S06.10's binding loader; CO band documented in closure note)
- 40-60 tests in `ingestion/tests/test_load_co_reporting_obligations.py`

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../adrs/ADR-010-decomposed-entity-model.md), [ADR-017](../adrs/ADR-017-confidence-calibration.md), [ADR-020](../adrs/ADR-020-id-text-pk-slug-derivation.md).

**Depends on:** S06.6 (regulation_record exists), S06.0 (Q18 disposition decided).

**Unblocks:** S06.10 (binding loader writes `regulation_reporting` link rows from this), S06.11 (M2 UAT).

**Acceptance Criteria:**

- [ ] `ingestion/states/colorado/load_reporting_obligations.py` exists, state-agnostic-clean, three-phase shape
- [ ] **ADR-020 `assert_dispatch_dict_drift_free`** invoked **at module top-level** (after the CO `_REPORTING_ROW_SPEC` definition; before any function definitions), passing the dispatch dict + a pure id-derivation callable via a `lambda key, entry: _derive_*(...)` adapter + `helper_name=` **the dispatch-dict's variable name** (the name surfaced in the RuntimeError message — MT passes `helper_name="_REPORTING_ROW_SPEC"`, NOT the upsert-helper name) + **`id_field=`** the field the entries key their id under (MT passes `id_field="id_suffix"` because the entries key the id as `id_suffix`, not the default `"id"`; if the CO dict keys its id differently, pass that field name — **omitting `id_field` silently defaults to `"id"` and would mis-verify**). The pure derivation function is the CO analog of MT's `_derive_expected_id_suffix(kind, deadline_hours, region_scope)` (`load_reporting_obligations.py:295`), lives at module level, and takes the entry's slug-encoded structured fields (mirrors the call shape at `load_reporting_obligations.py:342-348`). Verified by test that imports the module and asserts the assertion fires before any function executes
- [ ] Per-row `kind` value uses existing 6-value enum (`harvest_report | mandatory_check | tooth_submission | hide_skull_presentation | cwd_sample | other`); if CPW surfaces a new `kind`, flag-and-discuss before adopting (do NOT silently widen). **Same silent-widening prohibition applies to `SourceCitation.document_type`**: any new doc-type encountered fails loud and requires ADR-019 amendment per §"Decision" item 5
- [ ] Q18 disposition applied per S06.0 decision: option (c) ships 0 typed CWD rows; (a) zone-keyed or (b) license-keyed-as-typed-rows ship per the new spec
- [ ] Row-count fail-loud guard ±30% band fires pre-`db.connect()`
- [ ] Source citation populated on every row; `document_type` per S06.0 doc-type decisions
- [ ] If CPW publishes a non-post-harvest/in-season reporting obligation (e.g., bear-coursework analog), it lands in `regulation_record.additional_rules` via STATEWIDE anchor at S06.6 (NOT `reporting_obligation`)
- [ ] **ADR-017 FINALIZE lock:** framework is unmodified per S03.11 FINALIZE verdict; `low`-tier rows in CO are data-shape signal, not framework signal. Any candidate framework change is a flag-and-discuss event surfaced to the human; PM does NOT draft an ADR-017 amendment autonomously
- [ ] **UAT (if CWD rules surface):** PM-run faithfulness review against CPW's CWD section + Q18 disposition verification
- [ ] Test baseline grows additively; 40+ tests in `test_load_co_reporting_obligations.py`

---

### S06.10: `jurisdiction_binding` generation (consumes S05.5 fixture + S05.6 scaffold; final E06 DB-write story)

**Status:** Not Started

**As a** developer generating CO `jurisdiction_binding` rows for the V1 cross-product
**I want** every applicable CO regulation_record × geometry binding row written across statewide + overlay + portion + no-hunt-zone-nearby builders, with cross-state spatial filter `_STATE='US-CO'` discipline, and the 10 federal no-hunt zones from S05.4 bound with `role='no_hunt_zone'`
**So that** PRD 002 success criterion #4 verifies, the FK-direction-corrected E06→E05 dependency closes, and Q18/Known-Issue-#6/`_STATE`-naming decisions are operationalized

**UAT: no** (verification at SQL-count level + the spatial-test-points spot-checks deferred to S06.11)

**Context:**

The last E06 DB-write story; mirrors M1's S03.10 cross-cutting binding loader pattern. Reads the S05.5 `geometry-overlays.json` × `regulation_record` cross product, applies per-species filtering, walks 4 binding sources (statewide / overlay self-row / overlay portions [CO has none] / no-hunt-zone nearby), and UPSERTs in one atomic three-phase transaction.

**🚩 AFA classification — HARD CONSTRAINT (Known Issue #12 RESOLVED, baked here 2026-06-23 post-M2-build operator pass)**: The Air Force Academy row (`CO-restricted-united-states-air-force-academy-geom`, one of the 10 S05.4 `kind='restricted_area'` rows) is **a regulated-access HUNTING area, NOT a no-hunt zone** (GMU 512 carries CPW hunt codes; CPW publishes escorted rifle deer hunts there per CPW Big Game brochure p.78). S06.5's `verbatim_rule` for that row describes *how to hunt there*, not a closure — **confirmed live via M2-build operator pass Step 8 on 2026-06-23** (env=dev / M2-build; the operator pass made the deferral concrete by populating the verbatim_rule and verifying it reads as hunting-access prose). **S06.10 binding loader MUST split the 10-zone no-hunt-zone code path: 9 NPS/NM rows → `role='no_hunt_zone'`; 1 AFA row → `role='other_overlay'`.** Doing otherwise (binding AFA as `no_hunt_zone`) would protect a huntable zone as closed in query results, contradicting CPW-published reality and the user's stated intent ("AFA must remain protected as a huntable zone in query results"). **The implementer MUST NOT** treat this as a recommendation or open question; it is a hard constraint baked into the spec and enforced by AC #1040 below. Option (b) (geometry-layer `kind` reclassification) was considered + deferred to V2 if hunting-permission-bearing federal lands become numerous; for V1, option (a) at the binding-loader layer is the locked path:

- **(a) Bind AFA `role='other_overlay'`** at the binding-loader layer — keeps the geometry row as-is (`kind='restricted_area'`; PAD-US source), but the binding semantics correctly express "restricted access, not closed." Mirrors MT's pre-ADR-021 `other_overlay` disposition.

The other 9 S05.4 rows (4 NPs + 5 NMs) are genuine no-hunt zones — `role='no_hunt_zone'` is correct for them (the S06.5 phrasing-case (1) NPS sentence is the verbatim closure rule). See Known Issue #12 below for full history.

**S05.6 scaffold pre-shipped for import:**

- `_STATE: Final[str] = "US-CO"` — direct import; cross-state spatial-filter constant
- `_NO_HUNT_ZONE_NEARBY_DISTANCE_M: Final[int] = 5000` — direct import; CO recalibration deferred until empirical data lands (the band may narrow after first run, analog of S04.2's T16 empirical narrowing for MT)
- `_QUERY_NEARBY_GMUS_FOR_ZONE_SQL: Final[str]` — direct import; boundary-to-boundary `extensions.ST_DWithin` SQL with `state + zone-geom + distance` all `%s`-bound + `ORDER BY gmu.id` for determinism
- `query_nearby_gmus_for_zone(conn, zone_geom_wkt) -> list[str]` — reference function; S06.10 calls it for each of the 10 S05.4 no-hunt zones to find the nearby GMUs

**ADR-021 + Known Issue #6:** the 10 S05.4 federal no-hunt zones bind with `role='no_hunt_zone'` per ADR-021 (the DDL CHECK permits the value). Known Issue #6 (the `_VALID_ROLE_FOR_E03` subset-gate decision) was resolved at S06.0:

- **If subset-gate widened** (S06.0 option A): CO no-hunt-zone bindings flow through the overlay-fixture path with `role_for_e03='no_hunt_zone'` in the fixture row; the CO loader's analogous `_VALID_ROLE_FOR_E03`-equivalent gate admits the value
- **If hardcoded path** (S06.0 option B; matches MT precedent): CO no-hunt-zone bindings are constructed by a separate hardcoded builder analog of MT's `_build_no_hunt_zone_bindings`; the gate stays narrow

**`_STATE` vs `CO_STATE_CODE` unification** (S06.0 decision): if `_STATE` wins, the rename ships in this story across the 4 existing CO loaders (S05.0/S05.2/S05.4/S05.5 + `build_overlay_fixture.py`); if `CO_STATE_CODE` wins, the S05.6 scaffold is renamed here.

**id format and binding-id discipline:**

- Use the `_JURISDICTION_BINDING_ID_FORMAT` constant from S06.6 (mirrors S03.10's import-and-share pattern from S03.6.1); deterministic + symmetric so re-runs UPSERT as no-ops
- Statewide bindings: `CO-STATEWIDE-{species}` regulation_record × `CO-STATEWIDE-geom` (the statewide anchors from S06.6)
- Overlay self-row bindings: every CO `regulation_record` × its `CO-GMU-{GMUID}-geom`
- No-hunt-zone bindings: each `regulation_record` × each of the 10 nearby zones discovered via `query_nearby_gmus_for_zone()`, with `role='no_hunt_zone'`

**S03.10's 18 fail-loud guards carry forward** (per the audit-stored convention); CO loader inherits the pattern with CO-specific id-derivation logic. 4 PR-review iteration rounds added 4 additional guards in S03.10; PM expects ≥18 guards in the CO loader.

**Source attribution from `geometry.source`** via adapter-local `SELECT id, source FROM geometry WHERE id = ANY(%s)` (S03.10's choice; no new `db.py` helper); Pydantic `ValidationError` wrapped to name the failing geometry id (S03.10 review-fix C2 pattern).

**Deliverables:**

- `ingestion/states/colorado/load_jurisdiction_bindings.py` (already exists as S05.6 scaffold; S06.10 extends with `main()`, `argparse`, `db.connect()`, the 4-builder cross-product, and the row-count guard band)
- `jurisdiction_binding` rows in 1 atomic transaction (band: empirically derived during build; spec band `[400, 1100]` from S03.10's MT carry-forward is the loose starting estimate)
- 60-100 tests in `ingestion/tests/test_load_co_jurisdiction_bindings.py` (extending the existing `test_co_binding_reference.py` scaffold from S05.6)

**Relevant ADRs:** [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-010](../adrs/ADR-010-decomposed-entity-model.md), [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md), [ADR-017](../adrs/ADR-017-confidence-calibration.md) (binding has no `confidence` column — spatial-confidence carve-out per ADR-017 §2), [ADR-018](../adrs/ADR-018-e03-schema-additions.md), [ADR-021](../adrs/ADR-021-jurisdiction-binding-no-hunt-zone-role.md).

**Depends on:** S06.6 (regulation_record exists), S06.7 (link tables — for the cross-product picture), S06.9 (reporting_obligation exists for regulation_reporting link writes), S05.5 `geometry-overlays.json` (operator-pending Group B; live `geometry-overlays.json` is hard precondition for live S06.10 run; dry-run S06.10 can use the operator-pending fixture once captured).

**Unblocks:** S06.11 (M2 milestone UAT).

**Acceptance Criteria:**

- [ ] `ingestion/states/colorado/load_jurisdiction_bindings.py` extends the S05.6 scaffold with `main()`, `argparse`, `db.connect()`, the 4-builder cross-product
- [ ] State-agnostic-clean per AST guard; no `ingestion/lib/` edits (S05.6's CO-leak guard test + S05.6 import contracts hold)
- [ ] Reads `geometry-overlays.json` × `regulation_record` cross product; applies per-species filtering (mirrors S03.10 spec)
- [ ] **4 builders shipped:** statewide / overlay self-row / overlay portions / no-hunt-zone nearby. The overlay-portions builder is **included as a code path** but the iteration yields zero rows because `geometry-overlays.json` contains zero `kind='portion'` entries for CO (S05.2 closure confirmed CO has no portion-equivalents). This guards against an implementer omitting the code path entirely (which would then break the moment CO ever surfaces portion-like geometries in M3+)
- [ ] **No-hunt-zone bindings split 9 + 1 per AFA hard constraint (Known Issue #12 RESOLVED)**: the 9 NPS/NM rows (4 NPs: Rocky Mountain, Mesa Verde, Great Sand Dunes, Black Canyon of the Gunnison; 5 NMs: Dinosaur, Colorado NM, Florissant Fossil Beds, Hovenweep, Yucca House) bind × their nearby GMUs with `role='no_hunt_zone'` per ADR-021. The **1 AFA row** (`CO-restricted-united-states-air-force-academy-geom`) binds × its nearby GMUs with `role='other_overlay'` (NOT `no_hunt_zone` — AFA is a regulated-access HUNTING area per the S06.5 forward-note and operator-pass Step 8 confirmation). The binding-loader's no-hunt-zone code path MUST iterate the 10 zones from `EXPECTED_CO_RA_ORPHAN_IDS` (S05.5) and dispatch on the AFA id specifically to apply the `other_overlay` role for that one row.
- [ ] **AFA-not-no-hunt-zone lock test** — pure-function unit test asserts `_build_no_hunt_zone_bindings()` (or equivalent) returns 0 rows with `role='no_hunt_zone'` AND `geometry_id == 'CO-restricted-united-states-air-force-academy-geom'`, AND ≥1 row with `role='other_overlay'` AND that same `geometry_id`. Mirrors the M1 pattern of locking critical role-assignment decisions in test code so a future refactor can't silently regress to the wrong role for AFA. Test name suggestion: `test_afa_bound_other_overlay_not_no_hunt_zone`.
- [ ] Known Issue #6 disposition applied per S06.0 decision (subset-gate widened OR hardcoded path); test asserts the decision is locked
- [ ] `_STATE` vs `CO_STATE_CODE` unification applied per S06.0 decision; verified by grep across all 5 CO loaders
- [ ] ≥18 fail-loud guards (S03.10 pattern; surface count in run summary)
- [ ] Cross-state spatial filter `state = 'US-CO'` baked into every SQL query (verified by regression test — analog of `test_co_binding_loader_sql_filters_by_state_co_pollution_guard` from S05.6, extended to cover the new SQL added by S06.10)
- [ ] **`_NO_HUNT_ZONE_NEARBY_DISTANCE_M` constant is `%s`-bound (not hardcoded) in every nearby-GMU SQL execution**; recalibration flows through the constant only (mirrors S05.6 Stage-6 Critical fix at `load_jurisdiction_bindings.py:_QUERY_NEARBY_GMUS_FOR_ZONE_SQL`). Verified by test asserting `cur.execute(sql, (..., _NO_HUNT_ZONE_NEARBY_DISTANCE_M, ...))` is the only invocation pattern
- [ ] PRD 002 success criterion #4 verifies in the spatial query verification step (deferred to S06.11; spot-check passes when `ST_Contains(geom, ST_GeogFromText('POINT(...)')) WHERE state = 'US-CO'` returns the expected GMU + overlays for known coord)
- [ ] `_JURISDICTION_BINDING_ID_FORMAT` imported from S06.6; symmetric derive-and-assert via S03.10's review-fix-applied UPSERT contract; re-runs UPSERT as no-ops
- [ ] Atomic three-phase transaction (build → guards → conn loop / commit); row-count guard band documented in closure note
- [ ] **ADR-020 carve-out preserved:** `drift_guard` is NOT imported by `load_jurisdiction_bindings.py`; `db.upsert_jurisdiction_binding` is NOT instrumented (schema-level exclusion of identity fields from the UPDATE clause is strictly stronger per ADR-020 §"Context"). Verified by an AST guard test asserting `drift_guard` does not appear in the module's import list (mirrors M1's regression-guard pattern in `test_drift_guard.py:TestNoStateAdapterImports`)
- [ ] Test baseline grows additively; 60+ tests in `test_load_co_jurisdiction_bindings.py`
- [ ] Live `supabase` row count verified post-load: `SELECT COUNT(*) FROM jurisdiction_binding WHERE regulation_record_state = 'US-CO'` matches build count exactly (operator-driven; Group B verification step)

---

### S06.11: M2 milestone UAT preparation + handoff to M3 (final E06 story)

**Status:** Not Started

**As a** developer preparing M2 for milestone-level UAT sign-off + `m2` tag push
**I want** the operator UAT runbook for the 10 PRD 002 success criteria + the M2-to-M3 handoff document drafted + the working-notes directory deleted per ADR-017 §6 + CLAUDE.md / planning README / CHANGELOG.md updated for M2 closure
**So that** the M3 PM session can pick up MCP server work without ambiguity

**UAT: yes** — milestone-level UAT runbook produced AND human-driven UAT sign-off captured

**Context:**

The final E06 story; mirrors M1's S03.12 pattern. Operator runs the 10 success-criteria SQL queries against the production project; PM consolidates results into the UAT capture analog of `M1-uat-results-2026-05-28.md`. M2 PM produces the M2-to-M3 handoff document at `docs/planning/handoffs/M2-to-M3-handoff.md` covering: what M2 built; final row counts (5 entities × 5 species × CO GMUs); ADRs accepted in M2 (ADR-021 + any Q12/Q16/Q17/Q18 ADRs); what M3 inherits; open-questions status at M2 close; deferred items.

**Deliverables:**

- `docs/runbooks/M2-uat.md` (new) — analog of `docs/runbooks/M1-uat.md`; 10 SQL query blocks per the 10 success criteria + operator batch-run sequence
- `docs/planning/handoffs/M2-to-M3-handoff.md` (new) — analog of `docs/planning/handoffs/M1-to-M2-handoff.md`
- `docs/planning/epics/E06-confidence-findings/` deleted per ADR-017 §6 + `.gitignore` updated
- (Conditional) `docs/planning/epics/E06-confidence-calibration-synthesis.md` if any framework-vs-data calibration synthesis surfaces (lives outside `E06-confidence-findings/`; survives `m2` tag per E03 synthesis precedent)
- CHANGELOG.md + planning README.md + CLAUDE.md updated to reflect M2 closure
- E06 epic file migrated to `docs/planning/epics/completed/` (matches E03/E04/E05 precedent)
- `m2` tag candidate identified for user push at the commit where UAT passes

**Relevant ADRs:** [ADR-017](../adrs/ADR-017-confidence-calibration.md) §6 (deletion policy).

**Depends on:** S06.10 (final E06 DB-write story complete), operator Group B verification across S05.0 + S05.2 + S05.3.5 + S05.4 + S05.5 + S05.7 (E05 hard precondition).

**Unblocks:** `m2` tag push, M3 (MCP server) planning.

**Acceptance Criteria:**

- [ ] `docs/runbooks/M2-uat.md` exists with the 10 PRD 002 success-criteria SQL query blocks; operator batch-run sequence (`supabase db push` → loaders → fixture build → verification queries) extracted from working notes before deletion
- [ ] `docs/planning/handoffs/M2-to-M3-handoff.md` exists; covers what M2 built + final row counts + ADRs accepted in M2 (ADR-021 + Q12/Q16/Q17/Q18 if any landed) + what M3 inherits + open-questions status at M2 close + deferred items
- [ ] Working-notes `docs/planning/epics/E06-confidence-findings/` deleted; `.gitignore` updated (M1 S03.12 pattern)
- [ ] If a framework-vs-data calibration synthesis surfaces: `docs/planning/epics/E06-confidence-calibration-synthesis.md` exists OUTSIDE the deletion target; survives `m2` tag
- [ ] CHANGELOG.md has an `E06 — Colorado Regulation Text Ingestion` section + `M2 — Colorado Ingestion` closing section
- [ ] Planning README.md reflects M2 Complete; CLAUDE.md preamble reflects M2 Complete; epic file migrated to `epics/completed/`
- [ ] **UAT:** operator runs the 10 SQL queries against the production project; PM captures verbatim outputs in `docs/runbooks/M2-uat-results-{date}.md` (analog of M1's pattern); all 10 success criteria PASS or are documented as PARTIAL with rationale
- [ ] `m2` tag candidate identified (PM does not push the tag; human-driven action)

---

## Exit Criteria

- [ ] All 12 E06 stories complete (S06.0 through S06.11)
- [ ] All 5 V1 CO species (elk, mule_deer, whitetail, pronghorn, bear) have `regulation_record` rows for every applicable CO GMU + statewide-anchor rows where the data requires
- [ ] Every `regulation_record` has populated `source` (jsonb SourceCitation) + `confidence` (ADR-017 enum)
- [ ] `season_definition`, `license_tag`, `license_season`, `regulation_season`, `regulation_license`, `draw_spec`, `reporting_obligation`, `regulation_reporting` rows present per the S06.7-S06.9 specs
- [ ] Asymmetric license-coverage demonstrator verified via `license_season` join (CO analog of M1 success criterion #2)
- [ ] `jurisdiction_binding` rows generated by S06.10 with cross-state spatial filter `state='US-CO'` (verified by PRD 002 success criterion #4)
- [ ] The 10 S05.4 federal no-hunt-zone bindings use `role='no_hunt_zone'` per ADR-021
- [ ] `verbatim_rule` populated on each of the 10 `kind='restricted_area'` geometry rows via S06.5
- [ ] ADR-020 `drift_guard.assert_id_matches` invoked in `season_definition` + `license_tag` build functions; `assert_dispatch_dict_drift_free` invoked at module load on the CO `_REPORTING_ROW_SPEC` dispatch dict; `db.upsert_jurisdiction_binding` carve-out preserved
- [ ] S06.6 through S06.10 closed under the Group-A-at-merge / Group-B-operator-pending split (see S06.6 Context): Group A (loader code + dry-run tests + quality gates) satisfied at merge; Group B (live `supabase` row-count / SQL-shape verification ACs) operator-pending and PM-ticked in follow-up doc-only commits — unticked Group B ACs are deferred-by-design, not incomplete work
- [ ] Test suite grows additively; M1 + E05 baseline at **1346 + 2 skipped** is the M2 floor; E06 grows to TBD but never subtracts
- [ ] All 10 PRD 002 success criteria pass UAT (S06.11 captures)
- [ ] ADRs documenting Q12 / Q16 / Q17 / Q18 / multi-source-provenance resolutions exist (or each is explicitly deferred to V2 with documentation)
- [ ] CHANGELOG, CLAUDE.md, planning README reflect M2 closure
- [ ] M2-to-M3 handoff document exists and is complete (`docs/planning/handoffs/M2-to-M3-handoff.md`)
- [ ] E06 confidence-findings directory deleted per ADR-017 §6
- [ ] `m2` tag pushed at the commit where milestone UAT passes (human-driven action; PM does not push)

---

## Parallelization Notes

**Within E06: stories run sequentially.** Per M2 PM prompt §"Parallelization Strategy", the human creates a feature branch per story and merges before the next begins. The PM does not recommend parallel work within E06.

**Recommended merge order:** S06.0 → S06.1 → S06.2 (conditional) → S06.3 → S06.4 (may fold into S06.3) → S06.5 → S06.6 → S06.7 → **S06.8.0 (carve-out)** → S06.8 → S06.9 → S06.10 → S06.11

**Dependency rationale (in order):**

- **S06.0 → S06.1**: hard precondition — S06.1 cannot start until S06.0 records the operator-resolved Big Game brochure URL + the 5 pre-registered decisions are captured
- **S06.0 → S06.5**: multi-source provenance decision required before S06.5 spec
- **S06.0 → S06.9**: Q18 disposition required before S06.9 spec
- **S06.0 → S06.10**: Known Issue #6 + `_STATE` naming decisions required before S06.10 spec
- **S06.1 → S06.2 → S06.3 → S06.4**: PDF fetch infra → primitives extension (conditional) → per-source extraction (parallelizable across S06.3 + S06.4 if Black Bear is separate brochure; but convention is sequential per the prompt)
- **S06.3 + S06.4 → S06.6**: regulation_record ingestion needs all extraction artifacts available
- **S06.6 → S06.7**: link-table ingestion FKs to regulation_record (FK-direction)
- **S06.7 → S06.8.0 → S06.8**: S06.8.0 extracts the brochure draw-instructions front matter (`draw-mechanics-2026.json`) the per-unit artifacts lack; S06.8 then builds draw_spec from it + backfills license_tag.draw_spec_key (per ADR-012)
- **S06.6 → S06.9**: reporting_obligation ingestion may FK to regulation_record per Q18 disposition
- **S06.5 → S06.10**: binding loader writes `role='no_hunt_zone'` against geometry rows with populated `verbatim_rule` (S06.5 ships first)
- **S06.6 + S06.7 + S06.9 + S05.5 fixture → S06.10**: binding loader consumes the regulation_record × geometry-overlays.json cross product + writes regulation_reporting links
- **S06.10 → S06.11**: M2 UAT cannot start until all DB-write stories close
- **E05 operator Group B → S06.6 onward**: the operator must run the E05 Group B batch (`supabase db push` → loaders → fixture build → spatial-test-points.json) before S06.6+ executes against live state. **S06.0 through S06.5 are dry-run-decoupled and can begin without Group B.**

**Cross-milestone parallelization:** M2 may begin in parallel with M3 (MCP server) per the roadmap, but M3 is a future-PM's concern. The M2 PM does not recommend or coordinate cross-milestone parallel work.

---

## Open Questions and Deferred Items

The following items are pre-registered at E06 plan time. Resolutions land either in S06.0 (the schema-prep gate decisions) OR mid-epic via the flag-and-discuss protocol.

### Pre-registered at S06.0 (require human decision before downstream story specs draft)

1. **Q18 license-keyed disposition** (final call) — PM recommendation: retain V1 license-keyed (option c). Resolved at S06.0.
2. **Known Issue #6 — `_VALID_ROLE_FOR_E03` subset-gate vs hardcoded path** for CO no-hunt zones. Resolved at S06.0.
3. **`_STATE` vs `CO_STATE_CODE` naming unification.** PM recommendation: `_STATE` wins (matches MT precedent). Resolved at S06.0.
4. **CPW Big Game brochure URL hard precondition** — operator must resolve before S06.1. Resolved at S06.0.
5. **Multi-source provenance for the 10 S05.4 federal no-hunt zones.** Resolved at S06.0.

### M2-resolution candidates per PRD 002 § "Open decisions resolved during M2"

- **Q12 `parameters` enforcement** — first CO `draw_spec` row to require `parameters` triggers ADR. PM expectation: zero triggers across E06; every candidate is flag-and-discuss per R2 mitigation.
- **Q16 species granularity** — **DOES NOT FIRE for CO V1** (resolved 2026-06-19 via S06.6 closure). CO artifacts pre-separate species at the section level (`mule_deer` / `whitetail` / `elk` / `pronghorn`; no `deer` label requiring fan-out); the no-accidental-fan-out test in S06.6 locks the separation. The Q16 trigger condition ("CPW separates mule_deer from whitetail at row level requiring artifact-level fan-out") was the wrong shape — CPW does not need fan-out because the artifact is already row-level separated. AC #544 was reframed at S06.6 close accordingly. Q16 remains an open question for any future state that might re-surface deer fan-out at extraction time.
- **Q17 per-GMU allocation caps in `draw_spec`** — if CPW publishes per-GMU caps that don't fit `pools[].share` (numeric share sums to 1.0) shape, trigger ADR-candidate. `_KNOWN_CROSS_LISTING_OVERRIDES`-equivalent workaround applies V1.
- **`role='no_hunt_zone'` enum addition** — RESOLVED via ADR-021 (S05.3.5); E06 inherits.
- **Multi-source geometry provenance** — third trigger candidate may surface at S06.5 if S06.0 chose option (c); resolves via ADR-candidate.
- **`effective_after: date | None` on `ClosurePredicate`** — closure-temporal-anchors.md ADR-candidate; trigger condition: any CO closure conditional on BOTH a quota threshold AND a calendar gate. S06.7 evaluates.
- **Q20 — Season Choice (method letter `X`) modeling — RESOLVED 2026-06-23** via user decision at S06.7 entry-time flag-and-discuss → **Option 1: Per-window fan-out**. Each X hunt code (6 `season_choice` sections in `big-game-2026.json`) materializes as **3 `season_definition` rows** (one per choosable method: archery / muzzleloader / rifle), each with its own `weapon_type` + own date window verbatim from the brochure; **1 `license_tag`** per X hunt code with `weapon_types=["archery", "muzzleloader", "any_legal_weapon"]` (the union); **3 `license_season` links** connecting the tag to all 3 seasons. Rationale: ADR-008 verbatim/faithfulness — preserves the 3 distinct windows as published; mirrors the existing M1 pattern for non-X multi-method licenses; ADR-013 alignment (server returns structure; client composes presentation). The "choose-one" semantic is handled cleanly without schema changes (`license_tag.weapon_types` = legal methods; `license_season` linking to multiple = "valid in any"; "one license = one harvest" is a license-issuance-layer rule). **F-sex 0-window edge case (skip-with-warning, NOT fail-loud)**: a few F-sex X rows carry 0 windows in the extracted artifact; still create the `license_tag` (preserves license-type existence in our data); 0 `license_season` links; WARNING logged with hunt_code + GMU + sex + list_value for PM grep + brochure-spot-check post-build. Mirrors the S06.6 GMU 020 elk archery blank-section precedent. **Options explicitly rejected**: Option 2 (single multi-weapon span with `weapon_type=None`) would collapse 3 distinct windows to 1, violating ADR-008 + mis-answering weapon-type-scoped hunter queries; Option 3 (skip X rows for V1) would drop real regulatory data extracted by S06.3, violating ADR-001 + creating a coverage gap. Full resolution rationale in `docs/open-questions.md` Q20 entry; S06.7 closure note will record the modeling decision durably + retire the Q20 entry on next post-S06.7 cleanup.

### Explicitly NOT resolved in M2 (per PRD 002 §"Explicitly NOT resolved in M2")

- Cell-level source attribution — V1 row-level only
- Free-prose non-NOTE HD-wide content — V1 simplification stands
- Q10 product name; Q13 public/license posture — not E06 scope

---

## Known Issues to Escalate

These items are surfaced to the human for decision; they do not block E06 story drafting at plan time but require resolution before downstream consumers fire.

1. **Operator Group B batched live-write session** — the hard precondition feeding S06.6 onward live execution. Six S05.X Group B verifications outstanding (S05.0 + S05.2 + S05.3.5 + S05.4 + S05.5 + S05.7). Sequence: `supabase db push` → `load_state_boundary` → `load_gmus` → `load_restricted_areas` → `build_overlay_fixture` → generate `spatial-test-points.json` → run the 7 verification steps from `docs/runbooks/E05-colorado-geometry-verification.md`. PM ticks Group B ACs in follow-up doc-only commits once operator captures results. **PM recommendation: sequence before/with E06 spec drafting** so E06 references the verified live state.

2. **`.roughly/known-pitfalls.md` reorg/dedup** — at ~1045 LOC; doc-writer flagged in 5 consecutive E05 stories (S05.3.5 → S05.4 → S05.5 → S05.6 → S05.7; recurring). Worth scheduling a dedicated documentation-hygiene session when the M2 hygiene sweep opens.

3. **Recurring-RLS-gap M2 open question** (E04 §"Known Issues to Escalate" #1) — if E06 ships any new `public.*` table (via Q18 / Q16 / Q17 / multi-source-provenance ADR resolutions), the migration must include inline deny-all RLS for `authenticated` + `anon` + RLS verification queries per the M1 UAT canonical pattern. The gap discipline persists.

4. **Known Issue #7 — narrow overlay-builder shared-lib extraction** (post-E05 tech-debt; from E05 epic). Standalone post-E06 hygiene-sweep PR. Touches merged + audited MT code so needs its own review.

5. **E05 research-doc accuracy item** at `docs/research/colorado-restricted-areas-evaluation.md:249` (the softer "same federal-authoritative chain" MT-contrast phrasing). PM does not edit `docs/research/` autonomously; surface to human at convenient point.

6. **Q12 / Q16 / Q17 / multi-source-provenance ADR drafting** — when any of these triggers fire mid-E06, the human (or an explicit ADR-drafting session) authors the ADR. PM does not draft ADRs autonomously; PM consolidates findings + flags + drafts open-question prose for human review.

7. **CPW Big Game brochure URL** — **RESOLVED 2026-06-08 via S06.0 decision #4** (operator-resolved, HEAD-verified live, cover-page-2026 confirmed). Pinned at the Colorado State Publications Library "Artemis" durable path `https://spl.cde.state.co.us/artemis/nrserials/nr1431internet/nr14312026internet.pdf` with `expected_sha256: 38cf26e1d0cdb930c38a9d18f04bbaced7c72a2573c86613c3ca5a9adb3582b3` <!-- pragma: allowlist secret --> (authoritative fail-loud drift gate per ADR-001; a different fetch hash = stop-and-investigate). HEAD baseline captured verbatim in S06.0 memo §D4: `Last-Modified: Wed, 04 Mar 2026 18:17:05 GMT`; `Content-Length: 96660296` (informational only — operator's byte count matches exactly); `Content-Type: application/pdf`. Cover line: "2026 Colorado Big Game — Deer/Elk/Pronghorn/Moose/Bear/Bison; Primary draw deadline April 7, Secondary June 30." **Large-download flag for S06.1**: brochure is ~96.7 MB / 84 pp / PDF v1.6 — `pdf_fetch.py` must expect a ~97 MB download; raise any timeout/size guard accordingly. Companion correction PDF located at `https://spl.cde.state.co.us/artemis/nrserials/nr1431internet/nr14312026corrinternet.pdf` ("Latest Update Feb 19 2026"); S06.1 enters under `pdfs:` as a HEAD-verified or `pending: true` entry until its SHA is captured (ADR-019 doc-type-precedence merge happens at S06.4 if it carries Black Bear content). S06.1 fully unblocked.

8. **MT-extractor migration to `write_extraction_artifact`** (surfaced 2026-06-13 via S06.3 cross-cutting infra change; post-E06 M2 hygiene candidate). S06.3 introduced the new state-agnostic `lib/pdf.write_extraction_artifact(records, path)` helper after cubic refused to review S06.3's PR at 108k changed lines (the `indent=2` artifact was 103,854 lines, past cubic's 50k cap). The helper is now mandatory for new extractors (S06.4 inherits). **MT's existing three extractors** (`extract_dea.py` / `extract_black_bear.py` / `extract_legal_descriptions.py`) still emit `indent=2` artifacts — **MT's `dea-2026.json` is 47,956 lines (one bigger brochure from the cap)**. Recommendation: migrate MT's three extractors to the helper at their next re-extraction (format-only, data-unchanged, re-pin SHA). **Not done in S06.3** — surfaced as a flag-and-discuss item; landing alongside the M2 hygiene-sweep PR (with E05 Known Issue #7 — narrow overlay-builder shared-lib extraction).

9. **Recurring-review pattern: "monolithic extractor module" P2 raised 3× against S06.3** (surfaced 2026-06-13). The S06.3 `extract_big_game.py` file at 2,685 LOC triggered the same "split this into smaller modules" review finding three times across iteration. Each time declined as out-of-scope: (a) uniform single-module convention across all 4 MT + future CO extractors; (b) coupling is test-mitigated (1,334-LOC test file locks the public surface); (c) modularization is an ADR-level project-wide call, not an in-review per-story refactor. Rationale recorded in `.roughly/known-pitfalls.md` to stop this from being re-litigated. **Formalized 2026-06-16 as [ADR-022](../../adrs/ADR-022-single-module-per-state-extractors.md) (Accepted)** — the recurring finding now has a canonical ADR to cite; modularization is reopened only by a future ADR that supersedes ADR-022 and applies uniformly across all CO + MT extractors in one PR — not piecemeal at review time.

10. **Latent S06.3 elk-correction-content gap** — **RESOLVED via S06.3.1 (2026-06-16)** (carved out 2026-06-16 per user decision; mirrors S05.3.5 → Known Issue #2 RESOLVED pattern). The 2026 CPW Big Game correction PDF is **moose + elk**, NOT moose-only as the S06.1 forward-note claimed. Page 2 is an elk-muzzleloader correction (hunt-code `E-M-…`, p.44). S06.3 closed treating the correction as moose-only inert and may have missed applying this elk-muzzleloader correction. **S06.3.1 Phase A** investigation gate resolves to one of three outcomes ((a) re-extract with correction applied; (b) confirm structurally-outside-V1-scope; (c) defer to S06.6 load-time); see the S06.3.1 story spec for the full investigation protocol. Bear is inert and unaffected (S06.4 confirmed empty operations list for bear). **Resolution (2026-06-16):** Phase A outcome **(b)** — the V1-scope elk corrections (`E-M-059-O1-M` → List A, `E-F-044-O1-R` → List B) were already incorporated in the committed artifact because the brochure PDF (2026-03-04) postdates the corrections (2026-02-13/17/19) and is the post-correction online edition; the other two corrections are moose (out of V1 scope); inert, no correction-merge machinery built.

11. **Latent `big-game-2026.json` row-fusion defect** — **RESOLVED via S06.3.1 (2026-06-16)** (carved out 2026-06-16 per user decision; same combined carve-out as #10 since both touch the same code and produce one coordinated SHA shift). The same pdfplumber row-fusion bug that S06.4's Rule R17 fixed in bear extraction exists in `extract_big_game.py` — **9 fused cells in `big-game-2026.json` silently dropped codes**. **S06.3.1 Phase B** ports R17 logic directly (split on multi-hunt-code cells, fail-loud on misalignment); Phase C coordinated re-extraction captures all 9 codes + re-pins SHA. See the S06.3.1 story spec for the full port protocol. **Resolution (2026-06-16):** R17 ported to big-game as Rule R16; **4** fused rows recovered (`D-M-082-O3-R`, `D-F-107-O1-R`, `A-M-004-O1-M`, `A-F-118-O1-R`); the spec's "9" was an unmeasured approximation; SHA re-pinned to `9312e2595071a80cc317250504e4ba6a7eaaae33a201a313db275aa0f0c8bb2f` <!-- pragma: allowlist secret -->.

12. **🚩 AFA classification deferral — must NOT bind AFA `role='no_hunt_zone'` at S06.10** (surfaced 2026-06-18 via S06.5 closure; user-decided 2026-06-17; cubic's lone P2 from S06.5 = this documented deferral). The Air Force Academy (`CO-restricted-united-states-air-force-academy-geom`, one of the 10 S05.4 `kind='restricted_area'` rows) is a **regulated-access HUNTING area, NOT a no-hunt zone** — GMU 512 carries CPW hunt codes; CPW publishes escorted rifle deer hunts on AFA land per Big Game brochure p.78. S06.5's `verbatim_rule` for that row now describes how to hunt there, not a closure. **User intent**: AFA must remain protected as a huntable zone in query results. **The other 9 S05.4 rows (4 NPs + 5 NMs)** are genuine no-hunt zones; `role='no_hunt_zone'` is correct for them (the S06.5 phrasing-case (1) NPS sentence is their verbatim closure rule). **S06.10 implementer must split the no-hunt-zone code path**: 9 rows → `role='no_hunt_zone'`; 1 row (AFA) → `role='other_overlay'` per **PM-recommended option (a)** OR escalate option (b) (geometry-side reclassification via S05.4 amendment) to the human if option (a) feels wrong. The S06.10 spec carries an inline forward-note with both options + the PM recommendation; surface to PM at S06.10 entry before the binding-loader plan drafts.

13. **🚩 ~477 female-row empty-`season_windows` gap — data-modeling decision (surfaced 2026-06-24 via S06.7 silent-failure review).** In `big-game-2026.json`, ~477 NON-Season-Choice hunt codes (mostly female `-F-` rifle rows) carry empty `season_windows` because the pdfplumber extractor merged each female row's season-date cell into the adjacent **male** row's cell. S06.7 **faithfully loads the artifact** (writes the female `license_tag`, emits zero `season_definition`/`license_season` for it) and now **emits a WARNING per zero-season row** so the gap is visible in run logs — NOT a silent drop. At the `regulation_record` level the seasons are still present (M and F collapse to the same `(GMU, species)` record; the male rows carry the seasons + the `regulation_season` links), so this is a per-*female-license-tag* `license_season` coverage gap, not a whole-GMU gap. **Open question for the human:** should female-sex license tags INHERIT the same-GMU/same-season male row's windows? That is cross-row state-specific logic the S06.7 spec says to flag-and-discuss rather than bake in silently (analogous to the S06.4 `valid_gmus` cleanup / R16-R17 extractor carve-outs). **Candidate dispositions:** (a) an `extract_big_game.py` carve-out that recovers the merged female-row windows at extraction time (re-pin SHA; the cleanest fix — the data exists in the male cell); (b) a documented V1 deviation (female tags carry no own seasons; clients fall back to the regulation_record-level seasons); (c) loader-side inheritance keyed on `(gmu, species, season_code, sex-agnostic)` — discouraged (state-specific cross-row branch). **PM recommendation: (a)** as a post-E06 extractor hygiene carve-out, mirroring S06.3.1. Not blocking S06.7 close (the gap is visible + the regulation_record level is complete).

14. **Cross-loader private-import contract → make the shared CO surface explicit** (surfaced 2026-06-27 via an S06.8 post-merge review P2). `load_draw_specs.py` imports underscore-prefixed helpers/constants from its siblings (`_co_license_tag_id` / `_co_big_game_license_kind` / `_co_bear_license_kind` / `_load_citation_from_sources_yaml` from `load_seasons_and_licenses.py`; `_STATE` from `load_regulation_records.py`). The reviewer flagged this as an implicit cross-loader contract on private API. **Disposition: this is the deliberate, established convention, not a defect** — it is the byte-identical mirror of MT (`load_draw_specs.py:132` imports from `montana/load_seasons_and_licenses`; `load_jurisdiction_bindings.py:97` imports `_JURISDICTION_BINDING_ID_FORMAT` from `load_regulation_records`), CO S06.7 already chains the same imports (`load_seasons_and_licenses.py:116`), and there is **no shared CO module** in either state by design. Importing the canonical id-derivation helper is the exact mechanism that **prevents** the backfill-id-divergence bug class (see `.roughly/known-pitfalls.md` "Backfill-id derivation must byte-mirror the upstream builder") — re-implementing locally would be the duplication, not the import. **Candidate (post-E06 hygiene sweep):** promote the shared CO id-derivation/classification/constants (`_co_license_tag_id`, the kind heuristics, `_STATE`/`CO_STATE_CODE`) into a documented shared surface (e.g. `colorado/_shared.py` or module-public exports), applied **uniformly across CO + MT in one PR** — never piecemeal at per-story review time (same discipline as ADR-022 + Known Issue #7). **Overlaps the S06.0/D3 `_STATE` vs `CO_STATE_CODE` unification already slated for S06.10**, which is the natural first step. Touches merged + audited code (S06.6/S06.7), so it needs its own review. Bundle with Known Issue #7 (overlay-builder shared-lib extraction) + #8 (MT-extractor `write_extraction_artifact` migration) in the post-E06 M2 hygiene-sweep PR.

15. **🚩 Bear-extractor GMU-851 row-fusion residual → `extract_black_bear.py` carve-out** (surfaced 2026-06-26 via S06.8 build discovery; skip-disposition user-ratified 2026-06-27). Three bear hunt codes at GMU 851 carry a trailing `+` corruption in `black-bear-2026.json` — `B-E-851-O1-M +`, `B-E-851-O2-R +`, `B-E-851-O5-R +` — a pdfplumber row-fusion residual (the same defect class S06.4's R17 / S06.3.1's R16 fixed for bear/big-game, but a residual remains at GMU 851). **S06.8 disposition: skip-with-WARNING** — the loader does not write a malformed string as a `draw_spec`/`license_tag` PRIMARY KEY (un-lookupable in the serving DB), and normalizing in the loader is incoherent because S06.7 already wrote the matching `license_tag` with the *same* corrupted id (`CO-GMU-851-bear-B-E-851-O2-R +-2026`). The 3 corrupted bear `license_tag` rows therefore keep `draw_spec_key=NULL` (a tracked gap). These 3 codes also surface as **orphan hybrid codes** (`B-E-851-O1-R/O2-R/O5-R` — in the draw-mechanics hybrid set, no clean limited-draw match): the `+` corruption explains `O2-R`/`O5-R`; `O1-R` (rifle) is a genuinely-absent per-unit variant. Both surfaces are WARNING-logged by S06.8 (no silent drop). The 3-agent review triad concurred with skip; cubic dissented (preferred faithful-load) across 2 iterations — escalated and **human-ratified skip-with-WARNING (2026-06-27)**. **Candidate (post-E06 extractor hygiene carve-out, analog of S06.3.1):** fix the `extract_black_bear.py` GMU-851 row-fusion residual so both S06.7 and S06.8 emit clean ids; re-pin the bear-artifact SHA; then the 3 bear codes get proper `draw_spec` rows + `draw_spec_key` backfills, and the hybrid orphans clear. Out of S06.8 (loader) scope per ADR-022 (extractors own extraction). Not blocking — the gap is visible and small (3 of 1914 draw_specs).

If E06 implementation surfaces issues out of E06 scope, implementation agents flag on the relevant story rather than silently widening scope. PM surfaces to human.

---

## References

- **PRD source:** [`docs/planning/prds/002-M2-colorado-ingestion.md`](../prds/002-M2-colorado-ingestion.md)
- **M1→M2 handoff:** [`docs/planning/handoffs/M1-to-M2-handoff.md`](../handoffs/M1-to-M2-handoff.md)
- **E05 epic (audited):** [`epics/completed/E05-colorado-geometry-ingestion.md`](completed/E05-colorado-geometry-ingestion.md)
- **E05 audit:** [`epics/completed/E05-audit.md`](completed/E05-audit.md)
- **E03 epic (M1 reference shape):** [`epics/completed/E03-regulation-text-ingestion.md`](completed/E03-regulation-text-ingestion.md)
- **CO draw schema proposal:** [`docs/research/colorado-draw-schema-proposal.md`](../../research/colorado-draw-schema-proposal.md)
- **CO restricted-areas evaluation:** [`docs/research/colorado-restricted-areas-evaluation.md`](../../research/colorado-restricted-areas-evaluation.md)
- **Architecture data model:** [`docs/architecture.md`](../../architecture.md)
- **ADRs accepted at M2 plan time:** ADR-001, ADR-003, ADR-004, ADR-005, ADR-006, ADR-007, ADR-008, ADR-010, ADR-011, ADR-012, ADR-014, ADR-015, ADR-016, ADR-017, ADR-018, ADR-019, ADR-020, ADR-021 (the 8th value `no_hunt_zone` for `jurisdiction_binding.role`)
- **E03 deferred items (carried into E06 trigger inventory):** [`epics/completed/E03-deferred-items/draw-mechanics.md`](completed/E03-deferred-items/draw-mechanics.md), [`epics/completed/E03-deferred-items/cwd-sampling-modeling.md`](completed/E03-deferred-items/cwd-sampling-modeling.md), [`epics/completed/E03-deferred-items/closure-temporal-anchors.md`](completed/E03-deferred-items/closure-temporal-anchors.md), [`epics/completed/E03-deferred-items/README.md`](completed/E03-deferred-items/README.md)
- **E05 operator runbook (precondition for E06 live execution):** [`docs/runbooks/E05-colorado-geometry-verification.md`](../../runbooks/E05-colorado-geometry-verification.md)
- **S05.6 binding-loader scaffold (E06 S06.10 imports):** [`ingestion/states/colorado/load_jurisdiction_bindings.py`](../../../ingestion/states/colorado/load_jurisdiction_bindings.py)
