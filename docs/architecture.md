# HuntReady — Architecture

This document describes how HuntReady is built, why it's built that way, and the tradeoffs taken in the initial version. It's the first file to read in this repo after the README.

## What HuntReady is, architecturally

HuntReady is a regulatory data platform exposed through three consumer-facing surfaces: an MCP server for agentic clients, a consumer web companion, and a Claude Code plugin for development workflows. All three surfaces are backed by a single regulation corpus assembled by an upstream ingestion pipeline. Nothing in the architecture assumes a specific consumer surface is primary; the schema and the server are the product, and the surfaces are ways to reach it.

```
┌─────────────────────────────────────────────────────────────┐
│                     Data Sources (public)                    │
│  State F&W agencies · PAD-US · BLM PLAD · USFS · data.gov   │
└──────────────────────────┬──────────────────────────────────┘
                           │ (HTTP, PDFs, GeoJSON, CSV)
                           ▼
          ┌─────────────────────────────────────┐
          │      ingestion/  (Python)           │
          │  extractors, normalizers, schema    │
          │         validation, QA              │
          └─────────────────┬───────────────────┘
                            │ (writes structured records)
                            ▼
          ┌─────────────────────────────────────┐
          │  Supabase Postgres + PostGIS        │
          │  regulation_record · season_defn    │
          │  license_tag · draw_spec            │
          │  reporting_obligation · geometry    │
          │       Montana · Colorado            │
          └─────────────────┬───────────────────┘
                            │ (SQL / PostGIS queries)
                            ▼
          ┌─────────────────────────────────────┐
          │     mcp-server/  (TypeScript)       │
          │   tools: get_regulations,           │
          │          check_land_status, ...     │
          └────────┬──────────────┬─────────────┘
                   │              │
                   ▼              ▼
          ┌──────────────┐  ┌───────────────────┐
          │ web/ (Next)  │  │ plugin/ (CC plug) │
          │ map + query  │  │ dev-time skills   │
          └──────────────┘  └───────────────────┘
```

## The architectural commitments

Four decisions shape everything else in this repo. They are worth stating explicitly before any code.

**Ingestion is upstream and offline.** The Python ingestion pipeline runs separately from the serving stack. It writes structured records into a shared Postgres database (Supabase). The MCP server and the web app never shell out to Python, never import anything from the `ingestion/` directory, and do not require a Python install to run. A contributor who only wants to work on the serving stack can run `npm install && npm run dev` against the database and ignore the entire Python toolchain. This mirrors how a production version of the pipeline would operate — scheduled jobs writing to a shared data store, stateless reads from the serving layer — and the separation is visible in the repo structure from V1.

**The MCP server is the canonical interface.** The web app and the Claude Code plugin are both clients of the MCP server, not independent implementations. This keeps the behavior consistent across surfaces and means there is exactly one place where the regulation query logic lives. It also means that a future native mobile app, a future integration into a third-party product, or a future B2B API consumer all plug into the same server without a second implementation.

**The schema is versioned from day one.** State regulations change annually (most states publish updates between March and July), and the schema *for how we model regulations* will change as we onboard additional states and species. Every regulation row carries a `schema_version` column and a `source_date`. Postgres migrations track the evolution of the schema in ordered, reviewable files. A future migration from `schema_version: 1` to `schema_version: 2` is an anticipated event, not a crisis, and the MCP server explicitly rejects records with unsupported schema versions rather than silently misinterpreting them.

**Authority is preserved, not replaced.** HuntReady does not interpret regulations. Every regulation response includes the source URL, the publication date of the source, and the specific section or page being referenced. The product's job is to route the hunter to the right authoritative source with enough context to understand it — not to replace the hunter's responsibility to read the source. This is a scope discipline as well as a liability discipline, and it's enforced at the schema level: a regulation record without a source citation fails validation.

## Component-by-component

### `ingestion/` — Python

Responsible for turning messy public data into clean, schema-conformant rows in Postgres.

