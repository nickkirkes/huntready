# ADR-003: Ingestion Upstream and Offline

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** ingestion, scope

> Status note: Refined for edge-runtime serving access by [ADR-024](ADR-024-edge-runtime-postgres-access.md) (M3, 2026-06-24) — the serving stack reads from Postgres via the Cloudflare Workers edge runtime (Hyperdrive / Supabase serverless driver, read-only-enforced) rather than a long-running Node process. ADR-003's upstream/offline ingestion principle is unchanged.

---

## Context

HuntReady's regulation corpus is assembled from messy public sources — agency PDFs, ArcGIS FeatureServers, shapefiles, correction documents — through a pipeline that extracts, normalizes, validates, and writes structured records. The serving stack only needs to read those records.

Two naive shapes would bind ingestion and serving. One has the MCP server trigger extraction on demand against a live source. The other keeps ingestion in the same runtime as serving. Both couple query correctness to third-party source availability, and both force the serving stack to carry Python tooling it does not otherwise need.

## Decision

Ingestion runs upstream of the serving stack and offline from user traffic; it writes structured records into Supabase Postgres, and the MCP server and web companion only read from that database.

## Reasoning

Separating ingestion from serving mirrors how a production pipeline would operate — scheduled jobs writing to a shared store, stateless reads from the serving layer — and the separation is visible from V1 so the prototype does not have to be re-architected later.

The separation also enforces a useful constraint: the serving stack has no Python dependency. A contributor working only on the MCP server or the web app can run `npm install && npm run dev` against the database and ignore the entire Python toolchain.

Lazy ingestion was considered and rejected because it makes every user query dependent on a third-party source's availability. Montana FWP's ArcGIS endpoint was healthy at investigation time but Hunt Planner was returning "Data is currently unavailable"; that kind of outage is normal for state-agency infrastructure and cannot be allowed to produce user-facing errors. Offline ingestion also gives validation, QA, and correction handling a beat between fetch and insert — the Montana Black Bear correction PDF published one day after the base booklet is a real instance of why that beat matters.

## Alternatives Considered

**On-demand ingestion from the MCP server.** Rejected because it binds query correctness to source availability, provides no point at which QA can intervene, and pushes PDF-extraction latency into the request path.

**Ingestion inside the serving process as a scheduled job.** Rejected because it couples the serving process's uptime to a heavy batch workload and forces the serving runtime to carry Python tooling.

**Static file artifacts committed to git.** Rejected because regulation data has geospatial shape that wants PostGIS, and because file artifacts would require each consumer surface to parse them independently, defeating the canonical-interface commitment.

## Consequences

### Positive

- The serving stack is simple: read-only SQL against a shared database, one language, one dependency set.
- Ingestion can fail loudly without taking the product down.
- Correction handling, QA, and confidence scoring have a natural home between fetch and insert.

### Negative

- Data freshness is bounded by ingestion cadence. In V1, ingestion is manual; any regulation change between runs is invisible until the next run.
- Corrections are an acute case of the freshness bound: Montana's 2026 Black Bear correction was published 2026-03-18, one day after the base booklet. Under batch-only ingestion, a correction published between runs sits unamended in the corpus until the next manual ingestion — a non-trivial window for a product whose authority commitment turns on text fidelity.
- Two runtimes mean two dependency trees, two deploy paths, two sets of test tooling.
- Emergency-order handling (mid-season CWD closures and similar) cannot be supported under batch-only ingestion; that capability is deferred to V2.

### Neutral

- The boundary between V1's manual ingestion and V2's scheduled pipeline is clean: the same code run on a cron instead of on a prompt. No architectural migration is required.

## Links

- [ADR-002](ADR-002-mcp-canonical-interface.md) — The serving side of the boundary this ADR establishes.
- [ADR-004](ADR-004-supabase-postgres-postgis.md) — The shared data store the pipeline writes to.
- [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md) — The language split enabled by this separation.
