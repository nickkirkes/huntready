# E06: Colorado Regulation Text Ingestion

**Status:** Not Started
**Milestone:** M2 — Colorado Ingestion
**Dependencies:** E04 (M1 carry-forward + CO schema prep), E05 (CO geometry ingestion — all 9 stories closed + audited 2026-06-06; epic at [`completed/E05-colorado-geometry-ingestion.md`](completed/E05-colorado-geometry-ingestion.md))
**Validated:** 2026-06-08 (E06 validation triad: Source Faithfulness + Draw-Mechanics & Confidence + Schema Stress-Test & Drift-Guard; verdicts LAND-WITH-MINOR-EDITS + LAND-WITH-EDITS + LAND-WITH-MINOR-EDITS; **all 11 MUST-FIX findings applied at draft time** — broken ADR-020 link sweep [5 occurrences]; S06.0 Last-Modified/Content-Length header capture + cover-page confirmation + multi-source option (a)/(c) consequence chains + conditional 6th `db.update_geometry_verbatim` decision + schema-gap enum-extension precision; S06.1 `pending: true` drift-marker semantics; S06.3/S06.4/S06.5 ADR-008 paraphrase-prohibition + no-`layout=True` AST guard + docstring grep-parity discipline; S06.4/S06.6/S06.9 `SourceCitation.document_type` silent-widening guard per ADR-019 §"Decision" item 5; S06.6 `_JURISDICTION_BINDING_ID_FORMAT` 3-test lock + statewide-anchor 3rd-candidate flag tighten + ADR-017 FINALIZE lock; S06.7 `drift_guard.assert_id_matches` every-build-function-site language + pure id-derivation function AC + Q16/Q17/closure-temporal-anchors pre-code flag protocols; S06.8 `successor_hunt_code_key` composite-key form + 20%/25% coupling rule + `application_deadline` location lock + `purchase_only_code` per-species string + `inactive_forfeit_years=null` + module-level `Final` constants for `_HYBRID_*` parameters + `draw_spec` composite-PK exclusion AC + Q17 per-GMU caps flag; S06.9 `assert_dispatch_dict_drift_free` module-top timing + pure `_derive_reporting_obligation_id` callable; S06.10 `drift_guard` NOT imported AC + AST guard + `%s`-bound distance lock + 4-builder portion code-path preservation. Plus the most load-bearing SHOULD-FIX items.)
**Completed:** —
**Estimated Stories:** 13 (S06.0 through S06.11, plus S06.3.1 carved out 2026-06-16 post-S06.4-closure to address Known Issues #10 + #11 per the S03.6.1 / S05.3.5 mid-epic carve-out precedent; carve-outs added at sequencing slots if surfaced mid-epic)
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
| `role='no_hunt_zone'` enum | [ADR-021](../adrs/ADR-021-jurisdiction-binding-no-hunt-zone-role.md) (Accepted via S05.3.5) | E06's S06.10 binding-loader writes `role='no_hunt_zone'` directly for the 10 S05.4 federal no-hunt-zone geometry rows. No `other_overlay` fallback; no ADR-pause. DDL CHECK constraint permits the value. |
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
| CO federal no-hunt zones (10) | S05.4 production write (`kind='restricted_area'`, ids `CO-restricted-{slug}-geom`, `verbatim_rule=None`) | S06.10 binding loader writes `role='no_hunt_zone'` per ADR-021. S06.5 OR S06.10 (PM-decided at story open) populates `verbatim_rule` via `UPDATE geometry SET verbatim_rule = ... WHERE id = …` once CPW Big Game brochure URL is resolved. |
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
- [x] `extracted/big-game-2026.json` deterministic SHA-256 across two consecutive extraction runs; **737 sections / 2,758 rows** committed as the durable text-side fixture. **⚠️ SHA pin updated 2026-06-15 via S06.4 coordinated `valid_gmus` cleanup**: original pin `3c2ecd90…015d` → current pin `e5c7c33a728a95f3d2845894ce53d4de664ed20bfc40853eaa421ac8d12e6d1e` <!-- pragma: allowlist secret -->. Counts UNCHANGED (737/2758); confidence UNCHANGED (`{high: 2170, medium: 583, low: 5}`); only field contents moved (prose qualifiers routed out of `valid_gmus` to `extras`); re-pinned in `test_extract_co_big_game.py`. **⚠️ SHA pin advanced again 2026-06-16 via S06.3.1 R17 port + re-extraction**: `e5c7c33a…6d1e` → `9312e2595071a80cc317250504e4ba6a7eaaae33a201a313db275aa0f0c8bb2f` <!-- pragma: allowlist secret -->. Full lineage: `3c2ecd90…015d` (S06.3 close) → `e5c7c33a…6d1e` (S06.4 `valid_gmus` cleanup) → `9312e259…bb2f` (S06.3.1 R17 port). Counts: sections 737→736, rows 2758→2762; confidence high 2170→2178 / medium 583 / low 5→1; 4 previously-fused codes recovered (`D-M-082-O3-R`, `D-F-107-O1-R`, `A-M-004-O1-M`, `A-F-118-O1-R`).
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

**Status:** Complete — closed at-merge 2026-06-16

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
- [ ] **UAT (PM-pending at story close):** PM-run spot-check on (a) the 9 newly-captured codes cross-checked against the source PDF + (b) any elk-muzzleloader rows updated by Phase A outcome (a) merge *(PM-pending at close per Group-A/B posture)*
- [x] Closure note documents per-fix count delta: "Phase A applied N rows (or N/A if outcome (b)/(c))" + "Phase B captured 9 previously-dropped codes"
- [x] Epic Known Issues #10 + #11 annotated as **RESOLVED via S06.3.1** (mirrors S05.3.5 → Known Issue #2 RESOLVED pattern)
- [x] No production-DB writes from the build session (S06.3.1 is documentation + extraction-side only; no DB)

---

### S06.5: Restricted-area `verbatim_rule` population for the 10 S05.4 no-hunt zones

**Status:** Not Started

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

- [ ] `ingestion/states/colorado/load_restricted_area_verbatim.py` exists; state-agnostic-clean per AST guard
- [ ] All 10 S05.4 geometry rows (`CO-restricted-{slug}-geom`) have `verbatim_rule` populated post-load; SQL spot-check verifies non-null across all 10
- [ ] `source` field updated per S06.0 decision (UPDATE to CPW citation OR retained as PAD-US OR multi-source); SQL verifies field matches decision
- [ ] **ADR-008 paraphrase prohibition (UPDATE surface):** the brochure-source string written to `geometry.verbatim_rule` for each of the 10 zones is byte-equivalent to `pdf.extract_text` output (S03.2 word-grouping baseline) for the source span; if extraction from the brochure produces a per-zone `verbatim_rule` candidate that requires hand-editing to read as a coherent sentence, build fails loud and surfaces the candidate as flag-and-discuss; no silent rewording
- [ ] **Phrasing case locked:** implementer records in the closure note which case fired — (1) single generic sentence shared across all 9 NPS rows, or (2) per-park named sentences (9 distinct strings) — and the chosen case is locked by a regression test asserting either uniform vs distinct content across the 9 NPS rows
- [ ] Per-row text faithful to source PDF; PM-run spot-check on ≥3 of the 10 zones (e.g., Rocky Mountain NP, Mesa Verde NP, AFA) cross-checks against the brochure
- [ ] If REG + COMMENTS combination: ADR-015's `\n\n--- COMMENTS ---\n\n` separator used; spot-check verifies
- [ ] `db.update_geometry_verbatim` helper exists with `cur.rowcount == 0` fail-loud guard if added per S06.0 conditional-6th-decision (mirrors `update_legal_description` pattern post-S03.6)
- [ ] Test suite grows additively; 5-15 tests in `test_load_co_restricted_area_verbatim.py`
- [ ] No production-DB writes from the build session (live UPDATE is operator-driven); operator runbook in `docs/planning/epics/E06-confidence-findings/S06.5.md`

---

### S06.6: `regulation_record` ingestion (5 V1 species × applicable CO GMUs + statewide anchors)

**Status:** Not Started

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

- [ ] `ingestion/states/colorado/load_regulation_records.py` exists, state-agnostic-clean, three-phase shape (build → guards → conn/commit)
- [ ] Per-species fan-out applied: artifact `deer` → DB `mule_deer` + `whitetail` (verified by test asserting emit count for a GMU with `deer` artifact rows is 2 DB rows)
- [ ] Bear DB `species_group="bear"` not `"black_bear"` (per S03.6 pitfall)
- [ ] Row-count fail-loud guard ±30% band fires pre-`db.connect()` (OQ7); band documented in closure note
- [ ] Atomic transaction: all rows commit OR rollback together
- [ ] Source citation populated on every row; `SourceCitation.document_type` ∈ `{annual_regulations, correction}` for every CO `regulation_record.source` written by S06.6; **any other value encountered during build (including the existing-but-unranked `rule_change` / `emergency_order` / `gis_layer`) raises `ValueError` at build time and is surfaced as a flag-and-discuss event per ADR-019 §"Decision" item 5** — no silent enum participation, no implicit default rank, ADR-019 amendment required before adoption. The merge itself happens at S06.4 build time; S06.6 receives the post-Pass-3 merged artifact and reads `document_type` per row from it
- [ ] CO statewide-anchor row(s) written if CPW data requires (pronghorn STATEWIDE row analog of MT `900-20`; bear statewide coursework analog of S03.6.1). **PM expects 0-2 statewide-anchor rows**. **If extraction surfaces a 3rd candidate**, the implementer STOPS, files a flag-and-discuss event with the source span + rationale; PM consolidates and a human approves the candidate BEFORE the row is written. Silent addition of a 3rd statewide anchor is a process violation
- [ ] `_JURISDICTION_BINDING_ID_FORMAT` constant defined in module + locked by **three tests** (mirrors S03.6.1 / S03.10 pattern): (1) format string byte-identical to MT's `_JURISDICTION_BINDING_ID_FORMAT` in `load_regulation_records.py` (or an explicitly-documented CO-specific divergence with rationale); (2) the constant is importable by S06.10 (the S05.6 scaffold's symmetric derive-and-assert contract); (3) any CO statewide-anchor regulation_record written here produces a binding-id under this format that S06.10 re-derives byte-identically (UPSERT no-op contract)
- [ ] NOTE-line extraction follows S03.6's hardened `^NOTE:[ \t]*` regex (cross-NOTE absorption guard); SQL-spot-checks verify NOTE lines land in `regulation_record.additional_rules`
- [ ] No `db.py` helper additions unless explicitly required; if added (e.g., `upsert_regulation_record` for any CO-specific quirk), reused pattern from S03.6
- [ ] **ADR-017 FINALIZE lock:** framework is unmodified per S03.11 FINALIZE verdict; `low`-tier rows in CO are data-shape signal, not framework signal. Any candidate framework change is a flag-and-discuss event surfaced to the human; PM does NOT draft an ADR-017 amendment autonomously. The S03.11 deliberation (PM PARTIAL DEFER recommendation overridden to FINALIZE by user) is the precedent
- [ ] Test baseline grows additively; 50+ tests in `test_load_co_regulation_records.py`

