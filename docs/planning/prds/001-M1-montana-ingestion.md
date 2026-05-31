# PRD 001 — M1: Montana Ingestion

**Number:** 001
**Scope:** Milestone M1 (entire milestone; three epics)
**Status:** Active
**Date:** 2026-04-22
**Author:** Nick Kirkes
**Thinking-layer references:** [`roadmap.md`](../../roadmap.md), [`context.md`](../../context.md), [`architecture.md`](../../architecture.md), [`open-questions.md`](../../open-questions.md)
**Load-bearing ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md), [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-011](../../adrs/ADR-011-shape-c-response-envelope.md), [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md)

---

## Context

M0 (Frame locked) completed at tag `v0.0.0`. The repository has the full thinking layer committed — context, architecture, roadmap, thirteen ADRs, the schema-v2 proposal, and eight research documents. The four code directories (`ingestion/`, `mcp-server/`, `web/`, `plugin/`) contain hello-world scaffolds that lint and run but hold no business logic. Supabase is provisioned with PostGIS enabled; no tables exist yet.

M1 is the first milestone where code and data meet. It ingests Montana's hunting regulations into Postgres against the six-entity schema defined in `architecture.md`. It is the milestone where the schema stops being a design artifact and starts being a contract with real data on both sides of it.

This PRD exists because M1 is the first milestone with internal phase structure that benefits from explicit scoping before epic planning. M0 was simple enough that the roadmap + architecture gave the PM agent everything it needed to draft an epic directly. M1 is not — it has three genuine sub-phases with different risk profiles, and the sequencing between them is itself a decision worth surfacing here rather than letting a PM agent infer it.

## Outcome

When M1 is complete, the observable state of the world is:

- Montana regulations are present in Supabase Postgres, validated against the six-entity schema, covering the five V1 species (elk, mule deer, whitetail, pronghorn, black bear) across all applicable Hunting Districts, Bear Management Units, CWD zones, and Portions.
- The ingestion pipeline for Montana is reproducible — `make ingest STATE=montana` with Supabase credentials in `.env` produces the same loaded state every time.
- Spatial queries against Montana's unit boundaries work via PostGIS (`ST_Contains`, `ST_Intersects`).
- The schema has been stress-tested against real Montana data. If the schema required revision during M1, an ADR documents the change and migrations reflect it.
- RLS policies deny all access to `authenticated` and `anon` roles; only the service-role key can read or write. PostgREST consumer access is closed off structurally.
- Pre-commit hooks (lint, typecheck, secrets scanning) run on every commit. Tooling choice (Husky, `pre-commit`, lefthook) is decided at implementation time.
- A confidence calibration standard exists and is applied consistently across Montana extractions. An ADR documents the standard (resolving open-question Q11).
- The `m1` tag is pushed at the commit where M1 UAT passes.

The milestone exit criterion from the roadmap stands: *a second developer could, in theory, onboard Idaho using the Montana adapter as a reference, without further schema changes*. "In theory" is the honest standard; the real test comes in M2 (Colorado).

## In scope

**States:** Montana only.

**Species:** Elk, mule deer, whitetail, pronghorn, black bear. No small game. No waterfowl. No turkey.

**Entities:** All six entities per the schema-v2 proposal. Every entity is exercised by Montana's data:
- `regulation_record` — keyed by (state, jurisdiction_code, species_group, license_year)
- `season_definition` — weapon-specific and residency-specific windows
- `license_tag` — Montana A and B licenses for deer/elk (cross-referencing one `season_definition`), CWD-area tags, Portion tags, Bear Management Unit tags
- `draw_spec` — Montana's species licenses and permits with relevant allocation mechanics
- `reporting_obligation` — mandatory reporting, CWD sampling, Bear ID coursework
- `geometry` + `jurisdiction_binding` — HDs, BMUs, CWD zones, Portions, with their overlay relationships

**Geometries:** MT FWP ArcGIS MapServer `admbnd/huntingDistricts` as the canonical source per Q1 resolution. All 40 layers, scoped to the V1 big-game layers.

