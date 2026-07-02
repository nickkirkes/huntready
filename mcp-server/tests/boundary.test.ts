/**
 * Boundary + config-safety tests (S08.1 T7)
 *
 * These lock architectural guarantees that cannot be unit-imported because
 * src/index.ts imports `agents/mcp`, which is workerd-only and cannot load in the
 * Node vitest pool. Rather than scan raw source text (where a comment or string
 * literal can spuriously match a forbidden pattern), the TypeScript guards parse
 * the file with the TypeScript compiler API and inspect the SYNTAX TREE — the
 * direct analog of the Python ingestion AST guards (TestNoColoradoLeakIntoSharedLib
 * / TestNoStateAdapterImports, which use ast.walk). Comments and unrelated string
 * literals are not part of the inspected nodes, so documentation edits cannot
 * break these locks.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

// ESM __dirname equivalent.
const __dirname = dirname(fileURLToPath(import.meta.url));

// Paths computed relative to this test file so they work regardless of cwd.
const srcDir = resolve(__dirname, "../src");
const wranglerConfigPath = resolve(__dirname, "../wrangler.jsonc");
const indexTsPath = resolve(__dirname, "../src/index.ts");

// ---------------------------------------------------------------------------
// AST helpers (TypeScript compiler API)
// ---------------------------------------------------------------------------
function parseSourceFile(filePath: string): ts.SourceFile {
  return ts.createSourceFile(
    filePath,
    readFileSync(filePath, "utf-8"),
    ts.ScriptTarget.ES2022,
    /* setParentNodes */ true,
  );
}

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

