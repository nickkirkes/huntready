# E02: Montana Geometry Ingestion

**Status:** Not Started
**Milestone:** M1 — Montana Ingestion
**Dependencies:** E01 (complete, merged 2026-04-28)
**Validated:** 2026-04-28
**Estimated Stories:** 8
**UAT Gating:** S02.5, S02.6, S02.7 (spot-checks of CWD zones, geometry overlays, and spatial queries)

---

## Objective

E02 ingests every Montana big-game geometry that V1 needs from MT FWP's ArcGIS MapServer (`admbnd/huntingDistricts`) into Postgres, validated through `shapely.make_valid()` and stored as `geography(MultiPolygon, 4326)`. PostGIS spatial queries return the right HD/Portion/Restricted-Area for known coordinates. A geometry overlay fixture captures the spatial relationships (HD↔Portion, HD↔CWD, HD↔Restricted Area) for E03 to consume.

See [PRD 001](../../planning/prds/001-M1-montana-ingestion.md) for authoritative scope. See [`docs/research/montana-gis-endpoints-verified.md`](../../research/montana-gis-endpoints-verified.md) for verified endpoints.

---

## PRD/schema conflict — resolved by deferring jurisdiction_binding to E03

The PRD (lines 48, 90, 96, 111) says jurisdiction_binding rows are written in E02. The schema makes this physically impossible: `jurisdiction_binding` has a hard composite FK to `regulation_record`, and `regulation_record` rows are E03 territory.

**Resolution:** E02 produces a geometry overlay fixture at `ingestion/states/montana/fixtures/geometry-overlays.json` that captures HD↔Portion, HD↔CWD, HD↔Restricted Area spatial relationships. E03 consumes it to write jurisdiction_binding rows once regulation_records exist. Story S02.6 implements this. PRD 001 will need reconciliation at M2 PM hand-off.

This resolution was confirmed sound by the Schema Stress-Test reviewer; alternatives (nullable FK, deferred FK constraints, regulation_record stubs) were rejected for either schema-instability or invariant-violation reasons.

---

## Stories

### S02.0: Schema preparation — `document_type='gis_layer'` + `geometry.verbatim_rule`

**As a** developer ingesting Montana geometries
**I want** the schema extended to accommodate ArcGIS source citations and verbatim regulatory text on geometry rows
**So that** layer #2/#11 `REG`/`COMMENTS` fields and ArcGIS provenance can be stored without schema special-casing

**UAT: no**

**Context:**

Two schema gaps surfaced during E02 validation:

1. **`SourceCitation.document_type` enum** is `('annual_regulations' | 'rule_change' | 'emergency_order' | 'correction')`. None describe an ArcGIS MapServer feature. Forcing `'annual_regulations'` would conflate provenance categories — a query for "all annual_regulations sources" should not return GIS rows mixed with PDF rows.

2. **`geometry` has no `verbatim_rule` column.** But layer #2 (Big Game Restricted Areas) has `COMMENTS` and `REG` fields, and layer #11 (Deer Elk Lion HDs) has `REG` — both carry verbatim regulatory text scoped to a polygon. Per ADR-008, verbatim text is required wherever it exists in source. Stashing it in `source` jsonb would conflate provenance with regulatory content.

**Two ADRs required (drafted by human or in an explicit ADR-drafting session — PM does not write ADRs autonomously):**

- ADR-014 (proposed): Extend `SourceCitation.document_type` to include `'gis_layer'`. Rationale: GIS feature services are a distinct provenance category from published regulation documents.
- ADR-015 (proposed): Add `geometry.verbatim_rule text` (nullable). Rationale: real Montana geometries carry verbatim regulatory text in source attributes (`REG`, `COMMENTS`); per ADR-008, this text must not be paraphrased or stashed in jsonb.

**Migration deliverables:**

1. New migration adding `'gis_layer'` to `source` jsonb's `document_type` enum (Postgres can't enforce jsonb-internal CHECK constraints, so this is enforced in Pydantic + TypeScript only — but the documentation must reflect the additional value).
2. New migration adding `verbatim_rule text` (nullable) to `geometry`.
3. Pydantic model update: `SourceCitation.document_type: Literal[..., "gis_layer"]` and `Geometry.verbatim_rule: str | None`.
4. TypeScript interface update: same additions to `mcp-server/src/types/schema.ts`.
5. Architecture.md update: extend the `SourceCitation` and `Geometry` interface definitions in §"Schema types" to match.

**Three-place sync per ADR-006.** The Pydantic and TypeScript types must update in the same PR as the migration.

**No data is loaded by this story.** Verifies migration applies cleanly, types validate, all three representations match.

**Relevant ADRs:** [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md) (three-place sync), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) (verbatim text), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md) (decomposed entities).

**Acceptance Criteria:**

