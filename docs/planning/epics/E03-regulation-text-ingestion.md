# E03: Montana Regulation Text Ingestion

**Status:** Not Started
**Milestone:** M1 — Montana Ingestion
**Dependencies:** E01 (complete, merged 2026-04-28), E02 (complete and audited 2026-05-03)
**Validated:** 2026-05-03
**Estimated Stories:** 13
**UAT Gating:** S03.3, S03.4, S03.5 (per-booklet faithfulness review), S03.7, S03.10, S03.12 (entity ingestion + binding + milestone exit)

---

## Objective

E03 extracts every Montana regulation text relevant to the five V1 species (elk, mule deer, whitetail, pronghorn, black bear) from the three published FWP PDFs (DEA biennial, Black Bear annual, Legal Descriptions biennial) plus the Black Bear correction PDF, maps that text into the five remaining V1 entities (`regulation_record`, `season_definition`, `license_tag`, `draw_spec`, `reporting_obligation`), generates `jurisdiction_binding` rows by joining the new `regulation_record` rows with E02's overlay fixture, resolves Q11 (confidence calibration) via ADR-017, and produces the M1 UAT artifact set so the milestone tag can be pushed.

This is the largest and most variable epic in M1. PRD 001 R1 anticipates extraction variance; ADR-006 anticipates schema revision in response to real-data stress. **Story revisions surfaced mid-epic are expected and should be flagged as encountered, not batched at the end.**

See [PRD 001](../../planning/prds/001-M1-montana-ingestion.md) for authoritative scope. See [`docs/research/montana-source-structure-findings.md`](../../research/montana-source-structure-findings.md) for verified PDF structure findings.

---

## Architectural commitments inherited from E01/E02 + E03 ADRs

| Commitment | Source | E03 implication |
|---|---|---|
| Verbatim regulation text — no paraphrase | ADR-001, ADR-008 | Every regulation_record / season_definition / license_tag / reporting_obligation row's `verbatim_rule` is the source string, byte-for-byte. Lossy extractions raise loudly. |
| Three-place schema sync (DDL, Pydantic, TypeScript) | ADR-006 | S03.0 ships ADR-018's three schema additions in one migration with all four legs in the same PR (DDL, Pydantic, TypeScript, architecture.md). |
| Source citation on every row | ADR-001, ADR-014 | Every entity row has `source: SourceCitation` populated. PDF-sourced rows: `document_type='annual_regulations'`. Black Bear correction-touched rows: `document_type='correction'` with `supersedes` populated. ArcGIS-sourced rows: `document_type='gis_layer'`. |
| Schema versioned from day one | ADR-006 | `schema_version=2` on `regulation_record` and `draw_spec`. ADR-017 explicitly ties confidence-framework versioning to `schema_version`. |
| Confidence inheritance + spatial-confidence carve-out | ADR-017 | `regulation_record.confidence` derives via MIN aggregation; child entities inherit at query time (no per-entity confidence column); correction-touched rows demote one tier; geometry/jurisdiction_binding carry **provenance**, not confidence. |
| E03 schema additions | ADR-018 | `license_season` link table; `geometry.legal_description text` (nullable); `geometry.kind='state'` value; one Montana state geometry row. All shipped by S03.0. |
| `parameters` escape hatch deferred (Q12) | PRD 001 §"Out of scope", Q12 | If extraction surfaces a draw mechanic that seems to demand `parameters`, flag-and-defer per the operational definition below. **Add to `docs/planning/epics/E03-deferred-items/draw-mechanics.md` for M2 handoff.** Do not exercise the field. |

### "Flag" operational definition (used throughout E03)

When a story spec says "flag X for PM review" or "flag-and-defer," the implementer MUST do all four of the following:

1. **Structured anomaly artifact:** add an entry under the relevant filename in `docs/planning/epics/E03-confidence-findings/<story>.md` (working note for ADR-017 audit, deleted at `m1` tag) OR `docs/planning/epics/E03-deferred-items/<topic>.md` (durable; survives past M1; promise to M2). Calibration vs. deferred is the distinction — see "Working artifacts and deferred items" below.
2. **WARN log** at ingestion time with sufficient context (row id, source span, pattern matched).
3. **Open-questions entry** in `docs/open-questions.md` if the flag identifies a recurring decision class (PM authors after review, not the implementer).
4. **Non-silent commit:** the run summary surfaces the flagged count; the story PR description lists the flagged items by category. CI does not pass if a story-spec'd hard-flag fires without an artifact entry.

A "flag" is never silently dropped, silently special-cased, or silently committed. The whole point of the operational definition is that flagging produces a durable record at multiple layers.

---

## Inputs from E02

| Artifact | Source | E03 use |
|---|---|---|
| `geometry` table (349 rows) | E02 S02.2-S02.5 | FK target for `jurisdiction_binding.geometry_id`; `state` + `kind` already encode HD vs portion vs CWD vs RA. S03.0 adds the Montana state row (350th row). |
| `geometry-overlays.json` (kept fixture) | E02 S02.6 | Direct input to `jurisdiction_binding` generation in S03.10 — `parent_geometry_id` + `child_geometry_id` + `role_for_e03` pre-computed. **S03.10 must filter by species axis** (cross-species pairings exist in the fixture and are not regulatorily bound — see S03.10 spec). |
| `geometry-overlays-dropped.json` (audit log) | E02 S02.6 | NOT consumed by E03 per ADR-016 — those rows are below the 1% area-overlap threshold and were excluded by design. |
| `EXPECTED_RA_ORPHAN_IDS` allowlist (3 IDs) | E02 S02.6 | Glacier NP, Sun River Game Preserve, Yellowstone NP. These are no-hunt zones with no parent HD — see S03.10 for binding strategy (Option A: bind to nearby HDs as `other_overlay`, deterministic "nearby" definition). |

---

## Working artifacts and deferred items

E03 produces two categories of supplementary artifacts that have **different retention policies**:

| Category | Location | Retention | Purpose |
|---|---|---|---|
| **Calibration findings** (working notes for ADR-017 drafting/audit) | `docs/planning/epics/E03-confidence-findings/<story>.md` | **Deleted at the `m1` tag commit** (manual `git rm -r` in S03.12's final commit). Directory listed in `.gitignore` post-M1 to prevent re-creation. | Per-story signals + edge cases that fed S03.11's audit. The ADR is the durable record; the working notes are scaffolding. |
| **Deferred items** (Q12 + any other deferral surfaced during E03) | `docs/planning/epics/E03-deferred-items/<topic>.md` | **Survive past M1 close.** Carried into M2 PM handoff. | Promises to M2: things E03 surfaced that V1 explicitly defers. Initial files: `draw-mechanics.md` (per Q5 — antelope `900-20` + any other Q12 cases). Additional files added if anything else surfaces. |

**S03.0 creates both directories** with a `README.md` in each documenting the survival/deletion policy.

---

## Stories

### S03.0: Schema preparation — license_season + geometry.legal_description + geometry.kind='state' + Montana state geometry

**As a** developer preparing E03's schema additions before any text is extracted
**I want** ADR-018's three schema additions applied with three-place sync, plus the Montana state boundary geometry written, plus the working-artifact directories created
**So that** S03.5 / S03.6 / S03.7 / S03.10 have the schema and reference data they depend on

**UAT: no**

**Context:**

Mirrors E02's S02.0 pattern. ADR-018 has been accepted (the architecture.md update is part of this story's deliverable, not a separate human-approval gate, per ADR-018 §"Three-place sync"). Per ADR-006, all four legs of the change ship in the same PR.

**Schema additions (per ADR-018):**

1. **`license_season` link table** — explicit per-license season coverage (resolves the A/B asymmetric-coverage problem documented in ADR-018 §1)
2. **`geometry.legal_description text` (nullable)** — boundary-description prose, distinct from `verbatim_rule` regulatory text (ADR-018 §2)
3. **`geometry.kind` enum extended with `'state'`** — supports state-level boundary polygons (ADR-018 §3)

**Montana state geometry deliverable:**

