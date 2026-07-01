/**
 * Shape C response mechanism tests (S08.3 + T8 updates).
 *
 * Covers every S08.3 AC that requires no live DB:
 *   - null-bearing serialization (ADR-011: null ≠ omitted)
 *   - no-data vs not-required coverage distinction
 *   - all three Coverage values
 *   - buildDataFreshness (is_stale, extremes, null on empty sources — Decision 1)
 *   - sources[] presence
 *   - buildStructuredToolResult happy + negative (schema-violating → throws)
 *   - schema-version gating end-to-end: warnings thread into buildStructuredToolResult (Decision 3a)
 *   - verbatim_rule + confidence passthrough (byte-identical, never normalised)
 *   - read-only tool annotations shape
 */
import { describe, it, expect } from "vitest";
import {
  READ_ONLY_TOOL_ANNOTATIONS,
  buildDataFreshness,
  buildStructuredToolResult,
  gateBySchemaVersion,
  renderThinText,
} from "../src/response-builder.js";
import { getRegulationsResponseSchema } from "../src/output-schema.js";
import type {
  GetRegulationsResponse,
  SeasonsSection,
  ReportingSection,
} from "../src/types/response.js";

// ---------------------------------------------------------------------------
// Shared fixture helpers
// ---------------------------------------------------------------------------

/** Minimal valid SourceCitation. */
function makeSource(overrides: Partial<{
  id: string;
  publication_date: string;
}> = {}): GetRegulationsResponse["sources"][number] {
  return {
    id: overrides.id ?? "test-source-2026",
    agency: "Test Agency",
    title: "Test Regulations 2026",
    url: "https://example.gov/regs/2026",
    publication_date: overrides.publication_date ?? "2026-01-01",
    document_type: "annual_regulations",
    supersedes: null,
    page_reference: null,
  };
}

/** Minimal valid SeasonsSection. */
function makeSeasonsSection(): SeasonsSection {
  return {
    status: "out_of_season",
    windows: [],
    source: makeSource(),
  };
}

/** Minimal valid ReportingSection with empty obligations array. */
function makeReportingSection(): ReportingSection {
  return {
    obligations: [],
    source: makeSource(),
  };
}

/**
 * Build a minimal but fully-valid GetRegulationsResponse.
 * All sections are null by default; pass overrides to populate them.
 */
function makeResponse(
  overrides: Partial<GetRegulationsResponse> = {},
): GetRegulationsResponse {
  const src = makeSource();
  const generatedAt = "2026-06-29T00:00:00Z";
  const base: GetRegulationsResponse = {
    query: { lat: 39.7, lng: -104.9, species: "mule_deer", date: "2026-09-15" },
    resolved: {
      jurisdiction: {
        state: "US-CO",
        primary_unit: "CO-GMU-20",
        overlays: [],
      },
      species_canonical: "mule_deer",
      license_year: 2026,
    },
    seasons: null,
    tags: null,
    methods: null,
    reporting: null,
    contacts: null,
    additional_rules: null,
    sources: [src],
    meta: {
      schema_version: 2,
      generated_at: generatedAt,
      data_freshness: buildDataFreshness([src], generatedAt),
      coverage: {
        jurisdiction: "full",
        species: "full",
        overall: "full",
      },
      warnings: [],
    },
  };
  return { ...base, ...overrides };
}

// ---------------------------------------------------------------------------
// (a) Null-bearing serialisation: sections stay present-with-null, not omitted
// ---------------------------------------------------------------------------
describe("null-bearing serialisation", () => {
  it("all null sections are present as keys in JSON-serialised output", () => {
    const fixture = makeResponse(); // all sections null
    const parsed: Record<string, unknown> = JSON.parse(JSON.stringify(fixture));

    for (const key of ["seasons", "tags", "methods", "reporting", "contacts", "additional_rules"] as const) {
      expect(Object.keys(parsed).includes(key), `key "${key}" must be present`).toBe(true);
      expect(parsed[key], `parsed.${key} must be null`).toBeNull();
    }
  });
});

