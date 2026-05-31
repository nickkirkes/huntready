# HuntReady — Planning Index

**Last Updated:** 2026-05-31 (E05 planned + validated)
**Current Milestone:** M2 — Colorado Ingestion (In Progress; E04 Complete + Audited 2026-05-31 with 0 blocking findings; audit report at `epics/completed/E04-m1-carry-forward-audit.md`. **E05 (Colorado geometry ingestion) planned + validated 2026-05-31** — 8 stories drafted; E05 validation triad (Spatial Correctness + ArcGIS Fidelity + Schema Stress-Test) returned LAND-WITH-EDITS; 14 MUST-FIX + 9 SHOULD-FIX findings applied; epic at `epics/E05-colorado-geometry-ingestion.md`. Recommended first story: **S05.0 (Schema preparation — write `CO-STATEWIDE-geom`)** per merge order S05.0 → S05.1 → S05.2 → S05.3 → S05.4 → S05.5 → S05.6 → S05.7. E06 (regulation text) planned after E05's last story merges AND its post-implementation audit closes per the locked standard. **Post-implementation-audit standard**: per E02 + E04 precedent, each future epic closes with a post-implementation audit recorded under `docs/planning/epics/completed/E0X-audit.md` before `/plan-next-epic` is invoked for the following epic; PM refuses-and-flags any `/plan-next-epic` invocation where the prior epic's `Audited:` field is unpopulated). M1 closed 2026-05-27 with `m1` tag at PR #45 (`ccbe085`).
**Overall V1 Status:** 2/6 milestones complete; M2 active

---

## Milestone Status

| Milestone | Name | Status | Validated | Dependencies |
|---|---|---|---|---|
| M0 | Scaffold | Complete | 2026-04-22 | None |
| M1 | Montana Ingestion | Complete | 2026-05-27 | M0 |
| M2 | Colorado Ingestion | In Progress (E04 Complete + Audited 2026-05-31; **E05 In Progress** — planned + validated 2026-05-31 (8 stories; triad LAND-WITH-EDITS, findings applied); E06 awaits E05 audit) | 2026-05-29 (E04), 2026-05-31 (E05) | M1 |
| M3 | MCP Server | Not Started | — | M1 |
| M4 | Web Companion | Not Started | — | M3 |
| M5 | Claude Code Plugin | Not Started | — | M4 |

---

## Current Milestone: M2 — Colorado Ingestion

M2 delivers Colorado regulations into Supabase Postgres, validated against the same six-entity schema, covering five V1 species across all applicable Game Management Units (GMUs), CWD zones, and overlay geometries. Three sequential epics (PRD 002):

### Epic Status

