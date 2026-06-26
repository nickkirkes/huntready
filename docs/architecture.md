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

**The schema is versioned from day one.** State regulations change annually (most states publish updates between March and July), and the schema *for how we model regulations* will change as we onboard additional states and species. The two anchor entities — `regulation_record` and `draw_spec` — carry an explicit `schema_version` column. Every regulation-bearing entity carries a `source: SourceCitation` jsonb that includes `publication_date`, the source-document publication date that answers the freshness question. (Pure-structure link tables like `regulation_license`, `regulation_season`, `regulation_reporting`, and `license_season` do not carry `source` — they encode joins between regulation-bearing entities; the source provenance lives on the entities they link, not on the link itself.) Postgres migrations track the evolution of the schema in ordered, reviewable files. A future migration from `schema_version: 1` to `schema_version: 2` is an anticipated event, not a crisis, and the MCP server explicitly rejects records with unsupported schema versions rather than silently misinterpreting them.

**Authority is preserved, not replaced.** HuntReady does not interpret regulations. Every regulation response includes the source URL, the publication date of the source, and (for document-style sources) the specific section or page being referenced. The product's job is to route the hunter to the right authoritative source with enough context to understand it — not to replace the hunter's responsibility to read the source. This is a scope discipline as well as a liability discipline, and it's enforced at the schema level: a regulation record without a source citation fails validation. Two source-citation shapes coexist: published documents (URL + actual publication date + page/section) and GIS layers (URL + `Jan 1 of REGYEAR` pseudo-publication-date, no page). Both are valid `SourceCitation`s; both are required at the schema level. See ADR-014 for the GIS-layer document type.

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

State adapters are isolated from each other. Montana's extractor can be broken without breaking Colorado's. Adding a third state means adding a fourth directory, not modifying shared code. The shared code lives in `ingestion/lib/` and covers PDF extraction primitives, ArcGIS feature-service fetch infrastructure, geospatial preparation, schema validation, and the Postgres writer. Per-state adapters may also carry empirically-calibrated constants (e.g., the digitization-tolerance thresholds in ADR-016, calibrated against Montana's data) that intentionally do not lift to shared code until a second state's data validates them.

The ingestion pipeline is run via `make ingest STATE=montana` (or `make ingest-all`), which fetches, extracts, normalizes, validates, and loads in a single command. In V1, ingestion is run manually. In a production version, this would run as scheduled jobs against the same database. The boundary between those two versions is clean because the pipeline already writes idempotently to a shared store.

A deliberate note on PDF handling: regulations arriving as PDFs are the primary reason ingestion is in Python. Tools like `pdfplumber`, `pypdf`, and `unstructured` materially outperform their Node counterparts for this work, and regulation PDFs are rarely well-structured. The ingestion pipeline uses a layered strategy — structured extraction where possible, LLM-assisted extraction with validation for unstructured sections, and human-in-the-loop flagging for low-confidence records — and all three strategies have Python as their center of gravity. Attempting this in Node would mean fighting the tooling on the hardest part of the problem.

### `mcp-server/` — TypeScript

An MCP server built on the Anthropic TypeScript SDK. Exposes a small, well-scoped set of tools that agentic clients (Claude Desktop, Claude Code, Cursor, Windsurf) can call.

The V1 tool set:

- `get_regulations(lat, lng, species, date)` — the headline tool. Given a point, a species, and a date, returns the applicable regulation sections with source citations, license requirements, tag requirements, methods of take, and season windows.
- `check_land_status(lat, lng)` — returns the land management authority, public/private status, and access constraints for a point. Backed by PAD-US and BLM PLAD. **M3/V1 note:** in V1 this resolves against the loaded `geometry`/`jurisdiction_binding` overlays — the PAD-US-derived restricted-area / no-hunt-zone rows from E05 — distinguishing a true closure (`no_hunt_zone`) from a regulated-but-huntable `other_overlay`; the fuller PAD-US + BLM PLAD public/private framing is the eventual contract. See the M3 serving-posture addendum below, ADR-023, and PRD 003.
- `list_seasons(state, species, year)` — returns season windows for a given state/species/year combination.
- `get_tag_requirements(state, species, year, residency)` — returns the tag type(s), draw vs. general status, application deadlines, and direct links to the state agency's purchase flow.
- `get_agency_contacts(lat, lng)` — returns the regional game warden contact, regulation questions hotline, and regional office for the district containing the point.

The server reads regulation data from Supabase Postgres via a connection pool. **Read-time** spatial queries (point-in-polygon against unit boundaries, land-status lookups via PAD-US) use PostGIS operators on the `geography` columns and are expressed in SQL — `ST_Covers(geom, ST_GeogFromText('SRID=4326;POINT(...)'))` for the headline case. **Ingestion-time** spatial derivation is a different story: cross-joins over real Montana data (~12k candidate pairs × ~113 KB MultiPolygons each) hit Supabase's role-locked 2-min `statement_timeout`, so the overlay computation that produces the **input fixture** for `jurisdiction_binding` is done locally in `shapely + STRtree` against a single bulk SELECT, with the result committed as `geometry-overlays.json` (see Storage below). The actual `jurisdiction_binding` rows are written by a later ingestion stage (E03's S03.10) that reads the fixture and emits SQL UPSERTs against the existing `regulation_record` rows. Two stages, separated cleanly: spatial computation (E02, local) and SQL row generation (E03, server). ADR-016 codifies the discriminator. Query responses are not cached in V1 — Postgres is fast enough at this dataset size that caching is premature optimization, and leaving it out keeps the data freshness story honest: what the database shows is what the user sees.

