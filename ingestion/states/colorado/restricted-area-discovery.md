# Restricted-Area Source Discovery — Colorado

## Investigation Date
2026-06-03

## Author
Build-session synthesis of `docs/research/colorado-restricted-areas-evaluation.md` (research doc landed at `ed721c4` on 2026-06-03, authored by HuntReady research-drafting session delegated by PM).

---

## Decision

**Outcome (c) — no-hunt zones discovered.** Per E05 epic S05.4 AC #3, this is outcome (c): authoritative no-hunt-zone geometry found. CPW publishes no statewide restricted-area or no-hunt-zone geometry layer of its own, but the USGS PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer supplies empirically confirmed, federal-authoritative geometry for **10 V1 Colorado no-hunt zones** (4 National Parks + 5 National Monuments + Air Force Academy).

**S05.4 writes geometry rows only.** The loader (`load_restricted_areas.py`) writes 10 `geometry` rows with `kind='restricted_area'`. Bindings (`jurisdiction_binding` rows with `role='no_hunt_zone'`) are **E06's to assign**, per ADR-021 (S05.3.5). S05.4 does not create any `jurisdiction_binding` rows.

---

## Investigation Paths

### Path 1 — CPWAdminData service-root catalog scan → NO (no statewide restricted-area layer)

- **Date:** 2026-06-03
- **URL:** `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer?f=json`
- **Layers scanned for `restrict|no.?hunt|preserve|sanctuary|closed|prohibit` (30 total):** zero matches.

The closest candidate, **layer 5 "CPW Managed Properties (public access only)"** (928 features), enumerates *hunt-allowed* CPW properties — State Wildlife Areas, Walk-In Access lands, leased Hunting Access tracts, and State Parks — the semantic inverse of what S05.4 requires. The only CPW org service whose name advertises "Restricted Areas" is `Snake_River_RFW_Boundary_with_Restricted_Areas`, a property-specific structure-buffer dataset (4 features on one Recreation/Fishing/Wildlife property), not a statewide hunting-restriction layer.

A broader CPW org scan (`orgid:ttNGmDvKQA7oeDQ3`, 703 total items, 2026-06-03) returned only the same `Snake_River_RFW` hit for restriction-related name patterns. A narrower search for `"no hunting" OR restricted OR closed OR prohibited` returned 17 hits, none a statewide no-hunt-zone layer. `CPWArtificalLightUseClosure_DRAFT` is the closest by name; it is a predator-equipment-closure layer (DRAFT), not a no-hunt boundary.

**Decision:** CPWAdminData carries no statewide restricted-area or no-hunt-zone layer.

---

### Path 2 — PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer filter → YES (recommended path)

- **Date:** 2026-06-03
- **Service:** `https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0`
- **Layer:** `PADUS4_1FederalFeeMangAuth`; owner `mcroft@usgs.gov_USGS`; `editingInfo.lastEditDate` = `2026-04-22T18:06:27Z`

Query:
```
State_Nm = 'CO' AND (
  (Mang_Name = 'NPS' AND Des_Tp IN ('NP', 'NM', 'NRA'))
  OR (Mang_Name = 'DOD' AND Unit_Nm = 'United States Air Force Academy')
)
```

Returns **11 features** (10 NPS + 1 DOD). **Drop Curecanti NRA** (36 CFR §2.2 permits hunting in NRAs unless specifically closed; Curecanti is not specifically closed in its general regulatory scheme) → **10 V1 rows kept.**

Full NPS result (`State_Nm = 'CO' AND Mang_Name = 'NPS'` without `Des_Tp` filter → 13 features; V1-relevant 10 are those with `Des_Tp IN ('NP','NM','NRA')`):

