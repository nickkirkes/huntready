import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

/**
 * Factory that produces the HuntReady MCP server instance.
 *
 * E08 registers ZERO public tools — the server is intentionally empty at this
 * milestone. The load-bearing call below explains why we still invoke
 * setToolRequestHandlers():
 *
 * Without it, `{ capabilities: { tools: {} } }` in the constructor declares
 * the capability but does NOT install a tools/list request handler, so any
 * client that sends tools/list receives error -32601 (method not found).
 *
 * Calling setToolRequestHandlers() installs that handler (returning []) AND
 * sets the SDK's internal _toolHandlersInitialized flag. The flag makes the
 * call idempotent: E09/E10's first server.tool() call invokes the same method
 * internally without throwing "A request handler for tools/list already exists".
 *
 * The alternative — setRequestHandler(ListToolsRequestSchema, ...) — is NOT
 * used because it is forward-incompatible: E09's first server.tool() would
 * throw precisely that double-register error.
 *
 * Any future internal health check (S08.3) is NOT a registered MCP tool; the
 * tools-registry-empty lock in tests/server.test.ts enforces this invariant.
 * This is the canonical zero-tool-but-conformant pattern that E09/E10 inherit —
 * E09 simply adds server.tool(...) calls; this setup line stays unchanged.
 */
export function createMcpServer(): McpServer {
  const server = new McpServer(
    { name: "huntready-mcp", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  // Install the tools/list + tools/call handlers idempotently so the server
  // responds conformantly to tools/list with [] and remains forward-compatible
  // with E09/E10 tool registrations (see block comment above).
  (server as unknown as { setToolRequestHandlers(): void }).setToolRequestHandlers();

  return server;
}