The heart of the ingestion pipeline is a per-state adapter pattern. Each state has a directory under `ingestion/states/` containing:

- `fetch.py` — retrieves the source documents (PDFs, API responses, shapefiles)
- `extract.py` — pulls structured data from those sources
- `normalize.py` — maps state-specific fields onto the shared schema
- `validate.py` — runs the common validator with state-specific rules layered in
- `load.py` — writes validated records into Supabase Postgres via the shared database client
- `sources.yaml` — a static record of every source document, its URL, its publication date, and its intended usage

State adapters are isolated from each other. Montana's extractor can be broken without breaking Colorado's. Adding a third state means adding a fourth directory, not modifying shared code. The shared code lives in `ingestion/lib/` and covers PDF extraction primitives, geospatial preparation against PAD-US boundaries, schema validation, and the Postgres writer.

The ingestion pipeline is run via `make ingest STATE=montana` (or `make ingest-all`), which fetches, extracts, normalizes, validates, and loads in a single command. In V1, ingestion is run manually. In a production version, this would run as scheduled jobs against the same database. The boundary between those two versions is clean because the pipeline already writes idempotently to a shared store.

A deliberate note on PDF handling: regulations arriving as PDFs are the primary reason ingestion is in Python. Tools like `pdfplumber`, `pypdf`, and `unstructured` materially outperform their Node counterparts for this work, and regulation PDFs are rarely well-structured. The ingestion pipeline uses a layered strategy — structured extraction where possible, LLM-assisted extraction with validation for unstructured sections, and human-in-the-loop flagging for low-confidence records — and all three strategies have Python as their center of gravity. Attempting this in Node would mean fighting the tooling on the hardest part of the problem.

### `mcp-server/` — TypeScript

An MCP server built on the Anthropic TypeScript SDK. Exposes a small, well-scoped set of tools that agentic clients (Claude Desktop, Claude Code, Cursor, Windsurf) can call.

The V1 tool set:

- `get_regulations(lat, lng, species, date)` — the headline tool. Given a point, a species, and a date, returns the applicable regulation sections with source citations, license requirements, tag requirements, methods of take, and season windows.
- `check_land_status(lat, lng)` — returns the land management authority, public/private status, and access constraints for a point. Backed by PAD-US and BLM PLAD.
- `list_seasons(state, species, year)` — returns season windows for a given state/species/year combination.
- `get_tag_requirements(state, species, year, residency)` — returns the tag type(s), draw vs. general status, application deadlines, and direct links to the state agency's purchase flow.
- `get_agency_contacts(lat, lng)` — returns the regional game warden contact, regulation questions hotline, and regional office for the district containing the point.

The server reads regulation data from Supabase Postgres via a connection pool. Spatial queries (point-in-polygon against PAD-US, GMU lookups) use PostGIS operators and are expressed in SQL rather than reimplemented in application code. Query responses are not cached in V1 — Postgres is fast enough at this dataset size that caching is premature optimization, and leaving it out keeps the data freshness story honest: what the database shows is what the user sees.

Each tool response includes, alongside the answer, a `sources` array containing the source URL, source publication date, and schema version for every regulation record touched by the query. Agentic clients are expected to surface these to users. The web companion does so explicitly.

### `web/` — Next.js

A deliberately minimal map-first consumer surface. Not a polished consumer product; a credible demonstration of how a consumer would interact with HuntReady's data.

The single primary flow:

1. User lands on a map (Mapbox GL JS, zoomed to the supported states).
2. User drops a pin. A sidebar populates with land status (from `check_land_status`) and a species/date picker.
3. User selects species and date. The sidebar expands with the full regulation stack (from `get_regulations`): season status, tag requirements with direct purchase links, methods of take, unit-specific rules, and agency contacts.
4. Every regulation panel links to its authoritative source, with the source publication date visible.

