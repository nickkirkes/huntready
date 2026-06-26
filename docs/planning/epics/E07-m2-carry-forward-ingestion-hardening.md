# E07: M2 Carry-forward + Ingestion Hardening

**Status:** In Progress
**Milestone:** M3 — Canonical Interface Live
**Dependencies:** M2 ingestion work landing on `main` (see "M2-coordination timing" below). E07 is **isolation, not dependency** relative to E08–E11 — it shares no code with the serving stack (PRD 003 §"Why sequential"). It is the only Python/ingestion epic in M3.
**Validated:** 2026-06-26 (E07 ingestion triad — ArcGIS Fetch-Hardening + Ingestion-Hygiene Fidelity + ADR/Cross-Language reviewers all returned LAND-WITH-EDITS; all MUST-FIX + SHOULD-FIX findings applied; see "Validation triad notes" below)
**Drafted:** 2026-06-26
**Estimated Stories:** 4 (S07.1–S07.4; the M3 PM plan estimates 4–6 for E07)
**UAT Gating:** S07.1 (operator gate-behavior spot-check — Group A/B split; Group B non-blocking, mirroring the E05 operator-pending posture). S07.2 / S07.3 / S07.4 are `UAT: no` (verified against E07 exit criteria + the no-loaded-row-change invariant).

---

## Objective

E07 closes the ingestion-side carry-forward debt that M3's production posture makes load-bearing, before the serving stack (E08–E11) reads from a production environment. Three concrete code items plus one decision-gate:

