# HuntReady — Planning Index

**Last Updated:** 2026-05-08
**Current Milestone:** M1 — Montana Ingestion (E01 + E02 complete; E03 active — 4/13 stories complete: S03.0 schema, S03.1 PDF fetch, S03.2 PDF extraction primitives, S03.3 DEA booklet extraction (UAT pending))
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
| E03 | Montana Regulation Text Ingestion | In Progress (4/13 stories complete; S03.3 UAT pending) | 2026-05-03 | — | 13 |

### E03 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S03.0 | Schema preparation — license_season + geometry.legal_description + geometry.kind='state' + Montana state geometry | Complete | Implementation |
| S03.1 | PDF fetch infrastructure | Complete | Implementation |
| S03.2 | PDF extraction primitives (shared library) | Complete | Implementation |
| S03.3 | DEA booklet extraction (deer, elk, antelope) | Complete (code); UAT pending operator review | Implementation (UAT: yes) |
| S03.4 | Black Bear booklet extraction + correction PDF handling | Not Started | Implementation (UAT: yes) |
| S03.5 | Legal Descriptions extraction | Not Started | Implementation (UAT: yes) |
| S03.6 | regulation_record ingestion | Not Started | Implementation |
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

- **S03.3 code complete 2026-05-08; UAT pending.** Branch `feat/S03.3-dea-booklet-extraction`, 12 commits, cleared PR review. Artifact `dea-2026.json` (264 sections / 1178 rows / perfect 50/50 high-medium confidence split) plus all 4 first-fetch manifests committed in `7b1ec54`. Real-PDF discovery cycle surfaced 9 deviations from spec research notes — see closure note in epic. Three new pitfalls in `.roughly/known-pitfalls.md` under Integration — pdfplumber. **AC #342 (UAT faithfulness) is the single remaining open AC** — operator-owned; does NOT gate downstream stories. Recommended UAT candidates per `S03.3.md` working note: deer HD 124 Arvilla (p48), elk HD 170 Flathead River (p49), antelope HD 690 South Hill (p138), STATEWIDE 900-20 (p136).
- **PM/operator owns: Run S03.3 UAT** against `ingestion/states/montana/extracted/dea-2026.json` and the source PDF (in `ingestion/states/montana/fixtures/mt-fwp-dea-2026-booklet-2026-04-27.pdf` — gitignored, fetch via `python ingestion/states/montana/fetch_pdfs.py` if not already on disk). Faithfulness check is byte-for-byte modulo documented cleanup rules. Once UAT passes, flip AC #342 in the epic and roll counter from "4/13; UAT pending" to "4/13" plain.
- **Begin S03.4 (Black Bear booklet extraction + correction PDF handling)** — second per-booklet extractor; precondition (correction URL) was resolved 2026-05-07 in the S03.3-unblock commit, manifests now on disk. UAT story; faithfulness review against the Black Bear PDF + correction PDF for ≥3 sampled BMUs. Date-arbitrated three-pass architecture (base extraction → correction extraction → per-cell merge with MAX `publication_date` wins). The correction-touched-rows demote-one-tier rule from ADR-017 §4 must be unit-tested.
- **S03.3-S03.5 inherit from S03.2** (recorded in epic): byte-exact text path (`page.chars`) is available as a future helper if needed — to be added as `extract_text_chars_raw(page) -> str` rather than retrofitted onto `extract_text`. ADR-008 boundary defended in `docs/planning/epics/E03-confidence-findings/S03.2.md`.
- **S03.6+ planning inputs from S03.3 (recorded in epic § S03.3 closure note):** (a) per-row `page_reference` is currently section-starting-page; multi-page HDs need per-row page accuracy if S03.6 cares; (b) row-level `weapon_types` defaults to `["any_legal_weapon"]` — refine after S03.7 review; (c) section-level `season_windows` uses first-observation-wins; "Elk B License: 699-01" exhibits the most-prolific divergence — verify against source if S03.7 needs per-license windows.
- **S03.7 inputs from S03.3:** A/B asymmetric `season_coverage` is the load-bearing signal for `license_season` link-table writes. **143 HDs in artifact exhibit the pattern** — sample test data is HD 124 Arvilla deer / HD 170 Flathead River elk.
- **S03.8 inputs from S03.3:** `quota_range` is preserved as a verbatim string ("1-7500"); `quota` is a parsed int (5600). The `900-20` STATEWIDE antelope row is the V1 antelope `draw_spec` input.
- After S03.4: S03.5 → entity ingestion in S03.6-S03.9 → binding generation in S03.10 → calibration audit in S03.11 → M1 UAT in S03.12.
- The `m1` tag pushes at S03.12's final commit, alongside `git rm -r docs/planning/epics/E03-confidence-findings/` per ADR-017's working-notes deletion policy.

---

## Epic Files

- [M0 — Scaffold](epics/completed/M0-scaffold.md)
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/E01-schema-migrations.md)
- [E02 — Montana Geometry Ingestion](epics/completed/E02-geometry-ingestion.md)
- [E03 — Montana Regulation Text Ingestion](epics/E03-regulation-text-ingestion.md)
