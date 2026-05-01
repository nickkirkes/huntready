# CWD Source Discovery — Montana

## Investigation Date
2026-05-01

## Path Taken
**Path A — Dedicated ArcGIS Online Feature Service** (`ADMBND_HD_CWD`). A public, MT FWP-owned Feature Service with CWD zone polygon geometries was found on ArcGIS Online. It is the authoritative GIS source for CWD management hunt areas. No hand-tracing or discriminator filtering is required.

---

## ArcGIS Root Catalog Findings

- **Date queried:** 2026-05-01
- **URL:** `https://fwp-gis.mt.gov/arcgis/rest/services?f=json`
- **HTTP status:** 200
- **Folders inspected:** admbnd, cnsvtn, energy, fish, fwplnd, refrnc, toolboxes, Utilities, wild (all 9)

### Per-folder service inventory

| Folder | Services found | CWD match? |
|--------|---------------|-----------|
| admbnd | `admbnd/huntingDistricts` (MapServer) | No |
| cnsvtn | (empty) | No |
| energy | (empty) | No |
| fish | fishViewer, waterRightsPods, yctStatus (MapServer + FeatureServer variants) | No |
| fwplnd | `fwplnd/fwpLands` (MapServer) | No |
| refrnc | hydrography, riverMiles (MapServer) | No |
| toolboxes | appPrintSyncJs, waterbodyLocationEditor (GPServer) | No |
| Utilities | GeocodingTools, Geometry, OfflinePackaging, PrintingTools, RasterUtilities, Symbols | No |
| wild | bigGameDistribution, EOSageGrouse, hpNewAccessPrograms\_MIL, hpNewBMA\_MIL, uplandGameBirdDistribution (MapServer) | No |

### huntingDistricts layer scan (39 layers)

All 39 layers in `admbnd/huntingDistricts/MapServer` were individually queried (`?f=json`) and their `name`, `description`, and `fields` were checked for `cwd|chronic|wasting|disease` (case-insensitive). **Zero matches.** This confirms the empirical finding from S02.4: layer #2 (`Big Game Restricted Areas`) has zero CWD rows.

### bigGameDistribution layer scan (27 layers)

All 27 layers inspected by name. Layers cover species distribution ranges (Antelope, Bighorn Sheep, Bison, Black Bear, Elk, Moose, Mountain Goat, Mountain Lion, Mule Deer, White-tailed Deer, Wolf). **Zero CWD matches.**

- **Services matching `cwd|chronic|wasting|disease`:** None on `fwp-gis.mt.gov`
- **Decision:** `fwp-gis.mt.gov` does not host a dedicated CWD layer. CWD zone data is published separately on ArcGIS Online under the `MtFishWildlifeParks` organization account.

---

## Hub Catalog Findings

- **Date queried:** 2026-05-01

### Query attempts

| # | URL | HTTP status | Result |
|---|-----|-------------|--------|
| 1 | `https://hub.arcgis.com/api/v3/datasets?q=cwd&filter[owner]=mtfwp&page[size]=20` | **502 Bad Gateway** | Hub v3 API unavailable at time of query |
| 2 | `https://gis-mtfwp.hub.arcgis.com/api/v3/datasets?q=cwd&page[size]=20` | **502 Bad Gateway** | MT FWP Hub site v3 API also unavailable |
| 3 | `https://opendata.arcgis.com/api/v2/datasets?q=cwd+montana&page[size]=10` | **504 Gateway Timeout** | opendata.arcgis.com v2 timed out |
| 4 | `https://www.arcgis.com/sharing/rest/search?q=chronic+wasting+disease+montana+owner:mtfwp&f=json&num=10` | 200 | **Total: 0** — no results with owner filter applied to sharing REST |
| 5 | `https://www.arcgis.com/sharing/rest/search?q=chronic+wasting+disease+montana&f=json&num=10` | 200 | **Total: 36** — multiple MT FWP CWD items found (see below) |
| 6 | `https://www.arcgis.com/sharing/rest/search?q=cwd+montana+fwp&f=json&num=10` | 200 | **Total: 6** — narrower match, confirmed key item |

### Datasets matching `cwd` owned by `MtFishWildlifeParks` (query 5)

