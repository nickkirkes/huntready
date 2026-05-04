# ADR-018: E03 Schema Additions — license_season, geometry.legal_description, geometry.kind='state'

**Date:** 2026-05
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** schema, ingestion

---

## Context

E03 (Montana regulation text ingestion) planning surfaced three schema gaps the existing E01 schema cannot cleanly hold:

1. **A/B asymmetric season coverage.** Montana DEA per-HD tables show A (General) and B (antlerless) licenses with different season coverage (e.g., A valid in Heritage Muzzleloader, B not). The E01 schema models A/B sharing via the `regulation_record → many license_tags` and `regulation_record → many season_definitions` link tables — `regulation_license` and `regulation_season` (per ADR-010, both verified present at `supabase/migrations/20260425000000_initial_schema.sql:231,249`). That pattern over-attributes seasons to licenses that don't cover them. M1 success-criterion-2 walkthrough (HD 262 elk: A and B both reference the appropriate seasons) silently produces wrong data without a fix.

2. **Legal-description text on geometries.** S03.5 extracts FWP-published prose boundary descriptions for HDs, CWD zones, and restricted areas. ADR-015 added `geometry.verbatim_rule` for layer-#2 REG/COMMENTS — *regulatory text* attached to a polygon. Legal-description prose is semantically distinct (it describes the *boundary*, not the *regulation*). Overloading `verbatim_rule` would conflate two categories of text, force consumers to split on a multi-source separator, and lose the queryability of "the boundary description for HD-262" as a distinct field.

3. **Statewide regulations.** Montana publishes statewide-scoped regulations — the antelope `900-20` license is the canonical case; bear ID coursework, mandatory harvest reporting, and CWD sampling may also surface. These need `regulation_record` rows with `jurisdiction_code='MT-STATEWIDE-...'` per S03.6, but those regulation_records have no geometry to bind to. The E01 `geometry.kind` enum has no value for state-level boundaries.

All three are E03-load-bearing.

## Decision