Each tool response includes, alongside the answer, a `sources` array containing the source URL, source publication date, and schema version for every regulation record touched by the query. Agentic clients are expected to surface these to users. The web companion does so explicitly.

### `web/` — Next.js

A deliberately minimal map-first consumer surface. Not a polished consumer product; a credible demonstration of how a consumer would interact with HuntReady's data.

The single primary flow:

1. User lands on a map (Mapbox GL JS, zoomed to the supported states).
2. User drops a pin. A sidebar populates with land status (from `check_land_status`) and a species/date picker.
3. User selects species and date. The sidebar expands with the full regulation stack (from `get_regulations`): season status, tag requirements with direct purchase links, methods of take, unit-specific rules, and agency contacts.
4. Every regulation panel links to its authoritative source, with the source publication date visible.

The web app calls the MCP server via a thin internal HTTP adapter rather than calling the MCP protocol directly from the browser. This is a pragmatic choice — MCP is designed for agentic clients, not browsers, and the adapter keeps the web app's call pattern clean. The adapter lives in `web/lib/mcp-client.ts` and translates MCP tool calls into REST-style endpoints served by a small shim in `mcp-server/http.ts`. In a production version, this shim would either become a first-class HTTP API or be replaced by a dedicated BFF. For the prototype, it's intentionally tiny.

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

**What V1 uses from Supabase:** Postgres, PostGIS, database migrations, the ingestion pipeline's service-role connection, and the MCP server's read-only edge connection (a SELECT-only role reached via Hyperdrive or the Supabase serverless driver, per ADR-024 — *not* the service-role key). That is all.

**PostGIS operator note (operator-facing).** Supabase's bundled PostGIS rejects direct `geom::geometry` casts on `geography` columns — a cluster-config quirk, not a missing extension. Workaround at every site that needs a geometry-only PostGIS function (`ST_IsValid`, `ST_NumGeometries`, `ST_Equals`, etc.): round-trip via WKT, `ST_GeomFromText(ST_AsText(geom), 4326)`. Documented in `docs/runbooks/E02-geometry-verification.md` and `.roughly/known-pitfalls.md`. The runbooks use the workaround at every relevant query.

**Overlay fixture pattern (ingestion-time spatial derivation).** Spatial relationships between geometries (HD↔Portion containment, HD↔CWD overlay, HD↔Restricted-Area overlay) are pre-computed in the ingestion pipeline via local `shapely + STRtree` and committed as a JSON fixture (`ingestion/states/<state>/fixtures/geometry-overlays.json`) plus a paired audit log of dropped pairs (`geometry-overlays-dropped.json`). The discriminator is a three-band area-ratio threshold (per ADR-016) that handles digitization-precision noise without inventing a new SQL predicate. Subsequent epics consume the kept fixture to populate `jurisdiction_binding` rows. This is the project's answer to "how does a regulation_record bind to many geometries given Supabase's `statement_timeout`" — pre-compute once, commit, consume at later-epic ingestion time.

