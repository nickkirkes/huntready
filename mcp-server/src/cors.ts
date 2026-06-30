/**
 * Pure CORS module for the HuntReady MCP server (S08.4).
 *
 * This module uses ONLY Web Fetch API types (`Request`, `Response`, `Headers`,
 * `URL`) — no `agents/mcp` import, no `Env` interface, no Node-only types.
 * It is unit-testable in the Node vitest pool following the established
 * `src/server.ts` / `src/health-check.ts` / `src/db.ts` pure-module pattern.
 *
 * CORS must be re-applied as a layer on top of every response, including:
 *   - The `Response` returned by `createMcpHandler()`, which is built inside
 *     the Cloudflare Agents SDK and knows nothing about the caller's CORS policy.
 *   - The `/healthz` response built in `src/health-check.ts`.
 *   - 404 and other error responses built inline in `src/index.ts`.
 *
 * Why we NEVER set `Access-Control-Allow-Credentials`:
 *   MCP clients authenticate via the `Authorization` bearer header, not
 *   cookies, so credentials mode (`withCredentials: true`) is never needed.
 *   More critically: the combination of `Access-Control-Allow-Origin: *` and
 *   `Access-Control-Allow-Credentials: true` is silently rejected by all
 *   browsers (it violates the CORS spec — CWE-class CORS misconfiguration).
 *   Omitting the header keeps the wildcard default safe for the open V1 endpoint.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Methods the MCP server handles or advertises. */
const ALLOWED_METHODS = "GET, POST, OPTIONS";

/**
 * Headers MCP clients are permitted to send.
 *   - `Authorization` — bearer token for the OAuth-2.1 auth seam (ADR-023).
 *   - `Content-Type` — required for JSON-RPC POST bodies.
 *   - `MCP-Protocol-Version` — spec-required negotiation header.
 *   - `Accept` — content-type preference (e.g. `text/event-stream` for SSE).
 */
const ALLOWED_HEADERS =
  "Authorization, Content-Type, MCP-Protocol-Version, Accept";

/**
 * Headers the browser is permitted to expose to JS in cross-origin responses.
 * `WWW-Authenticate` is NOT a CORS-safelisted response header, so without it
 * here a browser `fetch()` can read a 401's status but NOT its
 * `WWW-Authenticate` value — which would hide the OAuth-2.1 / RFC 9728
 * `resource_metadata` discovery hint from exactly the browser MCP clients the
 * auth seam exists to support. Listing it is harmless on responses that don't
 * carry it (the browser simply has nothing to expose).
 *   - `Mcp-Session-Id` — returned by `createMcpHandler` on session creation;
 *     clients need to read it in order to resume sessions.
 *   - `WWW-Authenticate` — emitted by the auth-seam 401 (`buildUnauthorizedResponse`);
 *     OAuth-2.1 clients read it to discover the protected-resource-metadata URL.
 */
const EXPOSE_HEADERS = "Mcp-Session-Id, WWW-Authenticate";

/**
 * Preflight cache lifetime in seconds (24 hours).
 * Reduces the number of preflight round-trips for long-lived browser sessions.
 */
const MAX_AGE = "86400";

// ---------------------------------------------------------------------------
// Exported functions
// ---------------------------------------------------------------------------

/**
 * Build a `Headers` object carrying the CORS response headers appropriate for
 * the given request origin and server origin policy.
 *
 * Origin policy logic:
 *   - `allowedOrigins` is `undefined`, empty string, or the literal `"*"`
 *     → permissive default: `Access-Control-Allow-Origin: *`.
 *     This is the correct V1 posture for the open, read-only endpoint (ADR-023).
 *   - Otherwise `allowedOrigins` is parsed as a comma-separated list (each
 *     entry trimmed, empties dropped). If `requestOrigin` is non-null AND
 *     exactly matches an entry → echo the origin back and add `Vary: Origin`
 *     (per-origin reflection, required by the CORS spec when echoing).
 *   - No match → `Access-Control-Allow-Origin` is NOT set (browser blocks the
 *     response — the correct deny behavior) but `Vary: Origin` IS set so CDN
 *     layers do not cache a denied response and serve it to a permitted origin.
 *
 * The returned `Headers` object never includes `Access-Control-Allow-Credentials`
 * (see module-level docstring for the rationale).
 *
 * @param requestOrigin - The value of the `Origin` request header, or `null`
 *   if the header was absent (e.g. same-origin or non-browser request).
 * @param allowedOrigins - The `CORS_ALLOWED_ORIGINS` environment variable value,
 *   or `undefined` when the variable is unset.
 */
