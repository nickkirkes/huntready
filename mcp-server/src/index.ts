import { createMcpHandler } from "agents/mcp";

import { createMcpServer } from "./server.js";
import { handleRequest } from "./router.js";

interface Env {
  // SELECT-only-role DSN, held as a Workers Secret.
  // Set via: `wrangler secret put SUPABASE_READONLY_DSN`
  // Local dev: add `SUPABASE_READONLY_DSN=<dsn>` to the gitignored `.dev.vars`.
  // S08.2 wires the credential; S08.3 adds the live health-check call site.
  SUPABASE_READONLY_DSN: string;

  // Optional internal-only liveness token (Workers Secret). When UNSET, the
  // /healthz endpoint is DISABLED (returns 404, never opens a DB connection) so
  // the open public V1 endpoint exposes no unauthenticated DB-hitting path —
  // closing a connection-exhaustion / liveness-disclosure vector. When SET, a
  // /healthz request must present `Authorization: Bearer <token>`; anything else
  // gets 404 (the endpoint's existence is not disclosed). This is a liveness
  // gate, NOT an auth boundary (real auth is S08.4 / Q22).
  // Set via: `wrangler secret put HEALTHCHECK_TOKEN`.
  HEALTHCHECK_TOKEN?: string;

  // Comma-separated list of allowed browser origins for CORS (e.g.
  // "https://app.huntready.io,https://staging.huntready.io"). Unset/absent = `*`
  // (permissive default for the open, read-only V1 endpoint; M4 tightens it
  // when the web app origin is known). NOT a secret (origins are not sensitive)
  // — may be a plain `vars` entry in wrangler.jsonc rather than a Workers Secret.
  CORS_ALLOWED_ORIGINS?: string;

  // Set to the string `"true"` to enable the wired-but-unenforced OAuth-2.1
  // auth seam (useful for tests or staging environments). Unset/absent = disabled
  // (the deployed V1 default — open endpoint, ADR-023). Q22 is the deferred
  // production-auth decision; `@cloudflare/workers-oauth-provider` is the named
  // drop-in for real enforcement when that decision is made.
  AUTH_SEAM_ENABLED?: string;

  // The test-fixture Bearer credential the auth seam checks when enabled.
  // Set via: `wrangler secret put AUTH_SEAM_TOKEN` (Workers Secret — never committed).
  // NOT a V1 enforcement boundary: the deployed endpoint is open, and on a single
  // open endpoint a token is unenforceable (a client can omit it and take the open
  // path). A browser-visible token would be exposed regardless. Do NOT cite this as
  // evidence of an enforced V1 auth boundary — see AUTH_SEAM_ENABLED above.
  AUTH_SEAM_TOKEN?: string;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    // Thin Worker shim: project `env` onto the pure dispatcher's RouterConfig and
    // inject a PER-REQUEST MCP handler. The 4-step dispatch order (preflight →
    // /healthz → auth seam → MCP) and CORS-on-every-response live in src/router.ts,
    // which is behaviourally unit-tested in tests/router.test.ts (router.ts imports
    // no workerd-only module, so it can run in the Node vitest pool — index.ts
    // cannot, because of `agents/mcp`).
    return handleRequest(
      request,
      {
        corsAllowedOrigins: env.CORS_ALLOWED_ORIGINS,
        authSeamEnabled: env.AUTH_SEAM_ENABLED,
        authSeamToken: env.AUTH_SEAM_TOKEN,
        healthcheckToken: env.HEALTHCHECK_TOKEN,
        readonlyDsn: env.SUPABASE_READONLY_DSN,
      },
      // PER-REQUEST INSTANTIATION (REQUIRED): SDK >=1.26 + stateless workerd both
      // require the MCP server + handler to be constructed inside the request flow,
      // never at module/global scope (workerd cannot safely share server/transport
      // state across concurrent invocations). This callback runs once per MCP
      // request; tests/boundary.test.ts locks the in-function call site.
      // createMcpHandler serves the MCP endpoint at the Agents-SDK default route
      // "/mcp"; E09/E10 and the MCP Inspector connect to "<origin>/mcp".
      (mcpRequest) => {
        const server = createMcpServer(env.SUPABASE_READONLY_DSN);
        const handler = createMcpHandler(server);
        return handler(mcpRequest, env, ctx);
      },
    );
  },
} satisfies ExportedHandler<Env>;
