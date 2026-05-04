# E02: Montana Geometry Ingestion

**Status:** Complete
**Milestone:** M1 — Montana Ingestion
**Dependencies:** E01 (complete, merged 2026-04-28)
**Validated:** 2026-04-28
**Completed:** 2026-05-03 (all 8 stories merged S02.0 → S02.7; Montana geometry layer fully ingested at 349 rows; overlay fixture + audit log + spatial verification suite + drift-detection manifests in place; runbook at `docs/runbooks/E02-geometry-verification.md`)
**Audited:** 2026-05-03 — see [E02-audit.md](E02-audit.md). 89 ACs total: **86 MET, 3 PARTIAL, 0 NOT MET.** All 3 partials were P3 cosmetic findings (dead `MT_FWP_HOST` constant in shared library, asymmetric atomic-write between fixture writers, stale Kalispell OBJECTID); all addressed in commit `0093e88`. Epic ships clean.
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

- [x] Both layers (#2, #15) ingest without errors — 53 + 4 = 57 rows loaded 2026-04-30 (live load `b1646db`)
- [x] Every row's `kind = 'restricted_area'`
- [x] `verbatim_rule` populated per the five-case combination rule above (REG only / COMMENTS only / both differ / both identical / both empty → NULL) — implemented in `_extract_verbatim_rule_combined` in `load_restricted_areas.py`
- [x] When both REG and COMMENTS are populated and differ, `verbatim_rule` contains the literal separator `\n\n--- COMMENTS ---\n\n` between them — 55 of 57 rows exercise this branch
- [x] No `AREA_*` fields stored as columns; areas computed via `ST_Area` on demand
- [x] All geometries are MultiPolygon, valid, in WGS84 — 100% geometry validity confirmed during live load
- [x] Layer metadata fixtures committed for #2, #15 at `ingestion/states/montana/fixtures/huntingDistricts-{2,15}-metadata-*.json`
- [x] **S02.5 coordination:** shared discriminator predicate at `ingestion/states/montana/cwd_discriminator.py::is_cwd_feature` — imported by both stories; S02.4 applies `not is_cwd_feature(...)` over layer #2's features. **Empirical finding from live load:** layer #2 carries 0 CWD-matching rows; S02.5 cannot derive CWD zones from layer #2 and must fall back to the Hub-catalog or hand-traced paths described in S02.5's investigation tree.

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

- [x] Investigation report committed to `ingestion/states/montana/cwd-source-discovery.md` (189 lines) — Path A (standalone GIS layer) taken. All four investigation paths exercised and documented: root catalog scan of every fwp-gis.mt.gov folder confirmed zero CWD services there; Hub catalog query on arcgis.com/sharing/rest/search surfaced the `Chronic Wasting Disease Hunt Areas` Feature Service (ArcGIS Online item `8837c07298054f5e8be2e072681d870c`) at `https://services3.arcgis.com/Cdxz8r11hT0MGzg1/arcgis/rest/services/ADMBND_HD_CWD/FeatureServer`.
- [x] Discriminator predicate path NOT taken (Path A made it unnecessary), but the shared `ingestion/states/montana/cwd_discriminator.py::is_cwd_feature` from S02.4 is still the single definition (`grep -r "def is_cwd_feature" ingestion/` returns exactly one line).
- [x] 2 rows in `geometry` with `kind='cwd_zone'` — Libby CWD Management Zone (OBJECTID 967) and Kalispell CWD Management Zone (OBJECTID 968). Live load 2026-05-01 (`6fdb11b`); idempotency confirmed by 2nd run with identical row counts.
- [x] **UAT — named zones resolve correctly via `ST_Covers`:** **Spec substitution acknowledged and documented** in `cwd-source-discovery.md`. The 2026 FWP CWD layer publishes only 2 zones, not 3. Per the story spec's explicit permission ("substitute current names and document the substitution"), UAT covers: Libby CWD Management Zone (positive at `-115.555, 48.388` → PASS); Kalispell CWD Management Zone (positive); and an outside-zone negative-control point in eastern Montana (`-106.500, 46.800` → 0 features returned, PASS). The principle "named zones with assigned test coordinates" is preserved with positive + negative `ST_Covers` semantics exercised on the same dataset.
- [x] Hand-traced fallback NOT used — N/A (Path A succeeded; no `cwd-zones-manual.geojson` written)
- [x] **GIS source found — layer metadata fixture committed** at `ingestion/states/montana/fixtures/ADMBND_HD_CWD-0-metadata-20260501T141952Z.json`
- [x] Hand-tracing not blocked — N/A

---

### S02.6: Geometry overlay fixture

**As a** developer producing a handoff artifact for E03
**I want** a geometry overlay fixture capturing every spatial relationship between V1 geometries
**So that** E03 can populate `jurisdiction_binding` rows once `regulation_record` rows exist, without re-running PostGIS spatial computation

**UAT: yes** — visual spot-check that expected relationships appear in the fixture (e.g., HD-262 contains its expected Elk Portion, intersects its CWD zone, etc.).

**Context:**

This story replaces the PRD's "jurisdiction_binding rows" deliverable. The schema cannot accept binding rows without regulation_records (E03 territory). Instead, E02 produces a JSON fixture capturing the spatial topology that E03 will consume.

**Computation pattern: local shapely with area-ratio discriminator.**

Earlier drafts of this story prescribed a PostGIS cross-join (`SELECT … FROM geometry a, geometry b WHERE ST_Covers(a.geom, b.geom)`) for the spatial work. That approach has two problems on real Montana data, both confirmed during S02.6 implementation:

1. **Supabase's role-locked 2-min `statement_timeout` aborts the cross-join.** Even with the planner correctly using `geometry_geom_gix` (a geography GiST), the per-row detoasting cost on ~113 KB MultiPolygons across ~12,000 candidate pairs exceeds the cap.
2. **Strict `ST_Covers` orphans portions due to digitization precision.** Real portion edges fall fractions of a meter outside their parent HD boundary; only 23 of 55 Montana portions pass strict containment. The remaining 32 share the edge but extend slightly past it.

S02.6 implements the spatial work locally in shapely + STRtree against a single bulk `SELECT id, kind, ST_AsText(geom) FROM geometry WHERE state = 'US-MT'` (geography-native; no `::geometry` cast — see [.roughly/known-pitfalls.md](../../../.roughly/known-pitfalls.md)). Total runtime: ~5 seconds. The relationship label comes from a three-band area-ratio threshold instead of the binary `ST_Covers`:

```python
# For each (HD, child) candidate where parent.intersects(child):
overlap_pct = parent_geom.intersection(child_geom).area / child_geom.area

if overlap_pct >= COVER_RELABEL_THRESHOLD (0.99):
    relationship = "covers"           # digitization-tolerant containment
elif overlap_pct < COVER_DROP_THRESHOLD (0.01):
    drop the row, write to audit log  # boundary-touching artifact
else:
    relationship = "intersects"       # genuine partial overlap
```

The audit log lands at `ingestion/states/montana/fixtures/geometry-overlays-dropped.json` (committed) — filtering is one-way; the audit lets a future reviewer verify nothing semantically real was discarded. The thresholds, denominator choice (`child.area`), and rejected-alternative spaces are documented in [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md).

The `restricted_area` coverage invariant carves out an **explicit allowlist** of geometry IDs that are documented no-hunt zones. V1 entries: Glacier National Park, Sun River Game Preserve, Yellowstone NP — all three are adjacent to HDs but geometrically don't overlap them. Allowlisted RA orphans surface as INFO-logged warnings; any other RA orphan blocks the build, same as portion/CWD orphans. Adding a new ID to the allowlist is a code change (`EXPECTED_RA_ORPHAN_IDS` in `build_overlay_fixture.py`) that gets the same review as any other constant. See [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md) for the rationale (incl. the explicit rejection of blanket RA tolerance, which would silently swallow real data regressions).

Self-relationship rows for each `hunting_district` are generated programmatically; no spatial computation needed.

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

**Coverage invariant:**

Every `geometry` row must appear in the kept fixture (or be explicitly tolerated as a documented edge case), keyed off `kind`:

| `geometry.kind` | Required appearance in fixture | Orphan behavior |
| --- | --- | --- |
| `hunting_district` | At least one `self`-relationship row with `parent_geometry_id == child_geometry_id` and `role_for_e03='primary_unit'`. Optionally: appears as `parent_geometry_id` in covers/intersects rows toward children. | Cannot orphan — every HD gets a self row programmatically. |
| `portion` | Appears as `child_geometry_id` in at least one `covers` or `intersects` relationship to a `hunting_district` parent, with `role_for_e03='portion'`. | Build fails loudly with offending id surfaced. |
| `cwd_zone` | Same as `portion`, `role_for_e03='cwd_management_zone'`. | Build fails loudly with offending id surfaced. |
| `restricted_area` | Same shape, `role_for_e03='restricted_area'`. | **Allowlisted orphans tolerated.** An explicit set of IDs (`EXPECTED_RA_ORPHAN_IDS`) — currently the 3 known no-hunt zones (Glacier NP, Sun River Game Preserve, Yellowstone NP) — is INFO-logged. Any other RA orphan blocks the build, same as portion/CWD orphans. See [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md). |
| `bmu` (none expected in V1 — layer #10 is `hunting_district`) | n/a | n/a |

**Fixture schema documentation:** Python `TypedDict` at `ingestion/ingestion/lib/overlays.py` (`OverlayFixtureRow` + `DroppedOverlayPair` + role mapping). E03 imports this directly. JSON Schema was rejected: codebase has no other JSON Schema usage and Python is the canonical type contract here.

**Audit log:** `ingestion/states/montana/fixtures/geometry-overlays-dropped.json`. Captures every HD↔child pair filtered out by `COVER_DROP_THRESHOLD` with `(parent_geometry_id, child_geometry_id, parent_kind, child_kind, overlap_pct)` per row. Sorted, deterministic, committed alongside the kept fixture.

**Performance:** Local shapely runs the spatial work in ~5 seconds end-to-end (load WKT + parse + STRtree + threshold check) for the full Montana dataset (349 geometries, ~26,000 candidate pairs across all three relationship types). Earlier drafts of this story prescribed a PostGIS cross-join; that approach hits Supabase's role-locked 2-min `statement_timeout` on real data. The S02.7 runbook documents this finding and the local-shapely architecture rather than an `EXPLAIN ANALYZE` plan.

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md).

**Depends on:** S02.2, S02.3, S02.4, S02.5. **Note: S02.5 may produce zero `cwd_zone` rows under the hand-traced fallback path or if the discriminator returns no matches.** S02.6 still works in that case — it produces fixture rows for HD↔HD self-references, HD→Portion, and HD→Restricted Area, with no HD→CWD entries. The coverage invariant accommodates this (CWD zones only need a binding-row "if any exist").

**Acceptance Criteria:**

- [x] `ingestion/states/montana/fixtures/geometry-overlays.json` exists with: HD→HD self-references for every `hunting_district` row, plus HD→Portion / HD→CWD / HD→Restricted-Area covers/intersects relationships per the area-ratio thresholds in [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md).
- [x] Every relationship row has `parent_geometry_id`, `child_geometry_id`, `parent_kind`, `child_kind`, `relationship` (one of: `self`, `covers`, `intersects`), and `role_for_e03` (one of the seven `JurisdictionBinding.role` Literal values).
- [x] **Audit log** at `ingestion/states/montana/fixtures/geometry-overlays-dropped.json` committed alongside the kept fixture, capturing every HD↔child pair filtered out by `COVER_DROP_THRESHOLD` with `(parent_geometry_id, child_geometry_id, parent_kind, child_kind, overlap_pct)` per row. Sorted, deterministic.
- [x] **Fixture schema:** Python `TypedDict` at `ingestion/ingestion/lib/overlays.py` — `OverlayFixtureRow` + `DroppedOverlayPair` + `ROLE_FOR_E03_BY_CHILD_KIND` mapping. E03 imports these directly.
- [x] **Coverage invariant** (per the table above):
  - Every `hunting_district` row has a self-relationship with `role_for_e03='primary_unit'`.
  - Every `portion` row appears as `child_geometry_id` in ≥1 covers/intersects relationship to an HD parent with `role_for_e03='portion'`. Orphans fail the build loudly.
  - Every `cwd_zone` row appears as `child_geometry_id` in ≥1 covers/intersects relationship to an HD parent with `role_for_e03='cwd_management_zone'`. Orphans fail the build loudly.
  - Every `restricted_area` row appears as `child_geometry_id` in ≥1 covers/intersects relationship to an HD parent with `role_for_e03='restricted_area'`, **OR** the row's id is on the `EXPECTED_RA_ORPHAN_IDS` allowlist (currently 3 documented no-hunt zones — Glacier NP, Sun River Game Preserve, Yellowstone NP — INFO-logged at build time per ADR-016). Any orphan NOT on the allowlist fails the build loudly.
- [x] Every fixture-referenced `geometry_id` (parent or child) exists in the loaded geometry list (JSON-level FK check).
- [x] **Threshold edge tests** in `tests/test_build_overlay_fixture.py` lock in the contract: `overlap_pct = 0.989 → "intersects"`, `0.990 → "covers"`, `0.011 → "intersects"`, `0.009 → dropped`.
- [x] **UAT:** human spot-check that known relationships appear correctly (e.g., HD-262 has only its self-row plus any genuinely contained portions/RAs, not boundary-edge noise).
- [x] Generation script committed at `ingestion/states/montana/build_overlay_fixture.py`.
- [x] Both fixture files are reproducible — running the script produces byte-identical JSON across runs (sorted rows, sort_keys=True, indent=2, trailing newline, atomic tmp+rename, `overlap_pct` rounded to 6 decimals).

---

### S02.7: Spatial query verification + epic exit

**As a** developer validating that E02's geometries answer real spatial queries correctly
**I want** verification that `ST_Covers` against known Montana coordinates returns expected HDs
**So that** E03 and the eventual MCP server can rely on the spatial layer

**UAT: yes** — verify hand-picked coordinates resolve to the right HDs/Portions/Restricted Areas.

**Context:**

This is the final E02 story. No new geometries written; no new schema. Verifies what's been built — plus one small shared-library extension (feature-fixture manifest, see step 7) that resolves known-issues item 6.

**Verification steps:**

1. **Spot-checks via `ST_Covers` on geography (NOT `::geometry` cast):** Use `ST_Covers(geom, ST_GeogFromText('SRID=4326;POINT(<lng> <lat>)'))` to test point-in-polygon. (`ST_Contains(geography, geography)` does exist in PostGIS 2.4+ but its support is partial and semantically surprising at boundary-touching points; `ST_Covers` is the recommended predicate.) For each hand-picked Montana coordinate in the fixture, the expected HD/Portion/Restricted Area row is returned.

2. **Topology validity check:** `SELECT id FROM geometry WHERE NOT ST_IsValid(geom::geometry)` returns zero rows. (`ST_IsValid` is geometry-only; the cast is required here. The geography column already enforces lon/lat bounds at insert time, so this catches topology issues like self-intersection that survived `make_valid`.)

3. **Multi-part HD verification (named):** Use the same named multi-part HD identified in S02.2's AC — `SELECT id, ST_NumGeometries(geom::geometry) FROM geometry WHERE id = '<that HD id>'` returns `> 1`. The named HD is the load-bearing test; aggregate counts elsewhere are supportive but not sufficient.

4. **Geography GiST index reachability check (point-in-polygon only):** Run `EXPLAIN ANALYZE` on a representative point-in-polygon query (`SELECT id FROM geometry WHERE ST_Covers(geom, ST_GeogFromText('SRID=4326;POINT(...)'))`) and document the chosen plan in the runbook. Index Scan via `geometry_geom_gix` is preferred; a Seq Scan on this small dataset is acceptable as long as the index would be reachable on a larger one (i.e., the predicate is index-eligible, the planner chose Seq Scan for cost reasons). Bug case: predicate forces a cast or function call that prevents index use. **Note: this only applies to S02.7's MCP-style point-in-polygon spot-check.** S02.6's overlay computation moved off SQL entirely (Supabase's role-locked 2-min `statement_timeout` aborts cross-joins on real Montana data — see S02.6 line 472), so the overlay-detection query has no SQL plan to document. The runbook covers the local shapely + STRtree architecture, threshold calibration (per ADR-016), and audit-log review process for overlay computation instead.

5. **Reproducibility (topological, not byte-level):** Wipe geometry rows; re-run `make ingest STATE=montana STAGE=geometry` (or equivalent); confirm same row count, same id set, AND for every id, `ST_Equals(reloaded.geom, prior.geom) = true`. (`ST_Equals` works directly on geography.) If a hash-based comparison is preferred over a row-by-row predicate, cast to geometry first: `md5(ST_AsBinary(ST_Normalize(geom::geometry)))` — `ST_Normalize` is geometry-only, so the cast is required. Byte-level equality of the raw `geom` value is NOT a valid test — `geography(MultiPolygon, 4326)` round-trips through canonicalization that can produce different EWKB bytes for topologically identical geometries (ring ordering, vertex ordering after `make_valid`, etc.).

6. **Fixture file:** `ingestion/states/montana/fixtures/spatial-test-points.json` lists ≥1 named test point per `kind` value present in `geometry` (HD, Portion, Restricted Area, CWD zone if any). Each entry: `{name, lat, lng, expected_kind, expected_id_pattern, expected_role_for_e03}`. CI/UAT loops this fixture rather than hardcoding lat/lng in test code.

7. **Feature-fixture manifest (resolves known-issues item 6):** Extend `arcgis.fetch_features` to write a small JSON manifest alongside the (gitignored) `*-features-*.geojson` payload. Manifest path: `<service>-<layer>-manifest-<timestamp>.json` in the same fixtures directory. Required content per manifest:
   - `features_count` — number of features in the fetch
   - `layer_hash` — hash over the sorted per-feature canonical hashes (same hash function as `compute_feature_hash`)
   - `hash_distribution` — histogram of per-feature hashes by first 2 hex chars (256 buckets) for cheap drift signaling without per-feature detail
   - `fetched_at` — ISO timestamp of the fetch run
   - `source_url` — service URL + layer ID used
   - `source_layer_max_record_count` and `source_layer_object_id_field` — copied from the metadata fixture for cross-checking
   Manifests are tiny (~5KB each) and committed to git. Update `ingestion/states/montana/fixtures/.gitignore` to permit `*-manifest-*.json` while still excluding `*-features-*.geojson`. Re-fetch against unchanged source produces an identical manifest (modulo `fetched_at`); a manifest delta against the prior committed version is the cross-operator drift-detection signal that the metadata fixture alone can't catch (feature counts, geometry shape changes, attribute value drift). This is a ~30-line extension to `ingestion/ingestion/lib/arcgis.py` plus tests; not a new story.

**Reproducibility documentation:** Update or add to `docs/runbooks/E02-geometry-verification.md` (parallel to E01's runbook). Include a runbook note: *the wipe + re-ingest pattern works in E02 standalone because nothing yet FK-references `geometry`. Once E03 lands and `jurisdiction_binding` rows reference `geometry.id`, the wipe step will require coordinated handling (DELETE CASCADE or sequenced delete from `jurisdiction_binding` first). This pattern is E02-only.*

**Relevant ADRs:** [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md).

**Depends on:** All prior E02 stories.

**Acceptance Criteria:**

- [x] Spot-check fixture file `ingestion/states/montana/fixtures/spatial-test-points.json` exists with 11 named test points across all 5 `kind` values present in `geometry` (3 HDs incl. the named multi-part `MT-HD-deer-elk-lion-690-geom`, 1 portion, 4 restricted-area incl. all 3 `EXPECTED_RA_ORPHAN_IDS` no-hunt zones, 2 CWD zones, 1 outside-all-zones negative control). Every coordinate is a real `shapely.representative_point()` from the actual loaded geometry (no invented points).
- [x] **UAT:** Each fixture point resolves correctly via `ST_Covers(geom, ST_GeogFromText(...))` per the runbook's section 1 verification protocol.
- [x] All `geometry` rows pass `ST_IsValid` — runbook section 2 uses the Supabase-compatible `ST_GeomFromText(ST_AsText(geom), 4326)` cast workaround for the cluster-config quirk noted in `.roughly/known-pitfalls.md`.
- [x] **Named multi-part HD** `MT-HD-deer-elk-lion-690-geom` returns `ST_NumGeometries > 1` (12 parts) — verified per runbook section 3.
- [x] Runbook documents the point-in-polygon `EXPLAIN ANALYZE` workflow for S02.7's spot-check query (geography GiST reachability check). Overlay computation moved off SQL entirely in S02.6 (Supabase 2-min `statement_timeout` finding) — runbook section 6 documents the local shapely + STRtree architecture, ADR-016 threshold calibration, and audit-log review process for overlay computation instead.
- [x] Re-running ingestion is reproducible per runbook section 5: scoped wipe (`DELETE FROM geometry WHERE state = 'US-MT'`), re-load, then geometry-only `ST_Equals(...)` round-tripped through `ST_GeomFromText(ST_AsText(geom), 4326)` (Supabase rejects direct `geom::geometry` cast). Symmetric ID-parity check (snapshot↔current).
- [x] `arcgis.fetch_features` writes a `<service>-<layer>-manifest-<timestamp>.json` manifest alongside the gitignored features payload — fields per spec, plus an empty-layer branch that writes a marker manifest (zero count, sha256(b"") hash, full zero histogram) so silence ≠ no data. Atomic tmp+rename writer; deterministic JSON. Per-feature OID extraction routes through `_read_objectid` with "no resolvable OID" surfaced as `ArcGISError`. Test count: 300 → 311 (+10 manifest tests, +1 empty-layer regression test).
- [x] `ingestion/states/montana/fixtures/.gitignore` updated to permit `*-manifest-*.json` (anchor comment documenting policy + `*.tmp` orphan-cleanup ignore). 10 manifests committed (one per layer ingested S02.2-S02.5: `huntingDistricts-{2,3,4,10,11,12,13,14,15}-manifest-*.json` + `ADMBND_HD_CWD-0-manifest-*.json`). Backfill script at `ingestion/states/montana/backfill_manifests.py` pairs metadata-with-features by latest-metadata-at-or-before-features-timestamp (not independent latest-of-each); `fetched_at` parsed from filename so re-runs are byte-identical.
- [x] `docs/runbooks/E02-geometry-verification.md` exists (264 LOC) — operator-facing protocol mirroring E01's structure: prerequisites → 7 numbered sections → cleanup. Wipe-and-re-ingest pattern documented as E02-only with a blockquote callout that once E03 lands, the wipe step requires either `ON DELETE CASCADE` on `jurisdiction_binding.geometry_id` or coordinated delete from `jurisdiction_binding` first. Manifest-diff workflow documented as the drift-detection smoke test before any re-ingest.
- [x] No new schema or migration changes. `ingestion/ingestion/lib/arcgis.py` extended (+162 / -39 LOC, larger than the original ~30-line estimate due to OID extraction routing, atomic write helper, and empty-layer branch). Geometry table unchanged from S02.6 (349 V1 Montana rows).

---

## Exit Criteria

- [x] All 8 stories complete (S02.0 through S02.7)
- [x] All V1 Montana geometries loaded: 235 HDs (#3, #10, #11), 55 Portions (#4, #12, #13, #14), 57 Restricted Areas (#2, #15), 2 CWD zones (`ADMBND_HD_CWD` FeatureServer via S02.5 Path A) = **349 total `geometry` rows**
- [x] All geometries pass `shapely.make_valid()` and `ST_IsValid` post-insert
- [x] All geometries are `geography(MultiPolygon, 4326)`; multi-part HDs preserved (named anchor `MT-HD-deer-elk-lion-690-geom` has 12 parts)
- [x] `geometry-overlays.json` fixture covers every loaded geometry per the strengthened per-kind coverage invariant; ready for E03 to consume
- [x] Schema additions (S02.0): `verbatim_rule` on geometry; `gis_layer` document_type — both applied with ADR-014 + ADR-015
- [x] Source fixtures committed for every ingested layer: layer metadata (~7KB each, 10 files) + per-fetch manifest (~5KB each, 10 files added in S02.7). Raw `*-features-*.geojson` payloads remain local-only — gitignored due to ~180MB-per-run size; cross-operator drift detection uses the manifest, not the raw features.
- [x] Spatial queries (`ST_Covers`) against known coordinates return correct assignments — 11 spot-check points in `spatial-test-points.json`, all verified via runbook section 1.
- [x] Re-running ingestion is idempotent (UPSERT semantics — verified per runbook section 5 with `ST_Equals` topological-equality check)
- [x] Pre-commit hooks (E01) running cleanly throughout

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

5. ~~**PostGIS operator semantics on `geography` type.**~~ **Resolved during S02.6 by moving overlay computation off SQL entirely.** The cross-join SQL pattern (`SELECT … FROM geometry a, geometry b WHERE ST_Covers(a.geom, b.geom)`) hit Supabase's role-locked 2-min `statement_timeout` on real Montana data — even with the GiST index reachable, per-row detoasting of ~113 KB MultiPolygons across ~12,000 candidate pairs blew past the cap. S02.6 implements the spatial work locally in shapely + STRtree (~5 seconds end-to-end). The geography GiST index is still relied on for S02.7's MCP-style point-in-polygon spot-checks, where it works fine. **For any future state's overlay computation, plan for local shapely + STRtree, not cross-join SQL.**

6. ~~**Feature-fixture commit policy deviates from S02.1 spec.**~~ **Resolved by folding a checksum-manifest writer into S02.7 (see step 7 + AC).** Raw `*-features-*.geojson` payloads (~180MB per run) stay local-only; manifests (~5KB each, containing `features_count` / `layer_hash` / `hash_distribution`) are committed and provide cross-operator drift detection on counts, geometry shapes, and attribute values that metadata fixtures alone can't catch. The richer git-lfs / object-store options remain available for V2 if manifest-level detection proves insufficient — that decision can be made empirically once the manifest corpus has run for a milestone.

7. **E03 handoff: `restricted_area` kind conflates two semantically distinct concerns.** S02.4 loaded MT FWP layer #2 ("Big Game Restricted Areas") under `kind='restricted_area'`. Live overlay computation in S02.6 surfaced that the layer mixes (a) **internal HD restrictions** like archery-only zones inside a parent HD — these correctly bind to the parent HD's `regulation_record`, and (b) **entire no-hunt zones** like Glacier National Park, Sun River Game Preserve, and Yellowstone NP — these have NO HD parent because they're not part of any hunting jurisdiction; they're simply geographic no-go regions. The 3 V1 no-hunt zones are tolerated via the `EXPECTED_RA_ORPHAN_IDS` allowlist in S02.6 (per ADR-016) but no metadata distinguishes them in the schema — both surface as `kind='restricted_area'`. **E03 will need to disambiguate**: internal restrictions get bound to a specific HD's `regulation_record`; no-hunt zones probably need to bind to *every* nearby `regulation_record` as a "no hunting allowed" overlay (or some equivalent multi-bind mechanic). Adding a discriminator field — `restricted_area_subtype: Literal["internal_hd_restriction", "no_hunt_zone"]` — to `geometry` (or moving the distinction to `jurisdiction_binding.role`) is a candidate ADR for E03 planning.

8. **E03 handoff: jurisdiction_binding fan-out is higher than naive estimates.** Even after the area-ratio threshold filtering in S02.6, median ~3 parent HDs per child geometry, with one restricted area (a large multi-HD-spanning preserve) tied to 16 HD parents. E03's `jurisdiction_binding` row-volume estimate should account for this fan-out — for the V1 Montana dataset, expect roughly several thousand binding rows (not ~349 = one per geometry). The fixture at `ingestion/states/montana/fixtures/geometry-overlays.json` is the authoritative count source; check it before sizing E03 work.

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
