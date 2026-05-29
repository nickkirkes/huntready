# E04: M1 Carry-Forward and Colorado Schema Preparation

**Status:** Not Started
**Milestone:** M2 — Colorado Ingestion
**Dependencies:** M1 complete — `m1` tag at commit corresponding to PR #45 (`ccbe085`, Q19 RESOLVED via ADR-020); E03 closed 2026-05-27
**Validated:** 2026-05-29 (E04 validation triad: Migration & RLS + Carry-forward Fidelity returned LAND-WITH-EDITS; Cross-Language Consistency reviewer skipped — S04.6 omitted per epic header)
**Drafted:** 2026-05-29
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

**Status:** Not Started

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

- [ ] New timestamped migration file in `supabase/migrations/` whose timestamp prefix is strictly greater than `20260504032424`
- [ ] Migration enables RLS: `ALTER TABLE public.license_season ENABLE ROW LEVEL SECURITY`
- [ ] Migration forces RLS: `ALTER TABLE public.license_season FORCE ROW LEVEL SECURITY` (parity with the 10 original tables in `20260425000001_rls_deny_all.sql`)
- [ ] Migration creates policy `"Deny all access for authenticated" ON public.license_season FOR ALL TO authenticated USING (false) WITH CHECK (false)` (declared first, matching `20260425000001_rls_deny_all.sql:29-32` ordering for grep-parity)
- [ ] Migration creates policy `"Deny all access for anon" ON public.license_season FOR ALL TO anon USING (false) WITH CHECK (false)` (declared second)
- [ ] Migration revokes via `REVOKE ALL ON TABLE public.license_season FROM anon, authenticated` (explicit `ON TABLE` form for parity)
- [ ] `supabase db push` applies the migration cleanly to the production project
- [ ] `information_schema.table_privileges` returns 0 rows for `(license_season, {anon, authenticated})` after migration; baseline (per handoff §8 second bullet) was 14 rows
- [ ] `pg_policies` returns exactly 2 rows for `license_season` after migration (one per role); baseline was 0 rows
- [ ] `pg_class.relrowsecurity = true` AND `pg_class.relforcerowsecurity = true` for `license_season` after migration
- [ ] `SELECT COUNT(*) FROM public.license_season` returns the same count pre- and post-migration (service-role connection; M1 closed at ~3040 rows per handoff §3 — locking the exact pre-migration number as the baseline in the PR description)
- [ ] Sanity: a **service-role** Postgres connection (using `SUPABASE_SECRET_KEY` / the service-role DSN, NOT the migration-runner connection nor an `anon`/`authenticated` JWT) executes `SELECT COUNT(*) FROM public.license_season` and returns a number > 0 — proves the deny-all policies do not block service-role access and that Supabase's project-level `bypassrls` grant is configured as expected (default Supabase behavior; verify-not-assume per the M1 UAT discipline)
- [ ] Test suite remains green at 1165 passed + 2 skipped (no Python edits expected from this story; SQL-only migration)
- [ ] No Pydantic, TypeScript, or `architecture.md` edits — the `license_season` table already exists in all three places from S03.0; this story closes a posture gap, not a schema gap

---

### S04.2: Narrow _BINDING_COUNT_GUARD_BAND to (552, 1024)

**Status:** Not Started

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

