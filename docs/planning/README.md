# HuntReady — Planning Index

**Last Updated:** 2026-05-01
**Current Milestone:** M1 — Montana Ingestion (E01 complete, E02 active — S02.0–S02.6 complete, S02.7 next)
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
| E02 | Montana Geometry Ingestion | In Progress (7/8 stories complete) | 2026-04-28 | — | 8 |
| E03 | Montana Regulation Text Ingestion | Not Started — planned when E02 completes | — | — | TBD |

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

None blocking S02.7. S02.6 (Geometry overlay fixture) merged 2026-05-01 (PR #25): the overlay fixture and audit log are committed; ADR-016 codifies the three-band area-ratio discriminator that became necessary when (a) Supabase's role-locked 2-min `statement_timeout` aborted cross-join SQL on real Montana data and (b) strict `ST_Covers` rejected 32 of 55 Montana portions due to digitization precision. Spatial work moved off SQL to local shapely + STRtree (~5 sec). Two new E03 handoff items recorded in the epic's "Known issues to escalate" (`restricted_area` kind conflates internal HD restrictions vs no-hunt zones; jurisdiction_binding fan-out is higher than naive estimates).

One PRD-reconciliation item remains, but it does **not** block S02.7:

- **PRD 001 jurisdiction_binding sequencing** — PRD says E02 writes binding rows; schema FK to regulation_record makes that impossible until E03. E02 produces a geometry overlay fixture instead. Proposed PRD wording in [E02 epic](epics/E02-geometry-ingestion.md) § "Known issues to escalate". PM does not modify PRDs.

Documentation-debt items (non-blocking):

- Architecture.md prose says "every entity carries `confidence`" but interfaces only place it on `RegulationRecord` and `VerbatimRule`. Scheduled remote agent fires 2026-05-12 to PR a fix if still stale.

---

- Begin S02.7 (Spatial query verification + epic exit). Final E02 story — verifies `ST_Covers` spot-checks against named test points per `kind`, topology validity, named multi-part HD assertion, reproducibility via `ST_Equals`, and the small `arcgis.fetch_features` manifest extension that resolves the feature-fixture commit policy gap. Runbook at `docs/runbooks/E02-geometry-verification.md` documents the local-shapely overlay architecture (S02.6 finding), threshold calibration per ADR-016, audit-log review process, and the manifest-diff drift-detection workflow.
- E03 epic file will be drafted when E02 completes (run `/plan-next-epic`)

---

## Epic Files

- [M0 — Scaffold](epics/completed/M0-scaffold.md)
- [E01 — Schema Migrations, RLS, and Quality Gates](epics/E01-schema-migrations.md)
