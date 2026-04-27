# E01: Schema Migrations, RLS, and Quality Gates

**Status:** In Progress
**Milestone:** M1 — Montana Ingestion
**Dependencies:** M0 (complete)
**Validated:** 2026-04-24
**Estimated Stories:** 6
**UAT Gating:** All stories UAT: no (verification-gated, no human sign-off required)

---

## Objective

E01 creates the Postgres schema for all six entities in the decomposed regulation data model, establishes deny-all RLS policies that structurally disable PostgREST access, installs pre-commit quality gates, and produces Python and TypeScript type definitions that mirror the DDL. No data is loaded — E02 and E03 fill the tables. Every subsequent M1 story assumes E01's schema is stable and its migrations apply cleanly.

See [PRD 001](../../planning/prds/001-M1-montana-ingestion.md) for authoritative scope. See [`docs/architecture.md`](../../architecture.md) § "Schema types" for the canonical TypeScript interfaces that DDL mirrors.

---

## Stories

### S01.1: Install pre-commit hooks ✅

**As a** developer committing to this repo
**I want** pre-commit hooks running TypeScript lint, Python lint, and secrets scanning
**So that** code quality and credential hygiene are enforced before any M1 code lands

**UAT: no**

**Context:**

Pre-commit hooks are an E01 deliverable per [PRD 001](../../planning/prds/001-M1-montana-ingestion.md). Tool choice (Husky, `pre-commit`, lefthook) is deferred to the implementation agent — pick whichever works cleanly across the repo's polyglot structure (Python in `ingestion/`, TypeScript in `mcp-server/` and `web/`).

Hooks required:

- **TypeScript lint:** `tsc --noEmit` in `mcp-server/` and `web/`
- **Python lint:** `ruff check` in `ingestion/`
- **Secrets scanning:** detect-secrets, gitleaks, or equivalent

Per PRD 001 risk R6: false positives from secrets scanning are expected. Tune the config (allowlist `.env.example`, test fixtures) — do not disable the hook. Expect 1-2 rounds of config tuning.

Hooks must run cleanly against the current repo state (M0 scaffold). If existing code triggers lint errors, fix them as part of this story.

**Acceptance Criteria:**

- [x] Pre-commit hook tool is installed and configured at repo root
- [x] TypeScript lint hook runs `tsc --noEmit` for `mcp-server/` and `web/`
- [x] Python lint hook runs `ruff check` for `ingestion/`
- [x] Secrets scanning hook is configured and runs on every commit
- [x] All hooks pass cleanly against the current repo state (no unresolved false positives)
- [x] `README.md` updated with hook setup instructions if manual developer action is needed
- [x] Hook config files committed to repo

---

### S01.2: Initial migration — entity tables, link tables, and indexes ✅

**As a** developer preparing the database for Montana data ingestion
**I want** all entity tables, link tables, and indexes created via timestamped Supabase migration
**So that** E02 and E03 have a validated schema to write against

**UAT: no**

**Context:**

This is the core E01 story. Creates the Postgres DDL that mirrors the canonical TypeScript interfaces in [`docs/architecture.md`](../../architecture.md) § "Schema types". The DDL patterns in [`docs/research/schema-proposal-v2.md`](../../research/schema-proposal-v2.md) are a useful reference for Postgres-specific choices (link tables, `int4range`, index strategy), but **architecture.md is the canonical source — on any conflict, architecture.md wins.** The research doc has stale FK shapes (e.g., `draw_spec_id` instead of `draw_spec_key`) that were superseded during v2 evolution. Migration file(s) go in `supabase/migrations/` as timestamped SQL.

**Schema version:** All tables target schema version 2 per [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md). `schema_version` columns appear on `regulation_record` and `draw_spec`.

**Migration must begin with:**

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

PostGIS must be loaded before any `geography` column type can be used. On Supabase, the extension is available but not auto-loaded.

**Ten tables to create:**

#### Entity Tables (7)

**1. `regulation_record`** — Anchor entity. Composite PK.

```
state text NOT NULL                          -- ISO 3166-2, e.g. "US-MT"
jurisdiction_code text NOT NULL              -- e.g. "MT-HD-262"
species_group text NOT NULL                  -- "deer", "elk", etc.
license_year integer NOT NULL
schema_version integer NOT NULL DEFAULT 2
source jsonb NOT NULL                        -- SourceCitation (see below)
ingested_at timestamptz NOT NULL DEFAULT now()
confidence text NOT NULL CHECK (confidence IN ('high','medium','low'))
additional_rules jsonb NOT NULL DEFAULT '[]' -- VerbatimRule[] (see below)
PRIMARY KEY (state, jurisdiction_code, species_group, license_year)
```