The web app calls the MCP server via a thin internal HTTP adapter rather than calling the MCP protocol directly from the browser. This is a pragmatic choice — MCP is designed for agentic clients, not browsers, and the adapter keeps the web app's call pattern clean. The adapter lives in `web/lib/mcp-client.ts` and translates MCP tool calls into REST-style endpoints served by a small shim in `mcp-server/http.ts`. In a production version, this shim would either become a first-class HTTP API or be replaced by a dedicated BFF. For the prototype, it's a 50-line file.

The UI uses Tailwind, no component library beyond what Next.js ships with, and optimizes for "clearly a working demonstration" over "visually impressive." A Director-level reviewer looking at this repo is evaluating engineering thinking, not front-end polish. Spending the two-week budget on polish would subtract from the depth of the architecture, not add to it.

### `plugin/` — Claude Code plugin

A Claude Code plugin shaped explicitly like the plugin pattern used by working geospatial engineering teams (see, for reference, the `.claude-plugin/` + `plugins/<name>/skills/<skill>/SKILL.md` structure that is becoming standard). Two skills in V1:

- `regulation-lookup` — a skill for querying HuntReady's MCP tools from inside a Claude Code session during development. Wraps the MCP tools with examples, includes a reference of common query patterns, and provides shortcut commands for the states and species currently supported.
- `ingest-state` — a skill for onboarding a new state. Walks the developer through fetching the state's regulation sources, running the extractor, normalizing against the schema, and validating the output. Includes the boilerplate for a new state adapter directory.

The plugin's presence in the repo communicates something specific: this product has an opinion about how it should be developed, and that opinion is agentic-native. Regulation ingestion is exactly the kind of work where a developer in 2026 should be pairing with an agent — the work is schema-shaped but the inputs are messy, and the leverage is in the pairing. The plugin makes that explicit.

## Storage

HuntReady uses **Supabase Postgres with the PostGIS extension** as the single source of truth for regulation data. The choice is loadbearing enough to warrant explicit treatment.

Postgres+PostGIS is the correct storage for this product, not a future upgrade. Regulation data is inherently spatial (unit boundaries, land-status queries) and relational (regulations reference units reference seasons reference tags). Modeling it in any other shape — JSON files, key-value stores, document databases — requires reimplementing pieces of what PostGIS and SQL already do well. The cost of adopting Postgres early is small (one Supabase project, a handful of migrations, a connection pool); the cost of *not* adopting it early is carrying a data layer that doesn't match the shape of the data.

Supabase specifically is chosen over self-hosted Postgres, Fly.io Postgres, or Neon for three reasons. First, setup time is near zero — a project is provisioned in minutes with PostGIS available as a checkbox-enabled extension. Second, the managed dashboard and migration tooling reduce operational friction during V1 when time is the scarcest resource. Third, Supabase's capabilities beyond Postgres (Auth, Storage, Edge Functions, Realtime) are available for V2 without a platform migration — not because V1 needs them, but because the option to use them later is free.

**What V1 uses from Supabase:** Postgres, PostGIS, database migrations, and the service-role connection from the MCP server and ingestion pipeline. That is all.

**What V1 explicitly does not use:** Supabase Auth (no accounts in V1); Supabase Storage (no file uploads); Edge Functions (the MCP server is the only serving layer); Realtime (not a product concern yet); and — critically — the auto-generated PostgREST API. PostgREST is a second, uncontrolled path to query the database. Allowing it to be used by a consumer surface would violate the architectural commitment that the MCP server is the canonical interface. It is disabled at the schema level via Row Level Security policies that deny anonymous and authenticated-user access, permitting only the MCP server's service-role credentials.

**Local development:** each contributor runs their own free-tier Supabase project and points their local environment at it via project-specific environment variables. This isolates experiments, prevents migration collisions, and keeps setup friction to roughly five minutes. The Supabase CLI with local Docker is a supported fallback but not the V1 default; the cold-start cost of the CLI outweighs its benefits at V1 scale. This decision is worth revisiting if offline development becomes a real need or if more than a handful of contributors join the project.

