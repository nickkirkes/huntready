# ADR-023: Remote Authenticated MCP Server Posture

**Date:** 2026-06-24
**Status:** Proposed
**Decider:** Nick Kirkes
**Tags:** mcp, deployment

> Status note: `Proposed` pre-implementation per `docs/adrs/README.md` §"Status". The posture itself is human-signed-off (2026-06-24, during M3 planning); the status flips to `Accepted` when the implementing epics ship (E08 stands up the transport + deployment; E11 finalizes the auth seam and deploys). Resolves open-questions Q5 and Q6.

---

## Context

M0–M2 built HuntReady's data backend. M3 builds the serving layer — the MCP server that is the canonical interface (ADR-002). The roadmap originally framed M3 as a *local stdio* server that registers with Claude Desktop, plus a REST HTTP shim for the web companion, deployed to a Node PaaS (Railway/Fly).

Two things reframed that. First, the MCP spec moved: the 2025-11-25 stable revision (and the 2026-07-28 release candidate) make **Streamable HTTP** the remote transport and **OAuth 2.1 + PKCE** the authorization model, and explicitly direct stdio transports *not* to use OAuth (they pull credentials from the environment). A stdio server therefore cannot exercise the authenticated-MCP spec at all. Second, **production intent**: the user intends to move HuntReady toward a live public service if it does not become an OnX engagement. A production public API wants edge autoscale, a managed-OAuth upgrade path, native WAF/rate-limiting, and idle-cost-near-zero hibernation — primitives a remote platform provides and a hand-rolled Node host does not.

## Decision

Build the M3 MCP server as a **remote, spec-conformant Streamable HTTP server deployed on Cloudflare Workers** (stateless `createMcpHandler`; no Durable Objects, since the tools are stateless reads), retaining a stdio entrypoint for local development via the `mcp-remote` proxy. Gate access with a **minimal, OAuth-2.1-ready auth seam split by client type**: the public/browser read path carries **no secret token** (the M4 web app calls the server directly with **no BFF**, so a browser-embedded secret would be exposed) and is abuse-controlled at the **edge** (Cloudflare WAF + rate-limiting); a **static bearer-token / API-key checkpoint** gates **programmatic / non-browser clients** that can hold a secret. `@cloudflare/workers-oauth-provider` is the documented OAuth-2.1 upgrade path. This resolves Q5 (no BFF) and Q6 (Cloudflare Workers).

## Reasoning

Remote Streamable HTTP is where both the spec and the client ecosystem are; it is also the only posture under which the authenticated-MCP spec is exercisable, which is an explicit M3 goal. Cloudflare's remote-MCP toolchain supplies the production primitives cheaply — the OAuth provider library, edge autoscale, WAF/rate-limiting, and no-cold-start serving — and because HuntReady's tools are stateless reads, the stateless `createMcpHandler` path applies, sidestepping Durable Objects and their hibernation concerns entirely.

Auth is deliberately minimal but ready, and split by client type because the no-BFF browser-direct path (Q5) cannot hold a secret — a bearer/API key shipped to the browser is exposed in client-side code and is no control at all. So the browser/public read path carries no secret and relies on edge abuse-control (Cloudflare WAF + rate-limiting, optionally Turnstile), while the static bearer-token checkpoint gates only programmatic clients that can hold a secret. The data is public hunting regulations — there is no per-user resource owner — so even the token gate's job is metering/abuse-control, not authorization. Both sit behind one seam; the full OAuth 2.1 flow drops in later when a go-to-market strategy gives the auth model a subject to protect (deferred as Q22).

No BFF: with Postgres as the store and Shape C (ADR-011) composing the full regulatory stack in a single `get_regulations` SQL pass, the web app composites client-side. A BFF would duplicate server logic for no V1 benefit.

## Alternatives Considered

- **Local stdio server + REST shim on a Node PaaS (the original roadmap framing).** Rejected: a stdio server cannot exercise the authenticated-MCP spec, and a REST shim is not the MCP transport, weakening the canonical-interface claim.
- **Remote Streamable HTTP on a Node host (Railway/Fly), not Workers.** Rejected as the primary path: it keeps the direct-Postgres assumption intact but forces hand-rolling and securing an OAuth 2.1 server and session management — a maintained security surface — and is a weaker reference pattern. Its one advantage (no edge-Postgres amendment) is outweighed; the amendment is handled by ADR-024.
- **Full OAuth 2.1 authorization-code in V1.** Rejected: ceremonial human-consent for data with no resource owner; over-builds against GTM uncertainty.

## Consequences

### Positive

- Spec-conformant remote authenticated MCP server — the recognizable reference pattern (Linear, the Cloudflare MCP cohort) and the stronger portfolio/production signal.
- Production primitives (edge autoscale, managed-OAuth upgrade path, WAF/rate-limiting, no cold-start) available from V1.
- Stateless design is forward-compatible with the 2026-07-28 spec direction.

### Negative

- **Diverges from the roadmap's original M3 framing.** The roadmap M3 section is updated to match; this ADR records the divergence and its production-intent driver.
- **Requires the ADR-024 edge-runtime Postgres amendment** (workerd is not Node; the direct `pg` pool assumption does not hold).
- **New-platform surface** (Workers, Wrangler, KV) and its learning curve, against the Q6 caution about a second unfamiliar platform — mitigated by starting from Cloudflare's remote-MCP template.
- **CORS becomes an M3 server concern** (browser → Worker direct, from the no-BFF decision).
- OAuth machinery, when added, is a slightly off-label fit for public data (metering, not authorization).

### Neutral

- A stdio path is retained via `mcp-remote`, a transitional bridge that may be retired as clients gain native remote-MCP support.
- The full GTM-determined production auth model is deferred (Q22).

## Links

- [ADR-002](ADR-002-mcp-canonical-interface.md) — the canonical-interface commitment this serves
- [ADR-003](ADR-003-ingestion-upstream-offline.md) / [ADR-024](ADR-024-edge-runtime-postgres-access.md) — the serving read path on the edge runtime
- [ADR-011](ADR-011-shape-c-response-envelope.md) — Shape C composing the full stack server-side (the no-BFF basis)
- [ADR-013](ADR-013-server-returns-structure-client-composes-presentation.md) — clients compose presentation
- [`docs/planning/prds/003-M3-canonical-interface.md`](../planning/prds/003-M3-canonical-interface.md) — the M3 PRD this posture anchors
- [`docs/roadmap.md`](../roadmap.md) §"M3 — Canonical interface live" — the evolved roadmap section
- [`docs/open-questions.md`](../open-questions.md) — Q5, Q6 (resolved here); Q22 (deferred production auth model)
