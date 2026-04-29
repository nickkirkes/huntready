# HuntReady — Planning Index

**Last Updated:** 2026-04-29
**Current Milestone:** M1 — Montana Ingestion (E01 complete, E02 active — S02.0 complete, S02.1 next)
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
| E02 | Montana Geometry Ingestion | In Progress (1/8 stories complete) | 2026-04-28 | — | 8 |
| E03 | Montana Regulation Text Ingestion | Not Started — planned when E02 completes | — | — | TBD |

### E02 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S02.0 | Schema preparation — `document_type='gis_layer'` + `geometry.verbatim_rule` | Complete | Implementation |
| S02.1 | ArcGIS fetch infrastructure (shared library) | Not Started | Implementation |
| S02.2 | Hunting District ingestion (#3, #10, #11) | Not Started | Implementation |
| S02.3 | Portions ingestion (#4, #12, #13, #14) | Not Started | Implementation |
| S02.4 | Restricted Areas with verbatim text (#2, #15) | Not Started | Implementation |
| S02.5 | CWD zone discovery and ingestion | Not Started | Implementation (UAT: yes) |
| S02.6 | Geometry overlay fixture | Not Started | Implementation (UAT: yes) |
| S02.7 | Spatial query verification + epic exit | Not Started | Implementation (UAT: yes) |

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

None blocking S02.1. ADR blockers cleared 2026-04-28 (ADR-014, ADR-015 accepted) and S02.0 schema-prep merged 2026-04-29 (PR #18) — Pydantic `Geometry.verbatim_rule` and `SourceCitation.document_type='gis_layer'` are available for S02.1's ArcGIS SourceCitation construction.

One PRD-reconciliation item remains, but it does **not** block S02.1 or S02.2:

- **PRD 001 jurisdiction_binding sequencing** — PRD says E02 writes binding rows; schema FK to regulation_record makes that impossible until E03. E02 produces a geometry overlay fixture instead. Proposed PRD wording in [E02 epic](epics/E02-geometry-ingestion.md) § "Known issues to escalate". PM does not modify PRDs.

Documentation-debt items (non-blocking):

- Architecture.md prose says "every entity carries `confidence`" but interfaces only place it on `RegulationRecord` and `VerbatimRule`. Scheduled remote agent fires 2026-05-12 to PR a fix if still stale.

---

## Next Actions

- Begin S02.1 (ArcGIS fetch infrastructure) — shared `ingestion/ingestion/lib/arcgis.py` library with metadata fetch, paginated feature fetch, source-fixture capture, and per-feature change detection
- After S02.1 merges, S02.2–S02.5 proceed in dependency order using the shared library
- E03 epic file will be drafted when E02 completes (run `/plan-next-epic`)

---

## Epic Files

- [M0 — Scaffold](epics/completed/M0-scaffold.md)
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/E01-schema-migrations.md)
