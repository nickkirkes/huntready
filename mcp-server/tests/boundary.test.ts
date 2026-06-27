/**
 * Boundary + config-safety tests (S08.1 T7)
 *
 * Source/config-scanning tests that lock architectural guarantees that cannot be
 * unit-imported because src/index.ts imports `agents/mcp`, which is workerd-only
 * and cannot load in the Node vitest pool. All tests read files as text via
 * node:fs — no import of src/index.ts as a module.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

// ESM __dirname equivalent.
const __dirname = dirname(fileURLToPath(import.meta.url));

// Paths computed relative to this test file so they work regardless of cwd.
const srcDir = resolve(__dirname, "../src");
const wranglerConfigPath = resolve(__dirname, "../wrangler.jsonc");
const indexTsPath = resolve(__dirname, "../src/index.ts");

// ---------------------------------------------------------------------------
// Helper: recursively collect all .ts files under a directory.
// Analog of the Python ingestion AST guards (TestNoColoradoLeakIntoSharedLib /
// TestNoStateAdapterImports). Python uses ast.walk; TypeScript has no stdlib
// AST, so this is a regex source-scan — the same approach used in the ingestion
// project's raw-string slug scans.
// ---------------------------------------------------------------------------
function collectTsFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      results.push(...collectTsFiles(fullPath));
    } else if (entry.endsWith(".ts")) {
      results.push(fullPath);
    }
  }
  return results;
}

// ---------------------------------------------------------------------------
// Test 1: No Durable Objects in wrangler config
// ---------------------------------------------------------------------------
describe("wrangler.jsonc — no Durable Objects", () => {
  it("does not contain the durable_objects key", () => {
    const text = readFileSync(wranglerConfigPath, "utf-8");

    // The wrangler file contains a human-readable comment: "No Durable Objects"
    // (with a space + capital letters). That is intentional and fine.
    // The regex /durable_objects/i checks for the snake_case config key that
    // Wrangler parses. "Durable Objects" (space-separated, title-case) does NOT
    // contain "durable_objects" as a substring, so the comment does not trigger
    // this assertion. This correctly separates documentation from configuration.
    expect(/durable_objects/i.test(text)).toBe(false);
  });

  it("does not declare a migrations array", () => {
    const text = readFileSync(wranglerConfigPath, "utf-8");

    // Durable Object migrations would appear as `"migrations": [...]`.
    // Asserting this key is absent locks the no-DO guarantee from the config
    // side (complementing the durable_objects key check above).
    expect(/"migrations"\s*:/.test(text)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Test 2: No-ingestion-import guard
// Serving analog of the ingestion TestNoColoradoLeakIntoSharedLib /
// TestNoStateAdapterImports AST guards. Ensures no TypeScript source file
// under src/ imports from `ingestion/`, keeping the serving stack cleanly
// separated from the Python ingestion pipeline (ADR-003 / ADR-005).
// ---------------------------------------------------------------------------
describe("src/ — no ingestion imports", () => {
  const tsFiles = collectTsFiles(srcDir);

  it("has at least one TypeScript source file to check", () => {
    expect(tsFiles.length).toBeGreaterThan(0);
  });

  for (const filePath of tsFiles) {
    it(`${filePath} does not import from ingestion`, () => {
      const text = readFileSync(filePath, "utf-8");

      // Static import: from 'ingestion/...' or from "ingestion/..."
      const staticImportMatch = /from\s+['"][^'"]*ingestion/.test(text);
      // Dynamic import: import('ingestion/...') or import("ingestion/...")
      const dynamicImportMatch = /import\(\s*['"][^'"]*ingestion/.test(text);

      expect(staticImportMatch, `Static ingestion import found in ${filePath}`).toBe(false);
      expect(dynamicImportMatch, `Dynamic ingestion import found in ${filePath}`).toBe(false);
    });
  }
});

// ---------------------------------------------------------------------------
// Test 3: Per-request instantiation lock on index.ts
// Locks the SDK >=1.26 + stateless-workerd per-request construction
// requirement: createMcpServer() must be called INSIDE the fetch handler,
// never at module/global scope. Cannot be checked by import because index.ts
// imports agents/mcp (workerd-only); this is a source-text scan instead.
// ---------------------------------------------------------------------------
describe("src/index.ts — per-request server instantiation", () => {
  it("calls createMcpServer() inside the fetch handler, not at module scope", () => {
    const text = readFileSync(indexTsPath, "utf-8");

    // The function must appear somewhere in the file.
    expect(text.includes("createMcpServer()")).toBe(true);

    const fetchHandlerIdx = text.indexOf("async fetch(");
    // Use lastIndexOf for the CALL site: indexOf could be fooled by an earlier
    // mention in a comment (e.g. "// don't call createMcpServer() at module scope").
    // The real construction is the last occurrence; it must sit inside the handler.
    const createServerIdx = text.lastIndexOf("createMcpServer()");

    // fetch handler must be declared before createMcpServer() is called,
    // meaning the call appears after "async fetch(" in the source.
    expect(fetchHandlerIdx).toBeGreaterThan(-1);
    expect(createServerIdx).toBeGreaterThan(fetchHandlerIdx);
  });
});

// ---------------------------------------------------------------------------
// Test 4: index.ts does not hard-code protocolVersion
// The protocol version is negotiated by the SDK/transport layer, never
// hard-coded at the application layer. The positive assertion that the SDK
// owns the version lives in tests/server.test.ts.
// ---------------------------------------------------------------------------
describe("src/index.ts — no hard-coded protocolVersion", () => {
  it("does not contain the literal string protocolVersion", () => {
    const text = readFileSync(indexTsPath, "utf-8");

    expect(text.includes("protocolVersion")).toBe(false);
  });
});
