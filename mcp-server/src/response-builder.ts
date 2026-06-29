/**
 * Reusable Shape C serving mechanisms for the HuntReady MCP server.
 *
 * All exports here are the shared primitives that E09/E10 inherit — they do
 * NOT re-derive null-bearing-section handling, schema-version gating, data
 * freshness computation, zod validation, or annotation logic. Every tool
 * handler in E09/E10 calls into this module rather than rolling its own copy.
 *
 * Architectural references:
 *   - ADR-011: Shape C response envelope (null = not applicable, omitted = never)
 *   - ADR-013: Server returns structure, client composes presentation
 *   - ADR-006: Schema-version gating → meta.warnings, never silent-drop, never hard-error
 *   - ADR-001/ADR-008: verbatim + confidence pass through unchanged, no normalization
 */

import { getRegulationsResponseSchema } from "./output-schema.js";
import type { GetRegulationsResponse, Warning } from "./types/response.js";

// ---------------------------------------------------------------------------
// MCP read-only tool annotations
// ---------------------------------------------------------------------------

/**
 * Standard MCP read-only annotation set.
 *
 * Pass this object to `registerTool({ annotations: READ_ONLY_TOOL_ANNOTATIONS })`
 * in every E09/E10 tool handler. Kept as a plain `as const` object (no SDK
 * import) so it remains Node-importable in vitest tests without needing the
 * workerd runtime.
 */
export const READ_ONLY_TOOL_ANNOTATIONS = {
  readOnlyHint: true,
  idempotentHint: true,
  openWorldHint: false,
} as const;

// ---------------------------------------------------------------------------
// Schema-version gating
// ---------------------------------------------------------------------------

/**
 * Schema versions the serving stack currently understands.
 * The response envelope's `meta.schema_version` is always `2`.
 * Add future versions here — never remove old ones until a deprecation ADR lands.
 */
export const SUPPORTED_SCHEMA_VERSIONS: readonly number[] = [2];

// ---------------------------------------------------------------------------
// Data freshness
// ---------------------------------------------------------------------------

/** Number of days after which a response is considered stale. */
export const STALE_THRESHOLD_DAYS = 180;

/**
 * Parse a source `publication_date` (a canonical ISO calendar date, YYYY-MM-DD)
 * to epoch milliseconds, failing loud on anything that is not a real,
 * canonically-formatted date.
 *
 * `Date.parse` alone is NOT sufficient: its legacy fallback parser accepts
 * non-canonical strings ("2026-1-1", "01/02/2026") — often interpreted in LOCAL
 * time with different semantics — and some impossible dates roll over rather
 * than rejecting. So we (1) require the exact `YYYY-MM-DD` shape, then (2)
 * round-trip the parsed UTC date back to `YYYY-MM-DD` and require it to equal the
 * input, which rejects impossible calendar dates (e.g. "2026-02-30", which would
 * otherwise become 2026-03-02). Freshness is a correctness property (ADR-001),
 * so a malformed/impossible date throws rather than being treated as fresh.
 */
function parseSourceDate(value: string): number {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(
      `buildDataFreshness: source publication_date is not a canonical YYYY-MM-DD date: ${JSON.stringify(value)}`,
    );
  }
  const ms = Date.parse(`${value}T00:00:00Z`);
  if (Number.isNaN(ms) || new Date(ms).toISOString().slice(0, 10) !== value) {
    throw new Error(
      `buildDataFreshness: source publication_date is not a real calendar date: ${JSON.stringify(value)}`,
    );
  }
  return ms;
}

