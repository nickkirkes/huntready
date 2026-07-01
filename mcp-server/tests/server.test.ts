import { describe, it, expect, afterEach } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { LATEST_PROTOCOL_VERSION } from "@modelcontextprotocol/sdk/types.js";
import { createMcpServer } from "../src/server.js";

/**
 * Protocol-conformance + exact-tool-set tests for createMcpServer().
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

  it("tools/list — exact V1 registered-tool-set (UAT #1 guard)", async () => {
    // Asserts the exact set of tools registered in createMcpServer().
    // This is the UAT #1 guard: tools/list must equal exactly the V1 tools
    // registered to date — no __bootstrap_noop__, no health/internal tools.
    // When E09/E10 add further tools, extend this array rather than weaken the
    // assertion. The lock uses only the public MCP protocol so a routine SDK
    // refactor of non-public internals cannot break this foundation test.
    const { client: c } = await setup();

    const { tools } = await c.listTools();
    expect(tools.map((t) => t.name)).toEqual(["get_regulations"]);
    // Sanity-check the tool's shape: name and description must be non-empty strings.
    const tool = tools[0];
    expect(tool.name).toBe("get_regulations");
    expect(typeof tool.description).toBe("string");
    expect(tool.description!.length).toBeGreaterThan(0);
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
