# E05 Colorado Geometry Verification Runbook

Verifies that E05 Colorado geometry rows (S05.0–S05.5) loaded correctly and that spatial queries, topology, multi-part structure, and overlay relationships are sound. See [ADR-004](../adrs/ADR-004-supabase-postgres-postgis.md) (Supabase + PostGIS) and [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md) (overlay thresholds); the CO overlay artifact is at `ingestion/states/colorado/fixtures/geometry-overlays.json` (operator-generated per S05.5 Group B — not committed at-merge).

**All `ST_*` calls in this runbook are `extensions.`-prefixed.** The E02 runbook used bare `ST_*` calls because the Supabase quirk was learned after E02 shipped. This runbook does NOT inherit that style. See `.roughly/known-pitfalls.md` § "Integration — Supabase / PostGIS".

## Prerequisites

- `psql` connected to the Supabase project using the service-role `DATABASE_URL` (provides RLS bypass; anon/authenticated roles will be denied on every query).
- CO geometry rows loaded:
  - `CO-STATEWIDE-geom` (S05.0 — 1 row, kind=`state`)
  - `CO-GMU-{GMUID}-geom` (S05.2 — ~186 rows, kind=`gmu`; count guard band `[167, 205]`)
  - `CO-restricted-{slug}-geom` (S05.4 — 10 rows, kind=`restricted_area`)
  - S05.3 produced **zero** CWD-zone rows (documented gap — CO manages CWD by GMU/hunt-code, not mapped zones). No `cwd_zone` entries exist; this is expected.
  - Expected CO total: ~197 rows in band `[167, ~250]`. Confirm: `SELECT count(*) FROM geometry WHERE state = 'US-CO';`
- `ingestion/states/colorado/fixtures/spatial-test-points.json` generated and committed per **Section 0** below. This fixture is **operator-generated** (Group B output) — it is NOT committed at-merge, unlike the MT fixture.
- A loaded `ingestion` venv (`ingestion/.venv/`).

## 0. Generate `spatial-test-points.json` (Group B — run this first)

This section must be completed before the spot-check steps in Section 1. The fixture cannot be authored at-merge because it requires real representative points derived from the live production geometry.

**Step 1 — derive representative points from live geometry:**

```sql
SELECT id, kind,
       extensions.ST_AsText(
         extensions.ST_PointOnSurface(
           extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)
         )
       ) AS pt
FROM geometry
WHERE state = 'US-CO'
ORDER BY kind, id;
```

**Step 2 — select entries for the fixture.** Choose at minimum:

- **≥3 GMUs** — include the first entry from `ingestion/states/colorado/fixtures/multipart-gmus.json` as the multi-part anchor (the `pt` output for that GMU is the representative interior point).
- **All 10 restricted areas** (or a representative subset if desired; the orphan note in Section 1 applies).
- **The statewide row** (`CO-STATEWIDE-geom` — any CO interior point works).
- **One outside-CO negative-control point** — a real point just over the Wyoming or Kansas line; e.g. `lng=-104.0, lat=41.5` (Laramie County, WY). This is the **only** coordinate in the fixture that is NOT derived from `extensions.ST_PointOnSurface`; document it as such in the `notes` field. It is used to confirm that the `state='US-CO'` filter returns zero rows for a geographically adjacent but out-of-state location.

**Step 3 — write the fixture** at `ingestion/states/colorado/fixtures/spatial-test-points.json` using the exact MT schema:

```json
{
  "version": 1,
  "points": [
    {
      "name": "CO-STATEWIDE-geom representative point",
      "lat": <lat>,
      "lng": <lng>,
      "expected_kind": "state",
      "expected_id_pattern": "CO-STATEWIDE-geom",
      "expected_role_for_e03": null,
      "notes": "Interior point from extensions.ST_PointOnSurface. E05 writes no jurisdiction_binding rows; expected_role_for_e03 is null for all CO points."
    },
    {
      "name": "GMU <GMUID> (multi-part anchor)",
      "lat": <lat>,
      "lng": <lng>,
      "expected_kind": "gmu",
      "expected_id_pattern": "CO-GMU-<GMUID>-geom",
      "expected_role_for_e03": null,
      "notes": "First entry from multipart-gmus.json. Used as multi-part anchor in Section 3."
    },
    {
      "name": "Outside-CO negative control (Laramie County, WY)",
      "lat": 41.5,
      "lng": -104.0,
      "expected_kind": null,
      "expected_id_pattern": null,
      "expected_role_for_e03": null,
      "notes": "Only coordinate not derived from extensions.ST_PointOnSurface. Expected zero rows from state='US-CO' filtered query."
    }
  ]
}
```