export function buildCorsHeaders(
  requestOrigin: string | null,
  allowedOrigins: string | undefined,
): Headers {
  const headers = new Headers();

  // ── Origin policy ──────────────────────────────────────────────────────────
  // Decide by the TRIMMED raw value, so incidental whitespace cannot flip the
  // policy AND a malformed value cannot silently widen it. Three cases:
  //   (1) unset / empty / whitespace-only       → permissive ("*"): the
  //       documented "no policy configured" default for the open, read-only V1
  //       endpoint. Whitespace-only is treated as blank/unset BY DESIGN (NOT as a
  //       malformed restriction): incidental whitespace around the env var (a
  //       dashboard var / `.dev.vars`) must not silently flip the intended
  //       permissive default into deny-all. CORS is not a V1 security boundary
  //       (public data; tightened at M4), so "blank → open default" is correct
  //       here rather than fail-closed.
  //   (2) `*` present as any entry              → permissive ("*"): an explicit
  //       allow-all (handles "*", " * ", "https://a, *").
  //   (3) a present, non-blank value            → restricted to the parsed
  //       origins. A value that is genuinely a botched LIST — commas but ZERO
  //       valid origins (e.g. ",") — DOES fail CLOSED (deny-all), never a silent
  //       "*"; that case is distinct from the blank value in (1).
  const trimmedRaw = allowedOrigins?.trim() ?? "";

  if (trimmedRaw === "") {
    // (1) unset / empty / whitespace-only → permissive.
    headers.set("Access-Control-Allow-Origin", "*");
    // No Vary: Origin on the uniform wildcard response (avoids CDN fragmentation).
  } else {
    const entries = trimmedRaw
      .split(",")
      .map((o) => o.trim())
      .filter((o) => o.length > 0);

    if (entries.includes("*")) {
      // (2) explicit allow-all.
      headers.set("Access-Control-Allow-Origin", "*");
    } else {
      // (3) restricted. Set Vary: Origin so CDN/proxy layers always cache
      // per-origin — even for denied requests — preventing a cached denial from
      // being served to a permitted origin on the next hit.
      headers.set("Vary", "Origin");

      if (requestOrigin !== null && entries.includes(requestOrigin)) {
        // Exact-match: echo the request origin back (per-origin reflection).
        headers.set("Access-Control-Allow-Origin", requestOrigin);
      }
      // No match — OR a malformed value that parsed to zero valid origins —
      // leaves Access-Control-Allow-Origin absent: the browser blocks the
      // response (fail-closed deny, never a silent widen to "*").
    }
  }

  // ── Always-present headers ─────────────────────────────────────────────────
  // Allow-Methods / Allow-Headers / Max-Age are preflight-RESPONSE headers per
  // the Fetch standard — browsers read them only on the OPTIONS preflight and
  // ignore them on simple (non-preflight) responses. We emit them uniformly on
  // every response for simplicity (the idiomatic middleware default); this is
  // harmless, never misleading to a browser, only to an auditor reading raw
  // headers. Expose-Headers DOES apply to simple responses (it controls which
  // response headers cross-origin JS may read), so it belongs here regardless.
  headers.set("Access-Control-Allow-Methods", ALLOWED_METHODS);
  headers.set("Access-Control-Allow-Headers", ALLOWED_HEADERS);
  headers.set("Access-Control-Expose-Headers", EXPOSE_HEADERS);
  headers.set("Access-Control-Max-Age", MAX_AGE);

  return headers;
}