- [ ] ADR-014 (or equivalent) drafted and accepted documenting `document_type='gis_layer'` extension
- [ ] ADR-015 (or equivalent) drafted and accepted documenting `geometry.verbatim_rule` addition
- [ ] Timestamped migration in `supabase/migrations/` adds `verbatim_rule text` (nullable) to `geometry`
- [ ] Pydantic `SourceCitation.document_type` Literal updated to include `"gis_layer"`
- [ ] Pydantic `Geometry` model updated to include `verbatim_rule: str | None = None`
- [ ] TypeScript `SourceCitation` and `Geometry` interfaces updated to match
- [ ] `architecture.md` § "Schema types" updated with the new fields
- [ ] `tsc --noEmit`, `ruff check`, `mypy` all pass
- [ ] Migration applies cleanly to a fresh Supabase project after E01's migrations
- [ ] No data written

---

### S02.1: ArcGIS fetch infrastructure (shared library)

**As a** developer ingesting MT FWP MapServer layers
**I want** a robust shared `arcgis` library handling pagination, source-fixture capture, and idempotent re-fetch
**So that** S02.2-S02.5 can ingest layers without re-implementing fetch logic and PRD R2 (endpoint stability) is mitigated

**UAT: no**

**Context:**

Build `ingestion/ingestion/lib/arcgis.py`. **No state-specific code** — shared library territory per [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md). Used by Montana state adapter (E02/E03) and any future state.

The library must address ArcGIS-specific gotchas surfaced during validation. Each is a documented behavior, not a hypothetical:

**1. Layer metadata fetch (must run before feature fetch):**
- Fetch `<service>/<layer_id>?f=json`
- Capture as fixture: `ingestion/states/montana/fixtures/<service>-<layer_id>-metadata-<timestamp>.json`
- Read `maxRecordCount`, `objectIdField`, `fields[]`, `geometryType`, `extent.spatialReference`
- Cache per-layer for the run

