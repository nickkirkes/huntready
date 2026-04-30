# E02: Montana Geometry Ingestion

**Status:** In Progress (S02.0, S02.1 complete; S02.2 next)
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

**Status:** Complete (merged 2026-04-29, PR #18)

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

1. New migration adding `verbatim_rule text` (nullable) to `geometry`.
2. Pydantic model update: `SourceCitation.document_type: Literal[..., "gis_layer"]` and `Geometry.verbatim_rule: str | None = None`.
3. TypeScript interface update: same additions to `mcp-server/src/types/schema.ts`.
4. Architecture.md update: extend the `SourceCitation` and `Geometry` interface definitions in §"Schema types" to also cover the `'gis_layer'` enum value and the new `verbatim_rule` field. This is the audit trail for the `'gis_layer'` extension — there is no separate SQL migration for it (see below).

**Why no SQL migration for `'gis_layer'`:** Postgres *can* enforce jsonb-internal enum membership via `CHECK ((source->>'document_type') IN (...))`, but the schema as set up in E01 doesn't use such constraints anywhere — Pydantic at write time + TypeScript at compile time are the enforcement layers. Adding a CHECK constraint just for `document_type` would be a substantial scope add (apply across every entity table that has a `source` jsonb) that doesn't pay back at V1 scale. Decision: rely on type-layer enforcement; revisit if drift occurs.

**Pydantic model interaction note:** The `Geometry` model uses `model_config = ConfigDict(frozen=True, extra="forbid")`. Adding `verbatim_rule: str | None = None` is safe (additive default), but any test fixture or call site constructing `Geometry` instances must update its payloads — `extra="forbid"` rejects unknown fields, which means older callers passing only the original fields still work, but a typo like `verbatim_text` instead of `verbatim_rule` will fail loudly. No production data exists yet so this is low-risk in practice; flag in the AC.

**Three-place sync per ADR-006.** The Pydantic and TypeScript types must update in the same PR as the migration.

**No data is loaded by this story.** Verifies migration applies cleanly, types validate, all three representations match.

**Relevant ADRs:** [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md) (three-place sync), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) (verbatim text), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md) (decomposed entities).

**Acceptance Criteria:**

- [x] ADR-014 (or equivalent) drafted and accepted documenting `document_type='gis_layer'` extension (type-layer enforcement, no SQL migration)
- [x] ADR-015 (or equivalent) drafted and accepted documenting `geometry.verbatim_rule` addition AND the REG+COMMENTS handling decision in S02.4 (HuntReady-introduced `\n\n--- COMMENTS ---\n\n` separator vs. source content)
- [x] Timestamped migration in `supabase/migrations/` adds `verbatim_rule text` (nullable) to `geometry`
- [x] Pydantic `SourceCitation.document_type` Literal updated to include `"gis_layer"`
- [x] Pydantic `Geometry` model updated to include `verbatim_rule: str | None = None` (additive default; `extra="forbid"` keeps existing call sites valid; new misspellings fail loudly)
- [x] TypeScript `SourceCitation` and `Geometry` interfaces updated to match
- [x] `architecture.md` § "Schema types" updated with the new fields (this is the audit trail for the `'gis_layer'` enum extension — no SQL migration for that change)
- [x] `tsc --noEmit`, `ruff check`, `mypy` all pass
- [x] Migration applies cleanly to a fresh Supabase project after E01's migrations
- [x] No data written

---

### S02.1: ArcGIS fetch infrastructure (shared library)