**2. `season_definition`** — Named date ranges with weapon/residency constraints.

```
id text PRIMARY KEY                          -- deterministic, e.g. "MT-HD-262-elk-general-2026"
name text NOT NULL                           -- "General", "Archery Only", etc.
opens date NOT NULL
closes date NOT NULL
weapon_type text CHECK (weapon_type IN (
  'any_legal_weapon','archery','rifle','muzzleloader','shotgun',
  'handgun','crossbow','traditional_handgun','heritage_muzzleloader'))
residency text CHECK (residency IN ('resident','nonresident','both'))
closure_predicate jsonb                      -- ClosurePredicate (nullable)
verbatim_rule text NOT NULL                  -- per ADR-008
page_reference text
source jsonb NOT NULL                        -- SourceCitation
```

**3. `license_tag`** — Permit instruments.

```
id text PRIMARY KEY                          -- deterministic, e.g. "MT-HD-262-elk-B-2026"
license_code text NOT NULL
name text NOT NULL
kind text NOT NULL CHECK (kind IN ('general','limited_draw','over_the_counter','statewide'))
species text NOT NULL
weapon_types text[] NOT NULL                 -- WeaponType values
residency text NOT NULL CHECK (residency IN ('resident','nonresident','both'))
quota integer
quota_range int4range                        -- native Postgres range type (nullable)
purchase_url text NOT NULL
draw_spec_key jsonb                          -- soft FK to draw_spec {state, hunt_code, year} (nullable)
reserved_pools jsonb NOT NULL DEFAULT '[]'   -- ReservedPool[]
verbatim_rule text NOT NULL                  -- per ADR-008
source jsonb NOT NULL                        -- SourceCitation
```

Note: `draw_spec_key` is stored as jsonb (not decomposed FK columns) to avoid temporal ordering constraints during ingestion — a license_tag may be inserted before its referenced draw_spec exists. Referential integrity validated in application code. Per schema-proposal-v2.md.

**4. `draw_spec`** — Draw mechanics. Composite PK.

```
state text NOT NULL
hunt_code text NOT NULL
year integer NOT NULL
schema_version integer NOT NULL DEFAULT 2
quota integer
point_system jsonb                           -- PointSystem (nullable)
residency_cap jsonb                          -- ResidencyCap (nullable)
choices jsonb NOT NULL                       -- ChoiceConfig
pools jsonb NOT NULL                         -- AllocationPool[] (shares sum to 1.0, validated in app code)
draw_phase text NOT NULL CHECK (draw_phase IN ('primary','secondary','leftover'))
successor_hunt_code_key jsonb                -- soft self-FK {state, hunt_code, year} (nullable)
application_deadline date NOT NULL
parameters jsonb                             -- escape hatch; shared code NEVER reads (ADR-012)
source jsonb NOT NULL                        -- SourceCitation
PRIMARY KEY (state, hunt_code, year)
```

Note: `pools` has NO default — an empty array is semantically invalid (every draw has at least one allocation pool). `parameters` is the `Record<string, unknown>` escape hatch per [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md) — only state adapters in `ingestion/states/<state>/` may write to it; shared code must never read it.

**5. `reporting_obligation`** — Post-harvest/in-season duties.

```
id text PRIMARY KEY                          -- deterministic
kind text NOT NULL CHECK (kind IN (
  'harvest_report','mandatory_check','tooth_submission',
  'hide_skull_presentation','cwd_sample','other'))
deadline text NOT NULL                       -- human-readable
deadline_hours integer
submission_method text NOT NULL CHECK (submission_method IN (
  'online','phone','in_person_check_station','mail','agency_office'))
submission_url text
submission_phone text
applies_to_regions text[]                    -- nullable; null = statewide
what_to_present text[]
verbatim_rule text NOT NULL                  -- per ADR-008
source jsonb NOT NULL                        -- SourceCitation
```

**6. `geometry`** — Geographic polygons.

