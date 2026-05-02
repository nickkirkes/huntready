# E02 Geometry Verification Runbook

Verifies that E02 Montana geometry rows (S02.0–S02.6) loaded correctly and that spatial queries, topology, multi-part structure, and overlay relationships are sound. See [ADR-004](../adrs/ADR-004-supabase-postgres-postgis.md) (Supabase + PostGIS) and [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md) (overlay thresholds); the overlay artifact is at `ingestion/states/montana/fixtures/geometry-overlays.json`.

## Prerequisites

- `psql` connected to the Supabase project using the service-role `DATABASE_URL` (provides RLS bypass for read; anon/authenticated roles will be denied on every query).
- The 349 V1 Montana geometry rows loaded (S02.0–S02.5 complete; confirmed by `SELECT count(*) FROM geometry WHERE state='US-MT'` returning 349).
- The spot-check fixture committed at `../../ingestion/states/montana/fixtures/spatial-test-points.json` (relative to this runbook).
- A loaded `ingestion` venv (`ingestion/.venv/`) if running the manifest backfill script in section 6.

## 1. Spot-check via ST_Covers (per-kind verification)

Drive this check from `spatial-test-points.json`. For each entry's `(lng, lat)`, run:

```sql
SELECT id, kind FROM geometry
WHERE ST_Covers(geom, ST_GeogFromText('SRID=4326;POINT(<lng> <lat>)'));
-- Note: geom is geography(MultiPolygon, 4326); ST_Covers(geography, geography)
--   does NOT need a cast workaround — this is a direct geography predicate.
```

**Expected outputs by fixture entry type:**

- **HD / Portion / Restricted-Area (non-orphan) / CWD entries:** one row whose `id` matches the entry's `expected_id_pattern`.
- **Orphan no-hunt zone entries** (Glacier NP, Sun River Game Preserve, Yellowstone NP — IDs in `EXPECTED_RA_ORPHAN_IDS` in `build_overlay_fixture.py`): exactly one row matching the orphan's own ID. No HD parent row should appear — these zones are no-hunt by design and have no parent HD in the overlay map (see [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md)).
- **Control point** (eastern Montana plains, `lng=-106.5, lat=46.8`): zero rows.

**One-shot Python loop** (run from repo root with the ingestion venv):

```python
import json, os, subprocess, pathlib

fixture = json.loads(
    pathlib.Path("ingestion/states/montana/fixtures/spatial-test-points.json").read_text()
)
for pt in fixture["points"]:
    sql = (
        f"SELECT id, kind FROM geometry "
        f"WHERE ST_Covers(geom, ST_GeogFromText('SRID=4326;POINT({pt[\"lng\"]} {pt[\"lat\"]})'))"
        f";"
    )
    print(f"--- {pt['name']} (expected: {pt['expected_id_pattern'] or 'zero rows'}) ---")
    subprocess.run(["psql", os.environ["DATABASE_URL"], "-c", sql], check=True)
```

Or pipe directly:

```bash
cd ingestion && .venv/bin/python - <<'EOF'
import json, os, subprocess, pathlib
pts = json.loads(pathlib.Path("states/montana/fixtures/spatial-test-points.json").read_text())["points"]
for p in pts:
    sql = f"SELECT id,kind FROM geometry WHERE ST_Covers(geom,ST_GeogFromText('SRID=4326;POINT({p[\"lng\"]} {p[\"lat\"]})'))"
    print(f"\n=== {p['name']} ===")
    subprocess.run(["psql", os.environ["DATABASE_URL"], "-c", sql])
EOF
```

## 2. Topology validity check

```sql
-- All geometries must pass ST_IsValid; expected zero rows.
-- Note: ST_IsValid is geometry-only. Direct `geom::geometry` cast is rejected on Supabase
--   (see .roughly/known-pitfalls.md), so we round-trip through WKT.
SELECT id FROM geometry
WHERE NOT ST_IsValid(ST_GeomFromText(ST_AsText(geom), 4326));
-- Expected: zero rows.
```

