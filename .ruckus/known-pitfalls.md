# Known Pitfalls

Project: huntready
Domain: Regulatory data platform for licensed hunting in the US.

Pitfalls discovered through development. Updated by `/ruckus:build` and `/ruckus:fix` wrap-up stages.

---

## Data & State

### `verbatim_rule` columns silently accept `""`

Both `JurisdictionBinding.verbatim_rule` and `Geometry.verbatim_rule` are nullable `text` with no SQL CHECK constraint and no Pydantic `@field_validator` to reject empty strings. An ingestion adapter that writes `verbatim_rule=""` will succeed silently, and downstream code using `if x.verbatim_rule:` cannot distinguish "no rule text in source" (intended `NULL`) from "empty rule text in source" (`""`).

State adapters guard at the call site: `_extract_verbatim_rule(props)` in `load_hds.py` and `load_portions.py` returns `None` for missing/empty/whitespace-only `REG`. The schema itself remains permissive.

**Recommended cleanup** (cross-cutting, deferred): add a Pydantic validator that raises if `v is not None and not v.strip()` on both columns. Optionally add `CHECK (verbatim_rule IS NULL OR length(verbatim_rule) > 0)` if a non-Python writer ever appears.

Surfaced by silent-failure-hunter on 2026-04-28.

## Integration — ArcGIS

### Pagination terminator: empty page AND not-exceeded — never page-size

The `fetch_features` page loop in `ingestion/ingestion/lib/arcgis.py` terminates only when `exceededTransferLimit` is `False`/absent AND the page is empty. The naive-looking optimization "stop when fewer-than-page-size returned" silently drops data on layers that report `exceededTransferLimit=True` on the last full page (terminating one page early). The unit test `test_exact_n_times_max_record_count_boundary` exists to lock this in — do not delete or weaken it during refactors that "look like" they'd save a fetch.

Surfaced by epic E02 spec (line 116); validated by S02.1 implementation 2026-04-29.

### `where` clauses: read `metadata.object_id_field`, never hardcode `OBJECTID`

The epic E02 spec example (line 110) shows `where=OBJECTID>=0`, but ArcGIS layers may use `FID`, `OBJECTID_1`, or other names — the actual name is in `metadata.object_id_field`. State adapters that build their own ArcGIS queries (rather than going through `fetch_features`) must use `f"{metadata.object_id_field}>=0"`. A hardcoded `OBJECTID>=0` against a layer whose OID is named `FID` will return a server-side 4xx, or — pathologically — return a different count than the page query, producing a confusing count-mismatch error. The shared library handles this correctly.

Surfaced by `cubic review` + `silent-failure-hunter` on 2026-04-29.

### Layer metadata may omit top-level `objectIdField`