```
id text PRIMARY KEY                          -- deterministic, e.g. "MT-HD-262-geom"
name text NOT NULL
kind text NOT NULL CHECK (kind IN (
  'hunting_district','gmu','portion','bmu','cwd_zone',
  'restricted_area','bma','other'))
geom geography(MultiPolygon, 4326) NOT NULL  -- NOT Polygon, NOT geometry type
state text NOT NULL
license_year integer                         -- nullable; null = year-invariant geometries
source jsonb NOT NULL                        -- SourceCitation
```

**7. `jurisdiction_binding`** — Overlay relationships between geometries and regulation records.

```
id text PRIMARY KEY                          -- deterministic
regulation_record_state text NOT NULL
regulation_record_jurisdiction_code text NOT NULL
regulation_record_species_group text NOT NULL
regulation_record_license_year integer NOT NULL
geometry_id text NOT NULL REFERENCES geometry(id)
role text NOT NULL CHECK (role IN (
  'primary_unit','portion','restricted_area','cwd_management_zone',
  'bear_management_unit','block_management_area','other_overlay'))
verbatim_rule text
source jsonb NOT NULL                        -- SourceCitation
FOREIGN KEY (regulation_record_state, regulation_record_jurisdiction_code,
  regulation_record_species_group, regulation_record_license_year)
  REFERENCES regulation_record(state, jurisdiction_code, species_group, license_year)
```

#### Link Tables (3)

These link tables model the many-to-many relationships between `regulation_record` and its child entities. They replace the `_ids uuid[]` array columns from the TypeScript interfaces — the TypeScript interface shape is the logical view; the link tables are the physical storage. The MCP server populates the `_ids` arrays by JOINing these tables at query time.

**8. `regulation_season`**

```
state text NOT NULL
jurisdiction_code text NOT NULL
species_group text NOT NULL
license_year integer NOT NULL
season_definition_id text NOT NULL REFERENCES season_definition(id)
PRIMARY KEY (state, jurisdiction_code, species_group, license_year, season_definition_id)
FOREIGN KEY (state, jurisdiction_code, species_group, license_year)
  REFERENCES regulation_record(state, jurisdiction_code, species_group, license_year)
```

**9. `regulation_license`**

```
state text NOT NULL
jurisdiction_code text NOT NULL
species_group text NOT NULL
license_year integer NOT NULL
license_tag_id text NOT NULL REFERENCES license_tag(id)
PRIMARY KEY (state, jurisdiction_code, species_group, license_year, license_tag_id)
FOREIGN KEY (state, jurisdiction_code, species_group, license_year)
  REFERENCES regulation_record(state, jurisdiction_code, species_group, license_year)
```

**10. `regulation_reporting`**

```
state text NOT NULL
jurisdiction_code text NOT NULL
species_group text NOT NULL
license_year integer NOT NULL
reporting_obligation_id text NOT NULL REFERENCES reporting_obligation(id)
PRIMARY KEY (state, jurisdiction_code, species_group, license_year, reporting_obligation_id)
FOREIGN KEY (state, jurisdiction_code, species_group, license_year)
  REFERENCES regulation_record(state, jurisdiction_code, species_group, license_year)
```

#### Indexes

```sql
-- Spatial index (critical -- all point-in-polygon queries depend on this)
CREATE INDEX geometry_geom_gix ON geometry USING gist (geom);

-- Common query pattern indexes
CREATE INDEX geometry_state_kind_idx ON geometry (state, kind);
CREATE INDEX regulation_record_state_species_idx ON regulation_record (state, species_group);
CREATE INDEX jurisdiction_binding_geometry_id_idx ON jurisdiction_binding (geometry_id);
```

#### jsonb Sub-Model Contracts

The following types are stored as `jsonb` columns. Their structure is not enforced by DDL — it is enforced by Pydantic models in `ingestion/lib/schema.py` (S01.4) and by TypeScript interfaces in `mcp-server/src/types/` (S01.5). The canonical definitions are in [`docs/architecture.md`](../../architecture.md) § "Schema types":