| Des_Tp | Unit_Nm | GIS_Acres | V1? |
|--------|---------|-----------|-----|
| NP | Rocky Mountain National Park | 265,475 | ✓ |
| NP | Great Sand Dunes National Park | 104,902 | ✓ |
| NP | Mesa Verde National Park | 53,445 | ✓ |
| NP | Black Canyon of the Gunnison National Park | 30,272 | ✓ |
| NM | Dinosaur National Monument | 150,671 | ✓ |
| NM | Colorado National Monument | 20,448 | ✓ |
| NM | Florissant Fossil Beds National Monument | 6,264 | ✓ |
| NM | Hovenweep National Monument | 369 | ✓ |
| NM | Yucca House National Monument | 36 | ✓ |
| NRA | Curecanti National Recreation Area | 1,120 | ✗ (dropped per 36 CFR §2.2) |
| NCA | Great Sand Dunes National Preserve | 41,702 | ✗ (hunt-ambiguous; defer M2) |
| HCA | Bent's Old Fort National Historic Site | 767 | ✗ (non-hunting-relevant) |
| HCA | Sand Creek Massacre National Historic Site | 6,489 | ✗ (non-hunting-relevant) |

DOD query (`State_Nm = 'CO' AND Des_Tp = 'MIL'`) → 11 features; only AFA is unambiguous for V1 (Fort Carson hosts a managed military-recreation hunt program; all others are M2 scoping candidates). AFA: 18,519 ac, `Pub_Access='XA'`.

**Decision:** Path 2 yields the authoritative geometry. No further investigation paths are needed.

---

### Path 3 — CPW Big Game brochure PDF hand-trace → NOT NEEDED (Path 2 succeeded)

The 2026 CPW Big Game brochure (`https://cpw.state.co.us/regulations/hunting/regulations-brochures`) was 404 on 2026-06-03 across all four URL candidates tested by the research-drafting session. Path 3 is not needed for geometry — Path 2 supplies authoritative federal geometry. The brochure's role is to supply the future `verbatim_rule` text (CPW's regulatory citation that "no hunting" applies in each named NP/NM/AFA). Operator must resolve the 2026 brochure URL before Group B / E06 verbatim-rule population.

Per ADR-001, hand-tracing a prevalence or monitoring map is rejected. Hand-tracing an authoritative regulatory boundary is permitted (S02.5 precedent), but is unnecessary when Path 2 already succeeds.

---

## V1 Zone List (10)

The authoritative count is **10**: 4 NPs + 5 NMs + AFA = 10. See § "Count reconciliation note" below for resolution of the "9" slip in three locations in the research doc.

| Unit_Nm | geometry.id |
|---------|-------------|
| Rocky Mountain National Park | `CO-restricted-rocky-mountain-national-park-geom` |
| Mesa Verde National Park | `CO-restricted-mesa-verde-national-park-geom` |
| Great Sand Dunes National Park | `CO-restricted-great-sand-dunes-national-park-geom` |
| Black Canyon of the Gunnison National Park | `CO-restricted-black-canyon-of-the-gunnison-national-park-geom` |
| Dinosaur National Monument | `CO-restricted-dinosaur-national-monument-geom` |
| Colorado National Monument | `CO-restricted-colorado-national-monument-geom` |
| Florissant Fossil Beds National Monument | `CO-restricted-florissant-fossil-beds-national-monument-geom` |
| Hovenweep National Monument | `CO-restricted-hovenweep-national-monument-geom` |
| Yucca House National Monument | `CO-restricted-yucca-house-national-monument-geom` |
| United States Air Force Academy | `CO-restricted-united-states-air-force-academy-geom` |

**Curecanti note:** Curecanti NRA would have id `CO-restricted-curecanti-national-recreation-area-geom`. It is fetched by the WHERE clause (included in `Des_Tp IN ('NP','NM','NRA')`) and dropped post-fetch before any DB write. Never written.

Slug derivation: lowercase `Unit_Nm`, replace spaces with hyphens, drop non-alphanumeric characters (excluding hyphens). Lock with a regression test asserting each of the 10 V1 `Unit_Nm` values produces its expected id.

---

## Count Reconciliation Note

The research doc (`docs/research/colorado-restricted-areas-evaluation.md`) says **"9"** in three places:

- **Line 17 (TL;DR):** "the recommended V1 list below is 9 zones after dropping Curecanti NRA"
- **Line 64 (Option A code comment):** "4 NPs + 5 NMs + Air Force Academy = 9 candidates"
- **Line 79 (post-drop comment):** "expect 11 from the query (10 NPS + 1 DOD); 9 after Curecanti filter"