**Regulation text:** Three published PDFs per Q1 resolution — DEA biennial booklet, Black Bear annual booklet, Legal Descriptions biennial booklet — plus ad-hoc correction PDFs. All text carried verbatim per ADR-001 and ADR-008.

**Phasing:** Three sequential epics (E01, E02, E03) as described below.

**Tooling gates:** Pre-commit hooks introduced as an M1 deliverable per the roadmap. Tool choice decided by the implementation agent during the first epic that touches it.

## Out of scope

Explicitly named to prevent scope creep:

- **Colorado.** Every Colorado-specific consideration belongs to M2. Colorado research artifacts exist and stay read-only during M1.
- **MCP server implementation.** The five MCP tools (`get_regulations`, etc.) are M3 work. M1 produces the data; M3 serves it. The MCP server scaffold from M0 stays as-is during M1.
- **Web companion.** M4 work. The web scaffold stays at its M0 placeholder.
- **Claude Code plugin.** M5 work.
- **RLS beyond deny-all.** The only RLS policies written in M1 are the deny-all policies that close off PostgREST consumer access. Any future user-scoped or tenant-scoped RLS belongs to V2 or later.
- **Exercising the `parameters` escape hatch.** `draw_spec.parameters` exists in the schema per Q12, but Montana's draw mechanics are expected to use named fields (`pools`, `point_system`, etc.) rather than the escape hatch. If Montana requires `parameters`, that is a finding worth surfacing and documenting, not a routine use.
- **Automated ingestion scheduling.** M1 ships a reproducible manual ingestion pipeline. Scheduled re-ingestion with drift detection is V2.
- **MCP tool exposure.** Even though the Montana data would technically be queryable through MCP by M1 end, no MCP tool is implemented to expose it. Queries against Montana data during M1 happen through direct Postgres (`psql`) or through the ingestion pipeline's load step for verification.
- **Any species beyond the five V1 species.** If Montana regulations incidentally cover additional species (turkey, small game, waterfowl) in the same source PDFs, those regulations are *not* ingested. The adapter filters to the five species; the other regulations stay in the source documents.
- **Any state-specific logic leaking into `ingestion/lib/`.** Shared code is shared. Montana-specific code lives in `ingestion/states/montana/`.
- **Any schema special-casing for Montana.** If Montana's data doesn't fit the schema cleanly, the schema gets improved (per ADR-006 and the "schema is the contract" operating principle in `context.md`). Montana-shaped hacks that work only for Montana are not acceptable.

## Phasing and rationale

M1 decomposes into three sequential epics. They run in order — E02 cannot start before E01's migrations apply, E03 cannot start before E02's jurisdictions are loaded. The dependencies are technical (foreign keys, table existence), not coordination constraints. The "Why sequential" section below documents them explicitly.

### E01 — Schema migrations and deny-all RLS

**Outcome:** Supabase Postgres contains all six entity tables as defined in the schema-v2 proposal, with deny-all RLS policies in place. The database is ready to receive data. No data has been written yet.

**Why first:** The schema is the contract. Every subsequent epic reads from it or writes to it. Getting the DDL correct and the RLS policies in place before any data lands means the first real row written is written against a known-good structure.

**Why isolated from ingestion:** E01 is mostly objective work — translate the TypeScript interfaces and Postgres DDL from `architecture.md` into timestamped migration files, verify they apply cleanly, set up RLS. The work is low-risk and high-certainty. Bundling it with ingestion would mix DDL risk with extraction risk and make it harder to attribute failures when they happen.

**Exit criteria for E01:** Migrations exist in `supabase/migrations/` and apply to a clean Supabase project without error. All six entity tables (plus `jurisdiction_binding`) are queryable. RLS is enabled on all tables with deny-all policies for `authenticated` and `anon` roles. The service-role key can read and write. A `SELECT COUNT(*)` against every table returns 0. The Python dataclasses in `ingestion/lib/schema.py` match the DDL one-to-one.

### E02 — Montana geometry ingestion

