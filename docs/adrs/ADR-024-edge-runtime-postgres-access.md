# ADR-024: Edge-Runtime Postgres Access for the Serving Stack

**Date:** 2026-06-24
**Status:** Proposed
**Decider:** Nick Kirkes
**Tags:** storage, mcp

> Status note: `Proposed` pre-implementation per `docs/adrs/README.md` §"Status". Refines [ADR-003](ADR-003-ingestion-upstream-offline.md) for the edge-runtime serving deployment chosen in [ADR-023](ADR-023-remote-mcp-server-posture.md); it does not change ADR-003's upstream/offline principle. Flips to `Accepted` when E08 ships the access layer (the concrete driver is the E08 spike's deliverable).

---

## Context

ADR-003 establishes that the serving stack only *reads* from Supabase Postgres, and ADR-003's consequences assume "read-only SQL against a shared database" from a long-running Node process with a direct `pg` connection pool. ADR-023 deploys the M3 serving stack on **Cloudflare Workers**, which run on the `workerd` runtime — not Node. The direct `pg` pool does not run on `workerd`, so the read path needs a workerd-compatible mechanism. Separately, ADR-003's "read-only" is stated as a property but never enforced: the Supabase service-role key bypasses RLS and can write, which is an unnecessary risk surface on a public API.

## Decision

The serving stack reaches Postgres from the Workers edge runtime via **either Cloudflare Hyperdrive or the Supabase serverless/HTTP driver — chosen by an E08 spike** — over a **read-only-enforced connection: a dedicated SELECT-only Postgres role, not the write-capable service-role key.** Hyperdrive query-caching, if enabled, is short-TTL and purged on re-ingestion. This refines ADR-003's read path for the edge runtime; the upstream/offline ingestion separation is unchanged.

## Reasoning

`workerd` is not Node, so the existing direct-`pg`-pool assumption is incompatible; Hyperdrive (edge connection-pooling plus optional query-caching) and the Supabase serverless/HTTP driver are the two workerd-compatible options. PostGIS `ST_*` execution is unaffected either way — it runs server-side in Postgres; only the connection mechanism changes. The concrete choice has real cost and caching differences that are clearer after a hands-on spike, so it is deliberately deferred to E08 and recorded there as an addendum to this ADR.

Read-only is made an *enforcement*, not a convention. A dedicated SELECT-only role (a `GRANT`, not an RLS-policy change — so it does not touch the deny-all posture) means a serving-path defect or injection cannot mutate data. This is strictly safer than connecting as the write-capable service-role.

Caching is bounded by freshness. Regulatory freshness is a correctness property (ADR-001 / the response's `meta.freshness`); a cached-stale season window is an authority defect, not just a performance footnote. So V1 runs Hyperdrive caching off or short-TTL, with a cache purge built into the re-ingestion/deploy runbook. Default-on caching is not assumed.

## Alternatives Considered

- **Keep the direct `pg` pool on a long-running Node host.** Rejected here because that means *not* deploying on Workers — i.e., the ADR-023 fork already weighed and declined. The Postgres-assumption convenience does not outweigh ADR-023's posture benefits.
- **Connect as the service-role key directly.** Rejected: write-capable on a public-facing surface; a defect becomes a write. The SELECT-only role removes the capability entirely.
- **Supabase client over PostgREST.** Rejected: PostgREST is structurally disabled by the deny-all RLS posture (ADR-004), and the serving tools want raw SQL and PostGIS, not a REST query builder.

## Consequences

### Positive

- The serving stack runs on Workers (ADR-023) with a workerd-compatible read path.
- Read access is write-incapable by construction, not by discipline.
- Edge connection-pooling (and bounded caching) is available for a read-heavy public API; PostGIS is unaffected.

### Negative

- A dedicated SELECT-only Postgres role is a small role-provisioning step on Supabase.
- Hyperdrive (if chosen) is new infrastructure to configure, and its caching must be freshness-bounded.
- The concrete driver is an open spike at this ADR's acceptance — the ADR commits the *principle* (edge-runtime, read-only-enforced); the driver is E08's addendum.

### Neutral

- ADR-003's upstream/offline ingestion separation is unchanged; this refines only the serving read path.
- Interacts with Q14 (Supabase key-format migration): the read connection adopts the current key format during E08.

## Links

- [ADR-003](ADR-003-ingestion-upstream-offline.md) — the read-from-Postgres principle this refines for the edge runtime
- [ADR-004](ADR-004-supabase-postgres-postgis.md) — Supabase + PostGIS; PostgREST disabled by RLS
- [ADR-023](ADR-023-remote-mcp-server-posture.md) — the Cloudflare Workers deployment that requires this
- [`docs/planning/prds/003-M3-canonical-interface.md`](../planning/prds/003-M3-canonical-interface.md) — M3 scope (E07 records the principle; E08 picks the driver)
- [`docs/open-questions.md`](../open-questions.md) — Q14 (Supabase key migration)
