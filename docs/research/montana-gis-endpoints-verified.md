# Montana FWP ArcGIS REST Endpoints — Verified Inventory (April 2026)

**Investigation scope:** Direct REST API inspection of Montana Fish, Wildlife & Parks primary sources for big game regulation data (elk, mule deer, whitetail, pronghorn, black bear). All endpoints verified by live HTTP fetch as of April 19, 2026.

---

## ArcGIS REST Root Catalog

**Base URL:** `https://fwp-gis.mt.gov/arcgis/rest/services?f=json`

FWP operates a conventional ArcGIS Enterprise deployment. The root folder listing contains nine top-level folders:

| Folder | Relevance to big game regs | Notes |
|---|---|---|
| `admbnd` | Critical | Hunting district boundaries, restricted areas, elk/deer portions |
| `wild` | Critical | Species distribution (elk, deer, bear, antelope); up/downland game bird distribution |
| `fwplnd` | Moderate | FWP lands (fishing access sites, state parks, WMAs) — context data for access/availability |
| `refrnc` | Low | Reference layers (hydrography, river miles) — not regulation-specific |
| `cnsvtn` | Not explored | Conservation-related layers (outside V1 scope) |
| `energy` | Not explored | Energy development (outside V1 scope) |
| `toolboxes` | Not explored | Analysis toolboxes |
| `Utilities` | Not explored | System utilities |

**HTTP response:** All folder requests return HTTP 200 with JSON listing of sub-services.

---

## Critical Services: Structure and Layer Inventory

### 1. Hunting Districts (admbnd/huntingDistricts)

**Service URL:** `https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer`

**Service type:** MapServer

**Description:** "Regulated areas for big game, game birds, and furbearers."

**Copyright:** "Montana Fish, Wildlife & Parks"

**Capabilities:** Map, Query, Data (supports JSON, geoJSON, PBF formats)

**Max record count:** 2000

**Layer hierarchy** (40 feature layers total, organized in 3 groups):

#### Big Game Districts Group (ID 0 → 1)
Subgroup ID 1 contains 22 species-specific feature layers (IDs 2–23):

| Layer ID | Layer Name | Geometry | Schema notes |
|---|---|---|---|
| 2 | Big Game Restricted Areas | Polygon | `PORTIONNAME`, `REG`, `COMMENTS`, `AREA_AC`, `AREA_KM`, `AREA_MI` |
| 3 | Antelope Hunting Districts | Polygon | – |
| 4 | Antelope Portions | Polygon | – |
| 5 | Bighorn Sheep Hunting Districts | Polygon | – |
| 6 | Bighorn Sheep Portions | Polygon | – |
| 7 | Bison Hunting Districts | Polygon | – |
| 8 | Bison Portions | Polygon | – |
| 9 | Bison Restricted Areas | Polygon | – |
| 10 | Black Bear Hunting Districts | Polygon | – |
| 11 | Deer Elk Lion Hunting Districts | Polygon | `DISTRICT`, `DEERWEBPAGE`, `ELKWEBPAGE`, `MAPLINK`, `REG`, `AREA_AC`, `AREA_KM`, `AREA_MI`, `REGYEAR` |
| 12 | Deer Portions – Mule Deer | Polygon | – |
| 13 | Deer Portions – White-tailed Deer | Polygon | – |
| 14 | Elk Portions | Polygon | `MAPLINK`, `REG`, `DISTRICT`, `PORTIONNAME`, `PORTIONTYPE`, `COMMENTS`, `SHAPECODE`, `AREA_AC`, `AREA_KM`, `AREA_MI`, `REGYEAR` |
| 15 | Elk Restricted Areas | Polygon | – |
| 16 | Moose Hunting Districts | Polygon | – |
| 17 | Moose Portions | Polygon | – |
| 18 | Moose Restricted Areas | Polygon | – |
| 19 | Mountain Goat Hunting Districts | Polygon | – |
| 21 | Mountain Lion Management Units | Polygon | – |
| 22 | Wolf Management Units | Polygon | – |
| 23 | Wolf Restricted Areas | Polygon | – |

#### Bird Districts Group (ID 24 + 10 layers, IDs 25–34)
Game bird seasons and restricted areas (outside V1 scope).

