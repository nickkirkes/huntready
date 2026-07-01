# Epic Audit: E06 — Colorado Regulation Text Ingestion

**Audited:** 2026-07-01
**Method:** Independent per-story review — 4 parallel cluster-auditor agents (extraction / ingestion / infra+geometry-hardening / cross-cutting+binding) verifying each story's Acceptance Criteria against shipped evidence (epic per-story blocks, CLAUDE.md rolling closures, the `group-b-operator-pass.md` + `M2-operator-pass.md` live-write captures, on-disk artifacts/SHAs, test files, and git commits) + a PM-run faithfulness UAT batch (3 parallel agents comparing extracted artifacts against the source CPW brochure PDF) + PM cross-cutting synthesis. Mirrors the E05-audit re-run pattern (2026-06-08) and the E02/E04/E05 locked precedent.

| Tally | Count |
|---|---|
| Stories audited | 17 (12 core incl. S06.2-omitted + 5 mid-epic carve-outs) |
| Group A (at-merge) | MET across all stories |
| Group B (live-write) | MET on dev (M2-build 2026-06-23 + E06 Group B 2026-07-01); prod M2-release pass operator-pending |
| PM UAT faithfulness batch | 8 / 8 PASS (0 discrepancies) |
| PARTIAL | per-story UAT / spatial ACs, now closed by this audit's UAT batch + dev capture; AC #1111 dev-verified, prod-pending |
| NOT MET | **0** |
| Blocking findings | **0** |

**Verdict: E06 ships clean — 0 NOT MET, 0 blocking findings.** The only operator-pending item is the **prod M2-release pass** (a separate future operator write that gates the `m2` tag) — the established Group-A-authored / Group-B-operator-runs posture, not a gap.

---

## Summary

E06 delivered Colorado regulation-text ingestion across 17 stories (2026-06-08 → 2026-07-01), fully populating the 6-entity decomposed model (ADR-010) for Colorado 2026 with **zero shared-code state-specific branches**. The epic grew from a planned 12 stories to 17 via 5 mid-epic carve-outs (S06.3.1, S06.6.1, S06.6.2, S06.8.0, S06.9.1) — each a clean, human-decision-driven response to a concrete discovery, executed without reopening the parent story. S06.2 was omitted by design at S06.3 Stage-1 discovery (the `lib/pdf` primitives were already sufficient).

Every story's Group A ACs (loader/extractor code + dry-run tests + quality gates) were satisfied at merge. Every DB-write story's Group B ACs (live row-counts + SQL-shape + FK validity) were closed on the **dev** Supabase project across two operator passes, with full idempotency (re-run zero-deltas) and PRD 002 SC #9 (Montana untouched: 435 dev / 350 / 788 / 50 `no_hunt_zone`) held end-to-end. The 8 deferred PM faithfulness UATs (Option-C fold-in) were executed in this audit and all PASS. The one remaining verification — the prod M2-release pass — is operator-gated and produces the capture that gates the `m2` tag.

**Empirical Colorado composition:** geometry 197 · regulation_record 398 · S06.7 entity+link 10,979 · draw_spec 1914 (+1914 backfills) · reporting_obligation 1 · jurisdiction_binding 467 · regulation_reporting 46. Test baseline grew 1346 → **2301 + 5 skipped**, additively, no MT regressions.

---

## Per-Story Results

### Extraction stories

### S06.0 — Pre-E06 decisions + schema-prep gate (PR #65 / `5d6ab37`)
**✅ Group A MET (12/12) · doc-only, no Group B.** Decision-gate story: all 5 + conditional-6th decisions captured verbatim in the durable memo; schema-gap read-through fired NO migration (all 7 candidates already present in the live schema, each cited file:line). D4 (CPW brochure URL) resolved same-day with URL + SHA + HTTP-header baseline. The decision-gate-story pattern worked as intended — human decisions collected, zero code shipped.

