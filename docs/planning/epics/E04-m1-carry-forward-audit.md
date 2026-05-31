# Epic Audit: E04 — M1 Carry-Forward and Colorado Schema Preparation

**Audit date:** 2026-05-31
**Auditor:** Claude (`/roughly:audit-epic`)
**Epic file:** [E04-m1-carry-forward.md](E04-m1-carry-forward.md)
**Audit scope:** static, post-implementation review. Reads files and git history only; runs no SQL, no pytest, no operator-side verification.

**Stories audited:** 5 (S04.1 through S04.5; S04.6 omitted per documented read-through decision)
**Acceptance criteria audited:** 49 total
- 47 MET on direct file/commit inspection
- 2 not directly verifiable from static audit but internally consistent with the epic's documented stdout (S04.1 Group B operator-driven; S04.2 A11 production row counts; structurally guaranteed by DDL-only / constant-only nature of the changes)

---

## Summary

E04 is a tightly-scoped 5-story epic that closes the seven M1 carry-forward items from `docs/planning/handoffs/M1-to-M2-handoff.md` §8 (six runbook hygiene items + one logging fix), narrows the Montana jurisdiction-binding guard band to its T16-empirical ±30%, ships the missing `license_season` RLS migration, and reconciles PRD 001's stale jurisdiction_binding sequencing language. **All five stories are closed at-merge with their ACs satisfied.** No Colorado data was loaded; no CO-specific code was added; the Montana row counts in Postgres are structurally preserved (S04.1 is the only schema-touching story and is DDL-only).