Some ArcGIS MapServers (observed: MT FWP `admbnd/huntingDistricts` layers #3, #10, #11) return layer metadata without the `objectIdField` key at the top level even though the OID column is present in the `fields[]` array as a `type == "esriFieldTypeOID"` entry. `fetch_layer_metadata` falls back to scanning `fields[]` and prefers the canonical `OBJECTID` name when multiple OID-typed fields exist (joined layers, schema-repaired layers with `OBJECTID_1`, etc.); a WARNING is emitted on the fallback so operators can audit. A code path that reads `data["objectIdField"]` directly without the fallback will `KeyError` and halt ingestion on these otherwise-valid servers.

Surfaced by S02.2 live load on 2026-04-30.

### `shapely.make_valid` may produce `GeometryCollection [Polygon, LineString]`

Real-world ArcGIS Polygon layers (observed: MT FWP antelope HD 556, OBJECTID 385) carry self-intersecting source polygons. `shapely.make_valid` repairs them by emitting a `GeometryCollection` containing one `Polygon` (the real geometry) and a `LineString` (the zero-area edge that pokes out at the self-intersection vertex). `geojson_to_multipolygon_wkt` recovers the polygonal part when its area equals the input's area within `math.isclose(rel_tol=1e-6, abs_tol=1e-12)` and emits a WARNING with OBJECTID + attributes; lossy cases (overlapping polygons in a GC where `unary_union.area < sum_of_areas`) still raise.

Raising on every GC would block valid loads. Silently filtering would lose data when the GC carries real polygonal area beyond the unioned coverage. The area-preservation rule preserves ADR-008's "fail loud" discipline for genuinely lossy cases while letting topological-artifact cases through with audit trail. Test coverage in `tests/test_arcgis.py::TestGeojsonToMultipolygonWkt` locks both branches in; do not weaken `abs_tol` to `0.0` (rejects valid tiny polygons due to float noise).

Surfaced by S02.2 live load on 2026-04-30.

## Integration — Supabase / PostGIS

### `geom::geometry` direct cast not enabled

Supabase's bundled PostGIS does not allow direct `geom::geometry` casts on `geography` columns — `SELECT ... FROM geometry WHERE NOT ST_IsValid(geom::geometry)` returns `cannot cast type geography to geometry`. The S02.6/S02.7 epic verification SQL uses this cast pattern (and so do the docs/runbook examples). Operators running those queries against a Supabase project will hit the error.

**Workaround:** round-trip via WKT — `ST_GeomFromText(ST_AsText(geom), 4326)`. This is what `ingestion/states/montana/README.md` documents for post-load AC verification.

```sql
-- Validity check (was: WHERE NOT ST_IsValid(geom::geometry))
SELECT id FROM geometry
WHERE NOT ST_IsValid(ST_GeomFromText(ST_AsText(geom), 4326));

-- Multi-part check (was: ST_NumGeometries(geom::geometry))
SELECT id, ST_NumGeometries(ST_GeomFromText(ST_AsText(geom), 4326)) AS parts
FROM geometry WHERE kind='hunting_district' ORDER BY parts DESC LIMIT 5;
```

The cast IS standard PostGIS behavior on most installs; the absence on Supabase is a cluster-config quirk, not a missing extension. Confirmed: PostGIS 3.3.7 + supabase_vault 0.3.1 is the configuration where this surfaces. Worth verifying on each new Supabase project before assuming the casts work.

Surfaced by S02.2 post-load AC verification on 2026-04-30.

## Build & Deploy

### Style anchor for adding a nullable text column

When adding a nullable text column via a new migration, mirror `jurisdiction_binding.verbatim_rule` (`supabase/migrations/20260425000000_initial_schema.sql:207`) byte-for-byte:

- Type `text`, no `NOT NULL`, no default, no CHECK.
- Inline `--` comment on the same line documenting what `NULL` means semantically (e.g., `-- NULLABLE — null = no geometry-specific rule text from source attributes (REG/COMMENTS)`).
- No `COMMENT ON COLUMN` (E01 doesn't use it).
- For `ALTER TABLE` migrations, prefer `ADD COLUMN IF NOT EXISTS` — matches the `CREATE EXTENSION IF NOT EXISTS` idiom and makes the migration safely re-runnable on partially-applied environments.

The new column must also land in Pydantic (`ingestion/ingestion/lib/schema.py`) and TypeScript (`mcp-server/src/types/schema.ts`) in the same PR per ADR-006. Field ordering convention: nullable text fields go between `license_year` (or the last common field) and `source: SourceCitation`. `architecture.md` §"Schema types" must also update — it's the audit trail for type-only enum extensions that have no SQL migration (per ADR-014).

### Cubic flags `from states.montana.X import` as broken — false positive

Cubic review (1.3.2 as of 2026-04-30) flags `from states.montana.<module> import ...` in adapter scripts as a P1 import failure, claiming `states` is not on `sys.path`. This is incorrect. The `ingestion` package is editable-installed (`pip install -e .` in `ingestion/`), which puts the `ingestion/` directory on `sys.path` via the `.pth` file in `.venv/lib/.../site-packages`. Python then resolves `states.montana.X` as a namespace package starting from `ingestion/states/montana/X.py`. The same mechanism is what makes `from ingestion.lib.X import ...` work — both imports rely on the editable install.

Verification when cubic flags this: run the script directly via `ingestion/.venv/bin/python ingestion/states/montana/<script>.py --help`. If it prints argparse help, the imports resolve. The existing tests use the same pattern (`from states.montana.load_portions import ...`) — if cubic's claim were correct, the test suite would also fail to collect, and it doesn't.

Surfaced by S02.4 cubic review on 2026-04-30.

## Conventions — Ingestion adapters

### Shared predicate module when two stories partition a single source layer

When two stories must apply mutually exclusive filters over the same source layer (e.g. S02.4 ingests non-CWD rows of MT FWP layer #2 as `kind='restricted_area'`; S02.5 ingests the CWD rows of the same layer as `kind='cwd_zone'`), the discriminator predicate **must** live in a shared module that both adapters import. The naive approach — let one story write rows with one `kind`, then have the other mutate matching rows to a different `kind` — has an idempotency hole: re-running the first story reverts the kind via UPSERT.

The pattern: a module like `ingestion/states/<state>/<feature>_discriminator.py` exporting a single pure function `is_<feature>_feature(props: dict[str, Any]) -> bool`. Each adapter applies the predicate as a filter — one inverted, one not — at the point where features arrive from the source. Each row is written exactly once with the correct `kind`. Re-running either adapter is idempotent; sequence between them does not matter.

Test the predicate independently of the adapter (own pure-function test file). Test the adapter integration by stubbing the predicate in `_load_layer` tests.

Example: `ingestion/states/montana/cwd_discriminator.py` (shared by `load_restricted_areas.py` and the future `load_cwd_zones.py`).

Surfaced by S02.4 implementation on 2026-04-30.

### Single atomic commit across multi-layer adapters

Adapter `main()` functions that load multiple layers must call `conn.commit()` **once after the loop**, not inside it. Per-layer commits would leave partial state on a mid-loop failure (e.g. layer #2 written, layer #15 raises → layer #2 silently committed with no audit). The intended behavior is all-or-nothing: if any layer raises, the connection's `__exit__` rolls back the entire transaction.

The convention is brittle to "natural-looking" refactors that move the commit inside the loop for per-layer log alignment. Two defenses are required:

1. **A comment at the `conn.commit()` call** stating "single atomic commit covering BOTH/ALL layers — do not move inside the loop." Reference the rollback-on-`__exit__` mechanism so the reader understands why partial-commit is unsafe.
2. **A test asserting `conn.commit` is NOT called when a later layer raises.** Stub `_load_layer` to succeed once and raise on the second call; assert `mock_conn.commit.assert_not_called()` and that both layer attempts happened (so the test would fail under either short-circuit OR per-layer-commit refactors).

Both defenses are required because either alone allows the silent flip:

- Comment without test: a refactor edits the comment along with the code.
- Test without comment: the developer doing the refactor reads the test as "weird, must be testing something else" and rewrites it.

Example: `ingestion/states/montana/load_restricted_areas.py:main()` and the `TestMainCommitAtomicity` class in `tests/test_load_restricted_areas.py`.

Surfaced by silent-failure-hunter on S02.4 review on 2026-04-30.
