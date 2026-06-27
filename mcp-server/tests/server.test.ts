import { describe, it, expect, afterEach } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { LATEST_PROTOCOL_VERSION } from "@modelcontextprotocol/sdk/types.js";
import { createMcpServer } from "../src/server.js";

/**
 * Protocol-conformance + registry-empty tests for createMcpServer().
 *
 * These tests exercise the real MCP initialize/tools/list exchange via an
 * in-memory SDK Client/Server pair. They intentionally do NOT import
 * src/index.ts because index.ts imports `agents/mcp` (workerd-only; uses
 * cloudflare: protocol modules that cannot load in the Node vitest pool).
 */

describe("createMcpServer — protocol conformance", () => {
  // Shared cleanup state per test.
  let client: Client | undefined;
  let server: ReturnType<typeof createMcpServer> | undefined;

  afterEach(async () => {
    // Close in order: client first (sends disconnect), then server.
    // Use try/finally so both always run even if one throws.
    try {
      await client?.close();
    } finally {
      await server?.close();
    }
    client = undefined;
    server = undefined;
  });

  /** Shared setup: creates a linked pair and runs the real initialize handshake. */
  async function setup(): Promise<{
    client: Client;
    server: ReturnType<typeof createMcpServer>;
  }> {
    const [clientTransport, serverTransport] =
      InMemoryTransport.createLinkedPair();
    const s = createMcpServer();
    await s.connect(serverTransport);
    const c = new Client({ name: "test", version: "0.0.0" });
    await c.connect(clientTransport);
    // Assign to outer variables so afterEach can clean up even on test failure.
    client = c;
    server = s;
    return { client: c, server: s };
  }

  it("initialize handshake — server identity matches factory constants", async () => {
    const { client: c } = await setup();

    expect(c.getServerVersion()).toEqual({
      name: "huntready-mcp",
      version: "0.1.0",
    });
  });

  it("initialize handshake — tools capability is declared", async () => {
    const { client: c } = await setup();

    const caps = c.getServerCapabilities();
    // Assert the `tools` capability is declared without pinning internal SDK
    // shape (the SDK may add `listChanged`; toMatchObject is the right bound).
    expect(caps).toMatchObject({ tools: expect.any(Object) });
  });

  it("protocolVersion is owned by the SDK, not hard-coded by our app", () => {
    // The SDK Client over InMemoryTransport exposes no public negotiated-version
    // getter (no getProtocolVersion(); InMemoryTransport does not implement
    // setProtocolVersion), so we assert the SDK constant owns the version string.
    // The hard-coded-protocolVersion regression lock lives in
    // tests/boundary.test.ts (source scan of index.ts).
    expect(LATEST_PROTOCOL_VERSION).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("tools/list returns an empty array", async () => {
    const { client: c } = await setup();

    const { tools } = await c.listTools();
    expect(tools).toHaveLength(0);
  });

  it("registry-empty lock — public and internal agree that zero tools are registered", async () => {
    const { client: c } = await setup();

    // Public assertion via the MCP protocol.
    expect((await c.listTools()).tools).toEqual([]);

    // Internal introspection: catches a stray future tool registered inside the
    // factory before any connect() call. This assertion would fail loudly if a
    // future change registered a tool in createMcpServer(), even if the public
    // tools/list assertion somehow still passed.
    const s = createMcpServer();
    const reg = (
      s as unknown as { _registeredTools?: Record<string, unknown> }
    )._registeredTools;
    // Guard first so an SDK rename of this internal field produces an actionable
    // message rather than a generic "Cannot convert undefined to object".
    expect(
      reg,
      "_registeredTools must exist on McpServer — SDK internal API changed; see server.ts block comment",
    ).toBeDefined();
    expect(Object.keys(reg as Record<string, unknown>)).toHaveLength(0);
    // Close the standalone server to avoid open handles in the test runner.
    await s.close();
  });

  it("setToolRequestHandlers exists on McpServer (SDK private-API existence lock)", async () => {
    // server.ts calls the SDK's private setToolRequestHandlers() via a cast so that
    // tools/list is answered conformantly while zero tools are registered AND a later
    // server.tool() (E09/E10) composes without a double-register throw. The cast
    // defeats the type checker, so this test fails LOUDLY with a root-cause message if
    // a future SDK upgrade renames/removes the method (otherwise every other test would
    // fail with an opaque "is not a function" TypeError in setup()).
    const s = createMcpServer();
    const fn = (
      s as unknown as { setToolRequestHandlers?: unknown }
    ).setToolRequestHandlers;
    expect(
      typeof fn,
      "setToolRequestHandlers must exist — if this fails, the SDK renamed the private method; review the alternative pattern in server.ts block comment",
    ).toBe("function");
    await s.close();
  });

  it("per-request freshness — each createMcpServer() call yields a distinct instance", async () => {
    // This locks the per-request instantiation pattern used in src/index.ts:
    // every incoming Worker request gets its own McpServer, so state cannot
    // leak across requests.
    const a = createMcpServer();
    const b = createMcpServer();
    try {
      expect(a).not.toBe(b);
    } finally {
      await a.close();
      await b.close();
    }
  });
});
