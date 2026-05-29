# HuntReady — Planning Index

**Last Updated:** 2026-05-27
**Current Milestone:** M1 — Montana Ingestion (Complete; all 3 epics closed; m1 tag ready to push). M2 — Colorado Ingestion is next.
**Overall V1 Status:** 2/6 milestones complete

---

## Milestone Status

| Milestone | Name | Status | Validated | Dependencies |
|---|---|---|---|---|
| M0 | Scaffold | Complete | 2026-04-22 | None |
| M1 | Montana Ingestion | Complete | 2026-05-27 | M0 |
| M2 | Colorado Ingestion | Up Next | — | M1 |
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
| E03 | Montana Regulation Text Ingestion | Complete | 2026-05-03 | 2026-05-27 | 14 (13 original + S03.6.1) |

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
| S03.12 | M1 UAT preparation + handoff to M2 | Complete (closed 2026-05-27; M1 UAT runbook at `docs/runbooks/M1-uat.md` + M1→M2 handoff at `docs/planning/handoffs/M1-to-M2-handoff.md`; working notes deleted per ADR-017 §6; synthesis report survives; m1 tag ready for user push) | Implementation + PM |

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

None. M1 closed 2026-05-27. M2 (Colorado) kickoff queued.

**Pre-M2 blocker (Q19) — RESOLVED 2026-05-29** via PR #45 (`ccbe085`) per [ADR-020 (Accepted)](../adrs/ADR-020-id-text-pk-slug-derivation.md). New shared module `ingestion/ingestion/lib/drift_guard.py` ships `assert_dispatch_dict_drift_free` (compile-time S03.9 case) + `assert_id_matches` (runtime S03.7 case). The 3 SQL constants in `db.py` are unchanged — the assert lives at the dispatch-dict / row-construction layer. **M2 adapters writing to `season_definition`, `license_tag`, or `reporting_obligation` MUST adopt the pattern.** Test suite 1128 → 1165 + 2 skipped.

See [`docs/planning/handoffs/M1-to-M2-handoff.md`](handoffs/M1-to-M2-handoff.md) § "Known issues to escalate" for the full carry-forward list.

---

## Next Actions