**Migrations:** database migrations live in `supabase/migrations/` as timestamped SQL files. Every schema change is a migration. Schema drift between the TypeScript types in `mcp-server/src/types/`, the Python types in `ingestion/lib/schema.py`, and the Postgres DDL is a known manual-sync burden, captured as an open question. At V1 scale, the drift risk is low enough that discipline suffices; at V2 scale, a generator may be warranted.

## Data model

HuntReady's data model is decomposed into six entities that compose to produce a regulation view. The decomposition is motivated by real structural variance in state regulation data — multiple named seasons per hunting district, multiple license types per species, region-specific reporting obligations, overlapping geographic jurisdictions — that a single flat record cannot represent without duplication or ambiguity. The full reasoning and the research evidence behind each entity live in [`research/schema-v2-proposal.md`](research/schema-v2-proposal.md).

The six entities:

- **`regulation_record`** — the anchor entity. One row per (state, jurisdiction, species group, license year). References the other entities that compose the regulation view.
- **`season_definition`** — a named date range with weapon, residency, and optional conditional closure metadata. A regulation record references one or many.
- **`license_tag`** — a permit instrument. One license_tag per license code (e.g., Montana's `262-00` B license, Colorado's `E-E-024-O1-R`). Carries optional reserved-pool eligibility (landowner preference, youth set-asides).
- **`draw_spec`** — draw mechanics, keyed by `(state, hunt_code, year)`. Composes a `point_system`, a `residency_cap`, and a list of `allocation_pool`s with shares and selection methods. State-specific quirks live in a typed `parameters` escape hatch that shared code does not read.
- **`reporting_obligation`** — a post-harvest or in-season duty. Region-specific (e.g., Montana black bear Region 1 tooth submission vs. Regions 2–7 hide-and-skull check).
- **`geometry`** + **`jurisdiction_binding`** — geographic polygons and their roles. A regulation record binds to one primary unit geometry and zero or more overlay geometries (CWD management zones, Bear Management Units, restricted areas).

### Schema types

The canonical TypeScript interfaces. Mirrored in Postgres DDL in `supabase/migrations/` and in Python dataclasses in `ingestion/lib/schema.py`, kept in manual sync at V1 scale.

