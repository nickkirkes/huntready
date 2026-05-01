# Montana State Ingestion Adapter

Montana state ingestion adapter — loads big-game geometries from MT FWP's ArcGIS MapServer.

## Import path

Scripts in `ingestion/states/<state>/` are not modules of the installed package — they have no `__init__.py` and are not importable. They run as plain scripts (`python ingestion/states/montana/load_hds.py`).

The shared library is importable as `ingestion.lib.*` because `ingestion/pyproject.toml` configures `packages = ["ingestion"]`, making the package editable-installable under `.venv`. Imports inside adapter scripts follow the installed-package form:

```python
from ingestion.lib.arcgis import fetch_layer_metadata, fetch_features
from ingestion.lib.db import connect, upsert_geometries
```

The `.venv` is created and the package installed editable via `pip install -e .` inside `ingestion/` (or your preferred resolver — `uv pip install -e .`). The scripts must be invoked via the venv interpreter (see below).

## Running the S02.2 hunting-district loader

Run from the repo root:

```bash
ingestion/.venv/bin/python ingestion/states/montana/load_hds.py
```

Optional CLI arguments:

| Flag | Default | Description |
|------|---------|-------------|
| `--service-url` | MT FWP MapServer URL | Override the ArcGIS MapServer base URL (useful for testing against a local fixture server) |
| `--fetch-year` | Current UTC year | Which annual cycle to stamp on source citations |

## Running the S02.3 portions loader

Run from the repo root:

```bash
ingestion/.venv/bin/python ingestion/states/montana/load_portions.py
```

Same CLI flags (`--service-url`, `--fetch-year`) and same env requirements (`DATABASE_URL`, optional `HUNTREADY_INGESTION_CONTACT`) as `load_hds.py`. Hits the same MapServer at different layer IDs.

### Layers loaded by `load_portions.py`

| Layer ID | Name | `id` prefix |
|----------|------|-------------|
| #4 | Antelope Portions | `MT-HD-antelope-{DISTRICT}-portion-{slug}-geom` |
| #12 | Mule Deer Portions | `MT-HD-mule-deer-{DISTRICT}-portion-{slug}-geom` |
| #13 | Whitetail Portions | `MT-HD-whitetail-{DISTRICT}-portion-{slug}-geom` |
| #14 | Elk Portions | `MT-HD-elk-{DISTRICT}-portion-{slug}-geom` |

All rows have `kind='portion'`. The `slug` is the `SHAPECODE` value verbatim when present (already a code, not free text); otherwise the slugified `PORTIONNAME`. The loader fails loudly with `ArcGISError` if a layer produces duplicate geometry IDs (i.e. neither field yields collision-free identifiers).

Layer #14 fields are pre-verified in the epic spec (`DISTRICT`, `PORTIONNAME`, `PORTIONTYPE`, `SHAPECODE`, `REG`, `REGYEAR`). Field names for layers #4, #12, #13 are confirmed against committed metadata fixtures during the first live load.

## Running the S02.4 restricted-areas loader

Run from the repo root:

```bash
ingestion/.venv/bin/python ingestion/states/montana/load_restricted_areas.py
```

Same CLI flags (`--service-url`, `--fetch-year`) and same env requirements (`DATABASE_URL`, optional `HUNTREADY_INGESTION_CONTACT`) as the other Montana loaders. Hits the same `admbnd/huntingDistricts` MapServer at layers #2 and #15.

### Layers loaded by `load_restricted_areas.py`

| Layer ID | Name | `id` prefix |
|----------|------|-------------|
| #2 | Big Game Restricted Areas | `MT-restricted-bigame-{PORTIONNAME_slug}-geom` |
| #15 | Elk Restricted Areas | `MT-restricted-elk-{PORTIONNAME_slug}-geom` |

