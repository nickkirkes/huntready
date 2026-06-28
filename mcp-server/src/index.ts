import { createMcpHandler } from "agents/mcp";

import { createMcpServer } from "./server.js";

interface Env {
  // No bindings yet (S08.2 adds the DB binding).
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    // PER-REQUEST INSTANTIATION (REQUIRED): SDK >=1.26 + stateless workerd both require
    // the MCP server + handler to be constructed inside fetch, never in module/global
    // scope. workerd cannot safely share server/transport state across concurrent
    // invocations. tests/boundary.test.ts locks this via a source scan.
    const server = createMcpServer();
    // createMcpHandler serves the MCP endpoint at the default route "/mcp"; any other
    // path returns 404. The route is the Agents-SDK default (not overridden here) — E09/E10
    // and the MCP Inspector connect to "<origin>/mcp".
    const handler = createMcpHandler(server);
    return handler(request, env, ctx);
  },
} satisfies ExportedHandler<Env>;
