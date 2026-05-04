# HuntReady — Planning Index

**Last Updated:** 2026-05-04
**Current Milestone:** M1 — Montana Ingestion (E01 + E02 complete; E03 active — S03.0 schema landed, S03.1 next)
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
| E03 | Montana Regulation Text Ingestion | In Progress (1/13 stories complete) | 2026-05-03 | — | 13 |

### E03 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S03.0 | Schema preparation — license_season + geometry.legal_description + geometry.kind='state' + Montana state geometry | Complete (schema landed; MT-STATEWIDE-geom load operator-pending) | Implementation |
| S03.1 | PDF fetch infrastructure | Not Started | Implementation |
| S03.2 | PDF extraction primitives (shared library) | Not Started | Implementation |
| S03.3 | DEA booklet extraction (deer, elk, antelope) | Not Started | Implementation (UAT: yes) |
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

- **Operator step to close S03.0 AC #5:** run `cd ingestion && DATABASE_URL=... .venv/bin/python states/montana/load_state_boundary.py` to write `MT-STATEWIDE-geom`. Idempotent UPSERT. Required for E03 binding work in S03.10.
- **Begin S03.1 (PDF fetch infrastructure)** — shared `ingestion/ingestion/lib/pdf_fetch.py` library + `sources.yaml` registry for the four V1 PDFs (DEA, Black Bear, Legal Descriptions, Black Bear correction); per-PDF manifest writers mirroring S02.7's pattern; SHA drift hardened to fail-loud per the ADR-001 discipline that S03.0 just exercised.
- After S03.1: S03.2 (extraction primitives) → per-booklet extraction in S03.3-S03.5 → entity ingestion in S03.6-S03.9 → binding generation in S03.10 → calibration audit in S03.11 → M1 UAT in S03.12.
- The `m1` tag pushes at S03.12's final commit, alongside `git rm -r docs/planning/epics/E03-confidence-findings/` per ADR-017's working-notes deletion policy.

---

## Epic Files

- [M0 — Scaffold](epics/completed/M0-scaffold.md)
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/E01-schema-migrations.md)
- [E02 — Montana Geometry Ingestion](epics/completed/E02-geometry-ingestion.md)
- [E03 — Montana Regulation Text Ingestion](epics/E03-regulation-text-ingestion.md)
