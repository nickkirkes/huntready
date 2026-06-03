-- =============================================================================
-- HuntReady: jurisdiction_binding role no_hunt_zone
-- S05.3.5 — ADR-021 implementation
-- =============================================================================
-- Two coordinated operations ship atomically in a single migration, mirroring
-- the S03.0 pattern (20260504032424_e03_schema_additions.sql):
--
-- 1. Extend the `jurisdiction_binding.role` CHECK constraint from 7 values to
--    8 by adding 'no_hunt_zone' (categorical hunt-closure overlays — NPs/NMs,
--    DOD installations — distinct from weapon/season `other_overlay` cases).
-- 2. Reclassify MT V1's 3 existing no-hunt-zone bindings from 'other_overlay'
--    to 'no_hunt_zone' so the V1 disposition aligns with the new enum.
--
-- Relevant ADRs: 006 (three-place sync), 010 (enum-not-flag + role-as-
-- relationship), 021 (this migration).
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. jurisdiction_binding.role CHECK constraint extension (add 'no_hunt_zone')
-- =============================================================================

-- Drop the auto-generated column-level CHECK (name: jurisdiction_binding_role_check,
-- per Postgres convention <table>_<column>_check for inline column CHECKs with no
-- explicit name — the current 7-value constraint is at
-- 20260425000000_initial_schema.sql:201-206).
ALTER TABLE jurisdiction_binding DROP CONSTRAINT jurisdiction_binding_role_check;
ALTER TABLE jurisdiction_binding ADD CONSTRAINT jurisdiction_binding_role_check
    CHECK (role IN (
        'primary_unit', 'portion', 'restricted_area',
        'cwd_management_zone', 'bear_management_unit',
        'block_management_area', 'other_overlay', 'no_hunt_zone'
    ));

-- =============================================================================
-- 2. MT V1 no-hunt-zone reclassification (3 rows)
-- =============================================================================

-- Keys on `geometry_id` (NOT the binding `id`): each of the 3 federal no-hunt
-- zones fans out to multiple binding rows (one per nearby HD × regulation_record),
-- all sharing the same geometry_id. `WHERE geometry_id IN (...)` targets every
-- row for each zone without enumerating individual binding ids. The 3 ids are
-- grep-verified from ingestion/states/montana/build_overlay_fixture.py:236-242
-- (EXPECTED_RA_ORPHAN_IDS). Note: the binding `id` column still encodes
-- 'other_overlay' as a substring after this UPDATE — that is an accepted V1
-- artifact (id is immutable; updating it would be out of scope and unnecessary).
UPDATE jurisdiction_binding
    SET role = 'no_hunt_zone'
    WHERE geometry_id IN (
        'MT-restricted-bigame-glacier-national-park-geom',
        'MT-restricted-bigame-sun-river-game-preserve-geom',
        'MT-restricted-bigame-yellowstone-national-park-geom'
    );

COMMIT;