**2. Paginated feature fetch:**
- Page size = layer's `maxRecordCount` (do NOT hardcode 2000)
- Required query parameters:
  - `where=OBJECTID>=0` (always-true, more portable than `1=1`)
  - `outFields=` *explicit comma-separated list from metadata*, NOT `*` (some servers truncate `*` if `excludeFromAllRequest` is set on a field)
  - `orderByFields=<objectIdField> ASC` — required for stable pagination (without this, ArcGIS may return overlapping/missing rows on page boundaries)
  - `f=geojson&outSR=4326`
  - `returnTrueCurves=false` (defensive — prevents CIRCULARSTRING geometries that GeoJSON can't represent)
  - `geometryPrecision=7` (~1cm at this latitude — canonicalizes float output for hash stability)
- Termination condition: loop until response's `exceededTransferLimit` is `false`/absent AND page is empty. **Do NOT** use "fewer than page-size returned" as the termination signal — fails at exact-N×pageSize boundaries.
- Cross-check final feature count against a separate `returnCountOnly=true` query before pagination starts. Hard-fail on discrepancy.
- Dedup by OBJECTID after all pages collected.

**3. Spatial reference verification (do NOT trust the header):**
- ArcGIS may return Web Mercator coordinates while reporting `crs: EPSG:4326` in the GeoJSON envelope
- After fetch, sanity-check coordinate ranges. Montana lies in lon `[-116, -104]`, lat `[44, 49]`. If any geometry coordinate has `|x| > 180` or `|y| > 90`, response is in projected units regardless of what the header says — fail loudly. Fallback reprojection from EPSG:3857 via `pyproj.Transformer.from_crs(3857, 4326, always_xy=True)` (NOT shapely — shapely doesn't do CRS).

**4. Source fixture capture (per PRD R2 mitigation):**
- Write two artifacts per layer per fetch:
  - `<service>-<layer_id>-metadata-<timestamp>.json` (raw layer descriptor)
  - `<service>-<layer_id>-features-<timestamp>.geojson` (raw feature collection)
- Optionally: hash-suffixed historical copies + `<service>-<layer_id>-latest.{json,geojson}` symlinks for `ls`-based diff
- These fixtures are committed to the repo (small) and used for drift detection in future ingestions

**5. Idempotent re-fetch:**
- Per-feature canonical hash: `sha256(canonical_json({objectid, geometry_wkt, attributes_sorted}))`
- Layer-level hash: hash of sorted per-feature hashes
- If layer hash matches the previous fixture, skip re-fetch and reuse cached output
- If hash differs, write a new fixture and proceed with ingestion

**6. ArcGIS error envelope handling:**
- ArcGIS returns HTTP 200 with `{error: {code, message, details}}` for many transient and permanent failures
- After fetch: if response has `error` key, branch on `error.code`:
  - Transient (500, 504, 504001): retry with exponential backoff (max 3 retries)
  - Permanent (400, 4xx range): hard-fail with the error message
- Plain HTTP errors (5xx, network errors): retry with exponential backoff
- Empty `features: []` is valid only if `returnCountOnly` confirmed 0 — otherwise hard-fail (likely pagination bug)

**7. Throttling and identification:**
- 1 request per 500ms to `fwp-gis.mt.gov` (configurable; rate limits aren't documented but politeness is operational hygiene)
- `User-Agent: HuntReady-Ingestion/1.0 (contact: nick@rowdycloud.io)` so FWP can reach us if needed

**8. Helper: GeoJSON → Shapely → MultiPolygon → WKT pipeline:**
- The library exposes `geojson_to_multipolygon_wkt(feature) -> str` that:
  1. Parse GeoJSON geometry via `shapely.geometry.shape(...)`
  2. Run `shapely.make_valid()`
  3. Type-prune: if result is `Polygon` → wrap in `MultiPolygon([poly])`; if `MultiPolygon` → use as-is; if `GeometryCollection` → filter to polygonal members, union, wrap; if empty/zero-area → raise (do not insert silently)
  4. Return WKT string
- Per [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), partial extractions that lose meaning are flagged loudly, never silently committed.

**Source citation shape for ArcGIS layers (used by S02.2-S02.5):**
```python
SourceCitation(
    id=f"mt-fwp-arcgis-{service}-{layer_id}-{license_year}",
    agency="Montana Fish, Wildlife & Parks",
    title=f"{layer_metadata['name']} (Layer {layer_id})",
    url=f"{service_url}/{layer_id}",
    publication_date=layer_metadata.get("editingInfo", {}).get("lastEditDate") or fetch_date,
    document_type="gis_layer",  # requires S02.0 enum extension
    supersedes=None,
    page_reference=None,
)
```

**Relevant ADRs:** [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md). **Depends on:** S02.0.

**Acceptance Criteria:**

- [ ] `ingestion/ingestion/lib/arcgis.py` exists with documented public API
- [ ] Layer metadata fetcher captures `<service>-<layer>-metadata-<timestamp>.json` fixtures
- [ ] Paginated feature fetcher uses `orderByFields`, `exceededTransferLimit`, layer-discovered `maxRecordCount`
- [ ] `outFields` populated explicitly from layer metadata (not `*`)
- [ ] Coordinate-range sanity check (Montana bounds) hard-fails on Web Mercator coordinates returned with EPSG:4326 header
- [ ] Per-feature canonical hash + layer-level hash for idempotency
- [ ] Source fixture capture (metadata + features) committed
- [ ] ArcGIS error envelope handling with retry policy
- [ ] Throttling at ≤1 req/500ms with custom User-Agent
- [ ] `geojson_to_multipolygon_wkt(feature)` helper with type-pruning + make_valid
- [ ] Helper for `SourceCitation` construction with `document_type='gis_layer'`
- [ ] `ruff check ingestion/`, `mypy ingestion/ingestion/lib/arcgis.py` pass
- [ ] Unit tests cover: pagination boundary (N×maxRecordCount), error envelope, reprojection fallback, type-prune
- [ ] No imports from state adapters; no Montana-specific code

---

### S02.2: Hunting District ingestion — Antelope (#3), Black Bear (#10), Deer/Elk/Lion (#11)

**As a** developer loading Montana HDs
**I want** all V1-relevant hunting-district geometries written to `geometry` with proper provenance and validity
**So that** spatial queries can identify the HD for any Montana coordinate

**UAT: no**

**Context:**

Endpoint: `https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer`

Layers to ingest (all `kind = 'hunting_district'`):

| Layer ID | Name | License year source | ID derivation |
|---|---|---|---|
| #3 | Antelope Hunting Districts | Field-discovered from metadata; if `REGYEAR` exists use that, else NULL | `MT-HD-antelope-{DISTRICT}-geom` (or layer-specific ID field) |
| #10 | Black Bear Hunting Districts | Same | `MT-HD-bear-{DISTRICT}-geom` |
| #11 | Deer Elk Lion Hunting Districts | `REGYEAR` field present (verified) — use it | `MT-HD-deer-elk-lion-{DISTRICT}-geom` |

**Important kind clarification:** Layer #10 is `kind = 'hunting_district'`, NOT `'bmu'`. Per FWP nomenclature, these are "Black Bear Hunting Districts." The Montana regulation booklet calls them "Bear Management Units," but for V1 we use the GIS authority's classification. True ecological BMUs (e.g., NCDE Bear Management Units) are out of V1 scope (deferred per roadmap). The `bear_management_unit` role on `jurisdiction_binding` (E03 territory) captures the regulatory relationship without conflating the geometry's classification.

**Species-prefixed IDs:** District numbers may collide across species layers (e.g., "HD 700" in antelope layer #3 vs. deer/elk layer #11 — different polygons, same number). Include the species class in the deterministic ID.

**Per-feature processing:**
1. Fetch via `arcgis.fetch_layer(service, layer_id)` (S02.1's helper)
2. For each feature:
   - Extract identity field per layer metadata (`DISTRICT` for #11; verify field name for #3, #10 from metadata fixture)
   - Convert GeoJSON geometry to MultiPolygon WKT via `arcgis.geojson_to_multipolygon_wkt()` (S02.1's helper)
   - Construct `Geometry` Pydantic instance with deterministic `id`, `name` from feature attributes, `kind='hunting_district'`, `geom=wkt`, `state='US-MT'`, `license_year=REGYEAR or None`, `source=` ArcGIS SourceCitation (S02.1's helper), `verbatim_rule=` from `REG` field if present (else `None`)
   - Insert via `INSERT ... ON CONFLICT (id) DO UPDATE SET geom = EXCLUDED.geom, name = EXCLUDED.name, source = EXCLUDED.source, license_year = EXCLUDED.license_year, verbatim_rule = EXCLUDED.verbatim_rule`
3. Verify post-batch: at least one row in `geometry` for each layer; multi-part HD verification (see AC)

**Field discovery:** Layer metadata fixtures from S02.1 reveal actual field names. Story execution must verify field names per layer (#3 and #10 are unverified in research) before assuming `DISTRICT`. Fail loudly if expected fields are absent.

**Idempotency via UPSERT:** Re-running picks up upstream corrections. Orphan detection (rows in DB no longer in source) is deferred to S02.6.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md) (MultiPolygon commitment).

**Depends on:** S02.0, S02.1.

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/load_hds.py` (or equivalent) exists
- [ ] All three layers (#3, #10, #11) ingest without errors
- [ ] Every row's `kind = 'hunting_district'` (none `'bmu'`)
- [ ] `id` follows the species-prefixed pattern; no collisions between layers
- [ ] `geom` is `geography(MultiPolygon, 4326)` — verify by `SELECT ST_GeometryType(geom::geometry) FROM geometry WHERE kind='hunting_district'` returns only `ST_MultiPolygon`
- [ ] At least one row has `ST_NumGeometries(geom::geometry) > 1` (multi-part HD verification — Montana HDs along state lines)
- [ ] All rows pass `ST_IsValid(geom::geometry)` post-insert
- [ ] `source` is a populated `SourceCitation` with `document_type='gis_layer'`
- [ ] `license_year = 2026` for layer #11 (from `REGYEAR`); NULL or 2026 for #3, #10 per metadata
- [ ] `verbatim_rule` populated from `REG` field for #11; NULL where source field is absent
- [ ] UPSERT semantics confirmed: re-running the load produces identical state (same row count, no duplicates)
- [ ] Pre-S02.0 + S02.1 metadata fixtures committed for #3, #10, #11

---

### S02.3: Portions ingestion — Antelope (#4), Mule Deer (#12), Whitetail (#13), Elk (#14)

**As a** developer loading Montana Portions
**I want** all V1 species' Portion geometries loaded with parent-HD identity preserved
**So that** the overlay fixture (S02.6) can correctly relate Portions to their parent HDs

**UAT: no**

**Context:**

Endpoint: `https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer`

Layers to ingest (all `kind = 'portion'`):

| Layer ID | Name | Identity fields (verify from metadata) |
|---|---|---|
| #4 | Antelope Portions | TBD from metadata fixture |
| #12 | Deer Portions – Mule Deer | TBD from metadata fixture |
| #13 | Deer Portions – White-tailed Deer | TBD from metadata fixture |
| #14 | Elk Portions | `DISTRICT`, `PORTIONNAME`, `PORTIONTYPE`, `SHAPECODE`, `REG`, `REGYEAR` (verified in research) |

**ID derivation:** `MT-HD-{species}-{DISTRICT}-portion-{SHAPECODE_or_PORTIONNAME_slug}-geom`. For layer #14 with verified fields: `MT-HD-elk-262-portion-{SHAPECODE}-geom`. Fail loudly if neither SHAPECODE nor unique PORTIONNAME yields collision-free IDs within a layer.

**Same processing pattern as S02.2** (S02.1 helpers, MultiPolygon WKT, UPSERT, verbatim_rule from REG, license_year from REGYEAR).

**Relevant ADRs:** Same as S02.2.

**Depends on:** S02.0, S02.1.

**Acceptance Criteria:**

- [ ] All four layers (#4, #12, #13, #14) ingest without errors
- [ ] Every row's `kind = 'portion'`
- [ ] `id` collision-free within each layer; species-prefixed
- [ ] All geometries are MultiPolygon, valid, in WGS84
- [ ] `verbatim_rule` populated from `REG` for #14; NULL where absent
- [ ] `source.document_type = 'gis_layer'`
- [ ] UPSERT semantics confirmed
- [ ] Layer metadata fixtures committed for #4, #12, #13, #14

---

### S02.4: Restricted Areas with verbatim text — Big Game (#2), Elk (#15)

**As a** developer loading Montana restricted-area boundaries
**I want** restricted-area geometries loaded with the regulatory text from `REG`/`COMMENTS` fields preserved verbatim
**So that** E03 can attach those rules to regulation_records via jurisdiction_binding without paraphrasing

**UAT: no**

**Context:**

Endpoint: `https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer`

Layers to ingest (all `kind = 'restricted_area'`):

| Layer ID | Name | Identity / verbatim fields |
|---|---|---|
| #2 | Big Game Restricted Areas | `PORTIONNAME`, `REG`, `COMMENTS`, `AREA_AC/KM/MI` (verified in research) |
| #15 | Elk Restricted Areas | TBD from metadata fixture |

**Verbatim text:** Layer #2 carries both `REG` and `COMMENTS`. Per ADR-008, both must be preserved verbatim. The schema (S02.0) adds `geometry.verbatim_rule` for this. If both fields are populated and they differ, concatenate as `f"{REG}\n\n{COMMENTS}"` (with a documented separator) — do not silently drop either. This is the cleanest fit given current schema; if the two fields prove to need separate semantic handling, defer to a future ADR.

**Drop denormalized fields:** `AREA_AC`, `AREA_KM`, `AREA_MI` are pre-computed in the source. PostGIS computes `ST_Area(geom)` on demand. Do not store these — single source of truth.

**ID derivation:** `MT-restricted-bigame-{PORTIONNAME_slug}-geom` for #2; `MT-restricted-elk-{identity}-geom` for #15.

**Relevant ADRs:** [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-001](../../adrs/ADR-001-authority-preserved.md).

**Depends on:** S02.0, S02.1.

**Acceptance Criteria:**

- [ ] Both layers (#2, #15) ingest without errors
- [ ] Every row's `kind = 'restricted_area'`
- [ ] `verbatim_rule` populated from `REG` (and `COMMENTS` concatenated where present and distinct)
- [ ] No `AREA_*` fields stored as columns; areas computed via `ST_Area` on demand
- [ ] All geometries are MultiPolygon, valid, in WGS84
- [ ] Layer metadata fixtures committed for #2, #15
- [ ] If `REG` or `COMMENTS` is empty/whitespace, `verbatim_rule = NULL` (not empty string)

---

### S02.5: CWD zone discovery and ingestion

**As a** developer ensuring Montana CWD management zones are queryable
**I want** CWD zone geometries loaded if they exist as a GIS layer, or the gap explicitly documented if they don't
**So that** E03 can correctly bind CWD reporting obligations to spatial regions

**UAT: yes** — spot-check a known CWD zone (e.g., Libby CWD Management Zone) appears in the database and contains expected coordinates.

**Context:**

The verified research doc does NOT enumerate a clear CWD-zone layer in `admbnd/huntingDistricts`. Three plausible sources:

1. **Filtered subset of layer #2** (Big Game Restricted Areas) by `COMMENTS ILIKE '%CWD%' OR PORTIONNAME ILIKE '%chronic wasting%' OR REG ILIKE '%CWD%'`
2. **A separate MapServer or service** not catalogued in the research (search the root catalog at `https://fwp-gis.mt.gov/arcgis/rest/services?f=json` for layers matching `cwd|chronic`)
3. **Only available in the Legal Descriptions PDF** (E03 territory — would mean E02 can't ingest CWD zones at all)

**Investigation steps (story execution sequence):**
1. Query `https://fwp-gis.mt.gov/arcgis/rest/services?f=json` for any service or layer matching `cwd|chronic|disease|wasting` (case-insensitive)
2. Search Hub catalog at `https://gis-mtfwp.hub.arcgis.com/api/v3/...?q=cwd`
3. If neither yields a clear standalone CWD layer, query layer #2 (already loaded by S02.4) with the discriminator filter above. If matches found, classify those rows as CWD: update their `kind` from `'restricted_area'` to `'cwd_zone'`.
4. If still no GIS source, document the gap in the epic file and defer to E03 (Legal Descriptions PDF).

**Fallback decision tree:**
- ✅ GIS source found (standalone or filtered): ingest with `kind = 'cwd_zone'`. UAT spot-check Libby zone.
- ❌ No GIS source: document in epic "Deferred items" and add a note to the E03 plan that CWD zones must be hand-traced from the Legal Descriptions PDF or manually defined. Do NOT block the epic.

**Relevant ADRs:** Same as S02.2.

**Depends on:** S02.0, S02.1, S02.4 (if filtering layer #2).

**Acceptance Criteria:**

- [ ] Investigation report committed to `ingestion/states/montana/cwd-source-discovery.md` documenting which path was taken
- [ ] If GIS source found: at least one row in `geometry` with `kind='cwd_zone'`
- [ ] **UAT:** Libby CWD Management Zone (or equivalent named zone) is queryable; `ST_Covers(libby_geom, ST_GeogFromText('POINT(<known coordinate>)'))` returns true
- [ ] If no GIS source: epic file's "Deferred items" section updated with handoff to E03; no `cwd_zone` rows written
- [ ] Layer metadata fixture committed (if a layer was found)

---

### S02.6: Geometry overlay fixture

**As a** developer producing a handoff artifact for E03
**I want** a geometry overlay fixture capturing every spatial relationship between V1 geometries
**So that** E03 can populate `jurisdiction_binding` rows once `regulation_record` rows exist, without re-running PostGIS spatial computation

**UAT: yes** — visual spot-check that expected relationships appear in the fixture (e.g., HD-262 contains its expected Elk Portion, intersects its CWD zone, etc.).

**Context:**

This story replaces the PRD's "jurisdiction_binding rows" deliverable. The schema cannot accept binding rows without regulation_records (E03 territory). Instead, E02 produces a JSON fixture capturing the spatial topology that E03 will consume.

**Critical PostGIS gotcha:** `ST_Contains` and `ST_Overlaps` do **not** exist for `geography` type. Use `ST_Covers` (semantically `Contains`-with-boundary-included) and `ST_Intersects`. For partial-overlap detection, cast to `geometry`: `ST_Covers(a.geom::geometry, b.geom::geometry)` etc. Containment is a topological property invariant to projection, so the cast is safe for relationship tests on Montana-scale polygons. (For *area-ratio* computation with the cast, document that distances/areas are planar approximations — but area-ratio is not part of this story.)

**Computation pattern (per relationship type):**

```sql
-- HD → Portion (containment)
SELECT a.id AS parent, b.id AS child,
       a.kind AS parent_kind, b.kind AS child_kind,
       'covers'::text AS relationship
FROM geometry a, geometry b
WHERE a.kind = 'hunting_district' AND b.kind = 'portion'
  AND a.geom::geometry && b.geom::geometry           -- GiST index hint
  AND ST_Covers(a.geom::geometry, b.geom::geometry);

-- HD → CWD zone (containment OR intersection)
SELECT a.id, b.id, a.kind, b.kind,
       CASE WHEN ST_Covers(a.geom::geometry, b.geom::geometry) THEN 'covers' ELSE 'intersects' END
FROM geometry a, geometry b
WHERE a.kind = 'hunting_district' AND b.kind = 'cwd_zone'
  AND a.geom::geometry && b.geom::geometry
  AND ST_Intersects(a.geom::geometry, b.geom::geometry);

-- HD → Restricted Area (similar)
-- Self-referential: HD → itself (primary_unit role)
```

**Fixture format:** `ingestion/states/montana/fixtures/geometry-overlays.json`

```json
[
  {
    "parent_geometry_id": "MT-HD-deer-elk-lion-262-geom",
    "child_geometry_id": "MT-HD-deer-elk-lion-262-geom",
    "parent_kind": "hunting_district",
    "child_kind": "hunting_district",
    "relationship": "self",
    "role_for_e03": "primary_unit"
  },
  {
    "parent_geometry_id": "MT-HD-deer-elk-lion-262-geom",
    "child_geometry_id": "MT-HD-elk-262-portion-A-geom",
    "parent_kind": "hunting_district",
    "child_kind": "portion",
    "relationship": "covers",
    "role_for_e03": "portion"
  },
  ...
]
```

**`role_for_e03` field:** Pre-computes the `jurisdiction_binding.role` value E03 should use. Mapping:

| (parent_kind, child_kind) | role_for_e03 |
|---|---|
| (hunting_district, hunting_district) | primary_unit |
| (hunting_district, portion) | portion |
| (hunting_district, cwd_zone) | cwd_management_zone |
| (hunting_district, restricted_area) | restricted_area |
| (hunting_district, bmu) | bear_management_unit (only if BMUs eventually distinct from HDs; current V1 layer #10 is `hunting_district`) |

**Coverage invariant:** Every `geometry` row written in S02.2-S02.5 must appear in the fixture either as a `parent_geometry_id` or `child_geometry_id` (the self-referential `primary_unit` row guarantees this for HDs). Top-level standalone geometries that don't relate to anything else are an error worth flagging.

**Performance:** Use `EXPLAIN ANALYZE` to verify the GiST index `geometry_geom_gix` (E01) is used via the `&&` bounding-box pre-filter. Sequential scan on this query is a bug.

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md).

**Depends on:** S02.2, S02.3, S02.4, S02.5.

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/fixtures/geometry-overlays.json` exists with at least: HD→HD self-references, HD→Portion containment, HD→Restricted Area, HD→CWD (if S02.5 produced any)
- [ ] Every relationship has `parent_geometry_id`, `child_geometry_id`, `parent_kind`, `child_kind`, `relationship` (one of: `self`, `covers`, `intersects`), and `role_for_e03` (one of the seven `GeometryRole` enum values)
- [ ] **Coverage invariant:** every row in `geometry` table appears in the fixture as parent or child of at least one relationship
- [ ] Every fixture-referenced `geometry_id` exists in the `geometry` table (FK-equivalent JSON-level validation)
- [ ] **EXPLAIN ANALYZE** on the overlay-detection queries shows `Index Scan using geometry_geom_gix` (not Seq Scan)
- [ ] **UAT:** human spot-check that known relationships appear correctly (e.g., HD-262 contains its expected Elk Portion, if data supports it)
- [ ] Generation script committed at `ingestion/states/montana/build_overlay_fixture.py`
- [ ] Fixture is reproducible — running the script produces identical JSON (sorted keys, deterministic ordering)

---

### S02.7: Spatial query verification + epic exit

**As a** developer validating that E02's geometries answer real spatial queries correctly
**I want** verification that `ST_Covers` against known Montana coordinates returns expected HDs
**So that** E03 and the eventual MCP server can rely on the spatial layer

**UAT: yes** — verify hand-picked coordinates resolve to the right HDs/Portions/Restricted Areas.

**Context:**

This is the final E02 story. No new geometries written; no new schema. Verifies what's been built.

**Verification steps:**

1. **PostGIS gotcha-checked spot-checks:** Use `ST_Covers(geom::geometry, ST_GeogFromText('POINT(<lng> <lat>)')::geometry)` (NOT `ST_Contains`, NOT geography ST_Contains which doesn't exist). For each hand-picked Montana coordinate, the expected HD/Portion/Restricted Area row is returned.

2. **Topology validity check:** `SELECT id FROM geometry WHERE NOT ST_IsValid(geom::geometry)` returns zero rows. (Note the cast — `ST_IsValid(geography)` doesn't exist.)

3. **Multi-part HD verification:** `SELECT count(*) FROM geometry WHERE kind='hunting_district' AND ST_NumGeometries(geom::geometry) > 1` returns ≥1. Confirms multi-part districts (those along state lines) survived as MultiPolygon, not collapsed.

4. **GiST index usage:** `EXPLAIN ANALYZE SELECT id FROM geometry WHERE geom::geometry && ST_MakeEnvelope(...)` shows `Index Scan using geometry_geom_gix`. Sequential scan is a bug.

5. **Reproducibility:** Wipe geometry rows; re-run `make ingest STATE=montana STAGE=geometry` (or equivalent); confirm same row count, same id set, same `geom` byte-equality.

6. **Fixture file:** `ingestion/states/montana/fixtures/spatial-test-points.json` lists 3-5 known points with expected resolutions. CI/UAT loops this fixture rather than hardcoding.

**Reproducibility documentation:** Update or add to `docs/runbooks/E02-geometry-verification.md` (parallel to E01's runbook).

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md).

**Depends on:** All prior E02 stories.

**Acceptance Criteria:**

- [ ] Spot-check fixture file `ingestion/states/montana/fixtures/spatial-test-points.json` exists with ≥3 known coordinates and expected (HD, Portion if applicable, Restricted Area if applicable, CWD zone if applicable) resolution
- [ ] **UAT:** Human verifies each fixture point resolves to the expected HD via `ST_Covers` query
- [ ] All `geometry` rows pass `ST_IsValid(geom::geometry)`
- [ ] Multi-part HD count > 0
- [ ] GiST index used (EXPLAIN ANALYZE confirms)
- [ ] Re-running ingestion produces identical state (row count, id set, geom byte-equality)
- [ ] `docs/runbooks/E02-geometry-verification.md` exists documenting verification steps
- [ ] No new schema, migration, or shared-library changes — this story only verifies and documents

---

## Exit Criteria

- [ ] All 8 stories complete (S02.0 through S02.7)
- [ ] All V1 Montana geometries loaded: HDs (#3, #10, #11), Portions (#4, #12, #13, #14), Restricted Areas (#2, #15), CWD zones (S02.5 outcome)
- [ ] All geometries pass `shapely.make_valid()` and `ST_IsValid` post-insert
- [ ] All geometries are `geography(MultiPolygon, 4326)`; multi-part HDs preserved
- [ ] `geometry-overlays.json` fixture covers every loaded geometry; ready for E03 to consume
- [ ] Schema additions (S02.0): `verbatim_rule` on geometry; `gis_layer` document_type — applied with ADRs
- [ ] Source fixtures (metadata + features) committed for every ingested layer
- [ ] Spatial queries (`ST_Covers`) against known coordinates return correct HD assignments
- [ ] Re-running ingestion is idempotent (UPSERT semantics)
- [ ] Pre-commit hooks (E01) running cleanly throughout

---

## Parallelization Notes

**Within E02: stories run sequentially** with these data dependencies:

- S02.0 → S02.1 (S02.1 needs the new `document_type='gis_layer'` value to construct SourceCitations)
- S02.1 → S02.2, S02.3, S02.4 (use the shared `arcgis` library)
- S02.4 may inform S02.5 (filtered subset of layer #2 is one CWD source)
- S02.2-S02.5 → S02.6 (overlay fixture needs all geometries loaded)
- S02.6 → S02.7 (verification depends on all prior)

**Recommended merge order:** S02.0 → S02.1 → S02.2 → S02.3 → S02.4 → S02.5 → S02.6 → S02.7

S02.2 and S02.3 are theoretically parallelizable (different layers, no shared write keys), but sequential simplifies coordination and reuses the same patterns.

---

## Deferred items (tracked for future)

These were considered during E02 planning and explicitly deferred:

- **Block Management Areas (BMA layer):** FWP refreshes BMAs mid-season; treating them as static V1 ingestion conflicts with the offline-reproducible commitment (ADR-003). Defer to a later milestone with refresh-cadence design. Tracked in [`docs/roadmap.md`](../../roadmap.md) § "Deferred from V1".
- **Multi-year geometry backfill (2025 alongside 2026):** No V1 user need ("planning *this* trip"); risks orphan geometries vs. 2026-only regulations from E03. Defer until a real user request surfaces. Tracked in [`docs/roadmap.md`](../../roadmap.md) § "Deferred from V1".
- **True ecological BMUs (NCDE-style Bear Management Units):** Distinct from FWP's Black Bear Hunting Districts (layer #10). May not exist as a standalone GIS layer in MT FWP. Defer until species-management data drives a need. Tracked in [`docs/roadmap.md`](../../roadmap.md) § "Deferred from V1".
- **Big Game Distribution layers** (`wild/bigGameDistribution/MapServer`): Context layers for "where to hunt," not regulatory boundaries. Out of V1 scope per PRD.
- **FWP Lands Locations** (`fwplnd/fwpLands/MapServer`): Access/lands context (FAS, State Parks, WMAs). Out of V1 scope per PRD.

---

## Known issues to escalate

1. **PRD 001 jurisdiction_binding sequencing error.** The PRD says E02 writes jurisdiction_binding rows; the schema's FK to regulation_record makes that impossible until E03. E02 produces a geometry overlay fixture instead. **PRD 001 should be reconciled** — proposed wording: "E02 produces all geometry rows and a geometry-overlay fixture; E03 consumes the fixture to write jurisdiction_binding rows once regulation_records exist." Flag for human approval; PM does not modify PRDs.

2. **Two ADRs needed before S02.0 can complete:**
   - ADR for `SourceCitation.document_type='gis_layer'` enum extension
   - ADR for `geometry.verbatim_rule` column addition
   PM does not write ADRs autonomously — these need a human or an explicit ADR-drafting session.

3. **CWD zone source uncertainty (S02.5).** The verified research doesn't catalog a clear CWD-zone GIS layer. Story includes a fallback path (defer to E03's Legal Descriptions PDF) but the discovery may surface findings worth documenting separately.

4. **Layer metadata field-name verification.** Research only enumerated fields for layers #2, #11, #14. Layers #3, #4, #10, #12, #13, #15 have unverified field names. S02.1's metadata fixture capture handles this defensively, but it is a real surface area for surprises.

---

## References

- [PRD 001](../../planning/prds/001-M1-montana-ingestion.md) — M1 scope, E02 phasing
- [`docs/research/montana-gis-endpoints-verified.md`](../../research/montana-gis-endpoints-verified.md) — verified ArcGIS endpoints
- [`docs/architecture.md`](../../architecture.md) — canonical schema, especially `Geometry`, `JurisdictionBinding`, `SourceCitation`
- [E01 epic](E01-schema-migrations.md) — schema, RLS, types now in place
- [`docs/runbooks/E01-migration-verification.md`](../../runbooks/E01-migration-verification.md) — migration-verification pattern, mirrored in S02.7
- [ADR-001](../../adrs/ADR-001-authority-preserved.md) — source citations required
- [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md) — offline ingestion
- [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md) — PostGIS + RLS
- [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) — language split, three-place sync
- [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md) — schema versioned, three-place sync
- [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) — verbatim text required
- [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md) — six-entity model
- [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md) — MultiPolygon commitment
