# Known Pitfalls

Project: huntready
Domain: Regulatory data platform for licensed hunting in the US.

Pitfalls discovered through development. Updated by `/ruckus:build` and `/ruckus:fix` wrap-up stages.

---

## Domain-Specific

<!-- Pitfalls related to the project's domain logic -->

## Data & State

<!-- Pitfalls related to data handling, state management, persistence -->

### `verbatim_rule` columns silently accept `""`

Both `JurisdictionBinding.verbatim_rule` and `Geometry.verbatim_rule` are nullable `text` with no SQL CHECK constraint and no Pydantic `@field_validator` to reject empty strings. An ingestion adapter that writes `verbatim_rule=""` will succeed silently, and downstream code using `if x.verbatim_rule:` cannot distinguish "no rule text in source" (intended `NULL`) from "empty rule text in source" (`""`).

**Why deferred:** Aligning the two columns is a cross-cutting fix (touches both E01 schema and E02 adapter writes); was out of scope for S02.0. Surfaced by silent-failure-hunter on 2026-04-28.

**Recommended cleanup when this becomes a real risk:** add a Pydantic validator that raises if `v is not None and not v.strip()` on both `Geometry.verbatim_rule` and `JurisdictionBinding.verbatim_rule`. Optionally add SQL `CHECK (verbatim_rule IS NULL OR length(verbatim_rule) > 0)` if a non-Python writer ever appears (none today; service-role bypass is a general risk, not specific to this column).

## Integration

<!-- Pitfalls related to APIs, third-party services, cross-system communication -->

### ArcGIS pagination terminator: must be empty page AND not-exceeded — never page-size

The `fetch_features` page loop in `ingestion/ingestion/lib/arcgis.py` terminates only when `exceededTransferLimit` is `False`/absent AND the page is empty. The naive-looking optimization "stop when fewer-than-page-size returned" silently drops the last batch on exact-N×maxRecordCount boundaries (e.g., a 4-feature layer with `maxRecordCount=2` returns 2 full pages with `exceededTransferLimit=True`, then a third empty page with `exceededTransferLimit=False`). Skipping the third fetch loses no data on that example, but on a layer that returns N×pageSize features but reports `exceededTransferLimit=True` on the last full page, you'd terminate one page early and silently miss data.

**Why this is fragile:** the rule looks like a bug ("why fetch one more empty page?") and is exactly the kind of thing a refactor optimization will re-introduce. The unit test `test_exact_n_times_max_record_count_boundary` exists to lock this in — do not delete or weaken it.

Surfaced by epic E02 spec (line 116) and validated by S02.1 implementation 2026-04-29.

### `where` clauses must use `metadata.object_id_field`, not hardcoded `OBJECTID`

The epic E02 spec example (line 110) shows `where=OBJECTID>=0`, but ArcGIS layers may use `FID`, `OBJECTID_1`, or other names for the OID column — the actual name is in the layer descriptor's `objectIdField`. State adapters that build their own ArcGIS queries (rather than going through `fetch_features`) MUST read `metadata.object_id_field` and use `f"{metadata.object_id_field}>=0"`.

**Why this matters:** a hardcoded `OBJECTID>=0` against a layer whose OID is named `FID` will either return a server-side 4xx (visible failure) or — in pathological cases where both fields exist as different columns — return a different count than the page query would, producing a confusing count-mismatch error. The shared library handles this correctly; future state adapters that bypass it must too.

Surfaced by `cubic review` and `silent-failure-hunter` on 2026-04-29.

### ArcGIS layer metadata may omit top-level `objectIdField`