**Outcome:** All Montana geometries (HDs, BMUs, CWD zones, Portions) are loaded into the `geometry` table, and a `geometry-overlays.json` fixture captures their overlay relationships for E03 to consume. Spatial queries work.

**Why second:** Geometries are the anchor for every other entity — `regulation_record` references a jurisdiction, `license_tag` references jurisdictions via the binding table, `reporting_obligation` is region-specific. Having geometries in place before ingesting text makes the text ingestion's foreign-key targets already exist.

**Why before text:** Geometry ingestion is the lower-risk half of Montana. MT FWP publishes ArcGIS endpoints that return GeoJSON directly. The risks are known (coordinate reference systems, polygon validity, multi-part geometries along state lines) and mitigatable (`shapely.make_valid()`, explicit `geography(MultiPolygon, 4326)` columns). Getting this half done before the harder half means when the text ingestion hits PDF variance, the geometry layer is already stable and not a complicating factor.

**Exit criteria for E02:** All V1-relevant geometries loaded from MT FWP's ArcGIS MapServer. Every geometry passes `shapely.make_valid()`. Spot checks using `ST_Contains` against known Montana coordinates return correct HD/BMU identifications. a `geometry-overlays.json` fixture captures HD → Portion, HD → CWD-zone, and HD → restricted-area overlay relationships for E03's S03.6.1 + S03.10 to consume when writing `jurisdiction_binding` rows. Fetching the geometries is reproducible — `make ingest STATE=montana STAGE=geometry` can re-run the fetch without corrupting existing data.

### E03 — Montana regulation text ingestion

**Outcome:** Every regulation record, season definition, license tag, draw spec, and reporting obligation for Montana's five V1 species is in Postgres, sourced from the three published PDFs plus corrections. Text is verbatim per ADR-008. Confidence is calibrated per the resolution of Q11 (which resolves during this epic).

**Why third:** This is the hard half. PDF extraction has real variance — inconsistent table structures, mid-sentence species references, corrections that supersede booklet content, regulations that reference external sources. Q11 resolves here, because confidence calibration is only meaningful against real extraction output. Bundling schema work (E01) or geometry work (E02) with this would concentrate risk in a single epic and make blockers harder to isolate.

**Exit criteria for E03:** All five V1 species have regulation_record rows for every applicable jurisdiction. Every row has a source citation (URL, agency, publication_date). Every row's `verbatim_text` field contains the extracted source text without paraphrase. `license_tag` rows correctly reference `season_definition` and `draw_spec` where applicable (including the A/B license cross-reference pattern from the schema-v2 proposal). `reporting_obligation` rows are present for CWD, Bear ID, and mandatory reporting. Confidence values are assigned per the Q11 resolution and the resolution is documented in an ADR.

### Why sequential

M1's three epics have hard technical dependencies that prevent parallelization:

