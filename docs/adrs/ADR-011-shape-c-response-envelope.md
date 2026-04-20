# ADR-011: Shape C Response Envelope

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** mcp, schema

---

## Context

The `get_regulations(lat, lng, species, date)` tool is HuntReady's primary MCP surface; its response is the contract between the server and every consumer — agentic clients, the web companion, future B2B API consumers.

Three response-shape candidates were evaluated in [`research/mcp-tool-response-shape-recommendation.md`](../research/mcp-tool-response-shape-recommendation.md). Shape A is a flat array of regulation records. Shape B is a structured envelope whose sections are omitted when they don't apply. Shape C is a structured envelope whose sections are always present — empty or null-valued when they don't apply, populated when they do.

## Decision

The `get_regulations` tool returns a structured envelope (`GetRegulationsResponse`) with always-present, null-bearing sections and explicit coverage signals. Sections that do not apply to a query carry `null` rather than being omitted from the payload.

## Reasoning

Absence is ambiguous. In Shape B, the absence of a `reporting` section could mean "no reporting required" or "we don't have reporting data for this jurisdiction." These are radically different answers — one says the hunter is free, the other says the hunter should check directly with the agency — and collapsing them to the same response is a truthfulness failure. Shape C encodes the distinction explicitly: a populated `reporting` section with zero obligations means "no reporting required"; a `null` reporting section with a `meta.coverage.jurisdiction: "none"` signal means "we don't have data."

The argument for Shape A (flat array) held for search-style tools — Linear's issue search, Stripe's charge list — but fails for context assembly. `get_regulations` takes a subject and returns a view, not a result set to iterate. An agent probing that view along a fixed path ("is the season open, is a tag required") reads single fields in Shape C; in Shape A, each probe becomes a filter-and-group exercise over an array, and the agent still cannot tell whether the absence of a record means "not required" or "data missing."

The committed envelope differs from the original research recommendation in three ways, driven by the decomposed entity model in [ADR-010](ADR-010-decomposed-entity-model.md): `tags` and `reporting` are plural arrays rather than singular objects, and closure predicates are inline on season windows rather than a separate section. The full `GetRegulationsResponse` interface is documented in `architecture.md`.

## Alternatives Considered

**Shape A — flat array of regulation records.** Rejected because it pushes grouping and coverage judgment onto the consumer, and because the absence of a record type cannot distinguish "not required" from "not in the dataset."

**Shape B — structured envelope with omitted sections.** Rejected because omitted sections silently collapse the two meanings of absence. Adding a parallel `coverage` object to disambiguate recreates Shape C in all but name, more awkwardly.

## Consequences

### Positive

- Coverage gaps are a first-class signal, not an inferred absence. A Wyoming query against a Montana-and-Colorado corpus returns a shaped response that tells the consumer HuntReady doesn't cover Wyoming yet.
- Agents read fixed fields rather than inferring from absence; the tool is reliable to probe.
- Web UI skeletons, Suspense boundaries, and deep links all work because the response shape is stable.

### Negative

- Response payloads are larger than either alternative. A coverage-gap query carries an envelope with every section populated as null, which is still a few kilobytes of structure.
- The server handler must always construct the full envelope, even when most sections are null; short-circuit "return early if no data" patterns are unavailable.

### Neutral

- The envelope contains no server-composed `overview` or `headline` field; clients compose their own summaries from the structured sections. This is the principle committed in [ADR-013](ADR-013-server-returns-structure-client-composes-presentation.md), of which this ADR is the first application.
- The response shape depends on the entity decomposition in [ADR-010](ADR-010-decomposed-entity-model.md); reshaping the entities would reshape the response.

## Links

- [ADR-002](ADR-002-mcp-canonical-interface.md) — The canonical interface whose response contract this ADR defines.
- [ADR-010](ADR-010-decomposed-entity-model.md) — The entity model the envelope composes from.
- [ADR-013](ADR-013-server-returns-structure-client-composes-presentation.md) — The general principle under which the no-`overview` decision sits.
- [`research/mcp-tool-response-shape-recommendation.md`](../research/mcp-tool-response-shape-recommendation.md) — Extended reasoning and worked examples.
- [`architecture.md`](../architecture.md) — The full `GetRegulationsResponse` TypeScript interface.
