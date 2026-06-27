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

## Test-harness baseline

S08.1 establishes the serving test harness (vitest, Node pool) with a baseline of **14 passing tests** — the serving analog of the Python `pytest` baseline the project tracks. E09/E10 grow this count additively.

The harness is Node-pool: tests exercise the MCP server factory (`createMcpServer`) and scan source/config files. They do not import `src/index.ts`, which imports the workerd-only `agents/mcp` package. The deployed Streamable-HTTP transport handshake (the `initialize` + `tools/list` exchange against the live Worker) is verified by the Group B MCP Inspector run.

Test file breakdown:

| File | Tests | What it covers |
|------|-------|----------------|
| `tests/server.test.ts` | 5 | Protocol conformance: `initialize` handshake identity, tools capability declared, `protocolVersion` owned by the SDK, `tools/list` returns `[]` (registry-empty lock, public protocol only), per-request freshness |
| `tests/boundary.test.ts` | 9 | Config safety + architectural invariants: no Durable Objects in `wrangler.jsonc`, no ingestion imports in `src/`, per-request server instantiation locked in `src/index.ts`, no hard-coded `protocolVersion` |