/**
 * Compute the data freshness block from the contributing source citations.
 *
 * @param sources - The sources whose `publication_date` values are compared.
 *   Must be non-empty — a freshness block with zero sources is builder misuse.
 * @param generatedAt - ISO-8601 timestamp for the response generation time
 *   (e.g. `new Date().toISOString()`).
 *
 * Date comparison strategy: EVERY source `publication_date` is parsed and
 * validated via `parseSourceDate` (canonical `YYYY-MM-DD` format check + UTC
 * round-trip — see its JSDoc), and `most_recent`/`stalest` are selected by the
 * parsed UTC timestamp, NOT lexicographically. Selecting numerically (rather
 * than by string order) means the selection does not presuppose well-formed
 * input, and validating every source up front means a malformed sibling cannot
 * escape into `most_recent_source_date` unvalidated. The original input strings
 * (not reformatted dates) are returned, so no representation drift is
 * introduced.
 *
 * `is_stale` uses `Date.parse` on the full `generatedAt` ISO-8601 timestamp
 * (which includes a timezone offset and is therefore unambiguous) minus the
 * `parseSourceDate`-derived UTC timestamp of `stalest_source_date`. `generatedAt`
 * itself is guarded for parseability (a NaN there is a server bug, not bad
 * upstream data).
 */
export function buildDataFreshness(
  sources: readonly { publication_date: string }[],
  generatedAt: string,
): {
  most_recent_source_date: string;
  stalest_source_date: string;
  is_stale: boolean;
} {
  if (sources.length === 0) {
    throw new Error(
      "buildDataFreshness: sources must be non-empty — a freshness block with no contributing source is builder misuse",
    );
  }

  // Fail loud on an unparseable generatedAt. `Date.parse` returns NaN for a
  // malformed timestamp, and every NaN comparison is false — so a bad
  // generatedAt would silently yield `is_stale: false`, making stale data
  // look fresh. Freshness is a correctness property (ADR-001), so this is a
  // throw, not a silent default. (generatedAt is server-generated, so a NaN
  // here is a server bug, not bad upstream data.)
  const generatedAtMs = Date.parse(generatedAt);
  if (Number.isNaN(generatedAtMs)) {
    throw new Error(
      `buildDataFreshness: generatedAt is not a parseable timestamp: ${JSON.stringify(generatedAt)}`,
    );
  }

  // Parse and validate EVERY source date with parseSourceDate (canonical
  // YYYY-MM-DD + round-trip — see its JSDoc), then select min/max by the parsed
  // timestamp, NOT lexicographically. Two gaps are closed here: (1) validating
  // only the selected stalest would let a malformed sibling that is not the
  // lexicographic minimum escape validation and be returned as
  // most_recent_source_date; (2) lexicographic min/max presupposes well-formed
  // input, which a bad sibling breaks. Validating all up front and selecting
  // numerically closes both. Freshness is a correctness property (ADR-001), so a
  // malformed/impossible date is a loud throw, not silently treated as fresh.
  // This guard lives at the COMPUTATION site (not as a value-format regex on the
  // zod output schema): you literally cannot compute days-stale from a non-date,
  // whereas rejecting passthrough data at the schema boundary would over-
  // constrain legitimately-stored data (ADR-001 authority-preserved). The
  // original strings (not reformatted dates) are returned — no representation
  // drift.
  let mostRecent = sources[0].publication_date;
  let stalest = sources[0].publication_date;
  let mostRecentMs = -Infinity;
  let stalestMs = Infinity;

  for (const src of sources) {
    const ms = parseSourceDate(src.publication_date);
    if (ms > mostRecentMs) {
      mostRecent = src.publication_date;
      mostRecentMs = ms;
    }
    if (ms < stalestMs) {
      stalest = src.publication_date;
      stalestMs = ms;
    }
  }

  const ageMs = generatedAtMs - stalestMs;
  const is_stale = ageMs / 86_400_000 > STALE_THRESHOLD_DAYS;

  return {
    most_recent_source_date: mostRecent,
    stalest_source_date: stalest,
    is_stale,
  };
}

// ---------------------------------------------------------------------------
// Schema-version gating
// ---------------------------------------------------------------------------

