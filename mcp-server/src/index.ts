import { createMcpHandler } from "agents/mcp";

import { createMcpServer } from "./server.js";

interface Env {
  // SELECT-only-role DSN, held as a Workers Secret.
  // Set via: `wrangler secret put SUPABASE_READONLY_DSN`
  // Local dev: add `SUPABASE_READONLY_DSN=<dsn>` to the gitignored `.dev.vars`.
  // S08.2 wires the credential; S08.3 adds the live health-check call site.
  SUPABASE_READONLY_DSN: string;
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
