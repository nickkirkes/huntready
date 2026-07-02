# M2 → M3 Handoff Document

**Date:** 2026-07-01
**Milestone status:** M2 complete — E04 + E05 + E06 all closed + audited
**Final commit SHA:** `<COMMIT-SHA>` ← placeholder; user fills in at `git tag m2` time (tag lands at the commit where the **prod** M2-release UAT passes — see §9)
**UAT runbook:** `docs/runbooks/M2-uat.md`
**Prod UAT capture:** `docs/runbooks/M2-uat-results-<date>.md` (operator-produced by running the runbook against prod — pending at handoff authoring time)

---

## §1 What M2 Built

M2 delivered a complete regulatory data backend for **Colorado** V1 big-game hunting, built alongside — and reusing — the Montana foundation from M1 with **zero shared-code state-specific branches** (ADR-005 / ADR-007). Three epics closed and were audited:

- **E04 — M1 carry-forward + Colorado schema preparation** (5 stories; closed + audited 2026-05-31). RLS gap on `license_season` closed in production; M1 UAT runbook + M1→M2 handoff hygiene; PRD 001 sequencing reconciliation. No Colorado data.
- **E05 — Colorado geometry ingestion** (9 stories incl. the S05.3.5 carve-out; closed + audited 2026-06-06/-08). Full CO V1 geometry: 1 statewide + 186 GMU + 0 CWD zones (documented gap — CPW publishes no CWD-zone geometry) + 10 federal restricted areas = **197 rows**. ADR-021 (`jurisdiction_binding.role='no_hunt_zone'`) landed here via the S05.3.5 5-place-sync carve-out.
- **E06 — Colorado regulation text ingestion** (**17 stories**: 12 core S06.0–S06.11 with S06.2 omitted-by-design at S06.3 Stage-1 discovery, + 5 mid-epic carve-outs S06.3.1 / S06.6.1 / S06.6.2 / S06.8.0 / S06.9.1; closed + audited 2026-07-01). CPW Big Game brochure + correction extracted into committed artifacts; the 6-entity decomposed model (ADR-010) fully populated for Colorado 2026.

**What shipped in M2:**

- Colorado state adapter at `ingestion/states/colorado/` (mirrors the MT template; state-agnostic-clean per AST guards `TestNoColoradoLeakIntoSharedLib` / `TestNoStateAdapterImports`)
- Deterministic committed extraction artifacts (`big-game-2026.json`, `black-bear-2026.json`, `draw-mechanics-2026.json`, + corrections/base) via the S06.3 `lib/pdf.write_extraction_artifact` one-record-per-line serializer
- All 6 CO adapters live-verified on the **dev** Supabase project via two operator passes (M2-build 2026-06-23 for E05 geometry + S06.5/S06.6; E06 Group B 2026-07-01 for S06.7/S06.8/S06.9/S06.10), idempotency-confirmed
- Two new ADRs accepted during M2 (ADR-021, ADR-022) + ADR-020 resolving the M1-carry-forward Q19
- Test suite: **2301 passed + 5 skipped** at M2 close (M2-entry floor was 1346 + 2; grew additively, no MT regressions)
- E06 post-implementation audit (`docs/planning/epics/completed/E06-audit.md`); E04 + E05 audits already durable

