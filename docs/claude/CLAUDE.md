# huntready

Regulatory data platform for licensed hunting in the US. Given a coordinate, species, and date, returns applicable regulations with source citations, license/tag requirements, season windows, reporting obligations, and agency contacts. Routes hunters to authoritative state agency sources — does not interpret or paraphrase regulations.

## Stack

Python (ingestion: pdfplumber, geopandas, shapely), TypeScript (MCP server: Anthropic MCP SDK, Postgres), TypeScript (web: Next.js, Mapbox GL JS, Tailwind), Supabase Postgres + PostGIS

## Commands

| Action | Command |
|--------|---------|
| Build | No unified build yet (`cd mcp-server && npm run build`, `cd web && npm run build`) |
| Type check | `npx tsc --noEmit` (per-directory in mcp-server/ and web/) |
| Test | None yet |

## Conventions

- MCP server is the canonical interface — all data access goes through it. No surface bypasses it to query the DB directly.
- Authority preserved, not replaced — every regulation record requires source citation (URL, agency, publication date). No paraphrasing, no summarization. Records without citations fail validation.

## Architecture

Data Sources (state F&W agencies, PAD-US, BLM) -> ingestion/ (Python, per-state adapters, offline pipeline) -> Supabase Postgres + PostGIS -> mcp-server/ (TypeScript, 5 MCP tools) -> web/ (Next.js) + plugin/ (Claude Code plugin)

Ingestion is upstream and offline. Python pipeline writes to Postgres; the TypeScript serving stack never imports from ingestion/ or requires Python. Contributors working on serving can ignore the Python toolchain entirely.

## Cross-Boundary Concerns

Python/TypeScript boundary: ingestion (Python) and serving (TypeScript) share the database but never import from each other. Schema is defined in three places kept in manual sync: TypeScript types (mcp-server/src/types/), Python dataclasses (ingestion/lib/schema.py), and Postgres DDL (supabase/migrations/). Schema version bumps must propagate to all three.

## Documentation

- ADRs: docs/adrs/ (13 architecture decision records)
- Known pitfalls: docs/claude/known-pitfalls.md