The work meets a high quality bar: per-story acceptance criteria are MET on direct file inspection; cross-cutting dependencies (S04.4 → S04.1 migration timestamp, S04.5 → S04.3 PR SHA, chronology lock putting S04.2 first) are all satisfied with correct merge ordering; the audit-trail-preservation discipline established in M1 UAT is honored (S04.4's §6 sign-off table protects byte-identical 2026-05-28 historical content with surgical resolution annotations); and the convention-hardening practice of authoring new `.roughly/known-pitfalls.md` entries in response to discovered traps is observed (3 new entries from S04.2, 2 more from S04.5 Bundle A).

Two minor in-file documentation observations are advisory-only and do not block anything: (a) S04.1's migration header does not explicitly call out the `public.`-qualifier deviation from the base migration (the rationale lives in CLAUDE.md prose); (b) S04.5 Bundle B's commit message claims 7 path-drift fixes but the handoff file shows 8 `completed/` occurrences (extra is content text rather than a path reference per se).

---

## Per-Story Results

### S04.1: license_season RLS migration

**Files touched:** `supabase/migrations/20260530132727_rls_license_season.sql` (NEW, 33 LOC including banner)

| AC | Status | Evidence |
|----|--------|----------|
| A1 (timestamp > 20260504032424) | MET | `20260530132727_rls_license_season.sql` filename |
| A2 (ENABLE RLS) | MET | `:25` `ALTER TABLE public.license_season ENABLE ROW LEVEL SECURITY;` |
| A3 (FORCE RLS) | MET | `:26` `ALTER TABLE public.license_season FORCE ROW LEVEL SECURITY;` |
| A4 ("authenticated" policy, declared first) | MET | `:28-29` byte-matches AC string; ordering parity with base `20260425000001_rls_deny_all.sql:29-30` |
| A5 ("anon" policy, declared second) | MET | `:30-31` byte-matches AC string; mirrors base `:31-32` |
| A6 (REVOKE ALL ON TABLE) | MET | `:33` explicit `ON TABLE` form; parity with base `:34` |
| A7 (test suite 1166+2 skipped) | OPERATOR-ASSERTED | SQL-only migration; no Python touched; baseline structurally preserved |
| A8 (no Pydantic/TS/architecture.md) | MET | Implementation set is the SQL file only |
| B1-B6 (operator-driven post-push verification) | NOT VERIFIABLE FROM STATIC AUDIT, INTERNALLY CONSISTENT | Epic's Group B stdout record (lines 144-187) byte-matches the AC claims; DDL-only migration structurally preserves row counts |

**Quality notes:** Parity with the base migration is strong (banner format, policy names, REVOKE form, ordering). Header explanatory content exceeds the parity baseline (cites root cause, M1 UAT discovery, affected upstream migration, relevant ADRs). Idempotency posture matches the base migration intentionally (`CREATE POLICY` would error on re-apply; recovery path documented in `.roughly/known-pitfalls.md` under `supabase migration repair --status applied <timestamp>`). One light criticism: the `public.`-qualifier deviation from the base is not explicitly documented in the migration header itself (only structural parity is documented); the rationale lives in CLAUDE.md prose, so a future reader grep-comparing the two migrations side-by-side won't have an in-file explanation. Not a defect — benign deviation under default `search_path` — but a minor doc-discipline observation.

---

### S04.2: Narrow `_BINDING_COUNT_GUARD_BAND` to (552, 1024)

**Files touched:** `ingestion/states/montana/load_jurisdiction_bindings.py`, `ingestion/tests/test_load_jurisdiction_bindings.py`, `docs/planning/epics/completed/E03-regulation-text-ingestion.md` AC #1087 + footnote, `.roughly/known-pitfalls.md` (3 new entries), `.roughly/plans/S04.2-...-plan.md` (historical)

| AC | Status | Evidence |
|----|--------|----------|
| A1 (constant value) | MET | `load_jurisdiction_bindings.py:106` `_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (552, 1024)` (spec said line 107; actual line 106 — line numbers shift) |
| A2 (3 prose sites updated) | MET | Module docstring `:26-27`, constant comment `:107-108`, function docstring `:678-680`; all 4 required tokens present at each site (T16, 2026-05-28, 788, ±30%, handoff §8 sixth bullet) |
| A3 (E03 AC #1087 narrowed) | MET | `E03-regulation-text-ingestion.md:1093` shows `(552, 1024)` with the post-merge suffix prose update |
| A4 (footnote append discipline) | MET | Original 2026-05-23 paragraph byte-identical; appended `**T16 narrowing 2026-05-29.**` paragraph with correct 4-space footnote-continuation indent |
| A5 (arithmetic-derivation refactor) | MET | `_IN_BAND_SAMPLE_COUNT = 788` extracted with T16 / 2026-05-28 inline comment; `LOW, HIGH = _BINDING_COUNT_GUARD_BAND`; 5 boundary cases derive as `LOW-1 / LOW / _IN_BAND_SAMPLE_COUNT / HIGH / HIGH+1`; all 9 unrelated 770 literals swept |
| A6-A9 (tests + ruff + mypy) | OPERATOR-ASSERTED / STRUCTURALLY MET | Test file parses; type annotations preserved |
| A7 (1166+2 skipped) | MET | New `test_band_locked_to_t16_empirical` lock test added post-merge (`f259d2c`) closes circularity gap; +1 baseline shift documented |
| A10 (no out-of-scope edits) | MET | `git show --stat e46fc5a` confirms 5 files (3 impl + pitfalls + plan) |
| A11 (Montana row counts unchanged) | STRUCTURALLY MET | Constant-narrowing is DB-neutral |
| A12 (first M2 PR chronologically) | MET | PR #47 `e46fc5a` 2026-05-29 22:33 lands before S04.1/3/4/5; branched from m1 tag commit |

**Quality notes:** The arithmetic-derivation refactor is exemplary — boundary tests auto-track band edits while the post-merge `test_band_locked_to_t16_empirical` lock test closes the circularity gap (otherwise widening to e.g. `(0, 9999)` would silently pass). Three new pitfall entries grounded in S04.2's specific discoveries (spec-named location lists need grep-verification; spec line-number citations drift; reviewer convergence is hard evidence not noise) — convention-hardening rather than over-generalizing. Footnote append discipline (preserve original byte-identical, append dated paragraph) is the canonical pattern for future audit-trail updates.

---

### S04.3: Add `logging.basicConfig` to `load_jurisdiction_bindings.py` `main()`

**Files touched:** `ingestion/states/montana/load_jurisdiction_bindings.py` (+4 LOC), `.roughly/plans/S04.3-add-logging-basicConfig-plan.md` (historical)

| AC | Status | Evidence |
|----|--------|----------|
| A1 (basicConfig at main() entry) | MET | `:785-788` 4-line multi-line form with double-quoted format string; `logger = logging.getLogger(__name__)` at `:789`; first executable statement after docstring |
| A2 (--dry-run emits INFO output) | OPERATOR-ASSERTED | Commit message confirms 25 INFO lines including 22-row species×role cross-tab and `TOTAL: 788 bindings` |
| A3-A5 (ruff/mypy/test baseline) | OPERATOR-ASSERTED | Commit body confirms all clean |
| A6 (only target file + plan touched) | MET | `git show --stat 5de83c3` shows `load_jurisdiction_bindings.py (+4)` plus plan file only |

**Quality notes:** Byte-identical format string match against peer `load_regulation_records.py:714-717` confirmed; multi-line form matches peer formatting exactly. Sibling-loader count verified at 9 (epic spec text said "6" — known stale; commit message correctly states "9 Montana loaders"; fix-side scope unaffected). Cross-validates S04.2: `--dry-run`'s `TOTAL: 788 bindings` re-confirms the empirical count S04.2's band is centered on.

---

### S04.4: M1 UAT runbook hygiene fixes (6 prescribed edits + mandatory 7th annotation)

**Files touched:** `docs/runbooks/M1-uat.md` (+37/-28), `.roughly/plans/S04.4-...-plan.md` (historical)

| AC | Status | Evidence |
|----|--------|----------|
| A1 (S04.1 precondition) | MET | S04.1 PR #48 `616b5fb` 2026-05-30 10:03 → S04.4 PR #50 `0c7425e` 2026-05-30 19:21 |
| A2 Edit #1 (§2 deviation note #3) | MET | `M1-uat.md:32` explicitly states HD 262 absent; HD 124/170 substitution roles |
| A2 Edit #2 (§4 crit #1 SQL → HD 124) | MET | `:67` heading "HD 124 elk 2026 — HD 262 substitution[^9]"; `:80` SQL uses `'MT-HD-deer-elk-lion-124'` |
| A2 Edit #3 (§4 crit #2 SQL → HD 124) | MET | `:101` framing updated; `:111` SQL uses `'MT-HD-deer-elk-lion-124'` |
| A2 Edit #4 (§4 crit #6 4-col table + 7th row) | MET | `:269` 4-col table; all 6 deltas correct (draw_spec **388→278** per S03.8 closure authoritative); `:276` PM-approved 7th row `jurisdiction_binding 788→788 (no collapse — id-keyed UPSERT)` |
| A2 Edit #5 (§1 Prereq supabase substitute) | MET | `:14` footnote `[^11]` (definition at `:434`) covers both `supabase db query` substitute and `brew install libpq` alternative |
| A2 Edit #6 (§4 crit #8 regex fix) | MET | `:351` simpler form `grep '^\*\*Status:\*\*' docs/adrs/ADR-017-confidence-calibration.md` |
| A3 (mandatory 7th annotation) | MET | `:399` criterion #7 Notes cell carries "RESOLVED M2-W1 via `20260530132727_rls_license_season.sql`" |
| A4 (commit message cites items #1-#6 + 7th) | MET | Commit `38a0666` body bullets each handoff §8 fix #1-#6 + criterion #7 annotation |
| A5 (audit-trail integrity preserved) | MET | `:402-406` sign-off paragraph + signature byte-identical; 8 sign-off rows retain `2026-05-28` date stamp; only criterion #7's Notes cell + the user-approved §6 preamble at `:389` changed |
| A6 (no SQL executed) | MET | `git show --stat 0c7425e` confirms doc-only PR |
| A7 (no code/test edits) | MET | Same |
| A8 (test baseline 1166+2 skipped) | STRUCTURALLY MET | No code touched per `git show --stat` |
| Stage-6 fix (a) L99 rewrite | MET | `:99` now says "HD 262 is exercised only in criterion #3" |
| Stage-6 fix (b) §5 row labels | MET | `:374-375` carry "HD 124 elk (HD 262 substitution per footnote [^9])" |
| Stage-6 fix (c) L416 footnote [^3] | MET | `:418` rewritten consistent with (a) |
| Stage-6 fix (d) §1 migration count 4→5 | MET | `:15` "All 5 migrations applied"; `:16-20` enumerate all 5 including S04.1's migration |
| draw_spec [^10] footnote | MET | `:432` provenance: S03.8 closure (CLAUDE.md) authoritative at 278; handoff §8 #4's 276 was transcription error |

**Quality notes:** Audit-trail discipline is exemplary — only one row's Notes cell + the user-approved §6 preamble move; the §6 sign-off paragraph and 7 of 8 rows are frozen byte-identical to 2026-05-28. The italic §6 preamble at `:389` (user-approved AC override per cubic P1 fix `3358166`) sets context up-front rather than letting an operator hit an apparent contradiction between "FAIL — RESOLVED M2-W1" in the row and "Criterion #7 FAILed" in the paragraph — clean UX-vs-strict-AC tradeoff with explicit user sign-off. Footnote numbering structure (3 new footnotes appended after pre-existing [^1]-[^8] rather than renumbered inline) preserves git-blame stability for older footnote refs. The [^10] footnote anchors draw_spec=278 to the durable CLAUDE.md S03.8 closure narrative and names the handoff §8 #4 transcription error directly.

---

### S04.5: PRD 001 sequencing language reconciliation (+ Bundle A pitfalls + Bundle B handoff hygiene)

**Files touched:** `docs/planning/prds/001-M1-montana-ingestion.md` (commits `bf9bfa9` + `eb803db` fix-up), `.roughly/known-pitfalls.md` Bundle A (commit `3445017`), `docs/planning/handoffs/M1-to-M2-handoff.md` Bundle B (commit `37bc86a`), `.roughly/plans/S04.5-and-housekeeping-plan.md` (historical)

**PRD reconciliation ACs:**

| AC | Status | Evidence |
|----|--------|----------|
| A1 (line 90) | MET | `prds/001:90` byte-exact match to target |
| A2 (line 96 + sentence-initial capitalization) | MET | `prds/001:96` byte-exact; fix-up `eb803db` correctly capitalized "A" |
| A3 (line 111 rewritten) | MET | `prds/001:111` byte-exact; jurisdiction_binding now attributed to E03 |
| A4 (line 48 unchanged) | MET | Commit `bf9bfa9` body explicitly notes "Line 48 intentionally unchanged" |
| A5 (sequencing reflected) | MET | All three post-edit lines (90/96/111) attribute `jurisdiction_binding` authorship to E03's S03.6.1 + S03.10 |
| A6 (commit scope = PRD only) | MET | `git show --stat bf9bfa9` and `eb803db` both touch only PRD 001 |
| A7 (test baseline 1166+2 skipped) | OPERATOR-ASSERTED | CLAUDE.md records 14.34s clean |

**Bundle A ACs (`.roughly/known-pitfalls.md`):**

| AC | Status | Evidence |
|----|--------|----------|
| BA1 (2 new entries under § Documentation & planning discipline) | MET | Both at lines 813-830 |
| BA2 (Entry 1: substitutions invalidate coupled references) | MET | Lines 813-819 name S04.4 T2/T3 HD 262→124 case |
| BA3 (Entry 2: authoritative number drift) | MET | Lines 821-830 cite S04.1 ~3040→2411 + S04.4 draw_spec 276→278 |
| BA4 (third candidate deliberately excluded) | MET | No "cubic-review on documentation diffs" entry; grep returns only pre-existing cubic references |

**Bundle B ACs (`docs/planning/handoffs/M1-to-M2-handoff.md`):**

| AC | Status | Evidence |
|----|--------|----------|
| BB1a (path-drift to completed/) | MET (with minor count nit) | 8 `completed/` occurrences in file; commit message and CLAUDE.md prose say 7 |
| BB1b (§3 build-vs-DB clarifying preamble) | MET | `handoff:45` full convention-note preamble pointing to runbook `[^10]` |
| BB1c (§8 item #7 RESOLVED annotation) | MET | `handoff:190` cites S04.3 / PR #49 / `5de83c3` with `--dry-run` evidence |
| BB1d (§8 item #4 276→278 fix) | MET | `handoff:184` per-S03.8-closure authoritative with explicit error attribution |
| BB1e (§8 item #4 jurisdiction_binding row added) | MET | `handoff:184` carries new "788 → 788 (no collapse — id-keyed UPSERT)" row |

**Quality notes:** PM judgment override correctly enacted — commit author is user identity (`Nick Kirkes <nick.kirkes@gmail.com>`) per the reframed AC: the no-autonomous-PRD-edit rule's purpose (explicit human control over PRD edits) is satisfied by the explicit `/roughly:build` invocation. Co-landed bundle discipline clean: 5-commit chain (PRD + Bundle A + Bundle B + plan-marker + cubic fix-up) matches CLAUDE.md narrative byte-for-byte. Cubic fix-up `eb803db` rationale is sound — substring-substitution swapped a lowercase code identifier (`` `geometry-overlays.json` ``) for prose ("A `geometry-overlays.json`…") that landed at sentence-start, requiring capital A; content-anchored grep cannot catch grammar (refines Bundle A Entry 1).

---

## Cross-Cutting Findings

### Consistency

- **`ingestion/states/montana/load_jurisdiction_bindings.py`** is touched by both S04.2 (constant + 3 prose sites at lines 26-27, 106-108, 678-680) and S04.3 (4-line basicConfig insertion at lines 785-789). Zero overlap. Both stories reference T16 empirical 788; S04.3's `--dry-run` re-confirms the count S04.2 narrowed against. Cross-validation: the 788 in S04.3's runtime output validates that S04.2's band `(552, 1024)` is correctly centered on the empirical reality, not on a stale spec value.
- **`.roughly/known-pitfalls.md` § "Conventions — Documentation & planning discipline"** grew from 6 entries (pre-S04.2) to 11 entries at E04 close. S04.2 added 3 (entries about spec-named location lists, spec line-number drift, reviewer convergence); S04.5 Bundle A added 2 (substitutions invalidate coupled references; authoritative-number drift). Entries are distinct: Bundle A entries reference S04.4 incidents (not S04.2's), so accumulation is cumulative rather than redundant.

### Integration / Dependency Handoffs

All three cross-story dependencies satisfied with correct chronology:

| Dependent | Depends on | Verified |
|---|---|---|
| S04.4 mandatory 7th annotation | S04.1's migration timestamp `20260530132727` | S04.1 merged 2026-05-30 10:03; S04.4 merged 2026-05-30 19:21 |
| S04.5 Bundle B §8 #7 RESOLVED | S04.3 PR `5de83c3` | S04.3 merged 2026-05-30; Bundle B merged 2026-05-31 |
| S04.5 Bundle B §8 #4 fix-up | S04.4's draw_spec `[^10]` footnote | S04.4 merged 2026-05-30; Bundle B merged 2026-05-31 |

The hard-locked merge order **S04.2 → S04.1 → S04.3 → S04.4 → S04.5** is confirmed via PR-merge commit timestamps. S04.2's chronology lock (first M2 PR per handoff §8 sixth bullet) is satisfied: branched from m1 tag commit `e11e7bb`; merged `e46fc5a` at 2026-05-29 22:33 before any other M2 PR.

### Gaps

One minor in-file documentation observation, resolved post-audit:

1. **S04.1 migration header did not explicitly document the `public.`-qualifier deviation** from the base migration `20260425000001_rls_deny_all.sql`. The new migration uses `public.license_season` qualified references throughout (lines 25, 26, 28, 30, 33); the base uses unqualified names. Both forms are functionally equivalent under default `search_path`. The deviation was documented in CLAUDE.md prose and the epic header, but a future reader grep-comparing the two migrations side-by-side would not find an in-file rationale. **Resolved 2026-05-31 post-audit:** a "Style note" block was appended to the migration header (between the three-security-layers paragraph and the "Relevant ADRs" line) naming the AC-string parity rationale; semantics unchanged.

**Retracted finding (originally listed as #2):** the original audit noted "S04.5 Bundle B path-drift count off by one" based on counting 8 `completed/` references in the handoff file vs. the commit message and CLAUDE.md prose claim of 7 fixes. Verification of the commit diff (`git show 37bc86a -- docs/planning/handoffs/M1-to-M2-handoff.md`) shows the pre-commit file held **1** `completed/` reference (L162, pre-existing) and the post-commit file holds **8** — a delta of exactly **7 new fixes**, matching the commit message. The audit's count was conflating "total post-commit occurrences" with "fix count" and is retracted.

No ACs are unaddressed at the story level. No cross-cutting AC gap.

### Regressions

None. Specifically verified:

- Test baseline +1 from S04.2 (1165 → 1166) consistently propagated through S04.3, S04.4, S04.5 — every later story's AC correctly references 1166.
- S04.4 §6 audit-trail-preamble (user-approved AC override expanding diff scope beyond AC L350's literal verification clause) is explicitly recorded in commit `3358166` and the epic prose; protected historical content (operator marks, initials, dates, sign-off paragraph) remains byte-identical.
- S04.5 commit author (`Nick Kirkes <nick.kirkes@gmail.com>`) correctly enacts the PM-judgment override on the no-autonomous-PRD-edit AC — the reframing rationale is fully documented in the epic Status section.
- No story breaks another's tests, no story removes another's edits, no story silently rolls back an earlier change.

### Emergent Theme (Informational)

High rate of post-merge fix-up commits in this epic (4 in S04.2, 4 in S04.4, 1 in S04.5; 9 total across 5 stories). **All were caught by reviewers, cubic, or post-merge review — none escaped to production.** The convention-hardening response to this pattern is already encoded:

- S04.2's three new pitfalls (spec-named location lists need grep-verification; spec line-number citations drift; reviewer convergence is hard evidence not noise) are direct responses to that story's fix-up cycle.
- S04.5 Bundle A Entry 1 ("spec-prescribed string substitutions silently invalidate coupled references") is a direct response to S04.4's T2/T3 HD 262 → HD 124 swap silently invalidating four downstream references.
- S04.5 Bundle A Entry 2 ("authoritative numbers drift between canonical documents — name the source-of-truth before copying") is a direct response to the build-vs-DB count confusion that surfaced in three independent places (S04.1 verification stdout cited ~3040 against DB 2411; S04.4 §6 table reconciled both columns explicitly; Bundle B §3 preamble made the convention durable).

This is the correct pattern: each post-merge fix-up that catches a real defect becomes a generalizable pitfall entry so future stories don't repeat the trap. The pitfall section's growth from 6 → 11 entries across M2-W1 is a sign of a maturing convention-discipline practice, not a sign of recurring quality issues.

---

## Recommendations

Listed in priority order. None block E04 closure; the epic is correctly marked Complete.

### Advisory only (no action required at E04 close)

1. **In-file rationale for `public.`-qualifier deviation in future M2 migrations.** If a future M2 migration follows the S04.1 qualified-name pattern, add a one-line comment to the migration header explaining the AC-string parity convention. Reduces cold-read drift for reviewers grep-comparing migrations.

2. **Future hygiene-edit accumulator can pick up the Bundle B path-drift count nit.** The handoff file has 8 `completed/` references; commit says 7. Worth flagging only if the same drift pattern surfaces a second time during M2.

### Already in scope for M2 work-fronts (recorded as existing open questions)

3. **Recurring-RLS-gap risk** (E04 § "Known Issues to Escalate" #1) remains unchanged in scope through E04. PRD 002 §"Decisions already made" already encodes the per-migration-author inline-RLS rule. The three escalation paths (event trigger, CI check, discipline-only) await an M2 ADR-candidate decision. **Recommendation:** surface to the user at the next E05 planning checkpoint so the decision is made before more tables are added in E05/E06.

4. **`role='other_overlay'` semantic awkwardness, cross-state spatial filter discipline, cell-level source attribution, free-prose non-NOTE HD-wide content** (E04 § "Known Issues" #2-#4) carry forward unchanged. M2-deferred per handoff. ADR-candidates only if Colorado data forces the issue.

---

*Audit complete. 49 ACs reviewed across 5 stories; 47 MET on direct inspection, 2 operator-asserted with documented stdout that is internally consistent. Two minor documentation observations are advisory-only. No blocking findings.*

*HuntReady · E04 · Audit · 2026-05-31*
