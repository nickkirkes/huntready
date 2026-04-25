-- =============================================================================
-- HuntReady: Initial Schema Migration
-- S01.2 — Entity Tables, Link Tables, and Indexes
-- =============================================================================
-- Creates the full 6-entity decomposed regulation data model (10 tables total).
-- No data is loaded here — E02/E03 fill the tables.
--
-- Table creation order respects FK dependencies:
--   1. regulation_record, season_definition, license_tag, draw_spec  (no app FKs)
--   2. reporting_obligation, geometry                                 (no app FKs)
--   3. jurisdiction_binding                                           (FKs → regulation_record + geometry)
--   4. regulation_season, regulation_license, regulation_reporting    (FKs → regulation_record + child tables)
--   5. Indexes
--
-- Relevant ADRs: 001, 004, 006, 008, 010, 012
-- =============================================================================

-- PostGIS MUST be first — geography column type depends on it.
-- On Supabase the extension is available but not auto-loaded.
-- SCHEMA extensions avoids a type-name collision: PostGIS registers a base type
-- named "geometry" in pg_type, and CREATE TABLE geometry would fail if both land
-- in the public schema. Supabase projects always have an extensions schema in
-- the search_path, so PostGIS functions remain accessible unqualified.
CREATE EXTENSION IF NOT EXISTS postgis SCHEMA extensions;


-- =============================================================================
-- INDEPENDENT ENTITY TABLES (no FK dependencies on other app tables)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- regulation_record
-- Anchor entity. One row per (state, jurisdiction_code, species_group, year).
-- All other entities ultimately hang off this composite key.
-- -----------------------------------------------------------------------------
CREATE TABLE regulation_record (
    state                   text        NOT NULL,                -- ISO 3166-2, e.g. "US-MT"
    jurisdiction_code       text        NOT NULL,                -- e.g. "MT-HD-262"
    species_group           text        NOT NULL,                -- "elk", "deer", etc.
    license_year            integer     NOT NULL,
    schema_version          integer     NOT NULL DEFAULT 2,      -- ADR-006; bump propagates to all three type layers
    source                  jsonb       NOT NULL,                -- SourceCitation
    ingested_at             timestamptz NOT NULL DEFAULT now(),
    confidence              text        NOT NULL
        CHECK (confidence IN ('high', 'medium', 'low')),
    additional_rules        jsonb       NOT NULL DEFAULT '[]',   -- VerbatimRule[]

    PRIMARY KEY (state, jurisdiction_code, species_group, license_year)
);

-- -----------------------------------------------------------------------------
-- season_definition
-- Named date ranges with optional weapon/residency constraints.
-- Multiple regulation_records can reference the same season_definition row —
-- corrections update one row, not duplicated copies.
-- -----------------------------------------------------------------------------
CREATE TABLE season_definition (
    id              text    PRIMARY KEY,                         -- deterministic, e.g. "MT-HD-262-elk-general-2026"
    name            text    NOT NULL,                            -- "General", "Archery Only", etc.
    opens           date    NOT NULL,
    closes          date    NOT NULL,
    weapon_type     text
        CHECK (weapon_type IN (
            'any_legal_weapon', 'archery', 'rifle', 'muzzleloader',
            'shotgun', 'handgun', 'crossbow', 'traditional_handgun',
            'heritage_muzzleloader'
        )),                                                      -- nullable — null means no weapon restriction
    residency       text
        CHECK (residency IN ('resident', 'nonresident', 'both')),-- nullable — null means no residency restriction
    closure_predicate   jsonb,                                   -- ClosurePredicate (nullable)
    verbatim_rule       text    NOT NULL,                        -- per ADR-008
    page_reference      text,
    source              jsonb   NOT NULL                         -- SourceCitation
);

-- -----------------------------------------------------------------------------
-- license_tag
-- Permit instruments. May reference a draw_spec via soft FK.
-- -----------------------------------------------------------------------------
CREATE TABLE license_tag (
    id              text    PRIMARY KEY,                         -- deterministic, e.g. "MT-HD-262-elk-B-2026"
    license_code    text    NOT NULL,
    name            text    NOT NULL,
    kind            text    NOT NULL
        CHECK (kind IN ('general', 'limited_draw', 'over_the_counter', 'statewide')),
    species         text    NOT NULL,
    weapon_types    text[]  NOT NULL,                            -- WeaponType values
    residency       text    NOT NULL
        CHECK (residency IN ('resident', 'nonresident', 'both')),
    quota           integer,                                     -- nullable — null means no quota
    quota_range     int4range,                                   -- native Postgres range type (nullable)
    purchase_url    text    NOT NULL,
    draw_spec_key   jsonb,                                       -- soft FK → draw_spec {state, hunt_code, year} (ADR-012)
                                                                 -- stored as jsonb to avoid temporal ordering constraints;
                                                                 -- referential integrity validated in application code
    reserved_pools  jsonb   NOT NULL DEFAULT '[]',               -- ReservedPool[]
    verbatim_rule   text    NOT NULL,                            -- per ADR-008
    source          jsonb   NOT NULL                             -- SourceCitation
);

