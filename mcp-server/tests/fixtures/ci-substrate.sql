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
-- -----------------------------------------------------------------------------
INSERT INTO geometry (id, name, kind, geom, state, source) VALUES (
  'MT-TEST-geom', 'MT Test', 'hunting_district',
  extensions.ST_GeogFromText('SRID=4326;MULTIPOLYGON(((-114 47,-113 47,-113 48,-114 48,-114 47)))'),
  'US-MT', '{}'::jsonb
);
