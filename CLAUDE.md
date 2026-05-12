# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

HuntReady is a regulatory data platform for licensed hunting in the US. Given a coordinate, species, and date, it returns applicable regulations with source citations, license/tag requirements, season windows, reporting obligations, and agency contacts. It routes hunters to authoritative state agency sources — it does not interpret or paraphrase regulations.

## Project status

**M1 in progress (E01 + E02 complete; E03 active — 5/13 stories complete; S03.5 next).** M0 scaffold complete. E01 (schema migrations, RLS, quality gates) merged 2026-04-28. **E02 (Montana geometry ingestion) closed and audited 2026-05-03 with all 8 stories merged and all exit criteria met (post-implementation audit at `docs/planning/epics/E02-audit.md`: 86/89 ACs MET, 3 P3 cosmetic findings all fixed in `0093e88`).** Final geometry-table state: 235 HDs (layers #3, #10, #11) + 55 portions (#4, #12, #13, #14) + 57 restricted areas (#2, #15) + 2 CWD zones (dedicated `ADMBND_HD_CWD` FeatureServer) = **349 V1 Montana rows**, all `geography(MultiPolygon, 4326)`, all valid via `shapely.make_valid()`. Companion artifacts: `ingestion/states/montana/fixtures/geometry-overlays.json` + audit log `geometry-overlays-dropped.json` (built via local shapely + STRtree per ADR-016's three-band area-ratio discriminator since Supabase's 2-min `statement_timeout` aborts cross-join SQL on real data); 10 metadata fixtures + 10 per-fetch manifests (~5KB each) committed for cross-operator drift detection while raw features payloads stay gitignored at ~180MB/run; spatial verification suite at `spatial-test-points.json` with 11 named test points covering all 5 kinds; operator runbook at `docs/runbooks/E02-geometry-verification.md` (264 LOC, mirrors E01's structure). Schema additions during E02: `geometry.verbatim_rule text` (nullable) per ADR-015 with HuntReady-introduced `\n\n--- COMMENTS ---\n\n` separator for layer-#2 REG+COMMENTS combination; `SourceCitation.document_type='gis_layer'` per ADR-014. Two E03 handoff items recorded in epic § "Known issues to escalate": `kind='restricted_area'` conflates internal HD restrictions with no-hunt zones (3 V1 cases — Glacier NP, Sun River, Yellowstone) and may need a discriminator subtype or multi-bind role mechanic; jurisdiction_binding fan-out is higher than naive (median ~3 parents per child, max 16) so E03 should expect several thousand binding rows for V1 Montana, not ~349. **E03 (Montana regulation text ingestion) planned 2026-05-03**: 13 stories (S03.0 schema-prep through S03.12 M1 UAT/handoff); validated via the E03 triad (Source Faithfulness, Confidence Calibration, Schema Stress-Test); two new ADRs accepted: ADR-017 (confidence calibration + parent-inheritance rule, resolves Q11) and ADR-018 (E03 schema additions: `license_season` link table + `geometry.legal_description` column + `geometry.kind='state'` value). Working-artifact directories planned at `docs/planning/epics/E03-confidence-findings/` (deleted at m1 tag per ADR-017 §6) and `docs/planning/epics/E03-deferred-items/` (survives past M1, includes `draw-mechanics.md` for `parameters` Q12 deferrals). **E03 S03.0 (schema prep) merged 2026-05-04**: migration `20260504032424_e03_schema_additions.sql` ships ADR-018's three additions (`license_season` link table + `geometry.legal_description` column + `geometry.kind='state'` value) with three-place sync. `MT-STATEWIDE-geom` written to production 2026-05-04 16:25 PT via `ingestion/states/montana/load_state_boundary.py` (single-part valid MultiPolygon, area ≈ 380,840 km²; `license_year=NULL`; `source.id='mt-msdi-framework-boundaries-9-2026'`). Source choice deviates from ADR-018's two listed options — chose **Montana State Library MSDI Framework Boundaries layer 9** (gisservicemt.gov) as a third option that strictly dominates: state-published, GCDB-aligned at 1:24,000, fits `document_type='gis_layer'` cleanly. Pinned URL + SHA-256 + `2026-01-01` publication date. Three new entries in `.roughly/known-pitfalls.md` from S03.0's investigation + deployment: (a) MT GIS layers live on **three** hosts (FWP on-prem + AGOL MtFishWildlifeParks + Montana State Library MSDI), not two — extends the prior S02.5 pitfall; (b) one-off `requests.get()` against ArcGIS endpoints must explicitly check `data.get("error")` envelopes (200-with-error-body is the ArcGIS pattern); (c) `supabase db push` against a dashboard-bootstrapped project fails with "relation already exists" — fix is `supabase migration repair --status applied <timestamp>` per pre-existing migration before pushing. Working-artifact directories live: `docs/planning/epics/E03-confidence-findings/` (deleted at m1 tag) and `docs/planning/epics/E03-deferred-items/` (survives past M1). 332/332 tests green. **E03 S03.1 (PDF fetch infrastructure) shipped 2026-05-05** on `feat/S03.1-pdf-fetch-infrastructure` (8 commits, `b16dc9d..ef3f467`): `ingestion/ingestion/lib/pdf_fetch.py` (~310 LOC, state-agnostic per ADR-005 — public API `fetch_pdf` / `PdfMetadata` / `PdfFetchError`), `ingestion/states/montana/fetch_pdfs.py` (~230 LOC, fail-loud aggregating orchestrator with distinct buckets for failures vs. pending entries), `ingestion/states/montana/sources.yaml` (4 entries with full SourceCitation field set; correction PDF carries `pending: true` since URL is genuinely TBD — exit-0 still blocked until populated), per-PDF-manifest gitignore policy mirroring S02.1's pattern, and 33 new unit tests (332 → 365). SHA-256 drift on re-fetch raises `PdfFetchError` and writes a `<id>-<publication_date>-pending-reextraction.flag` marker; downstream stories (S03.3-S03.5) check the marker and refuse to proceed until an operator deletes it. State-agnostic-lib invariant enforced via AST-based test guard (not just substring scan). Two new pitfalls in `.roughly/known-pitfalls.md`: (a) state-adapter scripts must be invoked as `python <path>` not `python -m` (the editable-install layout makes `states/` a non-subpackage); (b) `expected_sha256` in `sources.yaml` is documentation/intent — runtime drift detection compares against the on-disk manifest, not the YAML field. AC #4 (manifest commits) infrastructure-met but fixture-deferred to first ops-run, same posture as E02 S02.1 → S02.2. Two ADR-adjacent design choices baked in but not promoted: `pending: true` YAML semantics (adapter-specific; revisit if a second state adopts the pattern) and the drift-marker convention as canonical fail-loud-and-block-downstream signal (already encoded in S03.1 epic prose; ADR-001's parent discipline covers the principle). **S03.3 unblocked 2026-05-07** after the implementation agent reported all four `sources.yaml` URLs returning 404 against the live FWP CDN. Canonical URLs located on `https://fwp.mt.gov/hunt/regulations`, verified live (HEAD → 200 application/pdf), and committed to `sources.yaml`. DEA citation id renamed `mt-fwp-dea-2026-2027-booklet` → `mt-fwp-dea-2026-booklet` to match the URL-truthful annual cadence (FWP publishes only `2026-dea-regulations`, not a `2026-2027` biennial — cover-page cadence to be confirmed at first extraction). All four `publication_date` values were revised to each PDF's HTTP `Last-Modified` header (DEA + Black Bear booklet: 2026-04-27; Legal Descriptions: 2026-02-03; correction stays 2026-03-18, matching the citation id). Black Bear correction URL also located in the same pass, **resolving S03.4's S03.1-inherited precondition** (no separate operator action remains). New pitfall recorded under "Conventions — Ingestion adapters": "`sources.yaml` URL slug ≠ publication cadence — confirm cadence by reading the PDF, not the URL." Surfaced learning: spec tables encoding URL guesses are pre-validated assumptions; live discovery + HEAD-verification before pinning is the right S03.X pre-implementation gate. **E03 S03.3 (DEA booklet extraction) code-complete 2026-05-08** on `feat/S03.3-dea-booklet-extraction` (12 commits, `e1a047f..69d98f7`, cleared PR review): `ingestion/states/montana/extract_dea.py` (~1545 LOC, state-agnostic-clean per AST guard) emits `ingestion/states/montana/extracted/dea-2026.json` (264 sections / 1178 rows / **perfect 50/50 high-medium confidence split, 589 each, no low**). Composition: 129 deer + 112 elk + 22 antelope per-HD sections + 1 STATEWIDE antelope overlay (`900-20`, quota=5600, range="1-7500", archery window Aug 15-Nov 8). All 4 first-fetch baseline manifests committed in `7b1ec54` (DEA, Black Bear booklet, Legal Descriptions, Black Bear correction); raw PDFs gitignored. **AC #342 (UAT faithfulness) is operator-pending** — the single open AC; does NOT gate downstream stories. **The S03.3 plan's research notes did not survive contact with the actual PDF — 9 real-PDF discoveries baked into the implementation:** (1) one table per page, not per HD; HD-section delimiters are embedded data rows; (2) column headers carry `... SEASON DATES` suffix; (3) `-` is a universal absent-cell sentinel — review caught dash leaking into apply_by/quota_range/extras (675/971/521 rows pre-fix); (4) species banners embedded mid-table as `['DEER', None, ...]` rows; (5) license-code carry-forward via `None` in LICENSE/PERMIT (merged-cell artifact); (6) antelope tables use a different column format ("License/Opportunity/Quota/Archery Season Dates/Season Dates"); (7) `_ANTELOPE_PAGES = (136, 141)` — actual PDF is 141 pages, not 142 as spec claimed; (8) `900-20` is a repeated table row, not a prose paragraph; (9) multi-page HDs repeat heading with ` - Continued` suffix — first-match-wins dedup added after 20 HDs were duplicated. **Three new pitfalls in `.roughly/known-pitfalls.md` under Integration — pdfplumber:** (a) FWP DEA-style tables: one-table-per-page assumption; (b) `-` as universal absence sentinel; (c) merged-cell sub-row license-code carry-forward via `None`. Schema additions for downstream: 5 TypedDicts (`SeasonCoverage`, `SeasonWindow`, `DeaRowExtraction`, `DeaSectionExtraction`) define the contract S03.6-S03.9 read directly from `dea-2026.json`. 74 tests in `test_extract_dea.py`; suite total ≈478. Three deferred follow-ups for downstream review (recorded in epic § S03.3 closure note): per-row page-accurate `page_reference` for multi-page HDs (S03.6); row-level `weapon_types` default refinement (S03.7); window divergence per row, with "Elk B License: 699-01" as the most-prolific divergence case (S03.7). **S03.3 closed 2026-05-08 after UAT-driven fix cycle.** Original PR (12 commits, `e1a047f..69d98f7`) cleared code review on 2026-05-08 but PM-run UAT against four candidate sections (deer HD 124 / elk HD 170 / antelope HD 690 / antelope STATEWIDE 900-20) surfaced six defects: **D1 (P0)** per-row General Season window divergence collapsed to first-row's value across ≥143 multi-row sections (HD 124 deer alone had 3 distinct General windows in PDF; artifact had only 1); **D2 (P0)** Region 7 "Portions of HDs ..." sub-sections absorbed into HD 690 with 4 phantom rows (`007-21`, `007-31`, `007-20`, `007-30`), actual portions sub-sections entirely missing; **D3 (P1)** STATEWIDE 900-20 row's `Aug. 15-Nov. 08` date in PDF's Season Dates column was remapped to `archery_only` based on extras-text interpretation rather than column position; **D4 (P2)** STATEWIDE extras "First and only choice. ArchEquip only." dropped; **D5+D6 (P3)** STATEWIDE `license_code` prefix and `quota_range` comma stripped inconsistently with per-HD rows. Implementation agent applied three fixes in single commit `cb3fb24`: deleted `_aggregate_section_season_windows` / `_row_season_windows` and rewrote `_rows_to_license_extractions` to read each row's own season-column cells inline (per-row windows; divergence-WARNING removed); added `_parse_portions_hd_list` / `_is_portions_subsection_row` / `_PORTIONS_HEADER_RE` and rewrote the antelope orchestrator to walk pages directly with three delimiter types (HD-numbered, Portions, Region N), emitting one `DeaSectionExtraction` per listed HD per option-(a) (rows duplicated; license_code disambiguates at S03.6); deleted `_extract_statewide_antelope_overlay` / `_ANTELOPE_900_ROW_RE` and routed the 900-20 row through the same `_rows_to_license_extractions` machinery with `is_statewide_overlay=True` flag for column-faithful emission. Added an extras-only `re.sub(r"\s+", " ", ...)` collapse at the write-site (one documented deviation from the directive) so multi-line extras prose collapses to single-space-joined text without affecting `_normalize_cell`'s HD-heading detection. PM re-ran the UAT workbench against the re-extracted artifact: **all six defects resolved**. Final artifact: **272 sections / 1190 rows** (+8 sections / +12 rows from Region 7 portions: HDs 700-705 each with `007-*` rows; HDs 701 and 703 appear in both North and South Yellowstone portions); confidence distribution 589 medium + 601 high. Test delta: −7 stale, +17 new = net +11 in `test_extract_dea.py` (73 → 84); full suite **488 passed + 1 skipped**; ruff + mypy + cubic clean. **Four pdfplumber pitfalls in `.roughly/known-pitfalls.md`**: (a) FWP DEA-style tables: one-table-per-page; (b) `-` as universal absence sentinel; (c) merged-cell sub-row license-code carry-forward via `None`; (d) "Section-level first-observation-wins for per-row variable fields is interpretive, not faithful" (UAT-discovered). Working artifacts at `docs/planning/epics/E03-confidence-findings/S03.3.md` (UAT fix log) and `S03.3-uat-fixes.md` (directive); both delete at m1 tag per ADR-017 §6. **Docstring parity restored 2026-05-08:** the new extras-only `\s+ → " "` collapse rule was added to the module-level "Cleanup rules" section at `extract_dea.py:44-60` with exact regex, scope, rationale, and a pointer to the tests that lock it (`TestStatewideOverlayColumnFaithful`, `TestArtifactRegion7Portions`). AC #338 strict parity established; the pattern — every cleanup rule applied to row cells must appear in the module docstring — is now the canonical S03.X discipline. **Phase 6 plan-realignment 2026-05-09:** five docs(S03.3) commits aligned the implementation plan with the UAT-corrected code so a future re-reader following the plan wouldn't re-create the UAT defects (T7 per-row windows; T8 page-range-bounded inline emit; T1 `_ANTELOPE_PAGES = (136, 141)`; T10 step 1 rewrites referencing the new orchestrator; T12 post-UAT test class enumeration; T9 confidence rules aligned with shipped `_assign_row_confidence`; T13 determinism-check command turned into complete two-step recipe; epic line 337 confidence count corrected from 589/589 to 601/589). **Phase 7 fail-loud guard 2026-05-09:** restructured the STATEWIDE 900-20 emit guard to fail loud at three distinct stages (row-not-captured / row-captured-but-zero-extractions / success); closes a P1 silent-data-loss path. New `TestStatewideOverlayFailLoudOnEmptyExtraction` test (monkeypatches `_rows_to_license_extractions` to return `[]` for the statewide call while letting per-HD calls pass through). PM re-verified all six UAT defects still clear after Phase 6+7 (artifact SHA-256 byte-identical to post-UAT-fix `a41a4fd7…`); 489 tests + 1 skipped, ruff + mypy + cubic all clean. **E03 S03.4 (Black Bear booklet + correction PDF handling) closed 2026-05-12** via PR `ab09e82` (squash of 5 commits on `feat/S03.4-black-bear-extraction`): `ingestion/states/montana/extract_black_bear.py` (~1820 LOC) implements the three-pass date-arbitrated extraction of the 16-page booklet + 1-page correction into three deterministic JSON artifacts: `black-bear-2026-base.json` (Pass 1: 35 BMU rows + 2 closures + 3 reporting candidates), `corrections-2026-03-18.json` (Pass 2: 35 per-BMU CorrectionOperation dicts), and `black-bear-2026.json` (Pass 3 merged — S03.6-S03.9 consume this). All 35 rows tagged `applied_correction=true`, `supersedes=mt-fwp-black-bear-2026-booklet`, confidence demoted HIGH→MEDIUM (correction touches every BMU's hound_training_season cell). **Three PM decisions accepted at closure**: (a) **AC #428 9→8 quota-closure BMUs** — BMU 530 absent from 2026 PDF; spec was stale; drift guard locks 8; (b) **AC #429 2→3 reporting obligations** — STATEWIDE Mandatory Reporting (48-hour harvest) is operationally distinct from the R1/R2-7 inspection split; spec was stale; (c) **AC #430-431 Option B (doc-type precedence) replaces spec's MAX-date Option A** — booklet Last-Modified (2026-04-27) post-dates correction (2026-03-18); Option A would silently no-op; `document_type='correction'` always wins over `'annual_regulations'` regardless of date; date is tiebreaker within same doc-type only. Row-level (not cell-level) source attribution accepted as V1 simplification per the schema-stability discipline. ADR-019 candidate flagged to formalize doc-type-precedence rule for all future state adapters; PM to draft next. **12 real-PDF discoveries** documented in closure note: rotated table requires `_reverse_cell_text` per cell, table spans pp. 9-12 (not 10-11), BMU 530 absent, correction is prose-only (operations synthesized per BMU), regional map is image-only (`hd_region` derived from in-table column markers), Permit Managed sub-table on p. 11 skipped via state flag, quota cells have 3 distinct word orderings, female-sub-quota BMUs carry `*` footnote suffix, page-7 closure prose is two-column (right-column bbox crop required), phone-number digit-linebreak preserves the structural dash, drift guards first-sentence-scoped. **Two cubic-review iterations during wrap-up** caught and fixed correctness defects in `_merge_with_corrections`: (a) per-(bmu, field) loop overwrote row-level source_id (refactored into 3 stages with row-level state updated exactly once per touched BMU); (b) `demote_one_tier` fired N times for a row touched by N corrections (moved to Stage 3 to fire exactly once per touched BMU, per ADR-017 §4 single-step rule); (c) initial `max(..., key=date)` was iteration-order-dependent on equal-date ties (added two-pass selection with lex-smallest-source_id tiebreaker). All three regressions locked by dedicated unit tests. **Eight new pitfalls in `.roughly/known-pitfalls.md`** (6 from initial implementation + 2 algorithmic patterns surfaced by cubic-review iteration). Test suite: **574 passed + 2 skipped** (+85 tests + 1 new skip). PM-driven UAT 2026-05-12 verified 4 BMUs (411 quota-closure+female-subquota, 300 Spring Closure, 100 unrestricted, 700 quota-closure) against `pdfplumber`-extracted source; closure prose + 3 reporting obligations cross-checked against PDF page 7. One faithfulness caveat documented: rotated-table extraction scrambles `opportunity` / `verbatim_text` word order (all source words preserved; sentence flow not); structured fields are clean and verifiable; meets ADR-008 verbatim discipline. **Two M2-deferred items recorded:** cell-level source attribution (would require `BmuRowExtraction` schema split); Spring Season Closure temporal anchor ("at any point after May 31") needs structured field if pattern recurs in future states (`effective_after: date | null` ADR-candidate at `docs/planning/epics/E03-deferred-items/closure-temporal-anchors.md`). **S03.5 (Legal Descriptions extraction) is now unblocked and is next; S03.6 (regulation_record ingestion) can begin in parallel since `dea-2026.json` + `black-bear-2026.json` are both ready.** **E03 S03.2 (PDF extraction primitives — shared library) shipped 2026-05-06** on `feat/S03.2-pdf-extraction-primitives` (3 commits, `80fcca0..ceaca2c`): `ingestion/ingestion/lib/pdf.py` (332 LOC, state-agnostic per ADR-005) wrapping `pdfplumber` 0.11.x with 12 public exports — `PdfDocument`, `open_pdf`, `iter_pages`, `extract_text`, `extract_tables` (returns `TableMatch` records with bbox + headers + rows; uses `page.find_tables()` not `page.extract_tables()` because only `find_tables()` carries spatial info), `find_section` (regex-anchored heading lookup), `PageReference` TypedDict + `page_reference_to_str` collapse helper, `ConfidenceTier(str, Enum)` mixin so instances ARE strings (no `.value` access at write-sites for `regulation_record.confidence`), `min_tier` (most-uncertain-wins MIN with explicit `key=lambda t: t.rank` — guards against the lexicographic trap where naive `min(["high","low","medium"])` returns `"high"` because h<l<m), `demote_one_tier` (ADR-017 correction-touched rule, floor-clamped), and `PdfExtractionError`. ADR-008 boundary clarified: `extract_text` adds zero wrapper-level normalization on top of pdfplumber's word-grouping (which collapses repeated *internal* whitespace as part of glyph-to-text reconstruction — PDF content streams don't carry literal inter-word spaces); paraphrase prevention is fully met because numeric tokens, units, and lexical words are byte-exact. Defense recorded in `docs/planning/epics/E03-confidence-findings/S03.2.md`. Char-level reconstruction (`page.chars`) remains available as a future helper (`extract_text_chars_raw`) if a downstream story needs byte-exact text — not retrofitted onto `extract_text`. `extract_tables` emits `_logger.warning` when `find_tables()` locates a boundary but `Table.extract()` returns [] (silent-failure-hunter P1 fix; surfaces parse ambiguity rather than recording empty rows). 39 new tests in `test_pdf.py` (404 total; ruff + mypy clean across 7 source files), including `test_lexicographic_trap_explicit` (three assertions locking against rank-ordering regressions on raw strings AND on enum `.value`), `test_no_layout_true_regression_guard` (monkeypatch spy ensures `extract_text` does not silently set `layout=True`), `test_empty_table_emits_warning`, and `TestPdfNoStateAdapterImports` (AST-walk + slug-substring scan). Two new pitfalls in `.roughly/known-pitfalls.md` under "Integration — pdfplumber": (a) `extract_text` collapses repeated spaces (not byte-exact verbatim) — `page.chars` is the byte-exact escape hatch; (b) `page.extract_tables()` drops bboxes; use `page.find_tables()` when bbox is needed. **S03.3 (DEA booklet extraction) is next.**

## Architecture

```
Data Sources (state F&W agencies, PAD-US, BLM)
       ↓
  ingestion/ (Python) — per-state adapters, offline pipeline
       ↓
  Supabase Postgres + PostGIS — single source of truth
       ↓
  mcp-server/ (TypeScript) — canonical interface, 5 MCP tools
     ↓          ↓
  web/ (Next.js)  plugin/ (Claude Code plugin)
```

### Architectural commitments (enforced, not aspirational)

- **MCP server is the canonical interface.** Web and plugin are both clients of the MCP server. No surface bypasses it to query the database directly.
- **Ingestion is upstream and offline.** Python pipeline writes to Postgres; the TypeScript serving stack never imports from `ingestion/` or requires Python. Contributors working on serving can ignore the Python toolchain entirely.
- **Authority preserved, not replaced.** Every regulation record requires a source citation (URL, agency, publication date). Regulation text is carried verbatim — no paraphrasing, no summarization. Records without citations fail validation.
- **Schema versioned from day one.** `regulation_record` and `draw_spec` carry `schema_version`; source provenance is tracked via the `source` jsonb field (which includes `publication_date`). The MCP server rejects records with unsupported schema versions.
- **Server returns structure; clients compose presentation.** No server-side `overview` or `headline` fields. Structured sections with always-present, null-bearing fields (null = "not applicable" vs omitted = ambiguous). Each client composes its own summary because each knows its presentation context.
- **Agentic development is first-class.** The Claude Code plugin (`plugin/`) uses `.claude-plugin/` + `plugins/<name>/skills/<skill>/SKILL.md` convention. Documentation is the primary handoff mechanism between sessions.

### Key constraints

- PostgREST API is disabled via RLS — only service-role credentials can read/write. This prevents an uncontrolled second path to the data.
- `draw_spec.parameters` is a `Record<string, unknown>` escape hatch for state-specific quirks. Shared code (MCP server, web client) must NEVER read this field. Only state adapters in `ingestion/states/<state>/` may use it.
- `draw_spec.pools` and `draw_spec.point_system` are stored as `jsonb`. Pool share sum-to-1.0 and eligibility consistency are validated in application code, not DB constraints.
- All geometries use `geography(MultiPolygon, 4326)` — not `Polygon` — because real state data (CPW GMUs, MT HDs) contains multi-part units along state lines.
- Every geometry goes through `shapely.make_valid()` before insert.
- No `any` types in .tsx files.

## Tech stack

| Layer | Language | Key dependencies |
|-------|----------|-----------------|
| Ingestion (`ingestion/`) | Python | pdfplumber, pypdf, unstructured, geopandas, shapely |
| MCP Server (`mcp-server/`) | TypeScript | Anthropic MCP SDK, Postgres connection pool |
| Web (`web/`) | TypeScript | Next.js, Mapbox GL JS, Tailwind |
| Plugin (`plugin/`) | TypeScript | Claude Code plugin conventions |
| Database | SQL | Supabase Postgres + PostGIS extension |
| Migrations | SQL | `supabase/migrations/` timestamped files |

## Build commands (once implementation exists)

```bash
# Ingestion (Python)
make ingest STATE=montana         # Full pipeline: fetch → extract → normalize → validate → load
make ingest-all                   # All states

# MCP Server (TypeScript)
cd mcp-server && npm install && npm run dev

# Web companion (Next.js)
cd web && npm install && npm run dev

# Database migrations
supabase db push                  # Apply migrations to Supabase
```

## Verification commands

Used by `/ruckus:verify-all` and the Stop hook. Run from the repo root.

```bash
# Python ingestion — lint, type, test
cd ingestion && .venv/bin/ruff check ingestion/ tests/
cd ingestion && .venv/bin/mypy ingestion/lib/
cd ingestion && .venv/bin/pytest tests/

# TypeScript serving (when files exist; mcp-server and web both currently empty)
cd mcp-server && npx tsc --noEmit
cd web && npx tsc --noEmit
```

## Data model (6 entities)

- **`regulation_record`** — anchor entity, keyed by (state, jurisdiction_code, species_group, license_year)
- **`season_definition`** — named date ranges with weapon/residency constraints
- **`license_tag`** — permit instruments with optional draw_spec reference
- **`draw_spec`** — draw mechanics, keyed by (state, hunt_code, year). Sibling entity referenced from `license_tag` by FK. Composes `point_system`, `residency_cap`, `choices`, and `allocation_pool[]` — verified against CO, WY, NM, UT draw systems with no state-specific branches in shared code.
- **`reporting_obligation`** — post-harvest/in-season duties, can be region-specific
- **`geometry` + `jurisdiction_binding`** — polygons and their roles (primary unit, overlays like CWD zones, BMUs)

Entities cross-share: e.g., Montana A and B licenses reference the same `season_definition` rows. Corrections update one row, not duplicated copies.

Schema is defined in three places kept in manual sync: TypeScript types (`mcp-server/src/types/`), Python dataclasses (`ingestion/lib/schema.py`), and Postgres DDL (`supabase/migrations/`). Schema version bumps propagate to all three. The canonical type definitions are in [docs/architecture.md](docs/architecture.md).

## Ingestion adapter pattern

Each state lives in `ingestion/states/<state>/` with isolated files:
- `fetch.py` — retrieve source documents
- `extract.py` — pull structured data from sources
- `normalize.py` — map state-specific fields to shared schema
- `validate.py` — common + state-specific validation
- `load.py` — write to Supabase Postgres
- `sources.yaml` — source document registry

State adapters are isolated from each other. Shared code lives in `ingestion/lib/`. Adding a new state means adding a new directory, not modifying shared code.

## V1 scope

- **States:** Montana, Colorado (deliberately chosen: MT for moderate complexity, CO for draw-system stress-test)
- **Species:** elk, mule deer, whitetail, pronghorn, black bear
- **MCP tools:** `get_regulations`, `check_land_status`, `list_seasons`, `get_tag_requirements`, `get_agency_contacts`
- **Surfaces:** MCP server, web companion, Claude Code plugin

Explicitly out of scope for V1: mobile app, user accounts, automated ingestion scheduling, B2B API packaging, harvest tracking, license purchase proxying.

## Documentation as handoff mechanism

Per ADR-009, documentation is the primary handoff mechanism between sessions (human or agent). The flow: question arises in `open-questions.md` -> resolved in an ADR -> `architecture.md`/`context.md` updated -> question removed. When hitting a decision point, check `open-questions.md` first; escalate new decisions there rather than making silent calls.

## Key documents

- [docs/context.md](docs/context.md) — product frame, what HuntReady is and is not
- [docs/architecture.md](docs/architecture.md) — system design, schema types, response shapes
- [docs/roadmap.md](docs/roadmap.md) — milestones M0-M5
- [docs/open-questions.md](docs/open-questions.md) — unresolved decisions (check before making architectural calls)
- [docs/adrs/](docs/adrs/) — 16 architecture decision records:
  - ADR-001: Authority preserved, not replaced
  - ADR-002: MCP server as canonical interface
  - ADR-003: Ingestion upstream and offline
  - ADR-004: Supabase Postgres + PostGIS
  - ADR-005: Python for ingestion, TypeScript for serving
  - ADR-006: Schema versioned from day one
  - ADR-007: Montana and Colorado as seed states
  - ADR-008: Verbatim regulation text
  - ADR-009: Agentic development as first-class project feature
  - ADR-010: Decomposed entity model (6 entities)
  - ADR-011: Shape C response envelope (null = not applicable, omitted = never)
  - ADR-012: Draw mechanics as sibling entity
  - ADR-013: Server returns structure, client composes presentation
  - ADR-014: `SourceCitation.document_type='gis_layer'` (type-layer enforcement)
  - ADR-015: `geometry.verbatim_rule` column + REG+COMMENTS handling rule
  - ADR-016: Digitization-tolerant containment for geometry overlays (area-ratio thresholds)

## Environment variables

- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_SECRET_KEY` — secret key (MCP server + ingestion)
- `SUPABASE_PUBLISHABLE_KEY` — publishable key (web app, scoped by RLS)
- `DATABASE_URL` — direct Postgres connection string (ingestion pipeline + migrations only; not used by serving stack per ADR-003)
- `MAPBOX_ACCESS_TOKEN` — Mapbox GL JS access token (web map)
- `HUNTREADY_INGESTION_CONTACT` — *recommended for ingestion runs.* Email or URL appended to the ArcGIS HTTP `User-Agent` as `(contact: <value>)`. Gives upstream data providers (state F&W agencies) a way to reach the operator if a fetch behaves unexpectedly. Empty/unset → User-Agent omits the contact suffix. Kept in env (not source) so the contact can change without a code edit.
