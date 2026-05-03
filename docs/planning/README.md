# HuntReady — Planning Index

**Last Updated:** 2026-05-03
**Current Milestone:** M1 — Montana Ingestion (E01 + E02 complete; E03 next — run `/plan-next-epic`)
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
| E02 | Montana Geometry Ingestion | Complete | 2026-04-28 | 2026-05-03 | 8 |
| E03 | Montana Regulation Text Ingestion | Not Started — ready to plan | — | — | TBD |

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

**E02 closed 2026-05-03.** All 8 stories merged, all exit criteria met. S02.7 (Spatial query verification + epic exit) added the per-fetch manifest writer to `arcgis.fetch_features` (resolving the prior known-issue #6 fixture-policy gap), spatial verification suite (11 test points), operator runbook, and 10 backfilled manifests. None blocking E03 planning.

One PRD-reconciliation item remains, but it does **not** block E03:

- **PRD 001 jurisdiction_binding sequencing** — PRD says E02 writes binding rows; schema FK to regulation_record makes that impossible until E03. E02 produces a geometry overlay fixture instead. Proposed PRD wording in [E02 epic](epics/E02-geometry-ingestion.md) § "Known issues to escalate". PM does not modify PRDs.

Documentation-debt items (non-blocking):

- Architecture.md prose says "every entity carries `confidence`" but interfaces only place it on `RegulationRecord` and `VerbatimRule`. Scheduled remote agent fires 2026-05-12 to PR a fix if still stale.

---

- **Run `/plan-next-epic`** to begin E03 (Montana Regulation Text Ingestion) — PM will draft 8-12 stories, run the E03 validation triad (Source Faithfulness Reviewer, Confidence Calibration Reviewer, Schema Stress-Test Reviewer), write the epic file, and update this index. E03 depends on E02's `geometry-overlays.json` fixture (consumed when generating `jurisdiction_binding` rows) and inherits two flagged handoff items in the E02 epic § "Known issues to escalate": (a) `kind='restricted_area'` discriminator question for no-hunt zones, (b) jurisdiction_binding fan-out sizing (~3 parents per child median).
- Q11 (confidence calibration) resolves during E03 per the M1 PM prompt — plan a story that explicitly produces the resolving ADR.

---

## Epic Files

- [M0 — Scaffold](epics/completed/M0-scaffold.md)
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/E01-schema-migrations.md)
- [E02 — Montana Geometry Ingestion](epics/E02-geometry-ingestion.md)