### S06.1 — CPW PDF fetch infrastructure (PR #66 / `abc6c21`)
**✅ Group A MET · Group B (manifest commits) PARTIAL by design (S03.1 precedent).** `fetch_pdfs.py` + 2 SHA-pinned CPW PDFs. The post-review `expected_sha256` fix to `lib/pdf_fetch.fetch_pdf` (state-agnostic; `"unknown"` skips, so MT unaffected) closed a real gap — CO was the first state with operator-verified SHA pins. SHA pins in `sources.yaml` match the S06.0/D4 memo exactly.

### S06.3 — Big-game extraction (PR #67 / `08bf396`)
**✅ Group A MET · UAT PASS (this audit).** `extract_big_game.py` → `big-game-2026.json`; introduced the load-bearing `lib/pdf.write_extraction_artifact` one-record-per-line serializer (drove ADR-022). Current artifact SHA `9312e259…` (post-S06.3.1/S06.4 lineage) verified on disk against the test pin.

### S06.3.1 — Big-game extractor hygiene carve-out (PR #69 / `bfeb60a`)
**✅ Group A MET · UAT PASS (this audit).** Known Issues #10 + #11 RESOLVED: elk-correction confirmed inert (outcome b — brochure postdates all corrections); R16 row-fusion split recovered **4** codes (the S06.4 narrative's "9" was an unmeasured estimate — corrected per the "name the source-of-truth" discipline). **ADR-022 created here.** SHA lineage `3c2ecd90 → e5c7c33a → 9312e259` fully documented.

### S06.4 — Black-bear extraction (PR #68 / `51f6aa7`)
**✅ Group A MET · UAT PASS (this audit).** `extract_black_bear.py` → `black-bear-2026.json` (173 records / 215 rows). Coordinated `valid_gmus` cleanup appropriately touched merged S06.3 code ("no broken windows"; SHA lineage documented). **Process note:** cubic was unavailable during the late review cycle — gates rested on ruff/mypy/full-suite + manual SHA/count verification; all triad findings were applied via post-review commits, and no quality defects are evident in the shipped code or downstream work.

### S06.8.0 — Draw-mechanics extraction carve-out (PR #77 / `68e0c04`)
**✅ Group A MET · UAT PASS (this audit).** `extract_draw_mechanics.py` → `draw-mechanics-2026.json` (123 records: 116 hybrid_code + 4 point_only_code + 1 important_dates + 1 nr_allocation + 1 hybrid_mechanics); SHA `7fd162ad…` verified. **Merge-bundle note:** PR #77 carried 2 unrelated bundled payloads (an M3 doc fix + permissions config) — flagged as not-S06.8.0-scope; landed cleanly, no interaction with extraction logic.

### Ingestion (DB-write) stories

### S06.6 — Regulation-record ingestion (PR #71 / `4ecd47d`)
**✅ Group A MET · Group B MET (dev, 2026-06-23).** First E06 DB-write: **398** regulation_record (bear 46 / elk 115 / mule_deer 141 / pronghorn 77 / whitetail 19; 0 statewide anchors, guard-enforced). Q16 does not fire for CO (species pre-separated). FK 0 dangling.

### S06.7 — Seasons + licenses ingestion (PR #75 / `433ea73`)
**✅ Group A MET · Group B MET (dev, 2026-07-01).** First CO multi-link adapter: **10,979** entity/link rows (2013 season_definition + 2470 license_tag + 2013 license_season + 2013 regulation_season + 2470 regulation_license). Q20 RESOLVED (per-window fan-out). **PRD 002 SC #2 asymmetric coverage LOCKED LIVE** on GMU 001 mule_deer (3 tags × 1 season). `drift_guard.assert_id_matches` at 4 entity-builder sites; link builders AST-locked NOT instrumented. Known Issue #13 (~477 female-row empty season_windows) documented + WARNING-flagged — regulation_record level is complete; not a silent drop.

### S06.8 — Draw-spec ingestion (PR #81 / `bf4e2c8`)
**✅ Group A MET · Group B MET (dev, 2026-07-01) · AC #983 UAT PASS (this audit).** **1914** draw_spec (113 hybrid 2-pool 0.80/0.20 + 1801 non-hybrid 1-pool; residency 0.20/0.25; `application_deadline=2026-04-07`) + 1914 `draw_spec_key` backfills (556 remain NULL: 2470−1914). Q12 + Q17 empirical zero-fire (`parameters=NULL` everywhere; no non-null quotas). 3 malformed bear GMU-851 codes skip-with-WARNING (user-ratified; Known Issue #15). ADR-022 amended to cover loaders.

