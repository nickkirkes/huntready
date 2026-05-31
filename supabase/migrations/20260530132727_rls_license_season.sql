-- =============================================================================
-- HuntReady: license_season RLS Deny-All (M1 carry-forward)
-- S04.1 — Row Level Security policies for the license_season link table
-- =============================================================================
-- license_season was added by 20260504032424_e03_schema_additions.sql (ADR-018)
-- after the base RLS deny-all migration (20260425000001_rls_deny_all.sql).
-- The base migration uses a flat per-table enumeration that does not auto-extend
-- to subsequently-added tables, leaving license_season with 14 privilege leaks
-- (every SELECT/INSERT/UPDATE/DELETE/REFERENCES/TRIGGER/TRUNCATE x {anon,
-- authenticated}) and zero RLS policies. M1 UAT 2026-05-28 confirmed the gap
-- (criterion #7 FAIL). This migration closes it.
--
-- Three security layers (matches every block in 20260425000001_rls_deny_all.sql):
--   Layer 1: ENABLE + FORCE RLS (applies even to table owner)
--   Layer 2: Deny-all policies for authenticated and anon roles
--   Layer 3: REVOKE ALL from anon and authenticated (defense-in-depth)
--
-- Style note: table references use the qualified `public.license_season` form
-- throughout. The base 20260425000001_rls_deny_all.sql uses unqualified names.
-- Both forms are functionally equivalent under the default search_path; the
-- qualified form here matches the literal-string ACs in the E04 S04.1 spec.
--
-- Relevant ADRs: 002, 004, 018
-- =============================================================================


-- -----------------------------------------------------------------------------
-- license_season
-- -----------------------------------------------------------------------------
ALTER TABLE public.license_season ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.license_season FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON public.license_season
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON public.license_season
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE public.license_season FROM anon, authenticated;