Some ArcGIS MapServers (observed: MT FWP `admbnd/huntingDistricts` layers #3, #10, #11) return layer metadata without the `objectIdField` key at the top level even though the OID column IS present in the `fields[]` array as an entry with `type == "esriFieldTypeOID"`. `fetch_layer_metadata` in `ingestion/ingestion/lib/arcgis.py` falls back to scanning `fields[]` and prefers the canonical `OBJECTID` name when multiple OID-typed fields exist (joined layers, schema-repaired layers with `OBJECTID_1`, etc.); a WARNING is emitted on the fallback so operators can audit.

**Why this matters:** a code path that reads `data["objectIdField"]` directly (without the fallback) will raise `KeyError` and halt ingestion on these otherwise-valid servers. State adapters that go through `fetch_features` are unaffected (the library handles it); custom query builders must use `metadata.object_id_field` after letting `fetch_layer_metadata` resolve it.

Surfaced by S02.2 live load on 2026-04-30.

### `geom::geometry` direct cast not enabled on Supabase's PostGIS install

Supabase's bundled PostGIS does not allow direct `geom::geometry` casts on `geography` columns — `SELECT ... FROM geometry WHERE NOT ST_IsValid(geom::geometry)` returns `cannot cast type geography to geometry`. The S02.6/S02.7 epic verification SQL uses this cast pattern (and so do the docs/runbook examples). Operators running those queries against a Supabase project will hit the error.

**Workaround:** round-trip the value via WKT — `ST_GeomFromText(ST_AsText(geom), 4326)`. This is what `ingestion/states/montana/README.md` documents for post-load AC verification.

```sql
-- Validity check (was: WHERE NOT ST_IsValid(geom::geometry))
SELECT id FROM geometry
WHERE NOT ST_IsValid(ST_GeomFromText(ST_AsText(geom), 4326));

-- Multi-part check (was: ST_NumGeometries(geom::geometry))
SELECT id, ST_NumGeometries(ST_GeomFromText(ST_AsText(geom), 4326)) AS parts
FROM geometry WHERE kind='hunting_district' ORDER BY parts DESC LIMIT 5;
```

**Why this matters:** the cast IS standard PostGIS behavior on most installs; the absence on Supabase is a cluster-config quirk, not a missing extension. Confirmed: PostGIS 3.3.7 + supabase_vault 0.3.1 is the configuration where this surfaces. Worth verifying on each new Supabase project before assuming the casts work.

Surfaced by S02.2 post-load AC verification on 2026-04-30.

### `shapely.make_valid` may produce `GeometryCollection [Polygon, LineString]` for self-intersecting source polygons

Real-world ArcGIS Polygon layers (observed: MT FWP antelope HD 556, OBJECTID 385) carry self-intersecting source polygons. `shapely.make_valid` repairs them by emitting a `GeometryCollection` containing one `Polygon` (the real geometry) and a `LineString` (the zero-area edge that pokes out at the self-intersection vertex). `geojson_to_multipolygon_wkt` recovers the polygonal part when its area equals the input's area within `math.isclose(rel_tol=1e-6, abs_tol=1e-12)` and emits a WARNING with OBJECTID + attributes; lossy cases (overlapping polygons in a GC where `unary_union.area < sum_of_areas`) still raise.

**Why this matters:** raising on every GC would block valid loads. Silently filtering would lose data when the GC carries real polygonal area beyond the unioned coverage. The area-preservation rule preserves ADR-008's "fail loud" discipline for genuinely lossy cases while letting topological-artifact cases through with audit trail. Test coverage in `tests/test_arcgis.py::TestGeojsonToMultipolygonWkt` locks both branches in; do not weaken `abs_tol` to `0.0` (rejects valid tiny polygons due to float noise).

Surfaced by S02.2 live load on 2026-04-30.

## Build & Deploy

<!-- Pitfalls related to build process, CI/CD, deployment -->

### Style anchor for adding a nullable text column

When adding a nullable text column via a new migration, mirror `jurisdiction_binding.verbatim_rule` (`supabase/migrations/20260425000000_initial_schema.sql:207`) byte-for-byte:

- Type `text`, no `NOT NULL`, no default, no CHECK.
- Inline `--` comment on the same line documenting what `NULL` means semantically (e.g., `-- NULLABLE — null = no geometry-specific rule text from source attributes (REG/COMMENTS)`).
- No `COMMENT ON COLUMN` (E01 doesn't use it).
- For `ALTER TABLE` migrations, prefer `ADD COLUMN IF NOT EXISTS` — matches the `CREATE EXTENSION IF NOT EXISTS` idiom and makes the migration safely re-runnable on partially-applied environments.

The new column must also land in Pydantic (`ingestion/ingestion/lib/schema.py`) and TypeScript (`mcp-server/src/types/schema.ts`) in the same PR per ADR-006. Field ordering convention: nullable text fields go between `license_year` (or the last common field) and `source: SourceCitation`. Architecture.md §"Schema types" must also update — it's the audit trail for type-only enum extensions that have no SQL migration (per ADR-014).

## Testing

<!-- Pitfalls related to test reliability, test data, flaky tests -->
