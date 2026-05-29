# E04 Epic Review

**Reviewed:** 2026-05-29
**Reviewer:** Roughly epic-reviewer (opus)
**Epic:** [E04-m1-carry-forward.md](E04-m1-carry-forward.md)

---

# Epic Review: E04 — M1 Carry-Forward and Colorado Schema Preparation

**Verdict:** Ready (with two P1 advisory findings worth addressing pre-implementation; no blockers)

## Summary

E04 is a well-formed maintenance epic. Every AC traces to a verifiable target in the handoff document or codebase. Story scopes are tightly drawn, the merge-order chronology is justified, and the epic correctly omits S04.6. The PM has already done a validation pass; I verified the load-bearing technical claims independently (file paths, line numbers, line contents) and found them accurate. Two advisory findings worth raising before implementation: a hidden cross-story coupling risk in S04.4's "deny-all-merged-first" precondition, and a minor mypy-target inconsistency in S04.2's AC.

## By Dimension

### Technical Accuracy

- **S04.1 migration body verified correct.** `supabase/migrations/20260425000001_rls_deny_all.sql:1-82` confirms the four-artifact-per-table pattern (ENABLE + FORCE + 2 deny-all policies + `REVOKE ALL ON TABLE`). The epic's migration body at lines 70-82 is a faithful copy of the per-table block (e.g., the `regulation_record` block at `20260425000001_rls_deny_all.sql:26-34`). PRD-cited policy name ordering ("Deny all access for anon" first) is a cosmetic divergence from the base migration's ordering ("Deny all access for authenticated" first) — non-functional, but worth aligning for grep-parity. P2.
- **S04.2 line-number citations verified.** `ingestion/states/montana/load_jurisdiction_bindings.py:107` is `_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (400, 1100)` as claimed. Lines 108-109 carry the "Intentionally wide pending T16" comment — but note this is a **module-level constant comment**, not the docstring at `_assert_binding_count_within_guard` (lines 679-680). The epic correctly identifies both locations (lines 108-109 AND the function docstring at 676-682), but AC #2 (epic line 182) says only "docstring no longer says 'intentionally wide pending T16's empirical count'". The phrase appears in **both** the module-constant comment (line 108-109) AND the function docstring (line 680). Implementation agent should update both. P2.
- **S04.2 test boundary values verified.** `ingestion/tests/test_load_jurisdiction_bindings.py:1175-1188` confirms the 5 hardcoded boundary values (399, 770, 1101, 400, 1100). Additional unrelated `770` literals appear at lines 1446, 1463, 1465, 1479, 1486, 1507, 1938, 1958, 2005, 2036 — these are synthetic-binding count generators, not `TestCountGuard` cases, and are NOT mentioned in the epic. Leaving them as 770 won't break tests, but leaving 770 here while changing the `TestCountGuard` value to 788 creates an inconsistency where "in-band sample count" diverges in two test classes. P2 — flag for implementation agent: decide whether to update these to 788 for consistency or leave at 770 (existing arbitrary in-band value).
- **PRD 001 line numbers verified.** Lines 48, 90, 96, 111 contain exactly the text the epic quotes. The PM correctly identifies line 48 as not requiring an edit.
- **M1 UAT runbook target strings verified.** `MT-HD-deer-elk-lion-262` appears at lines 29, 72, 79, 110, 178; the broken regex `^(\*\*Status\*\*|Status):` appears at line 350; the §6 Sign-Off table starts at line 386 with criterion row format `| Criterion | Operator sign-off | Date |`.
- **AC #1087 + footnote verified.** `docs/planning/epics/completed/E03-regulation-text-ingestion.md:1093` contains the AC #1087 checkbox with `(400, 1100)`; footnote `[^row-count-correction]` at line 1095 contains the 2026-05-23 audit-trail paragraph the epic asks to preserve verbatim.

### Best Practices

- **S04.1 follows the right migration-discipline pattern.** A new per-table follow-up migration is the correct response — modifying the original `20260425000001` migration would violate the immutable-after-applied discipline. The `FORCE` addition (epic line 84) correctly catches a template gap the handoff §8 example missed. No `bypassrls` configuration needed — service-role bypass is project-level, not per-table. P3 — nothing to fix.
- **S04.3's no-regression-test decision is defensible.** A test like "assert main() calls logging.basicConfig" would indeed lock implementation detail (matches the ADR-009 documentation-discipline philosophy where observable behavior, not internal calls, gates correctness). The deferral to operator-observational verification is consistent with how other ingestion-adapter "ergonomics" fixes have been handled. P3.
- **S04.5's PM-vs-human edit discipline is well-enforced.** AC #7 at epic line 340 (`git log --author` showing only human's commit hash) is a verifiable gate. The status-flow table at lines 309-316 makes the workflow explicit. P3.

### Risks

