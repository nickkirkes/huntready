# Schema v2 Proposal

**Status:** Decisions locked after review 2026-04-19. Ready for propagation into `architecture.md` and ADRs.
**Date:** 2026-04-19
**Supersedes:** The `RegulationRecord` interface currently documented in `architecture.md`.
**Triggered by:** Resolutions to open questions Q1 (Montana source structure), Q2 (MCP tool response shape), Q3 (Colorado draw system modeling), Q4 (Colorado GMU boundaries).

---

## Why this proposal exists

The schema currently documented in `architecture.md` was drafted before any real regulation data had been examined. It served as a thinking anchor — "records have a source, a jurisdiction, an applies_to, some rules, and optional tag info" — and it was right in spirit. It is not right in shape.

Four pieces of research completed in April 2026 — Montana source structure, Montana GIS endpoints, Colorado GMU boundaries, Colorado draw system modeling — surfaced nine structural patterns that the v1 schema does not represent cleanly. Each of them is evidenced by a specific passage in a published regulation document. None of them are invented or anticipated.

At the same time, the MCP tool response shape research surfaced the right consumer-facing shape for this data — a structured envelope with always-present, null-bearing sections and explicit coverage signals. The response shape and the storage schema are not the same thing, but they have to fit each other: the storage schema has to contain enough structure that the response builder can assemble the envelope without rederiving anything.

This proposal revises the storage schema and the response shape together. It treats them as a single design and walks the reasoning end-to-end, because splitting them produces decisions that don't compose.

The proposal is written so that the worst thing you can do with it is reject it. If any of the design choices below are wrong, say so — it is cheaper to argue over a Markdown document than to argue over Postgres migrations and a deployed MCP server.

---

## What stayed the same

Four commitments from v1 survive unchanged:

- **Authority is preserved.** Every regulation still carries a source URL, publication date, and verbatim rule text. Every response still surfaces the source prominently. Every record without a source still fails validation.
- **Schema is versioned.** The `schema_version` field remains on every record, and v2 is explicitly a forward version from v1. Records written under v1 are no longer produced; any future v1 records in test fixtures get migrated or discarded.
- **Geometry lives in PostGIS.** Boundaries continue to be stored as `geography(..., 4326)`. The concrete geometry type changes (see below), but the storage choice does not.
- **Postgres remains the source of truth.** The TypeScript interfaces below are the human-readable description of the schema; Postgres DDL is the enforcement point.

## What changed, in summary

Six structural changes, each motivated by a specific research finding:

1. **Geometry type.** Unit and portion polygons become `MultiPolygon`, not `Polygon`. *Motivated by: Q4 (Colorado GMU, multipart units) and Q1 (Montana HDs with cross-state fragments).*
2. **Entity decomposition.** A single `RegulationRecord` is decomposed into six entities that compose into a regulation view. *Motivated by: Q1 (pressure points 1, 2, 3, 4, 6, 7, 8, 9) and Q3 (draw_spec as a sibling entity).*
3. **Overlay geometries.** Jurisdictions are modeled as a many-to-many of records to geometries, not one geometry per record. *Motivated by: Q1 (BMUs, HDs, and CWD zones as three separate layers that cross-cut).*
4. **Composite primary keys.** `draw_spec` and `regulation_record` use year-scoped composite keys. *Motivated by: Q3 (annual draw-spec updates) and the need to preserve history across regulation cycles.*
5. **Response shape as a distinct artifact.** The `GetRegulationsResponse` is a separate TypeScript interface representing the assembled view, not a stored row. It composes sections from the underlying entities and adds coverage signals. *Motivated by: Q2 (Shape C envelope pattern).*
6. **A `corrections` publication type.** The `document_type` enum gains a `correction` value, and corrections carry a `supersedes` pointer. *Motivated by: Q1 (Montana Black Bear correction PDF, 2026-03-18).*

## What did NOT change

Some things the research could have pushed us toward but we deliberately did not adopt:

- **A formula DSL for draw mechanics.** Q3 flagged that if states invent unusual point math (cubed, age-weighted, etc.), a formula DSL might be needed. We use an enum (`rank_ordered_by_points`, `unweighted_random`, `squared_weighted_random`, `linear_weighted_random`) and will revisit only if more than one state requires a formula not in the enum.
- **A dedicated `closures` top-level entity.** Q1 surfaced closure predicates as a first-class concern. We considered a separate entity and decided against it: closure predicates are *modifiers of a season window*, not standalone regulatory objects. They live inline on `season_definition`.
- **Passage-level citation IDs.** Q2 flagged this as open question #3 and the analyst recommended document-level IDs for V1. We agree.
- **Real-time data refresh hooks.** Montana explicitly publishes Block Management Areas that change mid-season. We document this as a known V1 limitation and defer the refresh pipeline to V2.

---

## The entity model

Six entities. Each is stored as its own Postgres table. TypeScript interfaces mirror the table shape.

### 1. `regulation_record`

