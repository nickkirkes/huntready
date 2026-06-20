# M2 Operator Pass — Consolidated Group B Batched Session

**Purpose:** One coherent operator session that closes every accumulated Group B AC across **E05 (Colorado geometry ingestion)** and the DB-write half of **E06 (Colorado regulation text ingestion)**. Mirrors the `M1-uat.md` runbook pattern: numbered steps, inline verification SQL, single consolidated capture form at the end. PM later splits the captured outputs into per-story `docs/planning/epics/E06-confidence-findings/SXX.X.md` § "Group B verification record" entries via doc-only commits.

**Audience:** Operator (human + the M2-target environment's service-role DSN). Not for implementation agents — this session does not write code. It runs already-merged loaders against a live Supabase Postgres + PostGIS database and records the outputs.

**Scope:** All outstanding Group B work as of 2026-06-19 — 8 loader/fixture steps + the existing E05 7-step spatial verification + 2 E06 verification gates.

**Expected duration:** 60–90 minutes operator wall-clock, depending on PDF fetch latency. Most loaders complete in seconds; `load_regulation_records.py` may take ~15 s; `build_overlay_fixture.py` (local shapely + STRtree) ~5–10 s.

## Pass mode: M2-build vs M2-release

The runbook supports **two distinct passes**, both following identical structure / SQL / expected counts. Only the `DATABASE_URL` target changes between them.

- **M2-build pass** (this one). Run against the **M2-build environment** — whichever live Supabase project M2 development is targeting (typically a dev project). Validates that the loaders + migration + fixture generators all work against a real schema + real PostGIS, and closes the accumulated dev Group B ACs. Runs whenever the accumulated Group B backlog is worth validating; sequenced before the next implementation story (S06.7 in this case) so that next-story implementation can plan against actual live state.
- **M2-release pass** (eventual; run once at M2 close). Run against the **M2-release environment** (production) before the `m2` tag is pushed. Repeats the same runbook against the production project; the captured outputs feed the M2 → M3 handoff document at milestone close. Same SQL, same expected counts; the only delta is which `DATABASE_URL` is in scope.

The MT-untouched assertion in Step 10 (PRD 002 SC #9) holds in both passes — the baseline is "MT row counts unchanged from M1 close **in whichever environment this pass is targeting**." For an M2-build pass that's the dev env's M1-close state; for the M2-release pass that's production's M1-close state.

If this pass is the M2-release pass, the operator records that at the top of the capture form (an "Environment" field exists for this — see "Operator capture form" at the bottom). Otherwise, it's an M2-build pass.

The PM then splits captured outputs into per-story `confidence-findings/SXX.X.md` § "Group B verification record" entries with the env tag preserved, so a future M2-release pass writes its own entry alongside the M2-build entry rather than overwriting it.

---

## Prerequisites

### Environment

- Repo cloned and on `main` at commit `a1fea67` or later (`git log -1 --format=%H` to verify; the runbook itself should be in the working tree).
- `git status` clean (the loaders will produce committable fixture files; if status is not clean before the pass starts, capture what's outstanding before running).
- Python virtualenv at `ingestion/.venv` activated; dependencies installed via `make ingest-deps` or equivalent.
- `DATABASE_URL` env var set to the **M2-target environment's service-role DSN** (not the publishable key — service-role bypasses RLS, which is required for these UPSERTs). For an M2-build pass this is the dev project; for an M2-release pass this is the production project. The operator confirms which env before starting.
- `SUPABASE_URL` + `SUPABASE_SECRET_KEY` env vars set (for `supabase` CLI calls).
- `HUNTREADY_INGESTION_CONTACT` env var set per `CLAUDE.md` § "Environment variables" (gives CPW / USGS / Census a way to reach the operator if a fetch behaves unexpectedly).
- `supabase` CLI installed and authenticated.
- Test baseline before starting: `cd ingestion && .venv/bin/pytest tests/ -q` reports `1774 passed, 4 skipped` (the post-S06.6 floor). If this does not pass cleanly, **stop and surface to PM** — something has drifted.

### Safety guards

- **No `git push` from this session.** Every change in this pass is a fixture commit or a captured runbook output; the operator commits locally and the PM rolls them into doc-only commits afterward.
- **The 3 MT no-hunt-zone bindings carried by `MT-STATEWIDE-bear` from M1 / S03.6.1 are already in the target env (assuming M1 was built against the same env as this pass targets).** Expect to see them. Do not modify them.
- **PRD 002 success criterion #9 (MT untouched).** At end-of-pass, the MT row counts in `geometry` + `jurisdiction_binding` + `regulation_record` etc. must be byte-identical to the M1 close baseline. A consolidated MT-untouched assertion lives in Step 10 below.
- **Idempotency.** All write loaders here are UPSERT-by-id or composite-PK; a re-run produces the same DB state. If a step fails partway, you can re-run it cleanly. Exception: `build_overlay_fixture.py` and `spatial-test-points.json` are one-shot fixture generators — re-running just regenerates the file; commit the new one.
- **If a step's count or shape doesn't match the expected verification value documented inline below, stop and surface to PM.** Do not proceed. Group B is checking that the live target env agrees with dry-run; if it doesn't, something is genuinely off and the next implementation story should not be dispatched until reconciled.
- **The bear-binding `MT-STATEWIDE-bear-...-no_hunt_zone-...` ids reflect the S05.3.5 reclassification.** If you see `other_overlay` in their `role`, S05.3.5's migration did not actually run; that's a Step 1 failure mode.

### Pre-pass DB state

Before starting Step 1, run this quick reconciliation against the target env:

```sql
-- Expected pre-pass M1-close baseline:
--   350 MT geometry rows: 235 HDs (S02.2) + 55 portions (S02.3) + 57 restricted areas (S02.4) + 2 CWD zones (S02.5) + 1 MT-STATEWIDE-geom (S03.0)
--   0 CO geometry rows (nothing in the target env yet from M2)
--   437 MT regulation_record rows (S03.6 wrote 436 + S03.6.1 statewide bear anchor = 437)
--   0 CO regulation_record rows (nothing in the target env yet from M2)
--   ~788 jurisdiction_binding rows total (S03.10 T16 empirical for MT) — this INCLUDES the 1 statewide-bear binding from S03.6.1
--     AND the 3 MT federal no-hunt-zone bindings (Glacier NP, Sun River, Yellowstone NP) which at this point still carry role='other_overlay'
--     (S05.3.5's migration in Step 1 reclassifies those 3 → 'no_hunt_zone')
--   0 CO bindings (S06.10 still ahead in epic order)

SELECT 'geometry MT' AS table_, COUNT(*) AS rows FROM geometry WHERE state = 'US-MT'
UNION ALL SELECT 'geometry CO', COUNT(*) FROM geometry WHERE state = 'US-CO'
UNION ALL SELECT 'reg_record MT', COUNT(*) FROM regulation_record WHERE state = 'US-MT'
UNION ALL SELECT 'reg_record CO', COUNT(*) FROM regulation_record WHERE state = 'US-CO'
UNION ALL SELECT 'binding MT', COUNT(*) FROM jurisdiction_binding WHERE regulation_record_state = 'US-MT'
UNION ALL SELECT 'binding CO', COUNT(*) FROM jurisdiction_binding WHERE regulation_record_state = 'US-CO'
UNION ALL SELECT 'binding (all)', COUNT(*) FROM jurisdiction_binding;

-- Pre-pass S05.3.5-related sanity: the 3 MT federal no-hunt-zone bindings still carry role='other_overlay'
-- (Step 1 reclassifies them; Step 1 also confirms post-migration state.)
SELECT id, role
FROM jurisdiction_binding
WHERE geometry_id IN (
  'MT-restricted-bigame-glacier-national-park-geom',
  'MT-restricted-bigame-sun-river-game-preserve-geom',
  'MT-restricted-bigame-yellowstone-national-park-geom'
)
ORDER BY id;
-- Pre-pass expected: 3 rows; every role = 'other_overlay' (Step 1's S05.3.5 migration flips them to 'no_hunt_zone')
```

If `geometry CO` or `regulation_record CO` or `binding CO` is **non-zero before this pass**, stop and surface to PM — it means an earlier partial run wasn't cleaned up and the runbook's expected counts will be off.

If `binding (all)` is dramatically different from ~788 (more than ±10%), or `reg_record MT` differs from 437, the M1-close baseline has drifted — stop and surface to PM.

Capture the output verbatim under "Pre-pass DB state" in the form below.

---

## Overview & sequencing

The 10 steps below are **strictly ordered by FK dependency**. Do not reorder.

| Step | Action | Closes Group B for | Hard dependency |
|---|---|---|---|
| 0 | Pre-flight + baseline checks | — | — |
| 1 | Apply S05.3.5 migration (`supabase db push`) | S05.3.5 | none |
| 2 | Load `CO-STATEWIDE-geom` (`load_state_boundary.py`) | S05.0 #7 / #8 | Step 1 (CHECK constraint shape) |
| 3 | Load CO GMUs (`load_gmus.py`) | S05.2 | Step 1 |
| 4 | Load CO restricted areas (`load_restricted_areas.py`) | S05.4 | Step 1 |
| 5 | Build overlay fixture (`build_overlay_fixture.py`) | S05.5 | Steps 3 + 4 (reads geometry table) |
| 6 | Generate `spatial-test-points.json` (S05.7 fixture) | S05.7 | Step 3 |
| 7 | E05 spatial verification (7 sections from `E05-colorado-geometry-verification.md`) | S05.7 spatial UAT | Steps 2 + 3 + 4 + 5 + 6 |
| 8 | Populate restricted-area `verbatim_rule` (`load_restricted_area_verbatim.py`) | S06.5 #482 / #483 / #486 (modulo PM-run spot-check) | Step 4 |
| 9 | Load `regulation_record` rows (`load_regulation_records.py`) | S06.6 | Steps 2 + 3 |
| 10 | End-to-end verification + MT-untouched assertion | All of the above | All of the above |

---

## Step 1 — Apply S05.3.5 migration

S05.3.5 extended the `jurisdiction_binding.role` CHECK constraint enum 7 → 8 values (adds `'no_hunt_zone'`) and reclassified the 3 MT federal no-hunt-zone bindings from `'other_overlay'` → `'no_hunt_zone'`. The migration is single-atomic; either the whole thing applies or none of it.

### Command

```bash
supabase db push --db-url "$DATABASE_URL"
```

Capture the full `supabase db push` output verbatim — including the migration timestamp(s) applied. Expected: one new migration `20260603000000_jurisdiction_binding_no_hunt_zone_role.sql` applied; no other migrations.

### Verification SQL

```sql
-- (a) CHECK constraint shape: enum is now 8 values incl. 'no_hunt_zone'
SELECT pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_class t ON c.conrelid = t.oid
WHERE c.conname = 'jurisdiction_binding_role_check'
  AND t.relname = 'jurisdiction_binding';

-- Expected: a CHECK clause listing exactly 8 values (alphabetical or as ADR-021 sets):
--   primary_unit, portion, restricted_area, cwd_management_zone,
--   bear_management_unit, block_management_area, other_overlay, no_hunt_zone

-- (b) SELECT DISTINCT role on jurisdiction_binding: subset of the 8 values
SELECT DISTINCT role FROM jurisdiction_binding ORDER BY role;

-- (c) The 3 MT rows reclassified from 'other_overlay' → 'no_hunt_zone'
SELECT id, role
FROM jurisdiction_binding
WHERE geometry_id IN (
  'MT-restricted-bigame-glacier-national-park-geom',
  'MT-restricted-bigame-sun-river-game-preserve-geom',
  'MT-restricted-bigame-yellowstone-national-park-geom'
)
ORDER BY id;

-- Expected: 3 rows; every role = 'no_hunt_zone' (no 'other_overlay' remaining)

-- (d) Row count unchanged pre/post migration (DDL + 3-row UPDATE; no INSERT/DELETE)
SELECT COUNT(*) FROM jurisdiction_binding;

-- Expected: same count as the pre-pass DB state captured above.
```

Capture all four query outputs verbatim. **Closes S05.3.5 Group B ACs.**

---

## Step 2 — Load CO statewide geometry

Writes `CO-STATEWIDE-geom` (`kind='state'`, 1 row) from the pinned Census TIGER 2024 state shapefile. Source SHA-256 pinned per ADR-001 fail-loud.

### Command

```bash
ingestion/.venv/bin/python ingestion/states/colorado/load_state_boundary.py
```

The loader fetches the pinned TIGER 2024 zip, validates SHA-256, extracts Colorado's row, applies `shapely.make_valid()`, normalizes to `geography(MultiPolygon, 4326)`, and UPSERTs. Look for `INFO: wrote 1 row` (or similar) and `COMMIT`. Capture stdout verbatim.

### Verification SQL

```sql
-- (a) Exactly 1 statewide row
SELECT COUNT(*) AS co_statewide_rows
FROM geometry
WHERE state = 'US-CO' AND kind = 'state';
-- Expected: 1

-- (b) Area within 1% of 269,837 km² (Colorado's published surface area)
SELECT
  id,
  ROUND((extensions.ST_Area(geom::geography) / 1e6)::numeric, 0) AS area_km2,
  extensions.ST_IsValid(geom::geometry) AS valid
FROM geometry
WHERE id = 'CO-STATEWIDE-geom';
-- Expected: id='CO-STATEWIDE-geom'; area_km2 ∈ [267,138; 272,535] (±1% of 269,837); valid=true

-- (c) Source citation: TIGER pinned per ADR-014
SELECT id, source->>'id' AS source_id, source->>'document_type' AS doc_type, source->>'publication_date' AS pub_date
FROM geometry
WHERE id = 'CO-STATEWIDE-geom';
-- Expected: source_id='co-census-tiger-state-2024'; doc_type='gis_layer'; pub_date='2026-01-01'
```

Capture all three. **Closes S05.0 AC #7 (verification queries) + AC #8 (area_km2 within 1%).**

---

## Step 3 — Load CO GMUs (~186 polygons)

Writes ~186 CO Game Management Unit polygons from CPW FeatureServer layer 6. Includes the `multipart-gmus.json` analytics fixture (planar-WKT degrees — not authoritative km² per S05.2 closure).

### Command

```bash
ingestion/.venv/bin/python ingestion/states/colorado/load_gmus.py
```

The loader pages through `services5.arcgis.com/.../CPWAdminData/FeatureServer/6` with `outSR=4326`, runs `returnCountOnly` cross-check, applies `shapely.make_valid()`, and writes via the new `db.update_geometry_verbatim`-adjacent UPSERT helper (note: this is `upsert_geometry`, not the new helper from S06.5). Look for `INFO: count band guard fired` and `TOTAL: N geometries` near the end. Capture stdout verbatim.

### Verification SQL

```sql
-- (a) GMU row count (count-band guard already ran client-side at [167, 205]; live should be 186 ±10%)
SELECT COUNT(*) AS co_gmu_rows
FROM geometry
WHERE state = 'US-CO' AND kind = 'gmu';
-- Expected: in [167, 205] (CPW's actual ~186)

-- (b) Cross-check against the FeatureServer source count (sanity check)
-- Run this curl in a separate terminal; record the JSON 'count' value:
--   curl -s "https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6/query?where=1=1&returnCountOnly=true&f=json" | jq .count
-- Expected: matches the row count from (a)

-- (c) ST_IsValid round-trip on every row
SELECT COUNT(*) AS valid_count, COUNT(*) FILTER (WHERE NOT extensions.ST_IsValid(geom::geometry)) AS invalid_count
FROM geometry
WHERE state = 'US-CO' AND kind = 'gmu';
-- Expected: valid_count = total from (a); invalid_count = 0

-- (d) Distinct id pattern + a few representative spot-checks
SELECT id, source->>'id' AS source_id
FROM geometry
WHERE state = 'US-CO' AND kind = 'gmu'
  AND id IN ('CO-GMU-1-geom', 'CO-GMU-201-geom', 'CO-GMU-44-geom')
ORDER BY id;
-- Expected: 3 rows; ids match pattern CO-GMU-{int}-geom; source_id='co-cpw-arcgis-CPWAdminData-6-2026'
```

Confirm the per-PDF (actually per-FeatureServer) manifest is now in `ingestion/states/colorado/fixtures/` as a new file (e.g., `CPWAdminData-6-manifest-<timestamp>.json`). Capture `git status -s ingestion/states/colorado/fixtures/` output. The manifest should be committable; the metadata + multipart fixtures land alongside.

**Closes S05.2 Group B ACs.**

---

## Step 4 — Load CO restricted areas (10 federal no-hunt + AFA zones)

Writes 10 federal restricted-area polygons from USGS PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer. The fetched set is 11 (10 NPS incl. Curecanti NRA + 1 DOD AFA); Curecanti drops post-fetch per 36 CFR §2.2; final write is 10.

### Command

```bash
ingestion/.venv/bin/python ingestion/states/colorado/load_restricted_areas.py
```

Look for `INFO: V1_EXPECTED_IDS set-equality guard PASS` (the S06.4 Stage-6 review-fix). The Curecanti drop happens before the fixture/manifest writes, so the manifest's `features_count` reads 10. Capture stdout verbatim.

### Verification SQL

```sql
-- (a) Exactly 10 restricted-area rows
SELECT COUNT(*) AS co_restricted_rows
FROM geometry
WHERE state = 'US-CO' AND kind = 'restricted_area';
-- Expected: 10

-- (b) All 10 expected ids present; Curecanti NRA NOT present
SELECT id
FROM geometry
WHERE state = 'US-CO' AND kind = 'restricted_area'
ORDER BY id;
-- Expected 10 ids (alphabetical):
--   CO-restricted-black-canyon-of-the-gunnison-national-park-geom
--   CO-restricted-colorado-national-monument-geom
--   CO-restricted-dinosaur-national-monument-geom
--   CO-restricted-florissant-fossil-beds-national-monument-geom
--   CO-restricted-great-sand-dunes-national-park-geom
--   CO-restricted-hovenweep-national-monument-geom
--   CO-restricted-mesa-verde-national-park-geom
--   CO-restricted-rocky-mountain-national-park-geom
--   CO-restricted-united-states-air-force-academy-geom
--   CO-restricted-yucca-house-national-monument-geom
-- NO curecanti-* row.

-- (c) returnCountOnly cross-check (run in separate terminal; should be 11 — the pre-Curecanti-drop count)
--   curl -s "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0/query?where=...V1_WHERE_CLAUSE...&returnCountOnly=true&f=json"
-- (The implementer can pull the exact WHERE clause from load_restricted_areas.py; expected raw count = 11; written = 10)

-- (d) ST_IsValid + GIS_Acres ±10% sanity
SELECT id, ROUND((extensions.ST_Area(geom::geography) * 0.000247105)::numeric, 0) AS computed_acres, extensions.ST_IsValid(geom::geometry) AS valid
FROM geometry
WHERE state = 'US-CO' AND kind = 'restricted_area'
ORDER BY id;
-- Expected: 10 rows; valid=true on all 10. computed_acres values per the published PAD-US GIS_Acres ±10%
-- (operator sanity-checks against PAD-US published acreage; document any >10% delta).

-- (e) verbatim_rule still NULL at this step (Step 8 populates it)
SELECT COUNT(*) AS null_verbatim
FROM geometry
WHERE state = 'US-CO' AND kind = 'restricted_area' AND verbatim_rule IS NULL;
-- Expected: 10 (all 10 still pending Step 8 UPDATE)
```

Confirm the live-run metadata + manifest fixtures landed in `ingestion/states/colorado/fixtures/`. `git status -s` captures the new files. **Closes S05.4 Group B ACs.**

---

## Step 5 — Build overlay fixture

Generates `geometry-overlays.json` + paired `geometry-overlays-dropped.json` audit log via local shapely + STRtree (Supabase's 2-min `statement_timeout` aborts the cross-join SQL; local computation is the canonical path per ADR-016).

### Command

```bash
ingestion/.venv/bin/python ingestion/states/colorado/build_overlay_fixture.py
```

The builder reads `SELECT id, kind, ST_AsText(geom) FROM geometry WHERE state='US-CO'`, applies the ADR-016 three-band discriminator (0.99 relabel / 0.01 drop / `_OVERLAP_PCT_PRECISION=6`), writes both JSON files via two-phase tmp+rename. Look for the run-summary line with section count + dropped-pair count. Capture stdout.

### Verification

```bash
# (a) Both fixture files exist and are byte-identical across two runs
ls -la ingestion/states/colorado/fixtures/geometry-overlays.json
ls -la ingestion/states/colorado/fixtures/geometry-overlays-dropped.json

# (b) Reproducibility: re-run the builder; compare SHAs
shasum -a 256 ingestion/states/colorado/fixtures/geometry-overlays.json
ingestion/.venv/bin/python ingestion/states/colorado/build_overlay_fixture.py
shasum -a 256 ingestion/states/colorado/fixtures/geometry-overlays.json
# Expected: two consecutive SHAs match (deterministic two-phase tmp+rename write per ADR-016 + sort_keys)

# (c) Quick shape verification
python3 -c "
import json
with open('ingestion/states/colorado/fixtures/geometry-overlays.json') as f:
    d = json.load(f)
print(f'overlay rows: {len(d)}')
# Expected: gmu self-rows (~186) + cwd_zone children (0 — S05.3 documented gap) + restricted_area children/orphans
"

# (d) Threshold recalibration check per ADR-016 §4
python3 -c "
import json
with open('ingestion/states/colorado/fixtures/geometry-overlays-dropped.json') as f:
    dropped = json.load(f)
# Inspect borderline drops (overlap in [0.005, 0.02]) and borderline relabels ([0.98, 0.995]) from any 'covers'-tagged rows
# If counts differ from MT proportions by >10%, recalibrate per ADR-016 §4 and document in S05.5 closure note.
# If proportions look normal, MT thresholds carry forward unchanged.
"
```

Confirm the `EXPECTED_CO_RA_ORPHAN_IDS` allowlist (10 ids) shows all 10 restricted areas as expected orphans in the fixture (NPs/NMs/AFA adjacent to, not contained by, GMUs). **Closes S05.5 Group B ACs** (modulo PM-run UAT visual spot-check, which the PM will perform on the captured fixtures).

---

## Step 6 — Generate `spatial-test-points.json`

The S05.7 fixture generator. Uses `extensions.ST_PointOnSurface` to produce representative points per `kind` value present in CO geometry. Per AC #2 of S05.7: no invented points; real `representative_point()` only.

### Command

The exact generator script lives in `docs/planning/epics/completed/E05-confidence-findings/S05.7.md` § "Operator runbook"; copy it to a temp file or run inline. The output goes to `ingestion/states/colorado/fixtures/spatial-test-points.json`.

```bash
# (Generate via the snippet from S05.7.md — the exact command is operator-extracted from that runbook.)
# Expected output: spatial-test-points.json with:
#   ≥3 GMU named test points (incl. ≥1 multi-part anchor from S05.2's multipart-gmus.json)
#   0 CWD-zone test points (CO publishes no CWD zones — S05.3 gap; this kind is omitted)
#   ≥1 restricted-area test point
#   ≥1 statewide point
#   ≥1 outside-CO negative-control point
```

Verify the file exists; confirm each `kind` present in CO geometry has the expected count of test points. Capture file contents (or its SHA + line count). **Closes S05.7 fixture-generation AC.**

---

## Step 7 — E05 spatial verification (7 sections)

Run the 7 verification sections from `docs/runbooks/E05-colorado-geometry-verification.md` against the target env with the now-populated CO geometry. Per the E05 runbook's convention, all `ST_*` calls are `extensions.`-prefixed; every query carries `AND state = 'US-CO'`; the WKT round-trip cast workaround applies to all geometry-only functions per the S05.7 post-PR-review fixes.

Run **Section 1 → Section 7** in order. Capture each section's output verbatim. Each section's expected shape is documented inline in the E05 runbook; the operator confirms the actual outputs match.

**Sections** (per `E05-colorado-geometry-verification.md`):

1. Cross-state state filter regression (`SELECT DISTINCT state FROM geometry WHERE state = 'US-CO'`)
2. `ST_Covers` against the named test points from Step 6
3. `ST_IsValid` round-trip on every CO geometry
4. Multi-part anchor `ST_NumGeometries` against the named multi-part GMU
5. `EXPLAIN ANALYZE` showing the spatial index is used
6. `ST_Envelope` bounds check against Colorado's known coord box (the CO-specific Section 5)
7. Wipe + re-ingest dry-run (test that the FK-cascade wipe SQL is correct; do NOT actually wipe the target env — this section is read-only verification of the wipe SQL's shape)

If any section fails the documented expected shape, stop and surface to PM. **Closes S05.7 spatial UAT AC** + PRD 002 success criterion #4.

---

## Step 8 — Populate restricted-area `verbatim_rule`

Reads CPW Big Game brochure page 78 at runtime, extracts the NPS closure prose + the AFA access-rules prose, and runs targeted `UPDATE geometry SET verbatim_rule = %s WHERE id = %s` against the 10 restricted-area rows from Step 4.

### Command

```bash
ingestion/.venv/bin/python ingestion/states/colorado/load_restricted_area_verbatim.py
```

The loader uses `lib/pdf.open_pdf` + `lib/pdf.extract_text(page, bbox=…)` column crops + regex anchors; fail-loud on missing anchor / empty crop / wrong PDF. Look for `INFO: 9 NPS rows updated to shared closure sentence; 1 AFA row updated to access-rules prose` (or similar) and `COMMIT`. Capture stdout.

### Verification SQL

```sql
-- (a) All 10 rows have verbatim_rule populated (S06.5 AC #482)
SELECT COUNT(*) AS populated
FROM geometry
WHERE state = 'US-CO' AND kind = 'restricted_area' AND verbatim_rule IS NOT NULL;
-- Expected: 10

-- (b) source field still PAD-US gis_layer (D5 = (b) split-provenance honored; S06.5 AC #483)
SELECT COUNT(*) AS pad_us_count
FROM geometry
WHERE state = 'US-CO' AND kind = 'restricted_area'
  AND source->>'document_type' = 'gis_layer'
  AND source->>'id' = 'co-usgs-padus-arcgis-Federal_Fee_Managers_Authoritative_PADUS-0-2026';  -- pragma: allowlist secret
-- Expected: 10 (NOT updated to CPW citation; PAD-US stays the geometry provenance)

-- (c) Phrasing case (1) + 9+1 split — 9 NPS rows share ONE unique verbatim_rule; AFA differs
SELECT COUNT(DISTINCT verbatim_rule) AS unique_strings
FROM geometry
WHERE state = 'US-CO' AND kind = 'restricted_area'
  AND id != 'CO-restricted-united-states-air-force-academy-geom';
-- Expected: 1 (the 9 NPS rows collapse to one unique string)

SELECT
  CASE
    WHEN id = 'CO-restricted-united-states-air-force-academy-geom' THEN 'AFA'
    ELSE 'NPS'
  END AS category,
  COUNT(DISTINCT verbatim_rule) AS unique_strings
FROM geometry
WHERE state = 'US-CO' AND kind = 'restricted_area'
GROUP BY category;
-- Expected:
--   NPS | 1
--   AFA | 1

-- (d) Spot-check the NPS shared sentence — should be:
--     "National parks and monuments managed by the National Park Service are closed to hunting. Check park websites for more information."
SELECT verbatim_rule
FROM geometry
WHERE id = 'CO-restricted-rocky-mountain-national-park-geom';

-- (e) Spot-check the AFA distinct text — should describe how to hunt there (regulated-access),
-- NOT a closure (per Known Issue #12).
SELECT verbatim_rule
FROM geometry
WHERE id = 'CO-restricted-united-states-air-force-academy-geom';
```

Capture all five query outputs. PM-run faithfulness spot-check on ≥3 of the 10 zones (Rocky Mountain NP, Mesa Verde NP, AFA) cross-checked against the brochure happens after this session via the PM separately. **Closes S06.5 AC #482 + AC #483; AC #486 deferred to PM spot-check.**

---

## Step 9 — Load `regulation_record` rows

Writes 398 `regulation_record` rows from `big-game-2026.json` (S06.3.1 SHA `9312e259…bb2f`) + `black-bear-2026.json` (S06.4 SHA `7b35c202…d5f6`) in one atomic transaction. Collapse design: `(gmu_code, species_group)` reduces 906 sections → 398 records.

### Command

```bash
ingestion/.venv/bin/python ingestion/states/colorado/load_regulation_records.py
```

Look for the OQ7 ±30% count-band guard pre-`db.connect()` firing (PASS), then per-builder phase logs, then `TOTAL: 398 records written` and `COMMIT`. Capture stdout — including any `WARNING` lines (the GMU 020 elk archery blank-GMU section skip is expected and produces a single `WARNING`; if any other warnings appear, capture them).

### Verification SQL

```sql
-- (a) Live row count = 398 (S06.6 Group B AC #1)
SELECT COUNT(*) AS co_reg_records
FROM regulation_record
WHERE state = 'US-CO';
-- Expected: 398

-- (b) Per-species counts (S06.6 Group B AC #2)
SELECT species_group, COUNT(*) AS records
FROM regulation_record
WHERE state = 'US-CO'
GROUP BY species_group
ORDER BY species_group;
-- Expected (alphabetical species_group):
--   bear      | 46
--   elk       | 115
--   mule_deer | 141
--   pronghorn | 77
--   whitetail | 19

-- (c) SQL shape: all document_type='annual_regulations'; no low-tier rows; 0 CO-STATEWIDE
SELECT
  SUM(CASE WHEN source->>'document_type' = 'annual_regulations' THEN 1 ELSE 0 END) AS annual_reg,
  SUM(CASE WHEN confidence = 'low' THEN 1 ELSE 0 END) AS low_rows,
  SUM(CASE WHEN jurisdiction_code = 'CO-STATEWIDE' THEN 1 ELSE 0 END) AS statewide_rows
FROM regulation_record
WHERE state = 'US-CO';
-- Expected: annual_reg=398; low_rows=0; statewide_rows=0

-- (d) jurisdiction_code matches CO-GMU-{int}+ (per-GMU rows)
SELECT COUNT(*) AS per_gmu_match
FROM regulation_record
WHERE state = 'US-CO'
  AND jurisdiction_code ~ '^CO-GMU-\d+$';
-- Expected: 398 (all 398 rows match this pattern)

-- (e) FK validity: every regulation_record.jurisdiction_code resolves to a geometry.id via the append-'-geom' convention
SELECT COUNT(*) AS dangling_refs
FROM regulation_record r
WHERE r.state = 'US-CO'
  AND NOT EXISTS (
    SELECT 1 FROM geometry g
    WHERE g.id = r.jurisdiction_code || '-geom'
      AND g.state = 'US-CO'
  );
-- Expected: 0

-- (f) Confidence distribution sanity-check
SELECT confidence, species_group, COUNT(*) AS rows
FROM regulation_record
WHERE state = 'US-CO'
GROUP BY confidence, species_group
ORDER BY species_group, confidence;
-- Expected per S06.6 closure record:
--   mule_deer high=55 medium=86
--   elk       high=38 medium=77
--   pronghorn high=25 medium=52
--   whitetail high=2  medium=17
--   bear      high=46 medium=0
```

Capture all six query outputs. **Closes S06.6 Group B ACs.**

---

## Step 10 — End-to-end verification + MT-untouched assertion

Final consolidated check covering both the cumulative CO state and PRD 002 success criterion #9 (MT untouched).

### Consolidated CO state

```sql
-- (a) Final CO geometry composition
SELECT kind, COUNT(*) AS rows
FROM geometry
WHERE state = 'US-CO'
GROUP BY kind
ORDER BY kind;
-- Expected:
--   gmu             | ~186
--   restricted_area | 10
--   state           | 1
-- (NO cwd_zone rows — S05.3 documented gap)

-- (b) Final CO regulation_record count
SELECT COUNT(*) FROM regulation_record WHERE state = 'US-CO';
-- Expected: 398

-- (c) Final jurisdiction_binding count
-- Note: this pass writes NO CO bindings (S06.10 is still ahead).
-- Only the existing 3 reclassified MT no-hunt-zone bindings + the 1 MT-STATEWIDE-bear binding + any other MT bindings from S03.10 should be present.
SELECT
  SUM(CASE WHEN regulation_record_state = 'US-MT' THEN 1 ELSE 0 END) AS mt_bindings,
  SUM(CASE WHEN regulation_record_state = 'US-CO' THEN 1 ELSE 0 END) AS co_bindings
FROM jurisdiction_binding;
-- Expected: mt_bindings ≈ S03.10 live count from M1 close (T16 empirical 788 was MT's S03.10 binding count;
--           may include the +1 MT-STATEWIDE-bear from S03.6.1 + the 3 reclassified rows already counted in 788);
--           co_bindings=0 (S06.10 has not yet executed).
```

### MT-untouched assertion (PRD 002 SC #9)

```sql
-- (d) MT geometry count UNCHANGED from M1 close baseline
SELECT kind, COUNT(*) FROM geometry WHERE state = 'US-MT' GROUP BY kind ORDER BY kind;
-- Expected:
--   cwd_zone        | 2     (S02.5)
--   hunting_district| 235   (S02.2)
--   portion         | 55    (S02.3)
--   restricted_area | 57    (S02.4)
--   state           | 1     (S03.0 MT-STATEWIDE-geom)
-- Total: 350 MT rows. If any kind's count differs, MT was touched — investigate.

-- (e) MT regulation_record count UNCHANGED from M1 close baseline
SELECT COUNT(*) FROM regulation_record WHERE state = 'US-MT';
-- Expected: 437 (post-S03.6.1; if differs, MT was touched — investigate)

-- (f) The 3 reclassified MT no-hunt-zone bindings from S05.3.5 still hold role='no_hunt_zone'
SELECT id, role
FROM jurisdiction_binding
WHERE geometry_id IN (
  'MT-restricted-bigame-glacier-national-park-geom',
  'MT-restricted-bigame-sun-river-game-preserve-geom',
  'MT-restricted-bigame-yellowstone-national-park-geom'
);
-- Expected: 3 rows, all role='no_hunt_zone'
-- (Already verified in Step 1; this is the end-of-pass confirmation that nothing reverted.)
```

Capture all six query outputs. **Closes the MT-untouched implicit precondition** that gates the M2 milestone-UAT-eventual-pass per PRD 002 SC #9.

---

## Post-pass cleanup

After Step 10, the operator should:

```bash
# (a) Confirm no unexpected file changes
git status -s
# Expected new (committable) files:
#   ingestion/states/colorado/fixtures/CPWAdminData-6-metadata-*.json
#   ingestion/states/colorado/fixtures/CPWAdminData-6-manifest-*.json
#   ingestion/states/colorado/fixtures/multipart-gmus.json   (S05.2 analytics fixture)
#   ingestion/states/colorado/fixtures/Federal_Fee_Managers_Authoritative_PADUS-0-metadata-*.json
#   ingestion/states/colorado/fixtures/Federal_Fee_Managers_Authoritative_PADUS-0-manifest-*.json
#   ingestion/states/colorado/fixtures/geometry-overlays.json
#   ingestion/states/colorado/fixtures/geometry-overlays-dropped.json
#   ingestion/states/colorado/fixtures/spatial-test-points.json
# No modifications to existing code files.

# (b) Confirm full test suite still green
cd ingestion && .venv/bin/pytest tests/ -q
# Expected: 1774 passed, 4 skipped (same as the pre-pass baseline; no regressions from the live-write pass)

# (c) Confirm ruff + mypy still clean
.venv/bin/ruff check ingestion/ tests/
.venv/bin/mypy ingestion/lib/

# (d) Commit the new fixtures locally as a single fixture-commit (DO NOT PUSH)
git add ingestion/states/colorado/fixtures/
git commit -m "fixtures(M2-operator-pass): commit live-run manifests + analytics + spatial fixtures"
```

After commit, **stop**. The PM will:
- Take the captured runbook outputs from the form below and split them into per-story `confidence-findings/SXX.X.md` § "Group B verification record" entries via separate doc-only commits
- Tick the corresponding Group B ACs in the E06 epic + planning README
- Confirm the operator-pass fixture commit per PM doc-rules (no `git push` until PM has reviewed)

---

## Operator capture form

Fill this in as you go. Verbatim outputs are preferred over summaries — the PM will summarize on the way into per-story closure notes. **Do not edit prior step entries** if a later step changes your understanding; instead add a new "Re-verification" sub-entry under the affected step.

### Pass metadata

- **Pass mode:** `M2-build` / `M2-release` (select one)
- **Target environment:** `_____________` (e.g., "dev Supabase project `huntready-dev`" or "production Supabase project `huntready`")
- **`DATABASE_URL` host (no creds — just the hostname for audit):** `_____________`
- **Date:** `_____________`
- **Operator:** `_____________`

If `Pass mode = M2-release`, also confirm: this is the pre-`m2`-tag verification pass and the captured outputs will feed the M2 → M3 handoff document.

### Pre-pass DB state (from Step 0 reconciliation)

```
[paste the geometry/regulation_record/binding count query output here]
```

### Step 1 — S05.3.5 migration

- `supabase db push` output:

  ```
  [paste verbatim]
  ```

- (a) CHECK constraint shape:

  ```
  [paste verbatim]
  ```

- (b) `SELECT DISTINCT role`:

  ```
  [paste verbatim]
  ```

- (c) The 3 MT rows reclassified:

  ```
  [paste verbatim]
  ```

- (d) `jurisdiction_binding` row count:

  ```
  [paste verbatim]
  ```

### Step 2 — S05.0 statewide

- Loader stdout:

  ```
  [paste verbatim]
  ```

- (a) Statewide row count: `_____` (expected 1)
- (b) `area_km2` value: `_______` km² (expected 267,138–272,535); `valid`: `____`
- (c) `source` fields:

  ```
  [paste verbatim]
  ```

### Step 3 — S05.2 GMUs

- Loader stdout:

  ```
  [paste verbatim]
  ```

- (a) CO GMU row count: `____` (expected 167–205)
- (b) FeatureServer source count (curl): `____`
- (c) `valid_count` / `invalid_count`: `____` / `____` (expect `invalid_count=0`)
- (d) Spot-check `CO-GMU-1-geom` / `CO-GMU-201-geom` / `CO-GMU-44-geom`:

  ```
  [paste verbatim]
  ```

- Manifest filename(s) committed:

  ```
  [paste from git status]
  ```

### Step 4 — S05.4 restricted areas

- Loader stdout:

  ```
  [paste verbatim]
  ```

- (a) Restricted-area row count: `____` (expected 10)
- (b) 10 ids (alphabetical):

  ```
  [paste verbatim]
  ```

  Curecanti present? `____` (expected: NO)

- (c) FeatureServer raw count (curl): `____` (expected 11)
- (d) ST_IsValid + acres for all 10:

  ```
  [paste verbatim]
  ```

  Any >10% delta vs published GIS_Acres? `____`

- (e) `verbatim_rule` null count: `____` (expected 10 at this step; Step 8 populates)

### Step 5 — S05.5 overlay fixture

- Builder stdout:

  ```
  [paste verbatim]
  ```

- (a) `geometry-overlays.json` exists: `Y/N`; line count `____`
- (b) Reproducibility SHA match across two runs: `Y/N`
- (c) Overlay row count (from quick shape check): `____`
- (d) Threshold recalibration note: `____` (e.g. "borderline drops within MT proportions; carry MT thresholds forward")

### Step 6 — S05.7 spatial-test-points

- Generator output: `spatial-test-points.json` created at `_____________`
- Test point counts per kind:

  ```
  [paste]
  ```

### Step 7 — E05 spatial verification (7 sections)

- Section 1 (cross-state filter): `PASS/FAIL` + outputs:

  ```
  [paste]
  ```

- Section 2 (ST_Covers): `PASS/FAIL` + outputs:

  ```
  [paste]
  ```

- Section 3 (ST_IsValid): `PASS/FAIL` + outputs:

  ```
  [paste]
  ```

- Section 4 (multi-part anchor ST_NumGeometries): `PASS/FAIL` + outputs:

  ```
  [paste]
  ```

- Section 5 (EXPLAIN ANALYZE): `PASS/FAIL` + outputs:

  ```
  [paste]
  ```

- Section 6 (ST_Envelope bounds): `PASS/FAIL` + outputs:

  ```
  [paste]
  ```

- Section 7 (wipe + re-ingest dry-run): `PASS/FAIL` + outputs:

  ```
  [paste]
  ```

### Step 8 — S06.5 restricted-area verbatim

- Loader stdout:

  ```
  [paste verbatim]
  ```

- (a) Populated count: `____` (expected 10)
- (b) PAD-US source count: `____` (expected 10)
- (c) Unique strings (NPS / AFA breakdown):

  ```
  [paste verbatim]
  ```

- (d) Rocky Mountain NP `verbatim_rule`:

  ```
  [paste verbatim]
  ```

- (e) AFA `verbatim_rule`:

  ```
  [paste verbatim]
  ```

### Step 9 — S06.6 regulation_records

- Loader stdout:

  ```
  [paste verbatim]
  ```

- (a) `regulation_record` count: `____` (expected 398)
- (b) Per-species counts:

  ```
  bear:      ____ (expected 46)
  elk:       ____ (expected 115)
  mule_deer: ____ (expected 141)
  pronghorn: ____ (expected 77)
  whitetail: ____ (expected 19)
  ```

- (c) SQL-shape sums: `annual_reg=____`; `low_rows=____`; `statewide_rows=____` (expected `398/0/0`)
- (d) Per-GMU jurisdiction_code match: `____` (expected 398)
- (e) Dangling FK refs: `____` (expected 0)
- (f) Confidence × species breakdown:

  ```
  [paste verbatim — compare against expected per Step 9 SQL block]
  ```

### Step 10 — End-to-end + MT-untouched

- (a) CO geometry composition:

  ```
  [paste verbatim — expect gmu ~186, restricted_area 10, state 1, no cwd_zone]
  ```

- (b) CO regulation_record total: `____` (expected 398)
- (c) `mt_bindings` / `co_bindings`: `____` / `0`
- (d) MT geometry composition:

  ```
  [paste — expect 2 cwd_zone + 235 HD + 55 portion + 57 restricted_area + 1 state = 350]
  ```

- (e) MT regulation_record count: `____` (expected 437)
- (f) The 3 MT no-hunt-zone bindings still `role='no_hunt_zone'`: `Y/N`

### Post-pass

- `git status -s` (expect only the new fixture files, no modifications):

  ```
  [paste verbatim]
  ```

- `pytest` result: `____ passed, ____ skipped` (expected `1774 passed, 4 skipped`)
- `ruff` + `mypy`: `PASS / FAIL`
- Local fixture commit SHA: `_____________`

### Anomalies / surprises

(Use this section for anything you noticed that doesn't match the runbook's documented expected shapes. Even small deltas. PM will reconcile.)

```
[free-form notes here]
```

### Operator sign-off

- Operator: `_____________`
- Date: `_____________`
- Time elapsed: `____` minutes
- Confidence in pass results: `high / medium / low`
- Comments for PM:

  ```
  [free-form notes here]
  ```

---

## Troubleshooting

**Step 1 fails with "relation already exists" or similar.** A prior partial migration ran. Use `supabase migration repair --status applied <timestamp>` per `.roughly/known-pitfalls.md`'s S03.0 pitfall.

**Step 2/3/4 loader exits with `ArcGISError`.** Check the inline diagnostic (the lib wraps the upstream service's `error` envelope per the S03.0 pitfall). If the service is temporarily unavailable, retry; if SHA mismatch (Step 2 only), fail-loud — the pinned TIGER file has changed and needs PM consultation per ADR-001.

**Step 3 row count outside `[167, 205]` band.** CPW has changed GMU geometry. Stop, capture the upstream count, surface to PM. Do NOT widen the band.

**Step 4 row count != 10.** Curecanti drop may have been skipped (raw count = 11; written = 10). Verify the `_assert_curecanti_dropped` guard fired. If 11 rows are written, S06.4's Stage-6 fix did not execute correctly — investigate before proceeding.

**Step 5 fixture not deterministic across two consecutive runs.** A non-determinism leaked into the builder. Capture both fixture SHAs and surface to PM; this would be a regression of the S05.5 two-phase tmp+rename + `sort_keys` discipline.

**Step 7 Section 5 `EXPLAIN ANALYZE` shows seq scan instead of GiST index.** Index missing or stale; investigate before proceeding.

**Step 9 fails OQ7 count-band guard.** The build count is outside the ±30% band around the dry-run-verified 398. Stop. The artifact may have drifted (e.g., `big-game-2026.json` or `black-bear-2026.json` SHA changed without re-pinning), or the target env's geometry FK targets don't match the artifact's GMU codes. Surface to PM.

**Step 10 MT count changed from M1 close baseline.** Critical — PRD 002 SC #9 violation. Stop. Capture the delta. The pass may have inadvertently touched MT (e.g., a misconfigured loader, a bad migration). Do NOT proceed; do NOT commit fixtures; surface to PM for full reconciliation.

**Step 10 confidence breakdown for `regulation_record` doesn't match Step 9 spec.** S06.6's loader may have read a stale artifact or a different artifact version. Re-check the SHA of `big-game-2026.json` against the S06.3.1 pinned value (`9312e259…bb2f`) and `black-bear-2026.json` against the S06.4 pinned value (`7b35c202…d5f6`).

**Anything else.** Capture verbatim, surface to PM. Group B's job is to confirm the live target env agrees with dry-run; any disagreement is investigation-worthy by definition.

---

## References

- `docs/runbooks/E05-colorado-geometry-verification.md` — the existing E05 operator runbook (Step 7 calls into this)
- `docs/runbooks/M1-uat.md` — convention reference for the runbook structure + capture-form pattern
- `docs/planning/epics/completed/E05-colorado-geometry-ingestion.md` — E05 epic with all per-story Group A ACs
- `docs/planning/epics/E06-colorado-regulation-text-ingestion.md` — E06 epic with S06.5 + S06.6 Group A ACs
- `docs/planning/epics/E06-confidence-findings/S06.5.md` + `S06.6.md` — per-story closure notes where PM lands the Group B ticks after this pass
- `docs/planning/epics/completed/E05-confidence-findings/S05.0.md`, `S05.2.md`, `S05.3.5.md`, `S05.4.md`, `S05.5.md`, `S05.7.md` — per-story operator runbooks this consolidates from
- `.roughly/known-pitfalls.md` — runbook is consistent with the accumulated pitfalls (multi-column PDF prose extraction; SHA-pin two-gates model; etc.)

---

*Authored 2026-06-19 by the PM at the operator's request. Deletes at `m2` tag per ADR-017 §6 ONLY IF the captured outputs have been split into per-story `confidence-findings/SXX.X.md` entries first; otherwise this runbook is the authoritative record and survives `m2` until rolled into the M2 → M3 handoff document at milestone close.*
