# M2 UAT Runbook — Colorado Ingestion

**Milestone:** M2 — Colorado Ingestion
**Date:** 2026-07-01
**PRD reference:** [PRD 002](../planning/prds/002-M2-colorado-ingestion.md) § "Success criteria for the milestone (UAT level)" (lines 113–128; **10 numbered success criteria**)
**Related ADRs:** [ADR-017](../adrs/ADR-017-confidence-calibration.md) · [ADR-020](../adrs/ADR-020-id-text-pk-slug-derivation.md) · [ADR-021](../adrs/ADR-021-jurisdiction-binding-no-hunt-zone-role.md) · [ADR-022](../adrs/ADR-022-single-module-per-state-extractors.md)
**Handoff:** [`docs/planning/handoffs/M2-to-M3-handoff.md`](../planning/handoffs/M2-to-M3-handoff.md)

This runbook operationalizes the **10** PRD 002 success criteria for M2 (Colorado). Each criterion has a SQL (or bash) block the operator runs against the **production** Supabase database and a results-capture slot for actual output. UAT is complete when all 10 criteria produce the expected result and the operator signs off in the sign-off section.

> **Sequencing — dev pass COMPLETE, prod pass NOT YET RUN.** The Colorado loaders were live-verified on the **dev** Supabase project across two operator passes: the M2-build pass (2026-06-23, E05 geometry + S06.5/S06.6 — captured in [`docs/runbooks/M2-operator-pass.md`](M2-operator-pass.md)) and the E06 Group B pass (2026-07-01, S06.7/S06.8/S06.9/S06.10 — captured in the now-deleted working note, content preserved in this runbook's Appendix A). **This runbook orchestrates the separate prod M2-release write**, which writes to production for the first time and produces the capture that gates the `m2` tag. Each criterion below pre-fills the **dev pre-verification** result and leaves a blank **prod actual output** slot.

---

## 1. Prerequisites

- **`psql` connected via service-role `DATABASE_URL`** (RLS bypass for read; anon/authenticated are denied all tables). If `psql` is unavailable, use the Supabase CLI substitute `supabase db query --db-url "$DATABASE_URL" "<sql>"` (the form used in the dev passes).[^psql]
- **All migrations applied** (`supabase db push` confirmed clean against the **prod** project). M2 adds exactly one migration over M1's five:
  - `20260603000000_jurisdiction_binding_no_hunt_zone_role.sql` (S05.3.5 / ADR-021; extends `jurisdiction_binding.role` CHECK to 8 values + reclassifies the 3 MT federal geometries' bindings `other_overlay` → `no_hunt_zone`). E06 adds **no** migrations.
- **Operator prod-write batch-run complete** (see section 3).
- **Ingestion venv available** at `ingestion/.venv/`. Set `HUNTREADY_INGESTION_CONTACT` (email/URL) before the geometry loaders' ArcGIS fetches.
- **Source PDFs present** at `ingestion/states/colorado/fixtures/` (the CPW Big Game brochure `co-cpw-big-game-2026-brochure-2026-03-04.pdf`, SHA-pinned; the S06.5 verbatim loader reads it locally — no fetch).

---

## 2. Spec Deviation + dev/prod Notes

PRD-002-vs-actual-DB deviations, for orientation (footnoted in the relevant criteria):

1. `jurisdiction_code` DB format is `CO-GMU-<int>` (e.g. `CO-GMU-1`), leading-zeros stripped — not `GMU-<code>` as PRD prose implies.
2. `make ingest STATE=colorado` (PRD SC #7) does not exist — no Makefile at repo root; the individual CO loader scripts (section 3) are canonical. Idempotency is re-running them (all UPSERT).
3. **CO ships 0 statewide-anchor `regulation_record` rows** — CPW publishes no CO statewide-anchor content analogous to MT's pronghorn `900-20` / MT's bear STATEWIDE anchor. The S06.6 `main()` guard fails loud on any unexpected `CO-STATEWIDE-*` pair. SC #1's representative-GMU lookup is per-GMU.
4. **Asymmetric license-coverage (PRD SC #2)** is present in CO — GMU 001 mule_deer (3 distinct license_tags D-M-001-O1-A / O1-M / O2-R, 1 season each) is the CO analog of M1's HD 170 A/B split; the asymmetric clause is NOT marked N/A.
5. **AFA 9+1 split (SC #4-adjacent):** of the 10 federal `restricted_area` geometries, 9 NPS/NM bind `role='no_hunt_zone'`; the 1 Air Force Academy row binds `role='other_overlay'` (regulated-access hunting area — Known Issue #12 RESOLVED via S06.10).
6. **MT baseline reconciliation — assert 435, not 437 (no dev/prod divergence):** MT `regulation_record` DB count is **435 on both dev and prod**. **437 is the loader _build_ count** — 2 build-rows share the composite PK and UPSERT-merge to 435 in the DB (the M1-documented build-vs-DB gap, not a dev/prod delta). **SC #9 (§9 below) asserts DB count = 435.** If the prod loader logs `total | 437`, that is expected and correct.[^devprod]

### 2.1 SQL conventions (read before running any query)

**(A) PostGIS idiom (Supabase):**
- All `ST_*` calls are `extensions.`-prefixed (PostGIS lives in the `extensions` schema — see `.roughly/known-pitfalls.md` § "Integration — Supabase / PostGIS").
- `ST_Covers(geom, <geography point>)` is a direct geography predicate — **no** WKT round-trip.
- Geometry-only functions (`ST_IsValid`, `ST_Envelope`, `ST_NumGeometries`) require the WKT round-trip `extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)` — Supabase rejects a bare `geom::geometry` cast (SQLSTATE 42846). Do NOT copy the E05-geometry-verification runbook's `geom::geometry` forms.

**(B) The 3 KI#18 stale-column corrections (distinct from the PostGIS idiom above; surfaced + corrected during the E06 Group B pass):**
1. `regulation_season` / `regulation_license` are scoped by **`state='US-CO'`** (they carry the composite key `(state, jurisdiction_code, species_group, license_year)`); there is **no** `regulation_record_id` column to filter on.
2. `draw_spec.inactive_forfeit_years` is **not a column** — it is an optional `point_system` jsonb field, omitted when null: `WHERE point_system->>'inactive_forfeit_years' IS NULL`.
3. `jurisdiction_binding` and `regulation_reporting` FK to `regulation_record` via the composite **`(state, jurisdiction_code, species_group, license_year)`** (no single `regulation_record_id`); `jurisdiction_binding` has **no `state` column** — scope CO rows via `geometry_id IN (SELECT id FROM geometry WHERE state='US-CO')` or via `regulation_record_state='US-CO'`.

---

## 3. Operator Prod-Write Batch-Run Sequence

These adapters write Colorado V1 data into the **prod** Supabase project. Production writes are operator-gated per the "live-DB write is operator-driven" pattern. Order matters (FK dependencies): geometry first, then the fixture build + spatial points, then regulation text, then link tables, then draw specs, then reporting obligations, then bindings.

```bash
# Set the ArcGIS contact header before geometry fetches:
export HUNTREADY_INGESTION_CONTACT="<operator email or URL>"

# --- E05 geometry (writes CO geometry rows) ---
ingestion/.venv/bin/python ingestion/states/colorado/load_state_boundary.py       # S05.0  -> CO-STATEWIDE-geom
ingestion/.venv/bin/python ingestion/states/colorado/load_gmus.py                 # S05.2  -> 186 GMU geometries
ingestion/.venv/bin/python ingestion/states/colorado/load_restricted_areas.py     # S05.4  -> 10 restricted_area geometries
ingestion/.venv/bin/python ingestion/states/colorado/build_overlay_fixture.py     # S05.5  -> geometry-overlays.json (commit the regenerated fixture)
# S05.7 spatial-test-points.json generator (see docs/runbooks/M2-operator-pass.md Step 6)

# --- E06 regulation text + links + bindings ---
ingestion/.venv/bin/python ingestion/states/colorado/load_restricted_area_verbatim.py # S06.5 -> 10 verbatim_rule updates
ingestion/.venv/bin/python ingestion/states/colorado/load_regulation_records.py       # S06.6 -> 398 regulation_record
ingestion/.venv/bin/python ingestion/states/colorado/load_seasons_and_licenses.py     # S06.7 -> 10,979 entity+link rows
ingestion/.venv/bin/python ingestion/states/colorado/load_draw_specs.py               # S06.8 -> 1914 draw_spec + 1914 backfills
ingestion/.venv/bin/python ingestion/states/colorado/load_reporting_obligations.py    # S06.9 -> 1 reporting_obligation
ingestion/.venv/bin/python ingestion/states/colorado/load_jurisdiction_bindings.py --dry-run  # S06.10 dry-run (band + AFA guards)
ingestion/.venv/bin/python ingestion/states/colorado/load_jurisdiction_bindings.py            # S06.10 -> 467 bindings + 46 reg_reporting
```

Each adapter exits 0 on success and prints a row-count summary. If any adapter exits non-zero, stop and diagnose before UAT. **Expected build/write counts (locked from the dev passes; these are the expected prod outcomes):** geometry 197 · reg_record 398 · S06.7 10,979 (2013+2470+2013+2013+2470) · draw_spec 1914 + 1914 backfills · reporting_obligation 1 · jurisdiction_binding 467 · regulation_reporting 46.

---

## 4. UAT Criteria (PRD 002 SC #1–#10)

### Criterion #1 (SC #1) — regulation_record lookup + downstream resolution (representative GMU, elk)

**PRD text:** "A query to `regulation_record` for (state=US-CO, jurisdiction_code=CO-GMU-<representative-GMU>, species_group=elk, license_year=2026) returns a row with populated `source`. Joining outward, the row resolves to at least one downstream `season_definition` and at least one `license_tag`."

```sql
-- Anchor row (representative GMU with elk coverage; substitute a GMU CPW publishes elk for, e.g. CO-GMU-201)
SELECT state, jurisdiction_code, species_group, license_year, confidence, source, additional_rules
FROM regulation_record
WHERE state = 'US-CO' AND jurisdiction_code = 'CO-GMU-201'
  AND species_group = 'elk' AND license_year = 2026;

-- Outward join to license_tag + season_definition (KI#18: link tables scoped by state, 4-part composite join)
SELECT lt.license_code, lt.kind AS license_kind, sd.id AS season_id, sd.name AS season_name
FROM regulation_record rr
JOIN regulation_license rl
  ON (rl.state, rl.jurisdiction_code, rl.species_group, rl.license_year)
   = (rr.state, rr.jurisdiction_code, rr.species_group, rr.license_year)
JOIN license_tag lt ON lt.id = rl.license_tag_id
JOIN license_season ls ON ls.license_tag_id = lt.id
JOIN season_definition sd ON sd.id = ls.season_definition_id
WHERE rr.state = 'US-CO' AND rr.jurisdiction_code = 'CO-GMU-201'
  AND rr.species_group = 'elk' AND rr.license_year = 2026
ORDER BY lt.license_code, sd.name;
```

**Expected result:** 1 anchor row with non-null `source` jsonb (`id`+`url`+`agency`+`publication_date`), `confidence` ∈ {high, medium}; ≥1 `license_tag` + ≥1 `season_definition` from the join. `additional_rules` may legitimately be empty (parity with M1 Q15).

**Dev pre-verification (2026-07-01):** 398 CO `regulation_record` rows written, 115 elk; every row's `source`/`confidence` populated (loader fail-loud + ADR-019 doc-type guard); outward joins resolve (S06.7 wrote 2013 season_definition + 2470 license_tag + 2013 license_season). Representative-GMU elk row confirmed present.

**Prod actual output:**
```
[paste output here]
```

---

### Criterion #2 (SC #2) — asymmetric license_season coverage (GMU 001 mule_deer)

**PRD text:** "A query joining `regulation_record` → `license_tag` → `license_season` → `season_definition` for a representative Colorado GMU returns the CPW-published weapon-window seasons as separate `season_definition` rows. If Colorado's data exercises an asymmetric license-coverage pattern, that pattern is observable in the join."

```sql
SELECT lt.license_code, lt.kind AS license_kind,
       sd.id AS season_id, sd.name AS season_name, sd.weapon_type
FROM regulation_record rr
JOIN regulation_license rl
  ON (rl.state, rl.jurisdiction_code, rl.species_group, rl.license_year)
   = (rr.state, rr.jurisdiction_code, rr.species_group, rr.license_year)
JOIN license_tag lt ON lt.id = rl.license_tag_id
JOIN license_season ls ON ls.license_tag_id = lt.id
JOIN season_definition sd ON sd.id = ls.season_definition_id
WHERE rr.state = 'US-CO' AND rr.jurisdiction_code = 'CO-GMU-1'
  AND rr.species_group = 'mule_deer' AND rr.license_year = 2026
ORDER BY lt.license_code, sd.name;
```

**Expected result:** GMU 001 mule_deer resolves to 3 distinct `license_tag` rows — `D-M-001-O1-A` (archery), `D-M-001-O1-M` (muzzleloader), `D-M-001-O2-R` (rifle) — each with 1 distinct `season_definition` (weapon-window-scoped). This is the CO analog of M1 criterion #2's A/B asymmetric coverage (PRD 002 SC #2).

**Dev pre-verification (2026-07-01, group-b FK/invariant capture):**
```
CO-GMU-1-mule_deer-D-M-001-O1-A-2026 -> 1 season (archery)
CO-GMU-1-mule_deer-D-M-001-O1-M-2026 -> 1 season (muzzleloader)
CO-GMU-1-mule_deer-D-M-001-O2-R-2026 -> 1 season (rifle)
=> 3 distinct tags × 1 season each => PRD 002 SC #2 LOCKED LIVE.
Locked in code by test_license_season_asymmetric_coverage_m2_criterion.
```

**Prod actual output:**
```
[paste output here]
```

---

### Criterion #3 (SC #3) — preference-point draw_spec

**PRD text:** "A query joining `license_tag` → `draw_spec` for a preference-point Colorado hunt returns a `draw_spec` row with `point_system.kind='preference_linear'`, a non-empty `allocation_pool[]` whose entries use `selection='rank_ordered_by_points'` and `selection='unweighted_random'`, and `residency_cap` populated where CPW publishes it."

```sql
-- Hybrid (2-pool) draw_spec via a backfilled license_tag; KI#18: inactive_forfeit_years is a point_system jsonb field
SELECT ds.hunt_code,
       ds.point_system->>'kind'                       AS point_kind,
       ds.point_system->>'inactive_forfeit_years'     AS inactive_forfeit_years,  -- jsonb field, NULL/absent expected
       ds.residency_cap->>'nonresident_max_share'      AS nr_max_share,
       ds.application_deadline,
       jsonb_array_length(ds.pools)                    AS pool_count,
       ds.pools
FROM license_tag lt
JOIN draw_spec ds ON ds.state = 'US-CO' AND ds.year = 2026 AND ds.hunt_code = lt.draw_spec_key
WHERE lt.id LIKE 'CO-%' AND lt.draw_spec_key IS NOT NULL
ORDER BY pool_count DESC
LIMIT 5;
```

**Expected result:** hybrid rows show `pool_count=2` with `selection='rank_ordered_by_points'` (share 0.80) + `selection='unweighted_random'` (share 0.20, `min_points=5`) and `nonresident_max_share=0.20`; non-hybrid rows show `pool_count=1` (`rank_ordered_by_points`, share 1.0) and `nonresident_max_share=0.25`. `point_kind='preference_linear'`; `application_deadline='2026-04-07'`; `inactive_forfeit_years` NULL.

**Dev pre-verification (2026-07-01, group-b 8-1…8-5):**
```
draw_spec state=US-CO year=2026                       -> 1914
point_system->>'inactive_forfeit_years' IS NULL       -> 1914
application_deadline='2026-04-07'                      -> 1914
pool composition: 1 pool -> 1801 (non-hybrid), 2 pools -> 113 (hybrid)
residency coupling: 1 pool -> 0.25 ; 2 pools -> 0.20
license_tag CO draw_spec_key IS NOT NULL              -> 1914  (556 remain NULL)
```

**Prod actual output:**
```
[paste output here]
```

---

### Criterion #4 (SC #4) — PostGIS ST_Covers + explicit `state='US-CO'` filter (spatial spot-check; AC #1111)

**PRD text:** "A PostGIS `ST_Contains`/`ST_Covers` query with a coordinate inside a known Colorado GMU returns that GMU as the matching geometry, plus any overlay CWD zone or restricted area the coordinate falls within. The query's SQL includes an explicit `state = 'US-CO'` filter."

Run against the 7 points in `ingestion/states/colorado/fixtures/spatial-test-points.json` (template shows GMU 20 — repeat per point):

```sql
SELECT id, kind, state
FROM geometry
WHERE extensions.ST_Covers(
        geom,
        extensions.ST_SetSRID(extensions.ST_MakePoint(-105.33913545510845, 40.319462349999995), 4326)::geography
      )
  AND state = 'US-CO';
-- Repeat for each fixture point; the Wyoming negative control (lat 41.5, lng -104.0) must return ZERO rows.
```

**Expected result:** each CO interior point returns its `expected_id_pattern` GMU (RA points also return the overlapping GMU + the RA — documented "both rows correct"); every CO interior point also returns `CO-STATEWIDE-geom`; the **Wyoming negative control returns 0 rows** with the `state='US-CO'` filter (PRD SC #4 partitioning verified).

**Dev pre-verification (2026-06-23, M2-operator-pass Step 7 §2 — ALL PASS):**
```
1 GMU20      -> CO-GMU-20-geom, CO-STATEWIDE-geom
2 GMU1       -> CO-GMU-1-geom, CO-STATEWIDE-geom
3 GMU201     -> CO-GMU-201-geom, CO-STATEWIDE-geom
4 RMNP       -> CO-GMU-20-geom, CO-restricted-rocky-mountain-national-park-geom, CO-STATEWIDE-geom
5 MesaVerde  -> CO-GMU-73-geom, CO-restricted-mesa-verde-national-park-geom, CO-STATEWIDE-geom
6 Statewide  -> CO-GMU-581-geom, CO-STATEWIDE-geom
7 WY-negctrl -> (zero rows)
```
(Source-review half of SC #4: `grep _STATE ingestion/states/colorado/load_jurisdiction_bindings.py` → `_STATE = "US-CO"` interpolated into the nearby-GMU SQL — confirmed.)

**Prod actual output:**
```
[paste output here — 7 points]
```

---

### Criterion #5 (SC #5) — no regulation_record with empty source

**PRD text:** "A `regulation_record` row for Colorado with no `source` does not exist."

```sql
SELECT COUNT(*) FROM regulation_record
WHERE state = 'US-CO'
  AND (source IS NULL OR source = '{}'::jsonb OR source->>'id' IS NULL OR source->>'url' IS NULL);
-- Expected: 0
```

**Expected result:** 0.

**Dev pre-verification (2026-07-01):** 398 CO rows written, all `source`-populated (S06.6 loader is fail-loud on empty source + fires the ADR-019 doc-type-widening guard on every written citation).

**Prod actual output:**
```
[paste output here]
```

---

### Criterion #6 (SC #6) — no geometry row with invalid topology

**PRD text:** "A `geometry` row for Colorado with invalid topology does not exist."

```sql
SELECT id, kind
FROM geometry
WHERE NOT extensions.ST_IsValid(extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326))
  AND state = 'US-CO';
-- Expected: 0 rows  (WKT round-trip required; ST_IsValid is geometry-only)
```

**Expected result:** 0 rows across the 197 CO geometries.

**Dev pre-verification (2026-06-23, M2-operator-pass Step 7 §3):** 0 invalid rows (all 197 CO geometries valid via `shapely.make_valid()` at ingest; the RMNP GeometryCollection was recovered per S06.6.2 with 0.0676% area-loss WARNING).

**Prod actual output:**
```
[paste output here]
```

---

### Criterion #7 (SC #7) — idempotency (re-run produces same row counts)

**PRD text:** "Re-running `make ingest STATE=colorado` against an already-loaded database produces the same result (idempotent)."

**Deviation:** `make ingest` does not exist; re-run the section-3 loaders. All UPSERT (entity: `ON CONFLICT DO UPDATE`; link: `ON CONFLICT DO NOTHING`).

**Step 1 — baseline counts:**
```sql
SELECT 'geometry' AS tbl, COUNT(*) FROM geometry WHERE state='US-CO'
UNION ALL SELECT 'regulation_record', COUNT(*) FROM regulation_record WHERE state='US-CO'
UNION ALL SELECT 'season_definition', COUNT(*) FROM season_definition WHERE id LIKE 'CO-%'
UNION ALL SELECT 'license_tag',       COUNT(*) FROM license_tag       WHERE id LIKE 'CO-%'
UNION ALL SELECT 'license_season',    COUNT(*) FROM license_season    WHERE license_tag_id LIKE 'CO-%'
UNION ALL SELECT 'regulation_season', COUNT(*) FROM regulation_season WHERE state='US-CO'   -- KI#18: scope by state
UNION ALL SELECT 'regulation_license',COUNT(*) FROM regulation_license WHERE state='US-CO'  -- KI#18: scope by state
UNION ALL SELECT 'draw_spec',         COUNT(*) FROM draw_spec         WHERE state='US-CO'
UNION ALL SELECT 'reporting_obligation', COUNT(*) FROM reporting_obligation WHERE id LIKE 'co-%'
UNION ALL SELECT 'jurisdiction_binding', COUNT(*) FROM jurisdiction_binding WHERE regulation_record_state='US-CO'  -- KI#18: no state col
UNION ALL SELECT 'regulation_reporting', COUNT(*) FROM regulation_reporting WHERE reporting_obligation_id LIKE 'co-%';
```

**Expected counts (locked from dev; expected prod outcomes):**

| Table | Expected count |
|---|---|
| geometry | 197 |
| regulation_record | 398 |
| season_definition | 2013 |
| license_tag | 2470 |
| license_season | 2013 |
| regulation_season | 2013 |
| regulation_license | 2470 |
| draw_spec | 1914 |
| reporting_obligation | 1 |
| jurisdiction_binding | 467 |
| regulation_reporting | 46 |

**Step 2 — re-run the section-3 loaders. Step 3 — re-capture + diff (must be byte-identical).**

**Dev pre-verification (2026-07-01, group-b re-run):** all 4 E06 loaders re-executed live → **zero deltas** (post-rerun CO snapshot byte-identical to post-write); no slug-drift, no symmetry violation.

**Prod baseline output:**
```
[paste output here]
```
**Prod post-re-run output (should be byte-identical):**
```
[paste output here]
```

---

### Criterion #8 (SC #8) — RLS / privileges on CO-populated tables

**PRD text:** "`information_schema.table_privileges` shows no rights for `authenticated` or `anon` on `license_season` or on any of Colorado's newly-populated tables, and `pg_policies` shows deny-all rows for each."

> **Note:** E06 created **no new tables** — Colorado populates the same 11 tables Montana uses. RLS coverage is the existing deny-all set (base migration + `20260530132727_rls_license_season.sql` from S04.1, which closed the M1 `license_season` gap). This criterion confirms that coverage holds on prod.

```sql
-- (a) no privileges to anon/authenticated on any entity/link table
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE table_schema='public'
  AND table_name IN ('regulation_record','season_definition','license_tag','draw_spec',
    'reporting_obligation','geometry','jurisdiction_binding',
    'regulation_season','regulation_license','regulation_reporting','license_season')
  AND grantee IN ('anon','authenticated');
-- Expected: 0 rows

-- (b) deny-all RLS policies present (incl. license_season)
SELECT tablename, policyname, cmd FROM pg_policies
WHERE schemaname='public' ORDER BY tablename, policyname;
-- Expected: >=22 rows (2 deny-all policies per each of the 11 tables)
```

**Expected result:** 0 rows from (a); ≥22 policy rows from (b), including 2 for `license_season`.

**Dev pre-verification:** the S04.1 migration (`20260530132727_rls_license_season.sql`) closed the M1 `license_season` gap in production and was Group-B-verified at S04.1 close (0 privilege leaks; 2 deny-all policies). No new CO table was added by E05/E06, so coverage is unchanged. Confirm on the prod project during this pass.

**Prod actual output (a):**
```
[paste output here]
```
**Prod actual output (b):**
```
[paste output here]
```

---

### Criterion #9 (SC #9) — Montana unchanged (test suite + row counts)

**PRD text:** "The Montana test suite continues to pass; M1 row counts in Postgres are unchanged."

```sql
SELECT 'regulation_record' AS tbl, COUNT(*) FROM regulation_record WHERE state='US-MT'
UNION ALL SELECT 'geometry',              COUNT(*) FROM geometry WHERE state='US-MT'
UNION ALL SELECT 'jurisdiction_binding',  COUNT(*) FROM jurisdiction_binding WHERE regulation_record_state='US-MT'
UNION ALL SELECT 'jurisdiction_binding_no_hunt_zone', COUNT(*) FROM jurisdiction_binding
    WHERE regulation_record_state='US-MT' AND role='no_hunt_zone';
```

**Expected result (prod):** regulation_record **435** (DB; loader logs `total | 437` build — 2 PK collapses[^devprod]) · geometry **350** · jurisdiction_binding **788** · of which `no_hunt_zone` **50** (reclassified at S05.3.5). Test suite: **2301 passed + 5 skipped** (`cd ingestion && .venv/bin/pytest tests/`).

**Dev pre-verification (2026-07-01, group-b Z-1…Z-4):** MT reg_record 435 (dev) / geometry 350 / jurisdiction_binding 788 / no_hunt_zone 50 — unchanged pre/post the entire M2 write. **Prod DB is also 435** (M1 UAT capture) — no dev/prod divergence.[^devprod]

**Prod actual output:**
```
[paste output here]
```

---

### Criterion #10 (SC #10) — coupled-PR ADR discipline

**PRD text:** "For every ADR accepted during M2, the coupled-PR discipline from `architecture.md` is observable in git: the ADR file, the migration SQL, the Python schema edit, and the TypeScript-type edit all land in the same commit."

**M2 ADR-with-schema-change = ADR-021** (the only M2 ADR carrying a schema migration; ADR-020 and ADR-022 are convention/library ADRs with no migration). Verify the S05.3.5 coupled PR:

```bash
# Find the migration commit, then confirm the 4 file kinds landed together
git log --follow --oneline -- supabase/migrations/20260603000000_jurisdiction_binding_no_hunt_zone_role.sql
git show <sha> --name-only   # expect: the migration + ingestion/ingestion/lib/schema.py + mcp-server/src/types/schema.ts + docs/architecture.md (+ overlays.py) together
```

**Expected result:** the ADR-021 migration commit (S05.3.5, `3344971`) shows the DDL migration + Python `schema.py` + TypeScript `schema.ts` + `architecture.md` in one commit (a 5-place sync — stricter than the 3-place minimum). ADR-020 and ADR-022 carry no migration → no coupled-PR obligation.

**Dev pre-verification:** ADR-021 5-place sync landed at S05.3.5 / `3344971` (verified at S05.3.5 close). No E06 ADR carried a migration.

**Prod actual output (git — env-independent):**
```
[paste output here]
```

---

## 5. Results Summary

| SC | Description | Pass? | Notes |
|---|---|---|---|
| #1 | regulation_record lookup + downstream resolution (elk) | | |
| #2 | asymmetric license_season coverage (GMU 001 mule_deer) | | |
| #3 | preference-point draw_spec (hybrid pools + residency) | | |
| #4 | ST_Covers + state='US-CO' (7 spatial points; WY negctrl=0) | | |
| #5 | no regulation_record with empty source | | |
| #6 | no geometry with invalid topology | | |
| #7 | idempotency — CO counts byte-identical after re-run | | |
| #8 | RLS / no anon-authenticated privileges | | |
| #9 | Montana unchanged (435 DB/350/788/50; suite 2301+5) | | |
| #10 | coupled-PR ADR discipline (ADR-021 5-place sync) | | |

---

## 6. Sign-Off

| SC | Operator sign-off | Date |
|---|---|---|
| #1 | | |
| #2 | | |
| #3 | | |
| #4 | | |
| #5 | | |
| #6 | | |
| #7 | | |
| #8 | | |
| #9 | | |
| #10 | | |

**Milestone sign-off (operator completes after the prod pass):**

> [N] of 10 M2 UAT criteria PASS against the live **prod** Supabase project (batch run + idempotency re-run both completed <date>). Colorado V1 ingestion complete: 197 geometry + 398 regulation_record + 10,979 S06.7 entity/link + 1914 draw_spec + 1 reporting_obligation + 467 jurisdiction_binding + 46 regulation_reporting rows. Montana unchanged (435 reg_record DB/350/788/50). Full audit at `docs/runbooks/M2-uat-results-<date>.md`. M3 (MCP canonical interface) planning is unblocked.

Signed: ________________  Date: __________

**Note:** After UAT sign-off, the user pushes `git tag m2` at the commit where this runbook has full sign-off. See [`docs/planning/handoffs/M2-to-M3-handoff.md`](../planning/handoffs/M2-to-M3-handoff.md) §9.

---

## Appendix A — Dev pre-verification capture (preserved from `group-b-operator-pass.md` before ADR-017 §6 deletion)

> This appendix preserves the load-bearing dev-verification content from the E06 Group B working note (`docs/planning/epics/E06-confidence-findings/group-b-operator-pass.md`), which deletes at the `m2` tag per ADR-017 §6. Captured 2026-07-01 against dev project `eklivzoomtdluedzlyai` (never prod). The E05 geometry + S06.5/S06.6 dev capture lives durably in [`docs/runbooks/M2-operator-pass.md`](M2-operator-pass.md).

### A.1 Empirical dev row counts (= expected prod outcomes)

| Table | Count | Notes |
|---|---|---|
| geometry (CO) | 197 | 1 statewide + 186 GMU + 10 restricted_area |
| restricted_area verbatim_rule | 10 | 9 NPS/NM share the 130-char closure sentence; 1 AFA = 397-char access prose |
| regulation_record (CO) | 398 | mule_deer 141 / elk 115 / pronghorn 77 / whitetail 19 / bear 46; 0 statewide anchors |
| season_definition | 2013 | |
| license_tag | 2470 | 1914 backfilled draw_spec_key; 556 NULL |
| license_season | 2013 | |
| regulation_season | 2013 | |
| regulation_license | 2470 | |
| draw_spec | 1914 | 113 hybrid + 1801 non-hybrid |
| reporting_obligation | 1 | co-bear-mandatory-check-5day-statewide (verbatim_rule 1238 chars) |
| jurisdiction_binding | 467 | primary_unit 398 / no_hunt_zone 63 / other_overlay 6 |
| regulation_reporting | 46 | 1 STATEWIDE bear obligation × 46 bear reg_records |
| **MT (untouched)** | 435 reg_record DB (dev = prod; 437 is the build count) · 350 · 788 · 50 no_hunt_zone | PRD 002 SC #9 |

### A.2 Corrected verification SQL (KI#18 applied — the queries the operator actually ran)

```
7-1 season_definition  id LIKE 'CO-%'              -> 2013
7-2 license_tag        id LIKE 'CO-%'              -> 2470
7-3 license_season     license_tag_id LIKE 'CO-%'  -> 2013
7-4 regulation_season  state='US-CO'               -> 2013   (KI#18: filter by state, not regulation_record_id)
7-5 regulation_license state='US-CO'               -> 2470   (KI#18)
8-1 draw_spec state=US-CO year=2026                                 -> 1914
8-2 draw_spec point_system->>'inactive_forfeit_years' IS NULL       -> 1914   (KI#18: jsonb field, not a column)
8-3 draw_spec application_deadline='2026-04-07'                      -> 1914
8-4 license_tag CO draw_spec_key IS NOT NULL                        -> 1914
8-5 license_tag CO draw_spec_key IS NULL                            ->  556
9-1 reporting_obligation id=co-bear-mandatory-check-5day-statewide (kind=mandatory_check, deadline_hours=120,
    submission_method=agency_office, applies_to_regions=NULL, what_to_present=['bear head','hide'])
9-2 verbatim_rule length=1238  has_full_prose('five working days')=True
10-1 jurisdiction_binding regrec_state=US-CO -> 467
10-2 role breakdown: primary_unit 398, no_hunt_zone 63, other_overlay 6 (NO portion, NO statewide self-binding)
10-3 AFA geometry as role='no_hunt_zone'  -> 0   (AC #1105 hard constraint)
10-4 AFA geometry as role='other_overlay' -> 6   (AC #1104)
10-5 regulation_reporting reporting_obligation_id=co-bear-...-statewide -> 46
FK validity (KI#18: composite-key joins, not regulation_record_id):
  jb -> regulation_record dangling -> 0 ; jb -> geometry dangling -> 0 ; regulation_reporting -> regulation_record dangling -> 0
```

### A.3 Idempotency (re-run zero deltas — 2026-07-01)

All 4 E06 loaders re-executed live → post-rerun CO snapshot byte-identical to post-write (season_def 2013 / license_tag 2470 / license_season 2013 / reg_season 2013 / reg_license 2470 / draw_spec 1914 / backfilled 1914 / reporting_obl 1 / bindings 467 / reg_reporting 46). MT unchanged (435/350/788/50). No slug-drift; entity tables UPSERT by id, link tables `ON CONFLICT DO NOTHING`.

### A.4 CO bear reporting_obligation `verbatim_rule` (1238 chars — for SC-adjacent faithfulness, PM UAT AC #1036/#1170)

```
Mandatory Bear Inspections & Seals Hunters must personally present their bear head and hide to any CPW office (see inside front cover) during normal business hours, or by appointment with a CPW officer, for a free inspection, check report and sealing within five working days after harvest. Bear heads and hides must be unfrozen when presented for inspec- tion. Seals must be attached to the hide until tanned. At inspection, CPW is authorized to extract and keep a premolar tooth. If the head and hide are frozen, CPW may keep them long enough to thaw so that a tooth can be removed. Hunters can help by making sure the jaw is propped open with a stick before rigor mortis sets in. Bears cannot be taken out of Colo- rado until head and hide are inspected and sealed. Having a bear hide without a seal after the five-day period is illegal, and the hide becomes state property. To transport a bear or parts to a foreign country, you must first obtain CITES documents. Contact the U.S. Fish and Wildlife Service, 303-342- 7430. Do not call the U.S. Fish and Wildlife Service about inspections or seals for bears. Meat does not need to be presented at the check, however all edible por- tions of meat must be prepared for human consumption.
```

---

## Footnotes

[^psql]: If `psql` is not installed locally (not part of the standard macOS toolchain), use the Supabase CLI substitute `supabase db query --db-url "$DATABASE_URL" "<sql>"` — same service-role DSN, same RLS bypass, same result shape. This is the form used in the dev passes. Alternative: `brew install libpq && brew link --force libpq`.

[^devprod]: **No dev/prod divergence exists.** MT `regulation_record` DB count = **435 on both dev and prod**. The **437** figure is the loader's in-memory **build count** (`load_regulation_records.py` logs `total | 437`); 2 of those build-rows share the composite PK `(state, jurisdiction_code, species_group, license_year)` and UPSERT-merge, leaving **435 rows in the DB**. Prod was captured at 435 in M1 UAT (`docs/runbooks/M1-uat-results-2026-05-28.md` line 222, 2026-05-28); dev is 435 (group-b pass, 2026-07-01). This is the same build-vs-DB gap already documented in `M1-to-M2-handoff.md` §3 (line 184: "regulation_record 437 build → 435 DB") and PRD 002 line 15 (which cites 435 as the post-UPSERT DB baseline). **SC #9 asserts the DB count 435.** If the prod loader logs `total | 437`, that is expected — it collapses to 435 in the DB. Full investigation: `docs/planning/investigations/mt-regulation-record-435-vs-437.md`. (This footnote previously misdescribed the gap as a "2-pronghorn dev/prod divergence / dev never received the post-S03.6.1 build" — corrected 2026-07-02; group-b action item A1 is resolved by that investigation.)