The central entity. One row per (state, hunting district, species grouping, license year) combination. It is the thing that *gets ingested*; everything else composes around it.

```typescript
interface RegulationRecord {
  // Composite primary key: (state, jurisdiction_code, species_group, license_year)
  state: string;                    // ISO 3166-2, e.g. "US-MT"
  jurisdiction_code: string;        // e.g. "MT-HD-262" or "CO-GMU-024"
  species_group: string;            // "deer" | "elk" | "antelope" | "bear" | "whitetail"
  license_year: number;             // e.g. 2026 (the cycle year; biennial booklets emit two rows)

  schema_version: number;           // 2

  // Provenance
  source: SourceCitation;           // see below
  ingested_at: string;              // ISO timestamp
  confidence: "high" | "medium" | "low";

  // Composition — these are references, not embedded values
  season_definition_ids: string[];  // fk to season_definition.id
  license_tag_ids: string[];        // fk to license_tag.id
  reporting_obligation_ids: string[]; // fk to reporting_obligation.id
  jurisdiction_binding_ids: string[]; // fk to jurisdiction_binding.id (overlay geometries)

  // Free-form verbatim text not structured by a child entity
  additional_rules: VerbatimRule[]; // inline; catch-all for prose that doesn't fit a specific child
}
```

The decomposition matters because Montana's per-HD regulation row routinely contains:
- Multiple named seasons (Early / Archery Only / General / Heritage Muzzleloader / Late) — these are `season_definition`s.
- A General license and multiple B licenses, each with independent draw mechanics — these are `license_tag`s, each pointing at a `draw_spec`.
- Region-specific reporting rules (black bear Region 1 vs. Regions 2-7) — these are `reporting_obligation`s.
- Overlay memberships (the HD is also partly inside a CWD Management Zone, partly in a Bear Management Unit) — these are `jurisdiction_binding`s.

A single embedded `RegulationRecord` would have to carry arrays of each. That is legal, but it loses the ability for two `RegulationRecord`s to share a `season_definition` or a `reporting_obligation` — which is the common case (most B licenses in Montana share season windows with their parent A license, for example). Decomposition lets us normalize; embedding would force us to duplicate.

### 2. `season_definition`

A named date range with weapon, residency, and closure metadata.

```typescript
interface SeasonDefinition {
  id: string;                       // e.g. "MT-HD-262-deer-general-2026"
  name: string;                     // "General" | "Archery Only" | "Early Season" | ...
  opens: string;                    // ISO date
  closes: string;                   // ISO date
  weapon_type: WeaponType | null;   // null = all legal methods
  residency: Residency | null;      // null = both
  closure_predicate: ClosurePredicate | null;  // inline; conditional close rules
  verbatim_rule: string;            // direct quote from source
  page_reference: string | null;
  source: SourceCitation;
}

type WeaponType =
  | "any_legal_weapon"
  | "archery"
  | "rifle"
  | "muzzleloader"
  | "shotgun"
  | "handgun"
  | "crossbow"
  | "traditional_handgun"
  | "heritage_muzzleloader";

type Residency = "resident" | "nonresident" | "both";

interface ClosurePredicate {
  kind: "quota_threshold" | "sex_threshold" | "emergency_order";
  // For quota_threshold: "season closes when cumulative harvest reaches N percent of quota"
  threshold_percent?: number;
  threshold_sex?: "male" | "female";
  // For all kinds: how the closure is announced
  notification_channel: "agency_website" | "agency_phone" | "email_alert" | "other";
  // Observation channel — how the data that triggers the predicate is collected
  observation_channel?: "mandatory_reporting" | "check_station" | "harvest_survey";
  // Human-readable verbatim text of the closure rule
  verbatim_rule: string;
}
```

Closure predicates are the most novel piece here. Montana's black bear booklet is explicit: "In BMUs 411, 420, 440, 450, 510, 520, 530, 600, and 700 when the quota is reached or approached... the black bear season in that district will close." The season's printed dates are conditional. The schema now encodes that conditionality.

For V1, closure predicates are *informational* — the MCP server surfaces them to the hunter ("this season can close early if quota is reached"), but the server does not actively check whether the predicate has been triggered. Active checking requires an ingestion pathway for in-season harvest reporting, which is V2.

### 3. `license_tag`

The permit instrument. An HD like Montana's HD 262 will typically have one General (A) license and one or more B (antlerless) licenses; each is its own row here.

