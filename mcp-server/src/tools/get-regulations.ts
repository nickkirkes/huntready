/**
 * S09.1a — `get_regulations` thin handler (foundation happy-path).
 *
 * This module provides:
 *   - `getRegulationsInputSchema`    — zod input schema for MCP `registerTool`.
 *   - `createGetRegulationsHandler`  — factory that closes over a `dsn` string
 *                                      and returns a typed MCP ToolCallback.
 *
 * The DSN is passed as a parameter (NOT via process.env) because the Cloudflare
 * Workers runtime does NOT provide `process`. In `index.ts` `env.SUPABASE_READONLY_DSN`
 * is projected onto `RouterConfig.readonlyDsn`, and `server.ts` / `createMcpServer`
 * will pass the DSN through to this factory when wiring up the tool. The handler
 * never reads global process state — keeping it unit-testable and Workers-compatible.
 *
 * Scope (thin happy-path only — S09.1b is the full composite):
 *   • Resolves the covering bound `geometry`/`jurisdiction_binding` for (lat, lng),
 *     picking `primary_unit` by binding role.
 *   • Fetches `season_definition` rows scoped to the point's jurisdiction (via
 *     `jurisdiction_binding` → `regulation_record` → `regulation_season`) for the
 *     input species.
 *   • Computes the coverage tri-state (none / partial / full) and composes a
 *     schema-valid Shape C `GetRegulationsResponse` with `seasons` populated and
 *     all other optional sections set to `null`.
 *
 * What this handler does NOT do (S09.1b):
 *   • the populated-empty-section ↔ `full` distinction and the `conditionally_closed`
 *     status (the none/partial/full coverage signals themselves ARE computed here);
 *   • overlay population (`jurisdiction_binding` role=overlay/no_hunt_zone rows into
 *     `resolved.jurisdiction.overlays[]`);
 *   • `tags`, `methods`, `reporting`, `contacts`, `additional_rules` sections;
 *   • json_agg / single bounded composite query (this uses 2 point-lookups).
 *
 * SQL idioms inherited from db.ts and the M2 known-pitfalls:
 *   1. PostGIS functions are `extensions.`-prefixed (Supabase puts PostGIS in
 *      the `extensions` schema, NOT on the default search_path; bare names
 *      produce "function does not exist" at runtime).
 *   2. `prepare: false` is set on the DbClient (pooler-safe, per createDbClient).
 *   3. No direct geography-to-geometry cast; the WKT round-trip workaround is
 *      used when geometry-type functions are needed (this file needs none).
 *   4. Fixed SQL strings only — no in-SQL concatenation; params are positional
 *      ($1…) and bound by postgres.js, never interpolated into the SQL text. The
 *      geometry point is a single WKT literal built in JS from the `.finite()`-
 *      validated coordinates and bound as one parameter (see RESOLVE_GEOMETRY_SQL).
 *   5. `lng` is FIRST in the POINT literal: PostGIS POINT(x y) = (longitude latitude).
 *
 * What this handler does NOT do (S09.1b — deliberately deferred):
 *   • Overlay population: `resolved.jurisdiction.overlays[]` is left empty (the
 *     non-primary covering roles — CWD zones, restricted areas — are not yet
 *     surfaced). `primary_unit` IS chosen by binding role and seasons ARE
 *     jurisdiction-scoped (see RESOLVE_GEOMETRY_SQL / REGULATION_SEASONS_SQL).
 *   • Nullable-column hardening on `season_definition.verbatim_rule` and shape
 *     validation of the `source` jsonb before use (both currently fail loud via the
 *     builder's zod validation; 1b adds diagnostic guards with better messages).
 *   • A handler-level schema-version gating test (the mechanism is covered in
 *     response.test.ts; the handler-wiring test lands with 1b's live composite).
 */

import { z } from "zod";

import { createDbClient } from "../db.js";
import {
  buildDataFreshness,
  buildStructuredToolResult,
  gateBySchemaVersion,
  renderThinText,
} from "../response-builder.js";
import { getRegulationsResponseSchema } from "../output-schema.js";
import type { GetRegulationsResponse, Warning } from "../types/response.js";
import type { ClosurePredicate, SourceCitation, WeaponType, Residency } from "../types/schema.js";

// ---------------------------------------------------------------------------
// Input schema (exported — passed to MCP SDK's registerTool / tool())
// ---------------------------------------------------------------------------