/**
 * Return `true` iff `request` is a CORS preflight request.
 *
 * A genuine preflight requires all three of:
 *   1. `OPTIONS` method.
 *   2. An `Origin` header (identifies the cross-origin caller).
 *   3. An `Access-Control-Request-Method` header (names the actual method).
 *
 * A bare `OPTIONS` without those headers is a plain HTTP OPTIONS request
 * (e.g. a health-check or an HTTP/1.1 OPTIONS *) and must NOT be treated
 * as a CORS preflight — doing so would short-circuit handler dispatch.
 */
export function isCorsPreflightRequest(request: Request): boolean {
  return (
    request.method === "OPTIONS" &&
    request.headers.has("Origin") &&
    request.headers.has("Access-Control-Request-Method")
  );
}

/**
 * Return a NEW `Response` that preserves `response.status`, `response.statusText`,
 * and `response.body`, with CORS headers layered on top of the original headers.
 *
 * This function exists because `createMcpHandler()` returns its own `Response`
 * that knows nothing about the caller's CORS policy — CORS must be re-applied
 * on the way out for every response path (MCP handler, `/healthz`, 404s, etc.).
 *
 * Body preservation:
 *   Passing `response.body` (a `ReadableStream | null`) directly to the
 *   `Response` constructor does NOT buffer or consume the stream — the stream
 *   is transferred by reference. This is critical for the MCP SSE stream
 *   returned by `createMcpHandler`, which may be an unbounded event source.
 *
 * Header merge strategy:
 *   Start from `response.headers` (original), then apply each CORS header on
 *   top. CORS wins on key collision — this prevents an upstream handler from
 *   accidentally overriding the CORS policy with its own (possibly wrong)
 *   `Access-Control-Allow-Origin` header. The ONE exception is `Vary`, which is
 *   a list-valued cache-key header: it is MERGED (existing tokens preserved +
 *   `Origin` added) rather than overwritten, so an upstream `Vary` (e.g.
 *   `Accept-Encoding`) is not dropped — dropping it would let a shared cache
 *   serve a variant generated for the wrong request headers.
 *
 * @param response   - The upstream response whose status/body should be kept.
 * @param corsHeaders - The CORS headers produced by `buildCorsHeaders`.
 */
export function applyCorsHeaders(
  response: Response,
  corsHeaders: Headers,
): Response {
  // Build merged headers: original first, then CORS on top.
  const merged = new Headers(response.headers);
  corsHeaders.forEach((value, key) => {
    if (key.toLowerCase() === "vary") {
      // Merge, don't overwrite — preserve any upstream Vary tokens.
      merged.set("Vary", mergeVary(merged.get("Vary"), value));
    } else {
      merged.set(key, value);
    }
  });

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: merged,
  });
}

/**
 * Combine an existing `Vary` header value with additional token(s) without
 * dropping any upstream values. `Vary` controls how shared caches key a
 * response; overwriting it (e.g. replacing an upstream `Vary: Accept-Encoding`
 * with `Vary: Origin`) can make a cache serve a variant generated for the wrong
 * request headers. Tokens are de-duplicated case-insensitively, preserving the
 * existing order/casing; a `*` token in either input short-circuits to `*` (the
 * response varies on everything).
 */
function mergeVary(existing: string | null, addition: string): string {
  const parse = (raw: string): string[] =>
    raw
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

  const existingTokens = parse(existing ?? "");
  const additionTokens = parse(addition);

  if (existingTokens.includes("*") || additionTokens.includes("*")) {
    return "*";
  }

  const result = [...existingTokens];
  for (const token of additionTokens) {
    if (!result.some((t) => t.toLowerCase() === token.toLowerCase())) {
      result.push(token);
    }
  }
  return result.join(", ");
}
