# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

HuntReady is a regulatory data platform for licensed hunting in the US. Given a coordinate, species, and date, it returns applicable regulations with source citations, license/tag requirements, season windows, reporting obligations, and agency contacts. It routes hunters to authoritative state agency sources — it does not interpret or paraphrase regulations.

## Project status

**M1 in progress (E01 complete; E02 active — 6/8 stories complete).** M0 scaffold complete. E01 (schema migrations, RLS, quality gates) merged 2026-04-28: 10 tables (7 entity + 3 link) created in `supabase/migrations/`, deny-all RLS active on every table with three-layer defense-in-depth (ENABLE+FORCE, deny-all policies, REVOKE), Pydantic models in `ingestion/ingestion/lib/schema.py` and TypeScript interfaces in `mcp-server/src/types/` mirror the DDL, pre-commit hooks installed. Migration reproducibility verified against fresh Supabase projects; runbook at `docs/runbooks/E01-migration-verification.md`. E02 S02.0 (schema prep) merged 2026-04-29: `geometry.verbatim_rule text` (nullable) added; `SourceCitation.document_type` extended with `'gis_layer'` per ADR-014. E02 S02.1 (ArcGIS fetch infrastructure shared library) merged 2026-04-29. E02 S02.2 (Hunting District ingestion) merged 2026-04-30: 235 Montana HDs loaded; named multi-part HD anchor `MT-HD-deer-elk-lion-690-geom` (12 parts) reserved for S02.7. E02 S02.3 (Portions ingestion) merged 2026-04-30: 55 Montana portions loaded. E02 S02.4 (Restricted Areas with verbatim text) merged 2026-04-30: 57 restricted-area geometries; 55 of 57 rows exercise the ADR-015 separator branch. E02 S02.5 (CWD zone discovery and ingestion) merged 2026-05-01: investigation took **Path A — standalone GIS layer** via the dedicated `ADMBND_HD_CWD` FeatureServer on ArcGIS Online (item `8837c07298054f5e8be2e072681d870c`, separate from `fwp-gis.mt.gov`); 2 CWD zones loaded for 2026 (Libby and Kalispell CWD Management Zones); UAT used the spec-permitted name substitution since the live FWP layer publishes 2 zones (not 3) for 2026, plus a negative-control point. Comprehensive investigation report at `ingestion/states/montana/cwd-source-discovery.md`. Total geometry rows after S02.5: 235 HDs + 55 portions + 57 restricted areas + 2 CWD zones = 349. S02.6 (Geometry overlay fixture) is next.

## Architecture

```
Data Sources (state F&W agencies, PAD-US, BLM)
       ↓
  ingestion/ (Python) — per-state adapters, offline pipeline
       ↓
  Supabase Postgres + PostGIS — single source of truth
       ↓
  mcp-server/ (TypeScript) — canonical interface, 5 MCP tools
     ↓          ↓
  web/ (Next.js)  plugin/ (Claude Code plugin)
```

### Architectural commitments (enforced, not aspirational)

- **MCP server is the canonical interface.** Web and plugin are both clients of the MCP server. No surface bypasses it to query the database directly.
- **Ingestion is upstream and offline.** Python pipeline writes to Postgres; the TypeScript serving stack never imports from `ingestion/` or requires Python. Contributors working on serving can ignore the Python toolchain entirely.
- **Authority preserved, not replaced.** Every regulation record requires a source citation (URL, agency, publication date). Regulation text is carried verbatim — no paraphrasing, no summarization. Records without citations fail validation.
- **Schema versioned from day one.** `regulation_record` and `draw_spec` carry `schema_version`; source provenance is tracked via the `source` jsonb field (which includes `publication_date`). The MCP server rejects records with unsupported schema versions.
- **Server returns structure; clients compose presentation.** No server-side `overview` or `headline` fields. Structured sections with always-present, null-bearing fields (null = "not applicable" vs omitted = ambiguous). Each client composes its own summary because each knows its presentation context.
- **Agentic development is first-class.** The Claude Code plugin (`plugin/`) uses `.claude-plugin/` + `plugins/<name>/skills/<skill>/SKILL.md` convention. Documentation is the primary handoff mechanism between sessions.

### Key constraints

- PostgREST API is disabled via RLS — only service-role credentials can read/write. This prevents an uncontrolled second path to the data.
- `draw_spec.parameters` is a `Record<string, unknown>` escape hatch for state-specific quirks. Shared code (MCP server, web client) must NEVER read this field. Only state adapters in `ingestion/states/<state>/` may use it.
- `draw_spec.pools` and `draw_spec.point_system` are stored as `jsonb`. Pool share sum-to-1.0 and eligibility consistency are validated in application code, not DB constraints.
- All geometries use `geography(MultiPolygon, 4326)` — not `Polygon` — because real state data (CPW GMUs, MT HDs) contains multi-part units along state lines.
- Every geometry goes through `shapely.make_valid()` before insert.
- No `any` types in .tsx files.

## Tech stack

| Layer | Language | Key dependencies |
|-------|----------|-----------------|
| Ingestion (`ingestion/`) | Python | pdfplumber, pypdf, unstructured, geopandas, shapely |
| MCP Server (`mcp-server/`) | TypeScript | Anthropic MCP SDK, Postgres connection pool |
| Web (`web/`) | TypeScript | Next.js, Mapbox GL JS, Tailwind |
| Plugin (`plugin/`) | TypeScript | Claude Code plugin conventions |
| Database | SQL | Supabase Postgres + PostGIS extension |
| Migrations | SQL | `supabase/migrations/` timestamped files |

## Build commands (once implementation exists)