```typescript
interface RegulationRecord {
  // Composite primary key: (state, jurisdiction_code, species_group, license_year)
  state: string;                      // ISO 3166-2, e.g. "US-MT"
  jurisdiction_code: string;          // e.g. "MT-HD-262"
  species_group: string;              // "deer" | "elk" | "antelope" | "bear" | "whitetail"
  license_year: number;
  schema_version: number;             // 2
  source: SourceCitation;
  ingested_at: string;
  confidence: "high" | "medium" | "low";
  season_definition_ids: string[];
  license_tag_ids: string[];
  reporting_obligation_ids: string[];
  jurisdiction_binding_ids: string[];
  additional_rules: VerbatimRule[];   // verbatim prose not structured by a child entity
}

interface SeasonDefinition {
  id: string;
  name: string;                       // "General" | "Archery Only" | "Early Season" | ...
  opens: string;                      // ISO date
  closes: string;
  weapon_type: WeaponType | null;
  residency: Residency | null;
  closure_predicate: ClosurePredicate | null;
  verbatim_rule: string;
  page_reference: string | null;
  source: SourceCitation;
}

interface LicenseTag {
  id: string;
  license_code: string;
  name: string;
  kind: "general" | "limited_draw" | "over_the_counter" | "statewide";
  species: string;
  weapon_types: WeaponType[];
  residency: Residency;
  quota: number | null;
  quota_range: [number, number] | null;
  purchase_url: string;
  draw_spec_key: { state: string; hunt_code: string; year: number } | null;
  reserved_pools: ReservedPool[];
  verbatim_rule: string;
  source: SourceCitation;
}

interface DrawSpec {
  // Composite primary key: (state, hunt_code, year)
  state: string;
  hunt_code: string;
  year: number;
  schema_version: number;             // 2
  quota: number | null;
  point_system: PointSystem | null;
  residency_cap: ResidencyCap | null;
  choices: ChoiceConfig;
  pools: AllocationPool[];            // shares sum to 1.0
  draw_phase: "primary" | "secondary" | "leftover";
  successor_hunt_code_key: { state: string; hunt_code: string; year: number } | null;
  application_deadline: string;
  parameters: Record<string, unknown> | null;  // state-adapter escape hatch; shared code does NOT read this
  source: SourceCitation;
}

interface ReportingObligation {
  id: string;
  kind: "harvest_report" | "mandatory_check" | "tooth_submission"
      | "hide_skull_presentation" | "cwd_sample" | "other";
  deadline: string;                   // human-readable
  deadline_hours: number | null;      // structured form when parseable
  submission_method: "online" | "phone" | "in_person_check_station" | "mail" | "agency_office";
  submission_url: string | null;
  submission_phone: string | null;
  applies_to_regions: string[] | null;  // null = statewide
  what_to_present: string[] | null;
  verbatim_rule: string;
  source: SourceCitation;
}

interface Geometry {
  id: string;
  name: string;
  kind: "hunting_district" | "gmu" | "portion" | "bmu" | "cwd_zone"
      | "restricted_area" | "bma" | "other";
  geom: "MultiPolygon";               // PostGIS: geography(MultiPolygon, 4326)
  state: string;
  license_year: number | null;
  source: SourceCitation;
}

interface JurisdictionBinding {
  id: string;
  regulation_record_key: {
    state: string; jurisdiction_code: string;
    species_group: string; license_year: number;
  };
  geometry_id: string;
  role: GeometryRole;
  verbatim_rule: string | null;
  source: SourceCitation;
}

type GeometryRole =
  | "primary_unit"
  | "portion"
  | "restricted_area"
  | "cwd_management_zone"
  | "bear_management_unit"
  | "block_management_area"
  | "other_overlay";

// Shared types

interface SourceCitation {
  id: string;
  agency: string;
  title: string;
  url: string;
  publication_date: string;
  document_type: "annual_regulations" | "rule_change" | "emergency_order" | "correction";
  supersedes: string | null;          // for corrections: the SourceCitation.id being amended
  page_reference: string | null;
}

interface VerbatimRule {
  text: string;
  page_reference: string | null;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

interface ClosurePredicate {
  kind: "quota_threshold" | "sex_threshold" | "emergency_order";
  threshold_percent: number | null;
  threshold_sex: "male" | "female" | null;
  notification_channel: "agency_website" | "agency_phone" | "email_alert" | "other";
  observation_channel: "mandatory_reporting" | "check_station" | "harvest_survey" | null;
  verbatim_rule: string;
}

interface ReservedPool {
  share: number;                      // 0.0–1.0
  eligibility: {
    kind: "landowner" | "youth" | "hunter_education_recent" | "other";
    min_acres?: number;
    min_acres_contiguous?: boolean;
    min_age?: number;
    max_age?: number;
    notes?: string;
  };
  applies_to_residency: Residency | null;
  nonresident_subcap: number | null;
  verbatim_rule: string;
}

type WeaponType =
  | "any_legal_weapon" | "archery" | "rifle" | "muzzleloader"
  | "shotgun" | "handgun" | "crossbow"
  | "traditional_handgun" | "heritage_muzzleloader";

type Residency = "resident" | "nonresident" | "both";

type PointSystem = {
  kind: "preference_linear" | "bonus_squared" | "bonus_weighted";
  accrual: "annual_on_apply" | "annual_if_purchased";
  reset_on_success: boolean;
  purchase_only_code: string | null;
  inactive_forfeit_years: number | null;
};

type ResidencyCap = { nonresident_max_share: number };

type ChoiceConfig = {
  count: number;
  points_used_in_choices: number[];
};

type AllocationPool = {
  share: number;
  selection:
    | "rank_ordered_by_points"
    | "unweighted_random"
    | "squared_weighted_random"
    | "linear_weighted_random";
  eligibility: {
    min_points?: number;
    residency?: Residency;
    guided?: boolean;
  };
  tie_break?: "random" | "rank_ordered";
};
```

