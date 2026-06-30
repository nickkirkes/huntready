/**
 * Behavioural dispatch tests for src/router.ts (S08.4).
 *
 * router.ts owns the 4-step dispatch (CORS preflight → /healthz → auth seam →
 * MCP handler) as a PURE function — it imports no workerd-only module, so the
 * ordering is exercised here by real Requests through `handleRequest` in the
 * Node vitest pool. These tests replace the brittle source-order AST assertion
 * that previously lived in boundary.test.ts: they assert OBSERVABLE BEHAVIOUR, so
 * a behaviour-preserving refactor (helper extraction, reordering equivalent code)
 * cannot false-fail them, and a real ordering regression cannot pass.
 *
 * The MCP handler is injected as a stub (no agents/mcp). No test triggers a live
 * DB connection: every /healthz case returns from its token gate (404) before
 * runHealthCheck is reached.
 */
import { describe, it, expect, vi } from "vitest";
import { handleRequest, type RouterConfig, type McpHandler } from "../src/router.js";

const SEAM_TOKEN = "seam-tok"; // pragma: allowlist secret
const HEALTH_TOKEN = "health-tok"; // pragma: allowlist secret

/** A RouterConfig with safe defaults; override only what a test needs. */
function cfg(overrides: Partial<RouterConfig> = {}): RouterConfig {
  return {
    corsAllowedOrigins: undefined,
    authSeamEnabled: undefined,
    authSeamToken: undefined,
    healthcheckToken: undefined,
    readonlyDsn: "postgresql://unused-in-these-tests",
    ...overrides,
  };
}

/**
 * A stub MCP handler (a vitest mock) that records invocations and returns a
 * sentinel 200. Assertions use `toHaveBeenCalledTimes` / `not.toHaveBeenCalled`.
 */
function makeMcpHandler() {
  return vi.fn(
    async (_req: Request): Promise<Response> =>
      new Response("MCP_OK", { status: 200, headers: { "x-mcp": "1" } }),
  );
}

const MCP_URL = "https://mcp.example.com/mcp";
const HEALTHZ_URL = "https://mcp.example.com/healthz";