**Note:** `expected_role_for_e03` is `null` for **all** CO fixture points. E05 writes no `jurisdiction_binding` rows for Colorado — those are E06 territory. The `role_for_e03` field is retained in the schema for MT fixture compatibility.

**Step 4 — commit the fixture.** Once generated and confirmed, commit `ingestion/states/colorado/fixtures/spatial-test-points.json` and record results in the Group B verification record at `docs/planning/epics/E05-confidence-findings/S05.7.md`.

## 1. Spot-check via `extensions.ST_Covers` (per-kind verification)

Drive this check from `spatial-test-points.json`. For each entry's `(lng, lat)`, run:

```sql
SELECT id, kind FROM geometry
WHERE extensions.ST_Covers(geom, extensions.ST_GeogFromText('SRID=4326;POINT(<lng> <lat>)'))
  AND state = 'US-CO';
-- Note: geom is geography(MultiPolygon, 4326); extensions.ST_Covers(geography, geography)
--   does NOT need a cast workaround — this is a direct geography predicate.
-- AND state = 'US-CO' is mandatory per PRD 002 success criterion #4.
```

**Expected outputs by fixture entry type:**

- **GMU entries:** one row whose `id` matches the entry's `expected_id_pattern`.
- **Restricted-area entries:** one row matching the zone's own ID. CO restricted areas are ALL permanent orphans per `EXPECTED_CO_RA_ORPHAN_IDS` in `build_overlay_fixture.py` — none have a parent GMU in the overlay map.
- **Two-row result:** a point inside a restricted area that geographically overlaps a GMU may return **both** rows (one `restricted_area` row and one `gmu` row). This is a correct result — the zone and its surrounding GMU are distinct geometry rows. Do NOT read the extra row as an error.
- **Statewide entry:** one row, `id = 'CO-STATEWIDE-geom'`, `kind = 'state'`.
- **Outside-CO negative-control point** (e.g. `lng=-104.0, lat=41.5`): **zero rows** — the `state = 'US-CO'` filter excludes any geometries from Wyoming.

**One-shot Python loop** (run from repo root with the ingestion venv):

```bash
cd ingestion && .venv/bin/python - <<'EOF'
import json, os, subprocess, pathlib

pts = json.loads(
    pathlib.Path("states/colorado/fixtures/spatial-test-points.json").read_text()
)["points"]

# Fail loud on an empty / partially-generated fixture — otherwise the loop below
# silently does nothing and the clean exit reads as "all spot-checks passed."
assert len(pts) >= 5, f"fixture has only {len(pts)} points — was it fully generated (Section 0)?"

for p in pts:
    sql = (
        f"SELECT id, kind FROM geometry "
        f"WHERE extensions.ST_Covers(geom, extensions.ST_GeogFromText('SRID=4326;POINT({p[\"lng\"]} {p[\"lat\"]})'))"
        f" AND state = 'US-CO';"
    )
    expected = p["expected_id_pattern"] or "zero rows"
    print(f"\n=== {p['name']} (expected: {expected}) ===")
    subprocess.run(["psql", os.environ["DATABASE_URL"], "-c", sql], check=True)
EOF
```

## 2. Topology validity check

> **Precondition (read before interpreting):** this query returns zero rows for BOTH "all CO geometries are valid" AND "no CO geometry rows exist." Confirm the Prerequisites row count (`SELECT count(*) FROM geometry WHERE state = 'US-CO';` → ~197, non-zero) BEFORE running this section, or a vacuous zero-row result will read as a pass.

```sql
-- All geometries must pass extensions.ST_IsValid; expected zero rows.
-- Note: extensions.ST_IsValid is geometry-only. Direct geom::geometry cast is
--   rejected on Supabase ("cannot cast type geography to geometry") — round-trip
--   through WKT instead. See .roughly/known-pitfalls.md "Integration — Supabase / PostGIS".
SELECT id FROM geometry
WHERE NOT extensions.ST_IsValid(
    extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)
  )
  AND state = 'US-CO';
-- Expected: zero rows. (PRD 002 SC#6.)
```

