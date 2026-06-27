import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

/**
 * Factory that produces the HuntReady MCP server instance.
 *
 * E08 registers ZERO public tools — the server is intentionally empty at this
 * milestone. We must still answer tools/list: declaring `capabilities.tools` in
 * the constructor obliges the server to handle it, but `McpServer` does NOT
 * install the tools/list handler until the first tool is registered, so a bare
 * empty server returns error -32601 on tools/list.
 *
 * Bootstrap via the PUBLIC, ADDITIVE-FRIENDLY idiom: register a placeholder tool
 * (which installs the tools/list + tools/call handlers) and immediately
 * `.remove()` it. The result is an ALWAYS-VALID server whose tools/list returns
 * [] — and crucially the tools subsystem is now initialized, so E09/E10 add real
 * tools with the NORMAL `server.tool(...)` / `server.registerTool(...)` API as a
 * purely ADDITIVE change (no factory line removed, no "a request handler for
 * tools/list already exists" conflict).
 *
 * Why this idiom rather than the alternatives (each rejected for a concrete
 * reason; do not "simplify" back into one of them):
 *  - the private `setToolRequestHandlers()` / `_toolHandlersInitialized` /
 *    `_registeredTools` path depends on non-public SDK internals — a foundation
 *    must not break on a routine SDK refactor;
 *  - a low-level `server.server.setRequestHandler(ListToolsRequestSchema, …)`
 *    pre-installs the handler and makes the first `server.tool()` throw — turning
 *    extension into a breaking refactor instead of an additive call;
 *  - a "registerTools callback" branch can silently yield a handler-less (-32601)
 *    server if the callback registers nothing.
 * Register-then-remove is the only public idiom that is also always-valid AND
 * additively extensible via the normal tool API.
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

  // Initialize the tools subsystem with zero net tools, using only public API:
  // registering a tool installs the tools/list handler; removing it leaves the
  // handler in place (so tools/list returns []) AND leaves the subsystem ready
  // for additive server.tool() calls in E09/E10. See block comment for rationale.
  server
    .registerTool(
      "__bootstrap_noop__",
      { description: "Bootstrap placeholder; removed immediately. Never listed." },
      async () => ({ content: [{ type: "text" as const, text: "" }] }),
    )
    .remove();

  return server;
}