/**
 * Partition `rows` by whether their `schema_version` is in `supported`.
 *
 * Per ADR-006: unsupported rows are EXCLUDED and a `Warning` is emitted for
 * each one. This is never a silent drop (the Warning is always present) and
 * never a hard error (the call succeeds with the `included` subset). The
 * caller is responsible for appending the returned warnings to
 * `meta.warnings`.
 *
 * @param rows - Rows to partition; each must carry `schema_version: number`.
 * @param supported - Allow-list of schema versions; defaults to
 *   `SUPPORTED_SCHEMA_VERSIONS`.
 */
export function gateBySchemaVersion<T extends { schema_version: number }>(
  rows: readonly T[],
  supported: readonly number[] = SUPPORTED_SCHEMA_VERSIONS,
): { included: T[]; warnings: Warning[] } {
  const included: T[] = [];
  const warnings: Warning[] = [];

  for (const row of rows) {
    if (supported.includes(row.schema_version)) {
      included.push(row);
    } else {
      warnings.push({
        code: "UNSUPPORTED_SCHEMA_VERSION",
        section: "overall",
        message: `schema_version ${row.schema_version} is unsupported (supported: ${supported.join(", ")}); row excluded`,
      });
    }
  }

  return { included, warnings };
}

// ---------------------------------------------------------------------------
// Thin text rendering (ADR-013: server returns structure, client composes)
// ---------------------------------------------------------------------------

/**
 * Produce a minimal markdown derivative from the structured `GetRegulationsResponse`.
 *
 * This is assembled MECHANICALLY from the structured fields only — it is NOT
 * a server-composed overview or headline (ADR-013 forbids server-side
 * summarization). The text is kept factual and field-derived: a coverage
 * summary line, section presence inventory, and warning count. Each client
 * (web, plugin, etc.) composes its own richer presentation because only the
 * client knows its display context.
 */
export function renderThinText(response: GetRegulationsResponse): string {
  const { meta, seasons, tags, methods, reporting, contacts } = response;

  const coverageLine =
    `Coverage — jurisdiction: ${meta.coverage.jurisdiction}, ` +
    `species: ${meta.coverage.species}, ` +
    `overall: ${meta.coverage.overall}`;

  const sectionLines = [
    `seasons: ${seasons !== null ? "present" : "null"}`,
    `tags: ${tags !== null ? "present" : "null"}`,
    `methods: ${methods !== null ? "present" : "null"}`,
    `reporting: ${reporting !== null ? "present" : "null"}`,
    `contacts: ${contacts !== null ? "present" : "null"}`,
  ];

  const warningLine =
    meta.warnings.length > 0
      ? `Warnings (${meta.warnings.length}): ${meta.warnings.map((w) => w.code).join(", ")}`
      : "Warnings: none";

  return [coverageLine, `Sections — ${sectionLines.join(", ")}`, warningLine].join("\n");
}

// ---------------------------------------------------------------------------
// Structured tool result builder
// ---------------------------------------------------------------------------

/**
 * Validate `response` against the zod output schema and return the
 * `{ structuredContent, content }` payload the MCP SDK expects.
 *
 * Throws if zod validation fails — the server MUST conform to the declared
 * `outputSchema`; a validation failure is a server programming error, not a
 * client error.
 *
 * `verbatim_rule` and `confidence` values are passed through byte-identically
 * — this function performs no normalization (ADR-001/ADR-008).
 */
export function buildStructuredToolResult(response: GetRegulationsResponse): {
  structuredContent: Record<string, unknown>;
  content: { type: "text"; text: string }[];
} {
  const parsed = getRegulationsResponseSchema.safeParse(response);

  if (!parsed.success) {
    const paths = parsed.error.issues.map((i) => i.path.join(".")).join(", ");
    throw new Error(
      `GetRegulationsResponse failed schema validation — failing paths: ${paths}`,
    );
  }

  return {
    // any-free boundary cast to the SDK's `structuredContent: Record<string, unknown>`.
    // `response` is the validated GetRegulationsResponse; `as unknown as` is the
    // single sanctioned seam (mirrors the db.ts boundary-cast discipline).
    structuredContent: response as unknown as Record<string, unknown>,
    content: [{ type: "text" as const, text: renderThinText(response) }],
  };
}
