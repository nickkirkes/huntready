/**
 * CORS module unit tests (S08.4).
 *
 * Covers all three exported functions:
 *   - buildCorsHeaders  — origin policy, always-present headers, no Credentials header
 *   - isCorsPreflightRequest — true/false discrimination across method/header combos
 *   - applyCorsHeaders  — status/body/header preservation; CORS wins on collision
 *
 * All tests are unconditional (no describe.skipIf, no live DB).
 * Request / Response / Headers / URL are available natively in the Node vitest pool.
 */
import { describe, it, expect } from "vitest";
import {
  buildCorsHeaders,
  isCorsPreflightRequest,
  applyCorsHeaders,
} from "../src/cors.js";

// ---------------------------------------------------------------------------
// buildCorsHeaders
// ---------------------------------------------------------------------------
describe("buildCorsHeaders", () => {
  // ── Permissive cases ────────────────────────────────────────────────────────

  it("null origin + undefined allowedOrigins → Access-Control-Allow-Origin: *", () => {
    const headers = buildCorsHeaders(null, undefined);
    expect(headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("null origin + empty-string allowedOrigins → permissive: Access-Control-Allow-Origin: *", () => {
    const headers = buildCorsHeaders(null, "");
    expect(headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("request origin + literal '*' allowedOrigins → permissive: Access-Control-Allow-Origin: *", () => {
    const headers = buildCorsHeaders("https://app.example.com", "*");
    expect(headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("permissive case does NOT set Vary: Origin (wildcard response is uniform — no CDN fragmentation)", () => {
    const headers = buildCorsHeaders(null, undefined);
    expect(headers.get("Vary")).toBeNull();
  });

  // ── Restricted + matching origin ────────────────────────────────────────────

  it("origin in allowedOrigins list → echoes the origin back", () => {
    const headers = buildCorsHeaders(
      "https://app.example.com",
      "https://app.example.com,https://other.example.com",
    );
    expect(headers.get("Access-Control-Allow-Origin")).toBe(
      "https://app.example.com",
    );
  });

  it("matching origin → sets Vary: Origin (required by CORS spec for per-origin reflection)", () => {
    const headers = buildCorsHeaders(
      "https://app.example.com",
      "https://app.example.com,https://other.example.com",
    );
    expect(headers.get("Vary")).toBe("Origin");
  });

  // ── Restricted + non-matching origin ───────────────────────────────────────

  it("origin NOT in allowedOrigins list → Access-Control-Allow-Origin is absent (deny)", () => {
    const headers = buildCorsHeaders(
      "https://evil.example.com",
      "https://app.example.com",
    );
    expect(headers.get("Access-Control-Allow-Origin")).toBeNull();
  });

  it("denied origin still sets Vary: Origin (prevents CDN serving a denial to a permitted origin)", () => {
    const headers = buildCorsHeaders(
      "https://evil.example.com",
      "https://app.example.com",
    );
    expect(headers.get("Vary")).toBe("Origin");
  });

  // ── Restricted + null origin (no Origin header sent) ───────────────────────

  it("null origin + restricted allowedOrigins → Access-Control-Allow-Origin is absent", () => {
    const headers = buildCorsHeaders(null, "https://app.example.com");
    expect(headers.get("Access-Control-Allow-Origin")).toBeNull();
  });

  it("null origin + restricted allowedOrigins → Vary: Origin still set", () => {
    const headers = buildCorsHeaders(null, "https://app.example.com");
    expect(headers.get("Vary")).toBe("Origin");
  });

  // ── Whitespace handling ─────────────────────────────────────────────────────

  it("whitespace around entries in allowedOrigins is trimmed: matching still works", () => {
    const headers = buildCorsHeaders(
      "https://app.example.com",
      " https://app.example.com , https://other.example.com ",
    );
    expect(headers.get("Access-Control-Allow-Origin")).toBe(
      "https://app.example.com",
    );
  });

  // ── Wildcard-vs-credentials trap (CWE-class CORS misconfiguration lock) ────

  it("permissive case: Access-Control-Allow-Credentials is NEVER set", () => {
    const headers = buildCorsHeaders(null, undefined);
    expect(headers.get("Access-Control-Allow-Credentials")).toBeNull();
  });

  it("restricted matching case: Access-Control-Allow-Credentials is NEVER set", () => {
    const headers = buildCorsHeaders(
      "https://app.example.com",
      "https://app.example.com",
    );
    expect(headers.get("Access-Control-Allow-Credentials")).toBeNull();
  });

  // ── Always-present headers ──────────────────────────────────────────────────

  it("Access-Control-Allow-Methods contains GET, POST, OPTIONS", () => {
    const headers = buildCorsHeaders(null, undefined);
    const methods = headers.get("Access-Control-Allow-Methods") ?? "";
    expect(methods).toContain("GET");
    expect(methods).toContain("POST");
    expect(methods).toContain("OPTIONS");
  });

  it("Access-Control-Allow-Headers contains Authorization, Content-Type, MCP-Protocol-Version", () => {
    const headers = buildCorsHeaders(null, undefined);
    const allowedHeaders = headers.get("Access-Control-Allow-Headers") ?? "";
    expect(allowedHeaders).toContain("Authorization");
    expect(allowedHeaders).toContain("Content-Type");
    expect(allowedHeaders).toContain("MCP-Protocol-Version");
  });

  it("Access-Control-Expose-Headers contains Mcp-Session-Id", () => {
    const headers = buildCorsHeaders(null, undefined);
    expect(headers.get("Access-Control-Expose-Headers")).toContain(
      "Mcp-Session-Id",
    );
  });

  it("Access-Control-Expose-Headers contains WWW-Authenticate (so browser fetch() can read the 401 OAuth-2.1 discovery hint)", () => {
    // WWW-Authenticate is NOT a CORS-safelisted response header, so it must be
    // exposed explicitly or a cross-origin browser client cannot read the
    // resource_metadata discovery pointer advertised by the auth-seam 401.
    const headers = buildCorsHeaders(null, undefined);
    expect(headers.get("Access-Control-Expose-Headers")).toContain(
      "WWW-Authenticate",
    );
  });

  it("Access-Control-Max-Age is present and non-empty", () => {
    const headers = buildCorsHeaders(null, undefined);
    const maxAge = headers.get("Access-Control-Max-Age");
    expect(maxAge).not.toBeNull();
    expect(Number(maxAge)).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// isCorsPreflightRequest
// ---------------------------------------------------------------------------
describe("isCorsPreflightRequest", () => {
  const BASE_URL = "https://api.example.com/mcp";

  it("returns true for OPTIONS with Origin + Access-Control-Request-Method", () => {
    const request = new Request(BASE_URL, {
      method: "OPTIONS",
      headers: {
        Origin: "https://app.example.com",
        "Access-Control-Request-Method": "POST",
      },
    });
    expect(isCorsPreflightRequest(request)).toBe(true);
  });

  it("returns false for OPTIONS WITHOUT Origin header", () => {
    const request = new Request(BASE_URL, {
      method: "OPTIONS",
      headers: {
        "Access-Control-Request-Method": "POST",
      },
    });
    expect(isCorsPreflightRequest(request)).toBe(false);
  });

  it("returns false for OPTIONS WITHOUT Access-Control-Request-Method header", () => {
    const request = new Request(BASE_URL, {
      method: "OPTIONS",
      headers: {
        Origin: "https://app.example.com",
      },
    });
    expect(isCorsPreflightRequest(request)).toBe(false);
  });

  it("returns false for OPTIONS with neither Origin nor Access-Control-Request-Method (bare HTTP OPTIONS)", () => {
    const request = new Request(BASE_URL, { method: "OPTIONS" });
    expect(isCorsPreflightRequest(request)).toBe(false);
  });

  it("returns false for GET even with Origin header", () => {
    const request = new Request(BASE_URL, {
      method: "GET",
      headers: {
        Origin: "https://app.example.com",
        "Access-Control-Request-Method": "POST",
      },
    });
    expect(isCorsPreflightRequest(request)).toBe(false);
  });

  it("returns false for POST even with CORS headers", () => {
    const request = new Request(BASE_URL, {
      method: "POST",
      headers: {
        Origin: "https://app.example.com",
        "Access-Control-Request-Method": "POST",
      },
    });
    expect(isCorsPreflightRequest(request)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// applyCorsHeaders
// ---------------------------------------------------------------------------
describe("applyCorsHeaders", () => {
  it("preserves status code from the original response", async () => {
    const original = new Response("body", {
      status: 503,
      statusText: "Service Unavailable",
    });
    const corsHeaders = buildCorsHeaders(null, undefined);
    const result = applyCorsHeaders(original, corsHeaders);
    expect(result.status).toBe(503);
  });

  it("preserves statusText from the original response", () => {
    const original = new Response("body", {
      status: 503,
      statusText: "Service Unavailable",
    });
    const corsHeaders = buildCorsHeaders(null, undefined);
    const result = applyCorsHeaders(original, corsHeaders);
    expect(result.statusText).toBe("Service Unavailable");
  });

  it("preserves body text from the original response", async () => {
    const original = new Response("body text", {
      status: 503,
      statusText: "Service Unavailable",
      headers: { "content-type": "text/plain" },
    });
    const corsHeaders = buildCorsHeaders(null, undefined);
    const result = applyCorsHeaders(original, corsHeaders);
    expect(await result.text()).toBe("body text");
  });

  it("adds CORS header to the merged response", () => {
    const original = new Response("ok", {
      status: 200,
      headers: { "content-type": "application/json" },
    });
    const corsHeaders = buildCorsHeaders(null, undefined);
    const result = applyCorsHeaders(original, corsHeaders);
    expect(result.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("preserves pre-existing headers from the original response", () => {
    const original = new Response("ok", {
      status: 200,
      headers: { "content-type": "text/plain" },
    });
    const corsHeaders = buildCorsHeaders(null, undefined);
    const result = applyCorsHeaders(original, corsHeaders);
    expect(result.headers.get("content-type")).toBe("text/plain");
  });

  it("CORS wins on key collision: cors Access-Control-Allow-Origin overrides original", () => {
    // Original sets a (wrong) ACAO header; CORS must win.
    const original = new Response("ok", {
      status: 200,
      headers: { "Access-Control-Allow-Origin": "https://wrong.example.com" },
    });
    const corsHeaders = buildCorsHeaders(null, undefined); // produces "*"
    const result = applyCorsHeaders(original, corsHeaders);
    expect(result.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });
});
