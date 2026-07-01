/**
 * HuntReady MCP — zod schemas for the GetRegulationsResponse envelope.
 *
 * Each schema mirrors the corresponding TypeScript interface from
 * `./types/schema.ts` or `./types/response.ts`. Drift-guards (compile-time
 * `AssertEqual` assertions or `satisfies z.ZodType<Interface>` annotations)
 * ensure the two cannot diverge silently.
 *
 * `getRegulationsResponseSchema` (the exported envelope schema) is the artifact
 * E09/E10 will pass to the MCP SDK's `registerTool({ outputSchema })`, and
 * which the response-builder validates against via `.safeParse`.
 *
 * Idiom selection:
 *   - `AssertEqual` — used for flat schemas with no optional `?` fields.
 *   - `satisfies z.ZodType<Interface>` — used for schemas containing optional
 *     object properties (`ReservedPool.eligibility`, `AllocationPool.eligibility`
 *     + `tie_break?`, and `DrawSpec` which embeds both), where zod's optional
 *     inference produces `T | undefined` in ways that make the bidirectional
 *     `AssertEqual` brittle. (This is inherent to how zod models optionals —
 *     it is NOT specific to zod v4, so a version bump will not unlock
 *     `AssertEqual` for these schemas.)
 */

import { z } from "zod";

import type {
  WeaponType,
  Residency,
  GeometryRole,
  SourceCitation,
  VerbatimRule,
  ClosurePredicate,
  ReservedPool,
  PointSystem,
  ResidencyCap,
  ChoiceConfig,
  AllocationPool,
  DrawSpec,
} from "./types/schema.js";

import type {
  Coverage,
  Warning,
  SeasonsSection,
  ResolvedSeasonWindow,
  TagsSection,
  ResolvedTag,
  MethodsSection,
  ReportingSection,
  ResolvedReportingObligation,
  ContactsSection,
  Contact,
  AdditionalRulesSection,
  GetRegulationsResponse,
} from "./types/response.js";

// ---------------------------------------------------------------------------
// Drift-guard helper
// ---------------------------------------------------------------------------

/**
 * Compile-time bidirectional equality check.
 * `const _assertX: AssertEqual<z.infer<typeof xSchema>, X> = true;`
 * fails to compile if the two types are not identical.
 */
type AssertEqual<A, B> = [A] extends [B]
  ? [B] extends [A]
    ? true
    : never
  : never;

/**
 * Top-level key-set equality. `satisfies z.ZodType<Interface>` is ONE-
 * directional — it checks the schema's output is assignable to the interface
 * (catching a MISSING or wrong-typed key) but NOT the reverse, so an EXTRA key
 * in the schema produces an output that is still structurally assignable and
 * slips through. The optional-field schemas (`reservedPool`/`allocationPool`/
 * `drawSpec`) can't use the bidirectional `AssertEqual` (zod's `T | undefined`
 * optional inference makes it brittle), so pair their `satisfies` with this
 * key-set check to recover extra/missing top-level key detection.
 */
type SameKeys<A, B> = [keyof A] extends [keyof B]
  ? [keyof B] extends [keyof A]
    ? true
    : never
  : never;

// ---------------------------------------------------------------------------
// Enum schemas (shared)
// ---------------------------------------------------------------------------

export const weaponTypeSchema = z.enum([
  "any_legal_weapon",
  "archery",
  "rifle",
  "muzzleloader",
  "shotgun",
  "handgun",
  "crossbow",
  "traditional_handgun",
  "heritage_muzzleloader",
]);

const _assertWeaponType: AssertEqual<z.infer<typeof weaponTypeSchema>, WeaponType> = true;

export const residencySchema = z.enum(["resident", "nonresident", "both"]);

const _assertResidency: AssertEqual<z.infer<typeof residencySchema>, Residency> = true;

export const geometryRoleSchema = z.enum([
  "primary_unit",
  "portion",
  "restricted_area",
  "cwd_management_zone",
  "bear_management_unit",
  "block_management_area",
  "other_overlay",
  "no_hunt_zone",
]);

const _assertGeometryRole: AssertEqual<z.infer<typeof geometryRoleSchema>, GeometryRole> = true;

// ---------------------------------------------------------------------------
// Shared supporting schemas
// ---------------------------------------------------------------------------

export const sourceCitationSchema = z.object({
  id: z.string(),
  agency: z.string(),
  title: z.string(),
  url: z.string(),
  publication_date: z.string(),
  document_type: z.enum([
    "annual_regulations",
    "rule_change",
    "emergency_order",
    "correction",
    "gis_layer",
  ]),
  supersedes: z.string().nullable(),
  page_reference: z.string().nullable(),
});

