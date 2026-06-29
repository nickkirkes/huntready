# HuntReady MCP Server

## Overview

HuntReady MCP server — the canonical read interface (ADR-002). Remote **Streamable HTTP** transport on **Cloudflare Workers** via the Agents SDK's stateless `createMcpHandler` (no Durable Objects — V1 MCP tools are stateless reads, ADR-023). Built against the MCP **2025-11-25 stable** spec, stateless (no `Mcp-Session-Id` reliance) so a future spec RC is an SDK upgrade, not a rewrite. The MCP server + transport are constructed **per request** (SDK ≥1.26 + workerd requirement).

Factory: `src/server.ts` (`createMcpServer`). Entrypoint: `src/index.ts`. Config: `wrangler.jsonc`. Tests: `tests/`.

## Local development

- `npm install` — install dependencies.
- `npm run dev` — run the Worker locally (`wrangler dev`).
- `npm run lint` — typecheck (`tsc --noEmit`, strict, no `any`).
- `npm test` — run the test suite (vitest).
- `npm run test:ci` — CI test invocation (verbose reporter).

## Connecting a stdio-only client via `mcp-remote`

A stdio-only MCP client (e.g. Claude Desktop) connects to the remote Worker through the `mcp-remote` proxy. Point the client at the deployed Worker's `/mcp` endpoint:

```
npx -y mcp-remote https://<worker-preview-url>/mcp
```

**Note:** this is a documented note for E08. A committed client-config snippet (e.g. `claude_desktop_config.json` fragment) is deferred to a later milestone story (E11/S11.4). No code stub ships in S08.1.

## Deploy + remote verification (Group B)

- `npm run deploy` — deploy to a Cloudflare Workers preview (`wrangler deploy`). This is an operator/human action, not part of the at-merge close.
- Connect the **MCP Inspector** (or an equivalent remote MCP client) to the preview URL over Streamable HTTP and complete `initialize` + `tools/list` (expect an **empty** tools array — E08 registers no public tools yet). This is the S08.1 Group B verification, captured in the E08 working note.

## Database access (S08.2)

The single read path from the serving stack to the database is `src/db.ts` (`createDbClient`). It uses `postgres.js` (the `postgres` npm package) over the Postgres wire protocol, connecting to Supabase's Supavisor transaction-mode pooler with a SELECT-only role.

### Credential setup

The SELECT-only-role DSN is **never committed**. For deployed environments, set it as a Workers Secret:

```sh
# Run from mcp-server/
wrangler secret put SUPABASE_READONLY_DSN
```

For local `wrangler dev`, create a gitignored `.dev.vars` file in `mcp-server/`:

```
SUPABASE_READONLY_DSN=postgresql://huntready_readonly:<password>@<project-ref>.pooler.supabase.com:6543/postgres?sslmode=require
```

Never commit `.dev.vars`. It is listed in the project `.gitignore`.

### Role provisioning

The `huntready_readonly` role and its SELECT grant are **not** a Supabase migration — apply the GRANT SQL by hand on each environment:

```sh
supabase db query --db-url "$DATABASE_URL" < supabase/grant-readonly-role.sql
```

Then set the role password out of band:

```sql
ALTER ROLE huntready_readonly PASSWORD '<generated>';
```

See [`docs/planning/epics/E08-confidence-findings/S08.2.md`](../docs/planning/epics/E08-confidence-findings/S08.2.md) §6 for the full Group B operator runbook, including the FORCE-RLS verification step and the `extensions.ST_*` search-path check.

### Internal health check (`/healthz`) — S08.3

The Worker serves an internal smoke endpoint at `/healthz` (a real DB read + a Shape C envelope round-trip). It is **disabled by default**: with no `HEALTHCHECK_TOKEN` configured it returns `404` and opens **no** DB connection, so the open public endpoint never exposes an unauthenticated, DB-hitting path. It is a **liveness gate, not an auth boundary** (real auth is S08.4 / Q22).

To enable it, provision the secret and call the endpoint with a bearer token:

```sh
# Run from mcp-server/
wrangler secret put HEALTHCHECK_TOKEN
# then:
curl -H "Authorization: Bearer <token>" https://<worker-url>/healthz
# → 200 {"ok":true,...} healthy, 503 unhealthy
```

For local `wrangler dev`, add `HEALTHCHECK_TOKEN=<token>` to the gitignored `.dev.vars`. `runHealthCheck` is also exercised directly by `tests/health-check.test.ts`, so the gate costs no test coverage.

### Local live-DB tests

The five live database tests in `tests/db.test.ts` require a PostGIS container with the substrate and role applied. Without `TEST_READONLY_DSN` set they skip cleanly. To run them locally, start the container, apply `tests/fixtures/ci-substrate.sql` and `supabase/grant-readonly-role.sql`, set the password, then:

```sh
TEST_READONLY_DSN=postgresql://huntready_readonly:<password>@localhost:5432/huntready_test npm test
```

The CI workflow (`.github/workflows/ci.yml`) provisions the container and runs these tests automatically on every push/PR.

---

## Test-harness baseline

S08.1 establishes the serving test harness (vitest, Node pool) with a baseline of **15 passing tests** — the serving analog of the Python `pytest` baseline the project tracks. E09/E10 grow this count additively.

The harness is Node-pool: tests exercise the MCP server factory (`createMcpServer`) and scan source/config files. They do not import `src/index.ts`, which imports the workerd-only `agents/mcp` package. The deployed Streamable-HTTP transport handshake (the `initialize` + `tools/list` exchange against the live Worker) is verified by the Group B MCP Inspector run.

Test file breakdown:

| File | Tests | What it covers |
|------|-------|----------------|
| `tests/server.test.ts` | 6 | Protocol conformance: `initialize` handshake identity, tools capability declared, `protocolVersion` owned by the SDK, `tools/list` returns `[]` (registry-empty lock, public protocol only), additive `McpServer.tool()` extension works without conflict (E09/E10 contract), per-request freshness |
| `tests/boundary.test.ts` | 9 | Config safety + architectural invariants: no Durable Objects in `wrangler.jsonc`, no ingestion imports in `src/`, per-request server instantiation locked in `src/index.ts`, no hard-coded `protocolVersion` |
