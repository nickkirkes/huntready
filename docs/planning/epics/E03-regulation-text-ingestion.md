# E03: Montana Regulation Text Ingestion

**Status:** In Progress (11/14 stories complete; S03.6.1 closed 2026-05-22 — MT-STATEWIDE-bear anchor + first jurisdiction_binding ever written + `db.upsert_jurisdiction_binding` helper introduced for S03.10 to reuse)
**Milestone:** M1 — Montana Ingestion
**Dependencies:** E01 (complete, merged 2026-04-28), E02 (complete and audited 2026-05-03)
**Validated:** 2026-05-03
**Estimated Stories:** 13 original + S03.6.1 carved out during S03.9 → 14 total
**UAT Gating:** S03.3 (UAT cleared 2026-05-08), S03.4 (UAT cleared 2026-05-12), S03.5 (UAT cleared 2026-05-14), S03.6 (UAT: no), S03.7 (data-layer UAT cleared 2026-05-16), S03.8 (UAT: no), S03.9 (UAT: no), S03.6.1 (UAT: no — pattern extension of S03.6; closed 2026-05-22), S03.10, S03.12 (entity ingestion + binding + milestone exit)

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
3. **Open-questions entry** in `docs/open-questions.md`. **Mechanical trigger (replaces the prior "only when recurring" rule):** an entry is required whenever the matching `E03-deferred-items/<topic>.md` file accumulates 2+ entries (one entry alone may be a one-off; two becomes a class). When the second entry lands in any deferred-items file, the implementer adds a one-line `open-questions.md` pointer at the same time. PM (with user) consolidates and authors the actual question after review. This is mechanical, not judgment-dependent — the trigger is a file-size check.
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

- [x] New migration `supabase/migrations/20260504032424_e03_schema_additions.sql` creates `license_season` table (composite PK + index per ADR-018 §1), adds `geometry.legal_description text NULL`, and updates `geometry.kind` CHECK constraint to include `'state'`
- [x] Pydantic update (`ingestion/ingestion/lib/schema.py`): new `LicenseSeason` `BaseModel`; `Geometry.legal_description: str | None`; `Geometry.kind` Literal extended with `"state"`
- [x] TypeScript update (`mcp-server/src/types/schema.ts`): matching changes; `tsc --noEmit` clean
- [x] architecture.md §"Schema types" + supporting prose updated (per ADR-018 §"Three-place sync"); also absorbed in `615120c` ahead of S03.0's PR with the broader M1-reality alignment pass — T4 verified during S03.0 implementation
- [x] One `geometry` row written: `MT-STATEWIDE-geom`, `kind='state'`, valid MultiPolygon (`ST_IsValid=true`, single-part, `area_km2 ≈ 380,840`), `license_year=NULL`, `source = mt-msdi-framework-boundaries-9-2026` (Montana State Library, `document_type='gis_layer'`, `publication_date=2026-01-01`). Live-loaded 2026-05-04 16:25 PT via `load_state_boundary.py`. Idempotent UPSERT confirmed.
- [x] Source choice + SHA recorded in `docs/planning/epics/E03-confidence-findings/S03.0.md` — **chose Montana State Library MSDI Framework Boundaries layer 9** (gisservicemt.gov), a third option that strictly dominates ADR-018's two listed options (state-published + GCDB-aligned at 1:24,000; still fits `document_type='gis_layer'` so no `'reference_boundary'` Literal extension needed). Verified empty: no state-boundary layer on FWP on-prem (`fwp-gis.mt.gov`) or AGOL `MtFishWildlifeParks` org. Pinned URL + SHA-256 + `2026-01-01` publication date in load script + working note.
- [x] `docs/planning/epics/E03-confidence-findings/README.md` exists explaining deletion policy
- [x] `docs/planning/epics/E03-deferred-items/README.md` exists explaining survival policy
- [x] Migration applies cleanly to a fresh Supabase project after E01's + E02's migrations
- [x] `ruff check`, `mypy`, `tsc --noEmit` all clean — 332/332 ingestion tests green
- [x] No regulation data loaded — schema-prep only

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

- [x] `ingestion/ingestion/lib/pdf_fetch.py` exists with documented public API (`fetch_pdf`, `PdfMetadata`, `PdfFetchError`); module docstring cites ADR-001/003/005/014
- [x] `ingestion/states/montana/sources.yaml` exists with all four PDF entries; each entry carries the full SourceCitation field set per spec. **Schema extended with `pending: true` flag** — used on the Black Bear correction entry whose URL is genuinely TBD (operator-known-incomplete vs. configuration error). Pending entries still cause non-zero exit so downstream stories cannot run against an incomplete fixture set.
- [x] `ingestion/states/montana/fetch_pdfs.py` orchestrates the four fetches via the shared library; aggregated fail-loud (every entry attempted; failures and pending entries reported in distinct buckets in one `PdfFetchError`)
- [x] Per-PDF manifest written at `<id>-<publication_date>-pdf-manifest.json` with all 8 fields; ~1 KB each. **Infrastructure-met; first real manifests land at first ops-run** against live MT FWP URLs — same fixture-deferred posture as E02 S02.1.
- [x] Raw `.pdf` files stay local-only — gitignored at `ingestion/states/montana/fixtures/.gitignore` with anchor comment documenting the ~10MB-per-fetch policy; `*-pending-reextraction.flag` and `*.tmp` also excluded
- [x] Re-fetch against unchanged source produces identical manifest content (modulo `fetched_at`) — covered by `test_re_fetch_with_same_sha_preserves_manifest_modulo_fetched_at`
- [x] **SHA-256 drift on re-fetch raises `PdfFetchError` AND writes `<id>-<publication_date>-pending-reextraction.flag` marker file.** Marker write is itself wrapped in an `OSError` guard so the primary drift error is not masked by an FS failure. Downstream stories (S03.3-S03.5) check for the marker and refuse to proceed.
- [x] `pdf_fetch.py` honors the same throttling + User-Agent conventions as `arcgis.py` — reuses `arcgis._build_session` / `arcgis._throttle` so a single fetch script that hits both ArcGIS and PDF endpoints honors a unified per-host rate limit (documented in module docstring; refactor path to `lib/http.py` if a third HTTP consumer arrives)
- [x] `ruff check`, `mypy ingestion/lib/pdf_fetch.py` clean
- [x] Unit tests cover happy path, 404, network errors (Connection/Timeout), corrupt prior manifest, SHA drift (3 cases including marker-file write), polite throttling, manifest determinism, citation-field round-trip — **17 tests in `test_pdf_fetch.py` + 16 tests in `test_fetch_pdfs.py` = 33 new tests** (332 → 365 suite total)
- [x] No imports from state adapters; no Montana-specific code in the shared lib — enforced by AST-based test (`TestFetchPdfNoStateAdapterImports`) plus state-slug substring scan; AST guard prevents drift even if a future contributor hides an import behind aliasing

**Closure note (2026-05-04):** Branch `feat/S03.1-pdf-fetch-infrastructure`, 8 commits (`b16dc9d..ef3f467`). Net: 1,310 LOC of source/test + 860 LOC plan. Two ADR-adjacent design choices baked in: (a) `pending: true` YAML semantics for operator-visible incomplete intent that still blocks exit-0; (b) drift-marker convention (`*-pending-reextraction.flag`) as the canonical fail-loud-and-block-downstream signal, generalizable beyond PDFs. Both flagged for PM judgment in the closure summary; neither escalated to a formal ADR — `pending: true` is adapter-specific (revisit if a second state adopts), and the drift-marker pattern is already encoded in the S03.1 epic prose and ADR-001's parent discipline.

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

**Tier-rank MIN, NOT lexicographic MIN:** the helper `ConfidenceTier.min_tier(rows: Iterable[ConfidenceTier]) -> ConfidenceTier` MUST implement most-uncertain-wins semantics with explicit rank ordering: `high(rank=2) > medium(rank=1) > low(rank=0)`, MIN = lowest rank. The naive Python idiom `min(["high", "medium", "low"])` returns `"high"` lexicographically (h < l < m) — that's the wrong answer. Implement as a proper enum with `__lt__` comparing the rank field, OR as a helper function with an explicit rank dict. Unit tests must cover the trap case directly so a future refactor can't silently regress to lexicographic semantics.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md).

**Acceptance Criteria:**

- [x] `ingestion/ingestion/lib/pdf.py` exists with documented public API per spec above (332 LOC; 12 public exports including `PdfDocument`, `open_pdf`, `iter_pages`, `extract_text`, `extract_tables`, `find_section`, `PageReference`, `page_reference_to_str`, `ConfidenceTier`, `min_tier`, `demote_one_tier`, `PdfExtractionError`)
- [x] `extract_text` returns source string with no wrapper-level normalization. **ADR-008 boundary clarified during S03.2 review:** pdfplumber's word-grouping collapses repeated *internal* whitespace as part of its glyph-to-text reconstruction (PDF content streams don't carry literal inter-word spaces — recovering them is what pdfplumber does). The wrapper adds zero normalization on top. ADR-008's concrete concern (paraphrase prevention — e.g., "160 acres" vs "640 acres") is fully met: numeric tokens, units, and lexical words are byte-exact. Defense recorded in `docs/planning/epics/E03-confidence-findings/S03.2.md` § "Why extract_text accepts pdfplumber's word-grouping (ADR-008 boundary defense)". Char-level reconstruction (`page.chars`) remains available as a separate helper if a downstream story needs byte-exact text — to be added as `extract_text_chars_raw(page) -> str` rather than retrofitted onto `extract_text`.
- [x] `PageReference` TypedDict exposed for downstream callers; `page_reference_to_str` collapse helper produces deterministic strings (`f"{pdf_filename}:p{page_num_1based}"`); round-trip covered by `TestPageReference`
- [x] Confidence framework helpers reference ADR-017 (signal definitions, MIN aggregation, correction-touched demote-one-tier rule); `ConfidenceTier(str, Enum)` mixin so instances ARE strings, eliminating `.value` access at every callsite when writing to `regulation_record.confidence`
- [x] **MIN aggregation helper unit-tested with explicit tier-rank trap cases:** `test_lexicographic_trap_explicit` carries three assertions — rank-correct result; raw-string trap (`min(["high","low","medium"]) == "high"`); enum-`.value` trap (`min(tiers, key=t.value) == HIGH`). `min_tier` uses explicit `key=lambda t: t.rank` rather than bare `min()` so the rank ordering doesn't depend on MRO reasoning about the `[ConfidenceTier, str, Enum, object]` chain.
- [x] `ruff check`, `mypy ingestion/lib/pdf.py` clean (mypy clean across all 7 source files)
- [x] Unit tests cover: table extraction on a fixture, prose extraction with bbox crop, page-reference round-trip, whitespace preservation. **39 tests in `test_pdf.py`** (576 LOC); 365 → 404 suite total. Notable coverage: `test_no_layout_true_regression_guard` (monkeypatch spy ensures `extract_text` does not silently set `layout=True`); `test_empty_table_emits_warning` (silent-failure-hunter P1 fix — `find_tables()` locates a boundary but `Table.extract()` returns []); `TestPdfNoStateAdapterImports` (AST walk + slug substring scan, mirrors `test_pdf_fetch.py:422-473`).
- [x] No Montana-specific code; no imports from state adapters — enforced by AST-based test guard (not just substring scan)

**Closure note (2026-05-06):** Branch `feat/S03.2-pdf-extraction-primitives`, 3 commits (`80fcca0` feat, `2c3fed9` pitfalls, `ceaca2c` verbatim defense). Net: 332 LOC source + 576 LOC tests + 730 LOC plan + 62 LOC working note. Three load-bearing design choices recorded for downstream reuse: (a) `extract_tables` uses `page.find_tables()` not `page.extract_tables()` because only `find_tables()` returns Table objects with `.bbox` — `extract_tables()` returns cells with no spatial info (filed as pitfall); (b) `extract_text` accepts pdfplumber's internal word-grouping under the ADR-008 boundary defense above; (c) `open_pdf` wraps `pdfminer` exceptions in a broad `except Exception` because pdfminer's hierarchy has no stable public base — `__cause__` preserved via `from exc`. Two new pitfalls in `.roughly/known-pitfalls.md` under "Integration — pdfplumber".

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
          "archery_only": {"window": "9/7-10/20", "weapon_type_override": "archery"},
          "general": {"window": "10/26-12/1", "weapon_type_override": null},
          "heritage_muzzleloader": {"window": "12/2-12/15", "weapon_type_override": "muzzleloader"}
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

`season_coverage` is the per-license coverage truth that S03.7 reads to write `license_season` rows. `season_windows` is the union across all licenses (same window structure shared per HD), with each window carrying both the date span and a `weapon_type_override` derived from the source's column-header semantics:

- `ARCHERY ONLY` column → `weapon_type_override="archery"`
- `HERITAGE MUZZLELOADER` column → `weapon_type_override="muzzleloader"`
- `GENERAL`, `LATE`, `EARLY SEASON` columns → `weapon_type_override=null` (no season-level weapon restriction)

S03.7 reads `weapon_type_override` directly to populate `season_definition.weapon_type` — no string-matching on the season name. This avoids the "what weapon does the 'Archery Only' season impose" inference becoming a magic-string convention.

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