| Item ID | Title | Owner | Type |
|---------|-------|-------|------|
| `8837c07298054f5e8be2e072681d870c` | **Chronic Wasting Disease Hunt Areas** | MtFishWildlifeParks | **Feature Service** |
| `95048f5c6eac4985a1a0ac56771b2ec6` | Chronic Wasting Disease Dashboard Table | MtFishWildlifeParks | Feature Service |
| `e56feeed506c451d8fe74f0b4009cb58` | Hunter Harvest Check Stations for CWD Surveillance \_PublicView | MtFishWildlifeParks | Feature Service |
| `81f46b65f0f8414eb3c9895fb371dbd9` | Carcass Disposal Sites In Montana\_PublicView | MtFishWildlifeParks | Feature Service |
| `c8f7c79dd63d45b2a2dea3aebee75300` | Chronic Wasting Disease (CWD) Sampling Information Map | MtFishWildlifeParks | Web Map |
| `3f6c973ff61d4010b2c0bab598d5d9bb` | Chronic Wasting Disease (CWD) Monitoring and Management Information Map | MtFishWildlifeParks | Web Map |
| `a9ef899bdc7b4960821804d7c4b9f6e5` | Chronic Wasting Disease (CWD) Samples Collected in Montana Map | MtFishWildlifeParks | Image |
| `40a0406dc5904ba08bee646f9a156ffa` | Chronic Wasting Disease (CWD) Samples by Deer/Elk Hunting District Map | MtFishWildlifeParks | Image |
| `ccd4d1ee5d7e47bbb16e431102468173` | Chronic Wasting Disease (CWD) Testing Information Dashboard | MtFishWildlifeParks | Dashboard |

### Selected item: Chronic Wasting Disease Hunt Areas

- **ArcGIS Online item:** `https://www.arcgis.com/home/item.html?id=8837c07298054f5e8be2e072681d870c`
- **Feature Service URL:** `https://services3.arcgis.com/Cdxz8r11hT0MGzg1/arcgis/rest/services/ADMBND_HD_CWD/FeatureServer`
- **Access:** public
- **Snippet:** "For display and/or analysis of hunt areas associated with MT FWP Chronic Wasting Disease management. Note these areas are special management hunts with specific rules and regulations, with limited hunt dates."
- **Tags:** admbnd, chronic wasting disease, cwd, deer, elk, hunt, hunting, montana, moose, mtfwp, mtfwp open data
- **Created:** 2021-12-13 | **Modified:** 2026-04-21 (epoch 1774411267000)

### Layer 0: Chronic Wasting Disease Hunt Areas (esriGeometryPolygon)

| Field | Type | Notes |
|-------|------|-------|
| OBJECTID | esriFieldTypeOID | |
| AREANAME | esriFieldTypeString (50) | Zone name, e.g. "Libby CWD Management Zone" |
| AREATYPE | esriFieldTypeString (50) | Always "CWD Management Hunt Area" |
| SQMILES | esriFieldTypeInteger | Area in square miles |
| REG | esriFieldTypeSmallInteger | FWP region number |
| WEBPAGE | esriFieldTypeString (60) | Always `http://fwp.mt.gov/cwd` |
| VALID_DATES | esriFieldTypeString (60) | NULL for both current features |
| REGYEAR | esriFieldTypeString (50) | Regulation year; both features = "2026" |

### Feature inventory (as of 2026-05-01)

| OBJECTID | AREANAME | AREATYPE | SQMILES | REG | REGYEAR | BBox (lng) | BBox (lat) |
|----------|----------|----------|---------|-----|---------|------------|------------|
| 967 | Libby CWD Management Zone | CWD Management Hunt Area | 499 | 1 | 2026 | -115.80 to -115.29 | 48.16 to 48.64 |
| 968 | Kalispell CWD Management Zone | CWD Management Hunt Area | 154 | 1 | 2026 | -114.44 to -114.15 | 48.20 to 48.41 |

- **Total feature count:** 2 (confirmed via `returnCountOnly=true`)
- **Historical records (REGYEAR ≠ '2026'):** 0 — layer contains only current-year features
- **Distinct REGYEAR values:** `['2026']`
- **Geometry type at source:** `esriGeometryPolygon`, WKID 3857; fetched as GeoJSON with `outSR=4326`
- **Ring complexity:** Libby = 5,602 points (single ring); Kalispell = 4,541 points (single ring)

- **Decision:** Path A confirmed. This dedicated Feature Service is the authoritative GIS source for CWD management hunt area polygons. It is public, maintained by MtFishWildlifeParks, and updated as recently as 2026-04-21.

---

## Layer #2 CWD Row Count (T2 result)

**0** — confirmed by S02.4 live load and by the per-layer scan above. `admbnd/huntingDistricts/MapServer/2` (`Big Game Restricted Areas`) has no rows where `is_cwd_feature()` returns True. CWD zones are not embedded in layer #2; they live in the dedicated `ADMBND_HD_CWD` FeatureServer on ArcGIS Online.

---

## Path Decision Rationale

**Path A — Dedicated ArcGIS Online Feature Service.**

