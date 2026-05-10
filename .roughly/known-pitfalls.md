# Known Pitfalls

Project: huntready
Domain: Regulatory data platform for licensed hunting in the US.

Pitfalls discovered through development. Updated by `/roughly:build` and `/roughly:fix` wrap-up stages.

---

## Data & State

### Cross-module `Literal` duplication is sometimes intentional — don't refactor it away

**Symptom:** A static-analysis tool or reviewer flags two modules that define the same `Literal[...]` set as a DRY violation and proposes importing one from the other.

**Cause:** The duplication can be deliberate when the two modules have different dependency weights. Importing the Literal from the heavier module (e.g. `schema.py` with Pydantic models and postgres dependencies) into a lighter module (e.g. `overlays.py` used as a thin type contract by a future consumer) inverts the intended dependency direction.

**Fix:** Before consolidating, check for (a) a docstring in the lighter module saying "kept manually in sync with X" — leave it alone; or (b) a comment naming a specific downstream consumer that imports the lighter module — leave it alone. If neither exists, it may be a genuine DRY violation, but verify import direction first. When the duplication is intentional, the docstring is the contract: both files must be updated whenever the Literal set changes.

Concrete example: `ingestion/ingestion/lib/overlays.py` duplicates `JurisdictionBinding.role` from `schema.py` deliberately so E03 can import only the thin overlay types without pulling in the full schema module. The docstring documents the manual-sync expectation.

Surfaced by S02.6 implementation on 2026-05-01.

### Drift-signal artifacts must write a marker for the empty case

**Symptom:** A reviewer flags that an artifact-writing code path (e.g., `_write_manifest_fixture`, an audit log writer, a fixture builder) skips the write entirely when the input is empty. Operators relying on `git diff` to spot upstream drift see no diff for an N→0 source change — silence looks identical to "no drift, source unchanged."

**Cause:** The natural code path for an empty input is to skip the artifact write ("nothing to record"), but for any artifact whose primary purpose is drift detection or reproducibility verification, that breaks the contract. The artifact must distinguish "source was empty this run" from "this run never happened."

**Fix:** When the artifact's purpose is drift/audit/reproducibility, always write — use a sentinel for the empty case:

- `features_count=0`, `layer_hash=sha256(b"").hexdigest()`, fully-keyed empty histogram (256 zero buckets), other fields populated normally.
- Add a regression test pinning the empty-input behavior so a future refactor doesn't quietly bring back the skip.

The S02.7 manifest writer at `ingestion/ingestion/lib/arcgis.py:780-805` is the canonical example.

Surfaced by S02.7 review on 2026-05-02.

### `verbatim_rule` columns silently accept `""`

Both `JurisdictionBinding.verbatim_rule` and `Geometry.verbatim_rule` are nullable `text` with no SQL CHECK constraint and no Pydantic `@field_validator` to reject empty strings. An ingestion adapter that writes `verbatim_rule=""` will succeed silently, and downstream code using `if x.verbatim_rule:` cannot distinguish "no rule text in source" (intended `NULL`) from "empty rule text in source" (`""`).

State adapters guard at the call site: `_extract_verbatim_rule(props)` in `load_hds.py` and `load_portions.py` returns `None` for missing/empty/whitespace-only `REG`. The schema itself remains permissive.

**Recommended cleanup** (cross-cutting, deferred): add a Pydantic validator that raises if `v is not None and not v.strip()` on both columns. Optionally add `CHECK (verbatim_rule IS NULL OR length(verbatim_rule) > 0)` if a non-Python writer ever appears.

Surfaced by silent-failure-hunter on 2026-04-28.

## Integration — ArcGIS

### Pagination terminator: empty page AND not-exceeded — never page-size

The `fetch_features` page loop in `ingestion/ingestion/lib/arcgis.py` terminates only when `exceededTransferLimit` is `False`/absent AND the page is empty. The naive-looking optimization "stop when fewer-than-page-size returned" silently drops data on layers that report `exceededTransferLimit=True` on the last full page (terminating one page early). The unit test `test_exact_n_times_max_record_count_boundary` exists to lock this in — do not delete or weaken it during refactors that "look like" they'd save a fetch.

Surfaced by epic E02 spec (line 116); validated by S02.1 implementation 2026-04-29.