- **S03.4 closed 2026-05-12.** PR `ab09e82` squash-merged to main; 35 BMU rows + 2 closures + 3 reporting obligations in `black-bear-2026.json`. UAT cleared (4 BMUs spot-checked against `pdfplumber`-extracted source: BMU 411 quota-closure+female-subquota; BMU 300 Spring Closure; BMU 100 unrestricted; BMU 700 quota-closure). Three spec corrections accepted: (a) AC #428 9→8 quota-closure BMUs (BMU 530 absent from 2026 PDF); (b) AC #429 2→3 reporting obligations (statewide 48-hour mandatory reporting is distinct from R1/R2-7 inspection); (c) AC #430-431 **Option B (doc-type precedence)** replaces spec's MAX-date Option A (booklet Last-Modified 2026-04-27 post-dates correction 2026-03-18, so Option A would silently no-op). 35 BMU rows all confidence=medium (HIGH→MEDIUM demote via correction-touched single demote-one-tier per row). 12 real-PDF discoveries documented in closure note; 8 new pitfalls in `.roughly/known-pitfalls.md`. Test suite: 574 passed + 2 skipped.
- **ADR-019 accepted 2026-05-12** at [`docs/adrs/ADR-019-doc-type-precedence-multi-source-merge.md`](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md). Formalizes the doc-type-precedence rule (`correction` > `annual_regulations`) for all future state adapters. PRD 001 R5 wording reconciliation deferred to the next PM-led PRD review pass or before E04 planning, whichever comes first. The ADR's V1 rank table is exhaustive within the regulation-text merge path: a `rule_change` or `emergency_order` source attempting to participate fails loud at merge time, and adding a rank for either requires an ADR amendment first. `gis_layer` is structurally outside regulation-text merges (it's the geometry-source doc-type per ADR-014) and the rule doesn't apply.
- **S03.5 closed 2026-05-14** via PR `b2ad20b` (10 commits `ece1ab1..e96a195`). Initial implementation surfaced through PM-run review identified 1 P1 (verbatim spillage — column-crop x-range too narrow at 145pt for col 2, truncating "Those portions" → "Those portio" and defeating the regex anchor; bear-319 absorbed 4 subsequent HDs reaching 8059 chars vs 855 median) + 5 P2 findings (S03.5.md count, footer crop 20pt→50pt, plan unlinked-scope contradiction, plan HeadedBlock.kind missing "continuation", CWD canonicalize before consolidation). Agent applied all 6 fixes in 9 follow-up commits before merge; matched count rose 156 → 228 across the cycle and bleed cases dropped 35 → 0. Final artifact: 228 matched (226 HD + 2 CWD) / 31 by-design unmatched / 119 unlinked (full 347-row V1 surface accounted for); regression rate 0.000. Seven new pdfplumber pitfalls in `.roughly/known-pitfalls.md`. Test suite: 657 + 2 skipped (+83 from S03.5). PM UAT spot-check 2026-05-14 on 2 descriptions (HD 100 + Libby CWD) faithful to source.
- **S03.9 closed 2026-05-21** via PR `195ac8b` (squash of 8 pre-squash commits: 1 main implementation + 7 cubic-review fix-up rounds). Final state: **3 reporting_obligation rows (STATEWIDE harvest_report 48hr + R1 tooth_submission 10-day + R2-7 hide_skull_presentation 10-day) + 70 regulation_reporting link rows (35 STATEWIDE + 14 R1 + 21 R2-7)** in one atomic transaction. **Three substantive scope evolutions via the 2026-05-19 source-audit probe** (Three-Blocker discovery): (a) **CWD sampling deferred to Q18** — verbatim text already in `regulation_record.additional_rules` from S03.6; license-keyed pattern means zone-keyed `geometry-overlays.json` join would miss the `Deer Permit: 103-50` case. (b) **Bear ID coursework carved out to S03.6.1** — pre-purchase licensing prerequisite belongs in `regulation_record.additional_rules` via new `MT-STATEWIDE-bear` anchor (mirrors `MT-STATEWIDE-antelope` pattern), NOT in `reporting_obligation` which is post-harvest/in-season only. (c) **Epic line 807 corrected (PM-approved)** — "general reporting obligation for all V1 species" assumption removed; bear is the only V1 species with a statewide mandatory harvest report per FWP authoritative list (bear/wolf/marten/swans). **Two new open questions** in `docs/open-questions.md`: **Q18** (CWD sampling target-table modeling; M2 ADR-candidate when Colorado lands) and **Q19** (id text-PK UPSERT drift; **pre-M2 blocker**; affects 3 helpers in `db.py`; ADR required at resolution; leading option is derive-and-assert generalizing S03.9's local pattern). **Three new patterns for S03.6.1/S03.10+**: (1) OQ7 row-count guard is the canonical count authority (in-builder exact-count checks contradict band semantics — remove; build = data construction); (2) defensive fail-loud surface for artifact-list iterations (`isinstance` type-check BEFORE key access; try/except KeyError → RuntimeError wrapping; per-element diagnostics + duplicate-id guards); (3) `reporting_obligation.kind` semantic boundary — post-harvest/in-season only; pre-purchase prerequisites go in `regulation_record.additional_rules`. **Four new pitfalls** in `.roughly/known-pitfalls.md` (source-audit upstream artifacts before planning; kind semantic boundary; submission_method multi-modal interpretation; id-text-PK UPSERT drift). **7 cubic-review rounds during PR review** added 18 tests + the 4th pitfall; pre-merge test count was 963 (main commit), post-merge is **981 + 2 skipped**. **`cwd-sampling-modeling.md` added** to `docs/planning/epics/E03-deferred-items/` (survives past m1).
- **S03.6.1 closed 2026-05-22** via PR `339e213` (squash-merged from `feat/S03.6.1-mt-statewide-bear-anchor`). Final state: **437 regulation_record (+1) + 1 jurisdiction_binding (first ever written)** in one atomic transaction. **Four PM decisions baked in (OQ-S6.1-1 through OQ-S6.1-4)**: (1) artifact shape `list[StatewideRuleCandidate]` for M2 extensibility; (2) `rule_hint` as `str` (not Literal) for cross-state extensibility; (3) no `NOTE:` prefix on text — raw verbatim per ADR-008; (4) `db.upsert_jurisdiction_binding`'s UPDATE clause excludes 6 identity-encoded fields — silent-repoint protection refining ADR-018 binding semantics. **12 cubic-review cycles + Stage 6 triad** during PR review (review history catalogued in closure note). **Artifact SHA-256 stable across the entire cycle.** Test suite: **1024 + 2 skipped** (+43 net from S03.6.1).
- **S03.10 code-complete 2026-05-26** via PR `e83ef2d` (squash-merged from `feat/S03.10-jurisdiction-binding-generation`; 8 pre-squash commits: 1 main impl + 7 review-driven fixes). First **cross-cutting** binding loader (`ingestion/states/montana/load_jurisdiction_bindings.py` ~870 LOC). Reads `geometry-overlays.json` × regulation_record cross product, applies per-species filtering, walks 4 binding sources (statewide / overlay self-row / overlay portions / no-hunt-zone Option A), UPSERTs in one atomic three-phase transaction via `db.upsert_jurisdiction_binding` reused from S03.6.1 (no `db.py` changes — read SELECTs live in the adapter per S03.10 constraint #7). **T16 live UAT operator-pending** — regulation_record table empty at T0 probe; requires batch run of S03.0/S03.6/S03.6.1/S03.7/S03.8/S03.9 before binding writes can occur. Projected ~1000 bindings (2 statewide + ~940 overlay + ~59 no-hunt-zone) inside `[400, 1100]` guard band. **Four PM-approved spec deviations** footnoted in epic (L1045/L1070/L1092/L1311+L1313): (1) id format imports `_JURISDICTION_BINDING_ID_FORMAT` from S03.6.1's locked constant — bear binding UPSERTs as no-op; (2) count band `[400, 1100]` (spec's 1,500-3,500 was 2x too high); (3) source attribution via adapter-local SELECT against `geometry.source` (no new `db.py` helper); (4) no-hunt-zone "nearby" rule simplified to single-clause `extensions.ST_DWithin(zone.geom, hd.geom, 5000)` on native geography (boundary-to-boundary; spec's two-clause centroid-based rule returned 0 matches for all 3 orphans). **18 fail-loud guards** added across review-triad + 4 PR-review rounds. **7 new pitfalls** in `.roughly/known-pitfalls.md` (3 PostGIS/Supabase + 4 ingestion-adapter conventions). **Q19 NOT propagated to this module** — `db.upsert_jurisdiction_binding` already excludes identity fields from UPDATE (stronger mitigation than the 3 Q19-affected helpers); Q19 remains a pre-M2 blocker for those 3. **Test suite: 1128 + 2 skipped** (+104 net from S03.10). **5 M2-deferred items recorded:** `role='no_hunt_zone'` enum candidate; portion-keyed reg_records (3 coordinated touchpoints); Colorado adapter must filter `_STATE='US-CO'`; count band narrowing after T16; multi-source geometry provenance schema.
- **S03.11 closed 2026-05-27** via PR #42 (squash-merged as `b84955c`, on main at merge commit `7021bda`). **Verdict: FINALIZE.** ADR-017 active file unmodified (status remains `Accepted`; all 7 numbered sections untouched). **Q11 RESOLVED** in `docs/open-questions.md`. Audit shape: 50-row stratified sample × 10 documented edge cases (artifact-based per S03.10 T0 probe finding `regulation_record` empty); 50/50 = 100% pass-rate scoped per ADR-017 §3 (regulation_record.confidence 39/39 + EC8 parent-inheritance 6/6 + EC9 license_tag row-level 5/5). Tier distribution across projected 437 regulation_record rows: `high=32 medium=405 low=0`. **Defer-or-finalize arc**: PM recommended PARTIAL DEFER under LITERAL reading of Trigger 2 (`low=0` literally fires); `roughly:epic-reviewer` returned LAND-WITH-EDITS on PM's DRAFT; PM applied 4 refinements; user overrode to FINALIZE under INTENT reading (`low=0` is absence-by-data-property, not absence-by-framework-gap); DRAFT rejected and deleted. PM deliberation preserved in synthesis §5.2 + §6. **Synthesis report** at `docs/planning/epics/E03-confidence-calibration-synthesis.md` (~360 lines) is the durable audit record — lives outside `docs/planning/epics/E03-confidence-findings/` so it survives the S03.12 working-notes deletion. **F12 retrofits** to 4 prior working notes (S03.3 / S03.4 / S03.6 / S03.6.1) make the audit reproducible. **One new pitfall** in `.roughly/known-pitfalls.md`: "Deferred open-question verdicts require an amendment-pending breadcrumb in `docs/open-questions.md`" (generalizable, applies to future M2 audits). **Four generalizable lessons** in synthesis: (1) deferred-audit breadcrumb requirement; (2) anti-circularity discipline (derive `framework_predicted` from F12 inputs INDEPENDENTLY of artifact's pre-computed value); (3) scoped pass-rate calculations per ADR-017 §3 (don't roll different schema layers together); (4) PM does NOT modify active ADRs autonomously — DRAFT-file pattern is canonical. Test suite holds at **1128 + 2 skipped** (doc-only PR; no regression). 8 stale `docs/plans/` → `.roughly/plans/` references fixed as a separate sweep within the same PR.
- **S03.12 closed 2026-05-27 — M1 milestone complete.** Final M1 story shipped: `docs/runbooks/M1-uat.md` (operator UAT runbook with 8 SQL query blocks per PRD success criteria + operator batch-run sequence extracted from S03.10 working note before deletion); `docs/planning/handoffs/M1-to-M2-handoff.md` (M2 inheritance + Q11 RESOLVED + Q19 pre-M2 blocker + 4 deferred-items files + 7 known issues for escalation); `docs/planning/epics/E03-confidence-findings/` deleted per ADR-017 §6 with `.gitignore` update; CLAUDE.md + this README + CHANGELOG updated to reflect M1 closure. Synthesis report at `docs/planning/epics/E03-confidence-calibration-synthesis.md` survives (lives outside deletion target). S03.10 T16 live UAT folded into M1 UAT runbook as operator-prerequisite batch run. PM hands off to user for the `git tag m1` push. 6 PRD-vs-actual deviations footnoted in `M1-uat.md` (jurisdiction_code format; no `verbatim_text` column; HD 170 substituted for HD 262; no `make ingest STATE=montana` target; `license_season` RLS gap; ADR-017 unmodified satisfies criterion #8). Test suite holds at 1128 + 2 skipped (doc-only PR).

---

## Epic Files

- [M0 — Scaffold](epics/completed/M0-scaffold.md)
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/E01-schema-migrations.md)
- [E02 — Montana Geometry Ingestion](epics/completed/E02-geometry-ingestion.md)
- [E03 — Montana Regulation Text Ingestion](epics/E03-regulation-text-ingestion.md)
