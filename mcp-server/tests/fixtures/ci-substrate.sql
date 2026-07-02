-- =============================================================================
-- HuntReady: CI Test Substrate
-- mcp-server/tests/fixtures/ci-substrate.sql
-- =============================================================================
-- DELIBERATELY NOT the real migrations.
--
-- The real migrations reference Supabase-only roles (anon, authenticated) that
-- do not exist in a vanilla postgis/postgis image and would error.  This file
-- creates only the minimum the CI smoke query and write-rejection tests need.
--
-- Applied by CI before running npm run test:ci.  See .github/workflows/ci.yml.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. PostGIS in the `extensions` schema (mirroring production / Supabase).
--
--    The postgis/postgis CI image PRE-INSTALLS PostGIS into `public`.  That
--    breaks two things:
--      (a) PostGIS registers a `geometry` TYPE in public — so `CREATE TABLE
--          geometry` below (which creates an associated composite type
--          public.geometry) collides: "type geometry already exists".
--      (b) ST_* live in public, not `extensions`, so the serving stack's
--          `extensions.`-prefixed calls (and the smoke queries) would not
--          resolve.
--    Because the extension already exists, a bare
--    `CREATE EXTENSION IF NOT EXISTS postgis SCHEMA extensions` is a NO-OP (the
--    SCHEMA clause is ignored) — it does NOT relocate PostGIS.  And PostGIS is
--    non-relocatable, so `ALTER EXTENSION ... SET SCHEMA` is not an option.
--
--    Production installs PostGIS into `extensions`
--    (migrations/20260425000000_initial_schema.sql L24) with `extensions` on the
--    search_path.  Reproduce that here: drop the image's public install and
--    recreate it in `extensions`, then put `extensions` on this session's
--    search_path so the bare `geography` type name in the table below resolves
--    exactly as it does under Supabase.  (DROP ... CASCADE also removes the
--    image's postgis_topology / tiger_geocoder add-ons, which we do not need.)
--    See .roughly/known-pitfalls.md (extensions.-prefix entry).
-- -----------------------------------------------------------------------------
DROP EXTENSION IF EXISTS postgis CASCADE;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION postgis SCHEMA extensions;
SET search_path TO public, extensions;


-- -----------------------------------------------------------------------------
-- 2. geometry table — minimal mirror of the real DDL.
--
--    The geometry TYPE is bare geography(MultiPolygon, 4326), NOT
--    extensions.geography.  PostGIS types are registered in pg_type and
--    resolved by search_path (section 1 put `extensions` on this session's
--    search_path); only PostGIS function *calls* take the extensions. prefix.
--    This matches the real DDL exactly:
--    migrations/20260425000000_initial_schema.sql:173.
--
--    verbatim_rule and legal_description columns are intentionally omitted —
--    the CI smoke/write tests never reference them.
--
--    RLS is NOT enabled on this table (no FORCE ROW LEVEL SECURITY) so the
--    write-rejection test sees a clean grant-level error (SQLSTATE 42501)
--    rather than an RLS policy block.
-- -----------------------------------------------------------------------------
CREATE TABLE geometry (
  id           text PRIMARY KEY,
  name         text NOT NULL,
  kind         text NOT NULL,
  geom         geography(MultiPolygon, 4326) NOT NULL,
  state        text NOT NULL,
  license_year integer,
  source       jsonb NOT NULL
);


-- -----------------------------------------------------------------------------
-- 3. Seed row — ensures WHERE state = 'US-MT' returns at least one row in
--    smoke queries.  name is NOT NULL so it must be provided.
--
--    `source` is a VALID SourceCitation (not `{}`) because the get_regulations
--    partial-coverage path surfaces the covering geometry's `source` as the sole
--    `sources[]` entry, which is validated against `sourceCitationSchema`.
-- -----------------------------------------------------------------------------
INSERT INTO geometry (id, name, kind, geom, state, source) VALUES (
  'MT-TEST-geom', 'MT Test', 'hunting_district',
  extensions.ST_GeogFromText('SRID=4326;MULTIPOLYGON(((-114 47,-113 47,-113 48,-114 48,-114 47)))'),
  'US-MT',
  '{"id":"mt-ci-geom-citation","agency":"CI Test Agency","title":"CI Test Boundary","url":"https://example.test/geom","publication_date":"2026-01-01","document_type":"gis_layer","supersedes":null,"page_reference":null}'::jsonb
);


-- -----------------------------------------------------------------------------
-- 4. Regulation-stack tables — minimal mirrors of the real DDL, only the columns
--    the E09 get_regulations live tests read.  DELIBERATELY NOT the full schema.
--    opens/closes are `date` (matching the real DDL) so the handler's ::text cast
--    is exercised; postgres.js returns bare `date` columns as JS Date objects, so
--    the seasons query casts them to text for the string-typed response envelope.
-- -----------------------------------------------------------------------------
CREATE TABLE regulation_record (
  state             text    NOT NULL,
  jurisdiction_code text    NOT NULL,
  species_group     text    NOT NULL,
  license_year      integer NOT NULL,
  schema_version    integer NOT NULL,
  confidence        text    NOT NULL,
  source            jsonb   NOT NULL,
  PRIMARY KEY (state, jurisdiction_code, species_group, license_year)
);

CREATE TABLE season_definition (
  id                text  PRIMARY KEY,
  name              text  NOT NULL,
  opens             date  NOT NULL,
  closes            date  NOT NULL,
  weapon_type       text,
  residency         text,
  closure_predicate jsonb,
  verbatim_rule     text  NOT NULL,
  page_reference    text,
  source            jsonb NOT NULL
);

CREATE TABLE regulation_season (
  state                text    NOT NULL,
  jurisdiction_code    text    NOT NULL,
  species_group        text    NOT NULL,
  license_year         integer NOT NULL,
  season_definition_id text    NOT NULL,
  PRIMARY KEY (state, jurisdiction_code, species_group, license_year, season_definition_id)
);

CREATE TABLE jurisdiction_binding (
  id                                  text    PRIMARY KEY,
  regulation_record_state             text    NOT NULL,
  regulation_record_jurisdiction_code text    NOT NULL,
  regulation_record_species_group     text    NOT NULL,
  regulation_record_license_year      integer NOT NULL,
  geometry_id                         text    NOT NULL,
  role                                text    NOT NULL
);


-- -----------------------------------------------------------------------------
-- 5. Seed a full resolution chain for MT-TEST-geom:
--      geometry (primary_unit binding) → regulation_record (elk, 2026)
--      → regulation_season → season_definition (one General elk window).
--    This makes:
--      • the happy-path test resolve a jurisdiction with >=1 season (coverage full);
--      • the partial-coverage test resolve the jurisdiction for an out-of-dataset
--        species with 0 seasons (coverage partial, cited by the geometry source).
-- -----------------------------------------------------------------------------
INSERT INTO regulation_record (state, jurisdiction_code, species_group, license_year, schema_version, confidence, source) VALUES (
  'US-MT', 'MT-HD-TEST', 'elk', 2026, 2, 'high',
  '{"id":"mt-ci-reg-citation","agency":"CI Test Agency","title":"CI Test Regulations","url":"https://example.test/reg","publication_date":"2026-01-01","document_type":"annual_regulations","supersedes":null,"page_reference":null}'::jsonb
);

INSERT INTO season_definition (id, name, opens, closes, weapon_type, residency, closure_predicate, verbatim_rule, page_reference, source) VALUES (
  'MT-HD-TEST-elk-general-2026', 'General', DATE '2026-09-15', DATE '2026-11-30',
  'any_legal_weapon', 'both', NULL,
  'General elk season, MT-HD-TEST. Verbatim CI fixture text.', NULL,
  '{"id":"mt-ci-season-citation","agency":"CI Test Agency","title":"CI Test Regulations","url":"https://example.test/reg","publication_date":"2026-01-01","document_type":"annual_regulations","supersedes":null,"page_reference":null}'::jsonb
);

INSERT INTO regulation_season (state, jurisdiction_code, species_group, license_year, season_definition_id) VALUES (
  'US-MT', 'MT-HD-TEST', 'elk', 2026, 'MT-HD-TEST-elk-general-2026'
);

INSERT INTO jurisdiction_binding (id, regulation_record_state, regulation_record_jurisdiction_code, regulation_record_species_group, regulation_record_license_year, geometry_id, role) VALUES (
  'US-MT-MT-HD-TEST-elk-2026-primary_unit-MT-TEST-geom',
  'US-MT', 'MT-HD-TEST', 'elk', 2026, 'MT-TEST-geom', 'primary_unit'
);