**Parallel M3 track (context, not M2 scope):** E08 (M3 serving foundation) was planned and 4 stories shipped **in parallel** with E06 (PRs #79/#82/#84/#86, audited #87). The serving stack is therefore already partially built at M2 handoff time — see §5.

---

## §2 Schema Additions During M2

Colorado ingestion required **one** schema addition (all others reused M1's schema unchanged — the ADR-006 "schema is the contract" discipline held):

- **ADR-021** (`jurisdiction_binding.role='no_hunt_zone'`, 8th enum value) — shipped in migration `20260603000000_jurisdiction_binding_no_hunt_zone_role.sql` via the S05.3.5 carve-out with **5-place sync** (DDL + Pydantic `schema.py` + `overlays.py` `GeometryRoleForE03` alias + TypeScript `schema.ts` + `architecture.md`), plus reclassification of 3 MT federal no-hunt-zone geometries (50 fan-out binding rows) from `other_overlay` → `no_hunt_zone`. This resolves the M1→M2 §8 "`role='other_overlay'` semantic awkwardness" carry-forward.

**No E06 schema changes.** Every E06 schema-gap candidate (`PointSystem.kind`, `AllocationPool.selection`, `ReportingObligation.kind`, `SourceCitation.document_type`, the 4 `draw_spec` fields) was evaluated at S06.0 and found already-present — no migration fired across all of E06.

---

## §3 Final V1 Colorado Row Counts

> **Convention note.** Counts below are the **empirical dev DB counts** captured by the operator passes (2026-06-23 + 2026-07-01), which for CO equal the build counts (CO entity tables UPSERT by id; link tables `ON CONFLICT DO NOTHING`; CO data has no cross-listing collapse of the MT kind). They are locked as the **expected prod outcomes** in `docs/runbooks/M2-uat.md`. Verbatim capture: `group-b-operator-pass.md` (E06 loaders) + `docs/runbooks/M2-operator-pass.md` (E05 geometry + S06.5/S06.6; survives the m2 tag).

| Table | Count (CO) | Notes |
|---|---|---|
| `geometry` | 197 | 1 `CO-STATEWIDE-geom` + 186 GMU + 10 `restricted_area`; 0 CWD zones (documented gap — CPW publishes none) |
| `regulation_record` | 398 | mule_deer 141 / elk 115 / pronghorn 77 / whitetail 19 / bear 46; **0 statewide anchors** (CPW publishes no CO statewide-anchor content; `main()` guard fails loud on any `CO-STATEWIDE-*` pair) |
| `season_definition` | 2013 | |
| `license_tag` | 2470 | 1914 have `draw_spec_key` populated (S06.8 backfill); 556 remain NULL (non-limited-draw + 3 malformed bear GMU-851 — KI#15) |
| `license_season` | 2013 | link table |
| `regulation_season` | 2013 | |
| `regulation_license` | 2470 | |
| `draw_spec` | 1914 | 113 hybrid (2-pool 0.80 rank_ordered / 0.20 unweighted_random min_points 5; residency 0.20) + 1801 non-hybrid (1-pool; residency 0.25); `application_deadline='2026-04-07'` |
| `reporting_obligation` | 1 | `co-bear-mandatory-check-5day-statewide`; `verbatim_rule` = full 1238-char p.73 prose (KI#16 RESOLVED via S06.9.1) |
| `jurisdiction_binding` | 467 | roles: primary_unit 398 / no_hunt_zone 63 / other_overlay 6; **NO** `portion` (CO has none); **NO** `statewide` self-binding |
| `regulation_reporting` | 46 | 1 STATEWIDE bear obligation × 46 bear `regulation_record` rows |

**S06.7 entity+link total = 10,979** (2013 + 2470 + 2013 + 2013 + 2470).

**AFA 9+1 split (Known Issue #12, RESOLVED via S06.10):** of the 10 federal `restricted_area` geometries, the 9 NPS/NM rows bind `role='no_hunt_zone'` (ADR-021); the 1 Air Force Academy row binds `role='other_overlay'` (regulated-access HUNTING area — CPW publishes escorted rifle deer hunts there, brochure p.78). Locked live: AFA-as-`no_hunt_zone` = 0; AFA-as-`other_overlay` = 6.

### Montana — unchanged throughout M2 (PRD 002 SC #9)

| Table | Count | Notes |
|---|---|---|
| `regulation_record` (MT) | **437 (prod)** / 435 (dev)[^devprod] | |
| `geometry` (MT) | 350 | |
| `jurisdiction_binding` (MT) | 788 | of which `role='no_hunt_zone'` = 50 (reclassified at S05.3.5 from `other_overlay`) |

[^devprod]: The **dev** Supabase project reads 435 MT `regulation_record` rows vs the prod-anchored **437** (delta = exactly 2 pronghorn HD rows). Suspected cause: dev never received the post-S03.6.1 pronghorn build. The M2-release **prod** pass is expected to read 437 cleanly. Surfaced as group-b action item A1; the M2-uat runbook cites 437 as the prod baseline. Recommend investigating the 2-row dev/prod divergence before any future dev-vs-prod reconciliation, but it does not affect M2 correctness (MT was never written during M2 — both 435 and 437 are unchanged pre/post).

---

## §4 ADRs Accepted / Amended During M2

The ADR set grew from 19 (M1 close) to **24** at M2 close. M2-period ADR activity:

| ADR | Title | Status | Summary |
|---|---|---|---|
| ADR-020 | Derive-and-Assert for id text-PK Slug Drift | Accepted 2026-05-29 | Resolves Q19 (M1 carry-forward). Shared `ingestion/ingestion/lib/drift_guard.py` — two primitives (`assert_dispatch_dict_drift_free`, `assert_id_matches`); CO adapters adopt it in `season_definition`/`license_tag`/`reporting_obligation` builders |
| ADR-021 | `jurisdiction_binding.role='no_hunt_zone'` (8th enum value) | Accepted 2026-06-03 (S05.3.5) | 5-place sync; MT V1 reclassification of 3 federal geometries (50 bindings) `other_overlay` → `no_hunt_zone` |
| ADR-022 | Single-Module Per-State Adapters | Accepted 2026-06-16; **amended 2026-06-27** | Codifies the per-state monolithic-module convention (raised + declined 3× at S06.3). **Amended 2026-06-27** to broaden scope from "PDF extractors" to **all per-state adapters (extractors + loaders)** after the "split the loader" finding recurred against S06.8's `load_draw_specs.py`. Reopened only by a superseding ADR applied uniformly across all adapters of that kind in one PR. Synced across the ADR file + `docs/adrs/README.md` + `.roughly/known-pitfalls.md` + CLAUDE.md |

**M3-territory ADRs (Proposed; NOT M2 acceptance):** ADR-023 (Remote Authenticated MCP Server Posture) and ADR-024 (Edge-Runtime Postgres Access) landed as **Proposed** via the parallel E08 track and flip to `Accepted` as E08/E11 ship. They are M3's concern, listed here only so M3 does not re-discover them.

All M1 ADRs (ADR-001 through ADR-019) carry over unchanged.

---

## §5 What M3 Inherits

M3 (MCP canonical interface / serving stack) picks up a complete, tested two-state (MT + CO) regulatory backend plus a partially-built serving foundation from the parallel E08 track.

**M3 inherits:**

- Two-state populated schema (MT from M1, CO from M2); no shared-code state branches; all `ST_*` calls `extensions.`-prefixed (see `.roughly/known-pitfalls.md` § "Integration — Supabase / PostGIS")
- The Colorado adapter as a second worked example of the state-adapter pattern (extraction + ingestion + geometry + bindings)
- Confirmed-idempotent CO loaders + the M2-uat runbook orchestrating the **prod M2-release write** (operator-pending at handoff time)
- Test suite: **2301 passed + 5 skipped** at M2 close; M3 serving tests add to this without touching ingestion
- **E08 serving foundation already built in parallel** (this is the key difference from the M1→M2 clean handoff): Streamable HTTP transport on Cloudflare Workers (S08.1), read-only-enforced edge-Postgres single read path (S08.2), Shape C response envelope + reusable response/gating mechanisms (S08.3), CORS + wired-unenforced OAuth-2.1 auth seam (S08.4). Serving test baseline 0 → 139 (CI). E08 audited (PR #87), verdict ships clean. M3's remaining epics E09–E11 build on this.
- The `serving-audit shape` (E08's 4-per-story-agent + PM cross-cutting pass) as the E11 audit template

---

## §6 Open Questions Status at M2 Close

| Q | Status | Disposition / Action for M3 |
|---|---|---|
| Q11 | **RESOLVED** (M1, 2026-05-27) | ADR-017 FINALIZE; synthesis at `docs/planning/epics/completed/E03-confidence-calibration-synthesis.md` |
| Q12 | **Open — not fired for V1** | CO `draw_spec` wrote `parameters=NULL` on all 1914 rows (empirical zero-fire). No ADR needed for V1; the `parameters` escape hatch stays per ADR-012. Revisit only if a future state needs it |
| Q14 | **PARTIAL** | Serving half advanced in E08 (Supavisor pooler DSN format for edge-Postgres); RLS-runbook half remains M3 work |
| Q16 | **N/A for CO** | CO artifacts pre-separate species at extraction (`mule_deer`/`whitetail`/`elk`/`pronghorn`; no `deer` label). The MT `deer` → `mule_deer` + `whitetail` fan-out does not apply. Q16 stays open only for a hypothetical future state that re-surfaces deer fan-out |
| Q17 | **Open — not fired for V1** | CO published no per-GMU allocation caps that break the `pools[].share` shape (empirical zero-fire across S06.7/S06.8/S06.10; repeated hunt_codes are legitimate multi-GMU listings). No ADR needed for V1 |
| Q18 | **RESOLVED** (S06.0/D1, option c — license-keyed) | 0 typed CWD `reporting_obligation` rows; `cwd_sample` enum stays defined-but-unused; CWD text lives in `regulation_record.additional_rules`. CPW publishes no CWD-zone geometry (structurally unavailable — confirmed at E05 S05.3) |
| Q19 | **RESOLVED** (2026-05-29, ADR-020) | derive-and-assert via `drift_guard.py`; CO adapters adopt it |
| Q20 | **RESOLVED** (2026-06-23, S06.7 per-window fan-out) | Season Choice (method `X`) → 3 `season_definition` (one per method) + 1 `license_tag` (weapon_types union) + 3 `license_season` links; 0-window F-sex rows skip-with-WARNING |
| Q21 | **RESOLVED** (M3, option a) | Pin-enforce at fetch time; implemented in the M3 E07 epic. M3-territory; listed for completeness |
| Multi-source geometry provenance | **Deferred ADR-candidate** | S06.0/D5 = (b) split-provenance for V1: PAD-US keeps `geometry.source` (`document_type='gis_layer'`); CPW text reaches the 10 restricted-area rows via `verbatim_rule` only (S06.5). No migration. Becomes an ADR only if a future state needs true multi-source provenance in one geometry row |

Q1–Q10, Q13, Q22: see `docs/open-questions.md` parking lot / M3 scope. None are M3-blocking from M2's side.

---

## §7 Deferred Items — Post-E06 M2 Hygiene Ledger + V2 Candidates

The following are surfaced for a post-E06 hygiene-sweep PR (bundle them; several touch merged + audited code and each needs its own review). None block M3.

**Post-E06 M2 hygiene ledger (bundle into one sweep):**

| Item | Summary |
|---|---|
| KI#7 | Narrow overlay-builder shared-lib extraction (from E05) — hoist the 2 pure primitives (`_build_overlay_pairs` discriminator + `_write_outputs` serializer) into `lib/overlays.py`, migrate MT+CO; leave thresholds/allowlists per-state |
| KI#8 | MT-extractor migration to `write_extraction_artifact` — MT's 3 extractors still emit `indent=2` (`dea-2026.json` is 47,956 lines, one bigger brochure from cubic's 50k cap). Format-only, data-unchanged, re-pin SHA |
| KI#13 | ~477 female-`-F-` rifle rows carry empty `season_windows` (pdfplumber merged each female row's season-date cell into the adjacent male row). S06.7 loads faithfully + WARNING-flags; the regulation_record level is complete. PM recommendation: (a) `extract_big_game.py` carve-out that recovers the merged female-row windows + re-pins SHA |
| KI#14 | Cross-loader private-import contract — promote the shared CO id-derivation/classification/constants into a documented shared surface (`colorado/_shared.py`), applied uniformly across CO + MT in one PR; overlaps the S06.0/D3 `_STATE` unification already delivered at S06.10 |
| KI#15 | Bear-extractor GMU-851 row-fusion residual — 3 codes (`B-E-851-O1-M +` / `O2-R +` / `O5-R +`) carry a `+` corruption; S06.8 skips-with-WARNING (user-ratified); the 3 bear `license_tag` rows keep `draw_spec_key=NULL`. Carve-out fixes the extractor + re-pins SHA (3 of 1914) |
| KI#17 | (Informational) `db.py` blast-radius discipline note — the S06.9 `upsert_reporting_obligation` rowcount guard was a disciplined no-broken-windows lib touch; recorded so future planning factors "review-discovered lib touches are sometimes right" |
| KI#18 | (Folded into `docs/runbooks/M2-uat.md` this story) — 3 stale verification-SQL column-name corrections; applied at runbook authorship, not a separate PR |
| known-pitfalls.md reorg | ~1,684+ LOC; doc-writer flagged for reorg/dedup in every E05/E06 story since S05.3.5. Schedule a dedicated documentation-hygiene session in the sweep |

**V2 candidates (not V1 work):**

- **AFA geometry-layer classification** (KI#12 option b) — if hunting-permission-bearing federal lands become numerous, revisit the S05.4 `kind='restricted_area'` classification at the geometry layer (vs. the V1 binding-layer `other_overlay` disposition). Requires geometry-side migration + ADR.
- **Multi-source geometry provenance** — see §6; ADR-candidate only if a future state needs it.
- **PAD-US 4.1 source stability** — two distinct republish drifts in 18 calendar days during E06 (OID drift → GeometryCollection drift; both patched via S06.6.1/S06.6.2 carve-outs). Strategic call for M2-release/M3: pin a PAD-US snapshot fixture + cache vs. continue patching live-fetch drift vs. re-source from NPS/USFWS.

**Deferred items from M1 that survive (E03 deferred-items directory, `docs/planning/epics/completed/E03-deferred-items/`):** `draw-mechanics.md` (Q12), `cwd-sampling-modeling.md` (Q18 — now RESOLVED for CO but the file documents the general model), `closure-temporal-anchors.md` (`ClosurePredicate.effective_after` — did NOT fire for CO V1; still a candidate for a future quota-AND-calendar-gate closure).

---

## §8 Known Issues Audit at M2 Close (all 19 E06 KIs)

| KI | Disposition at M2 close |
|---|---|
| #1 Operator Group B batched live-write | **COMPLETE on dev** (M2-build 2026-06-23 + E06 Group B 2026-07-01). Prod M2-release pass orchestrated by `docs/runbooks/M2-uat.md` (operator-pending — gates the m2 tag) |
| #2 known-pitfalls.md reorg | Deferred → hygiene sweep (recurring flag) |
| #3 Recurring-RLS-gap M2 open question | No new `public.*` table in E06 → not triggered; discipline persists for M3 |
| #4 KI#7 overlay-builder lib extraction | Deferred → hygiene sweep |
| #5 E05 research-doc accuracy item | Open (PM does not edit `docs/research/` autonomously; surface to human) |
| #6 Q12/Q16/Q17/multi-source ADR drafting | No trigger fired for V1 → no ADR |
| #7 CPW Big Game brochure URL | **RESOLVED** 2026-06-08 (S06.0/D4; Artemis durable path + SHA pin) |
| #8 MT-extractor `write_extraction_artifact` migration | Deferred → hygiene sweep |
| #9 Monolithic extractor pattern | **RESOLVED** — formalized as ADR-022 (Accepted 2026-06-16; amended 2026-06-27) |
| #10 S06.3 elk-correction gap | **RESOLVED** via S06.3.1 (2026-06-16, outcome b — corrections already in the post-dated brochure) |
| #11 big-game row-fusion defect | **RESOLVED** via S06.3.1 (2026-06-16, 4 codes recovered) |
| #12 AFA no_hunt_zone prohibition | **RESOLVED** via S06.10 (2026-06-29, option a — AFA binds `other_overlay`) |
| #13 ~477 female-row empty season_windows | Deferred → hygiene sweep (extractor carve-out candidate; regulation_record level complete) |
| #14 Cross-loader private-import contract | Deferred → hygiene sweep (overlaps S06.0/D3 `_STATE`, delivered at S06.10) |
| #15 Bear GMU-851 row-fusion residual | Deferred → hygiene sweep (3 of 1914; skip-with-WARNING, user-ratified) |
| #16 Bear mandatory-inspection prose | **RESOLVED** via S06.9.1 (2026-06-30, full 1238-char p.73 prose) |
| #17 db.py blast-radius discipline note | Informational (no action) |
| #18 Runbook stale-SQL column-name drift | **Folded into `docs/runbooks/M2-uat.md`** this story (3 corrections applied at authorship) |
| #19 `_BINDING_COUNT_GUARD_BAND` narrowing | **RESOLVED** 2026-07-01 (commit `3aa5888`; band `(300,1200)` → `(327,607)` around empirical 467; lock test added) |

M2-substrate items (#1/#3/#5/#6) are the persisting-discipline set; the deferred bundle is (#2/#4/#8/#13/#14/#15) + informational #17; #18 folded; the RESOLVED set is (#7/#9/#10/#11/#12/#16/#19). (Numbers are this table's E06-epic KI numbering 1–19; row #4 is the overlay-builder shared-lib extraction — carried as E05's Known Issue #7 in the §7 hygiene ledger.)

---

## §9 Final Commit + Tag Handoff

**Final commit SHA:** `<COMMIT-SHA>` ← placeholder; user fills in at `git tag m2` time.

**Prod M2-release pass gates the tag.** Unlike M1 (where the tag landed at handoff-document time), the M2 tag lands at the commit where the **prod** M2-release UAT passes. Sequence:

1. Operator runs `docs/runbooks/M2-uat.md` against the **prod** Supabase project (`supabase db push` → E05 geometry loaders → `build_overlay_fixture` → `spatial-test-points.json` → E06 loaders S06.5→S06.6→S06.7→S06.8→S06.9→S06.10 → the 10 PRD 002 success-criteria verification queries).
2. Operator captures verbatim outputs in `docs/runbooks/M2-uat-results-<date>.md` (M1's `M1-uat-results-2026-05-28.md` pattern).
3. All PRD 002 success criteria PASS (or documented PARTIAL with rationale).
4. Human pushes the tag (PM does not push tags):

```bash
git tag m2 <COMMIT-SHA>
git push origin m2
```

M3 (MCP canonical interface) is the active milestone and is **already in progress** on the parallel E08 track. Start M3 planning for E09 from `docs/planning/prds/003-M3-canonical-interface.md` + the E08 audit + this handoff. The E06 `Audited:` field is populated, so `/plan-next-epic` for post-E06 planning (M3 E09 dispatch or the post-E06 M2 hygiene sweep) is unblocked.
