import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

/**
 * Initialize an MCP server's tools subsystem to an EMPTY-but-ready state, using
 * only the public SDK API.
 *
 * `McpServer` does not install the tools/list (or tools/call) request handlers
 * until the first tool is registered — so a server that declares the `tools`
 * capability but registers nothing returns error -32601 on tools/list. The only
 * public way to install those handlers WITHOUT leaving a tool behind, while
 * keeping the normal `server.tool()` API additive afterward, is to register a
 * placeholder and immediately remove it via the public `RegisteredTool.remove()`.
 * After this call: tools/list returns [], and E09/E10 add real tools with the
 * NORMAL `server.tool(...)` / `server.registerTool(...)` API as a purely additive
 * change (no conflict, no line removed).
 *
 * This register-then-remove idiom is deliberate. The alternatives were each
 * rejected: the SDK's private tool-handler internals would couple a foundation to
 * non-public surface; a hand-written low-level tools/list handler is "direct" but
 * makes the first `server.tool()` throw "a request handler for tools/list already
 * exists" (extension becomes a breaking refactor); a register-tools callback can
 * silently yield a -32601 handler-less server. `remove()` is public, documented
 * API whose contract is to leave the request handlers installed — the
 * register-then-remove behavior is locked by tests/server.test.ts
 * (registry-empty + additive-extension), so a contract change fails loudly.
 */
function initializeEmptyToolRegistry(server: McpServer): void {
  server
    .registerTool(
      "__bootstrap_noop__",
      { description: "Bootstrap placeholder; removed immediately. Never listed." },
      async () => ({ content: [{ type: "text" as const, text: "" }] }),
    )
    .remove();
}

/**
 * Factory that produces the HuntReady MCP server instance.
 *
 * E08 registers ZERO public tools — the server is intentionally empty at this
 * milestone but must still answer tools/list conformantly with [] (the `tools`
 * capability is declared). `initializeEmptyToolRegistry` installs the handlers
 * via public API and keeps `server.tool()` additive for E09/E10.
 *
 * Any future internal health check (S08.3) is NOT a registered MCP tool; the
 * tools-registry-empty lock in tests/server.test.ts (public `client.listTools()`
 * returning []) enforces this invariant.
 */
export function createMcpServer(): McpServer {
  const server = new McpServer(
    { name: "huntready-mcp", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  initializeEmptyToolRegistry(server);

  return server;
}
