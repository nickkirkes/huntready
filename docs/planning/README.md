# HuntReady — Planning Index

**Last Updated:** 2026-05-16
**Current Milestone:** M1 — Montana Ingestion (E01 + E02 complete; E03 active — 8/13 stories complete: S03.0-S03.6 (see history) + S03.7 season_definition+license_tag+license_season ingestion (closed 2026-05-16; M1 success criterion #2 satisfied at data layer; 8542 entity/link rows + 20 closure_predicates; Q16 species-granularity revisit deferred to M2))
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
| E03 | Montana Regulation Text Ingestion | In Progress (8/13 stories complete; S03.7 closed 2026-05-16 — M1 success criterion #2 data-layer satisfied) | 2026-05-03 | — | 13 |

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
- **S03.7 closed 2026-05-16** via PR `20db0fc` (5 commits past S03.6). **M1 success criterion #2 satisfied at the data layer.** Final state: 978 season_definition + 1225 license_tag + 3040 license_season + 1385 regulation_season + 1914 regulation_license = **8542 entity/link rows + 20 closure_predicate jsonb values** in one atomic transaction. Inherits OQ7 row-count guard precedent (5 guards fire pre-`db.connect()` with ±30% bands). **Eleven OQ-S7-1 through OQ-S7-11 decisions baked in** + 2 cubic-fix decisions (DEA builders gate on season_coverage truth; `_license_code_slug` prefixes by license type to resolve 6 cross-listing collisions). **Spec change accepted**: OQ-S7-3 shifts the UAT HD from spec's HD 262 elk to live-data HD 170 elk (Flathead River) — A covers `{archery_only, general, heritage_muzzleloader}`, B covers `{archery_only, general, late}`; A-only=`{heritage_muzzleloader}`, B-only=`{late}`. End-to-end SQL spot-check deferred to S03.12 post-jurisdiction_binding (canned query in working note). **PM applied 3 surgical mypy fixes during closure verification** (loop-variable type pollution; `key` shadowing; `weapon_type` `str | None` not narrowed to `WeaponType | None`); agent's "ruff + mypy clean" claim was wrong — discipline reminder filed for future closures. Five new pitfalls in `.roughly/known-pitfalls.md`. Test suite: **832 + 2 skipped** (+121 net + 2 cubic-fix tests from S03.7).
- **Q16 added to `docs/open-questions.md`** — species granularity revisit (S03.7 → M2). If any state ever ships a species-specific license (mule-deer-only with no whitetail), V1's shared `license_tag` wouldn't fit. M2 decides among per-species variants, `valid_species: list[str]` column, or hybrid.
- **Begin S03.8 (draw_spec ingestion) — UNBLOCKED.** Writes one `draw_spec` row per limited-draw `license_tag` from S03.7 except `900-20` (per Q5/Q12 deferral). Backfills `license_tag.draw_spec_key` via `UPDATE license_tag SET draw_spec_key = ? WHERE id = ?` after the `draw_spec` rows are written. Inherits OQ7 row-count guards. Flag-and-defer protocol for any draw mechanic that would require the `parameters` field (per Q12). hunt_code uses the DEA `license_code` per spec line 734.
- **S03.9 (reporting_obligation ingestion)** can begin in parallel with S03.8 once you choose — Bear artifact's 3 reporting_obligation candidates (R1 / R2-7 / STATEWIDE) are ready to consume; FK target rows (regulation_record) present from S03.6.
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
