# E05: Colorado Geometry Ingestion

**Status:** Not Started
**Milestone:** M2 — Colorado Ingestion
**Dependencies:** E04 Complete + Audited 2026-05-31 (PR #52 / `b168d28`); recurring-RLS-gap M2 open-question candidate surfaced at planning-start per E04 audit Recommendation §3 (no resolution required for E05 specifically — E05 adds no new public-schema tables; gap persists for any future M2/M3 work that does)
**Validated:** 2026-05-31 (E05 validation triad: Spatial Correctness + ArcGIS Fidelity + Schema Stress-Test reviewers all returned LAND-WITH-EDITS; 14 MUST-FIX + 9 SHOULD-FIX findings applied; one cross-reviewer conflict resolved in favor of the ArcGIS Fidelity finding — see §"Validation triad notes" below)
**Drafted:** 2026-05-31
**Estimated Stories:** 8 (S05.0 through S05.7; per PRD 002 §"E05 — Colorado geometry ingestion" estimate of 6–8 stories)
**UAT Gating:** S05.3, S05.5, S05.7 (S05.3 CWD-zone spot-check → **resolved 2026-06-03 as documented-gap UAT**: CPW publishes no CWD zones, so the `ST_Covers` spot-check is N/A; UAT met via the 3-path investigation report + Q18 surface — see `ingestion/states/colorado/cwd-source-discovery.md`; overlay-fixture visual spot-check; spatial-query verification against known CO coordinates per PRD 002 success criterion #4). Mirrors E02's UAT cadence (S02.5 / S02.6 / S02.7 in MT).

---

## Objective

E05 ingests every Colorado V1 geometry — CPW Game Management Units (GMUs), CWD zones, restricted-area / no-hunt-zone overlays (if CPW publishes them), and `CO-STATEWIDE-geom` — into the `geometry` table, validated through `shapely.make_valid()` and stored as `geography(MultiPolygon, 4326)`. Produces a Colorado `geometry-overlays.json` fixture that E06 consumes when writing `jurisdiction_binding` rows. PostGIS spatial queries return the right GMU/CWD-zone/restricted-area for known Colorado coordinates, with cross-state filter discipline (`state='US-CO'`) baked in per handoff §8 #5.

See [PRD 002 §"E05 — Colorado geometry ingestion"](../prds/002-M2-colorado-ingestion.md) for authoritative scope. See [`docs/research/gmu-source-evaluation.md`](../../research/gmu-source-evaluation.md) for the CPW FeatureServer evidence (layer 6, 186 polygons, `outSR=4326`, no auth) per Q4 resolution. The MT reference epic at [`docs/planning/epics/completed/E02-geometry-ingestion.md`](completed/E02-geometry-ingestion.md) is the structural template; the MT audit at [`completed/E02-audit.md`](completed/E02-audit.md) is the audit-pattern template for E05's own post-implementation audit.

---

## PRD/schema correction — jurisdiction_binding writes belong to E06 (not E05)

PRD 002 §"Why sequential" corrects an earlier-wrong PRD-001-style framing that would have placed `jurisdiction_binding` writes in E05. The reality: bindings carry FKs to BOTH `regulation_record` (E06 territory) AND `geometry(id)` (E05 territory). So **E05 produces the geometry rows + the `geometry-overlays.json` fixture only**; **E06's S03.10-equivalent story writes the bindings** once `regulation_record` rows exist. This is the same resolution E02 reached for the analogous PRD 001 sequencing bug (since reconciled via PRD 001 lines 90/96/111 in S04.5 Bundle B).

S05.6 codifies the cross-state spatial filter discipline (`_STATE = 'US-CO'`) that E06's CO binding-loader will inherit; S05.5 produces the overlay fixture that E06 reads directly. No `jurisdiction_binding` writes happen during E05.

---

## Architectural commitments inherited from M1 + M2

| Commitment | Source | E05 implication |
|---|---|---|
| `geography(MultiPolygon, 4326)` on every geometry; `shapely.make_valid()` before insert | [ADR-010](../adrs/ADR-010-decomposed-entity-model.md), E02 S02.1 pattern | S05.0/S05.2/S05.3/S05.4 ACs enforce. GeometryCollection results raise loudly per S02.4 precedent. |
| `document_type='gis_layer'` on every geometry SourceCitation | [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md) | Fail-loud AC in every loader story. |
| `publication_date = f"{license_year:04d}-01-01"` (Jan 1 of REGYEAR or fetch year); NOT `editingInfo.lastEditDate`, `EDIT_DATE`, or `INPUT_DATE` | [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md), `arcgis.py:953-998` `build_source_citation` | CPW's `EDIT_DATE` / `INPUT_DATE` captured in `geometry.source` jsonb for forensics only — never as `publication_date`. |
| Three-band area-ratio discriminator for overlay fixture (0.99 / 0.01 thresholds, audit log) | [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md) | S05.5 reuses thresholds as starting calibration; recalibrates empirically only if CO drop-band or relabel-band counts diverge >10% from MT proportions. |
| `geometry.kind='state'` for statewide-binding targets; `CO-STATEWIDE-geom` is the binding target for `CO-STATEWIDE-{species}` regulation_records E06 will write | [ADR-018](../adrs/ADR-018-e03-schema-additions.md), S03.0 / S03.6.1 precedent | S05.0 single-row write. |
| State-adapter isolation: no Colorado-specific code in `ingestion/ingestion/lib/` | [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) + `TestNoLibImports` / `TestNoStateAdapterImports` AST guards | New CO-leak-guard test class in S05.1; S05.5's library Literal extensions (`OverlayParentKind`, `OverlayChildKind`) are state-agnostic-clean expansions, not CO-specific code (same pattern as ADR-014/ADR-018). |
| Cross-state spatial filter discipline (`_STATE = 'US-CO'`) on every CO SQL query that scopes to GMUs | Handoff §8 #5; S03.10's `_query_nearby_hds_for_zone` precedent | S05.6 locks the pattern; S05.7 verifies via regression test mirroring `TestQueryNearbyHdsForZone::test_sql_excludes_portions_regression_guard`. |
| PostGIS `extensions.`-prefix on all `ST_*` calls in raw SQL | `.roughly/known-pitfalls.md` under "Integration — Supabase / PostGIS"; S03.10 + S03.6.1 closures | S05.7 runbook + S05.6 reference SQL follow this. |
| Confidence framework carve-out — `geometry` and `jurisdiction_binding` carry **provenance**, not confidence | [ADR-017](../adrs/ADR-017-confidence-calibration.md) §2 | No `confidence` column written on E05 entities. |
| Post-implementation audit standard | E02 precedent + E04 audit-closure | E05 closes with an audit recorded under `docs/planning/epics/completed/E05-audit.md` BEFORE `/plan-next-epic` is invoked for E06. PM refuses-and-flags any `/plan-next-epic` invocation where the prior epic's `Audited:` field is unpopulated. |
| Recurring-RLS-gap discipline (M2 open question per E04 §"Known Issues to Escalate" #1) | E04 close + audit Recommendation §3 | E05 adds no new public-schema tables; gap does not fire for E05 specifically. Discipline persists for any future M2/M3 work that does add a table. |

---

## Validation triad notes (2026-05-31)

The three E05 reviewers (Spatial Correctness + ArcGIS Fidelity + Schema Stress-Test) all returned LAND-WITH-EDITS. **14 MUST-FIX + 9 SHOULD-FIX findings applied across the 8 stories.** One cross-reviewer conflict:

- **Spatial Correctness** flagged "S05.2 must include an explicit Colorado-bounds (`[-109.06, -102.04] × [36.99, 41.00]`) coordinate-range sanity check" as MUST-FIX.
- **ArcGIS Fidelity** clarified: "the shared library's `_check_and_fix_projection` is **global WGS84-bounds-aware (±180/±90)**, not state-parameterized. The Spatial Correctness reviewer's premise was wrong." The E02 epic lines 124-130 describe spec, not lib reality.
- **PM resolution: ArcGIS Fidelity wins.** S05.2's coordinate-range check delegates to the shared library's existing global WGS84 guard + `declared_native_crs_wkid` WARNING path. The CO-bounds-specific check moves to S05.7 as a post-load PostGIS verification (`ST_Envelope` against CO bbox) — analytical layer, not fetch layer. Decision recorded inline in S05.2 + S05.7 ACs below.

Two structural findings landed at the planning layer rather than per-story:

1. **`role_for_e03` naming is semantically wrong for M2** (Schema Stress-Test MUST-FIX). The library at `ingestion/ingestion/lib/overlays.py` exports `ROLE_FOR_E03_BY_CHILD_KIND` and the `OverlayFixtureRow.role_for_e03` field — both named when only MT existed. **PM resolution: backward-compatible alias.** S05.5 introduces `ROLE_FOR_BINDING_BY_CHILD_KIND` as the new state/epic-agnostic export (extending the mapping with CO kinds); `ROLE_FOR_E03_BY_CHILD_KIND` is retained as a deprecated alias pointing to the new constant (zero-disruption for MT code that already imports the old name). The `OverlayFixtureRow.role_for_e03` field name stays (MT fixture data is already on disk that way); module docstring documents the historical naming.

2. **`role='no_hunt_zone'` ADR-trigger** (Schema Stress-Test MUST-FIX + handoff §8 #4 carry-forward). CO is the most likely state to surface RMNP / Mesa Verde NP / Great Sand Dunes NP / Air Force Academy as no-hunt zones whose semantic precision exceeds `other_overlay`. S05.4 ACs require flag-and-discuss with the human before adopting `other_overlay` silently; if adopted, ADR + migration + three-place sync land alongside S05.4. PM does not draft the ADR autonomously.

---

## Stories

### S05.0: Schema preparation — write `CO-STATEWIDE-geom`

**Status:** Closed at-merge 2026-06-01 — squash-merged to main as PR #54 / `7f3b071` from `feat/S05.0-write-co-statewide-geom-row` (5 pre-squash commits: 1 implementation + 1 plan-historical + 1 pitfalls + 2 cubic-fixes). **First E05 PR.** **Group A file-level / static ACs satisfied at-merge** (8 of 10; see checkbox state below). **Group B operator-driven verification ACs remain open** (AC #7 post-write verification queries + AC #8 area_km2 within 1% of ~269,837 km²) pending the live `supabase db push` + operator-run loader against the production project — mirrors S04.1's PRD-006-style "operator verifies live" pattern; S05.0 close is NOT blocked by Group B. Operator runbook in `docs/planning/epics/E05-confidence-findings/S05.0.md` § "Operator runbook for production DB write" (note: working-notes directory `E05-confidence-findings/` is the M2 analog of M1's `E03-confidence-findings/` and deletes at the `m2` tag per ADR-017 §6 retention policy; the durable closure record migrates to a future M2 synthesis report if one is produced). **Source choice locked at plan time**: Tier 3 — US Census TIGER 2024 state shapefile at `https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip` with SHA-256 `ad00cbe66c7177091b668cee202e93d4a1ddcee271c28d1c9f9874af59c04b92` <!-- pragma: allowlist secret --> pinned per ADR-001 fail-loud; `SourceCitation.id='co-census-tiger-state-2024'`; `publication_date='2026-01-01'` (REGYEAR-anchored per ADR-014, NOT TIGER vintage 2024-01-01). Tiers 1 (CPW-published) and 2 (Colorado state library) were not repo-confirmed within investigation budget; mirrors S03.0's "fourth option strictly dominates" deviation precedent (though in the inverse direction — S03.0 found a Tier-3-equivalent that beat the listed Tier-1 + Tier-2 options, while S05.0 fell through to a documented Tier-3 fallback because Tier-1 + Tier-2 surfaces weren't located in the live investigation pass). **Constants-block architecture supports later swap** if a richer CPW or Colorado-Portal source surfaces — `CO-STATEWIDE-geom` is id-keyed, not source-keyed, so any future Tier-1 / Tier-2 adoption is a sources.yaml + load-script swap without identity drift. **Stage-gate trajectory**: Stage-4 plan review Round 1 NEEDS REVISION → fixes → Round 2 PASS (1 Blocker — bare `gdf.to_crs(4326)` would have produced ~100m systematic NAD83-as-WGS84 offset undetectable by AC #8 area check; fixed by explicit reassignment + load-bearing comment block; 1 Concern — `urllib.request` diverged from project's `requests` convention; switched to `requests.Session` via `arcgis._build_session()`). Stage-6 parallel review (code-reviewer + static-analysis + silent-failure-hunter): **7 actionable findings landed in 1 review-fix cycle** (P0 detect-secrets baseline entry; P1 `ZipFile` resource leak; P1 empty response body diagnostic; P1 multiple `.shp` silent first-alphabetical; P1 NULL geometry → unhelpful TypeError; P2 missing `STATEFP` column → bare pandas `KeyError`; P3 overbroad test exception tuple). **2 cubic-fix iterations**: Iter 1 P2 removed `--service-url` override that created a silent-lie citation surface under deliberate dual-override; Iter 2 P2 added missing variable binding in a pitfall-entry example snippet. **9 fail-loud guards in the loader** (7 + 1 SHA + 1 non-MultiPolygon post-make_valid). **4 new pitfalls landed in `.roughly/known-pitfalls.md`** (2 under Integration — Census TIGER + geopandas covering the to_crs reassignment trap + TIGER native EPSG:4269; 2 under Conventions — Pre-commit & secrets covering detect-secrets baseline interactions). **Test baseline shifted post-S05.0: 1166 → 1184 + 2 skipped** (+18 from the new `test_load_co_state_boundary.py` unit tests — deliberate quality addition, not a regression; AC #5 is satisfied because the +18 is the new loader's own tests, not edits to existing tests). New baseline holds going forward across S05.1-S05.7. **Two M2 hygiene candidates surfaced and queued (out of S05.0 blast radius)** — flagged to user for decision; PM does NOT touch `ingestion/` autonomously: (1) `db.upsert_geometry` missing `cur.rowcount == 0` fail-loud guard (inconsistent with the `update_legal_description` / `update_license_tag_draw_spec_key` / `upsert_jurisdiction_binding` pattern established post-S03.6; low-risk today because psycopg3 returns `rowcount=1` for both INSERT and UPDATE under ON CONFLICT DO UPDATE; risk surfaces if DDL ever changes to ON CONFLICT DO NOTHING; single-PR fix in `db.py`); (2) MT `load_state_boundary.py --service-url` provenance silent-lie — same latent issue cubic-fixed in CO; single-line removal + test-import update. **No ADRs created**; **no schema or three-place-sync changes** (`kind='state'` already valid per `20260504032424_e03_schema_additions.sql:59-67`; Pydantic + TypeScript Literals already include `"state"` from S03.0); **no `db.py` touches**; **no production-database writes from the build session** (live write is operator-driven). Q19 stays RESOLVED via ADR-020; no new open questions opened.

**As a** developer preparing Colorado's geometry layer for E06's statewide-anchor regulation_records
**I want** the single `CO-STATEWIDE-geom` row written to `geometry` with `kind='state'`, `state='US-CO'`, `license_year=NULL`, and a `document_type='gis_layer'` SourceCitation pinning the source
**So that** E06's `CO-STATEWIDE-{species}` regulation_records have a binding target analogous to MT's `MT-STATEWIDE-geom` per ADR-018 §3

**UAT: no**

**Context:**

Mirrors S03.0's MT-STATEWIDE-geom write. No new schema migration needed; `geometry.kind='state'` value already exists per ADR-018 + S03.0's migration `20260504032424_e03_schema_additions.sql`. No three-place sync needed.

**Source priority** (per ADR-018 §3 + MT S03.0's deviation precedent):

1. **First preference:** a CPW-published state boundary (ArcGIS layer or downloadable GeoJSON) if one exists. `document_type='gis_layer'` per ADR-014.
2. **Second preference:** Colorado Geospatial Portal / state library equivalent of MT's MSDI Framework Boundaries (`gisservicemt.gov` analog).
3. **Fallback:** US Census TIGER 2026 (or latest available) state shapefile (`https://www.census.gov/geographies/mapping-files/...`). Pin URL + SHA-256 + `publication_date=2026-01-01` per ADR-014.

The S05.0 implementer picks during execution and documents the choice + SHA-256 in the story closure note (analog of S03.0's `mt-msdi-framework-boundaries-9-2026` choice over ADR-018's two listed options).

**Verification queries** (post-write):

```sql
SELECT id, kind, state, license_year, source->>'document_type'
FROM geometry
WHERE id = 'CO-STATEWIDE-geom';
-- Expected: 1 row; kind=state; state=US-CO; license_year=NULL; document_type=gis_layer

SELECT extensions.ST_IsValid(extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)) AS is_valid,
       extensions.ST_NumGeometries(extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)) AS n_parts,
       extensions.ST_Area(geom)/1000000 AS area_km2
FROM geometry
WHERE id = 'CO-STATEWIDE-geom';
-- Expected: is_valid=t; n_parts=1 (CO is single-part); area_km2 ≈ 269,837 (Colorado published area)
```

**Relevant ADRs:** [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-018](../adrs/ADR-018-e03-schema-additions.md).

**Acceptance Criteria:**

**Group A — file-level / static (satisfied at-merge):**

- [x] `ingestion/states/colorado/load_state_boundary.py` exists (mirrors `ingestion/states/montana/load_state_boundary.py` from S03.0; same 4-pure-functions + main() shape, only the parser body diverges — TIGER ZIP+shapefile vs MT's GeoJSON); idempotent UPSERT by id — actual: 326 LOC + 343-LOC unit tests at `ingestion/tests/test_load_co_state_boundary.py`
- [x] Single `geometry` row written via mocked tests: `id='CO-STATEWIDE-geom'`, `kind='state'`, `state='US-CO'`, `license_year=NULL` (year-invariant). Live-DB row write is operator-driven per Group B below
- [x] `source` jsonb populated with `document_type='gis_layer'` per ADR-014; `publication_date = '2026-01-01'` (Jan 1 of REGYEAR per ADR-014; NOT TIGER vintage 2024-01-01); `SourceCitation.id='co-census-tiger-state-2024'`
- [x] Source URL + SHA-256 pinned in the load script: `https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip` + SHA-256 `ad00cbe66c7177091b668cee202e93d4a1ddcee271c28d1c9f9874af59c04b92`; source-choice rationale (Tier-3 fallback because Tier-1 + Tier-2 were not repo-confirmed within investigation budget) documented in `docs/planning/epics/E05-confidence-findings/S05.0.md`
- [x] Geometry passes `shapely.make_valid()` before insert; result coerced to `MultiPolygon` (single-part Colorado boundary wrapped via Python `shapely.geometry.MultiPolygon([poly])`; **load-bearing reassignment fix** for `gdf = gdf.to_crs(4326)` Stage-4-plan-review Blocker — the bare expression would have silently discarded the reprojection, producing ~100m systematic NAD83-as-WGS84 offset undetectable by AC #8 area check); non-MultiPolygon result post-`make_valid` raises (catches GeometryCollection)
- [x] Live-source SHA-256 drift fails loud per ADR-001 (`_verify_sha256` returns observed digest on success, raises `RuntimeError` with both digests on mismatch — mirrors S03.0)
- [x] **Test suite shifted post-S05.0: 1166 → 1184 + 2 skipped** (+18 from `test_load_co_state_boundary.py` — deliberate quality addition, not a regression. AC originally cited "remains at the post-E04 baseline (1166 + 2 skipped) — schema-prep story, no Python edits expected beyond the new load script + its unit tests"; the +18 IS the new loader's unit tests per the AC's explicit carve-out, so AC text intent is satisfied. New 1184 baseline holds going forward across S05.1-S05.7)
- [x] No Pydantic / TypeScript / `architecture.md` / migration edits — `kind='state'` already valid per `20260504032424_e03_schema_additions.sql:59-67`; Pydantic + TypeScript Literals already include `"state"` from S03.0

**Group B — operator-driven post-`supabase db push` + loader-run (open; not blocking S05.0 close per the PRD-006-style "operator verifies live" pattern):**

- [ ] **Post-write verification queries return expected results** — *operator-pending*: AC #7 from the Context section's "Verification queries". Run after operator-driven loader-run against production Supabase (service-role DSN). Three-row verification block: identity columns + `document_type='gis_layer'`; `ST_IsValid` true + `ST_NumGeometries` = 1; `area_km2` populated for AC #8 cross-check. All `ST_*` calls already `extensions.`-prefixed in the documented queries per `.roughly/known-pitfalls.md`. Capture verbatim outputs in `docs/planning/epics/E05-confidence-findings/S05.0.md` § "Group B verification record" slot (analog of S04.1's 2026-05-30 verification record)
- [ ] **`area_km2` within 1% of Colorado's published area (~269,837 km²)** — *operator-pending*: AC #8 from the Context section. Capture in same Group B verification slot. Cross-check against CPW's authoritative boundary; ±1% tolerates digitization-precision and TIGER state-line generalization without falsely flagging a regression

---

### S05.1: CPW ArcGIS fetch infrastructure + Colorado adapter scaffold

**Status:** Closed at-merge 2026-06-02 — squash-merged to main as PR #55 / `ba6ef1c` from `feat/S05.1-cpw-arcgis-fetch-infra` (3 pre-squash commits: 1 implementation + 1 plan-historical + 1 doc-writer pitfalls update; **second E05 PR**). **Scaffold-only story**: 5 deliverable files; no production-database writes; no `db.py` touches; no schema/three-place-sync changes; **hard constraint held — `git diff --stat ingestion/ingestion/lib/` empty across all 3 pre-squash commits** (AC #6 + the broader zero-lib-edit constraint; the new leak-guard test locks this property going forward). Files: `ingestion/states/colorado/__init__.py` (verify-only; unchanged from S05.0); `README.md` new at 113 LOC with 8 h2 sections; `sources.yaml` new at 35 LOC using `gis_layers:` top-level key (deliberate divergence from MT's `pdfs:`-only structure since CO at S05.1 has no PDFs); `fixtures/.gitignore` new at 17 LOC (trimmed from MT's 45-line template — dropped PDF + drift-marker sections; ignores `*-features-*.geojson` + `*.tmp`, permits `*-metadata-*.json` + `*-manifest-*.json`); `ingestion/tests/test_arcgis.py` appended with `TestNoColoradoLeakIntoSharedLib` class (+95 insertions, 0 deletions; 3 tests + 1 class-body invariant assertion + 1 module-level Path import; walks `ingestion/ingestion/lib/` via `Path(lib.__file__).parent.rglob("*.py")` — auto-covers future lib additions; scans for `colorado` (case-insensitive) + 3 CPW host literals `services5.arcgis.com`, `ttngmdvkqa7oedq3`, `cpwadmindata`). **Source location locked** at `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer` layer 6 with `agency="Colorado Parks and Wildlife"`, `title="Big Game GMUs (Layer 6 of CPWAdminData)"`, `document_type='gis_layer'` per ADR-014; runtime SourceCitation construction stays in `arcgis.build_source_citation` — the YAML's `id_template: "co-cpw-arcgis-cpwadmindata-6-{license_year}"` is operator-facing documentation of intent, NOT a runtime input (inline YAML comment added Stage-6 review-fix warning future S05.2 authors against reading the field directly). **Stage-gate trajectory**: Stage-4 plan review PASS on first iteration with 4 minor findings (2 plan edits applied pre-Stage-5: `_check_and_fix_projection` line-number citation removed; detect-secrets remediation pattern flipped from inline pragma to baseline-merge per S05.0 precedent). Stage-6 parallel review triad (code-reviewer + static-analysis + silent-failure-hunter): **4 actionable findings landed in 1 review-fix cycle** (LOW return-type annotation `-> list` → `-> list[Path]`; silent-failure-hunter W1 class-body lowercase invariant for `_CPW_HOST_LITERALS`; silent-failure-hunter W2 inline non-empty guards in both scan methods for pytest-randomly safety; INFO inline anti-direct-read YAML comment on `id_template`). **1 mid-Stage-6 cubic-fix**: annotation change `-> list[Path]` triggered ruff F821 because Path was only imported inside the method body — PEP 563 makes the annotation a string at runtime but ruff's static analysis still flags unresolved names; fix hoisted `from pathlib import Path` to module-level imports (surfaced as the first of 4 generalizable pitfalls landed). **1 post-merge cubic finding empirically invalidated**: cubic flagged `assert all(s == s.lower() for s in _CPW_HOST_LITERALS)` at class-body level as a P1 NameError-at-import-time risk; empirically demonstrated invalid via isolated 4-line repro that DID raise AssertionError on a mixed-case entry — the generator expression's leftmost iterable is evaluated in class scope per Python language reference § 6.2.4 (only the inner expression + subsequent for/if clauses run in implicit function scope); pattern is correct, finding rejected. **PM-approved spec deviations baked in** (both flagged at Stage 4 reviewer as MINOR-not-blocking; both validated at Stage 1 + Stage 2 discovery): (1) Epic AC text "the `_STATE = 'US-CO'` convention S05.6 codifies" — S05.0's actual code uses `CO_STATE_CODE = "US-CO"`; README documents the current name with an explicit S05.6 forward-reference for unification across all CO loaders, rather than pre-documenting a constant that doesn't exist yet (preserves doc/code alignment; README's "State-code constant convention" section names both); (2) Epic AC text "import path (`from ingestion.lib.arcgis import ...`)" — codebase-actual convention is `from ingestion.lib import arcgis, db` (verified in both `load_state_boundary.py` files); README uses the codebase-actual form. **4 new pitfalls landed in `.roughly/known-pitfalls.md`** (file grew 887 → 923 LOC; doc-writer dispatched via Stage 8 step 6): (1) Conventions — Python (new section): PEP 563 deferred annotations do not satisfy ruff F821 — hoist annotation-only names to module level; (2) Conventions — Testing (new section), entry 1: Class-body tuple invariants must be locked by an inline `assert all(...)` immediately after the tuple — closes silent-failure-hunter W1 (mixed-case needle bypass risk); (3) Conventions — Testing (new section), entry 2: Multi-method test classes — each scan method must be self-sufficient with an inline `assert <collection>, …` guard rather than relying on a sibling sanity-check running first (pytest-randomly would break definition-order assumptions silently; cross-references S03.10's per-builder dedup pitfall); (4) Conventions — Ingestion adapters (existing section): YAML fields with placeholder substrings (`{license_year}`-style) need an inline comment warning against direct read — surfaced during silent-failure hunt on `sources.yaml`'s `id_template` field. **Test baseline shifted: 1184 → 1187 + 2 skipped** (+3 from the new `TestNoColoradoLeakIntoSharedLib` class — deliberate quality addition, satisfies AC #8 carve-out; new 1187 baseline holds going forward across S05.2-S05.7). **Quality gates final state at-merge**: ruff clean across `ingestion/` + `tests/`; mypy clean on `ingestion/lib/` (8 source files) AND `ingestion/states/colorado/` (2 source files — `__init__.py` + `load_state_boundary.py`); pytest 1187 passed + 2 skipped in ~14s; pre-commit detect-secrets passed on all 3 commits (with 1 routine `.secrets.baseline` line-number refresh on the pitfalls commit — recurring pattern documented in S03.6's existing pitfall). **No ADRs created**; implementation refines ADR-003 (ingestion upstream + offline), ADR-005 (the new `TestNoColoradoLeakIntoSharedLib` is the canonical enforcement mechanism for ADR-005 going forward for CO), and ADR-014. Q19 stays RESOLVED via ADR-020. The recurring-RLS-gap M2 open-question candidate (E04 §"Known Issues to Escalate" #1) is unchanged in scope — S05.1 added no new `public.*` tables. **`_STATE` constant codification deferred to S05.6** — README documents `CO_STATE_CODE` as current; S05.6's spec carries the unification across all CO loaders. **Two M2 hygiene candidates from S05.0 still pending** (unchanged in scope; not S05.1 scope): `db.upsert_geometry` rowcount guard + MT `load_state_boundary.py --service-url` removal.

**As a** developer ingesting CPW geometry layers
**I want** a Colorado state-adapter scaffold (`ingestion/states/colorado/`) + `sources.yaml` for the CPW FeatureServer + AST-guard regression test against shared-library Colorado-leak
**So that** S05.2 / S05.3 / S05.4 / S05.5 / S05.6 / S05.7 can ingest CPW layers without re-implementing fetch infrastructure and without contaminating `ingestion/ingestion/lib/`

**UAT: no**

**Context:**

The shared library at `ingestion/ingestion/lib/arcgis.py` is state-agnostic per ADR-005 and was hardened across E02. **No `arcgis.py` changes are expected during S05.1** — per ArcGIS Fidelity reviewer verification:

- Pagination: `fetch_features` uses `metadata.max_record_count` (no hardcoded 2000) at `arcgis.py:705-708`
- OID field discovery: uses `metadata.object_id_field` for `where` clause + dedup at `arcgis.py:678/703`
- `outSR=4326` hardcoded in page params at `arcgis.py:705`
- Per-host throttling keyed on `urlparse(service_url).hostname` at `arcgis.py:107-118` — `services5.arcgis.com` gets its own throttle bucket independent from MT FWP
- `_default_user_agent` reads `HUNTREADY_INGESTION_CONTACT` at call time (not import time) per `arcgis.py:60-72` — no Montana PII baked in
- Error envelope check via `_request_with_retry` at `arcgis.py:248-265` distinguishes transient/permanent
- `build_source_citation` enforces ADR-014 `publication_date = f"{license_year:04d}-01-01"` at `arcgis.py:953-998`
- E02 audit's P3 finding (dead `MT_FWP_HOST` constant) was fixed at commit `0093e88`; only docstring mentions of "montana" remain (illustrative examples, not Montana-specific code)

**Colorado adapter scaffold contents:**

- `ingestion/states/colorado/__init__.py`
- `ingestion/states/colorado/README.md` — documents import path (`from ingestion.lib.arcgis import ...` per MT precedent); CPW FeatureServer URL; per-loader operator invocation pattern; `_STATE = 'US-CO'` constant convention (S05.6 codifies)
- `ingestion/states/colorado/sources.yaml` — single entry for the CPW FeatureServer at this point: `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6` with `agency="Colorado Parks and Wildlife"`, `title="Big Game GMUs (Layer 6 of CPWAdminData)"`, `document_type='gis_layer'`. CWD-zone + restricted-area sources added during S05.3 / S05.4 after discovery investigations complete.
- `ingestion/states/colorado/fixtures/.gitignore` — permits `*-metadata-*.json` (~7KB each, committed) + `*-manifest-*.json` (~5KB each, committed); excludes `*-features-*.geojson` (gitignore-for-consistency-with-MT per ArcGIS Fidelity SHOULD-FIX; CO at 186 polygons is ~5-10MB versus MT's ~180MB but uniform discipline avoids per-layer policy decisions)

**Colorado-leak guard:** New AST-walk regression test `TestNoColoradoLeakIntoSharedLib` (analog of MT's `TestNoLibImports` / `TestPdfNoStateAdapterImports`) that walks every file under `ingestion/ingestion/lib/` and fails if any file contains the substring `colorado` (case-insensitive) or any CPW-host constant. Mirrors E02 audit's MT_FWP_HOST removal discipline.

**Relevant ADRs:** [ADR-003](../adrs/ADR-003-ingestion-upstream-offline.md), [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md).

**Acceptance Criteria:**

- [x] `ingestion/states/colorado/` directory + scaffold files created per Context above (verified `__init__.py` from S05.0 unchanged; `README.md` 113 LOC / 8 h2 sections; `sources.yaml` 35 LOC; `fixtures/.gitignore` 17 LOC trimmed from MT's 45-line template)
- [x] `ingestion/states/colorado/sources.yaml` has 1 entry (CPW FeatureServer layer 6); WAIT for S05.3/S05.4 closures before adding CWD-zone or restricted-area sources — implemented using `gis_layers:` top-level key (deliberate divergence from MT's `pdfs:`-only structure since CO at S05.1 has no PDFs); 7 fields including `id_template` carrying inline anti-direct-read warning per Stage-6 silent-failure-hunter fix
- [x] `ingestion/states/colorado/fixtures/.gitignore` mirrors `ingestion/states/montana/fixtures/.gitignore` (permits metadata + manifest; excludes features payload) — trimmed of MT-specific PDF + drift-marker sections; functionally equivalent at the metadata/manifest/features-payload boundary
- [x] `ingestion/states/colorado/README.md` documents: import path; operator invocation pattern; state-code constant convention; the `_check_and_fix_projection` global-WGS84 reliance. **PM-approved spec deviations** (both validated at Stage 1 + Stage 2 discovery, MINOR-not-blocking at Stage 4): (a) actual codebase import convention is `from ingestion.lib import arcgis, db` (NOT `from ingestion.lib.arcgis import ...`) — README uses codebase-actual form; (b) S05.0's actual code uses `CO_STATE_CODE = "US-CO"` (NOT `_STATE = 'US-CO'`) — README documents the current name with an explicit S05.6 forward-reference for unification rather than pre-documenting a constant that doesn't exist yet
- [x] **`TestNoColoradoLeakIntoSharedLib`** AST-walk regression test added to `ingestion/tests/test_arcgis.py` (+95 insertions, 0 deletions; 3 tests + 1 class-body invariant assertion + 1 module-level Path import; walks `ingestion/ingestion/lib/` via `Path(lib.__file__).parent.rglob("*.py")` — auto-covers future lib additions; scans for `colorado` (case-insensitive) + 3 CPW host literals)
- [x] No `arcgis.py` edits (confirmed by `git diff --stat ingestion/ingestion/lib/` empty across all 3 pre-squash commits — broader zero-lib-edit constraint held)
- [x] `ruff check`, `mypy ingestion/lib/`, `mypy ingestion/states/colorado/`, `pytest ingestion/tests/` all clean — ruff clean across `ingestion/` + `tests/`; mypy clean on `ingestion/lib/` (8 source files) + `ingestion/states/colorado/` (2 source files); pytest 1187 + 2 skipped in ~14s
- [x] Test suite reports **1187 + 2 skipped** (+3 from the new `TestNoColoradoLeakIntoSharedLib` class — deliberate quality addition, satisfies AC carve-out; baseline shift 1184 → 1187 holds going forward across S05.2-S05.7)

---

### S05.2: GMU ingestion (CPW FeatureServer layer 6, ~186 polygons)

**Status:** Closed at-merge 2026-06-02 — squash-merged to main as PR #56 / `d7ba731` from `feat/S05.2-GMU-ingestion` (2 pre-squash commits: `0b38758` implementation + tests; `f8087e1` plan-historical marker). **Third E05 PR.** Single new loader at `ingestion/states/colorado/load_gmus.py` (409 LOC) + comprehensive test suite at `ingestion/tests/test_load_gmus.py` (733 LOC, 47 tests). Mirrors `montana/load_hds.py` structure with single-layer simplifications. Reads CPWAdminData FeatureServer layer 6 and writes GMU polygons to `geometry` with `kind='gmu'`, deterministic ids `CO-GMU-{GMUID}-geom`. **Loader shape** (state-agnostic-clean; no `ingestion/lib/` edits per ADR-005; `TestNoColoradoLeakIntoSharedLib` from S05.1 continues to lock the property): pure helpers `_extract_gmuid` / `_extract_county`; `_feature_to_geometry` (normalization); `_collect_multipart_gmus` + `_write_multipart_fixture`; guards `_duplicate_ids` + `_check_count_band`. **fetch+build split from DB write** (`_fetch_and_build` / `_write_geometries`) so the count-band + duplicate-id guards fire BEFORE `db.connect()` per OQ7 discipline. `main()` carries function-level logger, `logging.basicConfig`, no `--service-url` flag (S05.0 cubic-fix silent-lie-citation precedent honored), uses `with arcgis._build_session()` for fetch, then guards, then `with db.connect()` + explicit `conn.commit()`. **Group A satisfied at-merge** (loader code + 47 mocked tests; all quality gates green; no live network; no DB write). **Group B operator-pending**: live run against CPW FeatureServer + production service-role DSN to (a) commit real `CPWAdminData-6-metadata-<ts>.json` + `-manifest-<ts>.json` + populated `multipart-gmus.json` fixtures; (b) `returnCountOnly=true` row-count cross-check; (c) post-insert `ST_IsValid` round-trip verification — mirrors S05.0 Group B + S02.1→S02.2 pattern. Operator capture in `docs/planning/epics/E05-confidence-findings/S05.2.md` when run. **Key decisions baked in**: (1) `id` derived from `GMUID` (NEVER `OBJECTID` / `metadata.object_id_field`); locked by spec-required regression test `test_geometry_id_derived_from_gmuid_not_objectid` asserting `id` tracks `GMUID=201` and `OBJECTID=999` never leaks. (2) `license_year=None` on the `Geometry` row (CPW layer 6 has no per-feature REGYEAR); `SourceCitation.license_year=2026` (fetch year) → `publication_date='2026-01-01'` per ADR-014; `document_type='gis_layer'`; citation id is `co-cpw-arcgis-CPWAdminData-6-2026` (service slug **case-preserved** from the URL — NOT the lowercase `id_template` in `sources.yaml`, which remains documentation-only per S05.1's anti-direct-read warning). (3) **AC #235 satisfied as LOG-ONLY (documented deviation; see footnote [^ac235-log-only] below).** CPW `EDIT_DATE`/`INPUT_DATE` are emitted at INFO for forensics but not persisted — `SourceCitation` is frozen with `extra="forbid"` (no `notes`/extension field), and E05 forbids schema migrations. Silent-failure-hunter independently confirmed this is a genuine constraint, not a silent omission. Recurrence of the S02.5 "SourceCitation has no notes field" finding. (4) `ColoradoGeometryError` defined new in the loader; the per-feature loop catches the shared lib's `ArcGISError` (carries the geometry-type tally) and re-raises with `GMUID` prepended (exc chain preserved); covers `GeometryCollection`-after-`make_valid`. (5) Count-band guard `[167, 205]` (186 ±10%) fires pre-`db.connect()`. (6) `multipart-gmus.json` schema: `{gmuid, part_count, total_area_sq_km}` with `total_area_sq_km=None` deliberately — planar WKT degrees can't yield faithful km²; authoritative `ST_Area(geom::geography)/1e6` is **deferred to S05.7's PostGIS analytical layer**. **Stage-gate trajectory**: Plan review Round 1 NEEDS REVISION (2 Blockers: stale `args.service_url_const` → AttributeError; missing detect-secrets baseline step — both fixed; 3 Concerns: shapely-wkt import threading, `_load_layer` retraction ambiguity, ruff path) → Round 2 PASS. Stage-6 triad (code-reviewer + static-analysis + silent-failure-hunter): all actionable findings fixed in 1 review-fix cycle, then cubic clean (`{"issues": []}`). Fixes: [Critical] docstring `kind='hunting_district'` → `kind='gmu'` (code was always correct; docstring would have misled operators); [P1] removed dead module-level `_logger` + backwards comment (state adapters use function-level logger which `main()` already does); [Critical/SFH] `_collect_multipart_gmus` `wkt.loads()` + `int(gmuid)` wrapped in fail-loud try/except re-raising `ColoradoGeometryError` with the geometry id (previously opaque on malformed WKT / non-integer GMUID); [P1] `Connection[Any]` → `Connection[tuple[object, ...]]` (matches `db.connect()` return type); [Info] docstring "DEBUG" → "INFO" for forensic logging (INFO is the de-facto forensic record since not persisted); [Tests +3] `test_main_no_commit_on_duplicate_id_guard`, `test_main_no_commit_on_count_band_guard` (lock OQ7 ordering), `test_no_other_state_adapter_imports` (broadened ADR-005 isolation guard beyond Montana). **detect-secrets baseline refresh proved unnecessary** — the CPW org ID in a URL string isn't flagged (same ID already ships in S05.1's `sources.yaml`/`README.md`), and this loader pins no SHA-256; pre-commit detect-secrets passed on both commits. **Test baseline shifted: 1187 → 1234 + 2 skipped** (+47 from `test_load_gmus.py` — deliberate quality addition; new 1234 baseline holds going forward across S05.3-S05.7). **No ADRs created**; refines ADR-001 (fail-loud), ADR-005 (CO isolation — `TestNoLibImports` / broadened guard via `test_no_other_state_adapter_imports`), ADR-010 (MultiPolygon/geography), ADR-014 (gis_layer + REGYEAR-anchored `publication_date`). **No schema or three-place-sync changes** (`geometry.kind='gmu'` already in the Literal); no `db.py` touches; no production-DB writes from the build session. Q18 (CWD sampling target-table) untouched — S05.3 territory. Q19 stays RESOLVED via ADR-020. **Two M2 hygiene candidates from S05.0 still pending** (unchanged in scope; not S05.2 scope): `db.upsert_geometry` rowcount guard + MT `load_state_boundary.py --service-url` removal. **S05.3 (CWD zone discovery + ingestion) is next** per the recommended merge order; S05.4 remains hard-blocked on the `colorado-restricted-areas-evaluation.md` research-doc prerequisite.

[^ac235-log-only]: **AC #235 deviation footnote.** AC #235 originally specified that CPW `EDIT_DATE` and `INPUT_DATE` be captured in `geometry.source` jsonb's free-form `notes` / extension field. At implementation time, silent-failure-hunter independently confirmed the constraint: `SourceCitation` is a frozen Pydantic model with `extra="forbid"` — no `notes` field exists, and E05 explicitly forbids schema migrations. Per ADR-006 + the no-autonomous-schema-add discipline, S05.2 satisfies AC #235 as LOG-ONLY: `EDIT_DATE` and `INPUT_DATE` are emitted at INFO level during the per-feature loop for forensic value, but not persisted. The forensic record remains accessible via operator log capture during Group B verification. This recurs the S02.5 "SourceCitation has no notes field" finding (obs #1016). Future M2 work that wants persisted edit-timestamps would need an ADR + three-place-sync extending `SourceCitation` with a notes/extension field; flagged as a forward-looking candidate, NOT pre-committed in E05.

**As a** developer loading Colorado's primary unit geometries
**I want** all 186 CPW GMU polygons written to `geometry` with `kind='gmu'`, deterministic IDs derived from `GMUID`, and proper per-feature provenance + validity guards
**So that** E06's reg-record + binding logic can identify the GMU for any Colorado coordinate

**UAT: no** (spatial verification UAT is S05.7 — the load is mechanical; verification is per-point sampling)

**Context:**

Endpoint: `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6`

Layer: 6 (Big Game GMUs). Research confirms 186 polygons, last edit 2026-04-09, native EPSG:3857 with `outSR=4326` server-side reprojection. Attribute schema named in `docs/research/gmu-source-evaluation.md` lines 116-127.

**`GMUID` vs. `OBJECTID` foot-gun (per ArcGIS Fidelity MUST-FIX):**

- `GMUID` = primary business key per CPW; used for `geometry.id` derivation: `CO-GMU-{GMUID}-geom`
- `OBJECTID` = ArcGIS-internal; used by shared library for dedup + pagination cursor (via `metadata.object_id_field`) but NEVER for `geometry.id`
- These are **two distinct uses** that look similar. Regression test required: `test_geometry_id_derived_from_gmuid_not_objectid` — fails if any code path derives `geometry.id` from `OBJECTID` or `metadata.object_id_field`

**`license_year` choice (per ArcGIS Fidelity MUST-FIX):**

CPW's CPWAdminData/6 has **no per-feature REGYEAR attribute** (the research doc's attribute schema lists `GMUID`, `COUNTY`, species-DAU fields, `EDIT_DATE`, `INPUT_DATE`, `AcresGISCa`, `SqMilesGIS`, `GlobalID`, `OBJECTID` — no REGYEAR). Per ADR-014 + the `arcgis.py:967-971` MT layer #3/#10 precedent: pass `license_year=2026` (the fetch year) as the deliberate default. Capture CPW's `EDIT_DATE` and `INPUT_DATE` in `geometry.source` jsonb for forensics — **never** as `publication_date`.

**Multi-part state-line cases:**

The research doc explicitly mentions "noncontiguous fragments along state lines" without naming specific GMUs. **No CO multi-part anchor is pre-named in the spec** — the S05.2 loader must surface multi-part GMUs at load time and commit the list as a fixture for S05.7 to consume.

**CRS sanity check delegation:**

Per Spatial Correctness × ArcGIS Fidelity conflict resolution above: S05.2 delegates coord-range sanity to the shared library's existing global-WGS84 guard at `arcgis.py:397-408` + `_check_and_fix_projection`'s mixed-batch / EPSG:3857-valid-extent / declared-CRS-WARNING discipline. CO bounds `[-109.06, -102.04] × [36.99, 41.00]` are far from `(0, 0)` so the origin-near residual blind spot is moot. S05.7 adds a post-load `ST_Envelope`-against-CO-bbox check as the analytical-layer verification.

**Per-feature processing:**

1. Fetch layer metadata via `arcgis.fetch_layer_metadata(service, 6)` — captures `<service>-6-metadata-<timestamp>.json` fixture (~7KB, committed)
2. Fetch features via `arcgis.fetch_features(metadata, ...)` — captures features payload (gitignored, ~5-10MB for 186 polygons) + manifest (~5KB, committed)
3. For each feature:
   - Read `GMUID` from feature properties (the business key, NOT `metadata.object_id_field` which is `OBJECTID`)
   - Convert GeoJSON geometry to MultiPolygon WKT via `arcgis.geojson_to_multipolygon_wkt()` (S02.1's helper); raises loud on `GeometryCollection` results with `GMUID` + geometry-type tally
   - Construct `Geometry` Pydantic instance with `id=f"CO-GMU-{GMUID}-geom"`, `name` from feature attributes (likely `f"GMU {GMUID} ({COUNTY})"` — verify field availability), `kind='gmu'`, `geom=wkt`, `state='US-CO'`, `license_year=None` (year-invariant; CPW has no per-feature REGYEAR), `source=` SourceCitation per ADR-014 with `publication_date='2026-01-01'`
   - Insert via shared `db.upsert_geometries`
4. Post-batch:
   - Cross-check final row count against `returnCountOnly=true` query (should be 186 ± CPW data drift)
   - Emit structured log entry for every GMU whose Shapely result is `MultiPolygon` with `>1` part; commit the list as `ingestion/states/colorado/fixtures/multipart-gmus.json` (small JSON: `gmuid`, `part_count`, `total_area_sq_km`)
   - Verify all rows pass `ST_IsValid` post-insert via the Supabase round-trip cast workaround documented in `.roughly/known-pitfalls.md`

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../adrs/ADR-010-decomposed-entity-model.md), [ADR-012](../adrs/ADR-012-draw-mechanics-sibling-entity.md) (MultiPolygon commitment), [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md).

**Depends on:** S05.0, S05.1.

**Acceptance Criteria:**

**Group A — file-level / static (satisfied at-merge):**

- [x] `ingestion/states/colorado/load_gmus.py` exists — 409 LOC; mirrors `montana/load_hds.py` structure with single-layer simplifications; fetch+build split from DB write per OQ7
- [x] All 186 GMUs ingest (±10% band for CPW data drift since 2026-04-09): row count in `[167, 205]` post-load; structural-error band check fires pre-`db.connect()` per OQ7 discipline — count-band guard `_check_count_band` implemented and locked by `test_main_no_commit_on_count_band_guard`
- [x] Every row's `kind = 'gmu'` (none `'hunting_district'` — that's MT-specific) — docstring corrected from a Stage-6 review-fix critical finding (`kind='hunting_district'` → `kind='gmu'`; code was always correct)
- [x] **`id` derived from `GMUID` attribute (NOT `OBJECTID` / `metadata.object_id_field`)** — pattern `CO-GMU-{GMUID}-geom`; no id collisions within the layer (pre-upsert `_duplicate_ids` check raises with up to 5 dupes listed, mirrors S02.3); locked by regression test `test_geometry_id_derived_from_gmuid_not_objectid` (asserts `id` tracks `GMUID=201` and `OBJECTID=999` never leaks)
- [x] **`shapely.make_valid()` runs on every geometry before insert; `GeometryCollection` results raise `ColoradoGeometryError`** naming `GMUID` + geometry-type tally — implemented; per-feature loop catches shared lib's `ArcGISError` (carries geometry-type tally) and re-raises with `GMUID` prepended; exc chain preserved; mirrors S02.4 + S02.2's `MT-HD-antelope-556-geom` repair pattern
- [x] `geom` is `geography(MultiPolygon, 4326)` (singleton `Polygon` wrapped via Python `shapely.geometry.MultiPolygon([poly])` — NOT SQL `ST_Multi`)
- [x] **`license_year = None` on every `Geometry` row** (CPW has no per-feature REGYEAR); **`SourceCitation.license_year = 2026`** (fetch year) so the citation carries an annual cycle per ADR-014; **`publication_date = '2026-01-01'`** (Jan 1 of REGYEAR per ADR-014); fail-loud if any row's `source.publication_date` is not `2026-01-01` — citation id `co-cpw-arcgis-CPWAdminData-6-2026` (service slug case-preserved from URL, NOT the lowercase `id_template` documentation field in `sources.yaml`)
- [x] **`source.document_type = 'gis_layer'`** on every row per ADR-014; fail-loud if any row's value is not `'gis_layer'`
- [x] **AC #235 — CPW `EDIT_DATE` and `INPUT_DATE` forensic emission** — **satisfied as LOG-ONLY per footnote [^ac235-log-only]**. SourceCitation is a frozen Pydantic model with `extra="forbid"` (no `notes`/extension field exists); E05 explicitly forbids schema migrations; silent-failure-hunter independently confirmed this is a genuine constraint, not a silent omission. Values emitted at INFO during per-feature loop for forensic value; not persisted. Recurs S02.5 obs #1016 finding
- [x] **Multi-part GMU surface**: every GMU whose Shapely geometry has `>1` part logged via structured INFO entry at load time; list committed as `ingestion/states/colorado/fixtures/multipart-gmus.json` with `gmuid`, `part_count`, `total_area_sq_km` per row — **PM-noted schema decision**: `total_area_sq_km=None` deliberately (planar WKT degrees cannot yield faithful km²; authoritative `ST_Area(geom::geography)/1e6` is deferred to S05.7's PostGIS analytical layer)
- [x] **Multi-source provenance flag**: if any single GMU needs assembly from >1 source, pause and flag for ADR before adopting silently — pattern wired in; not triggered in the at-merge state (CPW FeatureServer is single-source for all 186 GMUs)
- [x] CRS sanity check delegates to shared `_check_and_fix_projection` at `arcgis.py:397-408` (global WGS84 envelope + EPSG:3857 valid-extent pre-check + declared-CRS WARNING); **CO-bounds-specific `ST_Envelope` check is deferred to S05.7's analytical layer** (per validation-triad PM resolution)
- [x] Test suite delta: +47 tests in `ingestion/tests/test_load_gmus.py` (733 LOC; mirrors S02.2's `test_load_hds.py` test-suite scope) including the spec-required `test_geometry_id_derived_from_gmuid_not_objectid` regression test + 3 Stage-6-review-fix additions (`test_main_no_commit_on_duplicate_id_guard`, `test_main_no_commit_on_count_band_guard` locking OQ7 ordering, `test_no_other_state_adapter_imports` broadening ADR-005 isolation guard beyond Montana). **Baseline shifted 1187 → 1234 + 2 skipped**; new 1234 baseline holds across S05.3-S05.7

**Group B — operator-driven post-`supabase db push` + live CPW fetch + loader-run (open; not blocking S05.2 close per the PRD-006-style "operator verifies live" pattern):**

- [ ] All rows pass `ST_IsValid` post-insert (using the Supabase `ST_GeomFromText(ST_AsText(geom), 4326)` round-trip cast workaround from `.roughly/known-pitfalls.md`) — *operator-pending*: requires live DB write
- [ ] UPSERT semantics confirmed: re-running the load produces identical state (same row count, no duplicates, no `license_year` drift); analog of S02.2's idempotency AC — *operator-pending*: requires two live loader runs against the same production project
- [ ] Layer metadata fixture committed at `ingestion/states/colorado/fixtures/CPWAdminData-6-metadata-<timestamp>.json` (~7KB) — *operator-pending*: live fetch artifact
- [ ] Per-fetch manifest committed at `ingestion/states/colorado/fixtures/CPWAdminData-6-manifest-<timestamp>.json` (~5KB) with `features_count`, `layer_hash`, `hash_distribution`, `fetched_at`, `source_url`, `source_layer_max_record_count`, `source_layer_object_id_field` per S02.7's spec — *operator-pending*: live fetch artifact

Group B verification outputs are captured directly in `docs/planning/epics/E05-confidence-findings/S05.2.md` § "Group B verification record" when the operator runs the live fetch + loader; once captured, the PM ticks the boxes here in a follow-up doc-only commit. Mirrors S05.0's Group A/B split + S04.1's PRD-006-style "operator verifies live" pattern.

---

### S05.3: CWD zone discovery + ingestion

**Status:** Closed (documented gap) 2026-06-03 — live investigation across all 3 spec'd paths conclusively found CPW publishes **no CWD-zone geometry**: Path 1 (CPWAdminData service-root catalog, 30 layers) = NO; Path 2 (ArcGIS Online org search + full ~200-service CPW hosted-org listing) = NO; Path 3 (PDF hand-trace) = nothing polygonal to trace — Colorado manages CWD by **hunt code / GMU**, not mapped zone polygons (confirmed against CPW's CWD page + USGS reporting CO CWD positives by wildlife-management-unit). Path (c) (GMU-attribute filter) pre-recorded NO. **Outcome = documented gap** (analog of S05.4 outcome (b)): **zero `geometry` rows written; no loader created (`load_cwd_zones.py` not added); `sources.yaml` not extended**. Investigation report committed at `ingestion/states/colorado/cwd-source-discovery.md`. **Path 3 hand-trace rejected per ADR-001** — a prevalence/monitoring map is not an authoritative regulatory zone, and tracing one would invent a boundary CPW does not publish. **Q18 surfaced to human**: CO is the second-CWD-state named in Q18's trigger (`docs/open-questions.md:376`) — it confirms the license/unit-keyed CWD model is the general pattern (not an MT quirk) and that zone-keyed binding is **structurally unavailable** for CO (no zone to key on); PM recommends E06 retain Q18's V1 license-keyed disposition (0 typed CWD `reporting_obligation` rows; text in `regulation_record.additional_rules`), final call is E06's. **No loader, no tests** (suite unchanged at 1234 + 2 skipped); **no schema/three-place-sync**; **no `db.py` touch**; **no production-DB write**. Downstream S05.5/S05.7 `cwd_zone` coverage invariants are vacuously satisfied (zero rows). PR/commit reference to follow at merge.

**As a** developer ensuring Colorado CWD management zones are queryable
**I want** CWD zone geometries loaded if they exist as a CPW GIS layer, or the gap explicitly documented if they don't
**So that** E06 can correctly bind CWD reporting obligations to spatial regions (Q18 trigger surfaces here per `docs/open-questions.md`)

**UAT: yes** — spot-check ≥2 named CWD zones appear in the database and contain expected coordinates per CPW's published CWD-zone documentation

**Context:**

Colorado is the M2 trigger state for Q18 (CWD sampling target-table modeling) per [`docs/planning/epics/completed/E03-deferred-items/cwd-sampling-modeling.md`](completed/E03-deferred-items/cwd-sampling-modeling.md). The research doc at `docs/research/gmu-source-evaluation.md` does NOT enumerate a CWD-zone layer in CPWAdminData; **per ArcGIS Fidelity SHOULD-FIX, the GMU layer attributes carry no CWD-flag attribute (the named DAU fields are species-keyed, not CWD-keyed) — investigation path (c) "GMU layer attribute filter" is pre-recorded as a dead branch.**

**Investigation tree (3 paths; path (c) from S02.5 pre-recorded as NO):**

1. **CPWAdminData service root catalog scan** at `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer?f=json` — look for sibling layers matching `cwd|chronic|disease|wasting`. CPWAdminData may carry a CWD-zone layer as a sibling to layer 6 (Big Game GMUs).
2. **ArcGIS Online Hub search** for `CWD` + CPW organization id (CPW's services5.arcgis.com org id is `ttNGmDvKQA7oeDQ3`). Mirrors S02.5's Path 2 — surfaced MT's `ADMBND_HD_CWD` Feature Service.
3. **PDF hand-trace fallback** from CPW's published CWD-zone documentation (Big Game brochure + any CWD-specific publications) — analog of S02.5's Path 4. If used, ingest via the same path as ArcGIS layers but with a `SourceCitation` whose `document_type='annual_regulations'` (since the source is the published regulation, not a GIS layer) — per ADR-014 + S02.5 pattern.

**`role='no_hunt_zone'` consideration**: CWD zones in CO are **regulated hunt zones** (with sampling requirements), NOT no-hunt zones. They bind via `role='cwd_management_zone'` per the existing `jurisdiction_binding.role` CHECK constraint. No ADR trigger here.

**Q18 trigger condition**: Per `cwd-sampling-modeling.md`, if CPW publishes CWD sampling rules that don't fit `regulation_record.additional_rules` (the V1 disposition), flag immediately and pause for the human's Q18 decision before continuing to E06 implementation. S05.3 ingests the geometry; Q18 is E06's call.

**Named CWD zones for UAT spot-check** (TBD at investigation time — substitute current CPW-published names):

The S05.3 implementer surveys CPW's current published CWD zones and selects ≥2 named zones with assigned test coordinates for UAT verification. The principle is "named zones with assigned test coordinates," not "specific historical names" (mirrors S02.5's revised language at E02 lines 442).

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-018](../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S05.0, S05.1, S05.2.

**Acceptance Criteria:**

**Outcome (realized 2026-06-03): documented gap.** The spec's AC #2 below enumerated only two branches — (a) ≥1 ArcGIS-sourced `kind='cwd_zone'` row, or (b) hand-traced GeoJSON — and **under-specified the pure-gap branch** (CPW publishes nothing). The realized outcome is that gap branch: all three discovery paths returned NO (see `cwd-source-discovery.md`), so zero rows were written, no loader was created, and `sources.yaml` was not extended. This mirrors S05.4 outcome (b). The ingestion-shaped ACs are therefore **N/A by gap**; the investigation + Q18 ACs are met. (Checkboxes are ticked to indicate "dispositioned / nothing outstanding" — N/A items are labeled inline.)

- [x] Investigation report committed to `ingestion/states/colorado/cwd-source-discovery.md` (analog of S02.5's `cwd-source-discovery.md`); documents all 3 paths exercised + path (c) pre-recorded NO, with live evidence (30-layer CPWAdminData catalog; ~200-service CPW org listing; CPW CWD page + USGS unit-keyed reporting)
- [x] **Outcome resolved = documented gap (third branch; spec under-specified AC #2).** Neither (a) ≥1 `kind='cwd_zone'` row nor (b) hand-traced GeoJSON: CPW publishes no CWD-zone geometry (Path 1 + 2 = NO) and CWD is hunt-code/GMU-keyed, so there is no authoritative polygon for Path 3 to trace (hand-tracing a prevalence/monitoring map would violate ADR-001). Zero rows written
- [x] **N/A by gap** — Every row's `kind = 'cwd_zone'`; deterministic ID pattern `CO-CWD-{zone-name-slug}-geom` (no rows)
- [x] **N/A by gap** — All geometries MultiPolygon, valid, WGS84 via `arcgis.geojson_to_multipolygon_wkt` + `shapely.make_valid` (no rows)
- [x] **N/A by gap** — `source.document_type='gis_layer'` (ArcGIS) / `'annual_regulations'` (hand-traced) (no rows)
- [x] **N/A by gap** — `license_year` per ADR-014 (`2026-01-01` for V1) (no rows)
- [x] **N/A by gap** — **UAT, named zones resolve via `ST_Covers`**: no zones exist to query; UAT satisfied instead by the documented-gap investigation + Q18 surface, recorded in `cwd-source-discovery.md` § "UAT disposition"
- [x] **N/A by gap** — Layer metadata fixture (no ArcGIS CWD layer)
- [x] **N/A by gap** — `ingestion/states/colorado/sources.yaml` extended with CWD-zone source entry (no source to register)
- [x] **Q18 surface (PM-side):** flagged to the human at S05.3 close. CO confirms Q18's named trigger (`docs/open-questions.md:376`): license/unit-keyed is the general pattern, and zone-keyed binding is structurally unavailable for CO. PM recommends E06 retain the V1 license-keyed disposition; final Q18 decision is E06's, raised BEFORE E06's reporting-obligation loader specs draft

---

### S05.4: Restricted-area / no-hunt-zone overlay discovery + ingestion

**Status:** Not Started

**As a** developer loading Colorado restricted-area / no-hunt-zone overlays
**I want** any CPW-published restricted-area boundaries loaded with verbatim regulatory text preserved, OR the gap explicitly documented if CPW doesn't publish such a layer
**So that** E06 can attach reg-record overlays (e.g., national-park no-hunt boundaries) to GMUs via E06's S03.10-equivalent binding loader

**UAT: no** (visual review at investigation time; spatial verification in S05.7)

**Context:**

No prior CPW research exists for restricted areas or no-hunt zones. **Per ArcGIS Fidelity MUST-FIX, a research-doc prerequisite is required before S05.4 entry**: `docs/research/colorado-restricted-areas-evaluation.md` modeled on `gmu-source-evaluation.md`. The PM does not draft research docs autonomously; the research doc is either drafted by the human or by an explicit research-drafting session before S05.4 implementation begins.

**Investigation tree (3 candidate paths; spec the research doc against this):**

1. **CPWAdminData service root catalog scan** — look for sibling layers matching `restricted|no.hunt|no.hunting|preserve|sanctuary`. Likely candidates: "State Wildlife Areas" + state-park-no-hunt layers.
2. **PAD-US filter** to CO + designation_type ∈ {National Park, National Monument, National Wildlife Refuge with no-hunt status}. Per research doc line 26 PAD-US is the canonical protected-area dataset.
3. **CPW Big Game brochure PDF hand-trace fallback** — analog of S02.5's Path 4.

**`role='no_hunt_zone'` ADR-trigger (per Schema Stress-Test MUST-FIX + handoff §8 #4):**

Candidate CO no-hunt zones that would map awkwardly to `other_overlay`: Rocky Mountain National Park, Mesa Verde National Park, Great Sand Dunes National Park, Black Canyon of the Gunnison National Park, Florissant Fossil Beds National Monument, Air Force Academy. **Per handoff §8 #4, MT's three V1 no-hunt zones (Glacier NP, Sun River WMA, Yellowstone NP) use `role='other_overlay'` because no `no_hunt_zone` enum value exists in the DDL `role` CHECK constraint**. CO is the most likely state to surface enough volume that `other_overlay` becomes semantically untenable.

**Story flow:**

1. Investigate per the 3-path tree; commit findings to the research doc
2. **If ≥1 no-hunt zone discovered**: pause and surface an ADR proposal for adding `'no_hunt_zone'` to `jurisdiction_binding.role` CHECK constraint (migration + DDL CHECK update + Pydantic Literal extension + TypeScript `GeometryRole` extension; three-place sync per ADR-006 + ADR-018 precedent). PM does NOT draft the ADR autonomously; human-or-ADR-drafting-session.
3. **Until the ADR resolves**: V1 no-hunt zones land as `role='other_overlay'` per current DDL — matching MT's V1 disposition. Flag-and-discuss; do not silently adopt
4. **Internal restricted areas** (within a single GMU, like MT's archery-only zones inside HDs) bind via `role='restricted_area'` per existing CHECK constraint; no ADR trigger
5. **"Nearby" semantics** for no-hunt zones (per S03.10's Glacier NP / Yellowstone NP pattern): `extensions.ST_DWithin(zone.geom, gmu.geom, 5000)` on native geography (boundary-to-boundary), NOT centroid-to-centroid (pitfall C of S03.10's seven pitfalls). E06's binding loader uses this; S05.4 documents the predicate in the research doc

**Combination rule:** if CPW publishes restricted areas with both regulatory text and boundary description, follow ADR-015's REG+COMMENTS handling rule with the `\n\n--- COMMENTS ---\n\n` separator (analog of S02.4 layer #2 pattern). If only one source field per row, store as-is.

**Relevant ADRs:** [ADR-001](../adrs/ADR-001-authority-preserved.md), [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md), [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-015](../adrs/ADR-015-geometry-verbatim-rule-and-reg-comments-handling.md), [ADR-018](../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S05.0, S05.1, S05.2. **Prerequisite:** research doc at `docs/research/colorado-restricted-areas-evaluation.md` exists before S05.4 entry.

**Acceptance Criteria:**

- [ ] **Prerequisite:** `docs/research/colorado-restricted-areas-evaluation.md` exists (drafted by human or research session; NOT by PM autonomously) before S05.4 implementation opens
- [ ] Investigation report committed to `ingestion/states/colorado/restricted-area-discovery.md`; all 3 investigation paths documented
- [ ] One of three outcomes documented in story closure:
  - (a) **CPW restricted-area layer found** → ingest with `kind='restricted_area'`; `role_for_binding='restricted_area'` per `ROLE_FOR_BINDING_BY_CHILD_KIND`
  - (b) **CPW does not publish a restricted-area layer + no no-hunt zones to load** → document the gap in the discovery report; S05.4 closes with zero rows written; downstream S05.5 + S05.7 are unaffected (overlay-fixture invariants tolerate the zero-row case per S02.6's CWD precedent)
  - (c) **No-hunt zones discovered (e.g., RMNP, Mesa Verde NP, Great Sand Dunes NP, etc.)** → pause and surface ADR proposal for `role='no_hunt_zone'` enum addition; until ADR resolves, ingest with `role='other_overlay'` per current DDL (matches MT V1 disposition); flag-and-discuss with human before adopting silently
- [ ] If rows written: deterministic ID pattern `CO-restricted-{name-slug}-geom`; every row's `kind = 'restricted_area'`; all geometries MultiPolygon + valid + WGS84
- [ ] If rows written: `verbatim_rule` populated per ADR-015's five-case combination rule if both REG and COMMENTS fields exist; literal `\n\n--- COMMENTS ---\n\n` separator
- [ ] `source.document_type='gis_layer'` if from ArcGIS path; `'annual_regulations'` if from hand-traced PDF path
- [ ] Boundary-to-boundary nearby-binding predicate documented in `restricted-area-discovery.md`: `extensions.ST_DWithin(zone.geom, gmu.geom, 5000)` on native geography per S03.10 pitfall C — for E06's binding loader to pick up
- [ ] Layer metadata fixture committed (if ArcGIS path); `ingestion/states/colorado/sources.yaml` extended with restricted-area source entry
- [ ] **EXPECTED_CO_RA_ORPHAN_IDS allowlist seeded**: if no-hunt zones are ingested, list of geometry ids expected to orphan in the overlay fixture (analog of MT's `EXPECTED_RA_ORPHAN_IDS` for Glacier NP / Sun River / Yellowstone) — S05.5 references this constant

---

### S05.5: `geometry-overlays.json` fixture build (CO analog of MT S02.6)

**Status:** Not Started

**As a** developer producing a handoff artifact for E06
**I want** a Colorado geometry-overlays fixture capturing every spatial relationship between V1 CO geometries
**So that** E06's binding loader (analog of S03.10) can populate `jurisdiction_binding` rows once `regulation_record` rows exist, without re-running PostGIS spatial computation

**UAT: yes** — visual spot-check that expected relationships appear in the fixture (e.g., a CWD-zone-overlapping GMU shows the expected `cwd_management_zone` overlay; multi-part GMUs along state lines show their self-row; no-hunt-zone orphans appear in `EXPECTED_CO_RA_ORPHAN_IDS` if any were ingested in S05.4)

**Context:**

CO analog of MT's S02.6. Same computation pattern: local shapely + STRtree against a single bulk `SELECT id, kind, ST_AsText(geom) FROM geometry WHERE state = 'US-CO'` (geography-native; no `::geometry` cast per `.roughly/known-pitfalls.md`). Three-band area-ratio discriminator (0.99 covers / 0.01 drops / else intersects) per [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md).

**Library extension (state-agnostic-clean expansion of `ingestion/ingestion/lib/overlays.py`)** — per Schema Stress-Test MUST-FIX:

Current state at `ingestion/ingestion/lib/overlays.py:59-67`:
```python
OverlayParentKind = Literal["hunting_district"]
OverlayChildKind = Literal["hunting_district", "portion", "cwd_zone", "restricted_area"]
```

Note: `"hunting_district"` is already present in `OverlayChildKind` as the self-row case, and `ROLE_FOR_E03_BY_CHILD_KIND` at `overlays.py:122` already maps `"hunting_district" → "primary_unit"`. S05.5 mirrors that pattern symmetrically for `"gmu"`.

S05.5 extends these to cover CO kinds (and the (`gmu`, `gmu`) self-row case):
```python
OverlayParentKind = Literal["hunting_district", "gmu"]
OverlayChildKind = Literal["hunting_district", "portion", "cwd_zone", "restricted_area", "gmu"]
```

This extension follows the docstring guidance at `overlays.py:59-65` ("Extend this Literal (and update `ROLE_FOR_E03_BY_CHILD_KIND` if needed) when additional parent kinds are introduced"). The docstring itself is updated alongside the Literal extensions so the maintained sync-contract stays current.

The mapping at `overlays.py:102/114/121/127` (`ROLE_FOR_E03_BY_CHILD_KIND`) is **renamed for forward semantic correctness** while **preserving backward compatibility for MT code**:

```python
# New canonical export (state/epic-agnostic):
ROLE_FOR_BINDING_BY_CHILD_KIND: Mapping[OverlayChildKind, GeometryRole] = {
    "portion": "portion",
    "cwd_zone": "cwd_management_zone",
    "restricted_area": "restricted_area",
    "gmu": "primary_unit",  # NEW for CO self-row case
}

# Deprecated alias (zero-disruption for MT code that already imports the old name):
ROLE_FOR_E03_BY_CHILD_KIND = ROLE_FOR_BINDING_BY_CHILD_KIND
```

The `OverlayFixtureRow.role_for_e03` **field name stays unchanged** — MT fixture data is already on disk that way; renaming would require regenerating MT's committed fixture. Module docstring documents the historical naming + the deprecated-alias pattern.

**Fixture format** (CO analog mirrors `ingestion/states/montana/fixtures/geometry-overlays.json`):

`ingestion/states/colorado/fixtures/geometry-overlays.json` — list of `OverlayFixtureRow` (parent_geometry_id, child_geometry_id, parent_kind, child_kind, relationship ∈ {self, covers, intersects}, role_for_e03 — preserved field name per above):

- (`gmu`, `gmu`) self-row for every GMU loaded in S05.2 → `role_for_e03='primary_unit'`
- (`gmu`, `cwd_zone`) covers/intersects per ADR-016 thresholds → `role_for_e03='cwd_management_zone'`
- (`gmu`, `restricted_area`) covers/intersects → `role_for_e03='restricted_area'` (or `role_for_e03='other_overlay'` if S05.4 surfaced no-hunt zones under the V1 no-`no_hunt_zone` disposition)

**Statewide rows NOT pre-emitted** (per Schema Stress-Test SHOULD-FIX): S05.5 does not pre-emit `(state, state)` rows for `CO-STATEWIDE-geom` ↔ `CO-STATEWIDE-{species}` regulation_records. E06's binding loader reads `CO-STATEWIDE-geom` from the geometry table at binding-derivation time (mirrors S03.6.1's MT-STATEWIDE-bear pattern). The fixture covers only true overlay (parent ≠ child) and self-row (gmu, gmu) cases.

**Audit log:** `ingestion/states/colorado/fixtures/geometry-overlays-dropped.json` — paired with kept fixture, sorted, deterministic; captures every pair filtered out by `COVER_DROP_THRESHOLD` per `DroppedOverlayPair` TypedDict.

**Threshold recalibration discipline** (per Spatial Correctness SHOULD-FIX): MT's `COVER_RELABEL_THRESHOLD=0.99` and `COVER_DROP_THRESHOLD=0.01` carry forward as starting calibration. After the first CO overlay build, inspect the audit log for borderline drops (overlap in `[0.005, 0.02]`) and borderline relabels (overlap in `[0.98, 0.995]`). If either band's count differs from MT proportions by >10%, recalibrate per ADR-016 §4 and document in S05.5 closure note. Otherwise MT thresholds carry forward unchanged.

**EXPECTED_CO_RA_ORPHAN_IDS** (per Spatial Correctness + Schema Stress-Test SHOULD-FIX): Colorado-specific allowlist constant in `ingestion/states/colorado/build_overlay_fixture.py` (or shared lib if parameterized) — seeded from S05.4's discovery if no-hunt zones were ingested. Any RA orphan NOT on the allowlist fails the build loudly per S02.6 discipline.

**Coverage invariant** (mirrors S02.6 line 533 table):

- Every `geometry.kind='gmu'` row has a self-relationship with `role_for_e03='primary_unit'` (cannot orphan — programmatic)
- Every `kind='cwd_zone'` row appears as `child_geometry_id` in ≥1 covers/intersects relationship to a GMU parent with `role_for_e03='cwd_management_zone'`; orphans fail the build loudly
- Every `kind='restricted_area'` row appears as `child_geometry_id` in ≥1 covers/intersects relationship to a GMU parent with `role_for_e03='restricted_area'` OR `role_for_e03='other_overlay'` (per S05.4 disposition); **OR** the row's id is on `EXPECTED_CO_RA_ORPHAN_IDS` (INFO-logged, build proceeds); any orphan NOT on allowlist fails the build loudly

**`_JURISDICTION_BINDING_ID_FORMAT` contract for E06** (per Schema Stress-Test SHOULD-FIX): The S05.5 fixture header / module docstring documents that E06's CO binding loader **must import** `_JURISDICTION_BINDING_ID_FORMAT = "{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"` from S03.6.1's `load_regulation_records.py` (or its CO equivalent at S06.X.Y) so `CO-STATEWIDE-{species}` binding ids derive symmetrically — UPSERT no-op contract.

**Relevant ADRs:** [ADR-004](../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-010](../adrs/ADR-010-decomposed-entity-model.md), [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md).

**Depends on:** S05.2, S05.3, S05.4 (the latter two may produce zero rows; coverage invariant tolerates this per S02.6's CWD precedent).

**Acceptance Criteria:**

- [ ] `ingestion/states/colorado/build_overlay_fixture.py` exists; computes spatial relationships locally via shapely + STRtree against a single bulk `SELECT id, kind, ST_AsText(geom) FROM geometry WHERE state = 'US-CO'` (geography-native; no `::geometry` cast)
- [ ] **Library extension shipped state-agnostic-clean**: `ingestion/ingestion/lib/overlays.py` `OverlayParentKind` extended to `Literal["hunting_district", "gmu"]`; `OverlayChildKind` extended to `Literal["hunting_district", "portion", "cwd_zone", "restricted_area", "gmu"]` (the existing `"hunting_district"` self-row child kind is preserved alongside the new `"gmu"` self-row addition); new export `ROLE_FOR_BINDING_BY_CHILD_KIND` adds `"gmu" → "primary_unit"` and preserves the existing `"hunting_district" → "primary_unit"` mapping; `ROLE_FOR_E03_BY_CHILD_KIND` retained as deprecated alias (pointing to the new constant for MT code); `OverlayFixtureRow.role_for_e03` field name preserved (data compat with MT fixture); module docstring documents the historical naming
- [ ] `ingestion/states/colorado/fixtures/geometry-overlays.json` exists with: (`gmu`, `gmu`) self-references for every GMU row + GMU↔CWD + GMU↔Restricted-Area covers/intersects per ADR-016 thresholds
- [ ] **Paired audit log** at `ingestion/states/colorado/fixtures/geometry-overlays-dropped.json` committed alongside kept fixture; sorted, deterministic
- [ ] **No statewide rows pre-emitted** — fixture covers only overlay (parent ≠ child) + self-row (gmu, gmu); statewide (`state`, `state`) bindings emit from E06's binding loader at derivation time per S03.6.1 pattern
- [ ] **Coverage invariant** enforced:
  - Every `kind='gmu'` row has a self-relationship with `role_for_e03='primary_unit'`
  - Every `kind='cwd_zone'` row appears as `child_geometry_id` in ≥1 relationship to a GMU parent; orphans fail loud
  - Every `kind='restricted_area'` row appears as `child_geometry_id` in ≥1 relationship to a GMU parent OR is on `EXPECTED_CO_RA_ORPHAN_IDS`; orphans NOT on allowlist fail loud
- [ ] **`EXPECTED_CO_RA_ORPHAN_IDS: frozenset[str]`** constant defined in `build_overlay_fixture.py` (or parameterized via shared lib) seeded from S05.4's discovery; **defaults to `frozenset()`** if S05.4 outcome (b) fires (no restricted-area layer + no no-hunt zones); non-empty only when S05.4 outcome (c) lands no-hunt zones
- [ ] **`_JURISDICTION_BINDING_ID_FORMAT` contract documented** in fixture header or module docstring for E06's reuse
- [ ] **Threshold recalibration check**: closure note documents the audit-log inspection (borderline drops in `[0.005, 0.02]`; borderline relabels in `[0.98, 0.995]`); MT thresholds preserved unless either band differs from MT proportions by >10%
- [ ] **Threshold edge tests** in `ingestion/tests/test_build_co_overlay_fixture.py` mirror S02.6 (lock `overlap_pct = 0.989 → "intersects"`, `0.990 → "covers"`, `0.011 → "intersects"`, `0.009 → dropped`). The four numeric values shift symmetrically if thresholds recalibrate per the threshold-recalibration check above; the test pattern is the lock (band-edge correctness above/below `COVER_RELABEL_THRESHOLD` and `COVER_DROP_THRESHOLD`), not the literal numbers
- [ ] **UAT — visual spot-check**: closure note documents inspection of expected GMU↔CWD-zone relationships + multi-part GMU self-rows (consuming `multipart-gmus.json` from S05.2) + no-hunt-zone orphans appearing in `EXPECTED_CO_RA_ORPHAN_IDS`
- [ ] Every fixture-referenced `geometry_id` exists in the CO geometry list (JSON-level FK check)
- [ ] Both fixture files are reproducible — byte-identical JSON across runs (sorted, `sort_keys=True`, `indent=2`, trailing newline, atomic tmp+rename, `overlap_pct` rounded to 6 decimals per S02.6)
- [ ] Test suite delta documented; baseline preserved at **1234 (post-S05.2) + M (S05.5's delta)** (S05.2 already contributed +47 to the running baseline)

---

### S05.6: Cross-state spatial discipline + binding-loader reference

**Status:** Not Started

**As a** developer preparing E06's CO binding loader (the S03.10 equivalent)
**I want** the cross-state spatial filter discipline (`_STATE = 'US-CO'`) codified in the Colorado adapter + a reference SQL block ready for E06 to drop in
**So that** E06's binding loader avoids cross-state spatial pollution per handoff §8 #5 and the S03.10 precedent

**UAT: no** (verification is part of S05.7's spatial-query-verification UAT, including the regression test that locks the SQL filter)

**Context:**

Per PRD 002 §"Why sequential", actual `jurisdiction_binding` writes belong to E06 (binding FKs to BOTH `regulation_record` AND `geometry`). S05.6 prepares E06's binding-loader reference — it does not write to `jurisdiction_binding`.

**`_STATE` constant** (mirrors `ingestion/states/montana/load_jurisdiction_bindings.py:110` `_STATE: Final[str] = "US-MT"`):

```python
# In a new module ingestion/states/colorado/_constants.py (or load_jurisdiction_bindings.py
# scaffold for E06 to extend):
_STATE: Final[str] = "US-CO"
```

**Reference SQL** (mirrors S03.10's `_query_nearby_hds_for_zone` `cur.execute(...)` at `load_jurisdiction_bindings.py:587` — verify exact line number at story implementation time per pitfall #1 from `.roughly/known-pitfalls.md` Bundle A; the prior epic draft cited `:587/740` but `:740` is a different function `_load_non_statewide_reg_records`, not the nearby-zone query):

```python
# For E06's CO binding loader (NOT executed in E05; documented as reference):
_QUERY_NEARBY_GMUS_FOR_ZONE_SQL = """
SELECT gmu.id, gmu.geom
FROM geometry gmu
WHERE gmu.state = %s
  AND gmu.kind = 'gmu'
  AND extensions.ST_DWithin(%s::geography, gmu.geom, 5000)
"""
# Parameter binding: (_STATE, zone_geom_wkt)
```

**Critical discipline reminders (from S03.10's pitfall corpus and audit):**

1. **State filter is parameter-bound, not string-interpolated**: `WHERE gmu.state = %s` with `(_STATE, …)` parameters — prevents SQL injection AND makes the test-time regression check straightforward
2. **`gmu.kind = 'gmu'`** filter prevents accidentally matching `'state'` row (`CO-STATEWIDE-geom`) or other kinds
3. **Boundary-to-boundary `ST_DWithin` on geography** (NOT centroid-to-centroid `ST_Distance`) — per S03.10 pitfall C, centroid-to-centroid produces zero matches for large polygons (Yellowstone NP's centroid is ~30 km inside the park boundary)
4. **`extensions.`-prefix** on every `ST_*` call per `.roughly/known-pitfalls.md`
5. **5000-meter threshold** matches MT's `_NO_HUNT_ZONE_NEARBY_DISTANCE_M = 5000` per S03.10's Option A; CO may want to recalibrate empirically post-load (deferred to E06's spec or S06.X-equivalent closure note)

**Relevant ADRs:** [ADR-004](../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-010](../adrs/ADR-010-decomposed-entity-model.md).

**Depends on:** S05.0 through S05.5. S05.6's reference is for E06's binding loader; consumed in E06 territory.

**Acceptance Criteria:**

- [ ] `ingestion/states/colorado/_constants.py` (or equivalent) defines `_STATE: Final[str] = "US-CO"`
- [ ] Reference SQL block for E06's binding loader documented in `ingestion/states/colorado/load_jurisdiction_bindings.py` scaffold (NOT executed yet — E06 territory) OR in a closure note that E06's spec links
- [ ] **Cross-state SQL filter regression test** `test_co_binding_loader_sql_filters_by_state_co_pollution_guard` (mirrors S03.10's `TestQueryNearbyHdsForZone::test_sql_excludes_portions_regression_guard`): asserts the reference SQL contains `WHERE gmu.state =` and `AND gmu.kind = 'gmu'` as literal substrings; asserts the SQL does NOT contain a hardcoded `'US-MT'` (mirrors S03.10's regression guard against MT-state-leak)
- [ ] Reference SQL is `extensions.`-prefixed for every `ST_*` call per `.roughly/known-pitfalls.md`
- [ ] Reference SQL uses boundary-to-boundary `extensions.ST_DWithin(zone_geom, gmu.geom, 5000)` (NOT centroid-to-centroid `ST_Distance` between centroid points)
- [ ] Reference SQL filters by `gmu.kind = 'gmu'` (prevents accidentally matching the `kind='state'` `CO-STATEWIDE-geom` row)
- [ ] Closure note documents the 5000-meter threshold inheritance from MT + recalibration deferred to E06
- [ ] No `jurisdiction_binding` rows written in E05 (verified by `SELECT COUNT(*) FROM jurisdiction_binding WHERE …` against any CO geometry; should be 0 throughout E05)
- [ ] Test suite delta: +N tests in `ingestion/tests/test_co_binding_reference.py` (small file, regression tests only)

---

### S05.7: Spatial query verification + epic exit

**Status:** Not Started

**As a** developer validating that E05's CO geometries answer real spatial queries correctly
**I want** verification that `ST_Covers` against known Colorado coordinates returns expected GMUs + overlay rows, with the explicit `state='US-CO'` filter discipline locked
**So that** E06 and the eventual MCP server can rely on the CO spatial layer; AND so that the post-implementation-audit gate that gates `/plan-next-epic` for E06 is satisfiable

**UAT: yes** — verify hand-picked Colorado coordinates resolve to the right GMUs / CWD zones / restricted areas via the documented runbook protocol

**Context:**

Final E05 story. No new geometries written; no new schema. Verifies what's been built. Produces the CO analog of `docs/runbooks/E02-geometry-verification.md` at `docs/runbooks/E05-colorado-geometry-verification.md`.

**Verification steps** (mirror S02.7 with CO substitutions):

1. **Spot-checks via `extensions.ST_Covers` on geography**: Use `extensions.ST_Covers(geom, extensions.ST_GeogFromText('SRID=4326;POINT(<lng> <lat>)'))` to test point-in-polygon for hand-picked CO coordinates. **Every spot-check query MUST include `AND state = 'US-CO'`** in the WHERE clause per PRD 002 success criterion #4. Mirrors S02.7's spot-check protocol.

2. **Topology validity check**: `SELECT id FROM geometry WHERE NOT extensions.ST_IsValid(extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)) AND state = 'US-CO'` returns zero rows. The Supabase round-trip cast workaround per `.roughly/known-pitfalls.md`.

3. **Multi-part GMU verification (named)**: Read `ingestion/states/colorado/fixtures/multipart-gmus.json` from S05.2; use the first entry as the named anchor. `SELECT id, extensions.ST_NumGeometries(extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)) FROM geometry WHERE id = '<named anchor>' AND state = 'US-CO'` returns `> 1`. The named GMU is the load-bearing test; aggregate counts elsewhere are supportive but not sufficient.

4. **Geography GiST index reachability check (point-in-polygon)**: Run `EXPLAIN ANALYZE` on a representative point-in-polygon query and document the chosen plan in the runbook. Mirrors S02.7's protocol; the geography GiST is the existing `geometry_geom_gix` from E01.

5. **CO-bounds post-load `ST_Envelope` verification** (per validation-triad PM resolution): `SELECT extensions.ST_Envelope(extensions.ST_Collect(geom::geometry)) FROM geometry WHERE state = 'US-CO'` returns a bbox within CO bounds `[-109.06, -102.04] × [36.99, 41.00]`. This is the analytical-layer CO-specific check that the shared library's fetch-layer guard does NOT perform.

6. **Reproducibility (topological)**: Wipe + re-ingest pattern. **CRITICAL**: per the E02-cascade callout (E02 runbook line 189), `jurisdiction_binding` now FK-references `geometry.id`. The CO wipe MUST sequence: `DELETE FROM jurisdiction_binding WHERE state = 'US-CO'` BEFORE `DELETE FROM geometry WHERE state = 'US-CO'`. The runbook MUST include an explicit guard against `TRUNCATE` (would wipe MT). Mirrors S02.7's reproducibility protocol with the post-E04 FK cascade adapted.

7. **Cross-state filter regression**: Re-run S05.6's `test_co_binding_loader_sql_filters_by_state_co_pollution_guard` as a UAT step; document the pass.

**`spatial-test-points.json` fixture** (analog of S02.7's MT fixture):

`ingestion/states/colorado/fixtures/spatial-test-points.json` lists ≥1 named test point per `kind` value present in CO `geometry`:

- ≥3 GMUs including ≥1 multi-part anchor selected from `multipart-gmus.json` (S05.2 output)
- ≥0 CWD zones — CO publishes none (S05.3 documented gap, 2026-06-03); the CWD test point is omitted (no zone exists), documented in the closure note
- ≥1 restricted area if S05.4 ingested any
- ≥1 statewide test point (any CO coordinate inside `CO-STATEWIDE-geom`)
- ≥1 outside-CO negative-control point (e.g., a point in Wyoming or Kansas just over the state line — should return 0 rows from the `state='US-CO'` filtered query)

Every coordinate is a real `shapely.representative_point()` from the actual loaded geometry (no invented points per S02.7 discipline).

**Runbook deliverable**: `docs/runbooks/E05-colorado-geometry-verification.md` — CO analog of `docs/runbooks/E02-geometry-verification.md`. **All `ST_*` calls `extensions.`-prefixed** (per validation-triad MUST-FIX; the E02 runbook used bare `ST_*` calls because the Supabase quirk was learned later — the CO runbook does NOT inherit that style). **Wipe section MUST include the E03/E04 FK-cascade callout** with explicit `DELETE FROM jurisdiction_binding WHERE state = 'US-CO'` sequencing before geometry DELETE.

**Post-implementation-audit gate** (per E04 audit-closure locked standard): E05 epic does NOT close until `docs/planning/epics/completed/E05-audit.md` exists with a verdict similar to E02 audit (MET/PARTIAL/NOT-MET tally + zero blocking findings + actionable findings resolved). PM refuses-and-flags any `/plan-next-epic` invocation for E06 where E05's `Audited:` field is unpopulated.

**Relevant ADRs:** [ADR-004](../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-017](../adrs/ADR-017-confidence-calibration.md) §2 (no `confidence` written on E05 entities).

**Depends on:** All prior E05 stories.

**Acceptance Criteria:**

- [ ] `ingestion/states/colorado/fixtures/spatial-test-points.json` exists with ≥1 named test point per `kind` value present in CO geometry, including: ≥3 GMUs (with ≥1 multi-part anchor from S05.2's `multipart-gmus.json`); a CWD-zone test point only if S05.3 produced rows (it did not — CO publishes no CWD zones per the 2026-06-03 documented gap, so this point is omitted); ≥1 restricted area if S05.4 produced any; ≥1 statewide point; ≥1 outside-CO negative-control point
- [ ] Every coordinate is a real `shapely.representative_point()` from the actual loaded geometry (no invented points)
- [ ] **UAT — `ST_Covers` spot-check**: Each fixture point resolves correctly via `extensions.ST_Covers(geom, extensions.ST_GeogFromText(...))` per the runbook's section 1 verification protocol; **every spot-check SQL block includes `AND state = 'US-CO'`** in the WHERE clause per PRD 002 success criterion #4
- [ ] All CO geometry rows pass `extensions.ST_IsValid` (Supabase round-trip cast workaround)
- [ ] **Named multi-part anchor verification**: first entry in `multipart-gmus.json` returns `ST_NumGeometries > 1` via the runbook's section 3 protocol; if `multipart-gmus.json` is empty (CO unexpectedly has zero multi-part GMUs), document the verification as N/A in the closure note and surface as a data observation — do NOT silently skip the AC
- [ ] **CO-bounds post-load `ST_Envelope` check**: `extensions.ST_Envelope(extensions.ST_Collect(geom::geometry))` over `state='US-CO'` returns a bbox within `[-109.06, -102.04] × [36.99, 41.00]`
- [ ] Geography GiST index reachability documented per S02.7 protocol section 4; `EXPLAIN ANALYZE` plan captured in runbook
- [ ] **Reproducibility section in the runbook** correctly sequences `DELETE FROM jurisdiction_binding WHERE state = 'US-CO'` BEFORE `DELETE FROM geometry WHERE state = 'US-CO'`; includes explicit guard against `TRUNCATE`
- [ ] **Cross-state filter regression**: `test_co_binding_loader_sql_filters_by_state_co_pollution_guard` from S05.6 passes; documented in UAT
- [ ] `docs/runbooks/E05-colorado-geometry-verification.md` exists (264 LOC target per S02.7's E02 runbook scope); operator-facing protocol mirroring E02's structure: prerequisites → 7 numbered sections → cleanup; **all `ST_*` calls `extensions.`-prefixed**; **wipe-and-re-ingest section includes the E03/E04 FK-cascade callout**
- [ ] **PRD 002 success criteria explicitly mapped** to S05.7 ACs:
  - SC#4: PostGIS `ST_Covers` with explicit `state='US-CO'` filter — verified above
  - SC#6: zero geometry rows with invalid topology — verified above
  - SC#7: idempotent ingestion (re-run produces zero net new rows; locked by row-count diff = 0 across all CO `kind` values)
- [ ] **Post-implementation audit produced**: `docs/planning/epics/completed/E05-audit.md` exists with verdict similar to E02 audit (MET/PARTIAL/NOT-MET tally; ≥1 verdict line) BEFORE `/plan-next-epic` is invoked for E06; E05 epic header's `Audited:` field is populated at that time

---

## Exit Criteria

- [ ] All 8 stories complete (S05.0 through S05.7)
- [ ] All Colorado V1 geometries loaded: 1 statewide (S05.0) + ~186 GMUs (S05.2) + ≥0 CWD zones (S05.3) + ≥0 restricted-area / no-hunt-zone overlays (S05.4) — exact CWD + RA counts documented at story closures; total in band `[167, ~250]` depending on CO RA + CWD discovery outcomes
- [ ] All geometries are `geography(MultiPolygon, 4326)`; pass `shapely.make_valid()` and `ST_IsValid` post-insert
- [ ] `geometry-overlays.json` fixture covers every loaded CO geometry per the strengthened per-kind coverage invariant; ready for E06's binding loader to consume
- [ ] Library extension shipped state-agnostic-clean (`OverlayParentKind` + `OverlayChildKind` + `ROLE_FOR_BINDING_BY_CHILD_KIND`); deprecated alias `ROLE_FOR_E03_BY_CHILD_KIND` preserves MT compat; `OverlayFixtureRow.role_for_e03` field name unchanged
- [ ] `_STATE = 'US-CO'` constant codified in Colorado adapter; cross-state SQL filter regression test passes
- [ ] Source fixtures committed for every ingested layer: metadata (~7KB) + per-fetch manifest (~5KB); raw features payloads gitignored
- [ ] Spatial queries (`extensions.ST_Covers` with `state='US-CO'`) against known coordinates return correct assignments — `spatial-test-points.json` verified
- [ ] Re-running ingestion is idempotent (UPSERT semantics — verified per S05.7 runbook with the post-E04 FK-cascade sequencing)
- [ ] `docs/runbooks/E05-colorado-geometry-verification.md` operator-facing runbook complete
- [ ] **Post-implementation audit recorded** at `docs/planning/epics/completed/E05-audit.md` with populated `Audited:` field on this epic header BEFORE `/plan-next-epic` is invoked for E06 (per E04 audit-closure locked standard)
- [ ] No Colorado data loaded outside `ingestion/states/colorado/`; no CO-specific code in `ingestion/ingestion/lib/` (`TestNoColoradoLeakIntoSharedLib` passes)
- [ ] PRD 002 success criteria #4, #6, #7 satisfied per S05.7 ACs
- [ ] Test suite delta documented at every story close; **final E05 baseline = 1234 + sum of S05.3-S05.7 per-story deltas** (running history: M1 close 1166 → S05.0 1184 via `test_load_co_state_boundary.py` (+18) → S05.1 1187 via `TestNoColoradoLeakIntoSharedLib` (+3) → S05.2 1234 via `test_load_gmus.py` (+47))

---

## Parallelization Notes

**Within E05: stories run sequentially.** The human creates a feature branch per story and merges before the next begins per the PM-prompt §"Commit and branch workflow".

**Recommended merge order:** S05.0 → S05.1 → S05.2 → S05.3 → S05.4 → S05.5 → S05.6 → S05.7

**Rationale:**

- **S05.0 → S05.1**: S05.1's CO adapter scaffold references `CO-STATEWIDE-geom` in `sources.yaml` documentation; S05.0 must land first
- **S05.1 → S05.2**: S05.2 imports the scaffold + sources.yaml entry; uses the shared lib via the documented import path
- **S05.2 → S05.3 + S05.4**: CWD-zone + restricted-area discovery happens after GMUs land (so the discovery-context queries can join against actual loaded data); the two are independent of each other but the convention is sequential
- **S05.3 + S05.4 → S05.5**: overlay fixture needs all CO geometries loaded before it can compute relationships
- **S05.5 → S05.6**: S05.6 documents the binding-loader reference; the fixture's `role_for_e03` mapping informs the reference SQL
- **S05.6 → S05.7**: verification step verifies what S05.0–S05.6 built; includes the cross-state filter regression test from S05.6

**Sequential is the default**; S05.3 and S05.4 are technically parallelizable (independent layers; no shared write keys) **with the caveat that S05.4 has a research-doc prerequisite** (`docs/research/colorado-restricted-areas-evaluation.md` — drafted by human or research session, NOT by PM). If the research doc is unblocked, parallel S05.3 + S05.4 is acceptable.

**Cross-epic**: E05 → E06 is hard via FK (E06 binding loader references S05.5 fixture + S05.0/S05.2/S05.3/S05.4 geometry rows). E06 cannot begin until E05's `Audited:` field is populated per the locked post-implementation-audit standard.

The PM does not recommend parallel implementation within E05. The `/next` command returns exactly one story.

---

## Known Issues to Escalate

1. **Recurring-RLS-gap M2 open-question candidate (E04 §"Known Issues to Escalate" #1; carried unchanged through E04 audit Recommendation §3)**. None of the 8 E05 stories add a new public-schema table (S05.0 writes 1 row to existing `geometry`; S05.1 adds Colorado adapter scaffold but no DDL; S05.2-S05.5 write to existing `geometry` table; S05.6/S05.7 are docs+verification). **The gap does not fire for E05 specifically.** It persists for any future M2/M3 work that does add a `public.*` table. PM continues to recommend the user pick a mitigation path (event-trigger migration / CI check / discipline-only) before E06 implementation begins (E06 may add no new tables either, but the open question remains pending decision).

2. **`role='no_hunt_zone'` ADR-trigger** (handoff §8 #4 + Schema Stress-Test MUST-FIX). S05.4 has flag-and-discuss discipline baked in; if CO surfaces no-hunt zones in volume, the ADR + migration + three-place sync lands alongside or just after S05.4.

3. **Q18 trigger (CWD sampling target-table modeling)** per [`docs/planning/epics/completed/E03-deferred-items/cwd-sampling-modeling.md`](completed/E03-deferred-items/cwd-sampling-modeling.md). CO is the M2 trigger state. **S05.3 only ingests the geometry**; the Q18 decision (zone-keyed vs license-keyed `reporting_obligation` modeling) is E06's call. S05.3 ACs include a flag-and-discuss event with the human BEFORE E06's reporting-obligation loader specs draft.

4. **Multi-source geometry provenance** (handoff §8 #6 + PRD 002 §"Open decisions resolved during M2"). S05.2 + S05.3 + S05.4 ACs include flag-and-discuss if a single CO row needs assembly from >1 source. V1 simplification stands unless CO surfaces real volume.

5. **Cell-level source attribution** (handoff §8 #7). V1 simplification unchanged. Same trigger as M2-deferred.

If E05 implementation surfaces issues out of E05 scope (research-doc prerequisite delays, schema additions beyond the no_hunt_zone candidate, etc.), implementation agents flag on the relevant story rather than silently widening scope. PM surfaces to human.

---

## References

- [PRD 002 — M2 Colorado Ingestion](../prds/002-M2-colorado-ingestion.md) — E05 scope source
- [`docs/research/gmu-source-evaluation.md`](../../research/gmu-source-evaluation.md) — CPW FeatureServer layer 6 evidence (Q4 resolution)
- [`docs/research/colorado-restricted-areas-evaluation.md`](../../research/colorado-restricted-areas-evaluation.md) — **S05.4 prerequisite (NOT yet drafted)**; human or research-session deliverable before S05.4 entry
- [`docs/planning/epics/completed/E02-geometry-ingestion.md`](completed/E02-geometry-ingestion.md) — MT reference epic; structural template for E05
- [`docs/planning/epics/completed/E02-audit.md`](completed/E02-audit.md) — MT audit pattern; structural template for E05's own post-implementation audit
- [`docs/planning/epics/completed/E03-deferred-items/cwd-sampling-modeling.md`](completed/E03-deferred-items/cwd-sampling-modeling.md) — Q18 background; CO is the trigger state
- [`docs/planning/handoffs/M1-to-M2-handoff.md`](../handoffs/M1-to-M2-handoff.md) §8 — recurring carry-forward items
- [`docs/runbooks/E02-geometry-verification.md`](../../runbooks/E02-geometry-verification.md) — MT operator runbook; S05.7 produces the CO analog
- [`ingestion/ingestion/lib/arcgis.py`](../../../ingestion/ingestion/lib/arcgis.py) — shared ArcGIS fetch library; reused unchanged in S05.1+
- [`ingestion/ingestion/lib/overlays.py`](../../../ingestion/ingestion/lib/overlays.py) — overlay-fixture TypedDicts + role mapping; extended state-agnostic-clean in S05.5
- [`ingestion/ingestion/lib/db.py`](../../../ingestion/ingestion/lib/db.py) — shared upsert helpers; reused unchanged
- [`ingestion/states/montana/load_jurisdiction_bindings.py`](../../../ingestion/states/montana/load_jurisdiction_bindings.py) — `_STATE = 'US-MT'` + `_query_nearby_hds_for_zone` precedent for S05.6
- [`ingestion/states/montana/build_overlay_fixture.py`](../../../ingestion/states/montana/build_overlay_fixture.py) — overlay-fixture builder; CO analog at `ingestion/states/colorado/build_overlay_fixture.py`
- [ADR-001](../adrs/ADR-001-authority-preserved.md) — source citations required
- [ADR-003](../adrs/ADR-003-ingestion-upstream-offline.md) — offline ingestion
- [ADR-004](../adrs/ADR-004-supabase-postgres-postgis.md) — PostGIS + RLS
- [ADR-005](../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) — language split; state-adapter isolation discipline
- [ADR-006](../adrs/ADR-006-schema-versioned-from-day-one.md) — schema versioned; three-place sync
- [ADR-007](../adrs/ADR-007-montana-and-colorado-seed-states.md) — CO is the seed state's draw-system stress-test counterpart
- [ADR-008](../adrs/ADR-008-verbatim-regulation-text.md) — verbatim text required
- [ADR-010](../adrs/ADR-010-decomposed-entity-model.md) — 6-entity model; MultiPolygon commitment
- [ADR-014](../adrs/ADR-014-source-citation-gis-layer-document-type.md) — `document_type='gis_layer'` + `publication_date` semantics
- [ADR-015](../adrs/ADR-015-geometry-verbatim-rule-and-reg-comments-handling.md) — REG+COMMENTS combination rule
- [ADR-016](../adrs/ADR-016-digitization-tolerant-containment.md) — three-band area-ratio discriminator for overlay fixture
- [ADR-017](../adrs/ADR-017-confidence-calibration.md) §2 — spatial-confidence carve-out (no `confidence` on E05 entities)
- [ADR-018](../adrs/ADR-018-e03-schema-additions.md) — `geometry.kind='state'` value; CO-STATEWIDE-geom binding semantics

---

*HuntReady · E05 · M2 — Colorado Ingestion · v1.0 (validated 2026-05-31)*