```typescript
interface LicenseTag {
  id: string;                       // e.g. "MT-HD-262-deer-B-2026"
  license_code: string;             // e.g. "262-00" (Montana's B license code) or "E-E-024-O1-R" (CPW)
  name: string;                     // "Deer B License" | "General Elk License"
  kind: "general" | "limited_draw" | "over_the_counter" | "statewide";
  species: string;                  // canonical species string
  weapon_types: WeaponType[];       // restrictions on method
  residency: Residency;
  quota: number | null;             // null = unlimited or unpublished
  quota_range: [number, number] | null; // e.g. [25, 300] from Montana tables
  purchase_url: string;             // direct link to state agency flow
  draw_spec_id: string | null;      // fk to draw_spec; null for OTC/general
  reserved_pools: ReservedPool[];   // landowner preference, youth set-asides, etc.
  verbatim_rule: string;
  source: SourceCitation;
}

interface ReservedPool {
  // Example: "Up to 15% of final quotas set aside for deer permit landowners with ≥160 acres"
  share: number;                    // 0.0–1.0
  eligibility: {
    kind: "landowner" | "youth" | "hunter_education_recent" | "other";
    min_acres?: number;
    min_acres_contiguous?: boolean; // Montana elk landowner preference requires contiguous land
    min_age?: number;
    max_age?: number;
    notes?: string;
  };
  applies_to_residency?: Residency;
  nonresident_subcap?: number;      // e.g. 0.10 for Montana's 10% NR sub-cap
  verbatim_rule: string;
}
```

Note that `reserved_pools` lives here rather than in `draw_spec`. The reasoning: landowner preference is a property of the *tag* (who can apply for it, under what conditions), not of the *draw mechanics* (how applicants are selected). A B license might have both a landowner set-aside AND an 80/20 hybrid draw; these are orthogonal.

### 4. `draw_spec`

The draw mechanics. Imported largely as-is from the Q3 proposal, with composite primary key applied.

```typescript
interface DrawSpec {
  // Composite primary key: (state, hunt_code, year)
  state: string;                    // ISO 3166-2
  hunt_code: string;                // e.g. "E-E-024-O1-R"
  year: number;                     // cycle year — distinct rows for 2026 vs 2027

  schema_version: number;           // 2

  quota: number | null;
  point_system: PointSystem | null;
  residency_cap: ResidencyCap | null;
  choices: ChoiceConfig;
  pools: AllocationPool[];          // shares sum to 1.0
  draw_phase: "primary" | "secondary" | "leftover";
  successor_hunt_code: string | null;  // references next-phase hunt code
  application_deadline: string;     // ISO date — moved here from license_tag in v1
  parameters: Record<string, unknown> | null;  // state-adapter escape hatch; SHARED CODE NEVER READS THIS
  source: SourceCitation;
}

interface PointSystem {
  kind: "preference_linear" | "bonus_squared" | "bonus_weighted";
  accrual: "annual_on_apply" | "annual_if_purchased";
  reset_on_success: boolean;
  purchase_only_code: string | null;
  inactive_forfeit_years: number | null;
}

interface ResidencyCap {
  nonresident_max_share: number;    // 0.0–1.0
}

interface ChoiceConfig {
  count: number;
  points_used_in_choices: number[]; // e.g. [1] for CO; [] for NM
}

interface AllocationPool {
  share: number;
  selection:
    | "rank_ordered_by_points"
    | "unweighted_random"
    | "squared_weighted_random"
    | "linear_weighted_random";
  eligibility: {
    min_points?: number;
    residency?: Residency;
    guided?: boolean;               // NM outfitter pool
  };
  tie_break?: "random" | "rank_ordered";
}
```

The `parameters` field is critical and its contract must be loud: **shared code (the MCP server, the response builder, the web client) NEVER reads `parameters`**. It is state-adapter metadata — Wyoming tier pricing, Utah youth allocation categories, CPW preference-point exponential weighting for moose — that the ingestion adapter writes and the state-specific display code may consume, but that the generic tools must ignore. This boundary is what keeps the hard constraint intact.

### 5. `reporting_obligation`

Post-harvest and in-season reporting duties. Decomposed because (per Q1) a single species can have multiple region-specific reporting obligations.

```typescript
interface ReportingObligation {
  id: string;                       // e.g. "MT-black-bear-region-1-teeth-2026"
  kind: "harvest_report" | "mandatory_check" | "tooth_submission" | "hide_skull_presentation" | "cwd_sample" | "other";
  deadline: string;                 // human-readable, e.g. "within 48 hours of harvest"
  deadline_hours: number | null;    // structured form when parseable
  submission_method: "online" | "phone" | "in_person_check_station" | "mail" | "agency_office";
  submission_url: string | null;
  submission_phone: string | null;
  // Regional applicability — critical for Montana black bear where Region 1 and Regions 2-7 differ
  applies_to_regions: string[] | null;  // null = statewide; e.g. ["MT-Region-1"]
  what_to_present: string[] | null; // e.g. ["two_premolar_teeth"] or ["full_hide", "skull"]
  verbatim_rule: string;
  source: SourceCitation;
}
```

### 6. `jurisdiction_binding`

The overlay system. Each binding connects a `regulation_record` to a geometry, typed by the role that geometry plays.