- [x] `ingestion/states/montana/extract_dea.py` exists with `main(argv) -> int` CLI and produces deterministic `dea-2026.json` — byte-identical SHA-256 across re-runs (`extracted_at` sourced from manifest `fetched_at`, not `datetime.now()`)
- [x] All deer/elk HD subsections (pp. 48-123) extracted with `verbatim_text` and structured `rows` (each row carrying `season_coverage`) — **129 deer + 112 elk sections in artifact**
- [x] **`season_windows[<key>]` carries both `window` (date span string) and `weapon_type_override`** derived from source column header, not season name. **CLOSED 2026-05-08 (UAT fix cycle):** `_rows_to_license_extractions` now reads each row's own season-column cells inline; `_aggregate_section_season_windows` and `_row_season_windows` deleted; divergence-WARNING branch removed (divergence is data, not anomaly). HD 124 deer artifact preserves 3 distinct General Season window values (`Oct 24-Oct 30`, `Oct 24-Nov 29`, `Oct 31-Nov 29`) across 5 rows; `TestPerRowSeasonWindows` (5 tests) locks the contract with `len(set(...)) >= 3` set-cardinality assertion guarding against first-observation-wins regression.
- [x] All antelope HD subsections extracted, plus the `900-20` statewide overlay row. **CLOSED 2026-05-08 (UAT fix cycle):** new `_parse_portions_hd_list`, `_is_portions_subsection_row`, `_PORTIONS_HEADER_RE`. Antelope orchestrator walks pages directly, building logical sections from one of three delimiters (HD-numbered, Portions, Region N). Region 7 portions sub-sections now emit one `DeaSectionExtraction` per listed HD with rows duplicated (option (a) confirmed). HD 690 has exactly 2 native rows (`690-20`, `690-30`); HDs 700, 701, 702, 703, 704, 705 each present with `007-*` rows; HDs 701 and 703 appear in both North and South Yellowstone portions (correctly). Directional qualifier ("North of the Yellowstone River" / "South of the Yellowstone River") preserved in `verbatim_text`. `TestPortionsHelpers` (5 tests) + `TestArtifactRegion7Portions` (5 tests) lock the contract.
- [x] Every extracted row carries a `PageReference` and an `extraction_confidence` value (post-review fix added `page_reference` field to `DeaRowExtraction` after AC #337 contract gap caught in code review). Confidence distribution: **601 high + 589 medium + 0 low** (50.5% / 49.5% / 0%; the +12 high-tier rows over the pre-UAT-fix 589/589 split come from the six Region 7 portions sections under HDs 700-705 each carrying two HD-coded `007-*` license rows — see line 346 closure note for the matching count)
- [x] Cleanup rules documented in module docstring with exact regexes; whitespace + hyphenated-rejoin tests lock the contract incl. date-range counter-example (`9/7-10/20` NOT rejoined; license codes like `262-50` NOT rejoined)
- [x] **A/B asymmetric coverage verified:** **143 HDs in artifact exhibit the pattern** (well above "at least one"); structured-field test locks the difference
- [x] Statewide antelope overlay extracted exactly once; emitted row distinct from per-HD antelope rows. **CLOSED 2026-05-08 (UAT fix cycle):** `_extract_statewide_antelope_overlay` and `_ANTELOPE_900_ROW_RE` deleted. Orchestrator identifies the 900-20 row during the antelope walk, dedups, and emits via the same `_rows_to_license_extractions` machinery with `is_statewide_overlay=True` (suppresses only the universal 900-20 dedup filter). Result is column-faithful: `season_coverage.archery_only=False`, `season_coverage.general=True`, `season_windows.general.window="Aug. 15-Nov. 08"`, `license_code="Antelope License: 900-20"` (prefix kept), `quota_range="1-7,500"` (comma kept), `opportunity="Either-sex"` (verbatim from PDF), `extras="First and only choice. ArchEquip only."` (verbatim, with whitespace collapsed at extras write-site), `weapon_types=["archery"]` (derived from extras text). `TestStatewideOverlayColumnFaithful` (2 tests) locks the directive's Fix 3 dict field-by-field.
- [x] Working note `docs/planning/epics/E03-confidence-findings/S03.3.md` records confidence-assignment patterns + edge cases (~190 lines; deletes at m1 tag per ADR-017 §6). UAT-fix directive lives at [`E03-confidence-findings/S03.3-uat-fixes.md`](E03-confidence-findings/S03.3-uat-fixes.md) (also deletes at m1 tag).
- [x] **UAT (faithfulness, operator-owned):** **PASSED 2026-05-08 after one fix cycle.** Initial UAT (2026-05-08) failed with six defects across four candidates; implementation agent applied three fixes (per-row windows, Region 7 portions slicer, column-faithful STATEWIDE) in commit `cb3fb24`; PM re-ran the workbench against the re-extracted artifact and confirmed all six defects resolved. Verifications: (a) HD 124 deer has 3 distinct General windows across 5 rows preserving per-row divergence; (b) HD 690 has exactly 2 native rows (no phantom 007-* absorption); (c) HDs 700, 701, 702, 703, 704, 705 each present with `007-*` rows per option-(a) emission; (d) STATEWIDE row column-faithful per directive Fix 3 dict (general/archery_only flipped, extras preserved, prefix/comma kept); (e) HD 170 elk regression check clean. Quality gates green: 488/488 tests + 1 skipped, ruff + mypy + cubic clean.
- [x] `ruff check`, `mypy` clean for the new module
- [x] Unit tests cover column header detection, A/B-pattern row grouping with per-license `season_coverage`, statewide-overlay handling, hyphenated-line-break cleanup, cell-padding regex with date-range counter-example — **89 tests in `test_extract_dea.py`** through Phase 7 polish (73 → 84 after UAT fix → 89 after fail-loud guard; net +16 from original 73); suite total **489 + 1 skipped**

**Closure note (closed 2026-05-08 after UAT-driven fix cycle; finalized 2026-05-09 after plan-realignment + fail-loud polish):** Branch `feat/S03.3-dea-booklet-extraction`, 18 commits ahead of main. Final artifact: **272 sections / 1190 rows** (+8 sections / +12 rows vs pre-UAT-fix; the deltas are 6 new Region 7 portions sections under HDs 700-705 plus the dual-region 701/703 entries) / 4 manifests committed. Confidence distribution: 601 high + 589 medium + 0 low (50.5% / 49.5%). Story shipped, failed UAT, fixed, closed in one cycle — the audit trail of "shipped, UAT caught, fixed" is preserved on the branch (no rebase or squash). PR review caught structural issues during code review; PDF spot-checks (UAT) caught two extraction-logic defects (Region 7 absorption; STATEWIDE column remap) and confirmed the previously-flagged "deferred follow-up" of window divergence was actually a P0 faithfulness violation. Four new pitfalls in `.roughly/known-pitfalls.md` under Integration — pdfplumber: (a) FWP DEA-style tables: one-table-per-page assumption; (b) `-` as universal absence sentinel; (c) merged-cell sub-row license-code carry-forward via `None`; (d) "Section-level first-observation-wins for per-row variable fields is interpretive, not faithful" (UAT-discovered). UAT-fix directive at [`E03-confidence-findings/S03.3-uat-fixes.md`](E03-confidence-findings/S03.3-uat-fixes.md) and UAT fix log at [`E03-confidence-findings/S03.3.md`](E03-confidence-findings/S03.3.md) (both delete at m1 tag per ADR-017 §6).

**Phase 6 — plan-realignment (2026-05-09):** after UAT closed, the agent + PM caught that the implementation plan still described the bugs that UAT had just surfaced. Five plan-doc commits aligned the plan with the corrected code so a future re-reader following the plan wouldn't re-create the UAT defects: T7 rewritten to per-row windows ("divergence is the data, not an anomaly"); T8 rewritten to page-range-bounded inline emit (was unbounded `find_section`, P1 risk of TOC matches); T1 `_ANTELOPE_PAGES = (136, 141)` aligned with T8; T10 step 1 rewritten (the deleted helpers `_aggregate_section_season_windows` + `_extract_statewide_antelope_overlay` were still referenced); T12 enumerated post-UAT test classes (was listing the deleted ones); T9 confidence rules aligned with shipped `_assign_row_confidence`; T13 determinism-check command turned into a complete two-step recipe; epic line 337 confidence count corrected from 589/589 to 601/589. **Phase 7 — fail-loud guard (2026-05-09):** restructured the STATEWIDE emit guard to fail loud at three distinct stages (row-not-captured / row-captured-but-zero-extractions / success). Added `TestStatewideOverlayFailLoudOnEmptyExtraction` (monkeypatches `_rows_to_license_extractions` to return `[]` for the statewide call while letting per-HD calls pass through; asserts `PdfExtractionError` with descriptive message). Closes a P1 silent-data-loss path. PM re-verified all six UAT defects still clear after Phase 7 (artifact SHA-256 byte-identical to post-UAT-fix); 489 tests + 1 skipped, ruff + mypy + cubic all clean.

**Deferred follow-ups (non-blocking; surface to downstream):**
- **S03.6 review:** per-row page-accurate `page_reference` for multi-page HDs. Current implementation has every row in a section inherit the section's starting page. For multi-page HDs (e.g., HD 240 elk content lives on p59 but is tagged with p58), `row.page_reference.page_num_1based` does not reflect the actual source page. Fix would require `_extract_hd_table` to track per-row page-of-origin.
- **S03.7 review:** row-level `weapon_types` default. All rows emit `["any_legal_weapon"]` except statewide overlay (`["archery"]`). Per-license weapon eligibility comes from `weapon_type_override` in `season_windows`; the row-level field is operationally correct for V1 but may need refinement.
- ~~**Docstring polish:** the UAT fix added a 4th cleanup rule (extras-only `re.sub(r"\s+", " ", normalized_extras)` collapse) — documented inline at the write-site but not in the module-level "Cleanup rules" section.~~ **CLOSED 2026-05-08:** docstring entry added at `extract_dea.py:44-60` with exact regex, scope, rationale, and reference to the locking tests (`TestStatewideOverlayColumnFaithful`, `TestArtifactRegion7Portions`). AC #338 in strict parity with code. The pattern — every cleanup rule applied to row cells must appear in the module docstring — is established for S03.4+ to follow.

**Note:** the third deferred follow-up from the original 2026-05-08 closure ("window divergence per row, first-observation-wins") was promoted to P0 defect D1 by UAT and fixed in `cb3fb24`. It no longer appears as a deferred follow-up.

---

### S03.4: Black Bear booklet extraction + correction PDF handling

**As a** developer extracting Montana black bear regulations
**I want** the BMU regulation table, the closure-rules prose, and the March 18 correction PDF integrated into a single coherent intermediate via deterministic date-arbitration
**So that** S03.6-S03.9 ingest the latest authoritative state and the correction-handling pattern is established for future states with similar amendments

**UAT: yes** — faithfulness review against the Black Bear PDF + correction PDF for ≥3 sampled BMUs (one each from a quota-closure BMU, a female-sub-quota BMU, and an unrestricted BMU).

**Context:**

Black Bear booklet structure (2026, 16 pages; corrected against live PDF during S03.4):
- BMU regulation table: **pp. 9-12** (35 rows, one per Black Bear "Hunting District" / BMU) — research notes said 10-11; live PDF spans 4 pages, and the table is **transposed + rotated** in the print layout, so pdfplumber returns each cell with both line and char order reversed (see `_reverse_cell_text` in `extract_black_bear.py`)
- Closure rules prose: p. 7 (two-column page; closure prose is in the right column, requiring `extract_text(page, bbox=(306, 0, 612, 792))`)
  - **Quota closure list (8 BMUs, corrected from spec's stale 9):** BMUs 411, 420, 440, 450, 510, 520, 600, 700 — **BMU 530 does not exist in the 2026 PDF**; agent locked at 8 with a drift-guard test that fails loud if a future edition re-introduces 530
  - **Female sub-quota (4 BMUs, source-anchored as the Spring Season Closure list):** BMUs 300, 301, 319, 580 (each carrying a `*` footnote suffix in the BMU column; `_BMU_NUMBER_REGEX = r"^(\d{3})\*?$"` matches and strips)
- Region-specific reporting prose (3 obligations, corrected from spec's stale 2): the page-7 prose carries **three distinct reporting requirements**: (a) STATEWIDE Mandatory Reporting (48-hour harvest report applicable to all successful hunters statewide), (b) R1 Inspection (tooth submission within 10 days), (c) R2-7 Inspection (hide + skull presentation within 10 days). The STATEWIDE 48-hour requirement is operationally distinct from the R1/R2-7 inspection split and S03.9 must ingest it as its own `reporting_obligation` record.

**Correction PDF (1 page, 2026-03-18):**
- Amends black bear hound licensing
- Removes a column from the BMU table (per research notes — exact column TBD at extraction time)
- Per [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), `document_type='correction'` and the `supersedes` field in `SourceCitation` points to the **canonical id of the booklet's SourceCitation, sourced from `sources.yaml`** (per S03.1's deliverable). The correction's own `SourceCitation.id` is also from `sources.yaml`.

**Three-pass arbitration logic (Option B — doc-type precedence; revised 2026-05-12):**

> **Spec history:** the original spec rule was "MAX `publication_date` wins" (Option A). UAT against the live Montana 2026 set showed this would silently no-op: the booklet's `Last-Modified` header (`2026-04-27`) post-dates the correction (`2026-03-18`) by ~6 weeks. Option A would treat the booklet as authoritative over the correction, defeating the merge. **Decision (PM, 2026-05-12; ADR-019 candidate):** doc-type precedence — `document_type='correction'` always wins over `'annual_regulations'`; date is a tiebreaker only within the same doc-type. The Last-Modified-as-publication-date pin we adopted during the 2026-05-07 URL discovery is reliable for ordering within a single doc-type but does NOT carry semantic "supersedes" intent across doc-types. `document_type='correction'` is the hand-curated authoritative signal.

1. **Pass 1 — base extraction:** read the Black Bear booklet, produce `extracted/black-bear-2026-base.json` with all rows tagged `{source_id: <booklet_citation_id>, source_publication_date: <booklet date>}`
2. **Pass 2 — correction extraction:** read the correction PDF, produce `extracted/corrections-2026-03-18.json` of `{target: <addressing key>, change: <set/remove/replace>, new_value: <verbatim from correction>, source_id: <correction_citation_id>, source_publication_date: 2026-03-18}` operations
3. **Pass 3 — doc-type-precedence merge:** for each cell in the base extraction, resolve to the value from the source with the highest doc-type rank (`correction` > `annual_regulations`). Cells touched by a correction take the correction's value; untouched cells keep the booklet's value. Each resolved row's `source_id` matches the row-level winning source. Rows touched by the correction also get `supersedes: <booklet_citation_id>` and `applied_correction: true` markers (the latter is a derived convenience; consumers who want to query "which records were touched by a correction" use `source.document_type='correction'`).

The merged output `extracted/black-bear-2026.json` is what S03.6-S03.9 consume. The base + correction artifacts are **both committed** for audit trail (the doc-type-precedence merge is verifiable by re-running pass 3).

**Per-cell value arbitration; row-level source attribution (V1 simplification):** correction operations target individual cells, so the *value* arbitration is per-cell. However, `BmuRowExtraction` carries a single `source_id` + `source_publication_date` **per row**, not per cell. When a correction touches any cell of a row, the row-level source attribution updates to the winning correction's source. AC #431's "touched cells carry the correction's publication_date" is satisfied at row granularity. True cell-level source attribution would require splitting `BmuRowExtraction` into cell-level structures — **deferred to M2** per the schema-stability discipline.

**Tiebreaker rules and missing-date handling (V1 contract):**

- **Same-cell equal-date collisions across same-doc-type sources:** the loader raises `CorrectionConflictError` with both `source_id`s in the message. The 2026-03-18 correction is the only V1 correction so this never fires in M1, but the contract is locked in now.
- **Same-doc-type equal-date different-field ties at row level (touched by two corrections):** lex-smallest `source_id` wins for row-level provenance assignment. Deterministic regardless of dict-insertion order. Added during S03.4 cubic-review iteration after a first pass had iteration-order-dependent provenance.
- **Unparseable or missing `publication_date` on any source:** fail-loud at `sources.yaml` load time (in S03.1's `pdf_fetch.py` or wherever the citation set is parsed). Missing/unparseable dates never reach the merge stage. ISO-8601 date string required; reject everything else.

**Closure-prose handling:** The quota-closure list and female-sub-quota list from p. 7 become structured `ClosurePredicate` jsonb values on the corresponding `season_definition` rows in S03.7. Each closure has a `kind` (`quota_threshold` or `sex_threshold`), `notification_channel`, `verbatim_rule` (the source sentence from p. 7), and where applicable `threshold_percent` (e.g., 37% for the female sub-quota) and `threshold_sex='female'`.

**Closure temporal-anchor handling (per Schema validator SF2):** the female-sub-quota text says "at any point after May 31 if the cumulative spring harvest exceeds 37%." The temporal anchor ("after May 31") has no structured field in `ClosurePredicate` (which is `kind / threshold_percent / threshold_sex / notification_channel / observation_channel / verbatim_rule`). **For V1: keep the temporal anchor in `verbatim_rule` only; do NOT invent a structured field.** Flag for a future ADR (potentially adding `effective_after: date | null` to `ClosurePredicate`) per the operational definition. Add an entry to `docs/planning/epics/E03-deferred-items/closure-temporal-anchors.md` if this pattern recurs in future sources.

**Region-specific reporting (3 obligations, corrected from spec's stale 2):**
- **STATEWIDE Mandatory Reporting:** 48-hour harvest report applicable to all successful black bear hunters (page-7 prose: "All successful black bear hunters must personally report their black bear harvest within 48 hours.")
- **Region 1 Inspection:** 2 premolar teeth submission within 10 days
- **Regions 2-7 Inspection:** full hide + skull presentation within 10 days

These become **three distinct** `reporting_obligation` rows in S03.9. The STATEWIDE 48-hour requirement is operationally distinct from the R1/R2-7 inspection split — discovered during S03.4 UAT 2026-05-12; the spec's earlier "2 obligations" claim missed the statewide one.

**Per-BMU `hd_region` field in extraction output (per N2):** S03.4's extraction artifact carries `hd_region: 'R1'|'R2'|'R3'|'R4'|'R5'|'R6'|'R7'` per BMU row, sourced from the regional map in the Black Bear PDF (typically p. 5 — verify at execution time). S03.9 reads this field to drive the R1 vs R2-7 reporting_obligation linkage. If the map can't be parsed cleanly into a per-BMU mapping, fall back to a hand-curated `bmu_region_overrides.yaml` companion file checked into `ingestion/states/montana/`; flag-and-defer the cleaner extraction to M2.

**Confidence per ADR-017:**
- Base extraction rows: `high` (structured table cells)
- Closure-prose rows: `medium` (heading-anchored prose interpretation per ADR-017's tier definitions)
- Region-specific reporting rows: `medium` (same)
- **Correction-touched rows: demote one tier** per ADR-017 §4 (so a base `high` becomes `medium` after the correction merge; a base `medium` becomes `low`)

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md).

**Depends on:** S03.1, S03.2.

**Precondition (resolved 2026-05-07):** the Black Bear correction URL was located on FWP's regulations page during the S03.3 unblock — the file is at [`https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/corrections-to-the-2026-printed-black-bear-regulations.pdf`](https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/corrections-to-the-2026-printed-black-bear-regulations.pdf) (HTTP `Last-Modified: 2026-03-18`, matching the date in the citation id). [`ingestion/states/montana/sources.yaml`](../../../ingestion/states/montana/sources.yaml) was updated 2026-05-07 with the canonical URL and the `pending: true` flag was removed. S03.4 can now fetch the correction normally; no operator action remains.

**Acceptance Criteria:**

- [x] `ingestion/states/montana/extract_black_bear.py` exists with the three-pass arbitration architecture; deterministic outputs (~1820 LOC; AST state-agnostic guard verified)
- [x] `extracted/black-bear-2026-base.json`, `extracted/corrections-2026-03-18.json`, and `extracted/black-bear-2026.json` (merged) all committed
- [x] All 35 BMU rows extracted with verbatim_text, page_reference, and the structured row payload (each row carrying `hd_region` per rule N2). **`hd_region` derived from in-table "REGION N" column markers tracked left-to-right** — the regional map on p. 8 is image-only and unparseable, so no `bmu_region_overrides.yaml` fallback was needed.
- [x] **Fail-loud guard:** in-place; extraction halts with descriptive error if BMU count drops below the 30-row floor
- [x] Closure-prose extracted into structured `ClosurePredicate` candidates: **8 quota-closure BMUs (corrected from spec's stale 9; BMU 530 absent from 2026 PDF)** + 4 female-sub-quota BMUs; verbatim source sentence preserved; Spring Season Closure temporal anchor ("at any point after May 31") kept in `verbatim_rule` per V1 deferral; deferred-items note at `docs/planning/epics/E03-deferred-items/closure-temporal-anchors.md` (survives past M1). Drift guard in `_extract_closures` locks the 8-BMU count against any future cross-edition re-introduction.
- [x] Region-specific reporting prose extracted into **3 candidate `reporting_obligation` records (corrected from spec's stale 2): STATEWIDE 48-hour mandatory reporting + R1 tooth_submission + R2-7 hide_skull_presentation** — STATEWIDE is operationally distinct from the R1/R2-7 inspection split and S03.9 ingests all three. Verbatim source text preserved per row.
- [x] Correction PDF parsed; **doc-type-precedence merge applied (Option B per PM decision 2026-05-12)** — `document_type='correction'` wins over `'annual_regulations'` regardless of date; date is tiebreaker within same doc-type only. Correction is prose-only (no tables); 35 per-BMU `CorrectionOperation` dicts synthesized from the "Removed the hound training season column" anchor. Affected rows tagged `applied_correction: true` and carry `supersedes: mt-fwp-black-bear-2026-booklet`. ADR-019 candidate flagged to formalize the doc-type-precedence rule.
- [x] **Correction-wins verified at row granularity** (Option B equivalent of the spec's MAX-date claim): every BMU row in `black-bear-2026.json` carries `source.publication_date == 2026-03-18` and `source.id == mt-fwp-black-bear-2026-correction-2026-03-18` because the correction touches every BMU's `hound_training_season` cell. Unit test `test_correction_wins_despite_earlier_date` locks the Option B contract (a hand-crafted correction with an earlier date than the booklet still wins). **Row-level source attribution is a V1 simplification** — true cell-level attribution deferred to M2 (would require `BmuRowExtraction` schema split).
- [x] **Date-collision tiebreaker:** `TestMergeWithCorrections::test_cell_level_equal_date_conflict_raises` confirms same-cell equal-date raises `CorrectionConflictError` with both source_ids surfaced
- [x] **Missing/unparseable `publication_date`** fail-loud at `sources.yaml` load time covered by S03.1's `pdf_fetch.py` test suite; S03.4 adds citation-loader fail-loud paths for malformed dates that would reach the merge stage
- [x] **Correction-touched rows demoted one tier** per ADR-017 §4 — `demote_one_tier` fires **exactly once per touched BMU** (not once per touched field), enforced at Stage 3 of the merge. Unit test locks the regression: a HIGH row + 2 ops still demotes to MEDIUM (not LOW). All 35 BMUs HIGH → MEDIUM after merge (every row touched by the column-removal correction).
- [x] Citation IDs read from `sources.yaml` — `mt-fwp-black-bear-2026-booklet` (`publication_date: 2026-04-27`) and `mt-fwp-black-bear-2026-correction-2026-03-18` (`publication_date: 2026-03-18`). Citation-loader paths fail loud on missing IDs or malformed entries.
- [x] Working note `docs/planning/epics/E03-confidence-findings/S03.4.md` records confidence-assignment patterns, correction-demote interactions, and the Option B rationale (~8 KB; deletes at m1 tag per ADR-017 §6)
- [x] **UAT (faithfulness, PM-driven 2026-05-12):** **PASSED.** PM verified four BMUs (411 quota-closure + female-sub-quota interaction; 300 female-sub-quota / Spring Closure; 100 unrestricted; 700 quota-closure) against `pdfplumber`-extracted source text. Closure prose + reporting obligations cross-checked against PDF page 7 — all artifact values match source. One faithfulness caveat documented: pdfplumber returns rotated-table cells in word-by-word order that doesn't preserve sentence flow, so `opportunity` and `verbatim_text` fields contain every source word but in scrambled order. **Structured fields (general_season, archery_only_season, spring_season, quotas, hound_nr_license, hound_nr_max) — which is what S03.6+ consumes — are clean.** This meets ADR-008 verbatim discipline (no paraphrase, every word preserved) with the rotated-table limitation documented in agent's discovery #1 + new `.roughly/known-pitfalls.md` entry.
- [x] `ruff check`, `mypy` clean (9 source files including extract_black_bear.py)
- [x] Unit tests cover: text reversal, normalization, dash-sentinel detection, quota-cell parsing (3 word orderings), region detection, Permit Managed sub-table detection, BMU row extraction, closure prose + drift guard (8-BMU lock), reporting obligation prose (3 candidates), correction prose parsing + anchor-missing fail-loud, Option B merge correctness (correction-wins-despite-earlier-date regression test), cell-level date-collision (`CorrectionConflictError`), row-level tiebreaker (lex-smallest source_id), tier-demote-once-per-row, unknown-target_field validation, unrecognized hd_region fail-loud, deterministic JSON write, citation loader fail-loud paths, AST state-agnostic guard. **+85 tests in `test_extract_black_bear.py` + 1 intentional skip; suite went from 489/1 to 574/2.**

**Closure note (closed 2026-05-12; PR `ab09e82` squash-merged to main 2026-05-12):** Branch `feat/S03.4-black-bear-extraction` (5 commits `fbaaf6e..90e5628`), PR review cleared. Final artifact: **35 BMU rows / 2 closures (1 sex_threshold + 1 quota_threshold) / 3 reporting obligations / 2 sources** in `black-bear-2026.json`. Confidence distribution post-merge: **35 medium / 0 high / 0 low** (all 35 rows touched by the correction's hound_training_season column removal → HIGH → MEDIUM via `demote_one_tier`). The S03.4 spec's research notes did not survive contact with the actual PDF — **12 real-PDF discoveries** baked into the implementation: (1) BMU table is transposed + printed rotated; pdfplumber returns each cell with both line and char order reversed ("Sep.15-Nov.29" extracts as "92.voN-51.peS"; `page.rotation` reports 0); `_reverse_cell_text` applied before normalization. (2) Table page range is pp. 9-12, not pp. 10-11 as spec claimed. (3) 8 quota-closure BMUs (BMU 530 absent), not 9. (4) Correction PDF is prose-only (no tables) — operations synthesized per-BMU from the "Removed the hound training season column" anchor. (5) Regional map (p. 8) is image-only and unparseable; `hd_region` derives from in-table "REGION N" column markers tracked left-to-right. (6) Permit Managed sub-table on p. 11 (3 columns with different row semantics for BMUs 510-20, 520-20) skipped via `in_managed_block` state flag that resets on each REGION marker. (7) "Quota Managed Opportunities" is opportunity-description text (NOT a sub-table header). (8) Female-sub-quota BMUs carry a `*` footnote suffix (`300*`, `301*`, `319*`, `580*`); `_BMU_NUMBER_REGEX = r"^(\d{3})\*?$"` matches and strips. (9) Quota cells appear in 3 distinct word orderings in the rotated table; `_parse_quota_cell` uses a primary regex + word-order-invariant component-extraction fallback. (10) Closure-prose page (p. 7) is two-column — `extract_text(page, bbox=(306, 0, 612, 792))` required to isolate the right column. (11) Phone number "1-800-385-7826" splits across lines; `_DIGIT_LINEBREAK_RE` substitutes `r"\1-\2"` (NOT `r"\1\2"` — that would strip the structural dash and corrupt verbatim text per ADR-008). (12) Closure-prose drift guards scoped to the first sentence to avoid phone-number / threshold digits contaminating the BMU set comparison. **Two cubic-review iterations** during wrap-up caught and fixed correctness defects in `_merge_with_corrections`: (a) per-(bmu, field) loop overwrote row-level source_id on each iteration so final provenance depended on dict-insertion order — refactored into three stages with row-level state updated exactly once per touched BMU; (b) `demote_one_tier` fired inside the per-(bmu, field) loop, so a row touched by N corrections was demoted N times (HIGH + 2 ops would land at LOW, violating ADR-017 §4's single-step rule) — moved to Stage 3 to fire exactly once per touched BMU; (c) initial post-refactor `max(..., key=date)` was still iteration-order-dependent on equal-date ties — added a two-pass selection with lex-smallest-source_id tiebreaker. All three regressions locked by dedicated unit tests in `TestMergeWithCorrections`. **Eight new pitfalls in `.roughly/known-pitfalls.md`** (6 from initial implementation + 2 algorithmic patterns from cubic-review iteration): rotated tables emit doubly-reversed cells; two-column page layouts interleave text in extract_text; quota-cell word order varies by extraction context; spec-table BMU/HD lists must be cross-checked against the live PDF (with first-sentence-scoped drift guards); correction-merge arbitration is doc-type-precedence not date-precedence; BMU/HD identifier regexes must handle footnote-marker suffixes; multi-iteration state writes must hoist out of the loop (otherwise iteration-order-dependent or N-times-fired); `max()` / `min()` with comparable ties need an explicit secondary key for deterministic semantics.

**Deferred follow-ups (non-blocking; surface to downstream / M2):**
- **Cell-level source attribution (M2):** `BmuRowExtraction` carries one `source_id` + `source_publication_date` per row, not per cell. AC #431 is satisfied at row granularity. True cell-level would require a `RegulationRecord` schema change splitting rows into cell-level structures. Recorded in working note + closure-temporal-anchors deferred-items file.
- **Spring Season Closure temporal anchor:** "at any point after May 31" has no structured field in `ClosurePredicate` (current fields: `kind`, `threshold_percent`, `threshold_sex`, `notification_channel`, `observation_channel`, `verbatim_rule`). V1 keeps the anchor in `verbatim_rule` only. **ADR-candidate** at `docs/planning/epics/E03-deferred-items/closure-temporal-anchors.md` (survives past M1) if the pattern recurs in another state. Possible future field: `effective_after: date | null`.
- **ADR-019 candidate (immediate follow-up):** formalize doc-type-precedence correction arbitration as canonical for all future state adapters. Existing PRD 001 R5 "latest-dated source winning" wording needs reconciliation. PM to draft ADR-019 next.
- **Rotated-table verbatim_text limitation:** `opportunity` and `verbatim_text` fields for BMU rows are word-order-scrambled by pdfplumber's rotated-table extraction (all source words preserved; sentence flow not). Structured fields are clean. A future improvement could use OCR or a different PDF library that handles rotation better — deferred indefinitely (low priority; structured fields are the contract).

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

**Unmatched-rate fail-loud threshold:** if `unmatched_count / (matched_count + unmatched_count) > 0.10` (10% unmatched), `extract_legal_descriptions.py` exits non-zero with a clear error message naming the threshold and the actual rate. This catches a regressed PDF parser (e.g., FWP's 2027 update changes heading format) that would otherwise produce a 90%-empty extraction and look "successful." The 10% threshold is the V1 first-cut; tighten or loosen during S03.5 implementation if reality shows it should be different. Below the threshold: the WARN-log + working-note flag continues per the operational definition.

**Where this text goes in the database (per ADR-018):** S03.6 writes `verbatim_description` into **`geometry.legal_description`** (the new column added by ADR-018 §2). **No separator extension on `verbatim_rule`.** The two fields are independent: `verbatim_rule` carries layer-#2 REG/COMMENTS regulatory text (per ADR-015); `legal_description` carries this story's prose boundary description. Both are queryable; neither overloads the other.

**Single-writer contract (avoids dual-writer ambiguity):** S03.5 produces ONLY the JSON extraction artifact at `extracted/legal-descriptions-2026.json`. **S03.5 does NOT write to `geometry.legal_description`.** The database write is exclusively S03.6's responsibility. This prevents two implementers (or one implementer reading the spec independently in two sessions) from both writing the column.

**No regulation_record / season_definition / license_tag / reporting_obligation rows are produced from this booklet** — it's geometry-text-only enrichment.

**Confidence per ADR-017:**
- Headings that match cleanly: `high`
- Headings that fuzzy-match (multiple plausible candidates): `low`
- Headings that don't match (in `unmatched` array): no `extraction_confidence` (the row isn't ingested; it's flagged for human review)

**Relevant ADRs:** [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S03.1, S03.2; S03.0 (the `geometry.legal_description` column must exist); consumes E02's `geometry` table for the matching pass.

**Acceptance Criteria:**

- [x] `ingestion/states/montana/extract_legal_descriptions.py` exists; deterministic output (~1372 LOC; AST state-agnostic guard verified; atomic write, sorted arrays + sorted keys + trailing newline; byte-identical re-run)
- [x] **S03.5 produces only the JSON artifact;** the database write to `geometry.legal_description` is S03.6's responsibility. Single-writer contract locked by `test_no_db_imports` (AST guard against `from ingestion.lib.db import …`).
- [x] Every prose description matched to an existing `geometry_id` OR surfaced in `unmatched`/`unlinked`. Final artifact: **228 matched** (226 HD + 2 CWD, all `extraction_confidence=high`) + **31 unmatched** (by-design `portion_sub_heading_not_resolvable_to_opaque_slug` — out-of-V1-matcher-scope) + **119 unlinked** (9 HD genuinely absent from PDF + 55 portion + 54 restricted_area + 1 STATEWIDE; full 347-row V1 geometry surface accounted for).
- [x] Heading-to-geometry-id matching rule documented in module docstring with the 8 FWP heading variants the regex handles (canonical, no-locator-clause, "The portion of", truncated anchor word, wrapped name, no-colon, `HD` prefix, period-in-name).
- [x] Working note `docs/planning/epics/E03-confidence-findings/S03.5.md` records 11 discoveries (D1-D11), UAT package, and anomaly catalog (deletes at m1 tag per ADR-017 §6).
- [x] **UAT (faithfulness):** **PASSED 2026-05-14 (PM spot-check).** PM verified 2 descriptions against `pdfplumber`-extracted source: HD 100 North Kootenai (deer-elk-lion, page 19 col 1, 385 chars — opens "Beginning where the Kooten River meets the Idaho border..." ends "...the point of beginning"); Libby CWD Management Zone (page 19 multi-column, 1197 chars — the D4 longest-body-wins case that drove the consolidation rewrite; opens "Beginning at the junction of Fisher River Rd and Hwy 37..." ends "...the point o the beginning"). No spillage; no foreign-HD content; standard FWP boundary-description closing phrase preserved. Faithfulness caveat documented: pdfplumber's character-level extraction occasionally drops the last character of words at column-right-edge ("Kootenai" → "Kooten", "border" → "borde", "Libby" → "Libb") — this is a pdfplumber limitation preserved verbatim per ADR-008, not an S03.5 transformation.
- [x] `unmatched` array flagged via the operational definition (WARN log + working-note entry) below the **10% threshold**; above the threshold the script exits non-zero. **Threshold denominator scope excludes the by-design `portion_sub_heading_not_resolvable_to_opaque_slug` class** (those are out-of-V1-matcher-scope, not regression-unmatched). Both branches covered by 4 test methods in `TestMainExitCodes`. Current regression rate: **0.000** (0 regression-unmatched out of 228 V1-matcher candidates).
- [x] `ruff check`, `mypy` clean (10 source files post-S03.5)
- [x] Unit tests cover heading regex (all 8 FWP variants + edge cases), prose extraction, unmatched/unlinked handling, matched-id round-trip — **83 tests in `test_extract_legal_descriptions.py` across 12 classes**. Suite total: **657 + 2 skipped** (was 574+2 pre-S03.5; +83 new).

**Closure note (closed 2026-05-14 after PM-driven UAT-style review + 9 follow-up fix commits):** Branch `feat/S03.5-legal-descriptions-extraction`, 10 commits (`ece1ab1..e96a195`) merged to main as PR `b2ad20b`. Initial implementation surfaced through PM-run review identified 1 P1 (verbatim spillage) + 5 P2 findings; agent applied all in 9 follow-up commits before merge. **The P1 was substantial**: bear-319's `verbatim_description` reached 8059 chars (9x median) because the column-crop x-range was too narrow (145pt for col 2), truncating heading anchor phrases like "Those portions" → "Those portio" and defeating the `Those\s+portions?` regex. Result: 4 subsequent HDs (341, 411, 420, Deckard Flats portion) silently absorbed into bear-319. Agent's regex overhaul (D10 in working note) covers 8 FWP heading variants beyond the original anchor pattern; matched count rose 156 → 228 across the fix cycle and bleed cases dropped 35 → 0. Other discoveries from the cycle (folded into D1-D11): three-column layout makes full-page `extract_text()` unusable; rotated sidebar banners need `c.get("upright", True)` filter; CWD heading wraps across lines; same heading repeats once per column when description spans multiple columns; HD heading anchor phrase wraps onto continuation lines; running PDF footer leaks when crop strip too shallow (20pt → 50pt fix); CWD consolidation must canonicalize names before deduping (D11 defensive); Cleanup Rule C strips the FWP locator clause via `\b[Bb]eg\w*\s+\w` anchor (the `\s+\w` discriminator avoids matching "the point of beginning" closer). **Seven new pitfalls in `.roughly/known-pitfalls.md`** under Integration — pdfplumber (three-column layout; rotated sidebars; newline-in-name-capture; multi-column heading repetition; anchor-phrase line wrap; running footer leak; period-pre-wrap lookbehind). **PM UAT spot-check 2026-05-14** confirmed faithfulness on 2 representative descriptions. **No ADRs created** (S03.5 references ADR-001/005/008/017/018). **MT-STATEWIDE-geom hardcode in `_load_geometry_lookup`** is an M2 follow-up: the V1 `geometry-overlays.json` fixture predates S03.0 and lacks the state row, so the lookup injects it manually; when the fixture is regenerated to include the post-S03.0 row, the hardcode can be removed (the `setdefault` dedup prevents double-counting). Locked by `TestGeometryLookup::test_statewide_present_even_when_fixture_omits_it`.

**Deferred follow-ups (non-blocking; surface to downstream / M2):**
- **Fixture refresh:** regenerate `geometry-overlays.json` to include `MT-STATEWIDE-geom` post-S03.0; then remove the hardcoded injection in `_load_geometry_lookup` (the `setdefault` dedup keeps the loader idempotent against double-insertion).
- **9 missing HDs:** the 9 hunting_district rows in `unlinked` (with `reason='no_heading_in_pdf'`) genuinely don't appear in the 2026-2027 Legal Descriptions PDF. Investigate during M1 UAT if any are queried; escalate to FWP source revision if material.
- **Lowercase "beginning" (HD bear-309):** Cleanup Rule C handles the variant correctly now, but the working note flags whether this is an FWP-side typo or a recurring pattern across booklets. Watch for it in M2 Colorado.
- **Citation slug cadence:** `mt-fwp-legal-descriptions-2026-2027` is biennial; artifact filename is annual (`legal-descriptions-2026.json`). Verify at next operator re-fetch whether the 2027 PDF is a continuation or a separate annual booklet.

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
| ~~`regulation_record.verbatim_rule`~~ (column does not exist; see [^oq1]) | ~~The DEA section's `verbatim_text`~~ — decomposes into `season_definition.verbatim_rule` + `license_tag.verbatim_rule` via S03.7; NOTE-style lines land in `regulation_record.additional_rules` via S03.6 |
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

- [x] `ingestion/states/montana/load_regulation_records.py` exists (~590 LOC, state-agnostic-clean); reads the three extraction artifacts (`dea-2026.json` + `black-bear-2026.json` + `legal-descriptions-2026.json`); deterministic load order; atomic single-transaction write of all rows + all `geometry.legal_description` updates
- [x] **436 `regulation_record` rows written** (DEA species fan-out: artifact uses `{deer, elk, antelope}` per booklet column labels; DB uses `{mule_deer, whitetail, elk, pronghorn, bear}` granular species — `deer` fans out to two regulation_records). Real count differs from spec's 514 estimate due to actual extraction counts; per-species breakdown matches the pre-implementation cross-tab plan (129 mule_deer + 129 whitetail + 112 elk + 31 pronghorn + 35 bear).
- [x] Every row has `state='US-MT'`, `license_year=2026`, `schema_version=2`, populated `source` (jsonb SourceCitation), populated `confidence` per ADR-017's MIN aggregation **using S03.2's `ConfidenceTier.min_tier` helper** (NOT lexicographic `min()` over strings — see S03.2's tier-rank trap-case AC). ~~populated `verbatim_rule`~~ struck — column does not exist per OQ1 resolution; see [^oq1]
- [x] Row-count fail-loud guard: write count must be within `int(514 × 0.70)..int(514 × 1.30)` i.e. `[359, 668]`; outside the band raises `RuntimeError` and aborts the load (OQ7 resolution; first row-count guard in the pipeline, sets precedent for S03.7-S03.10). Symmetric guard added for `legal_description` writes within `[int(228 × 0.70), int(228 × 1.30)] = [159, 296]`. Both guards fire BEFORE `db.connect()` so a regression aborts with no partial writes.
- [x] `legal_description` empty / whitespace-only values written as SQL NULL, never `""` (review N4). V1 data has zero empty descriptions; guard is forward-looking for M2.
- [x] `MT-STATEWIDE-antelope` regulation_record exists (anchor for the DEA `900-20` row). Per ADR-018 §3 flag-and-surface: no additional statewide candidates surfaced during implementation; the working note's "additional statewide candidates" section is empty. **Structural fail-loud:** DEA elk/mule_deer/whitetail + `hd_number="STATEWIDE"` raises `ValueError` because only pronghorn has a sanctioned statewide anchor per ADR-018 §3.
- [x] DEA-sourced rows use `document_type='annual_regulations'`; Black-Bear-correction-touched rows use `document_type='correction'` with `supersedes` populated; citation IDs match `sources.yaml`. Bear path uses `ConfidenceTier(row["extraction_confidence"])` for at-row validation (not bare `cast(Confidence, ...)`) so an invalid extraction_confidence string surfaces with row context immediately.
- [x] NOTE-style lines in DEA HD subsections written to `regulation_record.additional_rules` as `VerbatimRule[]` jsonb (538 NOTEs preserved byte-identical pre/post `^NOTE:[ \t]*` regex hardening; the original `^NOTE:\s*` greedily ate newlines and could absorb downstream NOTE lines — closed before merge).
- [x] **228 geometry-text enrichment writes** to `geometry.legal_description` for matched rows; no `verbatim_rule` overload. `db.update_legal_description` fails loud on `cur.rowcount == 0` so matcher bugs (extractor emitting unknown `geometry_id`) surface immediately rather than silently no-op.
- [x] UPSERT idempotency confirmed: `upsert_regulation_record` is `ON CONFLICT (state, jurisdiction_code, species_group, license_year) DO UPDATE`; `ingested_at` excluded from UPDATE clause so re-runs preserve first-ingest time.
- [x] **UAT-prep queries** (consumed by S03.12) — the `_log_summary` cross-tab emits per-(species_group, document_type, confidence) row counts. Locked by `test_main_real_artifacts_produce_expected_counts`. Two mixed-confidence patterns flagged for S03.12 UAT spot-check: (a) elk has 2 high + 110 medium (audit the 2 high HDs); (b) pronghorn has 30 high + 1 medium (audit the single medium HD's MIN-aggregation source row).
- [x] Working note `docs/planning/epics/E03-confidence-findings/S03.6.md` exists (87 LOC; cross-tab + mixed-confidence findings + empty "additional statewide candidates" + empty "free-prose non-NOTE content" sections; deletes at m1 tag per ADR-017 §6).
- [x] `ruff check`, `mypy` clean (10 source files post-S03.6)
- [x] Unit tests cover jurisdiction_code derivation (incl. statewide), SourceCitation construction (incl. correction case + supersedes from sources.yaml), confidence MIN aggregation, NOTE-line→additional_rules mapping, legal_description write-to-geometry round-trip — **52 tests in `test_load_regulation_records.py` across 6 classes** (`TestExtractNoteLines`, `TestBuildDeaRecords`, `TestBuildBearRecords`, `TestLegalDescriptionWrites`, `TestCountGuard`, `TestMain`). Suite total: **709 + 2 skipped** (+52 from S03.6).

**Closure note (closed 2026-05-15 via PR `c0c1b77` squash-merged to main):** Branch `feat/S03.6-regulation-record-ingestion`, 4 commits (base `39cd4e3`, tip `686728d`). **First E03 database-write story.** Final state: 436 regulation_record rows + 228 `geometry.legal_description` updates in one atomic transaction. **OQ1 resolved 2026-05-14** during implementation discovery: `regulation_record` has no `verbatim_rule` column (DDL `supabase/migrations/20260425000000_initial_schema.sql:36-49` + Pydantic `RegulationRecord` `ingestion/ingestion/lib/schema.py:221-238` both define an anchor entity with no such field). Option (c) selected — drop section text from `regulation_record` and let it decompose into S03.7's `season_definition.verbatim_rule` + `license_tag.verbatim_rule`; HD-wide `NOTE:` lines land in `regulation_record.additional_rules` via S03.6. Full rationale in `docs/open-questions.md` Q15. **OQ7 introduced**: row-count fail-loud guards (±30% band) — first pipeline story to do so; precedent for S03.7-S03.10. **Eight real-data findings baked in**: DEA species fan-out (`deer` → `mule_deer` + `whitetail`); Bear DB species_group is `bear`, not the artifact's `black_bear`; bear path uses `ConfidenceTier(...)` validation, not bare `cast(Confidence, ...)`; `_DEA_SPECIES_FANOUT` emit order locked by test; bear artifact `sources` and `rows` top-level keys need shape validation; DEA elk/mule_deer/whitetail + `hd_number="STATEWIDE"` is structural fail-loud; `NOTE:` regex hardened from `\s*` to `[ \t]*` to prevent cross-NOTE absorption; `MT-STATEWIDE-antelope` is the single confirmed statewide regulation_record in V1. **Seven new pitfalls in `.roughly/known-pitfalls.md`** under Conventions — Ingestion adapters (6) + Conventions — Pre-commit & secrets (1). **No ADRs created** — OQ1 is a refinement of ADR-008's decomposition story, not a new architectural commitment. **Recovery note (PR provenance):** S03.6 was accidentally pushed directly to main as 3 commits + 1 chore commit; recovery sequence carved a feature branch from the S03.6 tip, force-pushed main back to S03.5 close + chore replay, pushed feature branch, opened and squash-merged PR #36. Single-user repo, `--force-with-lease` for safety, no collateral.

**Deferred follow-ups (non-blocking; surface to downstream):**
- **S03.12 UAT spot-check candidates** (from `_log_summary` cross-tab): identify the 2 elk HDs with `confidence=high` and confirm strict extraction matched; identify the single pronghorn HD with `confidence=medium` and audit the source row that dragged MIN aggregation down. No HIGH→LOW or MEDIUM→LOW demotions surfaced; S03.4's per-row HIGH→MEDIUM demote for correction-touched bear rows passed through MIN aggregation unchanged (all 35 bear rows are medium).
- **Free-prose non-NOTE HD-wide content** in DEA: currently has no structured DB home. V1 Montana DEA expected empty-set (every HD-wide annotation begins with `NOTE:`), but S03.12 should spot-check whether any HD has prose between rows that doesn't begin with `NOTE:` — those would currently fall through. M2-deferred.

[^oq1]: **OQ1 resolution (2026-05-14):** During S03.6 implementation, the
    discovery report surfaced that `regulation_record` has no `verbatim_rule`
    column in the DDL (`supabase/migrations/20260425000000_initial_schema.sql`
    lines 36-49) or in the Pydantic `RegulationRecord` model
    (`ingestion/ingestion/lib/schema.py` lines 221-238). Option (c) — drop
    section-level text from `regulation_record` and let it decompose into S03.7's
    `season_definition.verbatim_rule` + `license_tag.verbatim_rule` — was
    selected. ADR-008's verbatim-preservation invariant is satisfied because
    every reg-bearing piece of source text is stored on the entity it describes.
    NOTE-style HD-wide lines are captured by S03.6 in `additional_rules`. The
    DEA artifact's full `verbatim_text` field remains in the JSON artifact
    (committed to repo) as a debug/audit aid. See `docs/open-questions.md` for
    the full rationale and `docs/planning/epics/E03-confidence-findings/S03.6.md`
    for the working note.

---

### S03.7: season_definition + license_tag + license_season ingestion (with A/B asymmetric coverage)

**As a** developer expressing Montana's per-HD season windows and the A/B license relationship pattern with explicit per-license season coverage
**I want** `season_definition` rows for each unique season window per HD, `license_tag` rows for each General/B variant, and `license_season` link rows expressing exactly which seasons each license covers
**So that** the milestone UAT criterion #2 ("A and B licenses both cross-referencing the appropriate seasons") is satisfied **without** the over-attribution failure mode the legacy schema had

**UAT: yes** — query HD 170 (Flathead River) elk and verify (a) the season_definition rows match the source DEA subsection's distinct windows (Archery Only, General, Heritage Muzzleloader, Late), (b) both A (General Elk License) and B (Elk B License: 170-00) license_tag rows exist, and (c) the `license_season` join shows asymmetric coverage: A covers Heritage Muzzleloader (B does not), and B covers Late (A does not).  Note: the original spec referenced HD 262 elk, but HD 262 only exists for deer in the live DEA artifact — substitution made during S03.7 implementation discovery.

**Context:**

This is the load-bearing entity-mapping story for the A/B license pattern. ADR-018 added the `license_season` link table to model per-license season coverage explicitly; this story populates it from S03.3's per-license `season_coverage` extraction artifact.

**Per-HD construction pattern:**

For each HD's DEA subsection:
1. Identify all unique season windows present across the HD's licenses (e.g., HD 170 elk: Archery Only, General, Heritage Muzzleloader, Late). This goes in `season_windows` from S03.3's artifact.
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

**`license_tag.draw_spec_key` left NULL by S03.7 — backfilled by S03.8:**

S03.7 does NOT populate `license_tag.draw_spec_key`. The schema permits NULL because `draw_spec_key` is a soft FK per ADR-012 (validated in application code, not DB). S03.8 backfills `draw_spec_key` for limited-draw license_tag rows after writing the corresponding `draw_spec` rows, via `UPDATE license_tag SET draw_spec_key = ? WHERE id = ?`. This breaks the chicken-and-egg between license_tag and draw_spec writes without violating any DB constraint, and keeps each story's load script focused on a single entity.

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

**Actual counts at S03.7 implementation (2026-05-15):** season_definition=978, license_tag=1225, license_season=3040, regulation_season=1385, regulation_license=1914.  Closure_predicate count: 20 (8 quota-closure BMUs × 2 fall seasons + 4 female-sub-quota BMUs × 1 spring season).

Order-of-magnitude verification against the extraction artifacts is part of the AC.

**Confidence per ADR-017:** child entities inherit confidence from the parent regulation_record; nothing written to `season_definition`, `license_tag`, or `license_season`.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md).

**Depends on:** S03.0 (`license_season` table), S03.6 (regulation_record FK target).

**Acceptance Criteria:**

- [x] `ingestion/states/montana/load_seasons_and_licenses.py` exists (~1180 LOC); deterministic load order; single-transaction atomic write of all 5 entity/link tables. Five new DB helpers added to `ingestion/ingestion/lib/db.py`: `upsert_season_definition`, `upsert_license_tag` (with `CASE WHEN %s::int IS NULL THEN NULL ELSE int4range(%s, %s, '[]') END` for the quota_range column), `write_license_season`, `write_regulation_season`, `write_regulation_license` (all no-commit; caller-controlled transaction).
- [x] **978 `season_definition` rows written** (DEA 874 + bear 104 = 35 BMUs × 3 seasons - 1 missing archery_only for BMU 309). Per-HD unique-window dedup operates at the entity-table layer via UPSERT collapse; emit-time bear total is 104, not 105.
- [x] **1225 `license_tag` rows written** (DEA 1190 + bear 35); multiple license_tag rows per HD where DEA shows A + B variants. After UPSERT collapse, 790 unique license_tag ids across the live artifact (was 784 before the cubic-P1 slug fix; 6 cross-listing collisions resolved by including license-type prefix in `_license_code_slug`).
- [x] **`license_tag.draw_spec_key` is NULL on every row** — `_DEA_LICENSE_KIND_HEURISTIC` returns rows with `draw_spec_key=None`; backfill is S03.8's responsibility per ADR-012. Locked by `test_dea_license_tags_have_draw_spec_key_none` + `test_draw_spec_key_is_none` (bear).
- [x] **3040 `license_season` rows written per S03.3's `season_coverage` truth values** (DEA 2936 + bear 104). Per-license season selection explicit. **Drift guard** added in cubic-P2 commit `20c0f34`: three DEA builders gate iteration on `season_coverage` truth values (not `season_windows` keys alone) with WARN log on disagreement — defensive against S03.3 drift.
- [x] **1385 `regulation_season` + 1914 `regulation_license` link rows written** (DEA fan-out: artifact `deer` → DB `mule_deer` + `whitetail` produces two `regulation_license` rows pointing at the same physical `license_tag.id`).
- [x] Bear `season_definition` rows with `closure_predicate` jsonb populated: **20 closure_predicate rows** = 8 quota-closure BMUs × 2 fall seasons (general + archery_only) + 4 female-sub-quota BMUs × 1 spring season. **8 quota-closure BMUs** (411, 420, 440, 450, 510, 520, 600, 700 — BMU 530 absent per S03.4 revised count) + **4 female-sub-quota BMUs** (300, 301, 319, 580). Temporal anchors preserved in `verbatim_rule` only per S03.4 deferred-items policy.
- [x] Statewide antelope `900-20` license_tag row exists with `kind='statewide'`; `verbatim_rule` carries section-scoped verbatim_text per OQ-S7-9 fallback chain (per-cell precision deferred to M2); no `draw_spec_key`.
- [x] `quota_range` uses `[]` inclusive bounds via the `int4range(%s, %s, '[]')` CASE expression in `upsert_license_tag`; bear path emits NULL (no range, just `fall_quota.count`); DEA path uses `_parse_quota_range` to strip comma thousands ("1-7,500" → (1, 7500)).
- [x] `season_definition.weapon_type` populated directly from S03.3's `season_windows[<key>].weapon_type_override` (no name-based string matching). For bear path: `"archery"` when `season_key == "archery-only"`, else NULL.
- [x] **UAT (M1 success criterion 2) — PASSED at the data layer.** **Spec change accepted (OQ-S7-3):** spec originally specified HD 262 elk; live extraction showed HD 262 lacked the asymmetric pattern, so HD 170 (Flathead River) elk was substituted (spec lines 637 + 707 updated by the implementation agent). Asymmetry confirmed: A (General Elk License) covers `{archery_only, general, heritage_muzzleloader}`, B (Elk B License: 170-00) covers `{archery_only, general, late}`. A-only = `{heritage_muzzleloader}`; B-only = `{late}`. Locked by `TestBuildDeaLinkRows::test_license_season_asymmetric_coverage_m1_criterion`. **End-to-end SQL verification deferred to S03.12** post-jurisdiction_binding (canned query in S03.7 working note).
- [x] License/season patterns that don't fit the model are flagged via operational definition (per-row season-window divergence within a section emits WARN log per S03.3's "Elk B License: 699-01" closure precedent; first-occurrence-wins at season_definition level).
- [x] UPSERT idempotency confirmed (UPSERT on entity tables; ON CONFLICT DO NOTHING on link tables).
- [x] Working note `docs/planning/epics/E03-confidence-findings/S03.7.md` records A/B-pattern edge cases + OQ-S7-1 through OQ-S7-11 decisions + cubic-fix decisions (deletes at m1 tag per ADR-017 §6).
- [x] `ruff check`, `mypy` clean — initial agent verification missed 8 mypy errors (loop-variable type pollution across 3 sequential loops; `key` variable shadowing across two `dict[tuple[...]]` types; `weapon_type` `str | None` not narrowed to `WeaponType | None`). **PM applied surgical fixes** during closure verification (added `WeaponType` import; annotated `weapon_type` local; renamed `key` → `lt_key`; renamed `link` → `ls_link`/`rs_link`/`rl_link`). All 8 errors resolved; 832 tests + 2 skipped still pass.
- [x] **123 tests in `test_load_seasons_and_licenses.py`** across 14 test classes including: `test_license_season_asymmetric_coverage_m1_criterion` (M1 criterion #2 regression guard), `test_season_coverage_false_drift_skipped_across_three_builders` (drift-guard lock), `test_license_tag_id_disambiguates_same_numeric_across_species_in_section` (cross-license collision lock), `test_sex_threshold_closure_locks_4_bmus`, parametrized `test_*_quota_closure_bmus_locked` over all 8 quota-closure BMUs + BMU 530 absence. Suite total: **832 passed + 2 skipped** (+121 net from S03.7 with the 2 later cubic-fix tests; was 709+2 pre-S03.7).

**Closure note (closed 2026-05-16 via PR `20db0fc` squash-merged to main):** Branch `feat/S03.7-season-definition-license-tag-ingestion`, 5 commits past S03.6 close. **Load-bearing UAT-yes story for M1 success criterion #2** ("A and B licenses both cross-referencing the appropriate seasons"). Final state: **978 season_definition + 1225 license_tag + 3040 license_season + 1385 regulation_season + 1914 regulation_license = 8542 total rows in one atomic transaction**, plus **20 closure_predicate jsonb values** on bear season_definition rows. **Inherits OQ7 row-count guard precedent from S03.6** — all five guards fire BEFORE `db.connect()` with ±30% bands: season_definition `[684, 1271]`, license_tag `[857, 1592]`, license_season `[2128, 3952]`, regulation_season `[969, 1800]`, regulation_license `[1339, 2488]`. **Eleven decisions baked in (OQ-S7-1 through OQ-S7-11)** + 2 cubic-fix decisions: (1/2) species granularity — license_tag.species + season_definition.id use ARTIFACT-level labels (`deer`/`elk`/`antelope`/`bear`); DEA `deer` fan-out (→ `mule_deer` + `whitetail`) happens ONLY at the link-table layer; two `regulation_license` rows for deer point to the same physical `license_tag.id`; (3) UAT HD shift 262 → 170 per OQ-S7-3; (4) season name rendering via `_SEASON_NAME_BY_KEY` (`archery_only` → `"Archery Only"`, etc.); (5/6) bear closure_predicate attachment — `sex_threshold` → spring_season for the 4 female-sub-quota BMUs (37% female, agency_website notification, mandatory_reporting observation); `quota_threshold` → general_season AND archery_only_season for the 8 quota-closure BMUs; (7) license_tag.kind 5-ordered-branch heuristic with fail-loud `else` (profiled clean across full 1190-row artifact); (8) window parser handles dotless / dotted / bear-newline / "Sept" 4-letter / year-wrap; (9) verbatim_rule fallback chain prefers General/A-license extras, falls through to section verbatim_text; (10/10b) bear → NULL quota_range, DEA → parsed-int range with comma-thousands stripped, residency default `"both"`; (11) purchase_url evergreen `https://fwp.mt.gov/hunt/licensing/buy`. **Cubic fix #1 (P2 commit `20c0f34`):** DEA builders gate on `season_coverage` truth values (not `season_windows` keys alone) — defensive against S03.3 drift. **Cubic fix #2 (P1 commit `df1b6b0`):** `_license_code_slug` includes lowercased license-type prefix (`elk-b-262-50`, `deer-b-262-50`, `antelope-900-20`, `deer-permit-262-51`) — without prefix, 6 deer sections cross-list Elk B licenses with matching numeric codes → collision; HDs 410/455/555/630/700 affected. **PM-applied mypy fixes during closure verification (this commit):** 8 type errors in `load_seasons_and_licenses.py` — loop-variable type pollution across the 3 final write loops (renamed `link` → `ls_link`/`rs_link`/`rl_link`); `key` variable shadowing in `_log_summary` (renamed to `lt_key`); `weapon_type` `str | None` not narrowed to `WeaponType | None` (added type annotation + import). Agent's "ruff + mypy clean" claim was wrong; **discipline reminder filed**: every adapter closure should re-run `mypy ingestion/lib/ states/<state>/<module>.py` before reporting clean. **Five new pitfalls** in `.roughly/known-pitfalls.md` (DEA "Sept" 4-letter abbreviation; license_code kind heuristic full-artifact profiling discipline; Pydantic frozen+extra="forbid" required-field enumeration; duplicate-license_code-within-section no-pre-dedupe; cross-license slug-prefix collision). **No ADRs created** — implementation refines ADR-008 (verbatim discipline — section-scoped fallback), ADR-010 (decomposed entities — first multi-link adapter), ADR-012 (soft FK — draw_spec_key=NULL), ADR-017 (confidence inheritance — child entities carry no confidence column), ADR-018 (license_season link table operationalized).

**Deferred follow-ups (non-blocking; surface to downstream / M2):**
- **Q16 in `docs/open-questions.md`** — species granularity revisit. If MT (or any state) ever ships a species-specific license (e.g., mule-deer-only with no whitetail), V1's shared `license_tag` wouldn't fit. M2 decides among per-species variants, `valid_species: list[str]` column, or hybrid.
- **Per-cell `verbatim_rule` precision** — V1 uses section-scoped verbatim_text for `license_tag.verbatim_rule`. Defer until a downstream consumer demands cell-precision.
- **Cross-listed elk licenses in deer sections** — `Elk B License: 005-00` appearing in (`deer`, `555`) AND (`elk`, `502/515/525/...`) produces multiple `license_tag` rows for the same physical license. Acceptable for V1 (per-HD instance model); M2 could de-duplicate to one canonical `license_tag`.
- **S03.12 UAT SQL spot-check** (canned in `S03.7.md`): query HD 170 elk's `license_season` rows to demonstrate the A-vs-B asymmetric coverage end-to-end, post-jurisdiction_binding.

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

**Depends on:** S03.7 (limited-draw `license_tag` rows exist with `draw_spec_key=NULL` ready for backfill — see S03.7 § "`license_tag.draw_spec_key` left NULL by S03.7 — backfilled by S03.8" for the handoff contract).

**Acceptance Criteria:**

- [x] `ingestion/states/montana/load_draw_specs.py` exists (~720 LOC, state-agnostic-clean per AST guard); deterministic load order; **three-phase atomic transaction pattern inherited from S03.6**: build everything → row-count guards pre-`db.connect()` → open conn / phase loops / commit / rollback-on-error / close.
- [x] **388 `draw_spec` rows written** for every limited-draw `license_tag` from S03.7 except `900-20`. (After UPSERT collapse via `(state, hunt_code, year)` composite PK: **278 unique `draw_spec` rows**; the gap is cross-listed licenses where the same hunt_code appears under multiple HD sections.)
- [x] `pools` AllocationPool array shares sum to 1.0 per row (application-code validation enforced).
- [x] **S03.8 backfilled `license_tag.draw_spec_key`** for all 388 limited-draw license_tags via `UPDATE license_tag SET draw_spec_key = ? WHERE id = ?` AFTER the `draw_spec` rows were written. Loader idempotent against re-runs; locked by `update_license_tag_draw_spec_key` fail-loud helper (RuntimeError on `cur.rowcount == 0`, mirroring `db.update_legal_description` from S03.6).
- [x] `license_tag.draw_spec_key` jsonb correctly references draw_spec composite PK for every limited-draw row (cross-listing aware: multiple license_tag rows may resolve to the same draw_spec).
- [x] **`900-20` has NO `draw_spec` row;** `license_tag.draw_spec_key` is NULL; `verbatim_rule` carries the full "first and only choice" text from S03.7; entry exists in `docs/planning/epics/E03-deferred-items/draw-mechanics.md` documenting the deferral (now one of 3 entries in that file).
- [x] `parameters` field is `null` on every draw_spec row written (per Q12 deferral).
- [x] If extraction surfaces a draw mechanic that would require `parameters`: **flag-and-defer**. Two new entries added during S03.8 to `draw-mechanics.md`: (a) MT NR-cap (MCA Title 87-2-106) 10% structure not modeled; (b) per-HD allocation caps (HD 210 case where quota=300 in home HD vs quota=200 in cross-listings — real per-HD-cap semantic, not extraction defect). The HD 210 case opens **Q17** in `docs/open-questions.md` (M2 ADR-candidate) and is handled in V1 via the new `_KNOWN_CROSS_LISTING_OVERRIDES` dispatch table with documented rationale + page citations.
- [x] **S03.7 license_tag.kind heuristic amended during S03.8** to fix a real-PDF defect: 162 over-the-counter B Licenses were previously mis-labeled `limited_draw` because the heuristic only inspected `license_code`. Amended to also inspect `apply_by` cross-row AND cross-HD; OTC discriminator is `apply_by="OTC:\nJun 15"`-style cells. Post-amendment DEA subset breakdown: **790 unique license_tag identities classified as 388 `limited_draw` / 162 `over_the_counter` / 239 `general` / 1 `statewide`** (total rows unchanged from S03.7's 1190; only kind values shift). Without this fix, S03.8 would have written 550 `draw_spec` rows (388 + 162) instead of 388 — silent over-write of `draw_spec` rows for OTC-classified licenses.
- [x] UPSERT idempotency confirmed.
- [x] `ruff check`, `mypy` clean (per-file verification: `ingestion/lib/` 7 source files; `load_draw_specs.py` clean; `load_seasons_and_licenses.py` still clean post-S03.7 mypy fixes).
- [x] Unit tests cover pool-share-sum validation, residency-cap construction, license_tag↔draw_spec round-trip, `900-20` skip behavior. **+78 tests from S03.8** (suite total: **910 passed + 2 skipped**; was 832+2 pre-S03.8). New testing patterns introduced: `TestNoLibImports` AST guard for state-agnostic-clean enforcement; `caplog`-based WARN-log assertion; real-artifact regression locks against pinned counts.

**Closure note (closed 2026-05-19 via PR `323836f` squash-merged to main):** Branch `feat/S03.8-draw-spec-ingestion`, 8 commits (`5b48936..d733482`). Final state: **388 draw_spec rows (278 unique after UPSERT collapse) + 388 license_tag.draw_spec_key backfills** in one atomic three-phase transaction. **S03.7 license_tag.kind heuristic amended in the same PR**: the `_DEA_LICENSE_KIND_HEURISTIC` only inspected `license_code` per OQ-S7-7, but real-PDF analysis surfaced 162 over-the-counter B Licenses (HDs across the booklet) that carry `apply_by="OTC:\nJun 15"`-style cells — a load-bearing OTC discriminator that S03.7 missed. Amendment inspects `apply_by` cross-row AND cross-HD; result is 388 `limited_draw` (down from S03.7's 550) + 162 `over_the_counter` (new bucket) + 239 `general` + 1 `statewide` = 790 unique DEA license_tag identities (counts unchanged; classification corrected). Without this amendment, S03.8 would have over-written `draw_spec` rows for OTC-classified licenses. **Inherits OQ7 row-count guard precedent**: 1 guard on `draw_spec` write count with ±30% band; both guards fire BEFORE `db.connect()`. **Three new S03.8 patterns established for S03.9+**: (1) **Cross-listing consistency validator** — when multiple constituent rows share an entity PK, validate structural-field agreement; use `"key" in override_dict` for presence detection (NOT `.get(...) is None` which collapses key-absent with value-None); (2) **Defensive safety-net lookup** — `_DEA_DEADLINE_LOOKUP` is the prototype; for fields that COULD be missing from per-row extraction but live in front-matter, build an adapter-level fallback lookup whose runtime firing must raise (not WARN) so CI catches drift; place the check AFTER the builder + BEFORE the dry-run short-circuit; (3) **Override-dispatch table** — `_KNOWN_CROSS_LISTING_OVERRIDES` is the prototype; for known-irreconcilable real-PDF inconsistencies, document them in a state-adapter-owned dict with rationale strings + page citations; fail loud on undocumented conflicts. **Three real-PDF findings surfaced during S03.8 (informational for S03.9+)**: (a) DEA front-matter (pp. 5/9/10/11) carries authoritative species×license-type metadata not repeated per-row in species sections — per-row null is sometimes intentional; (b) cross-listed licenses (same license_code in multiple HD sections) can carry STRUCTURALLY-CONFLICTING data per real per-HD-cap semantics (HD 210: quota=300 home, quota=200 cross-listings); (c) DEA tables use `apply_by="OTC:\nJun 15"` as a load-bearing OTC discriminator that's easy to miss if heuristic only inspects `license_code`. **Q17 opened in `docs/open-questions.md`**: how should per-HD allocation caps be modeled in `draw_spec`? — M2 ADR-candidate; deferred via `_KNOWN_CROSS_LISTING_OVERRIDES` for V1; surfaced by the HD 210 cross-listing pattern. **Four new pitfalls** in `.roughly/known-pitfalls.md` (all referenced from CLAUDE.md § "Ingestion adapter pattern"): DEA cross-listed B Licenses can carry CONFLICTING structural fields across HD sections; DEA license_tag.kind requires inspecting `apply_by`, not just `license_code`; DEA front-matter carries authoritative deadlines when per-row `apply_by` is genuinely null; subagent-authored docs can reference stale task IDs from earlier plan drafts. **No ADRs created** — implementation refines ADR-010 (decomposed entities), ADR-012 (sibling entity referenced from license_tag by FK), ADR-017 (confidence inheritance unchanged), ADR-018 (license_season + draw_spec composite-PK references operationalized). Working note at `docs/planning/epics/E03-confidence-findings/S03.8.md` (~280 lines; deletes at m1 tag per ADR-017 §6).

**Deferred follow-ups (non-blocking; M2):**
- **Q17 in `docs/open-questions.md`** — per-HD allocation caps in `draw_spec`. V1 handles via `_KNOWN_CROSS_LISTING_OVERRIDES` override table; M2 ADR-candidate.
- **`draw-mechanics.md` now has 3 entries** (deferred-items survives past m1): (a) 900-20 "first and only choice" ordering semantic; (b) MT NR-cap (MCA Title 87-2-106) 10% structure not modeled; (c) per-HD allocation caps (HD 210 case).
- **Spec discrepancy at line 744** (informational): says `hunt_code` uses `262-50` numeric stub, but actual `license_code` and S03.8's `draw_spec.hunt_code` use full prefixed strings ("Deer B License: 262-50"). The spec example is illustrative; the discipline is "match `license_tag.license_code` verbatim." S03.9's `regulation_reporting.regulation_record_id` reference is unambiguous (composite-PK joins), so this won't bite. Worth telling future spec readers.

---

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
3. **Mandatory harvest reporting for black bear** (statewide): 48-hour personal harvest report. Carried into S03.9 as the STATEWIDE `harvest_report` row from the bear booklet. **Note:** the per-source authoritative list of mandatory-report species in Montana (per `fwp.mt.gov/hunt/regulations`) is black bear, wolf, marten, and migratory swans — deer / elk / pronghorn / mountain lion / moose / sheep / goat have no mandatory statewide reporting. The FWP Harvest Survey (DEA p. 31) is a voluntary telephone sampling program, not a `reporting_obligation`.
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

- [x] `ingestion/states/montana/load_reporting_obligations.py` exists (~600 LOC, state-agnostic-clean per AST guard); deterministic load order; **three-phase atomic transaction pattern inherited from S03.6/S03.7/S03.8**: build everything → row-count guards pre-`db.connect()` → open conn / phase loops / commit / rollback-on-error / close.
- [x] **1 STATEWIDE bear `harvest_report` row** sourced from `black-bear-2026.json` `reporting_obligations` list (the bear booklet's only statewide mandatory-reporting obligation; deer/elk/pronghorn have no mandatory statewide reporting per the FWP authoritative list at `fwp.mt.gov/hunt/regulations`). **Scope-reshape (2026-05-19 three-blocker probe):** (a) **CWD sampling** moved to Q18 deferral — verbatim text already in `regulation_record.additional_rules` via S03.6 (license-keyed in DEA artifact, not zone-keyed: HD 103's `Deer Permit: 103-50` carries the sampling rule but isn't inside the Libby CWD-zone overlap); see `docs/planning/epics/E03-deferred-items/cwd-sampling-modeling.md`. (b) **Bear ID coursework** carved out to **S03.6.1** (wrong target-table — pre-purchase licensing prerequisite belongs in `regulation_record.additional_rules` keyed by a new `MT-STATEWIDE-bear` anchor, mirroring `MT-STATEWIDE-antelope`'s pattern; NOT a post-harvest/in-season `reporting_obligation`). (c) **Epic line 807 corrected at S03.9 close** to remove the "general reporting obligation for all V1 species" assumption — bear is the only V1 species with a statewide mandatory harvest report.
- [x] Region-specific bear inspection: **3 rows total** — R1 split into 2 (48-hour report + 10-day teeth) per the table above; R2-7 as 1 row per the table above. (Bear booklet's `reporting_obligations` list provided all 3 candidates from S03.4's prior extraction; no upstream extraction changes in S03.9.)
- [x] Each R1 row carries `verbatim_rule` per the source-sentence-per-row split documented in the load script (each `ReportingObligation` row gets its own verbatim from the artifact entry; byte-faithful preservation per ADR-008; locked by `TestBuildReportingObligations::test_verbatim_rule_preserved_byte_faithful`).
- [x] `regulation_reporting` link table populated for every (regulation_record, reporting_obligation) pair (**70 link rows**: 35 STATEWIDE + 14 R1 + 21 R2-7; R1 BMU set `{100,101,103,104,110,120,121,122,123,130,140,141,150,170}` locked by `TestBuildRegulationReportingLinks::test_r1_bmu_set_locked`).
- [ ] ~~CWD-sampling obligation links only to regulation_records whose HD overlaps a CWD zone~~ — **DEFERRED per Q18** (`docs/planning/epics/E03-deferred-items/cwd-sampling-modeling.md`). The zone-keyed `geometry-overlays.json` join would miss the license-keyed `Deer Permit: 103-50` case; rules are already in `regulation_record.additional_rules` from S03.6. V1 ships 0 CWD-sampling `reporting_obligation` rows.
- [x] UPSERT idempotency confirmed (UPSERT on `reporting_obligation`; ON CONFLICT DO NOTHING on `regulation_reporting`; locked by `TestUpsertReportingObligation` + `TestWriteRegulationReporting` in test_db.py).
- [x] Working note `docs/planning/epics/E03-confidence-findings/S03.9.md` records the per-BMU `hd_region` mapping used for the R1/R2-7 split (sourced from the bear artifact's `rows[*].hd_region` field, populated by S03.4 from the bear PDF regional map; no DEA-page-5 derivation needed since bear regions are per-BMU, not HD-first-digit).
- [x] `ruff check`, `mypy` clean (per-file verification: `ingestion/lib/` 8 source files including new `db.py` helpers; `load_reporting_obligations.py` clean; full test suite + tests modules clean).
- [x] Unit tests cover: applies_to_regions array construction (STATEWIDE `None`, R1 `["R1"]`, R2-7 6-element list in exact order); R1-split-row generation (2 rows: `harvest_report` + `tooth_submission`); R2-7 row generation (1 row: `hide_skull_presentation`); link distribution 35+14+21; count guards `[2, 4]` and `[49, 91]`; main() lifecycle (dry-run, pre-`db.connect()` guard abort, rollback-on-failure, real-artifact smoke). **+71 tests net from S03.9** across 6 test classes (suite total: **981 passed + 2 skipped**; was 910+2 pre-S03.9; +53 at the main commit `136454d` + 18 more from 7 cubic-review rounds before merge). CWD-overlap selection AC dropped per the scope reshape above.

**Closure note (closed 2026-05-21; PR `195ac8b` squash-merged to main from `feat/S03.9-reporting-obligation-ingestion`):** Pre-squash branch carried 8 commits including the main implementation (`136454d` — 13 files, +2516/−9) plus 7 cubic-review fix-up rounds adding ~250 LOC + 18 tests + 1 new open question. Final state: **3 reporting_obligation rows + 70 regulation_reporting link rows** written via `ingestion/.venv/bin/python ingestion/states/montana/load_reporting_obligations.py` (dry-run verified; live-DB write is operator-driven, mirrors S03.6/S03.7/S03.8 pattern). **Three originally-spec'd row types carved out or deferred via the source-audit probe** (see scope-reshape note in AC #2 above). **Six review-triad findings applied during Stage 6** (1 HIGH duplicate-source_id guard; 1 MEDIUM diagnostic KeyError; 4 P2 incl. `_LOGGER` Final annotation, `_RowSpec` Literal narrowing, test_db fixtures aligned to production, `supersedes` read from artifact). **Seven cubic-review rounds during PR review** added the post-Stage-6 fixes: (R1) HIGH duplicate-id guard + state-code FK + convention drift; (R2) epic AC staleness + plan-doc clarity; (R3) id text-PK UPSERT slug-drift (opens Q19); (R4) bare key access on sources entries; (R5) bare key access + isinstance-type-check on entry lists; (R6) exact-count check contradicts OQ7 band (removed — OQ7 is count authority, builds are pure data construction); (R7) round-6 regression where duplicate IDs slipped through (re-introduced the guarantee via structural invariant). **Four new pitfalls in `.roughly/known-pitfalls.md`** under Conventions — Ingestion adapters: (a) E03 story discovery must source-audit upstream artifacts for every epic-required row type before planning (pattern bit twice — S03.8 B5, S03.9 three-blocker); (b) `reporting_obligation.kind` semantic boundary — post-harvest/in-season only; pre-purchase prerequisites belong in `regulation_record.additional_rules`; (c) `submission_method` interpretation for multi-modal source text — pick the headlined modality; verbatim_rule preserves the full source faithfully; (d) `id text`-PK UPSERTs carry a latent slug-drift risk when slug-encoded fields can be UPDATEd — local module-load drift guard added as belt-and-suspenders; project-wide fix is Q19. **Two new open questions** in `docs/open-questions.md`: **Q18** (CWD sampling target-table modeling; M2 ADR candidate when Colorado lands; defer-reason: zone-keyed `geometry-overlays.json` join would miss the license-keyed `Deer Permit: 103-50` case); **Q19** (id text-PK UPSERT slug-drift; affects 3 helpers in `db.py` — `_UPSERT_SEASON_DEFINITION_SQL`, `_UPSERT_LICENSE_TAG_SQL`, `_UPSERT_REPORTING_OBLIGATION_SQL`; **pre-M2 blocker**: must land in a single PR before first year-over-year re-ingestion run; ADR required at resolution; leading option is derive-and-assert generalizing S03.9's local pattern). **Three new patterns established for S03.6.1/S03.10+**: (1) **OQ7 row-count guard is the canonical count authority** — in-builder exact-count checks contradict band semantics; build functions are pure data construction; bands live in `main()`. (2) **Defensive fail-loud surface for artifact-list iterations** — `isinstance(element, dict)` before key access; `try/except KeyError → raise RuntimeError` with per-element diagnostics (index + keys-present); duplicate-id guard if list could produce composite-PK collisions. (3) **`reporting_obligation.kind` semantic boundary** — post-harvest/in-season only; pre-purchase prerequisites (Bear ID Test, hunter education) go in `regulation_record.additional_rules` via STATEWIDE anchors. **No ADRs created** — implementation refines ADR-001 (no invented data), ADR-008 (verbatim discipline — empty cleanup-rules section), ADR-010 (decomposed entities + link-table pattern), ADR-017 (confidence inheritance — no confidence column on `reporting_obligation`). Working note at `docs/planning/epics/E03-confidence-findings/S03.9.md` (deletes at m1 tag per ADR-017 §6). **`cwd-sampling-modeling.md` added to `docs/planning/epics/E03-deferred-items/`** (survives past m1 per Q18). **Spec change accepted: epic line 807 corrected** — "general reporting obligation for all V1 species" assumption removed; bear is the only V1 species with a statewide mandatory harvest report (FWP authoritative list at `fwp.mt.gov/hunt/regulations`: bear/wolf/marten/swans).

**Deferred follow-ups (non-blocking; carried into S03.6.1/S03.10/M2):**
- **S03.6.1 carved out (queued post-S03.9 close; see § S03.6.1 below)** — MT-STATEWIDE-bear anchor with Bear ID Test. Adds 1 new RegulationRecord row; brings count 436 → 437 (update `_REGULATION_RECORD_COUNT_GUARD` band). Coordination question for S03.10: does S03.6.1's regulation_record need a corresponding `jurisdiction_binding` to `MT-STATEWIDE-geom`? Likely yes (mirrors antelope pattern); decide before S03.10 ships or include in S03.6.1.
- **Q18 (M2)**: CWD sampling target-table modeling. Defer to M2 when Colorado lands (second CWD-state forces the architectural decision). `cwd-sampling-modeling.md` is the working artifact.
- **Q19 (pre-M2 blocker)**: id text-PK UPSERT drift guard project-wide fix. Affects 3 helpers in `db.py`. Must land in a single PR before first year-over-year re-ingestion. ADR required at resolution.
- **CLAUDE.md test-count baseline drift**: the 7 cubic-review rounds added 18 tests after the main commit; baseline will read 981 in the S03.9 PM-closure commit (this commit).

---

### S03.6.1: MT-STATEWIDE-bear anchor with Bear ID Test + jurisdiction_binding to MT-STATEWIDE-geom (queued post-S03.9)

**Status:** queued post-S03.9 close; do not interleave. Carved out of S03.9 scope 2026-05-19 after Probe 1 (Bear ID coursework source-audit) showed the verbatim text is on page 2 of the bear booklet but `reporting_obligation` is the wrong target table — Bear ID Test is a **pre-purchase licensing prerequisite**, not a post-harvest or in-season duty. Scope expanded 2026-05-21 (PM decision) to include the corresponding `jurisdiction_binding` row to `MT-STATEWIDE-geom`, so the statewide-anchor entity + binding land together in one atomic story rather than splitting the binding into S03.10.

**As a** developer recording Montana's pre-purchase licensing prerequisites for black bear
**I want** an `MT-STATEWIDE-bear` `regulation_record` carrying the Bear Identification Test requirement in `additional_rules`, plus the corresponding `jurisdiction_binding` row tying it to `MT-STATEWIDE-geom` with `role='primary_unit'`
**So that** the statewide-anchor entity is fully bound at story close (no orphan regulation_record waiting for S03.10), the rule lives with the regulation_record decomposed-entity story (not as a synthetic `reporting_obligation` that misrepresents its semantics), and S03.10 inherits a tested `db.upsert_jurisdiction_binding` helper from this story

**Pattern reference:** mirrors `MT-STATEWIDE-antelope` (S03.6 STATEWIDE anchor for DEA `900-20`). Pattern extension: antelope's anchor has populated `additional_rules` already (2 NOTE entries from in-section NOTE-prefixed lines via `_extract_note_lines`, confirmed 2026-05-20 pre-discovery verification). MT-STATEWIDE-bear's data shape differs — the Bear ID Test rule is page-2 right-column PROSE (not NOTE-prefixed), so a new extraction path is needed. Target-table pattern identical; extraction path novel. The antelope binding to `MT-STATEWIDE-geom` does NOT yet exist (S03.10 will derive it via overlay-fixture generation); S03.6.1's bear binding intentionally lands earlier to keep the bear anchor self-contained. Surface as a pattern extension in S03.6.1 discovery, not a pure replay.

**Verbatim text** (from Probe 1, 2026-05-19, `mt-fwp-black-bear-2026-booklet-2026-04-27.pdf` p. 2 right column under "Obtain a License"):

> A hunter may purchase only one Black Bear License per year. A free Black Bear Identification Test Certificate is required to obtain a license. A hunter must take and pass a "Black Bear Identification test" before purchasing a Black Bear Hunting license. A hunter must present a certificate of completion issued by FWP at the time of purchase. The test is available online at: fwp.mt.gov/hunt/education/bear-identification

**Upstream change (extraction):** Narrow amendment to `ingestion/states/montana/extract_black_bear.py` adding a page-2 right-column bbox + 2 regex anchors for the Bear ID Test paragraph. Page 2 is currently outside the scanned region (`_extract_reporting_obligations` is hard-scoped to `_CLOSURE_PROSE_PAGE = 7` right-column only — confirmed by Probe 1, 2026-05-19). The output artifact gets a new top-level field (e.g., `statewide_rules: list[StatewideRuleCandidate]` — exact shape part of S03.6.1's discovery); do NOT add a 4th entry to `reporting_obligations` since the target table is regulation_record.

**Adapter change part 1 — `regulation_record` (S03.6 amendment):** Update `ingestion/states/montana/load_regulation_records.py` to recognize the new artifact field and emit one new `RegulationRecord` row with:

- `state="US-MT"` (per the DDL state-code convention; not `"MT"` — see S03.9 cubic-review round 2)
- `license_year=2026`
- `schema_version=2`
- `jurisdiction_code="MT-STATEWIDE-bear"`
- `species_group="bear"`
- `additional_rules` containing one `Rule` entry derived from the Bear ID Test verbatim text (`Rule.kind`-equivalent value to be confirmed during S03.6.1 discovery; pattern reference is S03.6's NOTE-line `Rule` construction)
- `source` jsonb `SourceCitation` referencing `mt-fwp-black-bear-2026-booklet` at page 2 (`page_reference` collapsed via `pdf.page_reference_to_str`)
- `confidence="medium"` (heading-anchored prose per ADR-017's tier definitions; matches the bear booklet's pre-existing medium-confidence corpus per S03.4/S03.6 closure notes)

**Adapter change part 2 — `jurisdiction_binding` (new helper + new row, same atomic transaction):**

1. **Introduce `db.upsert_jurisdiction_binding(conn, binding)` helper** in `ingestion/ingestion/lib/db.py` — no-commit, UPSERT by `id` text PK, JSON-serializes `source` via the existing `Json(...)` jsonb convention used by `upsert_regulation_record`. S03.10 reuses this helper for the broader overlay-derived binding generation; introducing it here mirrors the S03.6 pattern of introducing `update_legal_description` ahead of its broader S03.8 reuse.
2. **Build one `JurisdictionBinding` row** in `load_regulation_records.py` immediately after building the `MT-STATEWIDE-bear` regulation_record:
   - `id`: deterministic encoding of `(regulation_record composite PK, geometry_id, role)`. **Recommended format:** `f"{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"` → for V1 bear: `"US-MT-MT-STATEWIDE-bear-bear-2026-primary_unit-MT-STATEWIDE-geom"`. Exact format part of S03.6.1 discovery; lock by test. **Constraint**: encoding MUST be deterministic + reproducible across re-runs (UPSERT-by-id depends on it).
   - `regulation_record_state="US-MT"`, `regulation_record_jurisdiction_code="MT-STATEWIDE-bear"`, `regulation_record_species_group="bear"`, `regulation_record_license_year=2026` (composite-FK reference)
   - `geometry_id="MT-STATEWIDE-geom"` (created by S03.0 per ADR-018 §3; existing row in `geometry` table)
   - `role="primary_unit"` (matches what S03.10 would have derived for a statewide-anchor → statewide-geometry binding per ADR-018 §3)
   - `verbatim_rule=None` (nullable per DDL line 207; null = no binding-specific rule text, since the rule text lives on the `regulation_record`)
   - `source`: same `SourceCitation` as the regulation_record
3. **Write both rows in the same `with db.connect() as conn:` block** — regulation_record + jurisdiction_binding commit atomically or roll back together. The existing S03.6 transaction structure extends cleanly; no new transaction shape needed.

**Idempotency:** rerunning the loader is a no-op for both writes (UPSERT-by-PK on regulation_record; UPSERT-by-id on jurisdiction_binding). S03.10's overlay-derived binding generation will independently arrive at the same `MT-STATEWIDE-bear → MT-STATEWIDE-geom` binding row; the UPSERT-by-id means S03.10's re-write is also a no-op against this row (identical content). Document this overlap in S03.10's working note when it ships.

**Row-count impact:**
- `regulation_record`: 436 → **437**. Update `_REGULATION_RECORD_COUNT_GUARD` band to `[int(437 × 0.70), int(437 × 1.30)] = [305, 568]` (was `[305, 566]` per current ±30% with 436 baseline; tiny shift).
- `jurisdiction_binding`: 0 → **1** (first binding row in the table). Introduce a new `_JURISDICTION_BINDING_COUNT_GUARD` band sized for the single-row write expected from S03.6.1 alone (e.g., exact-match band `[1, 1]` since this story writes exactly one binding; S03.10 will broaden the band when it ships).

**Depends on:**
- S03.0 (`MT-STATEWIDE-geom` row must exist in the `geometry` table — confirmed present per S03.0 closure note 2026-05-04)
- S03.6 (already merged; `load_regulation_records.py` is the adapter being amended)
- S03.9 (must close first per the original carve-out sequencing — do NOT interleave; PM-closed 2026-05-21)

**Estimated size:** small-to-medium (~300-400 LOC across extraction + adapter + tests + the new db helper). Slightly larger than the original placeholder estimate due to the added binding work + helper introduction.

**Implications for S03.10 (jurisdiction_binding generation):**
- S03.6.1 introduces the `db.upsert_jurisdiction_binding` helper that S03.10 reuses.
- S03.6.1 writes 1 binding row; S03.10 writes the remaining bindings (HD-level + portion + restricted_area + CWD-zone + the `MT-STATEWIDE-antelope → MT-STATEWIDE-geom` binding that S03.10 will derive symmetrically).
- S03.10 must arrive at the same `MT-STATEWIDE-bear → MT-STATEWIDE-geom` binding row via its overlay-derived logic; UPSERT-by-id idempotency means the re-write is a no-op. S03.10's row-count guard band starts from a baseline of 1 (the bear binding already present) plus its derived bindings; document this carry-over in S03.10's working note.
- The `id` encoding S03.6.1 chooses MUST be the same encoding S03.10 derives for its bindings. Lock the encoding (format + test) as part of S03.6.1.

**Working-note pointer:** see [`docs/planning/epics/E03-confidence-findings/S03.9.md`](E03-confidence-findings/S03.9.md) § "Probe 1 — Bear ID coursework" for the design-target rationale (target-table = regulation_record, not reporting_obligation) and the pre-discovery verification.

**Acceptance Criteria:**

- [x] `extract_black_bear.py` reads page-2 right-column verbatim text via new `_extract_statewide_rules(pdf, pdf_filename, source_id, source_publication_date, extracted_at)` with whitespace-flexible regex anchors (`\s+` between tokens, `[-\s]+` around URL hyphen for page-2 wrap). Existing page-7-only scoping preserved; 35 BMU extractions unchanged. New `StatewideRuleCandidate` TypedDict + cleanup-rules docstring entry.
- [x] `black-bear-2026.json` carries a new top-level field `statewide_rules: list[StatewideRuleCandidate]` (list-not-dict per OQ-S6.1-1 for M2 extensibility — hunter-ed / archery cert can be added without schema migration). Base + merged artifacts regenerated; SHA-256 byte-identical across the entire fix cycle: `a09aefdb845257c13a85ba6ed5c6e81191e6ab34e5ea16d2e59d7ef2b99a8fb8`.
- [x] `load_regulation_records.py` emits **1 new** `RegulationRecord` with `state="US-MT"`, `license_year=2026`, `schema_version=2`, `jurisdiction_code="MT-STATEWIDE-bear"`, `species_group="bear"`, the Bear ID Test rule in `additional_rules`, `source` jsonb pointing at bear booklet page 2, `confidence="medium"`. New builder `_build_statewide_bear_record`. Provenance validation on `source_id` + `source_publication_date` added (cubic-review cycle 1, P2).
- [x] **`db.upsert_jurisdiction_binding` helper added** to `ingestion/ingestion/lib/db.py` — no-commit, UPSERT by `id` text PK, `source` jsonb-wrapped via `Json(...)`. **UPDATE clause restricted to `verbatim_rule` + `source` only** (identity-encoded fields intentionally excluded per OQ-S6.1-4 — silent-repoint protection: a future id-derivation collision is contained, not silently repointed). Schema-drift tripwire on `cur.rowcount == 0` (cubic-review cycle 2, restored after P3→P1 flip-flop). Locked by `TestUpsertJurisdictionBinding` (7 tests including `test_upsert_sql_does_not_update_identity_fields`).
- [x] `load_regulation_records.py` writes **1 new** `JurisdictionBinding` row in the same atomic transaction (FK insert ordering verified: record loop runs before binding loop). New builder `_build_statewide_bear_binding`. Fields: `regulation_record_*` composite-FK to MT-STATEWIDE-bear; `geometry_id="MT-STATEWIDE-geom"`; `role="primary_unit"`; `verbatim_rule=None` (rule text lives on the regulation_record); `source` same as the regulation_record.
- [x] **`id` encoding is deterministic.** Format: `_JURISDICTION_BINDING_ID_FORMAT = "{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"`. For the bear anchor: `"US-MT-MT-STATEWIDE-bear-bear-2026-primary_unit-MT-STATEWIDE-geom"` — byte-identical lock in `TestBuildStatewideBearBinding::test_id_encoding_is_deterministic`. **S03.10 inherits this constant** and reuses it for its overlay-derived bindings so the bear binding UPSERTs as a no-op.
- [x] **Row-count guard bands updated**: `_SPEC_ESTIMATE_TOTAL` 514→437 with band `[305, 568]`; new `_JURISDICTION_BINDING_COUNT_GUARD` band sized for S03.6.1's single-row write; new `_assert_jurisdiction_binding_count_within_guard`. Both guards fire BEFORE `db.connect()` per OQ7 discipline.
- [x] **Atomic transaction**: regulation_record + jurisdiction_binding commit together under a single `conn.commit()`. FK insert ordering preserved (record before binding) — verified by `TestAtomicTransaction::test_rollback_on_record_failure_does_not_commit` (binding loop never reached if record loop fails). `TestAtomicTransaction` carries 4 tests covering rollback variations.
- [x] **Idempotency**: rerunning the loader is a no-op for both writes (UPSERT-by-PK on regulation_record; UPSERT-by-id on jurisdiction_binding). Locked by tests in `TestBuildStatewideBearRecord` + `TestBuildStatewideBearBinding`.
- [x] **Pre-discovery verification of `MT-STATEWIDE-antelope` `additional_rules`** recorded in `docs/planning/epics/E03-confidence-findings/S03.6.1.md`: antelope's anchor carries 2 NOTE entries from `_extract_note_lines` against DEA 900-20; no `jurisdiction_binding` row exists for antelope (S03.10 will derive it symmetrically via overlay-fanout); `jurisdiction_binding` table was empty pre-S03.6.1 (S03.6.1 writes the first row ever).
- [x] **Sources reference verified**: `mt-fwp-black-bear-2026-booklet` citation present in `sources.yaml`; new constants `_BEAR_BOOKLET_CITATION_ID` + `_MT_STATEWIDE_GEOM_ID` + `_JURISDICTION_BINDING_ID_FORMAT` in `load_regulation_records.py`; `_load_citation_from_sources_yaml` now reads `supersedes` via `.get()` (cubic-review hardening).
- [x] `ruff check` clean
- [x] `mypy` clean per-file PM-verified post-merge across `ingestion/lib/` (7 source files) + `load_regulation_records.py` + `load_seasons_and_licenses.py` + `load_draw_specs.py` + `load_reporting_obligations.py` + `extract_black_bear.py` (12 source files total).
- [x] **Unit tests** cover all required surfaces, organized into new test classes mirroring the S03.6/S03.7/S03.8 patterns:
  - `TestExtractStatewideRules` (10 tests in `test_extract_black_bear.py`) — layout-shift, URL-hyphen-wrap, warning-names-pdf_filename
  - `TestBuildStatewideBearRecord` (8) — provenance-mismatch guards
  - `TestBuildStatewideBearBinding` (7) — deterministic id encoding lock
  - `TestUpsertJurisdictionBinding` (7) — includes `test_upsert_sql_does_not_update_identity_fields` locking the silent-repoint guard
  - `TestJurisdictionBindingCountGuard` (3); `TestRegulationRecordCount` (1)
  - `TestAtomicTransaction` (4) — rollback ordering
  - `TestNoLibImports` (4) — AST walk over both `ast.Import` and `ast.ImportFrom` (cubic-review cycle 7 gap fix)
  - 3 stale `TestCountGuard` tests updated to the new baseline
  - **Total: +43 net tests from S03.6.1**; suite reaches **1024 passed + 2 skipped** (was 981+2 pre-S03.6.1)
- [x] **Working note** at `docs/planning/epics/E03-confidence-findings/S03.6.1.md` records: artifact-shape decision (OQ-S6.1-1 list-not-dict for M2 extensibility), `id` encoding choice + rationale (OQ-S6.1-4 UPSERT identity exclusion = silent-repoint protection), antelope-binding-absence verification, S03.10 carry-over implications. Deletes at m1 tag per ADR-017 §6.
- [x] **CLAUDE.md updated** with row-count delta + S03.6.1 close note + S03.10 implications (helper inherited, binding-id encoding locked, FK insert ordering convention, UPDATE-clause-excludes-identity discipline).

**Closure note (closed 2026-05-22; PR `339e213` squash-merged to main from `feat/S03.6.1-mt-statewide-bear-anchor`):** Carved out of S03.9 scope 2026-05-19 with `regulation_record`-only framing; expanded 2026-05-21 (PM decision) to include the corresponding `jurisdiction_binding` to `MT-STATEWIDE-geom` so the statewide-anchor entity ships fully bound at story close. Final state: **437 regulation_record rows (+1) + 1 jurisdiction_binding row (first ever)** in one atomic transaction. **Four PM decisions baked in (OQ-S6.1-1 through OQ-S6.1-4)**: (1) artifact shape `list[StatewideRuleCandidate]` for M2 extensibility; (2) `rule_hint` as `str` (not Literal) for cross-state extensibility without enum maintenance; (3) no `NOTE:` prefix on text — raw verbatim per ADR-008; (4) `db.upsert_jurisdiction_binding`'s UPDATE clause excludes the 6 identity-encoded fields so a future id-derivation collision is contained (existing row's identity preserved) instead of silently repointing — refines ADR-018's binding semantics. **12 cubic-review cycles + Stage 6 triad** during PR review surfaced and resolved: stale provenance validation; dead/restored rowcount guard with schema-drift-tripwire docstring (P3→P1 flip-flop); synthetic pdf_filename anti-pattern (added `pdf_filename` parameter; 5 test call sites updated; new invariant test); stale plan signature (plan realigned to 5-param signature + explicit "do NOT synthesize/fall back" guidance); UPSERT identity update (clause reduced to `verbatim_rule` + `source` only; new test parses SQL constant); stale plan test paths (all `states/montana/tests/` + `ingestion/lib/tests/` corrected to `ingestion/tests/`); `ast.Import` gap in AST guards (both `ast.Import` + `ast.ImportFrom` walks now); brittle anchor regexes (whitespace-flexible `\s+` + `[-\s]+`; artifact SHA-256 unchanged); warning logs wrong identifier (swapped `source_id` → `pdf_filename`); weak URL-wrap test assertion (stricter substring). Artifact SHA-256 stable across the entire cycle (`a09aefdb845257c13a85ba6ed5c6e81191e6ab34e5ea16d2e59d7ef2b99a8fb8`). **One new pitfall** in `.roughly/known-pitfalls.md`: "fail-soft extractor paths must emit warning at extraction time" (deferring the warning to later in the pipeline obscures the source-of-truth signal). **No new ADRs; no new open questions** — Q19 unchanged status (project-wide derive-and-assert still pre-M2 blocker).

**Locked contracts for S03.10 (must honor):**

1. **`_JURISDICTION_BINDING_ID_FORMAT`** = `"{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"`. S03.10 must derive the same encoding so its overlay-fanout UPSERT against the bear binding is a no-op.
2. **`db.upsert_jurisdiction_binding`** helper — reuse as-is. No-commit, caller-controlled transaction. UPDATE clause includes ONLY `verbatim_rule` and `source` (not identity fields). S03.10 must NOT relax this.
3. **FK insert ordering** — within the atomic transaction, `regulation_record` loop must run before `jurisdiction_binding` loop. Verified by `TestAtomicTransaction::test_rollback_on_record_failure_does_not_commit`.
4. **Row-count guard band** — S03.10 must broaden `_JURISDICTION_BINDING_EXPECTED_TOTAL` from 1 to its overlay-fanout size. Current `[1, 1]` exact-match is a deliberate carve-out for S03.6.1's single-row write.

**Deferred follow-ups (non-blocking; M2):**
- **Revisit `rule_hint` as `Literal[...]`** if a second-state pre-purchase prerequisite shape emerges. V1 keeps `str` for cross-state extensibility without enum maintenance.

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

**Cross-species portion filter (rule B1 — see "Validator rule glossary" at end of epic):**

The overlay fixture contains pairings like `parent=MT-HD-antelope-311-geom` + `child=MT-HD-mule-deer-312-portion-...-geom` (cross-species — spatial intersection but no regulatory binding). When binding for an antelope regulation_record, **only consume overlay rows where the child's namespace matches the regulation_record's species axis** (or the child is a species-agnostic overlay).

**Fixture-derived namespace inventory** — empirically derived from the committed `ingestion/states/montana/fixtures/geometry-overlays.json` on 2026-05-03 (the file E03 consumes verbatim) by enumerating distinct `child_geometry_id` and `parent_geometry_id` prefixes. This is the basis for the per-species filter table below. Re-walk the fixture before S03.10 ships to confirm namespaces haven't drifted; if they have, this section and the table need a corresponding update.

Namespaces present in the fixture as of 2026-05-03:

- Parent geometries (HDs themselves): `MT-HD-antelope-`, `MT-HD-bear-`, `MT-HD-deer-elk-lion-`
- Portion namespaces (per-species, not shared): `MT-HD-elk-` (e.g., `MT-HD-elk-215-portion-elPt21-geom`), `MT-HD-mule-deer-` (e.g., `MT-HD-mule-deer-312-portion-...-geom`), `MT-HD-whitetail-` (e.g., `MT-HD-whitetail-310-portion-wtPt7-geom` — confirmed present in the live fixture), `MT-HD-antelope-` (HDs and portions share the antelope prefix; disambiguate via the geometry's `kind` field)
- Restricted-area namespaces: `MT-restricted-bigame-` (species-agnostic — applies to all big-game species) and `MT-restricted-elk-` (elk-specific)
- CWD-zone namespaces: `MT-CWD-zone-...` (species-agnostic — CWD applies to deer/elk family but the zone overlays are not species-keyed in the fixture)

Verification command (Python one-liner) that the S03.10 implementer SHOULD re-run before locking the filter table — surfaces any namespace drift since 2026-05-03:

```bash
python3 -c "
import json, collections
with open('ingestion/states/montana/fixtures/geometry-overlays.json') as f:
    data = json.load(f)
prefixes = collections.Counter()
for r in (data if isinstance(data, list) else data.get('relationships', [])):
    for k in ('parent_geometry_id', 'child_geometry_id'):
        cid = r.get(k, '')
        parts = cid.split('-')
        prefix = []
        for p in parts:
            if p.isdigit(): break
            prefix.append(p)
        if prefix: prefixes[(k, '-'.join(prefix) + '-')] += 1
for (k, p), n in sorted(prefixes.items()): print(f'{k:24s} {p:50s} {n}')
"
```

If the output names a namespace not in the inventory above, S03.10's filter table is stale — update before merging the load script.

**Filter rule by species_group** (each rule below = "accept the overlay row, write a binding"):

| `species_group` | Accept self-row primary_unit | Accept portions where child_geom_id starts with | Accept restricted_area children | Accept cwd_zone children |
|---|---|---|---|---|
| `elk` | `MT-HD-deer-elk-lion-N-geom` | `MT-HD-elk-` | `MT-restricted-bigame-` OR `MT-restricted-elk-` | yes |
| `mule_deer` | `MT-HD-deer-elk-lion-N-geom` | `MT-HD-mule-deer-` | `MT-restricted-bigame-` (NOT `MT-restricted-elk-`) | yes |
| `whitetail` | `MT-HD-deer-elk-lion-N-geom` | `MT-HD-whitetail-` | `MT-restricted-bigame-` (NOT `MT-restricted-elk-`) | yes |
| `pronghorn` | `MT-HD-antelope-N-geom` | `MT-HD-antelope-` (portions; disambiguate from HD self-row by `kind='portion'`) | `MT-restricted-bigame-` (NOT `MT-restricted-elk-`) | no (CWD doesn't apply to antelope) |
| `bear` | `MT-HD-bear-N-geom` | `MT-HD-bear-` (no V1 portions exist for bear in the fixture; rule is forward-compatible) | `MT-restricted-bigame-` (NOT `MT-restricted-elk-`) | no (CWD doesn't apply to bear) |
| `pronghorn` (statewide `MT-STATEWIDE-antelope`) | `MT-STATEWIDE-geom` | n/a (statewide reg_record gets exactly one binding) | n/a | n/a |

The filter is implemented as a function `is_binding_eligible(regulation_record, overlay_row) -> bool` with explicit unit tests for each row of the table above (one positive case + one negative case per species — e.g., a `mule_deer` regulation_record correctly REJECTS a child starting with `MT-restricted-elk-` and correctly REJECTS a child starting with `MT-HD-elk-` portion). **Whitetail portion handling is NOT a gap** — `MT-HD-whitetail-` portions exist in the fixture (e.g., `MT-HD-whitetail-310-portion-wtPt7-geom`).

**Binding row construction:**

For each accepted (regulation_record, overlay_row) pair, write `jurisdiction_binding` with:
- `regulation_record_state`, `regulation_record_jurisdiction_code`, `regulation_record_species_group`, `regulation_record_license_year` from the regulation_record's PK
- `geometry_id` from `child_geometry_id`
- `role` from `role_for_e03` (mapped per ADR-016's overlay fixture)
- `verbatim_rule` typically null (the source text is on the geometry's `verbatim_rule` from S02.4 layer-#2 REG/COMMENTS, on `geometry.legal_description` from S03.5/S03.6, or on the regulation_record's `verbatim_rule` — not duplicated here)
- `source` from a synthesized SourceCitation **referencing the original ArcGIS layer that produced the geometry** (per Source-Faithfulness validator F10): `document_type='gis_layer'` per ADR-014, citing the source layer (not the overlay fixture file). The overlay fixture is derived; the source-of-record is the layer.
- `id` constructed deterministically per rule N4: ~~`f"{state}-{jurisdiction_code}-{species_group}-{license_year}-binding-{geometry_id}-{role}"`~~[^id-format-correction]. All five tuple components plus `geometry_id` and `role` are participants because (regulation_record, geometry, role) triples are unique by construction. The format is verbose but produces stable IDs across re-ingestions: same regulation_record + same overlay_row + same role → same id, so UPSERT semantics work cleanly. Verify ID stability by running the loader twice with no data changes and confirming zero ID drift. **The id is opaque-but-deterministic: downstream code MUST NOT parse it** (the format embeds hyphenated `jurisdiction_code` and `geometry_id` so naive `id.split('-')` is ambiguous and not round-trippable). Code commenting must include a one-line "DO NOT PARSE" directive on the id-construction site.

  [^id-format-correction]: **Spec correction 2026-05-23 during S03.10 planning:** the actual format shipped by S03.6.1 is `f"{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"` (no `-binding-` literal; role-then-geometry_id ordering). Locked by `TestBuildStatewideBearBinding::test_id_encoding_is_deterministic` in `ingestion/tests/test_load_regulation_records.py`. S03.10 imports `_JURISDICTION_BINDING_ID_FORMAT` from `load_regulation_records.py` to keep the bear binding's id stable across S03.6.1 → S03.10 (UPSERT no-op).

**Statewide regulation_records bind to `MT-STATEWIDE-geom`** (per ADR-018):

Each statewide `regulation_record` (e.g., `MT-STATEWIDE-antelope`) gets exactly one `jurisdiction_binding` row to `MT-STATEWIDE-geom` with `role='primary_unit'`. Per ADR-018: any new `role` value beyond `primary_unit` for a statewide binding requires an ADR amendment.

**No-hunt-zone handling (E02 handoff item #7):**

The 3 `EXPECTED_RA_ORPHAN_IDS` (canonical literal IDs from `ingestion/states/montana/build_overlay_fixture.py`):

- `MT-restricted-bigame-glacier-national-park-geom`
- `MT-restricted-bigame-sun-river-game-preserve-geom`
- `MT-restricted-bigame-yellowstone-national-park-geom`

These have no parent HD in the overlay fixture. **V1 default: Option A — bind to "nearby" HDs as `role='other_overlay'`.**

**Deterministic "nearby" definition** (rule S5):
- ~~"Nearby" means: any HD whose geometry **shares an edge** with the no-hunt zone (`ST_Touches`) OR whose **centroid is within 5km** of the no-hunt zone's centroid (`ST_DWithin(geog::geometry, geog::geometry, 5000)`)~~[^nearby-rule-correction]
- **"Nearby" means: any HD whose boundary is within 5000 meters of the zone's boundary.** Implemented as single-clause `extensions.ST_DWithin(zone.geom, hd.geom, 5000)` on the native `geography` type (boundary-to-boundary distance in meters). PostGIS lives in the `extensions` schema; the prefix is required. This is a superset of `ST_Touches` (touching = 0m distance).
- Exact threshold locked in code as constant `_NO_HUNT_ZONE_NEARBY_DISTANCE_M = 5000` in `ingestion/states/montana/load_jurisdiction_bindings.py`.
- Empirically: Glacier=8, Sun River=8, Yellowstone=13 nearby HDs (T0 probe 2026-05-23). Adds ~59 jurisdiction_binding rows total (within prior 30-100 estimate). Documented in working note `docs/planning/epics/E03-confidence-findings/S03.10.md`.
- If during implementation this proves clumsy or surfaces edge cases, escalate to PM for Option B (schema discriminator) or C (defer) consideration.

  [^nearby-rule-correction]: **Spec correction 2026-05-23 during S03.10 implementation:** the originally-spec'd two-clause rule (`ST_Touches OR ST_DWithin(centroid, centroid, 5000)`) empirically returned 0 matches for ALL 3 orphan zones at 5km on real Montana data. Replaced with single-clause boundary-to-boundary `extensions.ST_DWithin(zone.geom, hd.geom, 5000)` on the native `geography` type. Reasons: (a) geography-typed ST_DWithin is the canonical PostGIS pattern for lat/lon "nearby" queries; (b) boundary-to-boundary at 5000m covers ST_Touches (touching = 0m distance < 5000m); (c) avoids the cross-cast round-trip that hit 120s statement_timeout on the geometry-cast variant (consistent with ADR-016's geography-native-functions precedent). No new ADR required. Note: column name is `geom` (geography type), not `geog` — CLAUDE.md uses "geog" colloquially but DDL uses `geom`.

**Zero-binding fail-loud (per-zone):** if any of the 3 `EXPECTED_RA_ORPHAN_IDS` produces zero binding rows under the nearby-rule, `load_jurisdiction_bindings.py` exits non-zero with a clear error message naming the zone. The most-likely candidate for this failure is Yellowstone NP (centroid is ~30km deep in the park, far from any HD boundary). Producing zero bindings would silently make the zone invisible to spatial queries — same effect as if E02 had dropped it. A real zero-match is an escalation signal (likely needs Option B/C), not a soft warning.

**Filter scope (per N5):** the no-hunt-zone selector filters on `geometry.kind = 'restricted_area' AND id IN EXPECTED_RA_ORPHAN_IDS`. **Both predicates are required.** The `kind='restricted_area'` filter is the load-bearing structural one — it ensures `MT-STATEWIDE-geom` (`kind='state'`), portions, CWD zones, BMUs, etc. are NOT eligible for Option A binding even if their spatial relationships satisfy the "nearby" rule. The `id IN allowlist` predicate is a secondary safety belt — restricted_area rows that have parent HDs in the overlay fixture are also not no-hunt zones, so the allowlist filters them out too. **If implementation reveals the kind filter alone is sufficient (i.e., every kind='restricted_area' row that lacks an overlay-fixture parent is in fact a no-hunt zone), the allowlist can be removed in a follow-up — the structural kind filter is the real protection.**

**Fan-out estimate from E02 handoff item #8:** median ~3 parent HDs per child geometry; one RA tied to 16 parent HDs. For 514 regulation_records × ~3-5 binding rows per record = **roughly 1,500-3,000 jurisdiction_binding rows** for V1 Montana, plus ~30-100 from no-hunt-zone bindings.

**Confidence per ADR-017:** `jurisdiction_binding` carries provenance (the area-overlap percentage from ADR-016), not confidence. The ADR-017 framework explicitly does not apply (per ADR-017 §2). No `confidence` field on this entity.

**Relevant ADRs:** [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md) (overlay fixture provenance), [ADR-017](../../adrs/ADR-017-confidence-calibration.md) (spatial-confidence carve-out), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md) (statewide bindings + `MT-STATEWIDE-geom`).

**Depends on:** S03.0 (`MT-STATEWIDE-geom`), S03.6 (regulation_record FK target), S02.6 overlay fixture (input).

**Acceptance Criteria:**

- [ ] `ingestion/states/montana/load_jurisdiction_bindings.py` exists; reads overlay fixture + queries regulation_record table; deterministic load order
- [ ] **Per-regulation_record traversal:** each regulation_record produces its own set of binding rows; no shortcut "for every overlay row, find a regulation"
- [ ] **Cross-species filter:** `is_binding_eligible(regulation_record, overlay_row)` function implements the per-species table in the spec above; explicit unit tests cover (a) one positive case and one negative case per species_group row, (b) the `MT-restricted-elk-` accept-only-for-elk discriminator (mule_deer/whitetail/pronghorn/bear all reject), (c) the `MT-HD-whitetail-` portion accept-only-for-whitetail discriminator, (d) statewide-pronghorn binding to `MT-STATEWIDE-geom`. SQL spot-check confirms an antelope regulation_record has no binding to a `MT-HD-mule-deer-*-portion-*-geom` child AND a mule_deer regulation_record has no binding to any `MT-restricted-elk-*` child.
- [ ] Statewide regulation_records bind to `MT-STATEWIDE-geom` with `role='primary_unit'`; no other `role` values used for statewide
- [ ] No-hunt-zone Option A applied: each of the 3 zones binds to nearby HDs per the deterministic ~~`ST_Touches` OR `ST_DWithin(5000)`~~[^nearby-rule-correction] single-clause `extensions.ST_DWithin(zone.geom, hd.geom, 5000)` rule (per Spec Deviation #4); binding count documented in working note
- [ ] **Per-zone zero-binding fail-loud:** if any of the 3 `EXPECTED_RA_ORPHAN_IDS` produces zero binding rows, the loader exits non-zero with the zone's id surfaced; unit test exercises this with a synthetic zone whose centroid is 100km from any HD
- [ ] Estimated row count is order-of-magnitude verified: SQL `SELECT count(*) FROM jurisdiction_binding` returns 400-1,100 for V1 Montana (band intentionally wide; narrow to ±30% around observed value after first live run)[^row-count-correction]

  [^row-count-correction]: **Spec correction 2026-05-23 during S03.10 planning.** Original estimate (1,500-3,500) overestimated overlay fan-out. Revised estimate: 235 fixture self-rows × per-geometry species multiplicity (mule_deer + whitetail + elk all share `MT-HD-deer-elk-lion-N-geom`) + 155 portions × per-species filter + 188 RAs × cross-species filter + 8 CWDs × 3 deer-family species + 2 statewide + ~59 no-hunt-zone = projected ~500-1,000 total. Plan's `_BINDING_COUNT_GUARD_BAND` is `(400, 1100)` pending T16 empirical lock.
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

For each documented edge case in ADR-017 (closure-prose extraction, region split, correction PDF, legal-description cross-ref, statewide overlay, NOTE lines, etc.), sample **at least 5 rows per edge case** from the corresponding entity table (or all rows if fewer than 5 exist). **Audit total = `max(50, stratified_count)`:** stratified samples are never trimmed; random fill brings the audit up to 50 only if stratified count is below 50. If stratified count alone exceeds 50, that's the audit — random fill is skipped. Worked example: 6 documented edge cases → 30 stratified + 20 random = 50 total. 12 edge cases → 60 stratified + 0 random = 60 total. 4 edge cases → 20 stratified + 30 random = 50 total.

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
- [ ] Stratified audit performed: ≥5 rows per documented edge case; total audit size = `max(50, stratified_count)` (random fill skipped when stratified ≥ 50); all sampled rows' assigned `confidence` verified against ADR-017's framework
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

**Recommended merge order:** S03.0 → S03.1 → S03.2 → S03.3 → S03.4 → S03.5 → S03.6 → S03.7 → S03.8 → S03.9 → S03.6.1 → S03.10 → S03.11 → S03.12

**Parallelization opportunities:**
- S03.3, S03.4, S03.5 are genuinely parallelizable: different booklets, disjoint output artifacts, no shared write keys.
- S03.7, S03.8, S03.9 are partially parallel: S03.8 depends on S03.7; S03.9 is independent of both.
- S03.6.1 is queued post-S03.9 (carved out 2026-05-19 — see § S03.6.1 placeholder); MUST NOT interleave with S03.9.
- S03.10 needs S03.6 only (not S03.7-S03.9) for binding generation; if S03.10 starts before S03.6.1 ships, the `MT-STATEWIDE-bear` binding lands in a follow-up.
- S03.11's draft can begin as soon as S03.7-S03.10 are at least partially in flight; finalization waits for them all.

---

## Open Questions and Deferred Items

1. **Q11 confidence calibration (resolved during this epic via ADR-017).** S03.11 audits and may produce an amendment for user review; if amendment is open at m1 tag time, deferred to early M2 per ADR-017 §7.

2. **Restricted-area discriminator (E02 handoff item #7).** May surface a clean answer during S03.10's no-hunt-zone binding work (Option A taken for V1). If a clean schema-side answer surfaces, fold into a future ADR (potentially ADR-019). If ambiguous, leave open and resolve in M2.

3. **No-hunt-zone binding strategy (S03.10).** V1 default: Option A (bind to nearby HDs as `other_overlay`, deterministic via ~~`ST_Touches` OR `ST_DWithin(5000)`~~[^nearby-rule-correction] single-clause `extensions.ST_DWithin(zone.geom, hd.geom, 5000)` per Spec Deviation #4).

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

## Validator rule glossary

The epic references rule codes (B1, B2, F10, F12, N2-N5, S5, SF2, SF5, SF6) inline. Each came from a schema-/source-faithfulness/confidence-validation pass during E03 planning. The prefixes are origin labels — `B*` = binding, `F*` / `SF*` = source-faithfulness, `S*` = spatial, `N*` = naming/numbering, `Conf` = confidence — but for implementation purposes the rule body is what matters. Inlined here so the epic is self-contained and durable past the validator artifact's lifecycle.

| Code | Subject | Rule |
|---|---|---|
| **B1** | Binding — cross-species portion filter | When binding for a regulation_record, only consume overlay rows whose child namespace matches the regulation_record's species axis (or is a documented species-agnostic overlay). See S03.10 § "Cross-species portion filter" for the per-species table. |
| **B2** | Binding — per-regulation_record overlay traversal | Each regulation_record gets its own pass through the overlay fixture, keyed by its own derived geometry_id. Species-axis multiplication happens in the binding loader, not in the fixture. |
| **F10** | Source-faithfulness — binding's source citation | `jurisdiction_binding.source` references the **original ArcGIS layer that produced the child geometry** with `document_type='gis_layer'`, NOT the derived overlay fixture file. The overlay fixture is derived; the source-of-record is the layer. |
| **F12** (Conf) | Confidence — assignment inputs persisted | Each ingestion story's working note records the inputs that drove every (entity_id, assigned_confidence) pair: source format, extraction operation, transformation steps, correction-touched flag. Lets the audit reproduce framework logic without re-extracting. |
| **N2** | Naming — per-BMU `hd_region` field | S03.4's extraction artifact carries `hd_region: 'R1'..'R7'` per BMU row, sourced from the regional map in the Black Bear PDF. Drives the R1 vs R2-7 reporting_obligation linkage in S03.9. |
| **N3** | Naming — `season_definition.verbatim_rule` source rule | Source from the General (A) license's opportunity-specific-details cell when an A license covers the season; if the season is B-only, source from the B license's cell. Per-license cell differences inform `license_tag.verbatim_rule`, NOT `season_definition.verbatim_rule` (which is single-source-of-record). |
| **N4** | Naming — `jurisdiction_binding.id` format | `f"{state}-{jurisdiction_code}-{species_group}-{license_year}-binding-{geometry_id}-{role}"`. Opaque-but-deterministic; downstream code MUST NOT parse the id. |
| **N5** | Naming — no-hunt-zone selector | Filter on `geometry.kind = 'restricted_area' AND id IN EXPECTED_RA_ORPHAN_IDS`. Both predicates required — kind is the structural protection; allowlist is the safety belt. |
| **S5** | Spatial — deterministic "nearby" definition | "Nearby" = HD boundary is within 5000m of zone boundary (`extensions.ST_DWithin(zone.geom, hd.geom, 5000)` on native `geography` type; boundary-to-boundary, meters). Constant `_NO_HUNT_ZONE_NEARBY_DISTANCE_M = 5000` locked in code. Per Spec Deviation #4 (see `[^nearby-rule-correction]` footnote) — supersedes the originally-spec'd two-clause `ST_Touches` OR `ST_DWithin(geog::geometry, geog::geometry, 5000)` rule (which empirically returned 0 matches on real data). |
| **SF2** | Source-faithfulness — closure temporal anchors | For V1, keep temporal anchors (e.g., "after May 31") in `ClosurePredicate.verbatim_rule` only. Do NOT invent a structured `effective_after` field. Flag for future ADR if the pattern recurs. |
| **SF5** | Source-faithfulness — weapon convention | `season_definition.weapon_type` is nullable (NULL = no season-level restriction); `license_tag.weapon_types` is required array (the license is the source-of-truth for "what weapons can this hunter use"). MCP server (M3) renders the intersection. |
| **SF6** | Source-faithfulness — `quota_range` bounds | `int4range` with **inclusive bounds on both sides: `[lower, upper]`**. Postgres syntax: `int4range(lower, upper, '[]')`. Application-code validation: `lower <= quota <= upper` whenever both are non-null. |

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