All rows have `kind='restricted_area'`. Both layers use a slugified `PORTIONNAME` as the identity component (layer #2 carries no `SHAPECODE`; layer #15 carries one but `PORTIONNAME` is used uniformly so the ID grammar is consistent across the story's output).

`verbatim_rule` is populated from `REG` and `COMMENTS` per the five-case combination rule in [ADR-015](../../../docs/adrs/ADR-015-geometry-verbatim-rule.md): both populated and differ → `f"{REG}\n\n--- COMMENTS ---\n\n{COMMENTS}"`; both populated and identical (after strip) → original `REG`; one populated → that one; both empty → `NULL`.

**S02.5 coordination:** Layer #2 features matching the CWD discriminator are skipped here and ingested by S02.5 as `kind='cwd_zone'`. The predicate is field-specific (case-insensitive substring):

- `COMMENTS ILIKE '%CWD%'`
- `REG ILIKE '%CWD%'`
- `PORTIONNAME ILIKE '%chronic wasting%'` *(NOT `'%CWD%'` — `PORTIONNAME` matches the spelled-out form only)*

A row matches the discriminator if any one of those three checks is true. The discriminator predicate lives in `cwd_discriminator.py` and is shared between S02.4 and S02.5 so the partition is exact and re-runnable in any order. The `PORTIONNAME` asymmetry is intentional — see `test_portionname_cwd_alone_returns_false` and `test_portionname_cwd_with_empty_comments_and_reg_returns_false`.

## Required environment variables

**Required:**

- `DATABASE_URL` — Postgres connection string for the target Supabase project (e.g. `postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres`)

**Optional:**

- `HUNTREADY_INGESTION_CONTACT` — Operator email or URL appended to the ArcGIS HTTP `User-Agent` as `(contact: <value>)`. Gives MT FWP a way to reach you if a fetch behaves unexpectedly. Omit for anonymous requests.

## Layers loaded by `load_hds.py`

| Layer ID | Name | `id` prefix |
|----------|------|-------------|
| #3 | Antelope Hunting Districts | `MT-HD-antelope-{DISTRICT}-geom` |
| #10 | Black Bear Hunting Districts | `MT-HD-bear-{DISTRICT}-geom` |
| #11 | Deer/Elk/Lion Hunting Districts | `MT-HD-deer-elk-lion-{DISTRICT}-geom` |

Layer #10 uses `kind='hunting_district'`, not `'bmu'`. FWP's GIS authority names these "Black Bear Hunting Districts"; the regulation booklet's "Bear Management Unit" terminology is a separate concern carried by `jurisdiction_binding.role` in E03. See epic S02.2 line 246.

IDs are species-prefixed to prevent cross-layer collisions (district 700 exists in multiple species layers as different polygons).

## Idempotency

All writes are UPSERT on `id`. Re-running the loader picks up upstream geometry corrections without creating duplicates. Safe to run against a production database.

## Fixtures

Each run writes two fixture files per layer into `ingestion/states/montana/fixtures/`:

- `huntingDistricts-{layer_id}-metadata-{ts}.json` — ArcGIS layer metadata response (~7KB each)
- `huntingDistricts-{layer_id}-features-{ts}.geojson` — full feature collection (~38–90 MB per layer)

**Metadata fixtures are committed** for drift detection on field names, OID columns, and spatial reference. **Feature fixtures are gitignored** at `fixtures/.gitignore` — committing them would add ~180 MB per run to the repo. The S02.1 spec called for both, but assumed "small"; a follow-up ADR will choose the storage policy (git-lfs, manifest + object store, or sampling).

## Post-load verification

Run these against the same Supabase project after the first load:

```sql
-- Confirm all rows are kind='hunting_district' (per epic AC line 274)
SELECT kind, COUNT(*) FROM geometry GROUP BY kind;

-- Confirm all geometries are topologically valid
-- Note: direct `geom::geometry` cast is not enabled on this Supabase
-- project's PostGIS install; round-trip via ST_AsText/ST_GeomFromText.
SELECT id FROM geometry
WHERE NOT ST_IsValid(ST_GeomFromText(ST_AsText(geom), 4326));

-- Identify candidates for the named multi-part HD assertion (epic AC line 277)
SELECT id, ST_NumGeometries(ST_GeomFromText(ST_AsText(geom), 4326)) AS parts
FROM geometry
WHERE kind='hunting_district'
ORDER BY parts DESC LIMIT 5;
```

Expected: the validity query returns zero rows. The multi-part query should surface at least one HD with `parts > 1`.

After running `load_portions.py`, also confirm portions loaded correctly:

```sql
-- Counts by id_prefix; confirms all four portion layers wrote rows.
-- Plain LIKE filters per species since PORTIONNAME slugs may contain the
-- substring "portion" (e.g. mule-deer fallback uses "Portion of HD ..." names).
SELECT 'antelope'   AS species, COUNT(*) FROM geometry WHERE kind='portion' AND id LIKE 'MT-HD-antelope-%'
UNION ALL SELECT 'mule-deer',   COUNT(*) FROM geometry WHERE kind='portion' AND id LIKE 'MT-HD-mule-deer-%'
UNION ALL SELECT 'whitetail',   COUNT(*) FROM geometry WHERE kind='portion' AND id LIKE 'MT-HD-whitetail-%'
UNION ALL SELECT 'elk',         COUNT(*) FROM geometry WHERE kind='portion' AND id LIKE 'MT-HD-elk-%';

-- Spot-check the portion ID format
SELECT id FROM geometry WHERE kind='portion' ORDER BY id LIMIT 5;

-- Confirm verbatim_rule is populated where REG was non-empty
SELECT
  COUNT(*) FILTER (WHERE verbatim_rule IS NOT NULL) AS with_rule,
  COUNT(*) FILTER (WHERE verbatim_rule IS NULL) AS without_rule
FROM geometry WHERE kind='portion';
```

## Multi-part HD reference

**`MT-HD-deer-elk-lion-690-geom`** — `ST_NumGeometries = 12`. Loaded 2026-04-30 from MT FWP layer #11. Use this ID as the named multi-part HD assertion in S02.7's verification suite.

(HD-690 also appears multi-part in the bear and antelope species layers — `MT-HD-bear-600-geom` and `MT-HD-antelope-690-geom`, both with 12 parts. The deer-elk-lion entry is the canonical reference because layer #11 is the most authoritative HD source.)

## Initial load record (2026-04-30)

First successful load of all three layers:

| Layer | `id` prefix | Rows |
|-------|-------------|------|
| #3 (Antelope) | `MT-HD-antelope-` | 61 |
| #10 (Black Bear) | `MT-HD-bear-` | 35 |
| #11 (Deer/Elk/Lion) | `MT-HD-deer-elk-lion-` | 139 |
| **Total** | | **235** |

All rows: `kind='hunting_district'`, `state='US-MT'`, `source.document_type='gis_layer'`, `license_year=2026`, `verbatim_rule` populated from each feature's `REG` field. UPSERT idempotency confirmed by re-running with unchanged row counts.

**Data-quality note:** `MT-HD-antelope-556-geom` (OBJECTID=385, MT FWP layer #3) has a self-intersecting source polygon. `shapely.make_valid` produces a `GeometryCollection [Polygon, LineString]`; the `arcgis.geojson_to_multipolygon_wkt` helper recovers the polygonal part (area preserved exactly) and emits a WARNING. Worth flagging upstream to MT FWP.

## S02.3 initial load record (2026-04-30)

First successful load of all four portion layers:

| Layer | Slug strategy | Rows |
|-------|---------------|------|
| #4 (Antelope Portions) | SHAPECODE | 4 |
| #12 (Mule Deer Portions) | PORTIONNAME (SHAPECODE collided) | 11 |
| #13 (Whitetail Portions) | SHAPECODE | 13 |
| #14 (Elk Portions) | SHAPECODE | 27 |
| **Total** | | **55** |

All rows: `kind='portion'`, `state='US-MT'`, `source.document_type='gis_layer'`, `license_year=2026`, `verbatim_rule` populated from each feature's `REG` field (55/55 non-null). All geometries topologically valid (`ST_IsValid(...)=TRUE`). UPSERT idempotency confirmed by re-running with unchanged row counts.

**Slug-strategy note:** Layer #12 (mule-deer) reuses `SHAPECODE='mdPt312'` for both East- and West-half polygons of district 312, and `mdPt388` for both Inside/Outside-of-Weapons-Restriction-Area polygons of district 388. The loader detects the SHAPECODE collision after building the layer's geometries and silently retries with `_slugify(PORTIONNAME)` for the entire layer. Per spec line 308: "Fail loudly if neither SHAPECODE nor unique PORTIONNAME yields collision-free IDs within a layer." Layer #12's longer IDs (max 106 chars) reflect this fallback — the other three layers use the compact SHAPECODE form (≤39 chars). The strategy choice is logged at INFO level so operators can audit.

## S02.4 initial load record (2026-04-30)

First successful load of both restricted-area layers:

| Layer | `id` prefix | Rows |
|-------|-------------|------|
| #2 (Big Game Restricted Areas) | `MT-restricted-bigame-` | 53 |
| #15 (Elk Restricted Areas) | `MT-restricted-elk-` | 4 |
| **Total** | | **57** |

All rows: `kind='restricted_area'`, `state='US-MT'`, `source.document_type='gis_layer'`, `verbatim_rule` populated for all 57 rows (none null), 55 of 57 contain the `--- COMMENTS ---` separator (both `REG` and `COMMENTS` populated and differ; the other 2 are REG-only or REG==COMMENTS dedup cases). Layer #2 has no `REGYEAR` field, so its 53 rows have `license_year=NULL`. Layer #15's 4 rows have `license_year=2026`. All geometries topologically valid (`ST_IsValid(...)=TRUE`). UPSERT idempotency confirmed by re-running with unchanged row counts.

**CWD discriminator finding:** Layer #2's 53 features included **zero CWD-matching rows** — the discriminator filter ran clean. This is significant for [S02.5 planning](../../../docs/planning/epics/E02-geometry-ingestion.md): the exclusion-filter path over layer #2 will not yield any CWD zones. S02.5 must use the standalone-layer discovery path (Hub catalog search) or fall through to the hand-traced GeoJSON fallback.

**Post-load verification SQL** (Supabase-compatible — uses the `ST_GeomFromText(ST_AsText(...))` workaround per [.roughly/known-pitfalls.md](../../../.roughly/known-pitfalls.md)):

```sql
-- Counts by id_prefix
SELECT 'bigame' AS area, COUNT(*) FROM geometry WHERE kind='restricted_area' AND id LIKE 'MT-restricted-bigame-%'
UNION ALL SELECT 'elk', COUNT(*) FROM geometry WHERE kind='restricted_area' AND id LIKE 'MT-restricted-elk-%';

-- verbatim_rule populated and contains the separator
SELECT
  COUNT(*) FILTER (WHERE verbatim_rule IS NOT NULL) AS with_rule,
  COUNT(*) FILTER (WHERE verbatim_rule LIKE '%--- COMMENTS ---%') AS with_separator
FROM geometry WHERE kind='restricted_area';

-- No CWD rows escaped to S02.4 (sanity check on the discriminator).
-- Must scan BOTH verbatim_rule AND id, mirroring the predicate's two channels:
--   - REG/COMMENTS-driven matches: 'CWD' in REG or COMMENTS surfaces in verbatim_rule.
--   - PORTIONNAME-driven matches: 'chronic wasting' in PORTIONNAME is baked
--     into the id slug as 'chronic-wasting' (slugify lowercases + hyphenates).
-- DO NOT add 'id ILIKE %cwd%': PORTIONNAME containing 'CWD' alone (without
-- 'chronic wasting') is INTENTIONALLY allowed to stay in S02.4 — see
-- test_portionname_cwd_with_empty_comments_and_reg_returns_false. Adding
-- that check would flag the deliberate asymmetry as an escape.
SELECT id, verbatim_rule FROM geometry
WHERE kind='restricted_area' AND id LIKE 'MT-restricted-bigame-%'
  AND (
    verbatim_rule ILIKE '%CWD%'         -- REG/COMMENTS branch matched
    OR id ILIKE '%chronic-wasting%'     -- PORTIONNAME branch matched
  );

-- Geometry validity
SELECT id FROM geometry WHERE kind='restricted_area'
  AND NOT ST_IsValid(ST_GeomFromText(ST_AsText(geom), 4326));
```

## S02.5 — CWD Zones (Path A: ADMBND_HD_CWD FeatureServer)

**Source:** `ADMBND_HD_CWD` Feature Service on ArcGIS Online — `https://services3.arcgis.com/Cdxz8r11hT0MGzg1/arcgis/rest/services/ADMBND_HD_CWD/FeatureServer/0` (owner `MtFishWildlifeParks`, public, 2 polygon features for REGYEAR=2026).

See [cwd-source-discovery.md](cwd-source-discovery.md) for the investigation that selected Path A over the discriminator-filter (Path B) and hand-traced (Path C) fallbacks.

**Spec deviation:** The story spec called for three named zones (Libby, South-Central, Northeast); the live FWP layer publishes two (Libby, Kalispell). Substitution is permitted by the spec; documented in the discovery report.

### Running the S02.5 CWD zones loader

Run from the repo root:

```bash
ingestion/.venv/bin/python ingestion/states/montana/load_cwd_zones.py
```

Same env requirements (`DATABASE_URL`, optional `HUNTREADY_INGESTION_CONTACT`) as the other Montana loaders. Hits the dedicated `ADMBND_HD_CWD` FeatureServer rather than the `admbnd/huntingDistricts` MapServer.

### Layer loaded by `load_cwd_zones.py`

| Service                     | Layer ID | Name                               | `id` prefix                        |
|-----------------------------|----------|------------------------------------|------------------------------------|
| ADMBND_HD_CWD FeatureServer | 0        | Chronic Wasting Disease Hunt Areas | `MT-CWD-zone-{AREANAME_slug}-geom` |

All rows have `kind='cwd_zone'`, `state='US-MT'`, `license_year=2026`.

**Expected rows:** 2 rows.

| OBJECTID | AREANAME                      | SQMILES |
|----------|-------------------------------|---------|
| 967      | Libby CWD Management Zone     | 499     |
| 968      | Kalispell CWD Management Zone | 154     |

### Post-load verification (S02.5)

```sql
-- 1. Row count
SELECT count(*) FROM geometry WHERE state='US-MT' AND kind='cwd_zone';

-- 2. Geometry validity
SELECT id, ST_IsValid(ST_GeomFromText(ST_AsText(geom), 4326)) AS is_valid
  FROM geometry WHERE kind='cwd_zone' AND state='US-MT';

-- 3. UAT — Libby zone spot-check (test point inside the polygon bbox)
SELECT id, name FROM geometry
  WHERE kind='cwd_zone' AND state='US-MT'
    AND ST_Covers(ST_GeomFromText(ST_AsText(geom), 4326),
                  ST_SetSRID(ST_Point(-115.555, 48.388), 4326));
-- (expected: one row, "Libby CWD Management Zone")

-- 4. UAT — Kalispell zone spot-check
SELECT id, name FROM geometry
  WHERE kind='cwd_zone' AND state='US-MT'
    AND ST_Covers(ST_GeomFromText(ST_AsText(geom), 4326),
                  ST_SetSRID(ST_Point(-114.320, 48.310), 4326));
-- (expected: one row, "Kalispell CWD Management Zone")

-- 5. UAT — outside-zone control (eastern Montana)
SELECT count(*) FROM geometry
  WHERE kind='cwd_zone' AND state='US-MT'
    AND ST_Covers(ST_GeomFromText(ST_AsText(geom), 4326),
                  ST_SetSRID(ST_Point(-106.500, 46.800), 4326));
-- (expected: 0)
```

## S02.5 initial load record (2026-05-01)

First successful load of the dedicated `ADMBND_HD_CWD` FeatureServer:

| Layer                       | `id` prefix      | Rows |
|-----------------------------|------------------|------|
| ADMBND_HD_CWD/FeatureServer/0 | `MT-CWD-zone-` | 2    |

All 2 rows: `kind='cwd_zone'`, `state='US-MT'`, `license_year=2026`, `source.document_type='gis_layer'`, `source.agency='Montana Fish, Wildlife & Parks'`, `verbatim_rule=NULL` (this layer has no inline regulation text — only a `WEBPAGE` URL pointing to `https://fwp.mt.gov/cwd`). Both geometries pass `ST_IsValid`. UPSERT idempotency confirmed by re-running with unchanged row counts.

**UAT** — all five `ST_Covers` queries above pass:
- Libby zone resolves at `(-115.555, 48.388)` → `MT-CWD-zone-libby-cwd-management-zone-geom`
- Kalispell zone resolves at `(-114.320, 48.310)` → `MT-CWD-zone-kalispell-cwd-management-zone-geom`
- Outside-zone control at `(-106.500, 46.800)` returns 0 rows

**CRS detection:** The shared loader emitted the magnitude-based CRS warning (declared layer CRS is EPSG:3857; `outSR=4326` requested). Coordinates pass the WGS84 range check; bbox is `(-115.80 to -114.15)` lng / `(48.16 to 48.64)` lat — well outside equator/prime-meridian ambiguity. Per [.ruckus/known-pitfalls.md](../../../.ruckus/known-pitfalls.md) the warning is acceptable for this dataset.

## Building the overlay fixture (S02.6)

Builds the geometry-overlay fixture for E03 handoff. The fixture captures every spatial relationship between V1 Montana geometries — HD self-references, HD→Portion containment, HD→CWD-zone overlaps, and HD→Restricted-Area overlaps — so E03 can populate `jurisdiction_binding` rows once `regulation_record` rows exist, without re-running PostGIS spatial computation.

### Architecture: local shapely (not cross-join SQL)

The script issues a single bulk query (`SELECT id, kind, ST_AsText(geom) FROM geometry WHERE state = 'US-MT'` — geography-native, no `::geometry` cast) and computes spatial relationships locally with shapely + STRtree. The original epic spec used PostGIS cross-join SQL (`SELECT … FROM geometry a, geometry b WHERE ST_Covers(a.geom, b.geom)`); that approach hits Supabase's role-locked 2-min `statement_timeout` on the live MT dataset (~12k candidate pairs × ~113 KB MultiPolygons). Local shapely completes the same work in ~5 seconds.

The relationship label comes from a three-band area-ratio threshold (see [ADR-016](../../../docs/adrs/ADR-016-digitization-tolerant-containment.md)):

```text
overlap_pct = parent.intersection(child).area / child.area

overlap_pct >= 0.99   →  relationship = "covers"        (digitization-tolerant containment)
overlap_pct <  0.01   →  drop, write to audit log       (boundary-touching artifact)
otherwise              →  relationship = "intersects"    (genuine partial overlap)
```

### Running the S02.6 overlay fixture builder

Run from the repo root:

```bash
ingestion/.venv/bin/python ingestion/states/montana/build_overlay_fixture.py
```

Same env requirements (`DATABASE_URL`) as the other Montana scripts. No ArcGIS fetch is performed — this script queries only the Supabase Postgres instance.

### Output

Two files, both committed to the repo (not gitignored), both written via atomic tmp+rename:

- `ingestion/states/montana/fixtures/geometry-overlays.json` — kept rows. Each entry has `parent_geometry_id`, `child_geometry_id`, `parent_kind`, `child_kind`, `relationship` (one of `self`, `covers`, `intersects`), and `role_for_e03`.
- `ingestion/states/montana/fixtures/geometry-overlays-dropped.json` — audit log of HD↔child pairs filtered out by the lower threshold. Each entry has `parent_geometry_id`, `child_geometry_id`, `parent_kind`, `child_kind`, and `overlap_pct` (rounded to 6 decimal places). Filtering is one-way; the audit lets a future reviewer verify nothing semantically real was discarded.

**Idempotent:** re-running produces byte-identical output for both files (sorted rows, sorted JSON keys, deterministic serialization, trailing newline).

### Coverage invariant

- **Portions** and **CWD zones** must overlap at least one hunting district above the threshold. Orphans cause the script to raise `OverlayFixtureError` with the full violation list — fail loud.
- **Restricted areas** are *expected* to have HD parents. The script's `EXPECTED_RA_ORPHAN_IDS` allowlist exempts 3 known no-hunt zones — Glacier National Park, Sun River Game Preserve, Yellowstone National Park — from the orphan check (INFO-logged). Any other restricted_area orphan blocks the build, same as portion/CWD orphans. Adding a new ID to the allowlist requires a code edit and human review per [ADR-016](../../../docs/adrs/ADR-016-digitization-tolerant-containment.md).
- Every fixture-referenced `geometry_id` (parent or child) must exist in the loaded geometry list — otherwise `OverlayFixtureError`.

### Schema

`ingestion/ingestion/lib/overlays.py` defines:

- `OverlayFixtureRow` (TypedDict) — kept-row shape.
- `DroppedOverlayPair` (TypedDict) — audit-row shape.
- `GeometryRoleForE03`, `OverlayRelationship`, `OverlayParentKind`, `OverlayChildKind` (Literal aliases).
- `ROLE_FOR_E03_BY_CHILD_KIND` — mapping that E03 imports to populate `jurisdiction_binding.role`.

E03 imports these directly to type-check its consumer.

## Related

- Epic: [`docs/planning/epics/E02-geometry-ingestion.md`](../../../docs/planning/epics/E02-geometry-ingestion.md) — S02.2 starts at line 226
- Shared ArcGIS lib: [`ingestion/ingestion/lib/arcgis.py`](../../ingestion/lib/arcgis.py)
- DB writer: [`ingestion/ingestion/lib/db.py`](../../ingestion/lib/db.py)
- ADR-014: `SourceCitation.document_type='gis_layer'` (type-layer enforcement)
- ADR-015: `geometry.verbatim_rule` column and REG+COMMENTS handling rule
- ADR-016: Digitization-tolerant containment for geometry overlays (area-ratio thresholds)
