# Colorado GMU Boundaries — Source Evaluation

**Product:** HuntReady
**Target store:** Supabase Postgres + PostGIS, `geography(Polygon, 4326)`
**Pipeline:** Python (geopandas, shapely, requests)
**Date of evaluation:** 2026-04-19

---

## TL;DR

CPW publishes authoritative Game Management Unit boundaries as a **public, unauthenticated ArcGIS Feature Service** that HuntReady can query directly. The service is actively maintained (last edited 2026-04-09), returns the expected ~185 big-game GMUs, and can emit GeoJSON reprojected to EPSG:4326 server-side. **No authentication, API key, or licensing agreement is required.** There is one soft finding: CPW does not attach an explicit machine-readable license to the dataset — we rely on Colorado's Open Records Act default. A one-line email to CPW GIS should be sent before production launch to document permission, but this does not block ingestion.

**Recommendation:** Primary = CPW ArcGIS FeatureServer (layer 6 of `CPWAdminData`). Fallback = the same service's Shapefile export via `geodata.colorado.gov`. Confidence: **High.**

---

## Available Sources

| Source | URL | Format | Native CRS | Last Updated | Licensing | Programmatic retrieval |
|---|---|---|---|---|---|---|
| **CPW ArcGIS FeatureServer (layer 6)** | `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6` | ArcGIS REST (JSON, GeoJSON on request) | EPSG:3857 (Web Mercator); can emit 4326 via `outSR` | 2026-04-09 | No explicit license; implicitly open under Colorado Open Records Act | Yes |
| **Colorado Geospatial Portal (dataset page)** | `https://geodata.colorado.gov/datasets/2c0794ece2ee4c8d9ac1f64cda8d0216_0/about` | Shapefile, GeoJSON, KML, CSV download (same underlying service) | As packaged (Shapefile typically ships EPSG:3857 or NAD83 — verify `.prj` on download) | Mirrors the FeatureServer | Same as above | Yes (stable download URL) |
| **CPW Maps & GIS landing page** | `https://cpw.state.co.us/maps-and-gis` | Links to Shapefile + Layer Package downloads | Inherited from packaged file | Mirrors the FeatureServer | Same | Partial — human-oriented page, links resolve to the portal above |
| **Colorado GeoLibrary (CU Boulder)** | `https://geo.colorado.edu/catalog/47540-5c78019766d589000aa7d254` | Shapefile, KMZ, GeoJSON, WMS | NAD83 / Colorado Central (EPSG:2232) | **2011 baseline** — stale; do not use for current regulations | Public domain (stated) | Yes | 
| **USGS PAD-US** | `https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview` | GeoPackage, Shapefile | EPSG:4326 | 2024 | Public domain | Yes (but **does not contain hunt units** — PAD-US is protected-area ownership, not harvest management divisions) |
| **data.colorado.gov CPW GMU dataset** | `https://data.colorado.gov/dataset/CPW-GMU-Boundary-Big-Game-/qmpf-gxf8` | N/A | N/A | **Does not exist (404)** | N/A | No — earlier writeups that cite this dataset are incorrect |

---

## Recommended Primary Source

**CPW ArcGIS FeatureServer — `CPWAdminData` service, layer 6 (Big Game GMUs).**

This is CPW's own publishing infrastructure, not a derivative. It was edited ten days ago, contains exactly 186 polygons (matching Colorado's ~185 big-game unit count), and exposes a standard ArcGIS REST `/query` endpoint that accepts `outSR=4326&f=geojson`, so our pipeline never handles a reprojection manually. It needs no credentials.

## Fallback Source

**Shapefile download from the Colorado Geospatial Portal dataset page** (`geodata.colorado.gov/datasets/2c0794ece2ee4c8d9ac1f64cda8d0216_0`). Same underlying data, different delivery mechanism. Use this if the REST service is unreachable for any reason, or if we need a snapshot for offline reproducibility. Geopandas reads the shapefile directly; inspect the `.prj` to confirm which CRS the packaged file carries and reproject to 4326 in Python.

Note: there is no *independent* authoritative fallback — GMU boundaries are exclusively CPW's to define. Colorado GeoLibrary, PAD-US, data.gov, and the previously-cited `qmpf-gxf8` dataset are all either stale, out-of-scope, or nonexistent.

---

## Retrieval Strategy

### Option A — REST query (recommended for the pipeline)

```python
import requests
import geopandas as gpd

BASE = "https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6"

# 1) Sanity-check the feature count before pulling
count = requests.get(
    f"{BASE}/query",
    params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
    timeout=30,
).json()["count"]  # expect ~186

# 2) Page through results (ArcGIS default maxRecordCount is typically 1000-2000)
features = []
offset = 0
PAGE = 2000
while True:
    resp = requests.get(
        f"{BASE}/query",
        params={
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": 4326,         # server-side reprojection to WGS84
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": PAGE,
        },
        timeout=60,
    ).json()
    page_feats = resp.get("features", [])
    features.extend(page_feats)
    if len(page_feats) < PAGE:
        break
    offset += PAGE

gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
assert len(gdf) == count, f"expected {count} features, got {len(gdf)}"
```

