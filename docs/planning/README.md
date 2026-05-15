# HuntReady — Planning Index

**Last Updated:** 2026-05-15
**Current Milestone:** M1 — Montana Ingestion (E01 + E02 complete; E03 active — 7/13 stories complete: S03.0 schema, S03.1 PDF fetch, S03.2 PDF extraction primitives, S03.3 DEA booklet, S03.4 Black Bear booklet + correction, S03.5 Legal Descriptions extraction, S03.6 regulation_record + geometry.legal_description ingestion (closed 2026-05-15; 436 regulation_record rows + 228 legal_description writes; OQ1 + OQ7 resolved))
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
| E03 | Montana Regulation Text Ingestion | In Progress (7/13 stories complete; S03.6 closed 2026-05-15 — first DB-write story; OQ1+OQ7 resolved) | 2026-05-03 | — | 13 |

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
| S03.7 | season_definition + license_tag + license_season ingestion | Not Started | Implementation (UAT: yes) |
| S03.8 | draw_spec ingestion | Not Started | Implementation |
| S03.9 | reporting_obligation ingestion | Not Started | Implementation |
| S03.10 | jurisdiction_binding generation | Not Started | Implementation (UAT: yes) |
| S03.11 | Confidence calibration audit + ADR-017 finalization | Not Started | Implementation + PM |
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
- **S03.6 closed 2026-05-15** via PR `c0c1b77` (first E03 DB-write story). 436 regulation_record rows + 228 `geometry.legal_description` updates in one atomic transaction. **OQ1 resolved 2026-05-14** (recorded in `docs/open-questions.md` Q15): `regulation_record` has no `verbatim_rule` column; section text decomposes onto child entities at S03.7 (`season_definition.verbatim_rule` + `license_tag.verbatim_rule`); HD-wide `NOTE:` lines land in `regulation_record.additional_rules` at S03.6. Refinement of ADR-008's decomposition story; no new ADR. **OQ7 introduced**: row-count fail-loud guards (±30% band) — first pipeline story to do so; precedent for S03.7-S03.10 (regulation_record band `[359, 668]`; legal_description band `[159, 296]`). Eight real-data findings baked in: DEA species fan-out (`deer` → `mule_deer` + `whitetail`); Bear DB species_group is `bear` not artifact's `black_bear`; bear-path `ConfidenceTier(...)` validation; `_DEA_SPECIES_FANOUT` emit order locked by test; bear artifact `sources`/`rows` shape validation; DEA elk/mule_deer/whitetail + `hd_number="STATEWIDE"` structural fail-loud; `NOTE:` regex hardened from `\s*` → `[ \t]*`; `MT-STATEWIDE-antelope` is the single confirmed statewide regulation_record in V1. Seven new pitfalls in `.roughly/known-pitfalls.md`. Test suite: 709 + 2 skipped (+52 from S03.6).
- **Begin S03.7 (season_definition + license_tag + license_season ingestion) — UNBLOCKED. Load-bearing UAT-yes story for M1 success criterion #2** ("A and B licenses both cross-referencing the appropriate seasons"). Consumes the DEA + Black Bear artifacts (already produced); writes child entities whose FK target is the 436 `regulation_record` rows S03.6 just landed. Bear `season_definition` rows specifically need `closure_predicate` populated for the 8 quota-closure BMUs (411, 420, 440, 450, 510, 520, 600, 700 — BMU 530 absent from 2026 PDF per S03.4 decision) + 4 female-sub-quota BMUs (300, 301, 319, 580). Inherits OQ7 row-count guard precedent from S03.6.
- **Two S03.12 UAT spot-check candidates from S03.6** (recorded in `S03.6.md`): (a) identify the 2 elk HDs with `confidence=high` (2 of 112; verify strict extraction matched); (b) audit the single pronghorn HD with `confidence=medium` (1 of 31; identify the source row that dragged MIN aggregation down). No HIGH→LOW or MEDIUM→LOW demotions surfaced; correction-touched bear rows all medium per ADR-017 §4 demote-one-tier passing through MIN aggregation unchanged.
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