```typescript
interface JurisdictionBinding {
  id: string;                       // e.g. "MT-HD-100-base-2026"
  regulation_record_id: string;     // fk to regulation_record (composite key serialized)
  geometry_id: string;              // fk to geometry.id
  role: GeometryRole;
  verbatim_rule: string | null;     // optional: the prose that ties this geometry to the regulation
  source: SourceCitation;
}

type GeometryRole =
  | "primary_unit"                  // the HD/GMU itself
  | "portion"                       // a sub-polygon with different rules (Mule Deer Portion, Elk Portion)
  | "restricted_area"               // a closure or restriction polygon
  | "cwd_management_zone"           // overlay zone for CWD testing rules
  | "bear_management_unit"          // overlay where BMU boundaries differ from HDs
  | "block_management_area"         // private-land access overlay
  | "other_overlay";
```

And the geometries themselves are in their own table:

```typescript
interface Geometry {
  id: string;                       // stable ID, e.g. "MT-HD-100-geom"
  name: string;
  kind: "hunting_district" | "gmu" | "portion" | "bmu" | "cwd_zone" | "restricted_area" | "bma" | "other";
  geom: "MultiPolygon";             // PostGIS geography(MultiPolygon, 4326)
  state: string;
  license_year: number | null;      // null for year-invariant geometries (e.g., CWD zones)
  source: SourceCitation;
}
```

This factoring matters because in Montana:
- A Deer/Elk HD polygon (layer 11 of the ArcGIS service) and a Black Bear BMU polygon (layer 10) are *different geometries*. A hunt in that HD for deer uses one geometry; for bear uses another.
- CWD Management Zones are *overlay zones* that cross-cut HDs. The "Libby CWD Management Zone" appears in HDs 100 and 103 but is itself neither.
- Elk Portions and Mule Deer Portions are sub-polygons inside HDs.

The v1 schema assumed `jurisdiction.unit` + optional `unit_boundary`. That assumption collapsed three distinct concepts into one field. `jurisdiction_binding` is the fix.

### Shared types

```typescript
interface SourceCitation {
  id: string;                       // stable ID for deduplication
  agency: string;                   // e.g. "Montana FWP"
  title: string;                    // e.g. "2026 Deer Elk Antelope Hunting Regulations"
  url: string;
  publication_date: string;         // ISO date
  document_type: "annual_regulations" | "rule_change" | "emergency_order" | "correction";
  supersedes: string | null;        // for corrections: the SourceCitation.id being amended
  page_reference: string | null;
}

interface VerbatimRule {
  text: string;                     // direct quote from source
  page_reference: string | null;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}
```

The `correction` value on `document_type` is new in v2. When a correction supersedes a base publication, records descended from the base should either be re-ingested from the corrected text or carry an inline `warnings` signal that they've been amended. The `supersedes` pointer lets the ingestion pipeline track what's been amended without requiring a full re-ingest on every correction.

---

## Postgres DDL (abbreviated)

Not every CREATE TABLE, but the shape. Full DDL lives in `supabase/migrations/` when we commit.

```sql
-- Primary regulation entity, composite PK
create table regulation_record (
  state text not null,
  jurisdiction_code text not null,
  species_group text not null,
  license_year integer not null,
  schema_version integer not null default 2,
  source jsonb not null,
  ingested_at timestamptz not null,
  confidence text not null check (confidence in ('high','medium','low')),
  additional_rules jsonb not null default '[]'::jsonb,
  primary key (state, jurisdiction_code, species_group, license_year)
);

create table season_definition (
  id text primary key,
  name text not null,
  opens date not null,
  closes date not null,
  weapon_type text,
  residency text check (residency in ('resident','nonresident','both')),
  closure_predicate jsonb,
  verbatim_rule text not null,
  page_reference text,
  source jsonb not null
);

create table license_tag (
  id text primary key,
  license_code text not null,
  name text not null,
  kind text not null check (kind in ('general','limited_draw','over_the_counter','statewide')),
  species text not null,
  weapon_types text[] not null,
  residency text not null check (residency in ('resident','nonresident','both')),
  quota integer,
  quota_range int4range,
  purchase_url text not null,
  draw_spec_key jsonb,  -- {state, hunt_code, year}; fk enforced in code since composite
  reserved_pools jsonb not null default '[]'::jsonb,
  verbatim_rule text not null,
  source jsonb not null
);

create table draw_spec (
  state text not null,
  hunt_code text not null,
  year integer not null,
  schema_version integer not null default 2,
  quota integer,
  point_system jsonb,
  residency_cap jsonb,
  choices jsonb not null,
  pools jsonb not null,
  draw_phase text not null check (draw_phase in ('primary','secondary','leftover')),
  successor_hunt_code_key jsonb,  -- {state, hunt_code, year}; soft fk
  application_deadline date not null,
  parameters jsonb,
  source jsonb not null,
  primary key (state, hunt_code, year)
);

create table reporting_obligation (
  id text primary key,
  kind text not null,
  deadline text not null,
  deadline_hours integer,
  submission_method text not null,
  submission_url text,
  submission_phone text,
  applies_to_regions text[],
  what_to_present text[],
  verbatim_rule text not null,
  source jsonb not null
);

create table geometry (
  id text primary key,
  name text not null,
  kind text not null,
  geom geography(MultiPolygon, 4326) not null,
  state text not null,
  license_year integer,
  source jsonb not null
);

create index geometry_geom_gix on geometry using gist (geom);
create index geometry_state_kind_idx on geometry (state, kind);

create table jurisdiction_binding (
  id text primary key,
  state text not null,
  jurisdiction_code text not null,
  species_group text not null,
  license_year integer not null,
  geometry_id text not null references geometry(id),
  role text not null,
  verbatim_rule text,
  source jsonb not null,
  foreign key (state, jurisdiction_code, species_group, license_year)
    references regulation_record (state, jurisdiction_code, species_group, license_year)
);

-- Link tables: regulation_record to its composed entities
create table regulation_season (
  state text not null,
  jurisdiction_code text not null,
  species_group text not null,
  license_year integer not null,
  season_definition_id text not null references season_definition(id),
  primary key (state, jurisdiction_code, species_group, license_year, season_definition_id),
  foreign key (state, jurisdiction_code, species_group, license_year)
    references regulation_record (state, jurisdiction_code, species_group, license_year)
);

create table regulation_license (...);       -- same shape, points at license_tag
create table regulation_reporting (...);     -- same shape, points at reporting_obligation
```