export const getRegulationsInputSchema = z.object({
  // `.finite()` rejects NaN/Infinity at input validation (zod `z.number()` accepts
  // both by default) — otherwise a non-finite coordinate would reach the DB as a
  // malformed WKT literal and surface as a confusing Postgres parse error instead
  // of a clean input-validation failure.
  lat: z.number().finite(),
  lng: z.number().finite(),
  species: z.string(),
  date: z.string(),
});

// ---------------------------------------------------------------------------
// DB row types  (all extend Record<string, unknown> per DbClient.query<T>)
// ---------------------------------------------------------------------------

/**
 * Columns returned by the point-in-polygon geometry resolution query: one row
 * per (covering geometry × its binding), carrying the binding `role` so the
 * PRIMARY UNIT can be chosen by role (not by polygon size). Ordered smallest-
 * area first, so the first `role = 'primary_unit'` row is the most-specific
 * covering primary unit.
 */
interface GeometryRow extends Record<string, unknown> {
  state: string;
  name: string;
  role: string;
  source: SourceCitation;
}

/**
 * Columns returned by the regulation_record + season_definition join.
 * Aliased with `rr_` / `sd_` prefixes to avoid ambiguity (both tables carry
 * a `source` jsonb column among others).
 */
interface SeasonRow extends Record<string, unknown> {
  // regulation_record columns
  rr_schema_version: number;
  rr_source: SourceCitation;
  rr_confidence: "high" | "medium" | "low";
  rr_jurisdiction_code: string;
  rr_species_group: string;
  rr_license_year: number;
  // season_definition columns
  sd_id: string;
  sd_name: string;
  sd_opens: string;
  sd_closes: string;
  sd_weapon_type: string | null;
  sd_residency: string | null;
  sd_closure_predicate: ClosurePredicate | null;
  sd_verbatim_rule: string;
  sd_page_reference: string | null;
  sd_source: SourceCitation;
}

// ---------------------------------------------------------------------------
// Named SQL constants (fixed strings — no concatenation, positional params)
// ---------------------------------------------------------------------------

/**
 * Resolve which `geometry` row covers the given geographic point.
 *
 * `extensions.ST_GeogFromText` parses a WKT geography literal (SRID=4326).
 * `extensions.ST_Covers(geom, point)` — arg1 is the polygon geography column,
 * arg2 is the query point; "polygon covers point" = point lies within or on
 * the polygon's boundary.
 *
 * POINT(lng lat): PostGIS uses (x y) = (longitude latitude) ordering — lng
 * is bound to $1, lat to $2.
 *
 * Returns EVERY bound geometry covering the point (joined to `jurisdiction_binding`
 * so each row carries its `role`), ordered SMALLEST-area first. The handler uses
 * this to (a) decide jurisdiction coverage — did the point resolve to any bound
 * geometry? — and (b) pick `resolved.jurisdiction.primary_unit` as the name of the
 * smallest covering geometry whose binding `role = 'primary_unit'`, or `null` when
 * none covers. **`primary_unit` is chosen by ROLE, not polygon size** — a point can
 * fall inside a small overlay (restricted-area / CWD zone) that is smaller than its
 * hunting district, so ordering by area alone would mislabel the overlay as the
 * primary unit. Ordering by area only breaks ties AMONG primary-unit geometries
 * (an HD is smaller than the statewide boundary, so the HD wins). Populating
 * `resolved.jurisdiction.overlays[]` (the non-primary covering roles) is S09.1b.
 *
 * $1 = the full WKT geography literal `SRID=4326;POINT(<lng> <lat>)`, built in JS
 *      from the `.finite()`-validated coordinates and bound as a SINGLE positional
 *      parameter — there is NO in-SQL `||` concatenation of caller values, so no
 *      value ever reaches Postgres' SQL text (injection-safe; the coordinates are
 *      finite numbers, so the WKT is always well-formed).
 */
const RESOLVE_GEOMETRY_SQL = `
  SELECT g.state, g.name, jb.role, g.source AS source
  FROM geometry g
  JOIN jurisdiction_binding jb
    ON jb.geometry_id = g.id
  WHERE extensions.ST_Covers(g.geom, extensions.ST_GeogFromText($1))
  ORDER BY extensions.ST_Area(g.geom) ASC
`.trim();

