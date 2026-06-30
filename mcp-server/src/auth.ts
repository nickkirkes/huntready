/**
 * OAuth-2.1 auth-seam module for the HuntReady MCP server (S08.4).
 *
 * INTENT — wired but unenforced (ADR-023):
 *   The deployed V1 endpoint is a **single open, read-only MCP endpoint** with
 *   no enforced authentication (public data; consistent with the V1 scope).
 *   This module provides ONE middleware integration point — a gated code path
 *   that can be toggled via the `AUTH_SEAM_ENABLED` Workers Secret/binding.
 *
 * V1 BASELINE PROTECTION (not this module):
 *   With the seam unenforced, the deployed endpoint's baseline abuse protection
 *   is Cloudflare's ambient DDoS mitigation and WAF — a platform default of
 *   deploying on Cloudflare Workers, NOT a feature this module configures. Any
 *   ENFORCED token / tier / quota is V2 scope and needs a real boundary (a
 *   separate authenticated route or Cloudflare Access) — Q22, flag-don't-decide.
 *
 * TEST FIXTURE, NOT A V1 ENFORCEMENT BOUNDARY:
 *   The test credential (`AUTH_SEAM_TOKEN` Workers Secret) is a fixture that
 *   PROVES THE SEAM IS REAL — a test with the seam enabled verifies that an
 *   unauthenticated request is rejected and an authenticated one is admitted.
 *   It does NOT meter or gate production access. On a single open endpoint a
 *   token is unenforceable (a client can omit it and receive the open path),
 *   and a browser-visible token would be exposed anyway. Do NOT cite this
 *   module as evidence of an enforced V1 auth boundary.
 *
 * DROP-IN UPGRADE PATH (Q22, deferred):
 *   `@cloudflare/workers-oauth-provider` is the named drop-in for real
 *   OAuth-2.1 enforcement in a future M4/V2 milestone. It is NOT imported here
 *   and MUST NOT be added to this module — the full provider wraps the whole
 *   Worker and is an architectural change that warrants its own story. Any
 *   enforced token/tier/quota is V2 scope (flag-don't-decide per Q22).
 *
 * PORTABILITY:
 *   This module uses ONLY Web Fetch API types (`Request`, `Response`, `Headers`,
 *   `URL`). It does NOT import `agents/mcp` (workerd-only), the `Env` interface,
 *   `./cors.ts`, or any express-based SDK router. This makes it unit-testable in
 *   the Node vitest pool alongside `src/server.ts` and `src/health-check.ts`.
 */

// ---------------------------------------------------------------------------
// Auth-seam toggle
// ---------------------------------------------------------------------------

/**
 * Return `true` iff the AUTH_SEAM_ENABLED binding is set to the string `"true"`.
 *
 * Strict equality is intentional:
 *   - Absent / `undefined` → `false`  (deployed V1 default — seam disabled)
 *   - `"false"`, `"True"`, `"1"`, `""` → `false`
 *   - `"true"` → `true`
 *
 * The deployed V1 default is disabled. `AUTH_SEAM_ENABLED` is not set in
 * `wrangler.jsonc`, so production Workers never present the auth check. A test
 * suite or a future operator can enable it by setting the binding to `"true"`.
 *
 * @param authSeamEnabledRaw - Raw value of the `AUTH_SEAM_ENABLED`
 *   Workers Secret / `env` binding. Pass `undefined` when the binding is absent.
 */
export function isAuthSeamEnabled(
  authSeamEnabledRaw: string | undefined,
): boolean {
  return authSeamEnabledRaw === "true";
}

// ---------------------------------------------------------------------------
// Authorization check
// ---------------------------------------------------------------------------