### Verbatim text, confidence, and corrections

Three cross-cutting schema conventions worth stating explicitly.

**Verbatim text.** Every regulation reference carries a `verbatim_rule` string containing the exact published text. HuntReady does not paraphrase regulations; it routes to them. This is enforced at ingestion: records without verbatim text fail validation.

**Confidence.** Every entity carries a `confidence: "high" | "medium" | "low"` field produced by the ingestion pipeline. Records with `low` confidence surface with an explicit warning and a prominent link to the authoritative source. Records with `medium` confidence display normally but are included in periodic QA. Exact calibration of confidence is per-state adapter logic, tracked as an open question; the field exists in the schema regardless.

**Corrections.** State agencies publish correction documents mid-cycle (Montana FWP published a correction to the 2026 Black Bear booklet on 2026-03-18, one day after the booklet itself). The `document_type` enum includes a `correction` value, and corrections carry a `supersedes` pointer to the base publication's citation. Records descended from an amended base carry a `SUPERSEDED_BY_CORRECTION` warning in the response.

### Response shape: `GetRegulationsResponse`

The MCP tool `get_regulations(lat, lng, species, date)` returns a structured envelope with always-present, null-bearing sections. Every response has the same top-level shape regardless of data coverage; sections that don't apply carry explicit `null`, not omitted keys. This is Shape C in the taxonomy evaluated during response-shape research — the shape that distinguishes "not applicable" from "not in our dataset" explicitly rather than collapsing both to absence.

The server returns structure; clients compose presentation. There is no server-side `overview` or `headline` field. Web UIs and agentic clients each compose their own summary from the structured sections because each knows its presentation context.

```typescript
interface GetRegulationsResponse {
  query: { lat: number; lng: number; species: string; date: string };

  resolved: {
    jurisdiction: {
      state: string;
      primary_unit: string | null;
      overlays: { role: GeometryRole; name: string }[];
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
      is_stale: boolean;              // any source > 180 days
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
  status: "in_season" | "out_of_season" | "no_season_defined"
        | "conditionally_closed" | "unknown";
  windows: ResolvedSeasonWindow[];
  source: SourceCitation;
}

interface ResolvedSeasonWindow {
  name: string;
  opens: string;
  closes: string;
  weapon_type: WeaponType | null;
  residency: Residency | null;
  closure_predicate: ClosurePredicate | null;
  verbatim_rule: string;
  page_reference: string | null;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

interface TagsSection {
  tags: ResolvedTag[];                // plural — an HD can have one General + several B licenses
  source: SourceCitation;
}

interface ResolvedTag {
  license_code: string;
  name: string;
  kind: "general" | "limited_draw" | "over_the_counter" | "statewide";
  species: string;
  weapon_types: WeaponType[];
  residency: Residency;
  quota: number | null;
  application_deadline: string | null;
  draw_spec: DrawSpec | null;         // embedded for context-assembly efficiency
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
  obligations: ResolvedReportingObligation[];  // plural — region-specific variance
  source: SourceCitation;
}

interface ResolvedReportingObligation {
  kind: "harvest_report" | "mandatory_check" | "tooth_submission"
      | "hide_skull_presentation" | "cwd_sample" | "other";
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

interface Contact {
  role: string;
  name: string | null;
  phone: string | null;
  email: string | null;
  url: string | null;
  source: SourceCitation;
}

interface Warning {
  code:
    | "STALE_SOURCE"
    | "LOW_CONFIDENCE"
    | "CONFLICTING_RULES"
    | "PENDING_CHANGE"
    | "BOUNDARY_AMBIGUOUS"
    | "SUPERSEDED_BY_CORRECTION";
  section: "seasons" | "tags" | "methods" | "reporting" | "contacts" | "overall";
  message: string;
}
```

