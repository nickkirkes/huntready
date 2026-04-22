# ADR-013: Server Returns Structure, Client Composes Presentation

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** mcp, product

---

## Context

The Q2 research on MCP response shape recommended an `overview` field on the `GetRegulationsResponse` envelope — a server-composed headline and decision summary derived from the structured sections, useful for both the web UI's hero area and for agentic clients that want a ready-to-render answer. The field was dropped during schema-v2 review, which surfaced a question larger than the field itself: when a response could reasonably include a derivative summary, should the server compose it, or should the client?

## Decision

HuntReady's MCP server returns structured data; clients compose their own presentation. The response envelope does not include server-composed summaries, headlines, decision strings, or other presentation-layer fields derived from the structured sections.

## Reasoning

Each client knows its presentation context better than the server does. The web UI renders a map sidebar and wants a hero like "Elk season opens in 3 days" because that matches its spatial surface. An agentic client answering a hunter's question wants to compose "Yes, you can hunt elk here on Oct 15, but you need a general license" because that matches its conversational surface. A server-composed headline must either pick one context as canonical (and be wrong for the other) or try to be generic (and be useful for neither).

A server-composed summary is also a correctness hazard. The summary is derivative: it has to stay consistent with the structured sections it summarizes. If the seasons section says "out of season" and a drifted summary says "in season," the response is internally inconsistent in a way that's hard to detect through normal testing — a consumer reading either field alone sees a plausible answer, only the combination is wrong. The discipline to keep the summary in sync with the sections is real and ongoing; removing the summary removes the invariant.

The principle generalizes. Structural concerns — the shape of the data, the entities that compose it, the coverage signals, the source citations — belong in the server. Presentation-layer concerns belong in clients. The test is whether a field would read differently in a map sidebar, a chat transcript, and a CSV export; if so, it's presentation, and the server should not compose it.

## Alternatives Considered

**Include an `overview` field on the response envelope.** Rejected because it would force the server to pick a presentation context as canonical and because the drift risk between the summary and the structured sections is a correctness hazard not worth the convenience.

**Include an `overview` field as an opt-in parameter on the tool call.** Rejected because it pushes the presentation-composition logic onto the server anyway, and because the set of presentation contexts is open-ended; every new context either requires a new parameter or degrades to the canonical-context problem.

## Consequences

### Positive

- The response envelope has one source of truth per field; there is no derived field to keep in sync with its structured source.
- Clients are free to compose presentation that matches their context, including contexts the server was never designed to anticipate.
- The MCP server's responsibility is narrower and more legible: return structured data faithfully.

### Negative

- Every client implements its own composition logic. A headline that would have been written once on the server is written once per client instead.
- Simple use cases (a developer calling the tool from a Python script and wanting a human-readable summary) have no ready-made one.
- The "server returns structure" rule is a convention, not a type-level constraint; a future contributor could add a presentation field to the envelope without anyone noticing until review.

### Neutral

- [ADR-011](ADR-011-shape-c-response-envelope.md)'s decision to omit an `overview` field is the first concrete application of this principle. Future ADRs that touch response shape should apply the same test.

## Links

- [ADR-002](ADR-002-mcp-canonical-interface.md) — The canonical interface within which this principle operates.
- [ADR-011](ADR-011-shape-c-response-envelope.md) — The first concrete application of this principle.
- [`research/schema-proposal-v2.md`](../research/schema-proposal-v2.md) — The review in which the `overview` field was dropped and this principle was articulated.