S03.0 also writes one `geometry` row:
- `id='MT-STATEWIDE-geom'`
- `kind='state'`
- `state='US-MT'`
- `geom`: Montana state boundary as a MultiPolygon, validated via `shapely.make_valid()`
- `license_year=NULL` (year-invariant per ADR-018 §3 — state boundaries don't change between license years; HD definitions can)
- `source`: `SourceCitation` per source-priority rule below

**Source priority** (per ADR-018 §3):
1. **First preference:** an FWP-published state boundary (ArcGIS layer or downloadable GeoJSON), if one exists. `document_type='gis_layer'` per ADR-014.
2. **Fallback:** US Census TIGER 2020 state shapefile (`https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html`). Pin to specific file URL + SHA in the load script + the calibration-findings artifact.

The S03.0 implementer picks during execution and documents the choice + SHA in `docs/planning/epics/E03-confidence-findings/S03.0.md`.

**Working-artifact directories:**

S03.0 creates:
- `docs/planning/epics/E03-confidence-findings/README.md` — explains "deleted at m1 tag commit" policy
- `docs/planning/epics/E03-deferred-items/README.md` — explains "survives past M1, promise to M2" policy

**Relevant ADRs:** [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md), [ADR-015](../../adrs/ADR-015-geometry-verbatim-rule-and-reg-comments-handling.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md).

**Acceptance Criteria:**

- [ ] New migration `supabase/migrations/<timestamp>_e03_schema_additions.sql` creates `license_season` table (composite PK + index per ADR-018 §1), adds `geometry.legal_description text NULL`, and updates `geometry.kind` CHECK constraint to include `'state'`
- [ ] Pydantic update (`ingestion/ingestion/lib/schema.py`): new `LicenseSeason` `BaseModel`; `Geometry.legal_description: str | None`; `Geometry.kind` Literal extended with `"state"`
- [ ] TypeScript update (`mcp-server/src/types/schema.ts`): matching changes; `tsc --noEmit` clean
- [ ] architecture.md §"Schema types": `LicenseSeason` interface + `Geometry.legal_description` + `kind='state'` documented (per ADR-018 §"Three-place sync" — pre-approved by the ADR sign-off, no separate human gate)
- [ ] One `geometry` row written: `MT-STATEWIDE-geom`, `kind='state'`, valid MultiPolygon, `license_year=NULL`, `source` populated per the source-priority rule
- [ ] Source choice + SHA recorded in `docs/planning/epics/E03-confidence-findings/S03.0.md`
- [ ] `docs/planning/epics/E03-confidence-findings/README.md` exists explaining deletion policy
- [ ] `docs/planning/epics/E03-deferred-items/README.md` exists explaining survival policy
- [ ] Migration applies cleanly to a fresh Supabase project after E01's + E02's migrations
- [ ] `ruff check`, `mypy`, `tsc --noEmit` all clean
- [ ] No regulation data loaded — schema-prep only

---

### S03.1: PDF fetch infrastructure

**As a** developer ingesting Montana regulation text
**I want** a deterministic, reproducible fetch path for the four V1 PDFs
**So that** S03.3-S03.5 can extract from local fixtures and source drift is detectable

**UAT: no**

**Context:**

Mirrors E02's S02.1 (ArcGIS fetch infrastructure) for PDFs. Three biennial/annual booklets plus one correction PDF, all hosted by MT FWP. Per [`docs/research/montana-source-structure-findings.md`](../../research/montana-source-structure-findings.md):

| PDF | Cadence | Pages | URL pattern (verify at execution time) |
|---|---|---|---|
| DEA (Deer Elk Antelope) booklet | Biennial (2026/2027) | 141 | `fwp.mt.gov/binaries/.../deer-elk-antelope-regulations-2026-2027.pdf` |
| Black Bear booklet | Annual (2026) | 16 | `fwp.mt.gov/binaries/.../black-bear-regulations-2026.pdf` |
| Legal Descriptions | Biennial (2026/2027) | 56 | `fwp.mt.gov/binaries/.../legal-descriptions-2026-2027.pdf` |
| Black Bear correction | Ad-hoc (2026-03-18) | 1 | TBD — discoverable from FWP "errata" or "corrections" pages |

**Deliverables:**
- `ingestion/ingestion/lib/pdf_fetch.py` — shared library with documented public API (`fetch_pdf`, `PdfMetadata`, `PdfFetchError`). State-agnostic per ADR-005.
- `ingestion/states/montana/sources.yaml` — registry of the four PDF URLs. Each entry carries the **full SourceCitation field set** that downstream stories will use:
  - `id` (deterministic; canonical SourceCitation id, e.g., `mt-fwp-dea-2026-2027-booklet`, `mt-fwp-black-bear-2026-correction-2026-03-18`) — this is the value `SourceCitation.supersedes` references for the correction case (per S03.4)
  - `agency` (e.g., "Montana Fish, Wildlife & Parks")
  - `title` (the booklet's official title)
  - `url`
  - `expected_page_count`
  - `expected_sha256` (or "unknown" for first run; populated after first successful fetch)
  - `document_type` (`annual_regulations` or `correction`)
  - `publication_date` (ISO date)
- `ingestion/states/montana/fetch_pdfs.py` — Montana adapter that reads `sources.yaml` and calls the shared library.
- Source-fixture write path: `ingestion/states/montana/fixtures/<slug>-<date>.pdf` (gitignored due to size — DEA may exceed 5MB) **and** a paired `<slug>-<date>-manifest.json` (committed) carrying `{filename, pdf_sha256, page_count, fetched_at, source_url, document_type, publication_date, citation_id}` for cross-operator drift detection. **Mirrors E02 S02.7's manifest-policy pattern.**
- `ingestion/states/montana/fixtures/.gitignore` updated to permit `*-pdf-manifest.json` while excluding `*.pdf`.

**SHA drift policy (hardened from "WARN+proceed"):** if a re-fetch produces a SHA-256 different from the prior manifest's `pdf_sha256`, the fetcher **raises `PdfFetchError`** and writes a `<slug>-pending-reextraction.flag` marker file. The marker file's existence blocks downstream stories (S03.3-S03.5) from proceeding against this PDF until an operator (a) acknowledges the drift, (b) decides whether to re-extract, and (c) deletes the flag. Drift is a real fault condition — silent proceed risks ingesting a PDF that doesn't match what was extracted from.

**Polite fetch:** Same throttling and User-Agent conventions from S02.1's ArcGIS infrastructure (`HUNTREADY_INGESTION_CONTACT` env var); 1 request per 500ms minimum.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md).

**Acceptance Criteria:**

- [ ] `ingestion/ingestion/lib/pdf_fetch.py` exists with documented public API
- [ ] `ingestion/states/montana/sources.yaml` exists with all four PDF entries; each entry carries the full SourceCitation field set per spec
- [ ] `ingestion/states/montana/fetch_pdfs.py` orchestrates the four fetches via the shared library
- [ ] Per-PDF manifest written at `<slug>-<date>-manifest.json` with all 8 fields; ~1 KB each; committed to repo
- [ ] Raw `.pdf` files stay local-only — gitignored at `ingestion/states/montana/fixtures/.gitignore` with anchor comment documenting the ~10MB-per-fetch policy
- [ ] Re-fetch against unchanged source produces identical manifest content (modulo `fetched_at`)
- [ ] **SHA-256 drift on re-fetch raises `PdfFetchError` AND writes `<slug>-pending-reextraction.flag` marker file.** Downstream stories check for the marker and refuse to proceed. Operator acknowledges → deletes marker → re-runs.
- [ ] `pdf_fetch.py` honors the same throttling + User-Agent conventions as `arcgis.py` (no PII baked into source; `HUNTREADY_INGESTION_CONTACT` env var)
- [ ] `ruff check`, `mypy ingestion/lib/pdf_fetch.py` clean
- [ ] Unit tests cover: happy path, 404, SHA-256 drift (raises + marker created), polite throttling, manifest determinism, full-citation-field round-trip
- [ ] No imports from state adapters; no Montana-specific code in the shared lib

---

### S03.2: PDF extraction primitives (shared library)

**As a** developer extracting regulation text from MT FWP PDFs
**I want** a state-agnostic shared library wrapping `pdfplumber` with table-detection, prose-extraction, and page-reference helpers
**So that** S03.3-S03.5 can extract per-booklet content without reimplementing primitives, and Colorado in M2 can reuse the same toolkit

**UAT: no**

**Context:**

Per PRD 001 R1: start with `pdfplumber` for primary extraction; use `unstructured` only if `pdfplumber` is insufficient (deferred unless S03.3-S03.5 prove insufficient). Library lives at `ingestion/ingestion/lib/pdf.py` (state-agnostic per ADR-005).

| Helper | Purpose |
|---|---|
| `open_pdf(path) -> PdfDocument` | Wraps `pdfplumber.open()`, captures filename + path for page-reference traceability |
| `extract_tables(page, settings)` | Wraps `page.extract_tables()` with sensible defaults; returns typed `TableMatch` records with detected bounding box and column headers |
| `extract_text(page, bbox=None)` | Wraps `page.extract_text()` with optional bbox crop; preserves whitespace; returns the verbatim string (no normalization) |
| `find_section(pdf, heading_pattern)` | Locates a heading by regex; returns `(page_num, bbox)` for downstream cropping |
| `iter_pages(pdf, start, end)` | Iterates page range with 1-based page numbers (matches print convention) |
| `PageReference` typed-dict | `{pdf_filename, page_num_1based, bbox: (x0, y0, x1, y1) \| None, extracted_at}` for traceability inside extraction artifacts |
| `page_reference_to_str(PageReference) -> str` | **Collapse helper** for storing in `SourceCitation.page_reference` (which is `str` per architecture.md). Deterministic format: `f"{pdf_filename}:p{page_num_1based}"` (bbox omitted from the string form — bbox is for in-extraction cropping, not for citation). |

**PageReference→str collapse rule:** the `PageReference` TypedDict is the rich form used inside extraction artifacts (where bbox matters for re-extraction). The `SourceCitation.page_reference` field is `str | None` per architecture.md (§"Schema types"). The collapse rule is **`f"{pdf_filename}:p{page_num_1based}"`** — deterministic, sortable, human-readable, bbox-stripped. If a future schema change promotes `page_reference` to jsonb, the rich form survives. For V1, the collapse is one-way and bbox lives only in the extraction artifact.

**Verbatim discipline (ADR-008 boundary):** `extract_text` returns the source string with no normalization, no whitespace squashing, no Unicode normalization. Downstream extractors are responsible for any cleanup (e.g., joining hyphenated line-breaks) and must document their cleanup rules in story context. Pure pass-through is the baseline; deviations are documented exceptions.

**Confidence calibration framework:** ADR-017 codifies the three-tier framework (`high` / `medium` / `low`) and the correction-touched demote rule. S03.2 implements the framework as enum values and helper functions; per-story confidence assignments follow the framework's signal definitions. Working notes for any framework-edge cases go in `docs/planning/epics/E03-confidence-findings/<story>.md` per the artifact policy.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md).

**Acceptance Criteria:**

- [ ] `ingestion/ingestion/lib/pdf.py` exists with documented public API per spec above
- [ ] `extract_text` returns source string with no normalization (verified by unit test on a known-whitespace fixture)
- [ ] `PageReference` TypedDict exposed for downstream callers; `page_reference_to_str` collapse helper produces deterministic strings
- [ ] Confidence framework helpers reference ADR-017 (signal definitions, MIN aggregation, correction-touched demote-one-tier rule)
- [ ] `ruff check`, `mypy ingestion/lib/pdf.py` clean
- [ ] Unit tests cover: table extraction on a fixture, prose extraction with bbox crop, page-reference round-trip (rich form ↔ collapsed str), whitespace preservation
- [ ] No Montana-specific code; no imports from state adapters

---

### S03.3: DEA booklet extraction (deer, elk, antelope)

**As a** developer extracting Montana big-game regulations
**I want** every per-HD regulation row from the DEA biennial booklet captured as structured Python data with verbatim source text and `PageReference` provenance
**So that** S03.6-S03.9 can ingest regulation_record / season_definition / license_tag / draw_spec rows from a clean intermediate

**UAT: yes** — faithfulness review against the DEA PDF for ≥3 sampled HDs (one per species: deer, elk, antelope; one of those should be a multi-license A/B HD with the per-license season-coverage asymmetry that S03.7 will translate into `license_season` rows).

**Context:**

DEA booklet structure per research (2026/2027 cycle, 141 pages):
- Per-HD regulation tables: pp. 48-123 (deer/elk), pp. 136-142 (antelope)
- Uniform 11-column structure: LICENSE/PERMIT, OPPORTUNITY, APPLY BY DATE, QUOTA, QUOTA RANGE, EARLY SEASON, ARCHERY ONLY, GENERAL, HERITAGE MUZZLELOADER, LATE, OPPORTUNITY SPECIFIC DETAILS
- Heading anchor: `HD {number} - {name}` regex
- Statewide overlay: antelope **900-series license** `900-20` (statewide pool of 5,600, range 1-7,500, archery-only) — **separate row, not per-HD**

**A/B license pattern (load-bearing):** Every deer/elk HD has a General (A) license + one or more B (antlerless) licenses with **independent season coverage** (e.g., A valid in Heritage Muzzleloader, B not). Per ADR-018, this becomes per-license `license_season` rows in S03.7. S03.3's extraction artifact MUST capture per-license season-presence indicators (true/false per season column per license row) — not just the season's presence at the HD level.

**Output artifact:** `ingestion/states/montana/extracted/dea-2026.json` (committed; deterministic). Schema:

```json
[
  {
    "hd_number": "262",
    "hd_name": "Madison Valley",
    "species_group": "elk",
    "license_year": 2026,
    "page_reference": {"pdf_filename": "...", "page_num_1based": 73, "bbox": [...]},
    "verbatim_text": "<full HD-262 elk subsection text, verbatim, after documented cleanup>",
    "rows": [
      {
        "license_code": "262-00",
        "opportunity": "General",
        "apply_by": null,
        "quota": null,
        "quota_range": null,
        "season_coverage": {
          "early_season": false,
          "archery_only": true,
          "general": true,
          "heritage_muzzleloader": true,
          "late": false
        },
        "season_windows": {
          "archery_only": "9/7-10/20",
          "general": "10/26-12/1",
          "heritage_muzzleloader": "12/2-12/15"
        },
        "weapon_types": ["any_legal_weapon"],
        "extras": "<verbatim opportunity-specific-details cell text>",
        "extraction_confidence": "high"
      },
      {
        "license_code": "262-50",
        "opportunity": "B (antlerless)",
        "apply_by": "5/1/2026",
        "quota": 75,
        "season_coverage": {
          "early_season": false,
          "archery_only": false,
          "general": true,
          "heritage_muzzleloader": false,
          "late": true
        },
        ...
      }
    ]
  }
]
```

`season_coverage` is the per-license coverage truth that S03.7 reads to write `license_season` rows. `season_windows` is the union across all licenses (same window structure shared per HD).

**Cleanup rules (documented exceptions to verbatim pass-through):**
- **Cell padding:** "padding" is leading/trailing whitespace **and** internal runs of 3+ consecutive spaces (which pdfplumber sometimes inserts at column edges). Definition: `re.sub(r'\s{3,}', ' ', cell.strip())`. Documented in `extract_dea.py` docstring with the exact regex.
- **Hyphenated line-breaks at column edges:** rejoin only when the hyphen sits between two lowercase letters across a newline. Regex: `re.sub(r'(?<=[a-z])-\n(?=[a-z])', '', text)`. **Critically:** this regex does **NOT** rejoin date ranges (`9/7-10/20`) or codes (`262-50`) because those have non-lowercase neighbors. Documented in `extract_dea.py` docstring with both the regex and a counter-example for date ranges.
- **Empty cells:** explicit `null`, not empty string. `season_coverage[<key>]=false` when the cell is empty (not present in coverage); `season_windows[<key>]` omitted when no license at the HD covers that season.
- **Source string preserved as `verbatim_text` at the section level** — even if cells are normalized for the structured `rows` payload, the section text retains the source's exact whitespace + characters. The structured payload is for ingestion convenience; the verbatim_text is the source-of-truth for ADR-008 reviews.

**Antelope statewide overlay handled separately:** the `900-20` license appears once at the antelope section's start; extraction emits a single statewide row with `species_group="antelope"`, `hd_number="STATEWIDE"`, `license_code="900-20"`, and the appropriate quota/range. S03.7 maps this to a `license_tag` with `kind='statewide'`. **S03.8 does NOT write a draw_spec for `900-20`** (per Q5/Q12 deferral — see S03.8 spec).

**Confidence assignment per ADR-017:**
- Each `row` (license row) gets an `extraction_confidence` per the three-tier framework. Most DEA cells are `high` (structured table cells). Cells requiring interpretation (e.g., `extras` opportunity-specific-details prose) may be `medium`.
- The HD's regulation_record-level confidence (computed by S03.6 via MIN aggregation across rows) is NOT in this story's output — S03.6 owns it.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S03.1, S03.2.

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/extract_dea.py` exists with `main(argv) -> int` CLI and produces deterministic `dea-2026.json`
- [ ] All deer/elk HD subsections (pp. 48-123) extracted with `verbatim_text` and structured `rows` (each row carrying `season_coverage`)
- [ ] All antelope HD subsections (pp. 136-142) extracted, plus the `900-20` statewide overlay row (with `hd_number="STATEWIDE"`)
- [ ] Every extracted row carries a `PageReference` and an `extraction_confidence` value drawn from ADR-017's three-tier framework
- [ ] Cleanup rules documented in module docstring with exact regexes; whitespace + hyphenated-rejoin tests in `tests/test_extract_dea.py` lock in the contract (incl. counter-examples that the date-range regex does NOT rejoin `9/7-10/20`)
- [ ] **A/B asymmetric coverage verified:** at least one HD in the output has ≥2 license rows where `season_coverage` differs (e.g., A has `heritage_muzzleloader: true`, B has `heritage_muzzleloader: false`); structured field tests assert the difference
- [ ] Statewide antelope overlay extracted exactly once; emitted row distinct from per-HD antelope rows
- [ ] Working note `docs/planning/epics/E03-confidence-findings/S03.3.md` records confidence-assignment patterns and any edge cases
- [ ] **UAT (faithfulness):** Human reviews ≥3 HDs (one per species, one of those an A/B multi-license HD with asymmetric season coverage) against the source PDF. `verbatim_text` matches the source byte-for-byte modulo the documented cleanup rules.
- [ ] `ruff check`, `mypy` clean for the new module
- [ ] Unit tests cover: column header detection, A/B-pattern row grouping with per-license `season_coverage`, statewide-overlay handling, hyphenated-line-break cleanup, cell-padding regex with date-range counter-example

---

### S03.4: Black Bear booklet extraction + correction PDF handling

**As a** developer extracting Montana black bear regulations
**I want** the BMU regulation table, the closure-rules prose, and the March 18 correction PDF integrated into a single coherent intermediate via deterministic date-arbitration
**So that** S03.6-S03.9 ingest the latest authoritative state and the correction-handling pattern is established for future states with similar amendments

**UAT: yes** — faithfulness review against the Black Bear PDF + correction PDF for ≥3 sampled BMUs (one each from a quota-closure BMU, a female-sub-quota BMU, and an unrestricted BMU).

**Context:**

Black Bear booklet structure per research (2026, 16 pages):
- BMU regulation table: pp. 10-11 (35 rows, one per Black Bear "Hunting District" / BMU)
- Closure rules prose: p. 7
  - **Quota closure list:** BMUs 411, 420, 440, 450, 510, 520, 530, 600, 700
  - **Female sub-quota:** BMUs 300, 301, 319, 580
- Region-specific reporting prose: separate from the table; identifies the R1 vs R2-7 inspection split

**Correction PDF (1 page, 2026-03-18):**
- Amends black bear hound licensing
- Removes a column from the BMU table (per research notes — exact column TBD at extraction time)
- Per [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), `document_type='correction'` and the `supersedes` field in `SourceCitation` points to the **canonical id of the booklet's SourceCitation, sourced from `sources.yaml`** (per S03.1's deliverable). The correction's own `SourceCitation.id` is also from `sources.yaml`.

**Date-arbitration logic (replaces "three-pass overlay" from prior draft):**

Per PRD 001 R5: corrections are processed *after* booklets on every run, with the latest-dated source winning. The mechanism:

1. **Pass 1 — base extraction:** read the Black Bear booklet, produce `extracted/black-bear-2026-base.json` with all rows tagged `{source_id: <booklet_citation_id>, source_publication_date: <booklet date>}`
2. **Pass 2 — correction extraction:** read the correction PDF, produce `extracted/corrections-2026-03-18.json` of `{target: <addressing key>, change: <set/remove/replace>, new_value: <verbatim from correction>, source_id: <correction_citation_id>, source_publication_date: 2026-03-18}` operations
3. **Pass 3 — date-arbitrated merge:** for each cell in the base extraction, resolve to the value from the source with the **MAX `source_publication_date`** that touches that cell. The correction's date (2026-03-18) is later than the booklet's, so correction-touched cells take the correction's value; untouched cells keep the booklet's value. Each resolved row's `source_id` matches the winning source. Rows touched by the correction also get `supersedes: <booklet_citation_id>` and `applied_correction: true` markers (the latter is a derived convenience; consumers who want to query "which records were touched by a correction" use `source.document_type='correction'`).

The merged output `extracted/black-bear-2026.json` is what S03.6-S03.9 consume. The base + correction artifacts are **both committed** for audit trail (latest-publication-date-wins is verifiable by re-running pass 3).

**Per-cell date-arbitration is the rule, not per-row.** If the correction modifies a single cell of a row, only that cell takes the correction's source. Other cells of the same row keep the booklet's source. This is what distinguishes a correction (cell-level patch) from a full-record amendment.

**Closure-prose handling:** The quota-closure list and female-sub-quota list from p. 7 become structured `ClosurePredicate` jsonb values on the corresponding `season_definition` rows in S03.7. Each closure has a `kind` (`quota_threshold` or `sex_threshold`), `notification_channel`, `verbatim_rule` (the source sentence from p. 7), and where applicable `threshold_percent` (e.g., 37% for the female sub-quota) and `threshold_sex='female'`.

**Closure temporal-anchor handling (per Schema validator SF2):** the female-sub-quota text says "at any point after May 31 if the cumulative spring harvest exceeds 37%." The temporal anchor ("after May 31") has no structured field in `ClosurePredicate` (which is `kind / threshold_percent / threshold_sex / notification_channel / observation_channel / verbatim_rule`). **For V1: keep the temporal anchor in `verbatim_rule` only; do NOT invent a structured field.** Flag for a future ADR (potentially adding `effective_after: date | null` to `ClosurePredicate`) per the operational definition. Add an entry to `docs/planning/epics/E03-deferred-items/closure-temporal-anchors.md` if this pattern recurs in future sources.

**Region-specific reporting (R1 vs R2-7):**
- Region 1: 48-hour report + 2 premolar teeth submission within 10 days
- Regions 2-7: full hide + skull presentation within 10 days

These become **two distinct** `reporting_obligation` rows in S03.9 (R1 case becomes two rows per S03.9 spec — see there).

**Per-BMU `hd_region` field in extraction output (per N2):** S03.4's extraction artifact carries `hd_region: 'R1'|'R2'|'R3'|'R4'|'R5'|'R6'|'R7'` per BMU row, sourced from the regional map in the Black Bear PDF (typically p. 5 — verify at execution time). S03.9 reads this field to drive the R1 vs R2-7 reporting_obligation linkage. If the map can't be parsed cleanly into a per-BMU mapping, fall back to a hand-curated `bmu_region_overrides.yaml` companion file checked into `ingestion/states/montana/`; flag-and-defer the cleaner extraction to M2.

**Confidence per ADR-017:**
- Base extraction rows: `high` (structured table cells)
- Closure-prose rows: `medium` (heading-anchored prose interpretation per ADR-017's tier definitions)
- Region-specific reporting rows: `medium` (same)
- **Correction-touched rows: demote one tier** per ADR-017 §4 (so a base `high` becomes `medium` after the correction merge; a base `medium` becomes `low`)

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md).

**Depends on:** S03.1, S03.2.

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/extract_black_bear.py` exists with the date-arbitrated three-pass architecture; deterministic outputs
- [ ] `extracted/black-bear-2026-base.json`, `extracted/corrections-2026-03-18.json`, and `extracted/black-bear-2026.json` (merged) all committed
- [ ] All 35 BMU rows extracted with verbatim_text, page_reference, and the structured row payload (each row carrying `hd_region` per N2)
- [ ] Closure-prose extracted into structured `ClosurePredicate` candidates: 9 quota-closure BMUs and 4 female-sub-quota BMUs; verbatim source sentence preserved per row; temporal anchors stay in `verbatim_rule` (V1 deferral noted in `docs/planning/epics/E03-deferred-items/closure-temporal-anchors.md` if not already)
- [ ] Region-specific reporting prose extracted into 2 candidate `reporting_obligation` records (R1 vs R2-7) with verbatim source text — S03.9 does the row decomposition
- [ ] Correction PDF parsed; **per-cell date-arbitration** applied; affected cells reflect the correction's value; affected rows tagged `applied_correction: true` and carry `supersedes: <booklet_citation_id>`
- [ ] **Latest-publication-date-wins verified** by a unit test: a row touched by the correction has `source.publication_date == 2026-03-18` (not the booklet date) for the touched cells
- [ ] **Correction-touched rows demoted one tier** per ADR-017: a unit test confirms a base-`high` row becomes `medium` post-merge if the correction touched any of its cells; a base-`medium` becomes `low`
- [ ] Citation IDs read from `sources.yaml` (per S03.1) — both for the correction's `id` and its `supersedes` reference
- [ ] Working note `docs/planning/epics/E03-confidence-findings/S03.4.md` records confidence-assignment patterns + correction-demote interactions
- [ ] **UAT (faithfulness):** Human reviews ≥3 BMUs (quota-closure + female-sub-quota + unrestricted) against the source PDF + correction. `verbatim_text` and the applied correction match source.
- [ ] `ruff check`, `mypy` clean
- [ ] Unit tests cover: BMU row extraction, closure-prose-to-ClosurePredicate, region-reporting extraction, correction operation application, per-cell date-arbitration determinism, correction-touched demote rule

---

### S03.5: Legal Descriptions extraction

**As a** developer enriching Montana geometry rows with the FWP-published prose boundary descriptions
**I want** the boundary text from the Legal Descriptions PDF cross-referenced to the matching `geometry` rows by `kind` + identifier
**So that** when E03 surfaces a regulation tied to a geometry, the FWP-published boundary description is available for the response composition layer

**UAT: yes** — faithfulness review for ≥2 sampled descriptions (one HD, one CWD or restricted-area) against the source PDF.

**Context:**

Legal Descriptions PDF structure per research (2026/2027, 56 pages):
- Prose boundary descriptions for HDs, BMUs, overlay zones (e.g., Libby CWD Management Zone, Sun River Game Preserve)
- Format: heading naming the geometry, followed by paragraph(s) describing the boundary in textual terms (e.g., "Beginning at the junction of US-89 and...")

**Output artifact:** `ingestion/states/montana/extracted/legal-descriptions-2026.json`. Each entry maps to an existing `geometry` row by `geometry_id`:

```json
[
  {
    "geometry_id": "MT-HD-deer-elk-lion-262-geom",
    "geometry_kind": "hunting_district",
    "verbatim_description": "<full prose boundary description, verbatim>",
    "page_reference": {"pdf_filename": "...", "page_num_1based": 12, "bbox": [...]},
    "extraction_confidence": "high"
  }
]
```

**Linkage strategy:** Heading-to-geometry-id matching is heuristic. Document the matching rule (e.g., "extract HD number from heading regex `HD\s+(\d+)`; species class from preceding section context; combine into `MT-HD-{species}-{number}-geom`"). Mismatches (heading present in PDF but no matching geometry, or geometry present in DB but no heading in PDF) are flagged in the output's `unmatched` and `unlinked` arrays for human review — do not silently drop or invent.

**Where this text goes in the database (per ADR-018):** S03.6 writes `verbatim_description` into **`geometry.legal_description`** (the new column added by ADR-018 §2). **No separator extension on `verbatim_rule`.** The two fields are independent: `verbatim_rule` carries layer-#2 REG/COMMENTS regulatory text (per ADR-015); `legal_description` carries this story's prose boundary description. Both are queryable; neither overloads the other.

**No regulation_record / season_definition / license_tag / reporting_obligation rows are produced from this booklet** — it's geometry-text-only enrichment.

**Confidence per ADR-017:**
- Headings that match cleanly: `high`
- Headings that fuzzy-match (multiple plausible candidates): `low`
- Headings that don't match (in `unmatched` array): no `extraction_confidence` (the row isn't ingested; it's flagged for human review)

**Relevant ADRs:** [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S03.1, S03.2; S03.0 (the `geometry.legal_description` column must exist); consumes E02's `geometry` table for the matching pass.

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/extract_legal_descriptions.py` exists; deterministic output
- [ ] Every prose description matched to an existing `geometry_id` (or surfaced in `unmatched`/`unlinked` arrays for human review)
- [ ] Heading-to-geometry-id matching rule documented in module docstring
- [ ] Working note `docs/planning/epics/E03-confidence-findings/S03.5.md` records matching-rule edge cases + any fuzzy-match `low`-confidence rows
- [ ] **UAT (faithfulness):** Human reviews ≥2 descriptions (one HD, one CWD or restricted area) against source PDF
- [ ] `unmatched` array flagged via the operational definition (WARN log + working-note entry)
- [ ] `ruff check`, `mypy` clean
- [ ] Unit tests cover: heading regex, prose extraction, unmatched-handling, matched-id round-trip

---

### S03.6: regulation_record ingestion

**As a** developer populating Montana's anchor entities
**I want** one `regulation_record` row per (state, jurisdiction_code, species_group, license_year) tuple, with verbatim source text and a populated `SourceCitation`, plus geometry-text enrichment from S03.5 written to `geometry.legal_description`
**So that** every downstream entity (season_definition, license_tag, reporting_obligation, jurisdiction_binding) has a valid FK target

**UAT: no** (verification via SQL row counts + UAT-prep queries in S03.12)

**Context:**

For each V1 species × applicable jurisdiction, write one `regulation_record` row:

| species_group | applicable jurisdictions | Source for that row |
|---|---|---|
| `elk` | All 139 deer-elk-lion HDs | DEA per-HD subsection |
| `mule_deer` | All 139 deer-elk-lion HDs | DEA per-HD subsection |
| `whitetail` | All 139 deer-elk-lion HDs | DEA per-HD subsection |
| `pronghorn` (antelope) | All 61 antelope HDs + 1 statewide row | DEA per-HD subsection (or statewide for `900-20`) |
| `bear` | All 35 black-bear HDs/BMUs | Black Bear booklet (post-correction merge) |

**Estimated row count:** 139 × 3 + 61 + 1 + 35 = **514 regulation_record rows** for V1 Montana, license_year=2026 (subject to actual extraction counts).

**Statewide regulation_records (per ADR-018, flag-and-surface):**

- **`MT-STATEWIDE-antelope`** is confirmed (anchor for `900-20`).
- **Additional candidates** (Bear ID coursework anchor, statewide CWD sampling anchor, statewide harvest reporting anchor) MAY surface during implementation. **The implementer MUST NOT add these autonomously.** Per ADR-018 §3: each candidate is a flag-and-surface event — written into `docs/planning/epics/E03-confidence-findings/S03.6.md` for review. The implementer surfaces with a recommendation; PM (with user) decides whether to add the row in this story or defer.

**`jurisdiction_code`** matches the geometry id pattern from E02:

| species namespace | jurisdiction_code pattern | matches geometry id |
|---|---|---|
| Deer/elk/whitetail | `MT-HD-deer-elk-lion-{number}` | `MT-HD-deer-elk-lion-{number}-geom` |
| Pronghorn (antelope) per-HD | `MT-HD-antelope-{number}` | `MT-HD-antelope-{number}-geom` |
| Pronghorn (antelope) statewide | `MT-STATEWIDE-antelope` | `MT-STATEWIDE-geom` (per ADR-018) |
| Bear | `MT-HD-bear-{number}` | `MT-HD-bear-{number}-geom` |
| (any future statewide species) | `MT-STATEWIDE-{species}` | `MT-STATEWIDE-geom` |

Composite PK `(state, jurisdiction_code, species_group, license_year)` distinguishes elk vs mule_deer vs whitetail at the same `MT-HD-deer-elk-lion-{number}` jurisdiction_code via `species_group`.

**Verbatim chain mapping (which extraction span lands in which entity field):**

| Entity field | Source extraction span |
|---|---|
| `regulation_record.verbatim_rule` | The DEA section's `verbatim_text` (section-level text for that HD subsection) OR the Black Bear merged-row text for that BMU |
| `regulation_record.additional_rules` | NOTE-style lines from the DEA HD subsection that apply to the HD as a whole, not to a specific license. Each NOTE line becomes one `VerbatimRule` jsonb entry with its own `verbatim_rule`, `confidence`, `source`, `page_reference` |
| `season_definition.verbatim_rule` (S03.7) | The DEA opportunity-specific-details cell text for the relevant season window (per HD per license) |
| `license_tag.verbatim_rule` (S03.7) | The DEA full license-row text (the row's verbatim across all 11 columns) |
| `reporting_obligation.verbatim_rule` (S03.9) | The Black Bear closure-prose source sentence OR the regional-reporting source sentence |
| `geometry.legal_description` (this story, write to existing geometry rows from E02 + S03.0) | The S03.5 `verbatim_description` for the matched geometry |

**SourceCitation:**
- DEA-sourced rows: `document_type='annual_regulations'`, `id` from `sources.yaml`, `publication_date=<DEA booklet publication date>`, `url=<DEA PDF URL>`, `page_reference=` collapsed string from the extraction artifact's `PageReference`
- Black Bear-sourced rows: `document_type='annual_regulations'` for unaffected rows; `document_type='correction'` with `supersedes=<booklet_citation_id>` for rows touched by the March 18 correction (per S03.4's date-arbitration output)

**Confidence per ADR-017:**
- For each regulation_record, `confidence = MIN` over all extraction-row confidences that fed it (per ADR-017 §5)
- For Black Bear correction-touched rows: the rows passed in already-demoted from S03.4; the MIN aggregation here doesn't re-demote
- Working note `docs/planning/epics/E03-confidence-findings/S03.6.md` records the per-record aggregation outcomes + any anomalies

**Geometry-text enrichment from S03.5:**

This story writes `geometry.legal_description` (the column added by S03.0/ADR-018) for matched geometry rows. **No separator** — `legal_description` is its own column. Re-running this story is idempotent: the `UPDATE geometry SET legal_description = ?` overwrites with the same value if extraction is unchanged.

**Idempotency:** UPSERT-by-PK pattern from E02's `db.upsert_geometries`. Re-running with identical extraction artifacts produces identical state.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S03.0 (`geometry.legal_description` column + `MT-STATEWIDE-geom` row), S03.3 (DEA), S03.4 (Black Bear), S03.5 (Legal Descriptions for geometry-text enrichment).

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/load_regulation_records.py` exists; reads the three extraction artifacts; deterministic load order
- [ ] Approximately 514 `regulation_record` rows written (verify exact count from extraction; may differ if DEA HD count is not exactly 139 in the actual data)
- [ ] Every row has `state='US-MT'`, `license_year=2026`, `schema_version=2`, populated `verbatim_rule`, populated `source` (jsonb SourceCitation), populated `confidence` per ADR-017's MIN aggregation
- [ ] `MT-STATEWIDE-antelope` regulation_record exists (anchor for `900-20`); any additional statewide candidates surfaced via working note, NOT autonomously added
- [ ] DEA-sourced rows use `document_type='annual_regulations'`; Black-Bear-correction-touched rows use `document_type='correction'` with `supersedes` populated; citation IDs match `sources.yaml`
- [ ] NOTE-style lines in DEA HD subsections written to `regulation_record.additional_rules` as `VerbatimRule[]` jsonb
- [ ] Geometry-text enrichment from S03.5 written to `geometry.legal_description` for matched rows; no `verbatim_rule` overload
- [ ] UPSERT idempotency confirmed by running twice with identical extraction artifacts
- [ ] **UAT-prep queries** (consumed by S03.12) include count-by-(species_group, source.document_type, confidence) cross-tab
- [ ] Working note `docs/planning/epics/E03-confidence-findings/S03.6.md` exists
- [ ] `ruff check`, `mypy` clean
- [ ] Unit tests cover: jurisdiction_code derivation (incl. statewide), SourceCitation construction (incl. correction case + supersedes from sources.yaml), confidence MIN aggregation, NOTE-line→additional_rules mapping, legal_description write-to-geometry round-trip

---

### S03.7: season_definition + license_tag + license_season ingestion (with A/B asymmetric coverage)

**As a** developer expressing Montana's per-HD season windows and the A/B license relationship pattern with explicit per-license season coverage
**I want** `season_definition` rows for each unique season window per HD, `license_tag` rows for each General/B variant, and `license_season` link rows expressing exactly which seasons each license covers
**So that** the milestone UAT criterion #2 ("A and B licenses both cross-referencing the appropriate seasons") is satisfied **without** the over-attribution failure mode the legacy schema had

**UAT: yes** — query HD 262 elk and verify (a) the season_definition rows match the source DEA subsection's distinct windows, (b) both A and B license_tag rows exist, and (c) the `license_season` join shows A covers Heritage Muzzleloader while B does not (or whatever the actual asymmetry is in HD 262's source data).

**Context:**

This is the load-bearing entity-mapping story for the A/B license pattern. ADR-018 added the `license_season` link table to model per-license season coverage explicitly; this story populates it from S03.3's per-license `season_coverage` extraction artifact.

**Per-HD construction pattern:**

For each HD's DEA subsection:
1. Identify all unique season windows present across the HD's licenses (e.g., HD 262 elk: Archery Only, General, Heritage Muzzleloader). This goes in `season_windows` from S03.3's artifact.
2. For each unique season window, create a `season_definition` row with:
   - `name` (e.g., "Archery Only", "General", "Heritage Muzzleloader")
   - `opens` and `closes` (parsed from `season_windows[<key>]` like `9/7-10/20`)
   - `weapon_type` (per the season's documented constraint, or NULL if no season-level weapon restriction — see weapon convention below)
   - `residency` (or NULL — most Montana seasons don't restrict by residency at the season level)
   - `closure_predicate` (jsonb; for bear seasons in quota-closure or female-sub-quota BMUs, populate per S03.4's structured output; null otherwise for V1)
   - `verbatim_rule` (per N3: source from the **General (A) license's** opportunity-specific-details cell when an A license covers this season; if the season is B-only — covered by no A license at this HD — source from the B license's cell instead. License-level cell differences inform `license_tag.verbatim_rule` per row, NOT `season_definition.verbatim_rule`. The season's verbatim_rule is single-source-of-record.)
   - `page_reference` (collapsed string from the extraction artifact's `PageReference`)
3. Link `regulation_record → season_definition` via the `regulation_season` link table (one row per season the HD has, **regardless of which license covers it**).
4. For each license row in S03.3's `rows[]` (General A, each B variant), create a `license_tag` row with `license_code`, `kind`, `weapon_types`, `residency`, `quota`, `quota_range` (as `int4range` per the bound convention below), `purchase_url`, `verbatim_rule`. Link via `regulation_license` to the parent `regulation_record`.
5. **For each license row, write `license_season` rows for exactly the seasons the license covers** per S03.3's `season_coverage` truth values. If `season_coverage.heritage_muzzleloader = false`, no `license_season` row links this license to the Heritage Muzzleloader season_definition.

**weapon_type vs weapon_types convention** (per Schema validator SF5):
- `season_definition.weapon_type`: nullable single-value field. **NULL means "no season-level weapon restriction"** (the more common case in Montana — the General season allows whatever the licenses allow). When non-NULL, the season itself imposes a weapon constraint (e.g., the Archery Only season has `weapon_type='archery'`).
- `license_tag.weapon_types`: required array. **The license is the source of truth for "what weapons can this hunter use."** The implementation reads the license row's per-row weapon constraint from S03.3's extraction.
- For the rendering "what weapons may a hunter using License X in Season Y use?": the answer is the intersection of `license_tag.weapon_types` and (`season_definition.weapon_type` if non-NULL else "any of license_tag.weapon_types"). The MCP server response composer (M3) handles the rendering.

**`quota_range` bound convention** (per Schema validator SF6):
- `int4range` with **inclusive bounds on both sides: `[lower, upper]`**. Postgres syntax: `int4range(lower, upper, '[]')`.
- Application-code validation: `lower <= quota <= upper` whenever both `quota` and `quota_range` are non-null. Unit tests assert.

**Statewide antelope `900-20`:** the DEA extraction emits this as a separate row. It maps to a single `regulation_record` (`MT-STATEWIDE-antelope`, `species_group='pronghorn'`) and a single `license_tag` with:
- `kind='statewide'`
- `weapon_types=['archery']` (the source says "archery only")
- `verbatim_rule` carries the **full** source text including the "First and only choice" semantic that S03.8 cannot model in `draw_spec` (per Q5/Q12 deferral)
- No `draw_spec_key` (S03.8 explicitly does not write a draw_spec for `900-20`)

S03.7 writes the license_tag and one corresponding `license_season` row if the statewide license has any seasonal coverage (probably not — `900-20` is statewide and may or may not have season windows; check the source).

**Bear closure predicates from S03.4:** For bear seasons in the 9 quota-closure BMUs (411, 420, 440, 450, 510, 520, 530, 600, 700), the season's `closure_predicate.kind='quota_threshold'`. For the 4 female-sub-quota BMUs (300, 301, 319, 580), `closure_predicate.kind='sex_threshold'` with `threshold_sex='female'` and `threshold_percent=37.0`. Temporal anchors stay in `verbatim_rule` per S03.4 (V1 deferral).

**Estimated row counts** (rough; actual emerges during implementation):
- `season_definition`: ~3-5 unique season windows per (HD, species) × ~514 (HD, species) → **~1,500-2,500 rows** before deduplication; with sharing across A/B variants, expect **~600-1,000 unique rows**
- `license_tag`: General + 1-3 B variants per HD × 514 → **~1,000-2,000 rows**
- `license_season`: per-license × per-season-it-covers → **~3,000-6,000 rows**

Order-of-magnitude verification against the extraction artifacts is part of the AC.

**Confidence per ADR-017:** child entities inherit confidence from the parent regulation_record; nothing written to `season_definition`, `license_tag`, or `license_season`.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S03.0 (`license_season` table), S03.6 (regulation_record FK target).

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/load_seasons_and_licenses.py` exists; deterministic load order
- [ ] `season_definition` rows written; per-HD unique-window deduplication confirmed (e.g., `name='General'` count is near-1:1 with HD count, not multiplied by license-variant count)
- [ ] `license_tag` rows written; multiple license_tag rows per HD where DEA shows A + B variants
- [ ] **`license_season` rows written per S03.3's `season_coverage` truth values**; per-license season selection is explicit; SQL spot-check on HD 262 elk shows A's `license_season` set differs from B's (asymmetric coverage)
- [ ] `regulation_season` link table populated for every (regulation_record, season_definition) pair (HD-level: every season the HD has); `regulation_license` link table populated for every (regulation_record, license_tag) pair
- [ ] Bear `season_definition` rows with `closure_predicate` jsonb populated for the 9 quota-closure BMUs and 4 female-sub-quota BMUs; temporal anchors preserved in `verbatim_rule` only
- [ ] Statewide antelope `900-20` license_tag row exists with `kind='statewide'`, `verbatim_rule` carrying the full "first and only choice" text; **no `draw_spec_key`** (S03.8 doesn't write one)
- [ ] `quota_range` uses `[]` inclusive bounds; application-code validation confirms `lower <= quota <= upper` for non-null quota
- [ ] `season_definition.weapon_type` is NULL where the season has no season-level restriction (most cases); `license_tag.weapon_types` carries the per-license constraint
- [ ] **UAT (M1 success criterion 2):** query HD 262 elk → returns archery, general, heritage muzzleloader as separate `season_definition` rows; `license_season` join shows A covers a different set of seasons than B (asymmetric coverage explicitly verified)
- [ ] If extraction surfaces a license/season pattern that doesn't fit the model: flagged via the operational definition (working note + WARN log + run-summary count)
- [ ] UPSERT idempotency confirmed
- [ ] Working note `docs/planning/epics/E03-confidence-findings/S03.7.md` records any A/B-pattern edge cases or model-fit anomalies
- [ ] `ruff check`, `mypy` clean
- [ ] Unit tests cover: A/B-pattern flattening, season-window deduplication, **per-license `license_season` writes** with asymmetric-coverage assertion, closure-predicate construction from prose, statewide-overlay handling, weapon convention round-trip, quota_range bound validation

---

### S03.8: draw_spec ingestion

**As a** developer modeling Montana's draw mechanics
**I want** `draw_spec` rows for every Montana hunt that uses limited-draw allocation, with per-pool shares, point-system parameters, and choices captured per ADR-012, **except** the statewide `900-20` which is deferred per Q12
**So that** license_tag rows that are limited-draw (per S03.7) have a populated `draw_spec_key` reference and the M1 success criterion is met

**UAT: no** (verification via row counts + cross-join with license_tag in S03.12)

**Context:**

Montana's draw mechanics for V1 species:
- **Per-HD limited-draw quotas** for B-license antlerless deer/elk hunts (every HD with a B variant has a quota)
- **Statewide antelope `900-20`**: **NO `draw_spec` written for V1.** The "First and only choice" semantic is a Q12 deferral (see deferred-items below).
- **Bear quota-closure mechanics** are NOT draws — they're in-season closures captured in S03.7's `closure_predicate`. Skip.
- **Bear female-sub-quota** is a per-pool allocation but operates as a closure rather than a draw spec. Skip.

**Per ADR-012:** `draw_spec` has composite PK `(state, hunt_code, year)`; `draw_spec_key` jsonb on `license_tag` is a **soft FK** (validated in application code, not DB). `pools` is `AllocationPool[]` and shares must sum to 1.0 (validated in application code).

**`hunt_code`:** Use the DEA `license_code` (e.g., `262-50`) since it's already unique per-jurisdiction-per-year. This makes the join from `license_tag.draw_spec_key` to `draw_spec` straightforward.

**Estimated row count:** Per-HD B licenses with quotas: ~2-5 per deer/elk HD × 139 = **~280-700 draw_spec rows**.

**`parameters` escape hatch (Q12) — flag-and-defer:**

PRD explicitly defers `parameters` use. **Specific V1 deferrals to track:**

1. **Antelope `900-20` "First and only choice. ArchEquip only."** — ordering-rule semantic with no slot in `ChoiceConfig` or `AllocationPool`. **S03.8 writes NO `draw_spec` for `900-20`.** The license_tag from S03.7 carries the verbatim_rule with the "first and only choice" text; consumers see the rule but no structured draw mechanic. WARN logged at run time.
2. **Any other Montana extraction case that doesn't fit the schema cleanly:** surplus tags, late-season leftover allocation, partial-points carry-forward, etc. Flag-and-defer per the operational definition.

**`docs/planning/epics/E03-deferred-items/draw-mechanics.md`** is updated by S03.8 with each deferral case:
- Source location (which HD, which license, source-PDF page reference)
- Verbatim text of the rule
- Reason it doesn't fit V1 schema
- Recommendation for M2 design (e.g., "promote `parameters['ordering_rule']`" or "add an `ordered_choice_position` field to `ChoiceConfig`")

This file **survives past M1 close** — it's a promise to M2.

**Relevant ADRs:** [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md).

**Depends on:** S03.7 (license_tag rows with `draw_spec_key` populated).

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/load_draw_specs.py` exists; deterministic load order
- [ ] `draw_spec` rows written for every limited-draw `license_tag` from S03.7 **except `900-20`**
- [ ] `pools` AllocationPool array shares sum to 1.0 per row (application-code validation enforced)
- [ ] `license_tag.draw_spec_key` jsonb correctly references the `draw_spec` composite PK for every draw-eligible license_tag (cross-check via SQL: every `license_tag` with `kind='limited_draw'` has a non-null `draw_spec_key` resolving to an existing `draw_spec` row)
- [ ] **`900-20` has NO `draw_spec` row;** `license_tag.draw_spec_key` is NULL; `verbatim_rule` carries the full "first and only choice" text; entry exists in `docs/planning/epics/E03-deferred-items/draw-mechanics.md` documenting the deferral
- [ ] `parameters` field is `null` on every draw_spec row written (per Q12 deferral)
- [ ] If extraction surfaces a draw mechanic that would require `parameters`: **flag-and-defer** via the operational definition (WARN log + entry in `docs/planning/epics/E03-deferred-items/draw-mechanics.md` + run-summary count)
- [ ] UPSERT idempotency confirmed
- [ ] `ruff check`, `mypy` clean
- [ ] Unit tests cover: pool-share-sum validation, residency-cap construction, license_tag↔draw_spec round-trip, `900-20` skip behavior

---

### S03.9: reporting_obligation ingestion

**As a** developer recording Montana's post-harvest and in-season reporting duties
**I want** `reporting_obligation` rows for CWD sampling, Bear ID coursework, mandatory reporting, and the region-specific bear inspection rules from S03.4
**So that** clients can surface "what reports does the hunter owe?" alongside the regulations

**UAT: no** (verification via SQL spot-checks per region in S03.12)

**Context:**

Montana V1 reporting obligations:

1. **CWD sampling** (statewide where applicable): post-harvest CWD sample submission for deer/elk in CWD zones; details from DEA + Legal Descriptions
2. **Bear ID coursework** (statewide): mandatory online course for first-time black bear hunters; details from Black Bear booklet
3. **Mandatory harvest reporting** (statewide): general reporting obligation for all V1 species
4. **Region-specific bear inspection** — the R1 vs R2-7 distinction from S03.4

**Region-1 inspection — TWO rows per S03.9:**

The R1 obligation has two distinct deadlines (48-hour report + 10-day teeth submission). Per the schema-validator-recommended option (a) — two `reporting_obligation` rows linked to the same regulation_record:

| Row | `kind` | `deadline` (text) | `deadline_hours` | `submission_method` | `what_to_present` | `applies_to_regions` |
|---|---|---|---|---|---|---|
| 1 | `harvest_report` | "48 hours" | 48 | `phone` (or `online` per source — verify) | `[]` | `['R1']` |
| 2 | `tooth_submission` | "10 days" | 240 | `mail` (or `agency_office` per source — verify) | `['two premolar teeth']` | `['R1']` |

**Region-2-7 inspection — ONE row:**

| Row | `kind` | `deadline` (text) | `deadline_hours` | `submission_method` | `what_to_present` | `applies_to_regions` |
|---|---|---|---|---|---|---|
| 1 | `hide_skull_presentation` | "10 days" | 240 | `in_person_check_station` | `['hide', 'skull']` | `['R2', 'R3', 'R4', 'R5', 'R6', 'R7']` |

**Statewide rows:**
- CWD sampling: 1 row per applicable species (deer/elk), `applies_to_regions=NULL`
- Bear ID coursework: 1 row, `applies_to_regions=NULL`
- Mandatory harvest reporting: 1-N rows per species or 1 statewide row (verify from source)

**Estimated row count:** ~6-10 reporting_obligation rows for V1 Montana.

**Linkage to regulation_record:**
- Statewide CWD sampling: links to every deer/elk regulation_record where the HD overlaps a CWD zone (use S02.6's overlay fixture for the lookup)
- Bear-inspection R1 split: links to every bear regulation_record where the HD's region is R1 (region lookup TBD — may require an HD→region mapping the source provides)

**Confidence per ADR-017:** child entities inherit confidence from parent regulation_record; nothing written to `reporting_obligation`.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md).

**Depends on:** S03.6 (regulation_record FK target). May read S02.6's overlay fixture for CWD-zone-overlap lookup.

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/load_reporting_obligations.py` exists; deterministic load order
- [ ] Statewide `reporting_obligation` rows for CWD sampling, Bear ID coursework, mandatory harvest reporting (3-4 rows)
- [ ] Region-specific bear inspection: **3 rows total** — R1 split into 2 (48-hour report + 10-day teeth) per the table above; R2-7 as 1 row per the table above
- [ ] Each R1 row carries verbatim_rule per the source-sentence-per-row split documented in the load script
- [ ] `regulation_reporting` link table populated for every (regulation_record, reporting_obligation) pair
- [ ] CWD-sampling obligation links only to regulation_records whose HD overlaps a CWD zone (verified by cross-checking against S02.6's overlay fixture)
- [ ] UPSERT idempotency confirmed
- [ ] Working note `docs/planning/epics/E03-confidence-findings/S03.9.md` records the HD→region mapping used for the R1 lookup (and any anomalies)
- [ ] `ruff check`, `mypy` clean
- [ ] Unit tests cover: applies_to_regions array construction, R1-split-row generation (2 rows), R2-7 row generation (1 row), CWD-overlap regulation_record selection

---

### S03.10: jurisdiction_binding generation

**As a** developer linking Montana regulation_records to their relevant geometries
**I want** `jurisdiction_binding` rows generated from the cross product of new regulation_records (S03.6) and the overlay fixture (S02.6) with `role` derived from `role_for_e03`, **filtered by species axis** so cross-species pairings don't produce spurious bindings
**So that** spatial queries can navigate from "what regulations apply to a coordinate?" through geometries to regulation_records

**UAT: yes** — spot-check binding rows for a known multi-overlay case (e.g., HD 262 elk → primary_unit binding to its HD geometry + portion bindings + any RA/CWD bindings the overlay fixture surfaces, all SAME-species).

**Context:**

This is the entity that the PRD originally claimed E02 would write but the schema FK direction made impossible (resolved by E02 producing the `geometry-overlays.json` fixture for E03 to consume). S03.10 is where that handoff completes.

**Per-regulation_record overlay traversal (per Schema validator B2):**

**Each regulation_record gets its own pass through the overlay fixture, keyed by its own derived geometry_id.** The overlay fixture is parent-HD-keyed but doesn't carry species-axis multiplicity; species-axis multiplication happens in the binding loader.

For each `regulation_record` row:
1. Derive the parent geometry_id from the regulation_record's `jurisdiction_code` (e.g., `MT-HD-deer-elk-lion-262` → `MT-HD-deer-elk-lion-262-geom`; `MT-STATEWIDE-antelope` → `MT-STATEWIDE-geom` per ADR-018)
2. Find every overlay-fixture relationship row where `parent_geometry_id == <that geometry id>` (for HDs, includes the self-row → primary_unit role) — apply the cross-species filter (next paragraph)
3. Write one `jurisdiction_binding` row per qualified relationship

**Cross-species portion filter (per Schema validator B1):**

The overlay fixture contains pairings like `parent=MT-HD-antelope-311-geom` + `child=MT-HD-mule-deer-312-portion-...-geom` (cross-species — spatial intersection but no regulatory binding). When binding for an antelope regulation_record, **only consume overlay rows where the child's species namespace matches the regulation_record's species** (or the child is `kind ∈ {restricted_area, cwd_zone, bma}` which are species-agnostic overlays).

Concretely:
- For an `species_group='pronghorn'` regulation_record with `jurisdiction_code='MT-HD-antelope-311'`, accept overlay rows where `child_geometry_id` starts with `MT-HD-antelope-` (same-species portions) OR `child_kind ∈ {restricted_area, cwd_zone, bma}`. Reject overlay rows where the child is a different species' portion.
- For `species_group ∈ {elk, mule_deer, whitetail}` with `jurisdiction_code='MT-HD-deer-elk-lion-N'`, accept children starting with `MT-HD-deer-elk-lion-` (which captures all three deer/elk/whitetail portions since they share that namespace from layer #11) OR species-agnostic overlay kinds.
- For `species_group='bear'` with `jurisdiction_code='MT-HD-bear-N'`, accept children starting with `MT-HD-bear-` OR species-agnostic overlay kinds.

The filter is implemented as a function `is_binding_eligible(regulation_record, overlay_row) -> bool` with explicit unit tests for each species pair.

**Binding row construction:**

For each accepted (regulation_record, overlay_row) pair, write `jurisdiction_binding` with:
- `regulation_record_state`, `regulation_record_jurisdiction_code`, `regulation_record_species_group`, `regulation_record_license_year` from the regulation_record's PK
- `geometry_id` from `child_geometry_id`
- `role` from `role_for_e03` (mapped per ADR-016's overlay fixture)
- `verbatim_rule` typically null (the source text is on the geometry's `verbatim_rule` from S02.4 layer-#2 REG/COMMENTS, on `geometry.legal_description` from S03.5/S03.6, or on the regulation_record's `verbatim_rule` — not duplicated here)
- `source` from a synthesized SourceCitation **referencing the original ArcGIS layer that produced the geometry** (per Source-Faithfulness validator F10): `document_type='gis_layer'` per ADR-014, citing the source layer (not the overlay fixture file). The overlay fixture is derived; the source-of-record is the layer.
- `id` constructed deterministically per N4: `f"{state}-{jurisdiction_code}-{species_group}-{license_year}-binding-{geometry_id}-{role}"`. All five tuple components plus `geometry_id` and `role` are participants because (regulation_record, geometry, role) triples are unique by construction. The format is verbose but produces stable IDs across re-ingestions: same regulation_record + same overlay_row + same role → same id, so UPSERT semantics work cleanly. Verify ID stability by running the loader twice with no data changes and confirming zero ID drift.

**Statewide regulation_records bind to `MT-STATEWIDE-geom`** (per ADR-018):

Each statewide `regulation_record` (e.g., `MT-STATEWIDE-antelope`) gets exactly one `jurisdiction_binding` row to `MT-STATEWIDE-geom` with `role='primary_unit'`. Per ADR-018: any new `role` value beyond `primary_unit` for a statewide binding requires an ADR amendment.

**No-hunt-zone handling (E02 handoff item #7):**

The 3 `EXPECTED_RA_ORPHAN_IDS` (Glacier NP, Sun River Game Preserve, Yellowstone NP) have no parent HD in the overlay fixture. **V1 default: Option A — bind to "nearby" HDs as `role='other_overlay'`.**

**Deterministic "nearby" definition** (per Schema validator S5):
- "Nearby" means: any HD whose geometry **shares an edge** with the no-hunt zone (`ST_Touches`) OR whose **centroid is within 5km** of the no-hunt zone's centroid (`ST_DWithin(geog::geometry, geog::geometry, 5000)`)
- Exact thresholds locked in code as constants `NO_HUNT_ZONE_NEARBY_TOUCHES` and `NO_HUNT_ZONE_NEARBY_CENTROID_DISTANCE_M = 5000`
- Adds ~30-100 jurisdiction_binding rows total. Documented in load script + working note `docs/planning/epics/E03-confidence-findings/S03.10.md`.
- If during implementation this proves clumsy or surfaces edge cases, escalate to PM for Option B (schema discriminator) or C (defer) consideration.

**Filter scope (per N5):** the no-hunt-zone selector filters on `geometry.kind = 'restricted_area' AND id IN EXPECTED_RA_ORPHAN_IDS`. **Both predicates are required.** The `kind='restricted_area'` filter is the load-bearing structural one — it ensures `MT-STATEWIDE-geom` (`kind='state'`), portions, CWD zones, BMUs, etc. are NOT eligible for Option A binding even if their spatial relationships satisfy the "nearby" rule. The `id IN allowlist` predicate is a secondary safety belt — restricted_area rows that have parent HDs in the overlay fixture are also not no-hunt zones, so the allowlist filters them out too. **If implementation reveals the kind filter alone is sufficient (i.e., every kind='restricted_area' row that lacks an overlay-fixture parent is in fact a no-hunt zone), the allowlist can be removed in a follow-up — the structural kind filter is the real protection.**

**Fan-out estimate from E02 handoff item #8:** median ~3 parent HDs per child geometry; one RA tied to 16 parent HDs. For 514 regulation_records × ~3-5 binding rows per record = **roughly 1,500-3,000 jurisdiction_binding rows** for V1 Montana, plus ~30-100 from no-hunt-zone bindings.

**Confidence per ADR-017:** `jurisdiction_binding` carries provenance (the area-overlap percentage from ADR-016), not confidence. The ADR-017 framework explicitly does not apply (per ADR-017 §2). No `confidence` field on this entity.

**Relevant ADRs:** [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md) (overlay fixture provenance), [ADR-017](../../adrs/ADR-017-confidence-calibration.md) (spatial-confidence carve-out), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md) (statewide bindings + `MT-STATEWIDE-geom`).

**Depends on:** S03.0 (`MT-STATEWIDE-geom`), S03.6 (regulation_record FK target), S02.6 overlay fixture (input).

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/load_jurisdiction_bindings.py` exists; reads overlay fixture + queries regulation_record table; deterministic load order
- [ ] **Per-regulation_record traversal:** each regulation_record produces its own set of binding rows; no shortcut "for every overlay row, find a regulation"
- [ ] **Cross-species filter:** `is_binding_eligible(regulation_record, overlay_row)` function with explicit unit tests per species pair; SQL spot-check confirms an antelope regulation_record has no binding to a `MT-HD-mule-deer-*-portion-*-geom` child
- [ ] Statewide regulation_records bind to `MT-STATEWIDE-geom` with `role='primary_unit'`; no other `role` values used for statewide
- [ ] No-hunt-zone Option A applied: each of the 3 zones binds to nearby HDs per the deterministic `ST_Touches` OR `ST_DWithin(5000)` rule; binding count documented in working note
- [ ] Estimated row count is order-of-magnitude verified: SQL `SELECT count(*) FROM jurisdiction_binding` returns 1,500-3,500 for V1 Montana
- [ ] `source` jsonb on every binding row references the **original ArcGIS layer** that produced the child geometry, with `document_type='gis_layer'` (NOT the overlay fixture file)
- [ ] `geometry-overlays-dropped.json` is NOT consumed (per ADR-016)
- [ ] `confidence` not written (per ADR-017 spatial-confidence carve-out)
- [ ] **UAT:** spot-check HD 262 elk's binding rows match the overlay fixture's same-species relationships for the matching geometry id (primary_unit + any same-species portions + any CWD/RA overlays)
- [ ] UPSERT idempotency confirmed
- [ ] Working note `docs/planning/epics/E03-confidence-findings/S03.10.md` records the no-hunt-zone "nearby" matches + binding count
- [ ] `ruff check`, `mypy` clean
- [ ] Unit tests cover: regulation_record-to-geometry matching (incl. statewide), per-species cross-species-filter behavior, no-hunt-zone nearby-rule logic, source-citation construction (cites source layer not overlay fixture)

---

### S03.11: Confidence calibration audit + ADR-017 finalization

**As a** developer closing the loop on Q11
**I want** the per-story calibration findings synthesized into an audit; ADR-017 reviewed against actual ingestion outcomes; any necessary amendments drafted for user review
**So that** the M1 milestone exit criterion #8 (an ADR documenting the confidence calibration standard) is met and Q11 closes — OR is explicitly deferred to early M2 per PRD R4

**UAT: no** (PM hands any ADR-017 amendment to the user for review per the user's explicit instruction; user reviews and approves before merge)

**Context:**

ADR-017 was drafted during E03 planning (before S03.0). This story finalizes:
1. **Synthesis report:** consolidate all `docs/planning/epics/E03-confidence-findings/S03.X.md` working notes into `docs/planning/epics/E03-confidence-calibration-synthesis.md` (PM-owned)
2. **Audit:** stratified sample across the 6 ingested entity tables, validating the assigned `confidence` values match ADR-017's framework
3. **Amendment decision:** if audit surfaces gaps, PM drafts an ADR-017 amendment for user review (do not commit autonomously)
4. **Defer-or-finalize decision** per the OR-ed conditions in ADR-017 §7

**Stratified audit:**

For each documented edge case in ADR-017 (closure-prose extraction, region split, correction PDF, legal-description cross-ref, statewide overlay, NOTE lines, etc.), sample **at least 5 rows per edge case** from the corresponding entity table (or all rows if fewer than 5 exist). After per-edge-case sampling, fill the audit with random rows up to a total of 50.

For each sampled row, verify the assigned `confidence` matches what ADR-017's framework would assign given the row's source signals (which are persisted per AC below — the inputs to the assignment are recorded so the auditor can reproduce the framework's logic without re-extracting).

**Confidence-assignment inputs persisted (per Conf validator F12):**

Each ingestion story's working note (`docs/planning/epics/E03-confidence-findings/S03.X.md`) MUST record, for each (entity_id, assigned_confidence) pair, the **inputs that drove the assignment**:
- Source format (table cell / heading-anchored prose / heuristic / hand-corrected)
- Extraction operation (regex match, parser pass, fuzzy match, etc.)
- Transformation steps (number and type)
- Whether the row was correction-touched (and the demote-one-tier rule applied)

This makes re-classification under a future framework amendment possible — and makes the audit reproducible.

**Defer-or-finalize objective test (per ADR-017 §7, OR-ed conditions):**

- **Defer if** any documented edge case maps to >1 tier without contradiction, **OR**
- **Defer if** any tier (`high`/`medium`/`low`) has 0 rows in Montana data, **OR**
- **Defer if** audit pass-rate <80% against the framework

If any of the three triggers, the affected ADR-017 sections move to "deferred to M2" via an amendment; PM drafts the amendment for user review. If none trigger, ADR-017 stands as-is and the audit summary is recorded in the synthesis report.

**User-review SLA + auto-defer fallback:**

ADR-017 amendment review by user is gated by **no SLA on the user side** (this is the user's own time). To prevent S03.12 (and the `m1` tag) from blocking on an open ADR amendment indefinitely:

- If S03.11 surfaces an amendment for review and S03.12 is otherwise ready to ship, **S03.12 proceeds with the amendment in "deferred to M2" status recorded in the M1→M2 handoff document.** The current ADR-017 (V1 framework) ships unchanged with the milestone tag; the amendment becomes M2 first-week work.
- This means S03.11 NEVER blocks the milestone tag. The story's purpose is to surface what needs amendment; the amendment landing is a separate decision the user makes on their own timeline.

**Working notes deletion (at m1 tag commit):**

Per ADR-017 §6: at the `m1` tag commit (in S03.12), the entire `docs/planning/epics/E03-confidence-findings/` directory is deleted via manual `git rm -r`. The `.gitignore` is updated to prevent re-creation post-M1. Only the synthesis report (which lives in the planning epic dir, not the findings dir) and the ADR-017 itself survive.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-009](../../adrs/ADR-009-agentic-development-first-class.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md).

**Depends on:** S03.3-S03.10 (need per-story working notes + ingested rows to audit).

**Acceptance Criteria:**

- [ ] Synthesis report `docs/planning/epics/E03-confidence-calibration-synthesis.md` exists; consolidates all per-story working notes
- [ ] Stratified audit performed: ≥5 rows per documented edge case + random fill to 50 total; all sampled rows' assigned `confidence` verified against ADR-017's framework
- [ ] **Confidence-assignment inputs persisted** in each story's working note (source format, extraction op, transformation steps, correction-touched flag) — auditor can reproduce the framework's logic without re-extracting
- [ ] If no defer-trigger fires: ADR-017 stands as-is; audit summary recorded; Q11 marked resolved
- [ ] If any defer-trigger fires: PM drafts ADR-017 amendment for user review; **does NOT commit autonomously**; the affected sections move to "deferred to M2" status; this status is recorded in S03.12's M1→M2 handoff document
- [ ] **S03.12 does NOT block on ADR-017 amendment review** — auto-defer fallback per spec ensures the `m1` tag can ship even with an open amendment
- [ ] Working notes deletion is queued for S03.12's final commit (this story does NOT delete them — they're still being audited)

---

### S03.12: M1 UAT preparation + handoff to M2

**As a** developer closing M1
**I want** a complete UAT artifact set covering all 8 milestone success criteria, plus a `/handoff` summary for the M2 PM session, plus the working-notes cleanup
**So that** the `m1` tag can be pushed and M2 (Colorado) can begin without ambiguity

**UAT: yes** — this story IS the milestone-level UAT preparation; the user runs the UAT against Supabase per the produced queries and signs off before the m1 tag.

**Context:**

PRD 001 § "Success criteria for the milestone" lists the 8 UAT-level criteria for M1 (paraphrased; refer to PRD 001 lines 122-129 for authoritative text):

1. Query (state=MT, jurisdiction_code=HD-262, species_group=elk, license_year=2026) returns regulation_record with non-empty verbatim_text + populated sources array
2. Join regulation_record → license_tag → season_definition for HD 262 elk: archery, general, muzzleloader as separate season rows with **A/B asymmetric coverage via `license_season`** per ADR-018
3. PostGIS `ST_Contains` query with a coord inside HD 262 returns HD 262 + any overlay BMU/CWD/Portion (same-species per S03.10's filter)
4. regulation_record row with no `sources` entry does not exist
5. geometry row with invalid topology does not exist
6. Re-running `make ingest STATE=montana` produces same result (idempotent)
7. `pg_roles` privileges for authenticated/anon show no rights on entity tables
8. ADR exists documenting Q11 confidence calibration (ADR-017 — committed during E03 planning, possibly amended via S03.11)

**S03.12 deliverables:**

1. **UAT query set** at `docs/runbooks/M1-uat.md` — one SQL block per criterion above, copy-pasteable into `psql`. Mirrors `docs/runbooks/E01-migration-verification.md` and `docs/runbooks/E02-geometry-verification.md` style.
2. **UAT execution log** — when the user runs the queries, results captured into the runbook (or a paired `M1-uat-results-<date>.md`) for the milestone audit trail.
3. **`/handoff` summary** at `docs/planning/handoffs/M1-to-M2-handoff.md` per the M1 PM prompt's `/handoff` command — covers what M1 built, where it is committed, what M2 inherits (working schema + ADRs 001-018, adapter pattern, shared library, confidence calibration ADR, pre-commit hooks, deferred items), and any open items.
4. **Calibration findings deletion:** `git rm -r docs/planning/epics/E03-confidence-findings/`; update `.gitignore` to prevent re-creation. Per ADR-017 §6.
5. **Deferred-items survival check:** confirm `docs/planning/epics/E03-deferred-items/` survives in the m1 tag commit; the M1→M2 handoff document references each file.
6. **`m1` tag readiness check** — verify all 8 UAT criteria pass; verify CHANGELOG, CLAUDE.md, planning README all reflect M1 closure; nothing is half-finished. PM hands off to user for the actual `git tag m1` action.

**Out of scope:** the M2 epic file. M2 PM session drafts that.

**Relevant ADRs:** All M1 ADRs by reference (ADR-001 through ADR-018); nothing new in this story.

**Depends on:** All prior E03 stories (especially S03.11 for the ADR-017 status determination).

**Acceptance Criteria:**

- [ ] `docs/runbooks/M1-uat.md` exists with one SQL block per the 8 PRD success criteria; queries copy-pasteable into `psql`
- [ ] UAT execution log captures the result of each query against the loaded Montana data
- [ ] `docs/planning/handoffs/M1-to-M2-handoff.md` exists with the structure recommended by the M1 PM prompt's `/handoff` command
- [ ] All deferred items documented in the handoff: Q11 status (resolved or deferred per S03.11), `parameters` confirmation deferred per Q12 with reference to `docs/planning/epics/E03-deferred-items/draw-mechanics.md`, restricted_area discriminator status (resolved during S03.10 or deferred), no-hunt-zone binding decision (Option A confirmed)
- [ ] Calibration findings directory deleted (`git rm -r docs/planning/epics/E03-confidence-findings/`); `.gitignore` updated
- [ ] Deferred-items directory survives in the m1 tag commit
- [ ] CLAUDE.md, planning README, CHANGELOG all updated to reflect M1 closure (PM does this update; user pushes `m1` tag)
- [ ] **UAT (milestone-level):** user runs the 8 UAT queries against Supabase; all 8 pass; user signs off
- [ ] No new schema, code, or migration changes in this story — pure verification + documentation + cleanup

---

## Exit Criteria

- [ ] All 13 stories complete (S03.0 through S03.12)
- [ ] All 5 V1 Montana species (elk, mule deer, whitetail, pronghorn, black bear) have `regulation_record` rows for every applicable jurisdiction
- [ ] Every regulation_record has populated `verbatim_rule`, populated `source` (jsonb SourceCitation), populated `confidence`
- [ ] `season_definition`, `license_tag`, `license_season`, `draw_spec`, `reporting_obligation` rows present per S03.7-S03.9 specs; A/B asymmetric coverage verified via `license_season` join
- [ ] `jurisdiction_binding` rows generated from S02.6 overlay fixture with cross-species filter applied; fan-out within order-of-magnitude estimate
- [ ] ADR-017 (Q11 resolved) committed during E03 planning; possibly amended via S03.11 (or amendment deferred to M2 with status recorded in handoff)
- [ ] ADR-018 (E03 schema additions) committed during E03 planning; schema additions live (license_season, geometry.legal_description, geometry.kind='state')
- [ ] All 8 PRD success criteria pass UAT
- [ ] `m1` tag pushed at the commit where UAT passes
- [ ] CHANGELOG, CLAUDE.md, planning README reflect M1 closure
- [ ] M2 PM handoff document exists and is complete
- [ ] Calibration findings directory deleted; deferred-items directory survives

---

## Parallelization Notes

**Within E03: stories run sequentially** with these data dependencies:

- S03.0 → S03.5, S03.6, S03.7, S03.10 (schema additions and statewide geometry must exist first)
- S03.0 → S03.1 (S03.1 produces the SourceCitation field set in sources.yaml; could run in parallel with S03.0 since they touch different files, but sequential simplifies)
- S03.1 → S03.2 (S03.2 needs the fetched PDFs to test against)
- S03.2 → S03.3, S03.4, S03.5 (all per-booklet extractions use the shared lib)
- S03.3, S03.4, S03.5 → S03.6 (regulation_record needs all extraction artifacts)
- S03.6 → S03.7, S03.8, S03.9, S03.10 (FK target for all entity ingestion + binding)
- S03.7 → S03.8 (license_tag's `draw_spec_key` references draw_spec)
- S02.6 overlay fixture → S03.10 (binding generation input)
- S03.6-S03.10 → S03.11 (confidence calibration synthesizes patterns from real ingestion)
- S03.11 → S03.12 (UAT criterion #8 needs the ADR — may already be ADR-017 unchanged, may be amendment)
- All → S03.12 (milestone exit)

**Recommended merge order:** S03.0 → S03.1 → S03.2 → S03.3 → S03.4 → S03.5 → S03.6 → S03.7 → S03.8 → S03.9 → S03.10 → S03.11 → S03.12

**Parallelization opportunities:**
- S03.3, S03.4, S03.5 are genuinely parallelizable: different booklets, disjoint output artifacts, no shared write keys.
- S03.7, S03.8, S03.9 are partially parallel: S03.8 depends on S03.7; S03.9 is independent of both.
- S03.10 needs S03.6 only (not S03.7-S03.9) for binding generation.
- S03.11's draft can begin as soon as S03.7-S03.10 are at least partially in flight; finalization waits for them all.

---

## Open Questions and Deferred Items

1. **Q11 confidence calibration (resolved during this epic via ADR-017).** S03.11 audits and may produce an amendment for user review; if amendment is open at m1 tag time, deferred to early M2 per ADR-017 §7.

2. **Restricted-area discriminator (E02 handoff item #7).** May surface a clean answer during S03.10's no-hunt-zone binding work (Option A taken for V1). If a clean schema-side answer surfaces, fold into a future ADR (potentially ADR-019). If ambiguous, leave open and resolve in M2.

3. **No-hunt-zone binding strategy (S03.10).** V1 default: Option A (bind to nearby HDs as `other_overlay`, deterministic via `ST_Touches` OR `ST_DWithin(5000)`).

4. **License_tag-specific season selection.** **Resolved by ADR-018's `license_season` link table.** S03.7 implements.

5. **Multi-source separator on `geometry.verbatim_rule`.** **Resolved by ADR-018's `geometry.legal_description` column.** No separator extension needed.

6. **`parameters` escape hatch (Q12 deferred).** Confirmed flag-and-defer per Q5. Tracked in `docs/planning/epics/E03-deferred-items/draw-mechanics.md`. Initial entries: antelope `900-20`. Additional entries added by S03.8 if other cases surface.

7. **ClosurePredicate temporal anchors** (e.g., "after May 31"). V1: keep in `verbatim_rule` only. Flagged for future ADR (potentially adding `effective_after: date | null` to `ClosurePredicate`). Tracked in `docs/planning/epics/E03-deferred-items/closure-temporal-anchors.md` if S03.4 surfaces this.

8. **Statewide regulation_records beyond `MT-STATEWIDE-antelope`.** S03.6 implementer flag-and-surfaces candidates (Bear ID, CWD sampling, harvest reporting); user decides. Per ADR-018: implementer does NOT add autonomously.

---

## Known issues to escalate

1. **PRD 001 jurisdiction_binding sequencing language.** Already resolved by E02's geometry-overlay-fixture handoff (S02.6 → S03.10). PRD 001 lines 48, 90, 96, 111 still describe E02 as writing binding rows; the proposed reconciliation wording lives in the E02 epic § "Known issues to escalate" #1. Carries forward to M2 PM handoff.

2. **S03.10 no-hunt-zone binding choice.** Default Option A unless implementation surfaces a reason to escalate.

3. **ADR-017 user-review gate** for any S03.11 amendment. PM does not commit autonomously per explicit user instruction. S03.12 has auto-defer fallback to prevent milestone block.

4. **`ClosurePredicate` temporal anchor** (#7 above) — flagged for potential future ADR if pattern recurs.

---

## References

- [PRD 001](../../planning/prds/001-M1-montana-ingestion.md) — M1 scope, E03 phasing, success criteria
- [`docs/research/montana-source-structure-findings.md`](../../research/montana-source-structure-findings.md) — Montana PDF structure
- [E02 epic](E02-geometry-ingestion.md) — geometry layer, overlay fixture, handoff items #7 and #8
- [E01 epic](E01-schema-migrations.md) — schema and link tables this epic populates
- [ADR-001](../../adrs/ADR-001-authority-preserved.md) — source citations required
- [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md) — three-place schema sync
- [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) — verbatim text
- [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md) — six-entity model
- [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md) — draw_spec design, `parameters` escape hatch
- [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md) — `document_type` enum
- [ADR-015](../../adrs/ADR-015-geometry-verbatim-rule-and-reg-comments-handling.md) — `geometry.verbatim_rule` + REG/COMMENTS
- [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md) — overlay-fixture provenance for S03.10
- [ADR-017](../../adrs/ADR-017-confidence-calibration.md) — confidence inheritance + spatial-confidence carve-out (drafted during E03 planning)
- [ADR-018](../../adrs/ADR-018-e03-schema-additions.md) — `license_season` + `geometry.legal_description` + `kind='state'` (drafted during E03 planning)
- [Q11 in `open-questions.md`](../../open-questions.md) — confidence calibration (resolves via ADR-017)
- [Q12 in `open-questions.md`](../../open-questions.md) — `parameters` enforcement (deferred per Q12, PRD §"Out of scope")