Notes on the DDL:

- **`source` is stored as `jsonb`.** The `SourceCitation` shape is contractually defined, but JSON avoids an extra join on every query. Indexes on `(source->>'document_type')` and `(source->>'publication_date')` are cheap.
- **Composite FKs are honored where Postgres supports them** (jurisdiction_binding → regulation_record) and enforced in code where not (draw_spec link from license_tag uses `jsonb` because Postgres cannot FK-link to a composite across a `jsonb` column; this is a V1 tradeoff).
- **`draw_spec.successor_hunt_code_key` is a soft FK.** A primary hunt code's successor (the secondary-draw version) may not exist yet at primary-draw ingest time. Hard-linking would fail ingestion; soft-linking tolerates the temporal gap.

---

## The response shape: `GetRegulationsResponse`

Written against the v2 entity model, retaining Shape C (structured envelope, always-present null-bearing sections, explicit coverage signals), with the three refinements I flagged when reviewing the Q2 proposal: `overview` dropped, `tags` pluralized, `reporting` pluralized, `closures` inline on `SeasonWindow`.

```typescript
interface GetRegulationsResponse {
  query: {
    lat: number;
    lng: number;
    species: string;
    date: string;                  // ISO date
  };

  resolved: {
    jurisdiction: {
      state: string;
      primary_unit: string | null;
      overlays: { role: GeometryRole; name: string }[]; // overlay memberships
    } | null;
    species_canonical: string | null;
    license_year: number | null;
  };

  // Always-present, null-bearing sections
  seasons:   SeasonsSection   | null;
  tags:      TagsSection      | null;
  methods:   MethodsSection   | null;
  reporting: ReportingSection | null;
  contacts:  ContactsSection  | null;

  sources: SourceCitation[];

  meta: {
    schema_version: 2;
    generated_at: string;
    data_freshness: {
      most_recent_source_date: string;
      stalest_source_date: string;
      is_stale: boolean;           // any source > 180 days
    };
    coverage: {
      jurisdiction: Coverage;
      species: Coverage;
      overall: Coverage;
    };
    warnings: Warning[];
  };
}

type Coverage = "full" | "partial" | "none";

interface SeasonsSection {
  status: "in_season" | "out_of_season" | "no_season_defined" | "conditionally_closed" | "unknown";
  windows: ResolvedSeasonWindow[];
  source: SourceCitation;
}

interface ResolvedSeasonWindow {
  name: string;                    // e.g. "General", "Archery Only"
  opens: string;
  closes: string;
  weapon_type: WeaponType | null;
  residency: Residency | null;
  closure_predicate: ClosurePredicate | null; // surfaces any quota/sex conditional close rules
  verbatim_rule: string;
  page_reference: string | null;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

interface TagsSection {
  // Plural — an HD can have one General + several B licenses
  tags: ResolvedTag[];
  source: SourceCitation;          // most-specific citation for the tag requirement claim
}

interface ResolvedTag {
  license_code: string;
  name: string;
  kind: "general" | "limited_draw" | "over_the_counter" | "statewide";
  species: string;
  weapon_types: WeaponType[];
  residency: Residency;
  quota: number | null;
  application_deadline: string | null;  // pulled from draw_spec if applicable
  draw_spec: DrawSpec | null;            // embedded for context-assembly efficiency
  reserved_pools: ReservedPool[];
  purchase_url: string;
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

interface MethodsSection {
  allowed: WeaponType[];
  prohibited: WeaponType[];
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

interface ReportingSection {
  // Plural — Montana black bear Region 1 vs Regions 2-7 are distinct obligations
  obligations: ResolvedReportingObligation[];
  source: SourceCitation;
}

interface ResolvedReportingObligation {
  kind: "harvest_report" | "mandatory_check" | "tooth_submission" | "hide_skull_presentation" | "cwd_sample" | "other";
  deadline: string;
  deadline_hours: number | null;
  submission_method: "online" | "phone" | "in_person_check_station" | "mail" | "agency_office";
  submission_url: string | null;
  submission_phone: string | null;
  applies_to_regions: string[] | null;
  what_to_present: string[] | null;
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

interface ContactsSection {
  regional_warden: Contact | null;
  regional_office: Contact | null;
  rules_hotline: Contact | null;
}

interface Warning {
  code:
    | "STALE_SOURCE"
    | "LOW_CONFIDENCE"
    | "CONFLICTING_RULES"
    | "PENDING_CHANGE"
    | "BOUNDARY_AMBIGUOUS"
    | "SUPERSEDED_BY_CORRECTION";  // added for the Montana black bear correction case
  section: "seasons" | "tags" | "methods" | "reporting" | "contacts" | "overall";
  message: string;
}
```

