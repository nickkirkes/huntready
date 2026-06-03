# Colorado Restricted-Area / No-Hunt-Zone Overlays — Source Evaluation

**Product:** HuntReady
**Target store:** Supabase Postgres + PostGIS, `geography(MultiPolygon, 4326)`
**Pipeline:** Python (geopandas, shapely, requests)
**Date of evaluation:** 2026-06-03
**Author:** HuntReady research-drafting session (delegated by PM at user authorization 2026-06-03)

---

## TL;DR

CPW publishes **no statewide "restricted hunting areas" or "no-hunt zones" layer of its own**. The closest sibling layer on the same `CPWAdminData` FeatureServer that ships GMUs (layer 6) is layer 5 — "CPW Managed Properties (public access only)" — but that 928-feature layer enumerates *hunt-allowed* properties (State Wildlife Areas, Walk-In Access lands, leased Hunting Access tracts), not no-hunt zones. The single in-CPW-org service whose name advertises "Restricted Areas" (`Snake_River_RFW_Boundary_with_Restricted_Areas`) is a property-specific safety-buffer dataset (4 features around structures on one Recreation/Fishing/Wildlife property), not a statewide hunting-restriction layer.

The empirically authoritative source for Colorado no-hunt zones is the **USGS PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer** (live-as-of `editingInfo.lastEditDate` = **2026-04-22**, captured 2026-06-03), filtered to `State_Nm = 'CO'` and the NPS / DOD / FWS-where-closed manager classes. Live probes returned **10 NPS units matching `Des_Tp IN ('NP','NM','NRA')`** (4 National Parks + 5 National Monuments + 1 NRA), **11 DOD military installations** including the Air Force Academy, and **26 FWS-managed feature rows representing 13 distinct units** (the FeatureServer emits fee + designation overlay rows per unit; dedupe on `Unit_Nm` before ingestion) with `Pub_Access='RA'`.

**Outcome disposition: (c) — no-hunt zones discovered.** The named no-hunt-zone candidates the E05 epic flags as the `role='no_hunt_zone'` ADR trigger (RMNP, Mesa Verde NP, Great Sand Dunes NP, Black Canyon NP, Florissant Fossil Beds NM, Air Force Academy) are all empirically confirmed in PAD-US 4.1 with CO geometry. **S05.4 should pause and surface an ADR proposal** for adding `'no_hunt_zone'` to `jurisdiction_binding.role` per the epic's flag-and-discuss discipline (handoff §8 #4 carry-forward). Until the ADR resolves, V1 ingestion should land these as `role='other_overlay'` per current DDL, matching MT V1's disposition. **Recommendation:** Primary = PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer; secondary = the same dataset's per-state Geodatabase download for offline snapshotting. Confidence: **High** that the no-hunt zones exist and are authoritative; **Medium** on the precise V1 row count pending PM scoping (the recommended V1 list below is 9 zones after dropping Curecanti NRA per the NPS-NRA-permits-hunting default at 36 CFR §2.2).

---

## Available Sources

