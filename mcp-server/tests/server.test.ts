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

  it("tools/list returns an empty array — registry-empty lock", async () => {
    // E08 registers zero tools. This public-protocol assertion IS the
    // registry-empty lock: if a future edit registers a tool in
    // createMcpServer(), tools/list returns it and this test fails. The lock uses
    // only the public MCP protocol — it asserts no private SDK internal fields, so
    // a routine SDK refactor of non-public details cannot break this foundation
    // test. The handler is always installed (never 404s).
    const { client: c } = await setup();

    const { tools } = await c.listTools();
    expect(tools).toHaveLength(0);
    expect(tools).toEqual([]);
  });

  it("tools added later via the normal McpServer.tool() API are additive — no conflict (E09/E10 extension contract)", async () => {
    // Locks the forward path this bootstrap exists to enable: E09/E10 add a tool
    // with the NORMAL server.tool() API and it just works — no factory line
    // removed, no "a request handler for tools/list already exists" throw. The
    // register-then-remove bootstrap in createMcpServer() initializes the tools
    // subsystem so this additive call is conflict-free. This test fails loudly if
    // a future bootstrap change reintroduces the double-register block.
    const [clientTransport, serverTransport] =
      InMemoryTransport.createLinkedPair();
    const s = createMcpServer();
    // Simulate E09 adding a tool the normal way (must not throw).
    s.tool("ping", async () => ({
      content: [{ type: "text" as const, text: "pong" }],
    }));
    await s.connect(serverTransport);
    const c = new Client({ name: "test", version: "0.0.0" });
    await c.connect(clientTransport);
    // Assign to outer vars so afterEach cleans up even on failure.
    client = c;
    server = s;

    const { tools } = await c.listTools();
    expect(tools.map((t) => t.name)).toEqual(["ping"]);
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
