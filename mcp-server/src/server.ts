import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

/**
 * Factory that produces the HuntReady MCP server instance.
 *
 * E08 registers ZERO public tools — the server is intentionally empty at this
 * milestone. We must still answer tools/list: declaring `capabilities.tools`
 * in the constructor obliges the server to handle it (the declaration alone
 * does NOT install a handler, so an unhandled tools/list returns error -32601).
 * We therefore install an explicit empty tools/list handler.
 *
 * PUBLIC API ONLY — no private SDK internals. The handler is registered via the
 * public `server.server.setRequestHandler(...)` with the public
 * `ListToolsRequestSchema`. We deliberately do NOT reach into the SDK's private
 * `setToolRequestHandlers()` method or `_toolHandlersInitialized` flag: a
 * foundation that E09/E10 inherit must not break on a routine SDK refactor of
 * non-public details.
 *
 * FORWARD PATH for E09/E10 (when real tools land): DELETE the empty-handler line
 * below and register tools with `server.tool(...)` / `server.registerTool(...)`
 * — those install the tools/list handler themselves. Keeping BOTH would throw
 * "A request handler for tools/list already exists" at the first server.tool()
 * call. That failure is LOUD and immediate (caught by the first test run), not a
 * silent bug — it is the intended signal to remove this line.
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

  // Explicit empty tools/list handler (public API). Returns [] until E09/E10
  // register real tools — at which point this line is removed (see block comment).
  server.server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [],
  }));

  return server;
}