| Source | URL | Format | Native CRS | Last Updated | Licensing | Programmatic retrieval |
|---|---|---|---|---|---|---|
| **PAD-US 4.1 Federal Fee Managers Authoritative (FeatureServer)** | `https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0` | ArcGIS REST (JSON, GeoJSON on request) | EPSG:3857 (Web Mercator); supports `outSR=4326` | `editingInfo.lastEditDate` = 2026-04-22 (live-probed 2026-06-03); PAD-US 4.1 release (2024); USGS aggregates from NPS/DOD/FWS authoritative submissions | Public domain (USGS / federal works, 17 USC §105) | Yes |
| **PAD-US 4.1 per-state Geodatabase** | `https://www.sciencebase.gov/catalog/item/652d52f0d34ee4b6e05cca58` (PAD-US item; download CO ESRI Geodatabase) | ESRI File Geodatabase (.gdb in .zip) | EPSG:4326 | 2024 | Public domain | Yes (sciencebase.gov DOI-stable download) |
| **CPW `CPWAdminData` layer 5 — "CPW Managed Properties (public access only)"** | `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/5` | ArcGIS REST (JSON, GeoJSON on request) | EPSG:3857 | 2026 (active) | Implicitly open under Colorado Open Records Act; same posture as GMU layer 6 (gmu-source-evaluation.md L139) | Yes — but **enumerates hunt-*allowed* CPW properties (SWAs, Walk-In Access, leased Hunting Access), NOT no-hunt zones.** Not the right authority for restricted areas. |
| **`Snake_River_RFW_Boundary_with_Restricted_Areas` FeatureServer (CPW org)** | `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/Snake_River_RFW_Boundary_with_Restricted_Areas/FeatureServer/3` | ArcGIS REST | EPSG:3857 | per-property dataset | Same as GMU | Yes — but **scope is structure-buffer safety zones on one CPW property (4 features)**, not a statewide layer. Out of scope for V1. |
| **CPW Big Game brochure PDF (`verbatim_rule` provenance)** | `https://cpw.state.co.us/regulations/hunting/regulations-brochures` (canonical CPW brochures page; 2026 PDF URL all-404 on 2026-06-03 — **blocking**, see Blocking Issue #1) | PDF (text + map images) | n/a | annual (2026 edition) | Public regulation document | Partial — brochure names common federal no-hunt boundaries (NPs, AFA, NWRs) but defers to federal authorities for boundary definitions, mirroring MT FWP's S02.5 boundary-naming pattern |
| **NPS IRMA boundaries** | `https://irma.nps.gov/DataStore/` (per-park downloads) | Shapefile / KML | varies | per-park | Public domain | Partial — authoritative but per-park; PAD-US already aggregates NPS submissions, so this is the wrong altitude for V1 |

---

## Recommended Primary Source

**USGS PAD-US 4.1 — Federal Fee Managers Authoritative FeatureServer, layer 0 (`PADUS4_1FederalFeeMangAuth`).**

This is the canonical federal aggregation of NPS, DOD, FWS, USFS, and BLM fee-managed protected-area boundaries, owned by `mcroft@usgs.gov_USGS` on ArcGIS Online. Querying `State_Nm = 'CO' AND Des_Tp IN ('NP','NM','NRA')` on 2026-06-03 returned **10 features** (full list under §"Live Probe Evidence" below). Schema carries `Unit_Nm` (unit name), `Des_Tp` (designation type — NP / NM / NWR / MIL / etc.), `Mang_Name` (managing agency — NPS / DOD / FWS), `Pub_Access` (RA / OA / XA — access posture), `GIS_Acres` (sanity-check area), and `State_Nm` (state filter). The service supports `outSR=4326&f=geojson` for server-side reprojection. No authentication required. Public domain under 17 USC §105 (federal government works).

**Authority chain.** NPS is the regulatory authority for the named National Parks per the NPS Organic Act (16 USC §1) and per-park enabling legislation. PAD-US aggregates NPS-submitted boundaries; using PAD-US-via-NPS preserves the authority chain (NPS → USGS aggregation → HuntReady). This mirrors S03.5's MT precedent (`docs/planning/epics/completed/E03-regulation-text-ingestion.md` S03.5): FWP legal-description text from FWP, geometry from the federal aggregation chain — split-provenance for text-vs-geometry is established M1 practice. CPW's Big Game brochure references these federal boundaries by name (e.g., "Rocky Mountain National Park") but does not republish the geometry.

**Structural scope caveat — what this source excludes.** The Federal Fee Managers Authoritative layer is scoped to NPS / DOD / FWS / USFS / BLM **fee-managed** parcels. Three classes of public land are not represented and are by design **out of V1 scope**: (a) **BLM-managed national monuments** (e.g., Browns Canyon NM, designated 2015, ~21k acres BLM-managed in CO) — BLM management permits hunting under standard BLM rules, so the unit is V1-irrelevant as a no-hunt zone; (b) **USFS-managed wilderness areas** — USFS wilderness permits hunting under USFS rules, so V1-irrelevant; (c) **federal easements / proclamation overlays** (separate PAD-US layers — Easement, Proclamation, Combined). The clean V1 answer is "Federal Fee Managers covers NPS / FWS / DOD authoritatively for no-hunt purposes; BLM/USFS hunt-allowed lands are out of V1 scope by design." If a future state's research surfaces a BLM/USFS hunt-restricted unit, sibling probes against the PAD-US Easement or Combined layers would be the right escalation.

## Fallback Source

**PAD-US 4.1 per-state Geodatabase from sciencebase.gov** (DOI-stable). Same underlying authoritative data, snapshotted as ESRI File Geodatabase for offline reproducibility. Use this if the REST service is unreachable or if the M2 build needs a pinned snapshot. Geopandas reads File Geodatabase via the `fiona`/`pyogrio` driver; reproject to 4326 in Python with `gdf.to_crs(epsg=4326)`.

There is no *independent* fallback for federal no-hunt zones — boundaries are definitionally NPS / DOD / FWS / USFS to publish, and PAD-US 4.1 is the authoritative aggregation. CPW does not publish derivative federal boundary geometry.

---

## Retrieval Strategy

### Option A — REST query (recommended for the pipeline)

```python
import requests
import geopandas as gpd

BASE = ("https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
        "Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0")

# V1 scope: 4 NPs + 5 NMs + Air Force Academy = 9 candidates (Curecanti NRA excluded per
# the NPS-NRA-permits-hunting default at 36 CFR §2.2 — see Outcome Disposition §).
# Note: the NPS clause returns 10 rows including Curecanti; filter Curecanti out post-fetch.
# Expand by uncommenting DOD or FWS clauses; PM scopes the V1 row count.
WHERE = (
    "State_Nm = 'CO' AND ("
    "(Mang_Name = 'NPS' AND Des_Tp IN ('NP', 'NM', 'NRA'))"
    " OR (Mang_Name = 'DOD' AND Unit_Nm = 'United States Air Force Academy')"
    ")"
)

# 1) Sanity-check the feature count before pulling
count = requests.get(
    f"{BASE}/query",
    params={"where": WHERE, "returnCountOnly": "true", "f": "json"},
    timeout=30,
).json()["count"]  # expect 11 from the query (10 NPS + 1 DOD); 9 after Curecanti filter

# 2) Pull GeoJSON in 4326 (no Python-side reprojection — see gmu-source-evaluation.md L110)
resp = requests.get(
    f"{BASE}/query",
    params={
        "where": WHERE,
        "outFields": "Unit_Nm,Des_Tp,Mang_Name,Pub_Access,GIS_Acres,Src_Date",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "geojson",
    },
    timeout=60,
).json()
gdf = gpd.GeoDataFrame.from_features(resp["features"], crs="EPSG:4326")
assert len(gdf) == count, f"expected {count} features, got {len(gdf)}"
```

### Option B — Geodatabase (fallback / snapshot)

```python
# Download the CO PAD-US 4.1 .gdb.zip from sciencebase.gov, unzip, then:
gdf = gpd.read_file("/tmp/PADUS4_1_StateCO_Geodatabase.gdb",
                    layer="PADUS4_1Combined_Marine_Designation_Easement_Fee_Proclamation_State_CO")
gdf = gdf[gdf["Mang_Name"].isin(["NPS", "DOD"])]
gdf = gdf.to_crs(epsg=4326)
```

### Quick curl verification (for humans)

```bash
curl -s "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0?f=json" \
  | jq '.name, .geometryType'
curl -s "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0/query?where=State_Nm%3D%27CO%27%20AND%20Mang_Name%3D%27NPS%27%20AND%20Des_Tp%20IN%20(%27NP%27%2C%27NM%27%2C%27NRA%27)&returnCountOnly=true&f=json"
```

---

## Ingestion Notes (Python + PostGIS)

**CRS handling.** Pass `outSR=4326` on the REST query and the server returns WGS84 GeoJSON, so the pipeline never reprojects. For the Geodatabase fallback, always call `to_crs(epsg=4326)` after `read_file` — do not trust that the packaged file matches the REST endpoint's CRS. (Same rule as `gmu-source-evaluation.md` L110; same trap as S05.0's pitfalls on NAD83-vs-WGS84 silent offset.)

