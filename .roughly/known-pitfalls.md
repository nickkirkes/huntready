# Known Pitfalls

Project: huntready
Domain: Regulatory data platform for licensed hunting in the US.

Pitfalls discovered through development. Updated by `/roughly:build` and `/roughly:fix` wrap-up stages.

---

## Data & State

### Cross-module `Literal` duplication is sometimes intentional — don't refactor it away

**Symptom:** A static-analysis tool or reviewer flags two modules that define the same `Literal[...]` set as a DRY violation and proposes importing one from the other.

**Cause:** The duplication can be deliberate when the two modules have different dependency weights. Importing the Literal from the heavier module (e.g. `schema.py` with Pydantic models and postgres dependencies) into a lighter module (e.g. `overlays.py` used as a thin type contract by a future consumer) inverts the intended dependency direction.

**Fix:** Before consolidating, check for (a) a docstring in the lighter module saying "kept manually in sync with X" — leave it alone; or (b) a comment naming a specific downstream consumer that imports the lighter module — leave it alone. If neither exists, it may be a genuine DRY violation, but verify import direction first. When the duplication is intentional, the docstring is the contract: both files must be updated whenever the Literal set changes.

Concrete example: `ingestion/ingestion/lib/overlays.py` duplicates `JurisdictionBinding.role` from `schema.py` deliberately so E03 can import only the thin overlay types without pulling in the full schema module. The docstring documents the manual-sync expectation.

Surfaced by S02.6 implementation on 2026-05-01.

### Drift-signal artifacts must write a marker for the empty case

**Symptom:** A reviewer flags that an artifact-writing code path (e.g., `_write_manifest_fixture`, an audit log writer, a fixture builder) skips the write entirely when the input is empty. Operators relying on `git diff` to spot upstream drift see no diff for an N→0 source change — silence looks identical to "no drift, source unchanged."

**Cause:** The natural code path for an empty input is to skip the artifact write ("nothing to record"), but for any artifact whose primary purpose is drift detection or reproducibility verification, that breaks the contract. The artifact must distinguish "source was empty this run" from "this run never happened."

**Fix:** When the artifact's purpose is drift/audit/reproducibility, always write — use a sentinel for the empty case:

- `features_count=0`, `layer_hash=sha256(b"").hexdigest()`, fully-keyed empty histogram (256 zero buckets), other fields populated normally.
- Add a regression test pinning the empty-input behavior so a future refactor doesn't quietly bring back the skip.

The S02.7 manifest writer at `ingestion/ingestion/lib/arcgis.py:780-805` is the canonical example.

Surfaced by S02.7 review on 2026-05-02.

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

Real-world ArcGIS Polygon layers (observed: MT FWP antelope HD 556, OBJECTID 385; USGS PAD-US 4.1 Rocky Mountain NP after 2026-06-22 republish) carry self-intersecting source polygons. `shapely.make_valid` repairs them by emitting a `GeometryCollection` containing one `MultiPolygon` (the real geometry) and a `LineString` (the zero-area artifact at the self-intersection vertex). `geojson_to_multipolygon_wkt` recovers the polygonal part when its area is within `math.isclose(rel_tol=1e-3, abs_tol=1e-12)` of the input's area (0.1% band) and emits a WARNING with OBJECTID + attributes. Genuine lossy cases — e.g. overlapping polygons where the unioned area gaps by ~12.5% — still raise at ~125× the threshold.

The `1e-3` tolerance was set after Phase A characterization of all 10 V1 PAD-US zones: RMNP's ring-self-intersection cleanup artifact produced a `−0.0676%` discrepancy (the double-counted self-intersecting region removed by repair); recovered area matched the published `GIS_Acres` to 0.04%. Threshold `1e-3` clears that with margin while remaining orders of magnitude below the area loss seen in genuinely lossy cases. Before relaxing any tolerance further, run Phase A characterization: live-fetch all affected zones, measure `abs((recovered.area - parsed.area) / parsed.area)` per zone, and cross-check against published acreage. The relaxation is evidence-backed, not reflexive.

Raising on every GC would block valid loads. Silently filtering would lose data when the GC carries real polygonal area. The area-preservation rule preserves ADR-001's fail-loud discipline for genuinely lossy cases while letting topological-artifact cleanup through with audit trail. Test coverage in `tests/test_arcgis.py::TestGeojsonToMultipolygonWkt` locks both branches; do not weaken `abs_tol` to `0.0` (rejects valid tiny polygons due to float noise).

Surfaced by S02.2 live load on 2026-04-30; tolerance updated S06.6.2 (2026-06-22 PAD-US republish).

### `arcgis.fetch_features` cannot apply a server-side WHERE filter — compose private primitives for filtered single-page fetches

**Symptom:** A CO/state adapter needs to fetch a subset of a layer (e.g., PAD-US features filtered to `State_Nm='CO' AND Des_Tp IN (...)`), but `fetch_features` hardcodes `where = f"{metadata.object_id_field}>=0"` (see `arcgis.py:~678`). Editing `ingestion/lib/` violates ADR-005; replicating the full pagination loop duplicates maintenance-critical retry/throttle logic.

**Cause:** `fetch_features` is designed for full-layer pulls. Its `where` clause is not a parameter because the public API was scoped to full-layer use only.

**Fix:** For small fixed result sets that fit in ONE page (< `max_record_count` features), compose the existing private arcgis primitives in the state adapter directly: `arcgis._build_session`, `arcgis._request_with_retry` (handles throttle/backoff/200-with-error-envelope), `arcgis._check_and_fix_projection`, `arcgis._write_features_fixture`, `arcgis._write_manifest_fixture`, `arcgis.compute_feature_hash`, `arcgis._read_objectid`, `arcgis._utc_timestamp`. Issue a single page with the desired `where` clause, then assert `exceededTransferLimit` is absent/false AND `len(features) == returnCountOnly` result. Do NOT use this pattern for large or unbounded result sets — it is only valid when the filtered count is known to be << `max_record_count`. The private-call convention is already established (`load_gmus.py` calls `arcgis._build_session`). Reference: `ingestion/states/colorado/load_restricted_areas.py:_fetch_and_build` (S05.4).

Surfaced by S05.4 implementation on 2026-06-03.

### One-off ArcGIS scripts must detect `{"error": {...}}` envelopes before parsing

The shared `arcgis.fetch_features` (via `_request_with_retry`) detects ArcGIS error envelopes — bodies of shape `{"error": {"code": ..., "message": ..., "details": [...]}}` returned with HTTP 200 — and raises `ArcGISError` with the server's code+message. A one-off script that does its own `requests.get()` against an ArcGIS or MapServer endpoint (rather than going through the shared library) bypasses this detection. The script then parses the body as the expected shape (e.g. a GeoJSON `FeatureCollection`), gets `features=[]` from `data.get("features", [])`, and raises a misleading "zero features" diagnostic when the real cause is auth failure, layer removal, or a malformed query.

The fix in any custom-fetch path: before reading `features` (or the equivalent shape-specific key), check `data.get("error")` and raise with the server's `code` + `message` if present. Example pattern in `ingestion/states/montana/load_state_boundary.py:_parse_to_multipolygon_wkt`:

```python
data = json.loads(payload)
error = data.get("error")
if isinstance(error, dict):
    code = error.get("code", "?")
    message = error.get("message", "<no message>")
    raise RuntimeError(f"... (code={code}): {message}")
features = data.get("features", [])
```

Lock it in with a test that feeds an envelope payload and asserts the raise carries the server code+message. Without this defense, an upstream auth-token-required error returns `{"error": {"code": 499, "message": "Token Required"}}` with HTTP 200 and the operator's first diagnostic is "source geometry changed" rather than "credentials expired."

Surfaced by S03.0 silent-failure-hunter review on 2026-05-04.

### ArcGIS host republish can drop the top-level GeoJSON `id` field — include `"OBJECTID"` in every hardcoded `_*_OUT_FIELDS` tuple

**Failure mode:** An ArcGIS host can republish a layer such that the top-level GeoJSON `id` field is omitted from feature responses unless `"OBJECTID"` is explicitly listed in the request's `outFields`. A loader whose hardcoded `_*_OUT_FIELDS` tuple lacks `"OBJECTID"` then has every feature's OID resolve to `None`, causing `_require_objectid` (or the manual `if oid is None: raise` guard) to fail loud in the manifest-hash loop — 0 rows written, clean halt with no data corruption. Observed: PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer, M2 operator-pass Step 4, 2026-06-21.

**Forensic signal of the same republish:** the response's native CRS shifts (PAD-US `4269 → 3857`), captured as a `WARNING` by `ingestion/ingestion/lib/arcgis._check_and_fix_projection`. A future operator seeing a CRS-shift warning alongside an OID-failure should suspect an upstream republish (not local code rot) and re-audit the layer's `outFields` before anything else.

**Mitigation:** (1) Include `"OBJECTID"` in every hardcoded `_*_OUT_FIELDS` tuple in CO state adapters — locked by the `TestStateAdapterOutFieldsIncludeObjectid` AST-walk test in `ingestion/tests/test_load_co_restricted_areas.py`, which fails any future CO loader whose tuple omits the field. (2) On any OID-critical path (manifest-hash loops), use `arcgis._require_objectid` — which scans only `properties`/`attributes` and raises `ArcGISError` with an outFields-fix diagnostic — rather than `arcgis._read_objectid`, which keeps the `feature["id"]` fallback for error-message/dedup contexts where `None` is tolerated and would otherwise mask the gap. Loaders that delegate `outFields` to `fetch_features` via `metadata.out_fields` (e.g. `load_gmus.py`) are naturally safe: the server's full `fields[]` list includes OBJECTID.

Surfaced by M2 operator-pass Step 4 failure on 2026-06-21; hardened in S06.6.1.

### A single upstream republish can change multiple independent things — diagnose failure modes separately, and treat a CRS-shift WARNING as a full re-audit signal

**Pattern:** USGS PAD-US 4.1 (Federal Fee Managers Authoritative FeatureServer) was republished and introduced TWO distinct breakages within 18 calendar days: (1) 2026-06-21 — top-level GeoJSON `id` dropped unless `"OBJECTID"` in `outFields`, causing every OID to resolve `None` (fixed in S06.6.1); (2) 2026-06-22 — ring self-intersection in Rocky Mountain NP's boundary, causing `shapely.make_valid` to return `GeometryCollection([MultiPolygon, LineString])` with a 0.0676% area discrepancy that exceeded the then-strict `rel_tol=1e-6` guard (fixed in S06.6.2). Each failure mode raised loudly; neither caused silent data corruption. The operator pass halted twice, one story per fix.

**Forensic signal for both republishes:** the response's native CRS shifted `EPSG:4269 → 3857`, captured as a `WARNING` by `lib/arcgis._check_and_fix_projection`. A CRS-shift warning on a previously-stable layer means the upstream republished — **re-validate all failure surfaces, not just the one you hit first.** OID presence, geometry topology, field names, and count can all change in the same republish. Catching the second drift required a second operator-pass resume.

**The right response to a fail-loud guard firing on upstream drift:** characterize the actual discrepancy before changing tolerances. For S06.6.2 this meant Phase A — live-fetch all 10 V1 zones, measure `abs((recovered.area - parsed.area) / parsed.area)` per zone, cross-check against published `GIS_Acres`. Only RMNP triggered the GC branch (−0.0676%, a benign cleanup artifact; the other 9 passed unchanged). Evidence-backed relaxation to `rel_tol=1e-3` (0.1%) clears RMNP with margin while remaining ~125× below the area loss in genuinely lossy cases. Widening the epsilon reflexively — without Phase A — risks silently accepting real data loss.

Surfaced by M2 operator-pass second resume on 2026-06-22; hardened in S06.6.2.

## Integration — Census TIGER

### US Census TIGER state-boundary shapefiles ship in EPSG:4269 (NAD83), not WGS84

The `.prj` sidecar declares NAD83 explicitly; geopandas reads `gdf.crs == "EPSG:4269"` on load. Any adapter consuming TIGER must explicitly call `gdf = gdf.to_crs(4326)` (with reassignment — see geopandas entry below) before writing to a Postgres `geography(MultiPolygon, 4326)` column. Skipping the reprojection produces a silent ~100m offset undetectable by the area sanity check.

Pinned source for S05.0: `https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip` (SHA-256 `ad00cbe66c7177091b668cee202e93d4a1ddcee271c28d1c9f9874af59c04b92`); SHA pin fails loud on Census re-publication per ADR-001.

Surfaced at S05.0 plan-review Stage 4 (2026-06-01).

## Integration — geopandas

### `gdf.to_crs(epsg)` returns a new GeoDataFrame — bare call without reassignment silently discards the reprojection

`geopandas.GeoDataFrame.to_crs(epsg)` is non-mutating. A bare `gdf.to_crs(4326)` expression (without reassignment) leaves the original GeoDataFrame carrying the source CRS unchanged. For state-boundary adapters sourced from TIGER (EPSG:4269 NAD83), this produces NAD83 coordinates that Postgres `ST_GeomFromText(wkt, 4326)::geography` mis-interprets as WGS84 — a systematic ~100m offset that no area sanity check can catch.

**Fix:** always reassign — `gdf = gdf.to_crs(4326)`. Explicit prose at `ingestion/states/colorado/load_state_boundary.py:199-202` documents the trap.

Surfaced at S05.0 plan-review Stage 4 (2026-06-01).

## Integration — Supabase / PostGIS

### `geometry` table DDL column is `geom`, not `geog`

The actual DDL column name is `geom geography(MultiPolygon, 4326)` (see `supabase/migrations/20260425000000_initial_schema.sql:201`). CLAUDE.md uses "geog" colloquially in one sentence ("all geometries use `geography(MultiPolygon, 4326)`") but that phrase refers to the type, not the column name. Raw SQL that uses `zone.geog` or `hd.geog` receives `ERROR: column "geog" does not exist`. All hand-written queries must use `geom`.

Surfaced 2026-05-23 during S03.10 T0 probe (initial SQL block used `geog`; corrected before any execution). Reference: `S03.10.md` DDL findings section.

### PostGIS functions must use `extensions.` schema prefix in Supabase projects

The Supabase project installs PostGIS with `CREATE EXTENSION IF NOT EXISTS postgis SCHEMA extensions;` (see `supabase/migrations/20260425000000_initial_schema.sql` near the top). The `extensions` schema is NOT on the connection's default search_path, so bare names fail: `ERROR: function st_dwithin(geography, geography, integer) does not exist` (or equivalent for `ST_Touches`, `ST_Centroid`, etc.). Every raw-SQL PostGIS function call must be prefixed: `extensions.ST_DWithin(...)`, `extensions.ST_Touches(...)`, etc.

This is a Supabase-project-specific configuration choice, not a missing extension — the function exists but is only resolvable via the explicit schema qualifier. Reference: S03.10 schema-prefix audit section in `S03.10.md`; ADR-016 `statement_timeout` note also implied geography-native calls were needed. Locked in S03.10 by `TestQueryNearbyHdsForZone::test_sql_uses_extensions_prefix_not_bare_name`.

Surfaced previously (E02) and again 2026-05-23 during S03.10 T0 (the `load_jurisdiction_bindings.py` query required the prefix from the first draft).

### Centroid-to-centroid `ST_DWithin` produces zero matches for large national-park polygons

**Symptom:** `ST_DWithin(ST_Centroid(zone.geom), ST_Centroid(hd.geom), 5000)` returns 0 matches for all three Montana no-hunt zones (Glacier NP, Sun River Game Preserve, Yellowstone NP) even at a 5 km threshold — every HD is classified as "not nearby" and no bindings are written.

**Cause:** National-park and game-preserve polygons are large; their centroid is many kilometres from any HD boundary. Yellowstone NP's centroid is roughly 30 km inside the park, far from the nearest HD centroid. Centroid-to-centroid distance is only meaningful for compact, roughly-circular polygons.

**Fix:** Use boundary-to-boundary geography `extensions.ST_DWithin(zone.geom, hd.geom, distance_meters)` directly on the native `geography` columns. This covers the ST_Touches case (touching = 0 m distance), avoids geometry casts, and works correctly for large polygons. Reference: `load_jurisdiction_bindings.py::_query_nearby_hds_for_zone`; Deviation #4 footnote in S03.10 epic.

Surfaced 2026-05-23 during S03.10 T0 probe; confirmed via live-DB counts (centroid: 0/0/0; boundary-to-boundary: 8/8/13 matches).

### Follow-up migrations must include their own RLS policies — the base RLS migration's flat IN-list does not auto-extend

**Symptom:** A table added by a follow-up migration (e.g., `license_season` added by `20260504032424_e03_schema_additions.sql`) is silently permissive — no deny-all RLS policy covers it — because the original RLS migration (`20260425000001_rls_deny_all.sql`) uses a flat `table_name IN (...)` list that was never updated.

**Cause:** Postgres tables are permissive-by-default when no RLS policy exists. The flat IN-list in the base RLS migration does not enumerate tables that didn't exist when it was written; re-running it would be a no-op on the existing tables and would not cover new ones.

**Fix:** Every migration that adds a new table must include `CREATE POLICY` + `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` in the same migration file. Do not assume the base RLS migration will be updated. Audit gap detection: `SELECT tablename FROM pg_policies WHERE schemaname='public' GROUP BY tablename;` — compare against the full table list to surface any table with no policy. Surfaced by S03.12 UAT criterion #7 review on 2026-05-27.

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

### Spec-prescribed SQL can embed a broken idiom OR a column that doesn't exist — validate against the live DDL, don't transcribe

**Symptom:** A runbook section is authored by copying a SQL snippet from the epic spec. Two distinct failure modes hit S05.7, both from the same transcribe-don't-validate root cause:

1. **Broken cast idiom.** The snippet uses `extensions.ST_Envelope(extensions.ST_Collect(geom::geometry))`. This project's own pitfall ("geom::geometry direct cast not enabled") documents that the direct geography-to-geometry cast is rejected by Supabase; the workaround is the WKT round-trip `extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)`. The fix was applied correctly for `ST_IsValid`, `ST_NumGeometries`, `ST_Equals`, and `ST_Normalize` queries — but the one section transcribed verbatim from the spec carried the broken cast.

2. **Nonexistent column.** The spec's FK-cascade wipe wrote `DELETE FROM jurisdiction_binding WHERE state = 'US-CO'` — but `jurisdiction_binding` has **no `state` column** (its columns are `regulation_record_state` + `geometry_id`; see `supabase/migrations/20260425000000_initial_schema.sql`). The query fails at runtime with `column "state" does not exist`. The correct, FK-cascade-precise form targets the bindings by the geometry they reference (the FK that blocks the geometry DELETE): `DELETE FROM jurisdiction_binding WHERE geometry_id IN (SELECT id FROM geometry WHERE state = 'US-CO')` — matching the S05.3.5 migration's `geometry_id IN (...)` precedent.

Both were caught at review, not by the original authoring.

**Cause:** Spec-prescribed SQL snippets are pre-validated assumptions written at planning time, before the schema was consulted (or before a pitfall was known). Transcribing the snippet is the natural fast path; re-deriving against the actual DDL + pitfall doc is the correct path. A single `WHERE state = 'US-CO'` predicate that is correct for one table (`geometry` HAS a `state` column) is silently wrong for another (`jurisdiction_binding` does not) — same predicate, different schema.

**Fix:** Treat any spec-provided SQL as documentation of intent only. Before shipping runbook SQL, cross-check **every table + column against the live DDL** (`supabase/migrations/`) and **every geometry-only PostGIS function** (`ST_Collect`, `ST_Envelope`, `ST_IsValid`, `ST_NumGeometries`, `ST_Equals`, `ST_Normalize`, `ST_AsBinary`, …) against the cast pitfall. Do not assume a `WHERE <col>` clause valid on one table is valid on another. This extends the "spec-prescribed string substitutions silently invalidate coupled references" / "name the source-of-truth before copying numbers" family (Conventions — Documentation & planning discipline) to SQL: the DDL + pitfall doc are the source-of-truth, not the spec snippet.

Surfaced by S05.7 Stage-6 review (cast) and post-merge review (nonexistent column) on 2026-06-06.

## Integration — pdfplumber

### `page.extract_text()` collapses repeated spaces — output is not byte-exact verbatim

pdfplumber 0.11.x reassembles characters into words via its internal word-grouping algorithm and joins them with a single space. A PDF content stream with two literal spaces between words (e.g. `(hello  world) Tj`) is returned as `"hello world"` — one space, not two. Newlines from line-position changes ARE preserved; only intra-word spacing is collapsed.

ADR-008 ("verbatim regulation text") is implemented as "no additional normalization on top of pdfplumber" — pdfplumber's own normalization is the platform baseline. This interpretation is locked into S03.2's tests via `ingestion/ingestion/lib/pdf.py::extract_text`. Consequence: **do not assert byte-exact whitespace preservation against `extract_text` output**; tests that do will pass locally against a specific PDF but misrepresent what the function actually guarantees.

If a future story needs truly byte-exact source text (e.g., forensic comparison), walk `page.chars` directly — `extract_text` is not the right tool:

```python
# byte-exact path — bypasses pdfplumber's word grouping entirely
raw = "".join(ch["text"] for ch in page.chars)
```

Surfaced by S03.2 pre-implementation discovery + implementation on 2026-05-05.

### `page.extract_tables()` drops bounding boxes — use `page.find_tables()` instead

pdfplumber exposes two related table APIs with different return shapes:

- `page.extract_tables()` → `List[List[List[Optional[str]]]]` — cell data only, **no bbox**.
- `page.find_tables()` → `List[Table]` where each `Table` carries both `.bbox` and `.extract()`.

`TableMatch.bbox` (used for downstream region-cropping and provenance in `ingestion/ingestion/lib/pdf.py`) requires `find_tables()`. The natural-looking `extract_tables()` loses spatial info entirely — using it means calling BOTH methods and manually pairing cell data with bboxes, which is fragile and unnecessary.

The wrapper `ingestion/ingestion/lib/pdf.py::extract_tables` calls `find_tables()` internally despite the wrapper name suggesting otherwise. The docstring explains the choice, but anyone writing ad-hoc pdfplumber code outside the wrapper will reach for `extract_tables()` first and lose bboxes silently.

**Always use `page.find_tables()`** when bbox is needed; call `.extract()` on each returned `Table` object for cell data.

Surfaced by S03.2 implementation on 2026-05-05.

### FWP DEA-style tables: one table per page, not per regulation unit

The Montana DEA (Deer/Elk/Antelope) regulations PDF — and likely other state F&W table-formatted booklets — does NOT structure regulation tables as one-table-per-HD/unit. `pdfplumber.find_tables()` returns ONE TABLE PER PAGE, with HD-section delimiters embedded as data rows whose first cell matches `"HD NNN - Name"`. Multi-HD pages contain multiple such delimiter rows.

**Symptom:** A state adapter assuming one-table-per-HD silently truncates every HD's data after the first delimiter row, OR silently merges multiple HDs into one section. Both failures surface only at downstream validation, not at extraction time.

**Fix:** HD-level slicing must walk data rows looking for the heading regex, then accumulate rows until the next heading. Multi-page HDs (continuations) need bounded lookahead capped at 2–3 pages — do NOT scan unboundedly to "find the end." `pdfplumber.find_tables()` returning 1 table does not mean 1 HD's worth of data; it may contain 5 HDs on one page.

Reference implementation: `ingestion/states/montana/extract_dea.py::_slice_hd_rows` and `::_extract_hd_table` (S03.3, 2026-05-08).

### FWP tables use `"-"` as absence sentinel — applies to ALL nullable cells, not just season columns

FWP DEA table cells use the literal hyphen `"-"` to mean "not applicable / no value here." This applies to season-coverage columns (`EARLY SEASON DATES`, `ARCHERY ONLY SEASON DATES`, `GENERAL SEASON DATES`, `HERITAGE MUZZLELOADER SEASON DATES`, `LATE SEASON DATES`) AND to other nullable string fields: `APPLY BY DATE`, `QUOTA RANGE`, `OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS`. Likely extends to other FWP booklets.

