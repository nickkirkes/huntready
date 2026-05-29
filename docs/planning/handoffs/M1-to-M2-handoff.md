# M1 → M2 Handoff Document

**Date:** 2026-05-27
**Milestone status:** M1 complete — E01 + E02 + E03 all closed
**Final commit SHA:** `<COMMIT-SHA>` ← placeholder; user fills in at `git tag m1` time
**UAT runbook:** `docs/runbooks/M1-uat.md`

---

## §1 What M1 Built

M1 delivered a complete regulatory data backend for Montana V1 big-game hunting. All three epics were closed: E01 (schema migrations + RLS + quality gates), E02 (Montana geometry ingestion — 349 V1 rows across five geometry kinds), and E03 (Montana regulation text ingestion — 14 stories, S03.0 through S03.12). The 6-entity decomposed model (ADR-010) was fully operationalized with production data: regulation records, season definitions, license tags, draw specs, reporting obligations, geometry, and jurisdiction bindings all written for Montana 2026.

**What shipped:**

- All 3 epics complete (E01 schema + RLS; E02 Montana geometry ingestion; E03 Montana regulation text ingestion)
- 4 migrations applied: `20260425000000_initial_schema.sql`, `20260425000001_rls_deny_all.sql`, `20260428000000_geometry_verbatim_rule.sql`, `20260504032424_e03_schema_additions.sql`
- 11 tables operational with RLS deny-all policies (note: `license_season` RLS coverage is TBD per UAT criterion #7 — see §8)
- 6-entity decomposed model (ADR-010) fully operationalized for Montana
- State adapter pattern (`ingestion/states/montana/` as template for Colorado M2)
- Shared Python library (`ingestion/ingestion/lib/`: `arcgis`, `pdf`, `pdf_fetch`, `db`, `overlays`, `schema`)
- Confidence calibration framework (ADR-017 accepted; `ConfidenceTier` / `min_tier` / `demote_one_tier` helpers in `ingestion/ingestion/lib/pdf.py`)
- Doc-type precedence rule (ADR-019; `correction` rank > `annual_regulations` rank in multi-source merge)
- Pre-commit hooks: detect-secrets baseline, ruff, mypy, tsc
- E03 confidence calibration synthesis report (durable artifact at `docs/planning/epics/E03-confidence-calibration-synthesis.md`; survives m1 tag)
- Test suite: **1128 passed + 2 skipped** at M1 close

---

## §2 Schema Additions During M1

The four migrations add the following over the M0 scaffold:

- **ADR-014** (`document_type='gis_layer'`)  — `SourceCitation.document_type` extended to include the `gis_layer` value; enforces that geometry rows sourced from ArcGIS FeatureServers carry the correct citation type.
- **ADR-015** (`geometry.verbatim_rule` column + REG+COMMENTS separator rule) — nullable `text` column on `geometry`; populated from layer-#2 REG+COMMENTS combinations using the HuntReady-introduced `\n\n--- COMMENTS ---\n\n` separator. Shipped in `20260428000000_geometry_verbatim_rule.sql`.
- **ADR-018** (three E03 schema additions in `20260504032424_e03_schema_additions.sql`):
  - `license_season` link table — joins `license_tag` to `season_definition` many-to-many; the foundational data layer for criterion #2 asymmetric A/B coverage
  - `geometry.legal_description` column — nullable `text` column populated from the Legal Descriptions PDF extraction (S03.5 + S03.6)
  - `geometry.kind='state'` enum value — added to the `kind` CHECK constraint to support the `MT-STATEWIDE-geom` state-boundary geometry (S03.0)

---

## §3 Final V1 Montana Row Counts

| Table | Count | Notes |
|---|---|---|
| `regulation_record` | 437 | 32 high, 405 medium, 0 low |
| `season_definition` | ~978 | |
| `license_tag` | ~1225 | 388 limited_draw + 162 over_the_counter + 239 general + 1 statewide; 388 rows have `draw_spec_key` populated |
| `draw_spec` | ~278 unique (388 pre-collapse) | composite PK `(state, hunt_code, year)`; cross-listed licenses collapse |
| `reporting_obligation` | 3 | STATEWIDE 48-hr `harvest_report` + R1 `tooth_submission` (10-day) + R2-7 `hide_skull_presentation` (10-day) |
| `license_season` | ~3040 | link table; no state column |
| `regulation_season` | ~1385 | |
| `regulation_license` | ~1914 | |
| `regulation_reporting` | 70 | 35 (STATEWIDE) + 14 (R1) + 21 (R2-7) |
| `jurisdiction_binding` | ~1000 projected | **T16 operator-pending**; guard band `[400, 1100]`; first M2-week activity narrows to ±30% around empirical count |
| `geometry` | 350 | 349 V1 rows (235 HDs + 55 portions + 57 restricted areas + 2 CWD zones) + 1 `MT-STATEWIDE-geom` |

**Note on `jurisdiction_binding`:** the row count listed above is a pre-T16 projection. T16 live UAT is operator-pending (requires the batch sequence in `docs/runbooks/M1-uat.md` to complete). After T16 runs, `_BINDING_COUNT_GUARD_BAND` in `ingestion/states/montana/load_jurisdiction_bindings.py` must be narrowed to ±30% around the empirical count as the first M2-week activity.

---

## §4 ADRs Accepted During M1

All 19 ADRs are in `docs/adrs/`. ADR-017 status is `Accepted` (unmodified per S03.11 FINALIZE verdict, 2026-05-27). ADR-019 was accepted mid-E03 during S03.4 and applies to all future state adapters.

| ADR | Title | One-line summary |
|---|---|---|
| ADR-001 | Authority Preserved, Not Replaced | Every regulation record requires a source citation; no paraphrasing or summarization |
| ADR-002 | MCP Server as Canonical Interface | Web and plugin are clients of the MCP server; no surface bypasses it |
| ADR-003 | Ingestion Upstream and Offline | Python pipeline writes to Postgres; TypeScript serving stack never imports from ingestion |
| ADR-004 | Supabase Postgres + PostGIS | Single Supabase project for storage; PostGIS enabled in the `extensions` schema |
| ADR-005 | Python for Ingestion, TypeScript for Serving | Language boundary enforced at the architecture layer; state adapters are Python-only |
| ADR-006 | Schema Versioned from Day One | `regulation_record` and `draw_spec` carry `schema_version`; MCP server rejects unsupported versions |
| ADR-007 | Montana and Colorado as Seed States | MT for moderate complexity; CO for draw-system stress-test; all shared code must generalize across both |
| ADR-008 | Verbatim Regulation Text | Regulation text is carried verbatim — no normalization, no paraphrase, no summarization |
| ADR-009 | Agentic Development as First-Class | Documentation is the primary handoff mechanism between sessions; `open-questions.md` → ADR flow |
| ADR-010 | Decomposed Entity Model | 6-entity model: `regulation_record`, `season_definition`, `license_tag`, `draw_spec`, `reporting_obligation`, `geometry` + `jurisdiction_binding` |
| ADR-011 | Shape C Response Envelope | Structured envelope with always-present, null-bearing sections; null = not applicable, omitted = never |
| ADR-012 | Draw Mechanics as Sibling Entity | `draw_spec` is a sibling entity referenced from `license_tag` by FK; `parameters` escape hatch for state-specific quirks |
| ADR-013 | Server Returns Structure, Client Composes Presentation | No server-side `overview` or `headline` fields; each client composes its own summary |
| ADR-014 | `SourceCitation.document_type='gis_layer'` | Enforces correct citation type for geometry rows sourced from ArcGIS FeatureServers |
| ADR-015 | `geometry.verbatim_rule` Column + REG+COMMENTS Handling Rule | Nullable `text` column on `geometry`; HuntReady-introduced separator for layer-#2 REG+COMMENTS combinations |
| ADR-016 | Digitization-Tolerant Containment | Three-band area-ratio discriminator (ADR-016) for geometry overlay inclusion; built via local shapely + STRtree to avoid Supabase `statement_timeout` |
| ADR-017 | Confidence Calibration + Parent-Inheritance Rule | Defines `high`/`medium`/`low` calibration rules; confidence lives only on `regulation_record`; child entities inherit via query; `demote_one_tier` for correction-touched rows; **Status: Accepted, unmodified** |
| ADR-018 | E03 Schema Additions | `license_season` link table + `geometry.legal_description` + `geometry.kind='state'` value |
| ADR-019 | Doc-Type Precedence in Multi-Source Regulation Merge | `correction` rank > `annual_regulations` when merging multi-source regulation data; date is tiebreaker within same doc-type only |

---

## §5 What M2 Inherits

M2 (Colorado ingestion) picks up a complete, tested Montana foundation. No architectural decisions are left open for M2 to re-litigate; new ADRs are needed only when Colorado surfaces genuinely new patterns.

**M2 inherits:**

- Working schema with 4 migrations applied; PostGIS enabled at the `extensions` schema (all `ST_*` calls must be `extensions.`-prefixed — see `.roughly/known-pitfalls.md` under "Integration — Supabase / PostGIS")
- State adapter pattern at `ingestion/states/montana/` as the Colorado template; the four-file shape (`fetch_pdfs.py`, `extract_*.py`, `load_*.py`, `sources.yaml`) is established
- Shared Python library (`ingestion/ingestion/lib/`): `arcgis`, `pdf`, `pdf_fetch`, `db`, `overlays`, `schema` — all state-agnostic
- Confidence calibration framework (ADR-017): `ConfidenceTier`, `min_tier`, `demote_one_tier` in `ingestion/ingestion/lib/pdf.py`
- Doc-type precedence rule (ADR-019): applies to all future state adapters; correction PDFs always win over annual regulation booklets
- Pre-commit hooks: detect-secrets baseline, ruff, mypy, tsc
- Geometry overlay fixture format as Colorado template (`ingestion/states/montana/fixtures/geometry-overlays.json`)
- OQ7 row-count guard precedent: all adapter `main()` functions fire ±30% band guards before `db.connect()` — pattern must be applied to Colorado adapters
- Three-phase adapter shape (build → guards pre-`db.connect()` → conn/loops/commit/rollback/close) — established across S03.6 through S03.10
- Test suite: **1128 passed + 2 skipped** at M1 close; Colorado tests add to this baseline without touching Montana tests

---

## §6 Open Questions Status at M1 Close

| Q | Status | Action for M2 |
|---|---|---|
| Q11 | **RESOLVED 2026-05-27** | None — ADR-017 stands as-is; synthesis report durable at `docs/planning/epics/E03-confidence-calibration-synthesis.md` |
| Q12 | Parking lot | None — tracked in `docs/planning/epics/E03-deferred-items/draw-mechanics.md`; flag-and-defer per ADR-012; revisit if Colorado introduces similar draw-spec quirks |
| Q15 | **RESOLVED 2026-05-14** | None — section verbatim decomposed per OQ1; no `verbatim_text` column on `regulation_record`; decomposition documented in Q15 resolution note |
| Q16 | M2 revisit | Colorado may force species-specific licenses (mule-deer-only, no whitetail validity); revisit ADR-010 species granularity if that pattern appears |
| Q17 | M2 ADR-candidate | Per-HD allocation caps in `draw_spec`; HD 210 is the V1 case; detail in `docs/planning/epics/E03-deferred-items/draw-mechanics.md` |
| Q18 | M2 trigger: Colorado | CWD sampling target-table modeling; V1 ships zero rows (text in `regulation_record.additional_rules`); detail in `docs/planning/epics/E03-deferred-items/cwd-sampling-modeling.md` |
| Q19 | **RESOLVED 2026-05-29** | ADR-020 (Accepted) ships derive-and-assert via new `ingestion/ingestion/lib/drift_guard.py` with two primitives (`assert_dispatch_dict_drift_free` for compile-time dispatch dicts; `assert_id_matches` for runtime row-construction). Merged at `ccbe085` (PR #45). Test suite 1128 → 1165 + 2 skipped. M2 (Colorado) adopts the pattern when writing to `season_definition`, `license_tag`, or `reporting_obligation`. |

Q1–Q10, Q13–Q14: see `docs/open-questions.md` parking lot. None are M2-blocking.

---

## §7 Deferred Items (Survive Past m1 Tag)

The `docs/planning/epics/E03-deferred-items/` directory was designated at E03 kickoff as a durable carry-forward location for items too complex to resolve in V1 but too important to lose. Per ADR-017 §6, only this directory (not `E03-confidence-findings/`) survives the m1 tag.

| File | Summary |
|---|---|
| `README.md` | Retention policy for the deferred-items directory; defines what belongs here vs. the working-notes directory |
| `draw-mechanics.md` | Q12 deferrals: (a) 900-20 "first and only choice" ordering semantics; (b) Montana non-resident cap 10% structure (MCA 87-2-106) not currently modeled in `draw_spec`; (c) per-HD allocation caps for cross-listed B Licenses (Q17; HD 210 case) |
| `cwd-sampling-modeling.md` | Q18: target-table for CWD sampling obligations; V1 ships zero rows; license-keyed vs. zone-keyed authority is the core open question; revisit when Colorado lands a second CWD-zone state |
| `closure-temporal-anchors.md` | Temporal anchor modeling for `ClosurePredicate` (e.g., "at any point after May 31" in Spring Season Closure); `effective_after: date | null` is the candidate structural field; M2 ADR-candidate if the pattern recurs |

---

## §8 Known Issues to Escalate to M2

- **Q19 — RESOLVED 2026-05-29** via PR #45 (`ccbe085`) per ADR-020 (Accepted). New shared module `ingestion/ingestion/lib/drift_guard.py` (state-agnostic-clean per ADR-005; AST-locked by `TestNoStateAdapterImports`) ships two primitives: `assert_dispatch_dict_drift_free` for compile-time dispatch dicts (the S03.9 case — `_REPORTING_ROW_SPEC`) and `assert_id_matches` for runtime row-construction (the S03.7 case — the 4 build functions in `load_seasons_and_licenses.py`: `_build_dea_season_definitions`, `_build_bear_season_definitions`, `_build_dea_license_tags`, `_build_bear_license_tags`). Link-builder functions intentionally NOT instrumented — locked by `test_no_link_builders_have_asserts_regression_guard` AST guard. **`db.upsert_jurisdiction_binding` remains carve-out** (per S03.6.1 OQ-S6.1-4 the UPDATE clause excludes identity fields entirely — schema-level guarantee is strictly stronger than the application-level assert). The 3 SQL constants in `db.py` are **unchanged** — the assert lives at the dispatch-dict / row-construction layer, not in the SQL. Test suite delta: +37 tests (1128 → **1165 + 2 skipped**). **M2 adapters writing to `season_definition`, `license_tag`, or `reporting_obligation` MUST adopt the pattern**; `.roughly/known-pitfalls.md` § "id text-PK UPSERTs currently update slug-encoded fields on conflict" was rewritten in the same PR to reflect this. Full context: ADR-020 + `docs/open-questions.md` Q19.

- **`license_season` RLS gap — CONFIRMED at M1 UAT 2026-05-28** — `license_season` was added by `20260504032424_e03_schema_additions.sql` after the RLS deny-all migration `20260425000001_rls_deny_all.sql`. UAT criterion #7 surfaced **14 privilege leaks** (`SELECT`/`INSERT`/`UPDATE`/`DELETE`/`REFERENCES`/`TRIGGER`/`TRUNCATE` × {`anon`, `authenticated`}) AND **zero RLS policies** on `license_season`. Anyone with the publishable (anon) Supabase key can read/write the table directly — real exploitable data-integrity surface, not theoretical. **Per S03.12 pitfall #1, this does not block the m1 tag push**, but is **M2 week 1 work**. Fix scope:

  ```sql
  -- New migration: <timestamp>_rls_license_season.sql
  ALTER TABLE public.license_season ENABLE ROW LEVEL SECURITY;

  CREATE POLICY "Deny all access for anon"
    ON public.license_season FOR ALL TO anon
    USING (false) WITH CHECK (false);

  CREATE POLICY "Deny all access for authenticated"
    ON public.license_season FOR ALL TO authenticated
    USING (false) WITH CHECK (false);

  REVOKE ALL ON public.license_season FROM anon, authenticated;
  ```

- **PRD 001 jurisdiction_binding sequencing language** — PRD 001 lines 48, 90, 96, 111 still describe E02 as writing binding rows; the actual bindings are written by S03.6.1 and S03.10 (E03). The proposed reconciliation is captured in `docs/planning/epics/completed/E02-geometry-ingestion.md` § "Known issues to escalate" #1. Carries forward to M2 PRD review.

- **`role='other_overlay'` semantic awkwardness** — V1 no-hunt-zone bindings (Glacier NP, Sun River WMA, Yellowstone NP) use `role='other_overlay'` because no `no_hunt_zone` enum value exists in the DDL `role` CHECK constraint. M2 candidate: add `no_hunt_zone` to the `role` CHECK constraint via migration + ADR. Current `other_overlay` usage is correct per the DDL but semantically imprecise.

- **Colorado adapter `_STATE='US-CO'` filter** — S03.10 established the cross-state spatial filter pattern in `_query_nearby_hds_for_zone` (`hd.state = 'US-MT'`). Colorado's `load_jurisdiction_bindings.py` must mirror this with `_STATE = 'US-CO'` to prevent cross-state spatial pollution once Colorado geometry is loaded. Pattern is established; not a blocker, but must not be overlooked at M2 adapter implementation time.

- **S03.10 T16 live UAT — completed 2026-05-28.** Empirical jurisdiction_binding count: **788** (inside `[400, 1100]` guard band). Bear binding from S03.6.1 UPSERTed as no-op against the same id format as predicted. **First M2 PR narrows `_BINDING_COUNT_GUARD_BAND` to `[552, 1024]`** (±30% around 788) in `ingestion/states/montana/load_jurisdiction_bindings.py` and updates AC #1087 footnote in the E03 epic.

- **Cell-level source attribution** — V1 attributes binding and regulation source at row level per ADR-019's V1 simplification. Multi-source provenance schema field would be needed if a future state has multi-source HDs within a single geometry row. M2 ADR-candidate if Colorado data surfaces this pattern.

- **Free-prose non-NOTE HD-wide content in DEA** — currently has no structured DB home. V1 Montana DEA was expected to be empty-set (only `NOTE:` lines); S03.12 UAT spot-checks confirm this, but the gap is a known V1 simplification. M2 should verify Colorado DEA structure does not produce non-NOTE free prose that falls through.

### Runbook fixes needed before next run

Captured during M1 UAT 2026-05-28; flag-and-carry-forward only (the runbook was NOT modified during UAT — preserving audit trail of what was actually run). All edits land as part of M2-week-1 runbook hygiene PR.

1. **`docs/runbooks/M1-uat.md` §2 deviation note #3** — extend to: "HD 262 has no elk regulation_record at all (not just no A/B asymmetric pattern; the 2026 DEA booklet publishes no elk section for HD 262, only a deer section that fans out to mule_deer + whitetail). HD 124 substitutes for criterion #1 and criterion #2 part (a); HD 170 substitutes for criterion #2 part (b)."

2. **`docs/runbooks/M1-uat.md` §4 criterion #1 SQL** — change `jurisdiction_code = 'MT-HD-deer-elk-lion-262'` → `'MT-HD-deer-elk-lion-124'`. Update the section heading and PRD-text framing accordingly.

3. **`docs/runbooks/M1-uat.md` §4 criterion #2 part (a) SQL** — change `rr.jurisdiction_code = 'MT-HD-deer-elk-lion-262'` → `'MT-HD-deer-elk-lion-124'`. Update the "confirms HD 262 has data" framing to "confirms HD 124 has data".

4. **`docs/runbooks/M1-uat.md` §4 criterion #6 "Expected counts" table** — add a footnote distinguishing **build counts** (S03.7 reports 1225 license_tag / 3040 license_season at build time) from **post-UPSERT-collapse DB counts** (actual DB shows 825 license_tag / 2411 license_season after PK / link-row dedup). Both numbers are correct in their respective contexts; the runbook should make the distinction explicit so a future operator doesn't mark idempotency FAIL based on a build-count mismatch. Concrete deltas: regulation_record 437 build → 435 DB; license_tag 1225 build → 825 DB; license_season 3040 build → 2411 DB; regulation_license 1914 build → 1279 DB; regulation_season 1385 build → 1381 DB; draw_spec 388 build → 276 DB (S03.8 closure already noted the 388→278 collapse). Entity tables collapse via `INSERT … ON CONFLICT DO UPDATE`; link tables collapse via `ON CONFLICT DO NOTHING`.

5. **`docs/runbooks/M1-uat.md` §1 Prerequisites** — `psql` is not in the standard local toolchain. Add either (a) a "Tool prerequisites" item recommending `brew install libpq && brew link --force libpq`, OR (b) a footnote pointing to the supabase CLI substitute `supabase db query --db-url "$DATABASE_URL" "<sql>"` (the substitute used in the 2026-05-28 UAT run).

6. **`docs/runbooks/M1-uat.md` §4 criterion #8 bash command** — regex `grep -A1 -E '^(\*\*Status\*\*|Status):'` does not match the actual ADR-017 heading line `**Status:** Accepted` (asterisks wrap the colon, not just the word). Change to `grep -E '^\*\*Status:?\*\*'` or simpler `grep '^\*\*Status:\*\*'`.

7. **`ingestion/states/montana/load_jurisdiction_bindings.py` `main()`** — add `logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')` at the top of `main()`. The other 6 loaders configure logging implicitly; `load_jurisdiction_bindings.py` does not, which makes `--dry-run` exit 0 silently with no visible cross-tab or count output. M1 UAT 2026-05-28 worked around this with a runpy wrapper; the proper fix lives in the loader.

---

## §9 Final Commit + Tag Handoff

**Final commit SHA:** `<COMMIT-SHA>` ← placeholder; T9 verification confirms document placement; user fills in actual SHA at `git tag m1` time.

**PM to user handoff:**

After UAT signoff on `docs/runbooks/M1-uat.md` (all 8 criteria marked yes with operator initials and date), push the `m1` tag at the commit where this handoff document lands:

```bash
git tag m1 <COMMIT-SHA>
git push origin m1
```

M2 (Colorado ingestion) is the next milestone. The M2 epic file will be drafted in a fresh PM session. Start from `docs/planning/handoffs/M1-to-M2-handoff.md` (this document) + `docs/planning/epics/E03-deferred-items/` as the authoritative carry-forward context.