-- -----------------------------------------------------------------------------
-- draw_spec
-- Draw mechanics. Sibling entity referenced from license_tag by soft FK.
-- Composes point_system, residency_cap, choices, and allocation_pool[].
-- Per ADR-012: parameters is an escape hatch only state adapters may write.
-- -----------------------------------------------------------------------------
CREATE TABLE draw_spec (
    state                   text        NOT NULL,
    hunt_code               text        NOT NULL,
    year                    integer     NOT NULL,
    schema_version          integer     NOT NULL DEFAULT 2,      -- ADR-006
    quota                   integer,                             -- nullable
    point_system            jsonb,                               -- PointSystem (nullable)
    residency_cap           jsonb,                               -- ResidencyCap (nullable)
    choices                 jsonb       NOT NULL,                -- ChoiceConfig
    pools                   jsonb       NOT NULL,                -- AllocationPool[] — NO DEFAULT: empty array is semantically invalid
    draw_phase              text        NOT NULL
        CHECK (draw_phase IN ('primary', 'secondary', 'leftover')),
    successor_hunt_code_key jsonb,                               -- soft self-FK {state, hunt_code, year} (nullable)
    application_deadline    date        NOT NULL,
    parameters              jsonb,                               -- escape hatch — shared code MUST NEVER read (ADR-012)
    source                  jsonb       NOT NULL,                -- SourceCitation

    PRIMARY KEY (state, hunt_code, year)
);


-- =============================================================================
-- REMAINING INDEPENDENT ENTITY TABLES
-- (no FK dependencies on other app tables; separated for readability)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- reporting_obligation
-- Post-harvest and in-season duties (check stations, tooth submissions, etc.)
-- -----------------------------------------------------------------------------
CREATE TABLE reporting_obligation (
    id                  text    PRIMARY KEY,                     -- deterministic
    kind                text    NOT NULL
        CHECK (kind IN (
            'harvest_report', 'mandatory_check', 'tooth_submission',
            'hide_skull_presentation', 'cwd_sample', 'other'
        )),
    deadline            text    NOT NULL,                        -- human-readable deadline string
    deadline_hours      integer,                                 -- nullable — structured form of deadline
    submission_method   text    NOT NULL
        CHECK (submission_method IN (
            'online', 'phone', 'in_person_check_station', 'mail', 'agency_office'
        )),
    submission_url      text,
    submission_phone    text,
    applies_to_regions  text[],                                  -- nullable — null = statewide
    what_to_present     text[],
    verbatim_rule       text    NOT NULL,                        -- per ADR-008
    source              jsonb   NOT NULL                         -- SourceCitation
);

-- -----------------------------------------------------------------------------
-- geometry
-- Geographic polygons for hunting units and overlay zones.
-- ALL geometries use geography(MultiPolygon, 4326) — NOT Polygon, NOT geometry —
-- because real state data (CPW GMUs, MT HDs) contains multi-part units.
-- -----------------------------------------------------------------------------
CREATE TABLE geometry (
    id              text                            PRIMARY KEY, -- deterministic, e.g. "MT-HD-262-geom"
    name            text                            NOT NULL,
    kind            text                            NOT NULL
        CHECK (kind IN (
            'hunting_district', 'gmu', 'portion', 'bmu',
            'cwd_zone', 'restricted_area', 'bma', 'other'
        )),
    geom            geography(MultiPolygon, 4326)   NOT NULL,    -- geography NOT geometry; MultiPolygon NOT Polygon
    state           text                            NOT NULL,
    license_year    integer,                                     -- nullable — null = year-invariant geometries
    source          jsonb                           NOT NULL     -- SourceCitation
);