**Symptom:** A naive `_normalize_cell` that only strips whitespace returns `"-"` — a non-empty string — contaminating the artifact. S03.3 saw 675 / 971 / 521 leaked sentinel rows in `apply_by` / `quota_range` / `extras` before the fix. Downstream code using `if row["apply_by"]:` treats the sentinel as a real value (violates ADR-001's "absent data is explicit null").

**Fix:** Both season-coverage logic AND nullable string field assignment must apply an `_is_absent_cell(cell)` check treating `None` AND `"-"` (and whitespace-padded variants like `" - "`) as absent. The predicate normalizes to `None` before any consumer reads the cell.

Reference implementation: `ingestion/states/montana/extract_dea.py::_is_season_cell_absent` (S03.3, 2026-05-08) — despite the name it is used for non-season fields too; the name is a historical artifact.

### pdfplumber sub-rows under a merged-cell license code return `None` — implement carry-forward

The DEA PDF (and likely many state regulation tables) groups multiple opportunity sub-rows under a single license code via merged cells. pdfplumber returns `None` in the LICENSE/PERMIT column for every sub-row — the merged cell's value appears only on the first row of the group.

**Symptom:** Naive per-row processing emits sub-rows with `license_code=None`, which fails fail-loud guards or produces NULL primary-key violations downstream. The A/B-asymmetric coverage signal is also lost — sub-rows that differ only in `season_coverage` end up rejected rather than recorded as separate season rows.

**Fix:** Track `last_license_code` (and `last_opportunity` for sub-opportunity rows) across rows; inherit the prior value whenever the LICENSE/PERMIT cell is `None`. This pattern enables correct A/B-asymmetric coverage: one license can have multiple sub-rows with differing `season_coverage` values, all sharing the same license code. S03.7's `license_season` link table depends on this carry-forward.

Reference implementation: `ingestion/states/montana/extract_dea.py::_rows_to_license_extractions` — `last_license_code` and `last_opportunity` carry-forward variables (S03.3, 2026-05-08).

### Section-level "first-observation-wins" for per-row variable fields is interpretive, not faithful

**Symptom:** When a per-row PDF field varies within a section (e.g., season date windows that differ per license/opportunity row), capturing only the first observation and replicating it across rows replaces source data with a paraphrase — violates ADR-008. Per-row divergence collapses to a single value in the artifact, and downstream consumers reading individual rows see incorrect data.

**Fix:** Always extract per-row from each row's column cells; emit warnings only for cases that genuinely cannot be parsed (not for natural divergence). The "section-level windows + per-row filter" pattern is the trap — rebuild as "per-row windows from each row's own cells, no section-level aggregation."

Reference: `ingestion/states/montana/extract_dea.py::_rows_to_license_extractions` — per-row `season_windows` populated inline from each row's column cells. Surfaced by S03.3 UAT failure on 2026-05-08 (HD 124 deer had three distinct General Season windows in the source PDF; the artifact carried only the first observation across all 5 rows).

### Rotated tables emit doubly-reversed cells

- **Rotated tables emit doubly-reversed cells.** Some PDFs (Montana Black Bear booklet) print regulation tables physically rotated. pdfplumber returns each cell with both line order AND character order reversed (e.g., `"Sep.15-Nov.29"` extracts as `"92.voN-51.peS"`). `page.rotation` reports 0 — there's no hint that reversal is needed. Every cell must be passed through a reversal helper BEFORE normalization. Reference: `_reverse_cell_text` in `extract_black_bear.py`.

### Two-column page layouts interleave text in `extract_text(page)`

- **Two-column page layouts interleave text in `extract_text(page)`.** pdfplumber's default extraction reads top-to-bottom across both columns. For pages with two-column layouts (Black Bear p. 7), use `extract_text(page, bbox=(306, 0, 612, 792))` to isolate the right column before processing.

### Quota-cell word order varies by extraction context

- **Quota-cell word order varies by extraction context.** The same quota phrase can appear as `"= N Female subquota"`, `"= N quota Harvest"`, or `"quota = Harvest N"` depending on how pdfplumber splits multi-line cells in rotated tables. Use a primary regex + word-order-invariant component fallback (`_QUOTA_COUNT_REGEX` + `_QUOTA_KIND_REGEX` in `extract_black_bear.py`).

### Three-column FWP booklet layout — full-page `extract_text()` is unusable

The FWP Legal Descriptions PDF (2026-2027 edition, 56 pages) uses a three-column layout on every content page. `pdfplumber.Page.extract_text()` on the full page reads top-to-bottom across all three columns, producing severely interleaved text (e.g., column-3 heading interleaved with column-2 body). Heading regexes against this stream produce false-positive matches across column boundaries.

**Fix:** crop each column separately and concatenate the per-column streams in left-to-right order. Column boundaries for the FWP Legal Descriptions PDF (594pt × 756pt page):

- col1: `x ∈ (36, 195)`
- col2: `x ∈ (210, 355)`
- col3: `x ∈ (390, 555)`
- header strip top = **25pt** (no running title on V1 content pages; first content row sits at top≈29; an over-aggressive 40pt strip clipped HD headings at the top of each column)
- footer strip bottom = **50pt** (running footer `"Visit fwp.mt.gov <page#>"` sits at top≈716, ~40pt above page bottom; 20pt was too shallow)

Reference implementation: `ingestion/states/montana/extract_legal_descriptions.py::_extract_three_column_text` (S03.5, 2026-05-12; strip values revised 2026-05-13/14).

### Rotated chapter-label sidebars are non-upright glyphs — filter via `c.get("upright", True)`

Every content page of FWP booklets carries a vertical chapter label in the outer margin (e.g., `klE & reeD`, `epoletnA`). These are not separate page layers; they are sideways-drawn text characters whose `char["upright"]` is `False`. Without filtering, they contaminate column extractions and trigger spurious heading matches.

**Fix:** apply a chained filter when cropping for column text:

```python
page.crop(bbox).filter(lambda c: c.get("upright", True)).extract_text()
```

`page.rotation` reports `0` for these pages — there is no signal that filtering is needed except inspection. Reference: `ingestion/states/montana/extract_legal_descriptions.py::_extract_three_column_text` (S03.5, 2026-05-12).

### Heading regex name capture must exclude newline, not just colon

A naive heading regex like `^\s*(\d{2,3})\s+([^:]{3,80}?):\s+ANCHOR` looks safe because the lazy `[^:]{3,80}?` excludes the colon delimiter. But `[^:]` does NOT exclude `\n` — the lazy match can span line boundaries, letting a leading-digit fragment on a prior line absorb the next line's intended heading.

**Symptom:** A body fragment ending with a 2–3-digit number (e.g., `"93 in Missoula County."`) immediately preceding a real heading line (`"261 East Bitterroot: That portion..."`) causes the regex to capture `93` as the HD number and absorb `"in Missoula County.\n261 East Bitterroot"` into the lazy name span. Result: the false HD 93 surfaces as unmatched; the real HD 261 is silently swallowed.

**Fix:** use `[^:\n]` (or `[^:\r\n]` for Windows-line-ending tolerance) in the lazy name capture. Reference: `ingestion/states/montana/extract_legal_descriptions.py::_HD_HEADING_RE` (S03.5, 2026-05-12). Discovered during T11 end-to-end run; locked by `TestArtifactRegression::test_regression_unmatched_rate_below_10_percent`.

### Same heading text repeats once per column when a description spans multiple columns

The three-column layout causes a single zone-description (e.g., the Libby CWD Management Zone on PDF page 19) to span all three columns. The heading text appears in EACH column with a different body fragment in each. A naive page-walk yields three blocks with the same `cwd_name`; if the matcher first-match-wins, the body of the first column is recorded and the other two columns are dropped.

**Fix:** post-walk consolidation step that merges all blocks with the same canonical heading into a single block whose body concatenates the per-column fragments in original column order. Defensive: idempotent (running twice is a no-op). Reference: `ingestion/states/montana/extract_legal_descriptions.py::_consolidate_cwd_blocks` (S03.5, 2026-05-12).

### Heading anchor phrases wrap onto continuation lines when columns are narrow

The FWP Legal Descriptions PDF wraps the heading anchor phrase ("Those portions of Lincoln county...") onto the line after the heading line, and sometimes even wraps the trailing word `Zone:` of the heading itself (Kalispell case: page 21 col 2 reads `"Kalispell Area CWD Management"` with no colon or "Zone" suffix on that line).

**Fix:** for the narrow-column case, the heading regex CANNOT require the anchor phrase on the same line; it can match only the heading-name prefix:

```text
^\s*(Libby CWD Management Zone|Kalispell Area CWD Management(?:\s+Zone)?)\b
```

Then in the matcher, canonicalize the captured name (append " Zone" if missing) before the lookup. Reference: `ingestion/states/montana/extract_legal_descriptions.py::_canonicalize_cwd_name` (S03.5, 2026-05-12).

The same wrap also affects HD headings: HD 705 reads `"705 Prairie/Pines-Juniper Breaks: Those\nportions of..."` — the literal space in `Those portions?` doesn't match the newline. Fix: use `Those\s+portions?` (and `That\s+portion`) — whitespace-flex matches the wrap while still rejecting arbitrary non-whitespace text between the two words (since `\s` is whitespace-only). Surfaced 2026-05-13 — without this, +17 HDs silently surfaced as unlinked. Locked by `TestHeadingRegex::test_hd_anchor_phrase_wraps_across_newline`.

### FWP antelope DEA tables use 4-letter `"Sept"` month abbreviation

FWP DEA antelope per-HD A-license rows use `"Sept"` (4 letters) where all other DEA tables use `"Sep"` (3 letters), e.g. `"Sept. 05-Oct. 09"`. Python's `datetime.strptime` with `%b` only accepts the 3-letter POSIX form and raises `ValueError` on `"Sept"`.

**Symptom:** Date-parsing of antelope rows aborts with `ValueError: time data 'Sept. 05' does not match format '%b. %d'`. All other species parse cleanly, making the error look like a data anomaly rather than a normalization gap.

**Fix:** In the date-parsing helper, normalize before `strptime`: `re.sub(r"\bSept\b", "Sep", cell_text)`. Apply before any `strptime` call, not inside a try/except — fail-loud is better than silently skipping antelope rows. Reference: `_parse_window` in `ingestion/states/montana/load_seasons_and_licenses.py`.

Surfaced by S03.7 implementation 2026-05-15.

### Running PDF footer leaks into last body when crop strip is too shallow

The FWP Legal Descriptions PDF carries a `"Visit fwp.mt.gov <page#>"` running footer on every content page at `top ≈ 716` on a 756pt-tall page (roughly 40pt from the bottom). The initial column-crop footer strip of 20pt produced a cutoff at `page.height - 20 = 736` — above the footer — so the footer text leaked into whichever HD body extended near the bottom of the column. HD 704's `verbatim_description` ended with `"Visit fwp.mt.gov 9"`.

**Fix:** crop the bottom-most 50pt (not 20pt). The cutoff at `page.height - 50 = 706` is well above the footer's top y of 716. Probe footer position with `page.extract_words()` filtered to the bottom region before settling on a strip value. Reference: `ingestion/states/montana/extract_legal_descriptions.py::_FOOTER_STRIP_PT` (S03.5, 2026-05-13). Locked by `TestArtifactRegression::test_no_running_footer_leak_in_verbatim_descriptions`.

### pdfplumber uniform character-doubling on some pages — detect and recover per token

**Symptom:** On certain CPW Big Game PDF pages (e.g., GMU-20-area deer/elk), every glyph is emitted twice: `"Oct. 24–Nov. 1"` extracts as `"OOcctt.. 2244––NNoovv.. 11"`, hunt codes like `"D-M-020-O2-R"` become `"DD--MM--002200--OO22--RR"`. The MT analog is rotated-table `_reverse_cell_text`; this is a different artifact of pdfplumber's word-grouping on certain font encodings.

**Cause:** pdfplumber's glyph-to-text reconstruction replays each glyph twice for some embedded-font pages. The doubling is uniform across the whole cell when no whitespace is present (hunt codes recover cleanly with `s[::2]`), but doubled spaces get collapsed to single spaces during word-grouping, so whole-string positional de-doubling (`s[::2] == s[1::2]`) silently fails for any cell that contains whitespace.

**Fix:** Two-stage recovery. (1) Whole-string check: `len(s) >= 6 and len(s) % 2 == 0 and s[::2] == s[1::2]` — recovers no-whitespace cells via `s[::2]`. (2) Token-level fallback: split on whitespace, check that EVERY token is uniformly doubled AND at least one is long enough to anchor (`len(tok) >= 4 and tok[::2] == tok[1::2]`); if so, de-double each token and rejoin. Gate (2) only fires when ALL tokens pass to avoid corrupting coincidental short repeated patterns. Apply de-doubling row-level (gate on a long uniformly-doubled cell) BEFORE see-unit/footnote/header skip filters so doubled rows are not misclassified. Recovery is ADR-008-faithful — you are undoing a render artifact. Reference: `ingestion/states/colorado/extract_big_game.py` R14 de-doubling logic (S06.3).

Surfaced by S06.3 real-PDF probe on 2026-06-10.

### "Ranching for Wildlife" / private-land table sections use a different column layout — date-shaped `valid_gmus` signals a column shift

**Symptom:** ~160 rows extracted from CPW Big Game pages 32/44/51 have a structured `valid_gmus` field that contains a date string (e.g., `"Oct. 1–Nov. 30"`) and an empty season window. No valid GMU list ever looks like a date.

**Cause:** Ranching for Wildlife and some private-land hunt sections use a 5-column layout (`Ranch/Units | Dates | Sex | Hunt Code | List`) instead of the standard 6-column layout that includes a `Valid GMUs` column. The standard column-mapping code writes the Dates cell into `valid_gmus` and leaves the season window empty.

**Fix:** After standard column extraction, detect the column shift: when a structured `valid_gmus` value is date-shaped (matches a date-range pattern), treat it as the misplaced per-row season window — parse it into the season window and null `valid_gmus`. The detection is safe because a real GMU list never contains month names or date separators. This was only caught by cubic review, not by the original column-mapping logic — add a regression test asserting that date-shaped `valid_gmus` values are never written to the artifact. Reference: `ingestion/states/colorado/extract_big_game.py` Ranching for Wildlife column-shift handler (S06.3).

Surfaced by S06.3 cubic review on 2026-06-10.

### Page-level "Season Dates:" headers must be applied method-aware — a header from one weapon group bleeds onto the next group's rows

**Symptom:** On multi-section pages (e.g., muzzleloader section followed by rifle section), a `"Season dates:"` header row captured for the muzzleloader section bleeds onto rifle rows that follow on the same page. Rifle rows then carry the muzzleloader date window as their season window.

**Cause:** Two coupled failure modes: (a) a page-level `current_method_group` advances past a table via page-text pre-scan before the table rows have been read — so the method attributed to the header row no longer matches the method attributed to the table rows below it; (b) when a bare `"Season dates:"` heading-only row appears inside a table, attributing it to the page-level `current_method_group` (which the pre-scan already advanced) gives it the wrong method.

**Fix:** Two paired rules: (a) a header-set season window only applies to rows whose weapon method (derived from the hunt code) matches the method the header came from; (b) when a bare heading row appears inside a table, derive its method from the TABLE's own first hunt code, not the page-advanced `current_method_group`. Reference: `ingestion/states/colorado/extract_big_game.py` method-aware header attribution (S06.3).

Surfaced by S06.3 cubic review iteration 4 on 2026-06-10.

### Presentation glyphs (`■` OTC-marker) and map-page OCR leak into structured fields — strip the glyph and skip garbage rows with diagnostics

**Symptom:** 136 `unit` / `valid_gmus` fields carry values like `'■1'` or `'3\n■'`. Some rows extracted from map pages contain large scrambled-OCR blobs in their `valid_gmus` field with no parseable hunt code.

**Cause:** Two distinct sources: (1) CPW uses the `■` glyph as an OTC marker adjacent to unit numbers in table cells; `_normalize_cell` stripped whitespace and `-` but not `■`. (2) Map pages interleave image-OCR output with table-extraction, producing rows where no valid hunt code can be parsed and `valid_gmus` is a multi-line OCR dump.

**Fix:** (1) Strip `■` in the cell normalizer (`_normalize_cell`); it is a marker, not a value. (2) For garbage-row detection, use a three-condition gate: hunt code doesn't parse AND cell contains no hunt-code-shaped substring (`[A-Z]-[A-Z]-\d{3}` pattern) AND has no valid List value (`A`/`B`/`C`/`OTC`). Only rows passing all three are skipped, and they are WARNING-logged (not silently dropped) so operators can audit. The fragment-substring check preserves multi-hunt-code cells like `'D-M-082-O2-R\nD-M-082-O3-R'`. Reference: `ingestion/states/colorado/extract_big_game.py` `_normalize_cell` + garbage-row gate (S06.3).

Surfaced by S06.3 cubic review iteration 1 on 2026-06-10.

### Same-month date ranges drop the month from the end token — inherit start's month into the convenience field, keep `raw_text` verbatim

**Symptom:** A parsed date range like `"Sept. 2–30"` produces `end_date` with a bare `"30"` — no month — making the standalone end-date field ambiguous or unparseable.

**Cause:** State regulation PDFs commonly omit the month on the end token when start and end share the same month (`"Sept. 2–30"` rather than `"Sept. 2–Sept. 30"`). The date-range parser extracts the end token `"30"` as-is without inheriting the start month.

**Fix:** In the shared date-range helper, after parsing the start date, check whether the end token contains no month indicator. If so, inherit the start's month into the parsed `end_date` convenience field (e.g., `"Sept. 30"`). Apply only to the structured convenience field — `raw_text` always stays byte-verbatim. Apply this fix in the SHARED helper so both cell-date and section-header-date paths benefit; using separate regex paths in each call site causes the fix to be applied inconsistently. Reference: `ingestion/states/colorado/extract_big_game.py` shared date-range helper month-inheritance (S06.3).

Surfaced by S06.3 cubic review iteration 3 on 2026-06-10.

### Multi-column PDF prose extraction — crop by column; keep crop edges out of text lines

**Symptom:** `lib/pdf.extract_text(page)` (full-page, no bbox) on a dense multi-column brochure page interleaves the columns line-by-line in reading order — unusable for per-column byte-faithful text. (Same root cause as the FWP three-column Legal Descriptions pitfall above.) Separately, a *band* crop whose horizontal edge (`top` or `bottom`) is placed **mid-line** — clipping through glyphs or landing within the y-tolerance band shared by two adjacent physical lines — silently character-scrambles that line: the two lines' glyphs get merged and re-sorted by x-coordinate, corrupting (e.g.) the opening sentence of the crop. The failure is the *edge placement*, not the presence of a non-zero `top` per se — a strip boundary that lands in inter-line whitespace is safe (see the FWP Legal Descriptions header/footer strips above: `top=25pt` works because the first content row sits at `top≈29`, while an over-aggressive `40pt` strip clipped the headings).

**Cause:** pdfplumber's character-grouping is based on absolute y-coordinates. When a crop edge clips a line mid-glyph (or falls within the y-tolerance band of two close lines), the partially-visible glyphs from both lines are sorted by x — interleaving two lines into one scrambled run. The three-column problem and the mid-line-edge problem are both manifestations of the same y-sorting assumption.

**Fix:** Crop by **column bbox** — tune the x-gutter to isolate the column. For the vertical bounds: prefer the full page height (`top=0.0`, `bottom=page.height`) when you do not need to strip a running header/footer, and let the regex anchor handle vertical position (the S06.5 `verbatim_rule` case). When you *do* need a header/footer strip (the S03.5 Legal Descriptions case), place the cut boundary in inter-line whitespace — probe `page.extract_words()` y-positions first and set the strip just above the first content row / just above the footer, never through a line. Either way, regex-anchor the target span within the resulting single-column text stream.

**Verified gutters (CPW Big Game brochure p. 78, 3-column layout, 603pt-wide page):**

- right column: `x0=392`, `x1=603` (full page height)
- left column: `x0=0`, `x1=200` (full page height)

**Fail-loud guards (both required per ADR-001):**

1. Raise if the regex anchor is absent in the cropped text — indicates a layout change in a future brochure edition.
2. Raise if the column crop returns empty `.strip()` text — indicates the x-gutter has drifted past the column boundary. Distinguish the two diagnostically (`"anchor absent"` vs `"column crop empty"`) so the operator inspects the right cause.

**ADR-008 note:** the resulting span is byte-equivalent to `pdf.extract_text(page, bbox=…)` output — newlines and soft-hyphens are preserved. Never hand-edit the extracted text on anchor-not-found; that is an invented transcription.

Surfaced by S06.5 real-PDF probe on 2026-06-17 (CPW Big Game brochure p. 78, `verbatim_rule` population for restricted-area no-hunt zones). Related: three-column layout pitfall (FWP Legal Descriptions, S03.5) and two-column page layout pitfall (Black Bear booklet p. 7, S03.4) above.

### Multi-column PDF prose: an END-anchor regex can match a sibling-column heading before the body prose — capturing heading-only text

**Symptom:** A prose-block extractor bounds its capture between a START anchor (the section heading) and an END anchor (the next heading). On a multi-column page, pdfplumber's `extract_text()` interleaves columns in reading order that may place a RIGHT-column heading immediately after a LEFT-column heading — before the left-column body prose arrives. The END anchor matches the sibling-column heading first, so the captured `verbatim_rule` is the heading text ALONE with no rule text. Because the result is a non-empty string, no downstream non-empty validator fires.

**Concrete instance:** `ingestion/states/colorado/extract_black_bear.py::_extract_mandatory_inspection_candidate` (CPW Big Game brochure p. 73, "Mandatory Bear Inspections & Seals" section). `_BEAR_INSPECTION_END_RE` matched `"Multiple Options for Hunting Bear"` — the right-column heading — before the left-column body arrived. Consequently `black-bear-2026.json`'s lone reporting-obligation entry carries `verbatim_rule="Mandatory Bear Inspections & Seals"` (just the heading) instead of the full `"Hunters must personally present their bear head and hide…"` prose.

**Downstream impact:** A loader consuming such an artifact cannot distinguish heading-only from full prose — both are non-empty strings. ADR-008 forbids fabricating the missing text in the loader. S06.9's loader handles this by emitting a `WARNING` when the written `verbatim_rule` equals the `_KNOWN_HEADING_ONLY_VERBATIM` constant (a single `Final[str]` compared by `==`; a loader-side mitigation, not a root-cause fix).

**Mitigations:** (a) At extraction time, add a length or content sanity check on bounded prose blocks — warn or fail if a captured block equals its own heading text or is implausibly short. Prefer column-cropping (bbox per column) over whole-page `extract_text()` for multi-column prose, per the S06.5 multi-column-crop pitfall above. (b) At load time, compare each written `verbatim_rule` against the known heading-only value and emit a `WARNING` on a match — this makes the gap visible in run logs so operators can identify which brochure editions need re-extraction. S06.9 uses a single `_KNOWN_HEADING_ONLY_VERBATIM: Final[str]` constant compared by `==`; promote it to a `frozenset[str]` with membership testing only if multiple heading-only values accumulate across editions.

Surfaced by S06.9 implementation on 2026-06-28 (CPW Big Game brochure p. 73 mandatory-inspection prose extraction).

### Multi-column PDF prose: a non-empty bbox crop is insufficient against layout drift — assert interior body content, not just non-emptiness

**Symptom (S06.9.1):** The fix for the S06.9 END-anchor / sibling-column pitfall above is to switch from un-cropped `extract_text()` + END-anchor to column-scoped bbox crops assembled in reading order (heading → Col A → Col B), per the S06.5 multi-column-crop pitfall. The crop guard checks that `.strip()` is non-empty. However, if a future brochure re-render shifts column layout so the bbox falls over an adjacent table instead of the prose block, the crop is still non-empty (table rows) and a heading anchor can still match — the guard passes and silently produces **non-empty-but-wrong** regulatory text. Neither a non-empty check nor an anchor-absent raise catches this failure.

**The root cause:** "non-empty" proves only that pdfplumber extracted *some* characters inside the bbox. It says nothing about whether the extracted text is the regulation prose you intended to capture.

**Fix:** After assembling the cropped text, assert a **positive interior-prose anchor** — a regex that matches a phrase from the *body* of the rule, not the heading and not a structural marker. Raise (or return `None` → caller raises `PdfExtractionError`) if the anchor is absent.

```python
_INSPECTION_BODY_ANCHOR_RE = re.compile(r"(?i)five\s+working\s+days")
if not _INSPECTION_BODY_ANCHOR_RE.search(assembled_text):
    _LOGGER.warning("interior-prose anchor absent — possible layout drift on p.73")
    return None
```

This makes bbox drift fail loud instead of emitting plausible-looking wrong text.

**Scope:** bbox coordinates are page-specific — do not copy S06.5's page-78 values; re-probe each page independently. Soft-hyphens at line wraps (e.g., `"inspec- tion"`) are preserved verbatim by the existing `re.sub(r"\s+", " ", ...)` normalization and are faithful, not a defect (ADR-008).

**General rule:** when a fixed-geometry crop carries regulatory text, verify *content* (interior-prose anchor), not just *presence* (non-empty). Apply alongside the two existing guards from the S06.5 pitfall ("anchor absent" and "column crop empty").

Surfaced by S06.9.1 implementation on 2026-06-30 (re-anchor of CPW Big Game brochure p. 73 prose in `extract_black_bear.py`). See adjacent S06.9 entry for the upstream END-anchor failure this resolves, and S06.5 multi-column-crop pitfall for the bbox-column approach.

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

### Script invocation must use `python <path>`, not `python -m`, for state adapter scripts

The editable install of `ingestion/` (`pip install -e .` with `packages = ["ingestion"]` in `pyproject.toml`) makes the inner `ingestion/ingestion/` directory available as the top-level `ingestion` package. Its `__path__` resolves to `['/<repo>/ingestion/ingestion']` only — the project-root `states/` directory is NOT a subpackage of `ingestion`. As a result:

- `from ingestion.lib.X import ...` works (the inner package exports `lib/`)
- `from states.montana.X import ...` works in tests because pytest puts the project root (`ingestion/`) on `sys.path`, and `states.montana` is then resolvable as a namespace package
- `python -m ingestion.states.X.module` **fails** with `ModuleNotFoundError: No module named 'ingestion.states'` — `ingestion` is the inner package, not the project-root namespace
- `python -m states.montana.X` would only work if `cwd` is the project root AND nothing else interferes — fragile

Always invoke state adapter scripts directly by path (consistent with the docstring on `ingestion/states/montana/load_state_boundary.py`):

```sh
ingestion/.venv/bin/python ingestion/states/montana/<script>.py
```

The script's `from ingestion.lib.X import ...` calls at module load resolve via the editable install regardless of cwd. Surfaced during S03.1 implementation when an initial `python -m ingestion.states.montana.fetch_pdfs` invocation example was written into the orchestrator's docstring and tested wrong before commit.

Surfaced by S03.1 implementation on 2026-05-04.

### Adapter-module tests should use direct `import`, not `importlib.util.spec_from_file_location`

State-adapter scripts under `ingestion/states/<state>/*.py` are NOT a Python package (`states/` has no `__init__.py`), but the editable install adds `ingestion/` to `sys.path` so `import states.montana.<module>` resolves cleanly as a namespace package. Every adapter test in `ingestion/tests/test_load_*.py` uses this direct-import pattern — for instance `test_load_state_boundary.py` does `from states.montana.load_state_boundary import _build_source_citation, ...`. A `_load_module()` helper using `importlib.util.spec_from_file_location(...)` + `exec_module(...)` is the wrong shape for this codebase: it adds dead-code overhead (path computation, type-narrowing assertions, ModuleType import) for a problem that the editable install already solved.

The trap is that the `importlib.util` path *works* — tests pass — so the divergence is invisible at run time. Reviewers (static-analysis agent in S03.6's review cycle caught this) only spot it by comparing against peer test files. Surfaced during S03.6's Stage 6 review and corrected in the review-fix cycle.

### `supabase db push` against a project bootstrapped via dashboard fails with "relation already exists"

When a Supabase project's schema was originally created via the dashboard SQL editor — or via `supabase db push` from a different machine with a different local migration history — the remote `supabase_migrations.schema_migrations` tracker can be empty even though the schema is fully populated. The next `supabase db push` then attempts to replay all migrations from scratch and dies on the first `CREATE TABLE` with `relation already exists` (SQLSTATE 42P07).

**Diagnose:** `SELECT version FROM supabase_migrations.schema_migrations ORDER BY version;` — if the result is empty or missing entries that should be there, the tracker is out of sync.

**Fix:** mark each pre-existing migration as applied without re-running its SQL:

```sh
supabase migration repair --status applied <timestamp>
```

Run once per migration that's already reflected in the schema, then `supabase db push` will only apply what's actually pending. **Verify the schema state matches the migration first** (e.g., check `information_schema.columns` for the columns each migration adds) before running repair — `repair` is a meta-state lie if the schema and migration history have actually diverged.

Surfaced by S03.0 deployment on 2026-05-04.

### Subagent-authored docs can reference stale task IDs from earlier plan drafts

**Symptom:** An AC table or working note produced by a subagent references task numbers (e.g., T2–T9) that don't match the final plan's task numbering (e.g., T1–T11). The orchestrator only notices during spot-check.

**Cause:** Long `/roughly:build` pipelines go through multiple plan-revision cycles before the final plan is locked. A subagent dispatched at a later stage may carry forward an earlier plan draft's task numbering in its internal context, especially if the earlier draft was included in the prompt verbatim.

**Fix:** When dispatching a subagent that writes long-form docs referencing task IDs, include the final locked task list in the dispatch prompt verbatim and explicitly direct the subagent to consult the final plan file. On return, spot-check the generated doc against the final plan file before marking the stage complete — look for any T-number reference and verify it matches.

Surfaced by S03.8 Stage 8 wrap-up on 2026-05-18.

## Conventions — Ingestion adapters

### Serialize committed extraction artifacts one-record-per-line, not `indent=2`

Committed `ingestion/states/<state>/extracted/*.json` fixtures are large (hundreds–thousands of records). `json.dumps(..., indent=2)` inflates them roughly two orders of magnitude in line count — S06.3's `big-game-2026.json` (a JSON array of **737 section records**, with **2,758 rows** nested within them) was **103,854 lines** pretty-printed. That blows past code-review line-count limits: cubic refuses any PR over **50,000 changed lines**, and GitHub computes the PR's raw `+/-` line count from the diff — **`.gitattributes` (`-diff` / `linguist-generated`) does NOT reduce it** (those only affect display and language stats; verified — the PR still reported +108,201 with `-diff` set). The only fix that works is reducing the actual committed line count.

Use the shared helper **`ingestion.lib.pdf.write_extraction_artifact(records, path)`** (not a hand-rolled `json.dumps`). It writes one compact record per physical line inside the JSON array (`[\n{rec},\n{rec}\n]\n`): still valid JSON, still `json.load`-parseable, still diffable per record, but ~one line per record instead of ~100. S06.3's artifact dropped 103,854 → 739 lines (737 section records + 2 array-bracket lines; PR 108,201 → ~5,100 changed lines). Determinism is preserved (pass a pre-sorted `records`; the helper dumps each with `sort_keys=True`; embedded newlines in string values are JSON-escaped so each record stays one physical line). It also does the atomic `.tmp`+`replace` write and creates the parent dir.

Every NEW extractor must use this helper. The Montana extractors (`extract_dea.py`, `extract_black_bear.py`, `extract_legal_descriptions.py`) still pretty-print with `indent=2` — `dea-2026.json` is already **47,956 lines**, one bigger brochure from the 50k cap; migrate them to the helper at their next re-extraction (a format-only change: re-pin the determinism SHA, data unchanged).

### Extractors AND loaders are one module per state — do not split on a reviewer's "monolithic module" flag

Each state's PDF extractor is a single `.py` module organized into labelled sections (probe notes → constants/TypedDicts → cleanup helpers → hunt-code/season-window parsing → table-block parsing → confidence → orchestrator → CLI). They are large by design: MT `extract_dea.py` 1,655 LOC, `extract_black_bear.py` 1,978, `extract_legal_descriptions.py` 1,372; CO `extract_big_game.py` 2,685. **There is no multi-module/package extractor precedent in the repo.** Code reviewers (cubic included) recurrently raise a P2 "monolithic module, hard to evolve / split into focused modules" finding against these — it surfaced **three times** against CO `extract_big_game.py` alone (S06.3). It is a valid *observation* but **declining it is the correct, deliberate call**, for three reasons: (1) the coupling risk it cites is mitigated by the per-state test suite (artifact-regression locks on exact section/row/confidence counts + SHA; per-layer unit tests; AST isolation guards) — a change that breaks one part fails a test immediately, not in production; (2) splitting *one* state into a package while the other three stay single-module is *less* consistent, not more; (3) extractor modularization is a project-wide architectural decision (an ADR applying to every state + a shared structure), **not** a unilateral per-story refactor of just-merged, cubic-clean, fully-tested code. If the team ever wants modular extractors, that's an ADR (`docs/adrs/`) authored by a human or an ADR-drafting session — not an in-review code change. **Formalized 2026-06-16 as [ADR-022](../docs/adrs/ADR-022-single-module-per-state-extractors.md) (Accepted)** — the canonical, citable record of this decision; modularization is reopened only by a future ADR that supersedes ADR-022 and applies uniformly across all state extractors in one PR. Until then: acknowledge the finding, cite ADR-022, and move on. **The same disposition covers per-state DB loaders (`load_*.py`)** — each is one labelled-section module (constants → artifact loaders → pure builders → validators/guards → three-phase `main()` → CLI); CO `load_seasons_and_licenses.py` 1,924 LOC, MT 1,538, CO `load_draw_specs.py` 1,093. The "split the loader / split its tests" finding was declined at the S06.6 closure and again at S06.8; **ADR-022 was amended 2026-06-27 to name loaders explicitly**, so the loader case is dispositioned identically — cite ADR-022 and move on.

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

### "MT GIS layers" can live on FWP on-prem, FWP AGOL org, OR the Montana State Library MSDI catalog

Montana state-published GIS data lives on **three** distinct hosts, not just two. Discovery work that enumerates only one or two will miss layers that exist on the third.

1. **MT FWP on-prem MapServer** — `https://fwp-gis.mt.gov/arcgis/rest/services?f=json` (every folder, every service). Where `admbnd/huntingDistricts` lives.
2. **MT FWP ArcGIS Online org** — sharing search `https://www.arcgis.com/sharing/rest/search?q=<keyword>+montana&f=json`, filter by `owner=MtFishWildlifeParks` afterward (the Hub v3 API is unreliable: 502/504 on multiple endpoints during S02.5 investigation; the sharing REST API is the dependable fallback). Where the `ADMBND_HD_CWD` FeatureServer lives.
3. **Montana State Library MSDI Framework catalog** — `https://gisservicemt.gov/arcgis/rest/services?f=json`. Hosts state-published reference layers (boundaries, hydrography, transportation) NOT visible from the FWP catalogs. The state boundary lives at `MSDI_Framework/Boundaries/MapServer/9` (used by S03.0 for `MT-STATEWIDE-geom`).

Empirical pattern from across S02 + S03:

- S02.4's "no CWD rows in layer #2" was correct for the on-prem catalog; S02.5's `ADMBND_HD_CWD` find on the AGOL org would have been missed if discovery stopped at on-prem.
- S03.0's "no FWP state-boundary layer" was correct for both FWP catalogs (on-prem AND AGOL); the MSDI Framework Boundaries layer would have been missed if discovery stopped at FWP.

When asked "does MT have a layer for X," check all three hosts before concluding "no published source exists." Document which host the layer was found on in the SourceCitation `agency` field (e.g., `"Montana State Library"` for MSDI vs. `"Montana Fish, Wildlife & Parks"` for FWP) — both qualify as `document_type='gis_layer'` per ADR-014, but agency provenance still matters for citation accuracy.

Surfaced by S02.5 investigation on 2026-05-01; extended to MSDI by S03.0 source investigation on 2026-05-04.

### `expected_sha256` in `sources.yaml`: a real pin IS enforced on first fetch; `unknown`/absent is documentation-only; the manifest is the re-fetch drift gate

There are TWO independent SHA gates in `ingestion/ingestion/lib/pdf_fetch.py`, and they answer different questions:

1. **Manifest re-fetch drift gate** (since S03.1): compares the observed SHA against the prior committed `*-pdf-manifest.json` `pdf_sha256`. Fires only on a *re-fetch* (a prior manifest must exist). Writes a `*-pending-reextraction.flag` marker + raises on drift. It does NOT read `sources.yaml`.
2. **Expected-SHA pin gate** (since S06.1): `fetch_pdf` takes an optional `expected_sha256` param; when the caller passes a *real* 64-char lowercase hex pin (not the `"unknown"` sentinel, not `None`), the fetched bytes must match it or `PdfFetchError` is raised **before any PDF/manifest is written** — on EVERY fetch including the first. A malformed non-`"unknown"` value fails loud. This closes the trust-on-first-use gap (gate 1 can't fire on the first fetch, so without gate 2 a corrupt/wrong/stale first fetch would silently become the baseline).

Consequences / how to use it:

- `"unknown"` (the M1 default for un-verified entries) and an absent field both SKIP gate 2 — so Montana, whose entries are all `expected_sha256: unknown`, is unaffected by the S06.1 change. The orchestrator must opt in by passing `expected_sha256=entry.get("expected_sha256")` to `fetch_pdf` (CO's `fetch_pdfs.py` does; MT's does not, since it has no real pins).
- For an entry with a real pin, the first fetch is now gated: pin only AFTER the operator has out-of-band downloaded + byte-verified the document (the S06.0/D4 pattern), because the automated fetch must match the pin exactly.
- Gate 1's "first run records the observed SHA unconditionally" behavior still holds for `unknown`/un-pinned entries.

Surfaced by S03.1 (2026-05-04, gate 1) and refined by S06.1 (2026-06-09, gate 2 — the first CO entries carried real operator-verified pins; an unenforced pin was flagged as a first-fetch integrity P2).

### `sources.yaml` URL slug ≠ publication cadence — confirm cadence by reading the PDF, not the URL

**Symptom:** A spec table claims a source is "biennial 2026/2027" or "annual 2026", but the actual file on the agency CDN is named in a way that contradicts the spec — e.g. spec says biennial but the URL slug is just `2026-...`.

**Cause:** Spec authors infer cadence from the document's *content* (cover page, internal validity dates), but URL slugs encode whatever filename the agency's CMS chose for the binary. The two are independent. FWP's CDN names the DEA file `2026-dea-regulations-final-with-low-resolution-maps-for-web.pdf` even when (per PRD assumption) it covers the 2026/2027 biennium internally. The slug is not the contract.

**Fix:** Treat the URL slug as opaque. Confirm cadence by reading the PDF cover page — that is the authoritative source for "this document covers years X through Y." If the slug and content disagree, name the citation id after what the document *contains*, not what the URL string says (or rename to match the URL if the content is also single-year — which is what we did for `mt-fwp-dea-2026-booklet`).

Two concrete consequences:

- `sources.yaml` `id` and `title` should reflect document content, not URL slug verbatim.
- `expected_page_count` is a sanity-check claim, not a contract. The first live fetch reveals the true page count; pin `expected_sha256` only after the document content has been visually confirmed to match the spec's intent (or the spec has been amended).

**Surfaced 2026-05-07 during S03.3 unblock**: spec table called DEA "Biennial 2026/2027" but the FWP file is named `2026-dea-regulations`. Renamed citation id from `mt-fwp-dea-2026-2027-booklet` → `mt-fwp-dea-2026-booklet` (URL-truthful). Cover-page cadence to be verified at S03.3 first fetch. Three other URL slugs corrected in the same pass — all four were spec-table guesses that didn't survive contact with the live FWP CDN.

### YAML fields with placeholder substrings need an inline comment warning against direct reads

**Symptom:** A YAML entry contains a field like `id_template: "co-cpw-arcgis-cpwadmindata-6-{license_year}"` — a documentation-only template, not a runtime format string. A future implementer skims the YAML, reads `entry.get("id_template")`, and passes the placeholder-bearing string directly to the database, persisting the literal `{license_year}` unsubstituted.

**Cause:** Field-level inline comments are much harder to miss than top-level header comments. Without a warning on the specific line, the field name (`id_template` rather than `id`) is the only signal that the value requires derivation at load time.

**Fix:** For any YAML field whose value is a documentation-only template, add a one-line inline YAML comment immediately above or on the field documenting "do NOT read directly — runtime-generated by `<builder function name>`". Use a field name that signals template intent (e.g., `id_template` not `id`). Surfaced by S05.1 Stage 5 review of `ingestion/states/colorado/sources.yaml`; the actual `SourceCitation.id` is derived at load time by `arcgis.build_source_citation` from `state_slug + service_url + layer_id + license_year`.

### Read-only scripts must still fail loud on empty source data

**Symptom:** A script that only reads from the database (no upserts, no commits) silently produces empty output — e.g. a 2-byte `[]` fixture — and reports success when its source query returns zero rows.

**Cause:** The fail-loud discipline is typically associated with writers (zero features written = loader bug). Readers feel safe because they can't corrupt data. But a reader that produces empty output on missing prerequisites is equally misleading: downstream consumers see valid-looking empty data instead of an error pointing to the missing loader.

**Fix:** After the first foundational query (e.g. fetching HD IDs), check whether the result is empty. If a non-empty result is required for the script to do meaningful work, raise a script-specific exception with a message naming (a) what was queried, (b) the state/scope filter, and (c) which upstream loader the operator must run first. Do not log-and-continue or produce empty output.

Concrete example: `ingestion/states/montana/build_overlay_fixture.py` lines 166–172 raise `OverlayFixtureError` when `_fetch_hd_ids(conn)` returns empty, naming `load_hds.py` as the prerequisite. Extends the zero-features writer convention (see "Single atomic commit" entry) to the reader side.

Surfaced by S02.6 implementation on 2026-05-01.

### Spec-table BMU/HD lists must be cross-checked against the live PDF

- **Spec-table BMU/HD lists must be cross-checked against the live PDF.** The Black Bear 2026 spec listed 9 quota-closure BMUs; the actual PDF has 8 (BMU 530 absent). Use `re.findall(r"\d{3}", verbatim_rule)` against a constants tuple as a fail-loud drift guard at extraction time. Scope the drift guard to the first sentence to avoid phone-number digits (e.g., 385, 444, 800) contaminating the BMU set.

### Correction-merge arbitration is doc-type-precedence, not date-precedence

- **Correction-merge arbitration is doc-type-precedence, not date-precedence.** When merging a correction PDF with an annual_regulations booklet, `document_type='correction'` always wins over `'annual_regulations'` regardless of `publication_date`. Date is used only for tiebreaking among same-doc-type sources. The naive "MAX date wins" rule silently inverts intent when a correction is published BEFORE the booklet it corrects (Montana 2026 case: correction `2026-03-18` < booklet `2026-04-27`). Reference: `_merge_with_corrections` in `extract_black_bear.py`.

### BMU/HD identifier regexes must handle footnote-marker suffixes

- **BMU/HD identifier regexes must handle footnote-marker suffixes.** Female-sub-quota BMUs in the Montana Black Bear booklet carry a trailing asterisk (`"300*"`, `"580*"`) as a footnote marker. Capture the digits and strip the suffix at parse time (`re.compile(r"^(\d{3})\*?$")`).

### Multi-iteration state writes must hoist out of the loop

- **State-overwriting loops are dict/list-iteration-order-dependent.** When a `for X in collection: state.attr = X[...]` loop runs more than once and `collection` has a non-deterministic order (Python dicts preserve insertion order but the *insertion* itself may be order-dependent on upstream code), the final value of `state.attr` reflects whichever element was iterated last. The build pipeline for S03.4 caught this twice in `_merge_with_corrections`: row-level `source_id`/`source_publication_date` and `extraction_confidence` were both being overwritten on every `(bmu, field)` iteration, producing dict-order-dependent provenance and N-times-demoted confidence for rows touched by N field-level ops. **Rule:** hoist any per-row state assignment out of the per-cell loop into a separate post-loop pass keyed on the row, so each row's state is computed exactly once from a deterministic input. Reference: `_merge_with_corrections` Stage 3 in `extract_black_bear.py` for the canonical pattern (Stage 1 selects winners per cell; Stage 2 applies cell values; Stage 3 updates row-level state once per touched row).

### `max()` / `min()` with comparable ties need an explicit secondary key

- **`max(items, key=...)` and `min(items, key=...)` are list-iteration-order-dependent on ties.** When the keying function returns equal values for two or more items, `max` / `min` returns the first one encountered. For deterministic semantics across re-runs (e.g., re-generating an artifact whose SHA must be byte-stable), use a tuple key with a secondary sort field, OR do a two-pass selection: filter to ties, then pick by the secondary criterion. The S03.4 row-provenance code uses the two-pass form: `max_date = max(op["source_publication_date"] for op in ops); date_ties = [op for op in ops if op["source_publication_date"] == max_date]; row_winner = min(date_ties, key=lambda op: op["source_id"])` — lex-smallest `source_id` breaks ties. Reference: `_merge_with_corrections` row-provenance selection in `extract_black_bear.py`.

### `regulation_record` has no `verbatim_rule` column — section text decomposes onto child entities

- **`regulation_record` is a pure anchor; section verbatim text decomposes onto S03.7's child entities.** The DDL (`supabase/migrations/20260425000000_initial_schema.sql:36-49`) and the `RegulationRecord` Pydantic model (`ingestion/ingestion/lib/schema.py:221-238`) define this table as `(PK, source, confidence, schema_version, ingested_at) + additional_rules: VerbatimRule[]` — no `verbatim_rule` field. A loader for `regulation_record` MUST NOT attempt to write a section-level `verbatim_rule`. The DEA section's `verbatim_text` decomposes onto `season_definition.verbatim_rule` (per-window) and `license_tag.verbatim_rule` (per-license-row) via S03.7; HD-wide `NOTE:` lines are captured by S03.6 in `additional_rules`. Resolution recorded in `docs/open-questions.md` Q15 and epic footnote `[^oq1]` at line 565. Reference: `_build_dea_records` + `_build_bear_records` in `load_regulation_records.py`.

### `db.update_legal_description` fails loud on `cur.rowcount == 0`

- **Targeted UPDATE helpers must raise when the WHERE clause matches no row.** `update_legal_description(conn, geometry_id, text)` in `ingestion/lib/db.py` runs `UPDATE geometry SET legal_description = %s WHERE id = %s` and raises `RuntimeError` if `cur.rowcount == 0`. A silent no-op would mask matcher bugs — e.g., the S03.5 extractor emitting a `geometry_id` that doesn't exist in the `geometry` table because of E02 fixture drift. The same pattern should apply to any future targeted UPDATE helper added to `db.py` for child entities.

### DEA `species_group="deer"` requires fan-out to `mule_deer` + `whitetail`

- **The DEA artifact uses booklet-column species labels; the DB schema uses granular species values.** The DEA extraction artifact emits `species_group ∈ {"deer", "elk", "antelope"}` because those are the species column blocks in the FWP DEA booklet. The `regulation_record.species_group` DB column uses `{"mule_deer", "whitetail", "elk", "pronghorn", "bear"}`. The mapping is: `"deer"` fans out to **two rows** (`mule_deer` + `whitetail`) sharing the same per-HD verbatim/source/confidence; `"elk"` stays as `"elk"`; `"antelope"` renames to `"pronghorn"`. A naive `1:1` for-loop is wrong. Reference: `_DEA_SPECIES_FANOUT` and `_build_dea_records` in `load_regulation_records.py`. Locked by `test_deer_fans_out_to_mule_deer_and_whitetail`.

### Bear DB `species_group` is `"bear"`, NOT the artifact's top-level `"black_bear"`

- **The Black Bear extraction artifact's top-level `species_group` field is `"black_bear"`. The `regulation_record.species_group` DB value is `"bear"`.** Mixing the two produces silent FK mismatches against any future cross-table query joining on species. Reference: `_build_bear_records` in `load_regulation_records.py` (literal `species_group="bear"`). Locked by `test_bear_species_group_is_bear_not_black_bear`.

### Confidence MIN-aggregation must use `ConfidenceTier.min_tier`, not bare `min()` over strings

- **`min(["high", "low"])` returns `"high"` lexicographically** because `"h" < "l"` in ASCII order. The S03.2 `pdf.ConfidenceTier.min_tier` helper uses `key=lambda t: t.rank` so the most-uncertain tier wins ADR-017-faithfully. Loaders that aggregate confidence across multiple extraction rows MUST call `min_tier`, not the builtin. Reference: `pdf.py` lines 121-150 (helper); `_build_dea_records` in `load_regulation_records.py` (call site). The trap case is locked by `test_confidence_min_tier_trap_case_high_low_returns_low`.

### Closed-set kind/category heuristics require full-artifact profiling before plan finalization

- **Profile the FULL extraction artifact before writing a closed-set categorization branch list.** S03.7's `_build_dea_license_tags` uses `else: raise RuntimeError` on an unmatched `kind`. The initial plan listed 3 branches (general / B License / statewide). Plan-review caught that 121 of 1190 rows (91 `"Deer Permit: …"` / `"Elk Permit: …"` rows + 30 per-HD `"Antelope License: XYZ"` rows) would have aborted — two additional code families not in the spec. The plan was revised to 5 branches before implementation. The rule: for any `if/elif/else: raise RuntimeError` over a closed-set label (`license_kind`, `species_group_label`, `season_key`, `document_type`), run `collections.Counter(row[field] for row in artifact)` against the full artifact and enumerate every value seen before writing the branch list. Surfaced by S03.7 plan-review 2026-05-15.

### Pydantic `frozen=True, extra="forbid"` models — enumerate every required field at construction time

- **When constructing Pydantic models with `ConfigDict(frozen=True, extra="forbid")`, mechanically enumerate every field with no default and no `Optional` annotation before writing the constructor call.** A missed required field raises `ValidationError` at the first production row, not at import time. The cost at plan-review is one revision cycle; at runtime it is a full re-run plus a debug cycle to locate which builder omitted which field. Example: `schema.py:ClosurePredicate.notification_channel` has no default — S03.7 plan-review caught a T8 draft that didn't read it from the artifact. Fix: grep `schema.py` for the model class, list all fields that have no `= ...` or `Optional` annotation, and verify each is read from the artifact dict at the call site. Surfaced by S03.7 plan-review 2026-05-15.

### DEA artifact has duplicate `license_code` rows within sections — let UPSERT collapse, not the builder

- **Some DEA sections contain two rows with the same `license_code` value (202 sections affected in V1 Montana DEA).** Both rows produce the same deterministic `license_tag.id` and collide at the UPSERT layer. The semantic payload is the UNION of `season_coverage` across same-code rows; license-level fields are structurally identical across duplicates. **Do NOT pre-deduplicate in the builder.** Emit both rows; let the UPSERT `ON CONFLICT (id) DO UPDATE` collapse duplicate `license_tag` rows, and let `license_season` link rows collapse via `ON CONFLICT DO NOTHING`. Pre-deduplicating in the builder requires a parallel accumulator, adds complexity, and doesn't express the union semantic cleanly. Reference: `_build_dea_license_tags` in `load_seasons_and_licenses.py`. Locked by `test_duplicate_license_code_rows_collapsed_by_upsert`. Surfaced by S03.7 implementation 2026-05-15.

### Downstream FK adapters must grep upstream adapters for exact id-construction patterns

- **Before writing any adapter that populates a link table whose composite FK targets a previously-loaded entity, grep the upstream adapter for the exact id-construction expression and copy it verbatim.** A single-character drift in jurisdiction_code, species_group, license_year, or any other FK component breaks every link-row insert with a FK violation that is hard to diagnose (the error names the constraint, not which field drifted). Example: S03.7's bear builders use `jurisdiction_code = f"MT-HD-bear-{bmu_number}"` — this must match S03.6's `load_regulation_records.py:366` exactly. Pattern: add a code comment at the call site naming the upstream adapter and the line number where the original expression lives, e.g. `# must match load_regulation_records.py:366 exactly`. Optionally lock with a cross-module test that constructs both ids from the same fixture and asserts equality. Surfaced by S03.7 implementation 2026-05-15.

### DEA cross-listed B Licenses can carry conflicting structural fields across HD sections

**Symptom:** A `draw_spec` builder that groups rows by `license_code` and assumes same-code rows are structurally identical silently writes the wrong quota (or wrong hunt_code) — whichever row happened to be processed last wins.

**Cause:** A single `license_code` (e.g., `Elk B License: 210-03`) can appear in multiple DEA HD sections. The home-HD section shows the total drawable quota; cross-listed mentions in other HD sections show per-HD allocation caps — different `quota` values, same `license_code`, identical `extras` text. The DEA artifact faithfully records each appearance; collisions surface only when the adapter groups by `license_code` to build one `draw_spec` row per license.

**Real example (DEA 2026, pp. 53/54/57):** `Elk B License: 210-03` appears with `quota=300` in HD 210 (home) and `quota=200` in HDs 211, 212, 216 (cross-listed). Detail text is identical on all four rows: `"Valid on private lands in HDs 211, 212, 216 and south portion of 210..."`.

**Fix:** Pre-write consistency validator that groups draw_spec candidates by `(hunt_code, year)` PK; fail-loud on undocumented field conflicts; allow override entries in `_KNOWN_CROSS_LISTING_OVERRIDES` with a WARN log + rationale string. Reference: `_validate_cross_listing_consistency` in `ingestion/states/montana/load_draw_specs.py`. The per-HD allocation-cap structural gap (home vs. cross-listed quota semantics) is deferred to M2 per `docs/open-questions.md` Q17.

**Why it matters for future adapters:** The "same `license_code` = same data" assumption is FALSE for FWP DEA tables. Any adapter that builds entity rows keyed on `license_code` must validate cross-row structural agreement at build time, before writing.

Surfaced by S03.8 Stage 6 silent-failure-hunter on 2026-05-18.

### DEA `license_tag.kind` requires inspecting `apply_by`, not just `license_code`

**Symptom:** All B License rows are classified as `limited_draw`, but 160 of them are actually over-the-counter purchases — wrong `draw_spec` rows are written (or attempted) for OTC licenses.

**Cause:** A B License row's `license_code` alone (e.g., `Deer B License: 262-50`) does NOT discriminate drawing-eligible B Licenses from OTC B Licenses. The discriminator is the `apply_by` column: cells containing `"OTC:\nJun 15"` (or any `OTC:` prefix) indicate an OTC purchase window; cells containing only a date (e.g., `"Jun 1"`) indicate a drawing deadline. S03.7's original 5-branch heuristic classified all B License rows as `kind='limited_draw'` before S03.8 corrected it.

**Compounding factor:** The same `(species, hd_number, license_code)` triple can appear in multiple artifact rows with different `apply_by` values (extraction noise from S03.3's table structure). Apply OTC-wins discipline: any artifact row showing OTC demotes ALL rows of that identity to `over_the_counter`.

**Fix:** Pre-pass computes `_otc_identities: frozenset[tuple[str, str, str]]` from all artifact rows; per-row classification consults the set before assigning `kind`. `apply_by` must be type-guarded (`isinstance(str)`) before substring matching — raise on schema drift rather than silently defaulting. Reference: `_build_dea_license_tags` in `ingestion/states/montana/load_seasons_and_licenses.py` (post-S03.8 T1 amendment). Baseline post-fix: 390 `limited_draw` / 160 `over_the_counter` / 239 `general` / 1 `statewide`.

Surfaced by S03.8 Stage 2 discovery probe on 2026-05-17.

### DEA front-matter carries authoritative deadlines when per-row `apply_by` is genuinely null

**Symptom:** A `draw_spec` row has `application_deadline=None` even though the FWP source has a published deadline for that species/kind combination.

**Cause:** When a DEA per-row `apply_by` cell is genuinely blank (FWP chooses not to repeat the deadline in-table when it's already in the booklet's front-matter), the per-row extraction faithfully records `apply_by=None`. The canonical deadline lives in the DEA booklet's front-matter sections: pp. 5 "Highlights", p. 9 "Important Dates", pp. 10–11 "License Charts". This is not an extraction defect — the cell is blank by design.

**V1 chart values (DEA 2026, MT):**

- Deer/Elk Permit: April 1
- Deer/Elk B License (Drawing) + Antelope License + Antelope B: June 1

**Fix:** Adapter-level fallback lookup `_DEA_DEADLINE_LOOKUP: dict[tuple[str, str], date]` keyed on `(species, kind_token)` and populated from the front-matter chart values. Apply only when per-row `apply_by` is null; emit a WARN log on each hit (expected zero hits in V1 — any hit in production signals PDF drift and needs operator review). Reference: `_DEA_DEADLINE_LOOKUP` in `ingestion/states/montana/load_draw_specs.py`.

Surfaced by S03.8 Stage 2 B4 probe on 2026-05-17.

### E03 story discovery — source-audit upstream artifacts for every epic-required row type before planning

**Symptom:** An epic spec enumerates N output rows ("ingest 3-4 statewide reporting obligations: CWD sampling, Bear ID coursework, mandatory reporting, …"), but during implementation the upstream extraction artifact is missing the source text for one or more of them. Mid-pipeline gate decisions, scope-down probes, and unplanned upstream-amendment carve-outs result.

**Cause:** Story specs are authored against expected source content (often based on prior-year PDFs or web pages); the upstream-artifact extraction job that S03.X depends on may not have captured each named row type. Without a pre-plan audit, the mismatch surfaces only after the discovery agent's codebase trace — late, expensive, and gate-blocking.

**Fix:** The discovery agent's FIRST action for any S03.X story should be: enumerate the row types named in the epic spec, then grep the named upstream extraction artifacts for keywords matching each. Cheap (one grep per row type), catches scope mismatches before they reach the plan-review stage. Pattern bit twice — S03.8 B5 (Permit-row sub-rows missing from artifact), S03.9 three-blocker (Bear ID coursework, CWD sampling unified section, all-species mandatory reporting all missing from artifact).

Surfaced by S03.9 Stage 2 three-blocker probe on 2026-05-19.

### `reporting_obligation.kind` semantic boundary — post-harvest / in-season only

**Symptom:** A rule that is a pre-purchase licensing prerequisite (e.g., Bear Identification Test, hunter education certification) gets modeled as a `reporting_obligation` row with `kind="mandatory_check"` or a new `kind="education"` enum value.

**Cause:** `reporting_obligation` is defined in CLAUDE.md as "post-harvest/in-season duties." Pre-purchase prerequisites are operationally distinct — the hunter must complete them BEFORE they can buy the license, not AFTER they harvest an animal. Conflating the two would mis-answer consumer queries like "what mandatory checks does a successful hunter perform?" because the same `kind="mandatory_check"` value would mix check-station physical inspection of harvested animals with one-time pre-purchase certification.

**Fix:** Pre-purchase prerequisites belong in `regulation_record.additional_rules` keyed by a STATEWIDE anchor (e.g., `MT-STATEWIDE-bear`), mirroring the existing `MT-STATEWIDE-antelope` pattern from S03.6. The decomposed-entity story (ADR-010) is the right home for STATEWIDE pre-purchase rules; do not extend `reporting_obligation` to carry rules that aren't reporting or obligations. Concrete carve-out example: S03.6.1 (queued post-S03.9) writes `MT-STATEWIDE-bear` with the Bear ID Test verbatim text in `additional_rules`.

Surfaced by S03.9 Probe 1 on 2026-05-19 (PM reversed the initial "fold into S03.9" recommendation after the target-table mismatch was identified).

### `id text`-PK UPSERTs currently update slug-encoded fields on conflict — Q19 tracks the project-wide drift-guard fix

**Symptom:** A dispatch-dict edit changes a slug-encoded structured field (e.g., `kind`, `deadline_hours`, `applies_to_regions`, `weapon_type`, `residency`, `license_code`, `species`) but the corresponding `id_suffix` / id-derivation stays the same — and the next re-ingestion run silently rewrites the meaning of existing rows under the same `id` via the helper's `ON CONFLICT (id) DO UPDATE` clause. Any link-table rows (`license_season`, `regulation_season`, `regulation_license`, `regulation_reporting`) already pointing at that id now reference an entity whose semantics shifted.

**Affected helpers** (all in `ingestion/ingestion/lib/db.py`):

- `_UPSERT_SEASON_DEFINITION_SQL` (S03.7) — updates `name`, `weapon_type`, `residency` on conflict
- `_UPSERT_LICENSE_TAG_SQL` (S03.7) — updates `license_code`, `name`, `kind`, `species` on conflict
- `_UPSERT_REPORTING_OBLIGATION_SQL` (S03.9) — updates `kind`, `deadline`, `applies_to_regions` on conflict

**Cause:** For all three `id text`-PK tables, the `id` slug is a hand-encoded string built from a subset of the entity's structured fields (e.g., `mt-bear-harvest-report-48hr-statewide` encodes kind+deadline+scope). The UPSERT has no way to know "the slug came from these fields, but the fields have changed" — both states satisfy the conflict clause; DO UPDATE wins by definition. The risk is dormant during initial V1 ingestion (fresh DB, no conflicts) but becomes load-bearing on the first year-over-year re-ingestion run.

**V1-safe right now:** Closed compile-time dispatch dicts (no operator-runtime mutation path); unit tests lock canonical slug↔field pairings; V1 ingestion runs once against fresh artifacts. The project-wide fix shipped via ADR-020 (`ingestion/ingestion/lib/drift_guard.py`) — use `assert_dispatch_dict_drift_free(dispatch, derive_id, *, helper_name, id_field)` for compile-time dispatch-dict surfaces (S03.9 pattern) and `assert_id_matches(entity_id, expected_id, *, helper_name, context)` for runtime construction-time surfaces (S03.7 pattern). The local `_assert_dispatch_dict_drift_free` previously in `load_reporting_obligations.py` is superseded by the shared primitive.

**Fix:** Resolved by ADR-020 (`docs/adrs/ADR-020-id-text-pk-slug-derivation.md`, Status: Proposed pending PM accept). For each `id text`-PK helper whose UPSERT DO UPDATE clause can rewrite slug-encoded fields, encode the id derivation as a pure callable and assert that every stored or constructed entity's id matches its derivation — drift becomes impossible by construction. Any new state adapter (M2+) writing to `season_definition`, `license_tag`, or `reporting_obligation` MUST adopt this pattern. New helpers writing to other `id text`-PK tables with mutable identity in UPDATE clauses MUST do the same.

Surfaced by S03.9 cubic-review round 3 on 2026-05-21; resolved on `fix/Q19-id-text-pk-slug-drift` on 2026-05-28.

### `submission_method` interpretation for multi-modal source text

**Symptom:** A `reporting_obligation`'s verbatim source text lists multiple submission channels (e.g., "deliver in person or by mail," "call 1-877-FWPWILD or use MyFWP portal at fwp.mt.gov"), but the schema `submission_method` Literal accepts ONE value. Picking arbitrarily creates audit-trail ambiguity; picking the wrong primary modality embeds wrong operational guidance.

**Cause:** Schema design is single-modality but real source text is multi-modality. The structured field is a lossy summary of the verbatim text.

**Fix:** Pick the FIRST channel mentioned in the verbatim (the headlined modality — the one the source authors led with). The full `verbatim_rule` preserves the source faithfully so the choice is non-lossy at the data layer; the structured `submission_method` is a hint, not authority. Document the call in the working note (which channel was picked, why, and what alternatives the verbatim lists). Concrete examples in V1 Montana bear reporting:

- STATEWIDE harvest_report: verbatim leads "Harvest Reporting ................. 1-877-FWPWILD or 1-877-397-9453 or 406-444-0356 or through the MyFWP portal at fwp.mt.gov" → pick `"phone"` (toll-free phone is headlined). `submission_phone="1-877-FWPWILD"`; `submission_url="https://fwp.mt.gov"` for the MyFWP-portal hint.
- R1 tooth_submission: verbatim says "deliver them to an FWP office within 10 days, either in person or by mail" → pick `"agency_office"` (FWP office leads; mail is the alternative).

Surfaced by S03.9 Probe 1 on 2026-05-19.

### Fail-soft extractor paths that defer loud failure to a downstream row-count guard must emit a visible warning at extraction time

**Symptom:** An extractor function that uses a regex anchor to locate a PDF region returns `[]` silently when the anchor doesn't match (anchor has shifted or PDF was regenerated from a stale source). The downstream row-count guard eventually raises `RuntimeError`, but by then extraction and loading may have run in separate sessions — hours or days apart.

**Cause:** Fail-soft early-return paths (`return []` instead of `raise`) are sometimes correct (anchor absence is a recoverable condition, not a programmer error). But "recoverable" does NOT mean "quiet." Without an extraction-time warning, the diagnostic latency between the silent extraction failure and the downstream OQ7-band RuntimeError is measured in sessions, not milliseconds.

**Fix:** When an extractor's fail-soft path defers loud failure to a downstream row-count guard, the extractor MUST emit `_logger.warning(...)` before the early return. The warning should name (a) the page number or page range probed, (b) the source PDF / source-id, and (c) a pointer to which downstream guard will catch the regression. This rule applies only to fail-soft returns — `raise RuntimeError` paths are already loud and need no additional warning. Reference: `_extract_statewide_rules` in `ingestion/states/montana/extract_black_bear.py` (S03.6.1 review — silent-failure-hunter W2 finding).

Surfaced by S03.6.1 Stage 6 review on 2026-05-22.

### `with db.connect()` context manager commits on clean exit — explicit `conn.commit()` inside is the real gate

psycopg3's `Connection.__exit__` calls `self.commit()` on a clean exit and `self.rollback()` on an exception. The project adapter pattern calls explicit `conn.commit()` inside the `with` block before `__exit__` runs; the implicit context-manager commit is therefore a no-op (the transaction is already closed). This is safe but can be confusing to a reader who asks "is there a double-commit risk?" There is not — the explicit `conn.commit()` is the real gate; the `with` is the rollback-on-exception safety net. The ordering must be documented in every adapter's commit site so a refactor doesn't accidentally remove the explicit call (believing the `with` covers it) and lose the fail-loud "commit only after all loops complete" discipline.

Surfaced 2026-05-23 during S03.10 Stage 6 silent-failure-hunter review. Reference: `load_jurisdiction_bindings.py::main()` commit site comment.

### Per-builder dedup sets miss cross-builder collisions — add a global dedup check in `main()`

**Symptom:** An adapter has two or more binding/entity builders, each maintaining its own `seen_ids: set[str]` for duplicate detection. A cross-builder collision — same `id` produced by two different builders — is invisible to both per-builder sets and produces a second UPSERT call rather than failing.

**Fix:** After collecting all built entities (`all_entities = builder_a_results + builder_b_results + ...`), run a global dedup check before the write phase:

```python
all_ids = [e.id for e in all_entities]
if len(all_ids) != len(set(all_ids)):
    dupes = [i for i in all_ids if all_ids.count(i) > 1]
    raise RuntimeError(f"Cross-builder id collision: {dupes}")
```

The per-builder sets remain useful for detecting intra-builder collisions early (fail at construction time, not write time). The global check is the final gate. Reference: `load_jurisdiction_bindings.py::main()` pre-write global dedup.

Surfaced 2026-05-23 during S03.10 Stage 6 code-review. Relevant for any adapter with 2+ builders producing the same entity type (S03.6.1 had separate statewide + per-HD builders; S03.10 has statewide + overlay + no-hunt-zone builders).

### `Model.model_validate(...)` inside a dict-comprehension swallows row identity on failure

**Symptom:** A Pydantic `ValidationError` surfaces with the raw field path but no indication of which source row, geometry ID, or dict key triggered it. A comprehension like `{str(row[0]): SomeModel.model_validate(row[1]) for row in rows}` loses the outer iteration variable when it raises.

**Fix:** Refactor any `model_validate` call inside a comprehension to an explicit for-loop with a try/except that wraps the identity:

```python
result: dict[str, SomeModel] = {}
for row in rows:
    entity_id = str(row[0])
    try:
        result[entity_id] = SomeModel.model_validate(row[1])
    except Exception as exc:
        raise RuntimeError(f"entity {entity_id!r} has malformed source jsonb: {exc}") from exc
```

Apply this pattern for any `model_validate` call that iterates over DB rows, artifact dicts, or YAML entries — the diagnostic value of knowing WHICH item failed is worth the extra lines. Reference: `load_jurisdiction_bindings.py::_fetch_geometry_sources` post-S03.10 review fix.

Surfaced 2026-05-23 during S03.10 Stage 6 code-review.

### Live-DB write is operator-driven — closure-note row counts describe dry-run-verified shape, not DB state

**Symptom:** A story's S03.X implementation plan or pre-flight probe runs `SELECT count(*) FROM regulation_record` and gets 0, even though earlier closure notes in CLAUDE.md describe "437 regulation_record rows" written at S03.6 close.

**Cause:** The CLAUDE.md closure narrative describes the adapter's output shape as verified by the dry-run path. Live writes only happen when an operator explicitly invokes the loader script. In the single-developer workflow, earlier story loaders may never have been invoked live (only dry-run); the T0 probe for S03.10 confirmed `regulation_record=0` and `jurisdiction_binding=0` despite 11 completed prior stories.

**Fix:** Any story that depends on prior loaders' DB state (e.g., S03.10 joining `regulation_record` to build bindings) must include an explicit operator pre-flight step to run the prior loaders in FK order. The T16 prerequisites block in `S03.10.md` is the canonical checklist format:

```bash
ingestion/.venv/bin/python ingestion/states/montana/load_state_boundary.py
ingestion/.venv/bin/python ingestion/states/montana/load_regulation_records.py
# ... in FK-safe order; then the current story's loader
```

Do not assume the DB matches the closure-note narrative. Probe DB state with a COUNT query at plan time. Surfaced 2026-05-23 during S03.10 T0 pre-flight probe.

### Discovery/ingestion stories can legitimately resolve to a documented gap — no loader required

**Symptom:** An ingestion story targets a named geometry type (e.g., CWD zones) and has ACs shaped around "≥1 row ingested" or "hand-traced fallback." After exhausting all spec'd investigation paths the source genuinely does not exist — no FeatureServer layer, no published boundary file, no agency-maintained polygon dataset.

**Cause:** Epic specs are written from available documentation; the assumption "there is a source to ingest" is sometimes wrong. CPW publishes no CWD-zone geometry for Colorado — CO manages CWD by hunt-code/GMU, not by regulatory polygon boundary. A prevalence/surveillance/monitoring map (if one exists) is NOT a regulatory boundary; hand-tracing it would invent data per ADR-001.

**Fix:** Before concluding a gap, exhaust ALL spec'd investigation paths: ArcGIS service-root catalog scan, org-wide ArcGIS Online search, published-document review. When all paths return empty, close the story with an investigation report + zero rows + no loader. Mark the ingestion-shaped ACs N/A-by-gap with a one-line rationale each. Do not force an ingest to satisfy an AC that assumed the source exists. The investigation report is the deliverable.

Surfaced by S05.3 on 2026-06-03 (CPW CWD zone discovery — no authoritative geometry source found; CO CWD managed by hunt-code/GMU).

### Subset gates are intentionally narrower than the full enum — document the exclusion, don't reflexively widen

**Symptom:** A schema-enum extension adds a new value (e.g., `no_hunt_zone`). A reviewer finds a `frozenset` gate in an adapter that does NOT include the new value and flags it as a missed sync site. Reflexively widening the gate would actually mask a real bug — a fixture row with `role_for_e03='no_hunt_zone'` in the MT overlay fixture would itself be wrong (MT no-hunt-zone bindings are handled by a separate builder that hardcodes the role and never consults this gate).

**Cause:** Not every enum-consumer site is a "full-enum mirror." Some are intentional subset gates that admit only the values valid for a specific data path. Reviewers unfamiliar with the gate's purpose can mistake narrowness for staleness.

**Fix:** Distinguish "full-enum mirror" sites (Pydantic `Literal`, DDL `CHECK`, TS union — must stay in sync) from "intentional subset gates" (validation `frozenset`s that admit only a curated subset for one data path — must NOT reflexively widen). When a subset gate excludes a newly-added enum value, add or confirm a comment on the gate explaining which values it excludes and why, so a future contributor doesn't read the narrowness as an oversight. A gate that correctly rejects a new value is detecting a potential bug; widening it silently removes that protection. Surfaced by S05.3.5 Stage-6 review: `_VALID_ROLE_FOR_E03` in `ingestion/states/montana/load_jurisdiction_bindings.py` deliberately excludes `no_hunt_zone` because that role enters via `_build_no_hunt_zone_bindings`, not through the overlay-fixture path the gate guards.

### Spec-provided reference SQL can hardcode a value a sibling constant is meant to own — bind the constant, don't copy the literal

**Symptom:** A spec hands the implementer both (a) a named constant (e.g., `_NO_HUNT_ZONE_NEARBY_DISTANCE_M: Final[int] = 5000`) and (b) an illustrative SQL snippet that embeds the same numeric literal (`... gmu.geom, 5000)`). The literal is wired directly into the query string; the constant becomes dead weight. A future recalibration of the constant does not flow into the SQL, and the query silently continues using the old value.

**Cause:** Spec snippets are illustrative. The literal in the snippet shows the INTENT; the constant is the source-of-truth. Copying the literal from the snippet instead of binding the constant is the natural shortcut, and both paths produce identical behavior on first run — making the drift invisible until a recalibration cycle.

**Fix:** When a spec provides a reference SQL snippet AND a named constant for the same value, treat the literal in the snippet as documentation only. Wire the constant as a bound `%s` parameter so any future recalibration takes effect without touching the SQL string. Mirror the MT precedent: `montana/load_jurisdiction_bindings.py` binds `_NO_HUNT_ZONE_NEARBY_DISTANCE_M` as a `cur.execute` parameter (around line 588); the literal `5000` never appears in the SQL string.

**Test corollary:** assert the SQL contains the placeholder (`gmu.geom, %s)`, not `gmu.geom, 5000)`) AND that the bound params include `_NO_HUNT_ZONE_NEARBY_DISTANCE_M`. A test that only asserts `_NO_HUNT_ZONE_NEARBY_DISTANCE_M == 5000` is tautological — it does not catch the SQL-vs-constant disconnect. Extends the "authoritative numbers drift between canonical documents — name the source-of-truth before copying" family (Conventions — Documentation & planning discipline): same root cause applied to spec-illustrative SQL.

Surfaced by S05.6 Stage-6 review (code-reviewer Critical + silent-failure-hunter W1, static-analysis concurring) on 2026-06-05.

### Row-drop logic must run before fixture and manifest writes — not after

**Symptom:** A loader fetches N features, writes the features fixture and manifest (recording `features_count=N`, `layer_hash=hash(N features)`), then drops rows that don't meet V1 scope criteria, and finally writes M < N rows to the DB. The fixtures and manifest describe the fetched set; the DB holds the kept set. The inconsistency is permanent — a re-run that drops the same rows will never produce a fixture that matches DB state.

**Cause:** The natural code order is: fetch → validate → write fixtures → filter → write DB. Filtering after fixture writes feels safe because the fixture captures raw upstream data. But the fixture's `features_count` and `layer_hash` are then describing a set the DB has never fully held.

**Fix:** Drop ineligible rows immediately after `_check_and_fix_projection` (fetch validation), before any fixture or manifest write. The `returnCountOnly` cross-check that validates the fetch stays on the RAW fetched count (it is verifying the network fetch, not the V1 scope). Only the fixture writes, manifest writes, and DB writes operate on the kept set, so all three agree. Reference: `ingestion/states/colorado/load_restricted_areas.py:_fetch_and_build` — Curecanti NRA dropped from 11 fetched → 10 kept before fixtures are written (S05.4 Stage 6 code-reviewer finding).

Surfaced by S05.4 Stage-6 code review on 2026-06-03.

### Count-band / row-count guards are not portable across states — re-derive from that state's discovery doc

**Symptom:** A count-band or minimum-row guard ported from a source-state adapter is numerically wrong for the target state because the underlying spatial/data relationship differs. Concretely in S05.5: Montana's overlay builder legitimately expects HD↔restricted-area pairs (most MT restricted areas overlap HDs; only 3 federal zones are orphans), so a "≥1 RA pair" guard would be reasonable there. Colorado's 10 restricted areas (National Parks / Monuments / Air Force Academy) are all expected orphans per `restricted-area-discovery.md` — they are adjacent to, not contained by, GMUs — so zero `restricted_area` cover/intersect rows is the CORRECT Colorado outcome. A blindly-ported `if ras and not ra_rows: raise` guard false-positive-fails the build on the correct CO case.

**Cause:** Guards that encode spatial-relationship expectations are implicitly state-specific. Copying them without re-deriving from the target state's discovery doc or research report silently imports the source state's assumptions.

**Fix:** Treat count-band and minimum-row guards as state-specific constants that must be derived from that state's discovery doc before writing the plan. The portable invariant is a structural fail-loud guard ("no parent-kind rows at all → unpopulated table → raise"); the relationship-count guard is data-driven and must be re-derived per state. Reference: S05.5 Stage-6 review-triad W2 (proposed-and-rejected MT-style guard, with rationale in `docs/planning/epics/E05-confidence-findings/S05.5.md` § "Stage-6 review record").

Surfaced by S05.5 Stage-6 review on 2026-06-04.

### Duplicate hunt codes across "Unit" sub-rows are a faithful extraction shape — the loader collapses, not the extractor

When one license covers multiple units, CPW lists each unit on its own sub-row sharing the same hunt code. The extractor must faithfully emit one row per sub-row (same `hunt_code`, differing `unit` / `valid_gmus` values). This matches the big-game artifact's shape (265 such groups in `big-game-2026.json`).

**Do NOT add extractor-side dedup.** Deduplicating in the extractor diverges from the sibling and loses per-unit faithfulness — the downstream regulation_record loader (S06.6) keys by hunt code and collapses identical rows via UPSERT. The duplication is a data property of the source, not an extraction artifact. Adding a dedup step would require a parallel accumulator, add complexity, and would silently suppress per-unit distinctions that may matter for future loaders.

Reference: S06.4 / S06.6 design decision; consistent with `ingestion/states/colorado/extract_big_game.py` multi-unit sub-row shape.

Surfaced by S06.4 real-PDF probe on 2026-06-13.

## Conventions — Pre-commit & secrets

### `detect-secrets` flags ArcGIS `serviceItemId` UUIDs as hex high-entropy strings

ArcGIS Online metadata fixtures (`*-metadata-*.json` files committed for drift detection) carry a top-level `serviceItemId` field whose value is a 32-character hex UUID — for example `"serviceItemId": "8837c07298054f5e8be2e072681d870c"` in the S02.5 `ADMBND_HD_CWD` fixture. The pre-commit `detect-secrets` hook (`HexHighEntropyString` plugin, `limit: 3.0`) flags this as a potential secret and blocks the commit.

These IDs are NOT secrets — they are publicly addressable URL components: `https://www.arcgis.com/home/item.html?id=<serviceItemId>` resolves to the public item page for any anonymous user. They are part of the "what" of the data, not credentials.

The fix when committing a new ArcGIS metadata fixture:

```bash
detect-secrets scan --baseline .secrets.baseline   # update baseline with new finding
git add .secrets.baseline
```

The new finding lands in `results` with `is_verified: false`. That is fine — `is_verified: false` means "not yet audited," which is sufficient for the hook to skip the file. Optionally run `detect-secrets audit .secrets.baseline` to mark the entry as a confirmed false positive (sets `is_verified: true`).

Do NOT use `git commit --no-verify` to bypass the hook. The system instructions forbid it, and it would defeat the hook's purpose for genuine secrets.

Surfaced by S02.5 commit on 2026-05-01.

### `detect-secrets scan` baseline refresh ignores untracked files

**Symptom:** Refreshing `.secrets.baseline` for newly-created files (e.g., S02.7 manifest files) using `detect-secrets scan > .secrets.baseline` produces a baseline that does NOT include the new files. The pre-commit hook then trips on commit because the new file's hex strings (e.g., a 64-char `layer_hash` field) aren't in the baseline.

**Cause:** `detect-secrets scan` (no positional args) walks `git ls-files` by default — it sees only tracked files. New files are invisible to the rescan even if they're staged with `git add` (the path index may or may not include them depending on operation order).

**Fix:** Mark new files as intent-to-add first, then rescan:

```bash
git add --intent-to-add <new-files>
detect-secrets scan > .secrets.baseline
git add .secrets.baseline <new-files>
```

Or pass file paths directly: `detect-secrets scan <file1> <file2> ... > .secrets.baseline` (loses the existing baseline content — typically merge manually or stick with the `--intent-to-add` flow). The `--all-files` flag scans EVERY file including `.git/`, `.venv/`, `node_modules/` — slow and rarely what you want.

Surfaced by S02.7 manifest backfill on 2026-05-02.

### `detect-secrets` pre-commit hook updates `.secrets.baseline` line numbers on every commit that grows tracked files

**Symptom:** `git commit` reports `Detect secrets... Failed - exit code: 3 - files were modified by this hook` with `The baseline file was updated. Probably to keep line numbers of secrets up-to-date. Please \`git add .secrets.baseline\`, thank you.` The diff on `.secrets.baseline` is a pure line-number shift on an existing tracked false-positive — no new finding, no new line, just `line_number: N` → `line_number: N+k` where `k` is the number of lines added above it in the same file.

**Cause:** A pre-existing false-positive in `.secrets.baseline` (e.g., the BMU `300*` footnote pitfall in `.roughly/known-pitfalls.md`) has its absolute line number recorded. When a commit adds content to that same file above the false-positive's line, every subsequent run of `detect-secrets` rewrites the baseline's `line_number` field to match the new position. The hook intentionally surfaces this as a fail-loud "stage the new baseline" gate rather than silently rebasing on the operator's behalf.

**Fix:** Stage the modified baseline and re-commit. The diff is mechanical — verify it's only `line_number` and `generated_at` fields shifting, not a new finding:

```bash
git diff .secrets.baseline | grep -E '^[+-]' | head   # confirm no new `results` entries
git add .secrets.baseline
git commit -m "..."  # retry the original commit
```

If the diff shows a new `results` entry (not just a line-number shift), inspect what triggered it — that's a real new finding, not the drift case.

Surfaced repeatedly across stories (S03.6 wrap-up is the most recent); recurring whenever a story adds substantial content to a file that already has a tracked false-positive entry. The hook's behavior is correct and intentional — this entry exists to short-circuit the cognitive surprise of "wait, what just changed?"

### `detect-secrets scan --baseline` does not scan untracked files — use `git add -N` first

**Symptom:** A newly created file containing a pinned SHA-256 constant (e.g., a Census TIGER zip hash) is not picked up by `detect-secrets scan --baseline .secrets.baseline`. The rescan completes without error, but the file's high-entropy string is absent from the baseline. The pre-commit hook then trips on the next commit because the string isn't in the baseline.

**Cause:** `detect-secrets scan` uses `git ls-files` internally, which lists only tracked files. New files that haven't been committed yet are invisible to the rescan even if `git add <file>` has staged their content.

**Fix:** Before running the baseline rescan, mark new files as intent-to-add so `git ls-files` sees them:

```bash
git add -N <new-file>...
detect-secrets scan --baseline .secrets.baseline
git add .secrets.baseline <new-file>...
```

The `-N` flag registers the path in the index without staging content. This issue manifests only during manual baseline maintenance, not at commit time (the pre-commit hook scans staged-by-content files correctly). Surfaced during S05.0 secrets-baseline update for the loader's pinned SHA-256 constant (2026-06-01).

### `detect-secrets scan --baseline <file> <specific-path>` replaces the entire baseline — destructive, not additive

**Symptom:** Running `detect-secrets scan --baseline .secrets.baseline ingestion/states/colorado/load_state_boundary.py` to add one new file's findings destroys every other tracked entry — the MT loader's SHA, every committed fixture manifest, known-pitfalls.md false-positives, all gone. The baseline `results` dict is replaced with findings from only the named path.

**Cause:** Positional file-path arguments to `detect-secrets scan` override the default repo-wide scan. The tool performs a targeted scan of ONLY the named paths and writes the result back to `--baseline` — this is replacement, not merge. The CLI documents this behavior but the flag combination reads like "update baseline WITH findings from this file."

**Fix:** To add one new file's entry to the baseline without destroying others, run a full-tree scan (after `git add -N` per entry above), then selectively merge only the new file's entry:

```python
import json

new_filename = "ingestion/states/<state>/<your-new-file>.py"  # set to the path you're adding
new = json.load(open("new-baseline.json"))
old = json.load(open(".secrets.baseline"))
old["results"][new_filename] = new["results"][new_filename]
json.dump(old, open(".secrets.baseline", "w"), indent=2)
```

The alternative — inline `# pragma: allowlist secret` on the flagged line — is also valid but was rejected for the MT loader precedent. Pattern landed in S05.0 (2026-06-01).

### `detect-secrets` attributes secrets inside a YAML `run: |` block scalar to the block-START line — inline pragma on the secret line is silently ignored

**Symptom:** A secret literal inside a GitHub Actions `run: |` multi-line block scalar (e.g. a throwaway password in `psql ... -c "ALTER ROLE ... PASSWORD 'x'"`) gets flagged at the block-START line (the `run: |` line), NOT the line where the literal actually appears. An inline `# pragma: allowlist secret` placed on the secret line therefore does NOT suppress the finding — detect-secrets is looking at the block-start line, which has no pragma. The pre-commit hook keeps failing even after the secret line is annotated.

**Cause:** detect-secrets treats a YAML block-scalar value as a single logical string attributed to the key's line. The pragma check looks for the comment on that key line, not on the line within the expanded scalar where the literal appears.

**Fix:** Move the secret out of the block scalar into a `env:` var on its own line with a trailing pragma, and reference it via `$VAR_NAME` inside the block:

```yaml
env:
  READONLY_PW: ci_readonly_pw  # pragma: allowlist secret
steps:
  - run: |
      psql "$DATABASE_URL" -c "ALTER ROLE readonly_role PASSWORD '$READONLY_PW'"
```

Regular (non-block) YAML scalars and single-line shell commands honor an inline trailing pragma fine; only the `|` / `>` block-scalar form has this line-attribution quirk. Also: in Markdown shell-recipe code fences, a line ending in `\` (line continuation) cannot take a trailing pragma comment — collapse such commands to a single line, or use libpq env vars (`PGPASSWORD` + `-h/-U/-d` flags) instead of credential-in-URL DSNs to avoid the "Basic Auth Credentials" detector entirely.

Surfaced by S08.2 (`.github/workflows/ci.yml` CI substrate recipe + the S08.2 working-note shell recipe on 2026-06-27).

## Conventions — Documentation & planning discipline

### Deferred open-question verdicts require an amendment-pending breadcrumb in `docs/open-questions.md`

**Symptom:** An audit story yields a PARTIAL DEFER verdict on an open question (e.g., S03.11 on Q11: the `low` confidence tier has 0 rows in V1 Montana, so ADR-017 §7 Trigger 2 cannot be validated). A DRAFT amendment is authored (`docs/adrs/ADR-017-amendment-DRAFT.md`) and a working note is filed (`docs/planning/epics/E03-confidence-findings/S03.11.md`). The original Q11 entry in `docs/open-questions.md` is left unannotated. The working note deletes at the m1 tag commit per ADR-017 §6. After that deletion, no surviving-past-m1 signal flags that a DRAFT exists — a future reader scanning `docs/open-questions.md` sees Q11 in its original form and may silently let the DRAFT rot.

**Cause:** Story plans that handle the RESOLVED path (T11: "update Q11 to resolved") do not automatically handle the DEFERRED path. The working note is the only record of amendment-pending status, and working notes are ephemeral by design.

**Fix:** Any audit story whose verdict DEFERS (rather than RESOLVES) an open question MUST add a status annotation directly to the entry in `docs/open-questions.md` before the story closes. The annotation must be placed immediately under the question heading and include: (a) the date + gating story, (b) a markdown link to the DRAFT file, (c) a markdown link to the synthesis report, and (d) a sentence naming what user action closes the deferral. Example format:

```text
**Status (2026-05-26 via S03.11):** OPEN — amendment-pending user review.
See [`docs/adrs/ADR-017-amendment-DRAFT.md`](docs/adrs/ADR-017-amendment-DRAFT.md) and
[synthesis report](docs/planning/epics/E03-confidence-calibration-synthesis.md).
Closes when user approves and commits the amendment as the official ADR-017 revision.
```

This annotation is the only breadcrumb that survives the m1 working-note deletion. Discovered by silent-failure-hunter MEDIUM finding during S03.11 code review (2026-05-26); applied as a post-merge fix to Q11.

### File-deletion events require a paired grep-and-sweep for stale cross-references

**Symptom:** A milestone-deletion commit removes a directory of working files (e.g., `docs/planning/epics/E03-confidence-findings/` deleted per ADR-017 §6 at S03.12 close). A T9 reference sweep surfaced 19 stale references across 11 surviving files — docstrings, comments, operator-facing `RuntimeError` f-strings, and policy descriptions in docs. The same pattern surfaced at S03.11 (`docs/plans/` → `.roughly/plans/` migration, 8 stale references).

**Cause:** `git mv` and `git rm` move or remove the content but do not grep for references. Operator-facing error messages are highest-risk: they fire in production and point operators at paths that no longer exist.

**Fix:** Before executing any deletion or rename, run a four-step sweep:

1. Identify all references: `grep -rn <deletion-target> docs/ ingestion/ mcp-server/ web/`
2. Audit the deletion target for downstream-dependent content (e.g., operator runbooks embedded in working notes must migrate to a surviving doc before deletion).
3. Triage references: redirect to surviving doc, annotate with deletion note, or delete the cross-reference.
4. For operator-facing `RuntimeError` / log messages: redirect is mandatory — leaving operators pointing at a 404 path is a production diagnostic failure.

Surfaced by S03.12 T9 stale-reference sweep on 2026-05-27 (19 references in 11 files); prior instance S03.11 (8 references in 8 files).

### When UAT runs against a PRD that has drifted from implementation, footnote each deviation — do not silently reframe

**Symptom:** A UAT runbook is written against a PRD whose success criteria reference column names, query patterns, or story-specific details that were superseded during implementation. The runbook silently uses the "correct" query without noting the deviation, losing the audit trail between the PRD and the as-built system.

**Cause:** PRDs serve as source-of-record and are not autonomously edited by PMs. When implementation deviates (schema decomposition, HD substitution, Makefile not yet built, etc.), the gap between PRD text and DB reality can be large enough to make individual success criteria non-executable as written.

**Fix:** When authoring a UAT runbook against a drifted PRD, footnote each deviation inline. The footnote names: (a) what the PRD says, (b) what the as-built system actually has, and (c) the durable record of the decision (closure note, ADR reference, or OQ resolution). This preserves the PRD as source-of-record while making the runbook actionable. S03.12 surfaced 6 deviations: `jurisdiction_code` format (`HD-262` → `MT-HD-deer-elk-lion-262`); missing `verbatim_text` column (decomposed per Q15/OQ1); HD 262 elk asymmetric-coverage shift to HD 170 (S03.7 OQ-S7-3); `make ingest` Makefile nonexistent; `license_season` RLS gap; ADR-017 status resolved unmodified per S03.11. Reference: `docs/runbooks/M1-uat.md` footnote conventions.

Surfaced by S03.12 UAT runbook authoring on 2026-05-27.

### Spec-named location lists must be independently verified by grepping the file — do not trust the enumeration

**Symptom:** A story spec says "the framing phrase appears at N locations" and lists line numbers. Discovery and plan both anchor on that list. A reviewer's full-file read finds an additional location the spec missed — in this case a module-level docstring at the top of the file that carried the same "intentionally wide pending T16" framing as the two spec-named locations (a constant block and a function docstring). The missed location shipped unedited.

**Cause:** Spec authors use a mental model ("constants + function docstrings") that silently excludes other location types (module-level docstrings, inline comments, `__all__` declarations). The discovery agent and plan-writer both treat the spec's enumeration as authoritative rather than as a starting-point to verify.

**Fix:** When a spec or plan claims "the phrase appears at N locations in file X," the discovery phase MUST independently run `git grep -n "<distinctive phrase>" <file>` and compare the output against the spec's list. If discovery finds more locations than the spec named, escalate to PM before writing the plan — do not silently add the extra location without noting the discrepancy. The reviewer's full-file scan is a safety net, not the primary mechanism.

Surfaced by S04.2 Stage 6 static-analysis review on 2026-05-29 (module-level docstring at lines 26–27 of `load_jurisdiction_bindings.py` missed by spec, discovery, and plan; caught only at review).

### Spec line-number citations drift between spec authoring and execution — verify by content, not by line number

**Symptom:** A spec lists 10 occurrences of a literal value across a file at specific line numbers. Discovery finds that one spec-cited line actually contains different content (an unrelated comment mentioning the old band floor), not the literal the spec described. Real count was 9 matching literals plus 1 separate prose update — not 10 of the same thing.

**Cause:** Specs are drafted while the file is in a working state; multi-pass editing between spec authoring and story execution shifts line numbers. The spec writer's absolute line citations become stale. When an intervening constant-block insertion adds lines, every subsequent spec line reference shifts by the same delta (the "four-line drift" pattern — a block insertion in T2 shifting all T3+ spec lines).

**Fix:** Discovery's verification step must anchor on file content, not absolute line numbers. For each spec-cited "occurrence of X at line N," grep the file for X and verify the hit list matches the spec's claimed locations. When the content at a spec-cited line doesn't match what the spec describes, surface the discrepancy explicitly in the discovery report — do not silently correct it or skip it.

Surfaced by S04.2 discovery on 2026-05-29 (spec cited line 1486 as a `770` literal; actual content was an unrelated comment; discovery caught the mismatch before plan-writing).

### Reviewer findings are signals about the quality of the work as-built — dismissing on "the spec chose this path" grounds is wrong

**Symptom:** Two independent reviewers (Stage 6 silent-failure-hunter, post-merge cubic) converged on the same two findings: (a) an AC checkbox whose prose suffix contradicted the just-narrowed tuple value, and (b) a test class that derived all boundary cases from the production constant, leaving no contract lock on the tuple itself. At Stage 6 the orchestrator dismissed both with "the spec explicitly chose this path" — citing the spec's one-tuple-change instruction as forbidding prose cleanup, and citing "arithmetic-derivation is preferred" as ratifying every quality tradeoff that resulted. Both findings came back post-merge as P2/P3 cubic findings, requiring two follow-up fix commits on the same branch (a one-line prose rewrite to the AC checkbox + a new contract-lock test in TestCountGuard).

**Cause:** Treating a spec's explicit instruction as a CEILING rather than a FLOOR. The spec states the minimum that MUST happen; it does not enumerate what MUST NOT happen. When a finding identifies a quality gap the spec didn't require fixing, the question is "does the result meet the actual quality bar?" — not "did the spec require this change?"

**Fix:** When dismissing a reviewer finding at Stage 6, the orchestrator must be able to answer: "What would a clean code/doc state look like without spec constraints?" If that answer differs from the current state, the finding is valid and must be addressed. A secondary signal: when two independent reviewers (Stage 6 + post-merge cubic) converge on the same finding, that convergence is hard evidence the finding is valid. Single-reviewer findings can be debated; converged findings must not be dismissed on spec-language grounds.

Surfaced by S04.2 Stage 6 + cubic post-merge review on 2026-05-29.

### Spec-prescribed string substitutions silently invalidate coupled references elsewhere in the document

**Symptom.** A spec or plan prescribes a string substitution in one named location (e.g., `'MT-HD-deer-elk-lion-262'` → `'MT-HD-deer-elk-lion-124'` in two SQL blocks). The substitution lands cleanly there but silently breaks correctness elsewhere in the same document — inline notes that name the old value, summary tables whose row labels reference it, footnotes that anchor to it — all become stale post-substitution but pass spec compliance because the spec only named the original substitution location.

**Where surfaced.** S04.4 (M1 UAT runbook hygiene). T2/T3's spec-prescribed `HD 262 → HD 124` swap in `docs/runbooks/M1-uat.md` §4 criteria #1 + #2(a) silently invalidated four downstream references — the §2 inline deviation note, §5 Results Summary row labels (two), and footnote `[^3]`. The Stage-3 plan and Stage-4 plan-review both explicitly excluded §5 "by design"; Stage-6 review triad correctly caught it as a correctness defect requiring round-1 review-fixes.

**The discipline.** When a spec or plan prescribes a string substitution, grep the full file for every occurrence of the original string AND of any coupled reference (inline notes, table row labels, footnotes anchoring to the value) BEFORE writing the plan's task list. Each match is a per-occurrence decision — substitute or annotate — captured in the plan's task scope, not in review's compensating finds. Content-anchored verification beats absolute line-number lookup.

### Authoritative numbers drift between canonical documents — name the source-of-truth before copying

**Symptom.** The same numeric value (row count, version, timestamp, threshold) appears in multiple canonical documents in the repo. When one document is updated and the other isn't, the two carry different values. A spec or plan that copies from the wrong document silently propagates the stale number.

**Where surfaced.**

- S04.1 Group B verification: AC #11 cited `~3040` from handoff §3 as the `license_season` row baseline; operator-side verification on 2026-05-30 returned 2411 — the post-UPSERT-collapse DB count per S04.4 spec L280 footnote, the actually-authoritative source. Handoff §3 lists pre-collapse build projections; the post-collapse DB counts live in S04.4's runbook footnote.
- S04.4 T4: handoff §8 #4 cited `draw_spec 388 → 276 DB`; S03.8 closure in CLAUDE.md cites 278 (authoritative). Same handoff bullet parenthetically notes the 276 was a transcription error. Stage-4 plan-review caught the 276 in the plan; shipped runbook tracks 278 with explicit provenance footnote.

**The discipline.** When a spec, plan, or runbook copies a numeric value from another document, NAME the source-of-truth document inline (e.g., "per S03.8 closure" or "per S04.4 spec L280"). When two canonical documents carry different values for the same quantity, the spec that cites the authoritative source is correct; the other is drifted. Drift-detection lives in the per-cite source-of-truth attribution, not in spot-checking individual numbers.

### Explanatory comments that embed a broken-pattern literal trip token-matching reviewers (cubic)

**Symptom:** A SQL query containing the direct geography-to-geometry cast is fixed to use the WKT round-trip. The corrected query is correct. But the accompanying explanatory comment still contains the literal broken pattern twice — e.g., `-- the direct geom::geometry cast is rejected by Supabase; the spec's SQL used geom::geometry`. Cubic re-flags the section as still using the invalid cast, matching the literal inside the comment rather than the (now-correct) query body.

**Cause:** Token-matching tools (cubic, grep-based linters) cannot distinguish a cautionary mention of a broken idiom from a live occurrence. Same root cause as content-anchored grep verification failing to distinguish a comment from an active call site.

**Fix:** Describe the broken idiom in prose rather than embedding the exact token adjacent to corrected code — e.g., "the direct geography-to-geometry cast" instead of `geom::geometry`. The fix is a one-line reword and keeps the post-fix cubic pass clean. Low-severity / tooling-hygiene; surfaced by S05.7 Stage-6 cubic re-flag after the cast fix (2026-06-06).

### Large real-PDF extractors require multiple cubic iterations — budget for layered bug discovery, not a single clean pass

**Symptom:** A new real-PDF extractor passes an initial cubic review with only cosmetic findings. A second cubic pass after fixing those findings surfaces a structurally different, more specific bug (e.g., residency leaking into section keys). A third pass surfaces a date-format issue, a fourth a column-shift, a fifth a header-bleed. Each round's findings are real and correct — they were hidden by noisier bugs above them in the data path.

**Cause:** Cubic matches against the artifact the extractor currently produces. When an obvious bug (e.g., `■` glyph in 136 `unit` fields) is present, all subsequent artifact rows downstream of that bug look wrong for multiple reasons simultaneously. Fixing the top-level bug clears the noise and exposes the next-layer issue that was previously masked. S06.3 took 6 cubic rounds (■ leak / garbage rows → residency-in-section-key → date-format → valid_gmus column-shift → header-bleed → clean) against the 84-page CPW Big Game PDF.

**Fix:** Plan for at least 3–5 cubic iterations on any new large state-PDF extractor that introduces new column layouts, multi-section pages, or new PDF encoding patterns. Do not assume the first clean-ish pass is the last word. Treat each iteration as revealing real bugs, not as tooling noise. The iteration budget is proportional to how structurally different the new PDF is from prior adapters (CPW Big Game's GMU tables differ from FWP DEA tables in column layout, presentation glyphs, method-group header rows, and font encoding).

Surfaced by S06.3 6-round cubic iteration sequence on 2026-06-10.

### A story's AC list is necessary but not sufficient to scope the work — grep the whole epic and predecessor closure notes for contracted deliverables

**Symptom:** A story's AC list and Deliverables block name only entity X. The story is implemented and reviewed AC-by-AC, passing cleanly. At Stage-6 silent-failure-hunter review (which reads the broader epic), it is discovered that entity Y link writes were also contracted for this story — in the preceding story's closure note ("entity rows ONLY — Y links are the current story's job"), the epic's Depends-on block ("for Y link writes"), the epic's Exit Criteria, and the epic's dependency-rationale prose — but are absent from the AC list.

**Concrete instance (S06.10):** The S06.10 AC list (#1100–#1116) and Deliverables block named only `jurisdiction_binding` rows. But `regulation_reporting` link writes were mandated in six other places — epic lines 994, 1017, 1024, 1094, 1221, and 1256 — and S06.9's closure explicitly deferred them. The omission survived planning and was caught only by the Stage-6 silent-failure-hunter. The fix added a `_build_regulation_reporting_links` builder and write loop in the same review-fix cycle.

**Fix:** When scoping a story (discovery + planning), grep the WHOLE epic for the story id and for the entity/output names the story produces — not just its AC block. Cross-check the predecessor story's closure note for explicit deferrals naming the current story, and the epic Exit Criteria for outputs that must exist at close. Treat the AC list as one input among several, not the authoritative scope boundary. Extends the existing "spec-named location lists need grep-verification" / "name the source-of-truth before copying" family: here the failure mode is an under-specified AC list contradicted by the rest of the epic, which static AC-by-AC review cannot catch.

Surfaced by S06.10 Stage-6 silent-failure-hunter review on 2026-06-29.

### Dual issue-numbering schemes in summary lists create false contradictions — pin one scheme per list

**Symptom:** A milestone-close document (e.g., a handoff §8 summary table) lists Known Issues under both an epic-local sequential row number and a cross-epic-origin label (`KI#7`, `KI#12`). A later summary bullet says "#7 is in the deferred bundle" while another says "#7 is RESOLVED" — an apparent contradiction. In fact both claims are correct under different numbering schemes: row 7 of the table is the CPW-URL item (RESOLVED), while row 4 is the overlay-builder item carrying the cross-epic label `KI#7` (deferred).

**Cause:** Two overlapping numbering schemes (table row index vs. cross-epic origin label) applied without disambiguation in the same prose makes each reference ambiguous. Readers resolving the reference against the wrong scheme see a contradiction that does not exist.

**Fix:** Within any single summary list, pin ONE numbering scheme. Where a row carries a cross-origin label, disambiguate inline — e.g., "row #4 = overlay-builder extraction, cross-labeled as E05 KI#7" vs. "row #7 = CPW-URL item, RESOLVED". Related to the "name the source-of-truth before copying numbers" discipline; here the failure mode is ambiguous reference resolution rather than drifted values.

Surfaced by M2→M3 handoff §8 summary cleanup during S06.11 on 2026-07-01.

### Migrating an epic file to `completed/` keeps relative links as-is — do not rewrite them

The established E03/E04/E05 convention is `git mv docs/planning/epics/<epic>.md docs/planning/epics/completed/<epic>.md` WITHOUT rewriting internal relative links (`](../adrs/…)`, `](../prds/…)`, `](../handoffs/…)`, etc.). From the new `completed/` subdirectory these links are technically one level short, but every already-migrated epic is in this state — it is the accepted convention. Do NOT "fix" the links on migration; doing so creates unnecessary diff noise and diverges from the audited pattern.

**Two things that DO change on migration:** (1) the self-referential audit link the closing PM adds IS written relative to the post-move `completed/` location; (2) inbound references in `docs/planning/README.md`, CHANGELOG, or similar index files must be updated to point at the `completed/` path.

Surfaced by E06 epic migration during S06.11 on 2026-07-01.

### CLAUDE.md's rolling preamble is one giant single line — use Python `str.replace`, not the Edit tool

The CLAUDE.md project-instructions preamble (the M1/M2/M3 rolling summary paragraph) is a single line of ~269k+ characters. Reading or editing it via the standard `Read`/`Edit` tools overflows the token limit and produces truncated results or silently corrupts adjacent content.

**Fix:** For surgical in-place updates, write a Python script that (1) reads the entire file, (2) asserts `data.count(anchor) == 1` on a unique anchor substring to guard against mis-targeting, (3) applies `str.replace(anchor, replacement)`, and (4) writes back. Choose the anchor at a stable boundary — e.g., the transition from the newest content into older historical text. Verify the replacement leaves the overall character count plausible (not an accidental truncation). This is the only reliable editing pattern for a document whose largest "line" exceeds any reasonable token window.

Surfaced by S06.11 CLAUDE.md update on 2026-07-01.

## Conventions — Python

### PEP 563 deferred annotations do not satisfy ruff F821 — hoist annotation-only names to module level

**Symptom:** A file with `from __future__ import annotations` at the top uses a type name (e.g., `Path`, `datetime`, `Decimal`) only in an annotation — inside a method body's `def foo() -> list[Path]:` — with the actual import inside the method body or absent entirely. Python accepts this at runtime (PEP 563 turns all annotations into strings). Ruff's F821 ("Undefined name") rule still flags it and fails the lint gate.

**Cause:** Ruff performs static analysis; it sees `Path` referenced in an annotation before any module-level binding exists for it. PEP 563 defers evaluation at runtime but does not satisfy ruff's static-scope check.

**Fix:** Import the name at module level even when it appears only in annotations. The cost of one additional import line is much smaller than a Stage-6 ruff failure. Surfaced by S05.1 Stage 6: `TestNoColoradoLeakIntoSharedLib._lib_python_files` declared `-> list[Path]` with `from pathlib import Path` inside the method body; hoisting the import to module level resolved F821.

### Mixing `ingestion/lib/` and a `states/<state>/` path in one mypy invocation triggers a spurious "found twice" error

**Symptom:** Running `mypy ingestion/lib/ states/colorado/load_jurisdiction_bindings.py` (or any single combined invocation of `ingestion/lib/` and a `states/<state>/` file) fails immediately with:

```text
error: Source file found twice under different module names: "colorado" and "states.colorado"
```

The error fires on an imported sibling (e.g. `load_regulation_records.py`), not necessarily the file named on the command line.

**Cause:** The `states/` directory layout makes `states/colorado/` reachable under TWO module paths simultaneously — `colorado` (when `states/` is on the path) and `states.colorado` (when `ingestion/` is on the path). Passing both `ingestion/lib/` and a `states/` file in one invocation exposes both paths to mypy at once, triggering the double-module detection.

**Fix:** Never mix `ingestion/lib/` and `states/<state>/` paths in a single mypy call. The canonical project gate per CLAUDE.md is **`mypy ingestion/lib/`** only — it does not type-check `states/`. If you want to spot-check a CO loader separately, run it in a SEPARATE invocation (e.g. `mypy --explicit-package-bases states/colorado/load_jurisdiction_bindings.py`) and do not combine both in one shell command.

**Bonus trap:** a standalone `mypy --explicit-package-bases states/colorado/<loader>.py` can surface default-strictness notes on untouched code (e.g. an overload-resolution note on `list(raw_regions)`) that the canonical `mypy ingestion/lib/` gate never exercises. Do not treat such notes as regressions introduced by an unrelated change — they are an artifact of running mypy at a lower-strictness baseline than the lib gate assumes.

Surfaced 2026-07-01 during the S06.10 `_BINDING_COUNT_GUARD_BAND` narrowing build.

## Conventions — Testing

### Class-body tuple invariants must be locked by an inline `assert all(...)` immediately after the tuple

**Symptom:** A class declares a tuple of needle strings whose scan logic depends on a property (e.g., all needles must be lowercase because the haystack is lowercased via `.lower()` before comparison). The scan works correctly today but silently breaks if a future maintainer appends a mixed-case needle copied from a YAML or URL literal.

**Cause:** There is no structural enforcement that the tuple satisfies the property the scan logic assumes. A mixed-case needle like `"Services5.ArcGIS.com"` can never match `source.lower()`, so the scan passes for the wrong reason (the forbidden literal is present but undetected).

**Fix:** Immediately after the tuple definition, add a class-body assertion: `assert all(s == s.lower() for s in _NEEDLES), "..."` (or the appropriate predicate). This fires at module-collection time — before any test runs — and catches invariant violations for free. Pattern: `<container>: tuple[X, ...] = (...); assert all(<predicate> for v in <container>), "<diagnostic naming the invariant>"`. Surfaced by S05.1 Stage 6 silent-failure-hunter review of `TestNoColoradoLeakIntoSharedLib._CPW_HOST_LITERALS`.

### Multi-method test classes — each scan method must be self-sufficient, not dependent on a sibling sanity-check running first

**Symptom:** A sanity-check method (`test_lib_directory_enumeration_covers_known_files`) asserts the file list is non-empty before scan methods (`test_no_colorado_slug_in_lib`, `test_no_cpw_host_literals_in_lib`) iterate it. This works under pytest's default definition-order execution but silently breaks under `pytest-randomly` or any future fixture-reordering plugin: the scan methods iterate an empty list and trivially pass.

**Cause:** Relying on sibling-method execution order is a CPython dict-ordering detail, not a pytest contract. The scan methods assume the sanity check has already run and populated the invariant, but nothing enforces this ordering.

**Fix:** Add an inline `assert <collection>, "<diagnostic referencing the sanity-check method>"` at the top of each scan method body before the loop. This makes each scan method self-sufficient — it will fail loudly on an empty collection regardless of execution order. The sanity-check method remains useful as an explicit enumeration guard; it simply no longer needs to be the sole protection. Related: see "Per-builder dedup sets miss cross-builder collisions" (Conventions — Ingestion adapters) for the analogous self-sufficiency principle applied to multi-builder adapters. Surfaced by S05.1 Stage 6 silent-failure-hunter W2 finding.

### "One of A or B" ACs silently omit the pure-gap branch — name it explicitly at story closure

**Symptom:** A spec AC enumerates exactly two outcomes: "≥1 row ingested from source X" OR "hand-traced fallback Y." When a story discovers neither source X nor any fallback exists (the pure-gap branch), neither AC checkbox maps cleanly to the result. Leaving the checkboxes blank is ambiguous — a future reader cannot tell whether the story closed without evidence or whether the gap was deliberate and investigated.

**Cause:** "One of A or B" ACs are written under the assumption that at least one branch will be realized. The third branch — "neither source nor fallback exists; source is structurally unavailable" — is a valid outcome that the AC language didn't anticipate.

**Fix:** When the pure-gap branch is realized, mark the ingestion-shaped ACs `N/A-by-gap` with a one-line rationale each (e.g., "N/A — CPW publishes no CWD-zone geometry; CO manages CWD by hunt-code/GMU per S05.3 investigation report"). Document the gap outcome explicitly in the story closure note so the AC record is unambiguous. Surfaced by S05.3 epic AC #2 on 2026-06-03.

### Empirical discovery that supplies a deferred open question's named trigger — append dated evidence, not a status change

**Symptom:** Build or discovery work produces evidence that matches exactly what a deferred open question named as its decision trigger (e.g., Q18's "second CWD-state lands" trigger is met when CO confirms CWD is managed by hunt-code/GMU, making zone-keyed binding structurally unavailable for CO). The temptation is to mark Q18 RESOLVED immediately based on the new evidence.

**Cause:** Evidence that a trigger condition has fired is not the same as the formal decision. The owning epic/story (here E06) holds the resolution authority. Prematurely closing the question removes the signal that E06 still needs to make the formal call, and bypasses the review cycle where the decision and its consequences are captured together.

**Fix:** Append a dated evidence note directly to the open question's entry in `docs/open-questions.md` (e.g., "Evidence 2026-06-03 via S05.3: CO confirms CWD managed by hunt-code/GMU; zone-keyed binding structurally unavailable for CO — trigger condition met.") and flag it to the human. Do NOT change the question's status or verdict. The formal RESOLVED annotation belongs to the owning epic or story when it makes the deliberate decision. Surfaced by S05.3 → Q18 on 2026-06-03.

### Enum-extension sync surfaces — spec-named sites are necessary-not-sufficient; grep for all cast/Literal/frozenset consumers

**Symptom:** A schema-enum extension spec enumerates its sync surfaces (e.g., "five-place sync: DDL + Pydantic + TypeScript + `architecture.md` + `overlays.py` Literal alias"). All five land cleanly, but a sixth site — a `cast(Literal["primary_unit", ..., "other_overlay"], role_e03)` inline re-enumeration inside an adapter — is missed. Once the alias grows to include the new value, the cast silently narrows the type unless it also grows.

**Cause:** Spec authors enumerate the "obvious" sync surfaces (schema files, type definitions) from a mental model. Adapter-level cast/Literal re-enumerations are local to the adapter and invisible to a schema-file-only scan.

**Fix:** When implementing a schema-enum extension, treat the spec's named-sites list as a starting point, not a complete inventory. Before writing the plan, grep the whole codebase for every `cast(Literal[...])`, inline `Literal[...]` re-enumeration, `frozenset({...})`, and `== {"value"}` set-literal that mirrors the enum being extended. Each match is a potential sync site. Surfaced by S05.3.5 Stage-2 discovery: `cast(Literal["primary_unit", ..., "other_overlay"], role_e03)` in `ingestion/states/montana/load_jurisdiction_bindings.py::_build_overlay_bindings` was not in the spec's five-place list and required a sixth edit.

### Enumerated expected-set constants are only guards if compared against actual output at the write boundary

**Symptom:** A loader defines `_V1_EXPECTED_IDS: frozenset[str]` of N expected geometry ids, asserts `len(_V1_EXPECTED_IDS) == N` at module load time, and has a unit test verifying that `_fetch_and_build` returns the expected set. But `main()` never compares the built geometries' actual ids against `_V1_EXPECTED_IDS` before the DB write. An upstream rename (e.g., PAD-US `Unit_Nm` value changes) produces a different slug/id — the count band passes (still N rows), the Curecanti-drop guard passes (still excluded by a separate field check), and a wrong-id row is written while the expected row goes missing. No guard fires.

**Cause:** A module-load `assert len(...)` checks that the constant was typed correctly; a unit test checks the builder's internal logic. Neither checks that the IDs actually coming out of `main()` match the expected set. Length-check at import ≠ identity-check at runtime.

**Fix:** Wire `actual_ids == _V1_EXPECTED_IDS` (or equivalent set comparison) as a fail-loud guard in `main()` before `db.connect()` (pre-connect per OQ7 discipline). The check must fire on the IDs produced by the build phase, not on the constant alone. Two independent Stage-6 reviewers (code-reviewer + silent-failure-hunter) converged on this in S05.4. Reference: `ingestion/states/colorado/load_restricted_areas.py:main()` pre-connect id-set guard (S05.4).

Surfaced by S05.4 Stage-6 review on 2026-06-03.

### Allowlisted-orphan coverage checks can pass vacuously — assert the orphan log is ABSENT for items that should be covered

**Symptom:** A `_validate_coverage` helper classifies each child geometry as either (a) covered by a parent or (b) an allowlisted expected-orphan and skips the raise. When every member of a kind happens to be on the orphan allowlist (e.g., all 10 CO `restricted_area` geometries are in `EXPECTED_CO_RA_ORPHAN_IDS`), outcomes (a) and (b) become indistinguishable to a pass/fail assertion. A test that only asserts "no exception was raised" cannot distinguish a working `parent_kind == "gmu"` filter from a broken `parent_kind == "hunting_district"` copy-paste — under the broken filter the covered item falls into the allowlisted-orphan path and still does not raise (silent vacuous pass).

**Cause:** The allowlist path and the covered path produce the same observable outcome (no raise) when the allowlist is a superset of the kind being tested. The test's signal is gone.

**Fix:** When an item is genuinely covered, assert the ABSENCE of the allowlist/orphan INFO log line: `assert not any("ADR-016 allowlist" in r.message for r in caplog.records)`. The absence of the orphan log is the only signal that the coverage path actually fired. This extends the S05.4 pitfall "an enumerated expected-set constant is only a guard if compared against actual output at the write boundary" — here the allowlist masks a filter bug rather than an id-substitution bug. Reference: `ingestion/tests/test_build_co_overlay_fixture.py::TestValidateCoverage::test_all_children_covered_no_raise` (S05.5 review-triad W1 fix).

Surfaced by S05.5 Stage-6 review on 2026-06-04.

### A docstring `locked by: TestClass::method` citation can be a phantom — add a parity test that asserts the named test actually exists

**Symptom:** A module docstring or cleanup-rules section says `locked by: TestStatewideOverlayColumnFaithful::test_x`. The named class or method does not exist. A parity test that only checks that the rule text IS PRESENT in the docstring passes cleanly while the phantom citation rots undetected.

**Cause:** Docstring citations are free-form prose; nothing in Python or pytest enforces that the named class+method actually exists. A cleanup rule added during a fast iteration can reference a test that was renamed or never written.

**Fix:** Add a parity test that (a) parses every `locked by:` citation from the docstring via regex and (b) asserts that the named test class and method can be found in the test module (e.g., `assert hasattr(test_module, class_name)` and `assert hasattr(getattr(test_module, class_name), method_name)`). A presence-only parity test is insufficient — it confirms the rule text exists but not that the lock is real. Reference: `ingestion/states/colorado/extract_big_game.py` cleanup-rules parity discipline (S06.3).

Surfaced by S06.3 review on 2026-06-10.

### Import `assert_id_matches` by bare name — the AST drift-guard test matches `ast.Name`, not `ast.Attribute`

**Symptom:** A `TestDriftGuardCallSites` AST regression test is expected to confirm that every per-row entity-construction site in a module calls `assert_id_matches`. The test passes without error, but a construction site that uses `drift_guard.assert_id_matches(...)` is silently not matched — the test effectively passes vacuously for that site.

**Cause:** The AST guard walks `ast.Call` nodes and checks whether the `func` is an `ast.Name` with `id == "assert_id_matches"`. A dotted attribute call `drift_guard.assert_id_matches(...)` produces an `ast.Attribute` node, not an `ast.Name` node. The guard's predicate does not match it, so the guard reports "all sites instrumented" while that site is actually unguarded.

**Fix:** Always import the function by bare name and call it bare:

```python
from ingestion.lib.drift_guard import assert_id_matches
# ...
assert_id_matches(entity.id, expected_id, helper_name="...", context="...")
```

Never import the module and call via attribute (`drift_guard.assert_id_matches(...)`). The bare-name import convention is the only form the `TestDriftGuardCallSites` AST guard can verify. Reference: ADR-020 (`docs/adrs/ADR-020-id-text-pk-slug-derivation.md`); `ingestion/states/colorado/load_seasons_and_licenses.py` drift-guard call sites (S06.7).

Surfaced by S06.7 Stage-6 review on 2026-06-23.

### CPW per-species column layouts differ — probe each species' table shape against the live PDF, don't inherit from a sibling extractor

CPW Black Bear hunt-code tables use a 4-column layout (`Unit | Valid GMUs | Hunt Code | List`) or a 5-column variant adding `Dates` — with **no Sex column**. The sibling CPW Big Game (deer/elk/pronghorn) tables are 5- or 6-column **with** a Sex column. Applying the big-game column-index mapping to bear tables mis-maps every row: what big-game reads as `sex` is bear's `hunt_code`; what big-game reads as `hunt_code` is bear's `list`. The failure is silent — no `KeyError`, just wrong field assignments.

**Fix:** At Stage-1 discovery, open the target PDF and count actual column headers for each species' tables independently. Write a species-specific column-detection function (e.g., `_bear_classify_table_variant` in `ingestion/states/colorado/extract_black_bear.py`) rather than inheriting from a sibling extractor. When in doubt, emit a WARNING for unrecognized column counts rather than mapping blindly.

Surfaced by S06.4 implementation on 2026-06-13.

### Hunt code embedded in prose defeats an anchored regex — use an unanchored `re.search` fallback and store the prose verbatim

A hunt-code cell can carry a prose prefix alongside the code, e.g. `"Sales agents only: B-E-087-U6-R"`. An anchored pattern (`^[A-Z]-[A-Z]-\d{3,4}-[A-Z]\d-[A-Z]$`) fails to match and the row collapses to empty or low-confidence, silently dropping a real license.

**Fix:** After the anchored parse fails, attempt `re.search` for the full 5-component hunt-code pattern embedded anywhere in the cell. When found: use the extracted code for structured fields and store the surrounding prose verbatim in `extras` (ADR-008). Emit an INFO log so operators can audit. This recovered a dropped CO Plains-OTC bear license whose cell read `"Sales agents only: B-E-087-U6-R"` — a valid license that the anchored parser silently discarded. Reference: S06.4 Rule R16 in `ingestion/states/colorado/extract_black_bear.py`.

Surfaced by S06.4 real-PDF probe on 2026-06-13.

### pdfplumber merges two adjacent table rows into one when the inter-row ruling is missing — detect multi-hunt-code cells and split, fail loud on misalignment

When the PDF omits the horizontal ruling between two adjacent rows, pdfplumber returns a single logical row with newline-joined cell pairs, e.g. `Hunt Code = "B-E-058-O1-M\nB-E-059-O1-M"`, `Unit = "58\n59"`, `List = "B\nB"`. A naive "use first line only" rule keeps the first code, leaves the other cells fused as `list_value="B\nB"`, and **silently drops the second hunt code** — a real license that never appears in the artifact.

**Fix:** When a Hunt Code cell contains N≥2 full hunt codes (separated by `\n`), split every parallel block cell on `\n` into N logical rows. If any present, non-empty cell does not split into exactly N parts, raise immediately (ADR-001 — never guess the alignment). The split must happen before any downstream cell normalizer or confidence assignment so dropped rows surface as a hard error rather than a count-band miss. Reference: S06.4 Rule R17 `_split_fused_block_row` in `ingestion/states/colorado/extract_black_bear.py`.

**Note:** the same latent issue existed in the big-game extractor. **Resolved 2026-06-16 via S06.3.1**: R17 was ported to `extract_big_game.py` as big-game Rule R16; the empirical count was **4** fused rows recovered (`D-M-082-O3-R`, `D-F-107-O1-R`, `A-M-004-O1-M`, `A-F-118-O1-R`), not 9 — the "9" was an unmeasured approximation at the time of discovery.

**Big-game divergence — partial-column fusion (broadcast rule):** unlike bear (where a fused row doubled *every* column, so strict raise-on-any-mismatch is correct), big-game fusion is **partial-column** — some cells carry a single *shared* value spanning both logical rows (e.g. one `Valid GMUs = "82"` shared by `D-M-082-O2-R` and `D-M-082-O3-R`). So big-game's `_split_fused_block_row` uses `{N parts → distribute | 1 part → broadcast | else → raise}` rather than bear's strict rule. Two guard rails keep this fail-loud: (1) the **Hunt Code cell is the authority** — if it reports N codes but does not itself split into N `\n`-parts (e.g. codes abutted with no delimiter), raise rather than broadcast a concatenated unparseable code; (2) any non-1, non-N part count still raises. **Mis-distribution guard + residual limitation:** the broadcast/distribute decision is part-count based, so a fused row whose *shared* cell line-wraps to N parts could in principle be mis-distributed (truncated) rather than broadcast. The dominant manifestation — a comma-separated list that wraps, e.g. `valid_gmus="107, 112,\n113, 114"` — is caught **fail-loud**: a distributed part ending in a continuation comma triggers `PdfExtractionError` (genuine per-code values like `"3, 301"` / `"4, 5"` never end in a comma, so it is false-positive-free on the 4 real 2026 fused rows). **Residual:** a shared value that wraps to exactly N parts *without* a trailing-comma signal remains indistinguishable from N per-row values on part-count alone; no such case exists in the 2026 brochure. Also note the splitter's hunt-code matcher (`_HUNT_CODE_EMBEDDED_RE`) and the single-code parser (`_HUNT_CODE_RE`) both derive from one `_HUNT_CODE_GRAMMAR` fragment so the two can never drift to detect different code shapes.

Surfaced by S06.4 real-PDF probe on 2026-06-13.

### Forking a state-adapter module means forking its test suite too — verify guard-parity before closing the story

**Symptom:** A new state's adapter module is created as a near-verbatim copy of an existing state's module (e.g., CO `fetch_pdfs.py` forked from MT `fetch_pdfs.py` with only docstring/path/argparse substitutions). A handful of new-state-specific tests are written, but the sibling state's orchestrator-behavior test classes are not ported. The copied module carries fail-loud guards (malformed-entry, empty-or-invalid-field, empty-url), but those guards have zero test coverage in the new state. A future accidental weakening of a copied guard passes CI silently.

**Cause:** The shared-lib primitive (`pdf_fetch.fetch_pdf`) is covered once in `test_pdf_fetch.py`, but the per-state orchestrator copy is a separate artifact — each state's copy needs its own behavior coverage. Writing only new-state-specific tests leaves the inherited guard logic dark.

**Fix:** When forking a state-adapter module, port the sibling's behavior-test classes too (CO-renamed, with updated import paths). Verify guard-parity by diffing the new test file's class list against the sibling's before closing the story. Surfaced by S06.1 Stage-6 silent-failure-hunter: porting MT's `TestMalformedEntryShape`, `TestEmptyOrInvalidFieldValuesFailLoud`, and `TestEmptyUrlEntryFailsLoud` classes raised CO's orchestrator coverage from 12 → 22 tests and closed the guard-parity gap.

### A correction/supplement PDF can contradict a prior story's forward-note — parse it in full and evidence its real content; never trust the claimed scope

A closure note's forward-note (e.g., S06.1's "the 2026 CPW correction PDF is moose-only") is an observation recorded at the time that story closed — it is not a contract. The live 2-page correction extract turned out to be moose (p. 1) **AND** elk muzzleloader hunt codes (p. 2). An extractor that hardcodes the claimed scope ("skip this PDF; it only touches moose") would silently omit the elk correction, producing a faithfulness gap.

**Fix:** Always open and scan the full correction PDF in the extractor's implementation, log the real content as structured evidence (e.g., section headers found, page count, species detected), and make the inert/active decision from that evidence — not from the upstream closure note. A forward-note is a breadcrumb, not a bypass.

**Bonus signal:** when a correction PDF contains content the prior story said it wouldn't, flag the upstream extractor (S06.3 in this case) as a potential gap — the elk muzzleloader correction may not have been applied to `big-game-2026.json`. Reference: S06.4 `_extract_correction` in `ingestion/states/colorado/extract_black_bear.py`.

Surfaced by S06.4 real-PDF probe on 2026-06-13.

### An out-of-domain hunt code on a single-species page is a structural anomaly — fail loud, matching the extractor's other structural guards

A bear extractor parses bear-only pages (CPW PDF 72–77). A parsed-but-non-bear hunt code there (e.g. `D-E-050-O1-A` — a deer code) is not a degraded-but-valid bear row; it signals page-bleed, a wrong page range, or a parser bug. The original code only *warned* on `species_letter != "B"` while `_assign_bear_row_confidence` keyed LOW on `species_letter == ""` (unparseable) — so a misclassified code was promoted to **HIGH** and would be persisted by S06.6 as `species_group="black_bear"` (corrupt data).

**Fix:** `_extract_bear_block_row` raises `PdfExtractionError` on a non-`"B"` species letter (naming code + page), mirroring big-game `_species_group_for`'s raise-on-unknown. This matches the module's other structural-anomaly guards (unrecognized OTC heading, fused-row misalignment, `document_type`, count-band) which all fail hard before any write. Extraction is deterministic + re-runnable, so aborting is not permanent data loss — it forces a parser fix, the correct response. Keep `_parse_hunt_code` itself permissive (pure parser, used by the R16 embedded-search check); enforce at the emit site.

**Review-cycling note:** a code-review bot (cubic) objected to *every* candidate behavior across successive runs — `raise` ("discards other rows"), `emit-at-LOW` ("leaks non-bear data into the artifact"), and `warn+skip` ("silently drops; prefer a hard failure"). These objections are mutually exclusive; no behavior satisfies all three. When review findings *cycle* (contradict prior rounds) rather than *narrow*, stop iterating and decide on convention + domain priority, then document the rationale (here: fail-hard, because for a regulatory artifact a hard failure is more detectable than missing/leaked rows, and it matches the module + sibling convention). Reference: S06.4 `_extract_bear_block_row` (`06dcce8`).

Surfaced by S06.4 post-merge review on 2026-06-14.

### CO regulation_record builder collapses per-method-group sections into one anchor per (gmu, species) — section count ≠ record count

The CO big-game artifact (`extracted/big-game-2026.json`) has one section per `(gmu_code, species_group, method_group)` — archery, muzzleloader, rifle, and season_choice are each a separate section. The CO bear artifact (`extracted/black-bear-2026.json`) similarly has one section per `(gmu_code, method_group)`. But `regulation_record` is the anchor entity keyed by `(state, jurisdiction_code, species_group, license_year)` — no `method_group` column. S06.6's `_build_big_game_records` and `_build_co_bear_records` therefore **collapse** all sections sharing a `(gmu_code, species_group)` tuple into ONE record; confidence is `pdf.min_tier` across all rows of all sections in the group; method/season/license detail decomposes onto S06.7's child entities.

**Consequence:** section count (906 big-game sections + bear sections) ≠ record count (398 rows). S06.7+ link-table builders must group or key on the already-written `regulation_record` PKs the same way — do NOT assume one link row per section entry.

This differs from MT, where DEA sections are already one-per-`(species, HD)` and no collapse is needed. Reference: `ingestion/states/colorado/load_regulation_records.py::_build_big_game_records` (collapse loop) + `_build_co_bear_records` (S06.6).

Surfaced by S06.6 implementation on 2026-06-18.

### CO big-game artifact pre-separates species — no `deer` fan-out needed or correct

The CPW big-game extractor (`extract_big_game.py::_species_group_for`) emits `mule_deer`, `whitetail`, `elk`, and `pronghorn` directly; whitetail is split from mule_deer at extraction via Rule R11 (`_WHITETAIL_UNIT_RE`). There is **no** `"deer"` label in the CO big-game artifact. The CO loader therefore has **no** `_DEA_SPECIES_FANOUT` dict — contrast MT, where DEA `"deer"` fans out to `mule_deer` + `whitetail` at the link-table layer.

Do NOT add a redundant fan-out for CO; it would double-count. Q16 (row-level mule_deer/whitetail separation) does NOT fire for CO — the separation is section-level in the extractor. S06.7+ link-table builders that assume a `deer` label need to be guarded: `assert "deer" not in artifact_species_values` or equivalent.

Reference: `extract_big_game.py::_species_group_for` (the species map); `load_regulation_records.py::_build_big_game_records` (no fan-out dict) — compare with `montana/load_regulation_records.py::_DEA_SPECIES_FANOUT` (S03.6).

Surfaced by S06.6 design decision on 2026-06-18.

### CO bear artifact is a flat list with a `record_type` discriminator — do not port MT's dict-with-`sources`/`rows` shape

`extracted/black-bear-2026.json` is a **flat JSON list** of records. Each entry is a dict tagged `record_type ∈ {"section", "statewide_rule", "reporting_obligation"}`. Bear sections carry `species_group="black_bear"` (mapped to DB value `"bear"` at write time — see existing pitfall above) and a per-record `source_id`. There are **no** top-level `sources`, `rows`, or `statewide_rules` keys.

MT's `_build_bear_records` pattern (`bear_artifact.get("sources")` / `["rows"]` dict-lookup) would silently return `None` on the CO artifact and raise on the key-index. The correct CO pattern: iterate the flat list and filter `record_type == "section"`.

**Critical guard requirement:** do NOT use a bare `r.get("record_type") == "section"` filter — it silently drops any entry with a missing or misspelled `record_type` (e.g. `"Section"` or `"sections"`), violating ADR-001. The correct pattern is the three-step validation in `_build_co_bear_records`:

1. Raise if entry is not a `dict`.
2. Raise if `"record_type"` key is absent (name the present keys in the diagnostic).
3. Raise if `record_type` value is not in `_KNOWN_BEAR_RECORD_TYPES` (name the known types and call out the likely misspelling).

Then keep only `record_type == "section"` entries. Mirror the diagnostic-wrap convention from `load_reporting_obligations.py:399-413` and the E05 audit-hygiene `feature["properties"]` guard fixes.

Reference: `ingestion/states/colorado/load_regulation_records.py::_build_co_bear_records` + `_KNOWN_BEAR_RECORD_TYPES` (S06.6). Compare with `ingestion/states/montana/load_regulation_records.py::_build_bear_records` (the MT dict-shape that must NOT be ported to CO).

Surfaced by S06.6 Stage-6 review on 2026-06-18 (the bare-filter silent-drop failure mode was caught and fixed before merge).

### CO `season_windows` is a list, not MT's season-key-keyed dict — derive the key from `method_group`/positional index

**Symptom:** A CO link-table loader ported from Montana does `for k, v in row["season_windows"].items()` and crashes with `AttributeError: 'list' object has no attribute 'items'`.

**Cause:** MT's DEA extraction artifact emits `season_windows` as a `dict[season_key -> {window, weapon_type_override}]` where the season key (`"archery_only"`, `"general"`, `"late"`, …) is embedded in the structure. CO's big-game and bear extraction artifacts emit `season_windows` as a `list[{start_date, end_date, raw_text}]` — abbreviated dotted-month fragments with NO embedded season key. The positional index and the row's `method_group` / `method_letter` are the only handles for deriving the equivalent key.

**Fix:** In any CO link-table adapter that iterates season windows, iterate by index (`for i, win in enumerate(row["season_windows"])`). Derive the season-key equivalent from `row["method_group"]` (e.g., `"archery_only"`, `"muzzleloader_only"`, `"rifle"`, `"season_choice"`) and the index position within that method group, NOT from a key lookup on the window dict. Add a guard that raises if `season_windows` is not a `list` so MT-dict accidental usage surfaces immediately rather than returning an iterator of characters. Reference: `ingestion/states/colorado/load_seasons_and_licenses.py` season-window iteration (S06.7).

Surfaced by S06.7 implementation on 2026-06-23.

### Lossy dedup on id-text PKs must be made visible — warn on id-collisions where the content differs

**Symptom:** A first-occurrence-wins dedup (`if entity_id not in seen: seen.add(entity_id); emit(entity)`) silently drops a genuinely-different entity that collides on the same derived id. Real CO case: `E-F-085-P5-R` appears on two brochure pages with different `start_date` values (Oct 14 vs Oct 15); the second row was discarded without trace.

**Cause:** First-occurrence-wins is correct for exact duplicates (same id, same content — UPSERT is idempotent). It is wrong when two logically-distinct extraction rows happen to produce the same id because the id-derivation omits a distinguishing field. Silent discard masks a real data gap.

**Fix:** On a collision, compare the distinguishing fields (`start_date`/`end_date`/`weapon_type` for `season_definition`; `kind`/`quota`/`quota_range`/`weapon_types` for `license_tag`). If the fields differ, emit a `WARNING` naming the id, both values, and any page/section references. Stay silent only on identical-content collisions (genuine duplicates). The WARNING is the operator's signal that the id-derivation may need an additional discriminating field in a future extractor revision. Silent dedup of DIFFERING content is data loss masquerading as dedup — it is a faithfulness violation under ADR-008. Reference: `ingestion/states/colorado/load_seasons_and_licenses.py` collision-check pattern (S06.7).

Surfaced by S06.7 Stage-6 review on 2026-06-23.

### Merged-cell extractor gaps produce zero-window rows — load faithfully and warn, do NOT silently add cross-row inheritance

**Symptom:** ~477 CO female (`-F-`) rifle `license_tag` rows are written with zero linked `season_definition` rows because pdfplumber merged the female rows' season-date cells into the adjacent male row's cell during extraction — the artifact faithfully carries `season_windows: []` for those rows. A loader that silently skips zero-window rows (or silently inherits the same-GMU male row's window) writes a structurally incomplete artifact without any operator signal.

**Cause:** The extraction artifact is a faithful transcript of what pdfplumber returned; the per-row gap is not a loader bug. However, the decision of whether female tags should inherit the male-row season windows is a cross-row data-modeling call — it requires understanding the CPW regulatory intent (shared season vs. separate seasons). That decision belongs in a future extractor carve-out or a flag-and-discuss cycle, not in a loader that silently adds cross-row state to keep the count tidy.

**Fix:** The loader must (a) faithfully write what the artifact contains — a `license_tag` row with no linked `season_definition` rows is valid and correct given the artifact; (b) emit a `WARNING` for every row that produces zero output entities (naming species, GMU, method, and hunt code) so the gap is visible in run logs and can be quantified in the story's closure note. Do NOT silently add cross-row season-window inheritance in the loader — that is a state-specific modeling decision that bypasses review. Reference: `ingestion/states/colorado/load_seasons_and_licenses.py` zero-window WARNING pattern (S06.7).

Surfaced by S06.7 Stage-6 review on 2026-06-23.

### An id-derivation function parameter not encoded in the id string is a footgun — keep parameters == encoded fields

**Symptom:** A pure id-derivation function accepts a parameter that it does not embed in the returned id string. The ADR-020 drift-guard re-derivation re-derives the SAME id regardless of that parameter's value — so every `assert_id_matches` call passes while the docstring implies the parameter is load-bearing, and a future caller can pass a wrong value with no failure. Real CO case: `_co_season_definition_id` originally accepted an unused `season_code` parameter; removing it was required before the drift guard could be meaningful.

**Cause:** Parameters accumulate during iterative development; a field may have been intended for the id but was omitted from the format string "temporarily" and then forgotten.

**Fix:** Keep id-derivation function parameters in exact correspondence with the fields the id format string actually encodes — no more, no fewer. If a parameter is present but not in the format string, either add it to the format string (if it should be part of the id) or delete it from the function signature. A docstring that lists a parameter not embedded in the id is a lie that prevents the drift guard from working. Reference: `ingestion/states/colorado/load_seasons_and_licenses.py::_co_season_definition_id` (S06.7 — `season_code` removed). Extends the "name the source-of-truth before copying numbers" discipline to function signatures.

Surfaced by S06.7 Stage-4 plan review on 2026-06-23.

### A downstream story's premise can assume artifact fields the upstream extractor never captured — probe field presence on the committed artifact before planning

**Symptom:** A story spec reads plausibly: "derive hybrid pool splits, residency caps, deadlines, and successor chains from the committed CO extraction artifacts." At Stage-2 discovery, a direct artifact probe reveals that ALL rows in `big-game-2026.json` have `apply_by=null`, `quota=null`, `quota_range=null`, and no `draw_phase` or `successor_hunt_code` fields at all. The per-unit extractor (S06.3) captured hunt tables from the brochure's hunt-code pages (pp. 33–71) but not the draw-instructions front matter (pp. 8–32) where CPW publishes that data. This forced a mid-epic carve-out (S06.8.0) to extract the front matter first, delaying the downstream story.

**Cause:** Spec authors write against the source PDF — they know the data is *somewhere* in the document. But the upstream extraction story scoped only a subset of the PDF's sections. The downstream spec inherits the assumption "if the PDF has it, the artifact has it." That inference is wrong whenever the upstream extractor's page range excludes the relevant section.

**Fix:** During Stage-2 discovery for any story that reads from a committed extraction artifact, verify field presence explicitly before writing the plan. For JSON artifacts:

```bash
python -c "
import json, collections
rows = json.load(open('ingestion/states/colorado/extracted/big-game-2026.json'))
all_rows = [r for sec in rows for r in sec.get('rows', [])]
print(collections.Counter(r.get('apply_by') is not None for r in all_rows))
"
```

A result of `Counter({False: 2762})` means the field is universally null and the plan cannot depend on it. Do this for EVERY field the story spec requires. Discovering the gap at Stage-2 is cheap (one grep or json probe); discovering it at Stage-4 plan-review or at build time is a mid-epic carve-out. Extends the "E03 story discovery — source-audit upstream artifacts for every epic-required row type before planning" pitfall (Conventions — Ingestion adapters) to the field-presence level: that pitfall covers missing ROW TYPES; this one covers missing FIELDS on existing rows.

Surfaced by S06.8 Stage-2 discovery on 2026-06-24 (S06.8 draw_spec ingestion probed `big-game-2026.json` and found null `apply_by`/`quota`/`quota_range` on all 2,762 rows; CPW draw-instructions front matter was unextracted; carve-out S06.8.0 was required).

### Multi-column reference tables split across several `find_tables()` results — attribute header-less continuations to the preceding header table; recover callout lines via bbox crop

**Symptom:** A brochure section presents species/category codes in a visual grid whose pdfplumber extraction returns one header row and multiple header-less continuation blocks — often with an additional category (e.g., bear) that appears nowhere in any returned table at all, living instead in a callout text line adjacent to the grid.

**Cause:** pdfplumber's `find_tables()` splits visual columns into separate `Table` objects when it detects column gaps. A two-part table (header row + continuation rows) surfaces as TABLE A (header) followed by TABLE B (no header) — there is no parent-child relationship; only rendering order signals the connection. Separately, bear hunt codes on CPW p. 29 live in a callout / shaded-box line that pdfplumber never classifies as a table row.

**Concrete case:** CPW Big Game brochure p. 29 "Hybrid Draw Hunt Codes" — deer, elk, and pronghorn blocks each surface as a 1-row header table followed by 1–2 header-less continuation tables. Bear codes are in a standalone callout recovered only via `extract_text(page, bbox=(x0, y0, x1, y1))` crop, not via any `find_tables()` result.

**Fix — continuation attribution:** after finding a header table, attribute subsequent HEADER-LESS tables to the same category until the next header-bearing table appears. A header table is distinguished by having a first cell matching a known category name (e.g., `"Deer"`, `"Elk"`); a header-less table has a numeric or code first cell. Collect all tables in page order; walk them once, carrying `current_category` state.

**Fix — callout lines:** for sub-blocks that are not tabular (sidebars, shaded callout boxes), use a column-scoped bbox crop — `extract_text(page, bbox=(x0, y0, x1, y1))` — to isolate the region, then parse codes from the resulting text with a regex. Do not attempt to recover these via `find_tables()`. Pair with the existing multi-column-prose crop pitfall above (keep crop edges in inter-line whitespace, add fail-loud regex-anchor guard).

Surfaced by S06.8.0 real-PDF probe on 2026-06-24 (CPW draw-instructions front matter p. 29 "Hybrid Draw Hunt Codes" section).

### A per-category non-zero guard does not catch partial under-extraction — pin exact counts when known, and use ONE dedup strategy across all extraction paths

**Two related findings from S06.8.0 (hybrid draw-code extractor):**

**Finding A — band guards miss partial under-extraction.** The hybrid extractor guarded (a) "each of the 4 species categories must yield ≥ 1 code" and (b) a total count band `[80, 160]`. But a partial bear extraction (1–2 of the known 3 codes) passes both: the non-zero-per-category guard fires only at zero; the band guard is satisfied by `1+39+38+36=114`, which is well within `[80, 160]`. The 3 specific bear codes were identified empirically from the PDF (3 distinct `B-*` codes on p. 29); any under-extraction is detectable only via an exact-count assertion, not a band.

**Fix:** When an exact empirical count is known for a category, assert it exactly with a fail-loud check before the write boundary. Keep the band guard as a sanity check for the total, but add a per-category exact-count assertion for categories whose cardinality is fully enumerable from the source document.

**Finding B — mixed dedup strategies admit conflicting duplicates.** The bear path used `sorted(set(tuples))` (dedup on the full tuple). The table-species path used a `seen: set[str]` first-occurrence-wins guard keyed on the hunt-code string. A bear code appearing with both a plain form and a footnote-marker form (`*` suffix) in the source would produce one canonical entry via the tuple-set approach. If that same code appeared across both paths — e.g., from both the callout and a continuation table — the two paths would produce TWO records with potentially different attributes, because the tuple-set and the seen-set are separate and do not prevent cross-path duplicates. The inconsistency is invisible at test time because the two paths are exercised by separate test fixtures.

**Fix:** Use ONE dedup strategy across all extraction paths: dedup by identity key (hunt-code string), first-attribute-wins, applied after all paths have run. Collect into a single `dict[str, record]`; a late-arriving duplicate for an already-seen code logs a `WARNING` (same pattern as the "Lossy dedup on id-text PKs must be made visible" pitfall) rather than silently winning or being silently dropped. Reference: `ingestion/states/colorado/extract_draw_mechanics.py` unified-dedup pattern (S06.8.0).

Surfaced by S06.8.0 Stage-6 review on 2026-06-24.

### Backfill-id derivation must byte-mirror the upstream builder — grep the call site before writing the walk

**Symptom:** A loader that backfills a soft-FK onto rows another loader already wrote (e.g., S06.8 backfilling `license_tag.draw_spec_key` onto S06.7's `license_tag` rows) produces zero or wrong hits at `db.update_*` because the derived target id diverges from the id the upstream builder stored.

**Cause:** Subtle divergences accumulate silently. Common failure modes: (a) using a section-level fallback field (`row["section"]["gmu_code"]`) where the upstream used the row-level field (`row["gmu_code"]`); (b) mismatching species_group canonicalization (`"black_bear"` vs. the DB value `"bear"`); (c) inconsistent blank-row skip behavior. Each divergence makes the backfill target a nonexistent id — caught best-case by `db.update_*`'s `cur.rowcount == 0` fail-loud guard, but silently overwrites the wrong row worst-case.

**Fix:** Before writing the backfill walk, grep the upstream builder's `_*_id(...)` call site directly: `grep -n "_id(" ingestion/states/colorado/load_seasons_and_licenses.py`. Copy the field-access expression verbatim; do not paraphrase. If the upstream builder skips blank/malformed rows, the backfill must apply the same skip condition or it will attempt to update ids that were never written. Add a code comment at the call site naming the upstream module + function + approximate line number, e.g. `# must match load_seasons_and_licenses.py:_co_license_tag_id call at :1345`. Reference: `ingestion/states/colorado/load_draw_specs.py` backfill walk (S06.8).

Surfaced by S06.8 Stage-2 discovery on 2026-06-26.

### Malformed upstream values that become PKs — skip-with-WARNING, never normalize in the loader

**Symptom:** An extractor emits a row whose hunt-code field carries a trailing artifact (e.g., `"B-E-851-O2-R +"` from a pdfplumber row-fusion residual). The downstream loader receives it, derives a PK from it, and must decide: normalize the value and write a clean row, or skip it.

**Cause:** Normalizing in the loader is incoherent when a sibling loader already wrote the same corrupted id from the same artifact — the "cleaned" backfill would target a nonexistent id. The loader does not own the extraction layer; it must treat the artifact as authoritative (ADR-008). A `"B-E-851-O2-R +"` id in one loader does not match the `"B-E-851-O2-R +"` id that S06.7's `license_tag` writer used, so the backfill fails regardless. The real fix is at the extractor (ADR-022 — extractors own extraction).

**Fix:** Skip the malformed row with a `WARNING` naming (a) the raw value, (b) the row index/context, and (c) the extractor that should be fixed. Do NOT normalize/clean in the loader — that creates a silent mismatch with any sibling loader using the same artifact. Track skipped-row counts and include them in the `--dry-run` summary so the operator knows how many rows were affected. Note: cubic and the review triad disagreed on skip-vs-faithful-load here; the human ratified skip-with-WARNING (S06.8, 2026-06-27). Reference: `ingestion/states/colorado/load_draw_specs.py` malformed-hunt-code skip path (S06.8).

Surfaced by S06.8 Stage-6 review on 2026-06-27.

### Derive-and-asserted constants that are validate-only (not consumed in construction) must be marked with a comment

**Symptom:** A module-level `Final` constant (e.g., `_HYBRID_ELIGIBILITY_POINT_LINE: Final[int] = 6`) is asserted against an artifact field to validate it, but is not used in pool construction or any other runtime logic. Static analysis (cubic, ruff unused-variable) and human reviewers flag it as a dead constant or "unused import."

**Cause:** Some constants encode an UPSTREAM determination already applied by the extractor — the hybrid-vs-non-hybrid decision was made by `extract_draw_mechanics.py` and is encoded in the artifact's `hybrid_mechanics.point_line` field. The loader's `_HYBRID_ELIGIBILITY_POINT_LINE` validates that the artifact's value matches the expected threshold, but the pool-construction logic does not need to read it at runtime (the artifact already carries the result of applying it). Without a comment, the intent is invisible.

**Fix:** Add a comment directly on the constant's definition explaining that it is a validate-only drift guard, not a construction input: `# validate-only: asserted against artifact field at L<lineno>; not consumed in pool construction`. This prevents a future refactor from either deleting it (losing the drift guard) or "fixing" it by wiring it into construction logic where it doesn't belong. Reference: `ingestion/states/colorado/load_draw_specs.py::_HYBRID_ELIGIBILITY_POINT_LINE` (S06.8).

Surfaced by S06.8 Stage-6 review on 2026-06-27.

### Conflict-detection validators must compare raw artifact values — not coerced or normalized ones

**Symptom:** A cross-listing / quota-conflict guard converts values before checking for conflicts: `values.add(int(quota))`. Two distinct artifact encodings that coerce to the same integer (e.g., `"300"` and `300`) collapse into one set entry, and the conflict check `len(values) > 1` silently produces false-negative (no conflict detected).

**Cause:** Coercion before comparison loses the encoding distinction that the artifact faithfully preserves. For a guard whose job is to detect unexpected variation, a coercion step widens the equivalence class in ways that are not always sound — two semantically different values (e.g., `"N/A"` coerced to `0` alongside a real quota of `0`) would incorrectly appear identical.

**Fix:** Store the raw artifact value string in the comparison set: `values.add(str(quota))` or simply use the unmodified field. Reserve coercion for the downstream write site where the type must conform to the schema. The conflict guard's job is to detect ARTIFACT-level divergence — it must compare at the artifact's own granularity, not at the schema's. Reference: `ingestion/states/colorado/load_draw_specs.py::_validate_cross_listing_consistency` (S06.8).

Surfaced by S06.8 Stage-6 review on 2026-06-27.

### Per-state loader scope can diverge from the MT precedent — confirm the story boundary, not just the code shape, when porting

**Symptom:** A loader for a new state is architected as a port of the equivalent Montana loader. The MT loader combines two jobs in one transaction: writing entity rows AND writing link rows (e.g., MT S03.9 `load_reporting_obligations.py` writes both `reporting_obligation` entity rows AND `regulation_reporting` link rows in one atomic write). The new-state loader faithfully replicates both jobs — importing `RegulationReporting`, calling `db.write_regulation_reporting`, and building link rows — even though the epic's story split assigned link-row writes to a different story.

**Cause:** MT's combined structure is a valid single-story scope for Montana because its `regulation_reporting` links FK only to `regulation_record` (already written). CO's equivalent links FK to BOTH `regulation_record` AND `geometry` — entities whose write order is managed by a distinct story (S06.10). The epic's story boundary reflects this difference: CO S06.9 writes ONLY the `reporting_obligation` entity rows; CO S06.10's binding loader writes the `regulation_reporting` links alongside the jurisdiction bindings. A port that combines both jobs would write link rows before the geometry FK targets exist and would duplicate S06.10's work.

**The state-agnostic-clean AST guard does NOT catch a scope over-port.** The guard verifies that the adapter does not import from sibling state adapters. It does not verify that the adapter stays within its story-scoped write responsibilities. Only reading the epic's story-boundary prose catches this.

**Fix:** Before writing the plan for any new-state loader that mirrors a prior-state combined loader, confirm the NEW state's story boundary explicitly from the epic spec — not from the prior-state code shape. Write down which DB tables this story writes and which tables the next sequenced story writes. Over-porting is invisible to both CI and code-review unless the reviewer checks the epic spec against the module's write calls.

Surfaced by S06.9 scope-boundary confirmation on 2026-06-28 (CO reporting-obligation ingestion; MT's combined S03.9 pattern was NOT ported because CO S06.9 is entity-only, link rows belong to S06.10).

## Integration — MCP server / Cloudflare Workers (serving)

The entries below are the first serving-side pitfalls for this project. S08.1 established the vitest (Node pool) test baseline at **16 tests** — the serving analog of the Python pytest baseline. E09 and E10 grow it additively.

### `createMcpHandler` lives in `agents/mcp` (Cloudflare Agents SDK), not `@modelcontextprotocol/sdk`

The MCP server entrypoint imports `createMcpHandler` from `agents/mcp`. That module is **workerd-only** — it transitively imports `cloudflare:` protocol modules (via `agents/index.js`), so it CANNOT be imported in a plain-Node vitest test. The import throws:

```text
Only URLs with a scheme in: file, data, and node are supported … Received protocol 'cloudflare:'
```

**Fix:** Split the code. Put the testable MCP-server construction in a Node-importable factory (`src/server.ts`) that imports ONLY from `@modelcontextprotocol/sdk`. Keep the thin `createMcpHandler` wiring in the workerd-only entrypoint (`src/index.ts`). Node-pool tests import the factory directly; the entrypoint is verified only by a deployed MCP Inspector run (Group B). `McpServer`, the SDK `Client`, and `InMemoryTransport` ARE Node-importable and can be used freely in vitest.

Empirically verified against `agents@0.17.0`, `@modelcontextprotocol/sdk@1.29.0`, `wrangler@4.105.0`, `vitest@4.1.9` on 2026-06-26 (S08.1).

### `new McpServer({…}, { capabilities: { tools: {} } })` does NOT install a `tools/list` handler

Declaring the `tools` capability advertises it during `initialize` but installs no handler. `client.listTools()` then throws `-32601 Method not found`, and a deployed server errors on `tools/list`. `McpServer` installs the handler only when the first `server.tool()` call is made.

**To serve a conformant EMPTY tool list (zero tools registered), use the SDK's PUBLIC API:** register an explicit empty handler via the public `server.server.setRequestHandler` with the public `ListToolsRequestSchema`:

```typescript
import { ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
server.server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [] }));
```

**The resolution has four constraints that pull against each other** — four separate reviews each flagged one, so the design must satisfy all at once:

1. *No private SDK internals* — the private `setToolRequestHandlers()` / `_toolHandlersInitialized` / `_registeredTools` path makes a foundation depend on non-public surfaces a routine SDK upgrade can break.
2. *Don't block the first real tool* — once any `tools/list` handler is installed, `McpServer.tool()` / `registerTool()` throws `"A request handler for tools/list already exists"`.
3. *Always-valid, no silent handler-less server* — a "registerTools callback" branch that skips the handler when a callback is passed silently yields a `-32601` server if that callback registers nothing.
4. *Extension must be additive via the NORMAL tool API* — serving tools through a hand-written low-level `setRequestHandler(ListToolsRequestSchema, …)` works for E08 but forces E09 into a breaking refactor (it still can't call `server.tool()`); the next story must be able to just call `server.tool(...)`.

**Resolution: register a placeholder tool and immediately `.remove()` it.** This initializes the tools subsystem (installing the tools/list + tools/call handlers) using only PUBLIC API, then leaves zero net tools:

```typescript
export function createMcpServer(): McpServer {
  const server = new McpServer({ name, version }, { capabilities: { tools: {} } });
  // Public + always-valid + additively extensible. registerTool installs the
  // handlers; .remove() leaves them in place with zero tools, so tools/list
  // returns [] AND E09/E10 add tools with the NORMAL server.tool(...) API as a
  // plain additive call (no conflict, no line removed).
  server
    .registerTool("__bootstrap_noop__", { description: "removed immediately" },
      async () => ({ content: [{ type: "text", text: "" }] }))
    .remove();
  return server;
}
```

Satisfies all four: only public API (#1); `server.tool()` afterward is conflict-free because the subsystem is already initialized (#2, #4); the handlers are unconditionally present so the server is always valid (#3). `RegisteredTool.remove()` is public and leaves the request handlers installed.

**Lock it with the PUBLIC protocol, not internals:** over an in-memory `Client`/`Server` pair assert (a) `(await client.listTools()).tools` is `[]` (registry-empty lock), and (b) after calling `server.tool("ping", …)` on a fresh `createMcpServer()`, `tools/list` surfaces `ping` with no throw (additive-extension lock). No `_registeredTools` introspection.

Surfaced by S08.1 2026-06-26; converged 2026-06-27 across four reviews that flagged, in turn: private-internals dependency → `server.tool()` double-register block → a callback variant's silent handler-less server → the low-level-handler variant still blocking the normal tool API. Register-then-remove is the only public idiom that is always-valid AND additively extensible via `McpServer.tool()`.

### Stateless Workers + MCP SDK ≥ 1.26 require per-request server/transport instantiation

Construct the `McpServer` + handler INSIDE the `fetch` handler, never at module/global scope. workerd cannot safely share server/transport state across concurrent invocations, and SDK ≥ 1.26 enforces per-request construction. (`@modelcontextprotocol/sdk ^1.9.0` resolves to `1.29.0` via the `agents` peer pin, so this constraint applies to this project.)

Since `src/index.ts` is workerd-only and cannot be unit-imported, lock the per-request pattern with a source-scan test:

```typescript
// assert createMcpServer() appears AFTER async fetch(
const src = fs.readFileSync("src/index.ts", "utf8");
const fetchIdx = src.indexOf("async fetch(");
const callIdx = src.lastIndexOf("createMcpServer()");
assert(callIdx > fetchIdx, "createMcpServer() must be called inside the fetch handler");
```

Use `lastIndexOf` for the call site so an earlier mention in a comment cannot fool the assertion.

Surfaced by S08.1 implementation on 2026-06-26.

### `wrangler.jsonc` needs `compatibility_flags: ["nodejs_compat"]` — and must NOT contain a `durable_objects` block

`agents/mcp` imports `node:async_hooks`. Without `nodejs_compat` in `compatibility_flags`, the Worker fails to start. Add it to `wrangler.jsonc`:

```jsonc
"compatibility_flags": ["nodejs_compat"]
```

Also: keep the committed `wrangler.jsonc` free of any `durable_objects` binding or `migrations` block. V1 MCP tools are stateless reads — no Durable Object is needed. The `remote-mcp-authless` Cloudflare template scaffolds the DO/`McpAgent` path; following the `createMcpHandler` guide directly avoids it.

### Zod schema ↔ TS interface drift-guard: `AssertEqual` for flat schemas; `satisfies` + a key-set check for optional-field schemas

When a zod schema must stay in lockstep with a TypeScript interface (e.g. `getRegulationsResponseSchema` mirroring `GetRegulationsResponse` in `response.ts`), add a compile-time guard. For **flat schemas with no optional `?` fields**, use the bidirectional `AssertEqual` — it catches BOTH missing and extra fields:

```typescript
type AssertEqual<A, B> = [A] extends [B] ? ([B] extends [A] ? true : never) : never;
const _assertX: AssertEqual<z.infer<typeof xSchema>, X> = true;
```

For schemas with optional object properties or that embed types that do (in S08.3: `ReservedPool.eligibility`, `AllocationPool.eligibility`/`tie_break?`, and `DrawSpec` which embeds both), `AssertEqual` is brittle because zod models optionals as `T | undefined` in ways that break the bidirectional check. **`satisfies z.ZodType<Interface>` alone is NOT a sufficient replacement: it is ONE-directional** — it checks the schema's output is assignable to the interface (catching a missing or mistyped key) but NOT the reverse, so an **EXTRA key in the schema slips through** (its output is still structurally assignable). Pair `satisfies` with a top-level key-set equality assertion to recover extra/missing-key detection without tripping the `T | undefined` brittleness:

```typescript
type SameKeys<A, B> = [keyof A] extends [keyof B] ? ([keyof B] extends [keyof A] ? true : never) : never;
export const xSchema = z.object({ ... }) satisfies z.ZodType<X>;   // missing/mistyped keys
const _kX: SameKeys<z.infer<typeof xSchema>, X> = true;            // extra/missing keys
```

(Residual gap — `satisfies` + top-level `SameKeys` is NOT full NESTED coverage: both guards only see TOP-LEVEL keys. Inside an inline sub-object (e.g. `AllocationPool.eligibility`), neither an EXTRA key nor a MISSING/renamed OPTIONAL key is caught — `satisfies z.ZodType<T>` accepts any structurally-assignable nested shape, and `SameKeys` never descends past the top level. So nested optional-field drift — adding, dropping, or renaming a `min_acres?`-style key — passes silently. To get nested lockstep, extract the sub-object into its own named schema with its own `AssertEqual`/`SameKeys` guard, or keep inline sub-objects trivially small and review them by eye. Do not treat `satisfies` + top-level `SameKeys` as proof the nested shapes match.) The optional-field brittleness is inherent to zod's optional modeling — NOT specific to a zod major version, so a version bump will not unlock `AssertEqual`. Never reach for `@ts-expect-error` to force `AssertEqual` — the need to switch to `satisfies`+`SameKeys` IS the signal. (See `src/output-schema.ts`.) **Separately, for the RUNTIME contract:** make serving-composition response schemas `.strict()` so a server-composed `overview`/`headline` or any unknown key fails validation rather than passing through into `structuredContent` (`.strict()` does not change `z.infer`, so the compile-time guards still hold); leave embedded passthrough ENTITY schemas non-strict.

Surfaced by S08.3 2026-06-29; strengthened 2026-06-29 (satisfies one-directional gap + `.strict()` runtime guard).

### `Date.parse` returns `NaN` on malformed input — every NaN comparison is `false`, making stale data look fresh

`Date.parse(malformed)` returns `NaN`, and `NaN > 180` is `false`, so an unparseable date silently passes the staleness check as if it were fresh. In a freshness/staleness computation (a correctness property, ADR-001), guard at the computation site for EVERY parsed input — both `generatedAt` AND each source `publication_date`, not just the one you happen to select. **`Number.isNaN(Date.parse(x))` is necessary but NOT sufficient for `YYYY-MM-DD` source dates:** `Date.parse`'s legacy fallback parser ACCEPTS non-canonical strings (`"2026-1-1"`, `"01/02/2026"` — often in LOCAL time with different semantics), and some impossible dates ROLL OVER instead of rejecting (`Date.parse("2026-02-30T00:00:00Z")` → 2026-03-02, not NaN). For a canonical date, (1) require the exact `^\d{4}-\d{2}-\d{2}$` shape, then (2) round-trip the parsed UTC date back to `YYYY-MM-DD` and require equality with the input — this rejects both non-canonical formats and impossible calendar dates. Do NOT add this as a value-format regex on the serving-layer zod OUTPUT schema (format validation of stored data is the ingestion layer's job; over-constraining the serving boundary risks rejecting legitimately-stored passthrough data, ADR-001 authority-preserved) — the guard belongs at the freshness COMPUTATION site, where you genuinely cannot compute days-stale from a non-date. (See `parseSourceDate` / `buildDataFreshness` in `src/response-builder.ts`.)

Surfaced by S08.3 2026-06-29; strengthened 2026-06-29 (canonical-format + round-trip, not just NaN).

### `gateBySchemaVersion` returns warnings — callers must wire them into `meta.warnings` or they are silently dropped

`gateBySchemaVersion(rows)` returns `{ included, warnings }` and emits one `UNSUPPORTED_SCHEMA_VERSION` warning per excluded row — but it cannot force the caller to propagate those warnings into the response `meta.warnings`. An E09/E10 tool handler that uses `included` but drops `warnings` silently loses data with no user-visible signal, violating ADR-006's "never silent-drop" promise. Every call site in E09/E10 must spread the returned warnings into `meta.warnings`. Consider an AST guard or test lock when those stories land to prevent a future handler from omitting the wire-up. (See `gateBySchemaVersion` in `src/response-builder.ts`.)

Surfaced by S08.3 2026-06-29.

### Internal health check = HTTP route (`/healthz`), NOT a registered MCP tool

To exercise the envelope and a real DB read end-to-end without inflating `tools/list` (the S08.1 registry-empty lock), wire it as an HTTP route in `src/index.ts` that calls a Node-importable function (`runHealthCheck` in `src/health-check.ts`), NOT via `registerTool`. The entire DB-client lifecycle — including `createDbClient()` construction — belongs inside try/finally so that even a malformed or missing DSN degrades to a structured `{ ok: false }` 503 response, never a hard 500. Optional-chain the `close()` call (`client?.close()`) since `createDbClient()` may itself throw before `client` is assigned. The MCP SDK's `structuredContent` boundary is typed `Record<string, unknown>` — cast the validated response with `as unknown as Record<string, unknown>` (the single sanctioned any-free seam, mirroring the pattern in `src/db.ts`). (See `src/health-check.ts` + `src/index.ts`.)

Surfaced by S08.3 2026-06-29.

Lock the no-DO constraint with a config-text test matching the snake_case key:

```typescript
const cfg = fs.readFileSync("wrangler.jsonc", "utf8");
assert(!cfg.includes("durable_objects"), "wrangler.jsonc must not contain a durable_objects block");
```

Note: a human-readable comment `"// No Durable Objects"` does NOT contain the substring `durable_objects` (it has a space), so this assert is safe against such comments.

Surfaced by S08.1 implementation on 2026-06-26.

### CORS headers must be applied to EVERY response in the workerd `fetch` entrypoint — including responses the entrypoint did not build

`createMcpHandler` (from `agents/mcp`) returns its own `Response` that knows nothing about the caller's CORS policy. An uncaught throw from the MCP handler — or from a helper like `runHealthCheck` — surfaces as a Cloudflare platform 500 with NO CORS headers, which is invisible to a browser-origin MCP client as an opaque CORS error rather than a readable failure.

**Fix (shipped in S08.4 `mcp-server/src/index.ts`):** write a pure `applyCorsHeaders(response, corsHeaders)` re-wrapper and apply it to (a) the handler's return value, (b) every `/healthz` branch response, and (c) 404 responses. Wrap the MCP handler call and `runHealthCheck` call each in their own `try/catch` that returns a CORS-headered 500/503. The preflight 204 short-circuit passes `corsHeaders` directly (no upstream response to wrap).

Surfaced by S08.4 2026-06-29.

### The wildcard-vs-credentials CORS trap: never set `Access-Control-Allow-Credentials` on an open endpoint

`Access-Control-Allow-Origin: *` combined with `Access-Control-Allow-Credentials: true` is silently rejected by all browsers (CWE-942-class misconfig). MCP clients authenticate via the `Authorization` bearer header, not cookies, so credentials mode is never needed — omitting `Access-Control-Allow-Credentials` keeps the permissive `*` default safe for the open V1 endpoint. Lock this absence with tests in `mcp-server/tests/cors.test.ts` asserting the header is `null` on both preflight and non-preflight responses.

Note also: `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers`, and `Access-Control-Max-Age` are preflight-only response headers (browsers ignore them on simple responses), but emitting them uniformly on the preflight 204 is the idiomatic, harmless middleware default.

Surfaced by S08.4 2026-06-29.

### CORS preflight (`OPTIONS`) must short-circuit BEFORE any auth check

A CORS preflight carries no credentials per RFC 6454. If an auth seam runs first it 401s the preflight and breaks every browser MCP client before the actual request is ever attempted. The dispatch order in the Worker `fetch` entrypoint must be: **preflight → auth → routes**. Detect a genuine preflight via `OPTIONS` + `Origin` + `Access-Control-Request-Method` (a bare `OPTIONS` is not a preflight; a POST cannot masquerade as one).

Surfaced by S08.4 2026-06-29.

### Locking dispatch ORDER in a workerd entrypoint that cannot be imported in the Node vitest pool — use an AST source-order assertion

`mcp-server/src/index.ts` imports `agents/mcp` (workerd-only), so it cannot be imported in the Node vitest pool — only its pure helper modules (`cors.ts`, `auth.ts`) can be unit-tested. To lock a load-bearing wiring invariant (e.g. "preflight check dispatched before the auth check") without booting workerd, add an AST test in `tests/boundary.test.ts` that parses `index.ts` with the TypeScript compiler API and asserts the source position of one call (`isCorsPreflightRequest`) precedes another (`isAuthSeamEnabled`) — using the existing `callsToIdentifier` helper + `node.getStart(sf)`. This is the exact analog of the per-request-instantiation AST guard (Test 3) and the no-`ingestion`-import guard already in that file.

Surfaced by S08.4 2026-06-29.

### Keep `@types/node` out of the Workers `src` tsconfig — split into base + test configs

A single `tsconfig.json` with `"types": ["@cloudflare/workers-types", "node"]` lets Node globals (`process`, `Buffer`, `__dirname`, sync `fs`) type-check cleanly in `src/` even though they don't exist in workerd — a runtime failure that `tsc` silently misses.

**Fix:** split into two tsconfig files:

- **`tsconfig.json`** (base) — `"types": ["@cloudflare/workers-types"]`, `"include": ["src/**/*.ts"]`. This is the gate that keeps Node globals out of Worker source code.
- **`tsconfig.test.json`** — extends the base, adds `"node"` to `types`, sets `"include": ["tests/**/*.ts", "src/**/*.ts"]` for the test runner.

Make `lint` run both: `tsc --noEmit && tsc --noEmit -p tsconfig.test.json`.

Verified: a `process.env` reference in `src/` correctly fails `tsc --noEmit` with TS2591 under this split, and passes under the test config.

Surfaced by S08.1 implementation on 2026-06-26.

### `createMcpHandler`'s default route is `/mcp` — all clients must target that path

Requests to any other path return a silent 404. Clients (MCP Inspector, `mcp-remote`, E09/E10 integration tests) must hit `<origin>/mcp`. Name the route explicitly in a README or in-source comment so a path mismatch is not misread as a deploy failure.

Surfaced by S08.1 implementation on 2026-06-26.

### Drop `passWithNoTests: true` from `vitest.config.ts` once any test file exists

`passWithNoTests: true` is appropriate only during bootstrap before any test file exists. Afterward it is a CI footgun — a glob that resolves to zero files (e.g., a case-renamed `tests/` directory on a Linux CI runner) exits 0 and passes CI green with the entire test gate silently absent.

Remove the option as soon as the first test file is committed. The S08.1 baseline test file removes it.

Surfaced by S08.1 implementation on 2026-06-26.

### Use `postgres` (postgres.js) as the edge Postgres driver for Supabase — NOT `@neondatabase/serverless`

**Symptom:** Reaching for `@neondatabase/serverless` as "the serverless/edge Postgres driver" for a Supabase backend. Its `fetch`-HTTP mode (`neon()`) speaks ONLY to Neon's proprietary SQL-over-HTTP endpoint — not to Supabase's Supavisor or direct Postgres. Its WebSocket `Pool` mode requires a `wsproxy` process in front of Postgres. Neither path targets Supabase cleanly.

**Fix:** Use the `postgres` npm package (postgres.js). It speaks the standard Postgres wire protocol and runs in BOTH Node (TCP sockets, used by the vitest Node pool) and `workerd` (`cloudflare:sockets`, enabled by the `nodejs_compat` compatibility flag). For Supabase's Supavisor transaction-mode pooler, two settings are mandatory:

- `prepare: false` — named prepared statements are connection-scoped; Supavisor remaps connections per transaction, so named statements are unavailable.
- `max: 1` — workerd cannot reuse outbound sockets across requests; one connection per invocation is the correct model (connect-per-request, no shared pool).

Construct the client per request inside the `fetch` handler, never at module scope. `@supabase/supabase-js` is the PostgREST HTTP client, not a wire-protocol driver, and is rejected by ADR-024 for the serving stack.

Surfaced by S08.2 driver spike on 2026-06-27; decision recorded in ADR-024 addendum.

### Serving-CI Group A/B split for edge-only infra; PostGIS types are bare, only PostGIS function calls take `extensions.` prefix

**Two related findings from S08.2 (edge-Postgres access layer and CI substrate):**

**Finding A — role-level write-rejection tests can run in Node, not workerd.** A read-only-enforcement test (asserting that a `SELECT`-only role's write attempt raises `SQLSTATE 42501`) seems unrunnable in the vitest Node pool because Hyperdrive and other workerd-native edge bindings are unavailable in Node. However, `postgres` (postgres.js) runs in Node over TCP just as it runs in workerd over `cloudflare:sockets`. The enforcement test can therefore run in Node against a local or CI `postgis/postgis` Docker image with the committed `GRANT SELECT` applied (Group A, at-merge); the workerd runtime-compatibility proof is a deployed live check (Group B, operator-pending). The key constraint: the write-rejection MUST be a real `SQLSTATE 42501` from a `SELECT`-only role over the committed GRANT — never a mock that just throws.

**Finding B — in a CI substrate DDL, PostGIS types are bare but PostGIS function calls still need `extensions.` prefix.** Writing `geom extensions.geography(MultiPolygon, 4326)` in a `CREATE TABLE` fails with `type "extensions.geography" does not exist`. PostGIS types (`geography`, `geometry`, `box2d`, etc.) are registered in `pg_type` and resolved via `search_path` — reference them bare, exactly as the real migrations do: `geom geography(MultiPolygon, 4326)`. Only PostGIS *function calls* take the `extensions.` prefix (`extensions.ST_IsValid(...)`, `extensions.ST_DWithin(...)`, etc.). Additionally, a CI substrate must be minimal hand-authored DDL — NOT the real Supabase migrations — because the deny-all RLS migration references `anon` and `authenticated` roles absent from a vanilla `postgis/postgis` image. A `SELECT`-only role under `FORCE RLS` also needs an explicit `FOR SELECT ... USING (true)` ALLOW policy, because the deny-all policies are scoped to `anon`/`authenticated` only and do not cover a custom CI role.

Surfaced by S08.2 CI substrate authoring on 2026-06-27 (`ci-substrate.sql` + `grant-readonly-role.sql`).

### Workers tool handlers have no `process.env` — thread the DSN via a factory that closes over the `env` binding

**Symptom:** A tool handler reads `process.env.SUPABASE_READONLY_DSN` at call time. The Workers runtime has no `process` global (`@cloudflare/workers-types` provides none), so the reference throws at workerd startup — not at test time, because vitest runs in Node where `process` exists.

**Why:** The DSN is available only inside `src/index.ts`'s `fetch(request, env, ctx)` callback, on the `env` binding typed to `WorkerEnv`. Module-scope code runs before any request arrives and cannot access `env`.

**Fix / convention:** A tool handler is produced by a factory that closes over the DSN — `createGetRegulationsHandler(dsn: string)` — and `createMcpServer(dsn)` threads `env.SUPABASE_READONLY_DSN` from the per-request `fetch` entrypoint down to each tool's factory. Every E09/E10/E11 tool inherits this pattern. The split tsconfig (`tsconfig.json` omits `"node"` from `types`) makes `process.env` a compile-time error in `src/` — catching the mistake before workerd does.

Discovered in S09.1a 2026-07-01; the original plan wrongly assumed `process.env` was available.

### `npm run lint` typechecks test files; `vitest` does NOT — always run lint before declaring green

**Symptom:** `npx vitest run` exits 0 (all tests pass), but `npm run lint` fails with type errors in `tests/`. A type change in `src/` (e.g. making `buildDataFreshness` return `{…} | null`) leaves test files failing `tsc -p tsconfig.test.json` while vitest never surfaces the errors. In S09.1a this produced 7 `TS18047 'result' is possibly 'null'` errors in `response.test.ts` that vitest silently ignored.

**Why:** vitest uses esbuild for transformation — no type checking. `mcp-server`'s `lint` script is `tsc --noEmit && tsc --noEmit -p tsconfig.test.json`, so it typechecks BOTH `src/` and `tests/`.

**Fix:** Always run `npm run lint` (not just `npx vitest run`) before reporting a change as green. Add it to any local "done" checklist. CI runs both; a local-only vitest green is insufficient.

Surfaced by S09.1a 2026-07-01.

### `buildStructuredToolResult` is the SOLE writer of `meta.warnings` — handlers must init `meta.warnings: []`

**Symptom:** A tool handler accumulates warnings (e.g. from `gateBySchemaVersion`) into a local array, writes them into the response object's `meta.warnings` at construction time, and ALSO passes the same array as the `warnings` argument to `buildStructuredToolResult`. Today this is a no-op (same reference; the builder assigns the same array back). It is a latent double-write: if the builder ever changes to append rather than assign, every warning is duplicated.

**Why:** `buildStructuredToolResult(payload, schema, warnings, renderText)` takes ownership of `warnings` and assigns `payload.meta.warnings = warnings`. The handler should not write `meta.warnings` directly.

**Convention:** Build the response with `meta.warnings: []` and let `buildStructuredToolResult` be the only writer. Accumulate gated warnings (from `gateBySchemaVersion(…).warnings`) into a local array and pass it as the builder's `warnings` argument — never also assigning it to the response object beforehand.

Surfaced by S09.1a 2026-07-01.
