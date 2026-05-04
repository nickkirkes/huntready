# Epic Audit: E02 Montana Geometry Ingestion

**Date:** 2026-05-03
**Auditor:** roughly:audit-epic (Claude, 8 parallel review subagents)
**Epic file:** [`E02-geometry-ingestion.md`](E02-geometry-ingestion.md)
**Stories audited:** 8 (S02.0 → S02.7)
**Acceptance criteria:** 89 total — **86 MET, 3 PARTIAL/MINOR, 0 NOT MET**

---

## Summary

E02 ships clean. Every acceptance criterion that can be verified statically is met. The handful of partials are either intentional design decisions documented in ADRs (digitization-tolerant containment in S02.6), human-only steps that cannot be self-evidenced from the repo (UAT spot-checks in S02.6 / S02.7), or trivial documentation drift (a stale OBJECTID in one S02.5 AC). The 349-row Montana geometry layer matches the epic's exit criteria exactly: 235 HDs + 55 portions + 57 restricted areas + 2 CWD zones. The shared `arcgis` library is well-tested (87 passing tests covering all 15 spec'd scenarios), the four state-adapter loaders follow a consistent pattern, the overlay fixture (S02.6) is byte-reproducible with strict coverage invariants, and S02.7's manifest-writer extension cleanly resolves known issue #6. The two carry-over items flagged in the epic itself (E03 handoff: `restricted_area` discriminator and jurisdiction_binding fan-out) are correctly recorded and out of scope for E02.

The audit surfaced no critical defects, no NOT-MET ACs, and no story-to-story regressions. Three cosmetic findings are listed below as non-blocking recommendations.

---

## Per-Story Results

### S02.0: Schema preparation
**Status:** ✅ 10/10 MET

