/**
 * Read-only Postgres access layer for the HuntReady MCP server (S08.2).
 *
 * This module is the ONLY path from the serving stack to the database. It is
 * environment-portable (no workerd-only imports) so tests/db.test.ts can run it
 * in the Node vitest pool without mocking the Worker runtime.
 *
 * SUPABASE QUIRKS INHERITED BY ALL CALLERS (see .roughly/known-pitfalls.md):
 *
 * 1. `extensions.` prefix — PostGIS lives in the `extensions` schema on Supabase
 *    projects (`CREATE EXTENSION postgis SCHEMA extensions`). The schema is NOT on
 *    the default search_path, so every PostGIS function call must be prefixed:
 *    `extensions.ST_IsValid(...)`, `extensions.ST_DWithin(...)`, etc. Bare names
 *    produce "function does not exist" at runtime.
 *
 * 2. WKT round-trip for geometry-only functions — Supabase does not allow the
 *    direct geography-to-geometry cast (the cast that converts a geography column
 *    directly to geometry type). The workaround is to round-trip through WKT:
 *    `extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)`. This is what
 *    ST_VALID_SMOKE_SQL uses and what E09/E10 must inherit. Describe the broken
 *    idiom in prose (as this comment does) — do NOT embed the broken cast literal
 *    next to the corrected SQL (cubic token-match pitfall: .roughly/known-pitfalls.md
 *    "Explanatory comments that embed a broken-pattern literal trip token-matching
 *    reviewers"). This cast issue bit M2 twice (S05.7 and S06.6.2).
 */

import postgres from "postgres";

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

/**
 * Minimal read-only database client surface.
 *
 * The generic `T` constraint (`Record<string, unknown>`) ensures callers
 * name their result shapes explicitly and the return type is fully typed —
 * no `any` leaks through the public surface.
 */
export interface DbClient {
  /**
   * Execute a parameterized SQL query and return the rows as T[].
   *
   * `params` are bound positionally: the first element replaces `$1`,
   * the second replaces `$2`, etc. The SQL text must be a fixed string
   * (no concatenation) so this is injection-safe.
   */
  query<T extends Record<string, unknown>>(
    text: string,
    params: readonly unknown[],
  ): Promise<T[]>;

  /** Gracefully close the underlying connection pool. */
  close(): Promise<void>;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Create a DbClient backed by postgres.js.
 *
 * @param dsn - A `postgresql://` connection string for the SELECT-only role.
 *              In production this comes from the `SUPABASE_READONLY_DSN` Workers
 *              Secret; for local dev it comes from the gitignored `.dev.vars`.
 *
 * Connection options:
 *   - `prepare: false` — REQUIRED for Supabase's transaction-mode pgBouncer /
 *     connection pooler. Named prepared statements are connection-scoped; the
 *     pooler remaps connections per-transaction, so a prepared statement created
 *     on connection A may be routed to connection B on the next round-trip,
 *     producing "prepared statement does not exist" errors. Setting `prepare:
 *     false` forces simple-query protocol, which is pooler-safe.
 *   - `max: 1` — honors workerd's no-cross-invocation socket-reuse posture.
 *     workerd does not share TCP sockets across concurrent invocations, so a
 *     pool larger than 1 would queue connections that can never be reused.
 *     One connection per request keeps the pool size honest.
 *
 * NOTE: `createDbClient` MUST NOT be called at module scope. It must be
 * invoked inside a request handler or test setup function so each invocation
 * owns its own connection lifecycle. tests/boundary.test.ts (T5) locks this
 * invariant via an AST scan of src/db.ts.
 */
export function createDbClient(dsn: string): DbClient {
  const sql = postgres(dsn, {
    // prepare: false is REQUIRED by Supabase's transaction-mode pooler/pgBouncer.
    // Named prepared statements are connection-scoped and the pooler remaps
    // connections per-transaction — see module JSDoc above.
    prepare: false,
    // max: 1 honors workerd's no-cross-invocation-socket-reuse posture — one
    // connection per request, no shared pool across concurrent Worker invocations.
    max: 1,
  });

  return {
    async query<T extends Record<string, unknown>>(
      text: string,
      params: readonly unknown[],
    ): Promise<T[]> {
      // postgres.js `.unsafe(text, params)` BINDS params positionally ($1, $2, …)
      // — it is injection-safe despite the name. "unsafe" means the SQL text is
      // passed to the server as-is (no client-side parsing), while the params
      // array is still sent as a separate bound-value list. The SQL text must
      // always be a fixed string; never interpolate user input into `text`.
      //
      // The double `as unknown as` cast below is the single any-free boundary
      // between postgres.js's internal `ParameterOrJSON<never>[]` param type and
      // our public `readonly unknown[]` surface. Casting `params` first to
      // `unknown` erases the TypeScript type so the postgres.js call site sees no
      // constraint violation; the second cast (`as T[]`) restores the caller's
      // declared return type. This pattern keeps the entire public surface
      // any-free while working around a postgres.js d.ts constraint.
      return sql.unsafe(
        text,
        params as unknown as Parameters<typeof sql.unsafe>[1],
      ) as unknown as T[];
    },

    async close(): Promise<void> {
      // timeout: 5 gives in-flight queries up to 5 seconds to drain before the
      // connection is forcibly torn down.
      await sql.end({ timeout: 5 });
    },
  };
}

// ---------------------------------------------------------------------------
// Named SQL constants
// (defined once here; reused by tests/db.test.ts, E09, and E10 — never
//  duplicated across callers)
// ---------------------------------------------------------------------------

/**
 * Plain parameterized read that exercises the GiST-indexed `state` column.
 * $1 = state code (e.g. "US-MT" or "US-CO").
 *
 * Used as the basic connectivity smoke test: if this returns a row the
 * connection, credentials, and RLS/role all work.
 */
export const READ_SMOKE_SQL =
  "SELECT id, state, kind FROM geometry WHERE state = $1 LIMIT 1";

/**
 * PostGIS smoke test that validates the two Supabase-specific idioms described
 * in the module JSDoc:
 *
 *   1. Every PostGIS function is `extensions.`-prefixed.
 *   2. The WKT round-trip (`extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)`)
 *      is used instead of the direct geography-to-geometry cast, which Supabase
 *      rejects. This is the pattern E09/E10 inherit; it was discovered (and
 *      corrected) twice during M2 (S05.7 and the S06.6.x carve-outs).
 *
 * $1 = state code.
 *
 * Returns: `{ id: string, valid: boolean }` rows.
 */
export const ST_VALID_SMOKE_SQL =
  "SELECT id, extensions.ST_IsValid(extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)) AS valid FROM geometry WHERE state = $1 LIMIT 1";
