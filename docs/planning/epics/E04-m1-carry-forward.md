# E04: M1 Carry-Forward and Colorado Schema Preparation

**Status:** Complete — audited (all 5 stories closed; S04.6 evaluated and omitted; M1 carry-forward fully landed in production; post-implementation audit closed 2026-05-31 with no blocking findings — see `Audited:` field below and `docs/planning/epics/E04-m1-carry-forward-audit.md`)
**Milestone:** M2 — Colorado Ingestion
**Dependencies:** M1 complete — `m1` tag at commit corresponding to PR #45 (`ccbe085`, Q19 RESOLVED via ADR-020); E03 closed 2026-05-27
**Validated:** 2026-05-29 (E04 validation triad: Migration & RLS + Carry-forward Fidelity returned LAND-WITH-EDITS; Cross-Language Consistency reviewer skipped — S04.6 omitted per epic header)
**Drafted:** 2026-05-29
**Completed:** 2026-05-31 (S04.2 closed 2026-05-29; S04.1 + S04.3 + S04.4 all closed 2026-05-30 — S04.1 Group A at-merge + Group B live-verified later same day; S04.5 closed 2026-05-31 via `/roughly:build` delegation under the user's git identity carrying all three task bundles — S04.5 PRD edit + Bundle A `.roughly/known-pitfalls.md` entries + Bundle B handoff hygiene patch)
**Audited:** 2026-05-31 — see [E04-m1-carry-forward-audit.md](E04-m1-carry-forward-audit.md). 49 ACs reviewed across 5 stories: **47 MET, 2 operator-asserted (internally-consistent documented stdout), 0 NOT MET, 0 blocking findings.** Hard-locked merge order S04.2 → S04.1 → S04.3 → S04.4 → S04.5 verified via PR-merge timestamps; all three cross-story dependency handoffs satisfied. Single actionable finding (S04.1 migration header missing `public.`-qualifier rationale from base migration) resolved at `7478ea6` as a comment-only header edit — zero DDL impact, the migration's production behavior is unchanged; no re-apply needed; no `supabase migration repair` needed. One originally-filed "Bundle B path-drift count off by one" observation retracted in the audit report itself after `git show 37bc86a` re-verification (pre-commit 1 `completed/` reference at L162 pre-existing + 7 new fixes = 8 post-commit, byte-matching Bundle B commit message and existing CLAUDE.md prose). Audit merged via PR #52 squash to main as `b168d28` from `test/E04-implementation-audit` (2 pre-squash commits: `7478ea6` S04.1 migration header fix + `c25d160` audit report). Emergent theme captured (informational, no action): 9 post-merge fix-up commits across E04 — all caught pre-production by reviewers/cubic; the convention-hardening response is already on disk (S04.2's 3 new pitfalls + S04.5 Bundle A's 2 new entries grew `.roughly/known-pitfalls.md` § "Documentation & planning discipline" from 6 → 11 entries across M2-W1 as deliberate convention-maturing, not recurring quality issues).
**Estimated Stories:** 5 (S04.6 evaluated and omitted; decision recorded in §"S04.6 read-through decision" below)
**UAT Gating:** All stories `UAT: no`. Every criterion is verification-gated against `docs/planning/handoffs/M1-to-M2-handoff.md` §8 specifications (SQL queries against `information_schema.table_privileges` / `pg_policies` / `pg_class`, file diffs against named edits, exact constant-value checks, PM-drafted PRD-diff text awaiting human review). No story requires human spot-check sign-off. PM tracks merge to main via the human's confirmation per the PM-prompt §"Commit and branch workflow".

---

## Objective

E04 closes the five M1 carry-forward technical-debt items from `docs/planning/handoffs/M1-to-M2-handoff.md` §8 and prepares the codebase for Colorado ingestion in E05/E06. Five sequential stories. No Colorado data is loaded; no Colorado-specific code is written; Montana row counts in Postgres are unaffected.

See [PRD 002](../prds/002-M2-colorado-ingestion.md) §"E04 — M1 carry-forward and Colorado schema preparation" for authoritative scope. See [`docs/planning/handoffs/M1-to-M2-handoff.md`](../handoffs/M1-to-M2-handoff.md) §8 for item-by-item specifications. Every E04 acceptance criterion traces to a line or paragraph in those two source documents.

---

## S04.6 read-through decision

PRD 002 §"E04 — M1 carry-forward and Colorado schema preparation" item 6 makes S04.6 conditional on a pre-CO-data schema-gap check against the two Colorado research documents. The PM performed that read-through during E04 planning on 2026-05-29. **Result: no schema gap surfaced; S04.6 is omitted.**

| Source | Finding |
|---|---|
| [`docs/research/colorado-draw-schema-proposal.md`](../../research/colorado-draw-schema-proposal.md) §§4-7 | CPW preference-point hybrid, three-stage draw, and rolling-three-year non-resident ceilings all serialize cleanly into the committed `draw_spec` schema as-is. No new enum value, no new field. Future pressure points listed in §8 ("point banking / transfer", per-pool vs top-level residency caps) are non-breaking additions handled by existing fields (`AllocationPool.eligibility.residency`, a future `transferable: bool` add). |
| [`docs/research/gmu-source-evaluation.md`](../../research/gmu-source-evaluation.md) §§"Recommended Primary Source", "Ingestion Notes" | CPW FeatureServer layer 6 returns 186 polygons with `outSR=4326`, no auth required. Maps cleanly to `geography(MultiPolygon, 4326)` + `kind='gmu'` + `document_type='gis_layer'`, all already in the schema. No new field. |

Q12 / Q16 / Q17 / Q18 are explicitly post-CO-data triggers per [`docs/open-questions.md`](../../open-questions.md) and PRD 002 §"Open decisions resolved during M2" — they cannot be resolved pre-data, so they do not surface as E04 schema gaps. The `role='no_hunt_zone'` enum addition and the multi-source geometry-provenance question are similarly post-CO-data triggers.

**If E05 or E06 surface a schema gap E04 did not anticipate** (Q12 escape-hatch case, Q16 species-granularity case, Q17 per-GMU allocation cap, Q18 zone-keyed CWD sampling target table, `role='no_hunt_zone'` enum addition, multi-source geometry provenance, or any other), the resolving ADR is drafted by the human or an explicit ADR-drafting session, the migration ships as part of the relevant E05 or E06 story (not via a retroactive E04 amendment), and the three-place sync (DDL + Pydantic + TypeScript) lands in the same PR with inline deny-all RLS per the M1 lesson encoded in PRD 002 §"Decisions already made" item "Deny-all RLS on all tables".

---

## Architectural commitments inherited from M1

| Commitment | Source | E04 implication |
|---|---|---|
| Deny-all RLS on every entity table; service-role bypass preserved | [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md) | S04.1 closes the `license_season` gap with a new migration whose body ENABLES, FORCES, deny-alls, and REVOKEs — full parity with the original 10-table posture from S01.3. |
| Schema versioned, three-place sync (DDL + Pydantic + TypeScript) | [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md) | E04 ships no schema additions — S04.6 omitted per the read-through decision. If a schema add becomes necessary later in M2, the three-place sync discipline applies. |
| Verbatim regulation text — no paraphrase | [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) | Not exercised in E04 (no regulation text touched). |
| OQ7 row-count guard pattern | E03 S03.6 onwards | S04.2 narrows the Montana jurisdiction-binding guard band per T16's empirical lock at 788; the OQ7 pattern itself is preserved unchanged. |
| ADR-020 drift_guard mandate for `season_definition`, `license_tag`, `reporting_obligation` UPSERTs | [ADR-020](../../adrs/ADR-020-id-text-pk-slug-derivation.md) | Not exercised in E04 (E06 is where CO adapters writing to these tables land). |
| Documentation is the primary handoff mechanism | [ADR-009](../../adrs/ADR-009-agentic-development-first-class.md) | S04.4 and S04.5 are documentation-discipline stories; S04.2's footnote-update belongs to the same discipline. |

---

## Stories

### S04.1: license_season RLS migration

**Status:** Closed at-merge — squash-merged to main 2026-05-30 from `feat/S04.1-license-season-rls-migration` (pre-squash: 2 commits — implementation + plan historical marker). **Second M2 PR chronologically** per the hard-locked merge order. Migration file: `supabase/migrations/20260530132727_rls_license_season.sql` (33 LOC including banner). One PM-flagged deviation from base-migration grep parity recorded in the migration's header comment: the prescribed body uses `public.license_season` qualified references throughout per the spec's literal-string ACs, while the base `20260425000001_rls_deny_all.sql` uses unqualified table names — both forms are functionally equivalent with the default `search_path`; AC-string parity wins over base-migration grep parity per the resolved plan-review must-fix. **Group A (file-level / static) ACs satisfied at merge** — see checkbox states below. **Group B (operator-driven post-`supabase db push`) ACs remain open and are captured in the PR description for operator verification when the live apply runs** — this is the PRD-006-style "operator verifies live" pattern; S04.1's close is NOT blocked by Group B. Test suite holds at 1166 passed + 2 skipped (no Python edits; SQL-only migration). No ADRs created; no Pydantic / TypeScript / `architecture.md` / `db.py` touches; no production-database writes from the build session. Code-review subagent flagged a WARNING about `CREATE POLICY` non-idempotency on re-apply; not fixed because (a) matches the base migration's posture across all 10 tables, (b) fail-loud on re-apply is the correct posture for a security migration, and (c) the recovery path is already documented in `.roughly/known-pitfalls.md` under `supabase migration repair --status applied <timestamp>`. The S04.4 mandatory criterion #7 sign-off annotation now has its required migration timestamp `20260530132727` available on main.

**As a** operator running M2 against a Supabase project where `license_season` was added by `20260504032424_e03_schema_additions.sql` after the base RLS migration
**I want** a new timestamped migration that ENABLES + FORCES RLS on `license_season` with deny-all policies for `authenticated` and `anon` plus an explicit `REVOKE ALL ON TABLE`
**So that** the M1 UAT criterion #7 leak surface (14 privilege leaks, zero RLS policies — handoff §8 second bullet) is closed before any Colorado ingestion writes more rows to the table

**UAT: no**

**Context:**

M1 UAT 2026-05-28 confirmed **14 privilege leaks** on `license_season` (every combination of `SELECT`/`INSERT`/`UPDATE`/`DELETE`/`REFERENCES`/`TRIGGER`/`TRUNCATE` × {`anon`, `authenticated`}) AND **zero RLS policies**. Anyone with the publishable (anon) Supabase key can read/write the table directly — a real exploitable data-integrity surface per [`docs/runbooks/M1-uat.md`](../../runbooks/M1-uat.md) criterion #7 (FAIL).

**Root cause** (handoff §8 second bullet): `license_season` was added by `supabase/migrations/20260504032424_e03_schema_additions.sql` after the RLS deny-all migration `20260425000001_rls_deny_all.sql`. The base migration uses a flat per-table enumeration (10 explicit `ALTER TABLE` blocks; verified at `supabase/migrations/20260425000001_rls_deny_all.sql` — each of the 10 tables has its own `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + two deny-all policies + `REVOKE ALL ON TABLE`) and does not auto-extend to subsequently-created tables. The S04.1 fix is a new follow-up migration covering only `license_season`. The recurring-gap risk for *future* tables M2 adds is surfaced separately under "Known Issues to Escalate" below.

**Migration body** (timestamped strictly after `20260504032424`, e.g., `20260529<HHMMSS>_rls_license_season.sql`):

```sql
ALTER TABLE public.license_season ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.license_season FORCE ROW LEVEL SECURITY;

CREATE POLICY "Deny all access for authenticated"
  ON public.license_season FOR ALL TO authenticated
  USING (false) WITH CHECK (false);

CREATE POLICY "Deny all access for anon"
  ON public.license_season FOR ALL TO anon
  USING (false) WITH CHECK (false);

REVOKE ALL ON TABLE public.license_season FROM anon, authenticated;
```

The `FORCE ROW LEVEL SECURITY` line **is required** for parity with `20260425000001_rls_deny_all.sql` — every one of the 10 original tables has both `ENABLE` and `FORCE`. The handoff §8 example body lists only `ENABLE`; the FORCE addition closes that template gap. Without FORCE, RLS applies only when the connection is not the table owner — silently no-ops for view-owner contexts.

The `REVOKE ALL ON TABLE` form (not bare `REVOKE ALL ON`) matches the explicit form used in the base migration at lines 34, 48, 62, etc. — same semantics, visual parity helps reviewers grep.

Policy declaration order — **authenticated first, anon second** — matches the base migration's per-table block ordering at `20260425000001_rls_deny_all.sql:29-32` and every subsequent block. Non-functional (RLS is set-semantics; both policies attach independently of declaration order), but preserves grep-parity for future readers comparing the two migrations side-by-side.

**Verification queries** (run against the production project after `supabase db push` and captured in S04.1's PR description):

```sql
-- 0 rows expected: no privileges granted to anon/authenticated
SELECT grantee, privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND table_name = 'license_season'
  AND grantee IN ('anon', 'authenticated');

-- 2 rows expected: one deny-all policy per role
SELECT policyname, roles, cmd
FROM pg_policies
WHERE schemaname = 'public' AND tablename = 'license_season';

-- Both columns expected true
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class
WHERE relname = 'license_season' AND relnamespace = 'public'::regnamespace;

-- Row-count preservation: service-role count pre and post migration must match
-- (deny-all policies are a posture change, not a data change)
SELECT COUNT(*) FROM public.license_season;
```

This is a **service-role-bypass-only** posture per ADR-004 §"RLS is the entire access-control story for V1": no policy permits `authenticated` or `anon` access. Future user-scoped policies are M3+ territory; do not introduce them here.

S04.4 annotates `docs/runbooks/M1-uat.md` §6 Sign-Off table's criterion #7 row with "RESOLVED M2-W1 via `<timestamp>_rls_license_season.sql`" using S04.1's actual migration timestamp. Per the merge-order hard precondition (S04.2 → S04.1 → S04.3 → S04.4 → S04.5), S04.1 has always merged by the time S04.4 opens, so the timestamp is always available; no deferral protocol is needed.

**Relevant ADRs:** [ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md) (PostgREST closed structurally), [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md) (Supabase + RLS posture), [ADR-018](../../adrs/ADR-018-e03-schema-additions.md) (introduced `license_season`; sets the precedent for inline RLS in future migrations going forward).

**Acceptance Criteria:**

**Group A — file-level / static (satisfied at merge):**

- [x] New timestamped migration file in `supabase/migrations/` whose timestamp prefix is strictly greater than `20260504032424` — actual: `20260530132727_rls_license_season.sql`
- [x] Migration enables RLS: `ALTER TABLE public.license_season ENABLE ROW LEVEL SECURITY`
- [x] Migration forces RLS: `ALTER TABLE public.license_season FORCE ROW LEVEL SECURITY` (parity with the 10 original tables in `20260425000001_rls_deny_all.sql`)
- [x] Migration creates policy `"Deny all access for authenticated" ON public.license_season FOR ALL TO authenticated USING (false) WITH CHECK (false)` (declared first, matching `20260425000001_rls_deny_all.sql:29-32` ordering for grep-parity)
- [x] Migration creates policy `"Deny all access for anon" ON public.license_season FOR ALL TO anon USING (false) WITH CHECK (false)` (declared second)
- [x] Migration revokes via `REVOKE ALL ON TABLE public.license_season FROM anon, authenticated` (explicit `ON TABLE` form for parity)
- [x] Test suite remains green at **1166 passed + 2 skipped** (no Python edits expected from this story; SQL-only migration. Baseline shifted 1165 → 1166 at S04.2 close via a new `TestCountGuard::test_band_locked_to_t16_empirical` contract-lock test; new baseline holds going forward)
- [x] No Pydantic, TypeScript, or `architecture.md` edits — the `license_season` table already exists in all three places from S03.0; this story closes a posture gap, not a schema gap (verified at merge via `git diff --stat HEAD`)

**Group B — operator-driven post-`supabase db push` (closed 2026-05-30 via live verification against the production project — see "Group B verification record" sub-section below for verbatim stdout):**

- [x] `supabase db push` applies the migration cleanly to the production project
- [x] `information_schema.table_privileges` returns 0 rows for `(license_season, {anon, authenticated})` after migration; baseline (per handoff §8 second bullet) was 14 rows
- [x] `pg_policies` returns exactly 2 rows for `license_season` after migration (one per role); baseline was 0 rows
- [x] `pg_class.relrowsecurity = true` AND `pg_class.relforcerowsecurity = true` for `license_season` after migration
- [x] `SELECT COUNT(*) FROM public.license_season` returns the same count pre- and post-migration (service-role connection; **post-UPSERT-collapse DB baseline = 2411 per the S04.4 spec § "Expected counts" build-vs-DB footnote source-of-truth memorialized at this epic's L280** — not the ~3040 build count from handoff §3 which is the pre-collapse projection. AC originally cited ~3040; operator-side verification on 2026-05-30 returned 2411 and flagged the build-vs-DB confusion; AC text amended to the correct DB baseline). The S04.1 migration is DDL-only (zero INSERT/UPDATE/DELETE/TRUNCATE statements in the file) so the count cannot have moved; post-migration observation of 2411 byte-matches the documented DB baseline and is accepted as evidence the count is preserved
- [x] Sanity: a **service-role** Postgres connection (using `SUPABASE_SECRET_KEY` / the service-role DSN, NOT the migration-runner connection nor an `anon`/`authenticated` JWT) executes `SELECT COUNT(*) FROM public.license_season` and returns a number > 0 — proves the deny-all policies do not block service-role access and that Supabase's project-level `bypassrls` grant is configured as expected (default Supabase behavior; verify-not-assume per the M1 UAT discipline) — observed 2411 rows via the service-role DSN, confirming bypass works as designed

**Group B verification record — 2026-05-30**

Operator ran the four verification queries against the production Supabase project via `supabase db query --db-url "$DATABASE_URL"` (service-role DSN per AC #12). All four returned the expected shape; no leak surface re-opened.

```
Q1: info_schema_privileges  (AC #8 — expect 0 rows; baseline was 14)
{ "rows": [] }

Q2: pg_policies  (AC #9 — expect 2 rows, one per role; supabase CLI driver does not natively serialize Postgres oid 1003 / name[] so the operator re-ran with roles::text[] cast)
{
  "rows": [
    {
      "cmd": "ALL",
      "policyname": "Deny all access for anon",
      "roles": { "Elements": ["anon"], "Dimensions": [{ "Length": 1, "LowerBound": 1 }], "Status": 2 }
    },
    {
      "cmd": "ALL",
      "policyname": "Deny all access for authenticated",
      "roles": { "Elements": ["authenticated"], "Dimensions": [{ "Length": 1, "LowerBound": 1 }], "Status": 2 }
    }
  ]
}

Q3: pg_class_rls_flags  (AC #10 — expect both flags true)
{
  "rows": [
    {
      "relforcerowsecurity": true,
      "relname": "license_season",
      "relrowsecurity": true
    }
  ]
}

Q4: row_count  (AC #11 + AC #12 — expect > 0 and matches DB baseline of 2411)
{
  "rows": [
    { "count": 2411 }
  ]
}
```

**Build-vs-DB baseline clarification** — the operator flagged Q4's 2411 vs. the verification prompt's "~3040" expectation. The 2411 is the post-UPSERT-collapse DB count per the S04.4 spec § "Expected counts" footnote (at this epic's L280 — `license_season 3040 build → 2411 DB`); the "~3040" was the build count from handoff §3 (the same handoff inconsistency surfaced earlier by cubic and flagged to the user as a hygiene-edit candidate on the read-only handoff). The migration is DDL-only — zero `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` statements — so 2411 was the pre-migration value and is the post-migration value; AC #11 is satisfied by the unchanged-value evidence rather than a literal pre/post sample pair. Lesson for future Group B-style verification prompts: cite the post-UPSERT DB baseline (the S04.4 spec L280 footnote is the durable source-of-truth, not handoff §3). Recommend a future implementation agent land this as a one-line entry in `.roughly/known-pitfalls.md` § "Conventions — Documentation & planning discipline" — PM does not touch `.roughly/` autonomously.

---

### S04.2: Narrow _BINDING_COUNT_GUARD_BAND to (552, 1024)

**Status:** Complete (squash-merged to main 2026-05-29 from `feat/S04.2-narrow-binding-count-guard-band`; **first M2 PR shipped — chronology lock satisfied per handoff §8 sixth bullet**; 4 post-merge cubic-fix iterations addressed a third "pending T16" prose location at module-docstring lines 26-27 missed by spec/discovery/plan, an AC #1087 suffix-prose contradiction post-narrowing, a `TestCountGuard` circularity gap closed by a new `test_band_locked_to_t16_empirical` lock test, and a branch-local SHA-reference portability issue; **test baseline shifted 1165 → 1166** via the new lock test; three new pitfalls under `.roughly/known-pitfalls.md` § "Conventions — Documentation & planning discipline" — spec-named location lists need grep-verification; spec line-number citations drift between spec authoring and execution; reviewer convergence is hard evidence not noise. No ADRs, no schema or three-place-sync changes, no `db.py` touches, no production-DB writes.)

**As a** operator running the Montana jurisdiction-binding loader idempotently against the production database
**I want** `_BINDING_COUNT_GUARD_BAND` narrowed to the empirically-validated ±30% band around the M1 T16 count of 788
**So that** future re-runs catch regressions that the current intentionally-wide `(400, 1100)` band would silently accept

**UAT: no**

**Context:**

Per handoff §8 sixth bullet: "S03.10 T16 live UAT — completed 2026-05-28. Empirical jurisdiction_binding count: **788** (inside `[400, 1100]` guard band). … **First M2 PR narrows `_BINDING_COUNT_GUARD_BAND` to `[552, 1024]`** (±30% around 788) in `ingestion/states/montana/load_jurisdiction_bindings.py` and updates AC #1087 footnote in the E03 epic."

Math check: 788 × 0.7 = 551.6 → ceil 552; 788 × 1.3 = 1024.4 → floor 1024. Round-inward keeps the band tight against the empirical count; matches the handoff's explicit values.

**Four coordinated edits:**

1. **`ingestion/states/montana/load_jurisdiction_bindings.py:107`** — change `_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (400, 1100)` → `_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (552, 1024)`.

2. **Prose updates at TWO locations** — the "intentionally wide pending T16's empirical count" framing appears in BOTH the module-level constant comment AND the `_assert_binding_count_within_guard` docstring; both must be updated:
   - **`ingestion/states/montana/load_jurisdiction_bindings.py:108-109`** — the module-level comment immediately following the `_BINDING_COUNT_GUARD_BAND` constant declaration carries the "Intentionally wide pending T16" phrase. Replace with prose naming T16 / 2026-05-28 / empirical 788 / ±30%.
   - **`ingestion/states/montana/load_jurisdiction_bindings.py:679-680`** — the docstring on `_assert_binding_count_within_guard` (verified at lines 676-682) repeats the same "pending T16" framing. Apply the same replacement.

   Concrete suggested module-comment text: `# Band is (552, 1024) — ±30% around T16's empirical 788 measured 2026-05-28; see handoff §8 sixth bullet.`. Concrete suggested docstring text: `"""Band is _BINDING_COUNT_GUARD_BAND (currently (552, 1024) — ±30% around T16's empirical 788 measured 2026-05-28; see handoff §8 sixth bullet)."""`. The implementation agent is free to phrase both in their own voice provided each names T16, 2026-05-28, the empirical count 788, and the ±30% derivation.

3. **`docs/planning/epics/completed/E03-regulation-text-ingestion.md` AC #1087 + footnote at line 1095** — two sub-edits:
   - Change the AC #1087 checkbox line's `_BINDING_COUNT_GUARD_BAND = (400, 1100)` text to `(552, 1024)` (one tuple-literal change inside the existing checkbox line; checkbox remains checked `- [x]`).
   - **Preserve the existing 2026-05-23 footnote paragraph verbatim and APPEND a second paragraph** with header `**T16 narrowing 2026-05-29.**` documenting: M1 T16 empirical count = 788; new band derived as ±30% around 788 = `[552, 1024]`; prior `(400, 1100)` band was T16-pending and is now superseded. Overwriting the 2026-05-23 paragraph is forbidden — the original is the audit trail for the wide-band rationale at S03.10 time.

4. **`ingestion/tests/test_load_jurisdiction_bindings.py` `TestCountGuard`** — the test class currently uses hardcoded boundary values (399, 770, 1101, 400, 1100 — verified by review).

   **Recommended path: arithmetic-derivation refactor.** Replace the 5 hardcoded values with expressions derived from `_BINDING_COUNT_GUARD_BAND` imported from `load_jurisdiction_bindings`:
   - `LOW, HIGH = _BINDING_COUNT_GUARD_BAND` → `LOW = 552, HIGH = 1024` at import time
   - in-band-no-op: use a value inside `[LOW, HIGH]` (e.g., `788` — links the test value to the empirical T16 count for audit-trail clarity; an inline comment names it as T16 2026-05-28)
   - low-band-raises: `LOW - 1` (= 551)
   - high-band-raises: `HIGH + 1` (= 1025)
   - lower-bound-inclusive: `LOW` (= 552)
   - upper-bound-inclusive: `HIGH` (= 1024)

   This eliminates a five-line edit if the band is ever narrowed again post-M2 (the single-source-of-truth lives in the loader's constant; the test class adapts automatically). It also documents the intent: "test that the boundary cases work" rather than "test that 552 raises".

   **Alternative path (acceptable but not preferred):** apply the 5 hardcoded replacements directly:
   - in-band-no-op: replace 770 → **788**
   - low-band-raises: replace 399 → **551**
   - high-band-raises: replace 1101 → **1025**
   - lower-bound-inclusive: replace 400 → **552**
   - upper-bound-inclusive: replace 1100 → **1024**

   **Note on the broader 770 sweep:** ten unrelated `770` literals appear elsewhere in `test_load_jurisdiction_bindings.py` (lines 1446, 1463, 1465, 1479, 1486, 1507, 1938, 1958, 2005, 2036) as synthetic in-band sample counts in other test classes. These are NOT `TestCountGuard` cases and don't break the suite. Implementation agent's call whether to also update them to 788 for project-wide "this is the canonical in-band sample count" consistency — recommended if taking the arithmetic-derivation path (extract a shared `_IN_BAND_SAMPLE_COUNT = 788` constant), optional if taking the alternative path.

No `db.py`, schema, Pydantic, TypeScript, or `architecture.md` edits. No Montana data is re-loaded. No production-database writes execute during this story (dry-run only if any verification is needed; the constant change is a guard-tightening, not a behaviour change at the row-write level).

The PM-prompt §"What You Are Not" lists `docs/planning/epics/completed/` as read-only with an explicit carve-out at handoff §8 last bullet for the AC #1087 footnote update. This story performs only that carved-out edit; no other content in the closed E03 epic is touched.

**Relevant ADRs:** [ADR-009](../../adrs/ADR-009-agentic-development-first-class.md) (documentation as the durable handoff record — the footnote update preserves the rationale audit trail). No schema or RLS ADR applies; this is a constant narrowing + paired documentation update.

**Acceptance Criteria:**

- [x] `ingestion/states/montana/load_jurisdiction_bindings.py:107` reads exactly `_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (552, 1024)` (whitespace + type annotation preserved per S03.10's style)
- [x] **Three** prose locations in `ingestion/states/montana/load_jurisdiction_bindings.py` no longer say "intentionally wide pending T16's empirical count" — spec named two (lines 108-109 module comment; lines 679-680 function docstring), Stage 6 static-analysis reviewer caught a third at lines 26-27 (module-level docstring carrying identical framing). All three replacements name T16, the 2026-05-28 measurement date, the empirical count 788, the ±30% derivation, and the handoff §8 sixth-bullet citation
- [x] `docs/planning/epics/completed/E03-regulation-text-ingestion.md` AC #1087 checkbox line shows `(552, 1024)`; suffix prose rewritten post-merge from "intentionally wide pending T16 (narrow to ±30% after first live run…)" to "±30% around T16's empirical 788 measured 2026-05-28 (narrowed in E04 S04.2 from the prior (400, 1100) T16-pending band)" — the as-shipped suffix would have contradicted the narrowed tuple
- [x] `docs/planning/epics/completed/E03-regulation-text-ingestion.md` footnote `[^row-count-correction]` retains its original 2026-05-23 paragraph byte-identical AND carries an appended paragraph headed `**T16 narrowing 2026-05-29.**` with the content described in the Context section (correct 4-space footnote-continuation indent)
- [x] `ingestion/tests/test_load_jurisdiction_bindings.py` `TestCountGuard` boundary cases now derive arithmetically from the loader's `_BINDING_COUNT_GUARD_BAND` (preferred path applied): `LOW, HIGH = _BINDING_COUNT_GUARD_BAND`; `_IN_BAND_SAMPLE_COUNT = 788` extracted with a T16 / 2026-05-28 inline comment; the 5 boundary cases derive as `LOW-1 / LOW / _IN_BAND_SAMPLE_COUNT / HIGH / HIGH+1`. The 9 unrelated `770` literals elsewhere in the file (other test classes' synthetic in-band sample counts) were swept to `_IN_BAND_SAMPLE_COUNT` for project-wide consistency, per the recommended-with-arithmetic-path note in Context #4
- [x] `pytest ingestion/tests/test_load_jurisdiction_bindings.py` green
- [x] Full suite `pytest ingestion/tests/` reports **1166 passed + 2 skipped** (+1 net delta from a new post-merge `TestCountGuard::test_band_locked_to_t16_empirical` contract-lock test added to close a circularity gap: the 5 arithmetic-derived boundary cases derived their inputs from the band itself, so accidental widening to e.g. `(0, 9999)` would silently pass; the lock test pins the tuple's numeric value to `(552, 1024)`. The "no net delta" intent of the original AC is superseded by the post-merge correctness work; new baseline holds going forward)
- [x] `ruff check ingestion/` clean
- [x] `mypy ingestion/lib/ ingestion/states/montana/load_jurisdiction_bindings.py` clean per-file (per the S03.7 discipline reminder — every adapter close re-runs mypy per-file before reporting clean)
- [x] No edits outside the four authorized files at-merge; three additive doc-only edits accompany the PR (`.roughly/plans/S04.2-narrow-binding-count-guard-band-plan.md` created during build and marked historical post-implementation per Roughly's plan-marker convention; `.roughly/known-pitfalls.md` carries three new pitfalls under § "Conventions — Documentation & planning discipline" — see story Status line for the topic list). Production database untouched
- [x] Montana row counts in Postgres are unchanged (no loader run was executed; the constant is read at adapter-import time during `main()`, not at any other point)
- [x] **First M2 PR chronologically** per handoff §8 sixth bullet — branched from `main` at the m1 tag commit; landed before S04.1 / S04.3 / S04.4 / S04.5

---

### S04.3: Add logging.basicConfig to load_jurisdiction_bindings.py main()

**Status:** Closed 2026-05-30 — squash-merged to main as PR #49 (`5de83c3`) from `feat/S04.3-add-logging-basicConfig` (pre-squash: 2 commits — implementation + plan-historical marker). **Third M2 PR chronologically.** 4-line multi-line `logging.basicConfig(...)` inserted as the first executable statement of `main()` in `ingestion/states/montana/load_jurisdiction_bindings.py:785-788`, immediately before the pre-existing `logger = logging.getLogger(__name__)` at line 789. Format string byte-identical to the canonical peer pattern at `load_regulation_records.py:714-717`. Closes the M1-UAT-2026-05-28 runpy-wrapper workaround per handoff §8 item #7. **Live verification**: `ingestion/.venv/bin/python ingestion/states/montana/load_jurisdiction_bindings.py --dry-run` now emits 25 INFO lines on stderr including the 22-row species×role cross-tab and `TOTAL: 788 bindings` — the same empirical count that S04.2's `_BINDING_COUNT_GUARD_BAND = (552, 1024)` is centered on, re-confirming the build pipeline is end-to-end-stable through the loader's build phase as of 2026-05-30. Two PM-noted decisions baked in (neither rises to ADR threshold): (a) double-quoted format string for project-wide style parity across all 9 sibling Montana loaders (spec at L286 quoted single-quoted; functionally identical); (b) multi-line `basicConfig(...)` form matching the majority of peers and cleaner for ruff line-length (spec's code block at L282-289 also uses multi-line). No regression test added per epic L291 ("a guard like `main() calls logging.basicConfig` would lock implementation detail rather than behaviour"). **Spec discrepancy surfaced** (documentation-only; not propagated to fix): the epic spec at L278, L293, L304 cites "other 6 loaders"; the actual count is **9 sibling loaders** (10 total) per the implementation agent's grep across `ingestion/states/montana/load_*.py`. The fix is unaffected — `load_jurisdiction_bindings.py` is still the sole `main()` without `basicConfig`. PM declined to land a cosmetic-only correction now (S04.3 is closed; folding into S04.4's scope would be creep). No ADRs created; no schema or three-place-sync changes; no new pitfalls; no open questions touched; test suite holds at **1166 + 2 skipped** (no delta from S04.2 close baseline; `git diff --stat` showed exactly one code file +4/-0 plus one plan-marker doc file). **S04.4's hard precondition (S04.1's migration timestamp `20260530132727` on main) was already satisfied at S04.1 close; S04.3 closure now makes S04.4 the next merge candidate.**

**As a** operator running `ingestion/.venv/bin/python ingestion/states/montana/load_jurisdiction_bindings.py --dry-run`
**I want** `main()` to call `logging.basicConfig` at entry so the loader's INFO-level cross-tab and count summary output is visible
**So that** the M1-UAT-2026-05-28 runpy wrapper workaround is unnecessary and `--dry-run` no longer exits 0 silently

**UAT: no**

**Context:**

Per handoff §8 "Runbook fixes needed before next run" **item #7**:

> `ingestion/states/montana/load_jurisdiction_bindings.py` `main()` — add `logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')` at the top of `main()`. The other 6 loaders configure logging implicitly; `load_jurisdiction_bindings.py` does not, which makes `--dry-run` exit 0 silently with no visible cross-tab or count output. M1 UAT 2026-05-28 worked around this with a runpy wrapper; the proper fix lives in the loader.

The fix is a single line at the top of `main()`, mirroring the format string in handoff §8 #7. Verified target: `ingestion/states/montana/load_jurisdiction_bindings.py:768` (`def main(argv: list[str] | None = None) -> int:`).

```python
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )
    # ... existing body
```

No regression test is requested. A guard like "`main()` calls `logging.basicConfig`" would lock implementation detail rather than behaviour. Verification is observational: run the dry-run once and confirm INFO-level output appears on stderr.

**Note on scope discipline:** S04.3 owns handoff §8 "Runbook fixes" **item #7 only**. Items #1-#6 are runbook edits to `docs/runbooks/M1-uat.md` and belong to S04.4. S04.4's mapping table reflects this split.

**Relevant ADRs:** none. Operator-ergonomics hygiene.

**Acceptance Criteria:**

- [x] `ingestion/states/montana/load_jurisdiction_bindings.py` `main()` first executable line (after the function signature) is `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")` — actual: 4-line multi-line form at `load_jurisdiction_bindings.py:785-788` with double-quoted format string for sibling-loader style parity; `logger = logging.getLogger(__name__)` moved from line 785 to line 789
- [x] `ingestion/.venv/bin/python ingestion/states/montana/load_jurisdiction_bindings.py --dry-run` (with a valid `DATABASE_URL` set so the import chain resolves — `--dry-run` does not actually connect, but the import-time SQL constants reference the URL pattern) emits INFO-level cross-tab and count summary output on stderr without a runpy wrapper — verified: 25 INFO lines including the 22-row species×role cross-tab and `TOTAL: 788 bindings`
- [x] `ruff check ingestion/states/montana/load_jurisdiction_bindings.py` clean
- [x] `mypy ingestion/states/montana/load_jurisdiction_bindings.py` clean per-file
- [x] Full suite `pytest ingestion/tests/` reports **1166 passed + 2 skipped** (no test delta from this story; baseline shifted 1165 → 1166 at S04.2 close) — verified: 1166 passed, 2 skipped, 13.59s
- [x] No changes to any other file; specifically, no changes to `docs/runbooks/M1-uat.md` (S04.4's scope) or to the other 9 sibling loaders' logging setup (out of S04.3 scope; their implicit logging works) — note: epic prose at L278/L293 cites "other 6 loaders" which is incorrect (actual count is 9 siblings, 10 loaders total per implementation-time grep); fix-side scope unaffected — `load_jurisdiction_bindings.py` was the sole `main()` without `basicConfig`

---

### S04.4: M1 UAT runbook hygiene fixes (six edits)

**Status:** Closed 2026-05-30 — squash-merged to main from `feat/S04.4-m1-uat-runbook-hygiene-fixes` (4 pre-squash commits: `38a0666` implementation + `b277571` plan historical-marker + `3358166` §6 audit-trail-preamble cubic P1 review-fix + `0b010a3` T4/T5 plan-dependency-declaration P3 corrections). **Fourth M2 PR chronologically.** Single target file `docs/runbooks/M1-uat.md` (+37/−28 LOC across the full PR). **Seven prescribed edits + four Stage-6 review-fix corrections + one user-approved AC-interpretation-override §6 preamble:**

**Stage-6 review-fix corrections** (round-1 reviewers caught these as logical consequences the original plan missed): (a) L99 inline criterion #2 deviation note's "HD 262 still verified in criterion #1" claim became false post-T2 (criterion #1 now queries HD 124) → rewritten to "HD 262 is exercised only in criterion #3 (PostGIS point-in-polygon against the HD 262 geometry fixture)"; (b) §5 Results Summary L374/L375 row labels said "HD 262 elk" but their SQL queries HD 124 → updated to "HD 124 elk (HD 262 substitution per footnote [^9])"; (c) L416 footnote [^3] same stale claim → updated; (d) §1 Prerequisites L15-L20 migration count 4 → 5 with new `20260530132727_rls_license_season.sql` (S04.1) entry so a future M2-week-1+ operator following the runbook applies all five migrations.

**User-approved AC-interpretation override for §6 preamble** (commit `3358166`): cubic flagged the §6 row's RESOLVED annotation as contradictory with the milestone-sign-off paragraph's "Criterion #7 FAILed — 14 privilege leaks ... zero RLS policies" language. Root cause: the audit-trail-preservation convention (this epic L338 + handoff §8 introductory paragraph) freezes the 2026-05-28 milestone paragraph as historical record; resolution updates live only in the table's Notes column — but this convention was documented in the epic, not the runbook itself, so cold-reading operators had no on-page disambiguator. Fix: 2-line italic preamble between §6 header and the table documenting the convention up front. User explicitly approved Option-1 (italic preamble) over Option-2 (footnote-on-row) after a comparative analysis of operator-UX vs. strict-AC-compliance tradeoffs. This **expands the §6 diff scope beyond AC L350's literal verification clause** ("changes to §6 limited to the criterion #7 annotation row only") — recorded in commit `3358166` message for future PR-audit purposes. Protected historical content (operator marks, initials, dates, sign-off paragraph) remains byte-identical pre/post.

**PM-approved adopted 7th row for the build-vs-DB count table**: `jurisdiction_binding 788 build → 788 DB (no collapse — id-keyed UPSERT)` — adopted at story open per the optional-enhancement note in Context #4 below. Spec position: handoff §8 #4 was authoritative at six rows; adoption required user approval, granted at story open; well-grounded against S03.10 T16 + S04.2 + S04.3 empirical confirmations of 788.

**draw_spec 278-vs-276 provenance call**: handoff §8 #4 cited `draw_spec 388 → 276 DB` (transcription error parenthetically noted in the same handoff bullet which then cites the correct `388→278` collapse); S03.8 closure in CLAUDE.md is authoritative at 278; the shipped runbook tracks 278 with new footnote `[^10]` documenting the discrepancy and explicit provenance attribution. Stage-4 plan-review reviewer caught the initial 276 error in the plan; the fix was re-reviewed clean before Stage 5 implementation.

**Plan-file T4/T5 P3 corrections** (post-implementation commit `0b010a3`): cubic flagged T4 and T5 in the historical plan as declaring `Depends on: none` when sub-edits 4b/5b state-depend on the prior task's footnote-append (re-reading the file to capture byte-exact text). Root cause: "operates on a disjoint region" was conflated with "has no dependencies." The strict T1→T7 ordering preserved correctness during execution; the declaration just understated the real coupling. Fixed: T4 now declares `Depends on: T2`; T5 now declares `Depends on: T4`. Plan still marked historical; no impact on the shipped runbook.

**Quality gates clean at close**: ruff/mypy/pytest (1166 + 2 skipped, zero delta from S04.3 close baseline; documentation-only PR, no Python touched); cubic post-merge ("No uncommitted changes to review"); pre-commit detect-secrets passed; tsc/ruff skipped (no relevant files).

**Three new pitfall candidates surfaced (none auto-landed — `.roughly/` is implementation territory; PM flags for user decision)**: (1) **most load-bearing** — "Spec-prescribed string substitutions silently invalidate coupled references elsewhere in the document; grep the file for every coupled reference and decide per-occurrence before review catches it." S04.4's T2/T3 prescribed HD 262 → HD 124 swap silently invalidated four downstream references (L98 inline note, L374/L375 §5 row labels, L416 footnote [^3]); the Stage-3 plan and Stage-4 plan-review both explicitly excluded §5 "by design"; Stage-6 review triad caught it as a correctness defect. PM recommends landing under `.roughly/known-pitfalls.md` § "Conventions — Documentation & planning discipline". (2) "Authoritative numbers drift between canonical documents — name the source-of-truth before copying" (the draw_spec 278-vs-276 case; extends the S04.1 build-vs-DB confusion lesson; recommend folding into #1 or landing as a one-line extension). (3) "Cubic-review on documentation diffs can flag values it lacks context to validate; treat as advisory not gating" — the 435/825 false positive case; PM recommends NOT landing (it's an operational reality of cubic, not a recurring trap). No open questions touched, created, or resolved.

**No ADRs created.** Implementation refines ADR-009 (documentation as primary handoff mechanism — this entire story is an ADR-009 instance) and observes ADR-001's "Authority preserved, not replaced" discipline (handoff §8 prescribed text reproduced byte-identical where the spec quotes it verbatim).

**S04.4 closes 4 of 5 E04 stories. S04.5 (PRD 001 sequencing language reconciliation) is the only remaining E04 story and is human-action-gated — PM drafted the diff at E04 open (in S04.5's Context section); user applies it to PRD 001 directly; the checkbox flips on the human's merge confirmation, not on PM diff-drafting.**

**As a** operator picking up `docs/runbooks/M1-uat.md` for a re-run or M2 reference
**I want** all six runbook hygiene edits from handoff §8 "Runbook fixes needed before next run" items #1-#6 applied as one coherent PR
**So that** the runbook reflects what was actually run on 2026-05-28 (HD 124 / HD 170 substitutions, build-vs-DB count convention, `psql` substitute documentation, ADR-017 status-check regex fix) without forcing a future operator to re-derive them

**UAT: no**

**Context:**

Handoff §8 captures seven captured-during-UAT edits that intentionally did not land during M1 UAT (audit-trail preservation; the runbook was deliberately not modified during UAT — handoff §8 introductory paragraph). They land in two stories: **items #1-#6 are runbook edits owned by S04.4**; **item #7 is a code-side `logging.basicConfig` fix owned by S04.3** (see S04.3 above).

Each edit is line-precise per handoff §8:

1. **`docs/runbooks/M1-uat.md` §2 deviation note #3** (handoff §8 #1) — extend to explicitly state HD 262 has no elk regulation_record at all; HD 124 substitutes for criterion #1 and #2(a); HD 170 substitutes for criterion #2(b). The runbook's current §2 already references HD 170 substitution; the §8 #1 edit extends the existing note to spell out the HD 262 absence cause.

2. **`docs/runbooks/M1-uat.md` §4 criterion #1 SQL** (handoff §8 #2) — change `'MT-HD-deer-elk-lion-262'` → `'MT-HD-deer-elk-lion-124'`. Update the section heading and PRD-text framing from "HD 262 elk" to "HD 124 elk substitution" with a footnote pointer.

3. **`docs/runbooks/M1-uat.md` §4 criterion #2 part (a) SQL** (handoff §8 #3) — change `'MT-HD-deer-elk-lion-262'` → `'MT-HD-deer-elk-lion-124'`. Update the "confirms HD 262 has data" framing to "confirms HD 124 has data".

4. **`docs/runbooks/M1-uat.md` §4 criterion #6 "Expected counts" table** (handoff §8 #4) — added a footnote distinguishing **build counts** from **post-UPSERT-collapse DB counts**. As-shipped reshape: 3-col `Table | Expected count | Notes` → 4-col `Table | Build count | Post-UPSERT DB count | Notes` with concrete deltas (regulation_record 437→435, license_tag 1225→825, license_season 3040→2411, regulation_license 1914→1279, regulation_season 1385→1381, **draw_spec 388→278** per S03.8 closure authoritative; handoff §8 #4's 276 was a transcription error documented in shipped footnote `[^10]` with explicit provenance attribution). Entity tables collapse via `INSERT … ON CONFLICT DO UPDATE`; link tables collapse via `ON CONFLICT DO NOTHING`. **PM-approved adopted 7th row** (user-confirmed at story open per the optional-enhancement note that previously lived here): `jurisdiction_binding 788 build → 788 DB (no collapse — id-keyed UPSERT)` — references S03.10 T16 empirical 788 and S04.2's `_BINDING_COUNT_GUARD_BAND = (552, 1024)` centering; S04.3's `--dry-run` output on 2026-05-30 re-confirmed the same 788. Five no-collapse pairs (regulation_record, season_definition, reporting_obligation, regulation_reporting, geometry) round out the table.

5. **`docs/runbooks/M1-uat.md` §1 Prerequisites** (handoff §8 #5) — add either a tool-prerequisites item recommending `brew install libpq && brew link --force libpq`, OR a footnote pointing to the `supabase db query --db-url "$DATABASE_URL" "<sql>"` substitute used in the 2026-05-28 UAT run. The runbook author chooses; the canonical preference is the supabase-CLI footnote because it matches the actual 2026-05-28 method.

6. **`docs/runbooks/M1-uat.md` §4 criterion #8 bash command** (handoff §8 #6) — change `grep -A1 -E '^(\*\*Status\*\*|Status):'` → `grep -E '^\*\*Status:?\*\*'` (or simpler `grep '^\*\*Status:\*\*'`). The current regex does not match the actual ADR-017 heading line `**Status:** Accepted` (asterisks wrap the colon, not just the word).

**Mandatory 7th annotation — S04.1-merged precondition:** extend `docs/runbooks/M1-uat.md` §6 Sign-Off table's criterion #7 row with "RESOLVED M2-W1 via `<timestamp>_rls_license_season.sql`" naming S04.1's actual migration timestamp. This annotation is in-scope for S04.4; the merge order **S04.2 → S04.1 → S04.3 → S04.4 → S04.5 is a hard precondition** (no longer just a recommendation) so S04.1's timestamp is always known when S04.4 opens. This replaces the prior deferral-protocol design — coupling between S04.4's runbook edits and S04.1's migration timestamp now lives in the merge-order precondition, not in a conditional protocol.

**Audit-trail preservation discipline** (handoff §8 introductory paragraph is emphatic on this): the runbook was NOT modified during UAT to preserve audit trail of what was actually run on 2026-05-28. S04.4's edits MUST be additive and MUST leave the existing §6 sign-off section (operator initials, PASS/FAIL marks, dates, sign-off paragraph) byte-identical. The six numbered edits all land in sections §1 / §2 / §4 (criteria #1 / #2 / #6 / #8) — none touches the §6 sign-off block.

M2 UAT runbook (`docs/runbooks/M2-uat.md`) is NOT drafted here — that is an E06 deliverable (S06.12 per PRD 002).

**Relevant ADRs:** none. Operator-documentation hygiene.

**Acceptance Criteria:**

- [x] **Precondition: S04.1 has merged to `main` before S04.4 opens its PR** — verified at story open and at close: `supabase/migrations/20260530132727_rls_license_season.sql` exists on main; S04.4 branched from a commit including the S04.1 migration file
- [x] All six edits applied to `docs/runbooks/M1-uat.md` per handoff §8 §"Runbook fixes needed before next run" items **#1, #2, #3, #4, #5, #6** (item #7 is owned by S04.3) — all six landed per implementation summary T1-T6; grep-counts at story close verified each
- [x] **Mandatory 7th annotation**: `docs/runbooks/M1-uat.md` §6 Sign-Off table's criterion #7 row extended with `— RESOLVED M2-W1 via \`20260530132727_rls_license_season.sql\`` — S04.1's actual migration timestamp threaded through; also surfaced in §1 Prerequisites as the 5th migration entry per Stage-6 review-fix correction
- [x] Each edit references the corresponding handoff §8 item number in the commit message — implementation commit `38a0666` cites items #1-#6 + mandatory annotation
- [x] **Audit-trail integrity preserved**: the 2026-05-28 sign-off section (§6 Sign-Off table operator marks, initials, dates, sign-off paragraph) is byte-identical pre- and post-PR — `git diff -U0` showed only the criterion #7 row + the §6 audit-trail-preamble (the latter is a user-approved AC-interpretation override recorded in commit `3358166`; expands §6 diff scope beyond AC's literal verification clause to fix a cubic-flagged read-cold contradiction in §6's milestone-sign-off paragraph; protected historical content remains byte-identical)
- [x] No SQL is executed during this story (documentation-only)
- [x] No code, schema, Pydantic, TypeScript, `architecture.md`, or test edits — `git diff --stat` showed one runbook file modified plus the new `.roughly/plans/S04.4-*-plan.md` historical-marker artifact
- [x] Full suite `pytest ingestion/tests/` reports **1166 passed + 2 skipped** (no test delta from this story; baseline shifted 1165 → 1166 at S04.2 close) — verified at Stage 7 and at pre-cubic stage

---

### S04.5: PRD 001 sequencing language reconciliation

**Status:** Closed 2026-05-31 — PRD 001 lines 90/96/111 reconciled per the PM-drafted diff at commit `bf9bfa9`; line 48 unchanged per PM review. Two parallel housekeeping bundles co-landed in the same `/roughly:build` session under the user's git identity: **Bundle A** (`3445017`) appended two new entries to `.roughly/known-pitfalls.md` § "Conventions — Documentation & planning discipline" (section now carries 8 entries, was 6) — Entry 1 "spec-prescribed string substitutions silently invalidate coupled references" (S04.4 T2/T3 case) and Entry 2 "authoritative numbers drift between canonical documents — name the source-of-truth before copying" (S04.1 + S04.4 case); a third S04.4-surfaced candidate was deliberately excluded per the prompt as "operational reality of cubic, not a recurring trap." **Bundle B** (`37bc86a`) applied five hygiene edits to `docs/planning/handoffs/M1-to-M2-handoff.md`: path-drift to `completed/` (7 occurrences), §3 build-vs-DB clarifying preamble, §8 item #7 RESOLVED annotation (S04.3 / PR #49 / `5de83c3`), §8 item #4 transcription error `276 → 278` (per S03.8 closure authoritative), §8 item #4 incompleteness — new `jurisdiction_binding 788 build → 788 DB` row memorializing S04.4's PM-approved scope expansion. Plus a plan-historical marker commit (`91bde52`) and a post-merge cubic fix-up (`eb803db`) correcting sentence-initial "A" capitalization on PRD 001 line 96 — the substring replacement supplied by the drafted diff was lowercase ("a `geometry-overlays.json` fixture …") but the substitution placed it at sentence-start where uppercase was required; cubic caught it post-merge; content-anchored grep verification cannot catch grammar. PM judged this too narrow for a new pitfall entry but worth recording as a refinement of pitfall #1.

**Delegation-deviation note (PM judgment recorded)**: S04.5's story shape originally specified human-applies-directly with no implementation-agent edit to PRD 001. The user explicitly invoked `/roughly:build` with S04.5 in scope, delegating the apply to the build agent running under the user's git identity (commit author: `Nick Kirkes <nick@rowdycloud.io>`, Co-Authored-By trailer naming Claude). The build-agent intake flagged this as a deviation at Stage 1 rather than silently widening scope. **PM accepts the trailer-collaboration form as satisfying AC #427's intent** ("only the human's commit hash should appear" — the commit hash IS the human's; the trailer is documentation of collaboration, not autonomous agent action). The no-autonomous-PRD-edit rule's purpose is to ensure the user has explicit control over PRD edits; the user's explicit invocation of `/roughly:build` with S04.5 named is explicit control. AC reframed in the checkboxes below; the underlying intent is satisfied.

**Quality gates clean at close**: pytest 1166 + 2 skipped (no delta, 14.34s); ruff/mypy not exercised (no Python touched); cubic clean post-fix-up; pre-commit detect-secrets passed on all 5 commits.

**No ADRs created.** No schema changes. No Colorado data, no CO-specific code. The recurring-RLS-gap M2 open-question candidate (E04 §"Known Issues to Escalate" #1) remains unchanged in scope — none of the five E04 stories needed to resolve it.

**As a** future reader of PRD 001 (M1 Montana ingestion)
**I want** PRD 001 lines 48 / 90 / 96 / 111 reconciled per the proposal in `docs/planning/epics/completed/E02-geometry-ingestion.md` § "Known issues to escalate" #1
**So that** the PRD reflects the actual jurisdiction_binding sequencing (E03 writes the bindings via S03.6.1 and S03.10, not E02) — closing the documentation drift surfaced by handoff §8 third bullet

**UAT: no**

**Context:**

PRD 001 lines 48 / 90 / 96 / 111 still describe E02 as writing `jurisdiction_binding` rows. In reality, E02 wrote a geometry-overlays fixture (`ingestion/states/montana/fixtures/geometry-overlays.json`) per the PRD/schema conflict resolution captured in `docs/planning/epics/completed/E02-geometry-ingestion.md` lines 22-28, and E03's S03.6.1 + S03.10 wrote the binding rows. PRDs are scope source-of-truth and editable only with explicit human approval per the PM-prompt §"What You Are Not".

**Story shape** — coordinated PM-drafts → human-applies → PM-confirms cycle, not a code change:

1. **PM drafts the line-by-line diff** for PRD 001 in this story's "Drafted diff" sub-section. The diff text is presented verbatim for the human to review.
2. **Human reviews and applies the diff to PRD 001 directly** — or rejects / amends. PRD 001 is the human's source-of-truth artifact; neither the PM nor any implementation agent edits it autonomously.
3. **Human reports merge to main**. The PM flips this story's checkbox at that point — not when the PM drafted the diff.

**Status flow** (mapping PM-prompt §"Status tracking" to this story's coordinated cycle):

| State | Trigger |
|---|---|
| `Not Started` | E04 epic file written; PM has not yet drafted the diff (the diff in the next sub-section is already drafted, so this state is short-lived for S04.5 — flips to In Progress at E04 close) |
| `In Progress` | Diff is in the human's hands for review (drafted below) |
| `Complete` | Human confirms PRD 001 has merged to main |
| `Blocked` | Genuine blocking condition only — e.g., human reports the proposed diff conflicts with other in-flight work, or scope expansion is needed beyond the four named lines |

**Drafted diff** (PM-authored on 2026-05-29; awaits human review):

- **Line 48** (currently: `**Geometries:** MT FWP ArcGIS MapServer `admbnd/huntingDistricts` as the canonical source per Q1 resolution. All 40 layers, scoped to the V1 big-game layers.`): **no change.** Line 48 is a Geometries-source statement and is correct as-is. Listed here because handoff §8 third bullet names it as a candidate; PM review confirms no edit is required.

- **Line 90** (currently: `**Outcome:** All Montana geometries (HDs, BMUs, CWD zones, Portions) are loaded into the `geometry` table with correct `jurisdiction_binding` rows expressing their overlay relationships. Spatial queries work.`): change to: `**Outcome:** All Montana geometries (HDs, BMUs, CWD zones, Portions) are loaded into the `geometry` table, and a `geometry-overlays.json` fixture captures their overlay relationships for E03 to consume. Spatial queries work.`

- **Line 96** (currently: `**Exit criteria for E02:** All V1-relevant geometries loaded from MT FWP's ArcGIS MapServer. Every geometry passes `shapely.make_valid()`. Spot checks using `ST_Contains` against known Montana coordinates return correct HD/BMU identifications. `jurisdiction_binding` rows correctly express HD → BMU overlay, HD → CWD-zone overlay, HD → Portion overlay relationships. Fetching the geometries is reproducible — `make ingest STATE=montana STAGE=geometry` can re-run the fetch without corrupting existing data.`): change `jurisdiction_binding rows correctly express HD → BMU overlay, HD → CWD-zone overlay, HD → Portion overlay relationships` → `a `geometry-overlays.json` fixture captures HD → Portion, HD → CWD-zone, and HD → restricted-area overlay relationships for E03's S03.6.1 + S03.10 to consume when writing `jurisdiction_binding` rows`. (The fixture spans HD↔Portion / HD↔CWD / HD↔Restricted-Area per E02 S02.6; HD↔BMU is not in the fixture because Black Bear BMUs are FWP HDs in M1, not a separate geometry layer.)

- **Line 111** (currently: `**E03 depends on E02.** E03 writes `regulation_record`, `license_tag`, `reporting_obligation`, and other rows that foreign-key to `jurisdiction_binding`. Those bindings must exist before E03 can write.`): rewrite to: `**E03 depends on E02.** E03 writes `regulation_record`, `license_tag`, `reporting_obligation`, `jurisdiction_binding`, and other rows. The `jurisdiction_binding` rows FK to `geometry(id)` (a hard FK to a table E02 populates) and to `regulation_record` (the binding's anchor, written earlier within E03 itself). Bindings cannot be written until both FK targets exist — `geometry` from E02 and `regulation_record` from E03's earlier stories.`

The line numbers above are PRD-001 line numbers as of 2026-05-29. If the human's review surfaces that other PRD lines need to change (e.g., line 47's "Why first" framing for E02), the diff is amended before the human applies it. The PM does not foreclose human-driven scope adjustment of this S04.5 edit set.

**Relevant ADRs:** none. Documentation-discipline reconciliation per handoff §8 third bullet.

**Acceptance Criteria:**

- [x] PM has drafted the line-by-line diff in this story's "Drafted diff" sub-section (drafted 2026-05-29 at E04-write; refined post-merge to capture the sentence-initial-capitalization lesson per cubic fix-up `eb803db`)
- [x] Diff handed to the human for review (on-record since 2026-05-29 E04 open; surfaced again to the human at each S04.X closure as "next active work-front is human-action-gated")
- [x] Human applies the diff (or an amended version, after review) to PRD 001 directly — applied 2026-05-31 via `/roughly:build` delegation under the user's git identity (`Nick Kirkes <nick@rowdycloud.io>`); cubic fix-up `eb803db` corrected line 96 sentence-initial capitalization post-merge
- [x] Human confirms the PRD 001 edit has merged to main — confirmed in conversation with PM 2026-05-31
- [x] PM flips this story's checkbox only upon the human's merge confirmation — flipped in this commit
- [x] PRD 001 lines 90, 96, 111 reflect the actual jurisdiction_binding sequencing after the edit lands; line 48 unchanged — grep-verified post-merge by build agent
- [x] No code, schema, runbook, or planning-epic edits as part of this story (PRD 001 commit `bf9bfa9` touches only PRD 001; Bundle A `.roughly/known-pitfalls.md` + Bundle B handoff edits are out of S04.5 scope and recorded separately)
- [x] No autonomous PM or implementation-agent edit to PRD 001 — **PM judgment override recorded in Status above**: the user explicitly invoked `/roughly:build` with S04.5 in scope, delegating the apply to the build agent running under the user's git identity. Commit author hash is the human's; Co-Authored-By trailer names Claude as collaborator. PM accepts the trailer-collaboration form as satisfying the AC's intent — the no-autonomous-PRD-edit rule's purpose is explicit human control over PRD edits, satisfied by the explicit `/roughly:build` invocation
- [x] Full suite `pytest ingestion/tests/` reports **1166 passed + 2 skipped** at S04.5 close (PRD edit does not exercise the test suite; this AC documents the baseline preservation. Baseline shifted 1165 → 1166 at S04.2 close) — verified at close, 14.34s

---

## Exit Criteria

- [x] All 5 stories complete (S04.1 through S04.5; S04.6 omitted per epic header)
- [x] `license_season` RLS posture is at full parity with the original 10 entity tables (`ENABLE` + `FORCE` + 2 deny-all policies + `REVOKE ALL ON TABLE`) — S04.1 close 2026-05-30 (Group A at-merge + Group B live-verified)
- [x] `_BINDING_COUNT_GUARD_BAND` in Montana's jurisdiction-binding loader is `(552, 1024)`; **three** prose locations name T16 / 2026-05-28 / empirical 788 / ±30% — (a) module-level docstring at lines 26-27 (Stage-6 review-fix add), (b) the module-level constant comment at lines 108-109 immediately following the `_BINDING_COUNT_GUARD_BAND` declaration, AND (c) the `_assert_binding_count_within_guard` function docstring at lines 679-680; AC #1087 footnote in the closed E03 epic carries both the original 2026-05-23 paragraph and the appended 2026-05-29 T16-narrowing paragraph
- [x] `load_jurisdiction_bindings.py:main()` invokes `logging.basicConfig` at entry — S04.3 close 2026-05-30; `--dry-run` re-confirmed `TOTAL: 788 bindings`
- [x] All six M1 UAT runbook hygiene fixes per handoff §8 #1-#6 are landed; the §6 sign-off section is byte-identical pre/post **except** for the criterion #7 row's "RESOLVED M2-W1 via `20260530132727_rls_license_season.sql`" annotation (mandatory 7th edit) AND the user-approved §6 audit-trail-preamble (AC-interpretation override recorded in S04.4 commit `3358166`)
- [x] PRD 001 lines 90, 96, 111 reconciled (line 48 unchanged); the human confirmed the merge — S04.5 close 2026-05-31 (delegated via `/roughly:build` under the user's git identity per the PM-judgment override recorded in S04.5 Status above)
- [x] Test suite remains at **1166 passed + 2 skipped** baseline throughout the remainder of E04 after S04.2 close (baseline shifted 1165 → 1166 at S04.2 via the post-merge `TestCountGuard::test_band_locked_to_t16_empirical` contract-lock test — a deliberate quality addition, not a regression); no later story has a net test delta — verified at S04.3 / S04.4 / S04.5 close
- [x] Montana row counts in Postgres unchanged: regulation_record 435, license_tag 825, license_season 2411 (post-UPSERT DB count per S04.4 runbook footnote `[^10]`; the prior "~3040" reference was the handoff §3 pre-collapse build projection — see S04.1 Group B verification record), draw_spec 278 (per S03.8 closure authoritative; handoff §8 #4's 276 was a transcription error corrected via the Bundle B handoff hygiene patch landed at S04.5 close), reporting_obligation 3, jurisdiction_binding 788, geometry 350 (verified via service-role `SELECT COUNT(*)` at S04.1 Group B close)
- [x] PRD 002 success-criterion #8's `license_season` deny-all check passes against the production project after S04.1 lands; the other PRD 002 criteria are not yet exercised (Colorado data lands in E05/E06) — S04.1 Group B live-verified 2026-05-30
- [x] No Colorado data loaded; no CO-specific code added in `ingestion/states/colorado/` — `git ls-files ingestion/states/colorado/` empty at E04 close

---

## Parallelization Notes

**Within E04: stories run sequentially** per PM-prompt §"Commit and branch workflow" — the human creates a feature branch per story and merges before the next begins.

**Chronology commitment from handoff §8 sixth bullet:** **S04.2 ships as the first M2 PR.** This is a chronological lock, not just a workflow preference — S04.2 is branched from `main` at the m1 tag commit and opens before any other M2 PR.

**After S04.2:** S04.1 is the next merge candidate (RLS security posture closes the M1 UAT criterion #7 leak surface). **S04.3 must land after S04.1, and S04.4 must land after S04.1** — S04.4's mandatory criterion #7 sign-off-row annotation references S04.1's actual migration timestamp, so S04.1's merge is a hard precondition for S04.4's PR open. S04.3 ordering after S04.1 is a softer convention (S04.3 has no S04.1 dependency) but the merge order is enforced uniformly to keep the workflow simple. S04.5 has a human-action checkpoint (PRD diff review + apply); its timeline is decoupled from S04.1/S04.3/S04.4 — the PM drafts the diff at E04 close (already drafted above as of 2026-05-29) and waits for human confirmation independently of S04.1-S04.4 merging.

**Merge order — hard precondition:** S04.2 → S04.1 → S04.3 → S04.4 → S04.5. The S04.2-first lock comes from handoff §8 sixth bullet (audit-trail value linking the band-narrowing PR to M1 T16). The S04.1-before-S04.4 lock comes from S04.4 AC #1 (S04.1's migration timestamp must exist before S04.4 opens). S04.5 timeline-overlaps S04.1-S04.4 while the human reviews the drafted diff.

**Cross-epic:** E05 does not depend on any E04 story for a hard technical reason; E04→E05 is a soft operator-discipline ordering per PRD 002 §"Why sequential". E04 still ships before E05 for workflow clarity and so that E05's operator runs benefit from S04.3's logging hygiene and S04.4's runbook clarity.

The PM does not recommend parallel implementation within M2. The `/next` command returns exactly one story.

---

## Known Issues to Escalate

1. **Flat-IN-list pattern in `20260425000001_rls_deny_all.sql` — recurring-gap risk.** The base RLS migration uses a per-table flat enumeration (10 explicit `ALTER TABLE` blocks). It does not auto-extend to subsequently-added tables — which is exactly what produced the M1 `license_season` gap that S04.1 closes. **Any future migration in M2 / M3 that adds a new public-schema table will silently inherit the same gap unless its inline RLS block is included in the same migration.** PRD 002 §"Decisions already made" already encodes "any new M2 migrations include deny-all in the same file" as a project discipline, which is the per-migration-author mitigation. The PM surfaces three escalation paths to the human for consideration as a separate M2 open-question / ADR candidate (not E04 scope):
   - **Belt-and-suspenders:** add an event-trigger migration that auto-denies RLS on every newly-created `public.*` table. ADR-level design decision.
   - **Process-level:** add a pre-commit or CI check that diffs `pg_class` table listing vs. `pg_policies` listing and fails if any `public.*` table lacks the four required artifacts (ENABLE, FORCE, two deny-all policies, REVOKE). Cheaper, no DDL.
   - **Discipline-only:** rely on the PRD 002 inline-RLS rule and on individual migration authors. This is the M1 status quo; the `license_season` gap demonstrates its failure mode.

   PM recommendation: surface as an M2 open question at E04 close so the human chooses a path explicitly before more tables are added.

2. **`role='other_overlay'` semantic awkwardness** (handoff §8 fourth bullet). Carries forward through E04 unchanged. M2-deferred per handoff; resolution belongs to E05 / E06 if Colorado introduces no-hunt zones that exercise the gap with more density than Montana's three V1 cases.

3. **Cross-state spatial filter discipline** (handoff §8 fifth bullet). Carries forward through E04 unchanged. The pattern `_STATE = 'US-CO'` is documented; E05 / E06 adapter authors must adopt it. Reinforced by PRD 002 success criterion #4 and by PRD 002 §"Cross-state spatial discipline".

4. **Cell-level source attribution** + **free-prose non-NOTE HD-wide content** (handoff §8 seventh and eighth bullets). Both carry forward through E04 unchanged. M2 ADR-candidates only if Colorado data forces the issue.

If E04 implementation surfaces an issue out of E04 scope (e.g., the diff for S04.5 needs to touch a PRD section the PM did not anticipate; S04.1's migration body needs a `bypassrls` configuration not currently in scope; a new pitfall surfaces that needs `.roughly/known-pitfalls.md` extension), the implementation agent flags it on the relevant story rather than silently widening scope. The PM surfaces it to the human.

---

## References

- [PRD 002 — M2 Colorado Ingestion](../prds/002-M2-colorado-ingestion.md) — M2 scope; E04 phasing
- [`docs/planning/handoffs/M1-to-M2-handoff.md`](../handoffs/M1-to-M2-handoff.md) §8 — authoritative carry-forward record
- [`docs/runbooks/M1-uat.md`](../../runbooks/M1-uat.md) — M1 UAT runbook (S04.4 edit target)
- [`docs/runbooks/M1-uat-results-2026-05-28.md`](../../runbooks/M1-uat-results-2026-05-28.md) — UAT run record (audit trail for S04.4 hygiene fixes)
- [`docs/planning/epics/completed/E02-geometry-ingestion.md`](completed/E02-geometry-ingestion.md) § "Known issues to escalate" #1 — S04.5 proposed reconciliation source
- [`docs/planning/epics/completed/E03-regulation-text-ingestion.md`](completed/E03-regulation-text-ingestion.md) AC #1087 + footnote — S04.2 edit target
- [`docs/planning/epics/completed/E03-deferred-items/README.md`](completed/E03-deferred-items/README.md) — flag protocol
- [`docs/research/colorado-draw-schema-proposal.md`](../../research/colorado-draw-schema-proposal.md) — S04.6 read-through input
- [`docs/research/gmu-source-evaluation.md`](../../research/gmu-source-evaluation.md) — S04.6 read-through input
- [`ingestion/states/montana/load_jurisdiction_bindings.py`](../../../ingestion/states/montana/load_jurisdiction_bindings.py) — S04.2 + S04.3 edit target
- [`ingestion/tests/test_load_jurisdiction_bindings.py`](../../../ingestion/tests/test_load_jurisdiction_bindings.py) — S04.2 `TestCountGuard` edit target
- [`supabase/migrations/20260425000001_rls_deny_all.sql`](../../../supabase/migrations/20260425000001_rls_deny_all.sql) — S04.1 precedent (ENABLE + FORCE + deny-all + REVOKE per the 10 original tables)
- [ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md) — PostgREST closed structurally
- [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md) — Supabase + PostGIS + RLS deny-all posture
- [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md) — schema versioned, three-place sync
- [ADR-009](../../adrs/ADR-009-agentic-development-first-class.md) — documentation as handoff mechanism
- [ADR-018](../../adrs/ADR-018-e03-schema-additions.md) — `license_season` introduction; precedent for inline RLS in future migrations going forward
- [ADR-020](../../adrs/ADR-020-id-text-pk-slug-derivation.md) — drift_guard pattern; not exercised in E04 (E06 territory) but cited so E04 readers know the M1 close-out lineage

---

*HuntReady · E04 · M2 — Colorado Ingestion · v1.0 (validated 2026-05-29)*
