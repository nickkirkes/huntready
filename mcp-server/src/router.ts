/**
 * Pure request dispatcher for the HuntReady MCP Worker (S08.4).
 *
 * This module owns the 4-step dispatch order — CORS preflight, the internal
 * /healthz endpoint, the OAuth-2.1 auth seam, and the MCP handler — as a single
 * pure function. It imports ONLY the pure helper modules (`cors`, `auth`,
 * `health-check`) and NOT `agents/mcp` (workerd-only), so the whole dispatch is
 * unit-testable BY BEHAVIOR in the Node vitest pool: the MCP handler is injected
 * as a callback rather than constructed here. `src/index.ts` is the thin Worker
 * shim that wires `env` into a `RouterConfig` and supplies the per-request MCP
 * handler; the ordering correctness lives here, behaviourally locked by
 * `tests/router.test.ts` (which replaces the brittle source-order AST assertion).
 */
import {
  buildCorsHeaders,
  isCorsPreflightRequest,
  applyCorsHeaders,
} from "./cors.js";
import {
  isAuthSeamEnabled,
  isAuthorized,
  buildUnauthorizedResponse,
} from "./auth.js";
import { runHealthCheck } from "./health-check.js";

/**
 * Environment-derived configuration for the dispatcher. `index.ts` projects the
 * Worker `Env` onto this shape so the dispatcher never sees the `Env` interface
 * (which transitively couples to `agents/mcp`) and stays pure.
 */
export interface RouterConfig {
  /** Comma-separated allowed CORS origins, or undefined for the permissive `*` default. */
  corsAllowedOrigins: string | undefined;
  /** `"true"` enables the wired-but-unenforced auth seam; anything else leaves it disabled. */
  authSeamEnabled: string | undefined;
  /** The Bearer credential the seam checks when enabled (test fixture, not a V1 boundary). */
  authSeamToken: string | undefined;
  /** The /healthz Bearer credential; when undefined /healthz is disabled (404, no DB). */
  healthcheckToken: string | undefined;
  /** SELECT-only-role DSN used by the /healthz DB read. */
  readonlyDsn: string;
}

/**
 * The MCP request handler, injected so this module never imports `agents/mcp`.
 * `index.ts` supplies a per-request instance (`createMcpServer()` →
 * `createMcpHandler()`); tests supply a stub.
 */
export type McpHandler = (request: Request) => Promise<Response>;

/**
 * Dispatch a request through the 4 ordered stages, applying CORS to every
 * response path.
 *
 * Order (load-bearing for correctness):
 *   1. CORS preflight — must be FIRST: an OPTIONS preflight carries no
 *      credentials (RFC 6454), so 401'ing it would break every browser MCP
 *      client. It short-circuits before any auth.
 *   2. /healthz — the internal liveness endpoint, handled BEFORE the auth seam.
 *      It has its OWN independent token gate (HEALTHCHECK_TOKEN). A request
 *      carries a single `Authorization` bearer value, so sequencing /healthz
 *      behind the seam would require that one header satisfy BOTH the seam token
 *      AND the healthz token — making /healthz unreachable whenever the two
 *      secrets differ. /healthz is not an MCP route, so the MCP auth seam does
 *      not apply to it; the two gates are orthogonal by design.
 *   3. Auth seam — gates the MCP endpoint. Wired but unenforced in deployed V1
 *      (ADR-023); enabled only in tests/staging.
 *   4. MCP handler — the canonical interface; constructed per request by the
 *      caller and injected here.
 */
export async function handleRequest(
  request: Request,
  config: RouterConfig,
  mcpHandler: McpHandler,
): Promise<Response> {
  // Compute CORS headers once; every response path applies them.
  const requestOrigin = request.headers.get("Origin");
  const corsHeaders = buildCorsHeaders(requestOrigin, config.corsAllowedOrigins);

  // Parse the URL once; reused by the /healthz pathname check below.
  const url = new URL(request.url);

  // ── Step 1: CORS preflight short-circuit ─────────────────────────────────────
  if (isCorsPreflightRequest(request)) {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  // ── Step 2: /healthz (own token gate; orthogonal to the auth seam) ───────────
  if (url.pathname === "/healthz") {
    return applyCorsHeaders(await handleHealthz(request, config), corsHeaders);
  }

  // ── Step 3: Auth seam (gates the MCP endpoint) ───────────────────────────────
  // One gated code path toggled by AUTH_SEAM_ENABLED. Disabled (open) in the
  // deployed V1 config (ADR-023); the credential is a test fixture, not a V1
  // enforcement boundary.
  if (
    isAuthSeamEnabled(config.authSeamEnabled) &&
    !isAuthorized(request, config.authSeamToken)
  ) {
    return buildUnauthorizedResponse(url, corsHeaders);
  }

  // ── Step 4: MCP handler ──────────────────────────────────────────────────────
  try {
    const response = await mcpHandler(request);
    return applyCorsHeaders(response, corsHeaders);
  } catch {
    // A throw/rejection from the MCP handler would otherwise surface as a
    // platform 500 with NO CORS headers — invisible to a browser MCP client as
    // an opaque CORS error rather than a readable failure. Return a CORS-headered
    // 500 with a generic body so the failure is legible.
    return applyCorsHeaders(
      new Response("Internal Server Error", { status: 500 }),
      corsHeaders,
    );
  }
}

/**
 * Handle a /healthz request. Returns a bare `Response` (the caller applies CORS).
 *
 * Gated by HEALTHCHECK_TOKEN: disabled (404, NO DB connection) unless the token
 * is configured AND presented as a Bearer credential, so the open public V1
 * endpoint exposes no unauthenticated DB-hitting path. The 404 (not 401) means
 * an unauthorized caller cannot even confirm the endpoint exists. The DSN is
 * never included in the response body.
 */
async function handleHealthz(
  request: Request,
  config: RouterConfig,
): Promise<Response> {
  const expected = config.healthcheckToken;
  const presented = request.headers.get("authorization");
  if (!expected || presented !== `Bearer ${expected}`) {
    return new Response("Not found", { status: 404 });
  }

  try {
    const health = await runHealthCheck(config.readonlyDsn);
    return new Response(JSON.stringify(health), {
      status: health.ok ? 200 : 503,
      headers: { "content-type": "application/json" },
    });
  } catch {
    // runHealthCheck can throw rather than return an error-shaped result (e.g.
    // postgres.js throwing synchronously on a malformed DSN). Surface a readable
    // 503 instead of letting the throw become a platform 500. The error detail is
    // intentionally not surfaced (the DSN must never appear in the body); the
    // cause is in Worker logs.
    return new Response(
      JSON.stringify({ ok: false, error: "health check failed" }),
      { status: 503, headers: { "content-type": "application/json" } },
    );
  }
}
