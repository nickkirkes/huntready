# Changelog

## [Unreleased]

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
