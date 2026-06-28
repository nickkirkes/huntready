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