### S06.9 — Reporting-obligation ingestion (PR #83 / `ff23859`)
**✅ Group A MET · Group B MET (dev, 2026-07-01) · AC #1036 UAT PASS (this audit).** Exactly **1** reporting_obligation (`co-bear-mandatory-check-5day-statewide`); upstream-data reality reshaped the epic's "3-10" estimate → empirical 1. Q18 = option (c) honored (0 typed CWD rows). `assert_dispatch_dict_drift_free` at module top-level. Added the `upsert_reporting_obligation` rowcount guard to `db.py` (Known Issue #17 — disciplined no-broken-windows lib touch, state-agnostic).

### S06.9.1 — Bear mandatory-inspection prose carve-out (PR #88 / `735add4`)
**✅ Group A MET · AC #1170 UAT PASS (this audit).** Known Issue #16 RESOLVED: three-fixed-geometry-bbox-crop rewrite recovers the full **1238-char** p.73 prose (root cause: un-cropped multi-column read truncating at a right-column heading — same class as S06.5's split). New positive prose-anchor guard (`five\s+working\s+days`) prevents non-empty-but-wrong crops. SHA lineage `7b35c202… → 0c1f0fd1…`; 173 records unchanged (byte-slice verified — only the RO `verbatim_rule` changed).

### Infra / geometry-hardening carve-outs

### S06.6.1 — PAD-US OBJECTID `outFields` hardening (PR #72 / `0506831`)
**✅ Group A MET · Group B closed via S06.6.2 + operator pass.** New strict `_require_objectid` helper in `lib/arcgis.py` (state-agnostic; `_read_objectid` unchanged for its legitimate fallback callers) + `_RA_OUT_FIELDS` OBJECTID fix + AST-walk regression guard. Post-review scalar-only-coercion P1 fix prevented a manifest hash-collision risk. First of two PAD-US 4.1 republish-drift carve-outs.

### S06.6.2 — PAD-US GeometryCollection epsilon relaxation (PR #73 / `82e34df`)
**✅ Group A MET · Group B verified live (M2-build 2026-06-23).** Phase-A characterization proved only RMNP enters the GC branch (the 0.0676% "gap" is self-intersection artifact removal, not data loss); `rel_tol 1e-6 → 1e-3` with a ~20-line rationale comment; **fail-loud preserved** (genuine >0.1% overlap loss still raises at 125× the threshold). Two boundary tests pin both sides. Closed the deferred S06.6.1 metadata+manifest fixtures. Second PAD-US drift carve-out.

### Cross-cutting + binding

### S06.5 — Restricted-area verbatim_rule (PR #70 / `207f31d`)
**✅ Group A MET · Group B MET (dev, 2026-06-23) · AC #486 UAT PASS (this audit).** 10 `verbatim_rule` (9 NPS/NM share the 130-char closure sentence; 1 AFA = 397-char access prose); split-provenance D5=(b) (source stays PAD-US `gis_layer`). Delivered `db.update_geometry_verbatim`. Surfaced Known Issue #12 (AFA is a regulated-access hunting area, not a closure) — correctly propagated to S06.10. UAT confirmed AFA prose contains "access fee"/"allowed", no "closed"/"prohibited".

### S06.10 — Jurisdiction-binding generation (PR #85 / `1faa7b0`)
**✅ Group A MET (16 ACs) · Group B MET (dev, 2026-07-01) · AC #1111 PARTIAL (dev-verified; prod-pending).** Final E06 DB-write: **467** jurisdiction_binding (primary_unit 398 / no_hunt_zone 63 / other_overlay 6; NO portion; NO statewide self-binding) + **46** regulation_reporting, one atomic transaction. **Known Issue #12 RESOLVED** — AFA 9+1 split held live (`no_hunt_zone`=0, `other_overlay`=6 for AFA). `_STATE` unification delivered (S06.0/D3). The `regulation_reporting` scope omission (contracted in 6 epic locations, absent from the AC list) was caught by the Stage-6 silent-failure-hunter and added the same cycle (AC #1116b) — see cross-cutting finding #4. Count band narrowed to `(327,607)` (KI#19).

