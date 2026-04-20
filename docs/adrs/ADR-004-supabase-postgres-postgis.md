# ADR-004: Supabase Postgres + PostGIS as the Storage Layer

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** storage

---

## Context

HuntReady's data has two shapes that drive the storage choice. It is inherently spatial — unit boundaries, overlay geometries, point-in-polygon queries — and inherently relational — regulation records reference seasons, tags, reporting obligations, and geometries, with multiple overlay geometries per record (CWD zones, BMUs, portions). Montana's ArcGIS MapServer exposes forty feature layers; Colorado's CPW FeatureServer serves 186 big-game GMU polygons. The data asks for SQL and spatial predicates; anything else is rewriting a worse version of Postgres. V1 has roughly ten to fourteen focused working days, so setup friction at the storage layer matters.

## Decision

HuntReady uses Supabase Postgres with the PostGIS extension as the single source of truth for regulation data, with the MCP server and ingestion pipeline as the only readers and writers.

## Reasoning

Postgres+PostGIS is the correct storage for this product, not a future upgrade. The geometry type is `geography(MultiPolygon, 4326)` rather than `Polygon` because CPW data and Montana HDs contain legitimate multi-part units along state lines. Spatial queries use SQL via `ST_Contains` and `ST_Intersects`, not reimplemented in TypeScript. Joins between regulation records, seasons, tags, and jurisdiction bindings are joins, not application-level stitching.

Supabase is chosen for three reasons. Setup is near zero — a project provisions in minutes with PostGIS as a checkbox extension. Managed migrations and the dashboard reduce operational friction when time is scarce. And Supabase's V2-capable surfaces (Auth, Storage, Edge Functions, Realtime) are available without a platform migration, keeping options open at no V1 cost.

V1 uses a narrow slice: Postgres, PostGIS, migrations, and service-role connections. Auth, Storage, Edge Functions, and Realtime are not used. Critically, the auto-generated PostgREST API is disabled via Row Level Security — anonymous and authenticated-user access denied; only service-role credentials can reach the data. This prevents PostgREST from becoming an uncontrolled second query path that would violate [ADR-002](ADR-002-mcp-canonical-interface.md).

## Alternatives Considered

**Self-hosted Postgres on a VPS.** Rejected on V1 time budget. Backups, migrations, monitoring, and a stable address burn days the project does not have.

**Neon or Fly.io Postgres.** Both support PostGIS. Rejected because neither packages migrations and a dashboard as cleanly as Supabase, and neither offers a free path to optional V2 capabilities without a second vendor.

**Document store or JSON files in object storage.** Rejected because the data has real relational and spatial structure. Either choice forces the application to reimplement joins and spatial predicates, producing something strictly worse than Postgres.

## Consequences

### Positive

- Spatial and relational queries are expressed in SQL, where they belong.
- Setup friction is minimal, preserving the V1 time budget for ingestion and schema work.
- V2 capabilities are reachable without a platform migration.

### Negative

- Local development requires each contributor to run their own Supabase project — a vendor dependency even for experimentation.
- Supabase is a specific vendor; migrating off later means re-pointing connection strings and replacing the managed pieces (dashboard, migration tooling).
- PostgREST must be affirmatively disabled via RLS; forgetting the policy would silently expose a second query path.

### Neutral

- The offline-ingestion and canonical-interface commitments both depend on there being exactly one store shared by exactly two clients. Any replacement storage must honor the same shape.

## Links

- [ADR-002](ADR-002-mcp-canonical-interface.md) — The MCP server is the only reader; PostgREST is disabled to keep it that way.
- [ADR-003](ADR-003-ingestion-upstream-offline.md) — The ingestion pipeline is the only writer.
- [ADR-006](ADR-006-schema-versioned-from-day-one.md) — Schema evolution lives in Supabase migrations.
