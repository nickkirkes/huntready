# ADR-005: Python for Ingestion, TypeScript for Serving

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** ingestion, mcp, web

---

## Context

HuntReady has two distinct runtime workloads. Ingestion extracts structured data from PDFs, ArcGIS FeatureServers, and shapefiles; it is a batch pipeline that runs offline and never sees user traffic. Serving answers agentic and browser queries via the MCP server and a Next.js web companion; it is a long-running request path with no PDF parsing and no geospatial work.

The heaviest ingestion work is PDF extraction. Montana FWP publishes five species-specific booklets on an annual/biennial cycle with mid-cycle correction PDFs. Tables are fixed-column where present and prose elsewhere, with closure predicates expressed as prose outside the tables. The ingestion strategy combines structured extraction, LLM-assisted extraction with verbatim validation, and human-in-the-loop flagging.

## Decision

Ingestion is written in Python; the MCP server, web companion, and Claude Code plugin are written in TypeScript.

## Reasoning

The language split follows the work. Python has the mature ecosystem for the hardest parts of ingestion: `pdfplumber` and `pypdf` for PDF extraction, `unstructured` for fallbacks, `geopandas` and `shapely` for geometry preparation and `make_valid()` on every geometry before insert. Node-side equivalents trail materially on the part of the problem most time-sensitive to get right.

TypeScript is right for serving for different reasons. The Anthropic MCP SDK's reference implementation is TypeScript; Next.js is TypeScript-native; the Claude Code plugin runs against a TypeScript-native host. One language across server, web, and plugin lets shared types for the response shape and the six schema entities live in one place.

Keeping the two runtimes strictly separated is only possible because [ADR-003](ADR-003-ingestion-upstream-offline.md) puts a Postgres boundary between them. The MCP server never imports from `ingestion/`; ingestion never imports from `mcp-server/`. The shared contract is the schema, expressed in three representations (Postgres DDL, TypeScript interfaces, Python dataclasses) kept in manual sync at V1 scale.

## Alternatives Considered

**All TypeScript.** Rejected because Node's PDF and geospatial tooling is meaningfully behind Python's, and the V1 budget cannot afford to fight tooling on the hardest part of the problem.

**All Python.** Rejected because the MCP SDK's reference implementation is TypeScript, Next.js is TypeScript, and the plugin surface is TypeScript-adjacent. Choosing Python for serving trades a solved problem for an unsolved one.

**Python for ingestion, Go or Rust for serving.** Rejected on developer velocity at V1 scale and on loss of the shared-types benefit with the web and plugin surfaces.

## Consequences

### Positive

- Each half uses the language where its ecosystem is strongest; no tooling fights on either side.
- Shared TypeScript types cover the MCP server, the web client, and the plugin, removing one class of drift.
- Contributors can work on one half without installing the other half's toolchain.

### Negative

- The schema is defined three times, and drift is a known manual-sync burden logged as an open question.
- Testing and CI have to support two language ecosystems end to end.
- A contributor who wants to touch both halves must be fluent in both Python and TypeScript, which is a staffing constraint at team scale even though it is not a V1 constraint.

### Neutral

- The language boundary is also the process boundary and the deploy boundary. The three align by design, which makes any future consolidation a larger change than a language-only change would be.

## Links

- [ADR-002](ADR-002-mcp-canonical-interface.md) — The TypeScript serving stack is organized around the MCP server.
- [ADR-003](ADR-003-ingestion-upstream-offline.md) — The split is only safe because the runtimes share nothing but a database.
- [ADR-004](ADR-004-supabase-postgres-postgis.md) — The shared Postgres boundary that carries the schema contract.