- **`SourceCitation`** — `id`, `agency`, `title`, `url`, `publication_date`, `document_type` (enum: `annual_regulations | rule_change | emergency_order | correction`), `supersedes` (nullable), `page_reference` (nullable)
- **`VerbatimRule`** — `text`, `page_reference` (nullable), `confidence` (enum: `high | medium | low`), `source` (nested SourceCitation)
- **`ClosurePredicate`** — `kind` (enum: `quota_threshold | sex_threshold | emergency_order`), `threshold_percent` (nullable), `threshold_sex` (nullable, enum: `male | female`), `notification_channel` (enum: `agency_website | agency_phone | email_alert | other`), `observation_channel` (nullable, enum: `mandatory_reporting | check_station | harvest_survey`), `verbatim_rule`
- **`PointSystem`** — `kind` (enum: `preference_linear | bonus_squared | bonus_weighted`), `accrual` (enum: `annual_on_apply | annual_if_purchased`), `reset_on_success`, `purchase_only_code` (nullable), `inactive_forfeit_years` (nullable)
- **`ResidencyCap`** — `nonresident_max_share`
- **`ChoiceConfig`** — `count`, `points_used_in_choices` (integer array)
- **`AllocationPool`** — `share`, `selection` (enum: `rank_ordered_by_points | unweighted_random | squared_weighted_random | linear_weighted_random`), `eligibility` (optional fields: `min_points`, `residency`, `guided`), `tie_break` (optional, enum: `random | rank_ordered`)
- **`ReservedPool`** — `share`, `eligibility` (nested: `kind` enum: `landowner | youth | hunter_education_recent | other`, optional: `min_acres`, `min_acres_contiguous`, `min_age`, `max_age`, `notes`), `applies_to_residency` (nullable, Residency enum), `nonresident_subcap` (nullable), `verbatim_rule`

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md) (Supabase + PostGIS), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md) (schema versioned), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) (verbatim text), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md) (decomposed entity model), [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md) (draw mechanics).

**Acceptance Criteria:**

- [x] Timestamped migration file(s) exist in `supabase/migrations/`
- [x] Migration begins with `CREATE EXTENSION IF NOT EXISTS postgis`
- [x] All 10 tables created (7 entity + 3 link) with columns, types, and constraints per spec above
- [x] Composite PKs on `regulation_record(state, jurisdiction_code, species_group, license_year)` and `draw_spec(state, hunt_code, year)`
- [x] Text PKs on all other entities (deterministic IDs, not random UUIDs)
- [x] `geography(MultiPolygon, 4326)` on `geometry.geom` — not `Polygon`, not `geometry` type
- [x] All `verbatim_rule` columns are `NOT NULL` (per ADR-008)
- [x] All `source` columns are `jsonb NOT NULL` (per ADR-001)
- [x] `schema_version` columns on `regulation_record` and `draw_spec` with `DEFAULT 2`
- [x] All CHECK constraints on enum-like fields present and matching TypeScript union types (including `weapon_type` and `residency` on `season_definition`)
- [x] `license_tag.draw_spec_key` and `draw_spec.successor_hunt_code_key` stored as `jsonb` (soft FK)
- [x] `license_tag.quota_range` uses `int4range` type
- [x] `draw_spec.pools` is `NOT NULL` without a default
- [x] FK from `jurisdiction_binding` to `regulation_record` (composite) and to `geometry` (simple)
- [x] Link table FKs to both `regulation_record` and child entities
- [x] GiST spatial index on `geometry.geom`
- [x] Supporting indexes on `geometry(state, kind)`, `regulation_record(state, species_group)`, `jurisdiction_binding(geometry_id)`
- [x] Migration applies cleanly to a fresh Supabase project with PostGIS enabled
- [x] `SELECT COUNT(*) FROM <table>` returns 0 for every table after migration

---

### S01.3: RLS migration — deny-all policies ✅

**As a** developer ensuring the database cannot be accessed via PostgREST
**I want** deny-all RLS policies on every table with defense-in-depth protections
**So that** only service-role credentials (which bypass RLS) can read or write regulation data

**UAT: no**

**Context:**

Per [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md) and [PRD 001](../../planning/prds/001-M1-montana-ingestion.md), PostgREST is structurally disabled via RLS. This prevents an uncontrolled second path to the data that would bypass the MCP server ([ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md)).

This story creates a separate timestamped migration (after the entity tables migration from S01.2) that applies three security layers to **all 10 tables** (7 entity + 3 link):

**Layer 1 — Enable and force RLS:**

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
```

`FORCE` ensures RLS applies even to the table owner (the `postgres` role that runs migrations). The `service_role` is unaffected because its bypass comes from the `bypassrls` role attribute, not table ownership.

**Layer 2 — Deny-all policies:**

```sql
CREATE POLICY "Deny all access for authenticated" ON <table>
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON <table>
  FOR ALL TO anon USING (false) WITH CHECK (false);
