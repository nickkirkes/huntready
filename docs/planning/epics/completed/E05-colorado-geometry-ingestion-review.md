# Epic Review: E05 — Colorado Geometry Ingestion

**Date:** 2026-05-31
**Reviewer:** Roughly epic-reviewer (opus)
**Epic file:** [E05-colorado-geometry-ingestion.md](E05-colorado-geometry-ingestion.md)
**Verdict:** **Ready (LAND-WITH-MINOR-EDITS)**

The validation triad already did most of the heavy lifting (14 MUST-FIX + 9 SHOULD-FIX applied at draft time). The residual findings are minor: one off-by-one line citation, one mis-quoted "before-state" snippet, and a handful of defensive-default clarifications. No story-level rework needed; no ADR triggers missed.

---

## Confirmed-accurate (load-bearing for the verdict)

The most consequential technical claims were verified against the actual codebase:

| Epic claim | Source-of-truth check | Result |
|---|---|---|
| `arcgis.py:705-708` pagination params with `outSR=4326` at `:705` | [arcgis.py:700-709](../../../ingestion/ingestion/lib/arcgis.py#L700-L709) | **Accurate** — `outSR: 4326` is exactly at line 705 inside `base_params` |
| `arcgis.py:678/703` OID-field handling | Lines 678 (`where_clause = f"{metadata.object_id_field}>=0"`) + 703 (`orderByFields`) | **Accurate** |
| `arcgis.py:107-118` per-host throttling | `_throttle` is at 107-118 verbatim | **Accurate** |
| `arcgis.py:60-72` `_default_user_agent` reads env at call time | Lines 60-72 match exactly | **Accurate** |
| `arcgis.py:248-265` error-envelope check | Lines 248-265 match exactly | **Accurate** |
| `arcgis.py:953-998` `build_source_citation` with ADR-014 `publication_date` rule | Lines 953-998 match; `publication_date = f"{license_year:04d}-01-01"` at 986 | **Accurate** |
| `arcgis.py:397-408` global-WGS84 guard (not state-parameterized) | `_coordinates_in_wgs84_range` at 397-408 — recursive `|x|<=180, |y|<=90` only | **Accurate** — Spatial × ArcGIS Fidelity conflict resolution stands |
| MT overlay fixture has no statewide rows | `grep -c '"parent_kind": "state"\|STATEWIDE'` returns 0 | **Accurate** — S05.5's "no statewide pre-emit" claim matches MT precedent |
| `jurisdiction_binding.geometry_id REFERENCES geometry(id)` (FK cascade) | [supabase/migrations/20260425000000_initial_schema.sql:199-200](../../../supabase/migrations/20260425000000_initial_schema.sql#L199-L200) | **Accurate** — S05.7's wipe-order discipline is real |
| E02 runbook uses bare `ST_*` calls | Lines 18/40/54/63/67/90 of [E02-geometry-verification.md](../../runbooks/E02-geometry-verification.md) | **Accurate** — the `extensions.`-prefix deviation in S05.7 is justified |

The two highest-stakes structural claims — global-WGS84 guard, no MT statewide pre-emit, FK cascade reality, E02 runbook bare-`ST_*` deviation — all check out.

---

## Findings by dimension

### 1. Technical accuracy — **Ready (with MUST-FIX line-number correction)**

**MUST-FIX (T-1) — S05.6 line citation drift.** Epic L452 + L460 cite `load_jurisdiction_bindings.py:111` for `_STATE`. Actual location is **line 110**. Line 111 is `_LICENSE_YEAR`. This is exactly the "spec line-number citations drift between spec authoring and execution" pitfall (one of the 5 entries Bundle A added 2026-05-31). The epic even calls this out: "verify exact line numbers at story implementation time per pitfall #1 from `.roughly/known-pitfalls.md` Bundle A" (L460) — the inline disclaimer is correct, but the wrong citation should be fixed now.

**Fix:** Change `:111` → `:110` at L452. Also re-confirm the dual `:587/740` citation at L460 — only `:587` is `_query_nearby_hds_for_zone`'s `cur.execute(sql, ...)` call inside the function; `:740` is the `cur.execute(sql, (_STATE, _LICENSE_YEAR))` of `_load_non_statewide_reg_records`, a different function. The dual-citation is *misleading*. Collapse to just `:587` for the nearby-zone query, or clarify both.

**SHOULD-FIX (T-2) — `overlays.py` current-state misstated.** Epic L362 says current `OverlayChildKind = Literal["portion", "cwd_zone", "restricted_area"]` (3 values). Actual at `overlays.py:67`:

```python
OverlayChildKind = Literal["hunting_district", "portion", "cwd_zone", "restricted_area"]
```

(4 values — `hunting_district` is already in the set as the self-row case). The existing `ROLE_FOR_E03_BY_CHILD_KIND` already maps `"hunting_district" → "primary_unit"` at `overlays.py:122`. The epic's symmetric CO addition (`"gmu" → "primary_unit"` for the GMU self-row) is correct in spirit, but the "before" state at L361-363 is mis-quoted.

**Fix:** Correct L362's "before" snippet to show 4 values, including `"hunting_district"`. Adjust the proposed extension at L368 to show all 5 values (`"hunting_district", "portion", "cwd_zone", "restricted_area", "gmu"`).

**Confirmed-accurate (no change needed):** All other line citations to `arcgis.py` (705-708, 678/703, 705, 107-118, 60-72, 248-265, 953-998, 397-408) and the FK-cascade DDL claim at S05.7 step 6.

---

### 2. Best practices — **Ready**

**SHOULD-FIX (B-1) — `OverlayParentKind` extension docstring sync missed.** Epic L367-369 proposes `OverlayParentKind = Literal["hunting_district", "gmu"]` but the existing docstring at `overlays.py:59-65` says "V1 scope: only hunting districts act as parents. Extend this Literal (and update `ROLE_FOR_E03_BY_CHILD_KIND` if needed) when additional parent kinds are introduced." S05.5's plan to add `"gmu"` is the documented-correct extension path; the epic should explicitly note the docstring update lands alongside. Trivial but the maintained sync-contract convention warrants explicit mention.

**Confirmed-accurate (S05.7's `extensions.`-prefix deviation from E02 runbook):** Verified the E02 runbook uses bare `ST_*` calls (lines 18/40/54/63/67/90). The 2026-05-27 timeline entry "E02 Runbook Has Latent Bug — Uses Bare ST_* Calls Without extensions. Prefix" confirms this is a known gap. S05.7's protocol of fully prefixing all `ST_*` calls is correct and propagates the right convention forward.

**Confirmed-accurate (statewide rows not pre-emitted in S05.5):** MT's `geometry-overlays.json` has zero rows with `parent_kind: "state"` or `STATEWIDE` substring — S05.5's "do not pre-emit statewide rows" mirrors MT exactly and matches S03.6.1's bear-binding derive-at-query-time pattern.

---

### 3. Risks — **Ready (one SHOULD-FIX)**

**SHOULD-FIX (R-1) — S05.4 → S05.5 allowlist handoff timing.** L339 says S05.4 "seeds `EXPECTED_CO_RA_ORPHAN_IDS`"; L402, 427 say S05.5 consumes it. The risk is the case where S05.4 outcome (b) fires (CPW publishes no restricted-area layer + no no-hunt zones to load → zero rows). The epic at L332 + L414 already handles this case ("overlay-fixture invariants tolerate the zero-row case per S02.6's CWD precedent"), but the `EXPECTED_CO_RA_ORPHAN_IDS` constant itself needs an explicit "default: empty frozenset" disposition. Otherwise S05.5's "fail-loud on RA orphan NOT on allowlist" semantics could trip when S05.5 starts before S05.4 finalizes the allowlist value.

**Fix:** Add to S05.5 AC L427: "`EXPECTED_CO_RA_ORPHAN_IDS` defaults to `frozenset()` if S05.4 outcome (b) fires; non-empty only when S05.4 outcome (c) lands no-hunt zones."

**NICE-TO-HAVE (R-2) — Multi-part GMU absence case for S05.7.** L520 says S05.7's named-multi-part-anchor verification reads `multipart-gmus.json` and uses "the first entry." If `multipart-gmus.json` is empty (CO unexpectedly has zero multi-part GMUs), S05.7's verification cannot execute. The research doc mentions noncontiguous fragments "without naming specific GMUs" so the expectation is ≥1, but a defensive contract is worth adding: "If `multipart-gmus.json` is empty, document the verification as N/A in the closure note and surface as a data observation; do NOT silently skip." This protects the AC from being silently passed.

**Confirmed-accurate (R-3 / S05.4 research-doc prerequisite tracking):** Epic L324, L328, L600, L632 all flag the research-doc prerequisite explicitly. Status as "NOT yet drafted" is surfaced at the references section (L632) — adequately tracked as a blocker.

---

### 4. Overengineering — **Ready**

**On `ROLE_FOR_BINDING_BY_CHILD_KIND` rename:** Not premature. The rename is a one-line addition + alias retention; cost is ~5 LOC. The semantic value is real (the name `_E03_` will look weird when E07 / E08 reference it; better to do this now while MT is the only caller). Verdict: keep.

**On S05.0's three-tier source priority (CPW → state library → TIGER fallback):** Compare to S03.0's actual implementation, which chose `mt-msdi-framework-boundaries-9-2026` as a third option strictly dominating ADR-018's two listed options. The S03.0 implementer's actual flexibility is exactly what S05.0's three-tier framing encodes — prescriptive enough to give the implementer a starting point and permissive enough to allow a "fourth option strictly dominates" outcome like S03.0 did. Verdict: not overengineered; pattern-faithful.

**On Spatial Correctness × ArcGIS Fidelity conflict resolution (L48-54):** Verdict checks out. `_coordinates_in_wgs84_range` at `arcgis.py:397-408` is verifiably global (`|x|<=180, |y|<=90`); the Spatial Correctness reviewer's "must include CO-bounds check at fetch layer" was based on a wrong premise about lib semantics. The PM's resolution (delegate to lib at fetch layer; add CO-bounds `ST_Envelope` at S05.7 analytical layer) is correct.

---

### 5. Acceptance criteria quality — **Ready**

**Confirmed-accurate (AC-1) — S05.2 ±10% band justification.** Epic L222: "row count in `[167, 205]`" justified as "±10% band for CPW data drift since 2026-04-09". Research-doc cites 186 polygons; ~7-week drift window. Band is defensible. Could be tightened to ±5% if implementer wants conservative discovery; the wide band protects against silent under-fetch failures the way OQ7 bands have historically protected MT loaders.

**SHOULD-FIX (AC-2) — S05.5 threshold edge-tests are byte-identical to S02.6.** L430: tests pin `0.989 → "intersects"`, `0.990 → "covers"`, `0.011 → "intersects"`, `0.009 → dropped`. The four numeric values are the MT threshold boundaries; their *semantic* meaning (band-edge correctness) transfers fully to CO. The validation-triad SHOULD-FIX recalibration discipline at L400 already covers the recalibration case. Verdict: not cargo-culted — locking the band-edge behavior is the right invariant; if CO's empirical band shifts the thresholds, the four values shift symmetrically and the test still locks the behavior under whatever thresholds finally ship.

**Recommendation:** Add a one-line comment in the AC: "if thresholds recalibrate per L400, the four edge values shift symmetrically; the test pattern is the lock, not the literal numbers."

**Confirmed-accurate (AC-3) — S05.7 PRD-002 success-criteria mapping (L562-565):** SC#4 (PostGIS `ST_Covers` with explicit `state='US-CO'` filter) maps to S05.7 AC L554; SC#6 (zero invalid topology) maps to AC L555; SC#7 (idempotent ingestion) maps to S05.7 AC L559 ("re-run produces zero net new rows"). All three concretely satisfiable.

---

### 6. Dependencies — **Ready**

**Confirmed-accurate (D-1) — S05.0 → S05.1 ordering.** S05.1's `README.md` AC (L159) references the `_STATE = 'US-CO'` convention; `sources.yaml` mentions the statewide source via the scaffold. Real dependency.

**Confirmed-accurate (D-2) — S05.3 + S05.4 → S05.5 handoff via fixtures.** S05.5 reads geometry from DB (not from S05.3/S05.4 fixtures directly), so the cross-story coupling is via DB state, not file handoff. Coverage invariant at L407-408 tolerates the zero-rows-from-S05.3 case and zero-rows-from-S05.4 case (per S02.6 precedent). Real but minimal dependency.

**Confirmed-accurate (D-3) — S05.6 → S05.7 regression-test reuse.** S05.7 AC L560 re-runs S05.6's regression test as a UAT step. Not redundant — S05.6 lands the test; S05.7 verifies it survives the full geometry-loaded state. Mirrors S03.10's `TestQueryNearbyHdsForZone::test_sql_excludes_portions_regression_guard` pattern.

---

## Cross-cutting observations

**Observation 1 — Line-citation drift is the most likely failure mode for E05 implementation.** Two line-number citations are already wrong in the freshly-drafted epic (S05.6's `:111` and S05.5's `overlays.py` snippet). This is exactly the failure mode the Bundle A Entry 1 + Bundle A Entry 2 pitfalls warn about. The epic acknowledges this (L460: "verify exact line numbers at story implementation time per pitfall #1"). The implementer should grep-verify every `:XXX` citation at story-open time. Consider a Stage-0 pre-implementation grep audit as standard practice for all E05 stories.

**Observation 2 — E05's "convention-maturing" arc continues E04's discipline.** E04 closed with `.roughly/known-pitfalls.md` § "Documentation & planning discipline" growing from 6 → 11 entries. Two new conventions worth flagging at E05 closure: (a) explicit `extensions.`-prefix in operator runbooks (the E02 runbook bug is now correctable); (b) state-agnostic-clean library extensions land with deprecated-alias preservation when renaming. Worth recording in the post-implementation audit.

---

## Specific suggestions (PM-applicable edits)

1. **S05.6 L452, L460**: `load_jurisdiction_bindings.py:111` → `load_jurisdiction_bindings.py:110`. Also clarify the dual `:587/740` citation — only `:587` is the nearby-zone query; `:740` is a different function (`_load_non_statewide_reg_records`).

2. **S05.5 L361-363**: Correct the "current state" `OverlayChildKind` snippet to show 4 values (include `"hunting_district"`); proposed extension at L368 becomes 5 values. Existing `ROLE_FOR_E03_BY_CHILD_KIND` already has the `"hunting_district" → "primary_unit"` mapping that S05.5's `"gmu" → "primary_unit"` mirrors.

3. **S05.5 AC L427**: Add explicit default for `EXPECTED_CO_RA_ORPHAN_IDS`: "`frozenset()` if S05.4 outcome (b) fires; non-empty only when S05.4 outcome (c) lands no-hunt zones."

4. **S05.5 L367-369**: Note that `OverlayParentKind`'s docstring (overlays.py:59-65) "extend this Literal when additional parent kinds are introduced" guidance is being followed; the docstring also updates.

5. **S05.5 AC L430**: Add a one-line comment clarifying the edge-test pattern transfers; literal values shift with any threshold recalibration per L400.

6. **S05.7 AC L556**: Add a defensive-skip provision for the empty-`multipart-gmus.json` case (document as N/A; do not silently skip).

---

## Summary

The epic is unusually thorough — the validation triad's 14 MUST-FIX + 9 SHOULD-FIX cycle delivered a planning artifact with most surfaces correctly hardened. The residual issues are minor: one off-by-one line citation (consequence of the pitfall the epic itself warns about), one minor "before-state" snippet error on `OverlayChildKind`, and a handful of defensive-default clarifications. No story-level rework needed; no ADR triggers missed. **E05 is Ready to enter implementation** with the six small edits above applied first.

---

*HuntReady · E05 epic review · 2026-05-31 · Roughly epic-reviewer (opus)*