**Geometry validation.** Run `shapely.make_valid()` on every geometry before insert; expect every CO NP/NM polygon to be a `MultiPolygon` (RMNP has noncontiguous fragments along the eastern boundary; Dinosaur NM straddles the CO/UT line and CO-side fragments are multi-part). Use `geography(MultiPolygon, 4326)` per the project's MT precedent. GeometryCollection results from `make_valid()` raise loudly per S02.4 / S05.2's `ColoradoGeometryError` pattern.

**`kind`** = `'restricted_area'` per existing `geometry.kind` enum. Per the E05 epic § "Story flow" item #3, V1 binds as `role='other_overlay'` until the ADR-021-candidate (`'no_hunt_zone'` enum addition) resolves.

**Deterministic ID pattern.** Per S05.4 AC: `CO-restricted-{slug}-geom`, where `{slug}` is derived from `Unit_Nm` via the standard slugification rule (lowercase, hyphenate). Example: Rocky Mountain National Park → `CO-restricted-rocky-mountain-national-park-geom`. Lock the slug map by committing a regression test asserting each of the 9 V1 candidates produces its expected id.

**Attribute schema (relevant fields).**

| Field | Type | Purpose |
|---|---|---|
| `Unit_Nm` | String | Park / monument / installation name — drives the slug |
| `Des_Tp` | String | Designation type code (NP, NM, NRA, MIL, NWR, etc.) |
| `Mang_Name` | String | Managing agency (NPS / DOD / FWS) — provenance |
| `Pub_Access` | String | RA / OA / XA codedValue — **access posture, not a hunting determination**. Per PAD-US codedValue domain (verified 2026-06-03), `RA = "Restricted Access"` is officially defined as "requires a special permit from the owner for access, a registration permit on public land or has highly variable times when open to use"; `OA = "Open Access"` is "no special requirements for public access (may include regular hours of availability)"; `XA = "Closed"` is "no public access is allowed". Hunting is a separate determination from access (e.g., RMNP is `OA` but no-hunt; Browns Park NWR is `RA` and hunt-allowed-by-permit). Informational only — not the no-hunt discriminator. |
| `GIS_Acres` | Integer | Sanity-check area; recompute in PostGIS with `ST_Area(geom::geography)/4046.86` and compare ±1% |
| `Src_Date` | String | Source date for the underlying agency submission — capture as `source.publication_date` per ADR-014 |
| `OBJECTID`, `Source_PAID`, `WDPA_Cd` | various | Drop — internal / WDPA cross-ref |