**Status:** Complete (PR review passed 2026-04-29)

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
  - `where=f"{metadata.object_id_field}>=0"` (always-true, more portable than `1=1`; uses the layer's actual OID column from metadata — some ArcGIS layers use `FID`, `OBJECTID_1`, etc., not `OBJECTID`. *Earlier drafts of this epic hardcoded `OBJECTID>=0`; that was the source of a real bug caught by review on 2026-04-29 and corrected in commit 9d4961b.*)
  - `outFields=` *explicit comma-separated list from metadata*, NOT `*` (some servers truncate `*` if `excludeFromAllRequest` is set on a field)
  - `orderByFields=<objectIdField> ASC` — required for stable pagination (without this, ArcGIS may return overlapping/missing rows on page boundaries)
  - `f=geojson&outSR=4326`
  - `returnTrueCurves=false` (defensive — prevents CIRCULARSTRING geometries that GeoJSON can't represent)
  - `geometryPrecision=7` (~1cm at this latitude — canonicalizes float output for hash stability)
- Termination condition: loop until response's `exceededTransferLimit` is `false`/absent AND page is empty. **Do NOT** use "fewer than page-size returned" as the termination signal — fails at exact-N×pageSize boundaries.
- Cross-check final feature count against a separate `returnCountOnly=true` query before pagination starts. Hard-fail on discrepancy.
- Dedup by the layer's actual OID column (`metadata.object_id_field` — read from `feature["properties"][metadata.object_id_field]`, or `feature["id"]` if ArcGIS GeoJSON populated it). Same reasoning as the `where` clause: don't hardcode `OBJECTID` because layers may use `FID`, `OBJECTID_1`, etc.

**3. Spatial reference verification (do NOT trust the header):**
- ArcGIS may return Web Mercator coordinates while reporting `crs: EPSG:4326` in the GeoJSON envelope
- After fetch, sanity-check coordinate ranges. Montana lies in lon `[-116, -104]`, lat `[44, 49]`. If any geometry coordinate has `|x| > 180` or `|y| > 90`, response is in projected units regardless of what the header says. Fallback reprojection from EPSG:3857 via `pyproj.Transformer.from_crs(3857, 4326, always_xy=True)` (NOT shapely — shapely doesn't do CRS).
- **Implementation refinements (commits afe5be9, 2f0b6d5):** the simple "any out-of-range → reproject" heuristic was tightened during S02.1 build:
  - **Mixed batches refused.** ArcGIS layers serve a single CRS per layer; if some features are in WGS84 range and others are not, refuse rather than blindly reprojecting (would corrupt the in-range ones). Raise `ArcGISError` with counts and first offending OBJECTID.
  - **EPSG:3857 valid-extent pre-check.** Out-of-range inputs must additionally fit ±20037508 m (the 3857 bound at ±180°) before reprojection. Inputs beyond that are some other projected CRS (UTM, State Plane, etc.) and a 3857 transform would silently produce in-range-but-wrong WGS84 coords. Raise instead of guessing.
  - **Declared-CRS cross-check.** Read `extent.spatialReference.latestWkid` (fall back to `wkid`) from layer metadata; surface it on `LayerMetadata.spatial_reference_wkid`. When in-range coords are accepted from a non-4326-native layer, emit a WARNING — covers the residual blind spot where 3857 coords near `(0, 0)` (e.g. equator+prime meridian) fall within ±180/±90 and would otherwise pass through silently misprojected.
- **Dependency note:** `pyproj` is currently pulled transitively via `geopandas`. S02.1 imports it directly, so declare `pyproj` as a direct dependency in `ingestion/pyproject.toml` to prevent silent breakage if `geopandas` is ever removed or restructured.

**4. Source fixture capture (per PRD R2 mitigation):**
- Write two artifacts per layer per fetch:
  - `<service>-<layer_id>-metadata-<timestamp>.json` (raw layer descriptor)
  - `<service>-<layer_id>-features-<timestamp>.geojson` (raw feature collection)
- These fixtures are committed to the repo (small) and used for drift detection in future ingestions
- Rely on git history for diffs across runs — no symlinks or hash-suffix latest files (cross-platform fragility, no consumer)

**5. Per-feature change detection (NOT a skip-re-fetch optimization):**
- Per-feature canonical hash: `sha256(canonical_json({objectid, geometry_wkt, attributes_sorted}))`
- On each ingest run, compare per-feature hashes against the prior committed fixture (or against the rows already in `geometry`) and log which features changed, were added, or were removed since the last run.
- **Do NOT** skip the re-fetch on a layer-level hash match — V1 manual ingestion is rare enough that "skip if unchanged" saves seconds at most while adding maintenance surface (canonical_json correctness, shapely-version sensitivity in `geometry_wkt` output, test coverage for hash stability). Defer the layer-level hash + skip optimization until a real performance issue emerges.
- **Hash invariance caveat:** the per-feature hash includes `geometry_wkt` (shapely-canonicalized output). A `shapely` upgrade can change WKT formatting (float precision, etc.), one-time-busting every layer's hash even when source data is identical. The `geometryPrecision=7` server-side parameter mitigates but doesn't eliminate this. Document the caveat in the library so a future shapely bump doesn't trigger a false-positive "everything changed" alert.

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
  3. Type-prune:
     - if result is `Polygon` → wrap in `MultiPolygon([poly])`;
     - if `MultiPolygon` → use as-is;
     - if `GeometryCollection` → **raise loudly** with the offending feature's OBJECTID and attributes in the error message. Do NOT silently filter and union — a real ArcGIS Polygon layer that produces a GeometryCollection is a data-quality signal worth surfacing, not handling.
     - if empty/zero-area → raise (do not insert silently)
  4. Return WKT string
- Per [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), partial extractions that lose meaning are flagged loudly, never silently committed.

**Source citation shape for ArcGIS layers (used by S02.2-S02.5):**

Per [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), `publication_date` for `gis_layer` citations is **Jan 1 of REGYEAR** (the year of regulation applicability, which the caller already passes as `license_year`). `editingInfo.lastEditDate` is *not* a publication date — it is an edit timestamp that bumps on typo fixes — so it is intentionally not used for `publication_date`. It is kept on `LayerMetadata.last_edit_date_ms` for forensic value (drift detection across runs).

**`license_year` is required and must not be None** in the citation. This is distinct from `Geometry.license_year` (which is `int | None` and may be `NULL` for layers without a per-feature REGYEAR — see S02.2). The citation always carries a year because it answers "which annual regulation cycle does this evidence belong to?", a question the citation must always have an answer for. The state adapter resolves the year before constructing the citation:

```python
# In the state adapter (S02.2): one citation per feature.
license_year = feature_regyear if feature_regyear is not None else fetch_date.year

SourceCitation(
    id=f"mt-fwp-arcgis-{service}-{layer_id}-{license_year}",
    agency="Montana Fish, Wildlife & Parks",
    title=f"{layer_metadata['name']} (Layer {layer_id})",
    url=f"{service_url}/{layer_id}",
    publication_date=f"{license_year:04d}-01-01",  # ADR-014: Jan 1 of REGYEAR
    document_type="gis_layer",  # requires S02.0 type-layer extension
    supersedes=None,
    page_reference=None,
)
```

The `build_source_citation` helper enforces this contract at the type level (`license_year: int`, not `int | None`). Layers without a per-feature REGYEAR (e.g. #3 Antelope, #10 Black Bear) write `Geometry.license_year=None` for the row's regulation-applicability metadata while still providing a valid year for the citation (typically `fetch_date.year`).

> **Supersession note (2026-04-29).** Earlier drafts of this story used `editingInfo.lastEditDate → publication_date` directly. That contradicts ADR-014 (accepted 2026-04-28, after this epic was first drafted) and was corrected in commit 0e5e805. ADRs supersede story examples per [ADR-009](../../adrs/ADR-009-agentic-development-first-class.md).

**Partial dependency on S02.0:** S02.1 needs the Pydantic Literal extension (`document_type='gis_layer'`) and the `Geometry.verbatim_rule` field to typecheck and run. The `verbatim_rule` SQL migration is needed only before S02.2 inserts data. So S02.0's *type updates* (Pydantic + TypeScript) and architecture.md update can land first, unblocking S02.1 development; the migration can land in parallel as long as it's merged before S02.2 starts.

**Relevant ADRs:** [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md) (publication_date semantics). **Depends on:** S02.0.

**Acceptance Criteria:**

- [x] `ingestion/ingestion/lib/arcgis.py` exists with documented public API
- [x] `pyproj` declared as a direct dependency in `ingestion/pyproject.toml`
- [x] Layer metadata fetcher captures `<service>-<layer>-metadata-<timestamp>.json` fixtures
- [x] Paginated feature fetcher uses `orderByFields`, `exceededTransferLimit`, layer-discovered `maxRecordCount`
- [x] `outFields` populated explicitly from layer metadata (not `*`)
- [x] Coordinate-range sanity check (Montana bounds) hard-fails on Web Mercator coordinates returned with EPSG:4326 header
- [x] Per-feature canonical hash used for change-detection logging only (no layer-level skip-re-fetch optimization)
- [x] Library docstring documents shapely-version sensitivity of `geometry_wkt`-based hashes
- [x] Source fixture capture (metadata + features) committed; no symlinks or hash-suffixed latest files (write path implemented; first fixtures land in S02.2 when live MT FWP fetches run)
- [x] ArcGIS error envelope handling with retry policy (transient codes 500/504/504001 retry; permanent ArcGIS codes raise immediately; HTTP 408/429 transient with Retry-After honored up to 30s)
- [x] Throttling at ≤1 req/500ms with custom User-Agent (operator-configurable contact via `HUNTREADY_INGESTION_CONTACT` env var; no PII baked into source)
- [x] `geojson_to_multipolygon_wkt(feature)` helper raises loudly on `GeometryCollection` (with OBJECTID + attributes in the message); type-prunes `Polygon`/`MultiPolygon`; runs `shapely.make_valid` first
- [x] `SourceCitation.publication_date = f"{license_year:04d}-01-01"` per ADR-014 (NOT derived from `editingInfo.lastEditDate`)
- [x] `LayerMetadata` exposes `spatial_reference_wkid` (parsed from `extent.spatialReference.latestWkid` then `wkid`); `_check_and_fix_projection` accepts it and warns when accepting in-range coords from a non-4326-native layer
- [x] Mixed-CRS batches (some features in WGS84 range, others not) raise `ArcGISError` rather than reprojecting the in-range features
- [x] All-out-of-range batches must additionally fit ±20037508 m (EPSG:3857 valid extent) before reprojection; raise otherwise
- [x] Helper for `SourceCitation` construction with `document_type='gis_layer'`
- [x] `where` clause uses `metadata.object_id_field` (not hardcoded `OBJECTID`) so layers with non-default OID columns work
- [x] Pagination terminates on any empty page regardless of `exceededTransferLimit`; absolute iteration cap as belt-and-suspenders against pathological server responses
- [x] Geometry shape guard validates `coordinates` is a list before downstream access (raises `ArcGISError` with OID instead of bare `KeyError`/`TypeError`)
- [x] `ruff check ingestion/`, `mypy ingestion/ingestion/lib/arcgis.py` pass
- [x] Unit tests cover: pagination boundary (N×maxRecordCount), mid-page boundary, empty-page-with-exceeded-true, iteration cap, error envelope, HTTP 408/429 with Retry-After, reprojection fallback, mixed-batch refusal, EPSG:3857 bounds pre-check, declared-CRS warning, type-prune, GeometryCollection-raises, missing/null/non-list coordinates, publication_date is Jan 1 of license_year (not lastEditDate), User-Agent has no PII when env unset
- [x] No imports from state adapters; no Montana-specific code

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

**State-adapter import path:** State adapters at `ingestion/states/montana/...` need to import the shared library at `ingestion/ingestion/lib/arcgis.py`. The exact mechanism (top-level package vs. `__init__.py` in `ingestion/states/`, or relative-path tricks via `pyproject.toml` package configuration) was settled in E01 for `ingestion/ingestion/lib/schema.py` consumption, but `ingestion/states/` was empty during E01. **AC: confirm the import path works (`from ingestion.lib.arcgis import ...` or whatever pattern E01 settled on) and document the resolution in `ingestion/states/montana/README.md` or in this story's runbook section.**

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md) (MultiPolygon commitment).

**Depends on:** S02.0, S02.1.

**Acceptance Criteria:**

- [x] `ingestion/states/montana/load_hds.py` (or equivalent) exists
- [x] State-adapter import path works and is documented (`from ingestion.lib.arcgis import ...` or settled equivalent) — see [`ingestion/states/montana/README.md`](../../../ingestion/states/montana/README.md)
- [x] All three layers (#3, #10, #11) ingest without errors — 61 + 35 + 139 = 235 HDs loaded 2026-04-30
- [x] Every row's `kind = 'hunting_district'` (none `'bmu'`)
- [x] `id` follows the species-prefixed pattern; no collisions between layers (`MT-HD-antelope-`, `MT-HD-bear-`, `MT-HD-deer-elk-lion-`)
- [x] `geom` is `geography(MultiPolygon, 4326)` — verify by `SELECT ST_GeometryType(geom::geometry) FROM geometry WHERE kind='hunting_district'` returns only `ST_MultiPolygon`
- [x] **Named multi-part HD verification:** **`MT-HD-deer-elk-lion-690-geom` with `ST_NumGeometries = 12`** is the canonical assertion target (per `ingestion/states/montana/README.md` line 93). Reuse for S02.7's verification suite.
- [x] All rows pass `ST_IsValid(geom::geometry)` post-insert (Supabase cluster-config quirk surfaced — required `ST_GeomFromText(ST_AsText(geom), 4326)` cast; documented in `.ruckus/known-pitfalls.md`)
- [x] `source` is a populated `SourceCitation` with `document_type='gis_layer'` (per-feature construction enforced in commit `e78a1c4`)
- [x] `license_year` matches the source's `REGYEAR` field for each row — `Geometry.license_year` is REGYEAR-or-NULL; `SourceCitation.license_year` falls back to `fetch_year` when REGYEAR is absent (so the citation always has an annual cycle, while the geometry can stay year-invariant). Per-feature enforcement in commit `e78a1c4`.
- [x] `verbatim_rule` populated from `REG` field for #11; NULL where source field is absent (`_extract_verbatim_rule` in `load_hds.py`)
- [x] UPSERT semantics confirmed: re-running the load produces identical state (same row count, no duplicates) — `ingestion/ingestion/lib/db.py::upsert_geometries` plus 186 lines of `tests/test_db.py`
- [x] Layer metadata fixtures committed for #3, #10, #11 at `ingestion/states/montana/fixtures/huntingDistricts-{3,10,11}-metadata-*.json` (~7KB each). Feature fixtures (`*-features-*.geojson`) are local-only — gitignored due to ~180MB-per-run size; see "Known issues to escalate" item 6.

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

- [x] All four layers (#4, #12, #13, #14) ingest without errors — 4 + 11 + 13 + 27 = 55 portions loaded 2026-04-30
- [x] Every row's `kind = 'portion'`
- [x] `id` collision-free within each layer; species-prefixed (`MT-HD-antelope-`, `MT-HD-mule-deer-`, `MT-HD-whitetail-`, `MT-HD-elk-`). Layer-wide slug strategy (SHAPECODE preferred, slugified PORTIONNAME fallback) handles real SHAPECODE collisions in layer #12 (commit `ed2a05c`); pre-upsert collision check fails loud listing up to 5 duplicates.
- [x] All geometries are MultiPolygon, valid, in WGS84 (via `arcgis.geojson_to_multipolygon_wkt` + `make_valid`)
- [x] `verbatim_rule` populated from `REG` for #14; NULL where absent (`_extract_verbatim_rule` mirrors S02.2's `load_hds.py` pattern)
- [x] `source.document_type = 'gis_layer'` (per-feature `SourceCitation` construction with REGYEAR-derived `publication_date`)
- [x] UPSERT semantics confirmed via shared `ingestion/ingestion/lib/db.py::upsert_geometries` plus 661 lines of `tests/test_load_portions.py`
- [x] Layer metadata fixtures committed for #4, #12, #13, #14 at `ingestion/states/montana/fixtures/huntingDistricts-{4,12,13,14}-metadata-*.json` (~7KB each). Feature fixtures (`*-features-*.geojson`) are local-only — gitignored at `ingestion/states/montana/fixtures/.gitignore` because real MT data is ~180MB per run, ~3 orders of magnitude over the original "small fixtures" assumption in S02.1's spec. See "Known issues to escalate" item 6.

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

**Verbatim text:** Layer #2 carries both `REG` and `COMMENTS`. Per ADR-008, both must be preserved verbatim. The schema (S02.0) adds `geometry.verbatim_rule` for this.

**Combination rule (covered by ADR-015 scope):**

| `REG` | `COMMENTS` | `verbatim_rule` value |
|---|---|---|
| populated | populated, different from `REG` | `f"{REG}\n\n--- COMMENTS ---\n\n{COMMENTS}"` |
| populated | populated, identical to `REG` | `REG` (don't double-store the same string) |
| populated | empty/whitespace | `REG` |
| empty/whitespace | populated | `COMMENTS` |
| empty/whitespace | empty/whitespace | `NULL` |

**Separator is HuntReady-introduced delimiter, not source content.** The `\n\n--- COMMENTS ---\n\n` token is a deliberate editorial choice — pure concatenation (`\n\n`) was rejected because it loses the "these came from two distinct source attributes" signal that future consumers (E03 binding logic, MCP response composition) may need. The decision is captured in ADR-015 alongside the column addition; the reasoning is that ADR-008's verbatim discipline is preserved as long as the source strings themselves are not modified — only their concatenation is annotated.

**Drop denormalized fields:** `AREA_AC`, `AREA_KM`, `AREA_MI` are pre-computed in the source. PostGIS computes `ST_Area(geom)` on demand. Do not store these — single source of truth.

**ID derivation:** `MT-restricted-bigame-{PORTIONNAME_slug}-geom` for #2; `MT-restricted-elk-{identity}-geom` for #15.

**Relevant ADRs:** [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-001](../../adrs/ADR-001-authority-preserved.md).

**Depends on:** S02.0, S02.1.

**Acceptance Criteria:**

- [ ] Both layers (#2, #15) ingest without errors
- [ ] Every row's `kind = 'restricted_area'`
- [ ] `verbatim_rule` populated per the five-case combination rule above (REG only / COMMENTS only / both differ / both identical / both empty → NULL)
- [ ] When both REG and COMMENTS are populated and differ, `verbatim_rule` contains the literal separator `\n\n--- COMMENTS ---\n\n` between them
- [ ] No `AREA_*` fields stored as columns; areas computed via `ST_Area` on demand
- [ ] All geometries are MultiPolygon, valid, in WGS84
- [ ] Layer metadata fixtures committed for #2, #15
- [ ] **S02.5 coordination:** if S02.5 is using the layer-#2 exclusion-filter pattern for CWD zones, this story's load step applies the inverse (CWD-excluding) filter — see S02.5 for the exact discriminator predicate

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
3. If neither yields a clear standalone CWD layer, derive CWD zones from layer #2 (Big Game Restricted Areas) using the **exclusion-filter pattern** (see below)
4. If layer #2 contains no CWD-pattern rows, fall back to the **hand-traced GeoJSON path** (see below) — this preserves M1 success criterion 3 and avoids handing the work to E03 mid-stream

**Exclusion-filter pattern (resolves S02.4↔S02.5 idempotency hole):**

The naive approach — let S02.4 ingest layer #2 as `restricted_area`, then have S02.5 mutate matching rows to `cwd_zone` — has an idempotency hole: re-running S02.4 reverts the kind via UPSERT. The clean fix is for S02.4 and S02.5 to share a discriminator predicate over layer #2 and apply mutually exclusive filters:

- **Discriminator predicate:** `COMMENTS ILIKE '%CWD%' OR PORTIONNAME ILIKE '%chronic wasting%' OR REG ILIKE '%CWD%'` (case-insensitive). Implementation lives in `ingestion/states/montana/cwd_discriminator.py` (or equivalent) so both stories import the same predicate.
- **S02.4's filter:** ingests layer #2 rows that DO NOT match the discriminator → `kind='restricted_area'`
- **S02.5's filter:** ingests layer #2 rows that DO match the discriminator → `kind='cwd_zone'`
- Each row is written exactly once. Re-running either story is idempotent. No row carries the wrong `kind` after any sequence of runs.

**Hand-traced GeoJSON fallback** (when neither a standalone GIS layer nor layer-#2-filtered rows exist):

- Hand-trace polygons from the FWP Legal Descriptions biennial PDF (V1 publication) and from current FWP regulation pages naming each CWD Management Zone
- Check the GeoJSON into the repo at `ingestion/states/montana/cwd-zones-manual.geojson`
- Each feature's properties must include: `name` (e.g., "Libby CWD Management Zone"), `regulation_year`, `source_pdf_page`
- Ingest via the same load path as ArcGIS layers, but with a `SourceCitation` whose `agency="Montana Fish, Wildlife & Parks"`, `title="CWD Management Zones (manually traced from Legal Descriptions PDF)"`, `url=` link to the FWP regulation page or PDF, `document_type='annual_regulations'` (since we're sourcing from the published regulation), `page_reference` populated.
- All hand-traced rows get `confidence='low'` per [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) — but note: `confidence` is a regulation_record-level field (E03 territory), not a geometry-level field. Carry a `manually_traced: true` flag in the `source` jsonb's `notes` field (or equivalent additive jsonb extension) so E03 knows to assign `confidence='low'` on regulation_records that bind to these geometries.
- Hand-tracing is genuine work (not just file checking). Story execution must spec how many zones, who validates the polygons, and a UAT criterion (named zones — see below).

**Fallback decision tree (revised):**

| Scenario | Action | M1 success criterion 3 status |
|---|---|---|
| Standalone CWD MapServer/Hub layer found | Ingest with `kind='cwd_zone'`. | Met |
| Layer #2 has CWD-pattern rows (exclusion-filter path) | S02.5 ingests them with `kind='cwd_zone'`; S02.4 ingests the rest as `restricted_area`. | Met |
| Neither GIS source has CWD data | Hand-trace from PDF; check into `ingestion/states/montana/cwd-zones-manual.geojson`; ingest via same path. | Met (with documented `manually_traced` provenance) |
| Hand-tracing blocked (e.g., PDF unavailable) | Escalate to PM as a blocker on M1 success criterion 3. Do not silently defer to E03. | At risk — escalation required |

**Named CWD zones for UAT spot-check** (replaces "Libby or equivalent"):

The current FWP Black Bear booklet and Legal Descriptions PDF name several Montana CWD Management Zones. UAT must verify all three of:

1. **Libby CWD Management Zone** — Lincoln County, NW Montana. Test point ~`(48.388, -115.555)` (downtown Libby) should resolve to this zone.
2. **South-Central Montana CWD Zone** — encompassing parts of Carbon and Park counties. Test point in Carbon County interior (e.g., ~`(45.07, -109.35)`) should resolve.
3. **Northeast Montana CWD Zone** — historical hot spot in eastern HDs. Test point per current regulation document.

If the actual CWD zone names have changed by execution time (regulations are biennial; check the live booklet), substitute current names and document the substitution. The principle is "three named zones with assigned test coordinates," not "three specific historical names."

**Relevant ADRs:** Same as S02.2.

**Depends on:** S02.0, S02.1, S02.4 (if filtering layer #2).

**Acceptance Criteria:**

- [ ] Investigation report committed to `ingestion/states/montana/cwd-source-discovery.md` documenting which path was taken (standalone GIS / exclusion-filter / hand-traced) and the discriminator predicate used
- [ ] Discriminator predicate (if exclusion-filter path) lives in shared `cwd_discriminator.py` and is imported by both S02.4 and S02.5 — verified by grep that there is exactly one definition
- [ ] At least one row in `geometry` with `kind='cwd_zone'` (one of: standalone GIS layer, exclusion-filtered layer #2, or hand-traced GeoJSON)
- [ ] **UAT — three named zones must resolve correctly via `ST_Covers`:** Libby CWD Management Zone, South-Central Montana CWD Zone, and Northeast Montana CWD Zone (or current equivalents per the live FWP booklet — document any substitution and the test points used)
- [ ] If hand-traced fallback used: `ingestion/states/montana/cwd-zones-manual.geojson` exists; each feature has `name`, `regulation_year`, `source_pdf_page`; the load path tags `source` jsonb with `manually_traced: true` and a note in `cwd-source-discovery.md` describes who validated the polygons
- [ ] If GIS source found: layer metadata fixture committed
- [ ] If hand-tracing is blocked (e.g., PDF unavailable): escalate to PM as a blocker on M1 success criterion 3, NOT silent defer to E03

---

### S02.6: Geometry overlay fixture

**As a** developer producing a handoff artifact for E03
**I want** a geometry overlay fixture capturing every spatial relationship between V1 geometries
**So that** E03 can populate `jurisdiction_binding` rows once `regulation_record` rows exist, without re-running PostGIS spatial computation

**UAT: yes** — visual spot-check that expected relationships appear in the fixture (e.g., HD-262 contains its expected Elk Portion, intersects its CWD zone, etc.).

**Context:**

This story replaces the PRD's "jurisdiction_binding rows" deliverable. The schema cannot accept binding rows without regulation_records (E03 territory). Instead, E02 produces a JSON fixture capturing the spatial topology that E03 will consume.

**PostGIS operator semantics on `geography` (correction of a common misconception):**

PostGIS *does* implement `ST_Contains(geography, geography)` and `ST_Within(geography, geography)` (since 2.4), but their geography support is partial and semantically surprising at boundary-touching cases. The recommended pattern is to use `ST_Covers` and `ST_Intersects` directly on geography — both are well-supported, both are spheroid-correct, and both leverage the `geometry_geom_gix` GiST index that E01 created on the geography column.

**Critically: do NOT cast to `::geometry` in the WHERE clause.** A geography GiST index is built on the geography type; casting to geometry at query time forces materialization of the cast and the planner will not use the geography index. Earlier drafts of this epic specified `a.geom::geometry && b.geom::geometry AND ST_Covers(a.geom::geometry, b.geom::geometry)` — that pattern is wrong: `&&` is not a geography operator (so it forces the cast), and the cast loses the index. Use geography operators directly; PostGIS internally optimizes `ST_Intersects(geog, geog)` and `ST_Covers(geog, geog)` to use the geography GiST.

**Computation pattern (per relationship type):**

```sql
-- HD → Portion (containment)
SELECT a.id AS parent, b.id AS child,
       a.kind AS parent_kind, b.kind AS child_kind,
       'covers'::text AS relationship
FROM geometry a, geometry b
WHERE a.kind = 'hunting_district' AND b.kind = 'portion'
  AND ST_Covers(a.geom, b.geom);  -- geography native; uses geometry_geom_gix

-- HD → CWD zone (containment OR intersection)
SELECT a.id, b.id, a.kind, b.kind,
       CASE WHEN ST_Covers(a.geom, b.geom) THEN 'covers' ELSE 'intersects' END
FROM geometry a, geometry b
WHERE a.kind = 'hunting_district' AND b.kind = 'cwd_zone'
  AND ST_Intersects(a.geom, b.geom);  -- ST_Covers ⊂ ST_Intersects

-- HD → Restricted Area (similar to HD → CWD zone)
-- Self-referential: HD → itself (primary_unit role) — generated programmatically, no spatial query needed
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

**Coverage invariant (strengthened):**

Every `geometry` row must appear in the fixture, but the role placement depends on `kind`:

| `geometry.kind` | Required appearance in fixture |
|---|---|
| `hunting_district` | At least one `self`-relationship row with `parent_geometry_id == child_geometry_id` and `role_for_e03='primary_unit'`. Optionally: appears as `parent_geometry_id` in covers/intersects rows toward Portions, CWD zones, Restricted Areas. |
| `portion` | Appears as `child_geometry_id` in at least one `covers` relationship to a `hunting_district` parent, with `role_for_e03='portion'`. |
| `cwd_zone` | Appears as `child_geometry_id` in at least one `covers` or `intersects` relationship to a `hunting_district` parent, with `role_for_e03='cwd_management_zone'`. |
| `restricted_area` | Appears as `child_geometry_id` in at least one `covers` or `intersects` relationship to a `hunting_district` parent, with `role_for_e03='restricted_area'`. |
| `bmu` (none expected in V1 — layer #10 is `hunting_district`) | n/a |

A Portion or Restricted Area that doesn't overlap any HD is a data-quality flag worth surfacing — fail loudly during fixture build.

**Fixture schema documentation:** Commit a JSON Schema or TypedDict at `ingestion/states/montana/fixtures/geometry-overlays.schema.json` that types every field, every enum value, and the relationship-to-role mapping. E03 imports this to type-check its consumer rather than reverse-engineering the format from sample rows.

**Performance check (softened from earlier draft):** Run `EXPLAIN ANALYZE` on the overlay-detection queries and document the chosen plan in the runbook. With ~200 HDs × ~50 Portions ≈ 10K candidate pairs, sequential scan would still complete in well under a second — performance is not a V1 blocker. The point of the EXPLAIN check is to confirm the geography GiST index is reachable from `ST_Covers(geog, geog)` / `ST_Intersects(geog, geog)`, not to demand an index scan. If PostgreSQL chooses a sequential scan because the dataset is small, that is acceptable; document the choice.

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md).

**Depends on:** S02.2, S02.3, S02.4, S02.5. **Note: S02.5 may produce zero `cwd_zone` rows under the hand-traced fallback path or if the discriminator returns no matches.** S02.6 still works in that case — it produces fixture rows for HD↔HD self-references, HD→Portion, and HD→Restricted Area, with no HD→CWD entries. The coverage invariant accommodates this (CWD zones only need a binding-row "if any exist").

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/fixtures/geometry-overlays.json` exists with at least: HD→HD self-references for every `hunting_district` row, HD→Portion containment, HD→Restricted Area, HD→CWD (if S02.5 produced any)
- [ ] Every relationship has `parent_geometry_id`, `child_geometry_id`, `parent_kind`, `child_kind`, `relationship` (one of: `self`, `covers`, `intersects`), and `role_for_e03` (one of the seven `GeometryRole` enum values)
- [ ] **Fixture schema:** `ingestion/states/montana/fixtures/geometry-overlays.schema.json` (JSON Schema) committed and validates the fixture; alternatively, a TypedDict in `ingestion/ingestion/lib/overlays.py` typed for E03 import
- [ ] **Strengthened coverage invariant:**
  - Every `hunting_district` row has a self-relationship with `role_for_e03='primary_unit'`
  - Every `portion` row appears as `child_geometry_id` in ≥1 relationship to a `hunting_district` parent with `role_for_e03='portion'`
  - Every `cwd_zone` row appears as `child_geometry_id` in ≥1 relationship to a `hunting_district` parent with `role_for_e03='cwd_management_zone'`
  - Every `restricted_area` row appears as `child_geometry_id` in ≥1 relationship to a `hunting_district` parent with `role_for_e03='restricted_area'`
  - Any Portion / CWD / Restricted Area not overlapping any HD fails the build with the offending id surfaced
- [ ] Every fixture-referenced `geometry_id` exists in the `geometry` table (FK-equivalent JSON-level validation)
- [ ] **EXPLAIN ANALYZE plan documented in the runbook** (S02.7's runbook). The point is to verify the geography GiST index is reachable; an Index Scan is preferred but a Seq Scan on this small dataset is acceptable if documented. Sequential scan is NOT automatically a bug.
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

1. **Spot-checks via `ST_Covers` on geography (NOT `::geometry` cast):** Use `ST_Covers(geom, ST_GeogFromText('SRID=4326;POINT(<lng> <lat>)'))` to test point-in-polygon. (`ST_Contains(geography, geography)` does exist in PostGIS 2.4+ but its support is partial and semantically surprising at boundary-touching points; `ST_Covers` is the recommended predicate.) For each hand-picked Montana coordinate in the fixture, the expected HD/Portion/Restricted Area row is returned.

2. **Topology validity check:** `SELECT id FROM geometry WHERE NOT ST_IsValid(geom::geometry)` returns zero rows. (`ST_IsValid` is geometry-only; the cast is required here. The geography column already enforces lon/lat bounds at insert time, so this catches topology issues like self-intersection that survived `make_valid`.)

3. **Multi-part HD verification (named):** Use the same named multi-part HD identified in S02.2's AC — `SELECT id, ST_NumGeometries(geom::geometry) FROM geometry WHERE id = '<that HD id>'` returns `> 1`. The named HD is the load-bearing test; aggregate counts elsewhere are supportive but not sufficient.

4. **Geography GiST index reachability check:** Run `EXPLAIN ANALYZE` on a representative point-in-polygon query (`SELECT id FROM geometry WHERE ST_Covers(geom, ST_GeogFromText('SRID=4326;POINT(...)'))`) and document the chosen plan in the runbook. Index Scan via `geometry_geom_gix` is preferred; a Seq Scan on this small dataset is acceptable as long as the index would be reachable on a larger one (i.e., the predicate is index-eligible, the planner chose Seq Scan for cost reasons). Bug case: predicate forces a cast or function call that prevents index use.

5. **Reproducibility (topological, not byte-level):** Wipe geometry rows; re-run `make ingest STATE=montana STAGE=geometry` (or equivalent); confirm same row count, same id set, AND for every id, `ST_Equals(reloaded.geom, prior.geom) = true`. (`ST_Equals` works directly on geography.) If a hash-based comparison is preferred over a row-by-row predicate, cast to geometry first: `md5(ST_AsBinary(ST_Normalize(geom::geometry)))` — `ST_Normalize` is geometry-only, so the cast is required. Byte-level equality of the raw `geom` value is NOT a valid test — `geography(MultiPolygon, 4326)` round-trips through canonicalization that can produce different EWKB bytes for topologically identical geometries (ring ordering, vertex ordering after `make_valid`, etc.).

6. **Fixture file:** `ingestion/states/montana/fixtures/spatial-test-points.json` lists ≥1 named test point per `kind` value present in `geometry` (HD, Portion, Restricted Area, CWD zone if any). Each entry: `{name, lat, lng, expected_kind, expected_id_pattern, expected_role_for_e03}`. CI/UAT loops this fixture rather than hardcoding lat/lng in test code.

**Reproducibility documentation:** Update or add to `docs/runbooks/E02-geometry-verification.md` (parallel to E01's runbook). Include a runbook note: *the wipe + re-ingest pattern works in E02 standalone because nothing yet FK-references `geometry`. Once E03 lands and `jurisdiction_binding` rows reference `geometry.id`, the wipe step will require coordinated handling (DELETE CASCADE or sequenced delete from `jurisdiction_binding` first). This pattern is E02-only.*

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md).

**Depends on:** All prior E02 stories.

**Acceptance Criteria:**

- [ ] Spot-check fixture file `ingestion/states/montana/fixtures/spatial-test-points.json` exists with ≥1 named test point per `kind` present in `geometry` (HD, Portion, Restricted Area, CWD zone if any). Each entry has `{name, lat, lng, expected_kind, expected_id_pattern, expected_role_for_e03}`.
- [ ] **UAT:** Human verifies each fixture point resolves correctly via `ST_Covers(geom, ST_GeogFromText(...))`
- [ ] All `geometry` rows pass `ST_IsValid(geom::geometry)`
- [ ] **Named multi-part HD** (the same one identified in S02.2's AC) returns `ST_NumGeometries(geom::geometry) > 1`
- [ ] EXPLAIN ANALYZE plan documented in the runbook for both a point-in-polygon query and an overlay-detection query; predicate is index-eligible (Seq Scan on small dataset is acceptable if documented)
- [ ] Re-running ingestion is reproducible: row count, id set, and `ST_Equals(reloaded.geom, prior.geom) = true` for every id (NOT byte-equality; `ST_Equals` or `md5(ST_AsBinary(ST_Normalize(geom)))` is the right test)
- [ ] `docs/runbooks/E02-geometry-verification.md` exists, includes the wipe-and-re-ingest pattern note (E02-only; once E03 lands, this requires coordinated delete from `jurisdiction_binding` first)
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

S02.2, S02.3, and S02.4 are genuinely parallelizable: different layers, disjoint id prefixes, no shared write keys. Sequential is the default because it simplifies branch coordination and reuses the same loading patterns; **parallel is acceptable if branch-management cost is low.** S02.4 and S02.5 share a discriminator predicate (the CWD exclusion-filter), so coordinate the predicate definition before either starts.

S02.1's *type updates* (Pydantic + TypeScript) from S02.0 are needed for compile; the SQL migration from S02.0 is needed only before S02.2 inserts data. So S02.1 can begin development as soon as S02.0's type-layer changes land — the migration can land in parallel.

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

3. **CWD zone source uncertainty (S02.5).** The verified research doesn't catalog a clear CWD-zone GIS layer. Story includes a hand-traced GeoJSON fallback path that preserves M1 success criterion 3, but the discovery may surface findings worth documenting separately.

4. **Layer metadata field-name verification.** Research only enumerated fields for layers #2, #11, #14. Layers #3, #4, #10, #12, #13, #15 have unverified field names. S02.1's metadata fixture capture handles this defensively, but it is a real surface area for surprises.

5. **PostGIS operator semantics on `geography` type.** The S02.6 query patterns rely on `ST_Covers(geog, geog)` and `ST_Intersects(geog, geog)` using the `geometry_geom_gix` GiST index. PostgreSQL's planner choices on small datasets can vary, and `ST_Contains(geography, geography)` exists but with partial/surprising semantics. Before locking the S02.6 query patterns, run `EXPLAIN ANALYZE` against actual loaded data and verify the planner does not force a cast or full sequential scan that loses index reachability. If the planner refuses the index, escalate before downstream stories assume the pattern is performant.

6. **Feature-fixture commit policy deviates from S02.1 spec.** S02.1's spec line 134 says "Source fixture capture (metadata + features) committed; no symlinks or hash-suffixed latest files" under the assumption that fixtures would be small. Real MT FWP feature payloads are ~180MB per run (51 + 38 + 90 MB across layers #3, #10, #11; portions add tens of MB more). S02.2 surfaced this and added `ingestion/states/montana/fixtures/.gitignore` excluding `*-features-*.geojson` while keeping metadata files committed (~7KB each, sufficient for field-name and OID-column drift detection). **Decision needed before E02 closes:** adopt one of git-lfs, object-store + manifest, or sampling for feature-fixture preservation. Until then, drift detection on actual feature data depends on local fixture corpora that are not shared. The metadata-only commit pattern is documented in the gitignore.

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