/**
 * Fetch the `season_definition` rows applicable to the QUERIED POINT for the
 * input species — scoped to the jurisdiction(s) that actually cover the point,
 * NOT the whole state. This is the architecture's `jurisdiction_binding` fan-out
 * (architecture.md §"Resolution sizing"): a coordinate resolves through the
 * bindings on the geometries covering it, so a point in one hunting district
 * never receives another district's seasons.
 *
 * Join path (actual column names from supabase/migrations/):
 *   geometry               (covers the point via ST_Covers)
 *   → jurisdiction_binding (on geometry_id → the record's flat FK cols)
 *   → regulation_record    (PK: state, jurisdiction_code, species_group, license_year)
 *   → regulation_season    (link: same 4 cols + season_definition_id)
 *   → season_definition    (PK: id)
 *
 * The same regulation_record can be bound by more than one covering geometry
 * (binding fan-out), so a (record, season) pair can appear multiple times — the
 * handler de-duplicates by (jurisdiction_code, license_year, season id).
 *
 * $1 = the WKT geography literal `SRID=4326;POINT(<lng> <lat>)` (bound as one param).
 * $2 = species (matched against regulation_record.species_group).
 *
 * S09.1b hardens this further (overlay-role distinction, the ≤N-query bound proof
 * on the max-overlay district, multi-year handling); the jurisdiction SCOPING is
 * correct here.
 */
const REGULATION_SEASONS_SQL = `
  SELECT
    rr.schema_version          AS rr_schema_version,
    rr.source                  AS rr_source,
    rr.confidence              AS rr_confidence,
    rr.jurisdiction_code       AS rr_jurisdiction_code,
    rr.species_group           AS rr_species_group,
    rr.license_year            AS rr_license_year,
    sd.id                      AS sd_id,
    sd.name                    AS sd_name,
    sd.opens                   AS sd_opens,
    sd.closes                  AS sd_closes,
    sd.weapon_type             AS sd_weapon_type,
    sd.residency               AS sd_residency,
    sd.closure_predicate       AS sd_closure_predicate,
    sd.verbatim_rule           AS sd_verbatim_rule,
    sd.page_reference          AS sd_page_reference,
    sd.source                  AS sd_source
  FROM geometry g
  JOIN jurisdiction_binding jb
    ON jb.geometry_id = g.id
  JOIN regulation_record rr
    ON  rr.state             = jb.regulation_record_state
    AND rr.jurisdiction_code = jb.regulation_record_jurisdiction_code
    AND rr.species_group     = jb.regulation_record_species_group
    AND rr.license_year      = jb.regulation_record_license_year
  JOIN regulation_season rs
    ON  rs.state             = rr.state
    AND rs.jurisdiction_code = rr.jurisdiction_code
    AND rs.species_group     = rr.species_group
    AND rs.license_year      = rr.license_year
  JOIN season_definition sd
    ON sd.id = rs.season_definition_id
  WHERE extensions.ST_Covers(g.geom, extensions.ST_GeogFromText($1))
    AND rr.species_group = $2
  ORDER BY rr.license_year DESC, sd.opens ASC
`.trim();

// ---------------------------------------------------------------------------
// Handler factory
// ---------------------------------------------------------------------------

/**
 * Return type of `buildStructuredToolResult`, matched by the MCP SDK's
 * `CallToolResult` shape (content[] + optional structuredContent).
 */
type ToolResult = {
  structuredContent: Record<string, unknown>;
  content: { type: "text"; text: string }[];
};

/**
 * Factory that binds the SELECT-only-role DSN and returns a typed MCP
 * ToolCallback for `get_regulations`.
 *
 * The DSN is threaded as a parameter (not from process.env) so:
 *   a) The handler works in the Cloudflare Workers runtime (no `process` global).
 *   b) Tests can inject a test-double DSN without patching globals.
 *
 * Connection lifecycle mirrors `runHealthCheck` in health-check.ts:
 *   - `createDbClient(dsn)` called INSIDE the returned handler (never at module
 *     scope) — the boundary.test.ts T5 AST guard locks this per-file invariant.
 *   - `try { … } finally { await client.close() }` — close errors are swallowed
 *     so a teardown failure never masks the query result or produces a hard 500.
 *
 * @param dsn - SELECT-only-role DSN (from env.SUPABASE_READONLY_DSN in index.ts).
 */