### `where` clauses: read `metadata.object_id_field`, never hardcode `OBJECTID`

The epic E02 spec example (line 110) shows `where=OBJECTID>=0`, but ArcGIS layers may use `FID`, `OBJECTID_1`, or other names — the actual name is in `metadata.object_id_field`. State adapters that build their own ArcGIS queries (rather than going through `fetch_features`) must use `f"{metadata.object_id_field}>=0"`. A hardcoded `OBJECTID>=0` against a layer whose OID is named `FID` will return a server-side 4xx, or — pathologically — return a different count than the page query, producing a confusing count-mismatch error. The shared library handles this correctly.

Surfaced by `cubic review` + `silent-failure-hunter` on 2026-04-29.

### Layer metadata may omit top-level `objectIdField`

Some ArcGIS MapServers (observed: MT FWP `admbnd/huntingDistricts` layers #3, #10, #11) return layer metadata without the `objectIdField` key at the top level even though the OID column is present in the `fields[]` array as a `type == "esriFieldTypeOID"` entry. `fetch_layer_metadata` falls back to scanning `fields[]` and prefers the canonical `OBJECTID` name when multiple OID-typed fields exist (joined layers, schema-repaired layers with `OBJECTID_1`, etc.); a WARNING is emitted on the fallback so operators can audit. A code path that reads `data["objectIdField"]` directly without the fallback will `KeyError` and halt ingestion on these otherwise-valid servers.

Surfaced by S02.2 live load on 2026-04-30.

### `shapely.make_valid` may produce `GeometryCollection [Polygon, LineString]`

Real-world ArcGIS Polygon layers (observed: MT FWP antelope HD 556, OBJECTID 385) carry self-intersecting source polygons. `shapely.make_valid` repairs them by emitting a `GeometryCollection` containing one `Polygon` (the real geometry) and a `LineString` (the zero-area edge that pokes out at the self-intersection vertex). `geojson_to_multipolygon_wkt` recovers the polygonal part when its area equals the input's area within `math.isclose(rel_tol=1e-6, abs_tol=1e-12)` and emits a WARNING with OBJECTID + attributes; lossy cases (overlapping polygons in a GC where `unary_union.area < sum_of_areas`) still raise.

Raising on every GC would block valid loads. Silently filtering would lose data when the GC carries real polygonal area beyond the unioned coverage. The area-preservation rule preserves ADR-008's "fail loud" discipline for genuinely lossy cases while letting topological-artifact cases through with audit trail. Test coverage in `tests/test_arcgis.py::TestGeojsonToMultipolygonWkt` locks both branches in; do not weaken `abs_tol` to `0.0` (rejects valid tiny polygons due to float noise).

Surfaced by S02.2 live load on 2026-04-30.

### One-off ArcGIS scripts must detect `{"error": {...}}` envelopes before parsing

The shared `arcgis.fetch_features` (via `_request_with_retry`) detects ArcGIS error envelopes — bodies of shape `{"error": {"code": ..., "message": ..., "details": [...]}}` returned with HTTP 200 — and raises `ArcGISError` with the server's code+message. A one-off script that does its own `requests.get()` against an ArcGIS or MapServer endpoint (rather than going through the shared library) bypasses this detection. The script then parses the body as the expected shape (e.g. a GeoJSON `FeatureCollection`), gets `features=[]` from `data.get("features", [])`, and raises a misleading "zero features" diagnostic when the real cause is auth failure, layer removal, or a malformed query.

The fix in any custom-fetch path: before reading `features` (or the equivalent shape-specific key), check `data.get("error")` and raise with the server's `code` + `message` if present. Example pattern in `ingestion/states/montana/load_state_boundary.py:_parse_to_multipolygon_wkt`:

```python
data = json.loads(payload)
error = data.get("error")
if isinstance(error, dict):
    code = error.get("code", "?")
    message = error.get("message", "<no message>")
    raise RuntimeError(f"... (code={code}): {message}")
features = data.get("features", [])
```

Lock it in with a test that feeds an envelope payload and asserts the raise carries the server code+message. Without this defense, an upstream auth-token-required error returns `{"error": {"code": 499, "message": "Token Required"}}` with HTTP 200 and the operator's first diagnostic is "source geometry changed" rather than "credentials expired."

Surfaced by S03.0 silent-failure-hunter review on 2026-05-04.

## Integration — Supabase / PostGIS

### `geom::geometry` direct cast not enabled

Supabase's bundled PostGIS does not allow direct `geom::geometry` casts on `geography` columns — `SELECT ... FROM geometry WHERE NOT ST_IsValid(geom::geometry)` returns `cannot cast type geography to geometry`. The S02.6/S02.7 epic verification SQL uses this cast pattern (and so do the docs/runbook examples). Operators running those queries against a Supabase project will hit the error.

**Workaround:** round-trip via WKT — `ST_GeomFromText(ST_AsText(geom), 4326)`. This is what `ingestion/states/montana/README.md` documents for post-load AC verification.

```sql
-- Validity check (was: WHERE NOT ST_IsValid(geom::geometry))
SELECT id FROM geometry
WHERE NOT ST_IsValid(ST_GeomFromText(ST_AsText(geom), 4326));

-- Multi-part check (was: ST_NumGeometries(geom::geometry))
SELECT id, ST_NumGeometries(ST_GeomFromText(ST_AsText(geom), 4326)) AS parts
FROM geometry WHERE kind='hunting_district' ORDER BY parts DESC LIMIT 5;
```

The cast IS standard PostGIS behavior on most installs; the absence on Supabase is a cluster-config quirk, not a missing extension. Confirmed: PostGIS 3.3.7 + supabase_vault 0.3.1 is the configuration where this surfaces. Worth verifying on each new Supabase project before assuming the casts work.

Surfaced by S02.2 post-load AC verification on 2026-04-30.

## Integration — pdfplumber

### `page.extract_text()` collapses repeated spaces — output is not byte-exact verbatim

pdfplumber 0.11.x reassembles characters into words via its internal word-grouping algorithm and joins them with a single space. A PDF content stream with two literal spaces between words (e.g. `(hello  world) Tj`) is returned as `"hello world"` — one space, not two. Newlines from line-position changes ARE preserved; only intra-word spacing is collapsed.

ADR-008 ("verbatim regulation text") is implemented as "no additional normalization on top of pdfplumber" — pdfplumber's own normalization is the platform baseline. This interpretation is locked into S03.2's tests via `ingestion/ingestion/lib/pdf.py::extract_text`. Consequence: **do not assert byte-exact whitespace preservation against `extract_text` output**; tests that do will pass locally against a specific PDF but misrepresent what the function actually guarantees.

If a future story needs truly byte-exact source text (e.g., forensic comparison), walk `page.chars` directly — `extract_text` is not the right tool:

```python
# byte-exact path — bypasses pdfplumber's word grouping entirely
raw = "".join(ch["text"] for ch in page.chars)
```

Surfaced by S03.2 pre-implementation discovery + implementation on 2026-05-05.

### `page.extract_tables()` drops bounding boxes — use `page.find_tables()` instead

pdfplumber exposes two related table APIs with different return shapes:

- `page.extract_tables()` → `List[List[List[Optional[str]]]]` — cell data only, **no bbox**.
- `page.find_tables()` → `List[Table]` where each `Table` carries both `.bbox` and `.extract()`.

`TableMatch.bbox` (used for downstream region-cropping and provenance in `ingestion/ingestion/lib/pdf.py`) requires `find_tables()`. The natural-looking `extract_tables()` loses spatial info entirely — using it means calling BOTH methods and manually pairing cell data with bboxes, which is fragile and unnecessary.

The wrapper `ingestion/ingestion/lib/pdf.py::extract_tables` calls `find_tables()` internally despite the wrapper name suggesting otherwise. The docstring explains the choice, but anyone writing ad-hoc pdfplumber code outside the wrapper will reach for `extract_tables()` first and lose bboxes silently.

**Always use `page.find_tables()`** when bbox is needed; call `.extract()` on each returned `Table` object for cell data.

Surfaced by S03.2 implementation on 2026-05-05.

### FWP DEA-style tables: one table per page, not per regulation unit

The Montana DEA (Deer/Elk/Antelope) regulations PDF — and likely other state F&W table-formatted booklets — does NOT structure regulation tables as one-table-per-HD/unit. `pdfplumber.find_tables()` returns ONE TABLE PER PAGE, with HD-section delimiters embedded as data rows whose first cell matches `"HD NNN - Name"`. Multi-HD pages contain multiple such delimiter rows.

**Symptom:** A state adapter assuming one-table-per-HD silently truncates every HD's data after the first delimiter row, OR silently merges multiple HDs into one section. Both failures surface only at downstream validation, not at extraction time.

**Fix:** HD-level slicing must walk data rows looking for the heading regex, then accumulate rows until the next heading. Multi-page HDs (continuations) need bounded lookahead capped at 2–3 pages — do NOT scan unboundedly to "find the end." `pdfplumber.find_tables()` returning 1 table does not mean 1 HD's worth of data; it may contain 5 HDs on one page.

Reference implementation: `ingestion/states/montana/extract_dea.py::_slice_hd_rows` and `::_extract_hd_table` (S03.3, 2026-05-08).

### FWP tables use `"-"` as absence sentinel — applies to ALL nullable cells, not just season columns

FWP DEA table cells use the literal hyphen `"-"` to mean "not applicable / no value here." This applies to season-coverage columns (`EARLY SEASON DATES`, `ARCHERY ONLY SEASON DATES`, `GENERAL SEASON DATES`, `HERITAGE MUZZLELOADER SEASON DATES`, `LATE SEASON DATES`) AND to other nullable string fields: `APPLY BY DATE`, `QUOTA RANGE`, `OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS`. Likely extends to other FWP booklets.

**Symptom:** A naive `_normalize_cell` that only strips whitespace returns `"-"` — a non-empty string — contaminating the artifact. S03.3 saw 675 / 971 / 521 leaked sentinel rows in `apply_by` / `quota_range` / `extras` before the fix. Downstream code using `if row["apply_by"]:` treats the sentinel as a real value (violates ADR-001's "absent data is explicit null").

**Fix:** Both season-coverage logic AND nullable string field assignment must apply an `_is_absent_cell(cell)` check treating `None` AND `"-"` (and whitespace-padded variants like `" - "`) as absent. The predicate normalizes to `None` before any consumer reads the cell.

Reference implementation: `ingestion/states/montana/extract_dea.py::_is_season_cell_absent` (S03.3, 2026-05-08) — despite the name it is used for non-season fields too; the name is a historical artifact.

### pdfplumber sub-rows under a merged-cell license code return `None` — implement carry-forward

The DEA PDF (and likely many state regulation tables) groups multiple opportunity sub-rows under a single license code via merged cells. pdfplumber returns `None` in the LICENSE/PERMIT column for every sub-row — the merged cell's value appears only on the first row of the group.

**Symptom:** Naive per-row processing emits sub-rows with `license_code=None`, which fails fail-loud guards or produces NULL primary-key violations downstream. The A/B-asymmetric coverage signal is also lost — sub-rows that differ only in `season_coverage` end up rejected rather than recorded as separate season rows.

**Fix:** Track `last_license_code` (and `last_opportunity` for sub-opportunity rows) across rows; inherit the prior value whenever the LICENSE/PERMIT cell is `None`. This pattern enables correct A/B-asymmetric coverage: one license can have multiple sub-rows with differing `season_coverage` values, all sharing the same license code. S03.7's `license_season` link table depends on this carry-forward.

Reference implementation: `ingestion/states/montana/extract_dea.py::_rows_to_license_extractions` — `last_license_code` and `last_opportunity` carry-forward variables (S03.3, 2026-05-08).

### Section-level "first-observation-wins" for per-row variable fields is interpretive, not faithful

**Symptom:** When a per-row PDF field varies within a section (e.g., season date windows that differ per license/opportunity row), capturing only the first observation and replicating it across rows replaces source data with a paraphrase — violates ADR-008. Per-row divergence collapses to a single value in the artifact, and downstream consumers reading individual rows see incorrect data.

**Fix:** Always extract per-row from each row's column cells; emit warnings only for cases that genuinely cannot be parsed (not for natural divergence). The "section-level windows + per-row filter" pattern is the trap — rebuild as "per-row windows from each row's own cells, no section-level aggregation."

Reference: `ingestion/states/montana/extract_dea.py::_rows_to_license_extractions` — per-row `season_windows` populated inline from each row's column cells. Surfaced by S03.3 UAT failure on 2026-05-08 (HD 124 deer had three distinct General Season windows in the source PDF; the artifact carried only the first observation across all 5 rows).

## Build & Deploy

### Style anchor for adding a nullable text column

When adding a nullable text column via a new migration, mirror `jurisdiction_binding.verbatim_rule` (`supabase/migrations/20260425000000_initial_schema.sql:207`) byte-for-byte:

- Type `text`, no `NOT NULL`, no default, no CHECK.
- Inline `--` comment on the same line documenting what `NULL` means semantically (e.g., `-- NULLABLE — null = no geometry-specific rule text from source attributes (REG/COMMENTS)`).
- No `COMMENT ON COLUMN` (E01 doesn't use it).
- For `ALTER TABLE` migrations, prefer `ADD COLUMN IF NOT EXISTS` — matches the `CREATE EXTENSION IF NOT EXISTS` idiom and makes the migration safely re-runnable on partially-applied environments.

The new column must also land in Pydantic (`ingestion/ingestion/lib/schema.py`) and TypeScript (`mcp-server/src/types/schema.ts`) in the same PR per ADR-006. Field ordering convention: nullable text fields go between `license_year` (or the last common field) and `source: SourceCitation`. `architecture.md` §"Schema types" must also update — it's the audit trail for type-only enum extensions that have no SQL migration (per ADR-014).

### Cubic flags `from states.montana.X import` as broken — false positive

Cubic review (1.3.2 as of 2026-04-30) flags `from states.montana.<module> import ...` in adapter scripts as a P1 import failure, claiming `states` is not on `sys.path`. This is incorrect. The `ingestion` package is editable-installed (`pip install -e .` in `ingestion/`), which puts the `ingestion/` directory on `sys.path` via the `.pth` file in `.venv/lib/.../site-packages`. Python then resolves `states.montana.X` as a namespace package starting from `ingestion/states/montana/X.py`. The same mechanism is what makes `from ingestion.lib.X import ...` work — both imports rely on the editable install.

Verification when cubic flags this: run the script directly via `ingestion/.venv/bin/python ingestion/states/montana/<script>.py --help`. If it prints argparse help, the imports resolve. The existing tests use the same pattern (`from states.montana.load_portions import ...`) — if cubic's claim were correct, the test suite would also fail to collect, and it doesn't.

Surfaced by S02.4 cubic review on 2026-04-30.

### Script invocation must use `python <path>`, not `python -m`, for state adapter scripts

The editable install of `ingestion/` (`pip install -e .` with `packages = ["ingestion"]` in `pyproject.toml`) makes the inner `ingestion/ingestion/` directory available as the top-level `ingestion` package. Its `__path__` resolves to `['/<repo>/ingestion/ingestion']` only — the project-root `states/` directory is NOT a subpackage of `ingestion`. As a result:

- `from ingestion.lib.X import ...` works (the inner package exports `lib/`)
- `from states.montana.X import ...` works in tests because pytest puts the project root (`ingestion/`) on `sys.path`, and `states.montana` is then resolvable as a namespace package
- `python -m ingestion.states.X.module` **fails** with `ModuleNotFoundError: No module named 'ingestion.states'` — `ingestion` is the inner package, not the project-root namespace
- `python -m states.montana.X` would only work if `cwd` is the project root AND nothing else interferes — fragile

Always invoke state adapter scripts directly by path (consistent with the docstring on `ingestion/states/montana/load_state_boundary.py`):

```sh
ingestion/.venv/bin/python ingestion/states/montana/<script>.py
```

The script's `from ingestion.lib.X import ...` calls at module load resolve via the editable install regardless of cwd. Surfaced during S03.1 implementation when an initial `python -m ingestion.states.montana.fetch_pdfs` invocation example was written into the orchestrator's docstring and tested wrong before commit.

Surfaced by S03.1 implementation on 2026-05-04.

### `supabase db push` against a project bootstrapped via dashboard fails with "relation already exists"

When a Supabase project's schema was originally created via the dashboard SQL editor — or via `supabase db push` from a different machine with a different local migration history — the remote `supabase_migrations.schema_migrations` tracker can be empty even though the schema is fully populated. The next `supabase db push` then attempts to replay all migrations from scratch and dies on the first `CREATE TABLE` with `relation already exists` (SQLSTATE 42P07).

**Diagnose:** `SELECT version FROM supabase_migrations.schema_migrations ORDER BY version;` — if the result is empty or missing entries that should be there, the tracker is out of sync.

**Fix:** mark each pre-existing migration as applied without re-running its SQL:

```sh
supabase migration repair --status applied <timestamp>
```

Run once per migration that's already reflected in the schema, then `supabase db push` will only apply what's actually pending. **Verify the schema state matches the migration first** (e.g., check `information_schema.columns` for the columns each migration adds) before running repair — `repair` is a meta-state lie if the schema and migration history have actually diverged.

Surfaced by S03.0 deployment on 2026-05-04.

## Conventions — Ingestion adapters

### Shared predicate module when two stories partition a single source layer

When two stories must apply mutually exclusive filters over the same source layer (e.g. S02.4 ingests non-CWD rows of MT FWP layer #2 as `kind='restricted_area'`; S02.5 ingests the CWD rows of the same layer as `kind='cwd_zone'`), the discriminator predicate **must** live in a shared module that both adapters import. The naive approach — let one story write rows with one `kind`, then have the other mutate matching rows to a different `kind` — has an idempotency hole: re-running the first story reverts the kind via UPSERT.

The pattern: a module like `ingestion/states/<state>/<feature>_discriminator.py` exporting a single pure function `is_<feature>_feature(props: dict[str, Any]) -> bool`. Each adapter applies the predicate as a filter — one inverted, one not — at the point where features arrive from the source. Each row is written exactly once with the correct `kind`. Re-running either adapter is idempotent; sequence between them does not matter.

Test the predicate independently of the adapter (own pure-function test file). Test the adapter integration by stubbing the predicate in `_load_layer` tests.

Example: `ingestion/states/montana/cwd_discriminator.py` (shared by `load_restricted_areas.py` and the future `load_cwd_zones.py`).

Surfaced by S02.4 implementation on 2026-04-30.

### Single atomic commit across multi-layer adapters

Adapter `main()` functions that load multiple layers must call `conn.commit()` **once after the loop**, not inside it. Per-layer commits would leave partial state on a mid-loop failure (e.g. layer #2 written, layer #15 raises → layer #2 silently committed with no audit). The intended behavior is all-or-nothing: if any layer raises, the connection's `__exit__` rolls back the entire transaction.

The convention is brittle to "natural-looking" refactors that move the commit inside the loop for per-layer log alignment. Two defenses are required:

1. **A comment at the `conn.commit()` call** stating "single atomic commit covering BOTH/ALL layers — do not move inside the loop." Reference the rollback-on-`__exit__` mechanism so the reader understands why partial-commit is unsafe.
2. **A test asserting `conn.commit` is NOT called when a later layer raises.** Stub `_load_layer` to succeed once and raise on the second call; assert `mock_conn.commit.assert_not_called()` and that both layer attempts happened (so the test would fail under either short-circuit OR per-layer-commit refactors).

Both defenses are required because either alone allows the silent flip:

- Comment without test: a refactor edits the comment along with the code.
- Test without comment: the developer doing the refactor reads the test as "weird, must be testing something else" and rewrites it.

Example: `ingestion/states/montana/load_restricted_areas.py:main()` and the `TestMainCommitAtomicity` class in `tests/test_load_restricted_areas.py`.

Surfaced by silent-failure-hunter on S02.4 review on 2026-04-30.

### "MT GIS layers" can live on FWP on-prem, FWP AGOL org, OR the Montana State Library MSDI catalog

Montana state-published GIS data lives on **three** distinct hosts, not just two. Discovery work that enumerates only one or two will miss layers that exist on the third.

1. **MT FWP on-prem MapServer** — `https://fwp-gis.mt.gov/arcgis/rest/services?f=json` (every folder, every service). Where `admbnd/huntingDistricts` lives.
2. **MT FWP ArcGIS Online org** — sharing search `https://www.arcgis.com/sharing/rest/search?q=<keyword>+montana&f=json`, filter by `owner=MtFishWildlifeParks` afterward (the Hub v3 API is unreliable: 502/504 on multiple endpoints during S02.5 investigation; the sharing REST API is the dependable fallback). Where the `ADMBND_HD_CWD` FeatureServer lives.
3. **Montana State Library MSDI Framework catalog** — `https://gisservicemt.gov/arcgis/rest/services?f=json`. Hosts state-published reference layers (boundaries, hydrography, transportation) NOT visible from the FWP catalogs. The state boundary lives at `MSDI_Framework/Boundaries/MapServer/9` (used by S03.0 for `MT-STATEWIDE-geom`).

Empirical pattern from across S02 + S03:

- S02.4's "no CWD rows in layer #2" was correct for the on-prem catalog; S02.5's `ADMBND_HD_CWD` find on the AGOL org would have been missed if discovery stopped at on-prem.
- S03.0's "no FWP state-boundary layer" was correct for both FWP catalogs (on-prem AND AGOL); the MSDI Framework Boundaries layer would have been missed if discovery stopped at FWP.

When asked "does MT have a layer for X," check all three hosts before concluding "no published source exists." Document which host the layer was found on in the SourceCitation `agency` field (e.g., `"Montana State Library"` for MSDI vs. `"Montana Fish, Wildlife & Parks"` for FWP) — both qualify as `document_type='gis_layer'` per ADR-014, but agency provenance still matters for citation accuracy.

Surfaced by S02.5 investigation on 2026-05-01; extended to MSDI by S03.0 source investigation on 2026-05-04.

### `expected_sha256` in `sources.yaml` is documentation intent, not a runtime gate

`ingestion/states/montana/sources.yaml` carries `expected_sha256: <hex>` (or the literal `unknown`) per entry. The field reads like a runtime check, but it is **not** read by the fetcher. The actual drift-detection comparison in `ingestion/ingestion/lib/pdf_fetch.py` is between the observed SHA from the network fetch and the prior committed `*-pdf-manifest.json` file's `pdf_sha256` field — not against `sources.yaml`.

Two consequences:

1. The first run against a new entry never compares anything (no prior manifest exists). The observed SHA is recorded in the manifest unconditionally; no marker is written.
2. Updating `sources.yaml` to a new `expected_sha256` value does NOT cause the next fetch to fail or warn. Drift is detected purely from on-disk manifest state.

The field exists so reviewers can see operator intent in `git diff` ("the operator pinned this hash; did it change?") and so a corrupted manifest can be cross-checked against the YAML for forensic purposes. It is documentation, not enforcement.

If a future operator wants `sources.yaml` to actively gate fetches, that is a behavior change — read the field in `fetch_pdf` and compare against the observed SHA. As of S03.1 this is intentionally not wired up to avoid coupling fetch behavior to a hand-edited YAML field.

Surfaced by S03.1 implementation on 2026-05-04.

### `sources.yaml` URL slug ≠ publication cadence — confirm cadence by reading the PDF, not the URL

**Symptom:** A spec table claims a source is "biennial 2026/2027" or "annual 2026", but the actual file on the agency CDN is named in a way that contradicts the spec — e.g. spec says biennial but the URL slug is just `2026-...`.

**Cause:** Spec authors infer cadence from the document's *content* (cover page, internal validity dates), but URL slugs encode whatever filename the agency's CMS chose for the binary. The two are independent. FWP's CDN names the DEA file `2026-dea-regulations-final-with-low-resolution-maps-for-web.pdf` even when (per PRD assumption) it covers the 2026/2027 biennium internally. The slug is not the contract.

**Fix:** Treat the URL slug as opaque. Confirm cadence by reading the PDF cover page — that is the authoritative source for "this document covers years X through Y." If the slug and content disagree, name the citation id after what the document *contains*, not what the URL string says (or rename to match the URL if the content is also single-year — which is what we did for `mt-fwp-dea-2026-booklet`).

Two concrete consequences:
- `sources.yaml` `id` and `title` should reflect document content, not URL slug verbatim.
- `expected_page_count` is a sanity-check claim, not a contract. The first live fetch reveals the true page count; pin `expected_sha256` only after the document content has been visually confirmed to match the spec's intent (or the spec has been amended).

**Surfaced 2026-05-07 during S03.3 unblock**: spec table called DEA "Biennial 2026/2027" but the FWP file is named `2026-dea-regulations`. Renamed citation id from `mt-fwp-dea-2026-2027-booklet` → `mt-fwp-dea-2026-booklet` (URL-truthful). Cover-page cadence to be verified at S03.3 first fetch. Three other URL slugs corrected in the same pass — all four were spec-table guesses that didn't survive contact with the live FWP CDN.

### Read-only scripts must still fail loud on empty source data

**Symptom:** A script that only reads from the database (no upserts, no commits) silently produces empty output — e.g. a 2-byte `[]` fixture — and reports success when its source query returns zero rows.

**Cause:** The fail-loud discipline is typically associated with writers (zero features written = loader bug). Readers feel safe because they can't corrupt data. But a reader that produces empty output on missing prerequisites is equally misleading: downstream consumers see valid-looking empty data instead of an error pointing to the missing loader.

**Fix:** After the first foundational query (e.g. fetching HD IDs), check whether the result is empty. If a non-empty result is required for the script to do meaningful work, raise a script-specific exception with a message naming (a) what was queried, (b) the state/scope filter, and (c) which upstream loader the operator must run first. Do not log-and-continue or produce empty output.

Concrete example: `ingestion/states/montana/build_overlay_fixture.py` lines 166–172 raise `OverlayFixtureError` when `_fetch_hd_ids(conn)` returns empty, naming `load_hds.py` as the prerequisite. Extends the zero-features writer convention (see "Single atomic commit" entry) to the reader side.

Surfaced by S02.6 implementation on 2026-05-01.

## Conventions — Pre-commit & secrets

### `detect-secrets` flags ArcGIS `serviceItemId` UUIDs as hex high-entropy strings

ArcGIS Online metadata fixtures (`*-metadata-*.json` files committed for drift detection) carry a top-level `serviceItemId` field whose value is a 32-character hex UUID — for example `"serviceItemId": "8837c07298054f5e8be2e072681d870c"` in the S02.5 `ADMBND_HD_CWD` fixture. The pre-commit `detect-secrets` hook (`HexHighEntropyString` plugin, `limit: 3.0`) flags this as a potential secret and blocks the commit.

These IDs are NOT secrets — they are publicly addressable URL components: `https://www.arcgis.com/home/item.html?id=<serviceItemId>` resolves to the public item page for any anonymous user. They are part of the "what" of the data, not credentials.

The fix when committing a new ArcGIS metadata fixture:

```bash
detect-secrets scan --baseline .secrets.baseline   # update baseline with new finding
git add .secrets.baseline
```

The new finding lands in `results` with `is_verified: false`. That is fine — `is_verified: false` means "not yet audited," which is sufficient for the hook to skip the file. Optionally run `detect-secrets audit .secrets.baseline` to mark the entry as a confirmed false positive (sets `is_verified: true`).

Do NOT use `git commit --no-verify` to bypass the hook. The system instructions forbid it, and it would defeat the hook's purpose for genuine secrets.

Surfaced by S02.5 commit on 2026-05-01.

### `detect-secrets scan` baseline refresh ignores untracked files

**Symptom:** Refreshing `.secrets.baseline` for newly-created files (e.g., S02.7 manifest files) using `detect-secrets scan > .secrets.baseline` produces a baseline that does NOT include the new files. The pre-commit hook then trips on commit because the new file's hex strings (e.g., a 64-char `layer_hash` field) aren't in the baseline.

**Cause:** `detect-secrets scan` (no positional args) walks `git ls-files` by default — it sees only tracked files. New files are invisible to the rescan even if they're staged with `git add` (the path index may or may not include them depending on operation order).

**Fix:** Mark new files as intent-to-add first, then rescan:

```bash
git add --intent-to-add <new-files>
detect-secrets scan > .secrets.baseline
git add .secrets.baseline <new-files>
```

Or pass file paths directly: `detect-secrets scan <file1> <file2> ... > .secrets.baseline` (loses the existing baseline content — typically merge manually or stick with the `--intent-to-add` flow). The `--all-files` flag scans EVERY file including `.git/`, `.venv/`, `node_modules/` — slow and rarely what you want.

Surfaced by S02.7 manifest backfill on 2026-05-02.
