-- =============================================================================
-- HuntReady: RLS Deny-All Migration
-- S01.3 — Row Level Security policies for all entity and link tables
-- =============================================================================
-- Structurally disables PostgREST access so that only service-role credentials
-- (which carry the bypassrls role attribute) can read or write regulation data.
-- This enforces ADR-002 (MCP server as canonical interface) at the database layer.
--
-- Three security layers per table:
--   Layer 1: ENABLE + FORCE RLS (applies even to table owner)
--   Layer 2: Deny-all policies for authenticated and anon roles
--   Layer 3: REVOKE ALL from anon and authenticated (defense-in-depth)
--
-- Tables covered (all 10, same order as S01.2):
--   Entity:  regulation_record, season_definition, license_tag, draw_spec,
--            reporting_obligation, geometry, jurisdiction_binding
--   Link:    regulation_season, regulation_license, regulation_reporting
--
-- Relevant ADRs: 002, 004
-- =============================================================================


-- -----------------------------------------------------------------------------
-- regulation_record
-- -----------------------------------------------------------------------------
ALTER TABLE regulation_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE regulation_record FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON regulation_record
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON regulation_record
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE regulation_record FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- season_definition
-- -----------------------------------------------------------------------------
ALTER TABLE season_definition ENABLE ROW LEVEL SECURITY;
ALTER TABLE season_definition FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON season_definition
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON season_definition
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE season_definition FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- license_tag
-- -----------------------------------------------------------------------------
ALTER TABLE license_tag ENABLE ROW LEVEL SECURITY;
ALTER TABLE license_tag FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON license_tag
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON license_tag
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE license_tag FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- draw_spec
-- -----------------------------------------------------------------------------
ALTER TABLE draw_spec ENABLE ROW LEVEL SECURITY;
ALTER TABLE draw_spec FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON draw_spec
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON draw_spec
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE draw_spec FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- reporting_obligation
-- -----------------------------------------------------------------------------
ALTER TABLE reporting_obligation ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting_obligation FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON reporting_obligation
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON reporting_obligation
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE reporting_obligation FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- geometry
-- -----------------------------------------------------------------------------
ALTER TABLE geometry ENABLE ROW LEVEL SECURITY;
ALTER TABLE geometry FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON geometry
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON geometry
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE geometry FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- jurisdiction_binding
-- -----------------------------------------------------------------------------
ALTER TABLE jurisdiction_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE jurisdiction_binding FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON jurisdiction_binding
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON jurisdiction_binding
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE jurisdiction_binding FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- regulation_season
-- -----------------------------------------------------------------------------
ALTER TABLE regulation_season ENABLE ROW LEVEL SECURITY;
ALTER TABLE regulation_season FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON regulation_season
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON regulation_season
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE regulation_season FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- regulation_license
-- -----------------------------------------------------------------------------
ALTER TABLE regulation_license ENABLE ROW LEVEL SECURITY;
ALTER TABLE regulation_license FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON regulation_license
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON regulation_license
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE regulation_license FROM anon, authenticated;


-- -----------------------------------------------------------------------------
-- regulation_reporting
-- -----------------------------------------------------------------------------
ALTER TABLE regulation_reporting ENABLE ROW LEVEL SECURITY;
ALTER TABLE regulation_reporting FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated" ON regulation_reporting
  FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "Deny all access for anon" ON regulation_reporting
  FOR ALL TO anon USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE regulation_reporting FROM anon, authenticated;
