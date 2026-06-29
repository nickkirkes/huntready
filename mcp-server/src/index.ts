import { createMcpHandler } from "agents/mcp";

import { buildCorsHeaders, isCorsPreflightRequest, applyCorsHeaders } from "./cors.js";
import { isAuthSeamEnabled, isAuthorized, buildUnauthorizedResponse } from "./auth.js";
import { createMcpServer } from "./server.js";
import { runHealthCheck } from "./health-check.js";

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
    // Compute CORS headers once for the entire request. Every response path —
    // preflight, auth seam 401, /healthz, and the MCP handler — applies them.
    const requestOrigin = request.headers.get("Origin");
    const corsHeaders = buildCorsHeaders(requestOrigin, env.CORS_ALLOWED_ORIGINS);

    // Parse the URL once; reused by the auth seam and /healthz block below.
    const url = new URL(request.url);

    // ── Step 1: CORS preflight short-circuit ───────────────────────────────────
    // Must come BEFORE the auth seam: an OPTIONS preflight carries no credentials
    // (RFC 6454), so 401'ing it would break every browser MCP client.
    if (isCorsPreflightRequest(request)) {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    // ── Step 2: Auth seam ──────────────────────────────────────────────────────
    // One gated code path toggled by AUTH_SEAM_ENABLED. Wired but unenforced in
    // the deployed V1 endpoint (ADR-023). Runs after preflight, before /healthz
    // and /mcp, so both internal and MCP routes require a credential when enabled.
    if (isAuthSeamEnabled(env.AUTH_SEAM_ENABLED) && !isAuthorized(request, env.AUTH_SEAM_TOKEN)) {
      return buildUnauthorizedResponse(url, corsHeaders);
    }

    // ── Step 3: /healthz ───────────────────────────────────────────────────────
    // Internal smoke endpoint (DB read + Shape C envelope round-trip).
    // NOT an MCP tool; tools/list stays empty. Gated by an internal token so it
    // is not a public, unauthenticated, DB-hitting path: disabled (404) unless
    // HEALTHCHECK_TOKEN is configured AND presented as a Bearer credential. The
    // DSN is never included in the response body. runHealthCheck itself is
    // exercised directly by tests/health-check.test.ts, so this gate costs no
    // test coverage.
    if (url.pathname === "/healthz") {
      const expected = env.HEALTHCHECK_TOKEN;
      const presented = request.headers.get("authorization");
      if (!expected || presented !== `Bearer ${expected}`) {
        // 404 (not 401) so an unauthorized caller cannot even confirm the
        // endpoint exists.
        return applyCorsHeaders(new Response("Not found", { status: 404 }), corsHeaders);
      }
      try {
        const health = await runHealthCheck(env.SUPABASE_READONLY_DSN);
        return applyCorsHeaders(
          new Response(JSON.stringify(health), {
            status: health.ok ? 200 : 503,
            headers: { "content-type": "application/json" },
          }),
          corsHeaders,
        );
      } catch {
        // runHealthCheck can throw rather than return an error-shaped result
        // (e.g. postgres.js throwing synchronously on a malformed DSN). Without
        // this catch the throw becomes a platform 500 with NO CORS headers — a
        // browser-origin monitor would see an opaque CORS error instead of a
        // readable 503. The error detail is intentionally not surfaced (the DSN
        // must never appear in the body); the cause is in Worker logs.
        return applyCorsHeaders(
          new Response(JSON.stringify({ ok: false, error: "health check failed" }), {
            status: 503,
            headers: { "content-type": "application/json" },
          }),
          corsHeaders,
        );
      }
    }

    // ── Step 4: MCP handler ────────────────────────────────────────────────────
    // PER-REQUEST INSTANTIATION (REQUIRED): SDK >=1.26 + stateless workerd both require
    // the MCP server + handler to be constructed inside fetch, never in module/global
    // scope. workerd cannot safely share server/transport state across concurrent
    // invocations. tests/boundary.test.ts locks this via a source scan.
    const server = createMcpServer();
    // createMcpHandler serves the MCP endpoint at the default route "/mcp"; any other
    // path returns 404. The route is the Agents-SDK default (not overridden here) — E09/E10
    // and the MCP Inspector connect to "<origin>/mcp".
    const handler = createMcpHandler(server);
    try {
      const response = await handler(request, env, ctx);
      return applyCorsHeaders(response, corsHeaders);
    } catch {
      // A throw/rejection from the MCP handler would otherwise surface as a
      // platform 500 with NO CORS headers — invisible to a browser MCP client
      // as an opaque CORS error rather than a readable failure. Return a
      // CORS-headered 500 with a generic body so the failure is legible.
      return applyCorsHeaders(
        new Response("Internal Server Error", { status: 500 }),
        corsHeaders,
      );
    }
  },
} satisfies ExportedHandler<Env>;