---

### S06.7: `season_definition` + `license_tag` + `license_season` ingestion (drift_guard.assert_id_matches mandatory)

**Status:** Not Started

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

- [ ] `ingestion/states/colorado/load_seasons_and_licenses.py` exists, state-agnostic-clean, three-phase shape
- [ ] **ADR-020 `assert_id_matches`** invoked **in every per-row entity-construction site** inside the `season_definition` and `license_tag` build functions (mirrors MT precedent's 4 call sites at `load_seasons_and_licenses.py:589 / 660 / 926 / 1100`: one per `_build_*_season_definitions` and one per `_build_*_license_tags`, fanned by source — deer-equivalent + elk-equivalent + pronghorn-equivalent + bear-equivalent + any CO-specific source split). Each call site passes the entity's id and the value returned by re-calling a pure id-derivation function (e.g., `_co_season_definition_id` / `_co_license_tag_id`) on the entity's structured fields; the derivation function lives at module level and is the single source of id-construction truth (mirrors `_season_definition_id` / `_license_tag_id` at `load_seasons_and_licenses.py:370/387`). The verification test enumerates every build function in the module and asserts each constructs entities via `assert_id_matches` against a pure id-derivation function (mirrors M1's `TestDriftGuardCallSites` pattern). **A new build function added later without an `assert_id_matches` call must fail the test**
- [ ] Link-table builders NOT instrumented (`drift_guard` not imported in `_build_license_season_links` / `_build_regulation_season_links` / `_build_regulation_license_links`; AST regression-guard test from M1 stays green)
- [ ] 5 row-count fail-loud guards fire pre-`db.connect()` (one per entity/link table); bands documented in closure note
- [ ] All UPSERTs atomic in one transaction; CO license_tag.draw_spec_key = None on every row at S06.7 (S06.8 backfills per ADR-012)
- [ ] **Asymmetric coverage demonstrator:** if CO has A/B-license-equivalent asymmetric coverage, locked by `test_license_season_asymmetric_coverage_m2_criterion`; if CO does not, deviation documented in closure note + flag-and-discuss (downstream consequence: PRD 002 success criterion #2 status at S06.11 UAT carries an operator note acknowledging the N/A clause)
- [ ] **License-tag species fan-out** (Q16 trigger): if CPW publishes row-level mule_deer/whitetail separation, the implementer **STOPS adapter coding at that discovery**, files a flag-and-discuss event with the artifact-level evidence + page reference, and PM surfaces to the human BEFORE any CO-specific branching is added to the adapter. The fan-out decision flows through ADR-010 amendment + three-place sync; **the adapter does NOT branch on state until the ADR lands**. Artifact-level (deer) → DB-level decision recorded; verified by test
- [ ] License-tag kind heuristic inspects `apply_by` for OTC discriminator (per S03.8 fix); 5-ordered-branch with fail-loud else
- [ ] **Closure-predicate `effective_after` trigger:** for every bear/deer/elk closure prose in the CPW brochure, the implementer documents in the closure note: (a) is there a calendar gate? (b) is there a quota threshold? (c) are they conjoined? **If (a)+(b)+(c) all yes for any closure, the implementer STOPS adapter coding**, files a flag-and-discuss event with the verbatim prose + page reference, and PM surfaces to the human BEFORE any `closure_predicate` row is written for that case (per the `closure-temporal-anchors.md` ADR-candidate). **If a CO closure surfaces a predicate shape outside the M1-locked `sex_threshold` / `quota_threshold` enum AND outside the `effective_after` candidate, the implementer flags + halts** (do not silently widen the `ClosurePredicate` shape)
- [ ] **Cross-listing structural agreement** validated across same-`license_code` rows (S03.8 lesson); **if CO has cross-listed structural conflicts (Q17 trigger), the implementer STOPS, files a flag-and-discuss event documenting the per-GMU shape + a candidate ADR-disposition (override-table V1 stopgap vs schema extension)**; PM surfaces to human BEFORE adopting `_KNOWN_CROSS_LISTING_OVERRIDES`-equivalent. The V1 stopgap is acceptable only with human approval; silent adoption is a process violation
- [ ] Test baseline grows additively; 80+ tests in `test_load_co_seasons_and_licenses.py`

---

### S06.8: `draw_spec` ingestion (CPW preference-point hybrid — Q12/Q17 trigger surface)

**Status:** Not Started

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
- [ ] No-hunt-zone bindings: 10 `kind='restricted_area'` zones × their nearby GMUs (per `query_nearby_gmus_for_zone()`); `role='no_hunt_zone'` per ADR-021
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

**Recommended merge order:** S06.0 → S06.1 → S06.2 (conditional) → S06.3 → S06.4 (may fold into S06.3) → S06.5 → S06.6 → S06.7 → S06.8 → S06.9 → S06.10 → S06.11

**Dependency rationale (in order):**

- **S06.0 → S06.1**: hard precondition — S06.1 cannot start until S06.0 records the operator-resolved Big Game brochure URL + the 5 pre-registered decisions are captured
- **S06.0 → S06.5**: multi-source provenance decision required before S06.5 spec
- **S06.0 → S06.9**: Q18 disposition required before S06.9 spec
- **S06.0 → S06.10**: Known Issue #6 + `_STATE` naming decisions required before S06.10 spec
- **S06.1 → S06.2 → S06.3 → S06.4**: PDF fetch infra → primitives extension (conditional) → per-source extraction (parallelizable across S06.3 + S06.4 if Black Bear is separate brochure; but convention is sequential per the prompt)
- **S06.3 + S06.4 → S06.6**: regulation_record ingestion needs all extraction artifacts available
- **S06.6 → S06.7**: link-table ingestion FKs to regulation_record (FK-direction)
- **S06.7 → S06.8**: draw_spec ingestion backfills license_tag.draw_spec_key (per ADR-012)
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
- **Q16 species granularity** — if CPW separates mule_deer / whitetail at row level (artifact-level fan-out → row-level fan-out), trigger ADR-010 amendment.
- **Q17 per-GMU allocation caps in `draw_spec`** — if CPW publishes per-GMU caps that don't fit `pools[].share` (numeric share sums to 1.0) shape, trigger ADR-candidate. `_KNOWN_CROSS_LISTING_OVERRIDES`-equivalent workaround applies V1.
- **`role='no_hunt_zone'` enum addition** — RESOLVED via ADR-021 (S05.3.5); E06 inherits.
- **Multi-source geometry provenance** — third trigger candidate may surface at S06.5 if S06.0 chose option (c); resolves via ADR-candidate.
- **`effective_after: date | None` on `ClosurePredicate`** — closure-temporal-anchors.md ADR-candidate; trigger condition: any CO closure conditional on BOTH a quota threshold AND a calendar gate. S06.7 evaluates.
- **Q20 — Season Choice (method letter `X`) modeling** (opened 2026-06-13 in `docs/open-questions.md` via S06.3 closure). CPW publishes a `Season Choice` method (hunt-code suffix `X`) that maps in the artifact to `method_group="season_choice"` + `weapon_types=["archery", "muzzleloader", "any_legal_weapon"]`. How `X` licenses materialize into `season_definition` + `license_tag` rows is deferred to S06.7: one `season_definition` with a multi-weapon span, one `license_tag` per weapon-method permutation, or some other normalization. S06.7 spec drafting flags this as a pre-code decision (PM expectation: surface as flag-and-discuss at S06.7 entry; do NOT silently fan out or collapse).

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
