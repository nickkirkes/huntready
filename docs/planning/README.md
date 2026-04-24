# HuntReady — Planning Index

**Last Updated:** 2026-04-24
**Current Milestone:** M1 — Montana Ingestion
**Overall V1 Status:** 1/6 milestones complete

---

## Milestone Status

| Milestone | Name | Status | Validated | Dependencies |
|---|---|---|---|---|
| M0 | Scaffold | Complete | 2026-04-22 | None |
| M1 | Montana Ingestion | Not Started | — | M0 |
| M2 | Colorado Ingestion | Not Started | — | M1 |
| M3 | MCP Server | Not Started | — | M1 |
| M4 | Web Companion | Not Started | — | M3 |
| M5 | Claude Code Plugin | Not Started | — | M4 |

---

## Current Milestone: M1 — Montana Ingestion

M1 delivers Montana regulations into Supabase Postgres, validated against the six-entity schema, covering five V1 species across all applicable jurisdictions. Three sequential epics:

### Epic Status

| Epic | Name | Status | Validated | Stories |
|---|---|---|---|---|
| E01 | Schema Migrations, RLS, and Quality Gates | Not Started | 2026-04-24 | 6 |
| E02 | Montana Geometry Ingestion | Not Started — planned when E01 completes | — | TBD |
| E03 | Montana Regulation Text Ingestion | Not Started — planned when E02 completes | — | TBD |

### E01 Story Status

| Story | Name | Status | Owner |
|---|---|---|---|
| S01.1 | Install pre-commit hooks | Not Started | Implementation |
| S01.2 | Initial migration — entity tables, link tables, indexes | Not Started | Implementation |
| S01.3 | RLS migration — deny-all policies | Not Started | Implementation |
| S01.4 | Python dataclasses matching DDL | Not Started | Implementation |
| S01.5 | TypeScript types matching DDL | Not Started | Implementation |
| S01.6 | Migration reproducibility verification | Not Started | Implementation |

---

## Active Blockers

None. Previously identified blockers (`source_date`, `ingestion/lib/` path) resolved — see [E01 epic](epics/E01-schema-migrations.md) § "Known Issues to Escalate".

---

## Next Actions

- Resolve three E01 blockers (human decisions above)
- Begin S01.1 (pre-commit hooks) — recommended first story
- E02 and E03 epic files will be drafted when their predecessor completes

---

## Epic Files

- [M0 — Scaffold](epics/completed/M0-scaffold.md)
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/E01-schema-migrations.md)
