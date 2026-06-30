# Colorado State Ingestion Adapter

E05/E06 ingestion for Colorado Parks & Wildlife (CPW) data. The Colorado
adapter mirrors the Montana adapter pattern at `ingestion/states/montana/`
(see that directory's README for the mature, multi-loader form). This file
documents the S05.1 scaffold; per-loader sections will be appended in
S05.2 / S05.3 / S05.4 as those stories ship.

## Status

| Story | Status | Loader |
|-------|--------|--------|
| S05.0 | Closed (2026-06-01, PR #54, `7f3b071`) | `load_state_boundary.py` — writes `CO-STATEWIDE-geom` from US Census TIGER |
| S05.1 | Scaffold (this file) | — |
| S05.2 | Not started | (planned) `load_gmus.py` — CPW FeatureServer layer 6 |
| S05.3 | Not started | (planned) `load_cwd_zones.py` — pending discovery |
| S05.4 | Not started | (planned) `load_restricted_areas.py` — pending research doc |

## Import path

Per ADR-005, ingestion adapters live under `ingestion/states/<state>/` and
import shared utilities from `ingestion/ingestion/lib/`. The Colorado
adapter follows the same import discipline as Montana:

```python
from ingestion.lib import arcgis, db
from ingestion.lib.schema import Geometry, SourceCitation
```

There is no `ingestion.states.colorado.*` namespace to import from the
shared library — that direction is blocked by `TestNoColoradoLeakIntoSharedLib`
in `ingestion/tests/test_arcgis.py` (added in S05.1). State adapters depend
on the shared library; the shared library never depends on state adapters.

## Operator invocation

State-adapter scripts are invoked as a direct path, NOT via `python -m`
(`states/` is a namespace package, not an installed module — see
`.roughly/known-pitfalls.md`). From the repo root:

```bash
ingestion/.venv/bin/python ingestion/states/colorado/<loader>.py [--dry-run]
```

Required environment variable: `DATABASE_URL` (the service-role Postgres
DSN; the serving stack does not need this — see ADR-003). Optional:
`HUNTREADY_INGESTION_CONTACT` (appended to the User-Agent for outbound
ArcGIS requests as `(contact: <value>)`).

## State-code constant convention

All CO loaders use:

```python
_STATE: Final[str] = "US-CO"
```

This mirrors Montana's `_STATE` convention in `load_jurisdiction_bindings.py`
and the S05.6 scaffold. (Montana's `load_regulation_records.py` predates that
convention and still uses `_MT_STATE_CODE`.) Use `_STATE` for any new Colorado
loader.

## CRS / projection handling

Colorado loaders rely on the shared library's existing global-WGS84 guards
in `ingestion/ingestion/lib/arcgis.py`:

- `arcgis._check_and_fix_projection`: rejects geometries outside the global
  WGS84 envelope with `EPSG:3857`-valid-extent pre-check and declared-CRS
  WARNING discipline.
- Per-host throttle on `services5.arcgis.com` is independent from MT FWP;
  CPW gets its own throttle bucket automatically (`urlparse(service_url).hostname`-keyed).
- Server-side reprojection via `outSR=4326` is hardcoded in fetch params.

A Colorado-bounds-specific `ST_Envelope` check (`[-109.06, -102.04] × [36.99, 41.00]`)
is **deferred to S05.7's analytical layer**, not embedded in S05.2's loader.

## CPW sources

The CPW Big Game GMU layer is the only source registered in S05.1.
Additional CPW layers (CWD zones, restricted areas) are added during
S05.3 / S05.4 after the discovery investigations complete.

| Layer | Service | Layer ID | Document type | Source-citation builder |
|-------|---------|----------|---------------|-------------------------|
| Big Game GMUs | `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer` | 6 | `gis_layer` | `arcgis.build_source_citation(...)` at runtime |

Per ADR-014, `SourceCitation.publication_date` for `gis_layer` entries is
**Jan 1 of REGYEAR** — not the layer's `editingInfo.lastEditDate`. The
SourceCitation is constructed at load time by `arcgis.build_source_citation`,
which derives the publication_date from `license_year`. See
`sources.yaml` for the operator-facing layer registry; the YAML
documents intent and is not the runtime source of truth for `publication_date`.

## Fixtures policy

`ingestion/states/colorado/fixtures/` follows the Montana policy:

| Glob | Status | Rationale |
|------|--------|-----------|
| `*-metadata-*.json` (~7KB) | Committed | drift detection on field names, OID columns, spatialReference |
| `*-manifest-*.json` (~5KB) | Committed | per-fetch checksum manifest for cross-operator drift detection |
| `*-features-*.geojson` (~5-10MB for 186 polygons at S05.2; larger if future CWD/RA layers) | Gitignored | uniform discipline with MT per the ArcGIS Fidelity SHOULD-FIX |

See `fixtures/.gitignore` for the authoritative list.

## Related

- Epic: [`docs/planning/epics/E05-colorado-geometry-ingestion.md`](../../../docs/planning/epics/E05-colorado-geometry-ingestion.md)
- Shared ArcGIS library: [`ingestion/ingestion/lib/arcgis.py`](../../ingestion/lib/arcgis.py)
- ADR-003 (ingestion upstream + offline), ADR-005 (Python ingestion / TS serving), ADR-014 (`SourceCitation.document_type='gis_layer'`)
- Montana precedent (mature multi-loader form): [`ingestion/states/montana/README.md`](../montana/README.md)
