-- =============================================================================
-- HuntReady: Add geometry.verbatim_rule
-- S02.0 — Schema preparation for E02 Montana Geometry Ingestion
-- =============================================================================
-- Adds a nullable `verbatim_rule` column to the `geometry` table so polygon
-- source attributes carrying verbatim regulatory text (e.g., MT FWP layer #2
-- `COMMENTS`/`REG`, layer #11 `REG`) can be stored verbatim — never paraphrased
-- or stashed in `source` jsonb.
--
-- The column is NULLABLE: many geometries have no rule text in source attributes
-- at all (e.g., a hunting district polygon with no per-unit `REG` value).
--
-- The S02.4 REG+COMMENTS combination contract (HuntReady-introduced separator
-- `\n\n--- COMMENTS ---\n\n`) lives in the Montana adapter, not in this column.
-- This migration adds the column only.
--
-- Relevant ADRs: 006 (three-place sync), 008 (verbatim text), 015 (this column).
-- =============================================================================

ALTER TABLE geometry
    ADD COLUMN IF NOT EXISTS verbatim_rule text;    -- NULLABLE — null = no geometry-specific rule text from source attributes (REG/COMMENTS)
