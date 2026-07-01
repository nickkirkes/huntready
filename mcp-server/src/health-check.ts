/**
 * Internal smoke check for the HuntReady MCP server (S08.3).
 *
 * Exercises two sub-systems end-to-end:
 *   1. DB read — calls READ_SMOKE_SQL via `createDbClient` to verify
 *      connectivity, credentials, and RLS/role are functional.
 *   2. Envelope round-trip — constructs a minimal hand-built
 *      `GetRegulationsResponse` fixture and validates it through
 *      `buildStructuredToolResult` (which runs the zod outputSchema).
 *
 * NOT a registered MCP tool — does not appear in `tools/list`.
 * Imported by `src/index.ts` and served at the `/healthz` HTTP route only.
 * Does NOT import `./index.js` (would create a circular dependency).
 *
 * No regulation data or DSN string is ever included in the result.
 */

import { createDbClient, READ_SMOKE_SQL, type DbClient } from "./db.js";
import { buildStructuredToolResult, renderThinText } from "./response-builder.js";
import { getRegulationsResponseSchema } from "./output-schema.js";
import type { GetRegulationsResponse } from "./types/response.js";

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface HealthCheckResult {
  ok: boolean;
  db_reachable: boolean;
  envelope_valid: boolean;
}

// ---------------------------------------------------------------------------
// Smoke-check row shape
// ---------------------------------------------------------------------------

/** Minimal row type for the READ_SMOKE_SQL connectivity probe. */
interface SmokeRow extends Record<string, unknown> {
  id: string;
  state: string;
  kind: string;
}

// ---------------------------------------------------------------------------
// Health check implementation
// ---------------------------------------------------------------------------

/**
 * Run the internal smoke check.
 *
 * @param dsn - SELECT-only-role DSN (`SUPABASE_READONLY_DSN` Workers Secret).
 *   The DSN is consumed only to open the connection; it is NEVER included in
 *   the returned `HealthCheckResult`.
 *
 * Contract:
 *   - `db_reachable` — `true` iff `READ_SMOKE_SQL` completes without throwing.
 *     A successful query proves connectivity; `rows.length >= 0` is always true
 *     even for zero rows. The probe tests connectivity, not data existence.
 *   - `envelope_valid` — `true` iff a minimal hand-built `GetRegulationsResponse`
 *     fixture passes `buildStructuredToolResult` (the zod outputSchema round-trip).
 *   - `ok` — `true` iff both sub-checks pass.
 *
 * `createDbClient` is called INSIDE this function (per-request call site) so it
 * is never invoked at module scope — the boundary.test.ts T5 AST guard locks
 * this invariant.
 */
export async function runHealthCheck(dsn: string): Promise<HealthCheckResult> {
  let db_reachable = false;
  let envelope_valid = false;

  // ── 1. DB connectivity probe ───────────────────────────────────────────────
  // `createDbClient` is called per-request (inside this function), which
  // satisfies the boundary.test.ts T5 AST guard.
  // The ENTIRE client lifecycle — construction included — is inside try/finally
  // so that even a createDbClient() throw (a malformed or missing DSN) degrades
  // to db_reachable=false and a structured 503, never a hard 500. A health check
  // must always return a structured result.
  let client: DbClient | undefined;
  try {
    client = createDbClient(dsn);
    // "US-MT" is a deliberate connectivity-probe target: the Montana corpus is
    // frozen at the `m1` tag and is always present in every environment, so it
    // is a stable thing to probe. This is NOT a state-generic read (E09/E10
    // tools resolve state from the query) — it only proves the connection,
    // credentials, and SELECT-only role work. Mirrors db.test.ts's smoke read.
    const rows = await client.query<SmokeRow>(READ_SMOKE_SQL, ["US-MT"]);
    // rows.length >= 0 is ALWAYS true, even for zero rows. This intentionally
    // tests CONNECTIVITY, not data existence. Do NOT change to >= 1.
    db_reachable = rows.length >= 0;
  } catch {
    db_reachable = false;
  } finally {
    // Swallow a teardown error: a health check must always return a structured
    // result, never a hard 500. A close() failure does not change reachability
    // (the query above already resolved) and the error carries no DSN. `client`
    // may be undefined if createDbClient() threw — optional-chain the close.
    try {
      await client?.close();
    } catch {
      // intentionally ignored — see comment above.
    }
  }

  // ── 2. Shape C envelope round-trip ────────────────────────────────────────
  const generatedAt = new Date().toISOString();

  const fixture: GetRegulationsResponse = {
    query: {
      lat: 0,
      lng: 0,
      species: "healthcheck",
      date: "2026-01-01",
    },
    resolved: {
      jurisdiction: null,
      species_canonical: null,
      license_year: null,
    },
    seasons: null,
    tags: null,
    methods: null,
    reporting: null,
    contacts: null,
    additional_rules: null,
    sources: [],
    meta: {
      schema_version: 2,
      generated_at: generatedAt,
      data_freshness: null,
      coverage: {
        jurisdiction: "none",
        species: "none",
        overall: "none",
      },
      warnings: [],
    },
  };

  try {
    buildStructuredToolResult(fixture, getRegulationsResponseSchema, [], renderThinText);
    envelope_valid = true;
  } catch {
    envelope_valid = false;
  }

  return { ok: db_reachable && envelope_valid, db_reachable, envelope_valid };
}