/** Every module specifier this file imports/exports from, static + dynamic. */
function moduleSpecifiers(sf: ts.SourceFile): string[] {
  const specs: string[] = [];
  const visit = (node: ts.Node): void => {
    // import ... from "X"
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      specs.push(node.moduleSpecifier.text);
    }
    // export ... from "X"
    else if (
      ts.isExportDeclaration(node) &&
      node.moduleSpecifier &&
      ts.isStringLiteral(node.moduleSpecifier)
    ) {
      specs.push(node.moduleSpecifier.text);
    }
    // import X = require("Y")
    else if (
      ts.isImportEqualsDeclaration(node) &&
      ts.isExternalModuleReference(node.moduleReference) &&
      ts.isStringLiteral(node.moduleReference.expression)
    ) {
      specs.push(node.moduleReference.expression.text);
    }
    // dynamic import("X")
    else if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments.length > 0 &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      specs.push((node.arguments[0] as ts.StringLiteral).text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return specs;
}

/** All call expressions to a bare identifier `name` (e.g. `createMcpServer()`). */
function callsToIdentifier(sf: ts.SourceFile, name: string): ts.CallExpression[] {
  const calls: ts.CallExpression[] = [];
  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === name
    ) {
      calls.push(node);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return calls;
}

/** True if `node` is lexically nested inside any function/method body. */
function isInsideFunction(node: ts.Node): boolean {
  let p = node.parent;
  while (p) {
    if (
      ts.isFunctionDeclaration(p) ||
      ts.isFunctionExpression(p) ||
      ts.isArrowFunction(p) ||
      ts.isMethodDeclaration(p)
    ) {
      return true;
    }
    p = p.parent;
  }
  return false;
}

/** True if any Identifier node in the tree is named `name` (ignores comments/strings). */
function usesIdentifier(sf: ts.SourceFile, name: string): boolean {
  let found = false;
  const visit = (node: ts.Node): void => {
    if (ts.isIdentifier(node) && node.text === name) {
      found = true;
    }
    if (!found) ts.forEachChild(node, visit);
  };
  visit(sf);
  return found;
}

// ---------------------------------------------------------------------------
// Test 1: No Durable Objects in wrangler config (structural key check)
// ---------------------------------------------------------------------------
describe("wrangler.jsonc — no Durable Objects", () => {
  // Match the quoted CONFIG KEY form ("durable_objects":), not the bare word, so
  // the human comment "No Durable Objects" cannot trip the assertion. (wrangler
  // config is JSONC; a structural key check is the syntactic analog here.)
  it("does not declare a durable_objects binding", () => {
    const text = readFileSync(wranglerConfigPath, "utf-8");
    expect(/"durable_objects"\s*:/.test(text)).toBe(false);
  });

  it("does not declare a migrations array", () => {
    const text = readFileSync(wranglerConfigPath, "utf-8");
    expect(/"migrations"\s*:/.test(text)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Test 2: No-ingestion-import guard (AST walk over import/export specifiers)
// Serving analog of the ingestion TestNoColoradoLeakIntoSharedLib /
// TestNoStateAdapterImports AST guards (ADR-003 / ADR-005). Inspects actual
// module specifiers only — a comment or string literal mentioning "ingestion"
// cannot trip it.
// ---------------------------------------------------------------------------
describe("src/ — no ingestion imports", () => {
  const tsFiles = collectTsFiles(srcDir);

  it("has at least one TypeScript source file to check", () => {
    expect(tsFiles.length).toBeGreaterThan(0);
  });

  for (const filePath of tsFiles) {
    it(`${filePath} does not import from ingestion`, () => {
      const specs = moduleSpecifiers(parseSourceFile(filePath));
      const offending = specs.filter((s) => /(^|[/\\])ingestion([/\\]|$)/.test(s));
      expect(
        offending,
        `ingestion import(s) found in ${filePath}: ${offending.join(", ")}`,
      ).toEqual([]);
    });
  }
});

// ---------------------------------------------------------------------------
// Test 3: Per-request instantiation lock on index.ts (AST)
// Locks the SDK >=1.26 + stateless-workerd requirement: createMcpServer() must be
// constructed INSIDE the request handler, never at module/global scope (module
// scope = state shared across concurrent requests = the bug). Checks call sites in
// the syntax tree, so a comment mentioning createMcpServer() cannot affect it.
// ---------------------------------------------------------------------------
describe("src/index.ts — per-request server instantiation", () => {
  it("constructs createMcpServer() inside a function, never at module scope", () => {
    const sf = parseSourceFile(indexTsPath);
    const calls = callsToIdentifier(sf, "createMcpServer");

    // It must actually be called…
    expect(calls.length).toBeGreaterThan(0);
    // …and every call site must be nested inside a function/method (the fetch
    // handler), never a module-scope statement.
    const moduleScopeCalls = calls.filter((c) => !isInsideFunction(c));
    expect(
      moduleScopeCalls.length,
      "createMcpServer() must not be called at module scope (per-request only)",
    ).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Test 4: index.ts does not reference protocolVersion (AST)
// The protocol version is negotiated by the SDK/transport, never touched at the
// application layer. Checks for an actual `protocolVersion` Identifier in code —
// a comment mentioning protocolVersion is not an Identifier node and is ignored.
// The positive "SDK owns the version" assertion lives in tests/server.test.ts.
// ---------------------------------------------------------------------------
describe("src/index.ts — no app-layer protocolVersion", () => {
  it("does not reference a protocolVersion identifier", () => {
    const sf = parseSourceFile(indexTsPath);
    expect(usesIdentifier(sf, "protocolVersion")).toBe(false);
  });
});

// Dispatch ORDER (CORS preflight → /healthz → auth seam → MCP) is no longer
// asserted here by lexical source position — that was brittle to behaviour-
// preserving refactors. The dispatch now lives in the pure src/router.ts module
// (index.ts is a thin shim), so tests/router.test.ts locks the ordering by
// OBSERVABLE BEHAVIOUR (real Requests through handleRequest) in the Node pool.

// ---------------------------------------------------------------------------
// Test 5: DB client constructed per request, never at module scope (AST)
// Serving analog of the per-request createMcpServer() lock (Test 3 above).
// Honors workerd's no-cross-invocation-socket-reuse posture: createDbClient()
// opens a real connection and MUST be called inside a request handler or test
// setup function — never at module/global scope where it would be shared
// across concurrent requests.
//
// Unlike Test 3, this guard does NOT assert that a call EXISTS. In S08.2
// src/index.ts does not yet call createDbClient() (the live call site is
// S08.3). The guard passes vacuously now and locks the pattern for S08.3:
// when createDbClient() is added to index.ts it must be inside a function.
//
// Checks call sites in the syntax tree — a comment mentioning createDbClient
// cannot affect this guard.
// ---------------------------------------------------------------------------
describe("src/ — DB client constructed per request, never at module scope", () => {
  it("never calls createDbClient at module scope", () => {
    const moduleScopeCalls: string[] = [];
    for (const filePath of collectTsFiles(srcDir)) {
      const sf = parseSourceFile(filePath);
      for (const call of callsToIdentifier(sf, "createDbClient")) {
        if (!isInsideFunction(call)) moduleScopeCalls.push(filePath);
      }
    }
    expect(
      moduleScopeCalls,
      "createDbClient must be called per-request, never at module scope",
    ).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Test 8: Single read-path guard — only db.ts opens a DB connection (AST)
// Serving analog of the ingestion ADR-003/ADR-024 "single read path" principle.
// Audit Rec 5 from the E08 post-implementation audit: no src/ file other than
// db.ts may call `postgres(...)` (the postgres.js default export constructor)
// or even import the `postgres` package. db.ts is the ONLY path from the
// serving stack to the database.
//
// Two assertions per non-db.ts file:
//   (a) no call expression targeting the bare identifier `postgres`
//   (b) no import/export specifier for the `postgres` package
//
// Positive anchor: db.ts MUST call `postgres` — so a rename of the connection
// constructor cannot silently make this guard vacuous.
//
// Checks AST nodes only — comments and string literals cannot trip it.
// ---------------------------------------------------------------------------
describe("src/ — single read path: only db.ts opens a DB connection (audit Rec 5)", () => {
  const dbTsPath = resolve(__dirname, "../src/db.ts");
  const tsFiles = collectTsFiles(srcDir);

  it("db.ts calls postgres() — positive anchor (guard cannot go vacuous)", () => {
    const sf = parseSourceFile(dbTsPath);
    const calls = callsToIdentifier(sf, "postgres");
    expect(
      calls.length,
      "db.ts must call postgres() to open the connection — if the constructor was renamed, update this guard and the sweep below",
    ).toBeGreaterThan(0);
  });

  for (const filePath of tsFiles) {
    if (filePath === dbTsPath) continue;

    it(`${filePath} does not call postgres() or import the postgres package`, () => {
      const sf = parseSourceFile(filePath);

      // (a) No call to the bare `postgres` identifier.
      const postgresCallSites = callsToIdentifier(sf, "postgres");
      expect(
        postgresCallSites.length,
        `${filePath} must not call postgres() — only db.ts may open a DB connection`,
      ).toBe(0);

      // (b) No import of the "postgres" package specifier.
      const postgresImports = moduleSpecifiers(sf).filter((s) => s === "postgres");
      expect(
        postgresImports,
        `${filePath} must not import the "postgres" package — only db.ts may depend on it directly`,
      ).toEqual([]);
    });
  }
});

// ---------------------------------------------------------------------------
// Test 6: response.ts imports shared types from schema.js (AST)
// Locks that response.ts does NOT redefine SourceCitation, DrawSpec, etc. from
// scratch — it imports them from schema.js. A future refactor that moves the
// import or redefines the types inline would break the three-place sync
// discipline; this guard catches it at the module-specifier level.
// ---------------------------------------------------------------------------
describe("src/types/response.ts — imports shared types from schema.js", () => {
  it("has a module specifier for ./schema.js", () => {
    const responseTsPath = resolve(__dirname, "../src/types/response.ts");
    const sf = parseSourceFile(responseTsPath);
    expect(
      moduleSpecifiers(sf).includes("./schema.js"),
      "response.ts must import shared types from ./schema.js, not redefine them",
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Test 7: src/types/index.ts barrel re-exports response.js (AST)
// Locks the barrel convention established in T7: any consumer that imports from
// the types barrel (src/types/index.ts) gets the response types too. A future
// edit that removes the re-export block would break that consumer contract;
// this guard catches it immediately.
// ---------------------------------------------------------------------------
describe("src/types/index.ts — barrel re-exports response.js", () => {
  it("has a module specifier for ./response.js", () => {
    const indexTsTypesPath = resolve(__dirname, "../src/types/index.ts");
    const sf = parseSourceFile(indexTsTypesPath);
    expect(
      moduleSpecifiers(sf).includes("./response.js"),
      "src/types/index.ts must re-export from ./response.js",
    ).toBe(true);
  });
});
