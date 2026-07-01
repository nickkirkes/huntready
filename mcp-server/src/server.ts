import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { getRegulationsResponseSchema } from "./output-schema.js";
import { READ_ONLY_TOOL_ANNOTATIONS } from "./response-builder.js";
import {
  createGetRegulationsHandler,
  getRegulationsInputSchema,
} from "./tools/get-regulations.js";

/**
 * Factory that produces the HuntReady MCP server instance.
 *
 * Registers the `get_regulations` tool (S09.1a foundation). The DSN parameter
 * is threaded through to the tool handler factory — production callers pass
 * `env.SUPABASE_READONLY_DSN`; tests may pass an empty string or a test-double
 * DSN (the default `""` keeps existing no-arg call sites in tests compiling).
 *
 * The `dsn` default of `""` is intentional: handler execution is deferred to
 * request time, so tests that exercise server.ts structure (tool list, tool
 * metadata) without issuing actual DB queries will never open a connection.
 *
 * Any future internal health check (S08.3) is NOT a registered MCP tool; the
 * tool-set assertion in tests/server.test.ts (public `client.listTools()`)
 * enforces the exact registered tool set.
 */
export function createMcpServer(dsn: string = ""): McpServer {
  const server = new McpServer(
    { name: "huntready-mcp", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  server.registerTool(
    "get_regulations",
    {
      description:
        "Return applicable hunting regulations, season windows, and source citations for a given coordinate, species, and date.",
      inputSchema: getRegulationsInputSchema,
      outputSchema: getRegulationsResponseSchema,
      annotations: READ_ONLY_TOOL_ANNOTATIONS,
    },
    createGetRegulationsHandler(dsn),
  );

  return server;
}
