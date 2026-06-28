-- =============================================================================
-- HuntReady: SELECT-Only Role Provisioning
-- supabase/grant-readonly-role.sql
-- =============================================================================
-- OPERATOR-APPLIED DB PROVISIONING — NOT A MIGRATION.
-- This file lives OUTSIDE supabase/migrations/ and is applied by hand to each
-- environment and by CI against a test substrate:
--
--   supabase db query --db-url "$DATABASE_URL" < supabase/grant-readonly-role.sql
--
-- The SELECT-only-role DSN is held in Workers Secrets (Cloudflare), never in
-- source.  The role is created WITHOUT a password here; the operator/CI sets
-- the password out-of-band:
--
--   ALTER ROLE huntready_readonly PASSWORD '<generated>';
--
-- Apply this script AFTER all migrations have been applied (the tables must
-- exist for GRANT SELECT ON ALL TABLES to cover them).
--
-- Idempotent: safe to re-run on the same environment.  The RLS ALLOW-SELECT
-- policy block skips tables that already have the policy.
--
-- Table-set-agnostic: the same script applies cleanly on the full dev Supabase
-- project (all 10 app tables, every one FORCE ROW LEVEL SECURITY) AND on a
-- minimal CI substrate where only the `geometry` table exists.
--
-- Relevant ADRs: 002 (MCP server as canonical interface), 023 (remote
-- authenticated MCP server posture), 024 (edge-runtime Postgres access).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Create the role if it does not already exist (LOGIN, no password here).
-- -----------------------------------------------------------------------------
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'huntready_readonly') THEN
    CREATE ROLE huntready_readonly LOGIN;
  END IF;
END $$;


-- -----------------------------------------------------------------------------
-- 2. Grant CONNECT on the current database.
--    A literal DB name would be environment-specific; current_database() is
--    portable across dev / CI / prod.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  EXECUTE format(
    'GRANT CONNECT ON DATABASE %I TO huntready_readonly',
    current_database()
  );
END $$;


-- -----------------------------------------------------------------------------
-- 3. Schema-level USAGE grants.
--    public  — all app tables live here.
--    extensions — PostGIS is installed with SCHEMA extensions in this project
--                 (see migrations/20260425000000_initial_schema.sql L24).
--                 USAGE is required so the role can resolve ST_* function calls
--                 (e.g. extensions.ST_DWithin) made through the serving stack.
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public     TO huntready_readonly;
GRANT USAGE ON SCHEMA extensions TO huntready_readonly;


-- -----------------------------------------------------------------------------
-- 4. SELECT on all tables that currently exist in the public schema.
--    Table-set-agnostic: grants whatever tables are present at apply time.
--    CRITICAL: SELECT ONLY — no INSERT, UPDATE, DELETE anywhere in this file.
-- -----------------------------------------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA public TO huntready_readonly;


-- -----------------------------------------------------------------------------
-- 5. Default privileges for FUTURE tables.
--
--    ALTER DEFAULT PRIVILEGES is ROLE-SCOPED: it only affects tables created by
--    the named role.  A bare statement (no FOR ROLE) covers only tables created
--    by whoever applies THIS script — so if a later migration creates tables as
--    a different owner, huntready_readonly would silently lack SELECT on them.
--    To keep the coverage durable, set the default for every DDL-owner role that
--    (a) exists in this environment and (b) the applying role is a member of
--    (the membership check avoids "permission denied" on roles we can't alter):
--    the current role plus the common Supabase migration owners.
--
--    Belt-and-suspenders: this whole script is idempotent and re-grants SELECT
--    ON ALL TABLES (section 4), so re-running it after any migration also closes
--    the gap for any creating role not covered below.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  ddl_owner text;
BEGIN
  FOR ddl_owner IN
    SELECT rolname
      FROM pg_roles
     WHERE rolname IN (current_user, 'postgres', 'supabase_admin')
       AND pg_has_role(current_user, rolname, 'MEMBER')
  LOOP
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public'
      ' GRANT SELECT ON TABLES TO huntready_readonly',
      ddl_owner
    );
  END LOOP;
END $$;


-- -----------------------------------------------------------------------------
-- 6. RLS ALLOW-SELECT policies.
--
--    Every app table has FORCE ROW LEVEL SECURITY (see
--    migrations/20260425000001_rls_deny_all.sql).  The deny-all policies are
--    scoped TO anon, authenticated — huntready_readonly is neither, so without
--    explicit ALLOW policies the role would be blocked by FORCE RLS even though
--    it holds SELECT privilege.
--
--    This block loops over all tables in the public schema and creates a
--    FOR SELECT TO huntready_readonly USING (true) policy on each, skipping
--    tables that already have it (idempotent).
--
--    On the CI substrate (RLS not forced), the policy is created but inert —
--    harmless.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  t record;
BEGIN
  FOR t IN
    SELECT tablename
      FROM pg_tables
     WHERE schemaname = 'public'
  LOOP
    IF NOT EXISTS (
      SELECT FROM pg_policies
       WHERE schemaname = 'public'
         AND tablename  = t.tablename
         AND policyname = 'huntready_readonly_select'
    ) THEN
      EXECUTE format(
        'CREATE POLICY huntready_readonly_select ON public.%I'
        ' FOR SELECT TO huntready_readonly USING (true)',
        t.tablename
      );
    END IF;
  END LOOP;
END $$;