// ---------------------------------------------------------------------------
// Step 1 — CORS preflight short-circuits before everything
// ---------------------------------------------------------------------------
describe("handleRequest — CORS preflight", () => {
  it("returns 204 with CORS headers and never invokes the MCP handler", async () => {
    const mcp = makeMcpHandler();
    const res = await handleRequest(
      new Request(MCP_URL, {
        method: "OPTIONS",
        headers: {
          Origin: "https://app.example.com",
          "Access-Control-Request-Method": "POST",
        },
      }),
      cfg(),
      mcp,
    );
    expect(res.status).toBe(204);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(mcp).not.toHaveBeenCalled();
  });

  it("is not 401'd even when the auth seam is enabled (preflights carry no credentials)", async () => {
    const mcp = makeMcpHandler();
    const res = await handleRequest(
      new Request(MCP_URL, {
        method: "OPTIONS",
        headers: {
          Origin: "https://app.example.com",
          "Access-Control-Request-Method": "POST",
        },
      }),
      cfg({ authSeamEnabled: "true", authSeamToken: SEAM_TOKEN }),
      mcp,
    );
    expect(res.status).toBe(204);
    expect(res.headers.get("WWW-Authenticate")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Step 2 — /healthz is gated by its OWN token, orthogonal to the auth seam
// (regression lock for the "/healthz unreachable when the seam is enabled" bug)
// ---------------------------------------------------------------------------
describe("handleRequest — /healthz is orthogonal to the auth seam", () => {
  it("seam enabled + no Authorization → 404 from the healthz gate, NOT a seam 401", async () => {
    // Before the fix the seam ran first and 401'd this /healthz request. Now
    // /healthz is dispatched before the seam and falls through its own token gate.
    const mcp = makeMcpHandler();
    const res = await handleRequest(
      new Request(HEALTHZ_URL, { method: "GET" }),
      cfg({
        authSeamEnabled: "true",
        authSeamToken: SEAM_TOKEN,
        healthcheckToken: HEALTH_TOKEN, // distinct from the seam token
      }),
      mcp,
    );
    expect(res.status).toBe(404);
    expect(res.status).not.toBe(401);
    expect(res.headers.get("WWW-Authenticate")).toBeNull();
    expect(mcp).not.toHaveBeenCalled();
  });

  it("seam enabled + the SEAM token presented to /healthz → 404 (healthz needs its OWN token), never a DB call", async () => {
    // Proves the two tokens never collide on the single Authorization header:
    // presenting the seam token does not satisfy /healthz; it is rejected by the
    // healthz gate (returns 404 before runHealthCheck), not admitted by the seam.
    const mcp = makeMcpHandler();
    const res = await handleRequest(
      new Request(HEALTHZ_URL, {
        method: "GET",
        headers: { Authorization: `Bearer ${SEAM_TOKEN}` }, // pragma: allowlist secret
      }),
      cfg({
        authSeamEnabled: "true",
        authSeamToken: SEAM_TOKEN,
        healthcheckToken: HEALTH_TOKEN,
      }),
      mcp,
    );
    expect(res.status).toBe(404);
    expect(res.status).not.toBe(401);
  });

  it("healthcheck token unset → /healthz is disabled (404), regardless of the seam", async () => {
    const mcp = makeMcpHandler();
    const res = await handleRequest(
      new Request(HEALTHZ_URL, { method: "GET" }),
      cfg({ healthcheckToken: undefined }),
      mcp,
    );
    expect(res.status).toBe(404);
    expect(mcp).not.toHaveBeenCalled();
  });

  it("/healthz responses carry CORS headers", async () => {
    const res = await handleRequest(
      new Request(HEALTHZ_URL, {
        method: "GET",
        headers: { Origin: "https://app.example.com" },
      }),
      cfg(),
      makeMcpHandler(),
    );
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });
});

// ---------------------------------------------------------------------------
// Step 3 — auth seam gates the MCP endpoint
// ---------------------------------------------------------------------------
describe("handleRequest — auth seam (gates the MCP endpoint)", () => {
  it("disabled (default) → MCP request passes straight through", async () => {
    const mcp = makeMcpHandler();
    const res = await handleRequest(
      new Request(MCP_URL, { method: "POST" }),
      cfg(),
      mcp,
    );
    expect(res.status).toBe(200);
    expect(await res.text()).toBe("MCP_OK");
    expect(mcp).toHaveBeenCalledTimes(1);
  });

  it("enabled + no credential → 401 with WWW-Authenticate, MCP handler not invoked", async () => {
    const mcp = makeMcpHandler();
    const res = await handleRequest(
      new Request(MCP_URL, { method: "POST" }),
      cfg({ authSeamEnabled: "true", authSeamToken: SEAM_TOKEN }),
      mcp,
    );
    expect(res.status).toBe(401);
    expect(res.headers.get("WWW-Authenticate")).toContain('Bearer realm="HuntReady MCP"');
    expect(mcp).not.toHaveBeenCalled();
  });

  it("enabled + correct credential → MCP request admitted", async () => {
    const mcp = makeMcpHandler();
    const res = await handleRequest(
      new Request(MCP_URL, {
        method: "POST",
        headers: { Authorization: `Bearer ${SEAM_TOKEN}` }, // pragma: allowlist secret
      }),
      cfg({ authSeamEnabled: "true", authSeamToken: SEAM_TOKEN }),
      mcp,
    );
    expect(res.status).toBe(200);
    expect(mcp).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Step 4 — MCP handler response handling (CORS + error wrapping)
// ---------------------------------------------------------------------------
describe("handleRequest — MCP handler", () => {
  it("wraps the handler response with CORS headers", async () => {
    const res = await handleRequest(
      new Request(MCP_URL, {
        method: "POST",
        headers: { Origin: "https://app.example.com" },
      }),
      cfg(),
      makeMcpHandler(),
    );
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(res.headers.get("x-mcp")).toBe("1"); // upstream header preserved
  });

  it("a throw from the MCP handler becomes a CORS-headered 500 (not an opaque platform 500)", async () => {
    const throwing: McpHandler = async () => {
      throw new Error("boom");
    };
    const res = await handleRequest(
      new Request(MCP_URL, {
        method: "POST",
        headers: { Origin: "https://app.example.com" },
      }),
      cfg(),
      throwing,
    );
    expect(res.status).toBe(500);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });
});

// ---------------------------------------------------------------------------
// CORS origin policy is honoured end-to-end through the dispatcher
// ---------------------------------------------------------------------------
describe("handleRequest — configurable CORS origin policy", () => {
  it("echoes an allowlisted request origin on a normal MCP response", async () => {
    const res = await handleRequest(
      new Request(MCP_URL, {
        method: "POST",
        headers: { Origin: "https://app.example.com" },
      }),
      cfg({ corsAllowedOrigins: "https://app.example.com,https://staging.example.com" }),
      makeMcpHandler(),
    );
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("https://app.example.com");
  });

  it("omits Access-Control-Allow-Origin for a non-allowlisted origin", async () => {
    const res = await handleRequest(
      new Request(MCP_URL, {
        method: "POST",
        headers: { Origin: "https://evil.example.com" },
      }),
      cfg({ corsAllowedOrigins: "https://app.example.com" }),
      makeMcpHandler(),
    );
    expect(res.headers.get("Access-Control-Allow-Origin")).toBeNull();
  });
});
