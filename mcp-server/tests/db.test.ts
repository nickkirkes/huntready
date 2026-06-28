/**
 * Access-layer tests for src/db.ts (S08.2 T5).
 *
 * Live tests (A/B/C) run against a real Postgres with the SELECT-only role
 * applied. They require TEST_READONLY_DSN to be set and skip cleanly when it
 * is absent (local dev without the test substrate). In CI the substrate and
 * role are provisioned and TEST_READONLY_DSN is always set — the top-level
 * CI-guard `it` (outside any describe.skipIf) enforces this.
 *
 * Test C (write-rejection) is the load-bearing AC: it proves the committed
 * GRANT/REVOKE DDL actually prevents INSERT/UPDATE/DELETE at the Postgres role
 * level. A pure mock that throws does NOT satisfy this — the rejection must
 * come from the real database returning SQLSTATE 42501 (insufficient_privilege).
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { createDbClient, READ_SMOKE_SQL, ST_VALID_SMOKE_SQL } from "../src/db.js";
import type { DbClient } from "../src/db.js";

const DSN = process.env.TEST_READONLY_DSN;

// ---------------------------------------------------------------------------
// Top-level CI guard — NOT inside describe.skipIf so it ALWAYS runs in CI.
// If this test is skipped or removed, the live tests below silently vanish;
// this guard is the fence that prevents that.
// ---------------------------------------------------------------------------
it("requires TEST_READONLY_DSN when running in CI", () => {
  if (process.env.CI)
    expect(
      DSN,
      "TEST_READONLY_DSN must be set in CI — did the workflow provision step run?",
    ).toBeTruthy();
});

// ---------------------------------------------------------------------------
// Live role tests — skip cleanly when TEST_READONLY_DSN is absent.
// DSN is guaranteed non-null inside this block (skipIf(!DSN) prevents entry).
// ---------------------------------------------------------------------------
describe.skipIf(!DSN)("db access layer — live role tests", () => {
  let client: DbClient;

  beforeAll(() => {
    // DSN is non-null here by virtue of the skipIf guard above.
    client = createDbClient(DSN!);
  });

  afterAll(async () => {
    await client.close();
  });

  // -------------------------------------------------------------------------
  // Test A — plain parameterized read
  // Exercises the GiST-indexed `state` column. Proves the connection,
  // credentials, and RLS/role all work for basic reads.
  // -------------------------------------------------------------------------
  it("Test A — parameterized SELECT returns a geometry row for US-MT", async () => {
    interface GeometryRow extends Record<string, unknown> {
      id: string;
      state: string;
      kind: string;
    }

    const rows = await client.query<GeometryRow>(READ_SMOKE_SQL, ["US-MT"]);

    expect(rows.length).toBeGreaterThanOrEqual(1);
    const row = rows[0];
    expect(row).toHaveProperty("id");
    expect(row).toHaveProperty("state");
    expect(row).toHaveProperty("kind");
    expect(row.state).toBe("US-MT");
    // Assert the shape (id is a non-empty string), NOT a substrate-specific id
    // value: against the CI substrate this row is "MT-TEST-geom", but Group B
    // points TEST_READONLY_DSN at the real dev corpus where LIMIT 1 returns an
    // arbitrary US-MT geometry. The smoke proves connectivity + the read path,
    // not a specific row — so it must stay portable across both substrates.
    expect(typeof row.id).toBe("string");
    expect(row.id.length).toBeGreaterThan(0);
  });

  // -------------------------------------------------------------------------
  // Test B — PostGIS WKT round-trip smoke
  // Validates both Supabase-specific idioms from the module JSDoc:
  //   1. extensions.-prefixed PostGIS function names
  //   2. WKT round-trip instead of the direct geography-to-geometry cast
  // Proving the SQL actually executes against real PostGIS (not just that the
  // connection opens) is the only way to confirm these idioms work end-to-end.
  // -------------------------------------------------------------------------
  it("Test B — PostGIS WKT round-trip smoke returns valid = true for US-MT", async () => {
    interface ValidRow extends Record<string, unknown> {
      id: string;
      valid: boolean;
    }

    const rows = await client.query<ValidRow>(ST_VALID_SMOKE_SQL, ["US-MT"]);

    expect(rows.length).toBeGreaterThanOrEqual(1);
    const row = rows[0];
    expect(row.valid).toBe(true);
  });

  // -------------------------------------------------------------------------
  // Test C — role-level write-rejection (the load-bearing AC)
  // Asserts that the SELECT-only role blocks all writes at the Postgres level.
  // SQLSTATE 42501 = insufficient_privilege. postgres.js surfaces Postgres
  // errors with a .code property carrying the SQLSTATE.
  //
  // NOTE: A pure mock that throws does NOT satisfy this AC — the rejection
  // must come from real Postgres returning 42501 over the committed GRANT DDL
  // (no INSERT/UPDATE/DELETE privilege → permission denied → 42501). The role
  // is provisioned in CI; this test is the evidence that it works.
  // -------------------------------------------------------------------------
  it("Test C — SELECT-only role rejects UPDATE with SQLSTATE 42501", async () => {
    await expect(
      client.query("UPDATE geometry SET name = $1 WHERE id = $2", [
        "hacked",
        "MT-TEST-geom",
      ]),
    ).rejects.toMatchObject({ code: "42501" });
  });

  it("Test C (supplemental) — SELECT-only role rejects DELETE with SQLSTATE 42501", async () => {
    // DELETE is used (rather than INSERT) as the supplemental write witness
    // because it carries NO column-value constraints: an INSERT that omitted a
    // NOT NULL column could in principle surface a 23502 not-null violation, but
    // a privilege-denied role gets 42501 at executor startup before any tuple is
    // touched — so DELETE makes 42501 the unambiguous, only-possible failure.
    await expect(
      client.query("DELETE FROM geometry WHERE id = $1", ["MT-TEST-geom"]),
    ).rejects.toMatchObject({ code: "42501" });
  });
});