Three deliberate divergences from the Q2 proposal:

- **No `overview` field.** The Q2 analyst flagged this as open question #1, and I agree with the skeptical lean. A server-composed headline that must stay consistent with the structured sections is a correctness invariant we don't need at V1 scale. Agents and the web UI can compose their own headlines from the sections. If the Next.js team later finds they want a server-composed hero, it's additive.
- **`tags` is plural.** Montana's A/B license pattern requires it. New `ResolvedTag[]` array.
- **`reporting` is plural.** Montana black bear's regional variation requires it.
- **Closure predicates are inline on `ResolvedSeasonWindow`.** No separate `closures` section in the response.

And the `SUPERSEDED_BY_CORRECTION` warning is new, directly from the Montana correction PDF finding.

---

## Worked examples

Three canonical scenarios, showing how the schema and response shape compose.

### Example 1: Montana elk, HD 262, October 15, 2026 (rifle/archery)

**User query:** `get_regulations(lat=45.92, lng=-113.67, species="elk", date="2026-10-15")`.

**What's in storage:**

```json
// regulation_record
{
  "state": "US-MT",
  "jurisdiction_code": "MT-HD-262",
  "species_group": "elk",
  "license_year": 2026,
  "schema_version": 2,
  "source": { "id": "mt-fwp-dea-2026", "agency": "Montana FWP", ... },
  "season_definition_ids": ["MT-HD-262-elk-archery-2026", "MT-HD-262-elk-general-2026", "MT-HD-262-elk-late-2026"],
  "license_tag_ids": ["MT-HD-262-elk-general-2026", "MT-HD-262-elk-B-2026"],
  "reporting_obligation_ids": [],
  "jurisdiction_binding_ids": ["MT-HD-262-primary-2026"]
}
```

**What the response builder produces:**

```json
{
  "query": { "lat": 45.92, "lng": -113.67, "species": "elk", "date": "2026-10-15" },
  "resolved": {
    "jurisdiction": {
      "state": "US-MT",
      "primary_unit": "HD-262",
      "overlays": []
    },
    "species_canonical": "cervus_canadensis",
    "license_year": 2026
  },
  "seasons": {
    "status": "in_season",
    "windows": [
      {
        "name": "Archery Only",
        "opens": "2026-09-05",
        "closes": "2026-10-18",
        "weapon_type": "archery",
        "residency": "both",
        "closure_predicate": null,
        "verbatim_rule": "...",
        "confidence": "high",
        "source": { ... }
      },
      {
        "name": "General",
        "opens": "2026-10-19",
        "closes": "2026-11-29",
        "weapon_type": "any_legal_weapon",
        "residency": "both",
        "closure_predicate": null,
        "verbatim_rule": "...",
        "confidence": "high",
        "source": { ... }
      }
    ],
    "source": { ... }
  },
  "tags": {
    "tags": [
      { "license_code": "general-elk", "kind": "general", ... },
      { "license_code": "262-00", "kind": "limited_draw", "draw_spec": { ... }, ... }
    ],
    "source": { ... }
  },
  "methods": { "allowed": ["archery", "rifle", "muzzleloader"], "prohibited": [], ... },
  "reporting": null,
  "contacts": { "regional_warden": { ... }, ... },
  "sources": [ ... ],
  "meta": {
    "schema_version": 2,
    "coverage": { "jurisdiction": "full", "species": "full", "overall": "full" },
    "warnings": []
  }
}
```

Key observations:
- Multiple named seasons per response, each with independent weapon type and date range.
- Two tags returned — the General license and the 262-00 B license — each with its own draw_spec (null for General, populated for B).
- No reporting obligations for elk in Montana, so `reporting: null`. The UI will render "No reporting required" or similar.

### Example 2: Montana black bear, BMU 411, May 20, 2026 (quota closure predicate)