/**
 * Return `true` iff the request's `Authorization` header matches the expected
 * Bearer token exactly.
 *
 * Fail-closed design — the function returns `false` (admits nobody) when:
 *   - `expectedToken` is `undefined` (the seam was enabled without a credential
 *     configured — refuse rather than silently open the endpoint).
 *   - `expectedToken` is the empty string (same logic: an empty credential is
 *     indistinguishable from an unset one and must not admit any request).
 *   - The `Authorization` header is absent or does not match
 *     `Bearer <expectedToken>` exactly.
 *
 * No timing-safe comparison is used here. The credential is a **test fixture
 * proving the seam is real**, NOT a V1 enforcement boundary. A constant-time
 * compare would be appropriate only when the token genuinely meters access
 * (V2 / Q22 scope). Using `===` keeps the implementation straightforwardly
 * auditable and avoids false-security implications.
 *
 * @param request      - The incoming Fetch API `Request`.
 * @param expectedToken - Raw value of the `AUTH_SEAM_TOKEN` Workers Secret,
 *   or `undefined` when the binding is absent.
 */
export function isAuthorized(
  request: Request,
  expectedToken: string | undefined,
): boolean {
  // Fail-closed: a missing or empty credential admits nobody.
  if (expectedToken === undefined || expectedToken === "") {
    return false;
  }

  const authorizationHeader = request.headers.get("Authorization");

  // Strict string equality — see module docstring for the timing-safe rationale.
  return authorizationHeader === `Bearer ${expectedToken}`;
}

// ---------------------------------------------------------------------------
// 401 response builder
// ---------------------------------------------------------------------------

/**
 * Build a `401 Unauthorized` response with an RFC 9728 / OAuth-2.1 shaped
 * `WWW-Authenticate` header.
 *
 * WWW-Authenticate shape:
 *   `Bearer realm="HuntReady MCP",
 *    resource_metadata="<origin>/.well-known/oauth-protected-resource"`
 *
 * The `resource_metadata` URI is derived from `requestUrl.origin` — never
 * hardcoded. This advertises the OAuth-2.1 Protected Resource Metadata
 * endpoint where a client can discover authorization server metadata. The
 * well-known endpoint itself is NOT implemented here (it is the Q22 drop-in);
 * only the pointer is advertised so a compliant OAuth-2.1 client receives the
 * correct discovery hint immediately.
 *
 * CORS headers (`corsHeaders`) are merged onto the 401 so that browsers
 * can read the response (a CORS preflight succeeds but the actual 401 must
 * also carry `Access-Control-Allow-Origin` for the browser to expose the body
 * and the `WWW-Authenticate` header to the JS client). The caller is
 * responsible for building `corsHeaders`; this function does not import
 * `./cors.ts` (portability constraint — see module docstring).
 *
 * @param requestUrl  - Parsed `URL` of the incoming request.  Used ONLY to
 *   derive `requestUrl.origin` for the `resource_metadata` URI.
 * @param corsHeaders - Pre-built CORS response headers from the caller
 *   (e.g. from `buildCorsHeaders` in `src/cors.ts`).  Merged as-is.
 */
export function buildUnauthorizedResponse(
  requestUrl: URL,
  corsHeaders: Headers,
): Response {
  // Derive the Protected Resource Metadata discovery URI from the request
  // origin — never hardcode a hostname so the seam works identically across
  // local dev, preview deploys, and production.
  const resourceMetadataUri = `${requestUrl.origin}/.well-known/oauth-protected-resource`;

  // RFC 9728 §3 / OAuth 2.0 Bearer Token challenge (RFC 6750 §3).
  // The `resource_metadata` parameter is the OAuth-2.1 drop-in surface that
  // lets a client locate the authorization server. The well-known endpoint is
  // NOT implemented in V1 (Q22 deferred); the pointer is emitted now so a
  // compliant client can query it once the endpoint exists.
  const wwwAuthenticate =
    `Bearer realm="HuntReady MCP", ` +
    `resource_metadata="${resourceMetadataUri}"`;

  // Merge caller-supplied CORS headers so browsers can read the 401 body and
  // the WWW-Authenticate header from a cross-origin JS client.
  const responseHeaders = new Headers(corsHeaders);
  responseHeaders.set("WWW-Authenticate", wwwAuthenticate);
  responseHeaders.set("Content-Type", "application/json");

  const body = JSON.stringify({
    error: "unauthorized",
    error_description: "Authentication required (auth seam enabled).",
  });

  return new Response(body, {
    status: 401,
    headers: responseHeaders,
  });
}
