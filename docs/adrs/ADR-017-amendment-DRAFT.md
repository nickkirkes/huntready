# ADR-017 Amendment DRAFT — for user review

**Status:** DRAFT — not committed. Pending user review.
**Source:** S03.11 confidence calibration audit (docs/planning/epics/E03-confidence-calibration-synthesis.md)
**Triggers fired:** ADR-017 §7 Trigger 2 ("any tier has 0 rows in Montana data") — `low` = 0 rows in V1 Montana data
**Author:** PM (drafted 2026-05-26)
**User review SLA:** none (per ADR-017 §7); S03.12 proceeds with amendment-pending status if review is open at m1 tag time

---

## Affected section: ADR-017 §4 (LOW tier calibration)

### Current text (excerpt from ADR-017 lines 48-56, "Three-tier framework")

> **`high`:** extracted from a structured table cell, regex-validated against expected pattern, no manual interpretation. Signals: source format is structured (table); extraction is deterministic (regex/parser); transformation is one-step (cell → field).
> **`medium`:** extracted from prose with a deterministic heading anchor; structure is consistent across rows but not table-grid-precise. Signals: source format is prose with structural cues (heading + repeated pattern); extraction requires interpretation (e.g., date-range parsing from prose); transformation is up to two steps (prose → parsed field, OR table cell + correction merge).
> **`low`:** extracted via heuristic; requires manual review or LLM-assisted interpretation. Signals: source format is unstructured prose OR fuzzy match (heading-to-id matching with multiple plausible candidates); extraction requires multi-step inference; OR the row was hand-corrected post-extraction.

### Proposed addition (NEW paragraph appended to §4, after the existing tier table)

> **LOW tier calibration — deferred to M2 (per S03.11 audit).** V1 Montana data has 0 rows assigned `low` (`high`=32, `medium`=405, `low`=0 across 437 regulation_record rows; see `docs/planning/epics/E03-confidence-calibration-synthesis.md` §3.1). The LOW input conditions (empty `license_code` / empty `opportunity` / all-False `season_coverage`) are not triggered by V1 Montana DEA or Black Bear booklet rows. The rule definition is preserved as-written; its real-world calibration is deferred to M2's Colorado dataset, which is expected to exercise broader input variance. If M2 confirms the LOW rule fires on real data, this deferral is closed without further amendment. If M2's data also produces 0 LOW rows, an additional amendment will re-evaluate whether the LOW rule needs revision (e.g., a different absence-marker, or removal of the LOW tier if it's structurally unreachable in real-world hunting regulations).

### Reasoning

ADR-017 §7's deferral test reads "any tier has 0 rows in Montana data" without qualification. The LITERAL reading triggers partial deferral; the partial-defer mechanism (§7 line 80: "wholly or partially") is the exact tool for this case. The amendment is light-touch — no operational change to V1 framework, no schema migration, no re-ingestion. The framework HIGH and MEDIUM tiers remain calibrated and audit-passing. The only thing being deferred is the *confidence claim* that the LOW tier's rule is calibrated for production use; that confidence is restored when M2 data exercises it.

---

## Sections explicitly NOT amended

### ADR-017 §7 (deferral trigger interpretation)

The LITERAL reading of §7 Trigger 2 is being recommended by PM. §7's text is NOT amended in this draft. If the user prefers the INTENT reading at review time, the user can flip the verdict to FINALIZE — in which case the entire DRAFT is discarded, no amendment lands, and Q11 is marked resolved. Alternatively, if the user wants the LITERAL reading kept but the §7 text disambiguated for future readers, that disambiguation can be a separate amendment (out of scope for S03.11).

---

## Effect if amendment lands

- **V1 framework operationally unchanged.** No code touches. No re-ingestion. No schema migration.
- **ADR-017 §4 acquires a calibration-deferred paragraph for the LOW tier.** Active ADR file size grows ~10 lines. The HIGH and MEDIUM tier definitions are untouched.
- **Q11 status remains OPEN with amendment-pending → M2 verification.** Resolution is gated on M2's Colorado data exercising (or not) the LOW rule.
- **Working notes deletion (per ADR-017 §6) at m1 tag commit still proceeds.** The amended ADR is the durable record; the working notes are scaffolding.
- **M1→M2 handoff document (S03.12) records the amendment-pending status.** The user reviews on their own timeline; per ADR-017 §7 the m1 tag does NOT block on review.

---

## Reminders for the user reviewing this DRAFT

1. This file is a DRAFT. PM has NOT modified `docs/adrs/ADR-017-confidence-calibration.md`.
2. To LAND the amendment: copy the "Proposed addition" prose into the active ADR-017 §4, commit, and delete this DRAFT file.
3. To REJECT the amendment (preferring the INTENT reading of §7 Trigger 2): flip the synthesis report §6 verdict to FINALIZE, mark Q11 resolved in `docs/open-questions.md`, and delete this DRAFT file.
4. There is no user-side SLA. The m1 tag can ship with the amendment pending.
