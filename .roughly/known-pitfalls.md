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

### `geometry` table DDL column is `geom`, not `geog`

The actual DDL column name is `geom geography(MultiPolygon, 4326)` (see `supabase/migrations/20260425000000_initial_schema.sql:201`). CLAUDE.md uses "geog" colloquially in one sentence ("all geometries use `geography(MultiPolygon, 4326)`") but that phrase refers to the type, not the column name. Raw SQL that uses `zone.geog` or `hd.geog` receives `ERROR: column "geog" does not exist`. All hand-written queries must use `geom`.

Surfaced 2026-05-23 during S03.10 T0 probe (initial SQL block used `geog`; corrected before any execution). Reference: `S03.10.md` DDL findings section.

### PostGIS functions must use `extensions.` schema prefix in Supabase projects

The Supabase project installs PostGIS with `CREATE EXTENSION IF NOT EXISTS postgis SCHEMA extensions;` (see `supabase/migrations/20260425000000_initial_schema.sql` near the top). The `extensions` schema is NOT on the connection's default search_path, so bare names fail: `ERROR: function st_dwithin(geography, geography, integer) does not exist` (or equivalent for `ST_Touches`, `ST_Centroid`, etc.). Every raw-SQL PostGIS function call must be prefixed: `extensions.ST_DWithin(...)`, `extensions.ST_Touches(...)`, etc.

This is a Supabase-project-specific configuration choice, not a missing extension — the function exists but is only resolvable via the explicit schema qualifier. Reference: S03.10 schema-prefix audit section in `S03.10.md`; ADR-016 `statement_timeout` note also implied geography-native calls were needed. Locked in S03.10 by `TestQueryNearbyHdsForZone::test_sql_uses_extensions_prefix_not_bare_name`.

Surfaced previously (E02) and again 2026-05-23 during S03.10 T0 (the `load_jurisdiction_bindings.py` query required the prefix from the first draft).

### Centroid-to-centroid `ST_DWithin` produces zero matches for large national-park polygons

**Symptom:** `ST_DWithin(ST_Centroid(zone.geom), ST_Centroid(hd.geom), 5000)` returns 0 matches for all three Montana no-hunt zones (Glacier NP, Sun River Game Preserve, Yellowstone NP) even at a 5 km threshold — every HD is classified as "not nearby" and no bindings are written.

**Cause:** National-park and game-preserve polygons are large; their centroid is many kilometres from any HD boundary. Yellowstone NP's centroid is roughly 30 km inside the park, far from the nearest HD centroid. Centroid-to-centroid distance is only meaningful for compact, roughly-circular polygons.

**Fix:** Use boundary-to-boundary geography `extensions.ST_DWithin(zone.geom, hd.geom, distance_meters)` directly on the native `geography` columns. This covers the ST_Touches case (touching = 0 m distance), avoids geometry casts, and works correctly for large polygons. Reference: `load_jurisdiction_bindings.py::_query_nearby_hds_for_zone`; Deviation #4 footnote in S03.10 epic.

Surfaced 2026-05-23 during S03.10 T0 probe; confirmed via live-DB counts (centroid: 0/0/0; boundary-to-boundary: 8/8/13 matches).

### Follow-up migrations must include their own RLS policies — the base RLS migration's flat IN-list does not auto-extend

**Symptom:** A table added by a follow-up migration (e.g., `license_season` added by `20260504032424_e03_schema_additions.sql`) is silently permissive — no deny-all RLS policy covers it — because the original RLS migration (`20260425000001_rls_deny_all.sql`) uses a flat `table_name IN (...)` list that was never updated.

**Cause:** Postgres tables are permissive-by-default when no RLS policy exists. The flat IN-list in the base RLS migration does not enumerate tables that didn't exist when it was written; re-running it would be a no-op on the existing tables and would not cover new ones.

**Fix:** Every migration that adds a new table must include `CREATE POLICY` + `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` in the same migration file. Do not assume the base RLS migration will be updated. Audit gap detection: `SELECT tablename FROM pg_policies WHERE schemaname='public' GROUP BY tablename;` — compare against the full table list to surface any table with no policy. Surfaced by S03.12 UAT criterion #7 review on 2026-05-27.

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

### Rotated tables emit doubly-reversed cells

- **Rotated tables emit doubly-reversed cells.** Some PDFs (Montana Black Bear booklet) print regulation tables physically rotated. pdfplumber returns each cell with both line order AND character order reversed (e.g., `"Sep.15-Nov.29"` extracts as `"92.voN-51.peS"`). `page.rotation` reports 0 — there's no hint that reversal is needed. Every cell must be passed through a reversal helper BEFORE normalization. Reference: `_reverse_cell_text` in `extract_black_bear.py`.

### Two-column page layouts interleave text in `extract_text(page)`

- **Two-column page layouts interleave text in `extract_text(page)`.** pdfplumber's default extraction reads top-to-bottom across both columns. For pages with two-column layouts (Black Bear p. 7), use `extract_text(page, bbox=(306, 0, 612, 792))` to isolate the right column before processing.

### Quota-cell word order varies by extraction context

- **Quota-cell word order varies by extraction context.** The same quota phrase can appear as `"= N Female subquota"`, `"= N quota Harvest"`, or `"quota = Harvest N"` depending on how pdfplumber splits multi-line cells in rotated tables. Use a primary regex + word-order-invariant component fallback (`_QUOTA_COUNT_REGEX` + `_QUOTA_KIND_REGEX` in `extract_black_bear.py`).

### Three-column FWP booklet layout — full-page `extract_text()` is unusable

The FWP Legal Descriptions PDF (2026-2027 edition, 56 pages) uses a three-column layout on every content page. `pdfplumber.Page.extract_text()` on the full page reads top-to-bottom across all three columns, producing severely interleaved text (e.g., column-3 heading interleaved with column-2 body). Heading regexes against this stream produce false-positive matches across column boundaries.

**Fix:** crop each column separately and concatenate the per-column streams in left-to-right order. Column boundaries for the FWP Legal Descriptions PDF (594pt × 756pt page):

- col1: `x ∈ (36, 195)`
- col2: `x ∈ (210, 355)`
- col3: `x ∈ (390, 555)`
- header strip top = **25pt** (no running title on V1 content pages; first content row sits at top≈29; an over-aggressive 40pt strip clipped HD headings at the top of each column)
- footer strip bottom = **50pt** (running footer `"Visit fwp.mt.gov <page#>"` sits at top≈716, ~40pt above page bottom; 20pt was too shallow)

