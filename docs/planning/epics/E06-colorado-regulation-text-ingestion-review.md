# E06 Pre-Implementation Review

**Epic:** [E06 — Colorado Regulation Text Ingestion](E06-colorado-regulation-text-ingestion.md)
**Reviewer:** Roughly `epic-reviewer` (model: opus)
**Date:** 2026-06-08
**Verdict:** **Ready** (minor revisions recommended — no blockers)

**Resolution (2026-06-08):** All 6 actionable findings (1 MUST-FIX, 2 SHOULD-FIX, 3 CONSIDER) addressed in the epic file:

1. S06.0 AC #131 reworded to "5 pre-registered + conditional 6th" (count consistent across lines 91/95/131/779/801).
2. S06.9 drift-guard AC corrected (`helper_name`=dispatch-dict name, mandatory `id_field`, callable signature aligned to `_derive_expected_id_suffix`).
3. Group-A-at-merge / Group-B-operator-pending split stated explicitly in S06.6 Context + a new Exit Criteria bullet.
4. S06.8 AC #567 coupling lock softened to "observed-at-extraction, contradictions→flag-and-discuss."
5. S06.0 AC #132 `Content-Length` demoted to informational; SHA-256 named as the authoritative drift gate.
6. New Known Issue #7 flags the CPW brochure URL as the single highest-likelihood epic-stall cause.

---

## Summary

E06 is an unusually large, highly-prescriptive epic (12 stories, hundreds of ACs) that ports the M1/E03 regulation-text ingestion pipeline to Colorado. The reviewer grep-verified the load-bearing external claims — MT precedent line numbers, imported scaffold symbols, schema-type claims against both `architecture.md` and the Pydantic `schema.py`, enum value lists, the draw-schema-proposal numbers, and the test baseline — and **they are overwhelmingly accurate**, which is notable given this project's documented "line-citation drift" failure mode. The epic correctly anticipates that S06.2/S06.3/S06.4 scope is genuinely unknown until the live CPW PDF is read, and wisely defers those structures to Stage-1 discovery rather than over-specifying. The findings below are a small number of internal-consistency nits (the 5-vs-6 decision framing, two precise S06.9 AC mis-citations) plus a structural concern about the heavy operator-Group-B coupling and one overengineering observation. None rise to blocker status.

---

## Findings by Dimension

### 1. Technical Accuracy

The few issues (overwhelmingly accurate otherwise — see Verified-Accurate list):