const _assertSourceCitation: AssertEqual<
  z.infer<typeof sourceCitationSchema>,
  SourceCitation
> = true;

export const closurePredicateSchema = z.object({
  kind: z.enum(["quota_threshold", "sex_threshold", "emergency_order"]),
  threshold_percent: z.number().nullable(),
  threshold_sex: z.enum(["male", "female"]).nullable(),
  notification_channel: z.enum([
    "agency_website",
    "agency_phone",
    "email_alert",
    "other",
  ]),
  observation_channel: z
    .enum(["mandatory_reporting", "check_station", "harvest_survey"])
    .nullable(),
  verbatim_rule: z.string(),
});

const _assertClosurePredicate: AssertEqual<
  z.infer<typeof closurePredicateSchema>,
  ClosurePredicate
> = true;

/**
 * `ReservedPool.eligibility` contains optional fields — use `satisfies` to
 * avoid brittle `AssertEqual` interaction with zod v4 optional inference.
 */
export const reservedPoolSchema = z.object({
  share: z.number(),
  eligibility: z.object({
    kind: z.enum(["landowner", "youth", "hunter_education_recent", "other"]),
    min_acres: z.number().optional(),
    min_acres_contiguous: z.boolean().optional(),
    min_age: z.number().optional(),
    max_age: z.number().optional(),
    notes: z.string().optional(),
  }),
  applies_to_residency: residencySchema.nullable(),
  nonresident_subcap: z.number().nullable(),
  verbatim_rule: z.string(),
}) satisfies z.ZodType<ReservedPool>;

// `satisfies` above catches missing/mistyped keys; SameKeys catches an extra key.
const _kReservedPool: SameKeys<
  z.infer<typeof reservedPoolSchema>,
  ReservedPool
> = true;

export const pointSystemSchema = z.object({
  kind: z.enum(["preference_linear", "bonus_squared", "bonus_weighted"]),
  accrual: z.enum(["annual_on_apply", "annual_if_purchased"]),
  reset_on_success: z.boolean(),
  purchase_only_code: z.string().nullable(),
  inactive_forfeit_years: z.number().nullable(),
});

const _assertPointSystem: AssertEqual<
  z.infer<typeof pointSystemSchema>,
  PointSystem
> = true;

export const residencyCapSchema = z.object({
  nonresident_max_share: z.number(),
});

const _assertResidencyCap: AssertEqual<
  z.infer<typeof residencyCapSchema>,
  ResidencyCap
> = true;

export const choiceConfigSchema = z.object({
  count: z.number(),
  points_used_in_choices: z.array(z.number()),
});

const _assertChoiceConfig: AssertEqual<
  z.infer<typeof choiceConfigSchema>,
  ChoiceConfig
> = true;

/**
 * `AllocationPool.eligibility` contains optional fields and `tie_break` is
 * optional — use `satisfies` for the same reason as `reservedPoolSchema`.
 */
export const allocationPoolSchema = z.object({
  share: z.number(),
  selection: z.enum([
    "rank_ordered_by_points",
    "unweighted_random",
    "squared_weighted_random",
    "linear_weighted_random",
  ]),
  eligibility: z.object({
    min_points: z.number().optional(),
    residency: residencySchema.optional(),
    guided: z.boolean().optional(),
  }),
  tie_break: z.enum(["random", "rank_ordered"]).optional(),
}) satisfies z.ZodType<AllocationPool>;

const _kAllocationPool: SameKeys<
  z.infer<typeof allocationPoolSchema>,
  AllocationPool
> = true;

/**
 * `DrawSpec` embeds `AllocationPool[]` (optional fields) and `ChoiceConfig` —
 * use `satisfies` for the same reason as `reservedPoolSchema`.
 */
export const drawSpecSchema = z.object({
  state: z.string(),
  hunt_code: z.string(),
  year: z.number(),
  schema_version: z.number(),
  quota: z.number().nullable(),
  point_system: pointSystemSchema.nullable(),
  residency_cap: residencyCapSchema.nullable(),
  choices: choiceConfigSchema,
  pools: z.array(allocationPoolSchema),
  draw_phase: z.enum(["primary", "secondary", "leftover"]),
  successor_hunt_code_key: z
    .object({
      state: z.string(),
      hunt_code: z.string(),
      year: z.number(),
    })
    .nullable(),
  application_deadline: z.string(),
  parameters: z.record(z.string(), z.unknown()).nullable(),
  source: sourceCitationSchema,
}) satisfies z.ZodType<DrawSpec>;

