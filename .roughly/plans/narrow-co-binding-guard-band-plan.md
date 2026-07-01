> **Status:** Historical — implemented and merged in commit 3aa5888f4a2349988a68893487330af886c685e3 on 2026-07-01. This plan was an active build/fix artifact; treat as historical reference only.

# Implementation Plan: Narrow _BINDING_COUNT_GUARD_BAND to operator-empirical (327, 607)

Plan-format-version: 1

Closes Known Issue #19 (E06 Group B dev live-write operator pass, 2026-07-01, PR #89 / c53a81d).
Empirical count = 467 jurisdiction_binding rows. ±30% → (327, 607). Mirrors S04.2 T16
narrowing precedent for MT.

## File Table
| File | Action | Task(s) |
|------|--------|---------|
| ingestion/states/colorado/load_jurisdiction_bindings.py | Modify | T1 |
| ingestion/tests/test_load_co_jurisdiction_bindings.py | Modify | T2 |

## Tasks

### T1: Flip constant + de-provisionalize prose (~3 min)
**Files:** ingestion/states/colorado/load_jurisdiction_bindings.py
**Action:** Change `_BINDING_COUNT_GUARD_BAND` from `(300, 1200)` to `(327, 607)`; update the
two surrounding comment lines (160-161) and the `_assert_binding_count_within_guard` docstring
(825-827) + error-message parenthetical (835) so they no longer describe the band as
"provisional / narrow after first dry-run" — it is now narrowed to the operator-empirical count.
**Details:**
- Lines 33-39 (module docstring "OQ7 row-count guard" section): replace the `Band: (300, 1200)
  — PROVISIONAL pending the operator's first dry-run empirical count …` prose with the
  narrowed-to-467 statement (band now `(327, 607)`, ±30% around the S06.10 Group B dev
  operator-empirical count 467, 2026-07-01, PR #89 / c53a81d). This is the FIFTH edit site,
  added after plan review flagged it.
- Line 162: `_BINDING_COUNT_GUARD_BAND: Final[tuple[int, int]] = (327, 607)`
- Lines 160-161 comment: replace the "PROVISIONAL … Narrow to ±30% around the first dry-run
  empirical count per S04.2 T16 analog." text with a note that the band is now narrowed to
  ±30% around the S06.10 Group B dev operator-empirical count 467 (2026-07-01, PR #89 /
  c53a81d).
- Docstring lines 825-827: replace "PROVISIONAL `(300, 1200)` pending the operator's first
  dry-run empirical count. Narrow to ±30% …" with the narrowed-to-467 statement.
- Error-message line 835: drop the "(provisional — narrow after first dry-run)" parenthetical
  (band is now settled); keep the band interpolation `[{lo}, {hi}]`.
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_jurisdiction_bindings.py && .venv/bin/mypy ingestion/lib/ states/colorado/load_jurisdiction_bindings.py`
**UI:** no

### T2: Add regression-lock test class + update the stale provisional test (~4 min)
**Files:** ingestion/tests/test_load_co_jurisdiction_bindings.py
**Depends on:** T1
**Action:** (a) Add new class `TestBindingCountBandLockedToOperatorEmpirical` with method
`test_band_locked_to_group_b_empirical` pinning `_BINDING_COUNT_GUARD_BAND == (327, 607)`
(verbatim per the build spec, with the S04.2-mirror docstring). (b) Update the existing
`TestCountGuard::test_band_is_provisional_300_1200` (line 1164): change its assertion to
`(327, 607)` and rename to `test_band_is_narrowed_to_operator_empirical` + refresh its docstring
so the "provisional" name is no longer false. Boundary tests (1138-1156) and `test_zero_raises`
derive from the tuple — leave them unchanged.
**Details:**
- New class placed adjacent to `TestCountGuard` (after line 1166, before the section separator
  at 1169). Uses the exact class + method + docstring text from the build spec.
- Import of `_BINDING_COUNT_GUARD_BAND` already exists at module top (line 45); the spec's
  in-method `from ingestion.states.colorado.load_jurisdiction_bindings import …` is redundant
  but harmless — keep the spec's local import as written for self-documentation, OR reference
  the module-level import. Prefer referencing the existing module-level symbol to avoid a
  redundant-import lint/smell; assert against it directly.
- Net test delta = +1 (one method added; one method modified-in-place).
**Verify:** `cd ingestion && .venv/bin/ruff check tests/test_load_co_jurisdiction_bindings.py && .venv/bin/pytest tests/test_load_co_jurisdiction_bindings.py -q --tb=short`
**UI:** no

## Blast Radius
- Do NOT modify: any `ingestion/lib/` file, any `ingestion/states/montana/` file, any
  `supabase/migrations/` file, `ingestion/lib/db.py`, any `mcp-server/` or `web/` file.
- Do NOT touch the geometry-overlays.json fixture or any extracted artifact.
- Watch for: the redundant local import in the spec's test snippet (avoid F811/redefinition or
  a lint smell); the 5 arithmetic boundary tests must remain derived from the tuple (do not
  hardcode 327/607 into them).

## Conventions
- Mirrors S04.2's `TestCountGuard::test_band_locked_to_t16_empirical` circularity-gap-closure
  pattern (pin the tuple's literal value so accidental widening can't pass the derived
  boundary tests silently).
- ADR-001 fail-loud guard unchanged in behavior (only the band edges move).
- Single commit; standard Co-Authored-By trailer.