Reference implementation: `ingestion/states/montana/extract_legal_descriptions.py::_extract_three_column_text` (S03.5, 2026-05-12; strip values revised 2026-05-13/14).

### Rotated chapter-label sidebars are non-upright glyphs — filter via `c.get("upright", True)`

Every content page of FWP booklets carries a vertical chapter label in the outer margin (e.g., `klE & reeD`, `epoletnA`). These are not separate page layers; they are sideways-drawn text characters whose `char["upright"]` is `False`. Without filtering, they contaminate column extractions and trigger spurious heading matches.

**Fix:** apply a chained filter when cropping for column text:

```python
page.crop(bbox).filter(lambda c: c.get("upright", True)).extract_text()
```

`page.rotation` reports `0` for these pages — there is no signal that filtering is needed except inspection. Reference: `ingestion/states/montana/extract_legal_descriptions.py::_extract_three_column_text` (S03.5, 2026-05-12).

### Heading regex name capture must exclude newline, not just colon

A naive heading regex like `^\s*(\d{2,3})\s+([^:]{3,80}?):\s+ANCHOR` looks safe because the lazy `[^:]{3,80}?` excludes the colon delimiter. But `[^:]` does NOT exclude `\n` — the lazy match can span line boundaries, letting a leading-digit fragment on a prior line absorb the next line's intended heading.

**Symptom:** A body fragment ending with a 2–3-digit number (e.g., `"93 in Missoula County."`) immediately preceding a real heading line (`"261 East Bitterroot: That portion..."`) causes the regex to capture `93` as the HD number and absorb `"in Missoula County.\n261 East Bitterroot"` into the lazy name span. Result: the false HD 93 surfaces as unmatched; the real HD 261 is silently swallowed.

**Fix:** use `[^:\n]` (or `[^:\r\n]` for Windows-line-ending tolerance) in the lazy name capture. Reference: `ingestion/states/montana/extract_legal_descriptions.py::_HD_HEADING_RE` (S03.5, 2026-05-12). Discovered during T11 end-to-end run; locked by `TestArtifactRegression::test_regression_unmatched_rate_below_10_percent`.

### Same heading text repeats once per column when a description spans multiple columns

The three-column layout causes a single zone-description (e.g., the Libby CWD Management Zone on PDF page 19) to span all three columns. The heading text appears in EACH column with a different body fragment in each. A naive page-walk yields three blocks with the same `cwd_name`; if the matcher first-match-wins, the body of the first column is recorded and the other two columns are dropped.

**Fix:** post-walk consolidation step that merges all blocks with the same canonical heading into a single block whose body concatenates the per-column fragments in original column order. Defensive: idempotent (running twice is a no-op). Reference: `ingestion/states/montana/extract_legal_descriptions.py::_consolidate_cwd_blocks` (S03.5, 2026-05-12).

### Heading anchor phrases wrap onto continuation lines when columns are narrow

The FWP Legal Descriptions PDF wraps the heading anchor phrase ("Those portions of Lincoln county...") onto the line after the heading line, and sometimes even wraps the trailing word `Zone:` of the heading itself (Kalispell case: page 21 col 2 reads `"Kalispell Area CWD Management"` with no colon or "Zone" suffix on that line).

**Fix:** for the narrow-column case, the heading regex CANNOT require the anchor phrase on the same line; it can match only the heading-name prefix:

```text
^\s*(Libby CWD Management Zone|Kalispell Area CWD Management(?:\s+Zone)?)\b
```

Then in the matcher, canonicalize the captured name (append " Zone" if missing) before the lookup. Reference: `ingestion/states/montana/extract_legal_descriptions.py::_canonicalize_cwd_name` (S03.5, 2026-05-12).

The same wrap also affects HD headings: HD 705 reads `"705 Prairie/Pines-Juniper Breaks: Those\nportions of..."` — the literal space in `Those portions?` doesn't match the newline. Fix: use `Those\s+portions?` (and `That\s+portion`) — whitespace-flex matches the wrap while still rejecting arbitrary non-whitespace text between the two words (since `\s` is whitespace-only). Surfaced 2026-05-13 — without this, +17 HDs silently surfaced as unlinked. Locked by `TestHeadingRegex::test_hd_anchor_phrase_wraps_across_newline`.

### FWP antelope DEA tables use 4-letter `"Sept"` month abbreviation

FWP DEA antelope per-HD A-license rows use `"Sept"` (4 letters) where all other DEA tables use `"Sep"` (3 letters), e.g. `"Sept. 05-Oct. 09"`. Python's `datetime.strptime` with `%b` only accepts the 3-letter POSIX form and raises `ValueError` on `"Sept"`.

**Symptom:** Date-parsing of antelope rows aborts with `ValueError: time data 'Sept. 05' does not match format '%b. %d'`. All other species parse cleanly, making the error look like a data anomaly rather than a normalization gap.

**Fix:** In the date-parsing helper, normalize before `strptime`: `re.sub(r"\bSept\b", "Sep", cell_text)`. Apply before any `strptime` call, not inside a try/except — fail-loud is better than silently skipping antelope rows. Reference: `_parse_window` in `ingestion/states/montana/load_seasons_and_licenses.py`.

Surfaced by S03.7 implementation 2026-05-15.

### Running PDF footer leaks into last body when crop strip is too shallow

The FWP Legal Descriptions PDF carries a `"Visit fwp.mt.gov <page#>"` running footer on every content page at `top ≈ 716` on a 756pt-tall page (roughly 40pt from the bottom). The initial column-crop footer strip of 20pt produced a cutoff at `page.height - 20 = 736` — above the footer — so the footer text leaked into whichever HD body extended near the bottom of the column. HD 704's `verbatim_description` ended with `"Visit fwp.mt.gov 9"`.

**Fix:** crop the bottom-most 50pt (not 20pt). The cutoff at `page.height - 50 = 706` is well above the footer's top y of 716. Probe footer position with `page.extract_words()` filtered to the bottom region before settling on a strip value. Reference: `ingestion/states/montana/extract_legal_descriptions.py::_FOOTER_STRIP_PT` (S03.5, 2026-05-13). Locked by `TestArtifactRegression::test_no_running_footer_leak_in_verbatim_descriptions`.

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

### Adapter-module tests should use direct `import`, not `importlib.util.spec_from_file_location`