### Omitted / final

### S06.2 — PDF extraction primitives (extension)
**Omitted by design** at S06.3 Stage-1 discovery — the `lib/pdf` primitives from M1 were already sufficient for CO. Counted as complete-via-omission.

### S06.11 — M2 milestone UAT prep + handoff to M3 (this story)
**✅ In progress at audit authorship.** Produces `M2-uat.md`, `M2-to-M3-handoff.md`, this audit, the PM UAT batch (below), the AC #1111 spatial spot-check preservation, working-notes deletion, and the CHANGELOG/README/CLAUDE.md M2-closure updates. Prod M2-release pass operator-pending.

---

## PM UAT Faithfulness Batch (Option-C fold-in) — 8 / 8 PASS

Executed in this audit: 3 parallel agents compared the committed extraction artifacts (the verbatim source the loaders wrote) against the CPW 2026 Big Game brochure PDF, page-targeted via each record's `page_reference`. Minor pdfplumber normalizations (collapsed spaces, soft-hyphen line breaks, column-edge truncation) are ADR-008-acceptable.

| AC | Story | Check | Verdict |
|---|---|---|---|
| #343 | S06.3 | ≥4 GMU sections (mule_deer ×2, elk ×1, pronghorn ×1) vs brochure pages 33/37/55/67 | **PASS** |
| #429 | S06.3.1 | 4 recovered fused-row codes (`D-M-082-O3-R`, `D-F-107-O1-R`, `A-M-004-O1-M`, `A-F-118-O1-R`) vs pp.40/65/67 | **PASS** |
| #343 | S06.4 | ≥2 bear sections (GMU 002 archery p.73, GMU 040 rifle p.75) vs brochure | **PASS** |
| #486 | S06.5 | 3 zones (NPS closure sentence ×9 + AFA access prose) vs brochure p.78; AFA is access-not-closure | **PASS** |
| #905 | S06.8.0 | important_dates (Apr 7 / Jun 30 / Aug 4) p.14 + hybrid codes pp.28-29 + point-only codes p.30 | **PASS** |
| #983 | S06.8 | 4 draw_spec shapes (hybrid 2-pool 0.80/0.20 + non-hybrid 1-pool + residency 0.20/0.25 + deadline) vs pp.14/29 | **PASS** |
| #1036 | S06.9 | full 1238-char mandatory-inspection `verbatim_rule` byte-faithful to p.73 (all 4 sub-passages) | **PASS** |
| #1170 | S06.9.1 | re-extracted prose not heading-truncated; S06.9.1 fix confirmed effective | **PASS** |

**No discrepancies found.** The only systematic gap — empty `season_windows` on female (`-F-`) rows — is the pre-documented Known Issue #13 pdfplumber row-fusion artifact (the female cells merge into the male row in the source table), independently corroborated by the audit as NOT an extraction-faithfulness failure (the regulation_record level carries the seasons via the male rows).

**AC #1111 (PRD 002 SC #4 spatial spot-check):** dev-verified 2026-06-23 (M2-operator-pass Step 7 §2) — all 7 `spatial-test-points.json` points resolve to their expected GMU + overlays under `extensions.ST_Covers(...) WHERE state='US-CO'`; the Wyoming negative control returns 0 rows. Preserved in `M2-uat.md` §4 Criterion #4; the prod-side query is authored there for the prod pass.

---

## Cross-Cutting Findings

1. **PAD-US 4.1 upstream republish drift (2 drifts / 18 days).** The OBJECTID/`outFields` drift (S06.6.1) and the GeometryCollection topology drift (S06.6.2) both stemmed from a single PAD-US republish 18 days after S05.4 close. The project's fail-loud discipline surfaced both cleanly (0 rows written, actionable diagnostics, no silent corruption); the mid-epic carve-out pattern absorbed them without disrupting the E06 merge order. The strategic source-stability question (snapshot-and-cache vs. patch-live-drift vs. re-source) is correctly carried as an M2-release/M3 candidate, not resolved in scope.