The response is returned as `structuredContent` on the MCP tool response. A parallel `content[0].text` field carries a minimal markdown rendering (overview text assembled from the structured sections, plus a coverage summary) for agentic clients that do not parse `structuredContent` — the minimal rendering is a thin derivative for backward compatibility, not a source of truth.

## State coverage in V1

Montana and Colorado are the seed states. Rationale:

Montana: OnX's home jurisdiction, a major western hunting destination, data is moderately structured (some JSON endpoints from FWP, regulations published as navigable PDFs). Hunter licensing is centralized through a single agency portal, which simplifies the purchase-flow links.

Colorado: substantially different regulatory regime from Montana. CPW runs a draw-based tag system for big game that is one of the most complex in the country, with a five-year preference-point system and detailed unit-level quotas. This is deliberately chosen as the *hard* state — if the schema models Colorado cleanly, it generalizes well to the rest of the West.

Washington, Wyoming, Idaho, and Utah are obvious next candidates but deliberately out of scope for V1. The goal is depth in two states over breadth in five.

## What is *not* in V1

Named here so that a reader of this doc doesn't mistake their absence for an oversight:

- **A mobile app.** The web companion is sufficient to demonstrate the product shape. Native mobile is a post-PMF decision.
- **Authentication, accounts, or saved queries.** The prototype is stateless at the user level. A production version adds accounts to power hunt planning, reminders, and partnerships.
- **Real-time data feeds.** V1 uses data ingested at build time. A production version adds emergency-order monitoring and same-day rule-change ingestion, which is an operational capability rather than a feature.
- **B2B API packaging.** The MCP server *is* a B2B API, conceptually, but V1 does not ship rate limiting, authentication, billing, or tiered access. Those are part of the commercial V2.
- **Harvest reporting integration, hunter education verification, or license purchase proxying.** HuntReady links to the state agency's flows for these; it does not implement them. This is a permanent architectural position, not a V1 limitation.

## Deployment

V1 deploys to three hosting surfaces, all free-tier at V1 scale:

- **Supabase** hosts the Postgres database with PostGIS. Created as a single project with the extension enabled. Migrations applied via the Supabase CLI.
- **Vercel** hosts the Next.js web companion at a public URL.
- A process host (Railway or equivalent) runs the MCP server's HTTP shim as a long-running Node process. The server reads from Supabase via the service-role connection string.

The MCP server is also installable locally for agentic clients — a `.mcp-config.json` in the repo root lets a user register HuntReady with Claude Desktop in one line. Local installation uses the same Supabase database as the hosted server.

Secrets in V1: the Supabase service-role key (for the MCP server), the Supabase anon key (for the web app, scoped by RLS), and the Mapbox token (for the web map). All other configuration is non-sensitive.

## Operational posture

Regulation data is only as good as its freshness. V1's operational model is simple and honest: every source citation carries a `publication_date`, every response surfaces the freshness of its inputs via `meta.data_freshness`, and the README documents the date of the last ingestion run for each state. A response whose stalest source is more than 180 days old carries an `is_stale: true` flag that the web UI renders as a visible indicator. The 2027 regulation cycle (publication generally March–July) will be the first real test of the pipeline's ability to handle annual updates — that is a known forthcoming event, not a surprise.

## Why this architecture is the strategy

One regulation corpus, one schema, three surfaces, clean separation between ingestion and serving. Every piece of the architecture is chosen to serve the proposition that *the data platform is the product*, and the surfaces are consequences of the platform. A competitor who built the web app without the platform would have a demo, not a business. A competitor who built the platform without the surfaces would have infrastructure, not a product. HuntReady is both because the architecture insists on both from the first commit.

---

*See [`roadmap.md`](roadmap.md) for milestones and scope. See the README for installation and local development. See [`research/schema-v2-proposal.md`](research/schema-v2-proposal.md) for the reasoning behind the data model.*