- **SHOULD-FIX — S06.9, AC line 623.** The AC instructs calling `assert_dispatch_dict_drift_free(... helper_name="upsert_reporting_obligation" ...)`. The MT precedent at `ingestion/states/montana/load_reporting_obligations.py:342-348` passes `helper_name="_REPORTING_ROW_SPEC"` (the dispatch-dict's name, used in the RuntimeError message) and crucially `id_field="id_suffix"` (not the default `"id"`). The epic's `helper_name` value contradicts the precedent it cites, and the AC omits the `id_field="id_suffix"` argument entirely — load-bearing because `assert_dispatch_dict_drift_free` defaults `id_field="id"` (`drift_guard.py:16`) while the reporting-obligation dispatch dict keys its id under `id_suffix`. **Fix:** change the AC to `helper_name=<dispatch-dict-name>` and add the `id_field="id_suffix"` requirement (or whatever the CO dict uses).

- **SHOULD-FIX — S06.9, AC line 623 callable name.** The AC requires a pure `_derive_reporting_obligation_id(key, entry)` callable. The MT precedent's callable is `_derive_expected_id_suffix(kind, deadline_hours, region_scope)` (`load_reporting_obligations.py:295`), invoked via a lambda adapter. Naming/signature divergence presented as "mirrors :342" — the mirror is imperfect. **Fix:** either adopt the MT signature shape or drop the "mirrors :342" framing for the callable specifically.

- **CONSIDER — S06.0, AC line 132.** Requiring `Content-Length` captured verbatim and compared against baseline can false-positive: `Content-Length` can legitimately vary across CDN re-compression/transfer-encoding without the PDF bytes changing. The SHA-256 pin (S06.1's real contract) is the authoritative drift gate. Soften `Content-Length` to "informational, not a hard drift gate."

### 2. Best Practices

The epic faithfully reproduces every established M1/E03/E05 convention, all confirmed to exist:

- Three-phase transaction (build → guards pre-`db.connect()` → conn/commit) across S06.6–S06.10.
- OQ7 ±30% count guards firing pre-`db.connect()` on every DB-write story.
- State-agnostic-clean AST guards (`TestNoColoradoLeakIntoSharedLib`, `TestNoLibImports`).
- ADR-020 drift-guard mandate correctly distinguishes `assert_id_matches` (runtime row-construction, S06.7) from `assert_dispatch_dict_drift_free` (compile-time dispatch dict, S06.9), and correctly preserves the `db.upsert_jurisdiction_binding` and link-table-builder carve-outs. Both primitives confirmed at `drift_guard.py:11,44`.
- Additive-tests-only posture with the **verified** 1346-passed-+-2-skipped floor (pytest run confirmed `1346 passed, 2 skipped`).

No better-approach findings — the conventions are mature and the epic stays inside them.

### 3. Risks

- **SHOULD-FIX — operator-Group-B coupling is the dominant schedule risk, correctly identified but under-mitigated in AC structure.** S06.6–S06.11 cannot execute against live state until six outstanding E05 Group B operator writes land (`Inputs from E05` §, line 64; Known Issues #1, line 830). Several S06.6–S06.10 ACs are written as live-verification ACs (e.g., S06.10 AC line 703). A large fraction of E06's ACs are therefore operator-pending at merge time (the E05 Group-A/Group-B split). That model is right, but the epic should state explicitly **up front** (S06.6 header or Exit Criteria) that S06.6–S06.10 close with Group-A-at-merge / Group-B-operator-pending, so a future PM doesn't read unticked live-verification ACs as incomplete work.

- **CONSIDER — S06.3/S06.4/S06.5 cascade on a single unresolved URL.** The CPW Big Game brochure URL (404 on all 4 candidates as of 2026-06-03) gates S06.1 → S06.3 → S06.5 → S06.6+ — essentially the entire DB-write half. Handled correctly via S06.0 decision #4 (operator-resolved, HEAD-verified, cover-page-2026-confirmed). Residual risk is purely external; worth flagging in Known Issues as the single highest-likelihood epic-stall cause.

- **CONSIDER — S06.4 fold-into-S06.3 ambiguity propagates.** Whether Black Bear is a separate brochure or a Big Game section is "TBD at S06.1 discovery"; multiple downstream ACs branch on it. Genuinely unknowable pre-PDF and the conditional structure is appropriate; merge-order line 775 lists S06.4 as "may fold into S06.3" which the implementer must resolve before sequencing.

### 4. Overengineering

- **CONSIDER — S06.8 AC #567 coupling-lock test may be too rigid against pre-PDF reality.** The AC asserts `len(pools)==2 ⇒ residency_cap.nonresident_max_share==0.20` and `len(pools)==1 ⇒ ==0.25`. The draw-schema-proposal supports this coupling but stresses the determination is **upstream** of the schema and that the floor and split are administrative parameters CPW can adjust. Hard-coding the biconditional as a test invariant pre-commits to a structure the epic's own "do not trust research notes against the live PDF" principle (line 239) says will likely change. There is a flag-and-discuss escape (L522), but the locked-test and the escape are in mild tension. Recommend phrasing AC #567 as "lock the coupling **as observed at S06.8 extraction**, contradictions→flag-and-discuss" rather than as an a-priori invariant.

- **CONSIDER — general prescriptiveness.** Pre-specifies LOC ranges, test counts, and exact pool-share literals for stories whose source PDF hasn't been read. LOC/test-count ranges are harmless guidance, but combined with dozens of pre-registered ACs they add process cost. Deliberate house style (matches E05, which shipped clean), so CONSIDER not SHOULD-FIX — but a leaner S06.3/S06.4 (explicitly discovery-driven) would lose little.

### 5. Acceptance Criteria Quality

- **MUST-FIX — S06.0 internal 5-vs-6 decision-count inconsistency.** Grep-confirmed: line 91 says "**5** pre-registered decisions," line 95 header says "(5)," line 779 says "the **5** pre-registered decisions are captured," and lines 801-807 list exactly **5** — but **AC line 131** says "the **6** pre-registered decisions captured verbatim." The reconciliation is 5 pre-registered + a "**Conditional 6th decision**" (`db.update_geometry_verbatim`, AC line 138). AC #131 will read as requiring 6 captured decisions while the Context enumerates 5. **Fix:** make AC #131 say "the 5 pre-registered decisions plus the conditional 6th (`db.update_geometry_verbatim`)" or "5+1 conditional," and make the count consistent across lines 91/95/131/779/801.

- **SHOULD-FIX — S06.6 AC #428 statewide-anchor count testable but data-dependent.** "PM expects 0-2 statewide-anchor rows; a 3rd is a process violation" is a good guard but only verifiable post-extraction, and the "0-2" band is a transplant of MT's 2 anchors with no CO-data basis. Reasonable heuristic guard; note it cannot be a pre-implementation test.

- **CONSIDER — S06.7 AC #492** correctly says "every per-row entity-construction site" (robust) rather than "4 sites," and the MT `:589/660/926/1100` citations all verify. CO's source split will differ in count; the "fanned by source" language handles this. No change required.

### 6. Dependencies

The dependency graph is sound; the E05→E06 handoff wiring verified:

- The S05.6 scaffold exports exactly the four symbols S06.10 imports — `_STATE` (L55), `_NO_HUNT_ZONE_NEARBY_DISTANCE_M` (L59), `_QUERY_NEARBY_GMUS_FOR_ZONE_SQL` (L75), `query_nearby_gmus_for_zone` (L85), with no `main()` — exactly as line 676 states.
- `EXPECTED_CO_RA_ORPHAN_IDS` with `assert len()==10` exists in `build_overlay_fixture.py` (L205/L219).
- `_VALID_ROLE_FOR_E03` is MT-only, 4-value, excludes `no_hunt_zone` (`load_jurisdiction_bindings.py:417`) — Known Issue #6's premise (line 98) confirmed.
- S06.0 → {S06.1, S06.5, S06.9, S06.10} decision-gating is real and necessary (each downstream spec materially depends on a human decision). Not ceremony.
- Merge order (line 775) is correctly FK-ordered: regulation_record → link tables → draw_spec backfill → reporting → bindings → UAT.

- **CONSIDER** — S06.10 `Depends on` (line 682) lists S06.9, and S06.10 writes `regulation_reporting` links; S06.9 deliverables (line 611) say those links are "written by S06.10's binding loader." Consistent on close reading (S06.9 writes obligations, S06.10 writes links) but a reader could misread S06.9 as writing links. Wording is fine; flagged only for internal-consistency completeness.

### AC Mutual Satisfiability (checked)

- S06.8 #564 (`inactive_forfeit_years IS NULL`) vs #565/#566 (pool shapes + Final constants) vs proposal — jointly satisfiable; CO `inactive_forfeit` absent vs WY `=2` confirmed (proposal L219; schema.py L157).
- S06.8 #569 (`successor_hunt_code_key` composite object) vs #567/#570 — consistent with committed schema (architecture.md L220, schema.py L317); epic correctly flags the proposal's bare-string form (L102) as stale.
- S06.10 #691 (zero-row portion code path) vs #692 vs "4 builders" — jointly satisfiable; portion path deliberately preserved for M3+, no count-guard conflict (CO has zero `kind='portion'`).
- S06.0 #137 option (a)/(c) — mutually-exclusive branches of one decision, each internally consistent; not a conflicting pair.

**No structural-impossibility AC pairs found.** The only AC-pair tension is the soft S06.8 #567 rigidity concern above, not a joint impossibility.

---

## Verified-Accurate List (checked against the codebase, not taken on trust)

- MT drift_guard call sites `load_seasons_and_licenses.py:589/660/926/1100` — **all four exact**.
- MT id-derivation `_season_definition_id:370` / `_license_tag_id:387` — **exact**.
- MT `_JURISDICTION_BINDING_ID_FORMAT` at `load_regulation_records.py:115`, format `"{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"` — **confirmed**.
- MT binding loader binds distance as `%s` param; `_STATE: Final = "US-MT"` — **confirmed**.
- S05.6 CO scaffold exports the four imported symbols, no `main()` — **confirmed**.
- `architecture.md`: `purchase_only_code: string | null` (L346), `inactive_forfeit_years: number | null` (L347), `successor_hunt_code_key:{state,hunt_code,year}` (L220), `application_deadline` on `DrawSpec` (L221), `points_used_in_choices: number[]` (L354) — **all confirmed**.
- Pydantic `schema.py`: `successor_hunt_code_key: DrawSpecKey | None` (L317), `application_deadline: datetime.date` (L318), `purchase_only_code: str | None` (L157), `ClosurePredicate.kind` has `quota_threshold`/`sex_threshold` (L102) — **confirmed**.
- Enum value lists (`PointSystem.kind` 3, `AllocationPool.selection` 4, `ReportingObligation.kind` 6, `SourceCitation.document_type` 5) — **all match architecture.md**.
- Draw-schema-proposal: 80/20 split (L14), 20%/25% residency coupling (L16), min_points 5 (L14/L200), CO `inactive_forfeit` absent vs WY `=2` (L219), 2028 50/50 reform (L278), stale bare-string `successor_hunt_code` (L102) — **all confirmed; epic's "proposal is stale" claim correct**.
- `EXPECTED_CO_RA_ORPHAN_IDS` `len==10` (`build_overlay_fixture.py` L205/L219) — **confirmed**.
- `_VALID_ROLE_FOR_E03` MT-only, 4-value, excludes `no_hunt_zone` (L417) — **confirmed**.
- `overlays.py` exports `ROLE_FOR_BINDING_BY_CHILD_KIND`; `OverlayChildKind` includes `"gmu"` (L20/L74) — **confirmed**.
- Test baseline **1346 passed + 2 skipped** — **confirmed by running pytest**.
- `effective_after` **absent** from architecture.md and schema.py — **confirmed** (correctly treated as ADR-candidate).
- Q18/Q16/Q17/Q12/Q19 statuses in `docs/open-questions.md` — **confirmed** (Q19 RESOLVED via ADR-020; others open; S05.3 second-CWD-state breadcrumb at L379-381).

---

## Top Priorities Before Implementation

1. **(MUST-FIX) Reconcile the S06.0 5-vs-6 decision count.** AC line 131 says "6" while lines 91/95/779/801 say "5" (the 6th is the conditional `db.update_geometry_verbatim`). Recommend "5 pre-registered + 1 conditional," consistent across all five locations.
2. **(SHOULD-FIX) Fix S06.9 AC #623's two MT-precedent mis-citations.** Actual call at `load_reporting_obligations.py:342` passes `helper_name="_REPORTING_ROW_SPEC"` (not `"upsert_reporting_obligation"`) and the load-bearing `id_field="id_suffix"` (AC omits it; default is `"id"`). Reconcile the `_derive_reporting_obligation_id` callable against actual `_derive_expected_id_suffix(kind, deadline_hours, region_scope)`.
3. **(SHOULD-FIX) State the Group-A-at-merge / Group-B-operator-pending split explicitly for S06.6–S06.10** (S06.6 header or Exit Criteria), so unticked live-verification ACs aren't misread as incomplete.
4. **(CONSIDER) Soften S06.8 AC #567** from an a-priori coupling invariant to an "observed-at-extraction, contradictions→flag-and-discuss" lock.
5. **(CONSIDER) Demote `Content-Length` in S06.0 AC #132** from hard drift gate to informational; keep SHA-256 (S06.1) as the authoritative drift contract.