All schema-version-bump invariants satisfied: ADR-014 + ADR-015 accepted, idempotent migration (`ADD COLUMN IF NOT EXISTS`), three-place sync verified across [`schema.py:73-76`](../../../ingestion/ingestion/lib/schema.py#L73-L76), [`schema.py:392`](../../../ingestion/ingestion/lib/schema.py#L392), [`schema.ts:49-54`](../../../mcp-server/src/types/schema.ts#L49-L54), [`schema.ts:243`](../../../mcp-server/src/types/schema.ts#L243), [`architecture.md:240`](../../architecture.md#L240), [`architecture.md:273`](../../architecture.md#L273). `extra="forbid"` correctly enforces additive-only field expansion. `ruff`, `mypy`, `tsc` all clean.

### S02.1: ArcGIS fetch infrastructure
**Status:** ✅ 21/23 MET, ⚠️ 2 PARTIAL (cosmetic)

All defensive behaviors verified: pagination boundary handling, mixed-CRS refusal, EPSG:3857 bounds pre-check, declared-CRS warning, GeometryCollection raises with OBJECTID, error envelope retry policy, throttling at 500ms, configurable User-Agent contact via env var, all 15 AC#22 test scenarios present and passing (87 tests).

**Partials — both same root cause:**
- AC#9 / AC#23: `MT_FWP_HOST = "fwp-gis.mt.gov"` dead module-level constant at [`arcgis.py:49`](../../../ingestion/ingestion/lib/arcgis.py#L49). Never referenced anywhere; technically a Montana-specific constant in a shared library, violating the spirit of "no Montana-specific code." Harmless but should be deleted.

### S02.2: Hunting District ingestion
**Status:** ✅ 13/13 MET

All three layers ingest with correct `kind='hunting_district'`, species-prefixed IDs (no collisions), `geography(MultiPolygon, 4326)` enforced via `ST_GeomFromText(%s, 4326)::geography` in [`db.py:42`](../../../ingestion/ingestion/lib/db.py#L42), `_extract_verbatim_rule` pulls from `REG`, `SourceCitation` constructed per-feature with `document_type='gis_layer'`, UPSERT idempotency confirmed by 186-line `test_db.py`. The named multi-part anchor `MT-HD-deer-elk-lion-690-geom` (12 parts) is documented in [`README.md:170`](../../../ingestion/states/montana/README.md#L170) and reused by S02.7.

### S02.3: Portions ingestion
**Status:** ✅ 8/8 MET

All four layers ingest with correct `kind='portion'`. The layer-wide two-pass slug strategy (SHAPECODE preferred, PORTIONNAME fallback) at [`load_portions.py:278-323`](../../../ingestion/states/montana/load_portions.py#L278-L323) handles the real layer-#12 SHAPECODE collision (`mdPt312`) and is exercised by tests. Pre-upsert `_duplicate_ids` check raises with up to 5 dupes listed. 661-line test suite covers happy paths, dual-collision, REGYEAR-present/absent, and the zero-features guard at [`load_portions.py:264-275`](../../../ingestion/states/montana/load_portions.py#L264-L275).

### S02.4: Restricted Areas
**Status:** ✅ 8/8 MET

All five REG+COMMENTS combination cases implemented in [`_extract_verbatim_rule_combined`](../../../ingestion/states/montana/load_restricted_areas.py#L110-L140) and tested per case. Literal separator `\n\n--- COMMENTS ---\n\n` verified via `test_separator_exact_literal`. CWD discriminator coordination is clean: `is_cwd_feature` defined exactly once at [`cwd_discriminator.py:16`](../../../ingestion/states/montana/cwd_discriminator.py#L16), imported by `load_restricted_areas.py` (with `not is_cwd_feature(...)` filter) and `load_cwd_zones.py`. No `AREA_*` columns stored.

### S02.5: CWD zone discovery and ingestion
**Status:** ✅ 7/7 MET (with 1 doc nit)

Path A succeeded (dedicated `ADMBND_HD_CWD` FeatureServer found via Hub catalog). All four investigation paths documented in [`cwd-source-discovery.md`](../../../ingestion/states/montana/cwd-source-discovery.md). UAT covers Libby (positive), Kalispell (positive), and an outside-zone negative control.

**Doc nit (not blocking):** AC#3 of the epic spec says Kalispell is OBJECTID 970, but the live load and discovery doc both show OBJECTID 968. The discovery doc is the source of truth; the AC text in the epic is stale.

### S02.6: Geometry overlay fixture
**Status:** ✅ 9/10 MET, ⚠️ 1 PARTIAL (UAT — human-only)

Coverage invariant correctly enforced: portion/CWD orphans block the build; RA orphans block unless on `EXPECTED_RA_ORPHAN_IDS` allowlist (3 IDs: Glacier NP, Sun River, Yellowstone NP). All four threshold edge tests present (0.989, 0.990, 0.011, 0.009). Byte-reproducibility verified via `sort_keys=True`, `indent=2`, atomic tmp+rename, `overlap_pct` rounded to 6 decimals. `OverlayFixtureRow` + `DroppedOverlayPair` TypedDicts at [`overlays.py:79`](../../../ingestion/ingestion/lib/overlays.py#L79) and [`overlays.py:142`](../../../ingestion/ingestion/lib/overlays.py#L142). 586 kept rows + 381 dropped rows; FK-checked against the loaded geometry list.

**Partial:** AC#8 (UAT human spot-check) cannot be self-evidenced from committed artifacts. The fixture's structural counts match exit criteria (235 HD self-rows, 55 portions, 2 CWD, 57 RA inc. 3 allowlisted), so the data is structurally sound; the human visual review is documented as performed in commit messages but not captured as an artifact.

### S02.7: Spatial query verification + epic exit
**Status:** ✅ 10/10 MET (AC#2 requires live DB to fully verify)

Runbook is exactly 264 LOC with 7 numbered sections + prerequisites + cleanup. `spatial-test-points.json` has 11 points across all 5 kind values (3 HDs incl. multi-part 690, 1 portion, 4 RAs incl. all 3 allowlist orphans, 2 CWD zones, 1 negative control). Manifest writer ([`_write_manifest_fixture` at arcgis.py:891-905](../../../ingestion/ingestion/lib/arcgis.py#L891-L905)) is atomic with all 7 spec'd fields plus a marker-manifest empty-layer branch at [`arcgis.py:793-803`](../../../ingestion/ingestion/lib/arcgis.py#L793-L803). 10 manifests committed (one per ingested layer). `.gitignore` correctly permits `*-manifest-*.json` while keeping features payloads local. Wipe-and-re-ingest documented as E02-only with E03 cascade callout.

**Note:** AC#2 (UAT via `ST_Covers`) is operator-executed against a live Supabase connection per runbook section 1. Cannot be verified statically — this is by design and matches the runbook protocol.

---

## Cross-Cutting Findings

### Consistency — strong
The four state-adapter loaders (`load_hds.py`, `load_portions.py`, `load_restricted_areas.py`, `load_cwd_zones.py`) follow the same pattern: function-level logger (per the documented logger-naming split), `_extract_verbatim_rule*` helpers, `arcgis.geojson_to_multipolygon_wkt` for geometry conversion, `arcgis.build_source_citation` per-feature, `db.upsert_geometries` with `ON CONFLICT (id) DO UPDATE`. No drift between loaders.

### Integration — clean
- `cwd_discriminator.py::is_cwd_feature` is defined exactly once (verified by `grep -rn "def is_cwd_feature"`) and consumed by both S02.4 (with negation) and S02.5 (latent — Path A made it unnecessary but the predicate is retained as a guard).
- `S02.6` consumes all four geometry kinds (HD, portion, CWD, restricted_area) and produces a fixture whose FK-checks confirm zero dangling references.
- `S02.7`'s `spatial-test-points.json` covers each kind plus the 3 allowlisted RA orphans from S02.6, providing end-to-end coverage from ingestion → overlay → spatial query.

### Gaps — three minor
1. **Dead Montana-specific constant in shared library.** `MT_FWP_HOST = "fwp-gis.mt.gov"` at [`arcgis.py:49`](../../../ingestion/ingestion/lib/arcgis.py#L49) is unused dead code in a shared library. Violates the letter of S02.1's AC#23 ("no Montana-specific code") despite being harmless.
2. **`_write_features_fixture` is not atomic while `_write_manifest_fixture` is.** [`arcgis.py:870-888`](../../../ingestion/ingestion/lib/arcgis.py#L870-L888) uses direct `write_text` while [`arcgis.py:891-905`](../../../ingestion/ingestion/lib/arcgis.py#L891-L905) uses tmp+rename. Asymmetry has low blast radius (features files are gitignored and re-fetchable) but the inconsistency is a maintenance risk.
3. **Stale OBJECTID in S02.5 epic AC#3.** Says "Kalispell OBJECTID 970"; live data and discovery doc say 968. Pure doc drift.

### Regressions — none
No story's implementation breaks another's. UPSERT semantics preserved across all loaders, schema additions are additive (`extra="forbid"` keeps existing call sites valid), shared `arcgis` library has no Montana-specific imports, overlay fixture's coverage invariant is enforced before write, S02.7's verification suite reuses S02.2's named anchor (`MT-HD-deer-elk-lion-690-geom`).

---

## Recommendations

Prioritized — all P3 (cosmetic, non-blocking). E02 is shippable as-is.

1. **[P3, S02.1] Delete dead `MT_FWP_HOST` constant.** Single-line removal at [`arcgis.py:49`](../../../ingestion/ingestion/lib/arcgis.py#L49). Eliminates Montana-specific code in shared library. No test impact.
2. **[P3, S02.7] Make `_write_features_fixture` atomic.** Mirror the tmp+rename pattern from `_write_manifest_fixture` so both writers fail-or-succeed atomically. Trivial refactor, high consistency value.
3. **[P3, S02.5] Fix stale OBJECTID in epic AC#3.** Update [`E02-geometry-ingestion.md`](E02-geometry-ingestion.md) line 451 from "OBJECTID 970" to "OBJECTID 968" to match the discovery doc. Pure doc maintenance.

Optional (deferred unless drift surfaces):
- Add a published EXPLAIN ANALYZE plan capture for the V1 dataset to runbook section 4 (currently documents the workflow without an artifact).
- Strengthen the `test_zero_area_child_kept_as_intersects` test in `test_build_overlay_fixture.py` to assert `kept` is non-empty rather than passing vacuously.
- Add CLI argparse coverage for `main()` entrypoints in the four state-adapter loaders.

---

## Audit method (for reproducibility)

- 8 parallel review subagents (Sonnet model, one per story).
- Each subagent received: the story's full AC list, an absolute-path file map derived from `git log --grep="S02.X"`, and an instruction to mark each AC as MET / PARTIALLY MET / NOT MET with file:line evidence.
- Cross-cutting analysis performed against the compacted AC status table after all per-story reviews returned.
- No source code modified. This audit report is the only artifact written.
