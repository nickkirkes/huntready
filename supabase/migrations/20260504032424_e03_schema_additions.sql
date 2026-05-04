-- =============================================================================
-- HuntReady: E03 Schema Additions
-- S03.0 — Schema preparation for E03 Montana Regulation Text Ingestion
-- =============================================================================
-- Adds three coordinated schema additions required by E03 (regulation text
-- ingestion). All three ship atomically in a single migration, mirroring the
-- S02.0 pattern (20260428000000_geometry_verbatim_rule.sql).
--
-- 1. New link table `license_season` — explicit per-license season coverage.
--    Distinct from `regulation_season` (per-regulation coverage); both coexist.
-- 2. New column `geometry.legal_description text` (nullable) — FWP-published
--    prose describing the *boundary* of this geometry. Semantically distinct
--    from `verbatim_rule` (regulatory text per polygon, per ADR-015).
-- 3. Extend `geometry.kind` CHECK constraint to include `'state'` for
--    state-level boundary polygons (e.g., MT-STATEWIDE-geom).
--
-- Relevant ADRs: 006 (three-place sync), 010 (decomposed entities), 018 (this migration).
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. license_season (link table)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- license_season
-- Links license_tag → season_definition (per-license season coverage).
-- This is *per-license* season coverage — distinct from `regulation_season`
-- which links regulation_record → season_definition (per-regulation coverage).
-- Both link tables coexist; each answers a different join question:
--   regulation_season: "what seasons exist for this regulation_record?"
--   license_season:    "which of those seasons does THIS license actually cover?"
-- Per ADR-018 §1 and §"Consequences".
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS license_season (
    license_tag_id          text    NOT NULL
        REFERENCES license_tag(id),
    season_definition_id    text    NOT NULL
        REFERENCES season_definition(id),

    PRIMARY KEY (license_tag_id, season_definition_id)
);

CREATE INDEX IF NOT EXISTS license_season_season_definition_id_idx
    ON license_season (season_definition_id);

-- =============================================================================
-- 2. geometry.legal_description (nullable text column)
-- =============================================================================

ALTER TABLE geometry
    ADD COLUMN IF NOT EXISTS legal_description text;    -- NULLABLE — null = no FWP-published prose boundary description for this geometry

-- =============================================================================
-- 3. geometry.kind CHECK constraint extension (add 'state')
-- =============================================================================

-- Drop the auto-generated column-level CHECK (name: geometry_kind_check,
-- per Postgres convention <table>_<column>_check for inline column CHECKs
-- with no explicit name — confirmed at 20260425000000_initial_schema.sql:168-172).
ALTER TABLE geometry DROP CONSTRAINT geometry_kind_check;
ALTER TABLE geometry ADD CONSTRAINT geometry_kind_check
    CHECK (kind IN (
        'hunting_district', 'gmu', 'portion', 'bmu',
        'cwd_zone', 'restricted_area', 'bma', 'state', 'other'
    ));

COMMIT;