- **S04.4's "optional 7th annotation" creates a hidden cross-story coupling.** Per epic line 268, the criterion #7 sign-off-row annotation is conditional on S04.1 having merged first. The recommended merge order at line 368 puts S04.1 before S04.3 + S04.4, so the happy path includes the annotation. But if S04.4 lands before S04.1 (which the epic permits — line 366 says "S04.3 and S04.4 are mechanical hygiene and can land in any order after S04.1" but the merge order isn't a hard lock), the deferral protocol fires: the annotation moves into S04.1's PR. That's a code-side migration story now also responsible for a documentation edit, which expands S04.1's scope mid-flight. **P1 — recommend making the merge order S04.2 → S04.1 → S04.3 → S04.4 → S04.5 a hard precondition** (add an AC to S04.4: "S04.1 has merged before this story opens") rather than handling the conditional with a deferral protocol. Simpler and removes the cross-PR coordination cost.
- **Service-role bypass assumption (S04.1 AC #11) is reasonable but worth verifying.** Epic line 132 asserts `SELECT COUNT(*) > 0` proves service-role bypass works. This relies on the Supabase project having `bypassrls` granted to the `service_role` role (default Supabase behavior). The verification will catch a misconfiguration, but the AC could be stronger: "service-role connection (not the migration-runner connection) returns > 0 rows" — clarifies whose creds are tested. P2.
- **S04.2 band narrowing risk.** 788 was a single empirical observation. The ±30% band [552, 1024] is generous enough to absorb seasonal/annual MT data variation (the historical wide band was [400, 1100], a wider [-50%, +40%] effective range). The narrower band is justified by handoff §8's explicit instruction; the risk is bounded by OQ7 fail-loud — a regression band-exit raises before write. P3.
- **S04.4 audit-trail AC is testable** (epic line 280: `git diff` evidence shows no §6 changes). Well-formed AC.

### Overengineering

- **"Known Issues to Escalate" §1 (recurring-gap mitigation).** Epic lines 378-383 raise 3 options (event trigger / CI check / discipline-only) for the future-table RLS-gap risk. The PM explicitly scopes this OUT of E04 ("not E04 scope") and recommends surfacing it as an M2 open question. That's the right call — surfacing a real systemic risk without expanding the epic's scope. P3.
- **S04.2's coordinated 4-edit + 5-test-update approach.** Could be simpler. AC #5 at epic line 185 already allows an arithmetic-derivation refactor (compute `(low+1, high-1, low, high)` from `_BINDING_COUNT_GUARD_BAND` at module-test scope). Worth flagging this option as the recommended path for the implementation agent — it eliminates a future maintenance step if the band ever narrows again. P2.
- **S04.5's status-flow table.** Verbose for a 4-line PRD edit. Justified because it documents a coordinated PM-human workflow that's new; future PMs picking up similar stories will benefit. P3.

### AC Quality

- **S04.1: 13 ACs, well-formed.** AC #13 (epic line 134) explicitly clarifies the no-Pydantic/TS edits scope — useful guardrail. No redundancy.
- **S04.2: 11 ACs, well-formed.** Note AC #2 (epic line 182) names only "docstring" but the "intentionally wide pending T16" phrase lives in both the module-constant comment (lines 108-109) AND the function docstring (lines 679-680). See Technical Accuracy finding above. P2.
- **S04.3: 6 ACs.** AC #2 (epic line 232) is observational ("INFO-level output on stderr") which is the correct level of testability for an ergonomics fix.
- **S04.4: 7 ACs, audit-trail integrity verifiable.** AC #3 (epic line 280) is concrete and testable via `git diff`. AC #4 (epic line 281) handles the deferral protocol explicitly.
- **S04.5: 8 ACs.** AC #7 (epic line 340 `git log --author` check) is a strong autonomous-edit prevention gate.

### Dependencies

- **S04.2-first chronology lock is justified.** Handoff §8 sixth bullet is explicit; the lock has audit-trail value (links the band-narrowing PR to the M1 T16 observation lineage). The lock has zero cost — S04.2 has no dependency on any other E04 story.
- **S04.5 timeline-overlap with S04.1-S04.4 — no merge-conflict risk.** The PRD 001 file is not touched by any other story. PM-drafts → human-applies → PM-confirms cycle is correctly decoupled.
- **Hidden coupling between S04.1 and S04.4 via the optional 7th annotation.** See Risks finding above. **P1.**

## Recommendations

- **S04.4: convert "optional 7th annotation" to a hard precondition.** Add AC to S04.4: "S04.1 has merged before this PR opens." Remove the deferral-protocol AC. Simpler workflow, no cross-PR coordination cost. **(P1)**
- **S04.2: explicitly direct the implementation agent to update both the module-constant comment (lines 108-109) AND the function docstring (lines 679-680).** Current AC #2 is ambiguous about scope. **(P2)**
- **S04.2: prefer the arithmetic-derivation refactor for the test bounds.** Epic line 185 already permits it; recommending it eliminates a future maintenance edit if the band narrows again post-M2. Also resolves the 770-literal-elsewhere consistency question. **(P2)**
- **S04.1: align policy-name ordering with the base migration** ("Deny all access for authenticated" first, "Deny all access for anon" second) to match `20260425000001_rls_deny_all.sql:29-32`. Non-functional but helps grep-parity. **(P2)**
- **S04.1 AC #11: clarify whose connection runs the bypass test** (service-role explicit, not migration-runner). **(P2)**

Relevant file paths for reference:
- [docs/planning/epics/E04-m1-carry-forward.md](E04-m1-carry-forward.md)
- [supabase/migrations/20260425000001_rls_deny_all.sql](../../../supabase/migrations/20260425000001_rls_deny_all.sql)
- [supabase/migrations/20260504032424_e03_schema_additions.sql](../../../supabase/migrations/20260504032424_e03_schema_additions.sql)
- [ingestion/states/montana/load_jurisdiction_bindings.py](../../../ingestion/states/montana/load_jurisdiction_bindings.py) (lines 100-115, 670-690, 765-790)
- [ingestion/tests/test_load_jurisdiction_bindings.py](../../../ingestion/tests/test_load_jurisdiction_bindings.py) (lines 1159-1190)
- [docs/runbooks/M1-uat.md](../../runbooks/M1-uat.md) (lines 29, 72, 79, 110, 178, 350, 386-399)
- [docs/planning/epics/completed/E03-regulation-text-ingestion.md](completed/E03-regulation-text-ingestion.md) (lines 1093-1120)
- [docs/planning/prds/001-M1-montana-ingestion.md](../prds/001-M1-montana-ingestion.md) (lines 48, 90, 96, 111)