1. **PAD-US geometry pin-enforcement** (Q21 option (a) — the two-gates fetch model). The geometry fetch path gains an operator-controllable expected-hash gate that refuses to write when a live re-fetch diverges from the pinned snapshot, mirroring the PDF loaders' `expected_sha256` model and `*-pending-reextraction.flag` recovery workflow. Production intent makes dev/prod PAD-US snapshot drift a real correctness concern (PAD-US 4.1 republished twice in 18 days during the M2-build operator pass — S06.6.1 + S06.6.2).
2. **Overlay-builder shared-lib extraction** (E05 Known Issue #7) — hoist the two pure, low-divergence overlay primitives into `ingestion/ingestion/lib/overlays.py`, migrate MT + CO, leave thresholds/allowlists/orchestration per-state.
3. **MT extractor migration to `write_extraction_artifact`** (E06 Known Issue #8) — migrate the **one** flat-list MT extraction artifact (`dea-2026.json`, ~48k lines at `indent=2`, one big brochure away from cubic's 50k-line review cap) to the canonical one-record-per-line serializer; format-only. (MT's other artifacts are dict envelopes and are excluded — see S07.3; MT pins no determinism SHA today, so there is nothing to re-pin.)
4. **Edge-runtime Postgres access principle (ADR-024) — acceptance-readiness** — a no-code decision gate confirming the *principle* (the serving stack reads Postgres from the edge runtime, not a long-running Node process) is settled and surfacing ADR-024 for the human. ADR-024 stays `Proposed`; it flips to `Accepted` at E08 when the concrete driver ships.

See [PRD 003 §"E07 — M2 carry-forward and serving-stack preparation"](../prds/003-M3-canonical-interface.md) for authoritative scope. See [`docs/open-questions.md` Q21](../../open-questions.md) for the pin-enforcement decision record, and the E05/E06 epics under [`completed/`](completed/) for the ArcGIS-fetch + overlay-builder + extractor context this epic hardens.

**Non-negotiable invariant for all four stories: E07 changes fetch-time validation, extractor serialization format, and shared-library structure — it changes NO loaded rows.** Montana is frozen at `m1`; Colorado at `m2`. Row counts in Postgres are unchanged by every E07 story (PRD 003 success criterion #13). E07 is Python-only; no `mcp-server/` file is touched.

---

## M2-coordination timing (read before scheduling implementation)

E07 touches files that in-flight M2 ingestion PRs also touch: `ingestion/ingestion/lib/arcgis.py`, the CO geometry loaders (`load_gmus.py`, `load_restricted_areas.py`), the per-state overlay builders, and the MT extractors. M3 does not own M2's work (the M2 PM does). To avoid racing M2 ingestion PRs on shared files:

- **E07 implementation/merge follows the relevant M2 ingestion work landing** — in practice, after the `m2` tag, or after the specific M2 PRs touching these files merge. The PM surfaces the go/no-go timing to the human per story.
- **The test baseline is "current `main` at branch time," not a frozen number.** At the S06.7 close this branch derives from, the baseline is **1907 passed + 4 skipped**; if further M2 ingestion PRs land before an E07 story branches, that story rebases onto the then-current `main` and its test delta is measured additively against that baseline. Each E07 story's AC states "test baseline grows additively; no existing test deleted except format-driven re-pins in S07.3."
- **E08 *planning* may begin before E07 *merges* only with explicit human direction** (E07 and E08 share no code — only the ADR-024 principle, decidable independently). The default is sequential; the PM does not start E08 planning unprompted.

---

## Validation triad notes (2026-06-26)

Three ingestion reviewers validated the draft; all returned **LAND-WITH-EDITS** (no NEEDS-REVISION). Every finding was applied. The load-bearing corrections, each verified against the live code:

- **`TestNoStateAdapterImports` does not guard the shared lib** (ArcGIS reviewer MUST-FIX). It guards `drift_guard.py` and the CO *adapter*, not `arcgis.py`/`overlays.py`. Only `TestNoColoradoLeakIntoSharedLib` (`test_arcgis.py`, `rglob`s `ingestion/lib/`) is the lib-leak guard. Corrected in the commitments table, S07.1, and S07.2.
- **S07.3 migration set is exactly one artifact** (Ingestion-Hygiene reviewer MUST-FIX×2). `dea-2026.json` is the only flat-list MT artifact; `legal-descriptions-2026.json` and all three black-bear artifacts are dict envelopes the list-only `write_extraction_artifact` cannot serialize without a data-shape change (out of behavior-preserving scope). And **MT pins no determinism SHA** (tests are `json.load`-based / format-agnostic) — there is nothing to re-pin; the CO SHA-lineage discipline does not transfer.
- **Both geometry fetch paths must be gated and tested** (ArcGIS reviewer) — the public `fetch_features` path (CPW GMUs + MT) and the composed-primitive path in `load_restricted_areas.py` (PAD-US). The gate scopes to the `layer_hash`-bearing feature fetch, not `fetch_layer_metadata`. Drift-marker semantics mirror the PDF precedent (Gate-1 pin-mismatch raises without a marker; Gate-2 manifest drift writes the marker).
- **Q21 mechanism reconciliation** (ArcGIS reviewer) — Q21's resolution is mechanism-agnostic ("pin-enforce at fetch time"); its effort-note illustratively prescribes option (B). Choosing (A) (`sources.yaml` pin, PM recommendation) is a deliberate, acceptable deviation from the non-binding note.
- **S07.4 dangling reference + role-provisioning attribution** (ADR reviewer) — there is no ADR-status table in `docs/planning/README.md`; the SELECT-only role is provisioned in E08 (in M3 scope, not E07's). Corrected.
- **`_write_outputs` is not `write_extraction_artifact`** (Ingestion-Hygiene reviewer) — S07.2's hoisted overlay serializer preserves the existing `indent=2` two-file atomic format exactly (byte-identical fixtures expected); it is NOT migrated to the one-record-per-line format (that is S07.3's extractor-only concern).

All ADR links and internal paths were verified to resolve (no broken-link failure mode present). The "no schema / three-place-sync / migration / `db.py`-write-helper change" invariant was confirmed airtight across all four stories.

---

## Architectural commitments inherited from M1 + M2 (E07 must hold)

| Commitment | Source | E07 implication |
|---|---|---|
| State-adapter isolation: no state-specific code in `ingestion/ingestion/lib/` | [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) + `TestNoColoradoLeakIntoSharedLib` (`ingestion/tests/test_arcgis.py` — the lib-directory leak guard; `rglob`s every `.py` under `ingestion/lib/`, so it auto-covers new lib code) | S07.1's `arcgis.py` gate + S07.2's `overlays.py` extraction are **state-agnostic-clean expansions** (same pattern as S06.1's `fetch_pdf` `expected_sha256` addition and S05.5's `overlays.py` Literal extension). `TestNoColoradoLeakIntoSharedLib` stays green. **Note:** `TestNoStateAdapterImports` guards `drift_guard.py` and the CO *adapter* respectively — it does **not** guard `arcgis.py`/`overlays.py`; do not cite it as the lib-edit guard for E07. |
| Fail-loud over silent fallback | [ADR-001](../../adrs/ADR-001-authority-preserved.md) | S07.1's gate raises (no write) on hash mismatch — never trust-on-first-use, never a silent fallback. |
| Two-gates fetch model precedent (PDF side) | S06.1 `pdf_fetch.fetch_pdf(expected_sha256=...)` + the `*-pending-reextraction.flag` recovery workflow | S07.1 mirrors this shape for geometry fetches. |
| `write_extraction_artifact` is the canonical extraction serializer; single-module-per-state extractors | [ADR-022](../../adrs/ADR-022-single-module-per-state-extractors.md) + the S06.3 convention (`ingestion/ingestion/lib/pdf.write_extraction_artifact`) | S07.3 migrates MT to the helper; it does **not** modularize extractors (ADR-022 holds). |
| Overlay fixture three-band area-ratio discriminator (0.99 relabel / 0.01 drop / precision 6) | [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md) | S07.2 hoists the discriminator **with thresholds left as per-state inputs** (ADR-016 §4 anticipates per-state recalibration); the hoisted primitive takes thresholds as parameters. |
| Three-phase adapter shape (build → guards pre-`db.connect()` → write + single commit); OQ7 row-count guards fire before `db.connect()` | E03 OQ7 + the CO loaders (`load_gmus.py` `_check_count_band`) | S07.1/S07.2 preserve the existing loaders' three-phase shape; no guard moves after `db.connect()`. |
| Confidence framework carve-out — `geometry`/`jurisdiction_binding` carry provenance, not confidence | [ADR-017](../../adrs/ADR-017-confidence-calibration.md) §2 | E07 writes no `confidence` and touches no confidence logic. |
| No schema / three-place-sync / migration changes; no `db.py` write-helper changes | [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md) + the M3 read-only-schema posture | E07 is fetch/extract/lib-structure only. No DDL, no Pydantic, no TS, no `architecture.md` schema edits. (The S05.0-carry-forward `db.upsert_geometry` rowcount guard was retired in the E05 audit-hygiene PR #63 — confirm during S07.1 discovery and do not re-open.) |
| Post-implementation audit standard | E05 precedent (`completed/E05-audit.md`) | The PM closes E07 with the `Audited:` field populated before `/plan-next-epic` is invoked for E08. The serving epics adopt a different (serving) audit shape; E07 mirrors the M1/M2 ingestion-audit pattern. |

---

## Stories

### S07.1: PAD-US geometry pin-enforcement (Q21 option (a) — two-gates fetch model)

**Status:** Not started

**As a** developer preparing the geometry pipeline for a production environment that ingests against live upstream ArcGIS sources
**I want** the geometry fetch path to enforce an operator-controllable expected-hash pin and refuse to write when a live re-fetch diverges from the pinned snapshot, with a documented drift-marker recovery workflow
**So that** dev and prod cannot silently ingest different PAD-US (or CPW) snapshots fetched on different days mid-republish — closing the production-correctness gap Q21 names, with the same fail-loud discipline the PDF loaders already enforce

**UAT: yes** (operator gate-behavior spot-check; Group A static/unit ACs close the story at-merge; Group B operator live-gate spot-check is non-blocking and ticked in a follow-up doc-only commit, mirroring the E05 operator-pending posture)

**Context:**

Q21 resolved 2026-06-24 to **option (a) — pin-enforce at fetch time** (see [`docs/open-questions.md` Q21](../../open-questions.md)). PAD-US 4.1 (the USGS Federal Fee Managers Authoritative FeatureServer — source of the 10 CO V1 federal no-hunt zones) republished **twice in 18 calendar days** during the M2-build operator pass: an OBJECTID/`outFields` drift (fixed in S06.6.1) and a GeometryCollection area-loss drift (fixed in S06.6.2). The lib has the *detection* infrastructure (a committed per-fetch manifest carrying a `layer_hash`) but no *enforcement* policy — the loader does not refuse to write when the live re-fetch hash differs from the committed pin.

**Current state (from discovery; cite by symbol, not line — the repo has a documented line-citation-drift failure mode):**

- `ingestion/ingestion/lib/arcgis.py` — `fetch_features(service_url, layer_id, metadata, fixture_dir, *, layer_slug, timestamp=None, session=None)` paginates, dedups, and writes a fixture + a manifest. The manifest carries a `layer_hash` computed as `sha256` over the sorted per-feature hashes (`compute_feature_hash(...)`). **No function in `arcgis.py` currently accepts an `expected_sha256`/`expected_layer_hash` parameter, and nothing compares a fresh `layer_hash` against a committed baseline.** `_write_manifest_fixture` / `_write_features_fixture` write timestamped fixtures (`{layer_slug}-{layer_id}-manifest-{timestamp}.json`).
- **Two fetch paths must both be gated:** (1) the **public `fetch_features` path** — used by `ingestion/states/colorado/load_gmus.py` (CPW GMUs) and all four MT geometry loaders (`load_hds.py`, `load_portions.py`, `load_cwd_zones.py`, `load_restricted_areas.py`); and (2) the **composed-primitive path** in `ingestion/states/colorado/load_restricted_areas.py` (the actual PAD-US / Q21-trigger loader) — it does **not** call `fetch_features`; it composes `arcgis.fetch_layer_metadata` (public, Step 1) **plus** private primitives (`_request_with_retry`, `_check_and_fix_projection`, `_require_objectid`, `compute_feature_hash`, `_write_manifest_fixture`/`_write_features_fixture`) into a bounded single-page fetch and builds its own manifest `layer_hash`. A gate added only to `fetch_features` would leave the PAD-US loader — the precise drift trigger — unprotected.
- **Gate scope = the feature fetch (the `layer_hash`-bearing step), not `fetch_layer_metadata`.** Only `fetch_features` and the composed feature step compute `layer_hash` + write a manifest; `fetch_layer_metadata` writes a `*-metadata-*.json` fixture with no manifest/`layer_hash`. Metadata drift surfaces downstream as the S06.6.1 OBJECTID / S06.6.2 CRS failure modes, so it is deliberately out of the pin gate's scope — do not over-reach and pin metadata.

**The PDF precedent to mirror (truest analog):**

- `ingestion/ingestion/lib/pdf_fetch.py` — `fetch_pdf(*, citation_id, url, publication_date, document_type, fixture_dir, expected_sha256=None, session=None)`. Gate 1 ("eliminate trust-on-first-use"): when `expected_sha256` is a real 64-char hex pin (not `None`, not the `"unknown"` sentinel), the fetched bytes are hashed and compared **before any PDF or manifest is written, on every fetch including the first**; mismatch raises `PdfFetchError` with both digests and writes nothing. Gate 2 (re-fetch drift): the prior committed manifest's hash is compared to the fresh fetch; on mismatch a `<citation_id>-<publication_date>-pending-reextraction.flag` marker is written and `PdfFetchError` raised. A pre-fetch check refuses to proceed while the marker exists (operator must resolve + delete it).

**Design fork to resolve at Stage-1/Stage-4 (flag-and-discuss; do not guess silently):** where does the geometry pin value come from? Note: Q21's *resolution* commits only to "pin-enforce at fetch time" (mechanism-agnostic); Q21's *estimated-effort note* illustratively prescribes mechanism (B) ("thread the committed manifest's `layer_hash` through the loader call sites"). Choosing (A) is therefore a deliberate mechanism choice over Q21's illustrative note (acceptable — the note is non-binding), to be recorded in the closure note. Two candidates:
- **(A) `sources.yaml` operator-verified pin** (PM recommendation) — add an `expected_sha256`/`expected_layer_hash` field to **both** `gis_layers:` entries that fetch (PAD-US restricted areas + CPW GMUs), each reconciled against its respective committed manifest (truest parity with the PDF `sources.yaml` `expected_sha256` model; operator-controllable; `"unknown"` sentinel skips for un-pinned layers). A re-pin is a tracked PR.
- **(B) committed-manifest `layer_hash`** — the loader reads the pinned committed manifest fixture's `layer_hash` and passes it as the expected value (Q21's illustrative mechanism). Avoids a `sources.yaml` field but requires a deterministic "which committed manifest is the pin" rule given timestamped fixtures.

The story's outcome ACs are written pin-source-agnostic; the implementer + Stage-4 plan review pick (A) or (B) and record the choice in the closure note. PM leans (A) for PDF-precedent parity.

**Relevant ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md) (fail-loud), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) (state-agnostic-clean lib edit). PRD 003 §"E07" exit criteria; success criterion #13 (no loaded-row change).

**Acceptance Criteria:**

**Group A — static / unit (close the story at-merge):**

- [ ] The geometry fetch path accepts an operator-controllable expected-hash pin and **refuses to write any fixture or DB row when the live re-fetch's computed `layer_hash` (or per-feature SHA set) diverges from the pin** — enforced **before any write, on every fetch including the first** (not trust-on-first-use). On mismatch it raises a fail-loud error naming both the expected and observed hashes and the source URL; nothing is written. (Mirrors `fetch_pdf`'s Gate 1.)
- [ ] An absent / `"unknown"`-sentinel pin **skips** enforcement (so un-pinned layers and MT loaders that don't yet pin are unaffected — behavior-preserving), exactly as `fetch_pdf` treats `expected_sha256=None`/`"unknown"`.
- [ ] **Both fetch paths are gated:** the public `fetch_features` path (CPW GMUs + MT geometry loaders) **and** the composed-primitive path in `ingestion/states/colorado/load_restricted_areas.py` (PAD-US). A test proves **each** path refuses to write on a divergent fetch: one on the composed PAD-US path (`load_restricted_areas.py`) and one on the public `fetch_features` path (the GMU/MT blast radius).
- [ ] A drift-marker recovery workflow mirrors the PDF `*-pending-reextraction.flag` pattern, matching its marker semantics: a real-pin mismatch (Gate-1 analog) raises **without** writing a marker (nothing was persisted yet); a re-fetch manifest-`layer_hash` drift (Gate-2 analog) writes the marker and a pre-fetch check refuses to proceed while the marker exists. The closure note documents the operator recovery steps (resolve the source change → re-pin in a tracked PR → delete the marker). Tests cover both the marker-written-and-raises path and the marker-present-blocks-refetch path.
- [ ] The chosen pin source ((A) `sources.yaml` field or (B) committed-manifest `layer_hash`) is implemented and the choice + rationale is recorded in the closure note. If (A): the PAD-US and CPW-GMU `gis_layers:` entries carry the operator-verified pin (the PAD-US pin reconciles with S06.6.2's committed `000955Z` manifest `layer_hash`; the CPW-GMU pin reconciles with the live-verified M2-build operator-pass fetch).
- [ ] **State-agnostic-clean:** the `arcgis.py` change introduces no state identifiers and no host literals; `TestNoColoradoLeakIntoSharedLib` (`ingestion/tests/test_arcgis.py` — the lib-directory leak guard) stays green. (Do not cite `TestNoStateAdapterImports` as the `arcgis.py` guard — it guards `drift_guard.py` and the CO adapter, not the shared lib.)
- [ ] **No loaded-row change, no DB write from the build session, no schema/three-place-sync/`db.py`-write-helper change, no MT-data reclassification.** `git diff --stat supabase/migrations/`, `ingestion/ingestion/lib/db.py`, and `mcp-server/` are empty for this story.
- [ ] New unit tests cover: pin-match → writes; pin-mismatch → raises + writes nothing (both paths); absent/`unknown` pin → skips; marker-written; marker-blocks. Test baseline grows additively (no existing test deleted).
- [ ] A new pitfall lands in `.roughly/known-pitfalls.md` § "Integration — ArcGIS" formalizing the two-gates model for geometry fetches and naming the CRS-shift WARNING as the upstream-republish forensic signal (per Q21's estimated-effort note).
- [ ] Quality gates green: `ruff check`, `mypy ingestion/lib/`, full `pytest` suite, detect-secrets pre-commit.

**Group B — operator live-gate spot-check (non-blocking; ticked in a follow-up doc-only commit, mirroring E05's Group B posture):**

- [ ] An operator runs the PAD-US restricted-areas loader against live PAD-US with the committed pin and confirms it writes (no drift today); then runs it with a deliberately-wrong pin and confirms it refuses to write and emits the drift marker; then confirms the marker blocks a re-fetch until deleted. Captured in the E07 working note (`docs/planning/epics/E07-confidence-findings/S07.1.md` or equivalent; deletes at `m3` tag per the working-artifact retention policy).

---

### S07.2: Overlay-builder shared-lib extraction (E05 Known Issue #7)

**Status:** Not started

**As a** maintainer reducing duplication between the MT and CO overlay-fixture builders
**I want** the two pure, low-divergence overlay primitives hoisted into `ingestion/ingestion/lib/overlays.py` and both states migrated to them, with thresholds/allowlists/orchestration left per-state
**So that** the discriminator + serializer have one home (no divergence risk) while legitimate per-state divergence (ADR-016 per-state threshold recalibration, per-state allowlists, parent/child kinds) stays where it belongs

**UAT: no** (verified against the no-behavior-change invariant: the regenerated overlay fixtures are byte-identical, or the diff is explained and re-pinned format-only)

**Context:**

E05 Known Issue #7 (and the E05 audit's recommended M2 hygiene sweep) scoped this precisely: hoist **only** the two pure low-divergence primitives — the `_build_overlay_pairs` three-band area-ratio discriminator (ADR-016) and the `_write_outputs` two-phase atomic serializer — and migrate both `ingestion/states/montana/build_overlay_fixture.py` and `ingestion/states/colorado/build_overlay_fixture.py`. **Do not force convergence of orchestration / thresholds / allowlists** (ADR-016 §4 explicitly anticipates per-state threshold recalibration; forcing convergence would fight legitimate divergence).

**Current state (from discovery):**

- `ingestion/ingestion/lib/overlays.py` already exports `ROLE_FOR_BINDING_BY_CHILD_KIND` (+ the deprecated `ROLE_FOR_E03_BY_CHILD_KIND` alias), `OverlayFixtureRow`, `DroppedOverlayPair`, and the `OverlayParentKind`/`OverlayChildKind`/`OverlayRelationship`/`GeometryRoleForE03` Literal types. It is the natural home for the hoisted primitives.
- `_build_overlay_pairs(parents, children, child_kind) -> (list[OverlayFixtureRow], list[DroppedOverlayPair])` is **near-identical** in MT and CO — the only differences are variable names (`hd_id`/`hd_geom` vs `gmu_id`/`gmu_geom`) and the parent-kind label (`"hunting_district"` vs `"gmu"`), which appears in **three sites** the hoist must parameterize: the kept-row dict, the dropped-pair dict, and the role lookup. The thresholds (`COVER_RELABEL_THRESHOLD = 0.99`, `COVER_DROP_THRESHOLD = 0.01`, `_OVERLAP_PCT_PRECISION = 6`) are identical today but must become **parameters** of the hoisted function (so a state can recalibrate per ADR-016 §4 without editing lib). MT currently imports the deprecated `ROLE_FOR_E03_BY_CHILD_KIND` alias; CO imports the canonical `ROLE_FOR_BINDING_BY_CHILD_KIND` — they are the **same object**, so behavior is identical; the hoisted primitive references the canonical name directly and the alias is left untouched (MT keeps importing it for fixture-data/self-row compat).
- `_write_outputs(kept, dropped) -> None` is **byte-identical** in MT and CO except the fixture directory paths and a log-message string — clean to hoist with the output paths passed as parameters. **It uses `json.dumps(..., indent=2, ...)` and a coupled two-`.tmp` (fixture + audit) atomic write — it is NOT `write_extraction_artifact` and must NOT be migrated to the one-record-per-line format** (that is S07.3's MT-*extractor* concern; the overlay fixtures have E03/E06 consumers expecting the current bytes). The hoist preserves the existing `indent=2` two-file format exactly.
- Per-state must-stay: orchestration (`main`, the overlay-row collection, `_load_geometries` SQL with the `state=...` filter), the self-row builders (`_build_hd_self_rows` / `_build_gmu_self_rows`), parent/child kinds, **each state's** `_validate_coverage` + restricted-area allowlist (MT's `EXPECTED_RA_ORPHAN_IDS` (3 ids) and CO's `EXPECTED_CO_RA_ORPHAN_IDS` (10 ids)), and fixture-directory constants.
- AST guard `TestNoColoradoLeakIntoSharedLib` (`ingestion/tests/test_arcgis.py`) `rglob`s every `.py` under `ingestion/lib/`, so it auto-covers the newly-hoisted `overlays.py` primitives and must stay green. (`TestNoStateAdapterImports` does **not** guard `overlays.py` — do not cite it here.)

**Relevant ADRs:** [ADR-016](../../adrs/ADR-016-digitization-tolerant-containment.md) (thresholds stay per-state inputs), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) (state-agnostic lib), [ADR-022](../../adrs/ADR-022-single-module-per-state-extractors.md) (single-module convention is for *extractors*; this overlay extraction is the sanctioned Known-Issue-#7 narrow hoist, not a re-litigation of ADR-022).

**Acceptance Criteria:**

- [ ] `ingestion/ingestion/lib/overlays.py` gains the two hoisted primitives: the three-band discriminator (taking the relabel/drop thresholds + precision as **parameters**, defaulting to the ADR-016 values) and the two-phase atomic serializer (taking the output paths as **parameters**). Both are state-agnostic — no state identifiers, no CPW/MT host literals.
- [ ] MT's and CO's `build_overlay_fixture.py` both call the hoisted primitives; the per-state copies of `_build_overlay_pairs` / `_write_outputs` are removed; thresholds/allowlists/orchestration/parent-child-kinds remain per-state.
- [ ] **No behavior change:** regenerating each state's `geometry-overlays.json` + `geometry-overlays-dropped.json` from the migrated builders produces output **byte-identical** to the committed fixtures (this is the expected outcome — the hoist preserves the existing `indent=2` two-file format exactly; it is NOT a format migration). No overlay row's classification (relabel/drop/intersect) changes. If any byte diff appears, stop and treat it as a regression to explain, not a fixture to re-pin.
- [ ] **No loaded-row change** (the overlay fixtures are ingestion inputs, not DB rows; `jurisdiction_binding` is untouched by E07). No `db.py` change, no schema/three-place-sync change, no `mcp-server/` change.
- [ ] `TestNoColoradoLeakIntoSharedLib` (the lib-directory leak guard; auto-covers the new `overlays.py` primitives via `rglob`) stays green; test baseline grows additively (new tests for the hoisted lib primitives; existing per-state builder tests pass unchanged or are retargeted to the lib without losing coverage).
- [ ] Quality gates green (ruff / mypy `ingestion/lib/` + both `states/*/build_overlay_fixture.py` / pytest / detect-secrets).
- [ ] Any new convention surfaced is recorded in `.roughly/known-pitfalls.md`.

---

### S07.3: MT extractor migration to `write_extraction_artifact` (E06 Known Issue #8)

**Status:** Not started

**As a** maintainer keeping committed extraction artifacts under cubic's 50k-line review cap and on one canonical serializer
**I want** the list-shaped MT extraction artifacts migrated from `indent=2` to `ingestion/ingestion/lib/pdf.write_extraction_artifact` (one-record-per-line), with their determinism SHAs re-pinned
**So that** MT's biggest artifact (`dea-2026.json`, ~48k lines at `indent=2` — one bigger brochure from the 50k cap) stops being a review-blocker, and MT + CO use the same serializer

**UAT: no** (format-only; verified by the no-data-change invariant + re-pinned SHAs)

**Context:**

E06 Known Issue #8 (surfaced at S06.3) flagged MT's three extractors as still using `indent=2`/`json.dump` directly while CO uses `write_extraction_artifact`. The pressing target is **`dea-2026.json`** — at ~47,956 lines under `indent=2` it is one larger brochure away from cubic's 50k-line diff cap (the exact problem S06.3 solved for CO by inventing the one-record-per-line serializer).

**Current state (from discovery — confirm each artifact's shape at Stage-1 before migrating):**

- `ingestion/ingestion/lib/pdf.write_extraction_artifact(records: Sequence[object], path: Path) -> None` — atomic (`.tmp` + `Path.replace()`), deterministic (`json.dumps(record, sort_keys=True)` per record), one-record-per-line array. **It is list-only by design** (the S06.3/S06.4 convention; a flat list avoids an envelope wrapper).
- `ingestion/states/montana/extract_dea.py` writes `dea-2026.json` via `json.dumps(sections, indent=2, sort_keys=True, ...)` where `sections` is a **flat list** → clean drop-in migration to `write_extraction_artifact(sections, out)`.
- `ingestion/states/montana/extract_legal_descriptions.py` writes `legal-descriptions-2026.json` via `_write_deterministic_json` — discovery confirms it is a **dict envelope** (`LegalDescriptionsArtifact` TypedDict: `source_id`/`extracted_at`/`matched`/`unmatched`/`unlinked`; the file starts `{`), **not** a flat list. **Excluded** for the same reason as black-bear (list-only serializer cannot serialize an envelope without a data-shape change); it is also small (~3.6k lines), nowhere near the cap.
- `ingestion/states/montana/extract_black_bear.py` writes all **three** of `black-bear-2026.json` / `black-bear-2026-base.json` / `corrections-2026-03-18.json` via an internal `_write_deterministic_json` helper. **⚠️ Constraint:** MT black-bear's merged/base artifact is a **dict envelope** (top-level `sources` / `rows` / `statewide_rules` keys per S03.6/S03.6.1 — the "dict-with-sources shape" the S03.6 pitfall warns against porting; the merged artifact's `rows` is consumed via `merged["rows"]` by the S03.6 loader), and `corrections-2026-03-18.json` is likewise an envelope (`extracted_at`/`source`/`operations`). `write_extraction_artifact` cannot serialize a dict envelope, and restructuring into a flat list would be a **data-shape change that breaks the S03.6 MT regulation-record consumer** — out of E07's behavior-preserving scope. **All three black-bear artifacts are excluded** (small, not near the cap, list-only helper by design).
- **MT extractor tests pin NO determinism SHA** (unlike CO's `test_extract_co_big_game.py`). Discovery confirms `test_extract_dea.py` asserts against the committed artifact via `json.load(...)` + structural/count checks (`_load_artifact`), which is **format-agnostic** — a one-record-per-line migration changes no existing assertion and there is **nothing to re-pin**. (If Stage-1 discovery nonetheless finds a SHA pin, update it and document the old→new lineage per the S06.3/S06.4 discipline.)

**Relevant ADRs:** [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md) (verbatim discipline — serialization format change must not alter any record's content), [ADR-022](../../adrs/ADR-022-single-module-per-state-extractors.md) (no modularization; this is a serializer swap only), [ADR-001](../../adrs/ADR-001-authority-preserved.md).

**Acceptance Criteria:**

- [ ] Stage-1 discovery confirms each MT extractor's artifact shape and records it; the migration set is **exactly `dea-2026.json`** (the only flat-list MT artifact). `legal-descriptions-2026.json` and all three black-bear artifacts are dict envelopes and are excluded.
- [ ] `extract_dea.py` calls `write_extraction_artifact(sections, path)` instead of `json.dumps(sections, indent=2, ...)`; the emitted `dea-2026.json` is the canonical one-record-per-line array.
- [ ] **Data-unchanged:** every record's content is byte-identical pre/post migration modulo whitespace/serialization (same record count, same field values, same ordering after `sort_keys=True`). The migration is format-only; no extraction logic changes. The existing `json.load`-based regression test (`test_extract_dea.py::_load_artifact` + its structural/count assertions) is format-agnostic and must still pass; a regression assertion confirms record count + spot-checked field values are unchanged.
- [ ] **Line-count win confirmed:** the migrated `dea-2026.json` drops from ~47,956 lines (`indent=2`) to the one-record-per-line form (~hundreds of lines, well under cubic's 50k cap).
- [ ] **Dict-envelope artifacts are explicitly excluded and the exclusion is documented by name:** `black-bear-2026.json`, `black-bear-2026-base.json`, `corrections-2026-03-18.json` (the `sources`/`rows`/`statewide_rules` + `operations` envelopes; `merged["rows"]` is consumed by the S03.6 loader), and `legal-descriptions-2026.json` (`LegalDescriptionsArtifact` envelope). Migrating any of them would require a data-shape change breaking the S03.5/S03.6 consumer — out of E07's behavior-preserving scope.
- [ ] **No determinism SHA is re-pinned** (MT pins none — the tests are `json.load`-based and format-agnostic). The closure note states this explicitly. (If discovery finds a SHA pin after all, update it and document the lineage.)
- [ ] **No loaded-row change** (extraction artifacts are ingestion inputs; no DB write). No `db.py`, schema/three-place-sync, or `mcp-server/` change. State-agnostic-clean (the lib helper already exists; only the `extract_dea.py` write-site changes).
- [ ] Test baseline grows additively (no existing test deleted; the `json.load`-based DEA regression test passes unchanged).
- [ ] Quality gates green (ruff / mypy / pytest / detect-secrets). If a migrated artifact remains large, confirm the one-record-per-line line count is well under 50k.

---

### S07.4: Edge-runtime Postgres access principle (ADR-024) — acceptance-readiness gate

**Status:** Not started

**As a** PM closing the ingestion-side milestone prerequisites before the serving stack begins
**I want** the *principle* in ADR-024 (the serving stack reads Postgres from the edge runtime over a read-only-enforced connection, not a long-running Node `pg` pool) confirmed as settled and surfaced to the human, with ADR-024 left `Proposed`
**So that** E08 begins with the edge-runtime-Postgres principle already accepted-in-principle, while the concrete driver choice (Hyperdrive vs. Supabase serverless) is correctly deferred to E08's hands-on spike

**UAT: no** (decision-gate / documentation-readiness; **no code, no ADR edit by the PM**)

**Context:**

This is a **decision-gate story, not implementation** (mirroring the M2 S06.0 decision-gate pattern). ADR-024 already exists as `Proposed` and the posture is human-signed-off in principle per PRD 003 (2026-06-24). E07's PRD exit criterion is: "the ADR-003 amendment establishing the principle is drafted and accepted in principle (ADR-024 records it; it flips to `Accepted` at E08 when the access layer ships)."

What this story does:
- Confirms the **principle** is settled (edge-runtime read; read-only by enforcement — a dedicated SELECT-only Postgres role, not the write-capable service-role key; PostGIS `ST_*` unaffected because it runs server-side).
- Confirms the **driver is deliberately deferred** to E08's spike (Hyperdrive vs. Supabase serverless/HTTP driver) and recorded there as an ADR-024 addendum.
- Surfaces ADR-024 to the human for the principle-acceptance acknowledgment.
- Notes the Q14 interaction (the read connection adopts the current Supabase key format during E08).

What this story does **not** do: write code, provision the SELECT-only role (E08), choose the driver (E08), or edit ADR-024 (the PM does not edit ADRs; ADR-024 flips `Proposed → Accepted` at E08 via the human/ADR-drafting session).

**Relevant ADRs:** [ADR-024](../../adrs/ADR-024-edge-runtime-postgres-access.md) (the principle), [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md) (refined for the edge runtime), [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-023](../../adrs/ADR-023-remote-mcp-server-posture.md) (the deployment that requires this).

**Acceptance Criteria:**

- [ ] A short readiness note (in this epic's working-findings directory, or appended to the epic) records: the principle is settled; the driver is deferred to E08; the read-only-enforcement mechanism (dedicated SELECT-only role) and the Q14 key-format interaction are named.
- [ ] ADR-024 is surfaced to the human for principle-acceptance acknowledgment; the PM confirms ADR-024 remains `Proposed` and documents that it flips to `Accepted` at E08 when the access layer ships. (ADR-024's own status note already records this trigger; there is no separate ADR-status table in `docs/planning/README.md` today — if the readiness note wants a tracked home it lives in this epic's working-findings directory.)
- [ ] **No code, no migration, no role provisioning (the SELECT-only role is provisioned in E08 — it is in M3 scope, just not E07's), no driver selection (E08 spike), no ADR file edit by the PM.** This story produces documentation/decision-tracking only.

---

## Known issues / forward notes to carry into E08+

- **ADR-024 status tracking:** flips `Proposed → Accepted` at E08 (driver chosen + access layer ships). ADR-023 flips `Proposed → Accepted` across E08 (transport/deploy) and E11 (auth seam finalized + deployed). The PM flags the human to make each ADR status edit; the PM does not edit ADRs.
- **Q14 (Supabase key migration):** its serving half advances at E08 (the read-only connection adopts the current key format); the E01 RLS-verification-runbook half stays open. Not E07's to resolve.
- **PAD-US source-stability strategic question** (carried from the S06.6.2 closure; not in E07 scope): two PAD-US republish drifts in 18 days. S07.1's pin-enforcement is the *tactical* fix (detect + refuse-to-write on drift); the *strategic* posture (pin-a-snapshot-and-cache-forever vs. continue patching live-fetch drift vs. re-source) is a human decision at convenience, surfaced for M3-release / future consideration.
- **E07 → E08 gate:** E07 closes with all four stories merged and the `Audited:` field populated (PM post-implementation audit, ingestion pattern). E08 planning runs via `/plan-next-epic` only after E07 is fully closed (unless the human explicitly authorizes early E08 planning per the M2-coordination note — E07 and E08 share no code).
