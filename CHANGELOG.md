# Changelog

## [Unreleased]

- E02 S02.0: Schema preparation for Montana geometry ingestion — added `verbatim_rule text` (nullable) to `geometry` via migration `supabase/migrations/20260428000000_geometry_verbatim_rule.sql`; extended `SourceCitation.document_type` Literal/union with `"gis_layer"` (type-layer enforcement only per ADR-014, no SQL CHECK); three-place sync across Pydantic (`ingestion/ingestion/lib/schema.py`), TypeScript (`mcp-server/src/types/schema.ts`), and `docs/architecture.md` per ADR-006; merged 2026-04-29 (PR #18); no data loaded

## E01 — Schema Migrations, RLS, and Quality Gates — 2026-04-28

- S01.1: Installed pre-commit hooks (TypeScript `tsc --noEmit`, Python `ruff check`, secrets scanning via `detect-secrets`); secrets baseline at `.secrets.baseline`, config at `.pre-commit-config.yaml`
- S01.2: Initial migration creating all 10 entity and link tables with composite/text PKs, jsonb soft FKs, `geography(MultiPolygon, 4326)` columns, `int4range` quota ranges, CHECK constraints on every enum-like field, and 4 supporting indexes (GiST spatial + 3 query-pattern); migration at `supabase/migrations/20260425000000_initial_schema.sql`
- S01.3: RLS deny-all migration applying three-layer defense-in-depth (ENABLE + FORCE RLS, deny-all policies for `authenticated` and `anon`, explicit REVOKE) on all 10 tables; service-role bypass preserved; migration at `supabase/migrations/20260425000001_rls_deny_all.sql`
- S01.4: Pydantic models for all 18 entity and jsonb sub-model types in `ingestion/ingestion/lib/schema.py`, mirroring DDL one-to-one with `Literal` types matching CHECK constraints and `exclude_none=True` serialization for optional jsonb fields
- S01.5: TypeScript interfaces in `mcp-server/src/types/{schema.ts,index.ts}` matching architecture.md exactly; `tsc --noEmit` clean; no `any` types
- S01.6: Migration reproducibility verified against two fresh Supabase projects; cross-language type checks pass (`tsc --noEmit`, `ruff check`, `mypy`); runbook at `docs/runbooks/E01-migration-verification.md`
- E01 audit (#15) ran against all 64 ACs (53 MET, 4 PARTIALLY, 1 NOT) and applied 4 fixes: clarified `verbatim_rule` nullable convention for `jurisdiction_binding`, added missing `authenticated` curl test to runbook, replaced invalid Supabase CLI command in runbook, documented `exclude_none=True` convention in `schema.py`

## M0 — Scaffold — 2026-04-22

- Verified `.gitignore` covers Node, Python, Next.js, Supabase, OS files, and `.env*` patterns; documented gaps for pnpm and broader `.env.*` coverage
- Created `docs/planning/` directory with milestone index and M0 epic file
- Added `.env.example` documenting all required environment variables (Supabase, Postgres, Mapbox) with no real values
- Scaffolded `mcp-server/` with TypeScript, MCP SDK, Supabase client; hello-world compiles and runs
- Scaffolded `ingestion/` with Python 3.11+, pyproject.toml, pdfplumber/geopandas/shapely toolchain; package installs and imports
- Scaffolded `web/` with Next.js 15, React 19, App Router; production build succeeds
- Scaffolded `plugin/` with Claude Code plugin conventions per ADR-009; two placeholder skills (regulation-lookup, ingest-state) deferred to M5
- Created `supabase/` directory with config placeholder and migrations directory; provisioned Supabase free-tier project with PostGIS enabled
- Drafted README, updated CLAUDE.md to reflect M0 completion, created this changelog