```bash
# Ingestion (Python)
make ingest STATE=montana         # Full pipeline: fetch → extract → normalize → validate → load
make ingest-all                   # All states

# MCP Server (TypeScript)
cd mcp-server && npm install && npm run dev

# Web companion (Next.js)
cd web && npm install && npm run dev

# Database migrations
supabase db push                  # Apply migrations to Supabase
```

## Verification commands

Used by `/ruckus:verify-all` and the Stop hook. Run from the repo root.

```bash
# Python ingestion — lint, type, test
cd ingestion && .venv/bin/ruff check ingestion/ tests/
cd ingestion && .venv/bin/mypy ingestion/lib/
cd ingestion && .venv/bin/pytest tests/

# TypeScript serving (when files exist; mcp-server and web both currently empty)
cd mcp-server && npx tsc --noEmit
cd web && npx tsc --noEmit
```

## Data model (6 entities)

- **`regulation_record`** — anchor entity, keyed by (state, jurisdiction_code, species_group, license_year)
- **`season_definition`** — named date ranges with weapon/residency constraints
- **`license_tag`** — permit instruments with optional draw_spec reference
- **`draw_spec`** — draw mechanics, keyed by (state, hunt_code, year). Sibling entity referenced from `license_tag` by FK. Composes `point_system`, `residency_cap`, `choices`, and `allocation_pool[]` — verified against CO, WY, NM, UT draw systems with no state-specific branches in shared code.
- **`reporting_obligation`** — post-harvest/in-season duties, can be region-specific
- **`geometry` + `jurisdiction_binding`** — polygons and their roles (primary unit, overlays like CWD zones, BMUs)

Entities cross-share: e.g., Montana A and B licenses reference the same `season_definition` rows. Corrections update one row, not duplicated copies.

Schema is defined in three places kept in manual sync: TypeScript types (`mcp-server/src/types/`), Python dataclasses (`ingestion/lib/schema.py`), and Postgres DDL (`supabase/migrations/`). Schema version bumps propagate to all three. The canonical type definitions are in [docs/architecture.md](docs/architecture.md).

## Ingestion adapter pattern

Each state lives in `ingestion/states/<state>/` with isolated files:
- `fetch.py` — retrieve source documents
- `extract.py` — pull structured data from sources
- `normalize.py` — map state-specific fields to shared schema
- `validate.py` — common + state-specific validation
- `load.py` — write to Supabase Postgres
- `sources.yaml` — source document registry

State adapters are isolated from each other. Shared code lives in `ingestion/lib/`. Adding a new state means adding a new directory, not modifying shared code.

## V1 scope

- **States:** Montana, Colorado (deliberately chosen: MT for moderate complexity, CO for draw-system stress-test)
- **Species:** elk, mule deer, whitetail, pronghorn, black bear
- **MCP tools:** `get_regulations`, `check_land_status`, `list_seasons`, `get_tag_requirements`, `get_agency_contacts`
- **Surfaces:** MCP server, web companion, Claude Code plugin

Explicitly out of scope for V1: mobile app, user accounts, automated ingestion scheduling, B2B API packaging, harvest tracking, license purchase proxying.

## Documentation as handoff mechanism

Per ADR-009, documentation is the primary handoff mechanism between sessions (human or agent). The flow: question arises in `open-questions.md` -> resolved in an ADR -> `architecture.md`/`context.md` updated -> question removed. When hitting a decision point, check `open-questions.md` first; escalate new decisions there rather than making silent calls.

## Key documents

- [docs/context.md](docs/context.md) — product frame, what HuntReady is and is not
- [docs/architecture.md](docs/architecture.md) — system design, schema types, response shapes
- [docs/roadmap.md](docs/roadmap.md) — milestones M0-M5
- [docs/open-questions.md](docs/open-questions.md) — unresolved decisions (check before making architectural calls)
- [docs/adrs/](docs/adrs/) — 15 architecture decision records:
  - ADR-001: Authority preserved, not replaced
  - ADR-002: MCP server as canonical interface
  - ADR-003: Ingestion upstream and offline
  - ADR-004: Supabase Postgres + PostGIS
  - ADR-005: Python for ingestion, TypeScript for serving
  - ADR-006: Schema versioned from day one
  - ADR-007: Montana and Colorado as seed states
  - ADR-008: Verbatim regulation text
  - ADR-009: Agentic development as first-class project feature
  - ADR-010: Decomposed entity model (6 entities)
  - ADR-011: Shape C response envelope (null = not applicable, omitted = never)
  - ADR-012: Draw mechanics as sibling entity
  - ADR-013: Server returns structure, client composes presentation
  - ADR-014: `SourceCitation.document_type='gis_layer'` (type-layer enforcement)
  - ADR-015: `geometry.verbatim_rule` column + REG+COMMENTS handling rule

## Environment variables

- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_SECRET_KEY` — secret key (MCP server + ingestion)
- `SUPABASE_PUBLISHABLE_KEY` — publishable key (web app, scoped by RLS)
- `DATABASE_URL` — direct Postgres connection string (ingestion pipeline + migrations only; not used by serving stack per ADR-003)
- `MAPBOX_ACCESS_TOKEN` — Mapbox GL JS access token (web map)
- `HUNTREADY_INGESTION_CONTACT` — *recommended for ingestion runs.* Email or URL appended to the ArcGIS HTTP `User-Agent` as `(contact: <value>)`. Gives upstream data providers (state F&W agencies) a way to reach the operator if a fetch behaves unexpectedly. Empty/unset → User-Agent omits the contact suffix. Kept in env (not source) so the contact can change without a code edit.