All three are the same arithmetic slip: the commenter counted 4 NPs + 5 NMs = 9 NPS units and forgot to add AFA. The correct arithmetic is 4 NPs + 5 NMs + 1 AFA = **10**.

The authoritative count is 10, established by:
1. The enumerated named list in the research doc §"Outcome Disposition" — 10 items numbered 1–10 (Rocky Mountain NP through United States Air Force Academy).
2. The PAD-US live probe arithmetic: the NPS clause (`Mang_Name='NPS' AND Des_Tp IN ('NP','NM','NRA')`) matches **10** features (4 NP + 5 NM + Curecanti NRA), and the DOD clause matches **1** (AFA) → **11 fetched**. Dropping Curecanti post-fetch leaves 9 NPS-kept + 1 DOD = **10 written**.
3. This table above: count the rows — 10.

Per the "authoritative numbers drift between canonical documents — name the source-of-truth before copying numbers" pitfall (`.roughly/known-pitfalls.md` § "Conventions — Documentation & planning discipline"): the enumerated list in §"Outcome Disposition" of the research doc is the source-of-truth; the three "9" occurrences are the drifted copies. **Resolve to 10.**

The S05.4 loader's `_EXPECTED_ZONE_COUNT` constant and its count-band guard must use **10**, not 9.

---

## `verbatim_rule` Disposition

**`None` for V1.** Two constraints make V1 population impossible at the geometry-write stage:

1. **CPW Big Game brochure 404.** The 2026 brochure URL was unresolvable on 2026-06-03 (all four candidate URLs returned HTTP 404; research doc §"Blocking Issues" #1). The exact regulatory wording CPW uses to cite each no-hunt boundary is unknown at loader-write time.

2. **Single `source` field — split-provenance tension.** The `geometry.source` jsonb field carries one source record. PAD-US (geometry provenance) and the CPW brochure (regulatory text provenance) are different sources. Which source wins the `source` field when `verbatim_rule` is populated is a design call deferred with the text population — the same split-provenance pattern MT's `ADMBND_HD_CWD` ingestion handled (geometry from the MT-FWP layer; verbatim rule from the FWP DEA brochure).

**The CPW brochure is a precondition for the future `verbatim_rule`-population step (E06 / Group B).** Operator must resolve the canonical 2026 brochure URL before Group B verbatim-rule population begins. Once in hand, verify whether CPW cites no-hunt boundaries generically ("national parks are closed to hunting") or per-unit — the former yields one shared string across all NPS rows; the latter yields 9 distinct `verbatim_rule` values. If both a REG paragraph and a COMMENTS-style annotation exist per ADR-015, combine with the `\n\n--- COMMENTS ---\n\n` separator.

---

## Nearby-Binding Predicate (for E06)

Per the research doc §"Ingestion Notes" and S03.10 pitfall C (centroid-to-centroid `ST_DWithin` produces zero matches for large polygons; use boundary-to-boundary):

```sql
extensions.ST_DWithin(zone.geom, gmu.geom, 5000)
```

On the native `geography` type — **boundary-to-boundary**, NOT centroid-to-centroid. RMNP's centroid sits ~30 km deep in the park; a centroid-to-centroid 5 km query would return zero matches for every CO NP. E06's binding loader picks this up; this document records the predicate for posterity (same predicate as S03.10's MT no-hunt-zone binding).

---

## `EXPECTED_CO_RA_ORPHAN_IDS` Seed (for S05.5)

S05.5 (`build_overlay_fixture.py`) must define:

```python
EXPECTED_CO_RA_ORPHAN_IDS: frozenset[str] = frozenset({
    "CO-restricted-rocky-mountain-national-park-geom",
    "CO-restricted-mesa-verde-national-park-geom",
    "CO-restricted-great-sand-dunes-national-park-geom",
    "CO-restricted-black-canyon-of-the-gunnison-national-park-geom",
    "CO-restricted-dinosaur-national-monument-geom",
    "CO-restricted-colorado-national-monument-geom",
    "CO-restricted-florissant-fossil-beds-national-monument-geom",
    "CO-restricted-hovenweep-national-monument-geom",
    "CO-restricted-yucca-house-national-monument-geom",
    "CO-restricted-united-states-air-force-academy-geom",
})
```

These 10 ids are "orphans" in the overlay fixture because no GMU geometry contains them as children — restricted areas are overlaid onto (adjacent to, not children of) GMUs. S05.5 uses this frozenset in the same pattern as `EXPECTED_RA_ORPHAN_IDS` in `build_overlay_fixture.py` for Montana (the 3 MT federal no-hunt zones).

**S05.4 does NOT create `build_overlay_fixture.py`.** S05.5 owns that file and seeds it from the ids above.

---

## MT Contrast

| | Montana V1 (S02.5 / S05.3.5) | Colorado V1 (S05.4) |
|---|---|---|
| No-hunt zone geometry published? | **Yes** — dedicated `ADMBND_HD_CWD` / FWP FeatureServer (3 federal zones) | **No CPW-published layer** — federal geometry via PAD-US 4.1 |
| Authoritative source | MtFishWildlifeParks ArcGIS Online `ADMBND_HD_*` + S02.3 restricted-area service | USGS PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer |
| V1 no-hunt zones ingested | 3 (Glacier NP, Sun River WMA, Yellowstone NP) | 10 (4 NPs + 5 NMs + AFA) |
| Geometry provenance | MT FWP-published layer | NPS → USGS PAD-US aggregation |
| `kind` | `restricted_area` | `restricted_area` |
| Binding `role` | `no_hunt_zone` (reclassified from `other_overlay` per ADR-021 / S05.3.5) | `no_hunt_zone` (ADR-021; E06's loader to assign) |
| Nearby predicate | `extensions.ST_DWithin(zone.geom, hd.geom, 5000)` boundary-to-boundary | `extensions.ST_DWithin(zone.geom, gmu.geom, 5000)` boundary-to-boundary |
| Loader | `montana/load_jurisdiction_bindings.py` hardcoded builder | `colorado/load_restricted_areas.py` (S05.4) |

Both CO and MT no-hunt zones traverse the same federal-authoritative chain (NPS / DOD → USGS PAD-US → HuntReady). The split-provenance geometry-vs-text pattern is the same: federal agency publishes the boundary, state hunting brochure names the regulatory prohibition.

---

## Group B / UAT Disposition

**UAT criterion for S05.4: visual review (investigation time) + spatial verification in S05.7.**

S05.4's UAT approach mirrors S05.2 Group A / Group B split:

- **Group A (at-merge):** loader code + mocked tests; quality gates green; no live network; no DB write.
- **Group B (operator-pending):** live run against PAD-US FeatureServer + production service-role DSN. Operator capture in `docs/planning/epics/E05-confidence-findings/S05.4.md` when run. Includes:
  - `returnCountOnly=true` cross-check (expect 11 pre-drop, 10 post-drop)
  - `ST_IsValid` round-trip verification post-insert
  - Area sanity check: `ST_Area(geom::geography)/4046.86` (acres) within 1% of PAD-US `GIS_Acres` per zone
  - Visual spot-check of RMNP boundary (noncontiguous eastern fragments expected; should be `MultiPolygon`)
  - Dinosaur NM and Hovenweep NM straddle CO/UT; confirm only the CO-side geometry is stored (filter by `State_Nm='CO'` is the guard)

Spatial verification of overlay containment correctness folds into **S05.7** (the CO spatial-verification story) — not S05.4's responsibility.

---

## Source URLs (verified 2026-06-03)

- PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer: `https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0` (HTTP 200; CO NPS NP/NM/NRA query returns 10)
- PAD-US ScienceBase parent item: `https://www.sciencebase.gov/catalog/item/652d52f0d34ee4b6e05cca58`
- CPWAdminData FeatureServer root: `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer?f=json` (HTTP 200; 30 layers; no statewide restricted-area layer)
- CPW layer 5 (managed properties): `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/5` (928 features; all hunt-allowed categories)
- `Snake_River_RFW_Boundary_with_Restricted_Areas`: `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/Snake_River_RFW_Boundary_with_Restricted_Areas/FeatureServer` (4 property-specific safety-buffer features; out of V1 scope)
- CPW Big Game brochures index: `https://cpw.state.co.us/regulations/hunting/regulations-brochures` (HTTP 404 on 2026-06-03; operator resolves 2026 PDF URL before Group B / E06 verbatim-rule population)