const _kDrawSpec: SameKeys<z.infer<typeof drawSpecSchema>, DrawSpec> = true;

// ---------------------------------------------------------------------------
// Response schemas
// ---------------------------------------------------------------------------

export const confidenceSchema = z.enum(["high", "medium", "low"]);

export const coverageSchema = z.enum(["full", "partial", "none"]);

const _assertCoverage: AssertEqual<z.infer<typeof coverageSchema>, Coverage> = true;

export const verbatimRuleSchema = z.object({
  text: z.string(),
  page_reference: z.string().nullable(),
  confidence: confidenceSchema,
  source: sourceCitationSchema,
}).strict();

const _assertVerbatimRule: AssertEqual<z.infer<typeof verbatimRuleSchema>, VerbatimRule> = true;

export const additionalRulesSectionSchema = z.object({
  rules: z.array(verbatimRuleSchema),
  source: sourceCitationSchema,
}).strict();

const _assertAdditionalRulesSection: AssertEqual<
  z.infer<typeof additionalRulesSectionSchema>,
  AdditionalRulesSection
> = true;

export const warningSchema = z.object({
  code: z.enum([
    "STALE_SOURCE",
    "LOW_CONFIDENCE",
    "CONFLICTING_RULES",
    "PENDING_CHANGE",
    "BOUNDARY_AMBIGUOUS",
    "SUPERSEDED_BY_CORRECTION",
    "UNSUPPORTED_SCHEMA_VERSION",
  ]),
  section: z.enum([
    "seasons",
    "tags",
    "methods",
    "reporting",
    "contacts",
    "additional_rules",
    "overall",
  ]),
  message: z.string(),
}).strict();

const _assertWarning: AssertEqual<z.infer<typeof warningSchema>, Warning> = true;

export const resolvedSeasonWindowSchema = z.object({
  name: z.string(),
  opens: z.string(),
  closes: z.string(),
  weapon_type: weaponTypeSchema.nullable(),
  residency: residencySchema.nullable(),
  closure_predicate: closurePredicateSchema.nullable(),
  verbatim_rule: z.string(),
  page_reference: z.string().nullable(),
  confidence: confidenceSchema,
  source: sourceCitationSchema,
}).strict();

const _assertResolvedSeasonWindow: AssertEqual<
  z.infer<typeof resolvedSeasonWindowSchema>,
  ResolvedSeasonWindow
> = true;

export const seasonsSectionSchema = z.object({
  status: z.enum([
    "in_season",
    "out_of_season",
    "no_season_defined",
    "conditionally_closed",
    "unknown",
  ]),
  windows: z.array(resolvedSeasonWindowSchema),
  source: sourceCitationSchema,
}).strict();

const _assertSeasonsSection: AssertEqual<
  z.infer<typeof seasonsSectionSchema>,
  SeasonsSection
> = true;

export const resolvedTagSchema = z.object({
  license_code: z.string(),
  name: z.string(),
  kind: z.enum(["general", "limited_draw", "over_the_counter", "statewide"]),
  species: z.string(),
  weapon_types: z.array(weaponTypeSchema),
  residency: residencySchema,
  quota: z.number().nullable(),
  application_deadline: z.string().nullable(),
  draw_spec: drawSpecSchema.nullable(),
  reserved_pools: z.array(reservedPoolSchema),
  purchase_url: z.string(),
  verbatim_rule: z.string(),
  confidence: confidenceSchema,
  source: sourceCitationSchema,
}).strict();

const _assertResolvedTag: AssertEqual<
  z.infer<typeof resolvedTagSchema>,
  ResolvedTag
> = true;

export const tagsSectionSchema = z.object({
  tags: z.array(resolvedTagSchema),
  source: sourceCitationSchema,
}).strict();

const _assertTagsSection: AssertEqual<
  z.infer<typeof tagsSectionSchema>,
  TagsSection
> = true;

export const methodsSectionSchema = z.object({
  allowed: z.array(weaponTypeSchema),
  prohibited: z.array(weaponTypeSchema),
  verbatim_rule: z.string(),
  confidence: confidenceSchema,
  source: sourceCitationSchema,
}).strict();

const _assertMethodsSection: AssertEqual<
  z.infer<typeof methodsSectionSchema>,
  MethodsSection
> = true;

