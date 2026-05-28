# M1 UAT Results — 2026-05-28

**Operator:** PM Agent (Claude Code session)
**Batch run completed:** 2026-05-28 11:33 UTC-04 (S03.10 final write `Wrote 788 jurisdiction_binding rows`)
**Idempotency rerun completed:** 2026-05-28 13:23 UTC-04 (all 7 loaders re-executed; counts byte-identical)
**Branch:** main @ `a4657b2` (PR #43, S03.12)
**Runbook reference:** [docs/runbooks/M1-uat.md](M1-uat.md)
**Tooling note:** `psql` is not installed locally; all queries run via `supabase db query --db-url "$DATABASE_URL"` (output truncated to relevant `rows` arrays; untrusted-data envelope stripped).

---

## Summary

| # | Criterion | Result | Notes |
|---|---|---|---|
| 1 | regulation_record lookup | **PASS-with-noted-substitution** | HD 262 elk has no row at all; HD 124 elk substituted |
| 2(a) | regulation_record → license_tag join | **PASS-with-noted-substitution** | HD 262 elk has no row; HD 124 elk substituted |
| 2(b) | A/B asymmetric license_season coverage | **PASS** | HD 170 elk — exact S03.7 OQ-S7-3 outcome |
| 3 | PostGIS ST_Covers at HD 262 test point | **PASS** | HD 262 geometry exists independent of reg_record gap |
| 4 | No regulation_record with empty source | **PASS** | 0 leaks across 435 rows |
| 5 | No geometry with invalid topology | **PASS** | 0 invalid across 350 MT geometries |
| 6 | Idempotency (re-run produces same counts) | **PASS** (with runbook expected-count footnote) | 11/11 tables byte-identical pre/post re-run; runbook's "Expected counts" table mixes build-counts with DB-counts — see footnote below |
| 7 | pg_roles privileges + RLS policies | **FAIL (expected per S03.12 pitfall #1)** | `license_season` has 14 privilege leaks + 0 RLS policies; **M2 week 1 follow-up** |
| 8 | ADR-017 + synthesis report exist | **PASS** | ADR-017 Accepted (unmodified per S03.11 FINALIZE); synthesis 370 lines |

**Verdict:** **READY-TO-SIGN-OFF** (1 expected anomaly on #7; M2-week-1 carry-forward; not an m1-tag blocker per S03.12 closure note).

---

## Criterion #1 — regulation_record lookup

**Substitution applied:** `jurisdiction_code = 'MT-HD-deer-elk-lion-124'` (substituted from runbook's `MT-HD-deer-elk-lion-262`).

**Substitution rationale:** HD 262 elk has no regulation_record at all because the 2026 DEA booklet publishes no elk section for HD 262 — only a deer section, which fans out to mule_deer + whitetail. The runbook's §2 deviation note #3 was written under the wrong assumption (it stated HD 262 elk lacks A/B asymmetric pattern; in reality there is no elk regulation_record at all). HD 124 substituted; this extends the runbook's existing §2 deviation pattern (which already substituted HD 170 for criterion #2 part b on related-but-distinct grounds). HD 124 not 170 to preserve broader coverage; HD 170 is locked for #2(b) by `TestBuildDeaLinkRows::test_license_season_asymmetric_coverage_m1_criterion`.

**Confirmation query** (substitute exists):

```sql
SELECT jurisdiction_code, species_group, license_year
FROM regulation_record
WHERE state='US-MT' AND jurisdiction_code LIKE '%-124'
  AND species_group='elk' AND license_year=2026;
```

```json
[{"jurisdiction_code": "MT-HD-deer-elk-lion-124", "license_year": 2026, "species_group": "elk"}]
```

**Substituted criterion #1 SQL + result:**

```sql
SELECT state, jurisdiction_code, species_group, license_year,
       confidence, source, additional_rules
FROM regulation_record
WHERE state = 'US-MT'
  AND jurisdiction_code = 'MT-HD-deer-elk-lion-124'
  AND species_group = 'elk'
  AND license_year = 2026;
```

```json
[{
  "state": "US-MT",
  "jurisdiction_code": "MT-HD-deer-elk-lion-124",
  "species_group": "elk",
  "license_year": 2026,
  "confidence": "medium",
  "source": {
    "id": "mt-fwp-dea-2026-booklet",
    "url": "https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/2026-dea-regulations-final-with-low-resolution-maps-for-web.pdf",
    "title": "Deer, Elk, Antelope Hunting Regulations 2026",
    "agency": "Montana Fish, Wildlife & Parks",
    "document_type": "annual_regulations",
    "page_reference": "mt-fwp-dea-2026-booklet-2026-04-27.pdf:p48",
    "publication_date": "2026-04-27"
  },
  "additional_rules": [{
    "text": "NOTE: Swan River National Wildlife Refuge restricted to ArchEquip only.",
    "source": "(same source jsonb as above)",
    "confidence": "medium",
    "page_reference": "mt-fwp-dea-2026-booklet-2026-04-27.pdf:p48"
  }]
}]
```

**Pass conditions met:** 1 row ✓; `source` jsonb populated with `id`+`url`+`agency`+`publication_date` ✓; `confidence` = `"medium"` ∈ {high, medium} ✓; `additional_rules` is valid jsonb (1 NOTE entry) ✓.

---

## Criterion #2 — A/B asymmetric license_season coverage

### Part (a) — HD 124 elk (substituted from HD 262 per same rationale as criterion #1)

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

```json
[
  {"license_code": "Elk B License: 124-00", "license_name": "Antlerless Elk", "license_kind": "limited_draw"},
  {"license_code": "General Elk License",   "license_name": "Brow-tined Bull Elk", "license_kind": "general"}
]
```

**Pass conditions met:** ≥1 row ✓ (2 rows — General Elk License + Elk B License: 124-00).

### Part (b) — HD 170 elk (asymmetric demonstrator per S03.7 OQ-S7-3; locked by `TestBuildDeaLinkRows::test_license_season_asymmetric_coverage_m1_criterion`)

```sql
SELECT lt.license_code, lt.name AS license_name, lt.kind AS license_kind,
       sd.id AS season_id, sd.name AS season_name,
       sd.opens, sd.closes, sd.weapon_type
FROM regulation_record rr
JOIN regulation_license rl ON (rl.state, rl.jurisdiction_code, rl.species_group, rl.license_year)
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

**Coverage matrix (6 rows from result, formatted by license × season):**

| License | Archery Only | General | Heritage Muzzleloader | Late |
|---|---|---|---|---|
| **General Elk License** (A) | ✓ 2026-09-05 → 2026-10-18 (archery) | ✓ 2026-10-24 → 2026-11-29 | ✓ 2026-12-12 → 2026-12-20 (muzzleloader) | — |
| **Elk B License: 170-00** (B) | ✓ 2026-09-05 → 2026-10-18 (archery) | ✓ 2026-10-24 → 2026-11-29 | — | ✓ 2026-11-30 → 2027-02-15 |

**A-only:** {Heritage Muzzleloader} ✓
**B-only:** {Late} ✓
**Common:** {Archery Only, General}

**Pass conditions met:** exact S03.7 OQ-S7-3 outcome ✓. **M1 success criterion #2 demonstrated at the data layer.**

---

## Criterion #3 — PostGIS ST_Covers at HD 262 test point

```sql
SELECT id, name, kind
FROM geometry
WHERE extensions.ST_Covers(geom, extensions.ST_GeogFromText('SRID=4326;POINT(-114.0608 46.4281)'))
  AND state = 'US-MT';
```

```json
[
  {"id": "MT-HD-bear-216-geom",            "name": "Black Bear HD 216",    "kind": "hunting_district"},
  {"id": "MT-HD-deer-elk-lion-262-geom",   "name": "Deer/Elk/Lion HD 262", "kind": "hunting_district"},
  {"id": "MT-STATEWIDE-geom",              "name": "Montana",              "kind": "state"}
]
```

**Pass conditions met:** ≥1 row matching `MT-HD-deer-elk-lion-262-geom` ✓; same-species overlay (bear HD 216) + state-level (`MT-STATEWIDE-geom`) also returned. The `extensions.` prefix is required and functional. **The HD 262 geometry exists in the DB independent of the absent elk regulation_record gap** — geometries are loaded by E02 (S02.2-S02.5) and the state-level overlay by S03.0, neither of which depends on regulation_records.

---

## Criterion #4 — No regulation_record with empty source

```sql
SELECT COUNT(*) AS empty_source_count
FROM regulation_record
WHERE source IS NULL
   OR source = '{}'::jsonb
   OR source->>'id' IS NULL
   OR source->>'url' IS NULL;
```

```json
[{"empty_source_count": 0}]
```

**Pass conditions met:** 0 ✓. All 435 regulation_record rows have populated `source.id` and `source.url`. ADR-001 (authority preserved) verified empirically.

---

## Criterion #5 — No geometry with invalid topology

```sql
SELECT id, name, kind
FROM geometry
WHERE NOT extensions.ST_IsValid(
        extensions.ST_GeomFromText(extensions.ST_AsText(geom), 4326)
      )
  AND state = 'US-MT';
```

```json
[]
```

**Pass conditions met:** 0 rows ✓. All 350 MT geometries are topologically valid. CLAUDE.md's "Every geometry goes through `shapely.make_valid()` before insert" discipline confirmed empirically.

---

## Criterion #6 — Idempotency (re-run produces same row counts)

**Step 1 — Baseline (captured 2026-05-28 12:32 UTC-04, before re-run):**

| Table | Baseline | Post-rerun | Match |
|---|---|---|---|
| draw_spec | 276 | 276 | ✓ |
| geometry | 350 | 350 | ✓ |
| jurisdiction_binding | 788 | 788 | ✓ |
| license_season | 2411 | 2411 | ✓ |
| license_tag | 825 | 825 | ✓ |
| regulation_license | 1279 | 1279 | ✓ |
| regulation_record | 435 | 435 | ✓ |
| regulation_reporting | 70 | 70 | ✓ |
| regulation_season | 1381 | 1381 | ✓ |
| reporting_obligation | 3 | 3 | ✓ |
| season_definition | 978 | 978 | ✓ |

**Step 2 — Re-run** (all 7 loaders, 2026-05-28 13:13–13:23 UTC-04, ~10 min): completed cleanly with no exceptions. Per-loader final log lines confirm same build counts as first run:

- S03.0: `loaded geometry id=MT-STATEWIDE-geom`
- S03.6+S03.6.1: `total | 437` (build) + `legal_description updates: 228`
- S03.7: `loaded 978 season_definition + 1225 license_tag + 3040 license_season + 1385 regulation_season + 1914 regulation_license` (build counts)
- S03.8: `license_tags re-upserted: 1190. draw_specs written: 388. draw_spec_key backfills: 388`
- S03.9: `wrote 70 regulation_reporting link rows`
- S03.10: `Wrote 788 jurisdiction_binding rows`

**Step 3 — Post-rerun counts diff:** see table above. **11/11 tables byte-identical.**

**Pass conditions met:** idempotency confirmed at the DB layer ✓.

**Footnote — runbook expected-count discrepancy:** The runbook's §4 criterion #6 "Expected counts (post-batch-run)" table mixes loader **build counts** with post-UPSERT-collapse **DB counts**:

| Table | Runbook expected | Actual DB | Delta | Explanation |
|---|---|---|---|---|
| regulation_record | 437 | 435 | −2 | 2 PK collapses (cross-species near-duplicates) |
| license_tag | ≈1225 | 825 | −400 | S03.8 closure confirms 790 DEA + 35 bear = 825 unique identities |
| license_season | ≈3040 | 2411 | −629 | Link-row dedup via `ON CONFLICT DO NOTHING` |
| regulation_season | ≈1385 | 1381 | −4 | |
| regulation_license | ≈1914 | 1279 | −635 | Link-row dedup |
| draw_spec | ≈278 | 276 | −2 | |
| jurisdiction_binding | ∈[400, 1100] | 788 | inside | Unique by construction (`_JURISDICTION_BINDING_ID_FORMAT`) |
| reporting_obligation | 3 | 3 | 0 | |
| regulation_reporting | 70 | 70 | 0 | |
| geometry | 350 | 350 | 0 | |
| season_definition | ≈978 | 978 | 0 | |

This is **expected and correct** per CLAUDE.md's batch-run reconciliation note: entity tables UPSERT-collapse on PK; link tables dedup on `ON CONFLICT DO NOTHING`. The runbook's expected-count table needs a build-vs-DB footnote — captured as an M1→M2 handoff item below.

---

## Criterion #7 — pg_roles privileges + RLS policies — **FAIL (expected per S03.12 pitfall #1)**

### Query 1 — Privilege leaks on `anon` / `authenticated`

```sql
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND table_name IN ('regulation_record','season_definition','license_tag','draw_spec',
                     'reporting_obligation','geometry','jurisdiction_binding',
                     'regulation_season','regulation_license','regulation_reporting','license_season')
  AND grantee IN ('anon', 'authenticated');
```

**Expected:** 0 rows. **Actual:** 14 rows — all on `license_season`.

```csv
grantee,table_name,privilege_type
anon,license_season,DELETE
anon,license_season,INSERT
anon,license_season,REFERENCES
anon,license_season,SELECT
anon,license_season,TRIGGER
anon,license_season,TRUNCATE
anon,license_season,UPDATE
authenticated,license_season,DELETE
authenticated,license_season,INSERT
authenticated,license_season,REFERENCES
authenticated,license_season,SELECT
authenticated,license_season,TRIGGER
authenticated,license_season,TRUNCATE
authenticated,license_season,UPDATE
```

### Query 2 — RLS policy coverage

```sql
SELECT tablename, policyname, cmd
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;
```

**Expected:** ≥20 rows (2 policies per each of the 10 original tables). **Actual:** exactly 20 rows — **`license_season` completely absent from `pg_policies`**.

```csv
tablename,policyname,cmd
draw_spec,Deny all access for anon,ALL
draw_spec,Deny all access for authenticated,ALL
geometry,Deny all access for anon,ALL
geometry,Deny all access for authenticated,ALL
jurisdiction_binding,Deny all access for anon,ALL
jurisdiction_binding,Deny all access for authenticated,ALL
license_tag,Deny all access for anon,ALL
license_tag,Deny all access for authenticated,ALL
regulation_license,Deny all access for anon,ALL
regulation_license,Deny all access for authenticated,ALL
regulation_record,Deny all access for anon,ALL
regulation_record,Deny all access for authenticated,ALL
regulation_reporting,Deny all access for anon,ALL
regulation_reporting,Deny all access for authenticated,ALL
regulation_season,Deny all access for anon,ALL
regulation_season,Deny all access for authenticated,ALL
reporting_obligation,Deny all access for anon,ALL
reporting_obligation,Deny all access for authenticated,ALL
season_definition,Deny all access for anon,ALL
season_definition,Deny all access for authenticated,ALL
```

### Verdict — **FAIL (expected anomaly per S03.12 pitfall #1)**

**Root cause:** `license_season` was added by `20260504032424_e03_schema_additions.sql` after the RLS deny-all migration `20260425000001_rls_deny_all.sql`. The base RLS migration uses a flat IN-list that does not auto-extend to tables added by later migrations. `license_season` was never given `ENABLE ROW LEVEL SECURITY` or any DENY-ALL policy.

**Severity:** anyone with the anon (publishable) Supabase key can `SELECT` / `INSERT` / `UPDATE` / `DELETE` on `license_season`. The publishable key is intended to be exposed to web clients per ADR-002 / ADR-004; this is therefore a **real exploitable data-integrity surface**, not a theoretical gap.

**Per the runbook footnote at line 326:** this is a **pre-M2-blocker finding** flagged in the M1→M2 handoff. Does NOT block the m1 tag per S03.12 closure note — pitfall #1 anticipated this and pre-classified it as an M2-week-1 follow-up.

**Recommended M2-week-1 fix scope:**

```sql
-- New migration: <timestamp>_rls_license_season.sql
ALTER TABLE public.license_season ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for anon"
  ON public.license_season FOR ALL TO anon
  USING (false) WITH CHECK (false);

CREATE POLICY "Deny all access for authenticated"
  ON public.license_season FOR ALL TO authenticated
  USING (false) WITH CHECK (false);

-- Belt-and-suspenders: revoke direct table privileges
REVOKE ALL ON public.license_season FROM anon, authenticated;
```

---

## Criterion #8 — ADR-017 exists for Q11 confidence calibration

```bash
$ head -5 docs/adrs/ADR-017-confidence-calibration.md
# ADR-017: Confidence Calibration and Parent-Inheritance Rule

**Date:** 2026-05
**Status:** Accepted
**Decider:** Nick Kirkes

$ ls -la docs/planning/epics/E03-confidence-calibration-synthesis.md
-rw-r--r-- 1 nickkirkes staff 80879 May 27 19:29 docs/planning/epics/E03-confidence-calibration-synthesis.md

$ wc -l docs/planning/epics/E03-confidence-calibration-synthesis.md
370 docs/planning/epics/E03-confidence-calibration-synthesis.md
```

**Pass conditions met:** ADR-017 present with `Status: Accepted` ✓ (unmodified per S03.11 FINALIZE verdict); synthesis report 370 lines, 80KB ✓ (survives outside `E03-confidence-findings/` working-notes deletion target).

**Runbook gloss:** the runbook's bash command at line 350 uses regex `grep -A1 -E '^(\*\*Status\*\*|Status):'` which doesn't match the actual `**Status:** Accepted` formatting (asterisks wrap the colon, not the word). Fix candidate for M2-week-1: change regex to `grep -E '^\*\*Status:?\*\*'`.

---

## Operator notes / surfaced follow-ups (carry-forward, not runbook edits)

### Per-criterion items

1. **Criteria #1 + #2(a) — HD 262 elk has no regulation_record at all.** Runbook §2 deviation #3 was written assuming HD 262 elk lacks A/B asymmetry; reality is the 2026 DEA booklet publishes no elk section for HD 262 (only a deer section that fans out to mule_deer + whitetail). HD 124 substituted. HD 170 NOT used for #1/#2(a) because it's locked for #2(b) by `TestBuildDeaLinkRows::test_license_season_asymmetric_coverage_m1_criterion`.

2. **Criterion #6 — runbook expected-count table mixes build-counts with DB-counts.** See diff table above. Footnote needed in the runbook.

3. **Criterion #7 — `license_season` RLS gap CONFIRMED.** 14 privilege leaks + 0 RLS policies. M2-week-1 migration scope provided above.

4. **Criterion #8 — runbook regex glitch.** `^(\*\*Status\*\*|Status):` doesn't match `**Status:** Accepted` formatting.

### Tooling items

5. **`psql` not installed locally.** All queries run via `supabase db query --db-url "$DATABASE_URL"` (works fine; JSON-with-untrusted-data-envelope output; `-o csv` and `-o table` supported). Runbook should either footnote this substitute OR add a "Tool prerequisites" section recommending `brew install libpq && brew link --force libpq` for psql.

6. **`load_jurisdiction_bindings.py` doesn't call `logging.basicConfig`.** The other 6 loaders show INFO output by default; this one exits 0 silently. Needed a runpy wrapper with `logging.basicConfig(level=logging.INFO)` to see the cross-tab + dry-run count. Fix candidate: add `logging.basicConfig(level=logging.INFO)` at top of `main()` in the loader.

### Count band narrowing (S03.10 carry-forward)

7. **Narrow `_BINDING_COUNT_GUARD_BAND`** in `ingestion/states/montana/load_jurisdiction_bindings.py` from `[400, 1100]` to `[552, 1024]` (±30% around observed 788). Update AC #1087 footnote in the E03 epic. Tracked in S03.10 closure note as well.

---

## Sign-off

Pending — operator to sign off in [docs/runbooks/M1-uat.md §6](M1-uat.md#6-sign-off) after reviewing this results file.

After sign-off + results-file commit: `git tag m1 && git push --tags`.
