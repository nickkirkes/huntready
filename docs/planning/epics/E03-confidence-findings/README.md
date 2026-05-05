# E03 Confidence Findings

**Deleted at the `m1` tag commit.** This directory contains per-story working notes for ADR-017 drafting and audit. It is scaffolding — the ADR is the durable record.

See the policy table at [`../E03-regulation-text-ingestion.md`](../E03-regulation-text-ingestion.md) (lines 60–66, "Working artifacts and deferred items").

---

## Retention policy

**Deletion mechanism (per ADR-017 §6):** the final S03.12 commit runs `git rm -r docs/planning/epics/E03-confidence-findings/` as part of the same commit that pushes the `m1` tag. After that commit, `.gitignore` is updated to list `docs/planning/epics/E03-confidence-findings/` so accidental re-creation is caught at commit time.

The ADR is the durable artifact. Working notes are scaffolding; they do not survive M1 close.

---

## Contents

One file per story: `S03.X.md`. Each file records:

- Confidence signals used and their tier assignments.
- Edge cases encountered during extraction.
- Any anomalies that informed the final ADR-017 calibration.

---

## "Flag" operational definition

When a story spec says "flag X for PM review" or "flag-and-defer," the implementer MUST do all four of the following (source: E03 epic lines 34–43):

1. **Structured anomaly artifact:** add an entry under the relevant filename in this directory (`E03-confidence-findings/<story>.md`) for calibration findings, OR under `docs/planning/epics/E03-deferred-items/<topic>.md` for durable deferrals. Calibration vs. deferred is the distinction — see the epic table.
2. **WARN log** at ingestion time with sufficient context (row id, source span, pattern matched).
3. **Open-questions entry** in `docs/open-questions.md`. Mechanical trigger: required whenever the matching `E03-deferred-items/<topic>.md` file accumulates 2+ entries (one entry alone may be a one-off; two becomes a class). When the second entry lands, the implementer adds a one-line pointer at the same time.
4. **Non-silent commit:** the run summary surfaces the flagged count; the story PR description lists the flagged items by category.

A flag is never silently dropped, silently special-cased, or silently committed.