// ---------------------------------------------------------------------------
// (b) no-data vs not-required: coverage reflects data availability, not section shape
// ---------------------------------------------------------------------------
describe("no-data vs not-required coverage distinction", () => {
  it("null section pairs with coverage=none overall", () => {
    const fixture = makeResponse({
      reporting: null,
      meta: {
        schema_version: 2,
        generated_at: "2026-06-29T00:00:00Z",
        data_freshness: buildDataFreshness([makeSource()], "2026-06-29T00:00:00Z"),
        coverage: { jurisdiction: "none", species: "none", overall: "none" },
        warnings: [],
      },
    });
    expect(fixture.reporting).toBeNull();
    expect(fixture.meta.coverage.overall).toBe("none");
  });

  it("populated-but-empty section (obligations:[]) can coexist with coverage=full", () => {
    const fixture = makeResponse({
      reporting: makeReportingSection(), // obligations: [] — present but empty
      meta: {
        schema_version: 2,
        generated_at: "2026-06-29T00:00:00Z",
        data_freshness: buildDataFreshness([makeSource()], "2026-06-29T00:00:00Z"),
        coverage: { jurisdiction: "full", species: "full", overall: "full" },
        warnings: [],
      },
    });
    expect(fixture.reporting).not.toBeNull();
    expect(fixture.reporting!.obligations).toEqual([]);
    expect(fixture.meta.coverage.overall).toBe("full");
    // Must pass zod validation
    expect(() =>
      buildStructuredToolResult(fixture, getRegulationsResponseSchema, [], renderThinText),
    ).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// (c) All three Coverage values appear in a single fixture
// ---------------------------------------------------------------------------
describe("Coverage type values", () => {
  it("all three coverage values full/partial/none appear in coverage fields", () => {
    const fixture = makeResponse({
      meta: {
        schema_version: 2,
        generated_at: "2026-06-29T00:00:00Z",
        data_freshness: buildDataFreshness([makeSource()], "2026-06-29T00:00:00Z"),
        coverage: { jurisdiction: "full", species: "partial", overall: "none" },
        warnings: [],
      },
    });
    const { coverage } = fixture.meta;
    expect(coverage.jurisdiction).toBe("full");
    expect(coverage.species).toBe("partial");
    expect(coverage.overall).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// (d) buildDataFreshness
// ---------------------------------------------------------------------------
describe("buildDataFreshness", () => {
  const GENERATED_AT = "2026-06-29T00:00:00Z";

  it("is_stale=true when publication date is far in the past", () => {
    const result = buildDataFreshness([{ publication_date: "2020-01-01" }], GENERATED_AT);
    expect(result).not.toBeNull();
    expect(result?.is_stale).toBe(true);
  });

  it("is_stale=false when publication date is recent", () => {
    const result = buildDataFreshness([{ publication_date: "2026-06-01" }], GENERATED_AT);
    expect(result).not.toBeNull();
    expect(result?.is_stale).toBe(false);
  });

  it("returns null when sources array is empty (Decision 1: data_freshness null iff sources empty)", () => {
    // Decision 1 invariant: buildDataFreshness([]) returns null rather than throwing.
    // A total-coverage-gap response (sources:[], data_freshness:null) is valid.
    const result = buildDataFreshness([], GENERATED_AT);
    expect(result).toBeNull();
  });

  it("throws when generatedAt is not a parseable timestamp (no silent is_stale=false)", () => {
    expect(() =>
      buildDataFreshness([{ publication_date: "2020-01-01" }], "not-a-date"),
    ).toThrow();
  });

  it("throws when generatedAt is parseable but has NO timezone designator (would be parsed as local time)", () => {
    // "2026-06-29T12:00:00" (no trailing Z / offset) is parseable but interpreted
    // as LOCAL time, which makes is_stale timezone-dependent — reject it.
    expect(() =>
      buildDataFreshness([{ publication_date: "2020-01-01" }], "2026-06-29T12:00:00"),
    ).toThrow();
  });

  it("accepts a generatedAt with a ±HH:MM offset (not only trailing Z)", () => {
    const result = buildDataFreshness(
      [{ publication_date: "2026-06-01" }],
      "2026-06-29T12:00:00+02:00",
    );
    expect(result).not.toBeNull();
    expect(result?.is_stale).toBe(false);
  });

  it("throws when a source publication_date is unparseable (no silent is_stale=false)", () => {
    expect(() =>
      buildDataFreshness([{ publication_date: "TBD" }], GENERATED_AT),
    ).toThrow();
  });

  it("throws on a malformed source date even when it is NOT the stalest (every source validated, not just the selected min)", () => {
    // "not-a-date" sorts lexicographically AFTER "2025-06-01", so it is not the
    // stalest — an earlier impl that only validated the selected stalest would
    // have let it through into most_recent_source_date unvalidated.
    expect(() =>
      buildDataFreshness(
        [{ publication_date: "2025-06-01" }, { publication_date: "not-a-date" }],
        GENERATED_AT,
      ),
    ).toThrow();
  });

  it("throws on an IMPOSSIBLE calendar date (2026-02-30) that Date.parse would roll over", () => {
    // Date.parse("2026-02-30T00:00:00Z") rolls to 2026-03-02 rather than
    // rejecting; the round-trip check catches it.
    expect(() =>
      buildDataFreshness([{ publication_date: "2026-02-30" }], GENERATED_AT),
    ).toThrow();
  });

  it("throws on a non-canonical date format (2026-1-1, not zero-padded)", () => {
    expect(() =>
      buildDataFreshness([{ publication_date: "2026-1-1" }], GENERATED_AT),
    ).toThrow();
  });

  it("throws on a slash-delimited date (2026/06/01) that Date.parse's legacy parser would accept", () => {
    expect(() =>
      buildDataFreshness([{ publication_date: "2026/06/01" }], GENERATED_AT),
    ).toThrow();
  });

  it("most_recent_source_date picks the latest date across multiple sources", () => {
    const result = buildDataFreshness(
      [
        { publication_date: "2024-03-01" },
        { publication_date: "2026-06-01" },
        { publication_date: "2023-11-15" },
      ],
      GENERATED_AT,
    );
    expect(result).not.toBeNull();
    expect(result?.most_recent_source_date).toBe("2026-06-01");
  });

  it("stalest_source_date picks the earliest date across multiple sources", () => {
    const result = buildDataFreshness(
      [
        { publication_date: "2024-03-01" },
        { publication_date: "2026-06-01" },
        { publication_date: "2023-11-15" },
      ],
      GENERATED_AT,
    );
    expect(result).not.toBeNull();
    expect(result?.stalest_source_date).toBe("2023-11-15");
  });

  it("single source: most_recent and stalest are the same", () => {
    const result = buildDataFreshness([{ publication_date: "2026-01-01" }], GENERATED_AT);
    expect(result).not.toBeNull();
    expect(result?.most_recent_source_date).toBe("2026-01-01");
    expect(result?.stalest_source_date).toBe("2026-01-01");
  });
});

// ---------------------------------------------------------------------------
// (e) sources[] present and non-empty in a populated fixture
// ---------------------------------------------------------------------------
describe("sources[] field", () => {
  it("a populated fixture has a non-empty sources array", () => {
    const fixture = makeResponse();
    expect(Array.isArray(fixture.sources)).toBe(true);
    expect(fixture.sources.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// structuredContent happy path + negative (schema-violating → throws)
// ---------------------------------------------------------------------------
describe("buildStructuredToolResult", () => {
  it("happy path: returns structuredContent deep-equal to the fixture + non-empty text", () => {
    const fixture = makeResponse();
    const result = buildStructuredToolResult(
      fixture,
      getRegulationsResponseSchema,
      [],
      renderThinText,
    );

    expect(result.structuredContent).toEqual(fixture);
    expect(Array.isArray(result.content)).toBe(true);
    expect(result.content.length).toBeGreaterThan(0);
    expect(result.content[0].type).toBe("text");
    expect(result.content[0].text.length).toBeGreaterThan(0);
  });

  it("negative: throws when meta.schema_version is not 2", () => {
    const fixture = makeResponse();
    // Deliberate schema violation — cast through unknown to bypass tsc.
    const bad = {
      ...fixture,
      meta: { ...fixture.meta, schema_version: 3 },
    } as unknown as GetRegulationsResponse;

    expect(() =>
      buildStructuredToolResult(bad, getRegulationsResponseSchema, [], renderThinText),
    ).toThrow();
  });

  it("negative: throws when an unknown top-level key is present (strict envelope rejects server-composed overview/headline drift)", () => {
    const fixture = makeResponse();
    const bad = {
      ...fixture,
      overview: "server-composed summary — forbidden by ADR-013",
    } as unknown as GetRegulationsResponse;

    expect(() =>
      buildStructuredToolResult(bad, getRegulationsResponseSchema, [], renderThinText),
    ).toThrow();
  });

  it("empty sources with data_freshness:null is VALID — total-coverage-gap response succeeds (Decision 1)", () => {
    // Decision 1: sources:[] + data_freshness:null is the canonical total-coverage-gap shape.
    // buildDataFreshness([]) returns null (no longer throws); the schema permits null freshness.
    const fixture = makeResponse({
      sources: [],
      meta: {
        schema_version: 2,
        generated_at: "2026-06-29T00:00:00Z",
        data_freshness: null,
        coverage: { jurisdiction: "none", species: "none", overall: "none" },
        warnings: [],
      },
    });
    let result: ReturnType<typeof buildStructuredToolResult> | undefined;
    expect(() => {
      result = buildStructuredToolResult(
        fixture,
        getRegulationsResponseSchema,
        [],
        renderThinText,
      );
    }).not.toThrow();
    // structuredContent reflects zero sources and null freshness.
    const sc = result!.structuredContent as unknown as GetRegulationsResponse;
    expect(sc.sources).toEqual([]);
    expect(sc.meta.data_freshness).toBeNull();
  });

  it("negative: throws when a meta.warnings element carries an unknown key (warningSchema is strict)", () => {
    // The builder writes `warnings` into payload.meta.warnings before zod validation.
    // Pass the bad warning as the `warnings` arg so it reaches the strict schema check.
    const fixture = makeResponse();
    const badWarnings = [
      {
        code: "STALE_SOURCE",
        section: "overall",
        message: "x",
        extra: "server-composed field — forbidden",
      },
      // Cast through unknown: narrowest possible — we need to inject an extra key
      // that `warningSchema.strict()` must reject; `Warning` type doesn't allow `extra`.
    ] as unknown as import("../src/types/response.js").Warning[];

    expect(() =>
      buildStructuredToolResult(fixture, getRegulationsResponseSchema, badWarnings, renderThinText),
    ).toThrow();
  });

  it("Decision 3a — gating: unsupported-schema-version warning threads from gateBySchemaVersion into meta.warnings (UNSUPPORTED_SCHEMA_VERSION, section=overall)", () => {
    // Simulate an E09 tool handler that gates DB rows before building the response.
    // The unsupported row is excluded; its warning travels through buildStructuredToolResult.
    const { warnings } = gateBySchemaVersion([
      { schema_version: 2, id: "supported-row" },
      { schema_version: 999, id: "future-row" }, // unsupported → excluded, warning emitted
    ]);

    // Build a response that only includes the supported row's data.
    const fixture = makeResponse();

    const result = buildStructuredToolResult(
      fixture,
      getRegulationsResponseSchema,
      warnings, // ← gateBySchemaVersion warnings threaded in here
      renderThinText,
    );

    // (a) The unsupported row is excluded — the fixture itself only has supported data.
    // (b) The builder wrote the gating warning into meta.warnings.
    const sc = result.structuredContent as unknown as GetRegulationsResponse;
    expect(sc.meta.warnings).toHaveLength(1);
    expect(sc.meta.warnings[0].code).toBe("UNSUPPORTED_SCHEMA_VERSION");
    expect(sc.meta.warnings[0].section).toBe("overall");
    expect(sc.meta.warnings[0].message).toContain("999");
  });

  it("Decision 3b — negative: throws when payload violates the schema (extra key rejected by .strict())", () => {
    // Proves the 4-arg generalization did not weaken the S08.3 validation bite.
    // An extra server-composed key (like `overview`) is forbidden by ADR-013 and
    // rejected by the .strict() envelope schema.
    const fixture = makeResponse();
    // Cast through unknown — narrowest possible; we need to add an illegal key.
    const bad = { ...fixture, overview: "forbidden server summary" } as unknown as GetRegulationsResponse;

    expect(() =>
      buildStructuredToolResult(bad, getRegulationsResponseSchema, [], renderThinText),
    ).toThrow();
  });
});

// ---------------------------------------------------------------------------
// Schema-version gating
// ---------------------------------------------------------------------------
describe("gateBySchemaVersion", () => {
  it("includes supported rows and emits UNSUPPORTED_SCHEMA_VERSION warning for unsupported", () => {
    const { included, warnings } = gateBySchemaVersion([
      { schema_version: 2, id: "a" },
      { schema_version: 999, id: "b" },
    ]);

    // v2 row is included
    expect(included).toHaveLength(1);
    expect(included[0]).toMatchObject({ schema_version: 2, id: "a" });

    // v999 row is NOT in included
    const includedIds = included.map((r) => r.id);
    expect(includedIds).not.toContain("b");

    // Exactly one warning, correct shape
    expect(warnings).toHaveLength(1);
    expect(warnings[0].code).toBe("UNSUPPORTED_SCHEMA_VERSION");
    expect(warnings[0].section).toBe("overall");
    expect(warnings[0].message).toContain("999");
  });

  it("emits zero warnings when all rows are supported", () => {
    const { included, warnings } = gateBySchemaVersion([
      { schema_version: 2, id: "x" },
    ]);
    expect(included).toHaveLength(1);
    expect(warnings).toHaveLength(0);
  });

  it("emits one warning per unsupported row", () => {
    const { included, warnings } = gateBySchemaVersion([
      { schema_version: 999, id: "p" },
      { schema_version: 888, id: "q" },
    ]);
    expect(included).toHaveLength(0);
    expect(warnings).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Verbatim_rule + confidence passthrough
// ---------------------------------------------------------------------------
describe("verbatim_rule and confidence passthrough", () => {
  it("byte-identical verbatim_rule (with newline and soft-hyphen) survives buildStructuredToolResult", () => {
    // Soft-hyphen U+00AD embedded in the verbatim rule string.
    const verbatimWithSoftHyphen =
      "Archery season: Sep­15–Nov 30.\nCheck regulations for zone-specific closures.";

    const src = makeSource();
    const windowSource = makeSource({ id: "season-source" });

    const seasonsSection: SeasonsSection = {
      status: "out_of_season",
      windows: [
        {
          name: "General Archery",
          opens: "2026-09-15",
          closes: "2026-11-30",
          weapon_type: "archery",
          residency: null,
          closure_predicate: null,
          verbatim_rule: verbatimWithSoftHyphen,
          page_reference: "p. 42",
          confidence: "medium",
          source: windowSource,
        },
      ],
      source: src,
    };

    const fixture = makeResponse({ seasons: seasonsSection });
    const result = buildStructuredToolResult(
      fixture,
      getRegulationsResponseSchema,
      [],
      renderThinText,
    );

    // Cast through unknown to read back the structuredContent as a typed response.
    const back = result.structuredContent as unknown as GetRegulationsResponse;
    expect(back.seasons).not.toBeNull();
    expect(back.seasons!.windows[0].verbatim_rule).toBe(verbatimWithSoftHyphen);
    expect(back.seasons!.windows[0].confidence).toBe("medium");

    // Confidence must never be normalised to "high".
    expect(back.seasons!.windows[0].confidence).not.toBe("high");
  });
});

// ---------------------------------------------------------------------------
// renderThinText — thin, mechanically-derived markdown (ADR-013)
// ---------------------------------------------------------------------------
describe("renderThinText", () => {
  it("produces a non-empty thin derivative with coverage, section inventory, and warnings", () => {
    const fixture = makeResponse({
      seasons: makeSeasonsSection(), // present
      reporting: null, // null
      meta: {
        schema_version: 2,
        generated_at: "2026-06-29T00:00:00Z",
        data_freshness: buildDataFreshness([makeSource()], "2026-06-29T00:00:00Z"),
        coverage: { jurisdiction: "full", species: "partial", overall: "partial" },
        warnings: [
          { code: "UNSUPPORTED_SCHEMA_VERSION", section: "overall", message: "x" },
        ],
      },
    });

    const text = renderThinText(fixture);

    // Coverage values are surfaced.
    expect(text).toContain("full");
    expect(text).toContain("partial");
    // Section presence inventory distinguishes present vs null.
    expect(text).toContain("seasons");
    expect(text).toContain("reporting");
    // Warning codes are surfaced.
    expect(text).toContain("UNSUPPORTED_SCHEMA_VERSION");
    // Multi-line, non-empty.
    expect(text.length).toBeGreaterThan(0);
    expect(text.split("\n").length).toBeGreaterThan(1);
  });

  it("reports no warnings when the warnings array is empty", () => {
    const text = renderThinText(makeResponse());
    expect(text.toLowerCase()).toContain("none");
  });
});

// ---------------------------------------------------------------------------
// Read-only tool annotations
// ---------------------------------------------------------------------------
describe("READ_ONLY_TOOL_ANNOTATIONS", () => {
  it("has the expected read-only annotation shape", () => {
    expect(READ_ONLY_TOOL_ANNOTATIONS).toEqual({
      readOnlyHint: true,
      idempotentHint: true,
      openWorldHint: false,
    });
  });
});
