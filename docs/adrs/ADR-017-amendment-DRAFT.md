# ADR-017 Amendment DRAFT — for user review

**Status:** DRAFT — not committed. Pending user review.
**Source:** S03.11 confidence calibration audit (docs/planning/epics/E03-confidence-calibration-synthesis.md)
**Triggers fired:** ADR-017 §7 Trigger 2 ("any tier has 0 rows in Montana data") — `low` = 0 rows in V1 Montana data
**Author:** PM (drafted 2026-05-26; revised 2026-05-26 after independent architectural review of the initial DRAFT)
**User review SLA:** none (per ADR-017 §7); S03.12 proceeds with amendment-pending status if review is open at m1 tag time
**Changes proposed:** two — (A) a calibration-deferred paragraph in ADR-017 §4 (LOW tier); (B) a one-sentence clarification in ADR-017 §7 Trigger 2 (preempts future auditors relitigating the LITERAL vs INTENT ambiguity)

---

## Change A — Affected section: ADR-017 §4 (LOW tier calibration)

### Current text (excerpt from ADR-017 lines 48-56, "Three-tier framework")

> **`high`:** extracted from a structured table cell, regex-validated against expected pattern, no manual interpretation. Signals: source format is structured (table); extraction is deterministic (regex/parser); transformation is one-step (cell → field).
> **`medium`:** extracted from prose with a deterministic heading anchor; structure is consistent across rows but not table-grid-precise. Signals: source format is prose with structural cues (heading + repeated pattern); extraction requires interpretation (e.g., date-range parsing from prose); transformation is up to two steps (prose → parsed field, OR table cell + correction merge).
> **`low`:** extracted via heuristic; requires manual review or LLM-assisted interpretation. Signals: source format is unstructured prose OR fuzzy match (heading-to-id matching with multiple plausible candidates); extraction requires multi-step inference; OR the row was hand-corrected post-extraction.

### Proposed addition (NEW paragraph appended to §4, after the existing tier table)

> **LOW tier calibration — deferred to M2 (per S03.11 audit).** V1 Montana data has 0 rows assigned `low` (`high`=32, `medium`=405, `low`=0 across 437 regulation_record rows; see `docs/planning/epics/E03-confidence-calibration-synthesis.md` §3.1). The LOW input conditions (empty `license_code` / empty `opportunity` / all-False `season_coverage`) are not triggered by V1 Montana DEA or Black Bear booklet rows. The rule definition is preserved as-written; its real-world calibration is deferred to M2's Colorado dataset, which is expected to exercise broader input variance. This deferral does not require a `schema_version` bump — it is a calibration annotation on an unchanged rule, not a rule change (per ADR-017 line 93). If M2's Colorado data exercises the LOW rule, this deferral closes without further amendment. If M2's Colorado data also produces 0 LOW rows, PM will draft a second amendment at M2 close either revising the LOW conditions or removing the tier; the decision will be made from CO source data inspection, not deferred further.

### Reasoning

ADR-017 §7's deferral test reads "any tier has 0 rows in Montana data" without qualification. The LITERAL reading triggers partial deferral; the partial-defer mechanism (§7 line 80: "wholly or partially") is the exact tool for this case. The amendment is light-touch — no operational change to V1 framework, no schema migration, no re-ingestion. The framework HIGH and MEDIUM tiers remain calibrated and audit-passing. The only thing being deferred is the *confidence claim* that the LOW tier's rule is calibrated for production use; that confidence is restored when M2 data exercises it.

---

## Change B — Affected section: ADR-017 §7 (Trigger 2 disambiguation)

The initial DRAFT held §7 out of scope. Independent architectural review (2026-05-26) recommended adding a one-sentence disambiguation to §7 Trigger 2 so a future auditor (M2 Colorado) does not have to relitigate the LITERAL vs INTENT ambiguity that S03.11 had to adjudicate. Promoting this from "out of scope" to "second proposed change" — both Change A and Change B land or reject together as one user decision.

### Current text (ADR-017 §7 line 77)

> Any tier has 0 rows in Montana data, **OR**

### Proposed addition (one sentence appended to the Trigger 2 list-item, inline or as a parenthetical)

> Any tier has 0 rows in Montana data, **OR** *(a tier's absence due to data-property inputs — rather than a missing or broken rule — still fires this trigger; the partial-defer mechanism handles calibration gaps separately from rule correctness),*

### Why also amend §7

§7's text is unqualified ("any tier has 0 rows in Montana data"). S03.11's audit surfaced an ambiguity: should the trigger fire when a tier is empty *by design* (the rule exists and is sound, but the rule's inputs aren't present in real data) versus empty *by framework gap* (the rule is broken or missing)? PM resolved this via the LITERAL reading and the partial-defer mechanism. Codifying the resolution in §7 itself spares M2's auditor the same adjudication.

This disambiguation is independent of Change A: even if the user prefers the INTENT reading and rejects Change A, Change B still has value for future audits because it documents what "0 rows" means operationally. However, in practice the two changes are coupled — if Change A lands (LITERAL reading wins), Change B documents the reasoning; if Change A is rejected (INTENT reading wins), Change B should be revised to express the INTENT interpretation instead. The user reviews both together.

---

## Sections explicitly NOT amended

ADR-017 §1 (inherited confidence), §2 (spatial entities), §3 (per-VerbatimRule confidence), §4 HIGH and MEDIUM tier definitions, §5 (MIN-aggregation), §6 (working-note deletion at m1), §7's Trigger 1 + Trigger 3, and the Alternatives + Consequences sections all stand unchanged.

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
2. To LAND the amendment, do all 4 steps in one commit:
   1. Copy Change A's "Proposed addition" prose into the active ADR-017 §4 (append after the existing tier table).
   2. Apply Change B's amended Trigger 2 line to the active ADR-017 §7 (replace the bare Trigger 2 line with the disambiguated version).
   3. Update Q11 in `docs/open-questions.md`: change the status line from `OPEN — amendment-pending user review` to `OPEN — amendment landed (YYYY-MM-DD); LOW calibration deferred to M2 / Colorado` (Q11 stays OPEN because resolution is gated on M2's data, per Effect-if-lands above).
   4. Delete this DRAFT file (`docs/adrs/ADR-017-amendment-DRAFT.md`).
3. To REJECT both changes (preferring the INTENT reading of §7 Trigger 2): flip the synthesis report §6 verdict to FINALIZE, mark Q11 resolved in `docs/open-questions.md`, and delete this DRAFT file.
4. To LAND ONLY Change B (revise Change A or skip it but still preempt M2 ambiguity): possible but not the default — discuss before applying.
5. There is no user-side SLA. The m1 tag can ship with the amendment pending.