-- =============================================================================
-- JURISDICTION_BINDING
-- (FKs to regulation_record + geometry — must come after both)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- jurisdiction_binding
-- Overlay relationships between geometries and regulation records.
-- One regulation_record may bind to multiple geometries with different roles
-- (primary unit, CWD zone, BMA overlay, etc.).
-- verbatim_rule is NULLABLE here — matches architecture.md `string | null`
-- unlike all other verbatim_rule columns which are NOT NULL.
-- -----------------------------------------------------------------------------
CREATE TABLE jurisdiction_binding (
    id                                  text    PRIMARY KEY,     -- deterministic
    regulation_record_state             text    NOT NULL,
    regulation_record_jurisdiction_code text    NOT NULL,
    regulation_record_species_group     text    NOT NULL,
    regulation_record_license_year      integer NOT NULL,
    geometry_id                         text    NOT NULL
        REFERENCES geometry(id),
    role                                text    NOT NULL
        CHECK (role IN (
            'primary_unit', 'portion', 'restricted_area',
            'cwd_management_zone', 'bear_management_unit',
            'block_management_area', 'other_overlay'
        )),
    verbatim_rule                       text,                    -- NULLABLE — null = no binding-specific rule text
    source                              jsonb   NOT NULL,        -- SourceCitation

    FOREIGN KEY (
        regulation_record_state,
        regulation_record_jurisdiction_code,
        regulation_record_species_group,
        regulation_record_license_year
    ) REFERENCES regulation_record (state, jurisdiction_code, species_group, license_year)
);


-- =============================================================================
-- LINK TABLES
-- (all FKs to regulation_record + respective child table)
-- These model the many-to-many relationships between regulation_record and its
-- child entities. The MCP server populates the logical _ids arrays by JOINing
-- these tables at query time. All use the same 5-column composite PK pattern.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- regulation_season
-- Links regulation_record → season_definition (many-to-many)
-- -----------------------------------------------------------------------------
CREATE TABLE regulation_season (
    state                   text    NOT NULL,
    jurisdiction_code       text    NOT NULL,
    species_group           text    NOT NULL,
    license_year            integer NOT NULL,
    season_definition_id    text    NOT NULL
        REFERENCES season_definition(id),

    PRIMARY KEY (state, jurisdiction_code, species_group, license_year, season_definition_id),

    FOREIGN KEY (state, jurisdiction_code, species_group, license_year)
        REFERENCES regulation_record (state, jurisdiction_code, species_group, license_year)
);

-- -----------------------------------------------------------------------------
-- regulation_license
-- Links regulation_record → license_tag (many-to-many)
-- -----------------------------------------------------------------------------
CREATE TABLE regulation_license (
    state               text    NOT NULL,
    jurisdiction_code   text    NOT NULL,
    species_group       text    NOT NULL,
    license_year        integer NOT NULL,
    license_tag_id      text    NOT NULL
        REFERENCES license_tag(id),

    PRIMARY KEY (state, jurisdiction_code, species_group, license_year, license_tag_id),

    FOREIGN KEY (state, jurisdiction_code, species_group, license_year)
        REFERENCES regulation_record (state, jurisdiction_code, species_group, license_year)
);

-- -----------------------------------------------------------------------------
-- regulation_reporting
-- Links regulation_record → reporting_obligation (many-to-many)
-- -----------------------------------------------------------------------------
CREATE TABLE regulation_reporting (
    state                       text    NOT NULL,
    jurisdiction_code           text    NOT NULL,
    species_group               text    NOT NULL,
    license_year                integer NOT NULL,
    reporting_obligation_id     text    NOT NULL
        REFERENCES reporting_obligation(id),

    PRIMARY KEY (state, jurisdiction_code, species_group, license_year, reporting_obligation_id),

    FOREIGN KEY (state, jurisdiction_code, species_group, license_year)
        REFERENCES regulation_record (state, jurisdiction_code, species_group, license_year)
);


-- =============================================================================
-- INDEXES
-- =============================================================================

-- Spatial index — critical: all point-in-polygon queries depend on this.
-- GiST is the standard index type for PostGIS geography columns.
CREATE INDEX geometry_geom_gix ON geometry USING gist (geom);

-- Common query pattern: look up geometries by state + kind (e.g., all HDs in MT).
CREATE INDEX geometry_state_kind_idx ON geometry (state, kind);

-- Common query pattern: look up regulation records by state + species.
CREATE INDEX regulation_record_state_species_idx ON regulation_record (state, species_group);

-- Supports reverse-lookup: which regulation records bind to a given geometry?
CREATE INDEX jurisdiction_binding_geometry_id_idx ON jurisdiction_binding (geometry_id);
