# E03 Deferred Items

**Survives past M1 close.** This directory contains durable promises to M2: things E03 surfaced that V1 explicitly defers. Each file is input to the M2 PM handoff.

See the policy table at [`../E03-regulation-text-ingestion.md`](../E03-regulation-text-ingestion.md) (lines 60–66, "Working artifacts and deferred items").

---

## Retention policy

Files in this directory are carried forward past M1 close into the M2 PM handoff. They are NOT deleted at the `m1` tag commit (contrast with `E03-confidence-findings/`, which is).

Each file represents a class of items that E03 surfaced but V1 explicitly defers. The file is the durable record of what was deferred and why — M2 starts from it.

---

## Contents

| File | Tracks |
|------|--------|
| [`draw-mechanics.md`](draw-mechanics.md) | Q12 / `parameters` escape-hatch deferrals surfaced during E03 |
| [`closure-temporal-anchors.md`](closure-temporal-anchors.md) | Spring Season Closure "at any point after May 31"-style temporal anchors needing a structured field (M2 ADR candidate) |
| [`cwd-sampling-modeling.md`](cwd-sampling-modeling.md) | Q18 / whether `reporting_obligation` models per-zone CWD sampling rules in V1; deferred to M2 with Colorado |

Additional files may be added if E03 surfaces other deferral classes.

---

## "Flag" operational definition

When a story spec says "flag X for PM review" or "flag-and-defer," the implementer MUST do all four of the following (source: E03 epic lines 34–43):

1. **Structured anomaly artifact:** add an entry in the relevant file in this directory (`E03-deferred-items/<topic>.md`) for durable deferrals, OR under `docs/planning/epics/E03-confidence-findings/<story>.md` for calibration working notes. Deferred vs. calibration is the distinction — see the epic table.
2. **WARN log** at ingestion time with sufficient context (row id, source span, pattern matched).
3. **Open-questions entry** in `docs/open-questions.md`. Mechanical trigger: required whenever any file in this directory accumulates 2+ entries (one entry alone may be a one-off; two becomes a class). When the second entry lands in a file, the implementer adds a one-line `open-questions.md` pointer at the same time. PM (with user) consolidates and authors the actual question after review.
4. **Non-silent commit:** the run summary surfaces the flagged count; the story PR description lists the flagged items by category.

A flag is never silently dropped, silently special-cased, or silently committed.