Shows the closure predicate in action.

**What the response builder produces (abbreviated):**

```json
{
  "resolved": {
    "jurisdiction": {
      "state": "US-MT",
      "primary_unit": "BMU-411",
      "overlays": []
    },
    "species_canonical": "ursus_americanus"
  },
  "seasons": {
    "status": "conditionally_closed",
    "windows": [
      {
        "name": "Spring",
        "opens": "2026-04-15",
        "closes": "2026-05-31",
        "weapon_type": null,
        "closure_predicate": {
          "kind": "quota_threshold",
          "threshold_percent": 100,
          "notification_channel": "agency_website",
          "observation_channel": "mandatory_reporting",
          "verbatim_rule": "In BMUs 411, 420, 440, 450, 510, 520, 530, 600, and 700 when the quota is reached or approached... the black bear season in that district will close."
        },
        "verbatim_rule": "Spring season: April 15 - May 31, subject to closure...",
        "confidence": "high",
        "source": { ... }
      }
    ],
    "source": { ... }
  },
  "reporting": {
    "obligations": [
      {
        "kind": "harvest_report",
        "deadline": "within 48 hours of harvest",
        "deadline_hours": 48,
        "submission_method": "online",
        "applies_to_regions": null,
        "what_to_present": null,
        "verbatim_rule": "Hunters must report harvest within 48 hours..."
      },
      {
        "kind": "tooth_submission",
        "deadline": "within 10 days of harvest",
        "deadline_hours": 240,
        "submission_method": "mail",
        "applies_to_regions": ["MT-Region-1"],
        "what_to_present": ["two_premolar_teeth"],
        "verbatim_rule": "Region 1 hunters must submit two premolar teeth..."
      },
      {
        "kind": "hide_skull_presentation",
        "deadline": "within 10 days of harvest",
        "submission_method": "in_person_check_station",
        "applies_to_regions": ["MT-Region-2", "MT-Region-3", "MT-Region-4", "MT-Region-5", "MT-Region-6", "MT-Region-7"],
        "what_to_present": ["full_hide", "skull"],
        "verbatim_rule": "Hunters in Regions 2-7 must present the full hide and skull..."
      }
    ],
    "source": { ... }
  },
  "meta": {
    "warnings": [
      {
        "code": "SUPERSEDED_BY_CORRECTION",
        "section": "seasons",
        "message": "The 2026 Black Bear booklet was amended by a correction published 2026-03-18."
      }
    ]
  }
}
```

Key observations:
- Closure predicate inline on the spring window. Season status is `conditionally_closed` to signal the user should check current harvest levels.
- Three reporting obligations, one statewide and two region-specific. The UI can render these as separate cards or grouped by region; the data supports either.
- The correction PDF triggers a warning, referencing the amended publication.

### Example 3: Colorado elk, hybrid-draw unit, 2026 (Q3 draw_spec in action)

```json
{
  "resolved": {
    "jurisdiction": {
      "state": "US-CO",
      "primary_unit": "GMU-024",
      "overlays": []
    },
    "species_canonical": "cervus_canadensis",
    "license_year": 2026
  },
  "tags": {
    "tags": [
      {
        "license_code": "E-E-024-O1-R",
        "name": "Elk, GMU 024, 1st Rifle, Resident",
        "kind": "limited_draw",
        "species": "elk",
        "weapon_types": ["rifle"],
        "residency": "resident",
        "quota": 25,
        "application_deadline": "2026-04-02",
        "draw_spec": {
          "state": "US-CO",
          "hunt_code": "E-E-024-O1-R",
          "year": 2026,
          "quota": 25,
          "point_system": {
            "kind": "preference_linear",
            "accrual": "annual_on_apply",
            "reset_on_success": true,
            "purchase_only_code": "E-P-999-99-P",
            "inactive_forfeit_years": null
          },
          "residency_cap": { "nonresident_max_share": 0.20 },
          "choices": { "count": 4, "points_used_in_choices": [1] },
          "pools": [
            {
              "share": 0.80,
              "selection": "rank_ordered_by_points",
              "eligibility": {},
              "tie_break": "random"
            },
            {
              "share": 0.20,
              "selection": "unweighted_random",
              "eligibility": { "min_points": 5 }
            }
          ],
          "draw_phase": "primary",
          "successor_hunt_code": "E-E-024-O1-R-SECONDARY",
          "application_deadline": "2026-04-02",
          "parameters": null,
          "source": { ... }
        },
        "reserved_pools": [],
        "purchase_url": "https://cpw.state.co.us/apply",
        ...
      }
    ]
  }
}
```

Key observations:
- `draw_spec` is embedded in the response for context-assembly efficiency — agent gets the full draw mechanics in one response without an additional tool call.
- The hybrid-draw 80/20 structure is visible in `pools`. An agent answering "what are my odds" can use this directly.
- `reserved_pools` is empty here because Colorado doesn't use landowner preference on hybrid units the way Montana does; the field exists but is unused.

