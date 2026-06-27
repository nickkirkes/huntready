import { defineConfig } from "vitest/config";

// Serving test harness (S08.1) — Node pool.
// Group A tests import `createMcpServer` (Node-importable, MCP-SDK only) and read
// source/config files via node:fs. They must NOT import `src/index.ts`, which imports
// `agents/mcp` (workerd-only — uses cloudflare: protocol modules and cannot load in Node).
// A `@cloudflare/vitest-pool-workers` integration test (real workerd handshake) is a
// forward-note for E09, intentionally out of scope for S08.1.
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    // No passWithNoTests: now that tests exist, a glob that resolves to zero files
    // (e.g. a case-renamed tests/ dir on a Linux CI runner) MUST fail CI loudly rather
    // than pass green with the entire gate silently absent.
  },
});