**`verbatim_rule` content.** Per ADR-008 + S05.4 AC, populate from CPW's Big Game brochure citation for each no-hunt zone. **DEFER — exact brochure phrasing unconfirmed.** The 2026 brochure URL is unresolved as of 2026-06-03 (see Blocking Issue #3 below); the exact wording will be confirmed at S05.4 implementation time once the brochure is in hand. If the brochure says "national parks are closed" generically (not per-park), then `verbatim_rule` is the same string on the 9 NPS rows — fine per ADR-008 but worth confirming, because the alternative (per-park named sentences) generates 9 distinct `verbatim_rule` values. If both a per-zone REG paragraph AND a COMMENTS-style annotation exist in the brochure, combine per ADR-015's `\n\n--- COMMENTS ---\n\n` separator rule. Store the brochure sentence verbatim as `verbatim_rule` and let `source.document_type='annual_regulations'` reflect the CPW provenance — even though the *geometry* comes from PAD-US. The `source` field is the regulatory authority for the prohibition; PAD-US is the geometric authority. This is the same split MT's `ADMBND_HD_CWD` ingestion handled in S02.4 (geometry from MT-FWP layer; verbatim rule from FWP DEA brochure).

**Idempotency.** Key on the deterministic id. On refresh, upsert and track `Src_Date` to detect when PAD-US receives a new NPS submission.