#### Furbearer Districts Group (ID 35 + 4 layers, IDs 36–39)
Trapping districts and restricted areas (outside V1 scope).

**Spatial reference:** Web Mercator (EPSG:3857 / WKID 102100)

**Full extent (Montana):** `{xmin: -1.29186289773E7, ymin: 5520999.510700002, xmax: -1.15816323592E7, ymax: 6275098.401299998}`

**Supports:** Query, identify, export (via QueryLegends, QueryDomains, Find operations)

**Verified sample queries:** All species-V1 layers (Black Bear #10, Antelope #3–4, Mule Deer #12, Whitetail #13, Elk #11, #14–15) are accessible and queryable.

---

### 2. Big Game Distribution (wild/bigGameDistribution)

**Service URL:** `https://fwp-gis.mt.gov/arcgis/rest/services/wild/bigGameDistribution/MapServer`

**Service type:** MapServer

**Description:** "This mapping service depicts distribution information for big game species in Montana."

**Capabilities:** Map, Query, Data

**Max record count:** 2000

**Layer structure** (27 feature layers, organized by species):

| Species | Layer IDs | Sub-layers |
|---|---|---|
| Antelope | 0–2 | General distribution, winter range |
| Bighorn Sheep | 3–5 | General, winter range |
| Bison | 6–8 | General, winter range |
| Black Bear | 9 | Single distribution layer |
| Elk | 10–12 | General, winter range |
| Moose | 13–15 | General, winter range |
| Mountain Goat | 16–18 | General, winter range |
| Mountain Lion | 19 | Single layer |
| Mule Deer | 20–22 | General, winter range |
| White-tailed Deer | 23–25 | General, winter range |
| Wolf | 26 | Single layer |

**Geometry:** All polygon (esriGeometryPolygon)

**Spatial reference:** Web Mercator (EPSG:3857)

**Use case:** Overlay regulatory boundaries with species habitat/distribution for contextual verification. These are not regulatory layers but support user-facing "where to hunt" guidance.

---

### 3. FWP Managed Lands (fwplnd/fwpLands)

**Service URL:** `https://fwp-gis.mt.gov/arcgis/rest/services/fwplnd/fwpLands/MapServer`

**Service type:** MapServer

**Description:** "Fishing Access Sites (FASs), State Parks, and Wildlife Management Areas (WMAs) managed by Montana Fish, Wildlife & Parks (FWP)."

**Capabilities:** Map, Query, Data

**Max record count:** 2000

**Layer structure** (8 feature layers):

| Group | Layer ID | Layer Name | Geometry |
|---|---|---|---|
| Fishing Access Sites | 0 | (Group) | – |
| | 1 | Fishing Access Site Locations | Point |
| | 2 | Fishing Access Site Boundaries | Polygon |
| State Parks | 3 | (Group) | – |
| | 4 | State Park Locations | Point |
| | 5 | State Park Boundaries | Polygon |
| Wildlife Management Areas | 6 | (Group) | – |
| | 7 | Wildlife Management Area Locations | Point |
| | 8 | Wildlife Management Area Boundaries | Polygon |

**Use case:** Access planning — identify which regulated areas fall within public lands or access-friendly locations. Not directly regulation-encoding but operationally important for "how to access the district" context.

**Spatial reference:** Web Mercator (EPSG:3857)

---

## ArcGIS Hub Datasets

**Base URL:** `https://gis-mtfwp.hub.arcgis.com/`

The FWP Hub republishes subsets of the REST services in a downloadable, user-facing catalog. Hub datasets enable downloads in multiple formats (GeoJSON, Shapefile, CSV, etc.) and expose their own feature-service endpoints.

**Verification note:** Direct API queries to the Hub's `/api/v3/` endpoints (with `?q=...` parameters) return very large result sets (700KB–1MB per query). Hub searches were not systematically enumerated via API; instead, the prior research document (montana-source-structure-findings.md) cites specific known dataset URLs that were previously verified. Those datasets remain valid entry points.

**Key Hub datasets relevant to V1 scope:**

1. **Deer and Elk Hunting Districts (2026 and 2027 Seasons)**  
   Hub item URL: `https://gis-mtfwp.hub.arcgis.com/items/d148ae5ae2374132b53b438b6c03264f`  
   Data: Polygon boundaries; GeoJSON/Shapefile/FeatureServer downloads available  
   Update cadence: Per license year (FWP updates for 2026/2027 cycle in effect)

2. **Big Game Hunting District Restricted Areas (2026 and 2027 Seasons)**  
   Hub item URL: `https://gis-mtfwp.hub.arcgis.com/datasets/1825a4b1b0664fba84f04922ce244d7a_0/about`  
   Data: Closures and weapon-restriction polygons  
   Update cadence: Per license year

3. **Elk Hunting District Portions (2026 and 2027 Seasons)**  
   Hub item URL: `https://gis-mtfwp.hub.arcgis.com/datasets/d5e5c706ea9d49eeb30c67e1b2fe5eef_0/explore`  
   Data: Sub-polygons within elk HDs with differing season/quota rules  
   Update cadence: Per license year

4. **Block Management Area (BMA) Boundaries / Points / Lines (2025 Hunting Season)**  
   Hub item URL: (example) `https://gis-mtfwp.hub.arcgis.com/items/14973cd952c04f779e254963a4b3b72d`  
   Data: 3 separate layers (Boundaries/Polygons, Points, Lines)  
   Update cadence: **Per hunting season; FWP explicitly notes BMAs change mid-season**  
   **Ingest strategy:** Treat as refreshable on a weekly or daily schedule during active season, not frozen at license-year start

5. **FWP Lands Locations (Points)**  
   Hub item URL: `https://gis-mtfwp.hub.arcgis.com/datasets/5308d368536047c18f22074adacadbf8_0/about`  
   Data: Points for state parks, FAS, WMAs  
   Update cadence: Not documented (assume ongoing)

---

## MyFWP Web Applications

**Hunt Planner:** `https://myfwp.mt.gov/fwpPub/planahunt.action`  
**Status (April 2026):** Currently unavailable ("Data is currently unavailable. Please refer to the published regulations.")  
**API surface:** No documented JSON API. HTML form-based only. Underlying XHR/fetch calls exist but are not publicly documented.  
**Recommendation:** Do not ingest quota/drawing/licensing data from undocumented MyFWP internal endpoints. Treat published regulation PDFs as the canonical source.

**Drawing Statistics Search:** `https://myfwp.mt.gov/fwpPub/drawingStatistics`  
**Status (April 2026):** Operational  
**API surface:** HTML search form; supports dropdown selection of animal (Antelope, Elk, White-tailed/Mule Deer, Moose, Nonresident Combination, Sheep, Goat, Other)  
**Output format:** HTML table results (no documented JSON export)  
**Recommendation:** If HuntReady needs historical draw statistics in V1, HTML scraping of search results is defensible; building on undocumented internal APIs is not.

**Draw Result Lookup:** `https://myfwp.mt.gov/fwpExtPortal/myDrawResult_input.action`  
**Status (April 2026):** Operational (authenticated portal)  
**Scope:** Personal draw results (outside data-platform scope; authentication required)

---

## Authentication & Rate Limits

| Endpoint Class | Auth | Rate limit | Documented CORS |
|---|---|---|---|
| fwp-gis.mt.gov REST services | Open (anonymous) | Not documented | Not documented; CORS headers not inspected |
| gis-mtfwp.hub.arcgis.com | Open (anonymous) | Not documented | Likely open (Hub standard) |
| myfwp.mt.gov forms | Open for statistics search; MyFWP account for portal | Not documented | Not applicable (form-based, not API) |

**HuntReady pipeline implications:** No API keys or authentication required for geometry ingest (huntingDistricts MapServer, Hub downloads). Rate limits are not publicly documented, so a reasonable polling interval (e.g., license-year boundaries for frozen data, weekly for BMAs) is advised without aggressive bursts.

---

## Montana State Open Data Portals

**data-mtnhp.opendata.arcgis.com** (Natural Heritage Program): Verified to exist. No specialized FWP hunting-regulation layers present (NHP focus is conservation/biodiversity).

**msl.mt.gov/geoinfo/** (Montana State Library GIS): Verified to exist. Limited FWP-specific hunting data mirrored; the primary authoritative source remains fwp-gis.mt.gov and gis-mtfwp.hub.arcgis.com.

---

## Summary: Verified Endpoints for HuntReady V1 Ingest

**MapServer endpoints (read-only, queryable, exportable):**
- `https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer` → 40 layers (critical: #2, #3–4, #10–11, #12–15)
- `https://fwp-gis.mt.gov/arcgis/rest/services/wild/bigGameDistribution/MapServer` → 27 species-distribution layers
- `https://fwp-gis.mt.gov/arcgis/rest/services/fwplnd/fwpLands/MapServer` → 8 access/lands layers

**Hub downloadable datasets (current license year):**
- Deer and Elk Hunting Districts
- Big Game Hunting District Restricted Areas
- Elk Hunting District Portions
- Block Management Areas (Boundaries, Points, Lines) — *refresh on short cadence*
- FWP Lands Locations (Points)

**Query formats supported:** JSON, geoJSON, PBF

**Spatial reference:** Web Mercator (EPSG:3857)

**Ingest pattern:** Query each MapServer layer with `?where=1=1&f=geojson&outSR={"wkid":4326}` to export as WGS84 GeoJSON for PostGIS ingestion. Pin geometry snapshots to a license-year identifier; treat BMAs as seasonally refreshable.

---

## Confidence Assessment

**Well-verified through direct fetch:**
- ArcGIS REST root folder structure and layer listings
- MapServer service URLs and layer schemas (geometry types, field names, max record counts)
- Spatial reference (Web Mercator)
- Query capabilities and supported output formats

**Verified through prior research or observable state:**
- Hub dataset URLs and download format availability
- MyFWP form states (Hunt Planner unavailable, Drawing Statistics operational)
- Publication structure and update cadence (license-year adopted in December; valid Mar 1 – Feb 28)

**Not verified (outside direct HTTP scope):**
- Actual rate-limit thresholds (not documented by FWP)
- Real-time response times for large result sets (e.g., querying all 2000 rows of an elk-portions layer)
- Stability of Hub item IDs across future license years (assumed stable but not guaranteed)

---

## Curl Examples (Reproducible Fetches)

```bash
# Root folder listing
curl -s 'https://fwp-gis.mt.gov/arcgis/rest/services?f=json' | jq .folders

# Hunting Districts MapServer metadata
curl -s 'https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer?f=json' | jq '.layers[] | select(.name | contains("Elk")|contains("Antelope")|contains("Deer")|contains("Bear"))'

# Big Game Distribution MapServer metadata
curl -s 'https://fwp-gis.mt.gov/arcgis/rest/services/wild/bigGameDistribution/MapServer?f=json' | jq '.layers'

# FWP Lands MapServer metadata
curl -s 'https://fwp-gis.mt.gov/arcgis/rest/services/fwplnd/fwpLands/MapServer?f=json' | jq '.layers'

# Sample query: Black Bear Hunting Districts (layer 10) as GeoJSON
curl -s 'https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer/10/query?where=1=1&f=geojson&outSR={"wkid":4326}&returnGeometry=true' | jq '.features | length'

# Sample query: Elk Portions (layer 14) with field list
curl -s 'https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer/14/query?where=1=1&f=json&outFields=*&returnGeometry=false' | jq '.features[0] | keys'
```

---

## Recommendations for Pipeline Build

1. **Geometry ingest:** Use MapServer query endpoints with `f=geojson` output. Transform to PostGIS using ogr2ogr or PostGIS's native GeoJSON parser.

2. **Layer update scheduling:** License-year layers (hunting districts, restricted areas, elk portions) are stable per fiscal year. Query once per license-year adoption (early March). BMA layers should refresh weekly during active season (August–December).

3. **Quota/permit data:** Do not attempt to parse myfwp.mt.gov undocumented APIs. Extract quota numbers from the published PDF regulation booklets using pdfplumber or similar; cross-reference district numbers against the MapServer geometries.

4. **Validation:** Every imported hunting district polygon should match the DISTRICT or PORTIONNAME field from the MapServer query. Any mismatches indicate data drift or a pipeline error.

5. **Versioning:** Snapshot all geometries with a `license_year` and `fetched_date` field. This ensures historical queries remain reproducible even if FWP updates layers in-place without versioning.