**Three coordinated schema additions, applied in a single migration during S03.0 (the new schema-prep story mirroring E02's S02.0 pattern):**

1. New link table `license_season` for explicit per-license season coverage
2. New column `geometry.legal_description text` (nullable) for FWP-published boundary prose
3. Extend `geometry.kind` enum to include `'state'` for state-level boundary polygons

## Reasoning

### 1. New link table `license_season`

```sql
CREATE TABLE license_season (
  license_tag_id text NOT NULL REFERENCES license_tag(id),
  season_definition_id text NOT NULL REFERENCES season_definition(id),
  PRIMARY KEY (license_tag_id, season_definition_id)
);

CREATE INDEX license_season_season_definition_id_idx
  ON license_season (season_definition_id);
```

**Semantics:** explicit per-license season coverage. A `license_tag` covers exactly the `season_definition` rows referenced by `license_season` rows. Replaces the implicit "all license_tags attached to a regulation_record cover all its season_definitions" pattern from ADR-010.

**S03.7 ingestion logic:** for each license row in extraction artifacts, write a `license_season` row per season the license actually covers, derived from the source DEA table's column-presence indicators (an empty `–` cell in the Heritage Muzzleloader column means the license does NOT cover that season).

**Backward compatibility:** the `regulation_season` link table from E01 (verified present at `supabase/migrations/20260425000000_initial_schema.sql:231`) is unaffected — it still expresses `regulation_record → season_definition` (the right level for "what seasons exist for this HD"). `license_season` adds the per-license refinement (which is "which of those seasons does *this* license actually cover").

### 2. New column `geometry.legal_description text` (nullable)

```sql
ALTER TABLE geometry ADD COLUMN legal_description text NULL;
```

**Nullable.** Many `geometry` rows have no legal-description prose (e.g., portions, BMUs, statewide). Empty `legal_description` is `NULL`, not empty string — same convention as `verbatim_rule` per ADR-015.

**Semantics:** FWP-published prose describing the *boundary* of this geometry. Distinct from `verbatim_rule`, which holds *regulation text* per polygon (per ADR-015). Both fields are independently populated; both are queryable; neither depends on the other.

**Why both `legal_description` AND the MultiPolygon `geom` are needed:** The `geom` MultiPolygon is the source-of-record for **spatial queries** (PostGIS `ST_Covers`, `ST_Intersects`, etc.) and is the canonical machine-readable boundary. The `legal_description` text is the source-of-record for the **human-readable description** of the same boundary as published by FWP. They serve different consumers — spatial queries vs response composition for a user reading "what's the boundary of HD 262?". Neither is derivable from the other; both are needed.

**S03.5 + S03.6 ingestion logic:** S03.5 extracts the prose; S03.6 writes it to `geometry.legal_description` for the matched geometry rows. No separator pattern, no overloading of `verbatim_rule`.

### 3. Extend `geometry.kind` enum to include `'state'`

```sql
ALTER TABLE geometry DROP CONSTRAINT geometry_kind_check;
ALTER TABLE geometry ADD CONSTRAINT geometry_kind_check
  CHECK (kind IN (
    'hunting_district','gmu','portion','bmu','cwd_zone',
    'restricted_area','bma','state','other'
  ));
```

**Semantics:** state-level boundary polygon. Used as the binding target for statewide regulation_records.

**S03.0 deliverable:** writes one `geometry` row for Montana:

- `id='MT-STATEWIDE-geom'`
- `kind='state'`
- `state='US-MT'`
- `geom`: Montana state boundary as a MultiPolygon
- **`license_year=NULL` (year-invariant).** Per-HD geometries are pinned to `license_year` because HD definitions can change between years; state boundaries do not. The schema already permits NULL on `geometry.license_year` (verified in E01 DDL at `supabase/migrations/20260425000000_initial_schema.sql:175` — `license_year integer` with comment `nullable — null = year-invariant geometries`), so no schema change is needed to support this.

**Source priority for the Montana state boundary:**

1. **First preference:** an FWP-published state boundary, if one exists as an ArcGIS layer or downloadable GeoJSON. Pin to that source via `SourceCitation` with `document_type='gis_layer'` per ADR-014.
2. **Fallback:** US Census TIGER 2020 state shapefile (https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html). Pin to the specific file URL + SHA in S03.0 implementation.

The S03.0 implementer picks during execution, documents the chosen source in the load script and in the calibration findings artifact for that story, and pins the SHA. The MultiPolygon goes through `shapely.make_valid()` like every other geometry per ADR-012.

**S03.10 binding logic:** every statewide regulation_record (e.g., `MT-STATEWIDE-antelope`) gets a `jurisdiction_binding` to `MT-STATEWIDE-geom` with `role='primary_unit'`.

**Statewide regulation_records to be written during S03.6:**

- `MT-STATEWIDE-antelope` — anchor for the `900-20` license. **Confirmed.**
- Possibly per-species statewide records for bear (Bear ID coursework anchor) and deer/elk (CWD sampling anchor). **The S03.6 implementer surfaces candidates in the S03.6 calibration findings artifact for review; the implementer does NOT add statewide regulation_records autonomously.** Each candidate is a flag-and-surface event, not an add-and-proceed event. Any new `jurisdiction_binding.role` value beyond `primary_unit` for a statewide regulation_record requires an ADR amendment to ADR-018.

### Three-place sync (per ADR-006)

All three additions propagate:

- **DDL:** new migration in `supabase/migrations/<timestamp>_e03_schema_additions.sql`
- **Pydantic** (`ingestion/ingestion/lib/schema.py`): new `LicenseSeason` BaseModel; `Geometry.legal_description: str | None`; `Geometry.kind` Literal extended with `"state"`
- **TypeScript** (`mcp-server/src/types/schema.ts`): matching changes
- **architecture.md** §"Schema types": updated with `LicenseSeason`, `Geometry.legal_description`, `kind='state'`

**The architecture.md update is part of S03.0's deliverable, pre-approved by this ADR's sign-off.** No separate human-approval gate is required for that update — the ADR sign-off authorizes the canonical-types-doc update as a coupled deliverable. S03.0's PR includes the architecture.md change in the same commit as the migration, the Pydantic update, and the TypeScript update, satisfying ADR-006's three-place-sync invariant.

## Alternatives considered

- **(2 alt) Amend ADR-015 to allow N-source separator on `verbatim_rule`** for legal-description text. Rejected: conflates regulatory text with boundary description; forces consumers to split on multiple separators; loses queryability of legal description as its own field; sets a precedent for "we'll just add another separator" that erodes ADR-015's byte-frozen contract.
- **(3 alt) Multi-bind statewide regulation_records to all per-HD geometries** with `role='other_overlay'`. Rejected: noisy (60+ binding rows for one statewide regulation_record); semantically misleading (the statewide rule isn't an "overlay" on each HD, it's a different category); makes the statewide regulation_record's binding picture indistinguishable from a per-HD record's.
- **(1 alt) Add a `weapon_type[]` array to `season_definition` instead of a `license_season` link table.** Rejected: doesn't solve the asymmetric-coverage problem (the issue isn't weapon variety per season, it's whether a given license is valid in a given season at all).

## Consequences

- S03.0 becomes a real story (mirrors E02's S02.0): writes the migration, the Pydantic + TypeScript updates, the architecture.md update, and one `geometry` row (Montana state boundary). No regulation data loaded.
- S03.7 ingestion is structurally important: per-license season coverage is now first-class. The implementation reads the DEA column-presence indicators per license row and writes `license_season` rows accordingly. Test coverage validates A/B asymmetry survives.
- S03.10 knows how to bind statewide regulation_records: every statewide jurisdiction_code's regulation_record gets a binding to `MT-STATEWIDE-geom` with `role='primary_unit'`.
- Future state adapters (M2 Colorado) inherit the same patterns: `license_season` for any per-license season selection, `geometry.legal_description` for any FWP-style prose boundaries, `geometry.kind='state'` for any statewide regulations.
- `regulation_season` link table from E01 stays in place; consumers querying "what seasons exist for HD-262 elk" still join through `regulation_record → regulation_season → season_definition`. Consumers querying "what seasons does THIS license cover" join through `license_tag → license_season → season_definition`. Both joins coexist.