| Epic | Name | Status | Validated | Completed | Stories |
|---|---|---|---|---|---|
| E04 | M1 Carry-Forward and Colorado Schema Preparation | **Complete (audited) 2026-05-31** (5 of 5 stories closed across 5 calendar days; post-implementation audit closed same day at PR #52 / `b168d28` — 49 ACs reviewed, 47 MET + 2 operator-asserted + 0 NOT MET + 0 blocking findings; single actionable finding [S04.1 migration header `public.`-qualifier rationale] resolved at `7478ea6` as comment-only header edit, zero DDL impact; audit report at `epics/completed/E04-m1-carry-forward-audit.md`) | 2026-05-29 | 2026-05-31 | 5 (S04.6 evaluated and omitted) |
| E05 | Colorado Geometry Ingestion | **In Progress** (planned + validated 2026-05-31; 8 stories drafted; triad LAND-WITH-EDITS; 14 MUST-FIX + 9 SHOULD-FIX findings applied) | 2026-05-31 | — | 8 (S05.0–S05.7) |
| E06 | Colorado Regulation Text Ingestion | Not Started, planned later (gated by E05 audit per locked post-implementation-audit standard) | — | — | — |

### E04 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S04.1 | license_season RLS migration | **Fully Closed 2026-05-30** (Group A satisfied at-merge; Group B closed via live verification later same day — all 4 queries returned expected shape against the production project; Q4's 2411 vs. the prompt's "~3040" was the post-UPSERT-collapse DB baseline per S04.4 spec L280, not a leak; verbatim outputs captured in E04 epic § "Group B verification record — 2026-05-30"); migration `supabase/migrations/20260530132727_rls_license_season.sql` | Implementation |
| S04.2 | Narrow _BINDING_COUNT_GUARD_BAND to (552, 1024) — **first M2 PR per handoff §8** | Complete (squash-merged to main 2026-05-29; chronology lock satisfied; test baseline shifted 1165 → 1166 via new `TestCountGuard::test_band_locked_to_t16_empirical` contract-lock test; 4 post-merge cubic-fix iterations; 3 new pitfalls under `.roughly/known-pitfalls.md`) | Implementation |
| S04.3 | Add logging.basicConfig to load_jurisdiction_bindings.py main() | **Closed 2026-05-30** (PR #49 / `5de83c3`; third M2 PR chronologically; 4-line multi-line `basicConfig` at `load_jurisdiction_bindings.py:785-788`; `--dry-run` now emits 25 INFO lines including `TOTAL: 788 bindings` re-confirming S04.2's empirical 788; test suite stable at 1166 + 2 skipped, no delta) | Implementation |
| S04.4 | M1 UAT runbook hygiene fixes (six edits + mandatory 7th annotation + PM-approved adopted 7th row for jurisdiction_binding build-vs-DB) | **Closed 2026-05-30** (fourth M2 PR; 4-commit chain — impl + plan-marker + §6 audit-trail-preamble cubic P1 review-fix + T4/T5 plan-dep P3 fixes; 7 prescribed edits + 4 Stage-6 review-fix corrections + 1 user-approved AC-interpretation override; draw_spec 278-vs-276 provenance reconciled per S03.8 closure authoritative; 3 pitfall candidates surfaced for user decision; test suite stable at 1166 + 2 skipped, zero delta) | Implementation |
| S04.5 | PRD 001 sequencing language reconciliation (PM drafts diff; human applies) | **Closed 2026-05-31** (5-commit chain via `/roughly:build` under user's git identity: `bf9bfa9` PRD 001 lines 90/96/111 + `3445017` Bundle A pitfalls + `37bc86a` Bundle B handoff hygiene + `91bde52` plan-marker + `eb803db` cubic sentence-initial-capitalization fix-up; PM-judgment override accepted for the `/roughly:build` delegation as satisfying the no-autonomous-PRD-edit intent — user-initiated delegation under user's git identity is explicit human control) | PM + Human (delegated via `/roughly:build`) |

**E04 merge order is hard-locked:** S04.2 → S04.1 → S04.3 → S04.4 → S04.5 (S04.2-first per handoff §8 sixth bullet; S04.1-before-S04.4 because S04.4's mandatory criterion #7 sign-off annotation references S04.1's migration timestamp). See E04 epic §"Parallelization Notes" for the precondition details.

### E05 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S05.0 | Schema preparation — write `CO-STATEWIDE-geom` | Not Started | Implementation |
| S05.1 | CPW ArcGIS fetch infrastructure + Colorado adapter scaffold | Not Started | Implementation |
| S05.2 | GMU ingestion (CPW FeatureServer layer 6, ~186 polygons) | Not Started | Implementation |
| S05.3 | CWD zone discovery + ingestion (Q18 trigger surfaces here) | Not Started (UAT: yes) | Implementation |
| S05.4 | Restricted-area / no-hunt-zone overlay discovery + ingestion (`role='no_hunt_zone'` ADR-trigger surfaces here) | Not Started (prerequisite: `docs/research/colorado-restricted-areas-evaluation.md`) | Implementation + Human/Research session |
| S05.5 | `geometry-overlays.json` fixture build (CO analog; library extension state-agnostic-clean) | Not Started (UAT: yes) | Implementation |
| S05.6 | Cross-state spatial discipline + binding-loader reference (`_STATE = 'US-CO'`) | Not Started | Implementation |
| S05.7 | Spatial query verification + epic exit (UAT + audit gate for `/plan-next-epic`-to-E06) | Not Started (UAT: yes) | Implementation |

**E05 merge order**: S05.0 → S05.1 → S05.2 → S05.3 → S05.4 → S05.5 → S05.6 → S05.7. S05.3 and S05.4 are technically parallelizable but the convention is sequential; S05.4 has a research-doc prerequisite at `docs/research/colorado-restricted-areas-evaluation.md` that must be drafted (by human or research session, NOT autonomously by PM) before S05.4 implementation can open.

E05 and E06 are planned later via `/plan-next-epic` once E04's last story merges. PRD 002 §"Why sequential" — only the E06→E05 dependency is FK-hard; the other orderings are operator-discipline ordering.

---

## Past Milestone: M1 — Montana Ingestion (Complete 2026-05-27)

M1 delivered Montana regulations into Supabase Postgres, validated against the six-entity schema, covering five V1 species across all applicable jurisdictions. Three sequential epics:

### M1 Epic Status

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

None. M2 E04 fully closed S04.1 on 2026-05-30 — Group A satisfied at merge (PR #48 squash from `feat/S04.1-license-season-rls-migration`) and Group B closed via live verification later same day. All four verification queries against the production Supabase project returned the expected shape (Q1: 0 info-schema privileges for anon/authenticated; Q2: 2 deny-all policies attached, byte-exact policy names; Q3: `relrowsecurity` + `relforcerowsecurity` both true; Q4: 2411 rows preserved — the post-UPSERT-collapse DB baseline per S04.4 spec § "Expected counts" L280, not the ~3040 build count from handoff §3 which the verification prompt had cited in error). Verbatim outputs locked in `docs/planning/epics/completed/E04-m1-carry-forward.md` § "Group B verification record — 2026-05-30". The M1 UAT criterion #7 leak surface (14 privilege leaks + 0 RLS policies on `license_season` confirmed at M1 UAT 2026-05-28) is now structurally closed in production. **Discipline note for future Group B-style verification prompts**: cite the post-UPSERT DB baseline (S04.4 spec L280 is the durable source-of-truth) not the build count from handoff §3 — recommended a future implementation agent land as a one-line entry in `.roughly/known-pitfalls.md`; PM does not touch `.roughly/` autonomously.

**E04 closed 2026-05-31.** All 5 E04 stories shipped across 5 calendar days (2026-05-29 → 2026-05-31). The two parallel housekeeping bundles surfaced through S04.4 closure both co-landed at S04.5 close via the same `/roughly:build` session: Bundle A (2 of 3 surfaced pitfall candidates landed; 3rd deliberately excluded as operational reality of cubic per PM judgment); Bundle B (all 5 accumulated handoff hygiene candidates landed). The M1→M2 handoff is now self-consistent at §3 (build-vs-DB clarifying preamble pointing at runbook footnote `[^10]`), §8 #4 (draw_spec 276→278; jurisdiction_binding row added), and §8 #7 (RESOLVED annotation). The recurring-RLS-gap M2 open-question candidate (E04 §"Known Issues to Escalate" #1) remains unchanged in scope — none of the five E04 stories needed to resolve it; it persists as a flag for the human to land via event-trigger migration, CI check, or discipline-only mitigation path.

**Active work-front: E05 (Colorado geometry ingestion).** Planned + validated 2026-05-31. Epic at `epics/E05-colorado-geometry-ingestion.md`. **Recommended first story: S05.0** (write `CO-STATEWIDE-geom` per merge order S05.0 → S05.1 → S05.2 → S05.3 → S05.4 → S05.5 → S05.6 → S05.7). E06 planned later via `/plan-next-epic` after E05's audit closes.

**E05 validation triad summary**: Spatial Correctness + ArcGIS Fidelity + Schema Stress-Test all returned LAND-WITH-EDITS; 14 MUST-FIX + 9 SHOULD-FIX findings applied across the 8 stories. One cross-reviewer conflict resolved (Spatial vs. ArcGIS Fidelity on the CO coord-range check — ArcGIS Fidelity won; the shared library check is global WGS84, not state-parameterized; CO-bounds-specific check moved to S05.7's analytical layer). See E05 epic §"Validation triad notes" for details.

**Pre-S05.4 prerequisite (PM-flagged)**: S05.4 (restricted-area / no-hunt-zone overlay discovery) requires a research-doc prerequisite at `docs/research/colorado-restricted-areas-evaluation.md` modeled on `gmu-source-evaluation.md`. The PM cannot draft research docs autonomously per the no-autonomous-research-doc rule (research docs are user/research-session territory). Surface to the user to draft before S05.4 implementation can open. S05.0 + S05.1 + S05.2 + S05.3 are independent and can proceed in the meantime per the recommended merge order.

**Recurring-RLS-gap M2 open-question candidate** (E04 §"Known Issues to Escalate" #1) — **does NOT fire for E05**: none of the 8 E05 stories add a new public-schema table. The gap persists for any future M2/M3 work that does add a table; user-side mitigation decision (event-trigger migration / CI check / discipline-only) remains pending and is independent of the E05 critical path.

**Post-implementation-audit standard for E05+** (locked at E04 audit close): the E05 epic file carries explicit Exit Criterion gating `/plan-next-epic` for E06 on E05's audit-artifact existence under `epics/completed/E05-audit.md` with a populated `Audited:` field on the E05 header. Same pattern for E06 and beyond. The PM will refuse-and-flag any `/plan-next-epic` invocation where the prior epic's audit is unrecorded — no silent skip.

**M2 open-question candidate surfaced at E04 close**: the base RLS migration `20260425000001_rls_deny_all.sql` uses a flat per-table IN-list that does not auto-extend to subsequently-added tables — the same pattern that produced the M1 `license_season` gap S04.1 closes. Any future migration in M2 / M3 that adds a new `public.*` table will silently inherit the gap unless its inline RLS block is included in the same migration. Surfaced to user via E04 § "Known Issues to Escalate" for decision on mitigation path (event-trigger migration / CI check / discipline-only). PRD 002 §"Decisions already made" already encodes the discipline-only mitigation; the recurring-gap risk is whether to harden further.

See [`docs/planning/handoffs/M1-to-M2-handoff.md`](handoffs/M1-to-M2-handoff.md) § "Known issues to escalate" for the full M1 carry-forward list (all items mapped into E04 or flagged-and-carried per E04 § "Known Issues to Escalate").

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
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/completed/E01-schema-migrations.md)
- [E02 — Montana Geometry Ingestion](epics/completed/E02-geometry-ingestion.md)
- [E03 — Montana Regulation Text Ingestion](epics/completed/E03-regulation-text-ingestion.md)
- [E04 — M1 Carry-Forward and Colorado Schema Preparation](epics/completed/E04-m1-carry-forward.md)
- [E05 — Colorado Geometry Ingestion](epics/E05-colorado-geometry-ingestion.md)
- E06 — Colorado Regulation Text Ingestion (planned later via `/plan-next-epic` after E05 audit)