### Option B — Shapefile (fallback / snapshot)

The Hub page exposes a "Download → Shapefile" button whose URL is stable once clicked; copy it into the pipeline as a pinned fallback. Then:

```python
gdf = gpd.read_file("/tmp/CPWAdminData_GMU.zip")
gdf = gdf.to_crs(epsg=4326)
```

### Quick curl verification (for humans)

```bash
curl -s "https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6?f=json" | jq '.name, .geometryType, .extent.spatialReference'
curl -s "https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6/query?where=1=1&returnCountOnly=true&f=json"
```

---

## Ingestion Notes (Python + PostGIS)

**CRS handling.** Pass `outSR=4326` on the REST query and the server returns WGS84 GeoJSON, so the pipeline never reprojects. For the Shapefile fallback, always call `to_crs(epsg=4326)` after `read_file` — do not trust that the packaged file matches the REST endpoint's CRS.

**Geometry validation.** CPW polygons are generally clean but assume nothing: run `shapely.make_valid()` on every geometry before insert, and wrap the final `INSERT` with `ST_MakeValid(ST_GeomFromGeoJSON(...))` as a belt-and-suspenders check. Some unit boundaries are multipart (islands or noncontiguous fragments along state lines) — keep them as `MultiPolygon` rather than exploding, because the GMU is the unit of record.

> **Schema tweak:** the task brief specifies `geography(Polygon, 4326)`, but 186-feature verification and prior-art hunt-unit shapes both include multipart polygons. Use `geography(MultiPolygon, 4326)` and cast single polygons on insert (`ST_Multi(...)`). If you keep it as `Polygon`, the pipeline will reject legitimate multi-part units.

**Attribute schema.** The service exposes 16 fields; the useful ones are:

| Field | Type | Purpose |
|---|---|---|
| `GMUID` | Integer | Unit number — primary business key |
| `COUNTY` | String | County affiliation |
| `ELKDAU`, `DEERDAU`, `ANTDAU`, `MOOSEDAU`, `BEARDAU`, `LIONDAU` | String | Data Analysis Unit for each species (useful for future species-level joins) |
| `EDIT_DATE`, `INPUT_DATE` | Date | CPW's own edit timestamps — capture these for change detection |
| `AcresGISCa`, `SqMilesGIS` | Double | GIS-calculated area; recompute in PostGIS with `ST_Area(geom::geography)/2589988.1` and compare as a sanity check |
| `GlobalID`, `OBJECTID` | GUID / Integer | Drop — ArcGIS-internal |

Normalize to snake_case on the way in. Drop `SHAPE_Length`/`SHAPE_Area` if present.

**Idempotency.** Key on `GMUID`. On refresh, upsert by `GMUID` and track `EDIT_DATE` to detect which units actually changed between runs — avoids a full-table churn.

**Paging.** ArcGIS enforces `maxRecordCount` (observed as 1000–2000 on CPW's service). Always page, even when the unit count is small, so the pipeline stays correct if CPW adds layers later.

---

## Blocking Issues

**None that block ingestion.** The following are worth documenting but do not prevent shipping:

1. **No explicit license statement on the dataset.** The ArcGIS item's `licenseInfo` and `accessInformation` fields are null. The dataset is implicitly open under Colorado's Open Records Act, and the CPW Maps & GIS page distributes these files without paywall or click-through, but there is no CC0/CC-BY banner to cite. **Action:** send a short email to CPW's GIS contact (listed on `cpw.state.co.us/maps-and-gis`) confirming redistribution in a commercial hunt-planning product and retain the reply. This is a hygiene step, not a gate.

2. **Schema mismatch in the original spec.** The brief assumes `geography(Polygon, 4326)`; real CPW data includes multi-part units. Switch to `geography(MultiPolygon, 4326)` before writing the migration.

3. **No independent fallback exists.** Because GMUs are definitionally a CPW artifact, both our primary and fallback resolve to the same authority, just via different delivery mechanisms (REST vs. Shapefile export). If CPW's portal is down globally, the pipeline has no alternative — acceptable risk for a non-realtime dataset updated roughly once per year.

4. **Earlier writeups citing `data.colorado.gov/dataset/...qmpf-gxf8` are wrong.** That dataset 404s. Anyone reading prior research notes should ignore it.

---

## Confidence Levels

- **Source exists and is authoritative: High.** The FeatureServer was queried directly; 186 features, edit date 2026-04-09, CPW-owned `services5.arcgis.com` org.
- **Currency meets the "within 1 year" bar: High.** Last edit is ten days old.
- **Programmatic retrieval works as described: High.** The `/query` endpoint was hit live with `returnCountOnly` and `f=geojson` and returned valid responses.
- **Licensing is safe for commercial use: Medium.** No explicit license. Relies on Colorado public-records default plus CPW's de facto open distribution. Email to CPW GIS closes the loop.
- **No authentication required now or in the near future: Medium-High.** Publicly anonymous today; ArcGIS services can in principle add auth, so pin the URL and add a monitoring check that fails the build if the endpoint starts returning 401/403.
