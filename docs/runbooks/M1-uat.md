# M1 UAT Runbook — Montana Ingestion

**Milestone:** M1 — Montana Ingestion  
**Date:** 2026-05-27  
**PRD reference:** PRD 001 § "Success criteria for the milestone" (lines 122-129)  
**Related ADRs:** [ADR-017](../adrs/ADR-017-confidence-calibration.md) · [ADR-018](../adrs/ADR-018-e03-schema-additions.md) · [ADR-019](../adrs/ADR-019-doc-type-precedence-multi-source-merge.md)

This runbook operationalizes the 8 PRD success criteria for M1. Each criterion has a SQL (or bash) block the operator runs against the production Supabase database and a results-capture slot to paste actual output. UAT is complete when all 8 criteria produce the expected result and the operator signs off in the sign-off section.

---

## 1. Prerequisites

- **`psql` connected via service-role `DATABASE_URL`** (RLS bypass for read; anon/authenticated are denied all tables).[^11]
- **All 5 migrations applied** (`supabase db push` confirmed clean against the project):
  - `20260425000000_initial_schema.sql`
  - `20260425000001_rls_deny_all.sql`
  - `20260428000000_geometry_verbatim_rule.sql`
  - `20260504032424_e03_schema_additions.sql`
  - `20260530132727_rls_license_season.sql` (S04.1; closes the M1 UAT criterion #7 RLS gap — see §6 criterion #7 row)
- **Operator batch-run complete** (see section 3 below).
- **Ingestion venv available** at `ingestion/.venv/` for any Python snippets.

---

## 2. Spec Deviation Notes

Six PRD-vs-actual-DB deviations are footnoted in the relevant criterion sections. Summary for orientation:

1. `jurisdiction_code` format in the DB is `MT-HD-deer-elk-lion-262`, not `HD-262` as the PRD text says.
2. `verbatim_text` column does not exist on `regulation_record` — decomposed per Q15/OQ1.
3. HD 262 has no elk regulation_record at all (not just no A/B asymmetric pattern; the 2026 DEA booklet publishes no elk section for HD 262, only a deer section that fans out to mule_deer + whitetail). HD 124 substitutes for criterion #1 and criterion #2 part (a); HD 170 substitutes for criterion #2 part (b).
4. `make ingest STATE=montana` does not exist — no Makefile at repo root; individual loader scripts are canonical.
5. `license_season` may have an RLS gap — added after the RLS deny-all migration.
6. ADR-017 is unmodified (`Status: Accepted`) per the S03.11 FINALIZE verdict; criterion #8 is satisfied as-is.

---

## 3. Operator Batch-Run Sequence

These adapters write Montana V1 data into Supabase. The batch is operator-invoked because production writes are gated per the "live-DB write is operator-driven" pattern (see `.roughly/known-pitfalls.md` under "Conventions — Ingestion adapters"). Order matters: S03.0 first (writes `MT-STATEWIDE-geom`), then S03.6 + S03.6.1 (writes regulation_records + bear statewide anchor + populates `geometry.legal_description`), then S03.7 (season/license entity + link tables), then S03.8 (draw_specs), then S03.9 (reporting_obligations), then S03.10 dry-run + live (jurisdiction_bindings).

```bash
# Order matters: S03.0 first (writes MT-STATEWIDE-geom), then S03.6 (writes regulation_records
# + populates geometry.legal_description), then S03.6.1 (bear statewide anchor),
# then S03.7 (season/license entity + link tables), then S03.8 (draw_specs), then S03.9
# (reporting_obligations). Each adapter is operator-invoked per the established
# "live-DB write is operator-driven" pattern.

ingestion/.venv/bin/python ingestion/states/montana/load_state_boundary.py     # S03.0
ingestion/.venv/bin/python ingestion/states/montana/load_regulation_records.py # S03.6 + S03.6.1
ingestion/.venv/bin/python ingestion/states/montana/load_seasons_and_licenses.py # S03.7
ingestion/.venv/bin/python ingestion/states/montana/load_draw_specs.py         # S03.8
ingestion/.venv/bin/python ingestion/states/montana/load_reporting_obligations.py # S03.9

# Then S03.10:
ingestion/.venv/bin/python ingestion/states/montana/load_jurisdiction_bindings.py --dry-run
ingestion/.venv/bin/python ingestion/states/montana/load_jurisdiction_bindings.py
```

Each adapter exits 0 on success and prints a row-count summary. If any adapter exits non-zero, stop and diagnose before proceeding to UAT.

---

## 4. UAT Criteria

### Criterion #1 — regulation_record lookup (HD 124 elk 2026 — HD 262 substitution[^9])

**PRD text:** "Given a coordinate in HD 262, species=elk, date in season window, the system returns a regulation_record with non-empty verbatim_text and a source citation."

**Spec deviation note (verbatim_text):** `verbatim_text` does not exist as a column on `regulation_record`. Section-level verbatim was decomposed per Q15/OQ1 to `season_definition.verbatim_rule` and `license_tag.verbatim_rule`. This query verifies the regulation_record anchor: `source` jsonb populated, `confidence` set, and `additional_rules` valid. The verbatim decomposition is demonstrated by criterion #2's join query.[^1]

**Spec deviation note (jurisdiction_code):** PRD says `HD-262`; actual DB value is `MT-HD-deer-elk-lion-262`, encoded by `_dea_jurisdiction_code()` in `load_regulation_records.py:244-276`.[^2]

```sql
SELECT state, jurisdiction_code, species_group, license_year,
       confidence, source, additional_rules
FROM regulation_record
WHERE state = 'US-MT'
  AND jurisdiction_code = 'MT-HD-deer-elk-lion-124'
  AND species_group = 'elk'
  AND license_year = 2026;
```

**Expected result:** 1 row; `source` jsonb non-null with `id` + `url` + `agency` + `publication_date` keys; `confidence` ∈ {high, medium}; `additional_rules` is valid jsonb (may be empty array).

**Actual output:**

```
[paste psql output here]
```

---

### Criterion #2 — A/B asymmetric license_season coverage

**PRD text:** "A and B licenses for the same HD cover different season windows (e.g., B covers late season, A does not)."

**Spec deviation note (HD 262 → HD 170):** HD 262 elk lacks the asymmetric A/B pattern. HD 170 (Flathead River elk) is the asymmetric demonstrator per S03.7 OQ-S7-3 and is locked by `TestBuildDeaLinkRows::test_license_season_asymmetric_coverage_m1_criterion`. HD 262 is exercised only in criterion #3 (PostGIS point-in-polygon against the HD 262 geometry fixture); criterion #1 substitutes HD 124 per footnote [^9].[^3]

**Part (a) — HD 124 elk substitution: basic regulation_record → license_tag join (confirms HD 124 has data; HD 262 substituted per footnote [^9]):**

```sql
SELECT lt.license_code, lt.name AS license_name, lt.kind AS license_kind
FROM regulation_record rr
JOIN regulation_license rl
  ON (rl.state, rl.jurisdiction_code, rl.species_group, rl.license_year)
   = (rr.state, rr.jurisdiction_code, rr.species_group, rr.license_year)
JOIN license_tag lt ON lt.id = rl.license_tag_id
WHERE rr.state = 'US-MT'
  AND rr.jurisdiction_code = 'MT-HD-deer-elk-lion-124'
  AND rr.species_group = 'elk'
  AND rr.license_year = 2026
ORDER BY lt.license_code;
```

**Expected result (part a):** ≥1 row showing the elk licenses applicable to HD 124 (substituting for HD 262 per footnote [^9]).

**Actual output (part a):**

```
[paste psql output here]
```

**Part (b) — HD 170 elk: asymmetric A/B license_season coverage (M1 criterion #2 demonstrator):**

```sql
-- (b) HD 170 elk A/B asymmetric license_season coverage (M1 criterion #2 demonstrator)
--
-- Join chain explanation for operators new to the schema:
--   regulation_record    ── the anchor entity (per HD × species × year)
--   regulation_license   ── many-to-many link table: which license_tags apply to
--                          this regulation_record (one row per applicable license)
--   license_tag          ── the license/permit instrument (e.g., "General Elk License",
--                          "Elk B License: 170-00")
--   license_season       ── many-to-many link table per ADR-018: which seasons
--                          this specific license is valid in (A and B may differ)
--   season_definition    ── named date range with weapon/residency constraints
SELECT lt.license_code, lt.name AS license_name, lt.kind AS license_kind,
       sd.id AS season_id, sd.name AS season_name,
       sd.opens, sd.closes, sd.weapon_type
FROM regulation_record rr
JOIN regulation_license rl
  ON (rl.state, rl.jurisdiction_code, rl.species_group, rl.license_year)
   = (rr.state, rr.jurisdiction_code, rr.species_group, rr.license_year)
JOIN license_tag lt ON lt.id = rl.license_tag_id
JOIN license_season ls ON ls.license_tag_id = lt.id
JOIN season_definition sd ON sd.id = ls.season_definition_id
WHERE rr.state = 'US-MT'
  AND rr.jurisdiction_code = 'MT-HD-deer-elk-lion-170'
  AND rr.species_group = 'elk'
  AND rr.license_year = 2026
ORDER BY lt.license_code, sd.name;
```

**Expected result (part b):** General Elk License covers {archery_only, general, heritage_muzzleloader}; Elk B License: 170-00 covers {archery_only, general, late}. A-only = {heritage_muzzleloader}; B-only = {late}.

**Actual output (part b):**

```
[paste psql output here]
```

---

### Criterion #3 — PostGIS ST_Covers at HD 262 test point

**PRD text:** "Given a coordinate inside HD 262, the geometry lookup returns the correct HD polygon."

```sql
-- Test point from ingestion/states/montana/fixtures/spatial-test-points.json (HD 262)
-- All geometry rows containing point (lng -114.0608, lat 46.4281), MT-scoped
SELECT id, name, kind
FROM geometry
WHERE extensions.ST_Covers(geom, extensions.ST_GeogFromText('SRID=4326;POINT(-114.0608 46.4281)'))
  AND state = 'US-MT';
```

**Expected result:** ≥1 row matching `MT-HD-deer-elk-lion-262-geom` plus any same-species overlay portions/CWD/BMU. `ST_Covers(geography, geography)` is a direct geography predicate (no WKT round-trip needed; the round-trip in criterion #5 is required only for geometry-only functions like `ST_IsValid`).

**PostGIS prefix note:** PostGIS lives in the `extensions` schema in Supabase; all `ST_*` calls must be `extensions.`-prefixed per `.roughly/known-pitfalls.md` under "Integration — Supabase / PostGIS". The E02 runbook predates this pitfall and uses bare `ST_*` names — for M1 UAT, follow the prefixed form documented in known-pitfalls.md, not the E02 runbook's style.[^4]

**Actual output:**

```
[paste psql output here]
```

---

### Criterion #4 — No regulation_record with empty source

**PRD text:** "Every regulation_record has a populated source citation (URL, agency, publication date)."

```sql
SELECT COUNT(*) FROM regulation_record
WHERE source IS NULL
   OR source = '{}'::jsonb
   OR source->>'id' IS NULL
   OR source->>'url' IS NULL;
-- Expected: 0
```

**Expected result:** 0

**Actual output:**

```
[paste psql output here]
```

---

### Criterion #5 — No geometry row with invalid topology

**PRD text:** "All geometry polygons are topologically valid (no self-intersections, no unclosed rings)."

```sql
SELECT id, name, kind
FROM geometry
WHERE NOT extensions.ST_IsValid(
    extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)
)
  AND state = 'US-MT';
-- Expected: 0 rows
```

**Expected result:** 0 rows.

**Note:** `ST_IsValid` is geometry-only and Supabase rejects direct `geom::geometry` casts, so the `ST_GeomFromText(ST_AsText(geom), 4326)` round-trip is required. The `extensions.` prefix is required as documented in `.roughly/known-pitfalls.md` under "Integration — Supabase / PostGIS" (same authority as criterion #3).[^5]

**Actual output:**

```
[paste psql output here]
```

---

### Criterion #6 — Idempotency (re-run produces same row counts)

**PRD text:** "Re-running `make ingest STATE=montana` produces the same row counts as the first run."

**Spec deviation note (make ingest):** `make ingest STATE=montana` does not exist — no Makefile at repo root. The actual idempotency mechanism is re-running the individual loader scripts from the Operator Batch-Run Sequence (section 3). All adapters UPSERT, so row counts should be byte-identical pre/post re-run.[^6]

**Step 1 — Capture baseline counts before re-run:**

```sql
-- Idempotency baseline: capture before re-run, capture after, diff
SELECT 'regulation_record' AS tbl, COUNT(*) FROM regulation_record WHERE state='US-MT'
UNION ALL SELECT 'season_definition',     COUNT(*) FROM season_definition     WHERE id LIKE 'MT-%'
UNION ALL SELECT 'license_tag',           COUNT(*) FROM license_tag           WHERE id LIKE 'MT-%'
UNION ALL SELECT 'draw_spec',             COUNT(*) FROM draw_spec             WHERE state='US-MT'
UNION ALL SELECT 'reporting_obligation',  COUNT(*) FROM reporting_obligation  WHERE id LIKE 'mt-%'
UNION ALL SELECT 'jurisdiction_binding',  COUNT(*) FROM jurisdiction_binding  WHERE regulation_record_state='US-MT'
-- license_season has no state column (link table from license_tag to season_definition,
-- both of which carry MT-prefixed ids). Count is global; at UAT time only Montana
-- data is loaded, so this is effectively MT-scoped. If Colorado lands before UAT
-- runs, this row would include CO rows — operator must scope further if needed.
UNION ALL SELECT 'license_season',        COUNT(*) FROM license_season
UNION ALL SELECT 'regulation_season',     COUNT(*) FROM regulation_season     WHERE state='US-MT'
UNION ALL SELECT 'regulation_license',    COUNT(*) FROM regulation_license    WHERE state='US-MT'
UNION ALL SELECT 'regulation_reporting',  COUNT(*) FROM regulation_reporting  WHERE state='US-MT'
UNION ALL SELECT 'geometry',              COUNT(*) FROM geometry              WHERE state='US-MT';
```

**Expected counts (post-batch-run)[^10]:**

| Table | Build count | Post-UPSERT DB count | Notes |
|---|---|---|---|
| regulation_record | 437 | 435 | entity; `INSERT … ON CONFLICT DO UPDATE` (32 high, 405 medium, 0 low at build time) |
| season_definition | ≈978 | ≈978 | entity; no observed collapse delta |
| license_tag | 1225 | 825 | entity; PK-keyed UPSERT collapses cross-listed B-Licenses |
| draw_spec | 388 | 278 | entity; composite PK `(state, hunt_code, year)` collapses |
| reporting_obligation | 3 | 3 | STATEWIDE + R1 + R2-7 |
| jurisdiction_binding | 788 | 788 | no collapse — id-keyed UPSERT; matches S03.10 T16 empirical 788; S04.2's `_BINDING_COUNT_GUARD_BAND = (552, 1024)` is centered on this value |
| license_season | 3040 | 2411 | link; `ON CONFLICT DO NOTHING` collapses (license_tag_id, season_definition_id) duplicates |
| regulation_season | 1385 | 1381 | link; `ON CONFLICT DO NOTHING` |
| regulation_license | 1914 | 1279 | link; `ON CONFLICT DO NOTHING` |
| regulation_reporting | 70 | 70 | 35 + 14 + 21; no observed collapse |
| geometry | 350 | 350 | 349 V1 rows + MT-STATEWIDE-geom |

**Baseline output (before re-run):**

```
[paste psql output here]
```

**Step 2 — Re-run the operator batch sequence** (section 3 above).

**Step 3 — Capture counts again and diff:**

```
[paste psql output here — should be byte-identical to baseline]
```

---

### Criterion #7 — pg_roles privileges

**PRD text:** "anon and authenticated roles have no SELECT privileges on any regulation table; service-role only."

```sql
-- Verify no rights granted to anon/authenticated on any entity or link table
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND table_name IN (
    'regulation_record','season_definition','license_tag','draw_spec',
    'reporting_obligation','geometry','jurisdiction_binding',
    'regulation_season','regulation_license','regulation_reporting','license_season'
  )
  AND grantee IN ('anon', 'authenticated');
-- Expected: 0 rows

-- Verify deny-all RLS policies are in place for each table
SELECT tablename, policyname, cmd
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;
-- Expected: at least 20 rows (2 policies per original 10 tables)
-- license_season RLS coverage check: see footnote
```

**Expected result:** 0 rows from the first query; ≥20 rows from the second query (2 deny-all policies per each of the original 10 tables).

**`license_season` RLS note:** `license_season` was added by `20260504032424_e03_schema_additions.sql` after the RLS deny-all migration `20260425000001_rls_deny_all.sql`. If the second query returns NO rows for `license_season`, this is a **pre-M2-blocker finding** — flag in the handoff document. The first query covers `license_season` in its table list; if NO rows appear in the first query either, the table is correctly deny-by-default (all default privileges revoked at schema level). If rows DO appear in the first query, the table has a permissions leak.[^7]

**Actual output (first query — privileges):**

```
[paste psql output here]
```

**Actual output (second query — RLS policies):**

```
[paste psql output here]
```

---

### Criterion #8 — ADR-017 exists for Q11 confidence calibration

**PRD text:** "An ADR exists documenting the confidence calibration methodology and Q11 resolution."

This criterion is a file-existence + status check, not a SQL query.

```bash
# Verify ADR-017 exists with Status: Accepted
grep '^\*\*Status:\*\*' docs/adrs/ADR-017-confidence-calibration.md
# Expected: Status: Accepted

# Verify synthesis report exists (durable audit record per S03.11)
ls -la docs/planning/epics/E03-confidence-calibration-synthesis.md
```

**Expected result:** ADR-017 present with `Status: Accepted` (unmodified per S03.11 FINALIZE verdict); synthesis report ~360 lines surviving outside the working-notes deletion target.[^8]

**Actual output:**

```
[paste shell output here]
```

---

## 5. Results Summary

Operator pastes final counts and a pass/fail per criterion after running UAT.

| Criterion | Description | Pass? | Notes |
|---|---|---|---|
| #1 | regulation_record lookup HD 124 elk (HD 262 substitution per footnote [^9]) | | |
| #2a | HD 124 elk license list (basic join, HD 262 substituted per footnote [^9]) | | |
| #2b | HD 170 elk A/B asymmetric coverage | | |
| #3 | ST_Covers at HD 262 test point | | |
| #4 | No regulation_record with empty source | | |
| #5 | No geometry with invalid topology | | |
| #6 | Idempotency — row counts stable after re-run | | |
| #7 | anon/authenticated have no table privileges | | |
| #7 (RLS) | deny-all RLS policies in place | | |
| #8 | ADR-017 Status: Accepted + synthesis report present | | |

---

## 6. Sign-Off

| Criterion | Operator sign-off | Date |
|---|---|---|
| #1 — regulation_record lookup | PASS (HD 124 substituted; HD 262 elk has no row — extends §2 deviation #3) | 2026-05-28 |
| #2 — asymmetric license_season coverage | PASS (part a HD 124 substituted; part b HD 170 per S03.7 OQ-S7-3) | 2026-05-28 |
| #3 — PostGIS point-in-polygon | PASS | 2026-05-28 |
| #4 — no empty source citations | PASS (0 leaks across 435 reg_record rows) | 2026-05-28 |
| #5 — no invalid geometry | PASS (0 invalid across 350 MT geometries) | 2026-05-28 |
| #6 — idempotency | PASS (11/11 tables byte-identical pre/post re-run; runbook expected-count footnote carry-forward) | 2026-05-28 |
| #7 — RLS / pg_roles | FAIL — accepted as M2 week 1 carry-forward per S03.12 pitfall #1 (`license_season` RLS gap; does NOT block m1 tag) — RESOLVED M2-W1 via `20260530132727_rls_license_season.sql` | 2026-05-28 |
| #8 — ADR-017 present + accepted | PASS | 2026-05-28 |

**Milestone sign-off:**

> 7 of 8 M1 UAT criteria PASS against the live Supabase project (batch run + idempotency re-run both completed 2026-05-28). **Criterion #7 FAILed** — `license_season` has 14 privilege leaks to `anon`/`authenticated` and zero RLS policies. This failure was pre-classified by S03.12 pitfall #1 as an expected M2 week 1 carry-forward (root cause: `license_season` was added by `20260504032424_e03_schema_additions.sql` after the base RLS migration's flat IN-list); **does not block the m1 tag push** per the same pitfall. Fix-migration scope is recorded in [`docs/planning/handoffs/M1-to-M2-handoff.md`](../planning/handoffs/M1-to-M2-handoff.md) §8. Montana V1 ingestion complete: 435 regulation_record + 825 license_tag + 788 jurisdiction_binding + 350 geometry rows. Full audit at [`docs/runbooks/M1-uat-results-2026-05-28.md`](M1-uat-results-2026-05-28.md). M2 (Colorado) PM kickoff is now unblocked.

Signed: Nick Kirkes  Date: 2026-05-28

**Note:** After UAT signoff is complete, the user should push `git tag m1` at the commit where this runbook has full signoff. See `docs/planning/handoffs/M1-to-M2-handoff.md` § "Final commit + tag handoff" for the handoff narrative.

---

## Footnotes

[^1]: PRD criterion #1 references "non-empty verbatim_text" — this column does not exist on `regulation_record`. Section-level verbatim was decomposed per Q15/OQ1 to `season_definition.verbatim_rule` and `license_tag.verbatim_rule`. Demonstrated by criterion #2's join query reaching `season_definition`.

[^2]: PRD says `HD-262`; the actual DB `jurisdiction_code` value is `MT-HD-deer-elk-lion-262`. The format encodes `{state_prefix}-HD-{species_list}-{hd_number}` and is derived by `_dea_jurisdiction_code()` in `load_regulation_records.py:244-276`.

[^3]: Spec named HD 262 for the asymmetric demonstrator; S03.7 closure shifted the target to HD 170 (Flathead River elk) because HD 262 elk lacks the A/B asymmetric license_season coverage pattern. Locked by `TestBuildDeaLinkRows::test_license_season_asymmetric_coverage_m1_criterion`. HD 262 is exercised only in criterion #3 (PostGIS point-in-polygon against the HD 262 geometry fixture in `spatial-test-points.json`); criteria #1 and #2 part (a) substitute HD 124 — see footnote [^9].

[^4]: PostGIS lives in the `extensions` schema in Supabase; all `ST_*` calls must be `extensions.`-prefixed per `.roughly/known-pitfalls.md` under "Integration — Supabase / PostGIS". The E02 runbook predates this pitfall and uses bare `ST_*` names — for M1 UAT, follow the prefixed form documented in known-pitfalls.md, not the E02 runbook's style.

[^5]: `ST_IsValid` is geometry-only (not geography-aware). Supabase rejects direct `geom::geometry` casts on geography columns, so the `ST_GeomFromText(ST_AsText(geom), 4326)` round-trip is required to convert geography → text → geometry before validity checking. The `extensions.` prefix applies to all three `ST_*` calls in this expression. Authority: `.roughly/known-pitfalls.md` under "Integration — Supabase / PostGIS".

[^6]: PRD says `make ingest STATE=montana`; no Makefile exists at the repo root. The actual idempotency mechanism is re-running the individual loader scripts (see Operator Batch-Run Sequence, section 3). All adapters UPSERT (`INSERT … ON CONFLICT UPDATE`) for entity tables and `ON CONFLICT DO NOTHING` for link tables, so row counts are byte-identical pre/post re-run.

[^7]: `license_season` was added by `20260504032424_e03_schema_additions.sql` AFTER the RLS deny-all migration `20260425000001_rls_deny_all.sql`. The deny-all policies in that migration cover only the original 10 tables. If the `pg_policies` query returns zero rows for `license_season`, this is a **pre-M2-blocker finding** and must be flagged in `docs/planning/handoffs/M1-to-M2-handoff.md`. It is NOT being fixed in S03.12 — the scope is flag-and-carry-forward.

[^8]: ADR-017 status is `Accepted` (unmodified) per the S03.11 FINALIZE verdict (2026-05-27). The synthesis report at `docs/planning/epics/E03-confidence-calibration-synthesis.md` (~360 lines) is the durable audit record — it lives outside the `E03-confidence-findings/` working-notes deletion target and survives past the m1 tag per ADR-017 §6.

[^9]: HD 262 elk has no regulation_record (the 2026 DEA booklet publishes no elk section for HD 262 — see §2 deviation note #3). HD 124 substitutes for criterion #1 and criterion #2 part (a); HD 170 substitutes for criterion #2 part (b) (see §2 note #3 and footnote [^3]). Criterion #3 still uses HD 262 because the HD 262 geometry exists and is the canonical test-point fixture in `spatial-test-points.json`.

[^10]: Build counts are what the loaders report at `--dry-run` time (pre-database UPSERT); DB counts are what `SELECT COUNT(*)` returns after the live batch-run completes. Entity tables collapse via `INSERT … ON CONFLICT DO UPDATE` when the same PK appears in multiple builder paths (e.g., cross-listed B-Licenses); link tables collapse via `ON CONFLICT DO NOTHING` when the same (left_id, right_id) tuple appears multiple times in the build set. Both numbers are correct in their respective contexts: build counts validate the extraction/builder pipeline; DB counts validate the loaded state. Idempotency (criterion #6) is judged against DB counts pre/post re-run, NOT build counts. `jurisdiction_binding` shows no collapse because the loader UPSERTs by deterministic id and the cross-product produces no duplicate ids (the 788 figure matches S03.10 T16 empirical measurement and is the center of S04.2's narrowed `_BINDING_COUNT_GUARD_BAND = (552, 1024)`). **Provenance note for `draw_spec`:** the S03.8 closure (recorded in `CLAUDE.md`) is authoritative at 278 post-UPSERT DB rows; `docs/planning/handoffs/M1-to-M2-handoff.md` §8 #4 enumerated the delta as `388 → 276 DB` (a transcription error noted parenthetically in the same handoff bullet, which then cites the correct 388→278 collapse). The runbook value tracks the S03.8 closure.

[^11]: If `psql` is not installed locally (it is not part of the standard macOS toolchain), the 2026-05-28 UAT run used the Supabase CLI substitute: `supabase db query --db-url "$DATABASE_URL" "<sql>"`. This connects via the same service-role DSN, returns the same shape of result rows, and bypasses RLS the same way `psql` does. Alternative: `brew install libpq && brew link --force libpq` to make `psql` available; pick whichever fits the operator's environment. The supabase-CLI form is the canonical preference because it matches what was actually run on 2026-05-28 (see [`docs/runbooks/M1-uat-results-2026-05-28.md`](M1-uat-results-2026-05-28.md)).