The `ADMBND_HD_CWD` FeatureServer (item `8837c07298054f5e8be2e072681d870c`) is:
- Public, no authentication required
- Maintained by the authoritative agency (`MtFishWildlifeParks`)
- GeoJSON-queryable with `outSR=4326`
- Contains exactly the zone polygon geometries required (Libby, Kalispell)
- Updated 2026-04-21 — current regulation year

No discriminator filtering is needed (this is a single-purpose layer). No hand-tracing required.

---

## Discriminator Predicate (if Path B)

N/A — Path A selected. The `is_cwd_feature` predicate in `cwd_discriminator.py` is not used for this ingestion path. It remains available as an inverse filter guard in `load_restricted_areas.py` (S02.4) to prevent double-loading.

---

## Hand-Traced Source URL / PDF Reference (if Path C)

N/A — Path A selected. The FWP CWD regulations page (`https://fwp.mt.gov/cwd`) is the human-readable companion and should be used as `SourceCitation.url` alongside the GIS layer citation.

---

## Zone Names and Test Points (UAT Spec)

Spatial query validation performed live against the FeatureServer (2026-05-01):

| Zone | OBJECTID | SQMILES | Test point (lng, lat) | Expected ST_Covers result |
|------|----------|---------|----------------------|--------------------------|
| Libby CWD Management Zone | 967 | 499 | (-115.555, 48.388) | TRUE — point confirmed inside via ArcGIS spatial query |
| Kalispell CWD Management Zone | 968 | 154 | (-114.320, 48.310) | TRUE — point confirmed inside via ArcGIS spatial query |
| Outside both zones (eastern MT) | — | — | (-106.500, 46.800) | FALSE — 0 features returned |

---

## Manually-Traced Provenance Mechanism (if Path C)

N/A — Path A selected. For Path A ingestion, `SourceCitation` fields are:
- `document_type`: `'gis_layer'` (ADR-014)
- `url`: `https://services3.arcgis.com/Cdxz8r11hT0MGzg1/arcgis/rest/services/ADMBND_HD_CWD/FeatureServer/0`
- `agency`: `Montana Fish, Wildlife & Parks`
- ArcGIS Online item page: `https://www.arcgis.com/home/item.html?id=8837c07298054f5e8be2e072681d870c`
- FWP CWD info page: `https://fwp.mt.gov/cwd` (HTTP 200, resolves correctly)

---

## Initial Load Record

- **Date:** 2026-05-01
- **Loader:** `ingestion/states/montana/load_cwd_zones.py`
- **Path:** A (dedicated `ADMBND_HD_CWD` FeatureServer)
- **First-run result:** 2 features fetched, 2 geometry rows upserted
- **Second-run result (idempotency check):** 2 features fetched, 2 geometry rows upserted (UPSERT on PK; row counts unchanged)
- **CRS warning:** `arcgis.geojson_to_multipolygon_wkt` emitted the magnitude-based detection warning (layer native CRS is EPSG:3857 but `outSR=4326` is requested). Both features pass the WGS84 range check; bbox values are between `-115.80, -114.15` lng / `48.16, 48.64` lat — well outside the equator/prime-meridian ambiguity zone. Per the known pitfall, this warning is acceptable for Montana data. No action.

## UAT Results (executed 2026-05-01)

| # | Query | Test point (lng, lat) | Expected | Actual | Result |
|---|-------|----------------------|----------|--------|--------|
| 1 | Row count | n/a | 2 | 2 | PASS |
| 2 | Validity (`ST_IsValid`) | n/a | both `t` | both `t` | PASS |
| 3 | `ST_Covers` for Libby zone | (-115.555, 48.388) | 1 row, "Libby CWD Management Zone" | `MT-CWD-zone-libby-cwd-management-zone-geom`, "Libby CWD Management Zone" | PASS |
| 4 | `ST_Covers` for Kalispell zone | (-114.320, 48.310) | 1 row, "Kalispell CWD Management Zone" | `MT-CWD-zone-kalispell-cwd-management-zone-geom`, "Kalispell CWD Management Zone" | PASS |
| 5 | `ST_Covers` outside-zone control | (-106.500, 46.800) | 0 | 0 | PASS |
| 6 | Source-citation field listing | n/a | both `document_type='gis_layer'`, `agency='Montana Fish, Wildlife & Parks'`, `license_year=2026` | confirmed for both rows | PASS |

**Spec deviation acknowledged.** The story spec called for three named zones (Libby, South-Central, Northeast). The live FWP CWD layer publishes only two for the 2026 regulation year (Libby, Kalispell). The story spec explicitly permits substitution: "If the actual CWD zone names have changed by execution time, substitute current names and document the substitution. The principle is 'three named zones with assigned test coordinates,' not 'three specific historical names.'" UAT was strengthened by adding an outside-zone negative-control test (#5) to cover both positive and negative `ST_Covers` semantics on the same data.
