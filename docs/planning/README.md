# HuntReady — Planning Index

**Last Updated:** 2026-05-27
**Current Milestone:** M1 — Montana Ingestion (E01 + E02 complete; E03 active — 13/14 stories complete: S03.0-S03.9 + S03.6.1 + S03.10 + S03.11 confidence calibration audit (closed 2026-05-27 verdict FINALIZE; ADR-017 unmodified; Q11 RESOLVED; synthesis report survives m1 tag). **Only S03.12 (M1 UAT + handoff) remains.**)
**Overall V1 Status:** 1/6 milestones complete

---

## Milestone Status

| Milestone | Name | Status | Validated | Dependencies |
|---|---|---|---|---|
| M0 | Scaffold | Complete | 2026-04-22 | None |
| M1 | Montana Ingestion | In Progress | — | M0 |
| M2 | Colorado Ingestion | Not Started | — | M1 |
| M3 | MCP Server | Not Started | — | M1 |
| M4 | Web Companion | Not Started | — | M3 |
| M5 | Claude Code Plugin | Not Started | — | M4 |

---

## Current Milestone: M1 — Montana Ingestion

M1 delivers Montana regulations into Supabase Postgres, validated against the six-entity schema, covering five V1 species across all applicable jurisdictions. Three sequential epics:

### Epic Status

| Epic | Name | Status | Validated | Completed | Stories |
|---|---|---|---|---|---|
| E01 | Schema Migrations, RLS, and Quality Gates | Complete | 2026-04-24 | 2026-04-28 | 6 |
| E02 | Montana Geometry Ingestion | Complete (audited) | 2026-04-28 | 2026-05-03 | 8 |
| E03 | Montana Regulation Text Ingestion | In Progress (13/14 — S03.11 closed 2026-05-27 verdict FINALIZE, ADR-017 unmodified, Q11 RESOLVED; S03.12 is final M1 story; S03.10 T16 live UAT operator-pending but does not gate m1) | 2026-05-03 | — | 14 (13 original + S03.6.1) |

