> **Status:** Historical — implemented and merged in commit 569941c87fafecc42713f7b66ae63560a8f36020 on 2026-06-23. This plan was an active build/fix artifact; treat as historical reference only.

# Implementation Plan: S06.7 — CO `season_definition` + `license_tag` + `license_season` ingestion

Plan-format-version: 1

## Summary

New Colorado multi-link adapter `ingestion/states/colorado/load_seasons_and_licenses.py` (structural analog of MT `ingestion/states/montana/load_seasons_and_licenses.py`, ~1180 LOC). Reads the two committed extraction artifacts (`extracted/big-game-2026.json` + `extracted/black-bear-2026.json`) and writes five tables in one atomic transaction: `season_definition`, `license_tag`, `license_season`, `regulation_season`, `regulation_license`. Plus a new test file `ingestion/tests/test_load_co_seasons_and_licenses.py` (80+ tests).

**Pre-code decisions already resolved (do NOT re-litigate):**
- **Q20 Season Choice (`method_letter="X"`) → PER-WINDOW FAN-OUT** (human decision 2026-06-23). Each `X` row carries up to 3 `season_windows` (archery/muzzleloader/rifle). Emit ONE `season_definition` per window (weapon_type from that window's method), ONE `license_tag` with `weapon_types=["archery","muzzleloader","any_legal_weapon"]`, and `license_season` links the tag to all of its seasons. `X` rows with `season_windows=[]` (some F-sex rows) → still emit the `license_tag`, emit NO seasons for it, **skip-with-WARNING** (not fail-loud).
- **Q16 species fan-out → DOES NOT FIRE.** CO artifact pre-separates `mule_deer`/`whitetail`/`elk`/`pronghorn`. There is NO `deer` label and NO `_CO_SPECIES_FANOUT` dict. Link builders do NOT fan out.
- **Q17 cross-listing conflicts → DOES NOT FIRE** at this layer.
- **closure-temporal `effective_after` → DOES NOT FIRE.** No bear closures in CO V1; `ClosurePredicate` not used in S06.7.
- **Asymmetric-coverage demonstrator → GMU 001 mule_deer** (archery `D-M-001-O1-A` Sep 2–30 / muzzleloader `D-M-001-O1-M` Sep 12–20 / rifle `D-M-001-O2-R` Oct 24–Nov 1 — all collapse to one regulation_record `CO-GMU-1 / mule_deer / 2026` but produce 3 distinct seasons + 3 tags). Lock in `test_license_season_asymmetric_coverage_m2_criterion`.

**Key structural differences from MT (READ THESE — they change the code shape):**
1. CO row `season_windows` is a **LIST** of `{start_date, end_date, raw_text}` dicts — NOT MT's dict keyed by season_key. There is no embedded `season_key`; the "season key" must be derived from the row's `method_group`/`method_letter`. Window parsing reads `start_date`/`end_date` string fragments (e.g. `"Sept. 2"`, `"Sept. 30"`) with abbreviated dotted months and NO year.
2. ~36 rows have `start_date=None`/`end_date=None` (extractor garbage, e.g. `raw_text="New"`). Skip-with-WARNING; do not emit a season for them.
3. `apply_by` is `null` on EVERY CO row (big-game + bear). MT's OTC-via-`apply_by` discriminator does NOT apply. Big-game `kind` derives from `list_value`/`season_code`; bear `kind` maps from the section-level `license_kind` field.
4. CO regulation_record collapses all method_groups under one `(gmu_code, species_group)` per S06.6. Links must key to `jurisdiction_code = f"CO-GMU-{int(gmu_code)}"`.

## Conventions
- ADR-005 / ADR-022 state-adapter isolation: NO edits to `ingestion/ingestion/lib/` (all 5 db helpers + drift_guard already exist). State-agnostic-clean — locked by `TestNoStateAdapterImports` AST guard. Within-state imports from `states.colorado.load_regulation_records` ARE allowed (same adapter dir).
- ADR-020 drift_guard: `assert_id_matches` MUST be called at every per-row construction site in the `season_definition` + `license_tag` build functions; link-table builders must NOT import/call drift_guard.
- ADR-008 verbatim discipline: `verbatim_rule` non-empty; fallback chain row-text → section `verbatim_text`.
- Three-phase shape: build → 5 row-count guards (pre-`db.connect()`) → atomic write + single `conn.commit()`.
- `license_tag.draw_spec_key = None` on every row (S06.8 backfills per ADR-012).
- `_STATE: Final[str] = "US-CO"`; `_LICENSE_YEAR = 2026`.
- Mirror MT precedent exactly where shapes match: `ingestion/states/montana/load_seasons_and_licenses.py` is the reference. Read it.
- `# type: ignore[arg-type]` on the heuristic-derived `kind=` kwarg is an accepted documented pattern (mirrors MT `:1087`).

## Blast Radius
- Do NOT modify: anything under `ingestion/ingestion/lib/`, any `montana/` file, any `supabase/migrations/`, any TS (`mcp-server/`, `web/`), `docs/architecture.md`, `schema.py`.
- Do NOT touch the extraction artifacts (`extracted/*.json`) — read-only input.
- Watch for: Pydantic `extra="forbid"` + frozen on `SourceCitation`; non-empty validators on `verbatim_rule`; `WeaponType` Literal does NOT include `"season_choice"` (that's a `method_group`, not a weapon type).

## File Table
| File | Action | Task(s) |
|------|--------|---------|
| ingestion/states/colorado/load_seasons_and_licenses.py | Create | T1, T2, T3, T4, T5, T6, T7, T8, T9 |
| ingestion/tests/test_load_co_seasons_and_licenses.py | Create | T10, T11 |

## Tasks

### T1: Module skeleton — imports, constants, citation, artifact loader (~5 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Action:** Create the module with its header docstring, imports, module-level constants, the `SourceCitation` builder, and the artifact-reading functions.
**Details:**
- Read `ingestion/states/montana/load_seasons_and_licenses.py` (top ~120 lines) and `ingestion/states/colorado/load_regulation_records.py` (top ~130 lines) for the established CO conventions.
- Module docstring: describe the three-phase shape, the five tables written, the Q20 per-window-fan-out decision, and list the test classes (forward-reference).
- Imports: `argparse`, `datetime`, `json`, `logging`, `pathlib.Path`, `typing` (Final, Any, cast, etc.); from `ingestion.lib import db`; **`from ingestion.lib.drift_guard import assert_id_matches` (DIRECT bare-name import — mirrors MT `load_seasons_and_licenses.py:51`; do NOT do `from ingestion.lib import drift_guard`. The T10 AST guard matches `ast.Name` nodes, so call sites MUST read `assert_id_matches(...)`, not `drift_guard.assert_id_matches(...)`).** From `ingestion.lib.schema` import `SeasonDefinition`, `LicenseTag`, `LicenseSeason`, `RegulationSeason`, `RegulationLicense`, `SourceCitation`, `WeaponType`, `Residency`. Reuse `from states.colorado.load_regulation_records import _co_gmu_jurisdiction_code` — this symbol EXISTS at `load_regulation_records.py:267` returning `f"CO-GMU-{int(gmu_code)}"`; import it (do not redeclare). Also `from states.colorado.load_regulation_records import _STATE` (defined at `:75`).
- Constants: `_LICENSE_YEAR: Final[int] = 2026`; artifact paths `_BIG_GAME_ARTIFACT` / `_BEAR_ARTIFACT` resolved relative to `__file__` (`Path(__file__).parent / "extracted" / "big-game-2026.json"` etc.); `_LOGGER = logging.getLogger(__name__)`; **`_PURCHASE_URL: Final[str] = "https://www.cpw.state.co.us/buyapply"`** — the CPW evergreen analog of MT's `_PURCHASE_URL`; confirm/adjust against `states/colorado/sources.yaml` (use the CPW apply URL it records if present).
- Citation builder: build the shared `SourceCitation` for big-game (`id="co-cpw-big-game-2026-brochure"`, `document_type="annual_regulations"`, fields copied from how `load_regulation_records.py` builds its CO citation) and bear citation. Reuse `load_regulation_records.py`'s citation construction approach exactly; if it exposes a reusable builder, import it.
- Artifact loaders: `_load_big_game_sections() -> list[dict[str, Any]]` and `_load_bear_records() -> list[dict[str, Any]]`. **Both artifacts are standard JSON ARRAYS (first char `[`) — read via `json.load(f)` + an `isinstance(data, list)` fail-loud check, mirroring `load_regulation_records.py:787-794`. Do NOT write a line-by-line reader.**
- Leave `# TODO(Tn)` placeholders for functions added in later tasks so the file imports cleanly. Module must import without error at end of task.
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/python -c "import sys; sys.path.insert(0,'.'); import states.colorado.load_seasons_and_licenses"`
**UI:** no

### T2: Pure id-derivation functions + season-name rendering (~4 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Depends on:** T1
**Action:** Add the two module-level pure id-derivation functions and a season-name renderer.
**Details:**
- `_co_season_definition_id(species_group: str, gmu_code: str, hunt_code: str, season_code: str, window_index: int) -> str` — the single source of truth for season_definition ids. Because CO collapses method_groups under one (gmu,species) and 265 hunt_codes repeat across sections, the id MUST be precise per hunt_code + window. Recommended format: `f"CO-GMU-{int(gmu_code)}-{species_group}-{hunt_code}-w{window_index}-{_LICENSE_YEAR}"`. (Mirror MT's `_season_definition_id` at `:370` for style; adapt the field set to CO's.) Document why `hunt_code`+`window_index` rather than MT's `season_key`.
- `_co_license_tag_id(species_group: str, gmu_code: str, hunt_code: str) -> str` — recommended `f"CO-GMU-{int(gmu_code)}-{species_group}-{hunt_code}-{_LICENSE_YEAR}"`. (Mirror MT `_license_tag_id` at `:387`.)
- Bear analogs IF bear ids need a distinct shape (bear has `gmu_code` too — likely the same functions work with `species_group="bear"`; prefer reusing the two functions above over bear-specific ones unless bear's id collides). Inspect the bear artifact's `gmu_code`/`hunt_code` shape; if reusable, do not add bear-specific id functions.
- `_co_season_name(species_group: str, method_group: str, season_code: str) -> str` — human-readable name (analog of MT `_SEASON_NAME_BY_KEY`), e.g. `"Mule Deer Archery (O1)"`. Keep deterministic and pure.
- All three functions are pure (no I/O, no globals beyond `_STATE`/`_LICENSE_YEAR`).
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -5`
**UI:** no

### T3: CO window parser (~5 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Depends on:** T1
**Action:** Add a parser converting a CO `season_windows` list entry into `(opens, closes)` `datetime.date`s.
**Details:**
- `_parse_co_window(window: dict[str, Any], license_year: int) -> tuple[datetime.date, datetime.date] | None`. Input is one entry of the row's `season_windows` list: `{start_date, end_date, raw_text}`.
- If `start_date` is None OR `end_date` is None → return `None` (caller skips-with-WARNING). This handles the ~36 garbage rows.
- Parse the abbreviated dotted-month fragments (`"Sept. 2"`, `"Oct. 24"`, `"Nov. 08"`). Reuse MT's date-fragment normalization if exposed (look at MT `_parse_window` around the window-parsing helpers); otherwise normalize: strip trailing `.`, map `"Sept"`→`"Sep"`, strptime with `"%b %d"` then attach `license_year`. Handle year-wrap (closes month < opens month → closes is next year) the same way MT does.
- Fail-loud (raise `ValueError` with the raw_text in the message) on a non-null but unparseable fragment — a present-but-malformed date is a real defect, distinct from the null-garbage case.
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -5`
**UI:** no

### T4: kind heuristic + verbatim_rule fallback + weapon-type helpers (~5 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Depends on:** T1
**Action:** Add the license-tag `kind` heuristic, the `verbatim_rule` fallback chain, and weapon-type derivation.
**Details:**
- `_co_big_game_license_kind(list_value: str | None, season_code: str | None) -> Literal["general","limited_draw","over_the_counter","statewide"]` — ordered-branch heuristic with a fail-loud `else`. CO big-game: `list_value="A"` → `"limited_draw"` (primary draw); `list_value="B"` → `"over_the_counter"`; `list_value="C"` (season_choice) → `"limited_draw"` (it is a draw license). Document each branch with the CPW meaning; raise on an unrecognized `list_value`. (Note: `apply_by` is null in CO — do NOT inspect it.)
- `_co_bear_license_kind(license_kind: str) -> Literal[...]` — maps the bear section-level `license_kind` to the schema enum: `"limited_draw"`→`"limited_draw"`; `"over_the_counter"`/`"add_on_otc"`/`"plains_otc"`/`"private_land_otc"` → `"over_the_counter"`. Fail-loud `else`.
- `_select_co_verbatim_rule(row: dict, section: dict) -> str` — fallback chain: row `extras` (if non-empty) → section `verbatim_text` → raise if both empty (Pydantic requires non-empty). Mirror MT's `_select_season_verbatim_rule`.
- `_co_residency(scope: str) -> Residency` — read from `row["residency_scope"]` (fall back to `section["residency_scope"]`). The `Residency` Literal is `{"resident","nonresident","both"}`; CO V1 data carries only `"both"` (2672 rows) and `"nonresident"` (90 rows) for big-game, `"both"` for bear. Implement as `cast(Residency, scope)` guarded by a fail-loud `else` raising on any value not in the Literal. (`"resident"` does not appear in CO V1 but is a valid passthrough.) NOTE the artifact field is `residency_scope`, NOT `residency` — do not copy MT's `section.residency` field name.
- `_co_window_weapon_type(row: dict, window_index: int) -> WeaponType` — return type is always a `WeaponType` (never None; the value is always derivable). All non-X rows have exactly ONE entry in `weapon_types`; X (season_choice) rows have `weapon_types=["archery","muzzleloader","any_legal_weapon"]` whose order matches the season_windows order (verified across all 10 X rows). Implementation: `wt = row["weapon_types"][window_index] if window_index < len(row["weapon_types"]) else row["weapon_types"][0]` — but the precise contract is: non-X → `row["weapon_types"][0]`; X → `row["weapon_types"][window_index]`. Validate the result is a member of the `WeaponType` Literal; raise otherwise. Document that `window_index` aligns 1:1 with the X row's weapon_types positions.
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -5`
**UI:** no

### T5: Big-game season_definition + license_tag builders (with drift_guard) (~5 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Depends on:** T2, T3, T4
**Action:** Add `_build_big_game_season_definitions` and `_build_big_game_license_tags`.
**Details:**
- `_build_big_game_season_definitions(sections, citation) -> list[SeasonDefinition]`: iterate sections → rows → `for window_index, window in enumerate(row["season_windows"])`. For each parseable window (`_parse_co_window` not None) build a `SeasonDefinition(id=_co_season_definition_id(...), name=_co_season_name(...), opens, closes, weapon_type=_co_window_weapon_type(row, window_index), residency=_co_residency(...), verbatim_rule=_select_co_verbatim_rule(row, section), source=citation, page_reference=...)`. **Immediately after construction call `assert_id_matches(sd.id, _co_season_definition_id(species_group, gmu_code, hunt_code, season_code, window_index), helper_name="_build_big_game_season_definitions", context={...})`** (bare name, NOT `drift_guard.assert_id_matches`) before appending. First-occurrence-wins dedup on `sd.id` (a dict keyed by id). Windows that parse to None → `_LOGGER.warning(...)` naming gmu/hunt_code/raw_text, skip. This naturally implements Q20 per-window fan-out (X rows have 3 windows → 3 seasons).
- `_build_big_game_license_tags(sections, citation) -> list[LicenseTag]`: one `LicenseTag` per unique `_co_license_tag_id` (dedup by id). `kind=_co_big_game_license_kind(...)` (`# type: ignore[arg-type]` if mypy can't narrow), `species=species_group`, `weapon_types=` the row's `weapon_types` mapped to the Literal (for X rows this is the multi-weapon list), `residency=_co_residency(...)`, `purchase_url=_PURCHASE_URL`, `verbatim_rule=_select_co_verbatim_rule(...)`, `quota`/`quota_range` per row (big-game uses `quota`/`quota_range` fields; map per schema — `quota_range` string → `tuple[int,int]` or None), `draw_spec_key=None`, `source=citation`. **Call `assert_id_matches(lt.id, _co_license_tag_id(...), helper_name="_build_big_game_license_tags", context={...})` (bare name) immediately after construction.**
- Mirror MT `_build_dea_season_definitions` (`:830`/`:926`) and `_build_dea_license_tags` (`:996`/`:1100`) for structure and the exact `assert_id_matches` call shape.
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -5`
**UI:** no

### T6: Bear season_definition + license_tag builders (with drift_guard) (~4 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Depends on:** T2, T3, T4
**Action:** Add `_build_bear_season_definitions` and `_build_bear_license_tags`.
**Details:**
- Read the bear artifact shape: only `record_type == "section"` records carry rows; skip `statewide_rule` / `reporting_obligation` records. `species_group` is `"black_bear"` in the artifact but the DB species value must be `"bear"` (match S06.6's convention — confirm in `load_regulation_records.py`).
- `_build_bear_season_definitions(records, citation) -> list[SeasonDefinition]`: same per-window pattern as T5 but `species_group="bear"`, `kind` not relevant here (season defs have no kind), `residency=_co_residency(...)`. Wire `assert_id_matches` (bare name) with `helper_name="_build_bear_season_definitions"`.
- `_build_bear_license_tags(records, citation) -> list[LicenseTag]`: `kind=_co_bear_license_kind(record["license_kind"])`, `residency=_co_residency(...)`, `purchase_url=_PURCHASE_URL`, `quota_range` per CPW bear convention (bear → NULL quota_range per the spec's decision #11 unless the artifact carries an int range — inspect and follow the data), `species="bear"`. Wire `assert_id_matches` (bare name) with `helper_name="_build_bear_license_tags"`.
- If bear `gmu_code`/`hunt_code` make the T2 id functions reusable, reuse them; otherwise add `_co_bear_*_id` functions and wire their own assert_id_matches re-derivation.
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -5`
**UI:** no

### T7: Three link-table builders (NOT instrumented) (~5 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Depends on:** T5, T6
**Action:** Add `_build_license_season_links`, `_build_regulation_season_links`, `_build_regulation_license_links`. These MUST NOT import or call `drift_guard`.
**Details:**
- `_build_license_season_links(sections, bear_records) -> list[LicenseSeason]`: for each row, link its `license_tag_id` (`_co_license_tag_id(...)`) to each of its `season_definition_id`s (`_co_season_definition_id(...)` for each parseable window). Dedup on `(license_tag_id, season_definition_id)`. This is where the asymmetric-coverage demonstrator manifests (GMU 001 mule_deer tag→3 seasons across the 3 method rows). For X license tags whose windows all parsed to None → no links (the skip-with-warning case).
- `_build_regulation_season_links(sections, bear_records) -> list[RegulationSeason]`: one row per `(jurisdiction_code, species_group, season_definition_id)` where `jurisdiction_code=_co_gmu_jurisdiction_code(gmu_code)`, `state=_STATE`, `license_year=_LICENSE_YEAR`. NO species fan-out (Q16 N/A). Dedup.
- `_build_regulation_license_links(sections, bear_records) -> list[RegulationLicense]`: one row per `(jurisdiction_code, species_group, license_tag_id)`. NO fan-out. Dedup.
- Mirror MT `_build_dea_license_season_links` (`:1120`), `_build_dea_regulation_season_links` (`:1164`), `_build_dea_regulation_license_links` (`:1215`) for structure — but REMOVE the `_DEA_SPECIES_FANOUT` deer→{mule_deer,whitetail} logic (CO is pre-separated).
- Confirm `drift_guard` is NOT referenced anywhere in these three functions.
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -5`
**UI:** no

### T8: Count guards + `main()` three-phase (~5 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Depends on:** T5, T6, T7
**Action:** Add the 5 row-count guard bands, the guard-check function, and `main()`.
**Details:**
- Run the builders once in a throwaway `.venv/bin/python` dry-run (or read counts from the artifacts) to get the empirical counts for each of the 5 tables. Set each band to ±30% around the empirical count as named `Final` constants (`_SEASON_DEFINITION_BAND`, etc.). Document the empirical counts in a comment.
- `_check_count_band(name: str, count: int, band: tuple[int, int]) -> None` — raise `RuntimeError` (fail-loud) if out of band. Mirror MT.
- `main(argv: list[str] | None = None) -> int`: argparse with `--dry-run`; function-level logger + `logging.basicConfig`; NO `--service-url` flag (S05.0 silent-lie precedent). Phase 1: load artifacts, build all 5 lists. Phase 2: run all 5 count guards (BEFORE `db.connect()`). Phase 3: if `--dry-run`, log a summary table (counts per table) and return 0; else `with db.connect() as conn:` write season_definitions → license_tags → license_seasons → regulation_seasons → regulation_licenses (entity tables before link tables for FK order), single `conn.commit()`. Log a final summary of all 5 counts.
- `if __name__ == "__main__": raise SystemExit(main())`.
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -5 && .venv/bin/python states/colorado/load_seasons_and_licenses.py --dry-run 2>&1 | tail -20`
**UI:** no

### T9: Self-review pass — drift_guard coverage + ADR-008 + isolation (~3 min)
**Files:** ingestion/states/colorado/load_seasons_and_licenses.py
**Depends on:** T8
**Action:** Verify (and fix) cross-cutting invariants in the finished module.
**Details:**
- Confirm EVERY `SeasonDefinition(...)` and `LicenseTag(...)` construction site is immediately followed by an `assert_id_matches` call re-deriving from the pure id function. Add any missing.
- Confirm the three link builders do NOT reference `drift_guard`.
- Confirm no imports from `ingestion.lib` other than `db`, the bare-name `assert_id_matches` from `drift_guard`, and `schema` symbols (state-agnostic-clean).
- Confirm `--dry-run` runs and all 5 guards pass with the real artifacts. **Inspect the `--dry-run` log for WARNING messages; confirm any dedup/skip warnings match the KNOWN near-identical extractor pairs (GMU 025 elk `E-F-025-P5-R` and GMU 085 elk `E-F-085-P5-R`, plus the ~3 X female-whitetail 0-window rows) rather than signaling a logic error. Record the expected warnings in a comment.**
**Verify:** `cd ingestion && .venv/bin/ruff check states/colorado/load_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -5 && .venv/bin/python states/colorado/load_seasons_and_licenses.py --dry-run 2>&1 | tail -8`
**UI:** no

### T10: Test file part 1 — pure functions + AST guards (~5 min)
**Files:** ingestion/tests/test_load_co_seasons_and_licenses.py
**Depends on:** T9
**Action:** Create the test file with the pure-function and AST-guard test classes.
**Details:**
- Import pattern: `from states.colorado import load_seasons_and_licenses as mod` (mirror `test_load_co_regulation_records.py:22`).
- `TestSeasonDefinitionId` / `TestLicenseTagId` — lock the id format strings (assert exact output for a known input).
- `TestParseCoWindow` — parseable dotted-month fragments; year-wrap; `None` start/end → returns None; non-null malformed → raises ValueError.
- `TestLicenseKindHeuristic` — big-game A/B/C branches + bear `license_kind` mapping + fail-loud else.
- `TestVerbatimRuleFallback` — row extras → section verbatim → raise-on-both-empty.
- `TestDriftGuardCallSites` — AST walk of `load_seasons_and_licenses.py`: enumerate every function whose name matches `_build_*_season_definitions` or `_build_*_license_tags`; assert each body contains a call to `assert_id_matches`. **Because the module imports `assert_id_matches` by bare name, the call node is an `ast.Call` whose `func` is an `ast.Name` with `id == "assert_id_matches"` — match on that (mirror MT's `TestDriftGuardCallSites`, which uses the same `ast.Name` match).** A new build function without the call must fail this test.
- `TestLinkTableNotInstrumented` — AST assert that `_build_license_season_links` / `_build_regulation_season_links` / `_build_regulation_license_links` contain NO `assert_id_matches` call (no `ast.Name` with `id == "assert_id_matches"`) and no `drift_guard` reference.
- `TestNoStateAdapterImports` — AST guard mirroring `TestNoColoradoLeakIntoSharedLib` / MT `TestNoLibImports`: no imports of OTHER state adapters (within-state import of `states.colorado.load_regulation_records` IS allowed); lib imports limited to `db` + `assert_id_matches` + `schema` symbols.
**Verify:** `cd ingestion && .venv/bin/ruff check tests/test_load_co_seasons_and_licenses.py && .venv/bin/pytest tests/test_load_co_seasons_and_licenses.py -q 2>&1 | tail -15`
**UI:** no

### T11: Test file part 2 — builders, links, asymmetric criterion, guards, main (~5 min)
**Files:** ingestion/tests/test_load_co_seasons_and_licenses.py
**Depends on:** T10
**Action:** Add the builder/link/integration test classes.
**Details:**
- `TestBuildBigGameSeasonDefinitions` — with a small in-test section fixture: correct SD count per windows; weapon_type per window; Q20 X-row → 3 seasons; null-window skip-with-warning (assert via `caplog`); dedup.
- `TestBuildBigGameLicenseTags` — kind derivation; weapon_types; draw_spec_key is None; quota mapping.
- `TestBuildBearBuilders` — `species="bear"` (not "black_bear"); bear kind mapping; statewide_rule/reporting_obligation records skipped.
- `TestBuildLinks` — license_season / regulation_season / regulation_license counts; no species fan-out (a deer-equivalent section yields ONE regulation_season per season, not two); correct `jurisdiction_code = CO-GMU-{int}`.
- `test_license_season_asymmetric_coverage_m2_criterion` — the SC #2 lock. Build against a GMU 001 mule_deer fixture (archery `D-M-001-O1-A` Sep 2–30 / muzzleloader `D-M-001-O1-M` Sep 12–20 / rifle `D-M-001-O2-R` Oct 24–Nov 1). Assert: 3 distinct `season_definition` rows; the single regulation_record `(CO-GMU-1, mule_deer)` links via `regulation_season` to all 3 seasons; archery vs rifle coverage sets differ. (Mirror MT `test_license_season_asymmetric_coverage_m1_criterion`.)
- `TestCountGuards` — each of the 5 guards: in-band passes; below-low raises; above-high raises.
- `TestMain` — `main(["--dry-run"])` returns 0 against the REAL committed artifacts; mock `db.connect` for a non-dry-run path asserting entity-before-link write order and single commit.
- Target 80+ total tests across T10+T11.
**Verify:** `cd ingestion && .venv/bin/ruff check tests/test_load_co_seasons_and_licenses.py && .venv/bin/mypy states/colorado/load_seasons_and_licenses.py 2>&1 | tail -3 && .venv/bin/pytest tests/test_load_co_seasons_and_licenses.py -q 2>&1 | tail -15`
**UI:** no

## Post-implementation (orchestrator, not a subagent task)
- Full suite must stay green and grow additively from 1787 + 4 skipped (expect ~1787+80 = ~1867 + 4 skipped).
- Closure note + Q20-RESOLVED breadcrumb in `docs/open-questions.md` + the 5 band counts get recorded at Stage 8 wrap-up.