**Background:** All CO geometries were run through `shapely.make_valid()` before upsert during S05.0, S05.2, and S05.4. This query verifies that validity held through the Supabase round-trip.

## 3. Multi-part GMU verification (named)

Read the first entry from `ingestion/states/colorado/fixtures/multipart-gmus.json` (S05.2 output) and substitute its `gmuid` as `<anchor_id>`:

```sql
-- Expected: parts > 1 for the named multi-part anchor.
-- Note: extensions.ST_NumGeometries is geometry-only; same WKT round-trip workaround applies.
SELECT id,
       extensions.ST_NumGeometries(
         extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)
       ) AS parts
FROM geometry
WHERE id = '<anchor_id>'
  AND state = 'US-CO';
-- Expected: one row, parts > 1.
```

If this query returns zero rows, S05.2 has not completed (or its Group B live write has not run yet). If `parts = 1`, the GMU that appeared multi-part in the CPW FeatureServer has been collapsed — investigate upstream source changes via the manifest-diff workflow.

**Fallback:** If `multipart-gmus.json` is empty (CO has zero multi-part GMUs), document the verification as **N/A** and surface it as a data observation in the Group B record. Do NOT silently skip — an empty fixture is itself a data finding worth recording.

## 4. EXPLAIN ANALYZE plan documentation

```sql
EXPLAIN ANALYZE
SELECT id FROM geometry
WHERE extensions.ST_Covers(geom, extensions.ST_GeogFromText('SRID=4326;POINT(-105.270 40.015)'))
  AND state = 'US-CO';
```

*(Substitute a real CO interior point from your fixture in place of the placeholder above.)*

Paste the plan output inline as a code block when running this section. The plan should show either:

- **`Index Scan using geometry_geom_gix`** — preferred; the GiST index is in use.
- **`Seq Scan`** — acceptable for the V1 CO dataset of ~197 rows. The Postgres planner legitimately chooses a sequential scan when the index overhead exceeds the cost for a small table. This is cost-driven, not a bug.

The bug case is a predicate that forces a function call or cast preventing index use entirely. The current predicate (`extensions.ST_Covers(geom, extensions.ST_GeogFromText(...))`) is index-eligible because both sides are geography — the GiST index on `geometry.geom` is a geography index and supports this predicate directly.

**Important:** overlay computation is NOT a SQL operation — do not attempt to verify GMU↔child relationships by running cross-join SQL against Supabase. The 2-min `statement_timeout` aborts the cross-join on real data. The overlay fixture at `ingestion/states/colorado/fixtures/geometry-overlays.json` is the pre-computed artifact; see Section 7 for architecture details. The point-in-polygon spot-check in Section 1 is the only SQL geospatial path used here.

## 5. CO-bounds `ST_Envelope` check

```sql
-- Bounding-box sanity check: all CO geometries must fall within Colorado's extent.
-- Expected: bbox within [-109.06, -102.04] x [36.99, 41.00] (lng x lat).
-- Note: extensions.ST_Collect / extensions.ST_Envelope are geometry-only. A direct
--   geography-to-geometry cast is rejected on Supabase ("cannot cast type geography
--   to geometry") — round-trip through WKT instead, same workaround as Sections 2/3/6.
--   (The epic spec's literal SQL used the direct cast; corrected here to the WKT
--   round-trip so the query actually runs against the project's Supabase instance.)
SELECT extensions.ST_Envelope(extensions.ST_Collect(
  extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)
))
FROM geometry
WHERE state = 'US-CO';
```

Inspect the returned WKB envelope by casting to text if needed:

```sql
SELECT extensions.ST_AsText(
  extensions.ST_Envelope(extensions.ST_Collect(
    extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)
  ))
)
FROM geometry
WHERE state = 'US-CO';
```

Expected output: a `POLYGON` whose vertices fall within `[-109.06, -102.04] × [36.99, 41.00]`. Any coordinate outside this range indicates a geometry loaded under the wrong state code or a projection error.