### E03 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S03.0 | Schema preparation — license_season + geometry.legal_description + geometry.kind='state' + Montana state geometry | Complete | Implementation |
| S03.1 | PDF fetch infrastructure | Complete | Implementation |
| S03.2 | PDF extraction primitives (shared library) | Complete | Implementation |
| S03.3 | DEA booklet extraction (deer, elk, antelope) | Complete (UAT passed 2026-05-08 after one fix cycle; plan-realignment + fail-loud polish 2026-05-09) | Implementation (UAT: yes) |
| S03.4 | Black Bear booklet extraction + correction PDF handling | Complete (UAT passed 2026-05-12; Option B doc-type precedence accepted) | Implementation (UAT: yes) |
| S03.5 | Legal Descriptions extraction | Complete (UAT passed 2026-05-14 after PM-review-driven fix cycle) | Implementation (UAT: yes) |
| S03.6 | regulation_record ingestion | Complete (closed 2026-05-15; 436 rows + 228 legal_description writes) | Implementation |
| S03.7 | season_definition + license_tag + license_season ingestion | Complete (closed 2026-05-16; M1 criterion #2 satisfied at data layer; 8542 rows + 20 closure_predicates) | Implementation (UAT: yes) |
| S03.8 | draw_spec ingestion | Complete (closed 2026-05-19; 388 draw_spec rows / 278 unique + 388 license_tag.draw_spec_key backfills) | Implementation |
| S03.9 | reporting_obligation ingestion | Complete (closed 2026-05-21; 3 reporting_obligation rows + 70 regulation_reporting link rows; epic line 807 corrected; CWD sampling deferred to Q18; Bear ID coursework carved to S03.6.1) | Implementation |
| S03.6.1 | MT-STATEWIDE-bear anchor with Bear ID Test + jurisdiction_binding to MT-STATEWIDE-geom | Complete (closed 2026-05-22; 437 regulation_record + 1 jurisdiction_binding + new `db.upsert_jurisdiction_binding` helper for S03.10 to reuse) | Implementation (carved out 2026-05-19; binding scope-add 2026-05-21; closed 2026-05-22) |
| S03.10 | jurisdiction_binding generation | Complete (code-complete 2026-05-26 via PR `e83ef2d`; first cross-cutting binding loader; ~870 LOC; 18 fail-loud guards; 4 PM-approved spec deviations; 7 new pitfalls; reuses `db.upsert_jurisdiction_binding` helper from S03.6.1 — no `db.py` changes; T16 live UAT operator-pending; 1128 + 2 skipped tests) | Implementation (UAT T16: operator-pending; does not gate downstream) |
| S03.11 | Confidence calibration audit + ADR-017 finalization | Complete (closed 2026-05-27 via PR #42 squash `b84955c`; verdict FINALIZE; ADR-017 unmodified; Q11 RESOLVED; synthesis report at `docs/planning/epics/E03-confidence-calibration-synthesis.md` survives m1 tag; 50/50 = 100% audit pass-rate; doc-only PR — test suite holds at 1128+2) | Implementation + PM |
| S03.12 | M1 UAT preparation + handoff to M2 | Not Started | Implementation + PM (UAT: yes) |

### E02 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S02.0 | Schema preparation — `document_type='gis_layer'` + `geometry.verbatim_rule` | Complete | Implementation |
| S02.1 | ArcGIS fetch infrastructure (shared library) | Complete | Implementation |
| S02.2 | Hunting District ingestion (#3, #10, #11) | Complete | Implementation |
| S02.3 | Portions ingestion (#4, #12, #13, #14) | Complete | Implementation |
| S02.4 | Restricted Areas with verbatim text (#2, #15) | Complete | Implementation |
| S02.5 | CWD zone discovery and ingestion | Complete | Implementation (UAT: yes) |
| S02.6 | Geometry overlay fixture | Complete | Implementation (UAT: yes) |
| S02.7 | Spatial query verification + epic exit | Complete | Implementation (UAT: yes) |

### E01 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S01.1 | Install pre-commit hooks | Complete | Implementation |
| S01.2 | Initial migration — entity tables, link tables, indexes | Complete | Implementation |
| S01.3 | RLS migration — deny-all policies | Complete | Implementation |
| S01.4 | Python dataclasses matching DDL | Complete | Implementation |
| S01.5 | TypeScript types matching DDL | Complete | Implementation |
| S01.6 | Migration reproducibility verification | Complete | Implementation |

---

## Active Blockers

**E03 planned 2026-05-03.** 13 stories drafted, validated via the E03 triad (Source Faithfulness, Confidence Calibration, Schema Stress-Test), revised against findings. Two new ADRs accepted: **ADR-017** (confidence calibration + parent-inheritance rule, resolves Q11) and **ADR-018** (E03 schema additions: `license_season` link table + `geometry.legal_description` column + `geometry.kind='state'` value). None blocking S03.0.

Carry-over items from E02 (non-blocking, addressed within E03):

- **Restricted-area discriminator question** (E02 handoff #7) — addressed in S03.10 via no-hunt-zone Option A (bind to nearby HDs as `other_overlay`); structural answer deferred to M2 if Option A clumsy.
- **PRD 001 jurisdiction_binding sequencing** — proposed reconciliation wording in [E02 epic](epics/completed/E02-geometry-ingestion.md) § "Known issues to escalate". PM does not modify PRDs.

Documentation-debt items (non-blocking):

- Architecture.md prose says "every entity carries `confidence`" but interfaces only place it on `RegulationRecord` and `VerbatimRule`. Scheduled remote agent fires 2026-05-12 to PR a fix if still stale.

---

## Next Actions

- **S03.4 closed 2026-05-12.** PR `ab09e82` squash-merged to main; 35 BMU rows + 2 closures + 3 reporting obligations in `black-bear-2026.json`. UAT cleared (4 BMUs spot-checked against `pdfplumber`-extracted source: BMU 411 quota-closure+female-subquota; BMU 300 Spring Closure; BMU 100 unrestricted; BMU 700 quota-closure). Three spec corrections accepted: (a) AC #428 9→8 quota-closure BMUs (BMU 530 absent from 2026 PDF); (b) AC #429 2→3 reporting obligations (statewide 48-hour mandatory reporting is distinct from R1/R2-7 inspection); (c) AC #430-431 **Option B (doc-type precedence)** replaces spec's MAX-date Option A (booklet Last-Modified 2026-04-27 post-dates correction 2026-03-18, so Option A would silently no-op). 35 BMU rows all confidence=medium (HIGH→MEDIUM demote via correction-touched single demote-one-tier per row). 12 real-PDF discoveries documented in closure note; 8 new pitfalls in `.roughly/known-pitfalls.md`. Test suite: 574 passed + 2 skipped.
- **ADR-019 accepted 2026-05-12** at [`docs/adrs/ADR-019-doc-type-precedence-multi-source-merge.md`](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md). Formalizes the doc-type-precedence rule (`correction` > `annual_regulations`) for all future state adapters. PRD 001 R5 wording reconciliation deferred to the next PM-led PRD review pass or before E04 planning, whichever comes first. The ADR's V1 rank table is exhaustive within the regulation-text merge path: a `rule_change` or `emergency_order` source attempting to participate fails loud at merge time, and adding a rank for either requires an ADR amendment first. `gis_layer` is structurally outside regulation-text merges (it's the geometry-source doc-type per ADR-014) and the rule doesn't apply.
- **S03.5 closed 2026-05-14** via PR `b2ad20b` (10 commits `ece1ab1..e96a195`). Initial implementation surfaced through PM-run review identified 1 P1 (verbatim spillage — column-crop x-range too narrow at 145pt for col 2, truncating "Those portions" → "Those portio" and defeating the regex anchor; bear-319 absorbed 4 subsequent HDs reaching 8059 chars vs 855 median) + 5 P2 findings (S03.5.md count, footer crop 20pt→50pt, plan unlinked-scope contradiction, plan HeadedBlock.kind missing "continuation", CWD canonicalize before consolidation). Agent applied all 6 fixes in 9 follow-up commits before merge; matched count rose 156 → 228 across the cycle and bleed cases dropped 35 → 0. Final artifact: 228 matched (226 HD + 2 CWD) / 31 by-design unmatched / 119 unlinked (full 347-row V1 surface accounted for); regression rate 0.000. Seven new pdfplumber pitfalls in `.roughly/known-pitfalls.md`. Test suite: 657 + 2 skipped (+83 from S03.5). PM UAT spot-check 2026-05-14 on 2 descriptions (HD 100 + Libby CWD) faithful to source.
- **S03.9 closed 2026-05-21** via PR `195ac8b` (squash of 8 pre-squash commits: 1 main implementation + 7 cubic-review fix-up rounds). Final state: **3 reporting_obligation rows (STATEWIDE harvest_report 48hr + R1 tooth_submission 10-day + R2-7 hide_skull_presentation 10-day) + 70 regulation_reporting link rows (35 STATEWIDE + 14 R1 + 21 R2-7)** in one atomic transaction. **Three substantive scope evolutions via the 2026-05-19 source-audit probe** (Three-Blocker discovery): (a) **CWD sampling deferred to Q18** — verbatim text already in `regulation_record.additional_rules` from S03.6; license-keyed pattern means zone-keyed `geometry-overlays.json` join would miss the `Deer Permit: 103-50` case. (b) **Bear ID coursework carved out to S03.6.1** — pre-purchase licensing prerequisite belongs in `regulation_record.additional_rules` via new `MT-STATEWIDE-bear` anchor (mirrors `MT-STATEWIDE-antelope` pattern), NOT in `reporting_obligation` which is post-harvest/in-season only. (c) **Epic line 807 corrected (PM-approved)** — "general reporting obligation for all V1 species" assumption removed; bear is the only V1 species with a statewide mandatory harvest report per FWP authoritative list (bear/wolf/marten/swans). **Two new open questions** in `docs/open-questions.md`: **Q18** (CWD sampling target-table modeling; M2 ADR-candidate when Colorado lands) and **Q19** (id text-PK UPSERT drift; **pre-M2 blocker**; affects 3 helpers in `db.py`; ADR required at resolution; leading option is derive-and-assert generalizing S03.9's local pattern). **Three new patterns for S03.6.1/S03.10+**: (1) OQ7 row-count guard is the canonical count authority (in-builder exact-count checks contradict band semantics — remove; build = data construction); (2) defensive fail-loud surface for artifact-list iterations (`isinstance` type-check BEFORE key access; try/except KeyError → RuntimeError wrapping; per-element diagnostics + duplicate-id guards); (3) `reporting_obligation.kind` semantic boundary — post-harvest/in-season only; pre-purchase prerequisites go in `regulation_record.additional_rules`. **Four new pitfalls** in `.roughly/known-pitfalls.md` (source-audit upstream artifacts before planning; kind semantic boundary; submission_method multi-modal interpretation; id-text-PK UPSERT drift). **7 cubic-review rounds during PR review** added 18 tests + the 4th pitfall; pre-merge test count was 963 (main commit), post-merge is **981 + 2 skipped**. **`cwd-sampling-modeling.md` added** to `docs/planning/epics/E03-deferred-items/` (survives past m1).
- **S03.6.1 closed 2026-05-22** via PR `339e213` (squash-merged from `feat/S03.6.1-mt-statewide-bear-anchor`). Final state: **437 regulation_record (+1) + 1 jurisdiction_binding (first ever written)** in one atomic transaction. **Four PM decisions baked in (OQ-S6.1-1 through OQ-S6.1-4)**: (1) artifact shape `list[StatewideRuleCandidate]` for M2 extensibility; (2) `rule_hint` as `str` (not Literal) for cross-state extensibility; (3) no `NOTE:` prefix on text — raw verbatim per ADR-008; (4) `db.upsert_jurisdiction_binding`'s UPDATE clause excludes 6 identity-encoded fields — silent-repoint protection refining ADR-018 binding semantics. **12 cubic-review cycles + Stage 6 triad** during PR review (review history catalogued in closure note). **Artifact SHA-256 stable across the entire cycle.** Test suite: **1024 + 2 skipped** (+43 net from S03.6.1).
- **S03.10 code-complete 2026-05-26** via PR `e83ef2d` (squash-merged from `feat/S03.10-jurisdiction-binding-generation`; 8 pre-squash commits: 1 main impl + 7 review-driven fixes). First **cross-cutting** binding loader (`ingestion/states/montana/load_jurisdiction_bindings.py` ~870 LOC). Reads `geometry-overlays.json` × regulation_record cross product, applies per-species filtering, walks 4 binding sources (statewide / overlay self-row / overlay portions / no-hunt-zone Option A), UPSERTs in one atomic three-phase transaction via `db.upsert_jurisdiction_binding` reused from S03.6.1 (no `db.py` changes — read SELECTs live in the adapter per S03.10 constraint #7). **T16 live UAT operator-pending** — regulation_record table empty at T0 probe; requires batch run of S03.0/S03.6/S03.6.1/S03.7/S03.8/S03.9 before binding writes can occur. Projected ~1000 bindings (2 statewide + ~940 overlay + ~59 no-hunt-zone) inside `[400, 1100]` guard band. **Four PM-approved spec deviations** footnoted in epic (L1045/L1070/L1092/L1311+L1313): (1) id format imports `_JURISDICTION_BINDING_ID_FORMAT` from S03.6.1's locked constant — bear binding UPSERTs as no-op; (2) count band `[400, 1100]` (spec's 1,500-3,500 was 2x too high); (3) source attribution via adapter-local SELECT against `geometry.source` (no new `db.py` helper); (4) no-hunt-zone "nearby" rule simplified to single-clause `extensions.ST_DWithin(zone.geom, hd.geom, 5000)` on native geography (boundary-to-boundary; spec's two-clause centroid-based rule returned 0 matches for all 3 orphans). **18 fail-loud guards** added across review-triad + 4 PR-review rounds. **7 new pitfalls** in `.roughly/known-pitfalls.md` (3 PostGIS/Supabase + 4 ingestion-adapter conventions). **Q19 NOT propagated to this module** — `db.upsert_jurisdiction_binding` already excludes identity fields from UPDATE (stronger mitigation than the 3 Q19-affected helpers); Q19 remains a pre-M2 blocker for those 3. **Test suite: 1128 + 2 skipped** (+104 net from S03.10). **5 M2-deferred items recorded:** `role='no_hunt_zone'` enum candidate; portion-keyed reg_records (3 coordinated touchpoints); Colorado adapter must filter `_STATE='US-CO'`; count band narrowing after T16; multi-source geometry provenance schema.
- **S03.11 closed 2026-05-27** via PR #42 (squash-merged as `b84955c`, on main at merge commit `7021bda`). **Verdict: FINALIZE.** ADR-017 active file unmodified (status remains `Accepted`; all 7 numbered sections untouched). **Q11 RESOLVED** in `docs/open-questions.md`. Audit shape: 50-row stratified sample × 10 documented edge cases (artifact-based per S03.10 T0 probe finding `regulation_record` empty); 50/50 = 100% pass-rate scoped per ADR-017 §3 (regulation_record.confidence 39/39 + EC8 parent-inheritance 6/6 + EC9 license_tag row-level 5/5). Tier distribution across projected 437 regulation_record rows: `high=32 medium=405 low=0`. **Defer-or-finalize arc**: PM recommended PARTIAL DEFER under LITERAL reading of Trigger 2 (`low=0` literally fires); `roughly:epic-reviewer` returned LAND-WITH-EDITS on PM's DRAFT; PM applied 4 refinements; user overrode to FINALIZE under INTENT reading (`low=0` is absence-by-data-property, not absence-by-framework-gap); DRAFT rejected and deleted. PM deliberation preserved in synthesis §5.2 + §6. **Synthesis report** at `docs/planning/epics/E03-confidence-calibration-synthesis.md` (~360 lines) is the durable audit record — lives outside `docs/planning/epics/E03-confidence-findings/` so it survives the S03.12 working-notes deletion. **F12 retrofits** to 4 prior working notes (S03.3 / S03.4 / S03.6 / S03.6.1) make the audit reproducible. **One new pitfall** in `.roughly/known-pitfalls.md`: "Deferred open-question verdicts require an amendment-pending breadcrumb in `docs/open-questions.md`" (generalizable, applies to future M2 audits). **Four generalizable lessons** in synthesis: (1) deferred-audit breadcrumb requirement; (2) anti-circularity discipline (derive `framework_predicted` from F12 inputs INDEPENDENTLY of artifact's pre-computed value); (3) scoped pass-rate calculations per ADR-017 §3 (don't roll different schema layers together); (4) PM does NOT modify active ADRs autonomously — DRAFT-file pattern is canonical. Test suite holds at **1128 + 2 skipped** (doc-only PR; no regression). 8 stale `docs/plans/` → `.roughly/plans/` references fixed as a separate sweep within the same PR.
- **Begin S03.12 (M1 UAT preparation + handoff to M2) — UNBLOCKED. Final M1 story.** Inherits a clean closure-state from S03.11: ADR-017 stands as-is; **M1 UAT criterion #8** ("ADR exists documenting Q11 confidence calibration") satisfied as-is; **no amendment-pending state** to carry into M1→M2 handoff. S03.12's deliverables: (a) run/observe the 8 PRD success-criteria UAT queries against Supabase (criteria #1-7 require the live regulation_record + jurisdiction_binding tables — this is where S03.10 T16's operator batch-run becomes the gating dependency for S03.12, not a standalone item); (b) `git rm -r docs/planning/epics/E03-confidence-findings/` per ADR-017 §6 + `.gitignore` update to prevent re-creation (synthesis report at `E03-confidence-calibration-synthesis.md` survives because it lives outside the deletion target); (c) M1→M2 handoff document at `docs/planning/handoffs/M1-to-M2-handoff.md` recording Q11=RESOLVED + Q19=pre-M2 blocker + Q18=M2-CO-trigger + the 5 S03.10 M2-deferred items + the 8 stale-reference fix pattern; (d) push the `m1` tag at the final commit. **S03.10 T16 live UAT folds into S03.12** as the prerequisite for criteria #1-7; the operator runbook is already in S03.10 working note.
- **T16 live-UAT operator runbook** (from S03.10 working note — required before any S03.10 binding writes hit prod): batch-run in order `load_state_boundary.py` (S03.0) → `load_regulation_records.py` (S03.6 + S03.6.1) → `load_seasons_and_licenses.py` (S03.7) → `load_draw_specs.py` (S03.8) → `load_reporting_obligations.py` (S03.9) → `load_jurisdiction_bindings.py --dry-run` then `load_jurisdiction_bindings.py` (S03.10). After live count is observed, narrow `_BINDING_COUNT_GUARD_BAND` to ±30% in a follow-up PR and update AC #1087 footnote. T16 does NOT gate S03.11 planning or S03.12 scoping.
- **Q19 is a pre-M2 blocker**: id text-PK UPSERT drift guard project-wide fix affects `_UPSERT_SEASON_DEFINITION_SQL` + `_UPSERT_LICENSE_TAG_SQL` + `_UPSERT_REPORTING_OBLIGATION_SQL`. Must land in a single PR before first year-over-year re-ingestion run. ADR required at resolution. Don't propagate the slug-encoded UPSERT pattern to new helpers without addressing Q19.
- **Two S03.12 UAT spot-check candidates from S03.6** (recorded in `S03.6.md`): (a) identify the 2 elk HDs with `confidence=high` (2 of 112; verify strict extraction matched); (b) audit the single pronghorn HD with `confidence=medium` (1 of 31; identify the source row that dragged MIN aggregation down). No HIGH→LOW or MEDIUM→LOW demotions surfaced; correction-touched bear rows all medium per ADR-017 §4 demote-one-tier passing through MIN aggregation unchanged.
- **S03.12 UAT canned query from S03.7** (recorded in `S03.7.md`): query HD 170 elk's `license_season` rows post-jurisdiction_binding to demonstrate A-vs-B asymmetric coverage end-to-end.
- **S03.5 → S03.4 inherit from S03.3** (recorded in epic): per-row `season_windows` (no section-level aggregation); column-faithful row construction; deep-copy when emitting multiple sections from one source block; every cleanup rule applied to row cells must appear in the module-level docstring (AC #338 strict pattern); fail-loud at every "could-be-silent-data-loss" guard. **S03.5 added the column-crop discipline:** column-crop x-extents must be wide enough that heading anchor phrases aren't truncated mid-word — verify pre-implementation by sampling text at column-right-edge for known heading patterns.
- **S03.7+ inputs (carry forward from S03.3 + S03.4 + S03.5):** (a) per-row `page_reference` is section-starting-page in S03.3 (deferred per-row accuracy); (b) row-level `weapon_types` defaults to `["any_legal_weapon"]` in S03.3 (refine after S03.7 review); (c) row-level (not cell-level) source attribution in S03.4 / S03.5 (cell-level deferred to M2 per ADR-019). S03.7 also inherits the OQ7 row-count guard pattern from S03.6.
- **S03.7 inputs from S03.3 + S03.4 (pattern locked):** A/B asymmetric `season_coverage` in S03.3 = load-bearing for `license_season` link-table writes (143 HDs exhibit). S03.4 closure-prose populates `season_definition.closure_predicate` jsonb on 8 quota-closure + 4 female-sub-quota BMUs (per S03.4's confirmed 8-not-9 count). FK target: the 436 `regulation_record` rows just landed by S03.6.
- **S03.8 inputs from S03.3 (post-fix, locked):** STATEWIDE 900-20 row's `quota_range="1-7,500"` (comma kept), `license_code="Antelope License: 900-20"` (prefix kept), `quota=5600`, `weapon_types=["archery"]`, `season_coverage.general=true` (column-faithful). V1 antelope `draw_spec` input.
- **S03.9 inputs from S03.4:** 3 candidate `reporting_obligation` rows from page-7 prose (STATEWIDE 48-hour, R1 10-day tooth, R2-7 10-day hide/skull). Original spec said 2; revised to 3 per UAT.
- **S03.10 inputs from S03.4 + S03.5:** `hd_region` per BMU row (R1-R7) drives the R1 vs R2-7 reporting_obligation linkage. Region 7 portions from S03.3 carry directional qualifiers ("North of the Yellowstone River") that S03.10 must decide whether to bind geometrically. From S03.5: 55 `portion` rows + 54 `restricted_area` rows in `unlinked` need M1-binding strategy decisions (whether to bind at portion-level or HD-level).
- After S03.7: S03.8-S03.9 (draw_spec, reporting_obligation) → binding generation in S03.10 → calibration audit in S03.11 → M1 UAT in S03.12.
- The `m1` tag pushes at S03.12's final commit, alongside `git rm -r docs/planning/epics/E03-confidence-findings/` per ADR-017's working-notes deletion policy. `closure-temporal-anchors.md` and any other ADR-candidate notes in `E03-deferred-items/` survive past m1.

---

## Epic Files

- [M0 — Scaffold](epics/completed/M0-scaffold.md)
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/E01-schema-migrations.md)
- [E02 — Montana Geometry Ingestion](epics/completed/E02-geometry-ingestion.md)
- [E03 — Montana Regulation Text Ingestion](epics/E03-regulation-text-ingestion.md)