State-adapter scripts under `ingestion/states/<state>/*.py` are NOT a Python package (`states/` has no `__init__.py`), but the editable install adds `ingestion/` to `sys.path` so `import states.montana.<module>` resolves cleanly as a namespace package. Every adapter test in `ingestion/tests/test_load_*.py` uses this direct-import pattern — for instance `test_load_state_boundary.py` does `from states.montana.load_state_boundary import _build_source_citation, ...`. A `_load_module()` helper using `importlib.util.spec_from_file_location(...)` + `exec_module(...)` is the wrong shape for this codebase: it adds dead-code overhead (path computation, type-narrowing assertions, ModuleType import) for a problem that the editable install already solved.

The trap is that the `importlib.util` path *works* — tests pass — so the divergence is invisible at run time. Reviewers (static-analysis agent in S03.6's review cycle caught this) only spot it by comparing against peer test files. Surfaced during S03.6's Stage 6 review and corrected in the review-fix cycle.

### `supabase db push` against a project bootstrapped via dashboard fails with "relation already exists"

When a Supabase project's schema was originally created via the dashboard SQL editor — or via `supabase db push` from a different machine with a different local migration history — the remote `supabase_migrations.schema_migrations` tracker can be empty even though the schema is fully populated. The next `supabase db push` then attempts to replay all migrations from scratch and dies on the first `CREATE TABLE` with `relation already exists` (SQLSTATE 42P07).

**Diagnose:** `SELECT version FROM supabase_migrations.schema_migrations ORDER BY version;` — if the result is empty or missing entries that should be there, the tracker is out of sync.

**Fix:** mark each pre-existing migration as applied without re-running its SQL:

```sh
supabase migration repair --status applied <timestamp>
```

Run once per migration that's already reflected in the schema, then `supabase db push` will only apply what's actually pending. **Verify the schema state matches the migration first** (e.g., check `information_schema.columns` for the columns each migration adds) before running repair — `repair` is a meta-state lie if the schema and migration history have actually diverged.

Surfaced by S03.0 deployment on 2026-05-04.

### Subagent-authored docs can reference stale task IDs from earlier plan drafts

**Symptom:** An AC table or working note produced by a subagent references task numbers (e.g., T2–T9) that don't match the final plan's task numbering (e.g., T1–T11). The orchestrator only notices during spot-check.

**Cause:** Long `/roughly:build` pipelines go through multiple plan-revision cycles before the final plan is locked. A subagent dispatched at a later stage may carry forward an earlier plan draft's task numbering in its internal context, especially if the earlier draft was included in the prompt verbatim.

**Fix:** When dispatching a subagent that writes long-form docs referencing task IDs, include the final locked task list in the dispatch prompt verbatim and explicitly direct the subagent to consult the final plan file. On return, spot-check the generated doc against the final plan file before marking the stage complete — look for any T-number reference and verify it matches.

Surfaced by S03.8 Stage 8 wrap-up on 2026-05-18.

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

### Spec-table BMU/HD lists must be cross-checked against the live PDF

- **Spec-table BMU/HD lists must be cross-checked against the live PDF.** The Black Bear 2026 spec listed 9 quota-closure BMUs; the actual PDF has 8 (BMU 530 absent). Use `re.findall(r"\d{3}", verbatim_rule)` against a constants tuple as a fail-loud drift guard at extraction time. Scope the drift guard to the first sentence to avoid phone-number digits (e.g., 385, 444, 800) contaminating the BMU set.

### Correction-merge arbitration is doc-type-precedence, not date-precedence

- **Correction-merge arbitration is doc-type-precedence, not date-precedence.** When merging a correction PDF with an annual_regulations booklet, `document_type='correction'` always wins over `'annual_regulations'` regardless of `publication_date`. Date is used only for tiebreaking among same-doc-type sources. The naive "MAX date wins" rule silently inverts intent when a correction is published BEFORE the booklet it corrects (Montana 2026 case: correction `2026-03-18` < booklet `2026-04-27`). Reference: `_merge_with_corrections` in `extract_black_bear.py`.

### BMU/HD identifier regexes must handle footnote-marker suffixes

- **BMU/HD identifier regexes must handle footnote-marker suffixes.** Female-sub-quota BMUs in the Montana Black Bear booklet carry a trailing asterisk (`"300*"`, `"580*"`) as a footnote marker. Capture the digits and strip the suffix at parse time (`re.compile(r"^(\d{3})\*?$")`).

### Multi-iteration state writes must hoist out of the loop

- **State-overwriting loops are dict/list-iteration-order-dependent.** When a `for X in collection: state.attr = X[...]` loop runs more than once and `collection` has a non-deterministic order (Python dicts preserve insertion order but the *insertion* itself may be order-dependent on upstream code), the final value of `state.attr` reflects whichever element was iterated last. The build pipeline for S03.4 caught this twice in `_merge_with_corrections`: row-level `source_id`/`source_publication_date` and `extraction_confidence` were both being overwritten on every `(bmu, field)` iteration, producing dict-order-dependent provenance and N-times-demoted confidence for rows touched by N field-level ops. **Rule:** hoist any per-row state assignment out of the per-cell loop into a separate post-loop pass keyed on the row, so each row's state is computed exactly once from a deterministic input. Reference: `_merge_with_corrections` Stage 3 in `extract_black_bear.py` for the canonical pattern (Stage 1 selects winners per cell; Stage 2 applies cell values; Stage 3 updates row-level state once per touched row).

### `max()` / `min()` with comparable ties need an explicit secondary key

- **`max(items, key=...)` and `min(items, key=...)` are list-iteration-order-dependent on ties.** When the keying function returns equal values for two or more items, `max` / `min` returns the first one encountered. For deterministic semantics across re-runs (e.g., re-generating an artifact whose SHA must be byte-stable), use a tuple key with a secondary sort field, OR do a two-pass selection: filter to ties, then pick by the secondary criterion. The S03.4 row-provenance code uses the two-pass form: `max_date = max(op["source_publication_date"] for op in ops); date_ties = [op for op in ops if op["source_publication_date"] == max_date]; row_winner = min(date_ties, key=lambda op: op["source_id"])` — lex-smallest `source_id` breaks ties. Reference: `_merge_with_corrections` row-provenance selection in `extract_black_bear.py`.

### `regulation_record` has no `verbatim_rule` column — section text decomposes onto child entities

- **`regulation_record` is a pure anchor; section verbatim text decomposes onto S03.7's child entities.** The DDL (`supabase/migrations/20260425000000_initial_schema.sql:36-49`) and the `RegulationRecord` Pydantic model (`ingestion/ingestion/lib/schema.py:221-238`) define this table as `(PK, source, confidence, schema_version, ingested_at) + additional_rules: VerbatimRule[]` — no `verbatim_rule` field. A loader for `regulation_record` MUST NOT attempt to write a section-level `verbatim_rule`. The DEA section's `verbatim_text` decomposes onto `season_definition.verbatim_rule` (per-window) and `license_tag.verbatim_rule` (per-license-row) via S03.7; HD-wide `NOTE:` lines are captured by S03.6 in `additional_rules`. Resolution recorded in `docs/open-questions.md` Q15 and epic footnote `[^oq1]` at line 565. Reference: `_build_dea_records` + `_build_bear_records` in `load_regulation_records.py`.

### `db.update_legal_description` fails loud on `cur.rowcount == 0`

- **Targeted UPDATE helpers must raise when the WHERE clause matches no row.** `update_legal_description(conn, geometry_id, text)` in `ingestion/lib/db.py` runs `UPDATE geometry SET legal_description = %s WHERE id = %s` and raises `RuntimeError` if `cur.rowcount == 0`. A silent no-op would mask matcher bugs — e.g., the S03.5 extractor emitting a `geometry_id` that doesn't exist in the `geometry` table because of E02 fixture drift. The same pattern should apply to any future targeted UPDATE helper added to `db.py` for child entities.

### DEA `species_group="deer"` requires fan-out to `mule_deer` + `whitetail`

- **The DEA artifact uses booklet-column species labels; the DB schema uses granular species values.** The DEA extraction artifact emits `species_group ∈ {"deer", "elk", "antelope"}` because those are the species column blocks in the FWP DEA booklet. The `regulation_record.species_group` DB column uses `{"mule_deer", "whitetail", "elk", "pronghorn", "bear"}`. The mapping is: `"deer"` fans out to **two rows** (`mule_deer` + `whitetail`) sharing the same per-HD verbatim/source/confidence; `"elk"` stays as `"elk"`; `"antelope"` renames to `"pronghorn"`. A naive `1:1` for-loop is wrong. Reference: `_DEA_SPECIES_FANOUT` and `_build_dea_records` in `load_regulation_records.py`. Locked by `test_deer_fans_out_to_mule_deer_and_whitetail`.

### Bear DB `species_group` is `"bear"`, NOT the artifact's top-level `"black_bear"`

- **The Black Bear extraction artifact's top-level `species_group` field is `"black_bear"`. The `regulation_record.species_group` DB value is `"bear"`.** Mixing the two produces silent FK mismatches against any future cross-table query joining on species. Reference: `_build_bear_records` in `load_regulation_records.py` (literal `species_group="bear"`). Locked by `test_bear_species_group_is_bear_not_black_bear`.

### Confidence MIN-aggregation must use `ConfidenceTier.min_tier`, not bare `min()` over strings

- **`min(["high", "low"])` returns `"high"` lexicographically** because `"h" < "l"` in ASCII order. The S03.2 `pdf.ConfidenceTier.min_tier` helper uses `key=lambda t: t.rank` so the most-uncertain tier wins ADR-017-faithfully. Loaders that aggregate confidence across multiple extraction rows MUST call `min_tier`, not the builtin. Reference: `pdf.py` lines 121-150 (helper); `_build_dea_records` in `load_regulation_records.py` (call site). The trap case is locked by `test_confidence_min_tier_trap_case_high_low_returns_low`.

### Closed-set kind/category heuristics require full-artifact profiling before plan finalization

- **Profile the FULL extraction artifact before writing a closed-set categorization branch list.** S03.7's `_build_dea_license_tags` uses `else: raise RuntimeError` on an unmatched `kind`. The initial plan listed 3 branches (general / B License / statewide). Plan-review caught that 121 of 1190 rows (91 `"Deer Permit: …"` / `"Elk Permit: …"` rows + 30 per-HD `"Antelope License: XYZ"` rows) would have aborted — two additional code families not in the spec. The plan was revised to 5 branches before implementation. The rule: for any `if/elif/else: raise RuntimeError` over a closed-set label (`license_kind`, `species_group_label`, `season_key`, `document_type`), run `collections.Counter(row[field] for row in artifact)` against the full artifact and enumerate every value seen before writing the branch list. Surfaced by S03.7 plan-review 2026-05-15.

### Pydantic `frozen=True, extra="forbid"` models — enumerate every required field at construction time

- **When constructing Pydantic models with `ConfigDict(frozen=True, extra="forbid")`, mechanically enumerate every field with no default and no `Optional` annotation before writing the constructor call.** A missed required field raises `ValidationError` at the first production row, not at import time. The cost at plan-review is one revision cycle; at runtime it is a full re-run plus a debug cycle to locate which builder omitted which field. Example: `schema.py:ClosurePredicate.notification_channel` has no default — S03.7 plan-review caught a T8 draft that didn't read it from the artifact. Fix: grep `schema.py` for the model class, list all fields that have no `= ...` or `Optional` annotation, and verify each is read from the artifact dict at the call site. Surfaced by S03.7 plan-review 2026-05-15.

### DEA artifact has duplicate `license_code` rows within sections — let UPSERT collapse, not the builder

- **Some DEA sections contain two rows with the same `license_code` value (202 sections affected in V1 Montana DEA).** Both rows produce the same deterministic `license_tag.id` and collide at the UPSERT layer. The semantic payload is the UNION of `season_coverage` across same-code rows; license-level fields are structurally identical across duplicates. **Do NOT pre-deduplicate in the builder.** Emit both rows; let the UPSERT `ON CONFLICT (id) DO UPDATE` collapse duplicate `license_tag` rows, and let `license_season` link rows collapse via `ON CONFLICT DO NOTHING`. Pre-deduplicating in the builder requires a parallel accumulator, adds complexity, and doesn't express the union semantic cleanly. Reference: `_build_dea_license_tags` in `load_seasons_and_licenses.py`. Locked by `test_duplicate_license_code_rows_collapsed_by_upsert`. Surfaced by S03.7 implementation 2026-05-15.

### Downstream FK adapters must grep upstream adapters for exact id-construction patterns

- **Before writing any adapter that populates a link table whose composite FK targets a previously-loaded entity, grep the upstream adapter for the exact id-construction expression and copy it verbatim.** A single-character drift in jurisdiction_code, species_group, license_year, or any other FK component breaks every link-row insert with a FK violation that is hard to diagnose (the error names the constraint, not which field drifted). Example: S03.7's bear builders use `jurisdiction_code = f"MT-HD-bear-{bmu_number}"` — this must match S03.6's `load_regulation_records.py:366` exactly. Pattern: add a code comment at the call site naming the upstream adapter and the line number where the original expression lives, e.g. `# must match load_regulation_records.py:366 exactly`. Optionally lock with a cross-module test that constructs both ids from the same fixture and asserts equality. Surfaced by S03.7 implementation 2026-05-15.

### DEA cross-listed B Licenses can carry conflicting structural fields across HD sections

**Symptom:** A `draw_spec` builder that groups rows by `license_code` and assumes same-code rows are structurally identical silently writes the wrong quota (or wrong hunt_code) — whichever row happened to be processed last wins.

**Cause:** A single `license_code` (e.g., `Elk B License: 210-03`) can appear in multiple DEA HD sections. The home-HD section shows the total drawable quota; cross-listed mentions in other HD sections show per-HD allocation caps — different `quota` values, same `license_code`, identical `extras` text. The DEA artifact faithfully records each appearance; collisions surface only when the adapter groups by `license_code` to build one `draw_spec` row per license.

**Real example (DEA 2026, pp. 53/54/57):** `Elk B License: 210-03` appears with `quota=300` in HD 210 (home) and `quota=200` in HDs 211, 212, 216 (cross-listed). Detail text is identical on all four rows: `"Valid on private lands in HDs 211, 212, 216 and south portion of 210..."`.

**Fix:** Pre-write consistency validator that groups draw_spec candidates by `(hunt_code, year)` PK; fail-loud on undocumented field conflicts; allow override entries in `_KNOWN_CROSS_LISTING_OVERRIDES` with a WARN log + rationale string. Reference: `_validate_cross_listing_consistency` in `ingestion/states/montana/load_draw_specs.py`. The per-HD allocation-cap structural gap (home vs. cross-listed quota semantics) is deferred to M2 per `docs/open-questions.md` Q17.

**Why it matters for future adapters:** The "same `license_code` = same data" assumption is FALSE for FWP DEA tables. Any adapter that builds entity rows keyed on `license_code` must validate cross-row structural agreement at build time, before writing.

Surfaced by S03.8 Stage 6 silent-failure-hunter on 2026-05-18.

### DEA `license_tag.kind` requires inspecting `apply_by`, not just `license_code`

**Symptom:** All B License rows are classified as `limited_draw`, but 160 of them are actually over-the-counter purchases — wrong `draw_spec` rows are written (or attempted) for OTC licenses.

**Cause:** A B License row's `license_code` alone (e.g., `Deer B License: 262-50`) does NOT discriminate drawing-eligible B Licenses from OTC B Licenses. The discriminator is the `apply_by` column: cells containing `"OTC:\nJun 15"` (or any `OTC:` prefix) indicate an OTC purchase window; cells containing only a date (e.g., `"Jun 1"`) indicate a drawing deadline. S03.7's original 5-branch heuristic classified all B License rows as `kind='limited_draw'` before S03.8 corrected it.

**Compounding factor:** The same `(species, hd_number, license_code)` triple can appear in multiple artifact rows with different `apply_by` values (extraction noise from S03.3's table structure). Apply OTC-wins discipline: any artifact row showing OTC demotes ALL rows of that identity to `over_the_counter`.

**Fix:** Pre-pass computes `_otc_identities: frozenset[tuple[str, str, str]]` from all artifact rows; per-row classification consults the set before assigning `kind`. `apply_by` must be type-guarded (`isinstance(str)`) before substring matching — raise on schema drift rather than silently defaulting. Reference: `_build_dea_license_tags` in `ingestion/states/montana/load_seasons_and_licenses.py` (post-S03.8 T1 amendment). Baseline post-fix: 390 `limited_draw` / 160 `over_the_counter` / 239 `general` / 1 `statewide`.

Surfaced by S03.8 Stage 2 discovery probe on 2026-05-17.

### DEA front-matter carries authoritative deadlines when per-row `apply_by` is genuinely null

**Symptom:** A `draw_spec` row has `application_deadline=None` even though the FWP source has a published deadline for that species/kind combination.

**Cause:** When a DEA per-row `apply_by` cell is genuinely blank (FWP chooses not to repeat the deadline in-table when it's already in the booklet's front-matter), the per-row extraction faithfully records `apply_by=None`. The canonical deadline lives in the DEA booklet's front-matter sections: pp. 5 "Highlights", p. 9 "Important Dates", pp. 10–11 "License Charts". This is not an extraction defect — the cell is blank by design.

**V1 chart values (DEA 2026, MT):**

- Deer/Elk Permit: April 1
- Deer/Elk B License (Drawing) + Antelope License + Antelope B: June 1

**Fix:** Adapter-level fallback lookup `_DEA_DEADLINE_LOOKUP: dict[tuple[str, str], date]` keyed on `(species, kind_token)` and populated from the front-matter chart values. Apply only when per-row `apply_by` is null; emit a WARN log on each hit (expected zero hits in V1 — any hit in production signals PDF drift and needs operator review). Reference: `_DEA_DEADLINE_LOOKUP` in `ingestion/states/montana/load_draw_specs.py`.

Surfaced by S03.8 Stage 2 B4 probe on 2026-05-17.

### E03 story discovery — source-audit upstream artifacts for every epic-required row type before planning

**Symptom:** An epic spec enumerates N output rows ("ingest 3-4 statewide reporting obligations: CWD sampling, Bear ID coursework, mandatory reporting, …"), but during implementation the upstream extraction artifact is missing the source text for one or more of them. Mid-pipeline gate decisions, scope-down probes, and unplanned upstream-amendment carve-outs result.

**Cause:** Story specs are authored against expected source content (often based on prior-year PDFs or web pages); the upstream-artifact extraction job that S03.X depends on may not have captured each named row type. Without a pre-plan audit, the mismatch surfaces only after the discovery agent's codebase trace — late, expensive, and gate-blocking.

**Fix:** The discovery agent's FIRST action for any S03.X story should be: enumerate the row types named in the epic spec, then grep the named upstream extraction artifacts for keywords matching each. Cheap (one grep per row type), catches scope mismatches before they reach the plan-review stage. Pattern bit twice — S03.8 B5 (Permit-row sub-rows missing from artifact), S03.9 three-blocker (Bear ID coursework, CWD sampling unified section, all-species mandatory reporting all missing from artifact).

Surfaced by S03.9 Stage 2 three-blocker probe on 2026-05-19.

### `reporting_obligation.kind` semantic boundary — post-harvest / in-season only

**Symptom:** A rule that is a pre-purchase licensing prerequisite (e.g., Bear Identification Test, hunter education certification) gets modeled as a `reporting_obligation` row with `kind="mandatory_check"` or a new `kind="education"` enum value.

**Cause:** `reporting_obligation` is defined in CLAUDE.md as "post-harvest/in-season duties." Pre-purchase prerequisites are operationally distinct — the hunter must complete them BEFORE they can buy the license, not AFTER they harvest an animal. Conflating the two would mis-answer consumer queries like "what mandatory checks does a successful hunter perform?" because the same `kind="mandatory_check"` value would mix check-station physical inspection of harvested animals with one-time pre-purchase certification.

**Fix:** Pre-purchase prerequisites belong in `regulation_record.additional_rules` keyed by a STATEWIDE anchor (e.g., `MT-STATEWIDE-bear`), mirroring the existing `MT-STATEWIDE-antelope` pattern from S03.6. The decomposed-entity story (ADR-010) is the right home for STATEWIDE pre-purchase rules; do not extend `reporting_obligation` to carry rules that aren't reporting or obligations. Concrete carve-out example: S03.6.1 (queued post-S03.9) writes `MT-STATEWIDE-bear` with the Bear ID Test verbatim text in `additional_rules`.

Surfaced by S03.9 Probe 1 on 2026-05-19 (PM reversed the initial "fold into S03.9" recommendation after the target-table mismatch was identified).

### `id text`-PK UPSERTs currently update slug-encoded fields on conflict — Q19 tracks the project-wide drift-guard fix

**Symptom:** A dispatch-dict edit changes a slug-encoded structured field (e.g., `kind`, `deadline_hours`, `applies_to_regions`, `weapon_type`, `residency`, `license_code`, `species`) but the corresponding `id_suffix` / id-derivation stays the same — and the next re-ingestion run silently rewrites the meaning of existing rows under the same `id` via the helper's `ON CONFLICT (id) DO UPDATE` clause. Any link-table rows (`license_season`, `regulation_season`, `regulation_license`, `regulation_reporting`) already pointing at that id now reference an entity whose semantics shifted.

**Affected helpers** (all in `ingestion/ingestion/lib/db.py`):

- `_UPSERT_SEASON_DEFINITION_SQL` (S03.7) — updates `name`, `weapon_type`, `residency` on conflict
- `_UPSERT_LICENSE_TAG_SQL` (S03.7) — updates `license_code`, `name`, `kind`, `species` on conflict
- `_UPSERT_REPORTING_OBLIGATION_SQL` (S03.9) — updates `kind`, `deadline`, `applies_to_regions` on conflict

**Cause:** For all three `id text`-PK tables, the `id` slug is a hand-encoded string built from a subset of the entity's structured fields (e.g., `mt-bear-harvest-report-48hr-statewide` encodes kind+deadline+scope). The UPSERT has no way to know "the slug came from these fields, but the fields have changed" — both states satisfy the conflict clause; DO UPDATE wins by definition. The risk is dormant during initial V1 ingestion (fresh DB, no conflicts) but becomes load-bearing on the first year-over-year re-ingestion run.

**V1-safe right now:** Closed compile-time dispatch dicts (no operator-runtime mutation path); unit tests lock canonical slug↔field pairings; V1 ingestion runs once against fresh artifacts. The project-wide fix shipped via ADR-020 (`ingestion/ingestion/lib/drift_guard.py`) — use `assert_dispatch_dict_drift_free(dispatch, derive_id, *, helper_name, id_field)` for compile-time dispatch-dict surfaces (S03.9 pattern) and `assert_id_matches(entity_id, expected_id, *, helper_name, context)` for runtime construction-time surfaces (S03.7 pattern). The local `_assert_dispatch_dict_drift_free` previously in `load_reporting_obligations.py` is superseded by the shared primitive.

**Fix:** Resolved by ADR-020 (`docs/adrs/ADR-020-id-text-pk-slug-derivation.md`, Status: Proposed pending PM accept). For each `id text`-PK helper whose UPSERT DO UPDATE clause can rewrite slug-encoded fields, encode the id derivation as a pure callable and assert that every stored or constructed entity's id matches its derivation — drift becomes impossible by construction. Any new state adapter (M2+) writing to `season_definition`, `license_tag`, or `reporting_obligation` MUST adopt this pattern. New helpers writing to other `id text`-PK tables with mutable identity in UPDATE clauses MUST do the same.

Surfaced by S03.9 cubic-review round 3 on 2026-05-21; resolved on `fix/Q19-id-text-pk-slug-drift` on 2026-05-28.

### `submission_method` interpretation for multi-modal source text

**Symptom:** A `reporting_obligation`'s verbatim source text lists multiple submission channels (e.g., "deliver in person or by mail," "call 1-877-FWPWILD or use MyFWP portal at fwp.mt.gov"), but the schema `submission_method` Literal accepts ONE value. Picking arbitrarily creates audit-trail ambiguity; picking the wrong primary modality embeds wrong operational guidance.

**Cause:** Schema design is single-modality but real source text is multi-modality. The structured field is a lossy summary of the verbatim text.

**Fix:** Pick the FIRST channel mentioned in the verbatim (the headlined modality — the one the source authors led with). The full `verbatim_rule` preserves the source faithfully so the choice is non-lossy at the data layer; the structured `submission_method` is a hint, not authority. Document the call in the working note (which channel was picked, why, and what alternatives the verbatim lists). Concrete examples in V1 Montana bear reporting:

- STATEWIDE harvest_report: verbatim leads "Harvest Reporting ................. 1-877-FWPWILD or 1-877-397-9453 or 406-444-0356 or through the MyFWP portal at fwp.mt.gov" → pick `"phone"` (toll-free phone is headlined). `submission_phone="1-877-FWPWILD"`; `submission_url="https://fwp.mt.gov"` for the MyFWP-portal hint.
- R1 tooth_submission: verbatim says "deliver them to an FWP office within 10 days, either in person or by mail" → pick `"agency_office"` (FWP office leads; mail is the alternative).

Surfaced by S03.9 Probe 1 on 2026-05-19.

### Fail-soft extractor paths that defer loud failure to a downstream row-count guard must emit a visible warning at extraction time

**Symptom:** An extractor function that uses a regex anchor to locate a PDF region returns `[]` silently when the anchor doesn't match (anchor has shifted or PDF was regenerated from a stale source). The downstream row-count guard eventually raises `RuntimeError`, but by then extraction and loading may have run in separate sessions — hours or days apart.

**Cause:** Fail-soft early-return paths (`return []` instead of `raise`) are sometimes correct (anchor absence is a recoverable condition, not a programmer error). But "recoverable" does NOT mean "quiet." Without an extraction-time warning, the diagnostic latency between the silent extraction failure and the downstream OQ7-band RuntimeError is measured in sessions, not milliseconds.

**Fix:** When an extractor's fail-soft path defers loud failure to a downstream row-count guard, the extractor MUST emit `_logger.warning(...)` before the early return. The warning should name (a) the page number or page range probed, (b) the source PDF / source-id, and (c) a pointer to which downstream guard will catch the regression. This rule applies only to fail-soft returns — `raise RuntimeError` paths are already loud and need no additional warning. Reference: `_extract_statewide_rules` in `ingestion/states/montana/extract_black_bear.py` (S03.6.1 review — silent-failure-hunter W2 finding).

Surfaced by S03.6.1 Stage 6 review on 2026-05-22.

### `with db.connect()` context manager commits on clean exit — explicit `conn.commit()` inside is the real gate

psycopg3's `Connection.__exit__` calls `self.commit()` on a clean exit and `self.rollback()` on an exception. The project adapter pattern calls explicit `conn.commit()` inside the `with` block before `__exit__` runs; the implicit context-manager commit is therefore a no-op (the transaction is already closed). This is safe but can be confusing to a reader who asks "is there a double-commit risk?" There is not — the explicit `conn.commit()` is the real gate; the `with` is the rollback-on-exception safety net. The ordering must be documented in every adapter's commit site so a refactor doesn't accidentally remove the explicit call (believing the `with` covers it) and lose the fail-loud "commit only after all loops complete" discipline.

Surfaced 2026-05-23 during S03.10 Stage 6 silent-failure-hunter review. Reference: `load_jurisdiction_bindings.py::main()` commit site comment.

### Per-builder dedup sets miss cross-builder collisions — add a global dedup check in `main()`

**Symptom:** An adapter has two or more binding/entity builders, each maintaining its own `seen_ids: set[str]` for duplicate detection. A cross-builder collision — same `id` produced by two different builders — is invisible to both per-builder sets and produces a second UPSERT call rather than failing.

**Fix:** After collecting all built entities (`all_entities = builder_a_results + builder_b_results + ...`), run a global dedup check before the write phase:

```python
all_ids = [e.id for e in all_entities]
if len(all_ids) != len(set(all_ids)):
    dupes = [i for i in all_ids if all_ids.count(i) > 1]
    raise RuntimeError(f"Cross-builder id collision: {dupes}")
```

The per-builder sets remain useful for detecting intra-builder collisions early (fail at construction time, not write time). The global check is the final gate. Reference: `load_jurisdiction_bindings.py::main()` pre-write global dedup.

Surfaced 2026-05-23 during S03.10 Stage 6 code-review. Relevant for any adapter with 2+ builders producing the same entity type (S03.6.1 had separate statewide + per-HD builders; S03.10 has statewide + overlay + no-hunt-zone builders).

### `Model.model_validate(...)` inside a dict-comprehension swallows row identity on failure

**Symptom:** A Pydantic `ValidationError` surfaces with the raw field path but no indication of which source row, geometry ID, or dict key triggered it. A comprehension like `{str(row[0]): SomeModel.model_validate(row[1]) for row in rows}` loses the outer iteration variable when it raises.

**Fix:** Refactor any `model_validate` call inside a comprehension to an explicit for-loop with a try/except that wraps the identity:

```python
result: dict[str, SomeModel] = {}
for row in rows:
    entity_id = str(row[0])
    try:
        result[entity_id] = SomeModel.model_validate(row[1])
    except Exception as exc:
        raise RuntimeError(f"entity {entity_id!r} has malformed source jsonb: {exc}") from exc
```

Apply this pattern for any `model_validate` call that iterates over DB rows, artifact dicts, or YAML entries — the diagnostic value of knowing WHICH item failed is worth the extra lines. Reference: `load_jurisdiction_bindings.py::_fetch_geometry_sources` post-S03.10 review fix.

Surfaced 2026-05-23 during S03.10 Stage 6 code-review.

### Live-DB write is operator-driven — closure-note row counts describe dry-run-verified shape, not DB state

**Symptom:** A story's S03.X implementation plan or pre-flight probe runs `SELECT count(*) FROM regulation_record` and gets 0, even though earlier closure notes in CLAUDE.md describe "437 regulation_record rows" written at S03.6 close.

**Cause:** The CLAUDE.md closure narrative describes the adapter's output shape as verified by the dry-run path. Live writes only happen when an operator explicitly invokes the loader script. In the single-developer workflow, earlier story loaders may never have been invoked live (only dry-run); the T0 probe for S03.10 confirmed `regulation_record=0` and `jurisdiction_binding=0` despite 11 completed prior stories.

**Fix:** Any story that depends on prior loaders' DB state (e.g., S03.10 joining `regulation_record` to build bindings) must include an explicit operator pre-flight step to run the prior loaders in FK order. The T16 prerequisites block in `S03.10.md` is the canonical checklist format:

```bash
ingestion/.venv/bin/python ingestion/states/montana/load_state_boundary.py
ingestion/.venv/bin/python ingestion/states/montana/load_regulation_records.py
# ... in FK-safe order; then the current story's loader
```

Do not assume the DB matches the closure-note narrative. Probe DB state with a COUNT query at plan time. Surfaced 2026-05-23 during S03.10 T0 pre-flight probe.

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

### `detect-secrets` pre-commit hook updates `.secrets.baseline` line numbers on every commit that grows tracked files

**Symptom:** `git commit` reports `Detect secrets... Failed - exit code: 3 - files were modified by this hook` with `The baseline file was updated. Probably to keep line numbers of secrets up-to-date. Please \`git add .secrets.baseline\`, thank you.` The diff on `.secrets.baseline` is a pure line-number shift on an existing tracked false-positive — no new finding, no new line, just `line_number: N` → `line_number: N+k` where `k` is the number of lines added above it in the same file.

**Cause:** A pre-existing false-positive in `.secrets.baseline` (e.g., the BMU `300*` footnote pitfall in `.roughly/known-pitfalls.md`) has its absolute line number recorded. When a commit adds content to that same file above the false-positive's line, every subsequent run of `detect-secrets` rewrites the baseline's `line_number` field to match the new position. The hook intentionally surfaces this as a fail-loud "stage the new baseline" gate rather than silently rebasing on the operator's behalf.

**Fix:** Stage the modified baseline and re-commit. The diff is mechanical — verify it's only `line_number` and `generated_at` fields shifting, not a new finding:

```bash
git diff .secrets.baseline | grep -E '^[+-]' | head   # confirm no new `results` entries
git add .secrets.baseline
git commit -m "..."  # retry the original commit
```

If the diff shows a new `results` entry (not just a line-number shift), inspect what triggered it — that's a real new finding, not the drift case.

Surfaced repeatedly across stories (S03.6 wrap-up is the most recent); recurring whenever a story adds substantial content to a file that already has a tracked false-positive entry. The hook's behavior is correct and intentional — this entry exists to short-circuit the cognitive surprise of "wait, what just changed?"

## Conventions — Documentation & planning discipline

### Deferred open-question verdicts require an amendment-pending breadcrumb in `docs/open-questions.md`

**Symptom:** An audit story yields a PARTIAL DEFER verdict on an open question (e.g., S03.11 on Q11: the `low` confidence tier has 0 rows in V1 Montana, so ADR-017 §7 Trigger 2 cannot be validated). A DRAFT amendment is authored (`docs/adrs/ADR-017-amendment-DRAFT.md`) and a working note is filed (`docs/planning/epics/E03-confidence-findings/S03.11.md`). The original Q11 entry in `docs/open-questions.md` is left unannotated. The working note deletes at the m1 tag commit per ADR-017 §6. After that deletion, no surviving-past-m1 signal flags that a DRAFT exists — a future reader scanning `docs/open-questions.md` sees Q11 in its original form and may silently let the DRAFT rot.

**Cause:** Story plans that handle the RESOLVED path (T11: "update Q11 to resolved") do not automatically handle the DEFERRED path. The working note is the only record of amendment-pending status, and working notes are ephemeral by design.

**Fix:** Any audit story whose verdict DEFERS (rather than RESOLVES) an open question MUST add a status annotation directly to the entry in `docs/open-questions.md` before the story closes. The annotation must be placed immediately under the question heading and include: (a) the date + gating story, (b) a markdown link to the DRAFT file, (c) a markdown link to the synthesis report, and (d) a sentence naming what user action closes the deferral. Example format:

```text
**Status (2026-05-26 via S03.11):** OPEN — amendment-pending user review.
See [`docs/adrs/ADR-017-amendment-DRAFT.md`](docs/adrs/ADR-017-amendment-DRAFT.md) and
[synthesis report](docs/planning/epics/E03-confidence-calibration-synthesis.md).
Closes when user approves and commits the amendment as the official ADR-017 revision.
```

This annotation is the only breadcrumb that survives the m1 working-note deletion. Discovered by silent-failure-hunter MEDIUM finding during S03.11 code review (2026-05-26); applied as a post-merge fix to Q11.

### File-deletion events require a paired grep-and-sweep for stale cross-references

**Symptom:** A milestone-deletion commit removes a directory of working files (e.g., `docs/planning/epics/E03-confidence-findings/` deleted per ADR-017 §6 at S03.12 close). A T9 reference sweep surfaced 19 stale references across 11 surviving files — docstrings, comments, operator-facing `RuntimeError` f-strings, and policy descriptions in docs. The same pattern surfaced at S03.11 (`docs/plans/` → `.roughly/plans/` migration, 8 stale references).

**Cause:** `git mv` and `git rm` move or remove the content but do not grep for references. Operator-facing error messages are highest-risk: they fire in production and point operators at paths that no longer exist.

**Fix:** Before executing any deletion or rename, run a four-step sweep:

1. Identify all references: `grep -rn <deletion-target> docs/ ingestion/ mcp-server/ web/`
2. Audit the deletion target for downstream-dependent content (e.g., operator runbooks embedded in working notes must migrate to a surviving doc before deletion).
3. Triage references: redirect to surviving doc, annotate with deletion note, or delete the cross-reference.
4. For operator-facing `RuntimeError` / log messages: redirect is mandatory — leaving operators pointing at a 404 path is a production diagnostic failure.

Surfaced by S03.12 T9 stale-reference sweep on 2026-05-27 (19 references in 11 files); prior instance S03.11 (8 references in 8 files).

### When UAT runs against a PRD that has drifted from implementation, footnote each deviation — do not silently reframe

**Symptom:** A UAT runbook is written against a PRD whose success criteria reference column names, query patterns, or story-specific details that were superseded during implementation. The runbook silently uses the "correct" query without noting the deviation, losing the audit trail between the PRD and the as-built system.

**Cause:** PRDs serve as source-of-record and are not autonomously edited by PMs. When implementation deviates (schema decomposition, HD substitution, Makefile not yet built, etc.), the gap between PRD text and DB reality can be large enough to make individual success criteria non-executable as written.

**Fix:** When authoring a UAT runbook against a drifted PRD, footnote each deviation inline. The footnote names: (a) what the PRD says, (b) what the as-built system actually has, and (c) the durable record of the decision (closure note, ADR reference, or OQ resolution). This preserves the PRD as source-of-record while making the runbook actionable. S03.12 surfaced 6 deviations: `jurisdiction_code` format (`HD-262` → `MT-HD-deer-elk-lion-262`); missing `verbatim_text` column (decomposed per Q15/OQ1); HD 262 elk asymmetric-coverage shift to HD 170 (S03.7 OQ-S7-3); `make ingest` Makefile nonexistent; `license_season` RLS gap; ADR-017 status resolved unmodified per S03.11. Reference: `docs/runbooks/M1-uat.md` footnote conventions.

Surfaced by S03.12 UAT runbook authoring on 2026-05-27.