2. **ADR-022 lifecycle (formalize-a-repeatedly-declined-finding).** The "split the module" review finding was raised 3× against S06.3's 2,685-LOC extractor and declined uniformly; S06.3.1 formalized ADR-022, and S06.8 amended it to cover DB loaders after the same finding recurred against `load_draw_specs.py`. The pattern — codify a convention once a finding must be declined repeatedly — stopped the re-litigation.

3. **SHA lineage discipline.** `big-game-2026.json` (3 revisions: `3c2ecd90 → e5c7c33a → 9312e259`) and `black-bear-2026.json` (`7b35c202 → 0c1f0fd1`) each carry fully-documented SHA lineages with re-pinned test locks and byte-slice guards proving the intended (and only the intended) slice changed. This is the project's strongest data-provenance discipline.

4. **"AC list is necessary but not sufficient."** Twice in E06 (S06.9 and S06.10), a cross-story-boundary deliverable contracted in the epic prose was absent from the story's AC list and caught by the Stage-6 silent-failure-hunter (S06.10's `regulation_reporting` link writes → AC #1116b added at closure). The recorded pitfall — grep the whole epic + predecessor closure notes for contracted deliverables, not just the AC list — is the correct mitigation.

5. **Doc-figure drift, caught and corrected at source.** Three number-transcription errors were caught and corrected across the epic: S06.7 total 8,979 → 10,979 (rolled-up-sum arithmetic), verbatim_rule 1288 → 1238 (digit-swap), black-bear 172 → 173 records (closure-narrative transcription). Same class as the S04.x/S05.4 corrections; all corrected at source with the "name the source-of-truth before copying numbers" discipline.

6. **KI#18 verification-SQL drift.** Three stale column-name assumptions in the verification runbook (link tables filter by `state`; `draw_spec.inactive_forfeit_years` is a `point_system` jsonb field; `jurisdiction_binding`/`regulation_reporting` composite-FK, no `state` column) were corrected by the operator at run time (results unaffected) and are now baked into `M2-uat.md` at authorship.

7. **Closure-narrative LOC drift (informational).** Several loader LOC figures in closure narratives (S06.7 ~1700 vs 1924; S06.8 ~640 vs 1093; S06.9 ~290 vs 742) were written before post-review hardening commits landed; the extra code is guards/validators/test-locked constants, not a quality concern. Future PM close notes should measure LOC from `wc -l` post-merge.

8. **Two working notes absent** (`S06.9.md`, `S06.10.md`) from `E06-confidence-findings/` — non-blocking; their verification evidence lives in `group-b-operator-pass.md` and the epic/CLAUDE.md closures. Noted so the absence is explicit rather than an unrecorded gap; the T10 `git rm -r` removes only what exists.

---

## Recommendations

- **Advisory (no action required at E06 close):** none blocking. The prod M2-release pass is the one operator-pending item and gates the `m2` tag.
- **Post-E06 M2 hygiene sweep (bundle into one review-bearing PR):** KI#7 (overlay-builder shared-lib extraction) · KI#8 (MT-extractor `write_extraction_artifact` migration) · KI#13 (female-row empty-season_windows extractor carve-out) · KI#14 (cross-loader private-import shared surface) · KI#15 (bear GMU-851 row-fusion residual) · the `.roughly/known-pitfalls.md` reorg (~1,684 LOC; flagged since S05.3.5). Each touches merged + audited code and needs its own review.
- **M2-release / M3 strategic:** decide the PAD-US 4.1 source-stability posture before the prod pass or M3 (snapshot-and-cache vs. patch-live vs. re-source).
- **Informational:** KI#17 (db.py blast-radius discipline) — record that review-discovered lib touches are sometimes the right call.

---

*HuntReady · E06 audit · M2 — Colorado Ingestion · 2026-07-01 · 17 stories · verdict: ships clean, 0 NOT MET, 0 blocking findings; prod M2-release pass operator-pending gates the m2 tag.*
