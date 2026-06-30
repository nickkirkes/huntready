/**
 * OAuth-2.1 auth-seam unit tests (S08.4 AC #2).
 *
 * These tests prove the seam is REAL — a request missing credentials is
 * rejected and a credentialed request is admitted — IN TEST MODE ONLY.
 *
 * The deployed V1 configuration leaves the seam disabled (AUTH_SEAM_ENABLED
 * is not set in wrangler.jsonc), so the production endpoint is open and
 * read-only. The bearer-token literal below is a TEST FIXTURE, not a V1
 * enforcement boundary. Do NOT cite this file as evidence of an enforced
 * auth boundary in production.
 */
import { describe, it, expect } from "vitest";
import {
  isAuthSeamEnabled,
  isAuthorized,
  buildUnauthorizedResponse,
} from "../src/auth.js";
import { buildCorsHeaders } from "../src/cors.js";

// ---------------------------------------------------------------------------
// isAuthSeamEnabled
// ---------------------------------------------------------------------------

describe("isAuthSeamEnabled", () => {
  it('returns true when the binding is the exact string "true"', () => {
    expect(isAuthSeamEnabled("true")).toBe(true);
  });

  it("returns false when the binding is undefined (deployed V1 default)", () => {
    expect(isAuthSeamEnabled(undefined)).toBe(false);
  });

  it('returns false when the binding is "false"', () => {
    expect(isAuthSeamEnabled("false")).toBe(false);
  });

  it('returns false when the binding is "True" (case-sensitive strict equality)', () => {
    expect(isAuthSeamEnabled("True")).toBe(false);
  });

  it('returns false when the binding is "1" (only "true" is accepted)', () => {
    expect(isAuthSeamEnabled("1")).toBe(false);
  });

  it('returns false when the binding is "" (empty string)', () => {
    expect(isAuthSeamEnabled("")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isAuthorized
// ---------------------------------------------------------------------------

describe("isAuthorized", () => {
  const TOKEN = "test-secret-token"; // pragma: allowlist secret

  it("returns true when the Authorization header matches Bearer <token> exactly", () => {
    const req = new Request("https://mcp.example.com/mcp", {
      headers: { Authorization: `Bearer ${TOKEN}` }, // pragma: allowlist secret
    });
    expect(isAuthorized(req, TOKEN)).toBe(true);
  });

  it("returns false when the token is wrong", () => {
    const req = new Request("https://mcp.example.com/mcp", {
      headers: { Authorization: "Bearer wrong-token" }, // pragma: allowlist secret
    });
    expect(isAuthorized(req, TOKEN)).toBe(false);
  });

  it("returns false when the Authorization header is absent", () => {
    const req = new Request("https://mcp.example.com/mcp");
    expect(isAuthorized(req, TOKEN)).toBe(false);
  });

  it('returns false for a Basic-scheme header ("Basic xyz")', () => {
    const req = new Request("https://mcp.example.com/mcp", {
      headers: { Authorization: "Basic xyz" },
    });
    expect(isAuthorized(req, TOKEN)).toBe(false);
  });

  it('returns false when the token is sent bare without the "Bearer " prefix', () => {
    const req = new Request("https://mcp.example.com/mcp", {
      headers: { Authorization: TOKEN }, // pragma: allowlist secret
    });
    expect(isAuthorized(req, TOKEN)).toBe(false);
  });

  it("returns false (fail-closed) when expectedToken is undefined even if the request carries a Bearer header", () => {
    const req = new Request("https://mcp.example.com/mcp", {
      headers: { Authorization: "Bearer anything" },
    });
    expect(isAuthorized(req, undefined)).toBe(false);
  });

  it("returns false (fail-closed) when expectedToken is an empty string even if the request carries a Bearer header", () => {
    const req = new Request("https://mcp.example.com/mcp", {
      headers: { Authorization: "Bearer anything" },
    });
    expect(isAuthorized(req, "")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// buildUnauthorizedResponse
// ---------------------------------------------------------------------------

describe("buildUnauthorizedResponse", () => {
  const MCP_URL = new URL("https://mcp.example.com/mcp");
  const corsHeaders = buildCorsHeaders("https://app.example.com", undefined);

  it("returns HTTP 401", () => {
    const response = buildUnauthorizedResponse(MCP_URL, corsHeaders);
    expect(response.status).toBe(401);
  });

  it("WWW-Authenticate contains the Bearer realm", () => {
    const response = buildUnauthorizedResponse(MCP_URL, corsHeaders);
    const wwwAuth = response.headers.get("WWW-Authenticate");
    expect(wwwAuth).not.toBeNull();
    expect(wwwAuth).toContain('Bearer realm="HuntReady MCP"');
  });

  it("WWW-Authenticate contains the resource_metadata URI derived from the request origin", () => {
    const response = buildUnauthorizedResponse(MCP_URL, corsHeaders);
    const wwwAuth = response.headers.get("WWW-Authenticate");
    expect(wwwAuth).toContain(
      'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"',
    );
  });

  it("a CORS header (Access-Control-Allow-Origin) is present on the 401", () => {
    const response = buildUnauthorizedResponse(MCP_URL, corsHeaders);
    expect(response.headers.get("Access-Control-Allow-Origin")).not.toBeNull();
  });

  it("exposes WWW-Authenticate via Access-Control-Expose-Headers (browser fetch() can read the OAuth-2.1 discovery hint)", () => {
    // End-to-end with the shared CORS policy: without WWW-Authenticate in the
    // expose list a cross-origin browser client receives the 401 but cannot read
    // its WWW-Authenticate value — making the advertised resource_metadata hint
    // invisible to exactly the clients the seam supports.
    const response = buildUnauthorizedResponse(MCP_URL, corsHeaders);
    expect(response.headers.get("WWW-Authenticate")).not.toBeNull();
    expect(response.headers.get("Access-Control-Expose-Headers")).toContain(
      "WWW-Authenticate",
    );
  });

  it("Content-Type is application/json", () => {
    const response = buildUnauthorizedResponse(MCP_URL, corsHeaders);
    expect(response.headers.get("Content-Type")).toContain("application/json");
  });

  it("the body is valid JSON containing an error field", async () => {
    const response = buildUnauthorizedResponse(MCP_URL, corsHeaders);
    const body: unknown = await response.json();
    expect(body).toBeTypeOf("object");
    expect(body).not.toBeNull();
    expect((body as Record<string, unknown>)["error"]).toBeDefined();
  });

  it("resource_metadata is origin-derived, not hardcoded — changes with a different host", () => {
    const otherUrl = new URL("https://other-host.workers.dev/mcp");
    const response = buildUnauthorizedResponse(otherUrl, corsHeaders);
    const wwwAuth = response.headers.get("WWW-Authenticate");
    expect(wwwAuth).toContain(
      'resource_metadata="https://other-host.workers.dev/.well-known/oauth-protected-resource"',
    );
    // Must NOT still point at the original host.
    expect(wwwAuth).not.toContain("mcp.example.com/.well-known");
  });
});