export const resolvedReportingObligationSchema = z.object({
  kind: z.enum([
    "harvest_report",
    "mandatory_check",
    "tooth_submission",
    "hide_skull_presentation",
    "cwd_sample",
    "other",
  ]),
  deadline: z.string(),
  deadline_hours: z.number().nullable(),
  submission_method: z.enum([
    "online",
    "phone",
    "in_person_check_station",
    "mail",
    "agency_office",
  ]),
  submission_url: z.string().nullable(),
  submission_phone: z.string().nullable(),
  applies_to_regions: z.array(z.string()).nullable(),
  what_to_present: z.array(z.string()).nullable(),
  verbatim_rule: z.string(),
  confidence: confidenceSchema,
  source: sourceCitationSchema,
}).strict();

const _assertResolvedReportingObligation: AssertEqual<
  z.infer<typeof resolvedReportingObligationSchema>,
  ResolvedReportingObligation
> = true;

export const reportingSectionSchema = z.object({
  obligations: z.array(resolvedReportingObligationSchema),
  source: sourceCitationSchema,
}).strict();

const _assertReportingSection: AssertEqual<
  z.infer<typeof reportingSectionSchema>,
  ReportingSection
> = true;

export const contactSchema = z.object({
  role: z.string(),
  name: z.string().nullable(),
  phone: z.string().nullable(),
  email: z.string().nullable(),
  url: z.string().nullable(),
  source: sourceCitationSchema,
}).strict();

const _assertContact: AssertEqual<z.infer<typeof contactSchema>, Contact> = true;

export const contactsSectionSchema = z.object({
  regional_warden: contactSchema.nullable(),
  regional_office: contactSchema.nullable(),
  rules_hotline: contactSchema.nullable(),
}).strict();

const _assertContactsSection: AssertEqual<
  z.infer<typeof contactsSectionSchema>,
  ContactsSection
> = true;

// ---------------------------------------------------------------------------
// Envelope schema (exported — consumed by MCP SDK registerTool + response-builder)
// ---------------------------------------------------------------------------

// `.strict()` on every serving-composition object so envelope drift — a
// server-composed `overview`/`headline` or any unknown key (ADR-013 forbids
// these) — FAILS validation in buildStructuredToolResult instead of silently
// passing through into `structuredContent`. `.strict()` is a runtime-parse
// constraint only; it does NOT change `z.infer`, so the AssertEqual drift-guard
// below still holds and response.ts stays an exact mirror of architecture.md.
// Embedded ENTITY schemas (sourceCitation/drawSpec/...) are intentionally left
// non-strict — they are passthrough data, not serving composition.
export const getRegulationsResponseSchema = z
  .object({
    query: z
      .object({
        lat: z.number(),
        lng: z.number(),
        species: z.string(),
        date: z.string(),
      })
      .strict(),

    resolved: z
      .object({
        jurisdiction: z
          .object({
            state: z.string(),
            primary_unit: z.string().nullable(),
            overlays: z.array(
              z
                .object({
                  role: geometryRoleSchema,
                  name: z.string(),
                })
                .strict()
            ),
          })
          .strict()
          .nullable(),
        species_canonical: z.string().nullable(),
        license_year: z.number().nullable(),
      })
      .strict(),

    seasons: seasonsSectionSchema.nullable(),
    tags: tagsSectionSchema.nullable(),
    methods: methodsSectionSchema.nullable(),
    reporting: reportingSectionSchema.nullable(),
    contacts: contactsSectionSchema.nullable(),
    additional_rules: additionalRulesSectionSchema.nullable(),

    sources: z.array(sourceCitationSchema),

    meta: z
      .object({
        schema_version: z.literal(2),
        generated_at: z.string(),
        data_freshness: z
          .object({
            most_recent_source_date: z.string(),
            stalest_source_date: z.string(),
            is_stale: z.boolean(),
          })
          .strict()
          .nullable(),
        coverage: z
          .object({
            jurisdiction: coverageSchema,
            species: coverageSchema,
            overall: coverageSchema,
          })
          .strict(),
        warnings: z.array(warningSchema),
      })
      .strict(),
  })
  .strict()
  .superRefine((val, ctx) => {
    // Decision-1 invariant (architecture.md §"Response shape"):
    // meta.data_freshness must be null iff sources is empty.
    const sourcesEmpty = val.sources.length === 0;
    const freshnessNull = val.meta.data_freshness === null;
    if (sourcesEmpty !== freshnessNull) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "data_freshness must be null iff sources is empty: " +
          (sourcesEmpty
            ? "sources is empty but data_freshness is non-null"
            : "sources is non-empty but data_freshness is null"),
      });
    }
  });

const _assertGetRegulationsResponse: AssertEqual<
  z.infer<typeof getRegulationsResponseSchema>,
  GetRegulationsResponse
> = true;