- **E02 depends on E01.** E02 writes rows to the `geometry` table and `jurisdiction_binding` table. Those tables do not exist until E01's migrations apply. E02 cannot begin until E01's migrations are in place.
- **E03 depends on E02.** E03 writes `regulation_record`, `license_tag`, `reporting_obligation`, `jurisdiction_binding`, and other rows. The `jurisdiction_binding` rows FK to `geometry(id)` (a hard FK to a table E02 populates) and to `regulation_record` (the binding's anchor, written earlier within E03 itself). Bindings cannot be written until both FK targets exist — `geometry` from E02 and `regulation_record` from E03's earlier stories.
- **E03 depends on E01.** Even ignoring geometry entirely, E03 writes to every table except `geometry`. Those tables are created in E01.

The dependencies are all table-existence or foreign-key constraints, not coordination or review-bandwidth constraints. A team of three could not parallelize these epics either; the work is serial by structure.

The one piece of M1 work that *could* parallelize with the ingestion epics is the pre-commit hook installation (an M1 deliverable per the roadmap). It has no data or schema dependency. In practice it's simpler to fold it into E01 so the hooks are in place before any substantial code lands; that's a workflow choice, not a technical constraint, and the epic planning agent can revise if there's reason to split it out.

## Success criteria for the milestone (UAT level)

M1 is done when the following can be verified by hand or by script:

1. A query to `regulation_record` for (state=MT, jurisdiction_code=HD-262, species_group=elk, license_year=2026) returns a row with non-empty verbatim_text and a populated `sources` array.
2. A query joining `regulation_record` → `license_tag` → `season_definition` for HD 262 elk returns Montana's archery, general, and muzzleloader seasons as separate season_definition rows, with the A and B licenses both cross-referencing the appropriate seasons per the schema-v2 A/B pattern.
3. A PostGIS `ST_Contains` query with a coordinate inside HD 262 returns HD 262 as the matching geometry, plus any overlay BMU, CWD zone, or Portion that coordinate falls within.
4. A `regulation_record` row with no `sources` entry does not exist (validation enforces this at the ingestion layer).
5. A `geometry` row with invalid topology (per `ST_IsValid`) does not exist.
6. Re-running `make ingest STATE=montana` against an already-loaded database produces the same result (idempotent).
7. The `pg_roles` privileges for `authenticated` and `anon` show no rights on any of the six entity tables.
8. An ADR exists documenting the confidence calibration standard resolved during E03 (Q11).

The UAT prompt that drives this validation is drafted separately after E03 closes — its specifics depend on what emerges during E03. But the criteria above are the bar.

## Known risks and mitigations

**R1 — PDF extraction variance.** The three Montana PDFs have inconsistent structures, mid-sentence species references, and corrections that supersede booklet content. Mitigation: start with `pdfplumber` for primary extraction; use `unstructured` only if `pdfplumber` is insufficient (deferred to first Montana run per the schema-v2 research cycle). Budget extra time for E03. Flag to Nick if extraction quality is lower than expected; do not silently accept degraded output.

**R2 — MT FWP ArcGIS endpoint stability.** The endpoints are verified as of the April 2026 research cycle but are not publicly documented as stable APIs. Mitigation: capture canonical response shapes as fixtures during E02; if endpoints change, the fixtures let us detect the change and flag rather than silently break.

**R3 — Schema may require revision during E03.** The schema-v2 proposal anticipates this; ADR-006 commits to schema revision being the default response to real data stress. Mitigation: treat schema changes as expected, not exceptional. Any schema revision in E03 requires an ADR documenting the change and a migration file extending (not rewriting) the existing schema.

**R4 — Confidence calibration may not settle during E03.** Q11 is slated to resolve during E03, but if the resolution requires more data than Montana provides, it may defer to M2 (Colorado). Mitigation: if calibration is not settleable in E03, document the open-question state explicitly and defer the ADR to early M2. Do not block E03 on Q11's resolution if Montana alone is insufficient signal.

**R5 — Correction PDF handling.** Montana publishes ad-hoc correction PDFs that supersede sections of the biennial booklets. Mitigation: the ingestion pipeline must process corrections *after* booklets on every run, with the latest-dated source winning. The `publication_date` field on each `regulation_record` is the arbiter. Tension flagged in ADR-003.

**R6 — Lint-and-test hook false positives.** Pre-commit hooks introduced in M1 may generate noise during active ingestion work (e.g., secrets scanners flagging example test data). Mitigation: tune hook configs early, expect one or two rounds of revision before they settle. Do not disable hooks to paper over false positives; fix the config.

## Decisions already made

Load-bearing decisions that the PM agent and implementation agents should treat as fixed and reference rather than re-derive:

- **Hybrid ingestion strategy** — geometries from MT FWP ArcGIS, text from published PDFs, not `myfwp.mt.gov` endpoints. Q1 resolution.
- **Six-entity schema** — `regulation_record`, `season_definition`, `license_tag`, `draw_spec`, `reporting_obligation`, `geometry` + `jurisdiction_binding`. ADR-010.
- **`geography(MultiPolygon, 4326)` for all geometries.** ADR-012, architecture.md.
- **`shapely.make_valid()` applied before every geometry insert.** ADR-012.
- **Verbatim regulation text; no paraphrasing.** ADR-001, ADR-008.
- **Python for ingestion; TypeScript for serving.** ADR-005.
- **`schema_version` and `source_date` on every row.** ADR-006.
- **Deny-all RLS on all tables.** Per M1 roadmap deliverables, architecture.md.
- **Pre-commit hooks are a deliverable; tool choice is the implementation agent's call.** Per M1 roadmap deliverables.
- **A/B license cross-reference pattern.** Schema-v2 proposal.

## Open decisions resolved during M1

Resolved during or by the end of M1:

- **Q11 confidence calibration.** Resolves during E03. ADR drafted during or immediately after E03. If insufficient Montana-only signal, defers to early M2 with explicit documentation.
- **Pre-commit hook tool choice** (Husky vs `pre-commit` vs lefthook). Resolves when the implementation agent installs the first hook. Captured in the epic file that introduces the hooks (probably E01 since it's the first epic writing files that benefit from gating).

Not resolved during M1; remain open for M2 or later:

- **Q12 parameters enforcement.** Not exercised by Montana; revisits in M2 if Colorado requires it. If Colorado doesn't either, defers to a future state.
- **Q10 product name.** Unrelated to ingestion work.
- **Q13 public/license posture.** Post-V1 concern.

## Handoffs

### What M2 inherits from M1

- A working schema that Colorado can write against without modifications, unless Colorado surfaces new structure that requires schema extension (expected for Colorado's draw system).
- A working adapter pattern (`ingestion/states/montana/`) that Colorado can mirror.
- A shared library (`ingestion/lib/`) that handles PDF extraction, schema validation, geometry preparation, and Postgres writing — state-agnostic.
- A confidence calibration standard (probably). If Q11 deferred, M2 opens with calibration still unresolved and M2's plan should address this explicitly.
- Pre-commit hooks already in place. M2 benefits without additional setup.
- An established migration versioning pattern — M2's schema extensions (if any) follow the same timestamped-migration convention.

### What M3 inherits from M1

- Montana data queryable via Postgres. M3's MCP tools read from the same tables.
- A source-citation discipline that M3's tool responses honor — every response includes the `sources` array that was enforced at ingestion time.
- A confidence calibration that M3's responses can surface (the `LOW_CONFIDENCE` warning in `GetRegulationsResponse` references calibration established in M1).
- No MCP-server-facing API contracts. M3 defines those from the schema; M1 does not anticipate them.

### What the `m1` tag signals

`m1` on the commit where M1 UAT passes. The tag is the authoritative marker that Montana is done. Everything tagged `m1` or later can assume Montana is in Postgres, validated, and queryable.

## Non-goals beyond out-of-scope

Things the milestone is not optimizing for, even where they might seem adjacent:

- **Not optimizing for ingestion speed.** M1 ingests Montana once, in a reproducible way. Fast ingestion is not a V1 concern.
- **Not optimizing for storage efficiency.** `verbatim_text` may produce large rows. Compression and column-store are V2+ considerations.
- **Not optimizing for query performance.** Appropriate indexes per the schema definitions; no performance tuning beyond that.
- **Not producing documentation for external consumers.** The ingestion pipeline is internal. `ingestion/README.md` updates can happen but are not deliverables.

## What changes after this PRD

The following artifacts update when M1 progresses:

- `docs/planning/epics/` gains three epic files (E01, E02, E03) as each epic is planned.
- `docs/planning/README.md` updates to reflect M1 progress across the three epics.
- `docs/adrs/` gains at least one new ADR (Q11 confidence calibration) during or after E03.
- `docs/open-questions.md` removes Q11 from blocking when resolved; moves it to "recently resolved" with the ADR link.
- `CLAUDE.md` updates with M1 status as the milestone progresses.
- `CHANGELOG.md` accumulates M1 entries as stories merge.
- `schema-proposal-v2.md` may gain an addendum if the schema revised materially during E03.

This PRD itself does not typically update during M1 execution. If M1 scope changes materially (e.g., E03 discovers that Montana alone cannot settle Q11 and we need to re-scope), this PRD updates to reflect the new plan. Edits are tracked by commit history; no revision metadata block is needed.