**Background:** S02.4 loaded one self-intersecting source feature (`MT-HD-antelope-556-geom`, OBJECTID=385, layer #3). `shapely.make_valid` repaired it by extracting the polygonal part from a `GeometryCollection [Polygon, LineString]` — the area was preserved exactly. This query verifies the repair held through the upsert.

## 3. Multi-part HD verification (named)

```sql
-- Expected: 12 (the named anchor multi-part HD).
-- Note: ST_NumGeometries is geometry-only; same WKT round-trip workaround applies.
SELECT id, ST_NumGeometries(ST_GeomFromText(ST_AsText(geom), 4326)) AS parts
  FROM geometry WHERE id = 'MT-HD-deer-elk-lion-690-geom';
-- Expected: one row, parts = 12.
```

`MT-HD-deer-elk-lion-690-geom` is the canonical multi-part HD reference (MT FWP layer #11, loaded 2026-04-30). If this query returns zero rows, S02.2 has not completed. If `parts` differs from 12, investigate upstream source changes via the manifest-diff workflow in section 6.

## 4. EXPLAIN ANALYZE plan documentation

```sql
EXPLAIN ANALYZE
SELECT id FROM geometry
WHERE ST_Covers(geom, ST_GeogFromText('SRID=4326;POINT(-114.320 48.310)'));
```

Paste the plan output inline as a code block when running this section. The plan should show either:

- **`Index Scan using geometry_geom_gix`** — preferred; the GiST index is in use.
- **`Seq Scan`** — acceptable for the V1 dataset of 349 rows. The Postgres planner legitimately chooses a sequential scan when the index has overhead it deems unnecessary for a small table. This is cost-driven, not a bug.

The bug case is a predicate that forces a function call or cast preventing index use entirely. The current predicate (`ST_Covers(geom, ST_GeogFromText(...))`) is index-eligible because both sides are geography — the GiST index on `geometry.geom` is a geography index and supports this predicate directly.

**Important:** overlay computation is NOT a SQL operation — do not attempt to verify HD↔child relationships by running cross-join SQL against Supabase. The 2-min `statement_timeout` aborts the cross-join on real Montana data. The overlay fixture at `ingestion/states/montana/fixtures/geometry-overlays.json` is the pre-computed artifact; see section 7 for architecture details. The point-in-polygon spot-check above (section 1) is the only SQL geospatial path retained from the original S02.7 plan.

## 5. Reproducibility (topological, not byte-level)

This section verifies that re-ingesting Montana geometry from source produces topologically equivalent rows.

**Snapshot before wipe:**

```sql
CREATE TABLE geometry_snapshot AS SELECT * FROM geometry WHERE state = 'US-MT';
-- Or save to CSV: \COPY geometry TO '/tmp/geometry_snapshot.csv' CSV HEADER;
```

**Wipe (scoped to Montana — matches the snapshot above):**

```sql
DELETE FROM geometry WHERE state = 'US-MT';
-- Note: scoped to state = 'US-MT' so re-ingest does not destroy other states'
-- rows. The snapshot above is also Montana-scoped; the two MUST agree.
-- DO NOT use TRUNCATE: it wipes every state and breaks reproducibility for
-- any other state already loaded.
-- E02-only caveat: this DELETE is safe today because nothing yet FK-references
-- geometry.id. Once E03 lands, jurisdiction_binding.geometry_id will reference
-- it; the DELETE will then require a coordinated DELETE from jurisdiction_binding
-- first (or ON DELETE CASCADE).
```

**Re-ingest** (run from repo root):

```bash
ingestion/.venv/bin/python ingestion/states/montana/load_hds.py
ingestion/.venv/bin/python ingestion/states/montana/load_portions.py
ingestion/.venv/bin/python ingestion/states/montana/load_restricted_areas.py
ingestion/.venv/bin/python ingestion/states/montana/load_cwd_zones.py
```

Or via the unified make target if available: `make ingest STATE=montana STAGE=geometry`.

**Compare — topological equality:**

```sql
-- Topological inequality check — expected zero rows.
-- ST_Equals accepts geography directly — no cast needed.
SELECT a.id FROM geometry_snapshot a
  JOIN geometry b USING (id)
  WHERE NOT ST_Equals(a.geom, b.geom);
-- Expected: zero rows.
```

**Compare — row count and id-set parity:**

```sql
SELECT
  (SELECT count(*) FROM geometry_snapshot) AS before_count,
  (SELECT count(*) FROM geometry WHERE state = 'US-MT') AS after_count;
-- Expected: before_count = after_count = 349.

-- ID-set parity (rows present in snapshot but missing after re-ingest):
SELECT id FROM geometry_snapshot
EXCEPT
SELECT id FROM geometry WHERE state = 'US-MT';
-- Expected: zero rows.
```

**Hash variant** (if preferred for byte-level audit):

```sql
-- Note: ST_Normalize and ST_AsBinary are geometry-only; WKT round-trip required.
SELECT id, md5(ST_AsBinary(ST_Normalize(ST_GeomFromText(ST_AsText(geom), 4326)))) AS geom_hash
FROM geometry WHERE state = 'US-MT'
ORDER BY id;
-- Compare output against the same query run on geometry_snapshot.
```

> **E02-only:** This scoped-DELETE-and-re-ingest pattern works in E02 because nothing yet FK-references `geometry.id`. Once E03 lands and `jurisdiction_binding.geometry_id` references it, the DELETE step requires a coordinated DELETE from `jurisdiction_binding` first (or `ON DELETE CASCADE`). Always scope the DELETE by `state` — never `TRUNCATE geometry` (it would wipe every state's rows).

## 6. Manifest-diff workflow (cross-operator drift signal)

Each ArcGIS fetch via `fetch_features` writes a paired `*-manifest-*.json` (~5 KB) alongside the gitignored `*-features-*.geojson`. Manifests ARE committed to `ingestion/states/montana/fixtures/`.

**Drift check:**

```bash
# Re-fetch Montana geometry layers, then diff committed manifests:
git diff ingestion/states/montana/fixtures/*-manifest-*.json
```

A re-fetch against an unchanged upstream source produces a byte-identical manifest (modulo `fetched_at` for live re-fetches). Any change in `features_count`, `layer_hash`, or `hash_distribution` indicates upstream drift — feature counts, geometry shapes, or attribute values changed in the source layer.

**What to look for:**

- `features_count` change → MT FWP added or removed features from the layer.
- `layer_hash` change → some geometry or attribute value changed upstream.
- `hash_distribution` change with stable `features_count` → geometry or attributes mutated without a count change (e.g., a polygon was revised in place).

**Hash determinism caveat:** A shapely version bump can change WKT canonicalization and therefore all per-feature hashes. The resulting "every manifest changed" delta is a tooling-version event, not real source drift. When this happens, re-baseline the manifests and document the shapely version bump in the commit message. Compare `shapely.__version__` before/after to confirm.

**Backfill script** — `ingestion/states/montana/backfill_manifests.py` regenerates manifests from local features GeoJSON files (layers S02.2–S02.5 were ingested before manifests were introduced). Idempotent — `fetched_at` is parsed from the filename, not regenerated at runtime, so re-running produces byte-identical manifests when the source file is unchanged:

```bash
cd ingestion && .venv/bin/python -m states.montana.backfill_manifests
```

## 7. Overlay architecture (informational)

Overlay computation moved off SQL during S02.6. The cause: Supabase's role-locked 2-min `statement_timeout` aborts the cross-join SQL on real Montana data — per-row detoasting of ~113 KB MultiPolygons across ~12,000 candidate pairs blows past the cap even with the GiST index reachable.

**Implementation:** local `shapely` + `STRtree` in `ingestion/states/montana/build_overlay_fixture.py`. A single bulk query loads all Montana geometry WKT via `ST_AsText(geom)` (geography-native, no `::geometry` cast); shapely parses the WKT and runs the discriminator in-process. End-to-end runtime: ~5 seconds.

**Three-band area-ratio discriminator** per [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md):

```text
overlap_pct = parent.intersection(child).area / child.area

overlap_pct >= COVER_RELABEL_THRESHOLD (0.99)  ->  relationship = "covers"
overlap_pct <  COVER_DROP_THRESHOLD    (0.01)  ->  drop the row, write to audit log
otherwise                                       ->  relationship = "intersects"
```

- `COVER_RELABEL_THRESHOLD = 0.99` — child geometries with ≥99% area inside the parent are accepted as `covers`. This tolerates the digitization-precision gap in Montana source data where portion edges fall fractions of a meter outside their parent HD boundary.
- `COVER_DROP_THRESHOLD = 0.01` — child geometries with ≤1% overlap are dropped (boundary-touching artifacts logged to the audit log).
- Mid-range (0.01 < ratio < 0.99) is kept as `intersects`; a ratio outside both thresholds that is not one of these two cases would raise an error to force human review (the three bands are exhaustive by construction).
- **Asymmetric `child.area` denominator** — the denominator is the child's area, not the parent's. This correctly measures "what fraction of this child sits inside the parent?" rather than "what fraction of the parent does this child occupy?" See [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md) for the full rationale.

**Audit log:** `ingestion/states/montana/fixtures/geometry-overlays-dropped.json` lists every dropped child/parent pair with `overlap_pct` (rounded to 6 decimal places for byte-deterministic JSON). Spot-check this list when calibrating thresholds or investigating a missing HD↔child relationship.

**Permanent orphan no-hunt zones (3):**

- `MT-restricted-bigame-glacier-national-park-geom`
- `MT-restricted-bigame-sun-river-game-preserve-geom`
- `MT-restricted-bigame-yellowstone-national-park-geom`

These are tolerated by design via `EXPECTED_RA_ORPHAN_IDS` in `build_overlay_fixture.py`. They have no parent HD because they are no-hunt zones outside any hunting jurisdiction. Any other `restricted_area` orphan blocks the build with `OverlayFixtureError` — adding a new ID to the allowlist requires a code edit and human review confirming the entry is a no-hunt zone, not an internal HD restriction that lost its parent due to a data regression.

## Cleanup

If a `geometry_snapshot` table was created in section 5, drop it after confirming parity:

```sql
DROP TABLE geometry_snapshot;
```

If the geometry table was wiped and re-ingested, confirm it is back to the expected row count:

```sql
SELECT count(*) FROM geometry WHERE state = 'US-MT';
-- Expected: 349 (V1 Montana total as of S02.6 commit).
```

No other destructive state is introduced by this runbook. The overlay fixture and audit log are read-only artifacts; no cleanup needed for sections 1–4 or 6–7.