**Boundary-to-boundary nearby predicate (for E06's binding loader).** Per the E05 epic §S05.4 story-flow item #5 and S03.10 pitfall C, the canonical predicate is:

```sql
extensions.ST_DWithin(zone.geom, gmu.geom, 5000)
```

on the native `geography` type, **boundary-to-boundary**, NOT centroid-to-centroid. RMNP's centroid sits ~30 km deep in the park; a centroid-to-centroid 5km query would return zero matches for every CO NP. E06's binding loader picks this up; this doc records the predicate for posterity.

---

## Source-drift detection

PAD-US is a live FeatureServer with no stable ZIP — there is no SHA-256 to pin the way S05.0 pinned the TIGER state ZIP. Three drift-detection components compose the V1 mitigation:

**(a) FeatureServer-level `editingInfo.lastEditDate`.** The layer metadata endpoint returns `editingInfo.lastEditDate` as the canonical service-level drift signal. Live-as-of value captured 2026-06-03: **`2026-04-22T18:06:27Z`** (epoch ms `1776881187078`); `dataLastEditDate` = `2026-04-21T01:16:26Z`. The V1 loader should capture this value into `source.dataset_last_edited` (or equivalent provenance field) on every ingest run and emit a WARNING log if the value changed since the prior run. A change indicates USGS pushed an update — operator reviews before re-ingesting.

**(b) Per-feature `Src_Date` capture.** Each feature carries its own `Src_Date` field, which is the date the underlying agency (NPS / FWS / DOD) submitted the boundary to USGS. Capture this as a row-level drift signal alongside the FeatureServer-level `lastEditDate`. A FeatureServer `lastEditDate` change with no corresponding `Src_Date` change usually means metadata or schema-housekeeping rather than boundary movement; a `Src_Date` change on an NPS row means NPS actually re-submitted the park boundary.

**(c) Fallback: USGS per-state Geodatabase SHA-pin.** USGS publishes per-state ESRI Geodatabases at `https://www.sciencebase.gov/catalog/file/get/<id>` for the PAD-US 4.1 release (`https://www.sciencebase.gov/catalog/item/652d52f0d34ee4b6e05cca58`). These ARE stable downloads that can be SHA-256-pinned per S05.0's TIGER ZIP precedent. If a future story needs reproducible offline snapshotting (M2 audit, year-over-year diff, compliance evidence), shift to the Geodatabase as the authoritative pinned artifact and the FeatureServer becomes a freshness probe.

---

## Live Probe Evidence (2026-06-03)

All probes executed against live endpoints; results inline.

### Path 1 — CPWAdminData service root catalog scan → **NO** (no statewide restricted-area layer)

Re-scanned the same 30-layer catalog enumerated by S05.3 (`ingestion/states/colorado/cwd-source-discovery.md` lines 27-59). No layer matches `restricted|no.hunt|no.hunting|preserve|sanctuary|closed|prohibited`. The closest candidate, **layer 5 "CPW Managed Properties (public access only)"**, has 928 features broken down by `PropType`: `STL` 410, `SWA` 324, `Recreation Area` 51, `SP` 49, `Fishing Access` 47, `SFU` 15, `Other` 13, `SAA` 13, `WWA` 3, `Hunting Access (Non-STL)` 2, `State Park` 1. These are **hunt-allowed CPW properties** (State Wildlife Areas, leased Hunting Access lands, State Trust Lands) — the inverse of what S05.4 is looking for. Even the 49 SPs and 1 SP-spelled-out feature (49 State Park polygons + the malformed 50th entry "North Sterling State Park") represent the CPW-state-park boundary network as a property dataset, not a no-hunt regulatory layer.

The broader CPW org service catalog (`orgid:ttNGmDvKQA7oeDQ3`, **703 total items** per live `arcgis.com/sharing/rest/search` on 2026-06-03) was scanned for `restrict|no.?hunt|preserve|sanctuary|closed|prohibit|wildlife.?area|state.?park|national.?park|park|swa|refuge|safety|monument|recreation` and returned only one name-pattern match for "Restricted Areas": **`Snake_River_RFW_Boundary_with_Restricted_Areas`**, which on inspection is a **property-specific structure-buffer dataset (4 features)** for one Recreation/Fishing/Wildlife property — not a statewide hunting-restriction layer. Out of V1 scope.

A narrower ArcGIS Online search (`orgid:ttNGmDvKQA7oeDQ3 (restricted OR "no hunting" OR closed OR prohibited)`) returned **17 hits** (verified 2026-06-03), none of which are a statewide no-hunt-zone layer. `CPWArtificalLightUseClosure_DRAFT` is the closest by name; it is a predator-hunting-equipment closure layer, not a no-hunt boundary, and is DRAFT.

### Path 2 — PAD-US filter to CO + designation_type → **YES (recommended path)**

Service: `https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0` (PAD-US 4.1, USGS-authoritative, owner `mcroft@usgs.gov_USGS`).

**`State_Nm = 'CO' AND Mang_Name = 'NPS'` (no `Des_Tp` filter) → 13 features** (verified 2026-06-03). The 10 V1-relevant rows match `Des_Tp IN ('NP','NM','NRA')`; the 3 additional rows (1 NCA + 2 HCAs) are filtered out for V1 — see §"V1 filter rationale" below the table.

| Des_Tp | Unit_Nm | Mang_Name | GIS_Acres | Pub_Access | V1? |
|---|---|---|---|---|---|
| NP | Rocky Mountain National Park | NPS | 265,475 | OA | ✓ |
| NP | Great Sand Dunes National Park | NPS | 104,902 | OA | ✓ |
| NP | Mesa Verde National Park | NPS | 53,445 | OA | ✓ |
| NP | Black Canyon of the Gunnison National Park | NPS | 30,272 | OA | ✓ |
| NM | Dinosaur National Monument | NPS | 150,671 | OA | ✓ |
| NM | Colorado National Monument | NPS | 20,448 | OA | ✓ |
| NM | Florissant Fossil Beds National Monument | NPS | 6,264 | OA | ✓ |
| NM | Hovenweep National Monument | NPS | 369 | OA | ✓ |
| NM | Yucca House National Monument | NPS | 36 | OA | ✓ |
| NRA | Curecanti National Recreation Area | NPS | 1,120 | OA | ✗ (NPS NRAs permit hunting per 36 CFR §2.2 unless specifically closed — see Outcome §) |
| NCA | Great Sand Dunes National Preserve | NPS | 41,702 | OA | ✗ (National Preserve hunt-ambiguous per NPS Organic Act — see V1 filter rationale) |
| HCA | Bent's Old Fort National Historic Site | NPS | 767 | RA | ✗ (small acreage; non-hunting-relevant historic site) |
| HCA | Sand Creek Massacre National Historic Site | NPS | 6,489 | RA | ✗ (small acreage; non-hunting-relevant historic site) |

**V1 filter rationale (`Des_Tp IN ('NP','NM','NRA')`):** the V1 scope filter drops 3 NPS-managed rows. **Great Sand Dunes National Preserve (NCA)** is hunt-ambiguous: National Preserves are a hybrid NPS designation where hunting may be authorized by the enabling legislation; the Preserve sits adjacent to (not inside) Great Sand Dunes NP and warrants a focused M2 inclusion review against the Great Sand Dunes Act of 2000. **Bent's Old Fort NHS** (767 ac) and **Sand Creek Massacre NHS** (6,489 ac) are non-hunting-relevant historic sites — small-acreage HCAs whose regulatory boundaries do not appear in hunting brochures. Filtering them out keeps the V1 set semantically tight ("places hunters might inadvertently hunt and shouldn't"), not "every NPS-managed parcel in CO."

**`State_Nm = 'CO' AND Des_Tp = 'MIL'` → 11 features**: United States Air Force Academy (18,519 ac), Fort Carson (137,937 ac), Piñon Canyon Maneuver Site (235,507 ac), Pueblo Chemical Depot, Buckley SFB, Peterson SFB, Schriever AFB, Cheyenne Mountain SFS, Rocky Mountain Arsenal, Farish Memorial Recreational Annex, AFA Auxiliary Airfield. All `Pub_Access='XA'` (Restricted/no public access).

**`State_Nm = 'CO' AND Mang_Name = 'FWS'` → 26 features (13 distinct units)** with `Pub_Access='RA'` (verified 2026-06-03). The FeatureServer emits each unit twice — once as a fee parcel and once as a designation/proclamation overlay — so **dedupe on `Unit_Nm` before ingestion**. The 13 distinct units are: Alamosa NWR, Arapaho NWR, Baca NWR, Browns Park NWR, Colorado River WMA (NCA), Hotchkiss National Fish Hatchery (FOTH), Leadville National Fish Hatchery (FOTH), Monte Vista NWR, National Black-Footed Ferret Conservation Center (FOTH), Rocky Flats NWR, Rocky Mountain Arsenal NWR, San Luis Valley Conservation Area, Two Ponds NWR. NWR hunting is determined per-refuge by FWS regulations — **not all CO NWRs are no-hunt; some allow elk/deer/pronghorn hunts under FWS rules. PM scoping required before V1 ingestion.**

### Path 3 — CPW Big Game brochure PDF hand-trace fallback → **NOT NEEDED (Path 2 succeeded)**

The 2026 CPW Big Game brochure landing page (`https://cpw.state.co.us/regulations/hunting/regulations-brochures`) was not resolvable via WebFetch — all four URL guesses returned HTTP 404 on 2026-06-03 (see Blocking Issue #1). Operator must navigate to the brochures index in a browser and resolve the 2026 brochure's actual URL **before S05.4 begins**.

Per ADR-001's hand-trace-rejection rule, hand-tracing a prevalence map is rejected, but a regulatory boundary IS allowed (per S02.5 precedent). However, **Path 2 already succeeds with authoritative geometry**, so Path 3 is not needed for V1 — the brochure's role is to supply the `verbatim_rule` text (CPW's regulatory citation that "no hunting" applies in each named NP), not the geometry itself.

---

## Outcome Disposition

**(c) — No-hunt zones discovered; triggers `role='no_hunt_zone'` ADR proposal.**

Per S05.4 AC #3 outcome (c): "**No-hunt zones discovered (e.g., RMNP, Mesa Verde NP, Great Sand Dunes NP, etc.)** → pause and surface ADR proposal for `role='no_hunt_zone'` enum addition; until ADR resolves, ingest with `role='other_overlay'` per current DDL (matches MT V1 disposition); flag-and-discuss with human before adopting silently."

**Why outcome (c) is load-bearing — the semantic-precision argument.** NPs and NMs are PERMANENT regulatory boundaries: statutory closure under the NPS Organic Act (16 USC §1) plus per-park enabling legislation. The Air Force Academy is a similarly hard boundary under DOD installation-access rules. By contrast, MT V1's `role='other_overlay'` mixes two semantically distinct surfaces — archery-only restrictions inside HDs (weapon-type modifier) and 3 federal no-hunt zones (categorical closure). For an agentic client answering "can I hunt at this coordinate?" via the `check_land_status` MCP tool (ADR-002), `other_overlay` cannot distinguish "this rule restricts your weapon" from "you cannot hunt here at all." Adding `'no_hunt_zone'` as a distinct role preserves semantic precision in the response envelope. The volume argument (CO has more no-hunt zones than MT) is a noise correlate; the load-bearing argument is the role-semantic split that V1 Colorado forces.

**Named zones that trigger the ADR** (V1-priority scope; 10 candidates):

1. Rocky Mountain National Park (RMNP) — 265,475 ac, NPS
2. Mesa Verde National Park — 53,445 ac, NPS
3. Great Sand Dunes National Park — 104,902 ac, NPS
4. Black Canyon of the Gunnison National Park — 30,272 ac, NPS
5. Florissant Fossil Beds National Monument — 6,264 ac, NPS
6. Colorado National Monument — 20,448 ac, NPS
7. Dinosaur National Monument — 150,671 ac, NPS (straddles CO/UT)
8. Hovenweep National Monument — 369 ac, NPS (straddles CO/UT)
9. Yucca House National Monument — 36 ac, NPS
10. United States Air Force Academy — 18,519 ac, DOD

**Curecanti National Recreation Area is definitively dropped from V1.** Per NPS general regulatory framework (16 USC §460 family of statutes; 36 CFR §2.2), NRAs permit hunting unless specifically closed; Curecanti is not closed in its general regulatory scheme. If Curecanti has a partial closure overlay published by NPS (e.g., dam-safety zones around Blue Mesa Reservoir), that's the S05.4 row — not the whole NRA. Investigate at S05.4 implementation time.

**M2-expansion candidates (PM scoping required before V1 inclusion):**

- 10 additional DOD installations (Fort Carson, Piñon Canyon, etc.) — generally no-hunt by access posture (`XA`), but Fort Carson hosts a managed military-recreation hunt program; case-by-case
- 13 FWS-managed distinct units (NWRs + fish hatcheries; 26 raw feature rows pre-dedupe) — per-refuge hunting determination; Browns Park NWR and Monte Vista NWR have managed hunt programs; PM to scope which are V1 no-hunt vs. hunt-allowed-by-permit
- 1 NPS National Preserve (Great Sand Dunes National Preserve, 41,702 ac) — hunt-ambiguous per NPS Organic Act + Great Sand Dunes Act of 2000; warrants focused inclusion review
- **State Parks** — out of V1 scope because CPW publishes them in `CPWAdminData` layer 5 ("Managed Properties") as hunt-allowed-by-permit; per-park no-hunt sub-zones are M2 work pending a separate state-park-restrictions evaluation

**PM recommendation:** scope V1 to the 4 NPs + 5 NMs + Air Force Academy = **9 zones** (Curecanti dropped per the NPS-NRA hunt-permitted default), surface the ADR proposal, and defer NWR / additional DOD / National Preserve scoping to E06 if the volume becomes operationally relevant. This is the minimum-volume "the ADR is structurally necessary" trigger; the spec's named candidates (RMNP, Mesa Verde, Great Sand Dunes, Black Canyon, Florissant, AFA) are all included.

---

## MT Contrast

Montana V1 ships 3 federal no-hunt zones (Glacier NP, Sun River WMA, Yellowstone NP) as `role='other_overlay'` per handoff §8 #4 — the recurring carry-forward item that explicitly anticipated this load-bearing semantic decision would surface in Colorado. CO V1 surfaces 9 federal no-hunt zones with semantically clean categorical-closure boundaries, which makes the mixed-semantics weakness of `other_overlay` operationally untenable per the semantic-precision argument under §"Outcome Disposition" above. Other axes are unchanged: verbatim-rule provenance is the state's annual hunting brochure (MT FWP DEA, CO CPW Big Game); geometry provenance is the same federal-authoritative chain; the nearby-binding predicate is identical (`extensions.ST_DWithin(zone.geom, hd_or_gmu.geom, 5000)` on native `geography`, boundary-to-boundary, per S03.10 pitfall C); a new CO loader (`colorado/load_restricted_areas.py`) is the analog of MT's.

---

## Blocking Issues

1. **BLOCKING — 2026 CPW Big Game brochure URL unresolved.** Re-tested 2026-06-03: `https://cpw.state.co.us/regulations/hunting/regulations-brochures`, `https://cpw.colorado.gov/big-game-brochure`, `https://cpw.state.co.us/Documents/RulesRegs/Brochures/BigGame2026.pdf`, and `https://cpw.widen.net/s/k4vplz5dhf/2026-colorado-big-game-brochure` all return HTTP 404. **Elevated to blocking because `verbatim_rule` is the regulatory authority for the no-hunt prohibition, and the `source.id` slug depends on the publication-date cadence** — the `mt-fwp-dea-2026-booklet` precedent (S03.1) showed that cadence-from-URL assumptions silently bit the ingestion adapter. Operator must resolve the canonical 2026 brochure URL **before S05.4 begins**, not at implementation time, so `sources.yaml` and `source.id` are correctly pinned before any rows are written.

2. **PM scoping decision on V1 row count.** The empirical PAD-US filter returns 10 NPS-Des_Tp-eligible + 11 DOD + 26 FWS (13 distinct units) = 47 candidate features pre-dedupe. The recommended V1 set is **9 zones**: 4 NPs + 5 NMs + Air Force Academy (Curecanti dropped per the NPS-NRA hunt-permitted default). PM confirms the inclusion list before S05.4 implementation.

3. **`role='no_hunt_zone'` ADR is a separate deliverable.** Per the no-autonomous-ADR-drafting rule, this research doc names the trigger but does not draft the ADR. The ADR is a human-or-ADR-drafting-session deliverable; until it resolves, S05.4 lands rows as `role='other_overlay'` per current DDL (matching MT V1).

4. **NWR per-refuge scoping.** 8 of the 13 distinct FWS units are NWRs; hunting is determined per-refuge by FWS. Some CO NWRs (e.g., Browns Park, Monte Vista) host managed hunts; ingesting all 8 as `role='no_hunt_zone'` would be wrong for the hunt-allowed subset. Defer NWR scoping to M2.

5. **DOD installation scoping beyond AFA.** Fort Carson hosts a managed military-recreation hunt program; Piñon Canyon is closed to public hunting but is an Army training area, not a civilian no-hunt zone in the same sense as a National Park. AFA is the unambiguous V1 case per the E05 epic's named candidates; the other 10 DOD units defer to M2.

6. **Great Sand Dunes National Preserve (NCA) hunt-ambiguous.** Hybrid NPS designation — hunting may be authorized by Great Sand Dunes Act of 2000 enabling legislation. Adjacent to but not inside Great Sand Dunes NP. Defer to M2 inclusion review.

---

## Confidence Levels

- **PAD-US 4.1 is the authoritative source for federal no-hunt-zone geometry in CO, programmatically retrievable: High.** Live-probed 2026-06-03; service owned by `mcroft@usgs.gov_USGS` on `services.arcgis.com/v01gqwM5QqNysAAi`; `editingInfo.lastEditDate` = 2026-04-22; `/query` endpoint returns valid GeoJSON with `outSR=4326`; CPW does not publish an alternative statewide layer (re-scanned 30-layer `CPWAdminData` catalog + 703-item CPW org catalog).
- **The 9 recommended V1 zones (10-row NPS query minus Curecanti, plus AFA from the DOD query) are accurately scoped: High** on existence and queryability; **Medium** on whether outcome (c) is the only correct interpretation of S05.4 AC #3 (the broader read "CPW or federal authoritative restricted-area layer found" makes (b) a weak runner-up, but the conservative reading is (c) because CPW publishes nothing of its own).
- **Semantic-precision argument supports `role='no_hunt_zone'` ADR proposal: High.** NP/NM/AFA categorical-closure boundaries cannot share a role enum with MT's archery-only intra-HD overlays without losing semantic precision in the `check_land_status` MCP tool response (ADR-002).
- **Licensing safe for commercial use: High.** USGS PAD-US is federal public domain (17 USC §105); no API key, no click-through.
- **No authentication required now or in the near future: Medium-High.** Publicly anonymous on 2026-06-03; ArcGIS services can in principle add auth, so pin the URL and add a monitoring check that fails the build if the endpoint starts returning 401/403 (same posture as gmu-source-evaluation.md L155).
- **NWR + DOD-beyond-AFA + National Preserve scoping is unsettled: Medium-Low.** Per-refuge / per-installation / per-enabling-legislation hunting determinations require agency-specific regulation lookup. Deferring to M2 is the right call; V1 includes only the unambiguous 9 zones.

---

## Source URLs (verified 2026-06-03)

- PAD-US 4.1 Federal Fee Managers Authoritative FeatureServer: `https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Federal_Fee_Managers_Authoritative_PADUS/FeatureServer/0` (HTTP 200; layer name `PADUS4_1FederalFeeMangAuth`; CO NP/NM/NRA query returns 10)
- PAD-US ScienceBase parent item: `https://www.sciencebase.gov/catalog/item/652d52f0d34ee4b6e05cca58` (PAD-US 4.1 release page; per-state Geodatabase downloads)
- CPW `CPWAdminData` FeatureServer root: `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer?f=json` (HTTP 200; 30 layers; no statewide restricted-area layer per S05.3 enumeration)
- CPW `CPWAdminData` layer 5 (managed properties): `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/5` (HTTP 200; 928 features; `PropType` distinct values = STL/SWA/Recreation Area/SP/Fishing Access/SFU/Other/SAA/WWA/Hunting Access (Non-STL)/State Park — all hunt-allowed categories)
- `Snake_River_RFW_Boundary_with_Restricted_Areas`: `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/Snake_River_RFW_Boundary_with_Restricted_Areas/FeatureServer` (HTTP 200; property-specific safety-buffer dataset; 4 restricted-access features; out of V1 scope)
- CPW Big Game brochures index: `https://cpw.state.co.us/regulations/hunting/regulations-brochures` (HTTP 404 on 2026-06-03; operator resolves 2026 PDF URL **before S05.4 begins** per Blocking Issue #1)
- USGS PAD-US overview: `https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview`