**Note:** This is the analytical-layer CO-specific check that the shared library's fetch-layer guard does NOT perform. The fetch-layer guards (in `load_gmus.py`, `load_restricted_areas.py`) validate per-feature shape and count, not the aggregate bounding box of all loaded features combined.

## 6. Reproducibility (topological, not byte-level)

This section verifies that re-ingesting Colorado geometry from source produces topologically equivalent rows.

**Snapshot before wipe:**

```sql
CREATE TABLE geometry_snapshot AS SELECT * FROM geometry WHERE state = 'US-CO';
-- Or save to CSV: \COPY (SELECT * FROM geometry WHERE state = 'US-CO')
--                TO '/tmp/co_geometry_snapshot.csv' CSV HEADER;
```

**Wipe (FK-cascade order — CRITICAL):**

```sql
-- Step 1: delete jurisdiction_binding rows first (FK: jurisdiction_binding.geometry_id
-- REFERENCES geometry(id)). Note: jurisdiction_binding has NO `state` column — scope by
-- the geometry it references via geometry_id, which is exactly the FK dependency that
-- blocks the geometry DELETE below.
DELETE FROM jurisdiction_binding
WHERE geometry_id IN (SELECT id FROM geometry WHERE state = 'US-CO');
-- In E05, no CO jurisdiction_binding rows exist yet (E06 territory), so this DELETE
-- is a no-op today. The sequence MUST be documented here for when E06 lands and
-- CO binding rows exist in production.

-- Step 2: then delete geometry rows.
DELETE FROM geometry WHERE state = 'US-CO';

-- DO NOT use TRUNCATE: it wipes EVERY state (MT rows included) and breaks
-- reproducibility for any state already loaded. Always use scoped DELETEs.
```

**Re-ingest** (run from repo root):

```bash
ingestion/.venv/bin/python ingestion/states/colorado/load_state_boundary.py
ingestion/.venv/bin/python ingestion/states/colorado/load_gmus.py
ingestion/.venv/bin/python ingestion/states/colorado/load_restricted_areas.py
```

S05.3 produced zero CWD-zone rows — there is no `load_cwd_zones.py` for Colorado. This is expected per the documented gap.

**Compare — topological equality:**

```sql
-- Topological inequality check — expected zero rows.
-- Note: extensions.ST_Equals is geometry-only. Round-trip via WKT on both sides
--   (same Supabase cast workaround as extensions.ST_IsValid above).
SELECT a.id FROM geometry_snapshot a
  JOIN geometry b USING (id)
  WHERE NOT extensions.ST_Equals(
    extensions.ST_GeomFromText(extensions.ST_AsText(a.geom), 4326),
    extensions.ST_GeomFromText(extensions.ST_AsText(b.geom), 4326)
  )
  AND b.state = 'US-CO';
-- Expected: zero rows.
```

**Compare — row count and id-set parity:**

```sql
SELECT
  (SELECT count(*) FROM geometry_snapshot)                   AS before_count,
  (SELECT count(*) FROM geometry WHERE state = 'US-CO')      AS after_count;
-- Expected: before_count = after_count (~197; exact count confirmed at S05.0/S05.2/S05.4 closes).

-- ID-set parity is a TWO-DIRECTION check — run BOTH queries below. Stopping after
-- the forward direction (zero rows) misses IDs the re-ingest *added* but the snapshot
-- lacked. Neither query alone is sufficient. (PRD 002 SC#7.)

-- ID-set parity, forward (rows in snapshot missing after re-ingest):
SELECT id FROM geometry_snapshot
EXCEPT
SELECT id FROM geometry WHERE state = 'US-CO';
-- Expected: zero rows.

-- ID-set parity, reverse direction (unexpected extras introduced by re-ingest):
SELECT id FROM geometry WHERE state = 'US-CO'
EXCEPT
SELECT id FROM geometry_snapshot;
-- Expected: zero rows. Both directions must be checked — passing only the
-- forward direction would miss cases where re-ingest added an ID the snapshot
-- did not have (e.g. a renamed feature deleted and re-added, or a partial earlier
-- run that left state inconsistent). (PRD 002 SC#7.)
```

**Idempotency assertion** — re-run a second time and confirm zero net new rows:

```sql
-- After a second run of the three loaders above, row count must be unchanged.
SELECT count(*) FROM geometry WHERE state = 'US-CO';
-- Expected: same count as after first re-ingest run. (PRD 002 SC#7.)
```