**What V1 explicitly does not use:** Supabase Auth (no accounts in V1); Supabase Storage (no file uploads); Edge Functions (the MCP server is the only serving layer); Realtime (not a product concern yet); and — critically — the auto-generated PostgREST API. PostgREST is a second, uncontrolled path to query the database. Allowing it to be used by a consumer surface would violate the architectural commitment that the MCP server is the canonical interface. It is disabled at the schema level via Row Level Security policies that deny anonymous and authenticated-user access, permitting only the MCP server's service-role credentials.

**Local development:** each contributor runs their own free-tier Supabase project and points their local environment at it via project-specific environment variables. This isolates experiments, prevents migration collisions, and keeps setup friction to roughly five minutes. The Supabase CLI with local Docker is a supported fallback but not the V1 default; the cold-start cost of the CLI outweighs its benefits at V1 scale. This decision is worth revisiting if offline development becomes a real need or if more than a handful of contributors join the project.

**Migrations:** database migrations live in `supabase/migrations/` as timestamped SQL files. Every schema change is a migration. Schema is defined in **four** places kept in manual sync: Postgres DDL (`supabase/migrations/`), Pydantic v2 models (`ingestion/ingestion/lib/schema.py`), TypeScript interfaces (`mcp-server/src/types/schema.ts`), and the canonical interface listing in this document (§"Schema types" below). The four representations land in the same PR per ADR-006; ADR-018 codified this pattern as a coupled deliverable, not a follow-on chore. At V1 scale, the drift risk is low enough that discipline suffices; at V2 scale, a generator may be warranted.

## Data model

HuntReady's data model is decomposed into six entities that compose to produce a regulation view. The decomposition is motivated by real structural variance in state regulation data — multiple named seasons per hunting district, multiple license types per species, region-specific reporting obligations, overlapping geographic jurisdictions — that a single flat record cannot represent without duplication or ambiguity. The full reasoning and the research evidence behind each entity live in [`research/schema-proposal-v2.md`](research/schema-proposal-v2.md).

The six entities:

- **`regulation_record`** — the anchor entity. One row per (state, jurisdiction, species group, license year). References the other entities that compose the regulation view via four link tables (`regulation_season`, `regulation_license`, `regulation_reporting`, and `jurisdiction_binding`); the relationship arrays appear on the API-shape interface but are not stored columns on the table.
- **`season_definition`** — a named date range with weapon, residency, and optional conditional closure metadata. A regulation record references one or many via the `regulation_season` link.
- **`license_tag`** — a permit instrument. One license_tag per license code (e.g., Montana's `262-00` B license, Colorado's `E-E-024-O1-R`). Carries optional reserved-pool eligibility (landowner preference, youth set-asides).
- **`license_season`** — a link table connecting a `license_tag` to the specific `season_definition` rows it covers. Distinct from `regulation_season` (which is per-regulation_record). Both link tables coexist; each answers a different join question — `regulation_season` answers "what seasons exist for this HD" while `license_season` answers "which of those seasons does *this* license cover." Per ADR-018 §1, motivated by Montana's A/B asymmetric coverage (e.g., A valid in Heritage Muzzleloader, B not).
- **`draw_spec`** — draw mechanics, keyed by `(state, hunt_code, year)`. Composes a `point_system`, a `residency_cap`, and a list of `allocation_pool`s with shares and selection methods. State-specific quirks live in a typed `parameters` jsonb escape hatch that shared code does not read; through M1 nothing has needed it — Q12 deferrals (e.g., Montana's antelope `900-20` "first and only choice" semantic) are recorded in `docs/planning/epics/E03-deferred-items/draw-mechanics.md` for M2 exercise.
- **`reporting_obligation`** — a post-harvest or in-season duty. Region-specific (e.g., Montana black bear Region 1 tooth submission vs. Regions 2–7 hide-and-skull check).
- **`geometry`** + **`jurisdiction_binding`** — geographic polygons and their roles. A regulation record binds to one primary unit geometry and zero or more overlay geometries (CWD management zones, Bear Management Units, restricted areas). `geometry.kind='state'` exists for statewide regulations: a single `MT-STATEWIDE-geom` row is the binding target for `MT-STATEWIDE-{species}` regulation_records (Montana's antelope `900-20` license is the canonical V1 case). Per ADR-018.

### Schema types

The canonical TypeScript interfaces. Mirrored in Postgres DDL in `supabase/migrations/` and in Pydantic v2 models in `ingestion/ingestion/lib/schema.py`, kept in manual sync at V1 scale per the four-place rule above.

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
  // The four *_ids arrays are derived at query time via JOINs through the
  // regulation_season / regulation_license / regulation_reporting /
  // jurisdiction_binding link tables. They are NOT stored columns on
  // regulation_record itself; this is the API-shape view.
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
  pools: AllocationPool[];            // non-empty; shares should sum to 1.0 (validated in application code at ingestion time, not enforced by the schema)
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
      | "restricted_area" | "bma" | "state" | "other";
  geom: string;                       // WKT MultiPolygon; stored as geography(MultiPolygon, 4326)
  state: string;
  license_year: number | null;
  verbatim_rule: string | null;       // verbatim regulatory text from source attributes (e.g., ArcGIS REG/COMMENTS); null when source has none
  legal_description: string | null;  // FWP-published prose boundary description; null when source has none
  source: SourceCitation;
}

interface JurisdictionBinding {
  id: string;
  // API shape: nested object. DDL stores four flat columns
  // (regulation_record_state, regulation_record_jurisdiction_code,
  //  regulation_record_species_group, regulation_record_license_year)
  // referencing the composite PK on regulation_record. Pydantic mirrors
  // the flat DDL shape; TypeScript and this document use the nested shape
  // for ergonomic API surface. Both representations are correct for their
  // respective layer.
  regulation_record_key: {
    state: string; jurisdiction_code: string;
    species_group: string; license_year: number;
  };
  geometry_id: string;
  role: GeometryRole;
  verbatim_rule: string | null;
  source: SourceCitation;
}

// LicenseSeason is a link table connecting a license_tag to the season_definition(s)
// it covers — distinct from the regulation_season link (which is per-regulation_record).
// Both link tables coexist; each answers a different join question (per ADR-018 §1).
interface LicenseSeason {
  license_tag_id: string;
  season_definition_id: string;
}

type GeometryRole =
  | "primary_unit"
  | "portion"
  | "restricted_area"
  | "cwd_management_zone"
  | "bear_management_unit"
  | "block_management_area"
  | "other_overlay"
  | "no_hunt_zone";

// Shared types

interface SourceCitation {
  id: string;
  agency: string;
  title: string;
  url: string;
  publication_date: string;
  document_type: "annual_regulations" | "rule_change" | "emergency_order" | "correction" | "gis_layer";
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

Four cross-cutting schema conventions worth stating explicitly.

**Verbatim text.** Every regulation-bearing entity carries a `verbatim_rule` string containing the exact published text. HuntReady does not paraphrase regulations; it routes to them. This is enforced at ingestion: records without verbatim text fail validation. Two entities carry a nullable `verbatim_rule`: `JurisdictionBinding`, where some bindings are purely structural links between a regulation and a geometry with no specific regulation text to quote; and `Geometry`, where polygon source attributes (e.g., MT FWP layer #11's `REG` field) sometimes have no rule text at all.

`Geometry` separately carries `legal_description` (per ADR-018) for FWP-published *boundary* prose — semantically distinct from `verbatim_rule` (which holds *regulation text* per polygon). Both fields are independently nullable; both queryable; neither derived from the other. They serve different consumers — spatial queries vs. response composition for "what's the boundary of HD-262?". When a polygon's source has both a `REG` regulatory string and a `COMMENTS` regulatory string (e.g., MT FWP layer #2), the two are concatenated into `verbatim_rule` with the byte-frozen separator `\n\n--- COMMENTS ---\n\n` per ADR-015 — downstream consumers split on that token if they need to recover the two source strings.

**Confidence (regulation-text entities).** Confidence is stored on two carriers only: `regulation_record.confidence` and per-VerbatimRule `confidence` inside `additional_rules`. Child regulation-text entities (`season_definition`, `license_tag`, `draw_spec`, `reporting_obligation`) **inherit** at query time from their parent `regulation_record`; the schema does not store per-child confidence. Three-tier framework: `high` = structured table cell + regex-validated, no manual interpretation; `medium` = prose with deterministic anchor + interpretation; `low` = heuristic, fuzzy match, or hand-corrected. A regulation_record's confidence is the **MIN** across the per-row contributing values — most-uncertain wins, by design. Per ADR-017.

**Confidence (spatial entities).** `Geometry` and `JurisdictionBinding` are explicitly **out of the confidence framework** per ADR-017 §2 — they carry **provenance**, not confidence. `Geometry` carries a source-layer reference in its `source` jsonb (with `document_type='gis_layer'` per ADR-014); `JurisdictionBinding` carries an area-overlap percentage in the overlay-fixture audit trail (per ADR-016). Consumers asking "how reliable is this binding?" consult the appropriate provenance per entity type, not a uniform `confidence` field.

**Corrections.** State agencies publish correction documents mid-cycle (Montana FWP published a correction to the 2026 Black Bear booklet on 2026-03-18, one day after the booklet itself). The `document_type` enum includes a `correction` value, and corrections carry a `supersedes` pointer to the base publication's citation. The merge logic is **per-cell date arbitration**: when correction date and base-publication date conflict, the latest `publication_date` wins; the `supersedes` chain preserves the audit trail. Records descended from an amended base carry a `SUPERSEDED_BY_CORRECTION` warning in the response. **Correction-touched rows automatically demote one tier in confidence** (high→medium, medium→low, low→low) per ADR-017 §4 — a correction is itself a transformation step that introduces additional uncertainty about which version is currently in force.

### Response shape: `GetRegulationsResponse`

The MCP tool `get_regulations(lat, lng, species, date)` returns a structured envelope with always-present, null-bearing sections. Every response has the same top-level shape regardless of data coverage; sections that don't apply carry explicit `null`, not omitted keys. This is Shape C in the taxonomy evaluated during response-shape research — the shape that distinguishes "not applicable" from "not in our dataset" explicitly rather than collapsing both to absence.

The server returns structure; clients compose presentation. There is no server-side `overview` or `headline` field. Web UIs and agentic clients each compose their own summary from the structured sections because each knows its presentation context.

**Resolution sizing.** A single `(lat, lng)` resolves through `jurisdiction_binding` fan-out: M1 closes Montana with several thousand binding rows (median ~3 parents per child geometry, max 16), so the `resolved.jurisdiction.overlays` array can carry several entries in dense areas — typically one primary unit + 0-3 overlays, occasionally more. Likewise `tags` and `reporting` are first-class plural sections: A/B license asymmetry (per `license_season`) and region-specific reporting obligations are the norm, not edge cases. A typical Montana point resolves to 2-4 tags and 3-5 reporting obligations. Clients should size composition assumptions accordingly.

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
    | "SUPERSEDED_BY_CORRECTION"
    | "UNSUPPORTED_SCHEMA_VERSION";  // a row's schema_version is outside the
                                     // server's supported range: the row is excluded from output and
                                     // surfaced here (never silent-dropped, never a hard error) per the
                                     // ADR-006 schema-version gating; typically section: "overall"
  section: "seasons" | "tags" | "methods" | "reporting" | "contacts" | "overall";
  message: string;
}
```

The response is returned as `structuredContent` on the MCP tool response. A parallel `content[0].text` field carries a minimal markdown rendering (overview text assembled from the structured sections, plus a coverage summary) for agentic clients that do not parse `structuredContent` — the minimal rendering is a thin derivative for backward compatibility, not a source of truth.

## Serving deployment posture (M3 addendum)

*Added 2026-06-24 during M3 planning; see [ADR-023](adrs/ADR-023-remote-mcp-server-posture.md), [ADR-024](adrs/ADR-024-edge-runtime-postgres-access.md), and [PRD 003](planning/prds/003-M3-canonical-interface.md). This addendum supersedes the earlier implicit framing of M3 as a local stdio server with a REST shim.*

The MCP server (ADR-002) is deployed as a **remote, spec-conformant Streamable HTTP server on Cloudflare Workers** (stateless `createMcpHandler`; no Durable Objects, since the V1 tools are stateless reads). A stdio entrypoint is retained for local development via the `mcp-remote` proxy. **V1 auth is OAuth-2.1-ready but unenforced.** The endpoint is a **single open, read-only MCP endpoint** (public data; no enforced authentication, consistent with the "no authentication in V1" scope below). The OAuth-2.1 auth seam is **wired as one middleware integration point but not enforced** in the deployed V1 config — it is the drop-in for real auth (`@cloudflare/workers-oauth-provider`) when a GTM model gives the auth model a subject to protect (Q22). V1 does **not** rely on a static bearer token as a boundary: a single open endpoint cannot enforce a client-type split (a programmatic client could omit the token and take the open path), so any *enforced* token, tier, or quota requires a real boundary — a separate authenticated route or Cloudflare Access — which is a Q22/V2 decision. Baseline abuse protection in V1 is Cloudflare's **ambient DDoS/WAF** (a platform default, not a configured feature). The full GTM-determined auth model is deferred (open-questions Q22).

The server reads Postgres from the Workers edge runtime via Hyperdrive or the Supabase serverless driver (ADR-024), over a **read-only-enforced** connection (a dedicated SELECT-only role, not the write-capable service-role key). PostGIS `ST_*` runs server-side and is unaffected by the edge connection mechanism.

**No BFF (Q5 resolved):** because Shape C composes the full regulatory stack in a single `get_regulations` SQL pass, the web companion (M4) calls the MCP server directly and composites client-side; there is no backend-for-frontend. The browser-to-Worker call makes CORS/preflight a server-side (M3) concern.

Each tool returns `structuredContent` validated against a declared `outputSchema` as the source of truth, sets the read-only MCP annotations (`readOnlyHint`, `idempotentHint`), and carries `content[0].text` markdown only as a derivative.

## State coverage in V1

Montana and Colorado are the seed states. Rationale:

Montana: OnX's home jurisdiction, a major western hunting destination, data is moderately structured (some JSON endpoints from FWP, regulations published as navigable PDFs). Hunter licensing is centralized through a single agency portal, which simplifies the purchase-flow links.

Colorado: substantially different regulatory regime from Montana. CPW runs a draw-based tag system for big game that is one of the most complex in the country, with a five-year preference-point system and detailed unit-level quotas. This is deliberately chosen as the *hard* state — if the schema models Colorado cleanly, it generalizes well to the rest of the West.

Washington, Wyoming, Idaho, and Utah are obvious next candidates but deliberately out of scope for V1. The goal is depth in two states over breadth in five.

**M1 anchor numbers (Montana, license_year=2026).** 349 V1 geometry rows post-E02: 235 hunting districts (FWP layers #3, #10, #11) + 55 portions (#4, #12, #13, #14) + 57 restricted areas (#2, #15) + 2 CWD zones (`ADMBND_HD_CWD` Feature Service). E03's S03.0 adds the 350th — the Montana state boundary row (`MT-STATEWIDE-geom`, `kind='state'`). E03 then produces ~514 `regulation_record` rows across the five V1 species and the resulting several thousand `jurisdiction_binding` rows when S03.10 consumes the overlay fixture. These numbers are the M1 sizing reality; M2 (Colorado) is an order-of-magnitude calibration check.

## What is *not* in V1

Named here so that a reader of this doc doesn't mistake their absence for an oversight:

- **A mobile app.** The web companion is sufficient to demonstrate the product shape. Native mobile is a post-PMF decision.
- **Authentication, accounts, or saved queries.** The prototype is stateless at the user level. A production version adds accounts to power hunt planning, reminders, and partnerships.
- **Real-time data feeds.** V1 uses data ingested at build time. A production version adds emergency-order monitoring and same-day rule-change ingestion, which is an operational capability rather than a feature.
- **B2B API packaging.** The MCP server *is* a B2B API, conceptually, but V1 does not ship *enforced* authentication, configured rate limiting, billing, or tiered access. Those are part of the commercial V2. (The M3 remote endpoint stays consistent with this: it is open and read-only, protected only by Cloudflare's ambient DDoS/WAF, and ships the OAuth auth seam *wired but unenforced* — the drop-in point for V2 auth, not enforced auth. See the "Serving deployment posture (M3 addendum)" section and ADR-023.)
- **Harvest reporting integration, hunter education verification, or license purchase proxying.** HuntReady links to the state agency's flows for these; it does not implement them. This is a permanent architectural position, not a V1 limitation.

## Deployment

V1 deploys to three hosting surfaces, all free-tier at V1 scale:

- **Supabase** hosts the Postgres database with PostGIS. Created as a single project with the extension enabled. Migrations applied via the Supabase CLI.
- **Vercel** hosts the Next.js web companion at a public URL.
- **Cloudflare Workers** hosts the MCP server as a remote Streamable HTTP endpoint (per ADR-023; this supersedes the earlier "HTTP shim on a long-running Node process" plan). The server reads from Supabase from the edge runtime via Hyperdrive or the Supabase serverless driver, over a **read-only-enforced** connection (a dedicated SELECT-only role, not the service-role key — per ADR-024). See the "Serving deployment posture (M3 addendum)" section above.

The remote server also supports local development via the `mcp-remote` proxy — a committed example client-config snippet (for `.mcp.json` / `claude_desktop_config.json`) lets a user register HuntReady with Claude Desktop. Local dev uses the same Supabase database as the deployed server.

Secrets in V1: the MCP server's read-only DB credential (a SELECT-only-role DSN held in Workers Secrets — not the write-capable service-role key, per ADR-024), the Supabase publishable key (for the web app, scoped by RLS), and the Mapbox token (for the web map). (The OAuth auth seam is wired but unenforced in V1, so no auth credential is required for the deployed config; any credential added when the seam is enforced lives in Workers Secrets.) All other configuration is non-sensitive.

## Operational posture

Regulation data is only as good as its freshness. V1's operational model is simple and honest: every source citation carries a `publication_date`, every response surfaces the freshness of its inputs via `meta.data_freshness`, and the README documents the date of the last ingestion run for each state. A response whose stalest source is more than 180 days old carries an `is_stale: true` flag that the web UI renders as a visible indicator. The 2027 regulation cycle (publication generally March–July) will be the first real test of the pipeline's ability to handle annual updates — that is a known forthcoming event, not a surprise.

**Working artifacts vs. durable promises.** Per-epic working artifacts use two retention classes. **Calibration scaffolding** (e.g., E03's `docs/planning/epics/E03-confidence-findings/<story>.md` per-story working notes) is deleted at the milestone tag commit — the ADR is the durable record; the scratch is not. **Deferred items** (e.g., E03's `docs/planning/epics/E03-deferred-items/<topic>.md` files for Q12 deferrals) survive past milestone close — they are promises to the next milestone's PM. Per ADR-017 §6 for the deletion mechanism. This is how M1 closes without losing M2 inheritance.

## Why this architecture is the strategy

One regulation corpus, one schema, three surfaces, clean separation between ingestion and serving. Every piece of the architecture is chosen to serve the proposition that *the data platform is the product*, and the surfaces are consequences of the platform. A competitor who built the web app without the platform would have a demo, not a business. A competitor who built the platform without the surfaces would have infrastructure, not a product. HuntReady is both because the architecture insists on both from the first commit.

---

*See [`roadmap.md`](roadmap.md) for milestones and scope. See the README for installation and local development. See [`research/schema-proposal-v2.md`](research/schema-proposal-v2.md) for the reasoning behind the data model.*
