/**
 * Health check tests (S08.3 T9).
 *
 * Mirrors db.test.ts skip pattern:
 *   - A top-level CI-guard `it` (outside any describe.skipIf) enforces that
 *     TEST_READONLY_DSN is set in CI environments.
 *   - A `describe.skipIf(!DSN)` block houses all live tests so they skip
 *     cleanly in local dev without the substrate.
 */
import { describe, it, expect } from "vitest";
import { runHealthCheck } from "../src/health-check.js";

const DSN = process.env.TEST_READONLY_DSN;

// ---------------------------------------------------------------------------
// Top-level CI guard — NOT inside describe.skipIf so it ALWAYS runs in CI.
// ---------------------------------------------------------------------------
it("requires TEST_READONLY_DSN when running in CI", () => {
  if (process.env.CI)
    expect(
      DSN,
      "TEST_READONLY_DSN must be set in CI — did the workflow provision step run?",
    ).toBeTruthy();
});

// ---------------------------------------------------------------------------
// Live health check tests — skip cleanly when TEST_READONLY_DSN is absent.
// DSN is guaranteed non-null inside this block (skipIf(!DSN) prevents entry).
// ---------------------------------------------------------------------------
describe.skipIf(!DSN)("health check — live", () => {
  it("returns ok=true against the live substrate", async () => {
    const r = await runHealthCheck(DSN!);
    expect(r).toEqual({ ok: true, db_reachable: true, envelope_valid: true });
  });
});