## 7. Overlay architecture (informational)

Overlay computation is NOT a SQL operation (same as MT's S02.6 off-SQL migration). Supabase's role-locked 2-min `statement_timeout` aborts cross-join SQL on real polygon data — detoasting MultiPolygons across thousands of candidate pairs blows past the cap even with the GiST index reachable.

**Implementation:** local `shapely` + `STRtree` in `ingestion/states/colorado/build_overlay_fixture.py`. A single bulk query loads all CO geometry WKT via `extensions.ST_AsText(geom)` (geography-native, no `::geometry` cast); shapely parses the WKT and runs the discriminator in-process.

**Three-band area-ratio discriminator** per [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md):

```text
overlap_pct = parent.intersection(child).area / child.area

overlap_pct >= COVER_RELABEL_THRESHOLD (0.99)  ->  relationship = "covers"
overlap_pct <  COVER_DROP_THRESHOLD    (0.01)  ->  drop the row, write to audit log
otherwise                                       ->  relationship = "intersects"
```

**CO-specific notes vs. Montana:**

- **Parent kind:** `gmu` (CO) vs. `hunting_district` (MT).
- **No portions:** CO has no `kind='portion'` geometry. The portions fan-out step in the MT overlay builder is absent.
- **CWD zones:** vacuously empty (S05.3 documented gap — zero rows exist; the coverage invariant is satisfied trivially).
- **Restricted areas:** all 10 CO restricted areas are permanent orphans, enumerated in `EXPECTED_CO_RA_ORPHAN_IDS` in `build_overlay_fixture.py`:
  - 4 National Parks: rocky-mountain-national-park, mesa-verde-national-park, great-sand-dunes-national-park, black-canyon-of-the-gunnison-national-park
  - 5 National Monuments: dinosaur-national-monument, colorado-national-monument, florissant-fossil-beds-national-monument, hovenweep-national-monument, yucca-house-national-monument
  - 1 DOD: united-states-air-force-academy

Any `restricted_area` ID not in `EXPECTED_CO_RA_ORPHAN_IDS` and without a parent GMU blocks the build with `OverlayFixtureError` — adding a new ID to the allowlist requires a code edit and human review.

**CO overlay fixtures are operator-generated** (S05.5 Group B — cannot be built until S05.2 GMUs and S05.4 restricted areas are live in production):

- `ingestion/states/colorado/fixtures/geometry-overlays.json` — primary overlay artifact consumed by E06's binding loader.
- `ingestion/states/colorado/fixtures/geometry-overlays-dropped.json` — audit log of dropped pairs.

To generate after live writes complete:

```bash
cd ingestion && .venv/bin/python states/colorado/build_overlay_fixture.py
```

**Audit log:** `geometry-overlays-dropped.json` lists every dropped child/parent pair with `overlap_pct` (rounded to 6 decimal places for byte-deterministic JSON). Spot-check this list when calibrating thresholds or investigating a missing GMU↔child relationship.

### Cross-state filter regression

S05.6 shipped `test_co_binding_loader_sql_filters_by_state_co_pollution_guard` in `ingestion/tests/test_co_binding_reference.py`. This test verifies that CO binding SQL filters by `state = 'US-CO'` and cannot silently read MT geometry rows. Run it as the cross-state UAT step:

```bash
cd ingestion && .venv/bin/pytest tests/test_co_binding_reference.py -k co_pollution_guard -v
```

Expected: `1 passed`. This test passes at-merge as part of the 1340-test baseline; re-running it here confirms the cross-state isolation property holds in the operator's environment.

## Cleanup

If a `geometry_snapshot` table was created in Section 6, drop it after confirming parity:

```sql
DROP TABLE geometry_snapshot;
```

If the geometry table was wiped and re-ingested, confirm CO rows are restored to the expected count:

```sql
SELECT count(*) FROM geometry WHERE state = 'US-CO';
-- Expected: ~197 (1 statewide + ~186 GMUs + 10 restricted areas; exact count per
-- S05.0/S05.2/S05.4 Group B verification records).
```

No other destructive state is introduced by this runbook. The overlay fixture and audit log are read-only artifacts; no cleanup needed for sections 1–5 or 7.