```

`USING (false)` blocks reads. `WITH CHECK (false)` blocks writes. `FOR ALL` covers SELECT, INSERT, UPDATE, DELETE.

**Layer 3 — Explicit REVOKE (defense-in-depth):**

```sql
REVOKE ALL ON TABLE <table> FROM anon, authenticated;
```

Supabase's default `ALTER DEFAULT PRIVILEGES` grants `ALL` on new public-schema tables to `anon` and `authenticated`. The REVOKE removes these grants. Both layers must be breached for data to be exposed — RLS disabled AND grants re-added.

**Tables covered (all 10):** `regulation_record`, `season_definition`, `license_tag`, `draw_spec`, `reporting_obligation`, `geometry`, `jurisdiction_binding`, `regulation_season`, `regulation_license`, `regulation_reporting`.

**Service-role access:** In Supabase, `service_role` connects as a PostgreSQL role with the `bypassrls` attribute, which skips all RLS policy evaluation entirely. The deny-all policies and FORCE RLS do not affect it. Verify this, do not override it.

**Future convention:** No stored functions should be created in the `public` schema unless intentionally exposed via PostgREST. If spatial helper functions are needed (likely in E02), create them in a non-exposed schema.

**Verification approach:** After applying the migration, verify via the Supabase REST endpoint (curl against the REST URL), not just via `psql`:

1. Request as `anon` (using the publishable key) — empty result or error
2. Request as `authenticated` — same
3. Request as `service_role` (using the secret key) — query succeeds (tables empty but no RLS block)

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md).

**Acceptance Criteria:**

- [x] Timestamped migration file exists in `supabase/migrations/` (separate from entity table migration)
- [x] RLS enabled AND forced on all 10 tables
- [x] Deny-all policies for `authenticated` role on all 10 tables (USING false, WITH CHECK false)
- [x] Deny-all policies for `anon` role on all 10 tables
- [x] Explicit `REVOKE ALL` on all 10 tables from `anon` and `authenticated`
- [x] Service-role access is preserved (verify via `service_role` key query)
- [x] Verification via Supabase REST endpoint (curl-based) confirms: `anon` denied, `authenticated` denied, `service_role` succeeds
- [x] Migration applies cleanly after S01.2's migration

---

### S01.4: Python dataclasses matching DDL ✅

**As a** developer writing ingestion adapters
**I want** Pydantic models in `ingestion/lib/schema.py` that match the DDL one-to-one
**So that** ingestion code validates data against the same schema the database enforces

**UAT: no**

**Context:**

Per [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) and [`architecture.md`](../../architecture.md), schema is defined in three places kept in manual sync: DDL (S01.2), Python (this story), TypeScript (S01.5). The Python models are used by the ingestion pipeline to validate extracted data before writing to Postgres.

**File location:** `ingestion/ingestion/lib/schema.py`. The Python package root is `ingestion/ingestion/` (per `pyproject.toml`), so `lib/` must live inside it for imports to work. Create `ingestion/ingestion/lib/` with an `__init__.py`. The import path will be `from ingestion.lib.schema import ...`.

**Cross-language mapping convention:**

The three schema representations differ in structure where DDL requires flat columns but TypeScript uses nested objects. The convention is:

| Construct | DDL (Postgres) | Python (Pydantic) | TypeScript |
|-----------|---------------|-------------------|------------|
| Composite FK ref (e.g., `jurisdiction_binding` to `regulation_record`) | Flat columns: `regulation_record_state`, `regulation_record_jurisdiction_code`, etc. | Flat fields matching DDL column names | Nested object: `regulation_record_key: { state, jurisdiction_code, ... }` |
| Soft FK ref (e.g., `license_tag` to `draw_spec`) | `jsonb` column: `draw_spec_key` | Nested optional model: `draw_spec_key: DrawSpecKey \| None` | Nested optional object: `draw_spec_key: { state, hunt_code, year } \| null` |
| Relationship arrays (e.g., regulation to seasons) | Link tables (`regulation_season`) | Not on the entity model — handled by pipeline insert logic | Array of IDs: `season_definition_ids: string[]` (populated by JOIN at query time) |

Python models are DB-facing (flat fields for FK columns, no `_ids` arrays). TypeScript interfaces are API-facing (nested objects, `_ids` arrays). Transformation happens at the Postgres read boundary (MCP server).

**Models to create:**

All models use Pydantic `BaseModel`. Every field and every union/enum type from the architecture.md TypeScript interfaces must be mirrored exactly, including all `Literal` constraints.

**jsonb sub-models (shared):**

1. `SourceCitation` — `id: str`, `agency: str`, `title: str`, `url: str`, `publication_date: str` (ISO date), `document_type: Literal["annual_regulations", "rule_change", "emergency_order", "correction"]`, `supersedes: str | None`, `page_reference: str | None`
2. `VerbatimRule` — `text: str` (non-empty), `page_reference: str | None`, `confidence: Literal["high", "medium", "low"]`, `source: SourceCitation`
3. `ClosurePredicate` — `kind: Literal["quota_threshold", "sex_threshold", "emergency_order"]`, `threshold_percent: float | None`, `threshold_sex: Literal["male", "female"] | None`, `notification_channel: Literal["agency_website", "agency_phone", "email_alert", "other"]`, `observation_channel: Literal["mandatory_reporting", "check_station", "harvest_survey"] | None`, `verbatim_rule: str`
4. `ReservedPool` — `share: float`, `eligibility: ReservedPoolEligibility`, `applies_to_residency: Literal["resident", "nonresident", "both"] | None`, `nonresident_subcap: float | None`, `verbatim_rule: str`
5. `ReservedPoolEligibility` — `kind: Literal["landowner", "youth", "hunter_education_recent", "other"]`, `min_acres: int | None = None`, `min_acres_contiguous: bool | None = None`, `min_age: int | None = None`, `max_age: int | None = None`, `notes: str | None = None`
6. `PointSystem` — `kind: Literal["preference_linear", "bonus_squared", "bonus_weighted"]`, `accrual: Literal["annual_on_apply", "annual_if_purchased"]`, `reset_on_success: bool`, `purchase_only_code: str | None`, `inactive_forfeit_years: int | None`
7. `ResidencyCap` — `nonresident_max_share: float`
8. `ChoiceConfig` — `count: int`, `points_used_in_choices: list[int]`
9. `AllocationPool` — `share: float`, `selection: Literal["rank_ordered_by_points", "unweighted_random", "squared_weighted_random", "linear_weighted_random"]`, `eligibility: AllocationPoolEligibility | None = None`, `tie_break: Literal["random", "rank_ordered"] | None = None`
10. `AllocationPoolEligibility` — `min_points: int | None = None`, `residency: Literal["resident", "nonresident", "both"] | None = None`, `guided: bool | None = None`
11. `DrawSpecKey` — `state: str`, `hunt_code: str`, `year: int` (used for soft FK references)

**Entity models (matching DDL):**

12. `RegulationRecord` — all columns from DDL including composite PK fields; `schema_version: int = 2`; no `_ids` arrays (those are link table territory)
13. `SeasonDefinition` — `id: str`, all columns; `weapon_type: Literal[...] | None`; `residency: Literal[...] | None`
14. `LicenseTag` — `id: str`, all columns; `draw_spec_key: DrawSpecKey | None`; `quota_range` as `tuple[int, int] | None` (converted to `int4range` at write time)
15. `DrawSpec` — composite PK fields; `schema_version: int = 2`; `pools: list[AllocationPool]` (validated non-empty); `successor_hunt_code_key: DrawSpecKey | None`; `parameters: dict[str, Any] | None`
16. `ReportingObligation` — `id: str`, all columns with Literal types for `kind` and `submission_method`
17. `Geometry` — `id: str`, all columns; `geom` as `str` (WKT) or `dict` (GeoJSON) — implementation agent decides, must round-trip with PostGIS
18. `JurisdictionBinding` — `id: str`, flat FK fields (`regulation_record_state`, etc.), `geometry_id: str`, `role: Literal[...]`

**Serialization convention for optional fields:**

Models containing optional sub-fields (ReservedPoolEligibility, AllocationPoolEligibility, AllocationPool.tie_break) should use Pydantic's `model_config = ConfigDict(exclude_none=True)` or equivalent so that jsonb serialization omits `None` values rather than writing `null`. This matches TypeScript's absent-key semantics for optional properties (`?:`).

**Validation rules:**

- `verbatim_rule` fields validated as non-empty strings (per ADR-008)
- `source` fields typed as `SourceCitation` (not raw dict)
- `schema_version` has `default=2` on `RegulationRecord` and `DrawSpec`
- `DrawSpec.pools` validated as non-empty list (at least one AllocationPool)
- All `Literal` types match CHECK constraint values from DDL

**Relevant ADRs:** [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md).

**Acceptance Criteria:**

- [x] `ingestion/ingestion/lib/__init__.py` exists
- [x] `ingestion/ingestion/lib/schema.py` exists with Pydantic models for all 18 types listed above
- [x] Every model field matches the corresponding DDL column in name and type
- [x] Every jsonb sub-model field and enum matches the canonical TypeScript interfaces in architecture.md exactly
- [x] Literal types used for all enum-like fields matching DDL CHECK constraints and TypeScript unions
- [x] `verbatim_rule` fields validated as non-empty strings
- [x] `source` fields typed as `SourceCitation` (not raw dict)
- [x] `schema_version` has `default=2` on `RegulationRecord` and `DrawSpec`
- [x] `DrawSpec.pools` validated as non-empty list
- [x] Optional sub-fields use `None` defaults with exclude-none serialization config
- [x] `ruff check ingestion/` passes with no errors
- [x] `mypy ingestion/lib/schema.py` passes (or with `--ignore-missing-imports` for pydantic)
- [x] Module is importable: `python -c "from ingestion.lib.schema import RegulationRecord, SeasonDefinition, LicenseTag, DrawSpec, ReportingObligation, Geometry, JurisdictionBinding"`
- [x] No imports from `mcp-server/` or any TypeScript code

---

### S01.5: TypeScript types matching DDL ✅

**As a** developer building the MCP server
**I want** TypeScript interfaces in `mcp-server/src/types/` that match the DDL and Python models
**So that** the serving stack has type-safe access to the regulation schema

**UAT: no**

**Context:**

Per [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), TypeScript interfaces are the "canonical" schema types. They exist in [`docs/architecture.md`](../../architecture.md) § "Schema types" — this story copies them into source code and ensures they compile.

**File location:** `mcp-server/src/types/` per CLAUDE.md. This directory does not exist yet — create it.

**Files to create:**

1. `mcp-server/src/types/schema.ts` — all entity interfaces and supporting types, copied faithfully from architecture.md
2. `mcp-server/src/types/index.ts` — barrel export

**What to include:** All entity interfaces (`RegulationRecord`, `SeasonDefinition`, `LicenseTag`, `DrawSpec`, `ReportingObligation`, `Geometry`, `JurisdictionBinding`) plus all supporting types (`SourceCitation`, `VerbatimRule`, `ClosurePredicate`, `ReservedPool`, `PointSystem`, `ResidencyCap`, `ChoiceConfig`, `AllocationPool`, `WeaponType`, `Residency`, `GeometryRole`).

**What NOT to include:** The `GetRegulationsResponse` and related response-shape types. Those are M3 (MCP Server) scope. This story creates only the data-model types that mirror DDL.

**Cross-language sync check:** After writing these types, the implementation agent must verify field-by-field alignment with:

- DDL column names, types, and nullability from S01.2
- Python model field names and types from S01.4

Any mismatches are bugs to fix in the same PR.

**Note on `_ids` arrays:** The TypeScript interfaces include `season_definition_ids: string[]`, `license_tag_ids: string[]`, etc. on `RegulationRecord`. These represent the logical view — populated by JOINing link tables at query time. They do NOT correspond to DDL columns (the DDL uses link tables). Keep them in the TypeScript interface per architecture.md.

**Relevant ADRs:** [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md).

**Acceptance Criteria:**

- [x] `mcp-server/src/types/schema.ts` exists with all entity interfaces and supporting types
- [x] `mcp-server/src/types/index.ts` exists as barrel export
- [x] Interfaces match `docs/architecture.md` § "Schema types" exactly
- [x] `cd mcp-server && npx tsc --noEmit` passes with no errors
- [x] No `any` types anywhere in the types files (per CLAUDE.md)
- [x] No imports from `ingestion/` or any Python code
- [x] Cross-language sync verified: every DDL column has a matching TypeScript field and Python field with compatible types

---

### S01.6: Migration reproducibility verification

**As a** developer validating that E01's schema work is complete and repeatable
**I want** confirmation that migrations are reproducible and a brief runbook exists
**So that** E02 can begin with confidence that the database schema is stable

**UAT: no**

**Context:**

Final E01 story. Produces no new schema code — verifies existing migrations from S01.2 and S01.3 and documents the process.

**Verification steps:**

1. Start from a clean Supabase project (or reset the existing one)
2. Apply all migrations in order
3. Verify all 10 tables exist and are queryable
4. Verify `SELECT COUNT(*) FROM <table>` returns 0 for every table
5. Verify RLS: connect as `anon` — denied; `authenticated` — denied; `service_role` — succeeds
6. Verify PostGIS: `SELECT postgis_version()` returns version; spatial query succeeds
7. Apply migrations to a second fresh Supabase project — verify they apply cleanly (Supabase tracks applied migrations and won't re-run them on the same DB, so "reproducible" means any fresh project works)
8. Verify cross-language sync: run `tsc --noEmit` in `mcp-server/`, `ruff check` and `mypy` in `ingestion/`

**Runbook deliverable:** Brief documentation (in the epic file or a linked doc) covering:

- How to apply migrations from scratch
- How to verify RLS (including curl against Supabase REST endpoint)
- How to verify PostGIS
- Prerequisites (Supabase project, PostGIS enabled, credentials in `.env`)

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md).

**Acceptance Criteria:**

- [ ] Migrations apply cleanly to a fresh Supabase project
- [ ] All 10 tables are queryable after migration
- [ ] `COUNT(*)` returns 0 on every table
- [ ] RLS verification passes (anon denied, authenticated denied, service_role succeeds)
- [ ] PostGIS verification passes
- [ ] Migrations apply cleanly to a second fresh Supabase project (reproducible)
- [ ] Cross-language type checks pass (`tsc --noEmit`, `ruff check`, `mypy`)
- [ ] Brief runbook exists documenting migration and verification steps
- [ ] No new schema, migration, or type definition changes — this story only verifies existing work and produces documentation

---

## Exit Criteria

- [ ] All 6 stories complete (S01.1 through S01.6)
- [ ] All 10 tables exist with correct schema, constraints, and indexes
- [ ] RLS deny-all active on all 10 tables; service-role access preserved
- [ ] Python dataclasses match DDL one-to-one
- [ ] TypeScript interfaces match architecture.md and DDL
- [ ] Pre-commit hooks running cleanly
- [ ] Migrations reproducible on a fresh Supabase project
- [ ] No secrets in any committed file

---

## Parallelization Notes

**Within E01: stories run sequentially.** The developer creates a feature branch per story, implements, opens a PR, and merges before starting the next story.

**Recommended merge order:**

S01.1 -> S01.2 -> S01.3 -> S01.4 -> S01.5 -> S01.6

**Rationale:** Pre-commit hooks (S01.1) first so all subsequent work is linted. Entity tables (S01.2) before RLS (S01.3) because RLS references existing tables. Python types (S01.4) and TypeScript types (S01.5) are sequential to enable cross-sync verification. Reproducibility (S01.6) must be last as it verifies all prior work.

---

## Known Issues to Escalate

1. ~~**`source_date` column:**~~ **Resolved.** `source_date` was absorbed into `source.publication_date` during v1-to-v2 schema evolution. CLAUDE.md prose updated to reflect current state. ADR-006 and architecture.md prose still reference `source_date` and should be corrected when next touched.

2. **`confidence` on child entities:** Architecture.md prose says "every entity carries a `confidence` field" but the canonical TypeScript interfaces only place it on `RegulationRecord` and `VerbatimRule`. This epic follows the interfaces. Architecture.md prose should be corrected when next touched — not an implementation blocker.

3. ~~**`ingestion/lib/` path:**~~ **Resolved.** Correct path is `ingestion/ingestion/lib/schema.py` (inside the Python package). S01.4 updated accordingly.

---

## References

- [PRD 001](../../planning/prds/001-M1-montana-ingestion.md) — M1 scope, E01 exit criteria
- [`docs/architecture.md`](../../architecture.md) — canonical schema types, storage section
- [`docs/research/schema-proposal-v2.md`](../../research/schema-proposal-v2.md) — DDL reference, link table definitions
- [ADR-001](../../adrs/ADR-001-authority-preserved.md) — source citations required
- [ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md) — MCP server canonical; PostgREST blocked
- [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md) — Supabase + PostGIS; RLS commitment
- [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) — language split; three-place sync
- [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md) — schema_version on regulation_record, draw_spec
- [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) — verbatim_rule NOT NULL
- [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md) — six entity decomposition
- [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md) — draw_spec composite PK, pools, parameters
