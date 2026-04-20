# ADR-002: MCP Server as Canonical Interface

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** mcp, scope

---

## Context

HuntReady is a data platform with three V1 consumer surfaces: an MCP server, a Next.js web companion, and a Claude Code plugin. A regulation corpus that serves multiple surfaces needs one query path, not three. Without a designated canonical interface, each surface grows its own query logic against the database, and correctness drifts between them. Supabase's auto-generated PostgREST API also presents a second path by default.

## Decision

The MCP server is HuntReady's canonical interface; all consumer surfaces — web companion, Claude Code plugin, future clients — call MCP tools rather than querying the database directly.

## Reasoning

Putting the query logic in exactly one place keeps behavior consistent across surfaces and makes correctness a single-file problem. If `get_regulations` computes the wrong answer, it computes it everywhere, and the fix lands once — a better failure mode than each surface carrying its own bugs.

MCP is chosen over a REST API because agentic clients are the product's primary surface. Designing the interface for agents first and adapting it for browsers via a thin HTTP shim in `mcp-server/http.ts` is cheaper than the reverse; a REST API retrofitted for agents tends to leak presentation concerns and lack the tool-call discoverability agents expect.

The web companion calls MCP tools through the HTTP adapter; the plugin triggers Claude Code's existing MCP client against the same server. Every surface is a client.

Supabase's PostgREST API is disabled at the Row Level Security layer. Anonymous and authenticated-user roles have no access; only the MCP server's service-role credentials can reach the data. This turns the canonical-interface commitment into a policy enforced by the database, not an honor system.

## Alternatives Considered

**REST API as canonical, MCP layered on top.** Rejected because it inverts the priority: agentic clients are the primary consumer, and making their interface a translation of a browser-first API leaks browser assumptions into agent workflows.

**Direct database access per surface with a shared query library.** Rejected because a shared library every surface imports is either a server in disguise or a source of drift when surfaces extend it locally.

**GraphQL as canonical.** Rejected on scope. MCP covers the agent-first use cases with a simpler tool-call model; adding GraphQL is a second interface to maintain for no V1 benefit.

## Consequences

### Positive

- Query logic lives in one place, which makes correctness auditable and bug fixes singular.
- Every new consumer surface reaches the platform without a second implementation.
- Disabling PostgREST via RLS enforces the commitment structurally rather than by convention.

### Negative

- The web app pays a small indirection cost — calls go through the HTTP shim rather than hitting the database — which adds latency and a moving part that can fail.
- Every query pattern the web companion wants must be expressible as an MCP tool, constraining UI designs that would otherwise ask ad-hoc questions of the database.
- Debugging a web-app misbehavior has three hops (web → shim → tool → Postgres) instead of two.

### Neutral

- The shape of future B2B API work is prefigured: it will be a public wrapper of the MCP server, not a separate API.

## Links

- [ADR-001](ADR-001-authority-preserved.md) — One interface, one source-of-truth contract.
- [ADR-003](ADR-003-ingestion-upstream-offline.md) — Ingestion is the only writer; this ADR makes MCP the only reader.
- [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md) — The server is TypeScript because MCP's reference SDK is TypeScript.