- [ ] `ingestion/states/montana/load_jurisdiction_bindings.py:107` reads exactly `_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (552, 1024)` (whitespace + type annotation preserved per S03.10's style)
- [ ] **Both** prose locations in `ingestion/states/montana/load_jurisdiction_bindings.py` no longer say "intentionally wide pending T16's empirical count": (a) the module-level comment at lines 108-109 immediately following the `_BINDING_COUNT_GUARD_BAND` declaration, AND (b) the `_assert_binding_count_within_guard` function docstring at lines 679-680. Each replacement names T16, the 2026-05-28 measurement date, the empirical count 788, and the ±30% derivation
- [ ] `docs/planning/epics/completed/E03-regulation-text-ingestion.md` AC #1087 checkbox line shows `(552, 1024)` (one tuple change inside the same checkbox; checkbox remains `- [x]`)
- [ ] `docs/planning/epics/completed/E03-regulation-text-ingestion.md` footnote `[^row-count-correction]` retains its original 2026-05-23 paragraph byte-identical AND carries a new appended paragraph headed `**T16 narrowing 2026-05-29.**` with the content described in the Context section
- [ ] `ingestion/tests/test_load_jurisdiction_bindings.py` `TestCountGuard` boundary cases reflect the new band. **Preferred:** arithmetic-derivation refactor importing `_BINDING_COUNT_GUARD_BAND` from the loader and deriving the 5 boundaries as `LOW-1 / LOW / in-band / HIGH / HIGH+1` (in-band = 788 with inline comment naming T16 / 2026-05-28). **Alternative:** 5 hardcoded replacements (399→551, 770→788, 1101→1025, 400→552, 1100→1024). Either approach must cover the same 5 boundary cases
- [ ] `pytest ingestion/tests/test_load_jurisdiction_bindings.py` green
- [ ] Full suite `pytest ingestion/tests/` reports **1165 passed + 2 skipped** (no net test delta — replacement-in-place at five lines)
- [ ] `ruff check ingestion/` clean
- [ ] `mypy ingestion/lib/ ingestion/states/montana/load_jurisdiction_bindings.py` clean per-file (per the S03.7 discipline reminder — every adapter close re-runs mypy per-file before reporting clean)
- [ ] No edits outside the four files named (`load_jurisdiction_bindings.py`, `E03-regulation-text-ingestion.md`, `test_load_jurisdiction_bindings.py`; the production database is untouched)
- [ ] Montana row counts in Postgres are unchanged (no loader run is required for this story; the constant is read at adapter-import time during `main()`, not at any other point)
- [ ] **First M2 PR chronologically** per handoff §8 sixth bullet — branched from `main` at the m1 tag commit; opens before S04.1 / S04.3 / S04.4 / S04.5

---

### S04.3: Add logging.basicConfig to load_jurisdiction_bindings.py main()

**Status:** Not Started

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

- [ ] `ingestion/states/montana/load_jurisdiction_bindings.py` `main()` first executable line (after the function signature) is `logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')`
- [ ] `ingestion/.venv/bin/python ingestion/states/montana/load_jurisdiction_bindings.py --dry-run` (with a valid `DATABASE_URL` set so the import chain resolves — `--dry-run` does not actually connect, but the import-time SQL constants reference the URL pattern) emits INFO-level cross-tab and count summary output on stderr without a runpy wrapper
- [ ] `ruff check ingestion/states/montana/load_jurisdiction_bindings.py` clean
- [ ] `mypy ingestion/states/montana/load_jurisdiction_bindings.py` clean per-file
- [ ] Full suite `pytest ingestion/tests/` reports **1165 passed + 2 skipped** (no test delta)
- [ ] No changes to any other file; specifically, no changes to `docs/runbooks/M1-uat.md` (S04.4's scope) or to the other 6 loaders' logging setup (out of S04.3 scope; their implicit logging works)

---

### S04.4: M1 UAT runbook hygiene fixes (six edits)

**Status:** Not Started

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

4. **`docs/runbooks/M1-uat.md` §4 criterion #6 "Expected counts" table** (handoff §8 #4) — add a footnote distinguishing **build counts** from **post-UPSERT-collapse DB counts**. Concrete deltas per handoff §8 #4 (memorialize verbatim): regulation_record 437 build → 435 DB; license_tag 1225 build → 825 DB; license_season 3040 build → 2411 DB; regulation_license 1914 build → 1279 DB; regulation_season 1385 build → 1381 DB; draw_spec 388 build → 276 DB. Entity tables collapse via `INSERT … ON CONFLICT DO UPDATE`; link tables collapse via `ON CONFLICT DO NOTHING`. Both numbers correct in their respective contexts.

5. **`docs/runbooks/M1-uat.md` §1 Prerequisites** (handoff §8 #5) — add either a tool-prerequisites item recommending `brew install libpq && brew link --force libpq`, OR a footnote pointing to the `supabase db query --db-url "$DATABASE_URL" "<sql>"` substitute used in the 2026-05-28 UAT run. The runbook author chooses; the canonical preference is the supabase-CLI footnote because it matches the actual 2026-05-28 method.

6. **`docs/runbooks/M1-uat.md` §4 criterion #8 bash command** (handoff §8 #6) — change `grep -A1 -E '^(\*\*Status\*\*|Status):'` → `grep -E '^\*\*Status:?\*\*'` (or simpler `grep '^\*\*Status:\*\*'`). The current regex does not match the actual ADR-017 heading line `**Status:** Accepted` (asterisks wrap the colon, not just the word).

**Mandatory 7th annotation — S04.1-merged precondition:** extend `docs/runbooks/M1-uat.md` §6 Sign-Off table's criterion #7 row with "RESOLVED M2-W1 via `<timestamp>_rls_license_season.sql`" naming S04.1's actual migration timestamp. This annotation is in-scope for S04.4; the merge order **S04.2 → S04.1 → S04.3 → S04.4 → S04.5 is a hard precondition** (no longer just a recommendation) so S04.1's timestamp is always known when S04.4 opens. This replaces the prior deferral-protocol design — coupling between S04.4's runbook edits and S04.1's migration timestamp now lives in the merge-order precondition, not in a conditional protocol.

**Audit-trail preservation discipline** (handoff §8 introductory paragraph is emphatic on this): the runbook was NOT modified during UAT to preserve audit trail of what was actually run on 2026-05-28. S04.4's edits MUST be additive and MUST leave the existing §6 sign-off section (operator initials, PASS/FAIL marks, dates, sign-off paragraph) byte-identical. The six numbered edits all land in sections §1 / §2 / §4 (criteria #1 / #2 / #6 / #8) — none touches the §6 sign-off block.

M2 UAT runbook (`docs/runbooks/M2-uat.md`) is NOT drafted here — that is an E06 deliverable (S06.12 per PRD 002).

**Relevant ADRs:** none. Operator-documentation hygiene.

**Acceptance Criteria:**

- [ ] **Precondition: S04.1 has merged to `main` before S04.4 opens its PR** (verified by `git log main --oneline | grep -F '<S04.1 commit subject>'` returning a hit, OR by S04.4 branching from a commit that includes the S04.1 migration file). This hard-precondition replaces the prior deferral protocol — see Context section's "Mandatory 7th annotation — S04.1-merged precondition"
- [ ] All six edits applied to `docs/runbooks/M1-uat.md` per handoff §8 §"Runbook fixes needed before next run" items **#1, #2, #3, #4, #5, #6** (item #7 is owned by S04.3)
- [ ] **Mandatory 7th annotation**: `docs/runbooks/M1-uat.md` §6 Sign-Off table's criterion #7 row extended with "RESOLVED M2-W1 via `<S04.1's actual timestamp>_rls_license_season.sql`" — S04.1's migration timestamp is verifiable from `supabase/migrations/` directory listing as of the S04.4 branch point
- [ ] Each edit references the corresponding handoff §8 item number in the commit message (e.g., `runbook: M1-uat §4 criterion #6 build-vs-DB footnote (handoff §8 fix #4)`)
- [ ] **Audit-trail integrity preserved**: the 2026-05-28 sign-off section (§6 Sign-Off table operator marks, initials, dates, sign-off paragraph) is byte-identical pre- and post-PR; verified by `git diff` showing changes to §6 limited to the criterion #7 annotation row only
- [ ] No SQL is executed during this story (documentation-only)
- [ ] No code, schema, Pydantic, TypeScript, `architecture.md`, or test edits
- [ ] Full suite `pytest ingestion/tests/` reports **1165 passed + 2 skipped** (no test delta)

---

### S04.5: PRD 001 sequencing language reconciliation

**Status:** Not Started

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

- [ ] PM has drafted the line-by-line diff in this story's "Drafted diff" sub-section (already drafted above as of 2026-05-29 E04 epic-write)
- [ ] Diff handed to the human for review (the act of writing it into E04 + announcing E04's close fulfills this — the diff is on-record for the human at the same moment E04 is ready for implementation)
- [ ] Human applies the diff (or an amended version, after review) to PRD 001 directly
- [ ] Human confirms the PRD 001 edit has merged to main
- [ ] PM flips this story's checkbox only upon the human's merge confirmation
- [ ] PRD 001 lines 90, 96, 111 reflect the actual jurisdiction_binding sequencing after the edit lands; line 48 unchanged
- [ ] No code, schema, runbook, or planning-epic edits as part of this story
- [ ] No autonomous PM or implementation-agent edit to PRD 001 (verified by `git log --author` on PRD 001 between m1 tag and S04.5 close — only the human's commit hash should appear)
- [ ] Full suite `pytest ingestion/tests/` reports **1165 passed + 2 skipped** at S04.5 close (PRD edit does not exercise the test suite; this AC documents the baseline preservation)

---

## Exit Criteria

- [ ] All 5 stories complete (S04.1 through S04.5; S04.6 omitted per epic header)
- [ ] `license_season` RLS posture is at full parity with the original 10 entity tables (`ENABLE` + `FORCE` + 2 deny-all policies + `REVOKE ALL ON TABLE`)
- [ ] `_BINDING_COUNT_GUARD_BAND` in Montana's jurisdiction-binding loader is `(552, 1024)`; **both** prose locations name T16 / 2026-05-28 / empirical 788 / ±30% — (a) the module-level constant comment at lines 108-109 immediately following the `_BINDING_COUNT_GUARD_BAND` declaration, AND (b) the `_assert_binding_count_within_guard` function docstring at lines 679-680; AC #1087 footnote in the closed E03 epic carries both the original 2026-05-23 paragraph and a new 2026-05-29 paragraph
- [ ] `load_jurisdiction_bindings.py:main()` invokes `logging.basicConfig` at entry
- [ ] All six M1 UAT runbook hygiene fixes per handoff §8 #1-#6 are landed; the §6 sign-off section is byte-identical pre/post **except** for the criterion #7 row's "RESOLVED M2-W1 via `<timestamp>_rls_license_season.sql`" annotation (mandatory 7th edit, naming S04.1's actual migration timestamp)
- [ ] PRD 001 lines 90, 96, 111 reconciled (line 48 unchanged); the human confirmed the merge
- [ ] Test suite remains at **1165 passed + 2 skipped** baseline throughout E04; no story has a net test delta
- [ ] Montana row counts in Postgres unchanged: regulation_record 435, license_tag 825, license_season ~3040, draw_spec 276, reporting_obligation 3, jurisdiction_binding 788, geometry 350 (verified via service-role `SELECT COUNT(*)` at S04.1 close and at E04 close)
- [ ] PRD 002 success-criterion #8's `license_season` deny-all check passes against the production project after S04.1 lands; the other PRD 002 criteria are not yet exercised (Colorado data lands in E05/E06)
- [ ] No Colorado data loaded; no CO-specific code added in `ingestion/states/colorado/`

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
