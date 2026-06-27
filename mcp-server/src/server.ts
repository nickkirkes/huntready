import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

/**
 * Factory that produces the HuntReady MCP server instance.
 *
 * E08 registers ZERO public tools — the server is intentionally empty at this
 * milestone. We must still answer tools/list: declaring `capabilities.tools` in
 * the constructor obliges the server to handle it (the declaration alone does NOT
 * install a handler, so an unhandled tools/list returns error -32601).
 *
 * We install the tools/list handler directly on the low-level server via the
 * PUBLIC API — `server.server.setRequestHandler(ListToolsRequestSchema, …)`. This
 * yields an ALWAYS-VALID server (the handler always exists; tools/list never
 * 404s) using only public surface. We deliberately do NOT reach into the SDK's
 * private `setToolRequestHandlers()` method, `_toolHandlersInitialized` flag, or
 * `_registeredTools` field: a foundation that E09/E10 inherit must not break on a
 * routine SDK refactor of non-public details.
 *
 * FORWARD PATH for E09/E10 — this handler STAYS; you POPULATE it, you do not
 * remove it. When real tools land, S08.3 establishes the tool-registration +
 * structuredContent/outputSchema mechanism: this handler returns the populated
 * tool list (replace the `[]` with the registry) and a sibling
 * `CallToolRequestSchema` handler dispatches invocations. Serve tools through
 * these low-level public handlers — do NOT use the `McpServer.tool()` /
 * `registerTool()` sugar, which would call the SDK's internal
 * `setToolRequestHandlers()` and throw "A request handler for tools/list already
 * exists". Keeping the registry-driven low-level handler means the extension path
 * is a normal edit (`[]` -> registry) with no line removed and no conflict.
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

  // Always-valid empty tools/list handler (public API). E09/E10 populate the
  // returned list here (and add a CallTool dispatch handler) — see block comment.
  server.server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [],
  }));

  return server;
}