export function createGetRegulationsHandler(
  dsn: string,
): (args: z.output<typeof getRegulationsInputSchema>) => Promise<ToolResult> {
  return async (args) => {
    const { lat, lng, species, date } = args;

    const generatedAt = new Date().toISOString();
    const warnings: Warning[] = [];

    // createDbClient is called INSIDE the handler (per-request, never at module
    // scope) — the boundary.test.ts T5 AST guard locks this invariant.
    const client = createDbClient(dsn);

    try {
      // ── 1. Point-in-polygon resolution ───────────────────────────────────
      // The WKT point is `POINT(x y)` = `POINT(lng lat)` (lng first). It is built
      // here from the `.finite()`-validated coordinates and bound as a single $1
      // parameter — no in-SQL concatenation of caller values.
      const geometryRows = await client.query<GeometryRow>(
        RESOLVE_GEOMETRY_SQL,
        [`SRID=4326;POINT(${lng} ${lat})`],
      );

      if (geometryRows.length === 0) {
        // Point does not resolve to any geometry — return a structurally valid
        // no-coverage envelope. S09.1b owns the full graceful no-coverage path.
        const noConvResponse: GetRegulationsResponse = {
          query: { lat, lng, species, date },
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
            coverage: { jurisdiction: "none", species: "none", overall: "none" },
            // Placeholder — buildStructuredToolResult is the SOLE writer of
            // meta.warnings and assigns the `warnings` arg passed below.
            warnings: [],
          },
        };
        return buildStructuredToolResult(
          noConvResponse,
          getRegulationsResponseSchema,
          warnings,
          renderThinText,
        );
      }

      // Rows are ordered smallest-area first (all cover the point). State is the
      // same across covering geometries at a point; read it from any row.
      const resolvedState = geometryRows[0]!.state;
      // primary_unit = the smallest covering geometry bound as role='primary_unit'
      // (an HD/GMU or the statewide anchor) — NOT merely the smallest covering
      // polygon, which could be an overlay (restricted area / CWD zone). Null when
      // no primary-unit geometry covers the point (only overlays do).
      const primaryUnitRow = geometryRows.find((r) => r.role === "primary_unit");
      const primaryUnitName = primaryUnitRow?.name ?? null;
      // Citation for the resolved jurisdiction itself (the covering geometry's
      // SourceCitation) — used as the sole `sources` entry on a PARTIAL response
      // (jurisdiction resolved, species absent) so the invariant "data_freshness
      // null iff sources empty" holds and the jurisdiction is cited per ADR-001.
      // Prefer the primary-unit geometry; fall back to the smallest covering
      // (overlay-only) geometry when no primary unit covers the point.
      const jurisdictionSource: SourceCitation =
        primaryUnitRow?.source ?? geometryRows[0]!.source;

      // ── 2. Jurisdiction-scoped season fetch ───────────────────────────────
      // Seasons for the record(s) bound to the geometries covering THIS point
      // (via jurisdiction_binding) — not the whole state. Re-uses the same WKT
      // point literal; ST_Covers runs on the GiST index.
      const rawSeasonRows = await client.query<SeasonRow>(
        REGULATION_SEASONS_SQL,
        [`SRID=4326;POINT(${lng} ${lat})`, species],
      );

      // ── 3. Schema-version gate ────────────────────────────────────────────
      // Partition rows by schema_version; unsupported rows are excluded and
      // an UNSUPPORTED_SCHEMA_VERSION Warning is emitted per ADR-006.
      const gated = gateBySchemaVersion(
        rawSeasonRows.map((r) => ({
          ...r,
          schema_version: r.rr_schema_version,
        })),
      );
      warnings.push(...gated.warnings);

      // Binding fan-out can bind one regulation_record via multiple covering
      // geometries, yielding duplicate (record, season) rows — de-dup on
      // (jurisdiction_code, license_year, season id) so a season is counted once.
      const seenSeasonKeys = new Set<string>();
      const seasonRows = gated.included.filter((r) => {
        const key = `${r.rr_jurisdiction_code}|${r.rr_license_year}|${r.sd_id}`;
        if (seenSeasonKeys.has(key)) return false;
        seenSeasonKeys.add(key);
        return true;
      });

      // ── 4. Collect unique SourceCitation objects ──────────────────────────
      // Deduplicate by citation `id` — both rr.source and sd.source contribute.
      const sourcesById = new Map<string, SourceCitation>();
      for (const row of seasonRows) {
        const rrSrc = row.rr_source;
        const sdSrc = row.sd_source;
        if (!sourcesById.has(rrSrc.id)) sourcesById.set(rrSrc.id, rrSrc);
        if (!sourcesById.has(sdSrc.id)) sourcesById.set(sdSrc.id, sdSrc);
      }
      const seasonSources = Array.from(sourcesById.values());

      // ── 5. Derive license_year from the first row ─────────────────────────
      // Rows come only from the point's covering jurisdiction(s) (step 2) and are
      // ordered license_year DESC, so the first row carries the most-recent
      // applicable regulation for this coordinate. S09.1b handles multi-year and
      // multi-jurisdiction fan-out (distinct overlays).
      const firstRow = seasonRows[0];
      const licenseYear = firstRow?.rr_license_year ?? null;

      // ── 6. Build ResolvedSeasonWindow array ────────────────────────────────
      // Confidence is inherited from the parent regulation_record (ADR-017
      // parent-inheritance rule). weapon_type and residency are nullable columns
      // in season_definition (see initial_schema.sql:63/70).
      const windows = seasonRows.map((row) => ({
        name: row.sd_name,
        opens: row.sd_opens,
        closes: row.sd_closes,
        weapon_type: (row.sd_weapon_type ?? null) as WeaponType | null,
        residency: (row.sd_residency ?? null) as Residency | null,
        closure_predicate: row.sd_closure_predicate ?? null,
        verbatim_rule: row.sd_verbatim_rule,
        page_reference: row.sd_page_reference ?? null,
        confidence: row.rr_confidence,
        source: row.sd_source,
      }));

      // ── 7. Determine season status ─────────────────────────────────────────
      // Simple structural status from the input date vs window date ranges.
      // S09.1b owns the full status resolution including conditionally_closed.
      const queryDateMs = Date.parse(date);
      const status: "in_season" | "out_of_season" | "no_season_defined" =
        windows.length === 0
          ? "no_season_defined"
          : windows.some((w) => {
                const opensMs = Date.parse(w.opens);
                const closesMs = Date.parse(w.closes);
                return (
                  !Number.isNaN(queryDateMs) &&
                  !Number.isNaN(opensMs) &&
                  !Number.isNaN(closesMs) &&
                  queryDateMs >= opensMs &&
                  queryDateMs <= closesMs
                );
              })
            ? "in_season"
            : "out_of_season";

      // ── 8. SeasonsSection (null when no windows were found) ────────────────
      const seasonsSection =
        windows.length > 0 && firstRow !== undefined
          ? {
              status,
              windows,
              // The regulation_record source is the regulation anchor for the
              // section-level `source` field. Per-window sources are on each window.
              source: firstRow.rr_source,
            }
          : null;

      // ── 9. Coverage ────────────────────────────────────────────────────────
      // Jurisdiction ALWAYS resolves here — the "no covering geometry" case
      // early-returned above, so a bound geometry covers the point. Species is
      // "full" iff ≥1 season row survived gating. A jurisdiction that resolved
      // but has no data for the species is PARTIAL, NOT none — do not collapse it
      // (Shape C contract: architecture.md §"Response shape"; epic S09.1 mixed
      // boundary). Only the total-gap early-return above is `overall:"none"`.
      const speciesCovered = seasonRows.length > 0;
      const speciesCoverage = speciesCovered ? ("full" as const) : ("none" as const);
      const overallCoverage = speciesCovered ? ("full" as const) : ("partial" as const);

      // Full → the season/record citations; partial → the resolved jurisdiction's
      // own geometry citation (so `sources` is non-empty and `data_freshness` is
      // non-null on a partial response — the invariant holds; only the total-gap
      // early-return carries `sources: []` + `data_freshness: null`).
      const responseSources = speciesCovered ? seasonSources : [jurisdictionSource];

      // ── 10. Compose and validate the Shape C envelope ──────────────────────
      const response: GetRegulationsResponse = {
        query: { lat, lng, species, date },
        resolved: {
          // The point resolved to a bound geometry → jurisdiction is non-null
          // whether or not the species has data (species-absence is `species:"none"`
          // + `overall:"partial"`, not a null jurisdiction).
          jurisdiction: {
            state: resolvedState,
            primary_unit: primaryUnitName,
            overlays: [],
          },
          species_canonical: speciesCovered ? species : null,
          license_year: licenseYear,
        },
        seasons: seasonsSection,
        tags: null,
        methods: null,
        reporting: null,
        contacts: null,
        additional_rules: null,
        sources: responseSources,
        meta: {
          schema_version: 2,
          generated_at: generatedAt,
          data_freshness: buildDataFreshness(responseSources, generatedAt),
          coverage: {
            jurisdiction: "full",
            species: speciesCoverage,
            overall: overallCoverage,
          },
          // Placeholder — buildStructuredToolResult is the SOLE writer of
          // meta.warnings and assigns the `warnings` arg (which already carries
          // the gated UNSUPPORTED_SCHEMA_VERSION entries) passed below.
          warnings: [],
        },
      };

      return buildStructuredToolResult(
        response,
        getRegulationsResponseSchema,
        warnings,
        renderThinText,
      );
    } finally {
      // Swallow close() errors — a teardown failure must not mask the query result
      // or produce a hard 500. Mirrors the health-check.ts teardown discipline.
      try {
        await client.close();
      } catch {
        // intentionally ignored
      }
    }
  };
}
