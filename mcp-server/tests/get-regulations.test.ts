/**
 * Live happy-path test for `get_regulations` (S09.1a T10).
 *
 * Mirrors the db.test.ts / health-check.test.ts live-DB gating pattern:
 *   - A top-level CI-guard `it` (outside any describe.skipIf) enforces that
 *     TEST_READONLY_DSN is set in CI environments.
 *   - A `describe.skipIf(!DSN)` block houses all live tests so they skip
 *     cleanly in local dev without the substrate.
 *
 * The inner test is self-validating: it discovers a qualifying MT geometry at
 * runtime (non-statewide, bound to a regulation_record with ≥1 season_definition
 * via regulation_season) and derives a representative interior point via the
 * WKT round-trip idiom — so no fragile hardcoded lat/lng is required.
 *
 * SQL idioms inherited from db.ts and the M2 known-pitfalls:
 *   1. All PostGIS functions are `extensions.`-prefixed.
 *   2. The geography-to-geometry cast uses the WKT round-trip:
 *      `extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)`.
 *   3. `prepare: false` is set by createDbClient (pooler-safe).
 *   4. Fixed SQL strings only — no concatenation; params are positional ($1…).
 */

import { describe, it, expect } from "vitest";

import { createDbClient } from "../src/db.js";
import { createGetRegulationsHandler } from "../src/tools/get-regulations.js";
import { getRegulationsResponseSchema } from "../src/output-schema.js";

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
// Live happy-path — skip cleanly when TEST_READONLY_DSN is absent.
// DSN is guaranteed non-null inside this block (skipIf(!DSN) prevents entry).
// ---------------------------------------------------------------------------
describe.skipIf(!DSN)("get_regulations — live happy path", () => {
  it(
    "resolves an in-coverage MT point and returns a valid Shape C envelope with seasons",
    async () => {
      // ── 1. Discovery: find a qualifying MT geometry at runtime ─────────────
      //
      // We want:
      //   • A non-statewide US-MT geometry (id <> 'MT-STATEWIDE-geom' and
      //     kind <> 'state' to exclude the statewide boundary polygon).
      //   • Bound to a regulation_record via jurisdiction_binding (flat FK cols).
      //   • That regulation_record has ≥1 season_definition via regulation_season.
      //
      // The interior point uses the WKT round-trip instead of a bare
      // `::geometry` cast, which Supabase rejects (known-pitfalls §PostGIS).
      // ST_PointOnSurface guarantees a point inside the polygon even for
      // concave/multi-part geometries. ST_Y = latitude, ST_X = longitude.

      const DISCOVERY_SQL = `
        SELECT
          g.id                                              AS geom_id,
          jb.regulation_record_species_group                AS species,
          extensions.ST_Y(
            extensions.ST_PointOnSurface(
              extensions.ST_GeomFromText(extensions.ST_AsText(g.geom), 4326)
            )
          )                                                 AS lat,
          extensions.ST_X(
            extensions.ST_PointOnSurface(
              extensions.ST_GeomFromText(extensions.ST_AsText(g.geom), 4326)
            )
          )                                                 AS lng
        FROM geometry g
        JOIN jurisdiction_binding jb
          ON jb.geometry_id = g.id
        JOIN regulation_season rs
          ON  rs.state             = jb.regulation_record_state
          AND rs.jurisdiction_code = jb.regulation_record_jurisdiction_code
          AND rs.species_group     = jb.regulation_record_species_group
          AND rs.license_year      = jb.regulation_record_license_year
        WHERE g.state  = $1
          AND g.id    <> 'MT-STATEWIDE-geom'
          AND g.kind  <> 'state'
        LIMIT 1
      `.trim();

      interface DiscoveryRow extends Record<string, unknown> {
        geom_id: string;
        species: string;
        lat: number;
        lng: number;
      }

      // Open a dedicated discovery connection; close it in a finally block so
      // teardown failures never mask the real test failure.
      // (This is a TEST file — the Rec-5 single-read-path guard applies to
      //  src/ modules only; tests may open their own connections for setup.)
      const discoveryClient = createDbClient(DSN!);
      let lat: number;
      let lng: number;
      let species: string;

      try {
        const rows = await discoveryClient.query<DiscoveryRow>(
          DISCOVERY_SQL,
          ["US-MT"],
        );

        // Fail loudly if the corpus has no qualifying row — the MT corpus is
        // frozen at m1 and is expected to have many qualifying geometries.
        // A silent skip here would make the test vacuously pass.
        if (rows.length === 0) {
          throw new Error(
            "Discovery found no qualifying non-statewide US-MT geometry with " +
              "a bound regulation_record that has ≥1 season_definition. " +
              "The MT corpus at m1 is expected to have many such rows — " +
              "this indicates a substrate or corpus problem.",
          );
        }

        const row = rows[0]!;
        lat = Number(row.lat);
        lng = Number(row.lng);
        species = row.species;
      } finally {
        try {
          await discoveryClient.close();
        } catch {
          // swallow teardown errors — mirrors the health-check.ts discipline
        }
      }

      // ── 2. Invoke the handler ──────────────────────────────────────────────
      //
      // createGetRegulationsHandler returns a single-argument async function
      // (args: { lat, lng, species, date }) — it does not accept an MCP `extra`
      // second argument; the factory signature is:
      //   (args: z.output<typeof getRegulationsInputSchema>) => Promise<ToolResult>
      //
      // Use a fixed date string; the thin handler does not filter by date —
      // it only uses the date for the in_season / out_of_season status field.
      const handler = createGetRegulationsHandler(DSN!);
      const result = await handler({ lat, lng, species, date: "2026-09-15" });

      // ── 3. Assert: Shape C envelope parses cleanly ─────────────────────────
      //
      // getRegulationsResponseSchema.parse() throws a ZodError if the envelope
      // does not conform — this is the primary correctness gate.
      const parsed = getRegulationsResponseSchema.parse(result.structuredContent);

      // ── 4. Assert: thin happy-path postconditions ─────────────────────────
      //
      // These assertions prove the handler resolved a real jurisdiction, found
      // species coverage, and populated at least one season window — ruling out
      // a vacuous "no coverage" response.

      expect(
        parsed.resolved.jurisdiction,
        "jurisdiction must be non-null for an in-coverage MT point",
      ).not.toBeNull();

      expect(
        parsed.meta.coverage.overall,
        "overall coverage must be 'full' when a jurisdiction AND species are found",
      ).toBe("full");

      expect(
        parsed.sources.length,
        "sources array must be non-empty for a full-coverage response",
      ).toBeGreaterThanOrEqual(1);

      expect(
        parsed.seasons,
        "seasons section must be non-null when regulation_season rows exist",
      ).not.toBeNull();

      // TypeScript narrowing — seasons is non-null after the assertion above.
      const seasons = parsed.seasons!;
      expect(
        seasons.windows.length,
        "seasons.windows must have ≥1 entry for a qualifying geometry with season rows",
      ).toBeGreaterThanOrEqual(1);
    },
    // generous timeout for a live DB round-trip (default 5s can be tight)
    15_000,
  );
});