---

## Migration path from v1

The v1 schema was never populated with real data — all references so far have been to a documented TypeScript interface and TODO placeholder migrations. Migration is therefore cheap: we write v2 migrations from scratch and mark v1 as superseded in the ADR.

If ingestion had produced v1 data, the migration strategy would be:
1. Freeze v1 writes; all new ingestion targets v2.
2. Write `_v1` → v2 translation functions per entity; backfill v2 tables from v1 rows.
3. Cutover reads to v2 once v2 data is verified against v1 for a sample set.
4. Deprecate v1 tables, keep for 30 days, drop.

This is documented because later schema revisions (v2 → v3) will need to follow this pattern, and having the pattern written out now prevents ad-hoc migrations later.

---

## What this proposal does NOT answer

Deliberately out of scope for this document:

- **How confidence is calculated.** Every entity carries a `confidence` field. The ingestion pipeline assigns these, but the exact calculation is per-state and per-extraction-method. This is adapter-level logic, not schema-level.
- **Exactly which reporting obligations Montana has for each species.** The schema supports region-specific reporting; populating it correctly is ingestion work.
- **How successor hunt codes are resolved for secondary draws.** The schema supports the pointer; the ingestion pipeline has to produce both the primary draw_spec and the secondary draw_spec in the same run. This is an operational detail.
- **Caching and query performance at the MCP server.** The schema is designed for clean queries, not for throughput optimization. V1 relies on Postgres being fast enough at V1 scale; V2 may add caching.

---

## Design decisions, with context

Five design choices worth calling out specifically. Three are locked (decided during review); two remain as notes for future attention.

**Entity decomposition — locked.** Six entities instead of fewer. An alternative was to embed seasons, licenses, and reporting obligations directly into `regulation_record` as JSON arrays. That would be simpler to query (one table, no joins) but lose normalization and force duplication when two regulation records share a season definition (which is the common case in Montana — a B license and its parent A license typically share season windows). Decomposed form handles cross-sharing cleanly. Accepted because the research surfaced real structural variance that the decomposed form accommodates cleanly, and the cost of additional tables is small at V1 scale.

**Overlay geometries — locked.** `jurisdiction_binding` is included from day one rather than deferred to V2. The simpler alternative was to put the primary unit geometry directly on `regulation_record` and introduce bindings only when overlays become necessary. Rejected because the overlay cases are in the Montana primary sources *right now* — CWD Management Zones cross-cutting HDs, BMUs distinct from HDs, restricted areas overlaying both. A V1 that cannot express these would either misrepresent the regulation or require a schema migration before first ingestion. Accepted because deferral would have been false economy.

**No server-side `overview` field — locked.** The response shape omits the derivative "headline + decision" field that the Q2 proposal recommended. The principle: *server returns structure, client composes presentation.* A web UI rendering a map sidebar wants a hero like "Elk season opens in 3 days" because that matches its spatial surface. An agent answering a user's question wants to compose "Yes, you can hunt elk here on Oct 15, but you need a general license" because that matches its conversational surface. Each client knows its presentation context better than the server does. Keeping presentation out of the server response avoids a class of correctness bugs (server-composed summaries that drift from structured sections) and establishes a reusable principle for other potentially-derived fields. If a future API consumer needs a server-composed headline, adding an `overview` field is additive and breaks nothing; we will have lost nothing by deferring.

**Confidence calibration — noted for later.** Every entity carries a `confidence: "high" | "medium" | "low"` field. The ingestion pipeline assigns these, but this proposal does not define the calibration. If `confidence` is user-facing (it appears in `ResolvedTag`, `ResolvedSeasonWindow`, etc.), inconsistent calibration across states will make it noise rather than signal. Deferred to a specific open question during M1 implementation; the field exists in the schema regardless of how calibration is resolved.

**`parameters` escape hatch — noted for later.** The `draw_spec.parameters` field is typed as `Record<string, unknown>` and is explicitly not read by shared code. This discipline cannot be enforced at the type level — any code *can* read the field, the rule is that shared code *must not*. Enforcement is by convention plus code review. At V1 scale with one author, convention is sufficient. If contributors grow, this becomes a real enforcement question, possibly warranting a linter rule or a code-review checklist item.

---

## Next steps after review

Once this proposal is accepted (with any amendments from review):

1. Propagate the entity model into `architecture.md`, replacing the current `RegulationRecord` interface.
2. Update `open-questions.md`: mark Q1, Q2, Q3, Q4 as resolved with links to the research documents and this proposal.
3. Add or revise ADRs:
   - ADR-006 (Schema Versioned From Day One) gets the v1→v2 migration story.
   - A new ADR-010 or similar captures the entity decomposition decision.
   - A new ADR captures the response shape (Q2 resolution).
   - A new ADR captures the draw modeling (Q3 resolution).
4. Write the initial Postgres migrations to `supabase/migrations/`.
5. Begin M1 (Montana ingestion) against the v2 schema.
